"""run(spec, sut, seed) → Verdict + Trace: one scenario, one system under test, one seed.

Each 0.1 s step (the drone controllers' 10 Hz rate): the scenario's events that are due
happen; the ground software and then every drone's software run on what reached them;
their messages go out through a network that delivers them on the next step, unless a
fault has cut the sender or the recipient off; the autopilots and the wind move the
world; and the step is recorded. The assertions then read the trace.

Randomness comes from named streams derived from the seed (wind, GPS), so a scenario
with no wind draws the same GPS noise as the same scenario with wind — and a run is
reproduced exactly by its seed.
"""

from __future__ import annotations

import json
import random
import time
import uuid
from collections import defaultdict

from .assertions import evaluate
from .model import DroneSample, Frame, Trace, Verdict
from .sim import Vehicle, Wind
from .spec import ScenarioSpec
from .sut import EVERYONE, GROUND, DroneInfo, Message, SystemUnderTest

DT_S = 0.1


def _stream(seed: int, name: str) -> random.Random:
    return random.Random(f"{seed}:{name}")


def mission_payload(spec: ScenarioSpec, index: int, mission: dict, seed: int) -> dict:
    """The /swarm/mission payload for the scenario's ``index``-th event (contract v1)."""
    mission_id = uuid.uuid5(uuid.NAMESPACE_URL, f"swarmsim:{spec.name}:{index}:{seed}")
    return {
        "version": 1,
        "mission_id": str(mission_id),
        "type": mission["type"],
        "formation": mission.get("formation", "line"),
        "waypoints": [[float(c) for c in wp] for wp in mission["waypoints"]],
        "drone_count": mission["drone_count"],
        "spacing_m": float(mission["spacing_m"]),
    }


def run_scenario(spec: ScenarioSpec, sut: SystemUnderTest, seed: int) -> tuple[Verdict, Trace]:
    started = time.perf_counter()
    fleet = [DroneInfo(d, spec.home(d)) for d in spec.drone_ids]
    vehicles = {
        d.drone_id: Vehicle(d.drone_id, d.home, spec.initial_battery_pct, spec.world.limits)
        for d in fleet
    }
    ground = sut.ground(fleet)
    software = {d.drone_id: sut.drone(d, fleet) for d in fleet}
    wind = Wind(spec.world, _stream(seed, "wind"))
    gps = _stream(seed, "gps")
    trace = Trace(spec.name, sut.name, seed, DT_S, {d.drone_id: d.home for d in fleet})

    inbox: dict[str, list[Message]] = defaultdict(list)
    cut_off: list[tuple[frozenset[str], float]] = []  # (drones, until)
    pending = list(enumerate(spec.events))
    steps = int(round(spec.duration_s / DT_S))

    for step in range(steps):
        now = round(step * DT_S, 6)

        while pending and pending[0][1].at_s <= now + 1e-9:
            index, event = pending.pop(0)
            if event.kind == "mission":
                payload = mission_payload(spec, index, event.data, seed)
                trace.missions.append((now, payload["mission_id"], payload))
                ground.submit_mission(json.dumps(payload))
                trace.events.append((now, f"mission {payload['mission_id']} dispatched"))
            elif event.kind == "command":
                ground.submit_command(json.dumps({"version": 1, "command": event.data}))
                trace.events.append((now, f"operator command '{event.data}'"))
            elif event.kind == "battery":
                vehicles[event.data["drone"]].battery_pct = float(event.data["set_pct"])
                trace.events.append(
                    (now, f"{event.data['drone']} battery reads {event.data['set_pct']}%")
                )
            elif event.kind == "comms_loss":
                drones = frozenset(event.data["drones"])
                cut_off.append((drones, now + float(event.data["duration_s"])))
                trace.events.append(
                    (now, f"comms lost to {sorted(drones)} for {event.data['duration_s']} s")
                )

        cut = frozenset().union(*(d for d, until in cut_off if now < until))
        outgoing = ground.step(now, inbox.pop(GROUND, []))
        for drone_id, drone_software in software.items():
            vehicle = vehicles[drone_id]
            observation = vehicle.observe(gps, spec.world.gps_noise_std_m)
            actuation, sent = drone_software.step(now, observation, inbox.pop(drone_id, []))
            vehicle.actuate(now, actuation)
            outgoing += sent

        for message in outgoing:
            if message.sender in cut:
                continue
            if message.recipient == EVERYONE:
                recipients = [d for d in software if d != message.sender] + [GROUND]
            else:
                recipients = [message.recipient]
            for recipient in recipients:
                if recipient not in cut:
                    inbox[recipient].append(message)

        disturbance = wind.step(DT_S)
        for vehicle in vehicles.values():
            vehicle.step(now, DT_S, disturbance, spec.world.battery_drain_pct_per_s)

        report = ground.report()
        mission = report.get("mission") or {}
        trace.frames.append(
            Frame(
                t_s=round(now + DT_S, 6),
                drones=tuple(
                    DroneSample(v.drone_id, v.position, v.armed, v.mode, v.battery_pct, v.airborne)
                    for v in vehicles.values()
                ),
                reported_mission_id=mission.get("id"),
                reported_complete=bool(mission.get("complete")),
            )
        )

    outcomes = evaluate(spec, trace)
    verdict = Verdict(spec.name, sut.name, seed, outcomes, time.perf_counter() - started)
    return verdict, trace
