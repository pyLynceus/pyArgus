"""Classification.

Ground (Phase 3) is real: ``classify.ground.smrf`` is an in-core SMRF
implementation (see its docstring for why it is not a PDAL dependency),
scored against Summerville's delivered classification by
``reference/summerville_ground.py``.

Above-ground (Phase 5) is still a plan: a random forest on geometric
features (height above ground, eigenvalue shape descriptors, return
ratios) before any deep model is considered -- explainable beats
fashionable until it plateaus.
"""
