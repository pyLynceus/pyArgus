"""One install, upgrade and uninstall cycle for two dated Windows installers.

The cycle installs the first setup.exe silently into a directory whose name
contains spaces, checks the installed build record and executable hash, runs
the frozen self-test, installs the second setup.exe over it in place (the
installers share one AppId, so this is the upgrade an operator would get),
checks that the build changed and the self-test still passes, uninstalls with
the recorded uninstaller, and checks that an external project folder created
before the cycle is untouched throughout. Everything observed goes into the
report JSON; nothing is inferred.

Both installers register the same per-user AppId, so running this on a
workstation that already has pyArgus (Codex) installed re-points that
registration at the test directory and the final uninstall removes it. The
harness therefore refuses to start while that registration exists unless
--allow-existing-installation is given, and it never touches the production
default directory.

Run (from the checkout, with no pyArgus running):
  .venv/Scripts/python.exe -m devtools.installer_cycle --first <setup-16.exe> --second <setup-19.exe>
      --directory "C:/pyArgus cycle test/pyArgus-Codex" --report build/installer-cycle.json
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

APP_ID = '{88A25EB2-BA18-4722-A4CE-63D9EDC739AB}'
UNINSTALL_KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\\' + APP_ID + '_is1'
SILENT = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCANCEL']


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 ** 2), b''):
            result.update(block)
    return result.hexdigest()


def registration():
    """The per-user uninstall registration for the AppId, or None."""
    if sys.platform != 'win32':
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY.replace('\\\\', '\\')) as key:
            values = {}
            for name in ('DisplayName', 'DisplayVersion', 'InstallLocation', 'UninstallString'):
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    values[name] = None
            return values
    except FileNotFoundError:
        return None


def run(command, timeout):
    started = time.monotonic()
    completed = subprocess.run([str(c) for c in command], capture_output=True, text=True, timeout=timeout)
    return dict(command=[str(c) for c in command], returncode=completed.returncode,
                seconds=round(time.monotonic() - started, 1),
                stdout=completed.stdout[-2000:], stderr=completed.stderr[-2000:])


def installed_state(directory):
    exe = directory / 'pyArgus.exe'
    info = directory / 'build-info.json'
    state = dict(directory=str(directory), executable_present=exe.is_file(),
                 build_info_present=info.is_file())
    if info.is_file():
        record = json.loads(info.read_text(encoding='utf-8'))
        state.update(release=record.get('release'), recorded_exe_sha256=record.get('exe_sha256'))
    if exe.is_file():
        state['exe_sha256'] = digest(exe)
        state['exe_matches_build_info'] = state.get('recorded_exe_sha256') == state['exe_sha256']
    return state


def self_test(directory, report_path):
    exe = directory / 'pyArgus.exe'
    result = run([exe, '--self-test', '--self-test-report', report_path], timeout=1800)
    if report_path.is_file():
        evidence = json.loads(report_path.read_text(encoding='utf-8'))
        result['report'] = {k: evidence.get(k) for k in ('passed', 'software', 'copc', 'geoid', 'gpu', 'multicore')}
    return result


def install(setup, directory, log):
    return run([setup, *SILENT, f'/DIR={directory}', f'/LOG={log}'], timeout=1800)


def uninstall(directory, log):
    uninstaller = directory / 'Uninstall' / 'unins000.exe'
    if not uninstaller.is_file():
        return dict(error='uninstaller missing: ' + str(uninstaller))
    return run([uninstaller, *SILENT, f'/LOG={log}'], timeout=900)


def cycle(first, second, directory, report_path, *, allow_existing=False):
    report = dict(started_utc=datetime.now(timezone.utc).isoformat(), first=str(first), second=str(second),
                  first_sha256=digest(first), second_sha256=digest(second), directory=str(directory),
                  registration_before=registration(), steps=[], passed=False)
    if report['registration_before'] and not allow_existing:
        report['refused'] = ('pyArgus (Codex) is already registered for this user at '
                             f"{report['registration_before'].get('InstallLocation')}; the cycle would re-point "
                             'that registration. Uninstall it first, or pass --allow-existing-installation.')
        return report
    if directory.exists() and any(directory.iterdir()):
        report['refused'] = 'the target directory is not empty: ' + str(directory)
        return report
    logs = Path(tempfile.mkdtemp(prefix='pyargus-installer-cycle-'))
    external = logs / 'external project'
    external.mkdir()
    (external / 'project.argus.json').write_text('{"keep": "me"}', encoding='utf-8')
    external_before = digest(external / 'project.argus.json')
    report['external_project'] = str(external / 'project.argus.json')
    try:
        step = dict(name='install first', **install(first, directory, logs / 'install-first.log'))
        step['installed'] = installed_state(directory)
        step['registration'] = registration()
        report['steps'].append(step)
        if step['returncode'] != 0 or not step['installed']['executable_present']:
            return report
        report['steps'].append(dict(name='self-test first', **self_test(directory, logs / 'self-test-first.json')))
        step = dict(name='upgrade in place', **install(second, directory, logs / 'install-second.log'))
        step['installed'] = installed_state(directory)
        step['registration'] = registration()
        report['steps'].append(step)
        if step['returncode'] != 0:
            return report
        report['upgrade_changed_build'] = (report['steps'][0]['installed'].get('release') != step['installed'].get('release')
                                           and report['steps'][0]['installed'].get('exe_sha256') != step['installed'].get('exe_sha256'))
        report['steps'].append(dict(name='self-test second', **self_test(directory, logs / 'self-test-second.json')))
        step = dict(name='uninstall', **uninstall(directory, logs / 'uninstall.log'))
        time.sleep(3)   # the uninstaller removes itself after it exits
        step['directory_after'] = sorted(str(p.relative_to(directory)) for p in directory.rglob('*')) if directory.exists() else []
        step['registration'] = registration()
        report['steps'].append(step)
        report['external_project_unchanged'] = digest(external / 'project.argus.json') == external_before
        report['passed'] = (all(s.get('returncode') == 0 for s in report['steps'])
                            and all(s.get('report', {}).get('passed') for s in report['steps'] if 'report' in s)
                            and report['upgrade_changed_build'] and report['external_project_unchanged']
                            and step['registration'] is None)
        return report
    finally:
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        report['logs'] = str(logs)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--first', type=Path, required=True, help='the older setup.exe')
    parser.add_argument('--second', type=Path, required=True, help='the newer setup.exe installed over it')
    parser.add_argument('--directory', type=Path, required=True, help='an empty test directory, ideally with spaces in its name')
    parser.add_argument('--report', type=Path, required=True, help='where the JSON evidence is written')
    parser.add_argument('--allow-existing-installation', action='store_true',
                        help='proceed although pyArgus (Codex) is already registered for this user')
    args = parser.parse_args(argv)
    for setup in (args.first, args.second):
        if not setup.is_file():
            parser.error('installer not found: ' + str(setup))
    report = cycle(args.first.resolve(), args.second.resolve(), args.directory.resolve(), args.report.resolve(),
                   allow_existing=args.allow_existing_installation)
    print(json.dumps({k: v for k, v in report.items() if k != 'steps'}, indent=2))
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
