"""The desktop application: five stages over the library, one window.

The structure is pyLynceus's gui.py transplanted, deliberately: a
guarded tkinter import so the module stays importable headless; stage
classes whose ``prepare()`` validates on the UI thread and returns a
``work(runner)`` closure that touches no widget; a StageRunner whose
queue is the only bridge back; completion tracked by an explicit flag
because reading a widget's state back compares a Tcl_Obj whose
truthiness is a mood; and a launcher trio for the sibling tool.
Anything that produces pixels stays a pure array function; only
``preview_photo`` touches Tk.

Every stage calls the same library functions the CLI does -- the GUI
is a shell, never a second implementation.
"""

import os
import queue
import sys
import threading
import traceback
from pathlib import Path

import numpy as np

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    TK_AVAILABLE = True
except Exception:  # pragma: no cover
    TK_AVAILABLE = False

PREVIEW_MS = 700

# The mark: Argus Panoptes's hundred eyes ended up on the peacock's
# tail, so the palette is pine ink, peacock teal, and a gold eye-spot
# on cool paper.
PALETTE = {
    "ground": "#F2F4F0",
    "panel": "#E2E7DE",
    "field": "#FBFCFA",
    "ink": "#16281E",
    "muted": "#6E7C74",
    "gold": "#D9A441",
    "teal": "#2E7D6E",
}

ASSETS = Path(__file__).resolve().parent / "assets"


def apply_theme(root):
    palette = PALETTE
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=palette["ground"])
    style.configure(
        ".", background=palette["ground"], foreground=palette["ink"],
        fieldbackground=palette["field"], troughcolor=palette["panel"],
        bordercolor=palette["panel"], lightcolor=palette["ground"],
        darkcolor=palette["ground"], focuscolor=palette["gold"])
    style.configure("TEntry", foreground=palette["ink"],
                    insertcolor=palette["ink"])
    style.configure("TButton", background=palette["panel"],
                    foreground=palette["ink"], padding=4)
    style.map("TButton",
              background=[("active", palette["gold"])],
              foreground=[("active", palette["ink"])])
    style.configure("TNotebook", background=palette["ground"],
                    borderwidth=0)
    style.configure("TNotebook.Tab", background=palette["panel"],
                    foreground=palette["muted"], padding=(10, 4))
    style.map("TNotebook.Tab",
              background=[("selected", palette["ground"])],
              foreground=[("selected", palette["ink"])])
    style.configure("Horizontal.TProgressbar",
                    background=palette["gold"],
                    troughcolor=palette["panel"],
                    bordercolor=palette["panel"],
                    lightcolor=palette["gold"],
                    darkcolor=palette["gold"])
    return style


def apply_branding(root):
    """The window icon, from the committed assets. Branding must never
    stop the tool -- a missing or unreadable asset leaves the default
    icon and nothing else."""
    try:
        icon = ASSETS / "pyArgus.ico"
        if os.name == "nt" and icon.is_file():
            root.iconbitmap(default=str(icon))
        png = ASSETS / "pyargus-icon-256.png"
        if png.is_file():
            from PIL import Image, ImageTk

            image = ImageTk.PhotoImage(Image.open(png))
            root.iconphoto(True, image)
            root._pyargus_icon = image   # Tk keeps no reference
    except Exception:
        pass


def path_row(parent, label, variable, row, directory=False, save=False):
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
    ttk.Entry(parent, textvariable=variable, width=32).grid(
        row=row, column=1, sticky="we", padx=2)

    def browse():
        initial = os.environ.get("PYARGUS_DATA_DIR") or None
        if directory:
            chosen = filedialog.askdirectory(initialdir=initial)
        elif save:
            chosen = filedialog.asksaveasfilename(initialdir=initial)
        else:
            chosen = filedialog.askopenfilename(initialdir=initial)
        if chosen:
            variable.set(chosen)

    ttk.Button(parent, text="…", width=2, command=browse).grid(
        row=row, column=2)


def preview_image(rgba, size=760):
    """Fit an (H, W, 4) preview array into a square, pure numpy.

    The array half of the preview seam: everything up to the
    PhotoImage is testable without a display."""
    rgba = np.asarray(rgba)
    height, width = rgba.shape[:2]
    step = max(1, int(np.ceil(max(height, width) / size)))
    return rgba[::step, ::step]


