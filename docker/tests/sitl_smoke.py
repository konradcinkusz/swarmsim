#!/usr/bin/env python3
"""SITL smoke: M0, M1 and M3 checked against the real stack instead of asserted.

Run against a `docker compose up` stack (headless is fine — no GPU):

    python3 docker/tests/sitl_smoke.py --api http://localhost:8080 --drones 3

It talks only to SwarmApi.Api, so it exercises the whole path an operator uses: API →
rosbridge → mission_dispatcher_node → drone_controller_node → MAVROS → PX4 SITL → Gazebo,
and back through swarm_state_aggregator_node. Each step prints what it measured; with
--summary it also writes a Markdown table (the GitHub job summary). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SPAWN_SPACING_M = 3.0  # simulation/px4-configs: drone_n spawns at (0, 3 * (n - 1), 0)
results: list[tuple[str, str, str]] = []


class SmokeFailure(Exception):
    pass


def call(api: str, method: str, path: str, body: dict | None = None, timeout: float = 10.0):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"{api}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode()
            return response.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as error:
        text = error.read().decode()
        return error.code, (json.loads(text) if text.startswith("{") else text)


def wait_for(description: str, timeout_s: float, probe, interval_s: float = 1.0):
    started = time.monotonic()
    last = None
    while time.monotonic() - started < timeout_s:
        try:
            ok, last = probe()
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
            ok, last = False, f"unreachable: {error}"
        if ok:
            elapsed = time.monotonic() - started
            print(f"  ok   {description} ({elapsed:.1f}s)")
            return last, elapsed
        time.sleep(interval_s)
    raise SmokeFailure(f"timed out after {timeout_s:.0f}s waiting for {description}; last seen: {last}")


def record(check: str, measured: str, verdict: str) -> None:
    results.append((check, measured, verdict))
    print(f"  {verdict:<4} {check}: {measured}")


def state(api: str) -> dict:
    return call(api, "GET", "/api/swarm/state")[1]


def age_seconds(timestamp: str) -> float:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def run(api: str, drones: int) -> None:
    print("1. the API is up and connected to rosbridge")

    def connected():
        status, health = call(api, "GET", "/health")
        mode = health["checks"]["swarm_bridge"]["data"]["swarmBridge"] if status == 200 else None
        return mode == "Connected", health

    wait_for("GET /health reports swarmBridge=Connected", 600, connected, 2.0)

    print(f"2. M1: {drones} drones report, each at its own pad in the shared world frame")

    def all_reporting():
        current = state(api)
        return len(current["drones"]) == drones, current

    wait_for(f"{drones} drones in /api/swarm/state", 300, all_reporting, 2.0)

    def by_id(current):
        return sorted(current["drones"], key=lambda d: int(d["id"].split("_")[1]))

    def pad_error(index, drone):
        p = drone["position"]
        return ((p["x"]) ** 2 + (p["y"] - index * SPAWN_SPACING_M) ** 2) ** 0.5, abs(p["z"])

    # A drone's first reports come before PX4's estimator has converged: the first SITL run
    # read drone_1 at z = 3.42 m while it sat on its pad. Wait for every drone to settle —
    # a frame that is not being converted never does, and times out with where they are.
    # A height that never settles is the estimator's height reference, not a frame:
    # simulation/px4-configs/px4-rc.params sets it to the barometer for that reason.
    def all_on_pads():
        current = state(api)
        settled = all(
            horizontal < 1.0 and vertical < 0.5
            for horizontal, vertical in (pad_error(i, d) for i, d in enumerate(by_id(current)))
        )
        seen = {
            d["id"]: "({x:.2f}, {y:.2f}, {z:.2f})".format(**d["position"])
            + f" {d.get('status')} armed={d.get('armed')} mode={d.get('flightMode')}"
            for d in by_id(current)
        }
        return settled, seen

    try:
        _, settle_s = wait_for("every drone settled on its own pad", 240, all_on_pads, 2.0)
    except SmokeFailure as failure:
        raise SmokeFailure(f"drones never settled on their pads (frames, or the estimator): {failure}") from None
    current = state(api)
    for index, drone in enumerate(by_id(current)):
        p = drone["position"]
        record(f"{drone['id']} on its pad (0, {index * SPAWN_SPACING_M:.0f})", f"({p['x']:.2f}, {p['y']:.2f}, {p['z']:.2f})", "ok")
    record("time for the estimators to settle", f"{settle_s:.1f} s", "info")

    print("3. M0/M3: a waypoint mission takes off, flies, lands and completes")
    mission = {
        "name": "SITL smoke",
        "type": "waypoint",
        "waypoints": [{"x": 0, "y": 0, "z": 5}, {"x": 10, "y": 0, "z": 5}],
        "droneCount": drones,
        "spacingMeters": SPAWN_SPACING_M,
    }
    status, created = call(api, "POST", "/api/missions", mission)
    if status != 201:
        raise SmokeFailure(f"POST /api/missions returned {status}: {created}")
    mission_id = created["id"]

    max_altitude: dict[str, float] = {}
    state_ages: list[float] = []

    def completed():
        current = state(api)
        for drone in current["drones"]:
            max_altitude[drone["id"]] = max(max_altitude.get(drone["id"], 0.0), drone["position"]["z"])
            state_ages.append(age_seconds(drone["lastUpdatedUtc"]))
        _, fetched = call(api, "GET", f"/api/missions/{mission_id}")
        return fetched["status"] == "Completed", {"mission": fetched["status"], "drones": current["drones"]}

    final, flight_s = wait_for("mission status Completed", 420, completed, 0.5)
    for drone_id, altitude in sorted(max_altitude.items()):
        record(f"{drone_id} climbed", f"max z {altitude:.2f} m", "ok" if altitude > 4.0 else "FAIL")
    for index, drone in enumerate(sorted(final["drones"], key=lambda d: int(d["id"].split("_")[1]))):
        p = drone["position"]
        target_y = index * SPAWN_SPACING_M
        error = ((p["x"] - 10) ** 2 + (p["y"] - target_y) ** 2) ** 0.5
        record(
            f"{drone['id']} landed at the end of its lane (10, {target_y:.0f})",
            f"({p['x']:.2f}, {p['y']:.2f}, {p['z']:.2f}), status {drone['status']}",
            "ok" if error < 1.5 and p["z"] < 0.5 else "FAIL",
        )
    record("mission flight time", f"{flight_s:.1f} s", "info")

    p95 = statistics.quantiles(state_ages, n=20)[18] if len(state_ages) >= 20 else max(state_ages)
    record("M3 state age at the API, p95", f"{p95:.3f} s over {len(state_ages)} samples", "ok" if p95 < 1.0 else "FAIL")

    print("4. an operator can stop a flying formation: abort → land in place")
    formation = {
        "name": "SITL abort",
        "type": "formation",
        "formation": "line",
        "waypoints": [{"x": 0, "y": 0, "z": 6}, {"x": 60, "y": 0, "z": 6}],
        "droneCount": drones,
        "spacingMeters": SPAWN_SPACING_M,
    }
    status, created = call(api, "POST", "/api/missions", formation)
    if status != 201:
        raise SmokeFailure(f"POST /api/missions (formation) returned {status}: {created}")

    def airborne():
        current = state(api)
        return all(d["position"]["z"] > 3.0 for d in current["drones"]), current

    wait_for("every drone airborne in formation", 240, airborne, 0.5)
    status, aborted = call(api, "POST", f"/api/missions/{created['id']}/abort", {"action": "land"})
    record("abort accepted", f"HTTP {status}, mission {aborted.get('status') if isinstance(aborted, dict) else aborted}", "ok" if status == 200 else "FAIL")

    def landed():
        current = state(api)
        return all(d["position"]["z"] < 0.5 and d["status"] == "Landed" for d in current["drones"]), current

    wait_for("every drone landed and disarmed after the abort", 240, landed, 1.0)

    failures = [r for r in results if r[2] == "FAIL"]
    if failures:
        raise SmokeFailure(f"{len(failures)} check(s) failed: " + "; ".join(f[0] for f in failures))


def write_summary(path: str, outcome: str) -> None:
    lines = ["## SITL smoke", "", f"**{outcome}**", "", "| Check | Measured | Verdict |", "|---|---|---|"]
    lines += [f"| {check} | {measured} | {verdict} |" for check, measured, verdict in results]
    with open(path, "a", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8080")
    parser.add_argument("--drones", type=int, default=3)
    parser.add_argument("--summary", help="append a Markdown summary to this file")
    args = parser.parse_args()
    outcome = "passed"
    try:
        run(args.api.rstrip("/"), args.drones)
    except SmokeFailure as failure:
        outcome = f"failed: {failure}"
        print(f"FAIL {failure}", file=sys.stderr)
    if args.summary:
        write_summary(args.summary, outcome)
    return 0 if outcome == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
