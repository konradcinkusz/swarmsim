#!/usr/bin/env bash
# Prints one "stalled drone_N ..." line for every PX4 instance whose simulated GNSS has
# stopped while the instance itself is still running. That is the signature of a PX4 v1.15
# gz SITL fault, not of anything this repository sends it (docs/adr/0004, 2026-09-23;
# upstream PX4-Autopilot#23130). The SITL smoke runs this after a failed flight, inside the
# sim container, and flies once more only if it prints a line:
#
#   docker compose exec -T sim bash -s -- 3 < docker/tests/px4_sensor_stall.sh
#
# Prints nothing, and exits 0, when no instance shows it.
set -uo pipefail

count="${1:-1}"
bin="${PX4_DIR:-/opt/PX4-Autopilot}/build/px4_sitl_default/bin"
stale_s=5

# Seconds since instance $1 last published topic $2, from px4-listener's
# "timestamp: 13808000 (419.279999 seconds ago)"; empty if it cannot tell.
age() {
  timeout 10 "${bin}/px4-listener" --instance "$1" "$2" -n 1 2>/dev/null |
    sed -n 's/.*timestamp: [0-9]* (\([0-9.]*\) seconds ago).*/\1/p' | head -n 1
}

for ((i = 0; i < count; i++)); do
  status=$(age "${i}" vehicle_status)
  gps=$(age "${i}" sensor_gps)
  if [ -z "${status}" ] || [ -z "${gps}" ]; then
    continue
  fi
  if awk -v s="${status}" -v g="${gps}" -v l="${stale_s}" 'BEGIN { exit !(s < 1 && g > l) }'; then
    echo "stalled drone_$((i + 1)): sensor_gps last published ${gps} s ago, vehicle_status ${status} s ago"
  fi
done
exit 0
