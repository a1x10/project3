namespace GLF.Trading.Models;

public readonly record struct Forecast(double Mean, double Disagreement, double Sigma, bool Ready);

/// <summary>Cumulative prequential squared errors; subtract two snapshots to get a window.</summary>
public sealed record AccuracySnapshot(string[] Names, double[] Sse, double EnsembleSse, double NaiveSse, long N)
{
    public static AccuracySnapshot operator -(AccuracySnapshot a, AccuracySnapshot b) =>
        new(a.Names, a.Sse.Zip(b.Sse, (x, y) => x - y).ToArray(), a.EnsembleSse - b.EnsembleSse, a.NaiveSse - b.NaiveSse, a.N - b.N);
    public double Rmse(int i) => N == 0 ? 0 : Math.Sqrt(Sse[i] / N);
    public double EnsembleRmse => N == 0 ? 0 : Math.Sqrt(EnsembleSse / N);
    public double NaiveRmse => N == 0 ? 0 : Math.Sqrt(NaiveSse / N);
}

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
    readonly int[] _regRing;
    readonly RegimeDetector _regimes = new(new[] { 0.4, 0.7 });   // context units: 0.4 ticks of average spread, a factor of e^0.7 in volatility
    readonly double[] _ctx = new double[2];
    double _prevMid, _volEma, _spreadEma;
    public int CurrentRegime => _regimes.Current;
    public int RegimeCount => _regimes.Count;
    public long RegimeSwitches => _regimes.Switches;

    public AccuracySnapshot Snapshot() => new(_h.Select(h => h.Name).ToArray(), _h.Select(h => h.Sse).ToArray(), _ensSse, _naiveSse, _scored);

    public int HypothesisCount => _h.Length;
    public double EnsembleRmse => _scored == 0 ? 0 : Math.Sqrt(_ensSse / _scored);
    /// <summary>RMSE of always predicting "no change" - the bar every forecast must beat.</summary>
    public double NaiveRmse => _scored == 0 ? 0 : Math.Sqrt(_naiveSse / _scored);

    public HypothesisEnsemble(int horizon, bool neural = true, bool regimeReplay = true, int dim = FeatureExtractor.Dim, int warmup = 300, ulong seed = 1)
    {
        Horizon = horizon; _warmup = warmup + horizon;
        _ring = new double[(horizon + 1) * dim];
        _mid = new double[horizon + 1];
        _regRing = new int[horizon + 1];
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
            if (regimeReplay)
                list.Add(new Hypothesis("nn-32x16+regime-replay", nIdx, new NeuralModel(nIdx.Length, new[] { 32, 16 }, 1e-3f, seed: seed, regimeMemory: true)));
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
        sb.AppendLine($"  {"hypothesis",-24} {"rmse(ticks)",11} {"weight",7}");
        foreach (var h in _h)
            sb.AppendLine($"  {h.Name,-24} {(_scored == 0 ? 0 : Math.Sqrt(h.Sse / _scored)),11:F3} {h.Weight,7:F2}");
        sb.AppendLine($"  {"ENSEMBLE",-24} {EnsembleRmse,11:F3}");
        sb.Append($"  {"no-change baseline",-24} {NaiveRmse,11:F3}");
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
                h.Model.Learn(h.Xs, y, _regRing[old]);
                if (h.Loss < minLoss) minLoss = h.Loss;
            }
            if (_n > _warmup) { _scored++; _ensSse += (y - ensOld) * (y - ensOld); _naiveSse += y * y; }
            double temp = 0.05 * minLoss + 1e-12, wsum = 0;
            foreach (var h in _h) { h.Weight = Math.Exp(-(h.Loss - minLoss) / temp); wsum += h.Weight; }
            foreach (var h in _h) h.Weight /= wsum;
        }

        // market context -> regime id attached to this sample (it is used when the sample's outcome becomes known)
        double dm = _n == 0 ? 0 : Math.Abs(midTicks - _prevMid);
        _prevMid = midTicks;
        _volEma = 0.995 * _volEma + 0.005 * dm;
        _spreadEma = 0.98 * _spreadEma + 0.02 * (dim > 6 ? x[6] : 0);
        _ctx[0] = _spreadEma; _ctx[1] = Math.Log(_volEma + 0.05);
        _regRing[slot] = _regimes.Update(_ctx);

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
