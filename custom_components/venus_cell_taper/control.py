"""Pure voltage controller; no Home Assistant dependencies."""

from collections import deque
from dataclasses import dataclass, field
from math import ceil
from statistics import median

from .const import LIMIT, TARGET

DEFAULT_MIN_CHARGE_W = 40  # At 40 W AC, this battery delivered 8–11 W DC.


def lower_step(watts: int, minimum: int = DEFAULT_MIN_CHARGE_W) -> int:
    if watts > 200:
        return max(200, watts - 100)
    if watts > 50:
        return max(50, watts - 50)
    return max(minimum, watts - 10)


@dataclass
class VoltageController:
    """Discrete PD-like control with a short filtered voltage trend.

    No integral term: voltage under load is not a direct SOC measurement.
    Each control change requires at least 30 seconds of settling. The caller
    separately checks the unfiltered safety limit on every new sample.
    """

    power: int = 0
    min_charge_w: int = DEFAULT_MIN_CHARGE_W
    samples: deque = field(default_factory=lambda: deque(maxlen=7))
    last_change: float = 0

    def start(self, voltage: float, now: float) -> int:
        self.samples.clear()
        self.last_change = now
        self.power = 500 if voltage < 3.45 else 200 if voltage < TARGET else 50
        return self.power

    def update(self, voltage: float, now: float) -> int | None:
        """Return a changed setpoint, otherwise None. Raise on hard limit."""
        if voltage >= LIMIT:
            raise ValueError("cell voltage limit")
        if self.power <= self.min_charge_w and voltage >= 3.52:
            raise ValueError("minimum charging power cannot hold cell voltage")
        self.samples.append((now, voltage))
        if now - self.last_change < 30 or len(self.samples) < 4:
            return None

        # Use medians across two short windows. dV/dt is mV/minute.
        older = list(self.samples)[:3]
        recent = list(self.samples)[-3:]
        elapsed = recent[1][0] - older[1][0]
        if elapsed <= 0:
            return None
        slope = (median(v for _, v in recent) - median(v for _, v in older)) * 60000 / elapsed
        error_mv = (voltage - TARGET) * 1000

        # P term: voltage above target. D term: rising rapidly near the knee.
        pressure = max(0.0, error_mv) + max(0.0, slope) * 2
        if (voltage >= 3.45 and pressure >= 2) or voltage >= 3.50:
            # Convert the P+D pressure to 1–3 rungs of the agreed power ladder.
            # A large overshoot must not wait through several 30-second cycles.
            new = self.power
            for _ in range(min(3, max(1, ceil((pressure - 1e-8) / 10)))):
                new = lower_step(new, self.min_charge_w)
        elif self.power < 50 and voltage < 3.475 and slope < -1 and now - self.last_change >= 90:
            new = min(50, self.power + 10)
        else:
            new = self.power
        if new != self.power:
            self.power = new
            self.last_change = now
            self.samples.clear()
            self.samples.append((now, voltage))
            return new
        return None
