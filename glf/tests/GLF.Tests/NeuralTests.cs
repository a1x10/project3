using GLF.Neural;

namespace GLF.Tests;

public class NeuralTests
{
    // Numerical vs analytic gradient of an MSE loss w.r.t. every parameter and every input.
    static void GradCheck(Network net, int batch, ulong seed = 5, float eps = 1e-2f, float absTol = 0f)
    {
        var rng = new Rng(seed);
        var x = new float[batch * net.In]; var t = new float[batch * net.Out];
        for (int i = 0; i < x.Length; i++) x[i] = rng.NextGaussian();
        for (int i = 0; i < t.Length; i++) t[i] = rng.NextGaussian();

        float L() { var o = net.Forward(x, batch); var g = new float[o.Length]; return Loss.Compute(LossKind.Mse, o, t, g, batch, net.Out); }

        foreach (var p in net.Params) Array.Clear(p.G);
        var o0 = net.Forward(x, batch).ToArray(); var dOut = new float[o0.Length];
        Loss.Compute(LossKind.Mse, o0, t, dOut, batch, net.Out);
        var dx = new float[x.Length];
        net.Body.Backward(x, o0, dOut, batch, dx, true);

        foreach (var p in net.Params)
            for (int i = 0; i < p.W.Length; i += Math.Max(1, p.W.Length / 12))
            {
                float w = p.W[i];
                p.W[i] = w + eps; float lp = L();
                p.W[i] = w - eps; float lm = L();
                p.W[i] = w;
                float num = (lp - lm) / (2 * eps), ana = p.G[i];
                Assert.True(Math.Abs(num - ana) < absTol || Math.Abs(num - ana) / (Math.Abs(num) + Math.Abs(ana) + 1e-2f) < 0.05f, $"{p.Name}[{i}] numeric={num} analytic={ana}");
            }
        for (int i = 0; i < x.Length; i += 3)
        {
            float v = x[i];
            x[i] = v + eps; float lp = L();
            x[i] = v - eps; float lm = L();
            x[i] = v;
            float num = (lp - lm) / (2 * eps);
            Assert.True(Math.Abs(num - dx[i]) < absTol || Math.Abs(num - dx[i]) / (Math.Abs(num) + Math.Abs(dx[i]) + 1e-2f) < 0.05f, $"dx[{i}] numeric={num} analytic={dx[i]}");
        }
    }

    [Theory]
    [InlineData(Act.Tanh)]
    [InlineData(Act.Sigmoid)]
    [InlineData(Act.Gelu)]
    [InlineData(Act.Silu)]
    [InlineData(Act.ReLU)]
    [InlineData(Act.LeakyReLU)]
    public void Gradients_match_numerical_for_every_activation(Act act)
        => GradCheck(Mlp.Build(5, new[] { 7, 6 }, 3, act, maxBatch: 4, seed: 3), batch: 4, eps: act == Act.ReLU ? 1e-3f : 1e-2f, absTol: act == Act.ReLU ? 1e-2f : 0f); // ReLU kink + float32 loss resolution

    [Fact]
    public void Gradients_match_numerical_with_layernorm()
        => GradCheck(Mlp.Build(6, new[] { 8, 8 }, 2, Act.Tanh, layerNorm: true, maxBatch: 4, seed: 4), batch: 4);

    [Fact]
    public void Gradients_match_numerical_through_residual_block()
    {
        var rng = new Rng(9);
        var inner = new Sequential(3, new Dense(6, 6, ref rng, .4f), new Activation(Act.Tanh, 6), new Dense(6, 6, ref rng, .4f));
        var body = new Sequential(3, new Dense(4, 6, ref rng, .5f), new Residual(inner), new LayerNorm(6, 3), new Activation(Act.Gelu, 6), new Dense(6, 2, ref rng, .3f));
        GradCheck(new Network(body), batch: 3);
    }

    [Fact]
    public void Network_learns_xor()
    {
        var net = Mlp.Build(2, new[] { 8 }, 1, Act.Tanh, maxBatch: 4, seed: 2, lr: 0.02f);
        float[] x = { 0, 0, 0, 1, 1, 0, 1, 1 }, y = { 0, 1, 1, 0 };
        float loss = 0;
        for (int i = 0; i < 1500; i++) loss = net.TrainStep(x, y, 4);
        Assert.True(loss < 0.01f, $"loss {loss}");
        var o = net.Forward(x, 4);
        Assert.True(o[0] < .15f && o[1] > .85f && o[2] > .85f && o[3] < .15f);
    }

    [Fact]
    public void Softmax_classifier_separates_three_clusters()
    {
        var net = Mlp.Build(2, new[] { 12 }, 3, Act.Gelu, maxBatch: 30, seed: 6, lr: 0.01f);
        var rng = new Rng(8);
        var x = new float[60]; var lab = new int[30];
        for (int i = 0; i < 30; i++)
        {
            int c = i % 3; lab[i] = c;
            x[i * 2] = MathF.Cos(c * 2.1f) * 2 + rng.NextGaussian() * .3f;
            x[i * 2 + 1] = MathF.Sin(c * 2.1f) * 2 + rng.NextGaussian() * .3f;
        }
        float loss = 0;
        for (int i = 0; i < 400; i++) loss = net.TrainStepClassify(x, lab, 30);
        Assert.True(loss < 0.1f);
        int ok = 0;
        var o = net.Forward(x, 30);
        for (int i = 0; i < 30; i++)
        {
            int arg = 0; for (int c = 1; c < 3; c++) if (o[i * 3 + c] > o[i * 3 + arg]) arg = c;
            if (arg == lab[i]) ok++;
        }
        Assert.Equal(30, ok);
    }

