using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using SwarmApi.Application;
using SwarmApi.Domain;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>
/// Exercises <see cref="ServiceCollectionExtensions.AddSwarmAuthentication"/> directly
/// against a bare <see cref="ServiceCollection"/>: which <see cref="AuthStatus"/> a given
/// configuration registers, and how the JWT bearer options are shaped. What an
/// unauthenticated caller can reach through the real host is covered separately by
/// <see cref="EnforcedAuthEndpointTests"/>. See docs/adr/0005-mcp-server-and-bearer-auth.md.
/// </summary>
public class AuthenticationRegistrationTests
{
    private static IConfiguration BuildConfiguration(string? authority, string? requireHttpsMetadata = null) =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Auth:Authority"] = authority,
                ["Auth:RequireHttpsMetadata"] = requireHttpsMetadata,
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

    [Fact]
    public void Https_metadata_is_required_unless_explicitly_disabled()
    {
        var defaults = BearerOptions(BuildConfiguration("https://authservice.invalid"));
        var disabled = BearerOptions(BuildConfiguration("http://authservice:8080", requireHttpsMetadata: "false"));

        Assert.True(defaults.RequireHttpsMetadata);
        Assert.False(disabled.RequireHttpsMetadata);
        Assert.Equal("http://authservice:8080/.well-known/openid-configuration", disabled.MetadataAddress);
    }

    private static JwtBearerOptions BearerOptions(IConfiguration configuration)
    {
        var services = new ServiceCollection();
        services.AddSwarmAuthentication(configuration, NullLogger.Instance);
        using var provider = services.BuildServiceProvider();
        return provider.GetRequiredService<IOptionsMonitor<JwtBearerOptions>>().Get(JwtBearerDefaults.AuthenticationScheme);
    }
}
