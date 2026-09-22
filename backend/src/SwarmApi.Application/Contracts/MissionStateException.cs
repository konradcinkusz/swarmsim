namespace SwarmApi.Application.Contracts;

/// <summary>The mission exists but its current status does not allow the operation (e.g. aborting a completed mission); mapped to 409.</summary>
public sealed class MissionStateException(string message) : Exception(message);

/// <summary>The swarm cannot be reached right now (bridge disconnected); mapped to 503 so a caller retries later instead of assuming success.</summary>
public sealed class SwarmUnavailableException(string message, Exception? inner = null) : Exception(message, inner);
