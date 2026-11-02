from pathlib import Path
from types import SimpleNamespace
import pytest
from pyargus import desktop


def test_linux_folder_command_preserves_spaces(tmp_path,monkeypatch):
    folder=tmp_path/'folder with spaces';folder.mkdir();calls=[]
    monkeypatch.setattr(desktop.sys,'platform','linux')
    monkeypatch.delenv('WSL_DISTRO_NAME',raising=False)
    monkeypatch.setattr(desktop.shutil,'which',lambda name:'/usr/bin/'+name)
    monkeypatch.setattr(desktop.subprocess,'Popen',lambda command,**options:calls.append((command,options)))
    desktop.open_folder(folder)
    assert calls[0][0]==['/usr/bin/xdg-open',str(folder.resolve())]
    assert calls[0][1]['start_new_session']


def test_wsl_folder_uses_windows_file_manager(tmp_path,monkeypatch):
    calls=[];monkeypatch.setattr(desktop.sys,'platform','linux')
    monkeypatch.setenv('WSL_DISTRO_NAME','archlinux')
    monkeypatch.setattr(desktop.shutil,'which',lambda name:'/mnt/c/Windows/explorer.exe')
    monkeypatch.setattr(desktop.subprocess,'check_output',lambda *args,**kwargs:'WINDOWS_FOLDER\n')
    monkeypatch.setattr(desktop.subprocess,'Popen',lambda command,**kwargs:calls.append(command))
    desktop.open_folder(tmp_path)
    assert calls==[['/mnt/c/Windows/explorer.exe','WINDOWS_FOLDER']]


def test_folder_opener_reports_missing_command_and_missing_folder(tmp_path,monkeypatch):
    monkeypatch.setattr(desktop.sys,'platform','linux');monkeypatch.delenv('WSL_DISTRO_NAME',raising=False)
    monkeypatch.setattr(desktop.shutil,'which',lambda name:None)
    with pytest.raises(FileNotFoundError,match='Install xdg-open'):desktop.open_folder(tmp_path)
    with pytest.raises(FileNotFoundError,match='Folder is missing'):desktop.open_folder(tmp_path/'missing')


@pytest.mark.parametrize('original',[None,'/usr/local/lib'])
def test_external_programs_use_system_library_path_when_frozen(monkeypatch,original):
    monkeypatch.setattr(desktop.sys,'platform','linux');monkeypatch.setattr(desktop.sys,'frozen',True,raising=False)
    monkeypatch.setenv('LD_LIBRARY_PATH','/opt/pyargus/_internal')
    if original is None:monkeypatch.delenv('LD_LIBRARY_PATH_ORIG',raising=False)
    else:monkeypatch.setenv('LD_LIBRARY_PATH_ORIG',original)
    env=desktop.external_environment()
    assert env.get('LD_LIBRARY_PATH')==original
    assert desktop.os.environ['LD_LIBRARY_PATH']=='/opt/pyargus/_internal'


@pytest.mark.parametrize('fail',[False,True])
def test_x11_handler_is_restored_after_context_attempt(monkeypatch,fail):
    import ctypes
    import pyargus.gpu_renderer as module
    class Handler:
        value=17
        def __call__(self,value):
            old=self.value;self.value=value;return old
    handler=Handler()
    monkeypatch.setattr(module.sys,'platform','linux')
    monkeypatch.setattr(ctypes,'CDLL',lambda name:SimpleNamespace(XSetErrorHandler=handler))
    def attempt():
        with module._preserve_x11_error_handler():
            handler(None)
            if fail:raise RuntimeError('failed context')
    if fail:
        with pytest.raises(RuntimeError,match='failed context'):attempt()
    else:attempt()
    assert handler.value==17


def test_wsl_report_browser_translates_file_urls_and_keeps_urls_as_arguments(monkeypatch):
    import webbrowser
    registered=[];calls=[]
    monkeypatch.setattr(desktop.sys,'platform','linux');monkeypatch.setenv('WSL_DISTRO_NAME','archlinux');monkeypatch.delenv('BROWSER',raising=False)
    monkeypatch.setattr(desktop.shutil,'which',lambda name:'/mnt/c/Windows/explorer.exe')
    monkeypatch.setattr(webbrowser,'register',lambda *args,**kwargs:registered.append(args[2]))
    monkeypatch.setattr(desktop.subprocess,'check_output',lambda command,**kwargs:calls.append(command) or 'WINDOWS_REPORT\n')
    monkeypatch.setattr(desktop.subprocess,'Popen',lambda command,**kwargs:calls.append(command))
    assert desktop.register_wsl_browser()
    assert registered[0].open('file:///home/builder/report%20folder/report.html')
    assert calls[0]==['wslpath','-w','/home/builder/report folder/report.html']
    assert calls[1]==['/mnt/c/Windows/explorer.exe','WINDOWS_REPORT']
    assert registered[0].open('https://example.org/report?a=1&b=2')
    assert calls[-1]==['/mnt/c/Windows/explorer.exe','https://example.org/report?a=1&b=2']


def test_wsl_report_bridge_respects_explicit_browser(monkeypatch):
    monkeypatch.setattr(desktop.sys,'platform','linux');monkeypatch.setenv('WSL_DISTRO_NAME','archlinux');monkeypatch.setenv('BROWSER','chosen-browser')
    assert not desktop.register_wsl_browser()
