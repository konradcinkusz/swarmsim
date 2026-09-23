"""SwarmApi.Api over HTTP, for the MCP tools — with no `mcp` import, so it is unit tested
with no MCP install (the same split as swarm_coordination's nodes/ and pure modules).

What a caller learns from a failure is kept precise (architecture-standards
SERVICE-API-PATTERNS, "A write that timed out is not a write that failed"):

- ``SwarmApiError`` — the API answered with an error (a ProblemDetails body): nothing to
  guess, the status and its detail say what happened.
- ``SwarmUnreachable`` — the connection was refused or the name did not resolve: nothing
  was received, so nothing was done.
- ``SwarmOutcomeUnknown`` — the request may have been received and the answer lost (a
  timeout, a dropped connection). Every write carries an ``Idempotency-Key``, and the
  client retries it with the *same* key before giving up, which is safe: the API replays
  its first answer instead of acting twice. Only after that does the caller hear "unknown".
"""

from __future__ import annotations

import http.client
import json
import socket
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

DEFAULT_TIMEOUT_S = 10.0
WRITE_ATTEMPTS = 3  # the first attempt plus two retries under the same Idempotency-Key
RETRY_PAUSE_S = 0.5
# SwarmApi.Api's answer to a key whose first request is still running (IdempotencyFilter).
IN_PROGRESS_TITLE = "Request in progress"


class SwarmClientError(Exception):
    """Base for everything this client raises."""


@dataclass
class SwarmApiError(SwarmClientError):
    status: int
    title: str
    detail: str | None = None
    errors: dict[str, list[str]] | None = None

    def __str__(self) -> str:
        text = f"HTTP {self.status} {self.title}"
        if self.detail:
            text += f": {self.detail}"
        for field, messages in (self.errors or {}).items():
            text += f" [{field}: {'; '.join(messages)}]"
        return text


class SwarmUnreachable(SwarmClientError):
    """Nothing was received by the API, so nothing was done."""


class SwarmOutcomeUnknown(SwarmClientError):
    """The API may have acted; check its state before trying again."""


@dataclass(frozen=True)
class Waypoint:
    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


def build_mission_payload(
    name: str,
    mission_type: str,
    waypoints: list[Waypoint],
    drone_count: int,
    spacing_meters: float = 2.0,
    formation: str | None = None,
) -> dict[str, Any]:
    """SwarmApi.Application.Contracts.CreateMissionRequest's wire shape (camelCase, the
    ASP.NET Core minimal APIs' default JSON policy). ``formation`` is sent only when set."""
    payload: dict[str, Any] = {
        "name": name,
        "type": mission_type,
        "waypoints": [w.to_dict() for w in waypoints],
        "droneCount": drone_count,
        "spacingMeters": spacing_meters,
    }
    if formation is not None:
        payload["formation"] = formation
    return payload


def build_request(
    base_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
    idempotency_key: str | None = None,
) -> urllib.request.Request:
    """One request to the API. ``token`` is a bearer token the operator obtained from
    authservice (docs/adr/0005) — this module never logs in on its own behalf — and is
    omitted entirely when unset, matching the API's Open mode."""
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return urllib.request.Request(
        f"{base_url.rstrip('/')}{path}", data=data, headers=headers, method=method
    )


def parse_problem(status: int, body: bytes) -> SwarmApiError:
    """An error response as a SwarmApiError, whatever shape its body has."""
    try:
        problem = json.loads(body) if body else {}
    except ValueError:
        problem = {}
    if not isinstance(problem, dict):
        problem = {}
    errors = problem.get("errors") if isinstance(problem.get("errors"), dict) else None
    return SwarmApiError(
        status=status,
        title=str(problem.get("title") or http.client.responses.get(status, "Error")),
        detail=problem.get("detail"),
        errors=errors,
    )


def _refused(error: urllib.error.URLError) -> bool:
    reason = error.reason
    return isinstance(reason, (ConnectionRefusedError, socket.gaierror)) or (
        isinstance(reason, OSError) and reason.errno in (111, 61, 10061)  # ECONNREFUSED
    )


class SwarmClient:
    def __init__(
        self, base_url: str, token: str | None = None, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> None:
        self.base_url = base_url
        self.token = token
        self.timeout_s = timeout_s

    # --- reads ------------------------------------------------------------------------

    def swarm_status(self) -> dict[str, Any]:
        return self._read("/api/swarm/state")

    def mission(self, mission_id: str) -> dict[str, Any]:
        return self._read(f"/api/missions/{_uuid(mission_id)}")

    def mission_plan(self, plan_id: str) -> dict[str, Any]:
        return self._read(f"/api/mission-plans/{_uuid(plan_id)}")

    # --- writes -----------------------------------------------------------------------

    def plan_mission(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._write("POST", "/api/mission-plans", payload)

    def dispatch_plan(self, plan_id: str, approval_code: str) -> dict[str, Any]:
        return self._write(
            "POST",
            f"/api/mission-plans/{_uuid(plan_id)}/dispatch",
            {"approvalCode": approval_code},
        )

    def abort_mission(self, mission_id: str, action: str) -> dict[str, Any]:
        return self._write("POST", f"/api/missions/{_uuid(mission_id)}/abort", {"action": action})

    def land_all(self) -> dict[str, Any]:
        return self._write("POST", "/api/swarm/land", None)

    # --- transport --------------------------------------------------------------------

    def _read(self, path: str) -> dict[str, Any]:
        try:
            return self._send(build_request(self.base_url, "GET", path, token=self.token))
        except SwarmOutcomeUnknown as unknown:
            # A read has no outcome to be unsure of; it just did not answer in time.
            raise SwarmUnreachable(str(unknown)) from None

    def _write(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        key = f"mcp-{uuid.uuid4()}"
        last: SwarmOutcomeUnknown | None = None
        for _ in range(WRITE_ATTEMPTS):
            request = build_request(self.base_url, method, path, body, self.token, key)
            try:
                return self._send(request)
            except SwarmOutcomeUnknown as unknown:
                last = unknown  # safe to repeat: same key, so the API replays, not re-runs
            except SwarmApiError as error:
                if (error.status, error.title) != (409, IN_PROGRESS_TITLE):
                    raise
                last = SwarmOutcomeUnknown(str(error))  # the first attempt is still running
                time.sleep(RETRY_PAUSE_S)
        raise SwarmOutcomeUnknown(
            f"{method} {path} got no answer after {WRITE_ATTEMPTS} attempts under Idempotency-Key "
            f"{key}; it may have taken effect. Check the plan, mission or swarm state before "
            f"trying again. ({last})"
        )

    def _send(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                text = response.read()
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as error:
            raise parse_problem(error.code, error.read()) from None
        except urllib.error.URLError as error:
            if _refused(error):
                raise SwarmUnreachable(
                    f"{request.full_url} refused the connection: nothing was sent"
                ) from None
            raise SwarmOutcomeUnknown(f"{request.full_url}: {error.reason}") from None
        except (TimeoutError, ConnectionResetError, http.client.HTTPException) as e:
            raise SwarmOutcomeUnknown(f"{request.full_url}: {e!r}") from None


def _uuid(value: str) -> str:
    """Ids go into URL paths, so only a real UUID gets through (no path injection)."""
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise SwarmApiError(400, "Invalid id", f"{value!r} is not a UUID") from None
