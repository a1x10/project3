using GLF.Neural.Transformer;

namespace GLF.Neural;

/// <summary>Symmetric linear quantisation (Z = 0): X_q = clip(round(X/S), -qmax-1, qmax), S = max|X| / qmax. "Fake" variants quantise then dequantise in place to measure accuracy.</summary>
public static class Quant
{
    public static int QMax(int bits) => (1 << (bits - 1)) - 1;

    public static void FakeQuantGroup(Span<float> x, int bits)
    {
        float amax = 0; foreach (float v in x) amax = MathF.Max(amax, MathF.Abs(v));
        if (amax == 0) return;
        int qmax = QMax(bits);
        float s = amax / qmax;
        for (int i = 0; i < x.Length; i++) x[i] = Math.Clamp(MathF.Round(x[i] / s), -qmax - 1, qmax) * s;
    }

    /// <summary>Weights [rows=out, cols=in]; groups run along the input dimension of each output row (groupSize 0 = one scale per output channel).</summary>
    public static void FakeQuantWeights(float[] w, int rows, int cols, int bits, int groupSize)
    {
        int g = groupSize <= 0 ? cols : groupSize;
        for (int r = 0; r < rows; r++)
            for (int c = 0; c < cols; c += g)
                FakeQuantGroup(w.AsSpan(r * cols + c, Math.Min(g, cols - c)), bits);
    }

    /// <summary>Per-token activation quantisation.</summary>
    public static void FakeQuantRows(Span<float> x, int rows, int dim, int bits)
    {
        for (int r = 0; r < rows; r++) FakeQuantGroup(x.Slice(r * dim, dim), bits);
    }
}

/// <summary>
/// A genuinely integer linear layer (the "fused GEMM" of the spec): int8 weights with one scale per output channel,
/// int8 activations with one scale per token, int32 accumulation, and one rescale Y = acc · S_x · S_w at the end.
/// </summary>
public sealed class Int8Linear
{
    readonly sbyte[] _wq; readonly float[] _sw; readonly sbyte[] _xq;
    public readonly int In, Out;

    public Int8Linear(float[] w, int outD, int inD)
    {
        In = inD; Out = outD; _wq = new sbyte[outD * inD]; _sw = new float[outD]; _xq = new sbyte[inD];
        for (int o = 0; o < outD; o++)
        {
            float amax = 0; for (int i = 0; i < inD; i++) amax = MathF.Max(amax, MathF.Abs(w[o * inD + i]));
            float s = amax == 0 ? 1f : amax / 127f; _sw[o] = s;
            for (int i = 0; i < inD; i++) _wq[o * inD + i] = (sbyte)Math.Clamp((int)MathF.Round(w[o * inD + i] / s), -128, 127);
        }
    }

    public int WeightBytes => _wq.Length + 4 * _sw.Length;

    public void Forward(ReadOnlySpan<float> x, Span<float> y)
    {
        float amax = 0; for (int i = 0; i < In; i++) amax = MathF.Max(amax, MathF.Abs(x[i]));
        float sx = amax == 0 ? 1f : amax / 127f;
        for (int i = 0; i < In; i++) _xq[i] = (sbyte)Math.Clamp((int)MathF.Round(x[i] / sx), -128, 127);
        for (int o = 0; o < Out; o++)
        {
            int acc = 0, b = o * In;
            for (int i = 0; i < In; i++) acc += _xq[i] * _wq[b + i];
            y[o] = acc * sx * _sw[o];
        }
    }
}

/// <summary>Model-level post-training quantisation: plain round-to-nearest, SmoothQuant, AWQ-style scale search.</summary>
public static class Quantizer
{
    static IEnumerable<(Param W, int Rows, int Cols)> Linears(TransformerModel m)
    {
        int D = m.C.DModel, F = m.C.FfnDim, kv = m.C.KvDim;
        foreach (var l in m.Layer)
        {
            yield return (l.Wq, D, D); yield return (l.Wk, kv, D); yield return (l.Wv, kv, D); yield return (l.Wo, D, D);
            yield return (l.Wg, F, D); yield return (l.Wu, F, D); yield return (l.Wd, D, F);
        }
    }

