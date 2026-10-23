namespace GLF.Trading.Models;

public readonly record struct Forecast(double Mean, double Disagreement, double Sigma, bool Ready);

/// <summary>
/// Several competing hypotheses (different feature subsets / memory lengths) learn the same target online:
/// mid-price change (in ticks) over the next <c>Horizon</c> events. Each hypothesis is weighted by its
/// recent out-of-sample error, so the ensemble shifts to whichever hypothesis explains the current regime.
/// </summary>
public sealed class HypothesisEnsemble
{
    sealed class Hypothesis
    {
        public readonly int[] Idx;
        public readonly Rls Model;
        public readonly double[] Xs;
        public double Loss = double.NaN, Weight, Pred;
        public Hypothesis(int[] idx, double lambda)
        {
            Idx = idx; Model = new Rls(idx.Length, lambda); Xs = new double[idx.Length];
        }
        public void Gather(ReadOnlySpan<double> x) { for (int i = 0; i < Idx.Length; i++) Xs[i] = x[Idx[i]]; }
    }

    public readonly int Horizon;
    readonly int _warmup;
    readonly Hypothesis[] _h;
    readonly double[] _ring;
    readonly double[] _mid;
    long _n;

    public int HypothesisCount => _h.Length;

    public HypothesisEnsemble(int horizon, int dim = FeatureExtractor.Dim, int warmup = 300)
    {
        Horizon = horizon; _warmup = warmup + horizon;
        _ring = new double[(horizon + 1) * dim];
        _mid = new double[horizon + 1];
        _h = new[]
        {
            new Hypothesis(new[] { 0, 1, 2, 3, 4, 5 }, 0.9995),
            new Hypothesis(new[] { 0, 1, 2, 3, 4, 5 }, 0.99),
            new Hypothesis(new[] { 0, 1, 2, 3 }, 0.9995),
            new Hypothesis(new[] { 0, 4, 5 }, 0.999),
            new Hypothesis(new[] { 0, 1, 3 }, 0.9999),
            new Hypothesis(new[] { 0, 2, 4 }, 0.998),
        };
        foreach (var h in _h) h.Weight = 1.0 / _h.Length;
    }

    public string Describe()
    {
        var parts = new string[_h.Length];
        for (int i = 0; i < _h.Length; i++) parts[i] = $"h{i}:w={_h[i].Weight:F2}";
        return string.Join(' ', parts);
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
            double minLoss = double.MaxValue;
            foreach (var h in _h)
            {
                h.Gather(xo);
                double err = y - h.Model.Predict(h.Xs);
                double e2 = err * err;
                h.Loss = double.IsNaN(h.Loss) ? e2 : 0.995 * h.Loss + 0.005 * e2;
                h.Model.Update(h.Xs, y);
                if (h.Loss < minLoss) minLoss = h.Loss;
            }
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
