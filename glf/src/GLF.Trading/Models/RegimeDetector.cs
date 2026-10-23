namespace GLF.Trading.Models;

/// <summary>
/// Online k-means over a small "market context" vector (e.g. average spread, log-volatility), measured in fixed units given by <c>scales</c>
/// (distance 1.0 = one scale unit; fixed units keep centroids comparable over time). Centroids are created when a context
/// is far from all known ones and then drift slowly, so a regime keeps its identity when the market returns to it.
/// A hysteresis margin stops the label from flickering on the border between two regimes.
/// </summary>
public sealed class RegimeDetector
{
    readonly int _maxK, _d;
    readonly double[][] _c;
    readonly double[] _z;
    readonly double[] _scale;
    long _n;
    readonly double _newDist, _lr, _stick;
    readonly int _dwell;
    int _k, _cand = -1, _candRun;

    public int Current { get; private set; }
    public int Count => _k;
    public long Switches { get; private set; }
    public double LastDistance { get; private set; }
    public int CandidateRun => _candRun;

    public RegimeDetector(double[] scales, int maxRegimes = 4, double newRegimeDistance = 1.6, double learningRate = 0.001, double stickiness = 0.8, int dwellEvents = 120)
    {
        _d = scales.Length; _scale = scales; _maxK = maxRegimes; _newDist = newRegimeDistance; _lr = learningRate; _stick = stickiness; _dwell = dwellEvents;
        _c = new double[maxRegimes][];
        for (int i = 0; i < maxRegimes; i++) _c[i] = new double[_d];
        _z = new double[_d];
    }

    double Dist(int k)
    {
        double s = 0;
        for (int i = 0; i < _d; i++) { double e = _z[i] - _c[k][i]; s += e * e; }
        return Math.Sqrt(s);
    }

    public int Update(ReadOnlySpan<double> ctx)
    {
        _n++;
        for (int i = 0; i < _d; i++) _z[i] = ctx[i] / _scale[i];
        if (_n < 1000) return Current;                           // the context averages are still warming up: anything found now is start-up noise

        if (_k == 0) { Array.Copy(_z, _c[0], _d); _k = 1; Current = 0; return 0; }

        int best = 0; double bd = double.MaxValue;
        for (int k = 0; k < _k; k++) { double d = Dist(k); if (d < bd) { bd = d; best = k; } }

        // A change (to a known regime or a brand-new one) must persist for _dwell events before the label moves: noise cannot flip it.
        LastDistance = bd;
        bool wantsNew = bd > _newDist && _k < _maxK;
        int target = wantsNew ? _k : best;
        if (target == Current || (!wantsNew && bd >= _stick * Dist(Current))) { _cand = -1; _candRun = 0; }
        else
        {
            if (target == _cand) _candRun++; else { _cand = target; _candRun = 1; }
            if (_candRun >= _dwell)
            {
                if (wantsNew) { Array.Copy(_z, _c[_k], _d); _k++; }
                Current = target; Switches++; _cand = -1; _candRun = 0;
            }
        }
        // the centroid only follows points close to its core, so it cannot chase a change that has not been confirmed yet
        if (_candRun == 0 && Dist(Current) < 0.5 * _newDist) for (int i = 0; i < _d; i++) _c[Current][i] += _lr * (_z[i] - _c[Current][i]);
        return Current;
    }
}
