#!/usr/bin/env bash
# Entrypoint for the `sim` container: brings up rosbridge, then one PX4 SITL + Gazebo
# instance per simulation/px4-configs/drone_*.env found (M0: just drone_1; M1: up to
# drone_5). HEADLESS=1 runs Gazebo without a GUI — the fallback path when GPU/X11
# passthrough isn't available (see the README's "GPU and headless mode" section).
#
# Each PX4 instance runs inside its own named tmux session, not a bare background job:
# M0's acceptance criterion is confirming `commander takeoff` at PX4's own interactive
# `pxh>` console, and a backgrounded process with stdin/stdout redirected to a log file
# has no console left to attach to. `docker compose exec sim tmux attach -t drone_1`
# reaches the real console; `tmux` also captures the pane's scrollback as the instance's
# log, so nothing is lost by not redirecting to a file separately.
set -euo pipefail

SWARMSIM_ROOT=/opt/swarmsim
PX4_DIR=/opt/PX4-Autopilot
CONFIG_DIR="${SWARMSIM_ROOT}/px4-configs"

source /opt/ros/humble/setup.bash

echo "[entrypoint] starting rosbridge_websocket on :9090"
ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=9090 &
ROSBRIDGE_PID=$!

if [[ "${HEADLESS:-0}" == "1" ]]; then
  export GZ_SIM_SERVER_CONFIG_PATH=""
  export QT_QPA_PLATFORM=offscreen
  GZ_ARGS="-s -r"
  echo "[entrypoint] HEADLESS=1: launching Gazebo server only (no GUI)"
else
  GZ_ARGS="-r"
  echo "[entrypoint] launching Gazebo with GUI (requires X11/Wayland passthrough — see README)"
fi
export GZ_SIM_RUN_ARGS="${GZ_ARGS}"

shopt -s nullglob
configs=("${CONFIG_DIR}"/drone_*.env)
if [[ ${#configs[@]} -eq 0 ]]; then
  echo "[entrypoint] no drone_*.env found in ${CONFIG_DIR}; nothing to spawn" >&2
  exit 1
fi

cd "${PX4_DIR}"

sessions=()
for cfg in "${configs[@]}"; do
  # shellcheck disable=SC1090
  source "${CONFIG_DIR}/x500_common.env"
  # shellcheck disable=SC1090
  source "${cfg}"

  echo "[entrypoint] spawning ${ROS_NAMESPACE} (instance ${PX4_INSTANCE}, sys_id ${MAV_SYS_ID}) at pose ${PX4_GZ_MODEL_POSE}"
  tmux new-session -d -s "${ROS_NAMESPACE}" \
    "PX4_INSTANCE='${PX4_INSTANCE}' \
     PX4_SIM_MODEL='${PX4_SIM_MODEL}' \
     PX4_GZ_WORLD='${PX4_GZ_WORLD}' \
     PX4_GZ_MODEL_POSE='${PX4_GZ_MODEL_POSE}' \
     MAV_SYS_ID='${MAV_SYS_ID}' \
     '${PX4_DIR}/build/px4_sitl_default/bin/px4' \
       -i '${PX4_INSTANCE}' \
       '${PX4_DIR}/build/px4_sitl_default/etc' \
       -s etc/init.d-posix/rcS"
  sessions+=("${ROS_NAMESPACE}")
done

echo "[entrypoint] ${#sessions[@]} PX4 SITL instance(s) running; rosbridge on :9090"
echo "[entrypoint] attach to a console with: docker compose exec sim tmux attach -t <name>"
echo "[entrypoint] sessions: ${sessions[*]}"

shutdown() {
  echo "[entrypoint] shutting down"
  for s in "${sessions[@]}"; do
    tmux kill-session -t "${s}" 2>/dev/null || true
  done
  kill "${ROSBRIDGE_PID}" 2>/dev/null || true
}
trap shutdown TERM INT

# tmux sessions are detached background processes; poll for the container's real work
# (rosbridge and every PX4 session) rather than a `wait` that has nothing job-control-
# visible to wait on.
while kill -0 "${ROSBRIDGE_PID}" 2>/dev/null; do
  for s in "${sessions[@]}"; do
    if ! tmux has-session -t "${s}" 2>/dev/null; then
      echo "[entrypoint] session ${s} exited; shutting down" >&2
      shutdown
      exit 1
    fi
  done
  sleep 2
done
