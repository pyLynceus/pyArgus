# SH151 — Claude Code handoff, 2026-09-11

## Objective and authorization

Bryon wants the fixed-wing SH151 lidar to agree better with the supplied imagery/AT. He cannot currently access a stereo workstation and the client is unavailable. Do not send him back to manual stereo collection as the only next step. He authorized a direct image-to-lidar pilot, with AT initially fixed, and requested this handoff because Codex usage is running low.

Current status: two small direct-registration diagnostics have run; no defensible correction has been released, no corrected LAS exists, and COLMAP has NOT run. A known-pose COLMAP crop model is prepared. Continue the work rather than describing preparation as a completed correction.

## Workspace and isolation

- Repo: `C:/Users/bjordan/OneDrive - Platinum Geomatics/Desktop/pyArgus`
- Python: repo `.venv/Scripts/python.exe` (Python 3.11).
- Transfer assets: repo `reference/reports/sh151_claude_transfer/`.
- Original staging workspace: `C:/Users/bjordan/Desktop/ClaudeCodeFAA`.
- Source data: `Z:/Users/BJordan/SH 151`. Keep source LAS and imagery read-only. Write any eventual corrected LAS as new copies.
- Do not touch pyLynceus. Read repo CLAUDE.md and HANDOFF.md.
- Existing unrelated uncommitted changes were present at handoff: HANDOFF.md, README.md, pyargus/cli.py, pyargus/gui.py, reference/RESULTS.md, tests/test_desktop_above.py, tests/test_dialog_types.py, tests/test_gui.py; untracked pyargus/imagery/job.py. Do not revert, overwrite or sweep these into a commit. This handoff is separate to avoid racing HANDOFF.md.

## What to do next

1. Install/locate COLMAP or pycolmap in an isolated environment. Neither was available on the checked PATH / pyArgus environment. No installation was attempted this turn. OpenCV, tifffile, scipy, numpy, matplotlib and ezdxf are available in pyArgus's venv.
2. Load `sh151_colmap_pilot/model` and inspect the four cropped images in `sh151_colmap_pilot/images`. Validate text model import, camera/image IDs and local coordinate origin. This is a PREPARED import, not a completed independent check.
3. Extract/match features and triangulate with camera poses AND intrinsics fixed. Ensure database image/camera IDs agree with the supplied model; disable refinement explicitly using the installed version's API/options. Do not assume defaults preserve the supplied AT.
4. Check pixel centers carefully. COLMAP uses half-integer pixel centers; OpenCV uses integers. The supplied model uses geometric image-center principal point (5655,8655), subtracting crop origins. Its OpenCV equivalent is (5654.5,8654.5). Prior prototypes used (5655,8655) directly in OpenCV. A -0.5-pixel sensitivity run did not remove the pair disagreement, but the convention must still be correct.
5. Investigate why pair 1041/1042 and pair 2017/2018 disagree. Keep the original AT unchanged initially. Check interior orientation, rotations, camera-model assumptions, local versus global coordinate conventions and any missing curvature/refraction settings. Do not assume the AT is bad, nor that our projection is correct because a round-trip test passes.
6. Once geometry is supported, gather larger *reviewed pavement* neighborhoods (existing caches cover only about 3 ft around marks), then fit bounded image-driven Z offset/tilt while preserving lidar detail. Test horizontal displacement only with enough slopes and distinct image features to make it observable. Hold out image views/patches and survey checks. Do not let a flexible camera-and-cloud solve agree by drifting away from control.
7. Reject weak texture, out-of-image views, boundary optima, inconsistent views, vegetation and discontinuities. NCC approaching 1 is NOT proof of correct height. Demonstrate improvement on withheld data and maintained strip overlap before any LAS export.

## Direct-registration diagnostic just run

Script: `sh151_direct_pilot.py` (standalone reference experiment, not application code).
It reads repo `reference/reports/sh151_cache/*.npz`, robustly fits smooth low-slope local planes by strip, requires at least two strips, samples a 2.8-ft square within the combined lidar XY convex hull, and searches Z shifts -1 to +1 ft at 0.025-ft increments. For each shift it projects the plane into cropped original images and evaluates patch-wide normalized cross correlation. It does not solve XY, tilt or camera parameters. Cache is unclassified: smoothness alone does not establish ground. The diagnostic never declares a correction accepted.

Results with original OpenCV principal point convention:

| Zone | Anchor | Pair preferences | Finding |
|---|---|---|---|
| A | 200205, positive lidar miss | No result | A required view was outside the image. Original selection 1041/1042/1043 was retried as 1042/1043/2018; still insufficient coverage. Select views from actual projections, not filenames alone. |
| B | 80809, negative lidar miss | 3030/3031: +0.100 ft (NCC .962); 3031/3032: +0.300 ft (NCC .954) | 0.20-ft disagreement; pairs SHARE a camera, not independent validation. |
| C | 200104, near-zero lidar miss | 1041/1042: +0.400 ft (NCC .992); 2017/2018: -0.350 ft (NCC .971) | 0.75-ft disagreement in disjoint camera pairs. Do not apply either shift. |

With OpenCV principal point shifted -0.5 pixels: B remains +0.100/+0.300; C becomes +0.525/-0.250. This does not resolve the discrepancy. These small, potentially weak-texture patches are diagnostics, not regional surfaces.

Detailed curves, per-strip plane statistics and image crops are in `sh151_direct_pilot/` and `sh151_direct_pilot_pixelminus05/`. Source cache freshness against LAS was NOT revalidated in this turn; recheck before release work.

Run from the transfer folder in PowerShell:

