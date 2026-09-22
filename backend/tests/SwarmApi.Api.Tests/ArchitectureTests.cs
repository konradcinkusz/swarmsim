using System.Reflection;
using SwarmApi.Application;
using SwarmApi.Domain;
using SwarmApi.Infrastructure;
using Xunit;

namespace SwarmApi.Api.Tests;

/// <summary>
/// The mechanical half of architecture-standards P2 and the layering in
/// docs/architecture/README.md: stating the rules in prose has already failed twice in
/// the estate, so they are asserted here instead. The kernel's size ceiling is the other
/// half and lives in CI (`.github/workflows/ci.yml`, job `dotnet`), because it counts
/// source lines rather than types.
/// </summary>
public class ArchitectureTests
{
    private static readonly Assembly Domain = typeof(Mission).Assembly;
    private static readonly Assembly Application = typeof(MissionService).Assembly;
    private static readonly Assembly Infrastructure = typeof(RosBridgeOptions).Assembly;
    private static readonly Assembly Kernel = typeof(SwarmApi.ServiceDefaults.Extensions).Assembly;

    private static IReadOnlySet<string> SwarmApiReferences(Assembly assembly) =>
        assembly.GetReferencedAssemblies()
            .Select(reference => reference.Name ?? string.Empty)
            .Where(name => name.StartsWith("SwarmApi.", StringComparison.Ordinal))
            .ToHashSet();

    [Fact]
    public void The_shared_kernel_references_no_other_SwarmApi_project()
    {
        Assert.Empty(SwarmApiReferences(Kernel));
    }

    [Fact]
    public void The_shared_kernel_exports_only_static_extension_classes()
    {
        // No entity, DTO, enum or record may live in the kernel (P2): its public surface is
        // extension methods over the host builder, and nothing a service could inherit from.
        var offenders = Kernel.GetExportedTypes()
            .Where(type => !(type.IsAbstract && type.IsSealed))
            .Select(type => type.FullName)
            .ToList();

        Assert.Empty(offenders);
    }

    [Fact]
    public void Layers_depend_inwards_only()
    {
        Assert.Empty(SwarmApiReferences(Domain));
        Assert.Equal(new HashSet<string> { "SwarmApi.Domain" }, SwarmApiReferences(Application));
        Assert.DoesNotContain("SwarmApi.Api", SwarmApiReferences(Infrastructure));
        Assert.DoesNotContain("SwarmApi.ServiceDefaults", SwarmApiReferences(Infrastructure));
    }
}
