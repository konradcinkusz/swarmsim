"""Storing a report in SwarmApi.Api: what is sent, and that a failed upload never changes
the suite's outcome. Against a local stub of the API."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")
pytest.importorskip("yaml")

from swarm_coordination.scenarios.__main__ import main  # noqa: E402
from swarm_coordination.scenarios.upload import UploadError, upload_report  # noqa: E402

SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "waypoint_lanes.yaml"


class StubApi:
    """Answers POST /api/scenario-runs from a script and records what it was sent."""

    def __init__(self, answer):
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - the stdlib's name
                body = self.rfile.read(int(self.headers["Content-Length"]))
                stub.requests.append(
                    {"path": self.path, "headers": dict(self.headers), "body": json.loads(body)}
                )
                status, payload, delay = answer(len(stub.requests))
                time.sleep(delay)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api():
    stubs = []

    def make(answer):
        stubs.append(StubApi(answer))
        return stubs[-1]

    yield make
    for stub in stubs:
        stub.close()


def test_a_run_is_stored_with_its_label_and_the_operators_token(api, monkeypatch, capsys):
    stub = api(lambda n: (201, {"id": "run-1"}, 0))
    monkeypatch.setenv("SWARMSIM_API_TOKEN", "t0ken")

    status = main(["run", str(SCENARIO), "--upload", stub.url + "/", "--label", "abc123 main"])

    (request,) = stub.requests
    assert status == 0
    assert request["path"] == "/api/scenario-runs"
    assert request["headers"]["Authorization"] == "Bearer t0ken"
    assert request["headers"]["Idempotency-Key"].startswith("scenarios-")
    assert request["body"]["label"] == "abc123 main"
    assert request["body"]["report"]["version"] == 1
    assert "stored as scenario run run-1" in capsys.readouterr().out


def test_a_failed_upload_is_reported_and_the_verdict_stands(api, capsys):
    stub = api(lambda n: (500, {"title": "boom"}, 0))

    status = main(["run", str(SCENARIO), "--upload", stub.url])

    assert status == 0  # the scenario passed; storing it is not part of the verdict
    assert "the report was not stored" in capsys.readouterr().err
    assert len(stub.requests) == 1  # an answer, even a 500, is not retried


def test_a_timed_out_upload_is_retried_once_under_the_same_key(api):
    stub = api(lambda n: (201, {"id": "run-2"}, 1.0 if n == 1 else 0))

    stored = upload_report(stub.url, {"version": 1}, None, timeout_s=0.3)

    assert stored == {"id": "run-2"}
    assert len({r["headers"]["Idempotency-Key"] for r in stub.requests}) == 1


def test_an_api_that_never_answers_is_an_unknown_outcome(api):
    stub = api(lambda n: (201, {}, 1.0))

    with pytest.raises(UploadError, match="may or may not be stored"):
        upload_report(stub.url, {"version": 1}, None, timeout_s=0.2)
    assert len(stub.requests) == 2
