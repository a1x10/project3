using GLF.Neural;

namespace GLF.Trading.Models;

public interface IOnlineModel
{
    double Predict(ReadOnlySpan<double> x);
    void Learn(ReadOnlySpan<double> x, double y);
    /// <summary>Same, told which market regime the sample came from (models without regime memory ignore it).</summary>
    void Learn(ReadOnlySpan<double> x, double y, int regime) => Learn(x, y);
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
///
/// Regime replay: a plain window only remembers the recent past, so after a long stretch in one regime the network overwrites
/// what it knew about another (catastrophic forgetting) and pays to relearn it when that regime returns.
/// With <c>regimeMemory</c> on, every sample is also filed into a per-regime reservoir (uniform over that regime's whole history,
/// fixed size), and every mini-batch additionally contains <c>memBatch</c> samples drawn evenly across regimes - old regimes keep being rehearsed.
/// </summary>
public sealed class NeuralModel : IOnlineModel
{
    readonly int _d, _batch, _memBatch, _cap, _minSamples, _maxReg, _memCap;
    readonly bool _mem;
    readonly Network _net;
    readonly OnlineStandardizer _xs, _ys;
    readonly double[] _rx, _ry, _y1 = new double[1], _mx, _my;
    readonly int[] _mSize, _mSeen;
    readonly float[] _bx, _by, _fx;
    Rng _rng;
    int _count, _head;
    public float LastLoss { get; private set; }
    public int Parameters => _net.ParameterCount;

    public NeuralModel(int d, int[] hidden, float lr = 1e-3f, int batch = 4, int replay = 1024, int minSamples = 128, ulong seed = 1,
        bool regimeMemory = false, int memBatch = 2, int memCapPerRegime = 300, int maxRegimes = 4)
    {
        _d = d; _batch = batch; _cap = replay; _minSamples = minSamples; _rng = new Rng(seed);
        _mem = regimeMemory; _memBatch = regimeMemory ? memBatch : 0; _maxReg = maxRegimes; _memCap = memCapPerRegime;
        int total = _batch + _memBatch;
        _net = Mlp.Build(d, hidden, 1, Act.Gelu, layerNorm: false, maxBatch: total, seed: seed, lr: lr, weightDecay: 1e-4f);
        _xs = new OnlineStandardizer(d, 2e-3); _ys = new OnlineStandardizer(1, 2e-3);
        _rx = new double[replay * d]; _ry = new double[replay];
        _mx = new double[maxRegimes * memCapPerRegime * d]; _my = new double[maxRegimes * memCapPerRegime];
        _mSize = new int[maxRegimes]; _mSeen = new int[maxRegimes];
        _bx = new float[total * d]; _by = new float[total]; _fx = new float[d];
    }

    public double Predict(ReadOnlySpan<double> x)
    {
        if (_count < _minSamples) return 0;
        for (int i = 0; i < _d; i++) _fx[i] = _xs.Normalize(i, x[i]);
        return _net.Forward(_fx, 1)[0] * _ys.Std(0) + _ys.Mean(0);
    }

    public void Learn(ReadOnlySpan<double> x, double y) => Learn(x, y, 0);

    void Put(int b, ReadOnlySpan<double> x, double y)
    {
        for (int i = 0; i < _d; i++) _bx[b * _d + i] = _xs.Normalize(i, x[i]);
        _by[b] = _ys.Normalize(0, y);
    }

    public void Learn(ReadOnlySpan<double> x, double y, int regime)
    {
        _xs.Update(x);
        _y1[0] = y; _ys.Update(_y1);
        x.CopyTo(_rx.AsSpan(_head * _d, _d)); _ry[_head] = y;
        int newest = _head;
        _head = (_head + 1) % _cap;
        if (_count < _cap) _count++;

        if (_mem)
        {
            int r = Math.Clamp(regime, 0, _maxReg - 1);
            int slot = -1;
            if (_mSize[r] < _memCap) slot = _mSize[r]++;
            else { int j = _rng.NextInt(_mSeen[r] + 1); if (j < _memCap) slot = j; }   // reservoir sampling: uniform over the regime's history
            _mSeen[r]++;
            if (slot >= 0)
            {
                x.CopyTo(_mx.AsSpan((r * _memCap + slot) * _d, _d)); _my[r * _memCap + slot] = y;
            }
        }
        if (_count < _minSamples) return;

        int b2 = 0;
        Put(b2++, _rx.AsSpan(newest * _d, _d), _ry[newest]);
        for (; b2 < _batch; b2++) { int idx = _rng.NextInt(_count); Put(b2, _rx.AsSpan(idx * _d, _d), _ry[idx]); }

        int nonEmpty = 0; for (int r = 0; r < _maxReg; r++) if (_mSize[r] > 0) nonEmpty++;
        for (int m = 0; m < _memBatch && nonEmpty > 0; m++, b2++)
        {
            int pick = _rng.NextInt(nonEmpty), r = 0;
            for (; r < _maxReg; r++) if (_mSize[r] > 0 && pick-- == 0) break;
            int slot = _rng.NextInt(_mSize[r]);
            Put(b2, _mx.AsSpan((r * _memCap + slot) * _d, _d), _my[r * _memCap + slot]);
        }
        LastLoss = _net.TrainStep(_bx, _by, b2, LossKind.Huber, 1f);
    }

    /// <summary>Samples currently held per regime reservoir.</summary>
    public int MemorySize(int regime) => _mSize[regime];
}
