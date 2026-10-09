# Anaglyph point-cloud viewing

Load a cloud in the main viewer and enable **Anaglyph** beside the color
selector. Use red/cyan glasses (red lens on the left by default). **Swap eyes**
reverses the channels. Start with low **Depth**, then adjust to taste; 0 makes
the eye images coincide, and the range is 0–6 degrees, default 2.
Orbit, pan, zoom, Fit and the standard views still work. An oblique view can
help reveal relief. The camera center is the zero-disparity plane.

Stereo is grayscale, derived from the current color mode's luminance, so
classification colors are not preserved. Return to normal viewing for color
interpretation. Clouds have independent per-eye depth buffers. Features,
trajectories, extra overlays and the section corridor render for both eyes,
but overlays remain drawn on top rather than occluded by the cloud. The
section corridor uses the same camera-center elevation as the normal viewer.

Turn Anaglyph off for Shift-click picking/tracing, Ctrl-click section endpoints
then turn it back on to inspect the result. These picking actions are
explicitly refused in stereo; there is no floating stereo measurement mark.
Existing section plots remain ordinary 2D station/elevation plots. The three
stereo settings save with the workspace's viewer state; older workspaces
restore normal viewing. The original point coordinates remain unchanged.

## Rendering

The existing rotation maps XYZ into camera coordinates (u,v,d), with positive
depth facing the viewer. Parallel orthographic eye views use horizontal shear:

    u_left  = u + tan(depth_angle / 2) * d
    u_right = u - tan(depth_angle / 2) * d
    v_left = v_right = v

Both use the same scale and pan, so the images have no vertical disparity.
The left intensity becomes red and the right intensity becomes green/blue.
Swapping eyes swaps those assignments. This is synthetic stereo for cloud
inspection; it is not calibrated photographic stereo or a depth measurement.

No production-data accuracy claim is made. Automated tests cover geometry,
channel assignment, independent-eye occlusion, overlays and GUI action guards;
operator assessment with glasses is still needed. CPU stereo rendering costs
more than normal rendering and uses the same bounded display sample.

Manual and automatic local refinement now work with Anaglyph enabled and cover
both eye viewports. See [Auto detail](AUTO_DETAIL.md).
