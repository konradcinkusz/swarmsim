"""SwarmClient against a local stub of the API: request shape, errors, retries."""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from mcp_server.swarm_client import (
    WRITE_ATTEMPTS,
    SwarmApiError,
    SwarmClient,
    SwarmOutcomeUnknown,
    SwarmUnreachable,
    Waypoint,
    build_mission_payload,
    build_request,
    parse_problem,
)
from mcp_server.tools import dispatch_mission, plan_mission

PLAN = "3f2b6c1e-8a4d-4b7e-9c2a-1d5e8f7a9b0c"


class Stub:
    """A local HTTP server answering from a script; records every request it got."""

    def __init__(self, answer):
        self.answer = answer
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                stub.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": json.loads(body) if body else None,
                    }
                )
                status, payload, delay = stub.answer(len(stub.requests))
                time.sleep(delay)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _handle

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    stubs = []

    def make(answer):
        stubs.append(Stub(answer))
        return stubs[-1]

    yield make
    for s in stubs:
        s.close()


def test_build_mission_payload_matches_swarmapi_wire_shape():
    payload = build_mission_payload(
        "Perimeter sweep", "formation", [Waypoint(0, 0, 5), Waypoint(10, 0, 5)], 3, 2.5, "v"
    )

    assert payload == {
        "name": "Perimeter sweep",
        "type": "formation",
        "waypoints": [{"x": 0, "y": 0, "z": 5}, {"x": 10, "y": 0, "z": 5}],
        "droneCount": 3,
        "spacingMeters": 2.5,
        "formation": "v",
    }
    assert "formation" not in build_mission_payload("x", "waypoint", [Waypoint(0, 0, 5)], 1)


def test_the_operators_token_is_sent_only_when_set():
    with_token = build_request("http://api/", "POST", "/api/swarm/land", {}, token="abc123")
    without = build_request("http://api", "POST", "/api/swarm/land", {}, token=None)

    assert with_token.full_url == "http://api/api/swarm/land"
    assert with_token.headers["Authorization"] == "Bearer abc123"
    assert "Authorization" not in without.headers


def test_a_plan_is_proposed_with_an_idempotency_key(stub):
    api = stub(lambda n: (201, {"id": PLAN, "status": "PendingApproval"}, 0))

    plan = plan_mission(SwarmClient(api.url), "Sweep", "waypoint", [{"x": 0, "y": 0, "z": 5}], 2)

    (request,) = api.requests
    assert plan["status"] == "PendingApproval"
    assert (request["method"], request["path"]) == ("POST", "/api/mission-plans")
    assert request["headers"]["Idempotency-Key"].startswith("mcp-")
    assert request["body"]["droneCount"] == 2


def test_a_dispatch_carries_the_approval_code_in_its_body(stub):
    api = stub(lambda n: (201, {"id": "mission"}, 0))

    dispatch_mission(SwarmClient(api.url), PLAN, "the-code")

    (request,) = api.requests
    assert request["path"] == f"/api/mission-plans/{PLAN}/dispatch"
    assert request["body"] == {"approvalCode": "the-code"}


def test_an_api_error_is_reported_with_its_status_and_detail(stub):
    problem = {"title": "Approval refused", "detail": "The approval code does not match."}
    api = stub(lambda n: (403, problem, 0))

    with pytest.raises(SwarmApiError) as error:
        SwarmClient(api.url).dispatch_plan(PLAN, "wrong")

    assert (error.value.status, error.value.title) == (403, "Approval refused")
    assert "does not match" in str(error.value)
    assert len(api.requests) == 1  # an answer is an answer: never retried


def test_validation_errors_are_listed_field_by_field():
    error = parse_problem(
        400, json.dumps({"title": "Bad", "errors": {"request": ["a", "b"]}}).encode()
    )

    assert str(error) == "HTTP 400 Bad [request: a; b]"
    assert parse_problem(502, b"<html>").title == "Bad Gateway"


def test_a_write_without_an_answer_is_retried_under_the_same_key_then_reported_unknown(stub):
    api = stub(lambda n: (201, {}, 1.0))  # always answers after the client gave up

    with pytest.raises(SwarmOutcomeUnknown, match="may have taken effect"):
        SwarmClient(api.url, timeout_s=0.2).land_all()

    keys = {r["headers"]["Idempotency-Key"] for r in api.requests}
    assert len(api.requests) == WRITE_ATTEMPTS and len(keys) == 1


def test_a_write_answered_on_retry_succeeds(stub):
    api = stub(lambda n: (202, {"command": "Land"}, 1.0 if n == 1 else 0))

    assert SwarmClient(api.url, timeout_s=0.3).land_all() == {"command": "Land"}
    assert len({r["headers"]["Idempotency-Key"] for r in api.requests}) == 1


def test_a_refused_connection_says_nothing_was_sent_and_is_not_retried():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]  # closed again: nobody listens here

    with pytest.raises(SwarmUnreachable, match="nothing was sent"):
        SwarmClient(f"http://127.0.0.1:{port}").land_all()


def test_a_read_that_times_out_is_unreachable_not_unknown(stub):
    api = stub(lambda n: (200, {}, 1.0))

    with pytest.raises(SwarmUnreachable):
        SwarmClient(api.url, timeout_s=0.2).swarm_status()
    assert len(api.requests) == 1


def test_ids_that_are_not_uuids_never_reach_a_url(stub):
    api = stub(lambda n: (200, {}, 0))
    client = SwarmClient(api.url)

    for call in (
        lambda: client.mission("../swarm/land"),
        lambda: client.mission_plan("x"),
        lambda: client.dispatch_plan("1; drop", "c"),
        lambda: client.abort_mission("", "rtl"),
    ):
        with pytest.raises(SwarmApiError, match="not a UUID"):
            call()
    assert api.requests == []


def test_a_retry_that_finds_the_first_attempt_still_running_waits_for_its_answer(stub):
    def answer(n):
        if n == 1:
            return 202, {"command": "Land"}, 0.6  # answered, but after the client gave up
        if n == 2:
            return 409, {"title": "Request in progress"}, 0
        return 202, {"command": "Land"}, 0  # the replay of the first answer

    api = stub(answer)

    assert SwarmClient(api.url, timeout_s=0.3).land_all() == {"command": "Land"}
    assert len(api.requests) == 3
