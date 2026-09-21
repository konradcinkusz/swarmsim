namespace SwarmApi.Domain;

/// <summary>A position or offset in the simulation's local ENU frame, in meters.</summary>
public readonly record struct Vector3(double X, double Y, double Z)
{
    public static readonly Vector3 Zero = new(0, 0, 0);

    public static Vector3 operator +(Vector3 a, Vector3 b) => new(a.X + b.X, a.Y + b.Y, a.Z + b.Z);

    public static Vector3 operator -(Vector3 a, Vector3 b) => new(a.X - b.X, a.Y - b.Y, a.Z - b.Z);

    public Vector3 Scale(double factor) => new(X * factor, Y * factor, Z * factor);

    public double Norm() => Math.Sqrt(X * X + Y * Y + Z * Z);

    public double DistanceTo(Vector3 other) => (this - other).Norm();
}