def preview_photo(rgba):  # pragma: no cover - the Tk half of the seam
    import base64

    from pyargus.qa import raster

    data = base64.b64encode(raster.encode_png(np.ascontiguousarray(rgba)))
    return tk.PhotoImage(data=data)


# --- the sibling: pyLynceus ---------------------------------------------

PYLYNCEUS_STARTUP_MS = 2500   # how long before declaring a launch dead


def find_pylynceus():
    """The pyLynceus checkout: ``PYLYNCEUS_HOME`` when set, else a
    ``pyLynceus`` directory beside an ancestor of this code, validated
    by the presence of ``pylynceus/gui.py``. The walk anchors on the
    executable when frozen -- a bundle's ``__file__`` lives inside the
    bundle, where no sibling checkout can be."""
    candidates = []
    if os.environ.get("PYLYNCEUS_HOME"):
        candidates.append(Path(os.environ["PYLYNCEUS_HOME"]))
    anchor = (Path(sys.executable) if getattr(sys, "frozen", False)
              else Path(__file__))
    for parent in anchor.resolve().parents[:6]:
        candidates.append(parent / "pyLynceus")
    for home in candidates:
        if (home / "pylynceus" / "gui.py").is_file():
            return home
    return None


def pylynceus_command(home):
    """The command that launches pyLynceus in its own environment --
    this interpreter is not it; the tools stay separate and talk
    through files."""
    python = (home / ".venv" / "Scripts" / "python.exe" if os.name == "nt"
              else home / ".venv" / "bin" / "python")
    if not python.is_file():
        raise ValueError(
            f"pyLynceus has no environment at {python.parent.parent}; "
            f"in {home} run 'uv venv --python 3.11 .venv' then "
            f"'UV_LINK_MODE=copy uv pip install -e \".[dev]\"' "
            f"(copy mode: OneDrive refuses hardlinks)")
    return [str(python), "-m", "pylynceus", "gui"]


class StageRunner:
    def __init__(self):
        self.lines = queue.Queue()
        self.report = None       # a preview rgba array when a stage made one
        self.progress = (0, 1)
        self.thread = None
        self.error = None
        # (kind, Path) pairs a finished stage leaves for the window to
        # offer downstream -- appended by the worker, read only after
        # the thread has finished.
        self.products = []
        self._cancel = threading.Event()

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def cancel(self):
        self._cancel.set()

    def cancelled(self):
        return self._cancel.is_set()

    def log(self, text):
        self.lines.put(str(text))

    def start(self, work):
        self._cancel.clear()
        self.error = None
        self.report = None
        self.progress = (0, 1)
        self.products = []

        def body():
            try:
                work(self)
            except Exception as exc:   # surfaced in the log
                self.error = exc
                self.log(f"FAILED: {exc}")
                self.log(traceback.format_exc(limit=3))

        self.thread = threading.Thread(target=body, daemon=True)
        self.thread.start()


def _float(text, label):
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"{label} must be a number, got {text!r}")


def _int(text, label):
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{label} must be a whole number, got {text!r}")


# Align solves with the SAME defaults as `pyargus align` -- a GUI run
# and a CLI run on the same data must produce the same answer
# (tests pin these against the CLI parser).
ALIGN_CELL = 6.0
ALIGN_MIN_POINTS = 6


def cancelled_before(runner, what):
    """The one write gate every stage uses: after Stop, nothing lands
    on disk and nothing is offered downstream."""
    if runner.cancelled():
        runner.log(f"cancelled before {what}; nothing written")
        return True
    return False


def _require_cloud(app):
    cloud = app.cloud_path.get().strip()
    if not cloud:
        raise ValueError("pick a point cloud first (the Data panel)")
    if not Path(cloud).is_file():
        raise ValueError(f"no such cloud: {cloud}")
    return cloud


def _require_new_file(text, label):
    if not text.strip():
        raise ValueError(f"pick an output path for {label}")
    return text.strip()


def _refuse_existing(path, label):
    """The CLI refuses existing outputs without --force; the GUI
    equivalent refuses typed-in paths that already exist (the save
    dialog covers picked ones, a pasted path bypasses it)."""
    if Path(path).exists():
        raise ValueError(f"{label} already exists: {path} -- "
                         f"pick a new name, or remove it first")


