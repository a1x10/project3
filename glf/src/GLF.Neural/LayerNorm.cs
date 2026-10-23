namespace GLF.Neural;

/// <summary>Per-sample feature normalisation with learned gain/bias. Keeps deep stacks well conditioned.</summary>
public sealed class LayerNorm : Layer
{
    const float Eps = 1e-5f;
    readonly int _dim;
    readonly float[] _xhat, _inv;
    public readonly Param Gamma, Beta;
    public override int In => _dim;
    public override int Out => _dim;

    public LayerNorm(int dim, int maxBatch)
    {
        _dim = dim;
        _xhat = new float[maxBatch * dim]; _inv = new float[maxBatch];
        Gamma = new Param("gamma", dim, noDecay: true); Beta = new Param("beta", dim, noDecay: true);
        Array.Fill(Gamma.W, 1f);
    }

    public override void Forward(ReadOnlySpan<float> x, int batch, Span<float> y)
    {
        for (int b = 0; b < batch; b++)
        {
            var xb = x.Slice(b * _dim, _dim);
            float mean = 0; for (int i = 0; i < _dim; i++) mean += xb[i];
            mean /= _dim;
            float var = 0; for (int i = 0; i < _dim; i++) { float d = xb[i] - mean; var += d * d; }
            float inv = 1f / MathF.Sqrt(var / _dim + Eps);
            _inv[b] = inv;
            for (int i = 0; i < _dim; i++)
            {
                float h = (xb[i] - mean) * inv;
                _xhat[b * _dim + i] = h;
                y[b * _dim + i] = Gamma.W[i] * h + Beta.W[i];
            }
        }
    }

    public override void Backward(ReadOnlySpan<float> x, ReadOnlySpan<float> y, ReadOnlySpan<float> dy, int batch, Span<float> dx, bool paramGrads)
    {
        for (int b = 0; b < batch; b++)
        {
            float m1 = 0, m2 = 0;
            for (int i = 0; i < _dim; i++)
            {
                float h = _xhat[b * _dim + i], g = dy[b * _dim + i];
                if (paramGrads) { Gamma.G[i] += g * h; Beta.G[i] += g; }
                float dh = g * Gamma.W[i];
                m1 += dh; m2 += dh * h;
            }
            if (dx.IsEmpty) continue;
            m1 /= _dim; m2 /= _dim;
            for (int i = 0; i < _dim; i++)
            {
                float h = _xhat[b * _dim + i], dh = dy[b * _dim + i] * Gamma.W[i];
                dx[b * _dim + i] = _inv[b] * (dh - m1 - h * m2);
            }
        }
    }

    public override void CollectParams(List<Param> into) { into.Add(Gamma); into.Add(Beta); }
}
