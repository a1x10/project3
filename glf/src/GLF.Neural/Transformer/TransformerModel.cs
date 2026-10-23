namespace GLF.Neural.Transformer;

public sealed record TransformerConfig(int Vocab, int DModel, int Layers, int Heads, int KvHeads, int FfnDim, int MaxSeq,
    float RopeBase = 10000f, float Eps = 1e-5f)
{
    public int HeadDim => DModel / Heads;
    public int KvDim => KvHeads * HeadDim;
    public void Validate()
    {
        if (DModel % Heads != 0 || HeadDim % 2 != 0) throw new ArgumentException("DModel must split into heads of even size (RoPE rotates pairs)");
        if (Heads % KvHeads != 0) throw new ArgumentException("Heads must be a multiple of KvHeads (grouped-query attention)");
    }
}

/// <summary>
/// Decoder-only transformer, written out by hand with full backpropagation.
/// Pre-norm blocks: x += Attn(RMSNorm(x)); x += SwiGLU(RMSNorm(x)); logits = RMSNorm(x)·Embᵀ (tied embeddings).
/// Attention: multi-head, grouped-query (several query heads share one K/V head), rotary positions, causal mask.
/// </summary>
public sealed class TransformerModel
{
    public readonly TransformerConfig C;
    public readonly List<Param> Params = new();
    internal readonly Param Emb, Gf;
    internal readonly LP[] Layer;
    internal readonly float[] Cos, Sin;

    internal sealed class LP { public Param Wq = null!, Wk = null!, Wv = null!, Wo = null!, Wg = null!, Wu = null!, Wd = null!, G1 = null!, G2 = null!; }

    // training workspace (one sequence at a time)
    readonly float[][] _xs;       // layer inputs, [L+1][T*D]
    readonly float[][] _n1, _q, _k, _v, _ao, _x2, _n2, _a, _u, _hh;
    readonly float[][] _inv1, _inv2, _p;
    readonly float[] _invF, _nf, _logits, _dlog, _dcur, _dx2, _dtmp, _dn, _dhh, _da, _du, _dao, _dq, _dk, _dv, _dp;
    int _T;

    /// <summary>When &gt; 0, the inputs of every linear layer are fake-quantised per token to this many bits (inference-time W8A8 study).</summary>
    public int ActBits;
    internal float[] N1(int l) => _n1[l];
    internal float[] N2(int l) => _n2[l];

    public void CopyWeightsFrom(TransformerModel o) { for (int i = 0; i < Params.Count; i++) Array.Copy(o.Params[i].W, Params[i].W, Params[i].W.Length); }
    public TransformerModel Clone() { var m = new TransformerModel(C); m.CopyWeightsFrom(this); return m; }

    public int ParameterCount { get { int n = 0; foreach (var p in Params) n += p.W.Length; return n; } }
    public ReadOnlySpan<float> Logits => _logits.AsSpan(0, _T * C.Vocab);

    Param Add(string name, int n, float std, ref Rng rng, bool noDecay = false, float fill = 0f)
    {
        var p = new Param(name, n, noDecay);
        if (std > 0) for (int i = 0; i < n; i++) p.W[i] = rng.NextGaussian() * std;
        else Array.Fill(p.W, fill);
        Params.Add(p);
        return p;
    }

