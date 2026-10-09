# Cross-sections along imported linework

1. Open the clouds you want to review and import their reference DXF.
2. Select a DXF layer under **Layers → Linework** and right-click for sections.
   Alternatively choose **Sections → Follow imported line** in the viewer toolbar.
   Section controls open in the lower **Cross-section** pane.
3. Choose one entity from the list. Labels show layer, entity number, XY length
   and source filename. Each entity is independent; disconnected lines are not
   joined. Points and vertical-only lines are excluded.
4. Choose **Section source**: one cloud or **Compare all loaded clouds**.
5. Set **Station**, **Across-line span**, **Full width**, and **Spacing** in the
   cloud's map units. Span is the entire length of the cross-section across the
   route. Full width is the thickness of the extraction corridor along it.
6. Click **Go / extract**. **Next** and **Previous** move by Spacing and extract.
   With focus on the 3D canvas or profile, **Alt+Right / Alt+Left** do the same.
   Keyboard stepping only acts while this section-review tab and controls are
   visible; typing in entry fields keeps normal editing behavior.

Opening a route enlarges the section pane. Drag the horizontal divider to
adjust it further. The camera position is not reset. The main viewer shows the
usual yellow A/B corridor. Section extraction works with anaglyph left enabled;
manual point picking still requires normal viewing.

## Geometry and review semantics

Station zero is the entity's first vertex. Stationing measures cumulative XY
length, ignoring linework elevations. Curves use the imported DXF flattening
and its tolerance. At an internal vertex, the section uses the bisector of the
incoming/outgoing directions. A reversal has no unique normal and is refused
at that vertex; choose a nearby station instead. Consecutive duplicate XY
vertices are removed for stationing, including vertical-only edges.

A is left and B right when looking forward along the line. The profile's X axis
remains distance from A; the route station is displayed separately above the
controls. Both 2D reference lines at display elevation and supplied 3D lines
can guide sections: profile elevations always come from LAS points, never the
DXF's display elevation. No reprojection, cloud edits or accuracy certification
is performed. Source DXF metadata and CRS are checked before extraction.

Stepping stops at either endpoint. A final shorter step reaches the endpoint;
closed routes do not wrap. Settings and selected entity save with the workspace,
but restoring does not start extraction. Click Go after choosing the loaded
section source. Removed or changed route sources are refused. Saved route
station/settings reflect the last Go/step, not unsubmitted entry edits.

Busy clicks do not queue scans. Stop cancels the current extraction; Go retries.
Stop following returns to manual A/B controls. Picking a manual A/B endpoint
also exits route mode. Manual extraction with changed endpoints exits route
mode. Cache use and full-scan fallback follow the existing section policy;
Build section cache (or Build view cache) avoids repeated source scans. Display
refinement with unchanged cloud inputs no longer clears a completed section.

## Validation

Geometry tests cover XY stationing, left/right orientation, bends, reversed and
closed routes, duplicate/vertical vertices and invalid stations. GUI tests cover
real synthetic-LAS extraction, explicit source selection, endpoint clamping,
busy/keyboard behavior, route state capture/restore, changed or removed DXFs,
and preservation of sections across viewer sample refreshes. The packaged
smoke test also activates a DXF route and checks its cross-section geometry.
