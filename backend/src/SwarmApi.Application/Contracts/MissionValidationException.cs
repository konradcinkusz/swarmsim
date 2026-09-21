namespace SwarmApi.Application.Contracts;

/// <summary>Thrown by <see cref="SwarmApi.Application.MissionRequestValidator"/>; mapped to 400 at the endpoint (P9: transport-only mapping).</summary>
public sealed class MissionValidationException(IReadOnlyList<string> errors)
    : Exception(string.Join(" ", errors))
{
    public IReadOnlyList<string> Errors { get; } = errors;
}
