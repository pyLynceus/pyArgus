"""Open desktop folders without relying on Windows-only shell functions."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def external_environment():
    env = os.environ.copy()
    if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
        original = env.get("LD_LIBRARY_PATH_ORIG")
        if original is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = original
    return env


def open_folder(path):
    folder = Path(path).resolve()
    if not folder.is_dir():
        raise FileNotFoundError("Folder is missing: " + str(folder))
    if sys.platform == "win32":
        return os.startfile(str(folder))
    env = external_environment()
    # A bare WSLg image need not contain a Linux file manager.
    explorer = shutil.which("explorer.exe") if env.get("WSL_DISTRO_NAME") else None
    if explorer:
        native = subprocess.check_output(["wslpath", "-w", str(folder)], text=True, env=env).strip()
        command = [explorer, native]
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        executable = shutil.which(opener)
        if not executable:
            raise FileNotFoundError("Install " + opener + " to open folders from pyArgus.")
        command = [executable, str(folder)]
    return subprocess.Popen(command, env=env, start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def register_wsl_browser():
    """Use the Windows browser for report URLs in a bare WSLg desktop."""
    if not sys.platform.startswith("linux") or not os.environ.get("WSL_DISTRO_NAME") or os.environ.get("BROWSER"):
        return False
    explorer=shutil.which("explorer.exe")
    if not explorer:return False
    import webbrowser
    from urllib.parse import urlsplit,unquote
    class WindowsBrowser(webbrowser.BaseBrowser):
        def open(self,url,new=0,autoraise=True):
            target=url
            parsed=urlsplit(url)
            env=external_environment()
            try:
                if parsed.scheme=='file' and parsed.netloc in ('','localhost'):
                    target=subprocess.check_output(['wslpath','-w',unquote(parsed.path)],text=True,env=env).strip()
                subprocess.Popen([explorer,target],env=env,start_new_session=True,
                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                return True
            except (OSError,subprocess.SubprocessError):return False
    webbrowser.register('pyargus-wsl',None,WindowsBrowser(),preferred=True)
    return True
