namespace GLF.Trading.Models;

public readonly record struct Forecast(double Mean, double Disagreement, double Sigma, bool Ready);

/// <summary>
/// Several competing hypotheses (linear / neural, different feature subsets and memory lengths) learn the same target online:
/// mid-price change (in ticks) over the next <c>Horizon</c> events. Each hypothesis is weighted by its
/// recent out-of-sample error, so the ensemble shifts to whichever hypothesis explains the current regime.
/// </summary>
public sealed class HypothesisEnsemble
{
    sealed class Hypothesis
    {
        public readonly string Name;
        public readonly int[] Idx;
        public readonly IOnlineModel Model;
        public readonly double[] Xs;
        public double Loss = double.NaN, Weight, Pred, Sse;
        public Hypothesis(string name, int[] idx, IOnlineModel model) { Name = name; Idx = idx; Model = model; Xs = new double[idx.Length]; }
        public void Gather(ReadOnlySpan<double> x) { for (int i = 0; i < Idx.Length; i++) Xs[i] = x[Idx[i]]; }
    }

    public readonly int Horizon;
    readonly int _warmup;
    readonly Hypothesis[] _h;
    readonly double[] _ring;
    readonly double[] _mid;
    long _n, _scored;
    double _ensSse, _naiveSse;

    public int HypothesisCount => _h.Length;
    public double EnsembleRmse => _scored == 0 ? 0 : Math.Sqrt(_ensSse / _scored);
    /// <summary>RMSE of always predicting "no change" - the bar every forecast must beat.</summary>
    public double NaiveRmse => _scored == 0 ? 0 : Math.Sqrt(_naiveSse / _scored);

    public HypothesisEnsemble(int horizon, bool neural = true, int dim = FeatureExtractor.Dim, int warmup = 300, ulong seed = 1)
    {
        Horizon = horizon; _warmup = warmup + horizon;
        _ring = new double[(horizon + 1) * dim];
        _mid = new double[horizon + 1];
        var list = new List<Hypothesis>
        {
            Lin("rls-all/0.9995", new[] { 0, 1, 2, 3, 4, 5, 6 }, 0.9995),
            Lin("rls-all/0.99", new[] { 0, 1, 2, 3, 4, 5, 6 }, 0.99),
            Lin("rls-book", new[] { 0, 1, 2, 3 }, 0.9995),
            Lin("rls-flow", new[] { 0, 4, 5 }, 0.999),
            Lin("rls-slow", new[] { 0, 1, 3 }, 0.9999),
            Lin("rls-depth+ofi", new[] { 0, 2, 4 }, 0.998),
        };
        if (neural)
        {
            var nIdx = new[] { 1, 2, 3, 4, 5, 6 };
            list.Add(new Hypothesis("nn-32x16", nIdx, new NeuralModel(nIdx.Length, new[] { 32, 16 }, 1e-3f, seed: seed)));
            list.Add(new Hypothesis("nn-16", nIdx, new NeuralModel(nIdx.Length, new[] { 16 }, 3e-3f, seed: seed + 1)));
        }
        _h = list.ToArray();
        foreach (var h in _h) h.Weight = 1.0 / _h.Length;
    }

    static Hypothesis Lin(string name, int[] idx, double lambda) => new(name, idx, new RlsModel(idx.Length, lambda));

    public string Describe()
    {
        var parts = new string[_h.Length];
        for (int i = 0; i < _h.Length; i++) parts[i] = $"{_h[i].Name}:w={_h[i].Weight:F2}";
        return string.Join(' ', parts);
    }

    /// <summary>Prequential accuracy: every sample is predicted first, then learned. Lower RMSE is better.</summary>
    public string Report()
    {
        var sb = new System.Text.StringBuilder();
        sb.AppendLine($"  {"hypothesis",-18} {"rmse(ticks)",11} {"weight",7}");
        foreach (var h in _h)
            sb.AppendLine($"  {h.Name,-18} {(_scored == 0 ? 0 : Math.Sqrt(h.Sse / _scored)),11:F3} {h.Weight,7:F2}");
        sb.AppendLine($"  {"ENSEMBLE",-18} {EnsembleRmse,11:F3}");
        sb.Append($"  {"no-change baseline",-18} {NaiveRmse,11:F3}");
        return sb.ToString();
    }

    public Forecast Step(ReadOnlySpan<double> x, double midTicks)
    {
        int dim = x.Length, H = Horizon;
        int slot = (int)(_n % (H + 1));

        if (_n >= H)
        {
            int old = (int)((_n - H) % (H + 1));
            double y = midTicks - _mid[old];
            var xo = _ring.AsSpan(old * dim, dim);
            double minLoss = double.MaxValue, ensOld = 0;
            foreach (var h in _h)
            {
                h.Gather(xo);
                double p = h.Model.Predict(h.Xs), err = y - p;
                ensOld += h.Weight * p;
                double e2 = err * err;
                h.Loss = double.IsNaN(h.Loss) ? e2 : 0.995 * h.Loss + 0.005 * e2;
                if (_n > _warmup) h.Sse += e2;
                h.Model.Learn(h.Xs, y);
                if (h.Loss < minLoss) minLoss = h.Loss;
            }
            if (_n > _warmup) { _scored++; _ensSse += (y - ensOld) * (y - ensOld); _naiveSse += y * y; }
            double temp = 0.05 * minLoss + 1e-12, wsum = 0;
            foreach (var h in _h) { h.Weight = Math.Exp(-(h.Loss - minLoss) / temp); wsum += h.Weight; }
            foreach (var h in _h) h.Weight /= wsum;
        }

        x.CopyTo(_ring.AsSpan(slot * dim, dim));
        _mid[slot] = midTicks;
        _n++;

        double mean = 0, sig2 = 0;
        foreach (var h in _h)
        {
            h.Gather(x);
            h.Pred = h.Model.Predict(h.Xs);
            mean += h.Weight * h.Pred;
            if (!double.IsNaN(h.Loss)) sig2 += h.Weight * h.Loss;
        }
        double var = 0;
        foreach (var h in _h) { double d = h.Pred - mean; var += h.Weight * d * d; }
        return new Forecast(mean, Math.Sqrt(var), Math.Sqrt(sig2), _n > _warmup);
    }
}
