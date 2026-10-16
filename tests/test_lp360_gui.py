"""LP360 shortcut wiring and missing-input flow without touching operator data."""
import time
from pathlib import Path
from copy import deepcopy
import pytest
from tests.test_gui import root,application


def wait(app,shortcut):
    stop=time.monotonic()+10
    while shortcut.running and time.monotonic()<stop:app.root.update();time.sleep(.01)
    app.root.update();assert not shortcut.running


def test_lp360_button_and_menu_preserve_current_project(application,tmp_path):
    app=application;w=app.workspace;w.capture();before=deepcopy(w.tracker.data['project']);shortcut=w.layout.lp360
    labels=[w.layout.menus['File'].entrycget(i,'label') for i in range(w.layout.menus['File'].index('end')+1) if w.layout.menus['File'].type(i)=='command']
    assert 'LP360 job…' in labels
    shortcut.open(tmp_path);wait(app,shortcut)
    assert shortcut.window.winfo_exists() and 'Needs input:' in shortcut.status.get()
    assert 'source clouds' in shortcut.status.get() and 'Control CSV' in shortcut.status.get()
    assert w.tracker.data['project']==before
    shortcut.start();wait(app,shortcut)
    assert shortcut.result['status']=='Needs input'
    assert not (tmp_path/'pyArgus_jobs').exists()
    assert w.tracker.data['project']==before
    assert shortcut.close()


def test_bad_settings_stay_editable_without_starting_a_job(application,tmp_path):
    shortcut=application.workspace.layout.lp360;shortcut.open(tmp_path);wait(application,shortcut)
    shortcut.vars['workers'].set('not a number');shortcut.start()
    assert 'Needs input:' in shortcut.status.get() and not shortcut.running
    assert not application.runner.running
    shortcut.close()
