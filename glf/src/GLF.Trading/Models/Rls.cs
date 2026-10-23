namespace GLF.Trading.Models;

/// <summary>
/// Exponentially weighted ridge regression, solved from sufficient statistics (A = Σλᵏ·xxᵀ, b = Σλᵏ·y·x) by Cholesky every few updates.
/// The classic recursive-least-squares covariance update was replaced because with a forgetting factor it winds up and
/// loses positive-definiteness over long runs (found in the 400k-event test: single hypotheses drifted to RMSE in the tens of thousands).
/// The ridge term keeps unexcited directions bounded by construction. Allocation-free after construction.
/// </summary>
public sealed class Rls
{
    readonly int _d;
    readonly double _lambda;
    readonly double[] _a, _b, _w, _l, _z;
    int _since;

    public int SolveEvery = 4;
    public double RidgeFraction = 1e-3;

    public Rls(int d, double lambda, double delta = 100)
    {
        _d = d; _lambda = lambda;
        _a = new double[d * d]; _b = new double[d]; _w = new double[d]; _l = new double[d * d]; _z = new double[d];
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
            for (int j = 0; j < d; j++) _a[i * d + j] = _lambda * _a[i * d + j] + x[i] * x[j];
            _b[i] = _lambda * _b[i] + y * x[i];
        }
        if (++_since >= SolveEvery) { _since = 0; Solve(); }
    }

    void Solve()
    {
        int d = _d;
        double tr = 0;
        for (int i = 0; i < d; i++) tr += _a[i * d + i];
        double ridge = RidgeFraction * tr / d + 1e-9;

        for (int i = 0; i < d; i++)
            for (int j = 0; j <= i; j++)
            {
                double s = _a[i * d + j] + (i == j ? ridge : 0);
                for (int k = 0; k < j; k++) s -= _l[i * d + k] * _l[j * d + k];
                if (i == j)
                {
                    if (s <= 1e-14) return; // not positive definite: keep previous weights
                    _l[i * d + i] = Math.Sqrt(s);
                }
                else _l[i * d + j] = s / _l[j * d + j];
            }
        for (int i = 0; i < d; i++) { double s = _b[i]; for (int k = 0; k < i; k++) s -= _l[i * d + k] * _z[k]; _z[i] = s / _l[i * d + i]; }
        for (int i = d - 1; i >= 0; i--)
        {
            double s = _z[i];
            for (int k = i + 1; k < d; k++) s -= _l[k * d + i] * _w[k];
            _w[i] = s / _l[i * d + i];
        }
    }
}