class QaStage:
    title = "Strip QA"

    def __init__(self, parent, app):
        self.app = app
        self.out_dir = tk.StringVar()
        self.control = tk.StringVar()
        self.order = tk.StringVar(value="pnez")
        box = ttk.Frame(parent)
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        path_row(box, "Report folder", self.out_dir, 0, directory=True)
        path_row(box, "Control CSV (optional)", self.control, 1)
        ttk.Label(box, text="Control order").grid(row=2, column=0, sticky="w")
        ttk.Combobox(box, textvariable=self.order, values=("pnez", "penz"),
                     state="readonly", width=8).grid(row=2, column=1,
                                                    sticky="w", padx=2)

    def prepare(self):
        app = self.app
        cloud = _require_cloud(app)
        out_dir = _require_new_file(self.out_dir.get(), "the report")
        control_csv = self.control.get().strip()
        order = self.order.get()
        sbet_path = app.sbet_path.get().strip() or None

        def work(runner):
            from pyargus.formats import las
            from pyargus.qa import report

            runner.log(f"reading {cloud}")
            fields = ["x", "y", "z", "classification", "point_source_id"]
            if sbet_path:
                fields.append("gps_time")
            points = las.read_points(cloud, fields=tuple(fields))
            control = None
            if control_csv:
                from pyargus.formats import control as control_mod
                control = control_mod.read_control_csvs([control_csv], order)
            traj_time = None
            if sbet_path:
                from pyargus.formats import sbet
                traj_time = sbet.read_sbet(sbet_path)["time"]
            if cancelled_before(runner, "the report"):
                return
            summary = report.generate(points, out_dir,
                                      title=Path(cloud).name,
                                      control=control, traj_time=traj_time)
            for pair in summary["strip_dz"]:
                runner.log(f"dz {pair['a']}-{pair['b']}: "
                           f"median {pair['median']:+.3f}  "
                           f"rmse {pair['rmse']:.3f}")
            if "control" in summary and "median" in summary["control"]:
                c = summary["control"]
                runner.log(f"control: n {c['n']}  median {c['median']:+.3f}"
                           f"  nmad {c['nmad']:.3f}")
            runner.log(f"report: {summary['report']}")
            from pyargus.qa import density, raster
            dens, _, _ = density.density_grid(points["x"], points["y"],
                                              cell=3.0)
            runner.report = raster.sequential_rgba(dens)

        return work


class ClassifyStage:
    title = "Classify"

    def __init__(self, parent, app):
        self.app = app
        self.out_path = tk.StringVar()
        self.cell = tk.StringVar(value="3.0")
        self.slope = tk.StringVar(value="0.15")
        self.window = tk.StringVar(value="60.0")
        self.threshold = tk.StringVar(value="1.5")
        box = ttk.Frame(parent)
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        path_row(box, "Classified cloud out", self.out_path, 0, save=True)
        for i, (label, var) in enumerate((("Cell", self.cell),
                                          ("Slope", self.slope),
                                          ("Window", self.window),
                                          ("Threshold", self.threshold))):
            ttk.Label(box, text=label).grid(row=1 + i, column=0, sticky="w")
            ttk.Entry(box, textvariable=var, width=8).grid(
                row=1 + i, column=1, sticky="w", padx=2)

    def prepare(self):
        cloud = _require_cloud(self.app)
        out = _require_new_file(self.out_path.get(), "the classified cloud")
        if Path(out).resolve() == Path(cloud).resolve():
            raise ValueError("the classified cloud must be a NEW file, "
                             "never the input")
        _refuse_existing(out, "the classified cloud")
        cell = _float(self.cell.get(), "Cell")
        slope = _float(self.slope.get(), "Slope")
        window = _float(self.window.get(), "Window")
        threshold = _float(self.threshold.get(), "Threshold")

        def work(runner):
            import laspy

            from pyargus.classify import ground

            runner.log(f"reading {cloud}")
            las = laspy.read(cloud)
            x, y, z = (np.asarray(las.x), np.asarray(las.y),
                       np.asarray(las.z))
            try:
                eligible = (np.asarray(las.return_number)
                            == np.asarray(las.number_of_returns))
            except AttributeError:
                eligible = np.ones(x.size, dtype=bool)
            result = ground.smrf(x[eligible], y[eligible], z[eligible],
                                 cell=cell, slope=slope, window=window,
                                 threshold=threshold)
            if cancelled_before(runner, "writing"):
                return
            classification = np.ones(x.size, dtype=np.uint8)
            classification[np.flatnonzero(eligible)[result.ground]] = 2
            las.classification = classification
            las.write(out)
            n = int(result.ground.sum())
            runner.log(f"ground: {n:,} ({100.0 * n / x.size:.1f}% of cloud)")
            runner.log(f"wrote: {out}")
            runner.products.append(("classified", Path(out)))

        return work


