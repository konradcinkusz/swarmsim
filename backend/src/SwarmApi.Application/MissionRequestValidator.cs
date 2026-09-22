using SwarmApi.Application.Contracts;

namespace SwarmApi.Application;

public static class MissionRequestValidator
{
    /// <summary>The default drone ceiling, kept for callers that predate <see cref="MissionLimits"/>.</summary>
    public const int MaxDroneCount = 5;

    /// <summary>
    /// Validates a <see cref="CreateMissionRequest"/> against <paramref name="limits"/> (the
    /// defaults when omitted), throwing <see cref="MissionValidationException"/> with every
    /// failing rule — not just the first — so a caller fixes its request in one round trip.
    /// </summary>
    public static void Validate(CreateMissionRequest request, MissionLimits? limits = null)
    {
        limits ??= MissionLimits.Default;
        var errors = new List<string>();

        if (string.IsNullOrWhiteSpace(request.Name))
        {
            errors.Add("Name is required.");
        }
        else if (request.Name.Length > limits.MaxNameLength)
        {
            errors.Add($"Name must be at most {limits.MaxNameLength} characters.");
        }

        if (request.Type is not ("waypoint" or "formation"))
        {
            errors.Add("Type must be 'waypoint' or 'formation'.");
        }

        if (request.Formation is not (null or "line" or "v"))
        {
            errors.Add("Formation must be 'line' or 'v' when given.");
        }

        if (request.DroneCount < 1 || request.DroneCount > limits.MaxDroneCount)
        {
            errors.Add($"DroneCount must be between 1 and {limits.MaxDroneCount}.");
        }

        if (!double.IsFinite(request.SpacingMeters) || request.SpacingMeters <= 0)
        {
            errors.Add("SpacingMeters must be a positive, finite number.");
        }

        if (request.Waypoints is null || request.Waypoints.Count == 0)
        {
            errors.Add("At least one waypoint is required.");
        }
        else
        {
            if (request.Waypoints.Count > limits.MaxWaypoints)
            {
                errors.Add($"At most {limits.MaxWaypoints} waypoints are allowed.");
            }

            for (var i = 0; i < request.Waypoints.Count; i++)
            {
                var w = request.Waypoints[i];
                if (!double.IsFinite(w.X) || !double.IsFinite(w.Y) || !double.IsFinite(w.Z))
                {
                    errors.Add($"Waypoint {i} must have finite coordinates.");
                    continue;
                }

                if (w.Z <= 0 || w.Z > limits.MaxAltitudeMeters)
                {
                    errors.Add($"Waypoint {i} altitude must be above 0 and at most {limits.MaxAltitudeMeters} m.");
                }

                if (Math.Sqrt((w.X * w.X) + (w.Y * w.Y)) > limits.GeofenceRadiusMeters)
                {
                    errors.Add($"Waypoint {i} lies outside the {limits.GeofenceRadiusMeters} m geofence.");
                }
            }
        }

        if (errors.Count > 0)
        {
            throw new MissionValidationException(errors);
        }
    }
}
