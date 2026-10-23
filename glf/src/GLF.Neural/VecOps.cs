using System.Numerics;

namespace GLF.Neural;

/// <summary>SIMD primitives (System.Numerics.Vector) used by every layer.</summary>
public static class VecOps
{
    public static float Dot(ReadOnlySpan<float> a, ReadOnlySpan<float> b)
    {
        int n = a.Length, i = 0;
        float s = 0;
        if (Vector.IsHardwareAccelerated && n >= Vector<float>.Count)
        {
            var acc = Vector<float>.Zero;
            int w = Vector<float>.Count;
            for (; i <= n - w; i += w) acc += new Vector<float>(a.Slice(i)) * new Vector<float>(b.Slice(i));
            s = Vector.Sum(acc);
        }
        for (; i < n; i++) s += a[i] * b[i];
        return s;
    }

    /// <summary>y += alpha * x</summary>
    public static void Axpy(float alpha, ReadOnlySpan<float> x, Span<float> y)
    {
        int n = x.Length, i = 0;
        if (Vector.IsHardwareAccelerated && n >= Vector<float>.Count)
        {
            int w = Vector<float>.Count;
            var va = new Vector<float>(alpha);
            for (; i <= n - w; i += w)
                (new Vector<float>(y.Slice(i)) + va * new Vector<float>(x.Slice(i))).CopyTo(y.Slice(i));
        }
        for (; i < n; i++) y[i] += alpha * x[i];
    }
}

/// <summary>Small deterministic RNG (xorshift64*) so training is reproducible and allocation-free.</summary>
public struct Rng
{
    ulong _s;
    public Rng(ulong seed) { _s = seed * 0x9E3779B97F4A7C15UL + 0x1234567UL; if (_s == 0) _s = 1; }

    public ulong NextU64() { _s ^= _s >> 12; _s ^= _s << 25; _s ^= _s >> 27; return _s * 0x2545F4914F6CDD1DUL; }
    public double NextDouble() => (NextU64() >> 11) * (1.0 / (1UL << 53));
    public int NextInt(int n) => (int)((NextU64() >> 33) % (ulong)n);
    public float NextGaussian()
    {
        double u = Math.Max(NextDouble(), 1e-12), v = NextDouble();
        return (float)(Math.Sqrt(-2 * Math.Log(u)) * Math.Cos(2 * Math.PI * v));
    }
}