class DtmStage:
    title = "DTM / DSM"

    def __init__(self, parent, app):
        self.app = app
        self.cloud_override = tk.StringVar()
        self.out_path = tk.StringVar()
        self.cell = tk.StringVar(value="3.0")
        self.dsm = tk.BooleanVar(value=False)
        box = ttk.Frame(parent)
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        path_row(box, "Classified cloud (blank = main)", self.cloud_override,
                 0)
        path_row(box, "Surface out (.asc)", self.out_path, 1, save=True)
        ttk.Label(box, text="Cell").grid(row=2, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.cell, width=8).grid(
            row=2, column=1, sticky="w", padx=2)
        ttk.Checkbutton(box, text="DSM (highest surface, all returns)",
                        variable=self.dsm).grid(row=3, column=0,
                                                columnspan=2, sticky="w")

    def source_cloud(self):
        return self.cloud_override.get().strip() or _require_cloud(self.app)

    def prepare(self):
        cloud = self.source_cloud()
        if not Path(cloud).is_file():
            raise ValueError(f"no such cloud: {cloud}")
        out = _require_new_file(self.out_path.get(), "the surface")
        cell = _float(self.cell.get(), "Cell")
        want_dsm = bool(self.dsm.get())

        def work(runner):
            from pyargus.formats import las
            from pyargus.surfaces import dtm

            runner.log(f"reading {cloud}")
            points = las.read_points(cloud,
                                     fields=("x", "y", "z", "classification"))
            if want_dsm:
                grid, xe, ye = dtm.dsm_grid(points["x"], points["y"],
                                            points["z"], cell)
            else:
                m = points["classification"] == 2
                if not m.any():
                    raise ValueError("no class-2 points; classify first")
                grid, xe, ye = dtm.dtm_grid(points["x"][m], points["y"][m],
                                            points["z"][m], cell)
            if cancelled_before(runner, "writing"):
                return
            dtm.write_esri_ascii(out, grid, xe, ye)
            finite = grid[np.isfinite(grid)]
            runner.log(f"z {finite.min():.2f}..{finite.max():.2f} over "
                       f"{finite.size:,} cells")
            runner.log(f"wrote: {out}")

        return work


