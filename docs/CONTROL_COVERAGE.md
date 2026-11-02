# Control / PID coverage audit

Every new project or LP360 alignment includes this read-only audit in
`report.html`, before the flight-line agreement tables. It screens the original
class-2 ground geometry. It never adds observations to the alignment solve or
approves its output.

## Setup

Open **Tools > Alignment report settings**, then **Control coverage**. Add an
optional reference control/PID CSV and choose its explicit `pnez` or `penz`
coordinate order. These audit-only PIDs do not become fitting controls. LP360
jobs include their selected project Control CSV automatically when this field
is blank, including when separate independent asphalt checks are selected.
Use **Survey checks** for those independent checks and their surface declaration.

The initial editable planning thresholds are three distinct supported control
sites per analysis flight and a largest projected gap of 1,000 US survey feet.
They are pyArgus screening defaults, not prescribed GDOT/ASPRS minimums. Length
thresholds convert through the declared cloud units, including both foot types.
The existing report neighborhood radius and minimum returns also govern support.
Settings are saved with projects and workspaces.

## Review

The equal-scale north-up map has role and analysis-flight filters. Select a mark
on the map or in its table to inspect per-flight return counts and support
rejection reasons. Purple identifies supplied fitting controls, amber reference
PIDs, blue declared independent checks, and gray checks excluded because their
neighborhood overlaps fitting control. Unsupported marks remain visible.

The per-flight table retains the analysis ID, original LAS line ID, trajectory
and contributing source files. Tiled flights stay unified, and reused LAS line
IDs on different trajectories stay separate. Flights with no supported survey
locations remain present. Supplied records, supported records, rejected records
and distinct supported XY sites are retained separately; coincident locations
cannot manufacture additional geometric sites. A CSV retained both as LP360
reference and report checks is coalesced by identical role, ID and coordinates.

Screening uses supplied fitting-control sites if an actual fitting-control array
was passed to the solve; otherwise it uses supported reference locations.
Independent and excluded checks never satisfy control thresholds. Conflicting
reference/control and independent declarations within 1 mm retain both records
but receive neither control-site credit nor independent accuracy credit until
the roles are resolved. With no fitting
or reference survey, control coverage is explicitly unassessed.

Warnings flag too few sites, projected gaps including unsupported ends, sites
spanning less than half the longitudinal extent, sites spanning less than a
quarter of its width, and nearly collinear geometry after normalizing by both
extent dimensions. These are prompts for review, not proof that a solver is
under-determined or that additional field observations are always necessary.

## Geometry and evidence limits

Local support uses the report's circular neighborhood, OLS plane, conditioning,
and surveyed-XY convex-hull gates. These differ from the solver's square/SVD
control-patch gates. The audit identifies **supplied fitting controls with audit
support**, not the exact marks used in the last solver iteration. No solver
observation membership is inferred.

Map outlines are oriented bounding rectangles of finite class-2 returns. They
are not exact flight footprints, occupied-cell coverage, or proof of data inside
holes. Longitudinal gaps are straight principal-axis projections, including the
leading and trailing ends; they are not distance along a curved flight path or
elapsed navigation time. Curved routes, disconnected components, classification
errors and ground outliers need additional review.

A valid local plane does not establish survey uncertainty, physical surface
identity, or horizontal recovery of a stripe corner/manhole center. Existing
independence and material declarations retain their original limitations.

## Retained products

Each new alignment folder includes `control_coverage.json`,
`control_coverage_flights.csv`, `control_coverage_points.csv` and a static
`control_coverage.svg` map, plus the interactive embedded HTML section.
The point CSV includes every retained mark/analysis-flight combination, even
when no local ground returns exist. Geometry is captured before corrected LAS
export mutates the analysis arrays. The audit-only source is hashed, retained as
`report_controls.csv` and registered in the job record. Source changes during
processing refuse publication. Existing reports and input clouds are preserved.
