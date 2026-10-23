namespace GLF.Neural;

/// <summary>
/// Elastic Weight Consolidation: after a task, remember the weights θ* and how much the loss cares about each one
/// (diagonal empirical Fisher F). Later training pays a quadratic price λ/2 · Σ F_i (θ_i − θ*_i)² for moving important weights.
/// </summary>
public sealed class Ewc
{
    readonly List<float[]> _fisher = new(), _anchor = new();
    public float Lambda;
    public bool Active => _fisher.Count > 0;

    public Ewc(float lambda) => Lambda = lambda;

    public void Consolidate(Network net, float[] x, int[] labels, int samples)
    {
        _fisher.Clear(); _anchor.Clear();
        foreach (var p in net.Params) { _fisher.Add(new float[p.W.Length]); _anchor.Add((float[])p.W.Clone()); }
        int dim = net.In;
        for (int i = 0; i < samples; i++)
        {
            net.GradientsClassify(x.AsSpan(i * dim, dim), labels.AsSpan(i, 1), 1);
            for (int k = 0; k < net.Params.Count; k++)
            {
                var g = net.Params[k].G; var f = _fisher[k];
                for (int j = 0; j < g.Length; j++) f[j] += g[j] * g[j] / samples;
            }
        }
        net.BeforeStep = AddPenalty;
    }

    void AddPenalty(List<Param> ps)
    {
        for (int k = 0; k < ps.Count; k++)
        {
            var w = ps[k].W; var g = ps[k].G; var f = _fisher[k]; var a = _anchor[k];
            for (int j = 0; j < w.Length; j++) g[j] += Lambda * f[j] * (w[j] - a[j]);
        }
    }
}