class ContourStage:
    title = "Contours"

    def __init__(self, parent, app):
        self.app = app
        self.cloud_override = tk.StringVar()
        self.out_path = tk.StringVar()
        self.interval = tk.StringVar(value="1.0")
        self.cell = tk.StringVar(value="3.0")
        self.breaklines = tk.StringVar()
        box = ttk.Frame(parent)
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        path_row(box, "Classified cloud (blank = main)", self.cloud_override,
                 0)
        path_row(box, "Contours out (.dxf/.geojson)", self.out_path, 1,
                 save=True)
        path_row(box, "Breaklines (3D GeoJSON, optional)", self.breaklines,
                 2)
        for i, (label, var) in enumerate((("Interval", self.interval),
                                          ("Cell", self.cell))):
            ttk.Label(box, text=label).grid(row=3 + i, column=0, sticky="w")
            ttk.Entry(box, textvariable=var, width=8).grid(
                row=3 + i, column=1, sticky="w", padx=2)

    def prepare(self):
        cloud = (self.cloud_override.get().strip()
                 or _require_cloud(self.app))
        if not Path(cloud).is_file():
            raise ValueError(f"no such cloud: {cloud}")
        out = _require_new_file(self.out_path.get(), "the contours")
        if Path(out).suffix.lower() not in (".dxf", ".geojson", ".json"):
            raise ValueError("contours go to .dxf or .geojson")
        interval = _float(self.interval.get(), "Interval")
        cell = _float(self.cell.get(), "Cell")
        breakline_path = self.breaklines.get().strip()

        def work(runner):
            from pyargus.core import gridding
            from pyargus.formats import dxf, geojson, las
            from pyargus.surfaces import contours as contours_mod
            from pyargus.surfaces import dtm, tin

            runner.log(f"reading {cloud}")
            points = las.read_points(cloud,
                                     fields=("x", "y", "z", "classification"))
            m = points["classification"] == 2
            if not m.any():
                raise ValueError("no class-2 points; classify first")
            if breakline_path:
                breaks = geojson.read_breaklines_geojson(breakline_path)
                surface = tin.build_tin(
                    np.column_stack([points["x"][m], points["y"][m],
                                     points["z"][m]]),
                    breaklines=breaks, cell_hint=cell)
                grid, xe, ye = surface.grid(cell)
                covered = gridding.coverage_mask(
                    surface.points[:, 0], surface.points[:, 1], xe, ye,
                    max_distance=10)
                grid = np.where(covered, grid, np.nan)
                runner.log(f"TIN with {len(breaks)} breakline(s), "
                           f"{surface.n_breakline_points:,} vertices")
            else:
                grid, xe, ye = dtm.dtm_grid(points["x"][m], points["y"][m],
                                            points["z"][m], cell)
            lines = contours_mod.contour_grid(grid, xe, ye, interval)
            if not lines:
                raise ValueError("relief is smaller than one interval; "
                                 "no contours")
            if cancelled_before(runner, "writing"):
                return
            if Path(out).suffix.lower() == ".dxf":
                dxf.write_contours_dxf(out, lines)
            else:
                geojson.write_contours_geojson(out, lines)
            runner.log(f"{len(lines)} lines, "
                       f"{len({line.level for line in lines})} levels")
            runner.log(f"wrote: {out}")

        return work


class AlignStage:
    title = "Align"

    def __init__(self, parent, app):
        self.app = app
        self.vertical = tk.StringVar(value="EPSG:6360")
        self.network = tk.BooleanVar(value=True)
        self.write_path = tk.StringVar()
        box = ttk.Frame(parent)
        box.pack(fill="x")
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Vertical (CRS or N meters)").grid(
            row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.vertical, width=14).grid(
            row=0, column=1, sticky="w", padx=2)
        ttk.Checkbutton(box, text="Let PROJ fetch geoid grids",
                        variable=self.network).grid(row=1, column=0,
                                                    columnspan=2, sticky="w")
        path_row(box, "Corrected cloud out (optional)", self.write_path, 2,
                 save=True)

    def prepare(self):
        app = self.app
        cloud = _require_cloud(app)
        sbet_path = app.sbet_path.get().strip()
        if not sbet_path:
            raise ValueError("alignment needs the SBET (the Data panel)")
        if not Path(sbet_path).is_file():
            raise ValueError(f"no such SBET: {sbet_path}")
        vertical = self.vertical.get().strip()
        if not vertical:
            raise ValueError("state the vertical story: a vertical CRS "
                             "(EPSG:6360) or a geoid N in meters "
                             "(negative across CONUS)")
        try:
            vertical = float(vertical)
        except ValueError:
            pass
        network = bool(self.network.get())
        write = self.write_path.get().strip() or None
        if write and Path(write).resolve() == Path(cloud).resolve():
            raise ValueError("the corrected cloud must be a NEW file")
        if write:
            _refuse_existing(write, "the corrected cloud")

        def work(runner):
            import laspy

            from pyargus.align import attach, solve_alignment
            from pyargus.formats import crs as crs_mod
            from pyargus.formats import las as las_mod
            from pyargus.formats import sbet as sbet_mod

            runner.log(f"reading {cloud}")
            points = las_mod.read_points(
                cloud, fields=("x", "y", "z", "gps_time",
                               "point_source_id", "classification"))
            trajectory = sbet_mod.read_sbet(sbet_path)
            with laspy.open(cloud) as reader:
                map_crs = reader.header.parse_crs()
            if map_crs is None:
                raise ValueError(f"{cloud} declares no CRS")
            map_e, map_n, map_z = crs_mod.sbet_to_map(
                trajectory, map_crs, vertical=vertical,
                allow_network=network)
            mask = points["classification"] == 2
            if not mask.any():
                raise ValueError("no class-2 points to solve on; "
                                 "classify first")
            sub = {k: points[k][mask] for k in
                   ("x", "y", "z", "gps_time", "point_source_id")}
            attached = attach.bundles_from_cloud(sub, trajectory,
                                                 map_e, map_n, map_z)
            runner.log(f"week {attached.gps_week}, heading "
                       f"{attached.heading_source!r}, "
                       f"AGL {attached.agl_median:.0f}")
            if cancelled_before(runner, "the solve"):
                return
            result = solve_alignment(attached.bundles, cell=ALIGN_CELL,
                                     min_points=ALIGN_MIN_POINTS)
            runner.log(f"boresight {result.boresight}")
            for i, sid in enumerate(attached.strip_ids):
                runner.log(f"offset strip {sid}: "
                           f"{result.offsets[i, 2]:+.4f}")
            runner.log(f"patch rms {result.rms_before:.3f} -> "
                       f"{result.rms_after:.3f}")
            if write and cancelled_before(runner, "writing"):
                return
            if write:
                offsets = {sid: result.offsets[i]
                           for i, sid in enumerate(attached.strip_ids)}
                xyz, skipped = attach.apply_corrections(
                    points, trajectory, map_e, map_n, map_z,
                    attached.heading_source, result.boresight, offsets)
                las = laspy.read(cloud)
                las.x, las.y, las.z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
                las.write(write)
                runner.log(f"wrote: {write}"
                           + (f" ({skipped:,} outside trajectory "
                              f"unchanged)" if skipped else ""))
                runner.products.append(("classified", Path(write)))

        return work


