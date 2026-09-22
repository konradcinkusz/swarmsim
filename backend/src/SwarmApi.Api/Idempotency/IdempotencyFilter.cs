using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using HttpJsonOptions = Microsoft.AspNetCore.Http.Json.JsonOptions;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;

namespace SwarmApi.Api.Idempotency;

/// <summary>
/// Honours a client-supplied <c>Idempotency-Key</c> on a write (architecture-standards
/// SERVICE-API-PATTERNS, "A write that timed out is not a write that failed"): the first
/// request with a key runs; a replay of the same request returns the stored answer, marked
/// <c>Idempotency-Replayed: true</c>, instead of running again; the same key with a different
/// request is refused (422), and one still running is 409. A 5xx answer is not stored — it
/// says nothing definite happened — so a retry with the same key runs again. Keys are scoped
/// to the caller, the method and the path. No key: the request runs as it always did.
/// </summary>
public sealed partial class IdempotencyFilter(IdempotencyStore store, IOptions<HttpJsonOptions> json) : IEndpointFilter
{
    public const string HeaderName = "Idempotency-Key";
    public const string ReplayedHeaderName = "Idempotency-Replayed";

    public async ValueTask<object?> InvokeAsync(EndpointFilterInvocationContext context, EndpointFilterDelegate next)
    {
        var http = context.HttpContext;
        var key = http.Request.Headers[HeaderName].ToString();
        if (key.Length == 0)
        {
            return await next(context);
        }

        if (!WellFormedKey().IsMatch(key))
        {
            return Results.Problem(
                "Idempotency-Key must be 1–200 characters of letters, digits, '-', '_', '.' or ':'.",
                statusCode: StatusCodes.Status400BadRequest,
                title: "Invalid Idempotency-Key");
        }

        var scope = string.Join('\n', Caller.Subject(http.User) ?? "anonymous", http.Request.Method, http.Request.Path.Value, key);
        var (outcome, stored) = store.Begin(scope, Fingerprint(context.Arguments));
        switch (outcome)
        {
            case IdempotencyStore.Outcome.Replay:
                http.Response.Headers[ReplayedHeaderName] = "true";
                return Replay(http, stored!);
            case IdempotencyStore.Outcome.InFlight:
                return Results.Problem(
                    "A request with this Idempotency-Key is still being processed; retry once it has finished.",
                    statusCode: StatusCodes.Status409Conflict,
                    title: "Request in progress");
            case IdempotencyStore.Outcome.Mismatch:
                return Results.Problem(
                    "This Idempotency-Key was already used for a different request; use a new key for a new request.",
                    statusCode: StatusCodes.Status422UnprocessableEntity,
                    title: "Idempotency-Key reused");
        }

        object? result;
        try
        {
            result = await next(context);
        }
        catch
        {
            store.Abandon(scope);
            throw;
        }

        var response = Capture(result);
        if (response.StatusCode >= 500)
        {
            store.Abandon(scope);
        }
        else
        {
            store.Complete(scope, response);
        }

        return result;
    }

    private string Fingerprint(IList<object?> arguments)
    {
        // What the endpoint was asked to do: its bound route values and body, not the
        // services and cancellation tokens it was handed.
        var request = arguments
            .Where(a => a is Guid or string || a?.GetType().Namespace == "SwarmApi.Application.Contracts")
            .ToArray();
        var bytes = JsonSerializer.SerializeToUtf8Bytes(request, json.Value.SerializerOptions);
        return Convert.ToHexString(SHA256.HashData(bytes));
    }

    private IdempotencyStore.StoredResponse Capture(object? result)
    {
        var status = result is IStatusCodeHttpResult { StatusCode: { } code } ? code : StatusCodes.Status200OK;
        var value = result switch
        {
            IValueHttpResult valueResult => valueResult.Value,
            IResult => null,
            _ => result,
        };
        var body = value is null ? null : JsonSerializer.Serialize(value, value.GetType(), json.Value.SerializerOptions);
        var contentType = value is ProblemDetails ? "application/problem+json" : "application/json";
        var location = result?.GetType().GetProperty("Location")?.GetValue(result) as string;
        return new IdempotencyStore.StoredResponse(status, body, contentType, location);
    }

    private static IResult Replay(HttpContext http, IdempotencyStore.StoredResponse stored)
    {
        if (stored.Location is not null)
        {
            http.Response.Headers.Location = stored.Location;
        }

        return stored.Body is null
            ? Results.StatusCode(stored.StatusCode)
            : Results.Text(stored.Body, stored.ContentType, Encoding.UTF8, stored.StatusCode);
    }

    [GeneratedRegex("^[A-Za-z0-9._:-]{1,200}$")]
    private static partial Regex WellFormedKey();
}

/// <summary>Endpoint metadata: this write honours <c>Idempotency-Key</c> (checked by ApiSurfaceTests).</summary>
public sealed class IdempotentWriteMetadata
{
    public static readonly IdempotentWriteMetadata Instance = new();
}

public static class IdempotencyEndpointExtensions
{
    /// <summary>Makes a write replay-safe under a client-supplied <c>Idempotency-Key</c>.</summary>
    public static RouteHandlerBuilder WithIdempotency(this RouteHandlerBuilder builder) =>
        builder.AddEndpointFilter<IdempotencyFilter>().WithMetadata(IdempotentWriteMetadata.Instance);
}
