#!/usr/bin/env bash
# Prints what each PX4 instance believes about itself: its arming and navigation state,
# whether offboard setpoints are arriving and how it answered the last command, the
# parameters that choose its height reference, its estimator's local position and flags,
# the ground truth next to it, home, GNSS, barometer and land detector. The SITL smoke
# pipes it into the running sim container after every run, so a failure can be read
# from the job log alone:
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
  for topic in vehicle_status offboard_control_mode vehicle_command_ack \
    vehicle_local_position vehicle_local_position_groundtruth home_position \
    estimator_status estimator_status_flags vehicle_gps_position vehicle_air_data \
    vehicle_land_detected failsafe_flags; do
    echo "--- ${topic}"
    timeout 10 "${bin}/px4-listener" --instance "${i}" "${topic}" -n 1 2>&1 || true
  done
  # The simulated GNSS, compass and battery are PX4 modules fed from gz_bridge's ground
  # truth. One run lost all three on one drone at arming while its IMU and barometer kept
  # coming: whether the ground truth stopped (Gazebo) or the modules did (PX4's work
  # queue) shows in the timestamps below and in each module's cycle count.
  for topic in sensor_gps sensor_mag battery_status vehicle_attitude_groundtruth \
    vehicle_global_position_groundtruth; do
    echo "--- ${topic}"
    timeout 10 "${bin}/px4-listener" --instance "${i}" "${topic}" -n 1 2>&1 | head -n 4 || true
  done
  echo "--- perf (simulation modules)"
  timeout 10 "${bin}/px4-perf" --instance "${i}" 2>&1 | grep -E "_sim|battery|gz_bridge" || true
done
