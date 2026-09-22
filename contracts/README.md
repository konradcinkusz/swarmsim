# Contracts

Messages that cross a language boundary in this repository, written down once so both
sides test against the same file instead of against their own idea of it
(architecture-standards P11: one internal model per side, one agreed dialect between them).

## `rosbridge/` — SwarmApi.Api ↔ swarm_coordination

Three topics carry JSON inside a `std_msgs/String` (`data` field) over rosbridge_suite:

| Topic | Direction | Schema | Example |
|---|---|---|---|
| `/swarm/mission` | API → ROS 2 | [`swarm_mission.v1.schema.json`](rosbridge/swarm_mission.v1.schema.json) | [`examples/swarm_mission.json`](rosbridge/examples/swarm_mission.json) |
| `/swarm/command` | API → ROS 2 | [`swarm_command.v1.schema.json`](rosbridge/swarm_command.v1.schema.json) | [`examples/swarm_command.json`](rosbridge/examples/swarm_command.json) |
| `/swarm/state` | ROS 2 → API | [`swarm_state.v1.schema.json`](rosbridge/swarm_state.v1.schema.json) | [`examples/swarm_state.json`](rosbridge/examples/swarm_state.json) |

Who checks what:

- `swarm_coordination/test/test_contracts.py` validates every example against its schema,
  parses the mission and command examples with the same functions the ROS nodes use, and
  validates what the state aggregator builds against the state schema.
- `backend/tests/SwarmApi.Infrastructure.Tests/RosBridgeProtocolTests.cs` serialises a
  mission and a command and compares them field by field with the examples, and parses the
  state example into the domain model.

Changing a message means changing its schema and example here first; both test suites then
say which side has not caught up. A breaking change bumps `version` and the file name.

Positions in `/swarm/state` are in the shared **world** frame (ENU, metres, Gazebo world
origin) — never a drone's own local frame, whose origin is wherever that drone spawned.
