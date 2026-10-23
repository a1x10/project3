namespace GLF.Neural.Transformer;

/// <summary>
/// Autoregressive inference with a KV cache (раздел III). Keys/values of every processed position are stored once (post-RoPE);
/// a new token only computes its own q/k/v and attends over the cache, so one step costs O(N) instead of recomputing the whole prefix.
/// </summary>
public sealed class KvDecoder
{
    readonly TransformerModel _m;
    readonly TransformerConfig C;
    readonly float[][] _kc, _vc;
    readonly float[] _x, _n, _q, _k, _v, _ao, _x2, _a, _u, _hh, _dn, _logits, _inv = new float[1], _score;
    public int Position { get; private set; }
    /// <summary>Multiply-adds spent in attention scores + value mixing over the last step: grows linearly with position.</summary>
    public long LastStepAttentionMacs { get; private set; }

    public KvDecoder(TransformerModel m)
    {
        _m = m; C = m.C;
        _kc = new float[C.Layers][]; _vc = new float[C.Layers][];
        for (int l = 0; l < C.Layers; l++) { _kc[l] = new float[C.MaxSeq * C.KvDim]; _vc[l] = new float[C.MaxSeq * C.KvDim]; }
        int D = C.DModel, F = C.FfnDim, kv = C.KvDim;
        _x = new float[D]; _n = new float[D]; _q = new float[D]; _k = new float[kv]; _v = new float[kv]; _ao = new float[D];
        _x2 = new float[D]; _a = new float[F]; _u = new float[F]; _hh = new float[F]; _dn = new float[D];
        _logits = new float[C.Vocab]; _score = new float[C.MaxSeq];
    }

    public void Reset() => Position = 0;

    public ReadOnlySpan<float> Step(int token)
    {
        int pos = Position;
        if (pos >= C.MaxSeq) throw new InvalidOperationException("context window full");
        int D = C.DModel, H = C.Heads, G = C.KvHeads, hd = C.HeadDim, F = C.FfnDim, kv = C.KvDim, rep = H / G;
        float scale = 1f / MathF.Sqrt(hd);
        long macs = 0;

        _m.Emb.W.AsSpan(token * D, D).CopyTo(_x);
        for (int l = 0; l < C.Layers; l++)
        {
            var w = _m.Layer[l];
            TransformerModel.RmsForward(_x, w.G1.W, _inv, _n, 1, D, C.Eps);
            TransformerModel.Linear(w.Wq.W, D, D, _n, _q, 1);
            TransformerModel.Linear(w.Wk.W, kv, D, _n, _k, 1);
            TransformerModel.Linear(w.Wv.W, kv, D, _n, _v, 1);
            _m.Rope(_q, pos, H, false);
            _m.Rope(_k, pos, G, false);
            _k.CopyTo(_kc[l].AsSpan(pos * kv, kv)); _v.CopyTo(_vc[l].AsSpan(pos * kv, kv));

            for (int h = 0; h < H; h++)
            {
                int g = h / rep;
                var qh = _q.AsSpan(h * hd, hd);
                float max = float.MinValue;
                for (int s = 0; s <= pos; s++)
                {
                    float sc = VecOps.Dot(qh, _kc[l].AsSpan(s * kv + g * hd, hd)) * scale;
                    _score[s] = sc; if (sc > max) max = sc;
                }
                float sum = 0;
                for (int s = 0; s <= pos; s++) { _score[s] = MathF.Exp(_score[s] - max); sum += _score[s]; }
                var o = _ao.AsSpan(h * hd, hd); o.Clear();
                for (int s = 0; s <= pos; s++) VecOps.Axpy(_score[s] / sum, _vc[l].AsSpan(s * kv + g * hd, hd), o);
                macs += 2L * (pos + 1) * hd;
            }

            TransformerModel.Linear(w.Wo.W, D, D, _ao, _x2, 1);
            for (int i = 0; i < D; i++) _x2[i] += _x[i];
            TransformerModel.RmsForward(_x2, w.G2.W, _inv, _n, 1, D, C.Eps);
            TransformerModel.Linear(w.Wg.W, F, D, _n, _a, 1);
            TransformerModel.Linear(w.Wu.W, F, D, _n, _u, 1);
            for (int i = 0; i < F; i++) _hh[i] = TransformerModel.Silu(_a[i]) * _u[i];
            TransformerModel.Linear(w.Wd.W, D, F, _hh, _dn, 1);
            for (int i = 0; i < D; i++) _x[i] = _x2[i] + _dn[i];
        }
        TransformerModel.RmsForward(_x, _m.Gf.W, _inv, _n, 1, D, C.Eps);
        for (int v = 0; v < C.Vocab; v++) _logits[v] = VecOps.Dot(_n, _m.Emb.W.AsSpan(v * D, D));
        Position++;
        LastStepAttentionMacs = macs;
        return _logits;
    }

    /// <summary>Prefill the prompt, then sample <paramref name="count"/> tokens.</summary>
    public List<int> Generate(ReadOnlySpan<int> prompt, int count, float temperature, int topK, float topP, ref Rng rng)
    {
        Reset();
        ReadOnlySpan<float> logits = default;
        foreach (int t in prompt) logits = Step(t);
        var outp = new List<int>(count);
        for (int i = 0; i < count && Position < C.MaxSeq; i++)
        {
            int next = Sampler.Sample(logits, temperature, topK, topP, ref rng);
            outp.Add(next);
            logits = Step(next);
        }
        return outp;
    }
}
