from tests.test_gui import root, application
from pyargus import gui


def test_every_save_dialog_has_formats_and_extension(application, monkeypatch):
    calls = []
    monkeypatch.setattr(gui.filedialog, 'asksaveasfilename', lambda **kw: calls.append(kw) or '')
    def browse(stage, row):
        frame = application.notebook.nametowidget(application.notebook.tabs()[application.stages.index(stage)])
        for container in frame.winfo_children():
            for child in container.winfo_children():
                if child.winfo_class() == 'TButton' and int(child.grid_info()['row']) == row:
                    child.invoke()
                    return
        raise AssertionError('browse button missing')
    for index, row, expected in [(1,0,gui.CLOUD_TYPES),(2,1,gui.SURFACE_TYPES),
                                 (3,1,gui.CONTOUR_TYPES),(4,2,gui.CLOUD_TYPES)]:
        browse(application.stages[index],row)
        assert calls[-1]['filetypes'] == expected
        assert calls[-1]['defaultextension'] == expected[0][1][1:]
    stage = _stage_of(application, gui.AboveStage)
    stage.mode.set('Train model')
    browse(stage,3)
    assert calls[-1]['filetypes'] == gui.MODEL_TYPES
    stage.mode.set('Apply model')
    browse(stage,3)
    assert calls[-1]['filetypes'] == gui.CLOUD_TYPES


def _stage_of(application, stage_class):
    """Pick a stage BY TYPE. Positional lookup breaks the moment a
    stage is added, which is how adding Colorize broke these."""
    for stage in application.stages:
        if isinstance(stage, stage_class):
            return stage
    raise AssertionError(f'no {stage_class.__name__} registered')
