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
    for stage_class, row, expected in [
            (gui.ClassifyStage, 0, gui.CLOUD_TYPES),
            (gui.DtmStage, 1, gui.SURFACE_TYPES),
            (gui.ContourStage, 1, gui.CONTOUR_TYPES),
            (gui.AlignStage, 2, gui.CLOUD_TYPES),
            (gui.ColorizeStage, 4, gui.CLOUD_TYPES)]:
        browse(_stage_of(application, stage_class), row)
        assert calls[-1]['filetypes'] == expected, stage_class.__name__
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


def test_every_save_dialog_anywhere_declares_its_formats(application,
                                                         monkeypatch):
    """DISCOVER the save dialogs instead of listing them. The list in
    the test above is hand-written, so it silently fell behind when
    Colorize was added; this walks every browse button in every stage
    and demands that any that opens a SAVE dialog names its formats
    and a default extension."""
    saves = []
    monkeypatch.setattr(gui.filedialog, 'asksaveasfilename',
                        lambda **kw: saves.append(kw) or '')
    monkeypatch.setattr(gui.filedialog, 'askopenfilename',
                        lambda **kw: '')
    monkeypatch.setattr(gui.filedialog, 'askdirectory', lambda **kw: '')
    for stage in application.stages:
        frame = application.notebook.nametowidget(
            application.notebook.tabs()[application.stages.index(stage)])
        for container in frame.winfo_children():
            for child in container.winfo_children():
                if child.winfo_class() == 'TButton':
                    child.invoke()
    assert saves, 'no save dialog found at all -- the walk is broken'
    for kw in saves:
        assert kw.get('filetypes'), kw
        assert kw.get('defaultextension'), kw
        assert kw['defaultextension'] == kw['filetypes'][0][1][1:], kw
