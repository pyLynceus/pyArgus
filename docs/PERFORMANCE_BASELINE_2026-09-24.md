# Workflow performance baseline methodology

The project-specific September 24 measurements are retained privately and
are not part of this public source backup. Do not infer timing or memory
performance for a new dataset from those records.

Use reference.profile_workflow as described in PERFORMANCE_PROFILING.md.
Record input identities, parameter units, repetitions, cache state, file access,
computation, redraw, whole-process memory and output parity separately.
Keep source datasets read-only and benchmark outputs separate from accepted
processing inputs. State missing or interrupted measurements explicitly.

For publicly documented synthetic GPU/tile measurements and their limits,
see ACCELERATION.md. Optional spatial-access methodology is documented in
SECTION_CACHE_EXPERIMENT.md.
