#!/usr/bin/env bash
# Prints what each PX4 instance believes about itself: the parameters that choose its
# height reference, its estimator's local position and flags, the ground truth next to
# it, home, GNSS, barometer and land detector. The SITL smoke pipes it into the running
# sim container after every run, so a failure can be read from the job log alone:
#
#   docker compose exec -T sim bash -s -- 3 < docker/tests/px4_state.sh
#
# Diagnostics only: every command may fail (a crashed instance, a topic never
# published) and the script carries on.
set -uo pipefail

count="${1:-1}"
bin="${PX4_DIR:-/opt/PX4-Autopilot}/build/px4_sitl_default/bin"

# Who is using the CPU: three PX4 instances, Gazebo, MAVROS and the ROS nodes share a
# 4-CPU runner, and a starved estimator looks like a broken one.
echo "=== top"
top -b -n 1 -w 160 2>&1 | head -n 30 || true

for ((i = 0; i < count; i++)); do
  echo "=== PX4 instance ${i} (drone_$((i + 1))) ==="
  for param in EKF2_HGT_REF EKF2_GPS_CTRL EKF2_BARO_CTRL; do
    timeout 10 "${bin}/px4-param" --instance "${i}" show "${param}" 2>&1 | grep "${param}" || true
  done
  for topic in vehicle_local_position vehicle_local_position_groundtruth home_position \
    estimator_status estimator_status_flags vehicle_gps_position vehicle_air_data \
    vehicle_land_detected; do
    echo "--- ${topic}"
    timeout 10 "${bin}/px4-listener" --instance "${i}" "${topic}" -n 1 2>&1 || true
  done
done