    public static long LinearParameters(TransformerModel m) => Linears(m).Sum(t => (long)t.Rows * t.Cols);

    /// <summary>Round-to-nearest of every transformer linear weight (embedding / head and norm gains stay in float).</summary>
    public static void Rtn(TransformerModel m, int bits, int group)
    {
        foreach (var (w, r, c) in Linears(m)) Quant.FakeQuantWeights(w.W, r, c, bits, group);
    }

    // ---- calibration: capture the inputs of the norm-fed linear layers ----
    public sealed class Calibration
    {
        public float[][] N1 = null!, N2 = null!; // per layer: [rows, D]
        public int Rows;
    }

    public static Calibration Calibrate(TransformerModel m, IEnumerable<int[]> windows, int maxRows = 4096)
    {
        int L = m.C.Layers, D = m.C.DModel;
        var n1 = Enumerable.Range(0, L).Select(_ => new List<float>()).ToArray();
        var n2 = Enumerable.Range(0, L).Select(_ => new List<float>()).ToArray();
        int rows = 0;
        int saved = m.ActBits; m.ActBits = 0;
        foreach (var w in windows)
        {
            m.Forward(w, w.Length);
            for (int l = 0; l < L; l++) { n1[l].AddRange(m.N1(l).AsSpan(0, w.Length * D).ToArray()); n2[l].AddRange(m.N2(l).AsSpan(0, w.Length * D).ToArray()); }
            rows += w.Length;
            if (rows >= maxRows) break;
        }
        m.ActBits = saved;
        return new Calibration { N1 = n1.Select(l => l.ToArray()).ToArray(), N2 = n2.Select(l => l.ToArray()).ToArray(), Rows = rows };
    }

    static float[] ColMax(float[] x, int rows, int dim)
    {
        var mx = new float[dim];
        for (int r = 0; r < rows; r++) for (int j = 0; j < dim; j++) mx[j] = MathF.Max(mx[j], MathF.Abs(x[r * dim + j]));
        return mx;
    }

    /// <summary>S_j = max|X_j|^α / max|W_j|^(1−α), where W_j is column j (input channel j) of all weights sharing the input.</summary>
    public static float[] SmoothScales(float[] actMax, IReadOnlyList<(float[] W, int Rows)> weights, int dim, double alpha)
    {
        var s = new float[dim];
        for (int j = 0; j < dim; j++)
        {
            float wm = 0;
            foreach (var (w, rows) in weights) for (int o = 0; o < rows; o++) wm = MathF.Max(wm, MathF.Abs(w[o * dim + j]));
            double v = Math.Pow(Math.Max(actMax[j], 1e-5f), alpha) / Math.Pow(Math.Max(wm, 1e-5f), 1 - alpha);
            s[j] = (float)Math.Clamp(v, 1e-4, 1e4);
        }
        return s;
    }

    /// <summary>Folds diag(s): inputs become X/s (through the RMSNorm gain), weights become W·s. Exactly output-preserving in floating point.</summary>
    static void Fold(float[] gain, IReadOnlyList<(float[] W, int Rows)> weights, float[] s, int dim)
    {
        for (int j = 0; j < dim; j++) gain[j] /= s[j];
        foreach (var (w, rows) in weights) for (int o = 0; o < rows; o++) for (int j = 0; j < dim; j++) w[o * dim + j] *= s[j];
    }

    public static void SmoothQuant(TransformerModel m, Calibration cal, double alpha)
    {
        int D = m.C.DModel, kv = m.C.KvDim, F = m.C.FfnDim;
        for (int l = 0; l < m.C.Layers; l++)
        {
            var w = m.Layer[l];
            var qkv = new List<(float[], int)> { (w.Wq.W, D), (w.Wk.W, kv), (w.Wv.W, kv) };
            var s1 = SmoothScales(ColMax(cal.N1[l], cal.Rows, D), qkv, D, alpha);
            Fold(w.G1.W, qkv, s1, D);
            var gu = new List<(float[], int)> { (w.Wg.W, F), (w.Wu.W, F) };
            var s2 = SmoothScales(ColMax(cal.N2[l], cal.Rows, D), gu, D, alpha);
            Fold(w.G2.W, gu, s2, D);
        }
    }

