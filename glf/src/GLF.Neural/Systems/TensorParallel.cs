using GLF.Neural.Transformer;

namespace GLF.Neural;

public sealed class TpStats
{
    public int AllReduces;
    public long AllReduceFloats;
    public long KvFloatsPerShard, KvFloatsSingleDevice;
}

/// <summary>
/// Megatron-style tensor parallelism simulated on one machine, to check the maths of the spec exactly:
/// Wq/Wk/Wv and Wgate/Wup are split by output features (column-parallel, no communication, input replicated),
/// Wo and Wdown are split by input features (row-parallel), and the partial products are summed by an All-Reduce.
/// Exactly two All-Reduces per layer in the forward pass. When there are fewer KV heads than shards, KV heads are replicated.
/// </summary>
public static class TensorParallel
{
    // y[t, i] = x[t,:] · W[row0+i, :]           (column-parallel: a slice of output features)
    static void LinRows(float[] w, int row0, int nRows, int inD, ReadOnlySpan<float> x, Span<float> y, int T)
    {
        for (int t = 0; t < T; t++)
            for (int i = 0; i < nRows; i++) y[t * nRows + i] = VecOps.Dot(x.Slice(t * inD, inD), w.AsSpan((row0 + i) * inD, inD));
    }

    // y[t, o] = x[t,:nCols] · W[o, col0 : col0+nCols]   (row-parallel: a slice of input features, full-width partial output)
    static void LinCols(float[] w, int outD, int inTotal, int col0, int nCols, ReadOnlySpan<float> x, Span<float> y, int T)
    {
        for (int t = 0; t < T; t++)
            for (int o = 0; o < outD; o++) y[t * outD + o] = VecOps.Dot(x.Slice(t * nCols, nCols), w.AsSpan(o * inTotal + col0, nCols));
    }

    public static float[] Forward(TransformerModel m, int[] tok, int P, out TpStats st)
    {
        var C = m.C;
        int D = C.DModel, H = C.Heads, G = C.KvHeads, hd = C.HeadDim, F = C.FfnDim, V = C.Vocab, T = tok.Length, rep = H / G;
        if (H % P != 0 || F % P != 0) throw new ArgumentException("heads and ffn width must divide by P");
        int hqp = H / P, qd = hqp * hd, fp = F / P;
        float scale = 1f / MathF.Sqrt(hd);
        st = new TpStats { KvFloatsSingleDevice = 2L * C.KvDim * T };

        var x = new float[T * D];
        for (int t = 0; t < T; t++) m.Emb.W.AsSpan(tok[t] * D, D).CopyTo(x.AsSpan(t * D, D));
        var n = new float[T * D]; var inv = new float[T];

        for (int l = 0; l < C.Layers; l++)
        {
            var w = m.Layer[l];
            TransformerModel.RmsForward(x, w.G1.W, inv, n, T, D, C.Eps);      // input replicated on every shard (Identity op)
            var z = new float[T * D];                                          // All-Reduce accumulator
            for (int p = 0; p < P; p++)
            {
                int g0 = (p * hqp) / rep, g1 = ((p + 1) * hqp - 1) / rep, ng = g1 - g0 + 1;
                var q = new float[T * qd]; var k = new float[T * ng * hd]; var v = new float[T * ng * hd];
                LinRows(w.Wq.W, p * qd, qd, D, n, q, T);
                LinRows(w.Wk.W, g0 * hd, ng * hd, D, n, k, T);
                LinRows(w.Wv.W, g0 * hd, ng * hd, D, n, v, T);
                for (int t = 0; t < T; t++) { m.Rope(q.AsSpan(t * qd, qd), t, hqp, false); m.Rope(k.AsSpan(t * ng * hd, ng * hd), t, ng, false); }
                st.KvFloatsPerShard = 2L * ng * hd * T;

                var ao = new float[T * qd]; var sc = new float[T];
                for (int hl = 0; hl < hqp; hl++)
                {
                    int gl = (p * hqp + hl) / rep - g0;
                    for (int t = 0; t < T; t++)
                    {
                        var qh = q.AsSpan(t * qd + hl * hd, hd);
                        float max = float.MinValue;
                        for (int s = 0; s <= t; s++) { sc[s] = VecOps.Dot(qh, k.AsSpan(s * ng * hd + gl * hd, hd)) * scale; if (sc[s] > max) max = sc[s]; }
                        float sum = 0; for (int s = 0; s <= t; s++) { sc[s] = MathF.Exp(sc[s] - max); sum += sc[s]; }
                        var o = ao.AsSpan(t * qd + hl * hd, hd);
                        for (int s = 0; s <= t; s++) VecOps.Axpy(sc[s] / sum, v.AsSpan(s * ng * hd + gl * hd, hd), o);
                    }
                }
                var zp = new float[T * D];
                LinCols(w.Wo.W, D, D, p * qd, qd, ao, zp, T);                  // Z_p = Attention_p · W_O,p
                for (int i = 0; i < z.Length; i++) z[i] += zp[i];              // All-Reduce (Sum)
            }
            st.AllReduces++; st.AllReduceFloats += (long)T * D;
            for (int i = 0; i < x.Length; i++) x[i] += z[i];

            TransformerModel.RmsForward(x, w.G2.W, inv, n, T, D, C.Eps);
            var f = new float[T * D];
            for (int p = 0; p < P; p++)
            {
                var gate = new float[T * fp]; var up = new float[T * fp];
                LinRows(w.Wg.W, p * fp, fp, D, n, gate, T);
                LinRows(w.Wu.W, p * fp, fp, D, n, up, T);
                for (int i = 0; i < gate.Length; i++) gate[i] = TransformerModel.Silu(gate[i]) * up[i];   // H_p, Hadamard product stays local
                var op = new float[T * D];
                LinCols(w.Wd.W, D, F, p * fp, fp, gate, op, T);                // Out_p = H_p · W_down,p
                for (int i = 0; i < f.Length; i++) f[i] += op[i];              // All-Reduce (Sum)
            }
            st.AllReduces++; st.AllReduceFloats += (long)T * D;
            for (int i = 0; i < x.Length; i++) x[i] += f[i];
        }

        TransformerModel.RmsForward(x, m.Gf.W, inv, n, T, D, C.Eps);
        var logits = new float[T * V];
        for (int t = 0; t < T; t++) for (int v2 = 0; v2 < V; v2++) logits[t * V + v2] = VecOps.Dot(n.AsSpan(t * D, D), m.Emb.W.AsSpan(v2 * D, D));
        return logits;
    }
}
