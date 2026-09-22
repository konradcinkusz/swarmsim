# PX4 SITL per-drone configs

One `.env` file per swarm member, sourced by `docker/entrypoint.sh` before launching that
member's `px4` SITL instance. Kept as plain, shell-sourceable `KEY=value` lines rather
than a single YAML/JSON manifest, because the values map 1:1 onto the environment
variables PX4's own init scripts read — no translation layer between "what this file
says" and "what PX4 sees".

| File | Purpose |
|---|---|
| `x500_common.env` | Shared defaults: the airframe (`PX4_SIM_MODEL`) and the Gazebo world (`PX4_GZ_WORLD`). Sourced first. |
| `drone_<n>.env` | Per-instance values: `PX4_INSTANCE`, `ROS_NAMESPACE`, `PX4_GZ_MODEL_POSE`. Sourced after the common file, so it can override anything in it. |
| `px4-rc.params` | PX4 parameters for every instance (`param set-default ...`). Not an env file: PX4's `init.d-posix/rcS` sources the first `px4-rc.params` on its PATH after the airframe, and the entrypoint puts this directory first. Today it sets one parameter, `EKF2_HGT_REF 0` (below). |

How PX4 (v1.15, the version `docker/Dockerfile.sim` pins) consumes each variable:

| Variable | Consumed by | Effect |
|---|---|---|
| `PX4_SIM_MODEL` | `init.d-posix/rcS` | `gz_x500` selects airframe `4001_gz_x500` by file name |
| `PX4_GZ_WORLD` | `px4-rc.simulator` → `gz_bridge -w` | The world every instance joins; must equal the `<world name>` and the file name in `simulation/worlds/` |
| `PX4_INSTANCE` | `px4 -i` | Working directory `rootfs/<instance>`, `MAV_SYS_ID = instance + 1`, offboard MAVLink on UDP `14580+instance` → `14540+instance` |
| `PX4_GZ_MODEL_POSE` | `gz_bridge -p` | Spawn pose `x,y,z,roll,pitch,yaw` in the world frame — and therefore the origin of that drone's local frame |
| `ROS_NAMESPACE` | `docker/entrypoint.sh` | The tmux session name, and the namespace the ROS 2 side uses for this drone |

### Why the barometer is the height reference

PX4 v1.15 defaults `EKF2_HGT_REF` to GNSS. The local frame's zero height is then taken
from the GNSS altitude when the first fix passes the estimator's checks, and in the SITL
smoke, drones standing on their pads still read between -1.9 m and +2.6 m after four
minutes. Every altitude in this repository — mission waypoints, the smoke test's
checks, `frames.py`'s world ↔ local conversion — assumes a drone's local zero is its
pad. With the barometer as the reference it is the height the drone booted at, which
is its pad; GNSS height is still fused, with its offset estimated as a bias.

There is no `MAV_SYS_ID` variable on purpose: PX4 derives it from the instance index, so a
value here could only disagree with it.

`docker/entrypoint.sh` starts one Gazebo server itself and runs every instance with
`PX4_GZ_STANDALONE=1`, so all of them attach to that server instead of racing to start
their own. It globs `drone_*.env` in numeric order and spawns one instance per match; set
`SWARM_DRONE_COUNT` to spawn only the first N. M0 (one drone) and M1 (up to five) run the
same image and script — only the number of configs used changes.

A sixth drone is a sixth file, not a code change: next instance index, next namespace, and
a pose at least a few metres from the others (the five here stand 3 m apart along +y).

These files are committed configuration, not secrets. A blanket `*.env` rule in
`.gitignore` once kept them out of the repository entirely, so the root `.gitignore` now
names secret files explicitly, and CI (`.github/workflows/ci.yml`, job
`simulation-config`) fails if these files go missing.
