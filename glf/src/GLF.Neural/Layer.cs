namespace GLF.Neural;

/// <summary>A trainable tensor: weights, gradient and the optimizer's two moment buffers.</summary>
public sealed class Param
{
    public readonly string Name;
    public readonly float[] W, G, M, V;
    public bool NoDecay;
    public Param(string name, int n, bool noDecay = false)
    {
        Name = name; W = new float[n]; G = new float[n]; M = new float[n]; V = new float[n]; NoDecay = noDecay;
    }
}

/// <summary>
/// One differentiable stage. Tensors are row-major [batch, features]. Conventions:
/// Forward writes y. Backward receives the same x and y plus dL/dy, OVERWRITES dx (dL/dx; an empty span means "not needed")
/// and ADDS dL/dparam into Param.G when paramGrads is true.
/// </summary>
public abstract class Layer
{
    public abstract int In { get; }
    public abstract int Out { get; }
    public abstract void Forward(ReadOnlySpan<float> x, int batch, Span<float> y);
    public abstract void Backward(ReadOnlySpan<float> x, ReadOnlySpan<float> y, ReadOnlySpan<float> dy, int batch, Span<float> dx, bool paramGrads);
    public virtual void CollectParams(List<Param> into) { }
}