```powershell
$py = 'C:/Users/bjordan/OneDrive - Platinum Geomatics/Desktop/pyArgus/.venv/Scripts/python.exe'
& $py ./sh151_direct_pilot.py
& $py ./sh151_direct_pilot.py --pixel-shift -0.5
& $py ./prepare_colmap_pilot.py
```

The direct script and COLMAP preparation script locate transferred assets relative to themselves. Some older scripts retain absolute staging paths; inspect before rerunning. The repo path inside the direct script is explicit and must be updated if relocating to another machine.

## Data and camera geometry

- `IMAGES/0001.tif` through `0046.tif`: uncompressed 11310 x 17310 RGB, about 587 MB/frame. Use `tifffile.memmap(..., mode='r')` for bounded ROIs. Never load all 46 images at once.
- `AT/VRAT_FINAL/8242026BundleReportExtOri.txt`: 42 final EO records, XYZ and omega/phi/kappa degrees. All 42 mapped convincingly to renamed frames using TIFF UTM center footprints transformed to State Plane and one-to-one assignment. Images 0019,0020,0021,0046 have no final EO in this file; exclude them unless orientations are found.
- Mapping/provenance: `sh151_stereo/frame_mapping.json`. TIFF approximate georeferencing is EPSG:32614; final EO and LAS use NAD83(2011)/Oklahoma North ftUS (EPSG:6553). Do not treat the TIFF worldfile as an orthophoto transform.
- Final camera `UC-F-1-90513022.cam`: focal 100.5 mm, physical format 67.86 x 103.86 mm; 6 micron pixels -> focal 16750 pixels. Principal point offsets zero; listed distortion coefficients zero. Different fixed-wing sensor from the UAS projects.
- Provisional world-to-photo rotation: scipy `Rotation.from_euler('xyz', -opk, degrees=True)`. Photo +x right, +y up, viewing toward -z. Do not borrow the TrueView rotation convention from pyargus/core.
- COLMAP world-to-camera conversion: `diag(1,-1,-1) @ R_photo`; quaternion order w,x,y,z; translation `-R @ (camera_center - local_origin)`. Local origin in `coordinate_origin.json`; add it to reconstructed XYZ to recover State Plane ftUS. Camera-center and projection round trips passed numerical assertions, NOT vendor-geometry validation.
- Calibration PDFs are in IMAGES. Relevant axis-diagram renders are included in sh151_stereo. Original `.vmf` / per-image interior-orientation files were not found anywhere in the supplied SH151 folder.
- Source lidar: 22 LAS, 917,372,069 points; `LIDAR/TERRAFLIGHT/LAS`. LAS1.4 format6, .001 coordinate scales, horizontal EPSG6553 + NAVD88 ftUS EPSG6360. Near controls, points are class1/unclassified; do not filter only class2.

## Prior experiments and cautions

1. Sparse AT fit: `reference/reports/sh151_at_fit/` in repo. 53 explicit Bundle Coord XYZ values; 29 screened targets. Baseline RMS .131796 ft; fitted .120826; LOO .125847; spatial CV .128846. Candidate correction range -.049223 to +.030255 ft: marginal, never applied. `pyargus/at_fit.py` already has guarded new-file Z-only export and tests; do not mistake model existence for released LAS.
2. 60x60-ft custom stereo surface near 200104: `sh151_stereo/`. 0.25-ft grid, Z search745–805, no lidar used for that reconstruction. Pair median disagreement .465 ft, gross mismatches remain; experimental ASC/XYZ are NOT approved surfaces. Four-view feature check found71 cycle-consistent tracks,9 in manually selected pavement,0 passing .15-ft pair-Z and .25-pixel maximum reprojection screening. Pavement median discrepancy .413 ft. Stable local-coordinate DLT fixed an earlier numerical conditioning problem; initial absolute-coordinate DLT tests failed and were replaced.
3. Manual collection package: repo `reference/reports/sh151_profile_pilot/`, copied into transfer. 45 2D navigation guides,18 withheld, no elevations. User cannot currently use stereo; do not treat this as the active solution.
4. `SURVEY/rtesults.txt` has65 points/103 stereo residual measurements, NOT direct measured XYZ; resZ sign is undocumented. Do not manufacture elevations by adding/subtracting those residuals. Use explicit Bundle Coord where appropriate, or obtain actual readings later.
5. Earlier `reference/sh151_cross_sensor.py` narrative overclaims independence and a vendor/LCP2 cause. Those are NOT established. AT and survey may share controls. Reusing control in a fit is not independent validation.

## Validation and preservation

This turn changed no pyargus application modules. Ran real bounded diagnostics and their pixel sensitivity repeat; prepared COLMAP model with numerical conversion checks. No full pytest/acceptance battery was rerun this turn. Earlier full-suite count305 is historical, not a statement about the current dirty checkout. Follow CLAUDE.md test requirements for future substantive module changes.

Transfer contains the previous scripts, small image crops, reports, diagnostics and navigation package. It does NOT contain full-resolution source TIFFs or the large LAS; they remain on Z:. The existing repo caches are still needed for direct-pilot reruns. No email/messages to client were sent; user has not authorized sending them.

Primary implementation references:
- https://colmap.github.io/faq.html — known-pose reconstruction, fixed intrinsics, half-pixel conventions; database IDs must agree with model IDs.
- https://colmap.github.io/format.html — quaternion/translation and model format.

Success means demonstrably better agreement with held-out image evidence and survey checks, with strip consistency preserved. If that cannot yet be demonstrated, retain diagnostics and explain the unresolved geometry; do not force a cloud warp to one convenient pair.