    public TransformerModel(TransformerConfig c, ulong seed = 1)
    {
        C = c; c.Validate();
        var rng = new Rng(seed);
        int D = c.DModel, F = c.FfnDim, kv = c.KvDim, V = c.Vocab, L = c.Layers, T = c.MaxSeq;
        float s = 1f / MathF.Sqrt(D), sOut = s / MathF.Sqrt(2f * L);
        Emb = Add("emb", V * D, 0.1f, ref rng);
        Layer = new LP[L];
        for (int l = 0; l < L; l++)
            Layer[l] = new LP
            {
                Wq = Add($"l{l}.wq", D * D, s, ref rng), Wk = Add($"l{l}.wk", kv * D, s, ref rng), Wv = Add($"l{l}.wv", kv * D, s, ref rng),
                Wo = Add($"l{l}.wo", D * D, sOut, ref rng),
                Wg = Add($"l{l}.wgate", F * D, s, ref rng), Wu = Add($"l{l}.wup", F * D, s, ref rng), Wd = Add($"l{l}.wdown", D * F, sOut, ref rng),
                G1 = Add($"l{l}.g1", D, 0, ref rng, true, 1f), G2 = Add($"l{l}.g2", D, 0, ref rng, true, 1f),
            };
        Gf = Add("gf", D, 0, ref rng, true, 1f);

        int half = c.HeadDim / 2;
        Cos = new float[T * half]; Sin = new float[T * half];
        for (int pos = 0; pos < T; pos++)
            for (int i = 0; i < half; i++)
            {
                double ang = pos * Math.Pow(c.RopeBase, -2.0 * i / c.HeadDim);
                Cos[pos * half + i] = (float)Math.Cos(ang); Sin[pos * half + i] = (float)Math.Sin(ang);
            }

        _xs = Rows(L + 1, T * D);
        _n1 = Rows(L, T * D); _q = Rows(L, T * D); _k = Rows(L, T * kv); _v = Rows(L, T * kv); _ao = Rows(L, T * D);
        _x2 = Rows(L, T * D); _n2 = Rows(L, T * D); _a = Rows(L, T * F); _u = Rows(L, T * F); _hh = Rows(L, T * F);
        _inv1 = Rows(L, T); _inv2 = Rows(L, T); _p = Rows(L, c.Heads * T * T);
        _invF = new float[T]; _nf = new float[T * D]; _logits = new float[T * V]; _dlog = new float[T * V];
        _dcur = new float[T * D]; _dx2 = new float[T * D]; _dtmp = new float[T * D]; _dn = new float[T * D];
        _dhh = new float[T * F]; _da = new float[T * F]; _du = new float[T * F]; _dao = new float[T * D];
        _dq = new float[T * D]; _dk = new float[T * kv]; _dv = new float[T * kv]; _dp = new float[T];
    }

    static float[][] Rows(int n, int len) { var r = new float[n][]; for (int i = 0; i < n; i++) r[i] = new float[len]; return r; }

    // ---------- primitives ----------
    internal static void Linear(float[] W, int outD, int inD, ReadOnlySpan<float> x, Span<float> y, int T)
    {
        for (int t = 0; t < T; t++)
        {
            var xt = x.Slice(t * inD, inD);
            for (int o = 0; o < outD; o++) y[t * outD + o] = VecOps.Dot(xt, W.AsSpan(o * inD, inD));
        }
    }

    // accumulates into dW and dx
    static void LinearBack(float[] W, float[] dW, int outD, int inD, ReadOnlySpan<float> x, ReadOnlySpan<float> dy, Span<float> dx, int T)
    {
        for (int t = 0; t < T; t++)
        {
            var xt = x.Slice(t * inD, inD);
            for (int o = 0; o < outD; o++)
            {
                float g = dy[t * outD + o];
                if (g == 0f) continue;
                VecOps.Axpy(g, xt, dW.AsSpan(o * inD, inD));
                VecOps.Axpy(g, W.AsSpan(o * inD, inD), dx.Slice(t * inD, inD));
            }
        }
    }

    internal static void RmsForward(ReadOnlySpan<float> x, float[] g, Span<float> inv, Span<float> y, int T, int D, float eps)
    {
        for (int t = 0; t < T; t++)
        {
            float ss = 0; for (int i = 0; i < D; i++) ss += x[t * D + i] * x[t * D + i];
            float r = 1f / MathF.Sqrt(ss / D + eps);
            inv[t] = r;
            for (int i = 0; i < D; i++) y[t * D + i] = x[t * D + i] * r * g[i];
        }
    }

