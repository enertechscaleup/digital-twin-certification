"""The escalation protocol: the rules operation runs against.

These values are recorded in the evidence ledger at verification time, so the
rules any later status change was judged by are themselves part of the record.
Defaults follow the design doc's prototype parameters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EscalationProtocol:
    # Flagged after this many consecutive out-of-tolerance readings on one channel
    # (or consecutive out-of-envelope readings on one input).
    flag_after_consecutive: int = 3
    # Nullified after this many consecutive readings beyond tolerance x multiplier.
    nullify_after_consecutive: int = 10
    nullify_tolerance_multiplier: float = 2.0
    # Data-quality rule: a jump larger than this (percent, versus the last
    # accepted reading on the same channel) is treated as a sensor spike.
    spike_jump_pct: float = 20.0
    # Data-quality rule: a sensor is stuck once it reports the exact same value
    # this many times in a row. (A single repeat happens by chance on healthy
    # sensors with finite resolution, so one repeat is not enough.)
    stuck_after_identical: int = 3
    # Envelope violations can move status to Flagged, never to Nullified:
    # the twin was used outside where it was tested, not shown to be wrong.
    envelope_can_nullify: bool = False
    # Recalibration (Real2Sim): flagged-period data is split BY TIME. The earlier
    # part is released to the twin's owner; the later part is held out and used
    # only by the platform to validate the recalibrated twin.
    holdout_fraction: float = 0.3
    min_holdout_ticks: int = 5

    def to_dict(self) -> dict:
        return asdict(self)
