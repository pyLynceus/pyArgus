"""Assemble an offline Windows installer payload; no client datasets are copied."""
from pathlib import Path
import argparse
import hashlib
import html
import importlib.metadata as metadata
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
GIT = shutil.which("git") or str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dump(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def copy_tree(src, dst):
    shutil.copytree(src, dst, dirs_exist_ok=True)


def render_guide(text, title, home="index.html"):
    """Readable local HTML without an extra build dependency."""
    body = []
    for para in re.split(r"\n\s*\n", text):
        lines = para.splitlines()
        if not lines:
            continue
        if len(lines) == 1 and re.match(r"^#{1,6} ", lines[0]):
            level = min(len(lines[0].split(" ")[0]), 3)
            body.append(f"<h{level}>{html.escape(lines[0].lstrip('# '))}</h{level}>")
        else:
            body.append("<p>" + "<br>".join(html.escape(line) for line in lines) + "</p>")
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>' + html.escape(title) + '</title><style>body{max-width:960px;margin:40px auto;padding:0 24px;color:#24313d;background:#fafcfb;font:16px/1.65 Segoe UI,sans-serif}h1,h2,h3{line-height:1.3}a{color:#146b9d}p{overflow-wrap:anywhere}</style><a href="' + home + '">Documentation home</a>' + "\n".join(body) + "</html>"


def source_bundle(stage):
    names = subprocess.check_output(
        [GIT, "-c", f"safe.directory={ROOT.as_posix()}", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT).decode().split("\0")
    allowed = ("pyargus/", "tests/", "packaging/", "docs/", "devtools/", "reference/")
    top = {"LICENSE", "README.md", "pyproject.toml", "requirements-validation-win-py311.txt",
           "HANDOFF.md", "CLAUDE.md"}
    files = sorted({n for n in names if n and (n.startswith(allowed) or n in top)})
    files += [p.relative_to(ROOT).as_posix() for p in (ROOT / "packaging/windows").glob("*.py")
              if p.relative_to(ROOT).as_posix() not in files]
    files += [p.relative_to(ROOT).as_posix() for p in (ROOT / "docs").glob("WINDOWS_INSTALLER.md")
              if p.relative_to(ROOT).as_posix() not in files]
    with zipfile.ZipFile(stage / "Sources/pyArgus-source.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(set(files)):
            p = ROOT / name
            if p.is_file():
                z.write(p, "pyArgus/" + name)


def collect_native(stage, prefix):
    target = stage / "native-pdal"
    for part in ("Library/bin", "Library/share", "Library/ssl", "Library/libexec", "etc"):
        if (prefix / part).exists():
            copy_tree(prefix / part, target / part)
    for p in prefix.glob("*.dll"):
        shutil.copy2(p, target / p.name)
    native = []
    records = sorted((prefix / "conda-meta").glob("*.json"))
    for record in records:
        info = json.loads(record.read_text())
        cache = Path(info["link"]["source"]) / "info"
        key = info["name"] + "-" + info["version"]
        notices = stage / "Licenses/native" / key
        if (cache / "licenses").is_dir():
            copy_tree(cache / "licenses", notices)
        recipe = cache / "recipe"
        if recipe.is_dir():
            copy_tree(recipe, stage / "Sources/native-recipes" / key)
        public_record = {k: info.get(k) for k in ("name", "version", "build", "license", "url", "sha256", "md5", "depends", "files")}
        public_record["license_files"] = [p.relative_to(notices).as_posix() for p in notices.rglob("*") if p.is_file()] if notices.exists() else []
        dump(stage / "Sources/native-package-records" / record.name, public_record)
        native.append(public_record)
        # Supply upstream sources plus the exact recipes/patches for copyleft packages.
        if "GPL" not in info.get("license", "") and "MPL" not in info.get("license", "") and info["name"] not in ("libarchive", "libgdal-core"):
            continue
        recipe_file = next((f for f in (recipe / "meta.yaml", recipe / "recipe.yaml") if f.exists()), None)
        if recipe_file is None:
            raise RuntimeError("Missing native source recipe: " + key)
        text = recipe_file.read_text(encoding="utf-8")
        match = re.search(r"\nsource:\s*\n\s+url: ([^\n]+)\n\s+sha256: ([0-9a-f]{64})", text)
        if not match:
            raise RuntimeError("Cannot read native source URL: " + key)
        url = match[1].strip().replace("${{ version }}", info["version"])
        url = re.sub(r"^http:", "https:", url)
        filename = url.rsplit("/", 1)[-1]
        out = stage / "Sources/native-upstream" / key / filename
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            print("Downloading native source:", key, flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "pyArgus-installer-builder"})
            with urllib.request.urlopen(request, timeout=90) as response, out.open("wb") as f:
                shutil.copyfileobj(response, f)
        if digest(out) != match[2]:
            raise RuntimeError("Native source checksum mismatch: " + key)
        public_record["upstream_source"] = {"url": url, "sha256": match[2], "included": out.relative_to(stage).as_posix()}
    dump(stage / "Sources/native-packages.json", native)
    return native


def collect_python_licenses(stage):
    packages = []
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name:
            continue
        selected = []
        for f in dist.files or []:
            # Include dependency notices, including bundled OpenBLAS and other subprojects.
            if any(s in f.name.lower() for s in ("license", "copying", "notice")):
                src = Path(dist.locate_file(f)).resolve()
                if not src.is_file():
                    continue
                rel = Path(*[p for p in f.parts if p not in (".", "..")])
                dst = stage / "Licenses/python" / (name + "-" + dist.version) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                selected.append(dst.relative_to(stage).as_posix())
        packages.append({"name": name, "version": dist.version, "notices": selected})
    # CPython and Tk have runtime licenses outside Python distribution metadata.
    runtime = stage / "Licenses/runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    for parent in (Path(sys.base_prefix), Path(sys.base_prefix) / "tcl"):
        if not parent.is_dir():
            continue
        for p in parent.rglob("*"):
            if p.is_file() and p.name.lower() in ("license.txt", "license.terms"):
                dst = runtime / p.relative_to(Path(sys.base_prefix))
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dst)
    dump(stage / "Licenses/python-packages.json", packages)
    return packages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release",default="2026-10-08",help="Release date recorded in the payload")
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--native-prefix", type=Path, required=True)
    parser.add_argument("--tutorial-zip", type=Path, required=True)
    parser.add_argument("--example-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    stage = args.output_dir.resolve()
    stage.mkdir(parents=True, exist_ok=True)
    copy_tree(args.app_dir, stage)
    for sub in ("Sources", "Documentation", "Licenses", "Examples", "Training"):
        (stage / sub).mkdir(exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", stage / "LICENSE.txt")
    with zipfile.ZipFile(args.tutorial_zip) as z:
        for member in z.infolist():
            target = (stage / "Training" / member.filename).resolve()
            if not target.is_relative_to(stage / "Training"):
                raise ValueError("Unsafe training archive path")
        z.extractall(stage / "Training")
    docs = []
    for p in sorted((ROOT / "docs").rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT / "docs")
        out = stage / "Documentation" / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        if p.suffix == ".md":
            web = out.with_suffix(".html")
            web.write_text(render_guide(p.read_text(encoding="utf-8"), p.stem.replace("_", " "), "../" * len(rel.parent.parts) + "index.html"), encoding="utf-8")
            docs.append((p.stem.replace("_", " "), web.relative_to(stage / "Documentation").as_posix()))
        elif p.suffix in (".pdf", ".docx"):
            docs.append((p.name, out.relative_to(stage / "Documentation").as_posix()))
    links = "".join(f'<li><a href="{html.escape(path)}">{html.escape(label)}</a></li>' for label, path in docs)
    (stage / "Documentation/index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>pyArgus documentation</title>'
        '<style>body{max-width:1000px;margin:40px auto;padding:0 24px;font:17px/1.6 Segoe UI,sans-serif}a{color:#146b9d}</style>'
        '<h1>pyArgus documentation</h1><p><a href="../Getting-started.html">Getting started</a> | <a href="../Training/Watch-pyArgus.html">Watch the step-by-step video</a></p>'
        '<p>These guides describe the implemented features and their verification limits. Production accuracy remains a project-specific review.</p><ul>' + links + '</ul></html>', encoding="utf-8")
    examples = [p for p in args.example_dir.iterdir() if p.is_file() and p.name.startswith("TRAINING_") and p.suffix.lower() in (".las", ".trj", ".dxf")]
    if len([p for p in examples if p.suffix == ".las"]) != 2:
        raise RuntimeError("Expected two synthetic practice clouds")
    for p in examples:
        shutil.copy2(p, stage / "Examples" / p.name)
    (stage / "Examples/README.txt").write_text(
        "SYNTHETIC PRACTICE DATA - no client survey data.\n\n"
        "Copy this Examples folder to Documents or another working folder first.\n"
        "Start pyArgus, use File > Add files, and select the two TRAINING_*.las clouds.\n"
        "Add both TRAINING_*.trj trajectories; set their time base to same stored LAS timestamps.\n"
        "Import the TRAINING_*.dxf as reference linework. EPSG:6447, US survey feet.\n"
        "Select an output folder outside the installation folder and save a new workspace there.\n"
        "The video uses this generated dataset. Heights are illustrative, not surveyed.\n"
        "No pre-saved workspace with another computer's absolute paths is included.\n", encoding="utf-8")
    native = collect_native(stage, args.native_prefix.resolve())
    packages = collect_python_licenses(stage)
    source_bundle(stage)
    (stage / "Sources/README.txt").write_text(
        "pyArgus-source.zip contains the application, tests, packaging, guides and pinned Python requirements.\n"
        "Repository: https://github.com/pyLynceus/pyArgus\n"
        "native-package-records and native-packages.json identify conda-forge package builds and archive hashes.\n"
        "native-recipes contains the corresponding build recipes and patches for every native package.\n"
        "native-upstream contains checksum-verified upstream archives for GPL/LGPL/MPL dependencies,\n"
        "plus GDAL and libarchive. Dependencies retain their respective licenses; see Licenses.\n"
        "Native libraries remain separate dynamically loaded files and can be replaced by compatible builds.\n"
        "The runtime omits development headers/static libraries, not runtime binaries or CRS data.\n", encoding="utf-8")
    (stage / "Launch pyArgus.cmd").write_text('@echo off\nsetlocal\nstart "" /D "%~dp0" "%~dp0pyArgus.exe"\n', encoding="ascii")
    (stage / "README.txt").write_text(
        f"pyArgus 0.1.0 - Windows x64 - {args.release}\n\n"
        "Start pyArgus.exe or the Start menu shortcut. Python, QGIS and Conda are not needed.\n"
        "Open Getting-started.html, or Training/Watch-pyArgus.html for the narrated walkthrough.\n"
        "Keep _internal and native-pdal with the executable when moving a portable copy.\n"
        "Store project files and outputs outside this application folder.\n"
        "Uninstall removes installed application files, not project data stored elsewhere.\n"
        "This is an unsigned development release. No production accuracy acceptance is implied.\n",
        encoding="utf-8")
    (stage / "Getting-started.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Start with pyArgus</title>'
        '<style>body{max-width:940px;margin:40px auto;padding:0 24px;font:18px/1.65 Segoe UI,sans-serif;color:#25333d}a{color:#146b9d}</style>'
        '<h1>Start with pyArgus</h1><p>Open pyArgus from the Start menu. This installation includes the Python and native PDAL runtimes.</p>'
        '<p><a href="Training/Watch-pyArgus.html">Watch the 13-minute step-by-step video</a> &middot; <a href="Documentation/index.html">Read the user and technical guides</a></p>'
        '<ol><li>Create a working project folder outside this installation. Use File to add LAS/LAZ files and optional TRJ/SBET trajectories.</li>'
        '<li>Set trajectory clocks and verify the coordinate system, units and datum. Save the workspace in your project folder.</li>'
        '<li>Use Process for Inspect/match. Review the inventory and matching results before continuing.</li>'
        '<li>Use Review to navigate in 3D, import DXF reference linework, extract profiles and save views or issue notes.</li>'
        '<li>Run initial QA. An unclassified cloud has no ground overlap results; classify and rerun QA before judging alignment.</li>'
        '<li>Classify to new output files. Compare original and result clouds, inspect ground sections, and review any noise removal.</li>'
        '<li>Align only after the relevant inputs and conventions are verified. Review independent checks and post-adjustment QA.</li>'
        '<li>Use Deliver to export the review package and retain the workspace, reports and output provenance.</li></ol>'
        '<h2>Acceleration</h2><p>View &gt; Renderer &gt; Auto uses a supported graphics device; the status bar names the active renderer. Process &gt; Classify offers Tiled / multicore with CPU workers and a tile memory budget. Read <a href="Documentation/ACCELERATION.html">the acceleration guide</a> for controls and measurements.</p>'
        '<h2>Practice without client data</h2><p>Copy the <a href="Examples/">Examples folder</a> to your working folder. It contains two synthetic LAS clouds, trajectories, and DXF reference linework. Read Examples/README.txt and follow the video.</p>'
        '<h2>Installation and project files</h2><p>The installer defaults to your own Programs folder and needs no administrator rights. It does not change the system PATH. Keep outputs outside the application folder. Windows Settings &gt; Apps can uninstall this copy while those project files stay in place.</p>'
        '<p>Source code, native package recipes and notices are included under Sources and Licenses. This is an unsigned development build.</p></html>',
        encoding="utf-8")
    revision = subprocess.check_output([GIT, "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    dirty = subprocess.check_output([GIT, "-c", f"safe.directory={ROOT.as_posix()}", "status", "--porcelain"], cwd=ROOT).decode().strip()
    fingerprint = hashlib.sha256()
    for p in sorted(list((ROOT / "pyargus").rglob("*.py")) + list((ROOT / "packaging").rglob("*.py")) + list((ROOT / "packaging").rglob("*.spec"))):
        fingerprint.update(p.relative_to(ROOT).as_posix().encode() + b"\0" + p.read_bytes())
    build = {"schema_version": 1, "release": args.release, "version": "0.1.0",
             "source_commit": revision, "source_clean_at_build": not bool(dirty),
             "source_note": ("Working-tree changes are included; " if dirty else "Committed source; ")+"exact source is in Sources/pyArgus-source.zip.",
             "source_fingerprint": fingerprint.hexdigest(), "built_utc": datetime.now(timezone.utc).isoformat(),
             "python": sys.version, "pyinstaller": metadata.version("pyinstaller"),
             "exe_sha256": digest(stage / "pyArgus.exe"), "video_sha256": digest(stage / "Training/pyArgus-Step-by-Step.mp4"),
             "native_package_count": len(native), "packages": packages}
    dump(stage / "build-info.json", build)
    files = [{"path": p.relative_to(stage).as_posix(), "bytes": p.stat().st_size, "sha256": digest(p)}
             for p in sorted(stage.rglob("*")) if p.is_file() and p.name != "payload-manifest.json"]
    dump(stage / "payload-manifest.json", {"release": args.release, "files": files})
    print(json.dumps({"stage": str(stage), "files": len(files), "bytes": sum(f["bytes"] for f in files),
                      "exe_sha256": build["exe_sha256"]}), flush=True)


if __name__ == "__main__":
    main()
