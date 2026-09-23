"""Scenario files: YAML, validated against contracts/scenario/scenario.v1.schema.json.

A scenario is data, not code: the world (wind, GPS noise, battery), a timeline of events
(missions, operator commands, injected faults) and the assertions to hold the swarm to.
Writing one needs no Python, and a malformed one is refused with the schema's reason
before anything runs. PyYAML and jsonschema are needed here, and only here — nothing the
ROS nodes import touches this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..trajectory import Vector3
from .sim import VehicleLimits, WorldConfig

SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "contracts" / "scenario" / "scenario.v1.schema.json"
)
PAD_SPACING_M = 3.0  # simulation/px4-configs: drone_n spawns at (0, 3 * (n - 1), 0)


class ScenarioError(ValueError):
    """A scenario file that cannot be run: unreadable, or not what the schema allows."""


@dataclass(frozen=True)
class Event:
    at_s: float
    kind: str  # mission | command | battery | comms_loss
    data: object


@dataclass(frozen=True)
class AssertionSpec:
    kind: str
    params: dict


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    description: str
    drones: int
    duration_s: float
    world: WorldConfig
    initial_battery_pct: float
    events: tuple[Event, ...]
    assertions: tuple[AssertionSpec, ...]
    expect: str = "pass"
    expect_reason: str | None = None
    source: str | None = None
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def drone_ids(self) -> list[str]:
        return [f"drone_{i + 1}" for i in range(self.drones)]

    def home(self, drone_id: str) -> Vector3:
        index = int(drone_id.rsplit("_", 1)[1]) - 1
        return Vector3(0.0, PAD_SPACING_M * index, 0.0)


def _vector(values) -> Vector3:
    return Vector3(float(values[0]), float(values[1]), float(values[2]))


def _validator():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:  # pragma: no cover - exercised only without the dependency
        raise ScenarioError(
            "validating scenarios needs the jsonschema package: pip install jsonschema pyyaml"
        ) from None
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def parse_scenario(document: dict, source: str | None = None) -> ScenarioSpec:
    """Validates ``document`` against the schema and builds the spec, or raises ScenarioError."""
    errors = sorted(_validator().iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        where = source or document.get("name", "scenario")
        details = "; ".join(
            f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
            for e in errors[:5]
        )
        raise ScenarioError(f"{where}: {details}")

    world = document.get("world", {})
    wind = world.get("wind", {})
    battery = world.get("battery", {})
    config = WorldConfig(
        wind_mean=_vector(wind.get("mean_m_s", [0.0, 0.0, 0.0])),
        wind_gust_std_m_s=float(wind.get("gust_std_m_s", 0.0)),
        gust_time_constant_s=float(wind.get("gust_time_constant_s", 5.0)),
        gps_noise_std_m=float(world.get("gps_noise_std_m", 0.0)),
        battery_drain_pct_per_s=float(battery.get("drain_pct_per_s", 0.05)),
        limits=VehicleLimits(),
    )

    drone_count = document["drones"]
    events = []
    for raw in document["events"]:
        kind = next(k for k in raw if k != "at_s")
        data = raw[kind]
        for drone in _drones_named(kind, data):
            if int(drone.rsplit("_", 1)[1]) > drone_count:
                raise ScenarioError(f"{source or document['name']}: {drone} does not exist")
        if kind == "mission" and data["drone_count"] > drone_count:
            raise ScenarioError(
                f"{source or document['name']}: a mission needs {data['drone_count']} "
                f"drone(s), the scenario has {drone_count}"
            )
        events.append(Event(float(raw["at_s"]), kind, data))
    events.sort(key=lambda e: e.at_s)

    assertions = []
    for raw in document["assertions"]:
        ((kind, params),) = raw.items()
        drone = params.get("drone") or params.get("leader")
        if drone is not None and int(drone.rsplit("_", 1)[1]) > drone_count:
            raise ScenarioError(f"{source or document['name']}: {drone} does not exist")
        assertions.append(AssertionSpec(kind, dict(params)))

    if document.get("expect") == "fail" and not document.get("expect_reason"):
        raise ScenarioError(
            f"{source or document['name']}: expect: fail needs an expect_reason saying why"
        )

    return ScenarioSpec(
        name=document["name"],
        description=" ".join(document["description"].split()),
        drones=drone_count,
        duration_s=float(document["duration_s"]),
        world=config,
        initial_battery_pct=float(battery.get("initial_pct", 100.0)),
        events=tuple(events),
        assertions=tuple(assertions),
        expect=document.get("expect", "pass"),
        expect_reason=document.get("expect_reason"),
        source=source,
        raw=document,
    )


def _drones_named(kind: str, data) -> list[str]:
    if kind == "battery":
        return [data["drone"]]
    if kind == "comms_loss":
        return list(data["drones"])
    return []


def load_scenario(path: str | Path) -> ScenarioSpec:
    try:
        import yaml
    except ImportError:  # pragma: no cover - exercised only without the dependency
        raise ScenarioError(
            "reading scenarios needs the PyYAML package: pip install pyyaml jsonschema"
        ) from None
    path = Path(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScenarioError(f"{path}: {exc}") from None
    if not isinstance(document, dict):
        raise ScenarioError(f"{path}: a scenario file must hold a mapping")
    return parse_scenario(document, source=str(path))


def discover(paths: list[str | Path]) -> list[Path]:
    """Scenario files under ``paths`` (files as given, directories searched for *.yaml)."""
    found: list[Path] = []
    for entry in paths:
        path = Path(entry)
        if path.is_dir():
            found += sorted(p for p in path.rglob("*.y*ml") if p.suffix in (".yaml", ".yml"))
        elif path.exists():
            found.append(path)
        else:
            raise ScenarioError(f"{path}: no such file or directory")
    return found
