from mcp_server.swarm_client import (
    Waypoint,
    build_mission_payload,
    build_mission_request,
    build_status_request,
)


def test_build_mission_payload_matches_swarmapi_wire_shape():
    payload = build_mission_payload(
        name="Perimeter sweep",
        mission_type="waypoint",
        waypoints=[Waypoint(0, 0, 5), Waypoint(10, 0, 5)],
        drone_count=3,
        spacing_meters=2.5,
    )

    assert payload == {
        "name": "Perimeter sweep",
        "type": "waypoint",
        "waypoints": [{"x": 0, "y": 0, "z": 5}, {"x": 10, "y": 0, "z": 5}],
        "droneCount": 3,
        "spacingMeters": 2.5,
    }


def test_build_status_request_targets_swarm_state_endpoint():
    request = build_status_request("http://localhost:5000")

    assert request.full_url == "http://localhost:5000/api/swarm/state"
    assert request.get_method() == "GET"


def test_build_status_request_strips_a_trailing_slash_from_base_url():
    request = build_status_request("http://localhost:5000/")

    assert request.full_url == "http://localhost:5000/api/swarm/state"


def test_build_mission_request_omits_authorization_header_without_a_token():
    request = build_mission_request("http://localhost:5000", {"name": "x"}, token=None)

    assert "Authorization" not in request.headers


def test_build_mission_request_forwards_a_bearer_token():
    request = build_mission_request("http://localhost:5000", {"name": "x"}, token="abc123")

    assert request.headers["Authorization"] == "Bearer abc123"
    assert request.get_method() == "POST"
