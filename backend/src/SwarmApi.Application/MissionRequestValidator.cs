using SwarmApi.Application.Contracts;

namespace SwarmApi.Application;

public static class MissionRequestValidator
{
    public const int MaxDroneCount = 5; // M1's own scope ("3-5 instancji"); raise deliberately, not silently.

    /// <summary>
    /// Validates a <see cref="CreateMissionRequest"/>, throwing <see cref="MissionValidationException"/>
    /// with every failing rule (not just the first) so a caller fixes its request in one round trip.
    /// </summary>
    public static void Validate(CreateMissionRequest request)
    {
        var errors = new List<string>();

        if (string.IsNullOrWhiteSpace(request.Name))
        {
            errors.Add("Name is required.");
        }

        if (request.Type is not ("waypoint" or "formation"))
        {
            errors.Add("Type must be 'waypoint' or 'formation'.");
        }

        if (request.DroneCount < 1 || request.DroneCount > MaxDroneCount)
        {
            errors.Add($"DroneCount must be between 1 and {MaxDroneCount}.");
        }

        if (request.Waypoints is null || request.Waypoints.Count == 0)
        {
            errors.Add("At least one waypoint is required.");
        }

        if (request.SpacingMeters <= 0)
        {
            errors.Add("SpacingMeters must be positive.");
        }

        if (errors.Count > 0)
        {
            throw new MissionValidationException(errors);
        }
    }
}
