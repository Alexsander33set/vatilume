import math


class Periodic:
    """Schedule slower work against planned cycle deadlines, not completion time.

    Reading temperature at t=0.003 must not move the next scheduled read to
    t=30.003 and accidentally skip a main cycle planned for t=30.000.
    """

    def __init__(self):
        self.next_due: float | None = None

    def due(self, planned_cycle: float, period: float) -> bool:
        if self.next_due is not None and planned_cycle + 1e-6 < self.next_due:
            return False
        baseline = planned_cycle if self.next_due is None else self.next_due
        periods = max(1, math.floor((planned_cycle - baseline) / period) + 1)
        self.next_due = baseline + periods * period
        return True