    /// <summary>
    /// AWQ-style: for each group of layers that share an input, search γ in [0,1] for the per-channel scale s_j = (mean|X_j|)^γ that minimises
    /// the output error ‖XWᵀ − X Q(W·diag s)ᵀ diag(s)⁻¹‖² after low-bit weight quantisation. γ = 0 is plain round-to-nearest, so the search can only help.
    /// Layers fed straight from a matmul (Wo, Wd) use plain rounding.
    /// </summary>
    public static (double Gamma1, double Gamma2)[] Awq(TransformerModel m, Calibration cal, int bits, int group)
    {
        int D = m.C.DModel, kv = m.C.KvDim, F = m.C.FfnDim;
        var gammas = new (double, double)[m.C.Layers];
        for (int l = 0; l < m.C.Layers; l++)
        {
            var w = m.Layer[l];
            double g1 = SearchAndApply(w.G1.W, new List<(float[], int)> { (w.Wq.W, D), (w.Wk.W, kv), (w.Wv.W, kv) }, cal.N1[l], cal.Rows, D, bits, group);
            double g2 = SearchAndApply(w.G2.W, new List<(float[], int)> { (w.Wg.W, F), (w.Wu.W, F) }, cal.N2[l], cal.Rows, D, bits, group);
            Quant.FakeQuantWeights(w.Wo.W, D, D, bits, group);
            Quant.FakeQuantWeights(w.Wd.W, D, F, bits, group);
            gammas[l] = (g1, g2);
        }
        return gammas;
    }

    static double SearchAndApply(float[] gain, List<(float[] W, int Rows)> weights, float[] X, int rows, int dim, int bits, int group)
    {
        int use = Math.Min(rows, 512);
        var meanAbs = new float[dim];
        for (int r = 0; r < rows; r++) for (int j = 0; j < dim; j++) meanAbs[j] += MathF.Abs(X[r * dim + j]) / rows;

        double bestLoss = double.MaxValue, bestGamma = 0; float[]? bestScale = null;
        for (int gi = 0; gi <= 10; gi++)
        {
            double gamma = gi / 10.0;
            var s = new float[dim];
            for (int j = 0; j < dim; j++) s[j] = (float)Math.Pow(Math.Max(meanAbs[j], 1e-5f), gamma);
            float norm = MathF.Sqrt(s.Max() * s.Min()); for (int j = 0; j < dim; j++) s[j] /= norm;

            double loss = 0;
            foreach (var (w, outD) in weights)
            {
                var scaled = new float[outD * dim];
                for (int o = 0; o < outD; o++) for (int j = 0; j < dim; j++) scaled[o * dim + j] = w[o * dim + j] * s[j];
                Quant.FakeQuantWeights(scaled, outD, dim, bits, group);
                for (int r = 0; r < use; r++)
                    for (int o = 0; o < outD; o++)
                    {
                        float yref = 0, yq = 0;
                        for (int j = 0; j < dim; j++) { float x = X[r * dim + j]; yref += w[o * dim + j] * x; yq += scaled[o * dim + j] * x / s[j]; }
                        loss += (double)(yref - yq) * (yref - yq);
                    }
            }
            if (loss < bestLoss) { bestLoss = loss; bestGamma = gamma; bestScale = s; }
        }

        foreach (var (w, outD) in weights)
        {
            for (int o = 0; o < outD; o++) for (int j = 0; j < dim; j++) w[o * dim + j] *= bestScale![j];
            Quant.FakeQuantWeights(w, outD, dim, bits, group);
        }
        for (int j = 0; j < dim; j++) gain[j] /= bestScale![j];
        return bestGamma;
    }
}
