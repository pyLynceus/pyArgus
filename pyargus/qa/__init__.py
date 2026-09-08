"""Strip QA: the referee for everything downstream.

Density and coverage, strip-overlap dZ, and checkpoint accuracy per the
ASPRS standard. Runs before alignment to measure the problem and after
to prove the fix; an alignment result that these numbers do not confirm
did not happen.
"""
