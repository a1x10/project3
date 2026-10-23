namespace GLF.Neural;

/// <summary>A stack of layers executed in order; keeps every intermediate activation so Backward can run without recomputation.</summary>
public sealed class Sequential : Layer
{
    readonly Layer[] _layers;
    readonly float[][] _a;   // _a[i] = output of layer i (i < n-1)
    readonly float[][] _d;   // _d[i] = dL/d(input of layer i+1)
    public readonly int MaxBatch;
    public IReadOnlyList<Layer> Layers => _layers;
    public override int In => _layers[0].In;
    public override int Out => _layers[^1].Out;

    public Sequential(int maxBatch, params Layer[] layers)
    {
        if (layers.Length == 0) throw new ArgumentException("no layers");
        for (int i = 1; i < layers.Length; i++)
            if (layers[i].In != layers[i - 1].Out) throw new ArgumentException($"layer {i}: expected input {layers[i - 1].Out}, got {layers[i].In}");
        _layers = layers; MaxBatch = maxBatch;
        _a = new float[layers.Length - 1][]; _d = new float[layers.Length - 1][];
        for (int i = 0; i < layers.Length - 1; i++)
        {
            _a[i] = new float[maxBatch * layers[i].Out];
            _d[i] = new float[maxBatch * layers[i + 1].In];
        }
    }

    public override void Forward(ReadOnlySpan<float> x, int batch, Span<float> y)
    {
        ReadOnlySpan<float> cur = x;
        int n = _layers.Length;
        for (int i = 0; i < n; i++)
        {
            Span<float> o = i == n - 1 ? y : _a[i].AsSpan(0, batch * _layers[i].Out);
            _layers[i].Forward(cur, batch, o);
            cur = o;
        }
    }

    public override void Backward(ReadOnlySpan<float> x, ReadOnlySpan<float> y, ReadOnlySpan<float> dy, int batch, Span<float> dx, bool paramGrads)
    {
        ReadOnlySpan<float> dcur = dy;
        int n = _layers.Length;
        for (int i = n - 1; i >= 0; i--)
        {
            ReadOnlySpan<float> input = i == 0 ? x : _a[i - 1].AsSpan(0, batch * _layers[i].In);
            ReadOnlySpan<float> output = i == n - 1 ? y : _a[i].AsSpan(0, batch * _layers[i].Out);
            Span<float> dxi = i == 0 ? dx : _d[i - 1].AsSpan(0, batch * _layers[i].In);
            _layers[i].Backward(input, output, dcur, batch, dxi, paramGrads);
            dcur = dxi;
        }
    }

    public override void CollectParams(List<Param> into) { foreach (var l in _layers) l.CollectParams(into); }
}

/// <summary>y = x + f(x). Gradients flow through the shortcut untouched, which is what makes deep nets trainable.</summary>
public sealed class Residual : Layer
{
    readonly Sequential _f;
    readonly float[] _t, _dxf;
    public override int In => _f.In;
    public override int Out => _f.Out;

    public Residual(Sequential inner)
    {
        if (inner.In != inner.Out) throw new ArgumentException("residual block must preserve width");
        _f = inner;
        _t = new float[inner.MaxBatch * inner.Out]; _dxf = new float[inner.MaxBatch * inner.In];
    }

    public override void Forward(ReadOnlySpan<float> x, int batch, Span<float> y)
    {
        int n = batch * Out;
        _f.Forward(x, batch, _t.AsSpan(0, n));
        for (int i = 0; i < n; i++) y[i] = x[i] + _t[i];
    }

    public override void Backward(ReadOnlySpan<float> x, ReadOnlySpan<float> y, ReadOnlySpan<float> dy, int batch, Span<float> dx, bool paramGrads)
    {
        int n = batch * Out;
        _f.Backward(x, _t.AsSpan(0, n), dy, batch, _dxf.AsSpan(0, n), paramGrads);
        if (dx.IsEmpty) return;
        for (int i = 0; i < n; i++) dx[i] = dy[i] + _dxf[i];
    }

    public override void CollectParams(List<Param> into) => _f.CollectParams(into);
}
