namespace GLF.Neural.Transformer;

/// <summary>Раздел V: temperature, top-k and nucleus (top-p) sampling over logits.</summary>
public static class Sampler
{
    public static int Sample(ReadOnlySpan<float> logits, float temperature, int topK, float topP, ref Rng rng)
    {
        int V = logits.Length;
        if (temperature <= 1e-4f)
        {
            int arg = 0;
            for (int i = 1; i < V; i++) if (logits[i] > logits[arg]) arg = i;
            return arg;
        }
        var lg = logits.ToArray();
        var idx = new int[V]; var p = new double[V];
        for (int i = 0; i < V; i++) idx[i] = i;
        Array.Sort(idx, (a, b) => lg[b].CompareTo(lg[a])); // descending by logit

        int keep = topK > 0 ? Math.Min(topK, V) : V;
        double max = lg[idx[0]] / temperature, sum = 0;
        for (int r = 0; r < keep; r++) { p[r] = Math.Exp(lg[idx[r]] / temperature - max); sum += p[r]; }
        for (int r = 0; r < keep; r++) p[r] /= sum;

        if (topP > 0 && topP < 1)
        {
            double cum = 0; int n = 0;
            while (n < keep) { cum += p[n++]; if (cum >= topP) break; }
            keep = n; sum = 0;
            for (int r = 0; r < keep; r++) sum += p[r];
            for (int r = 0; r < keep; r++) p[r] /= sum;
        }

        double u = rng.NextDouble(), acc = 0;
        for (int r = 0; r < keep; r++) { acc += p[r]; if (u <= acc) return idx[r]; }
        return idx[keep - 1];
    }
}