    static void RmsBack(ReadOnlySpan<float> x, float[] g, float[] dg, ReadOnlySpan<float> inv, ReadOnlySpan<float> dy, Span<float> dx, int T, int D)
    {
        for (int t = 0; t < T; t++)
        {
            float r = inv[t], dot = 0;
            for (int i = 0; i < D; i++) dot += dy[t * D + i] * g[i] * x[t * D + i] * r;
            dot /= D;
            for (int i = 0; i < D; i++)
            {
                float xh = x[t * D + i] * r;
                dg[i] += dy[t * D + i] * xh;
                dx[t * D + i] += r * (dy[t * D + i] * g[i] - xh * dot);
            }
        }
    }

    /// <summary>Rotary embedding (раздел I.2): rotates each (2i, 2i+1) pair of every head by angle pos·θᵢ. inverse=true is the transpose, used in backprop.</summary>
    public void Rope(Span<float> row, int pos, int nHeads, bool inverse)
    {
        int hd = C.HeadDim, half = hd / 2;
        for (int h = 0; h < nHeads; h++)
            for (int i = 0; i < half; i++)
            {
                float c = Cos[pos * half + i], s = Sin[pos * half + i];
                float a = row[h * hd + 2 * i], b = row[h * hd + 2 * i + 1];
                if (!inverse) { row[h * hd + 2 * i] = a * c - b * s; row[h * hd + 2 * i + 1] = a * s + b * c; }
                else { row[h * hd + 2 * i] = a * c + b * s; row[h * hd + 2 * i + 1] = -a * s + b * c; }
            }
    }

    internal static float Silu(float a) => a / (1f + MathF.Exp(-a));

    // ---------- forward (full sequence, keeps everything for backprop) ----------
    public void Forward(ReadOnlySpan<int> tok, int T)
    {
        if (T > C.MaxSeq) throw new ArgumentException("sequence longer than MaxSeq");
        _T = T;
        int D = C.DModel, H = C.Heads, G = C.KvHeads, hd = C.HeadDim, F = C.FfnDim, V = C.Vocab, kv = C.KvDim, rep = H / G;
        float scale = 1f / MathF.Sqrt(hd);

        for (int t = 0; t < T; t++) Emb.W.AsSpan(tok[t] * D, D).CopyTo(_xs[0].AsSpan(t * D, D));

        for (int l = 0; l < C.Layers; l++)
        {
            var w = Layer[l];
            RmsForward(_xs[l], w.G1.W, _inv1[l], _n1[l], T, D, C.Eps);
            if (ActBits > 0) Quant.FakeQuantRows(_n1[l].AsSpan(0, T * D), T, D, ActBits);
            Linear(w.Wq.W, D, D, _n1[l], _q[l], T);
            Linear(w.Wk.W, kv, D, _n1[l], _k[l], T);
            Linear(w.Wv.W, kv, D, _n1[l], _v[l], T);
            for (int t = 0; t < T; t++)
            {
                Rope(_q[l].AsSpan(t * D, D), t, H, false);
                Rope(_k[l].AsSpan(t * kv, kv), t, G, false);
            }

            var p = _p[l]; var ao = _ao[l];
            for (int h = 0; h < H; h++)
            {
                int g = h / rep;
                for (int t = 0; t < T; t++)
                {
                    var qh = _q[l].AsSpan(t * D + h * hd, hd);
                    int pb = (h * T + t) * T;
                    float max = float.MinValue;
                    for (int s = 0; s <= t; s++)
                    {
                        float sc = VecOps.Dot(qh, _k[l].AsSpan(s * kv + g * hd, hd)) * scale;
                        p[pb + s] = sc; if (sc > max) max = sc;
                    }
                    float sum = 0;
                    for (int s = 0; s <= t; s++) { p[pb + s] = MathF.Exp(p[pb + s] - max); sum += p[pb + s]; }
                    var o = ao.AsSpan(t * D + h * hd, hd); o.Clear();
                    for (int s = 0; s <= t; s++)
                    {
                        p[pb + s] /= sum;
                        VecOps.Axpy(p[pb + s], _v[l].AsSpan(s * kv + g * hd, hd), o);
                    }
                }
            }

            var x2 = _x2[l];
            if (ActBits > 0) Quant.FakeQuantRows(ao.AsSpan(0, T * D), T, D, ActBits);
            Linear(w.Wo.W, D, D, ao, x2, T);
            for (int i = 0; i < T * D; i++) x2[i] += _xs[l][i];

            RmsForward(x2, w.G2.W, _inv2[l], _n2[l], T, D, C.Eps);
            if (ActBits > 0) Quant.FakeQuantRows(_n2[l].AsSpan(0, T * D), T, D, ActBits);
            Linear(w.Wg.W, F, D, _n2[l], _a[l], T);
            Linear(w.Wu.W, F, D, _n2[l], _u[l], T);
            for (int i = 0; i < T * F; i++) _hh[l][i] = Silu(_a[l][i]) * _u[l][i];
            if (ActBits > 0) Quant.FakeQuantRows(_hh[l].AsSpan(0, T * F), T, F, ActBits);
            var xo = _xs[l + 1];
            Linear(w.Wd.W, D, F, _hh[l], xo, T);
            for (int i = 0; i < T * D; i++) xo[i] += x2[i];
        }

        RmsForward(_xs[C.Layers], Gf.W, _invF, _nf, T, D, C.Eps);
        for (int t = 0; t < T; t++)
        {
            var nt = _nf.AsSpan(t * D, D);
            for (int v2 = 0; v2 < V; v2++) _logits[t * V + v2] = VecOps.Dot(nt, Emb.W.AsSpan(v2 * D, D));
        }
    }