class Application:
    def __init__(self, root):
        self.root = root
        root.title("pyArgus")
        root.geometry("1100x720")
        root.protocol("WM_DELETE_WINDOW", self._confirm_close)

        self.runner = StageRunner()
        self._stage_open = False
        self._photo = None
        self._drawn = None      # the report array last put on the canvas

        left = ttk.Frame(root, padding=8)
        left.pack(side="left", fill="y")
        right = ttk.Frame(root, padding=8)
        right.pack(side="right", fill="both", expand=True)

        data = ttk.LabelFrame(left, text="Data", padding=6)
        data.pack(fill="x")
        data.columnconfigure(1, weight=1)
        self.cloud_path = tk.StringVar()
        self.sbet_path = tk.StringVar()
        path_row(data, "Point cloud (.las/.laz)", self.cloud_path, 0)
        path_row(data, "SBET (optional)", self.sbet_path, 1)

        self.notebook = ttk.Notebook(left)
        self.notebook.pack(fill="x", pady=(8, 0))
        self.stages = []
        for stage_class in (QaStage, ClassifyStage, DtmStage, ContourStage,
                            AlignStage):
            tab = ttk.Frame(self.notebook, padding=6)
            self.notebook.add(tab, text=stage_class.title)
            self.stages.append(stage_class(tab, self))

        self._build_run_panel(left)
        self.canvas = tk.Canvas(right, background=PALETTE["ink"],
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.root.after(PREVIEW_MS, self._tick)

    def _build_run_panel(self, parent):
        box = ttk.Frame(parent)
        box.pack(fill="x", pady=(8, 0))
        self.run_button = ttk.Button(box, text="Run", command=self.run)
        self.run_button.pack(side="left")
        self.stop_button = ttk.Button(box, text="Stop", state="disabled",
                                      command=self.runner.cancel)
        self.stop_button.pack(side="left", padx=4)
        self.progress = ttk.Progressbar(box, length=110, mode="determinate")
        self.progress.pack(side="left", padx=6)
        ttk.Button(box, text="pyLynceus",
                   command=self.open_pylynceus).pack(side="right")

        self.log = tk.Text(parent, height=11, width=46, state="disabled",
                           font=("Consolas", 8),
                           background=PALETTE["ink"],
                           foreground=PALETTE["ground"],
                           insertbackground=PALETTE["ground"],
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True, pady=(6, 0))

    def run(self):
        if self.runner.running:
            return
        stage = self.stages[self.notebook.index(self.notebook.select())]
        try:
            work = stage.prepare()
        except ValueError as exc:
            messagebox.showerror("pyArgus", str(exc))
            return
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.runner.start(work)
        self._stage_open = True

    def open_pylynceus(self):
        """Launch pyLynceus detached, in its own environment; a launch
        that dies within PYLYNCEUS_STARTUP_MS reports its exit code and
        last output line instead of nothing."""
        import subprocess
        import tempfile

        home = find_pylynceus()
        if home is None:
            messagebox.showerror(
                "pyArgus",
                "pyLynceus was not found: set PYLYNCEUS_HOME, or keep "
                "its checkout beside this one")
            return
        try:
            command = pylynceus_command(home)
        except ValueError as exc:
            messagebox.showerror("pyArgus", str(exc))
            return
        log = tempfile.NamedTemporaryFile(
            mode="w", prefix="pylynceus-", suffix=".log", delete=False)
        options = {"cwd": home, "stdout": log,
                   "stderr": subprocess.STDOUT, "env": dict(os.environ)}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        process = subprocess.Popen(command, **options)
        log.close()
        self.runner.log(f"pyLynceus launched from {home}")
        self.root.after(
            PYLYNCEUS_STARTUP_MS,
            lambda: self._pylynceus_watch(process, Path(log.name)))

    def _pylynceus_watch(self, process, log_path):
        if process.poll() is None:
            return    # alive; the window from here on is pyLynceus's own
        tail = ""
        try:
            lines = log_path.read_text(errors="replace").strip().splitlines()
            tail = lines[-1] if lines else ""
        except OSError:
            pass
        self.runner.log(
            f"pyLynceus exited immediately (code {process.returncode})"
            + (f": {tail}" if tail else "")
            + f" -- full output in {log_path}")

    def _confirm_close(self):
        if self.runner.running:
            if not messagebox.askyesno(
                    "pyArgus", "a stage is still running; close anyway?"):
                return
        self.root.destroy()

    def _adopt_products(self, runner):
        """Offer a finished stage's outputs downstream: fill EMPTY
        override fields only, and say so in the log."""
        for kind, path in runner.products:
            if kind != "classified":
                continue
            for stage in self.stages:
                variable = getattr(stage, "cloud_override", None)
                if variable is not None and not variable.get().strip():
                    variable.set(str(path))
                    self.runner.log(
                        f"{stage.title}: using {path.name}")

    def _tick(self):
        runner = self.runner
        while True:
            try:
                line = runner.lines.get_nowait()
            except queue.Empty:
                break
            self.log.configure(state="normal")
            self.log.insert("end", line + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        done, total = runner.progress
        self.progress.configure(maximum=max(total, 1), value=done)
        # Draw whenever a report exists that is not already on the
        # canvas -- NEVER gate this on having drained log lines: the
        # worker sets the report after its last log line, so on a real
        # cloud the drained tick precedes the report and a gated draw
        # never fires (found by the review panel; the pyLynceus
        # original redraws unconditionally).
        report = runner.report
        if report is not None and report is not self._drawn:
            self._drawn = report
            self._draw_preview(report)
        # Completion is tracked with an explicit flag, never by reading
        # the button's state back: widget options come back as Tcl_Obj,
        # whose comparison against "disabled" is unreliable (the
        # pyLynceus lesson, kept).
        if self._stage_open and not runner.running \
                and runner.thread is not None:
            self._stage_open = False
            self.run_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self._adopt_products(runner)
        self.root.after(PREVIEW_MS, self._tick)

    def _draw_preview(self, rgba):  # pragma: no cover - pixels on screen
        try:
            self._photo = preview_photo(preview_image(rgba))
            self.canvas.delete("all")
            self.canvas.create_image(
                self.canvas.winfo_width() // 2,
                self.canvas.winfo_height() // 2, image=self._photo)
        except Exception:
            pass


def main():
    if not TK_AVAILABLE:  # pragma: no cover
        raise SystemExit(
            "tkinter is not available in this Python; the GUI needs it "
            "(the library does not)")
    root = tk.Tk()
    apply_theme(root)
    apply_branding(root)
    Application(root)
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
