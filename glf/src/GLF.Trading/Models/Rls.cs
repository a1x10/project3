namespace GLF.Trading.Models;

/// <summary>Recursive least squares with forgetting factor. Online, O(d^2), allocation-free after construction.</summary>
public sealed class Rls
{
    const double MaxTrace = 1e4;
    readonly int _d;
    readonly double _lambda;
    readonly double[] _w, _p, _px, _k;

    public Rls(int d, double lambda, double delta = 100)
    {
        _d = d; _lambda = lambda;
        _w = new double[d]; _p = new double[d * d]; _px = new double[d]; _k = new double[d];
        for (int i = 0; i < d; i++) _p[i * d + i] = delta;
    }

    public ReadOnlySpan<double> Weights => _w;

    public double Predict(ReadOnlySpan<double> x)
    {
        double s = 0;
        for (int i = 0; i < _d; i++) s += _w[i] * x[i];
        return s;
    }

    public void Update(ReadOnlySpan<double> x, double y)
    {
        int d = _d;
        for (int i = 0; i < d; i++)
        {
            double s = 0;
            for (int j = 0; j < d; j++) s += _p[i * d + j] * x[j];
            _px[i] = s;
        }
        double denom = _lambda;
        for (int i = 0; i < d; i++) denom += x[i] * _px[i];
        double err = y - Predict(x);
        double inv = 1.0 / _lambda;
        for (int i = 0; i < d; i++) { _k[i] = _px[i] / denom; _w[i] += _k[i] * err; }
        double tr = 0;
        for (int i = 0; i < d; i++)
        {
            for (int j = 0; j < d; j++) _p[i * d + j] = (_p[i * d + j] - _k[i] * _px[j]) * inv;
            tr += _p[i * d + i];
        }
        if (tr > MaxTrace)
        {
            double sc = MaxTrace / tr;
            for (int i = 0; i < _p.Length; i++) _p[i] *= sc;
        }
    }
}
