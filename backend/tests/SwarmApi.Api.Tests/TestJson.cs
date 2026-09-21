using System.Text.Json;
using System.Text.Json.Serialization;

namespace SwarmApi.Api.Tests;

/// <summary>
/// `PostAsJsonAsync`/`ReadFromJsonAsync` without explicit options use
/// `JsonSerializerDefaults.Web` but know nothing of `Program.cs`'s
/// `JsonStringEnumConverter` registration (that only applies to the server's own
/// `JsonOptions.SerializerOptions`) — so a test client parsing `Mission.Type` back out
/// of the response needs the same converter, explicitly, or it throws on the enum.
/// </summary>
internal static class TestJson
{
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        Converters = { new JsonStringEnumConverter() },
    };
}
