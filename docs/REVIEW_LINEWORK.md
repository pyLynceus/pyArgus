# Review mode and reference linework

Choose the **Review** tab to maximize viewing space. **Review pane** toggles
the lower controls. Choose **Process** for processing tasks or **Deliver** for
existing outputs and exports. The current mode and pane save with the workspace.
See [workspace layout](WORKSPACE_LAYOUT.md).

## Navigation

- Wheel zoom follows the cursor rather than the center of the window.
- **Previous view** restores camera position, rotation, pan and zoom from the
  session history (up to 40 views; not a saved bookmark). A new cloud load clears it.
- **Set orbit center**, then click a displayed cloud point. The image stays
  in place, but subsequent rotation pivots around that point. Esc cancels.
  Disable Anaglyph to pick the pivot, then re-enable it for inspection.
- **Fit layer** frames the selected DXF layer; Previous view returns.

## Import DXF

Choose **Layers → Add data → Reference linework (DXF)** after loading the cloud.
Confirm the DXF uses the cloud's XY frame, linear units and, for 3D, height
datum. DXF usually cannot establish these by itself. The importer does not
reproject, rescale, translate or infer a vertical datum. Known INSUNITS values
must match the cloud's units; unsupported declared units are refused. Unitless
DXF requires your explicit compatibility declaration.

Supported model-space geometry: LINE, POINT, straight 3D POLYLINE, 2D
POLYLINE/LWPOLYLINE (including bulges), ARC, CIRCLE, ELLIPSE and SPLINE.
Curves are flattened with the entered chord tolerance in map units (default
0.1). Blocks/INSERT, annotation and other unsupported entities are counted and
reported, not silently expanded. Explode blocks before export for this version.
Files with no supported geometry are refused. Each import is limited to
200,000 vertices; workspace linework is limited to one million.

Choose **2D plan only** for geometry without usable heights and enter a display
Z. This is explicitly labeled and is not measured height or terrain draping.
Supplied XYZ mode refuses all-zero-Z entities as ambiguous; separate mixed
2D/3D files before import. Original DXF files are never edited.

Import runs on the viewer worker; **Stop loading** cancels conversion. Initial
DXF parsing may finish before cancellation can be observed. Results appear as
layers with original names. Entity colors are normalized to the DXF layer
color; individual per-entity overrides are not preserved.

## Inspect layers

Select a DXF under **Layers → Linework**. Right-click for visibility, fit,
sections or style controls. In the lower Linework pane,
Show/hide, Isolate, Show all, Fit layer, Color and line thickness (1–6 pixels)
apply to the selected layer. Double-click toggles visibility. **Always on top**
shows linework over the cloud. Uncheck it and Apply style for depth testing
against the displayed cloud points. This works in normal and anaglyph views;
stereo uses grayscale. It is not mesh occlusion: lines can show through gaps in
the point sample. Classification and feature-drawing overlays retain their
existing behavior. Layers in a different CRS from the viewer are not drawn.

Geometry, layer styles, coordinate declaration and source metadata identity
save in workspace JSON. On reopening, changed/missing DXF sources hide their
saved layers and produce a notice. Reimport for current geometry. Source checks
use file size and mtime, not cryptographic identity. The saved geometry can be
shown manually for historical reference.

The existing feature editor is under **Tools → Optional feature tracing**. It is optional;
reference imports do not alter terrain breaklines or classification. Optional automatic local refinement is delivered; see [Auto detail](AUTO_DETAIL.md).
Sections stepping along imported lines are available through **Sections…**;
see [Line-following sections](LINE_FOLLOWING_SECTIONS.md). Saved view presets
and issue markers remain future work.
