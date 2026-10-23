using GLF.Neural;
using GLF.Neural.Transformer;

namespace GLF.Tests;

public class SystemsTests
{
    static TransformerModel Model(ulong seed = 4) => new(new TransformerConfig(30, 32, 2, Heads: 8, KvHeads: 2, FfnDim: 64, MaxSeq: 16), seed);
    static int[] Tokens(int n, ulong seed = 8) { var r = new Rng(seed); return Enumerable.Range(0, n).Select(_ => r.NextInt(30)).ToArray(); }

    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(4)]
    [InlineData(8)]
    public void Tensor_parallel_forward_equals_single_device_with_two_allreduces_per_layer(int P)
    {
        var m = Model(); var tok = Tokens(12);
        m.Forward(tok, tok.Length); var single = m.Logits.ToArray();
        var tp = TensorParallel.Forward(m, tok, P, out var st);
        Assert.Equal(single.Length, tp.Length);
        for (int i = 0; i < single.Length; i++) Assert.Equal(single[i], tp[i], 4);
        Assert.Equal(2 * m.C.Layers, st.AllReduces);
    }

    [Fact]
    public void Pipeline_bubble_matches_theory_and_1f1b_bounds_activation_memory()
    {
        foreach (var (S, M) in new[] { (4, 8), (4, 32), (8, 16) })
        {
            var gp = Pipeline.Simulate("g", S, M, false);
            var f1 = Pipeline.Simulate("f", S, M, true);
            Assert.Equal(Pipeline.TheoreticalBubble(S, M), gp.BubbleFraction, 9);
            Assert.Equal(Pipeline.TheoreticalBubble(S, M), f1.BubbleFraction, 9);   // 1F1B does not shrink the bubble...
            Assert.All(gp.PeakInFlight, p => Assert.Equal(M, p));
            Assert.All(f1.PeakInFlight, p => Assert.True(p <= S));                  // ...it bounds memory by the stage count
        }
    }

    [Fact]
    public void Zero_memory_formulas()
    {
        double phi = 1e9;
        Assert.Equal(16 * phi, ZeroMemory.PerGpu(0, phi, 8));
        Assert.Equal(16 * phi / 8, ZeroMemory.PerGpu(3, phi, 8));
        Assert.True(ZeroMemory.PerGpu(1, phi, 8) > ZeroMemory.PerGpu(2, phi, 8));
        Assert.True(ZeroMemory.PerGpu(2, phi, 8) > ZeroMemory.PerGpu(3, phi, 8));
    }

    [Fact]
    public void Int8_gemm_matches_float_and_quantisation_error_is_bounded()
    {
        var r = new Rng(3); int D = 64;
        var W = new float[D * D]; for (int i = 0; i < W.Length; i++) W[i] = r.NextGaussian() * .1f;
        var x = new float[D]; for (int i = 0; i < D; i++) x[i] = r.NextGaussian();
        var y = new float[D]; new Int8Linear(W, D, D).Forward(x, y);
        double e = 0, n = 0;
        for (int o = 0; o < D; o++) { float s = VecOps.Dot(W.AsSpan(o * D, D), x); e += (s - y[o]) * (s - y[o]); n += s * s; }
        Assert.True(Math.Sqrt(e / n) < 0.03);

        var g = new float[16]; for (int i = 0; i < 16; i++) g[i] = r.NextGaussian();
        var q = (float[])g.Clone(); Quant.FakeQuantGroup(q, 4);
        float scale = g.Max(MathF.Abs) / 7f;
        for (int i = 0; i < 16; i++) Assert.True(MathF.Abs(q[i] - g[i]) <= scale / 2 + 1e-6f);
    }

    [Fact]
    public void SmoothQuant_is_exact_in_float_and_tames_outlier_channels()
    {
        var m = Model(); var tok = Tokens(14);
        var cal = Quantizer.Calibrate(m, new[] { Tokens(16, 1), Tokens(16, 2) });
        m.Forward(tok, tok.Length); var before = m.Logits.ToArray();
        var sm = m.Clone(); Quantizer.SmoothQuant(sm, cal, 0.5);
        sm.Forward(tok, tok.Length);
        for (int i = 0; i < before.Length; i++) Assert.Equal(before[i], sm.Logits[i], 3);

        var r = new Rng(9); int D = 64, N = 128;
        var W = new float[D * D]; for (int i = 0; i < W.Length; i++) W[i] = r.NextGaussian() * .1f;
        var X = new float[N * D]; for (int i = 0; i < X.Length; i++) X[i] = r.NextGaussian();
        for (int t = 0; t < N; t++) X[t * D + 3] *= 60f;
        float[] Mat(float[] w, float[] x) { var y = new float[N * D]; for (int t = 0; t < N; t++) for (int o = 0; o < D; o++) y[t * D + o] = VecOps.Dot(w.AsSpan(o * D, D), x.AsSpan(t * D, D)); return y; }
        double Rel(float[] a, float[] b) { double e = 0, n = 0; for (int i = 0; i < a.Length; i++) { e += (a[i] - b[i]) * (a[i] - b[i]); n += b[i] * b[i]; } return Math.Sqrt(e / n); }
        var yref = Mat(W, X);
        var w1 = (float[])W.Clone(); var x1 = (float[])X.Clone(); Quant.FakeQuantWeights(w1, D, D, 8, 0); Quant.FakeQuantRows(x1, N, D, 8);
        var amax = new float[D]; for (int t = 0; t < N; t++) for (int j = 0; j < D; j++) amax[j] = MathF.Max(amax[j], MathF.Abs(X[t * D + j]));
        var s = Quantizer.SmoothScales(amax, new List<(float[], int)> { (W, D) }, D, 0.5);
        var w2 = (float[])W.Clone(); var x2 = (float[])X.Clone();
        for (int o = 0; o < D; o++) for (int j = 0; j < D; j++) w2[o * D + j] *= s[j];
        for (int t = 0; t < N; t++) for (int j = 0; j < D; j++) x2[t * D + j] /= s[j];
        Quant.FakeQuantWeights(w2, D, D, 8, 0); Quant.FakeQuantRows(x2, N, D, 8);
        Assert.True(Rel(Mat(w2, x2), yref) < Rel(Mat(w1, x1), yref) / 3);
    }

    [Fact]
    public void Awq_is_never_worse_than_round_to_nearest_on_calibration_output()
    {
        var m = Model(5); var cal = Quantizer.Calibrate(m, new[] { Tokens(16, 1), Tokens(16, 2), Tokens(16, 3) });
        var tok = Tokens(16, 4);
        m.Forward(tok, tok.Length); var fp = m.Logits.ToArray();
        double Err(TransformerModel q) { q.Forward(tok, tok.Length); double e = 0; for (int i = 0; i < fp.Length; i++) e += (q.Logits[i] - fp[i]) * (q.Logits[i] - fp[i]); return e; }
        var rtn = m.Clone(); Quantizer.Rtn(rtn, 3, 16);
        var awq = m.Clone(); Quantizer.Awq(awq, cal, 3, 16);
        Assert.True(Err(awq) <= Err(rtn) * 1.25, $"awq {Err(awq)} rtn {Err(rtn)}");
    }

    [Fact]
    public void Replay_prevents_catastrophic_forgetting_that_naive_training_suffers()
    {
        var rng = new Rng(4);
        (float[] X, int[] Y) Make(int n, bool left)
        {
            var x = new float[n * 2]; var y = new int[n];
            for (int i = 0; i < n; i++)
            {
                float x1 = (float)rng.NextDouble(), x2 = (float)(rng.NextDouble() * 2 - 1);
                if (left) x1 = -x1;
                x[i * 2] = x1; x[i * 2 + 1] = x2; y[i] = left ? (x2 > 0 ? 1 : 0) : (x2 < 0 ? 1 : 0);
            }
            return (x, y);
        }
        var (xa, ya) = Make(2000, true); var (xb, yb) = Make(2000, false); var (xat, yat) = Make(500, true);
        double Acc(Network net) { int ok = 0; for (int i = 0; i < yat.Length; i++) { var o = net.Forward(xat.AsSpan(i * 2, 2)); if ((o[1] > o[0] ? 1 : 0) == yat[i]) ok++; } return ok / (double)yat.Length; }
        var tr = new Rng(9);
        void Train(Network net, bool replay)
        {
            var bx = new float[128]; var by = new int[64];
            for (int s = 0; s < 400; s++)
            {
                for (int b = 0; b < 64; b++)
                {
                    bool mem = replay && b >= 48;
                    int i = tr.NextInt(mem ? 200 : 2000);
                    var sx = mem ? xa : xb; var sy = mem ? ya : yb;
                    bx[b * 2] = sx[i * 2]; bx[b * 2 + 1] = sx[i * 2 + 1]; by[b] = sy[i];
                }
                net.TrainStepClassify(bx, by, 64);
            }
        }
        Network Fresh() { var n = Mlp.Build(2, new[] { 32, 32 }, 2, Act.Gelu, maxBatch: 64, seed: 3, lr: 0.01f); var bx = xa; for (int s = 0; s < 400; s++) { var x = new float[128]; var y = new int[64]; for (int b = 0; b < 64; b++) { int i = tr.NextInt(2000); x[b * 2] = xa[i * 2]; x[b * 2 + 1] = xa[i * 2 + 1]; y[b] = ya[i]; } n.TrainStepClassify(x, y, 64); } return n; }
        var naive = Fresh(); Assert.True(Acc(naive) > 0.95); Train(naive, false);
        var rep = Fresh(); Train(rep, true);
        Assert.True(Acc(naive) < 0.5, $"naive {Acc(naive)}");
        Assert.True(Acc(rep) > 0.9, $"replay {Acc(rep)}");
    }
}
