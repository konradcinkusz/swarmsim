"""Storing a suite report in SwarmApi.Api (POST /api/scenario-runs, docs/adr/0011).

The verdict is decided where the scenarios ran — in the caller's CI — and uploading it is
only remembering it, so a failed upload never changes the suite's outcome: it is reported,
and the run carries on. Standard library only. The write carries an Idempotency-Key and a
timed-out attempt is retried once under the same key, which the API answers with its
first reply instead of storing the run twice (architecture-standards
SERVICE-API-PATTERNS, "A write that timed out is not a write that failed").
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

TIMEOUT_S = 30.0
TOKEN_VARIABLE = "SWARMSIM_API_TOKEN"


class UploadError(Exception):
    """The report was not stored, or it is unknown whether it was."""


def upload_report(
    api: str,
    report: dict,
    label: str | None,
    token: str | None = None,
    timeout_s: float = TIMEOUT_S,
) -> dict:
    """Stores ``report`` (runner.to_json's output) and returns the API's summary of it."""
    body = json.dumps({"label": label, "report": report}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Idempotency-Key": f"scenarios-{uuid.uuid4()}",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{api.rstrip('/')}/api/scenario-runs"

    for attempt in (1, 2):
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:500]
            raise UploadError(f"{url} answered {error.code}: {detail}") from None
        except (TimeoutError, ConnectionResetError) as error:
            if attempt == 2:
                raise UploadError(
                    f"{url} did not answer twice ({error!r}); the run may or may not be stored"
                ) from None
        except urllib.error.URLError as error:
            raise UploadError(f"{url} could not be reached: {error.reason}") from None
    raise AssertionError("unreachable")
