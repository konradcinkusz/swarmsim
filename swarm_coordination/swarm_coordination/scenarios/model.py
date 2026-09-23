"""What a scenario run produces: a trace of what happened, and a verdict on it.

The trace is the truth of the simulated world at every step (where each drone really
was, what its autopilot was doing) next to what the system under test *reported* (its
swarm state). Assertions read the trace and nothing else, so every violation carries
the time it was measured at — not a timestamp a scenario author typed in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..trajectory import Vector3


@dataclass(frozen=True)
class DroneSample:
    drone_id: str
    position: Vector3  # truth, world frame
    armed: bool
    mode: str
    battery_pct: float
    airborne: bool


@dataclass(frozen=True)
class Frame:
    t_s: float
    drones: tuple[DroneSample, ...]
    reported_mission_id: str | None  # what the system under test said, not the truth
    reported_complete: bool


@dataclass
class Trace:
    scenario: str
    sut: str
    seed: int
    dt_s: float
    homes: dict[str, Vector3]
    missions: list[tuple[float, str, dict]] = field(default_factory=list)  # (t, id, payload)
    events: list[tuple[float, str]] = field(default_factory=list)  # (t, what happened)
    frames: list[Frame] = field(default_factory=list)

    def as_dict(self) -> dict:
        """JSON-ready, columnar per drone so a long run stays readable and small."""
        drone_ids = list(self.homes)
        columns: dict[str, dict[str, list]] = {
            d: {"x": [], "y": [], "z": [], "armed": [], "mode": [], "battery_pct": []}
            for d in drone_ids
        }
        for frame in self.frames:
            for sample in frame.drones:
                c = columns[sample.drone_id]
                c["x"].append(round(sample.position.x, 3))
                c["y"].append(round(sample.position.y, 3))
                c["z"].append(round(sample.position.z, 3))
                c["armed"].append(sample.armed)
                c["mode"].append(sample.mode)
                c["battery_pct"].append(round(sample.battery_pct, 2))
        return {
            "scenario": self.scenario,
            "sut": self.sut,
            "seed": self.seed,
            "dt_s": self.dt_s,
            "t_s": [round(f.t_s, 3) for f in self.frames],
            "homes": {d: [h.x, h.y, h.z] for d, h in self.homes.items()},
            "missions": [{"t_s": t, "id": i, "payload": p} for t, i, p in self.missions],
            "events": [{"t_s": t, "event": e} for t, e in self.events],
            "reported": {
                "mission_id": [f.reported_mission_id for f in self.frames],
                "complete": [f.reported_complete for f in self.frames],
            },
            "drones": columns,
        }


@dataclass(frozen=True)
class Violation:
    """One concrete, reportable fact about a failure, measured from the trace."""

    assertion: str
    drone_ids: tuple[str, ...]
    timestamp_s: float | None
    measured_value: float | None
    threshold: float | None
    description: str


@dataclass(frozen=True)
class AssertionOutcome:
    assertion: str  # e.g. "min_separation"
    passed: bool
    measured: float | None  # the headline number (e.g. the smallest separation seen)
    unit: str
    violations: tuple[Violation, ...] = ()


@dataclass(frozen=True)
class Verdict:
    """One scenario, one system under test, one seed."""

    scenario: str
    sut: str
    seed: int
    outcomes: tuple[AssertionOutcome, ...]
    wall_time_s: float

    @property
    def passed(self) -> bool:
        return all(o.passed for o in self.outcomes)

    @property
    def violations(self) -> list[Violation]:
        return [v for o in self.outcomes for v in o.violations]
