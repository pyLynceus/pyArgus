"""Surfaces and deliverables.

``surfaces.dtm`` grids ground returns into a DTM (and all returns into
a DSM) and writes ESRI ASCII rasters -- plain text, GIS-ready, no
GDAL. ``surfaces.tin`` triangulates with soft breaklines (densified
vertices, honestly documented as not a constrained Delaunay).
``surfaces.contours`` runs marching squares over either surface and
joins the segments into lines; ``formats.dxf`` and ``formats.geojson``
carry them out the door. Deliverable formats mirror what LP360
produces today.
"""
