using GLF.Neural;

namespace GLF.Trading.Models;

public interface IOnlineModel
{
    double Predict(ReadOnlySpan<double> x);
    void Learn(ReadOnlySpan<double> x, double y);
}

public sealed class RlsModel : IOnlineModel
{
    readonly Rls _m;
    public RlsModel(int d, double lambda) => _m = new Rls(d, lambda);
    public double Predict(ReadOnlySpan<double> x) { double p = _m.Predict(x); return double.IsFinite(p) ? Math.Clamp(p, -500, 500) : 0; }
    public void Learn(ReadOnlySpan<double> x, double y) => _m.Update(x, y);
}

/// <summary>
/// A small neural network trained online from a stream. Every new (features, outcome) pair is pushed into a replay window;
/// each event takes one Adam step on a mini-batch made of the newest sample plus random older ones.
/// Inputs and targets are standardised with running statistics, the loss is Huber (robust to price spikes).
/// </summary>
public sealed class NeuralModel : IOnlineModel
{
    readonly int _d, _batch, _cap, _minSamples;
    readonly Network _net;
    readonly OnlineStandardizer _xs, _ys;
    readonly double[] _rx, _ry, _y1 = new double[1];
    readonly float[] _bx, _by, _fx;
    Rng _rng;
    int _count, _head;
    public float LastLoss { get; private set; }
    public int Parameters => _net.ParameterCount;

    public NeuralModel(int d, int[] hidden, float lr = 1e-3f, int batch = 4, int replay = 1024, int minSamples = 128, ulong seed = 1)
    {
        _d = d; _batch = batch; _cap = replay; _minSamples = minSamples; _rng = new Rng(seed);
        _net = Mlp.Build(d, hidden, 1, Act.Gelu, layerNorm: false, maxBatch: batch, seed: seed, lr: lr, weightDecay: 1e-4f);
        _xs = new OnlineStandardizer(d, 2e-3); _ys = new OnlineStandardizer(1, 2e-3);
        _rx = new double[replay * d]; _ry = new double[replay];
        _bx = new float[batch * d]; _by = new float[batch]; _fx = new float[d];
    }

    public double Predict(ReadOnlySpan<double> x)
    {
        if (_count < _minSamples) return 0;
        for (int i = 0; i < _d; i++) _fx[i] = _xs.Normalize(i, x[i]);
        return _net.Forward(_fx, 1)[0] * _ys.Std(0) + _ys.Mean(0);
    }

    public void Learn(ReadOnlySpan<double> x, double y)
    {
        _xs.Update(x);
        _y1[0] = y; _ys.Update(_y1);
        x.CopyTo(_rx.AsSpan(_head * _d, _d)); _ry[_head] = y;
        int newest = _head;
        _head = (_head + 1) % _cap;
        if (_count < _cap) _count++;
        if (_count < _minSamples) return;

        for (int b = 0; b < _batch; b++)
        {
            int idx = b == 0 ? newest : _rng.NextInt(_count);
            for (int i = 0; i < _d; i++) _bx[b * _d + i] = _xs.Normalize(i, _rx[idx * _d + i]);
            _by[b] = _ys.Normalize(0, _ry[idx]);
        }
        LastLoss = _net.TrainStep(_bx, _by, _batch, LossKind.Huber, 1f);
    }
}
