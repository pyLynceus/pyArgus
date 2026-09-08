"""Classification: Phases 3 and 5, not yet implemented.

Ground first (Phase 3): PDAL's filters.smrf and filters.csf driven
through JSON pipelines, with per-terrain parameter presets tuned
against the reference dataset. Above-ground later (Phase 5): a random
forest on geometric features (height above ground, eigenvalue shape
descriptors, return ratios) before any deep model is considered --
explainable beats fashionable until it plateaus.
"""
