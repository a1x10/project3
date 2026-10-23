using System.Numerics;
using System.Text;

namespace GLF.Core;

/// <summary>Allocation-free log-linear histogram of nanosecond latencies (8 sub-buckets per power of two).</summary>
public sealed class LatencyHistogram
{
    readonly long[] _b = new long[512];
    long _n, _max;

    public long Count => _n;
    public long MaxNs => _max;

    public void Record(long ns)
    {
        if (ns < 0) ns = 0;
        _b[Index(ns)]++;
        _n++;
        if (ns > _max) _max = ns;
    }

    static int Index(long v)
    {
        if (v < 8) return (int)v;
        int msb = 63 - BitOperations.LeadingZeroCount((ulong)v);
        return (msb - 2) * 8 + (int)((v >> (msb - 3)) & 7);
    }

    static long LowerBound(int idx)
    {
        if (idx < 8) return idx;
        int msb = idx / 8 + 2, sub = idx % 8;
        return (long)(8 + sub) << (msb - 3);
    }

    public long PercentileNs(double p)
    {
        if (_n == 0) return 0;
        long target = (long)Math.Ceiling(_n * p);
        long acc = 0;
        for (int i = 0; i < _b.Length; i++)
        {
            acc += _b[i];
            if (acc >= target) return Math.Min(LowerBound(i), _max);
        }
        return _max;
    }

    public string Summary(string name)
    {
        var sb = new StringBuilder();
        sb.Append($"{name}: n={_n} ");
        sb.Append($"p50={PercentileNs(.50) / 1000.0:F2}us p99={PercentileNs(.99) / 1000.0:F2}us ");
        sb.Append($"p99.9={PercentileNs(.999) / 1000.0:F2}us max={_max / 1000.0:F2}us");
        return sb.ToString();
    }
}
