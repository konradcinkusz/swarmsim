namespace SwarmApi.Domain;

/// <summary>
/// Pure position math shared by every mission-movement implementation
/// (<c>SimulatedSwarmBridge</c> today; a future in-process planner tomorrow).
/// Deliberately the same shape as <c>swarm_coordination/trajectory.py</c>'s
/// <c>step_towards</c> — two independent implementations of one idea, not one
/// canonical implementation and a stub. See docs/adr/0003.
/// </summary>
public static class Trajectory
{
    /// <summary>
    /// Moves <paramref name="current"/> towards <paramref name="target"/> by at most
    /// <paramref name="maxStep"/>. Returns <paramref name="target"/> exactly once
    /// within <paramref name="maxStep"/> of it, so a fixed-rate caller reaches the
    /// target in a finite, predictable number of calls.
    /// </summary>
    public static Vector3 StepTowards(Vector3 current, Vector3 target, double maxStep)
    {
        if (maxStep <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxStep), "maxStep must be positive.");
        }

        var delta = target - current;
        var distance = delta.Norm();
        return distance <= maxStep ? target : current + delta.Scale(maxStep / distance);
    }
}
