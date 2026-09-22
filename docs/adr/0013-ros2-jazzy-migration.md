# ADR-0013: Move the simulation image to ROS 2 Jazzy before Humble's end of life

## Status

Accepted (2026-09-22). Deadline-driven: **start by January 2027, finish before May 2027.**

## Context

The simulation image (ADR-0001) is built on ROS 2 Humble and Ubuntu 22.04. Humble's
support ends in May 2027. After that date the image keeps building — until an upstream
package or key rotation breaks it — but it gets no security fixes, and a customer's
security review (ADR-0006, ADR-0012) will ask exactly that question.

The successor is ROS 2 Jazzy (Ubuntu 24.04, supported to May 2029). Three things this
repository does by hand today are, on Jazzy, what the distribution does for you. This is
what rosdistro's `jazzy/distribution.yaml` said on 2026-09-22:

- **Gazebo Harmonic is Jazzy's own pairing.** Jazzy ships Harmonic through
  `gz_sim_vendor` (0.0.13) and `ros_gz` 1.0.24. Humble's pairing is Fortress, which is
  why the Humble image adds the OSRF repository and installs `gz-harmonic` explicitly.
  On Jazzy that detour goes.
- **MAVROS is released for Jazzy** (2.15.1-1, the same version the image pins). On Humble
  the image builds MAVROS and the mavlink messages from their release tags, because the
  Humble apt repository had no MAVROS binary even though rosdistro releases one. Whether
  Jazzy's apt repository carries the binary is checked, not assumed, when the work starts.
- **rosbridge_suite** is released for Jazzy (2.7.1).

What carries over unchanged is everything above the ROS boundary:
- the rclpy-free modules and their tests, the L0 scenarios, the API;
- the rosbridge contracts, which are plain JSON on `std_msgs/String`.

What needs checking:
- PX4's own `Tools/setup/ubuntu.sh` on 24.04, for the pinned (or a newer) `PX4_VERSION`;
- NumPy: PX4's pip installs must still stay out of the runtime stage (the Humble image's
  NumPy 2 lesson);
- MAVROS's topic and service names, which the nodes and `px4_config.MAVROS_PLUGINS` rely
  on.

## Decision

- **The distribution becomes a build argument** — `ROS_DISTRO` for `docker/Dockerfile.sim`
  (`humble` | `jazzy`) — rather than a second Dockerfile. The OSRF-repository and
  MAVROS-from-source steps become conditional on Humble.
- **Both are flown by the SITL smoke during the migration**, as a matrix over `ROS_DISTRO`,
  nightly. Jazzy becomes the default when its smoke is as green as Humble's.
- **Humble is dropped before May 2027.** The Dockerfile's comments, ADR-0001, the README
  and CLAUDE.md name one distribution again.
- **Deadline, not trigger.** Every other deferred item here waits on an event; this one
  waits on a date, because the event — end of support — does not announce itself in the
  build.

## Consequences

- For a few months the image is built twice a night. The GHCR layer cache keeps a warm
  build to minutes, and the cold build runs once per distribution.
- The Humble-only knowledge in CLAUDE.md goes when Humble goes: Garden versus Harmonic,
  the missing MAVROS binary. The NumPy 2 lesson stays, because it comes from PX4's
  installer, not from ROS.
- If PX4's setup script does not support 24.04 for the pinned version, the migration
  moves `PX4_VERSION` too. That is a flight-stack change, and it gets its own SITL-smoke
  evidence before the default switches.

Worked example: `docker/Dockerfile.sim` (the stages this changes), `.github/workflows/sim-smoke.yml`.