    [Fact]
    public void Save_and_load_roundtrip_preserves_outputs()
    {
        var a = Mlp.Build(4, new[] { 8, 8 }, 2, seed: 1);
        var b = Mlp.Build(4, new[] { 8, 8 }, 2, seed: 99);
        float[] x = { .1f, -.2f, .3f, .4f };
        var ms = new MemoryStream();
        a.Save(ms); ms.Position = 0; b.Load(ms);
        Assert.Equal(a.Forward(x).ToArray(), b.Forward(x).ToArray());
    }

    [Fact]
    public void Train_and_inference_do_not_allocate()
    {
        var net = Mlp.Build(6, new[] { 32, 16 }, 1, maxBatch: 8, layerNorm: true);
        var x = new float[8 * 6]; var y = new float[8];
        for (int i = 0; i < 20; i++) { net.TrainStep(x, y, 8); net.Forward(x, 1); }
        long a0 = GC.GetAllocatedBytesForCurrentThread();
        for (int i = 0; i < 200; i++) { net.TrainStep(x, y, 8, LossKind.Huber); net.Forward(x, 1); net.InputGradient(x, 0); }
        Assert.Equal(0, GC.GetAllocatedBytesForCurrentThread() - a0);
    }

    [Fact]
    public void Standardizer_tracks_mean_and_std()
    {
        var s = new OnlineStandardizer(1, 0.01);
        var rng = new Rng(1);
        Span<double> v = stackalloc double[1];
        for (int i = 0; i < 5000; i++) { v[0] = 10 + 3 * rng.NextGaussian(); s.Update(v); }
        Assert.InRange(s.Mean(0), 9.5, 10.5);
        Assert.InRange(s.Std(0), 2.5, 3.5);
    }

    [Fact]
    public void FormulaDiscovery_recovers_exact_formula_from_data()
    {
        var rng = new Rng(3);
        var X = new double[3000][]; var y = new double[3000];
        for (int i = 0; i < X.Length; i++)
        {
            X[i] = new double[] { rng.NextDouble() * 2 - 1, rng.NextDouble() * 2 - 1, rng.NextDouble() * 2 - 1 };
            y[i] = 2 * Math.Sin(3 * X[i][0]) * X[i][1] + X[i][2] * X[i][2] - 0.5 * X[i][0] * X[i][2];
        }
        var f = FormulaDiscovery.Fit(FormulaDiscovery.Library(new[] { "x1", "x2", "x3" }), X, y);
        Assert.True(f.R2 > 0.9999, f.ToString());
        var s = f.ToString();
        Assert.Contains("sin(3x1)·x2", s); Assert.Contains("x3²", s); Assert.Contains("x1·x3", s);
        Assert.True(f.Terms.Length <= 4, s);
    }

    [Fact]
    public void Online_neural_model_learns_an_interaction_that_ridge_cannot()
    {
        var lin = new GLF.Trading.Models.RlsModel(3, 0.9999);
        var nn = new GLF.Trading.Models.NeuralModel(2, new[] { 32, 16 }, 2e-3f);
        var rng = new Rng(5); var x = new double[3]; var x2 = new double[2];
        double seL = 0, seN = 0; int cnt = 0;
        for (int i = 0; i < 100_000; i++)
        {
            double a = rng.NextDouble() * 2 - 1, b = rng.NextDouble() * 2 - 1;
            double y = 3 * a * Math.Sign(b) + 0.5 * rng.NextGaussian();
            x[0] = 1; x[1] = a; x[2] = b; x2[0] = a; x2[1] = b;
            if (i >= 50_000) { double e1 = lin.Predict(x) - y, e2 = nn.Predict(x2) - y; seL += e1 * e1; seN += e2 * e2; cnt++; }
            lin.Learn(x, y); nn.Learn(x2, y);
        }
        double rl = Math.Sqrt(seL / cnt), rn = Math.Sqrt(seN / cnt);
        Assert.True(rl > 1.5, $"linear {rl}");
        Assert.True(rn < 0.8 * rl, $"neural {rn} vs linear {rl}");
    }

    [Fact]
    public void Ridge_model_stays_bounded_on_a_long_stream_with_a_nearly_constant_feature()
    {
        var m = new GLF.Trading.Models.Rls(3, 0.999);
        var rng = new Rng(2); var x = new double[3];
        for (int i = 0; i < 300_000; i++)
        {
            x[0] = 1; x[1] = 1.0 + (i % 5000 == 0 ? 1 : 0); x[2] = rng.NextGaussian();
            m.Update(x, 2 * x[2] + rng.NextGaussian());
        }
        foreach (var w in m.Weights) Assert.True(Math.Abs(w) < 50, $"weight {w}");
        x[0] = 1; x[1] = 1; x[2] = 1;
        Assert.InRange(m.Predict(x), 0, 4);
    }
}
