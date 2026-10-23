namespace GLF.Neural;

/// <summary>Running per-feature mean/variance (exponential forgetting) so inputs and targets stay O(1) on non-stationary streams.</summary>
public sealed class OnlineStandardizer
{
    readonly double[] _mean, _var;
    readonly double _alpha;
    long _n;
    public int Dim => _mean.Length;
    public long Count => _n;

    public OnlineStandardizer(int dim, double alpha = 1e-3)
    {
        _mean = new double[dim]; _var = new double[dim]; _alpha = alpha;
        Array.Fill(_var, 1.0);
    }

    public void Update(ReadOnlySpan<double> x)
    {
        _n++;
        double a = Math.Max(1.0 / _n, _alpha);
        for (int i = 0; i < _mean.Length; i++)
        {
            double d = x[i] - _mean[i];
            _mean[i] += a * d;
            _var[i] = _n == 1 ? 1.0 : (1 - a) * (_var[i] + a * d * d);
        }
    }

    public double Mean(int i) => _mean[i];
    public double Std(int i) => Math.Sqrt(_var[i] + 1e-12);

    public float Normalize(int i, double x)
    {
        double z = (x - _mean[i]) / Std(i);
        return (float)Math.Clamp(z, -6, 6);
    }
}
