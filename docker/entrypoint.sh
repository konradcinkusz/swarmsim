#!/usr/bin/env bash
# Entrypoint for the `sim` container: brings up rosbridge, one Gazebo server, and one
# PX4 SITL instance per simulation/px4-configs/drone_*.env (M0: drone_1; M1: up to
# drone_5, or the first SWARM_DRONE_COUNT of them).
#
# Gazebo is started HERE, once, and every PX4 instance runs with PX4_GZ_STANDALONE=1 so
# it attaches to that server instead of starting its own. Left to PX4's own init script
# (px4-rc.simulator in v1.15), each instance probes for a running world and starts a
# server if it finds none — start five instances at once and several of them race to
# start competing servers. Owning the server here also puts HEADLESS under this
# script's control: PX4's script treats HEADLESS as "set means headless", so even
# HEADLESS=0 used to suppress the GUI.
#
# Each PX4 instance runs inside its own named tmux session, not a bare background job:
# M0's acceptance criterion is confirming `commander takeoff` at PX4's own interactive
# `pxh>` console, and a backgrounded process with stdin/stdout redirected has no console
# left to attach to. `docker compose exec sim tmux attach -t drone_1` reaches the real
# console; every pane is also mirrored to ${LOG_DIR}/<session>.log for CI and debugging.
set -euo pipefail

# Paths are overridable only so docker/tests/test_entrypoint.sh can run this script
# against stubs in CI; inside the image the defaults are the truth.
SWARMSIM_ROOT="${SWARMSIM_ROOT:-/opt/swarmsim}"
PX4_DIR="${PX4_DIR:-/opt/PX4-Autopilot}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/humble/setup.bash}"
COORDINATION_SETUP="${COORDINATION_SETUP:-/opt/swarmsim/ws/install/setup.bash}"
PX4_BIN="${PX4_DIR}/build/px4_sitl_default/bin/px4"
CONFIG_DIR="${SWARMSIM_ROOT}/px4-configs"
WORLD_DIR="${SWARMSIM_ROOT}/worlds"
LOG_DIR="${SWARMSIM_LOG_DIR:-/tmp/swarmsim}"
GZ_WAIT_SECONDS="${GZ_WAIT_SECONDS:-120}"

log() { echo "[entrypoint] $*"; }
die() { echo "[entrypoint] ERROR: $*" >&2; exit 1; }

# ROS 2's setup scripts expand unset variables, so they cannot be sourced under `set -u`.
set +u
# shellcheck disable=SC1090
source "${ROS_SETUP}"
set -u

# --- HEADLESS: 1 (default) = Gazebo server only; 0 = also start the GUI --------------
case "${HEADLESS:-1}" in
  1|true|yes) GUI=0 ;;
  0|false|no) GUI=1 ;;
  *) die "HEADLESS must be 1 (server only) or 0 (with GUI), got '${HEADLESS}'" ;;
esac

