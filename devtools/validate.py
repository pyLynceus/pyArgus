"""Serial validation with source identity, environment and explicit skips.

Run: .venv/Scripts/python.exe -m devtools.validate
Optional: --reference (requires reference data), --exe PATH (built desktop).
This validates a source checkout; it does not claim to build a release.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()

def git_or_note(*args):
    """Git's answer, or a note when git is not on PATH; the fingerprint does not need git."""
    try:
        return git(*args)
    except (OSError, subprocess.CalledProcessError) as exc:
        return f'git unavailable: {type(exc).__name__}'

def source_identity():
    """Fingerprint the source with the scheme review packets use (devtools.fingerprint).

    Before October 22, 2026 this hashed every nonignored file known to git while
    the packet hashed a fixed set of roots, so a validation record could not be
    tied to a packet. Both now share one scheme; git adds only commit and status.
    """
    from devtools.fingerprint import SCHEME, source_fingerprint
    return dict(commit=git_or_note('rev-parse', 'HEAD'), status=git_or_note('status', '--porcelain'),
                sha256=source_fingerprint(ROOT), scheme=SCHEME)

def lock_directory():
    """The shared Git directory when git can name it, so sibling worktrees serialize; else the checkout."""
    try:
        common = Path(git('rev-parse', '--git-common-dir'))
    except (OSError, subprocess.CalledProcessError):
        return ROOT
    if not common.is_absolute(): common = ROOT / common
    return common.resolve()

def distribution_inventory(distributions=None):
    """Keep malformed installed metadata visible without crashing validation."""
    packages, warnings = [], []
    for dist in metadata.distributions() if distributions is None else distributions:
        location = str(getattr(dist, '_path', '(metadata location unavailable)'))
        try:
            name, version = dist.metadata.get('Name'), dist.version
            if not isinstance(name, str) or not name.strip():
                raise ValueError('missing distribution Name')
            if not isinstance(version, str) or not version.strip():
                raise ValueError('missing distribution Version')
            packages.append(dict(name=name, version=version))
        except Exception as exc:
            warnings.append(dict(location=location, error=f'{type(exc).__name__}: {exc}'))
    return dict(packages=sorted(packages, key=lambda row: row['name'].casefold()),
                environment_warnings=warnings)


def junit_summary(path):
    root = ET.parse(path).getroot()
    rows = []
    for case in root.iter('testcase'):
        outcome = 'passed'
        reason = ''
        for tag in ('error', 'failure', 'skipped'):
            node = case.find(tag)
            if node is not None:
                outcome = tag
                reason = node.get('message') or node.text or '(no reason supplied)'
                break
        rows.append(dict(test=case.get('classname', '') + '::' + case.get('name', ''),
                         outcome=outcome, reason=reason))
    return dict(total=len(rows), counts={s:sum(r['outcome']==s for r in rows)
                for s in ('passed', 'skipped', 'failure', 'error')},
                nonpassing=[r for r in rows if r['outcome']!='passed'])

def decision(steps, tests, before, after, environment_warnings=()):
    if before != after:
        return 'invalid_source_changed'
    if any(s['returncode'] != 0 for s in steps):
        return 'failed'
    if tests is None or tests['total'] == 0:
        return 'failed_missing_test_results'
    if tests['counts']['failure'] or tests['counts']['error']:
        return 'failed'
    if tests['counts']['skipped']:
        return 'needs_skip_review'
    if environment_warnings:
        return 'needs_environment_review'
    return 'passed_requested_checks'

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', action='store_true')
    parser.add_argument('--exe', type=Path, help='optional existing frozen executable')
    args = parser.parse_args(argv)
    # Place the lock in the shared Git directory so sibling worktrees using
    # this runner cannot start heavy checks concurrently.
    lock = lock_directory() / 'pyargus-validation.lock'
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        parser.error(f'validation lock exists: {lock}; do not remove until its recorded process has ended')
    with os.fdopen(handle, 'w') as f:
        json.dump(dict(pid=os.getpid(), checkout=str(ROOT)), f)
    report = {'status':'interrupted', 'steps':[], 'tests':None,
              'reference_requested':args.reference, 'packaged_exe_requested':bool(args.exe)}
    folder = None
    try:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        folder = ROOT / 'reference' / 'reports' / f'validation-{stamp}-{os.getpid()}'
        folder.mkdir(parents=True, exist_ok=False)
        report.update(started_utc=stamp, checkout=str(ROOT), source_before=source_identity(),
                      python=sys.version, interpreter=sys.executable, platform=platform.platform(),
                      **distribution_inventory())
        def run(name, command):
            print(f'{name}: running serially; log {folder / (name + ".log")}', flush=True)
            with (folder / (name+'.log')).open('w', encoding='utf-8') as log:
                try:
                    rc = subprocess.run(command, cwd=ROOT, stdout=log,
                                        stderr=subprocess.STDOUT, check=False).returncode
                except OSError as exc:
                    log.write(str(exc));rc = 127
            report['steps'].append(dict(name=name, command=list(map(str,command)), returncode=rc))
            print(f'{name}: exit {rc}',flush=True)
            return rc
        if run('dependencies', [sys.executable,'-m','pip','check']) == 0:
            rc = run('pytest', [sys.executable,'-m','pytest','tests/','-q','-ra',
                               '--junitxml',str(folder/'pytest.xml')])
            if (folder/'pytest.xml').exists():report['tests']=junit_summary(folder/'pytest.xml')
            if rc == 0 and args.reference:
                run('reference', [sys.executable,'-m','reference.run_all'])
            if rc == 0 and args.exe:
                exe = args.exe.resolve()
                if not exe.is_file():raise ValueError(f'executable not found: {exe}')
                report['executable'] = dict(path=str(exe), sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                    provenance='Supplied executable tested; source-to-build provenance NOT established by this hash.')
                run('packaged-self-test',[str(exe),'--self-test'])
        report['source_after']=source_identity()
        report['status']=decision(report['steps'],report['tests'],report['source_before'],report['source_after'],
                                  report.get('environment_warnings', ()))
        return 0 if report['status']=='passed_requested_checks' else 1
    except Exception as exc:
        report['status']='runner_error';report['error']=repr(exc)
        return 1
    finally:
        if folder is not None:
            (folder/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(f'{report["status"]}: {folder / "validation.json"}',flush=True)
        lock.unlink(missing_ok=True)

if __name__=='__main__':
    raise SystemExit(main())
