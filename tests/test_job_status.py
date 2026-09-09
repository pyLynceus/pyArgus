import threading
from pyargus.gui import StageRunner
from tests.test_gui import root, application


def test_elapsed_freezes_and_status_distinguishes_outcomes(monkeypatch):
    import pyargus.gui as gui
    now = [10.0]
    monkeypatch.setattr(gui.time, 'monotonic', lambda: now[0])
    release = threading.Event()
    entered = threading.Event()
    def work(runner):
        entered.set()
        release.wait(3)
    runner = StageRunner()
    assert runner.status == 'Ready'
    runner.start(work)
    assert entered.wait(2)
    now[0] = 15.0
    assert runner.status == 'Running' and runner.elapsed == 5
    runner.cancel()
    assert runner.status.startswith('Stopping')
    release.set()
    runner.thread.join(3)
    assert runner.status.startswith('Stopped')
    now[0] = 30.0
    assert runner.elapsed == 5
    def fail(runner):
        raise ValueError('test failure')
    runner.start(fail)
    runner.thread.join(3)
    assert runner.status == 'Failed'
    runner.start(lambda r: None)
    runner.thread.join(3)
    assert runner.status == 'Finished'


def test_window_shows_running_then_finished(application):
    release = threading.Event()
    runner = application.runner
    runner.stage_name = 'Test job'
    runner.start(lambda r: release.wait(3))
    application._update_job_status()
    assert 'Running' in application.job_status.get()
    assert 'Elapsed' in application.job_status.get()
    assert application._busy_animation
    release.set()
    runner.thread.join(3)
    application._update_job_status()
    assert 'Finished' in application.job_status.get()
    assert not application._busy_animation
