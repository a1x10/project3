using System.Diagnostics;

namespace GLF.Core;

public static class Clock
{
    static readonly double NsPerTick = 1e9 / Stopwatch.Frequency;

    public static long Now() => Stopwatch.GetTimestamp();
    public static long ToNs(long ticks) => (long)(ticks * NsPerTick);
    public static long NowNs() => ToNs(Stopwatch.GetTimestamp());
}
