"""Time-dependent per-strip corrections: the drift model.

A constant per-strip offset cannot fix GNSS wander WITHIN a line --
the bad-sky days where the trajectory breathes over a flight line.
The model here is TerraMatch's "fluctuating" idea kept deliberately
plain: per strip, a piecewise-linear VERTICAL correction in time,
with nodes every ``spacing`` seconds. Each patch observation votes
for the two nodes bracketing its moment; stiffness rows tie
neighboring nodes so a node that no patch observes (line ends, gaps)
follows its neighbors instead of wandering off.

Vertical only, on purpose: horizontal drift is weakly observable from
surface patches and folding it in mostly buys noise. A constant
offset is the special case of equal nodes, so drift mode replaces the
constant-offset unknowns entirely.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class DriftModel:
    """Per-strip node times and vertical corrections."""
    node_times: list      # per strip: (K_s,) seconds
    values: list          # per strip: (K_s,) map units (z)

    def offset_at(self, strip, times):
        """(N, 3) correction vectors for one strip at ``times``."""
        times = np.asarray(times, dtype=float)
        dz = np.interp(times, self.node_times[strip], self.values[strip])
        out = np.zeros((times.size, 3))
        out[:, 2] = dz
        return out

    def span(self, strip):
        """(min, max) correction over the strip -- the headline number."""
        v = self.values[strip]
        return float(v.min()), float(v.max())


def nodes_for(times, spacing):
    """Node times covering a strip's span, one node at each end and no
    gap wider than ``spacing``. A strip shorter than one spacing still
    gets two nodes (a linear ramp -- the minimum that can drift)."""
    if spacing <= 0:
        raise ValueError(f"drift node spacing must be positive seconds, "
                         f"got {spacing}")
    times = np.asarray(times, dtype=float)
    t0, t1 = float(times.min()), float(times.max())
    if t1 <= t0:
        return np.array([t0, t0 + 1.0])
    segments = max(1, int(np.ceil((t1 - t0) / spacing)))
    return np.linspace(t0, t1, segments + 1)


def bracket(node_times, t):
    """(index, weight) such that the correction at ``t`` is
    (1 - w) * v[index] + w * v[index + 1]."""
    t = np.asarray(t, dtype=float)
    idx = np.clip(np.searchsorted(node_times, t) - 1, 0,
                  len(node_times) - 2)
    step = node_times[idx + 1] - node_times[idx]
    w = np.clip((t - node_times[idx]) / step, 0.0, 1.0)
    return idx, w
