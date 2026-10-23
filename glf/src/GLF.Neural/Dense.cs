namespace GLF.Neural;

/// <summary>Fully connected layer: y = x Wᵀ + b, W stored [out, in] so each neuron is one contiguous SIMD dot product.</summary>
public sealed class Dense : Layer
{
    readonly int _in, _out;
    public readonly Param W, B;
    public override int In => _in;
    public override int Out => _out;

    /// <param name="std">weight standard deviation (He: sqrt(2/in) for ReLU-like, LeCun: sqrt(1/in) otherwise)</param>
    public Dense(int inp, int outp, ref Rng rng, float std)
    {
        _in = inp; _out = outp;
        W = new Param("W", inp * outp);
        B = new Param("b", outp, noDecay: true);
        for (int i = 0; i < W.W.Length; i++) W.W[i] = rng.NextGaussian() * std;
    }

    public override void Forward(ReadOnlySpan<float> x, int batch, Span<float> y)
    {
        for (int b = 0; b < batch; b++)
        {
            var xb = x.Slice(b * _in, _in);
            for (int o = 0; o < _out; o++)
                y[b * _out + o] = VecOps.Dot(xb, W.W.AsSpan(o * _in, _in)) + B.W[o];
        }
    }

    public override void Backward(ReadOnlySpan<float> x, ReadOnlySpan<float> y, ReadOnlySpan<float> dy, int batch, Span<float> dx, bool paramGrads)
    {
        bool needDx = !dx.IsEmpty;
        if (needDx) dx.Slice(0, batch * _in).Clear();
        for (int b = 0; b < batch; b++)
        {
            var xb = x.Slice(b * _in, _in);
            for (int o = 0; o < _out; o++)
            {
                float g = dy[b * _out + o];
                if (g == 0f) continue;
                if (paramGrads)
                {
                    B.G[o] += g;
                    VecOps.Axpy(g, xb, W.G.AsSpan(o * _in, _in));
                }
                if (needDx) VecOps.Axpy(g, W.W.AsSpan(o * _in, _in), dx.Slice(b * _in, _in));
            }
        }
    }

    public override void CollectParams(List<Param> into) { into.Add(W); into.Add(B); }
}
