"""Fixtures for the dashboard's end-to-end tests: a running SwarmApi.Api and a browser.

`SWARMSIM_E2E_URL` points at an API that is already running; otherwise one is started
with `dotnet run` on a free port (simulated swarm, Open auth) and stopped afterwards.
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` launches a specific Chromium instead of the one
`playwright install chromium` put in place.
"""

import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _alive(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/alive", timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


@pytest.fixture(scope="session")
def api_url():
    existing = os.environ.get("SWARMSIM_E2E_URL")
    if existing:
        yield existing.rstrip("/")
        return

    url = f"http://127.0.0.1:{_free_port()}"
    log = open(ROOT / "e2e" / "api.log", "w", encoding="utf-8")  # noqa: SIM115 - closed below
    process = subprocess.Popen(
        [
            "dotnet",
            "run",
            "--project",
            str(ROOT / "backend" / "src" / "SwarmApi.Api"),
            "--urls",
            url,
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        env={**os.environ, "ASPNETCORE_ENVIRONMENT": "Development"},
    )
    try:
        deadline = time.monotonic() + 180
        while not _alive(url):
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"SwarmApi.Api did not start; see {log.name}")
            time.sleep(1)
        yield url
    finally:
        process.terminate()
        process.wait(timeout=30)
        log.close()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
        browser = playwright.chromium.launch(executable_path=executable)
        yield browser
        browser.close()


@pytest.fixture
def page(browser, api_url):
    context = browser.new_context(base_url=api_url)
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture
def agent(api_url):
    """What an agent does through the MCP server's plan_mission: POST a plan to the API."""

    def propose(
        name, mission_type="waypoint", formation=None, drone_count=2, spacing=3.0
    ):
        body = {
            "name": name,
            "type": mission_type,
            "waypoints": [{"x": 0, "y": 0, "z": 5}, {"x": 20, "y": 0, "z": 5}],
            "droneCount": drone_count,
            "spacingMeters": spacing,
        }
        if formation:
            body["formation"] = formation
        request = urllib.request.Request(
            f"{api_url}/api/mission-plans",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

    return propose
