using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using SwarmApi.Application;
using SwarmApi.Domain;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>
/// Exercises <see cref="ServiceCollectionExtensions.AddSwarmAuthentication"/> directly
/// against a bare <see cref="ServiceCollection"/>, deliberately not through
/// <c>WebApplicationFactory</c>: <c>Program.cs</c> reads <c>Auth:Authority</c>
/// synchronously before <c>WebApplicationBuilder.Build()</c> runs, and
/// <c>WebApplicationFactory</c>'s <c>ConfigureAppConfiguration</c> override is only
/// merged in at <c>Build()</c> time — too late to affect that read. Testing the
/// registration function directly is deterministic and needs no web host; the JWT
/// bearer 401 behavior itself is framework-guaranteed, not bespoke logic. See
/// docs/adr/0005-mcp-server-and-bearer-auth.md.
/// </summary>
public class AuthenticationRegistrationTests
{
    private static IConfiguration BuildConfiguration(string? authority) =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Auth:Authority"] = authority,
            })
            .Build();

    [Fact]
    public void Open_mode_is_registered_when_authority_is_not_configured()
    {
        var services = new ServiceCollection();

        services.AddSwarmAuthentication(BuildConfiguration(null), NullLogger.Instance);
        using var provider = services.BuildServiceProvider();

        var status = provider.GetRequiredService<AuthStatus>();
        Assert.Equal(AuthMode.Open, status.Mode);
    }

    [Fact]
    public void Enforced_mode_is_registered_when_authority_is_configured()
    {
        var services = new ServiceCollection();

        services.AddSwarmAuthentication(BuildConfiguration("https://authservice.invalid"), NullLogger.Instance);
        using var provider = services.BuildServiceProvider();

        var status = provider.GetRequiredService<AuthStatus>();
        Assert.Equal(AuthMode.Enforced, status.Mode);
    }
}
