using System.Text;

namespace GLF.Neural;

public sealed class ScheduleResult
{
    public string Name = "";
    public double Makespan, BubbleFraction;
    public int[] PeakInFlight = Array.Empty<int>();
    public List<(double Start, string Op)>[] Timeline = Array.Empty<List<(double, string)>>();

    public string Render(double unit = 1)
    {
        var sb = new StringBuilder();
        int slots = (int)Math.Ceiling(Makespan / unit);
        for (int s = 0; s < Timeline.Length; s++)
        {
            var row = Enumerable.Repeat(" . ", slots).ToArray();
            foreach (var (start, op) in Timeline[s])
            {
                int i = (int)Math.Round(start / unit);
                if (i < slots) row[i] = op.Length == 2 ? " " + op : op.PadLeft(3);
            }
            sb.AppendLine($"  stage {s}: " + string.Concat(row));
        }
        return sb.ToString();
    }
}

/// <summary>Discrete-event simulation of pipeline schedules: dependencies, idle "bubbles" and activation memory.</summary>
public static class Pipeline
{
    public static ScheduleResult Simulate(string name, int stages, int micro, bool oneFOneB, double fwd = 1, double bwd = 1)
    {
        var ops = new List<(bool Fwd, int Mb)>[stages];
        for (int s = 0; s < stages; s++)
        {
            ops[s] = new();
            if (!oneFOneB) { for (int m = 0; m < micro; m++) ops[s].Add((true, m)); for (int m = 0; m < micro; m++) ops[s].Add((false, m)); continue; }
            int warm = Math.Min(stages - s - 1, micro), nf = 0, nb = 0;
            for (int i = 0; i < warm; i++) ops[s].Add((true, nf++));
            while (nf < micro) { ops[s].Add((true, nf++)); ops[s].Add((false, nb++)); }
            while (nb < micro) ops[s].Add((false, nb++));
        }

        var fEnd = new double[stages, micro]; var bEnd = new double[stages, micro];
        for (int s = 0; s < stages; s++) for (int m = 0; m < micro; m++) fEnd[s, m] = bEnd[s, m] = double.NaN;
        var free = new double[stages]; var next = new int[stages];
        var timeline = new List<(double, string)>[stages];
        for (int s = 0; s < stages; s++) timeline[s] = new();
        int done = 0, total = stages * micro * 2, guard = 0;
        while (done < total)
        {
            bool progress = false;
            for (int s = 0; s < stages; s++)
            {
                if (next[s] >= ops[s].Count) continue;
                var (isF, m) = ops[s][next[s]];
                double ready;
                if (isF) ready = s == 0 ? 0 : fEnd[s - 1, m];
                else ready = s == stages - 1 ? fEnd[s, m] : bEnd[s + 1, m];
                if (double.IsNaN(ready)) continue;
                double start = Math.Max(free[s], ready), end = start + (isF ? fwd : bwd);
                if (isF) fEnd[s, m] = end; else bEnd[s, m] = end;
                free[s] = end; next[s]++; done++; progress = true;
                timeline[s].Add((start, (isF ? "F" : "B") + m));
            }
            if (!progress || ++guard > 1_000_000) throw new InvalidOperationException("pipeline deadlock");
        }

        double makespan = free.Max();
        var peak = new int[stages];
        for (int s = 0; s < stages; s++)
        {
            int cur = 0;
            foreach (var (_, op) in timeline[s].OrderBy(t => t.Item1)) { cur += op[0] == 'F' ? 1 : -1; peak[s] = Math.Max(peak[s], cur); }
        }
        return new ScheduleResult
        {
            Name = name, Makespan = makespan, BubbleFraction = 1 - micro * (fwd + bwd) / makespan,
            PeakInFlight = peak, Timeline = timeline,
        };
    }

    /// <summary>Closed form for either schedule with equal stage times: (P−1)/(M+P−1).</summary>
    public static double TheoreticalBubble(int stages, int micro) => (stages - 1.0) / (micro + stages - 1.0);
}

/// <summary>Per-GPU training memory (bytes) for mixed-precision Adam: 2Φ fp16 weights + 2Φ fp16 grads + 12Φ optimizer (fp32 master, m, v) = 16Φ.</summary>
public static class ZeroMemory
{
    public static double PerGpu(int stage, double phi, int nDp) => stage switch
    {
        0 => 2 * phi + 2 * phi + 12 * phi,
        1 => 2 * phi + 2 * phi + 12 * phi / nDp,
        2 => 2 * phi + (2 * phi + 12 * phi) / nDp,
        3 => (2 * phi + 2 * phi + 12 * phi) / nDp,
        _ => throw new ArgumentOutOfRangeException(nameof(stage)),
    };
}