# --- Which drones to spawn --------------------------------------------------------------
shopt -s nullglob
configs=("${CONFIG_DIR}"/drone_*.env)
shopt -u nullglob
[[ -f "${CONFIG_DIR}/x500_common.env" ]] || die "${CONFIG_DIR}/x500_common.env is missing"
[[ ${#configs[@]} -gt 0 ]] || die "no drone_*.env found in ${CONFIG_DIR}; nothing to spawn"

# Numeric order (drone_2 before drone_10), whatever the glob returned.
mapfile -t configs < <(printf '%s\n' "${configs[@]}" | sort -V)

if [[ -n "${SWARM_DRONE_COUNT:-}" ]]; then
  [[ "${SWARM_DRONE_COUNT}" =~ ^[1-9][0-9]*$ ]] || die "SWARM_DRONE_COUNT must be a positive integer"
  (( SWARM_DRONE_COUNT <= ${#configs[@]} )) \
    || die "SWARM_DRONE_COUNT=${SWARM_DRONE_COUNT} but only ${#configs[@]} drone config(s) exist"
  configs=("${configs[@]:0:${SWARM_DRONE_COUNT}}")
fi

# shellcheck disable=SC1091
source "${CONFIG_DIR}/x500_common.env"
: "${PX4_GZ_WORLD:?x500_common.env must set PX4_GZ_WORLD}"
: "${PX4_SIM_MODEL:?x500_common.env must set PX4_SIM_MODEL}"
WORLD_FILE="${WORLD_DIR}/${PX4_GZ_WORLD}.sdf"
[[ -f "${WORLD_FILE}" ]] || die "world file ${WORLD_FILE} not found (PX4_GZ_WORLD=${PX4_GZ_WORLD})"
[[ -x "${PX4_BIN}" ]] || die "${PX4_BIN} not found — was the image built with 'make px4_sitl_default'?"

mkdir -p "${LOG_DIR}"

# --- rosbridge ----------------------------------------------------------------------------
log "starting rosbridge_websocket on :9090"
ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=9090 &
ROSBRIDGE_PID=$!

# --- Gazebo -------------------------------------------------------------------------------
# The server resolves `x500/model.sdf` (what PX4's gz_bridge asks it to spawn) through
# GZ_SIM_RESOURCE_PATH, so PX4's model directory has to be on it.
export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:+${GZ_SIM_RESOURCE_PATH}:}${PX4_DIR}/Tools/simulation/gz/models:${PX4_DIR}/Tools/simulation/gz/worlds:${WORLD_DIR}"

log "starting Gazebo server on ${WORLD_FILE}"
gz sim --verbose=1 -r -s "${WORLD_FILE}" > "${LOG_DIR}/gz-server.log" 2>&1 &
GZ_PID=$!

GZ_GUI_PID=""
if [[ "${GUI}" == "1" ]]; then
  log "HEADLESS=0: starting the Gazebo GUI (needs X11/Wayland passthrough — see README)"
  gz sim -g > "${LOG_DIR}/gz-gui.log" 2>&1 &
  GZ_GUI_PID=$!
else
  log "HEADLESS=1: Gazebo server only, no GUI"
fi

log "waiting up to ${GZ_WAIT_SECONDS}s for world '${PX4_GZ_WORLD}' to publish its clock"
for ((i = 0; i < GZ_WAIT_SECONDS; i++)); do
  if gz topic -l 2>/dev/null | grep -qx "/world/${PX4_GZ_WORLD}/clock"; then
    break
  fi
  kill -0 "${GZ_PID}" 2>/dev/null || { tail -n 50 "${LOG_DIR}/gz-server.log" >&2; die "gz server exited"; }
  sleep 1
done
gz topic -l 2>/dev/null | grep -qx "/world/${PX4_GZ_WORLD}/clock" \
  || { tail -n 50 "${LOG_DIR}/gz-server.log" >&2; die "world '${PX4_GZ_WORLD}' never came up"; }
log "world '${PX4_GZ_WORLD}' is running"

# --- PX4 SITL instances ------------------------------------------------------------------
sessions=()
for cfg in "${configs[@]}"; do
  # Each drone's variables are read in a subshell, so nothing leaks from one config
  # into the next; the subshell prints the three values this loop needs.
  read -r instance namespace pose < <(
    set +u
    # shellcheck disable=SC1090,SC1091
    source "${CONFIG_DIR}/x500_common.env"
    # shellcheck disable=SC1090
    source "${cfg}"
    printf '%s %s %s\n' "${PX4_INSTANCE:-}" "${ROS_NAMESPACE:-}" "${PX4_GZ_MODEL_POSE:-}"
  )
  [[ "${instance}" =~ ^[0-9]+$ ]] || die "${cfg}: PX4_INSTANCE must be a non-negative integer"
  [[ -n "${namespace}" ]] || die "${cfg}: ROS_NAMESPACE is required"
  [[ -n "${pose}" ]] || die "${cfg}: PX4_GZ_MODEL_POSE is required"

  # `px4 -i N` with no rootfs argument runs in build/px4_sitl_default/rootfs/N, so every
  # instance keeps its own parameters and dataman instead of sharing one directory.
  cmd=$(printf 'env PX4_GZ_STANDALONE=1 PX4_SIM_MODEL=%q PX4_GZ_WORLD=%q PX4_GZ_MODEL_POSE=%q %q -i %q' \
    "${PX4_SIM_MODEL}" "${PX4_GZ_WORLD}" "${pose}" "${PX4_BIN}" "${instance}")

  log "spawning ${namespace} (PX4 instance ${instance}, MAV_SYS_ID $((instance + 1))) at ${pose}"
  tmux new-session -d -s "${namespace}" -x 200 -y 50 "${cmd}"
  tmux pipe-pane -o -t "${namespace}" "cat >> ${LOG_DIR}/${namespace}.log"
  sessions+=("${namespace}")
done

# --- ROS 2 coordination: MAVROS per drone, controllers, dispatcher, aggregator ----------
# SWARM_COORDINATION=0 leaves PX4 bare (M0's console-only check, or bring-your-own nodes).
if [[ "${SWARM_COORDINATION:-1}" == "1" ]]; then
  [[ -f "${COORDINATION_SETUP}" ]] || die "${COORDINATION_SETUP} not found — was swarm_coordination built into the image?"
  coordination=$(printf 'set +u; source %q; source %q; exec ros2 launch swarm_coordination spawn_swarm.launch.py with_mavros:=true px4_config_dir:=%q drone_count:=%q' \
    "${ROS_SETUP}" "${COORDINATION_SETUP}" "${CONFIG_DIR}" "${#configs[@]}")
  log "starting swarm_coordination for ${#configs[@]} drone(s): MAVROS, controllers, dispatcher, aggregator"
  tmux new-session -d -s coordination -x 200 -y 50 "bash -c $(printf '%q' "${coordination}")"
  tmux pipe-pane -o -t coordination "cat >> ${LOG_DIR}/coordination.log"
  sessions+=("coordination")
else
  log "SWARM_COORDINATION=0: PX4 only, no ROS 2 coordination nodes"
fi

log "${#sessions[@]} session(s) running; rosbridge on :9090"
log "attach to a console with: docker compose exec sim tmux attach -t <name>"
log "sessions: ${sessions[*]}"

shutdown() {
  log "shutting down"
  for s in "${sessions[@]}"; do
    tmux kill-session -t "${s}" 2>/dev/null || true
  done
  if [[ -n "${GZ_GUI_PID}" ]]; then
    kill "${GZ_GUI_PID}" 2>/dev/null || true
  fi
  kill "${GZ_PID}" "${ROSBRIDGE_PID}" 2>/dev/null || true
}
trap shutdown TERM INT

# Everything above runs detached; poll for the container's real work (rosbridge, the
# Gazebo server and every PX4 session) rather than `wait`, which has no tmux session
# to wait on.
while true; do
  if ! kill -0 "${ROSBRIDGE_PID}" 2>/dev/null; then
    log "rosbridge exited; shutting down" >&2
    shutdown
    exit 1
  fi
  if ! kill -0 "${GZ_PID}" 2>/dev/null; then
    tail -n 50 "${LOG_DIR}/gz-server.log" >&2 || true
    log "Gazebo server exited; shutting down" >&2
    shutdown
    exit 1
  fi
  for s in "${sessions[@]}"; do
    if ! tmux has-session -t "${s}" 2>/dev/null; then
      tail -n 50 "${LOG_DIR}/${s}.log" >&2 || true
      log "session ${s} exited; shutting down" >&2
      shutdown
      exit 1
    fi
  done
  sleep 2
done