    /// <summary>Mean next-token cross-entropy over the T positions; writes dL/dlogits scaled by <paramref name="scale"/>.</summary>
    public float Loss(ReadOnlySpan<int> targets, int T, float scale)
    {
        int V = C.Vocab; float total = 0;
        for (int t = 0; t < T; t++)
        {
            var l = _logits.AsSpan(t * V, V);
            float max = l[0]; for (int i = 1; i < V; i++) if (l[i] > max) max = l[i];
            float sum = 0; for (int i = 0; i < V; i++) sum += MathF.Exp(l[i] - max);
            float lse = MathF.Log(sum) + max;
            total += lse - l[targets[t]];
            for (int i = 0; i < V; i++) _dlog[t * V + i] = (MathF.Exp(l[i] - lse) - (i == targets[t] ? 1f : 0f)) * scale;
        }
        return total / T;
    }

    // ---------- backward ----------
    public void Backward(ReadOnlySpan<int> tok, int T)
    {
        int D = C.DModel, H = C.Heads, G = C.KvHeads, hd = C.HeadDim, F = C.FfnDim, V = C.Vocab, kv = C.KvDim, rep = H / G;
        float scale = 1f / MathF.Sqrt(hd);

        // LM head (tied): logits = nf · Embᵀ
        var dnf = _dn.AsSpan(0, T * D); dnf.Clear();
        for (int t = 0; t < T; t++)
        {
            var nt = _nf.AsSpan(t * D, D);
            for (int v2 = 0; v2 < V; v2++)
            {
                float g = _dlog[t * V + v2];
                if (g == 0f) continue;
                VecOps.Axpy(g, nt, Emb.G.AsSpan(v2 * D, D));
                VecOps.Axpy(g, Emb.W.AsSpan(v2 * D, D), dnf.Slice(t * D, D));
            }
        }
        var dcur = _dcur.AsSpan(0, T * D); dcur.Clear();
        RmsBack(_xs[C.Layers], Gf.W, Gf.G, _invF, dnf, dcur, T, D);

        for (int l = C.Layers - 1; l >= 0; l--)
        {
            var w = Layer[l];
            // --- FFN branch: out = x2 + Wd·(silu(a)⊙u)
            var dx2 = _dx2.AsSpan(0, T * D); dcur.CopyTo(dx2);
            var dhh = _dhh.AsSpan(0, T * F); dhh.Clear();
            LinearBack(w.Wd.W, w.Wd.G, D, F, _hh[l], dcur, dhh, T);
            var da = _da.AsSpan(0, T * F); var du = _du.AsSpan(0, T * F);
            for (int i = 0; i < T * F; i++)
            {
                float a = _a[l][i], sg = 1f / (1f + MathF.Exp(-a)), silu = a * sg;
                du[i] = dhh[i] * silu;
                da[i] = dhh[i] * _u[l][i] * sg * (1f + a * (1f - sg));
            }
            var dn2 = _dn.AsSpan(0, T * D); dn2.Clear();
            LinearBack(w.Wg.W, w.Wg.G, F, D, _n2[l], da, dn2, T);
            LinearBack(w.Wu.W, w.Wu.G, F, D, _n2[l], du, dn2, T);
            RmsBack(_x2[l], w.G2.W, w.G2.G, _inv2[l], dn2, dx2, T, D);

            // --- attention branch: x2 = xin + Wo·ao
            var dao = _dao.AsSpan(0, T * D); dao.Clear();
            LinearBack(w.Wo.W, w.Wo.G, D, D, _ao[l], dx2, dao, T);
            var dq = _dq.AsSpan(0, T * D); dq.Clear();
            var dk = _dk.AsSpan(0, T * kv); dk.Clear();
            var dv = _dv.AsSpan(0, T * kv); dv.Clear();
            var p = _p[l];
            for (int h = 0; h < H; h++)
            {
                int g = h / rep;
                for (int t = 0; t < T; t++)
                {
                    int pb = (h * T + t) * T;
                    var doh = dao.Slice(t * D + h * hd, hd);
                    float dot = 0;
                    for (int s = 0; s <= t; s++)
                    {
                        float dp = VecOps.Dot(doh, _v[l].AsSpan(s * kv + g * hd, hd));
                        _dp[s] = dp; dot += p[pb + s] * dp;
                        VecOps.Axpy(p[pb + s], doh, dv.Slice(s * kv + g * hd, hd));
                    }
                    var qh = _q[l].AsSpan(t * D + h * hd, hd);
                    for (int s = 0; s <= t; s++)
                    {
                        float ds = p[pb + s] * (_dp[s] - dot) * scale;
                        VecOps.Axpy(ds, _k[l].AsSpan(s * kv + g * hd, hd), dq.Slice(t * D + h * hd, hd));
                        VecOps.Axpy(ds, qh, dk.Slice(s * kv + g * hd, hd));
                    }
                }
            }
            for (int t = 0; t < T; t++)
            {
                Rope(dq.Slice(t * D, D), t, H, true);
                Rope(dk.Slice(t * kv, kv), t, G, true);
            }
            var dn1 = _dn.AsSpan(0, T * D); dn1.Clear();
            LinearBack(w.Wq.W, w.Wq.G, D, D, _n1[l], dq, dn1, T);
            LinearBack(w.Wk.W, w.Wk.G, kv, D, _n1[l], dk, dn1, T);
            LinearBack(w.Wv.W, w.Wv.G, kv, D, _n1[l], dv, dn1, T);
            dx2.CopyTo(dcur);                                  // residual path into the layer input
            RmsBack(_xs[l], w.G1.W, w.G1.G, _inv1[l], dn1, dcur, T, D);
        }

        for (int t = 0; t < T; t++) VecOps.Axpy(1f, dcur.Slice(t * D, D), Emb.G.AsSpan(tok[t] * D, D));
    }

    public void ZeroGrads() { foreach (var p in Params) Array.Clear(p.G); }

    /// <summary>One optimiser step over a mini-batch of (input, target) sequences. Returns the mean loss.</summary>
    public float TrainBatch(IReadOnlyList<(int[] Tok, int[] Tgt)> batch, Adam opt)
    {
        ZeroGrads();
        float loss = 0, scale = 1f / batch.Count;
        foreach (var (tok, tgt) in batch)
        {
            Forward(tok, tok.Length);
            loss += Loss(tgt, tok.Length, scale / tok.Length) * scale;
            Backward(tok, tok.Length);
        }
        opt.Step(Params);
        return loss;
    }

    /// <summary>Loss without touching gradients (evaluation).</summary>
    public float Evaluate(int[] tok, int[] tgt) { Forward(tok, tok.Length); return Loss(tgt, tok.Length, 0f); }
}
