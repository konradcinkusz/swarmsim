namespace SwarmApi.Application.Contracts;

/// <summary>
/// Optional body of <c>POST /api/missions/{id}/abort</c>: what the swarm does instead.
/// <c>"rtl"</c> (default) returns to launch and lands, <c>"land"</c> lands in place,
/// <c>"hold"</c> stops and hovers.
/// </summary>
public sealed record AbortMissionRequest(string? Action = null);
