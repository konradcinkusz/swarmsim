using System.Text.Json;

namespace SwarmApi.Infrastructure.Tests;

/// <summary>
/// Locates <c>contracts/rosbridge/</c> — the message files the Python side is tested
/// against too — by walking up from the test binaries to the repository root.
/// </summary>
internal static class ContractFiles
{
    private static readonly Lazy<string> RosBridgeDirectory = new(() =>
    {
        for (var dir = new DirectoryInfo(AppContext.BaseDirectory); dir is not null; dir = dir.Parent)
        {
            var candidate = Path.Combine(dir.FullName, "contracts", "rosbridge");
            if (Directory.Exists(candidate))
            {
                return candidate;
            }
        }

        throw new DirectoryNotFoundException("contracts/rosbridge not found above " + AppContext.BaseDirectory);
    });

    public static string Example(string name) =>
        File.ReadAllText(Path.Combine(RosBridgeDirectory.Value, "examples", name + ".json"));

    /// <summary>
    /// Semantic JSON equality: same properties, same values, numbers compared as numbers —
    /// so C#'s <c>5</c> and Python's <c>5.0</c> for the same double are the same message.
    /// Returns the path of the first difference, or null when equal.
    /// </summary>
    public static string? FirstDifference(JsonElement expected, JsonElement actual, string path = "$")
    {
        if (expected.ValueKind == JsonValueKind.Number && actual.ValueKind == JsonValueKind.Number)
        {
            return expected.GetDouble().Equals(actual.GetDouble()) ? null : path;
        }

        if (expected.ValueKind != actual.ValueKind)
        {
            return $"{path} ({expected.ValueKind} vs {actual.ValueKind})";
        }

        switch (expected.ValueKind)
        {
            case JsonValueKind.Object:
                var expectedNames = expected.EnumerateObject().Select(p => p.Name).ToHashSet();
                var actualNames = actual.EnumerateObject().Select(p => p.Name).ToHashSet();
                if (!expectedNames.SetEquals(actualNames))
                {
                    return $"{path} (properties {string.Join(",", expectedNames.Order())} vs {string.Join(",", actualNames.Order())})";
                }

                foreach (var property in expected.EnumerateObject())
                {
                    var difference = FirstDifference(property.Value, actual.GetProperty(property.Name), $"{path}.{property.Name}");
                    if (difference is not null)
                    {
                        return difference;
                    }
                }

                return null;
            case JsonValueKind.Array:
                var e = expected.EnumerateArray().ToList();
                var a = actual.EnumerateArray().ToList();
                if (e.Count != a.Count)
                {
                    return $"{path} (length {e.Count} vs {a.Count})";
                }

                for (var i = 0; i < e.Count; i++)
                {
                    var difference = FirstDifference(e[i], a[i], $"{path}[{i}]");
                    if (difference is not null)
                    {
                        return difference;
                    }
                }

                return null;
            default:
                return expected.GetRawText() == actual.GetRawText() ? null : path;
        }
    }
}
