using System.Runtime.InteropServices;

namespace GLF.Core;

/// <summary>Best-effort tuning for latency-critical threads: affinity + priority.</summary>
public static class HotThread
{
    [DllImport("libc", SetLastError = true)]
    static extern int sched_setaffinity(int pid, nint cpusetsize, ref ulong mask);

    [DllImport("kernel32.dll")] static extern nint GetCurrentThread();
    [DllImport("kernel32.dll")] static extern nuint SetThreadAffinityMask(nint h, nuint mask);

    public static bool Prepare(int core)
    {
        try
        {
            Thread.CurrentThread.Priority = ThreadPriority.Highest;
            if (core < 0 || core >= 64) return false;
            ulong mask = 1UL << core;
            if (OperatingSystem.IsLinux()) return sched_setaffinity(0, sizeof(ulong), ref mask) == 0;
            if (OperatingSystem.IsWindows()) return SetThreadAffinityMask(GetCurrentThread(), (nuint)mask) != 0;
        }
        catch { }
        return false;
    }
}
