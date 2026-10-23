namespace GLF.Neural;

/// <summary>A model: a Sequential body plus loss, optimizer, saving/loading and input-gradient analysis. No allocation after construction.</summary>
public sealed class Network
{
    public readonly Sequential Body;
    public readonly int In, Out, MaxBatch;
    public readonly List<Param> Params = new();
    public Adam Opt;
    readonly float[] _out, _dOut, _dIn;
    public float LastGradNorm { get; private set; }
    /// <summary>Called after backprop and before the optimiser step; may add extra gradient terms (e.g. an EWC penalty).</summary>
    public Action<List<Param>>? BeforeStep;

    public Network(Sequential body, Adam? opt = null)
    {
        Body = body; In = body.In; Out = body.Out; MaxBatch = body.MaxBatch;
        Opt = opt ?? new Adam();
        _out = new float[MaxBatch * Out]; _dOut = new float[MaxBatch * Out]; _dIn = new float[Math.Max(MaxBatch * In, In)];
        body.CollectParams(Params);
    }

    public int ParameterCount { get { int n = 0; foreach (var p in Params) n += p.W.Length; return n; } }

    /// <summary>Inference. The returned span is an internal buffer, valid until the next call.</summary>
    public ReadOnlySpan<float> Forward(ReadOnlySpan<float> x, int batch = 1)
    {
        Body.Forward(x, batch, _out.AsSpan(0, batch * Out));
        return _out.AsSpan(0, batch * Out);
    }

    void ZeroGrads() { foreach (var p in Params) Array.Clear(p.G); }

    public float TrainStep(ReadOnlySpan<float> x, ReadOnlySpan<float> target, int batch, LossKind kind = LossKind.Mse, float huberDelta = 1f)
    {
        ZeroGrads();
        var o = _out.AsSpan(0, batch * Out);
        Body.Forward(x, batch, o);
        float loss = Loss.Compute(kind, o, target, _dOut.AsSpan(0, batch * Out), batch, Out, huberDelta);
        Body.Backward(x, o, _dOut.AsSpan(0, batch * Out), batch, default, true);
        BeforeStep?.Invoke(Params);
        LastGradNorm = Opt.Step(Params);
        return loss;
    }

    /// <summary>Gradients of the classification loss into Param.G without an optimiser step.</summary>
    public float GradientsClassify(ReadOnlySpan<float> x, ReadOnlySpan<int> labels, int batch)
    {
        ZeroGrads();
        var o = _out.AsSpan(0, batch * Out);
        Body.Forward(x, batch, o);
        float loss = Loss.SoftmaxCrossEntropy(o, labels, _dOut.AsSpan(0, batch * Out), batch, Out);
        Body.Backward(x, o, _dOut.AsSpan(0, batch * Out), batch, default, true);
        return loss;
    }

    public float TrainStepClassify(ReadOnlySpan<float> x, ReadOnlySpan<int> labels, int batch)
    {
        ZeroGrads();
        var o = _out.AsSpan(0, batch * Out);
        Body.Forward(x, batch, o);
        float loss = Loss.SoftmaxCrossEntropy(o, labels, _dOut.AsSpan(0, batch * Out), batch, Out);
        Body.Backward(x, o, _dOut.AsSpan(0, batch * Out), batch, default, true);
        BeforeStep?.Invoke(Params);
        LastGradNorm = Opt.Step(Params);
        return loss;
    }

    /// <summary>∂output[outputIndex]/∂input for a single sample: which inputs the network's answer depends on.</summary>
    public ReadOnlySpan<float> InputGradient(ReadOnlySpan<float> x, int outputIndex = 0)
    {
        var o = _out.AsSpan(0, Out);
        Body.Forward(x, 1, o);
        var d = _dOut.AsSpan(0, Out); d.Clear(); d[outputIndex] = 1f;
        Body.Backward(x, o, d, 1, _dIn.AsSpan(0, In), false);
        return _dIn.AsSpan(0, In);
    }

    public void Save(Stream s)
    {
        using var w = new BinaryWriter(s, System.Text.Encoding.UTF8, leaveOpen: true);
        w.Write(0x4E4C4647); w.Write(1); w.Write(Params.Count);
        foreach (var p in Params) { w.Write(p.W.Length); foreach (var f in p.W) w.Write(f); }
    }

    public void Load(Stream s)
    {
        using var r = new BinaryReader(s, System.Text.Encoding.UTF8, leaveOpen: true);
        if (r.ReadInt32() != 0x4E4C4647 || r.ReadInt32() != 1) throw new InvalidDataException("not a GLF network file");
        if (r.ReadInt32() != Params.Count) throw new InvalidDataException("architecture mismatch");
        foreach (var p in Params)
        {
            if (r.ReadInt32() != p.W.Length) throw new InvalidDataException("architecture mismatch");
            for (int i = 0; i < p.W.Length; i++) p.W[i] = r.ReadSingle();
        }
    }
}

public static class Mlp
{
    /// <summary>Feed-forward net. Initialisation follows the activation: He for ReLU-like, LeCun otherwise; the head starts small.</summary>
    public static Network Build(int input, int[] hidden, int output, Act act = Act.Gelu, bool layerNorm = false,
        int maxBatch = 64, ulong seed = 1, float lr = 1e-3f, float weightDecay = 0f)
    {
        var rng = new Rng(seed);
        var layers = new List<Layer>();
        int prev = input;
        bool reluLike = act is Act.ReLU or Act.LeakyReLU or Act.Gelu or Act.Silu;
        foreach (int h in hidden)
        {
            layers.Add(new Dense(prev, h, ref rng, MathF.Sqrt((reluLike ? 2f : 1f) / prev)));
            if (layerNorm) layers.Add(new LayerNorm(h, maxBatch));
            layers.Add(new Activation(act, h));
            prev = h;
        }
        layers.Add(new Dense(prev, output, ref rng, 0.1f * MathF.Sqrt(1f / prev)));
        return new Network(new Sequential(maxBatch, layers.ToArray()), new Adam(lr, weightDecay));
    }
}
