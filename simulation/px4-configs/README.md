# PX4 SITL per-drone configs

One `.env` file per swarm member, sourced by `docker/entrypoint.sh` before launching
that member's `px4` SITL instance. Kept as plain, shell-sourceable `KEY=value`
exports rather than a single YAML/JSON manifest, because the values map 1:1 onto the
environment variables PX4's own `sitl_multiple_run.sh` pattern reads — no translation
layer between "what this file says" and "what PX4 sees".

| File | Purpose |
|---|---|
| `x500_common.env` | Shared vehicle-type defaults (model, world, home position). Sourced first. |
| `drone_<n>.env` | Per-instance overrides: `PX4_INSTANCE`, `MAV_SYS_ID`, spawn pose offset, ROS 2 namespace. Sourced after the common file, so it can override anything in it. |

`docker/entrypoint.sh` globs `drone_*.env` and spawns one PX4 instance per match, so M0
(one drone) and M1 (up to five) run the same container image and script — only the set
of `.env` files present changes. The ROS 2 side namespaces its nodes the same way; see
`swarm_coordination/launch/spawn_swarm.launch.py`.

A sixth drone is a sixth file, not a code change.
