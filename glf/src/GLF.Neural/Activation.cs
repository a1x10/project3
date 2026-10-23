namespace GLF.Neural;

public enum Act { Linear, ReLU, LeakyReLU, Tanh, Sigmoid, Gelu, Silu }

/// <summary>Element-wise non-linearity.</summary>
public sealed class Activation : Layer
{
    const float C = 0.7978845608f, K = 0.044715f; // sqrt(2/pi)
    readonly int _dim;
    public readonly Act Kind;
    public override int In => _dim;
    public override int Out => _dim;

    public Activation(Act kind, int dim) { Kind = kind; _dim = dim; }

    public static float Apply(Act k, float x) => k switch
    {
        Act.Linear => x,
        Act.ReLU => x > 0 ? x : 0,
        Act.LeakyReLU => x > 0 ? x : 0.01f * x,
        Act.Tanh => MathF.Tanh(x),
        Act.Sigmoid => 1f / (1f + MathF.Exp(-x)),
        Act.Gelu => 0.5f * x * (1f + MathF.Tanh(C * (x + K * x * x * x))),
        Act.Silu => x / (1f + MathF.Exp(-x)),
        _ => x,
    };

    static float Deriv(Act k, float x, float y)
    {
        switch (k)
        {
            case Act.Linear: return 1f;
            case Act.ReLU: return x > 0 ? 1f : 0f;
            case Act.LeakyReLU: return x > 0 ? 1f : 0.01f;
            case Act.Tanh: return 1f - y * y;
            case Act.Sigmoid: return y * (1f - y);
            case Act.Gelu:
            {
                float t = MathF.Tanh(C * (x + K * x * x * x));
                return 0.5f * (1f + t) + 0.5f * x * (1f - t * t) * C * (1f + 3f * K * x * x);
            }
            case Act.Silu:
            {
                float s = 1f / (1f + MathF.Exp(-x));
                return s * (1f + x * (1f - s));
            }
            default: return 1f;
        }
    }

    public override void Forward(ReadOnlySpan<float> x, int batch, Span<float> y)
    {
        int n = batch * _dim;
        for (int i = 0; i < n; i++) y[i] = Apply(Kind, x[i]);
    }

    public override void Backward(ReadOnlySpan<float> x, ReadOnlySpan<float> y, ReadOnlySpan<float> dy, int batch, Span<float> dx, bool paramGrads)
    {
        if (dx.IsEmpty) return;
        int n = batch * _dim;
        for (int i = 0; i < n; i++) dx[i] = dy[i] * Deriv(Kind, x[i], y[i]);
    }
}
