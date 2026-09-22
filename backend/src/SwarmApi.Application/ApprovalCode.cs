using System.Security.Cryptography;
using System.Text;

namespace SwarmApi.Application;

/// <summary>
/// The single-use code an approval produces. 192 random bits from the OS CSPRNG, as
/// base64url; only its SHA-256 is kept, and a presented code is compared in constant time.
/// </summary>
public static class ApprovalCode
{
    public static string New() =>
        Convert.ToBase64String(RandomNumberGenerator.GetBytes(24)).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    public static byte[] Hash(string code) => SHA256.HashData(Encoding.UTF8.GetBytes(code));

    public static bool Matches(string? presented, byte[]? expectedHash) =>
        !string.IsNullOrEmpty(presented)
        && expectedHash is not null
        && CryptographicOperations.FixedTimeEquals(Hash(presented), expectedHash);
}
