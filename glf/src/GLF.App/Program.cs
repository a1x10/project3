using System.Text;
using GLF.Agent;
using GLF.Agent.Vision;
using GLF.Core;
using GLF.Neural;
using GLF.Neural.Transformer;
using GLF.Market;
using GLF.Trading;
using GLF.Trading.Sim;
using GLF.Trading.Models;

var a = new Args(args);
switch (a.Command)
{
    case "bench": Bench(a); break;
    case "backtest": Backtest(a); break;
    case "sweep": Sweep(a); break;
    case "agent": RunAgent(a); break;
    case "vision": RunVision(a); break;
    case "neural": NeuralDemo(a); break;
    case "gpt": GptDemo(a); break;
    case "quant": QuantDemo(a); break;
    case "scale": ScaleDemo(a); break;
    case "continual": ContinualDemo(a); break;
    case "regime-test": RegimeTest(a); break;
    case "evaluate": Evaluate(a); break;
    case "make-test-data": MakeTestData(a); break;
    case "live": await Live(a); break;
    default:
        Console.WriteLine("""
        GLF - low-latency trading core + model-based agent

          bench     [--events N]                       hot-path latency + allocation check on synthetic data
          backtest  [--events N] [--fee bps] [--latency events] [--file f.jsonl --tick 0.01 --lot 0.001]
          sweep     [--events N]                       PnL vs fee and latency (synthetic)
          agent     [--episodes N]                     model-based agent escapes a locked room it knows nothing about
          vision    [--episodes N] [--noise 12] [--shuffle] [--palette 3]   agent learns the room from raw pixels
          neural    fit | trade [--events N]          neurons learn an unknown formula and print it / compete with linear models in trading
          gpt       [--steps N --dim 64 --layers 2]      tiny decoder transformer (BPE, RoPE, GQA, KV-cache, SwiGLU, sampling) trained from scratch
          quant     [--steps N]                          INT8/INT4 quantisation: naive vs SmoothQuant vs AWQ, measured perplexity
          scale                                          tensor parallelism (exact), 1F1B pipeline schedule, ZeRO memory
          continual                                      catastrophic forgetting vs replay vs EWC
          regime-test [--block 15000 --blocks 6 --strength 8]   long alternating regimes: does regime replay stop forgetting?
          evaluate  --file f.jsonl [--chunk 20000]       the same forecasting report on recorded real data
          make-test-data --out f.jsonl [--events N]      write a synthetic file in the recorded-feed format (tests the evaluate pipeline end to end)
          live      --symbol btcusdt [--seconds 60] [--record f.jsonl] [--paper] [--tick 0.01 --lot 0.001 --fee 4]
                    public market data only; --paper simulates fills locally. No real orders are ever sent.
        """);
        break;
}

static EngineConfig Cfg(Args a, double tick = 0.01, double lot = 1.0, double fee = 1.0) => new()
{
    TickSize = a.Dbl("tick", tick),
    LotQty = a.Dbl("lot", lot),
    FeeBps = a.Dbl("fee", fee),
};

static void Bench(Args a)
{
    long n = a.Lng("events", 2_000_000);
    var cfg = Cfg(a);
    var engine = new TradingEngine(cfg);
    var snap = new BookSnapshot();
    var hist = new LatencyHistogram();
    HotThread.Prepare(0);

    var warm = new SyntheticMarket(300_000, 7);
    while (warm.Next(snap)) engine.Process(snap, snap.TsNs, out _);

    var src = new SyntheticMarket(n, 11);
    long alloc0 = GC.GetAllocatedBytesForCurrentThread();
    int gc0 = GC.CollectionCount(0);
    while (src.Next(snap))
    {
        long t0 = Clock.Now();
        engine.Process(snap, snap.TsNs, out _);
        hist.Record(Clock.ToNs(Clock.Now() - t0));
    }
    long alloc = GC.GetAllocatedBytesForCurrentThread() - alloc0;
    Console.WriteLine(hist.Summary("snapshot->book->features->8 hypotheses (2 online neural nets)->decision->risk"));
    Console.WriteLine($"heap allocated in hot loop (incl. generator): {alloc} bytes, gen0 GCs: {GC.CollectionCount(0) - gc0}");
}

static void Backtest(Args a)
{
    var cfg = Cfg(a);
    int lat = (int)a.Lng("latency", 1);
    BacktestResult r;
    if (a.Str("file") is { } f)
    {
        cfg = Cfg(a, 0.01, 0.001, 4.0);
        using var rp = new JsonLinesReplay(f);
        r = Backtester.Run(rp, cfg, lat);
        Console.WriteLine($"replay skipped lines: {rp.Skipped}");
    }
    else r = Backtester.Run(new SyntheticMarket(a.Lng("events", 1_000_000)), cfg, lat);
    Console.WriteLine($"fee={cfg.FeeBps}bps latency={lat} events");
    Console.WriteLine(r);
    Console.WriteLine(r.Compute.Summary("decision latency"));
}

static void Sweep(Args a)
{
    long n = a.Lng("events", 500_000);
    Console.WriteLine("SYNTHETIC data with injected edge - shows sensitivity, not real profitability.");
    Console.WriteLine("fee_bps latency  fills     pnl");
    foreach (double fee in new[] { 0.0, 0.5, 1.0, 2.0 })
        foreach (int lat in new[] { 1, 2, 5, 10, 20 })
        {
            var cfg = new EngineConfig { FeeBps = fee, UseNeural = a.Has("neural") };
            var r = Backtester.Run(new SyntheticMarket(n), cfg, lat);
            Console.WriteLine($"{fee,7:F1} {lat,7} {r.Fills,7} {r.Pnl,10:F2}");
        }
}

static void NeuralDemo(Args a)
{
    string sub = a.Pos(0) ?? "fit";
    if (sub == "trade") NeuralTrade(a); else NeuralFit(a);
}

static void NeuralFit(Args a)
{
    // The "world": a formula the network is never shown, only samples of it.
    static double Truth(double[] x) => 2 * Math.Sin(3 * x[0]) * x[1] + x[2] * x[2] - 0.5 * x[0] * x[2];
    var rng = new Rng(7);
    int n = 20000, nTest = 4000;
    var X = new double[n + nTest][]; var Y = new double[n + nTest];
    for (int i = 0; i < X.Length; i++)
    {
        X[i] = new[] { rng.NextDouble() * 2 - 1, rng.NextDouble() * 2 - 1, rng.NextDouble() * 2 - 1 };
        Y[i] = Truth(X[i]) + 0.01 * rng.NextGaussian();
    }
    double varY = Y.Skip(n).Select(v => v * v).Average();
    Console.WriteLine("Hidden law: y = 2*sin(3*x1)*x2 + x3^2 - 0.5*x1*x3 (+ noise). The network sees only (x1,x2,x3) -> y samples.");

    var net = Mlp.Build(3, new[] { 64, 64 }, 1, Act.Gelu, maxBatch: 64, seed: 3, lr: 3e-3f);
    Console.WriteLine($"Network 3 -> 64 -> 64 -> 1, GELU, Adam, {net.ParameterCount} parameters.");
    var bx = new float[64 * 3]; var by = new float[64];
    var sw = System.Diagnostics.Stopwatch.StartNew();
    int epochs = (int)a.Lng("epochs", 40), steps = n / 64;
    for (int ep = 1; ep <= epochs; ep++)
    {
        if (ep == epochs * 2 / 3) net.Opt.Lr = 5e-4f;
        float loss = 0;
        for (int s = 0; s < steps; s++)
        {
            for (int b = 0; b < 64; b++)
            {
                int idx = rng.NextInt(n);
                for (int k = 0; k < 3; k++) bx[b * 3 + k] = (float)X[idx][k];
                by[b] = (float)Y[idx];
            }
            loss = net.TrainStep(bx, by, 64);
        }
        if (ep % 10 == 0 || ep == 1)
        {
            double se = 0; var xt = new float[3];
            for (int i = n; i < X.Length; i++)
            {
                for (int k = 0; k < 3; k++) xt[k] = (float)X[i][k];
                double e = net.Forward(xt)[0] - Y[i]; se += e * e;
            }
            Console.WriteLine($"  epoch {ep,3}: train loss {loss:F5}   test R2 = {1 - se / (X.Length - n) / varY:F4}");
        }
    }
    Console.WriteLine($"trained in {sw.Elapsed.TotalSeconds:F1} s");

    // 1) which inputs matter: |dy/dx_i| via backpropagation to the input
    var imp = new double[3]; var xs = new float[3];
    for (int i = n; i < X.Length; i++)
    {
        for (int k = 0; k < 3; k++) xs[k] = (float)X[i][k];
        var g = net.InputGradient(xs);
        for (int k = 0; k < 3; k++) imp[k] += Math.Abs(g[k]) / nTest;
    }
    Console.WriteLine($"mean |dy/dx| learned by the network: x1={imp[0]:F2} x2={imp[1]:F2} x3={imp[2]:F2}");

    // 2) turn the network into a formula: sample the network itself, then sparse-regress over a library of terms
    var Xf = new double[6000][]; var Yf = new double[6000]; var xf = new float[3];
    for (int i = 0; i < Xf.Length; i++)
    {
        Xf[i] = new[] { rng.NextDouble() * 2 - 1, rng.NextDouble() * 2 - 1, rng.NextDouble() * 2 - 1 };
        for (int k = 0; k < 3; k++) xf[k] = (float)Xf[i][k];
        Yf[i] = net.Forward(xf)[0];
    }
    var f = FormulaDiscovery.Fit(FormulaDiscovery.Library(new[] { "x1", "x2", "x3" }), Xf, Yf, threshold: 0.08);
    Console.WriteLine($"formula extracted from the network ({f.Terms.Length} terms, R2 vs network {f.R2:F4}):");
    Console.WriteLine($"  y ≈ {f}");
    double se2 = 0;
    for (int i = n; i < X.Length; i++) { double e = f.Eval(X[i]) - Y[i]; se2 += e * e; }
    Console.WriteLine($"extracted formula on unseen data: R2 vs truth = {1 - se2 / (X.Length - n) / varY:F4}");
}

static void NeuralTrade(Args a)
{
    long n = a.Lng("events", 400_000);
    foreach (bool regime in new[] { false, true })
    {
        Console.WriteLine($"\n=== synthetic market, {(regime ? "REGIME-DEPENDENT edge (sign flips with spread regime)" : "linear edge")} ===");
        foreach (bool neural in new[] { false, true })
        {
            var cfg = new EngineConfig { FeeBps = a.Dbl("fee", 0.3), UseNeural = neural };
            var r = Backtester.Run(new SyntheticMarket(n, 21) { Regime = regime, RegimeStrength = a.Dbl("strength", 3.0) }, cfg, 1);
            Console.WriteLine($"-- {(neural ? "linear + NEURAL hypotheses" : "linear hypotheses only")}");
            Console.WriteLine(r.Engine!.Ensemble.Report());
            Console.WriteLine($"  PnL={r.Pnl:F2} fills={r.Fills} fees={r.Fees:F2}{(r.Killed ? " KILLED" : "")}   " + r.Compute.Summary("decision latency"));
        }
    }
    Console.WriteLine("\n=== isolated test: y = 3*a*sign(b) + noise (an interaction; the best linear fit explains nothing) ===");
    {
        var lin = new GLF.Trading.Models.RlsModel(3, 0.9999);
        var nn = new GLF.Trading.Models.NeuralModel(2, new[] { 32, 16 }, 2e-3f);
        var rng = new Rng(5); var x = new double[3]; var x2 = new double[2];
        double seL = 0, seN = 0, seB = 0; int cnt = 0;
        for (int i = 0; i < 100_000; i++)
        {
            double aa = rng.NextDouble() * 2 - 1, bb = rng.NextDouble() * 2 - 1;
            double y = 3 * aa * Math.Sign(bb) + 0.5 * rng.NextGaussian();
            x[0] = 1; x[1] = aa; x[2] = bb; x2[0] = aa; x2[1] = bb;
            if (i >= 50_000) { double e1 = lin.Predict(x) - y, e2 = nn.Predict(x2) - y; seL += e1 * e1; seN += e2 * e2; seB += y * y; cnt++; }
            lin.Learn(x, y); nn.Learn(x2, y);
        }
        Console.WriteLine($"  predict-nothing RMSE {Math.Sqrt(seB / cnt):F3}   linear {Math.Sqrt(seL / cnt):F3}   neural {Math.Sqrt(seN / cnt):F3}   (noise floor 0.500)");
    }
    Console.WriteLine("\nSynthetic data: the edge is injected by construction; this shows the learning machinery, not real profitability.");
}

static void GptDemo(Args a)
{
    var rng = new Rng(11);
    string[] subj = { "Агент", "Робот", "Трейдер", "Система" };
    var sb = new System.Text.StringBuilder();
    for (int i = 0; i < 700; i++)
    {
        string S = subj[rng.NextInt(4)];
        if (rng.NextInt(2) == 0)
            sb.Append($"{S} ищет ключ. {S} находит ключ и открывает дверь. {S} выходит из комнаты.\n");
        else if (rng.NextInt(2) == 0)
            sb.Append($"{S} читает стакан. Спрос больше предложения, и {S} покупает. Цена растёт.\n");
        else
            sb.Append($"{S} читает стакан. Спрос меньше предложения, и {S} продаёт. Цена падает.\n");
    }
    string corpus = sb.ToString();

    var tk = BpeTokenizer.Train(corpus, a.Has("vocab") ? (int)a.Lng("vocab", 400) : 400);
    var ids = tk.Encode(corpus);
    Console.WriteLine($"[I] BPE: {System.Text.Encoding.UTF8.GetByteCount(corpus)} bytes -> {ids.Length} tokens (x{System.Text.Encoding.UTF8.GetByteCount(corpus) / (double)ids.Length:F1} shorter), vocab {tk.VocabSize}");
    Console.WriteLine("    sample tokens: " + string.Join(" | ", Enumerable.Range(256, 12).Select(i => tk.TokenText(i).Replace("\n", "⏎"))));

    int D = (int)a.Lng("dim", 64), L = (int)a.Lng("layers", 2), T = 96;
    var cfg = new TransformerConfig(tk.VocabSize, D, L, Heads: 4, KvHeads: 2, FfnDim: D * 2, MaxSeq: T);
    var model = new TransformerModel(cfg, 5);
    Console.WriteLine($"[II-IV] decoder: {L} layers, d_model {D}, 4 query heads / 2 KV heads (GQA), SwiGLU ffn {cfg.FfnDim}, RoPE, RMSNorm, tied LM head -> {model.ParameterCount:N0} parameters");

    int split = ids.Length * 9 / 10;
    var opt = new Adam(3e-3f, weightDecay: 0.01f, clipNorm: 1f);
    int steps = (int)a.Lng("steps", 500), batchSize = 8;
    var trng = new Rng(3);
    var sw = System.Diagnostics.Stopwatch.StartNew();
    (int[] Tok, int[] Tgt) Window(int lo, int hi)
    {
        int st = lo + trng.NextInt(hi - lo - T - 1);
        return (ids.AsSpan(st, T).ToArray(), ids.AsSpan(st + 1, T).ToArray());
    }
    for (int step = 1; step <= steps; step++)
    {
        opt.Lr = 3e-3f * (step < 30 ? step / 30f : 0.1f + 0.9f * 0.5f * (1 + MathF.Cos(MathF.PI * (step - 30) / (steps - 30))));
        var batch = new List<(int[], int[])>();
        for (int b = 0; b < batchSize; b++) batch.Add(Window(0, split));
        float loss = model.TrainBatch(batch, opt);
        if (step == 1 || step % 100 == 0)
        {
            var (vt, vg) = Window(split, ids.Length);
            Console.WriteLine($"    step {step,4}: train loss {loss:F3}  val loss {model.Evaluate(vt, vg):F3}  (random guess = {Math.Log(tk.VocabSize):F2})  {sw.Elapsed.TotalSeconds:F0}s");
        }
    }

    var dec = new KvDecoder(model);
    string Gen(string prompt, int n, float temp, int k, float p, ulong seed)
    {
        var r = new Rng(seed);
        var pr = tk.Encode(prompt);
        var o = dec.Generate(pr, n, temp, k, p, ref r);
        return prompt + tk.Decode(o.ToArray());
    }
    Console.WriteLine("\n[V] sampling from the same prompt: 'Трейдер читает стакан. Спрос больше предложения, и'");
    foreach (var (name, temp, k, p) in new[] { ("greedy (T=0)", 0f, 0, 1f), ("T=0.8 top-k 20 top-p 0.9", 0.8f, 20, 0.9f), ("T=2.0 no filtering", 2f, 0, 1f) })
        Console.WriteLine($"  {name,-26} -> {Gen("Трейдер читает стакан. Спрос больше предложения, и", 28, temp, k, p, 9).Replace("\n", "⏎")}");

    // does attention carry information across the sentence? subject must be repeated, condition must match the action.
    int ok = 0, n = 200;
    var er = new Rng(77);
    for (int i = 0; i < n; i++)
    {
        string S = subj[er.NextInt(4)]; bool more = er.NextInt(2) == 0;
        string prompt = $"{S} читает стакан. Спрос {(more ? "больше" : "меньше")} предложения, и";
        string g = Gen(prompt, 40, 0f, 0, 1f, 1);
        string line = g.Split('\n')[0];
        string want = $"{prompt} {S} {(more ? "покупает. Цена растёт." : "продаёт. Цена падает.")}";
        if (line == want) ok++;
    }
    Console.WriteLine($"\nlong-range consistency (subject copied, action matches the condition, price follows): {ok}/{n} exact");

    // KV cache vs recomputing the prefix
    var prompt0 = tk.Encode("Агент ищет ключ.");
    int total = 60;
    var rr = new Rng(1);
    var tok = new List<int>(prompt0);
    var sw2 = System.Diagnostics.Stopwatch.StartNew();
    while (tok.Count < total)
    {
        model.Forward(tok.ToArray(), tok.Count);
        int V = cfg.Vocab;
        tok.Add(Sampler.Sample(model.Logits.Slice((tok.Count - 1) * V, V), 0f, 0, 1f, ref rr));
    }
    double naive = sw2.Elapsed.TotalMilliseconds;
    sw2.Restart();
    var rr2 = new Rng(1);
    var cached = dec.Generate(prompt0, total - prompt0.Length, 0f, 0, 1f, ref rr2);
    double fast = sw2.Elapsed.TotalMilliseconds;
    bool same = cached.SequenceEqual(tok.Skip(prompt0.Length));
    Console.WriteLine($"[III] generating up to {total} tokens: recompute whole prefix each step {naive:F1} ms | KV cache {fast:F1} ms (x{naive / fast:F1}), identical output: {same}");
    dec.Reset(); dec.Step(1); long m1 = dec.LastStepAttentionMacs; for (int i = 0; i < 49; i++) dec.Step(2);
    Console.WriteLine($"    attention work per new token: position 1 = {m1:N0} MACs, position 50 = {dec.LastStepAttentionMacs:N0} MACs (linear in context length)");
}


static ToyGpt TrainToyGpt(int steps, bool log)
{
    var rng = new Rng(11);
    string[] subj = { "Агент", "Робот", "Трейдер", "Система" };
    var sb = new System.Text.StringBuilder();
    for (int i = 0; i < 700; i++)
    {
        string S = subj[rng.NextInt(4)];
        if (rng.NextInt(2) == 0) sb.Append($"{S} ищет ключ. {S} находит ключ и открывает дверь. {S} выходит из комнаты.\n");
        else if (rng.NextInt(2) == 0) sb.Append($"{S} читает стакан. Спрос больше предложения, и {S} покупает. Цена растёт.\n");
        else sb.Append($"{S} читает стакан. Спрос меньше предложения, и {S} продаёт. Цена падает.\n");
    }
    var tk = BpeTokenizer.Train(sb.ToString(), 400);
    var ids = tk.Encode(sb.ToString());
    const int T = 96;
    var model = new TransformerModel(new TransformerConfig(tk.VocabSize, 64, 2, 4, 2, 128, T), 5);
    int split = ids.Length * 9 / 10;
    var opt = new Adam(3e-3f, weightDecay: 0.01f, clipNorm: 1f);
    var trng = new Rng(3);
    for (int step = 1; step <= steps; step++)
    {
        opt.Lr = 3e-3f * (step < 30 ? step / 30f : 0.1f + 0.9f * 0.5f * (1 + MathF.Cos(MathF.PI * (step - 30) / Math.Max(1, steps - 30))));
        var batch = new List<(int[], int[])>();
        for (int b = 0; b < 8; b++) { int st = trng.NextInt(split - T - 1); batch.Add((ids.AsSpan(st, T).ToArray(), ids.AsSpan(st + 1, T).ToArray())); }
        float loss = model.TrainBatch(batch, opt);
        if (log && (step == 1 || step % 100 == 0)) Console.WriteLine($"  training step {step}: loss {loss:F3}");
    }
    return new ToyGpt(model, tk, ids, split, T);
}

static double Perplexity(TransformerModel m, ToyGpt g)
{
    double total = 0; int n = 0;
    for (int st = g.Split; st + g.T + 1 < g.Ids.Length; st += g.T / 2)
    {
        total += m.Evaluate(g.Ids.AsSpan(st, g.T).ToArray(), g.Ids.AsSpan(st + 1, g.T).ToArray()); n++;
    }
    return Math.Exp(total / n);
}

static void QuantDemo(Args a)
{
    Console.WriteLine("training a small transformer to quantise...");
    var g = TrainToyGpt((int)a.Lng("steps", 300), false);
    var m = g.Model;
    var rngW = new Rng(2);
    var windows = Enumerable.Range(0, 24).Select(_ => { int st = rngW.NextInt(g.Split - g.T - 1); return g.Ids.AsSpan(st, g.T).ToArray(); }).ToList();
    var cal = Quantizer.Calibrate(m, windows);
    long lin = Quantizer.LinearParameters(m);

    var rows = new List<(string, double, string)>();
    double fp = Perplexity(m, g);
    rows.Add(("FP32 baseline", fp, $"{lin * 4 / 1024.0:F0} KB"));

    TransformerModel Q(Action<TransformerModel> f) { var c = m.Clone(); f(c); return c; }
    var w8 = Q(c => { Quantizer.Rtn(c, 8, 0); c.ActBits = 8; });
    rows.Add(("W8A8 naive (per-channel W, per-token A)", Perplexity(w8, g), $"{lin / 1024.0:F0} KB"));
    var w8s = Q(c => { Quantizer.SmoothQuant(c, cal, 0.5); Quantizer.Rtn(c, 8, 0); c.ActBits = 8; });
    rows.Add(("W8A8 SmoothQuant a=0.5", Perplexity(w8s, g), $"{lin / 1024.0:F0} KB"));
    var w4 = Q(c => Quantizer.Rtn(c, 4, 0));
    rows.Add(("W4 round-to-nearest, per-channel", Perplexity(w4, g), $"{lin / 2048.0:F0} KB"));
    var w4g = Q(c => Quantizer.Rtn(c, 4, 32));
    rows.Add(("W4 round-to-nearest, group 32", Perplexity(w4g, g), $"{lin * (0.5 + 2.0 / 32) / 1024.0:F0} KB"));
    (double, double)[] gam = Array.Empty<(double, double)>();
    var awq = Q(c => gam = Quantizer.Awq(c, cal, 4, 0));
    rows.Add(("W4 AWQ-style, per-channel", Perplexity(awq, g), $"{lin / 2048.0:F0} KB"));
    var awqg = Q(c => Quantizer.Awq(c, cal, 4, 32));
    rows.Add(("W4 AWQ-style, group 32", Perplexity(awqg, g), $"{lin * (0.5 + 2.0 / 32) / 1024.0:F0} KB"));

    foreach (int bits in new[] { 3, 2 })
    {
        var rb = Q(c => Quantizer.Rtn(c, bits, 32));
        rows.Add(($"W{bits} round-to-nearest, group 32", Perplexity(rb, g), $"{lin * (bits / 8.0 + 2.0 / 32) / 1024.0:F0} KB"));
        var ab = Q(c => Quantizer.Awq(c, cal, bits, 32));
        rows.Add(($"W{bits} AWQ-style, group 32", Perplexity(ab, g), $"{lin * (bits / 8.0 + 2.0 / 32) / 1024.0:F0} KB"));
    }
    Console.WriteLine($"\n{"variant",-42} {"perplexity",11} {"linear weights",15}");
    foreach (var (name, ppl, size) in rows) Console.WriteLine($"{name,-42} {ppl,11:F3} {size,15}");
    Console.WriteLine($"AWQ gamma per layer (qkv-input, ffn-input), per-channel run: {string.Join("  ", gam.Select(x => $"({x.Item1:F1},{x.Item2:F1})"))}");

    // SmoothQuant is an exact re-parameterisation in floating point
    var sm = m.Clone(); Quantizer.SmoothQuant(sm, cal, 0.5);
    var toks = g.Ids.AsSpan(g.Split, 40).ToArray();
    m.Forward(toks, 40); var l0 = m.Logits.ToArray(); sm.Forward(toks, 40); var l1 = sm.Logits;
    double md = 0; for (int i = 0; i < l0.Length; i++) md = Math.Max(md, Math.Abs(l0[i] - l1[i]));
    Console.WriteLine($"\nSmoothQuant before quantising: max |logit difference| = {md:E1} (float round-off only)");

    // controlled outlier experiment: one activation channel 60x larger than the rest
    var r = new Rng(9); int D = 64, N = 256;
    var W = new float[D * D]; for (int i = 0; i < W.Length; i++) W[i] = r.NextGaussian() * 0.1f;
    var X = new float[N * D]; for (int i = 0; i < X.Length; i++) X[i] = r.NextGaussian();
    for (int t = 0; t < N; t++) X[t * D + 3] *= 60f;
    float[] Mat(float[] w, float[] x) { var y = new float[N * D]; for (int t = 0; t < N; t++) for (int o = 0; o < D; o++) { float s = 0; for (int j = 0; j < D; j++) s += w[o * D + j] * x[t * D + j]; y[t * D + o] = s; } return y; }
    double Rel(float[] yq, float[] yr) { double e = 0, n = 0; for (int i = 0; i < yr.Length; i++) { e += (yq[i] - yr[i]) * (yq[i] - yr[i]); n += yr[i] * yr[i]; } return Math.Sqrt(e / n); }
    var yref = Mat(W, X);
    var w1 = (float[])W.Clone(); var x1 = (float[])X.Clone(); Quant.FakeQuantWeights(w1, D, D, 8, 0); Quant.FakeQuantRows(x1, N, D, 8);
    double eNaive = Rel(Mat(w1, x1), yref);
    var amax = new float[D]; for (int t = 0; t < N; t++) for (int j = 0; j < D; j++) amax[j] = MathF.Max(amax[j], MathF.Abs(X[t * D + j]));
    var sc = Quantizer.SmoothScales(amax, new List<(float[], int)> { (W, D) }, D, 0.5);
    var w2 = (float[])W.Clone(); var x2 = (float[])X.Clone();
    for (int o = 0; o < D; o++) for (int j = 0; j < D; j++) w2[o * D + j] *= sc[j];
    for (int t = 0; t < N; t++) for (int j = 0; j < D; j++) x2[t * D + j] /= sc[j];
    Quant.FakeQuantWeights(w2, D, D, 8, 0); Quant.FakeQuantRows(x2, N, D, 8);
    double eSmooth = Rel(Mat(w2, x2), yref);
    var il = new Int8Linear(W, D, D); var yi = new float[D]; var yf = new float[D];
    il.Forward(X.AsSpan(5 * D, D), yi);
    Console.WriteLine($"outlier channel x60: relative output error  W8A8 naive {eNaive:P2}  ->  SmoothQuant {eSmooth:P2}");
    Console.WriteLine("(our toy transformer has no such outlier channels, so on it INT8 is already near-lossless; the effect shows up in large models.)");
}

static void ScaleDemo(Args a)
{
    var cfg = new TransformerConfig(50, 64, 3, Heads: 8, KvHeads: 2, FfnDim: 128, MaxSeq: 32);
    var m = new TransformerModel(cfg, 4);
    var rng = new Rng(8); var tok = Enumerable.Range(0, 24).Select(_ => rng.NextInt(50)).ToArray();
    m.Forward(tok, tok.Length); var single = m.Logits.ToArray();
    Console.WriteLine($"[tensor parallelism] {cfg.Layers} layers, {cfg.Heads} query heads, {cfg.KvHeads} KV heads, ffn {cfg.FfnDim}");
    Console.WriteLine($"  {"P",2} {"max|logit diff|",16} {"All-Reduces",12} {"floats/All-Reduce",18} {"KV floats/shard",16}  note");
    foreach (int P in new[] { 1, 2, 4, 8 })
    {
        var tp = TensorParallel.Forward(m, tok, P, out var st);
        double md = 0; for (int i = 0; i < single.Length; i++) md = Math.Max(md, Math.Abs(single[i] - tp[i]));
        string note = P <= cfg.KvHeads ? "KV cache split" : "KV heads replicated (P > KV heads)";
        Console.WriteLine($"  {P,2} {md,16:E1} {st.AllReduces,12} {st.AllReduceFloats / st.AllReduces,18} {st.KvFloatsPerShard,16}  {note}");
    }
    Console.WriteLine($"  single-device KV floats per layer: {2 * cfg.KvDim * tok.Length}; exactly 2 All-Reduces per layer (after Wo and after Wdown).");

    Console.WriteLine("\n[pipeline parallelism] 4 stages, 8 micro-batches, forward = backward = 1 time unit");
    var gp = Pipeline.Simulate("GPipe", 4, 8, false);
    var f1 = Pipeline.Simulate("1F1B", 4, 8, true);
    Console.WriteLine($"  theory bubble (P-1)/(M+P-1) = {Pipeline.TheoreticalBubble(4, 8):P1}");
    foreach (var r in new[] { gp, f1 })
        Console.WriteLine($"  {r.Name,-6} makespan {r.Makespan,4:F0}  bubble {r.BubbleFraction:P1}  peak activations held per stage: [{string.Join(", ", r.PeakInFlight)}] micro-batches");
    Console.WriteLine("  1F1B timeline (Fk = forward of micro-batch k, Bk = backward):");
    Console.Write(f1.Render());
    var big = Pipeline.Simulate("1F1B", 4, 64, true);
    Console.WriteLine($"  with 64 micro-batches: bubble {big.BubbleFraction:P1}, peak activations per stage [{string.Join(", ", big.PeakInFlight)}] (unchanged)  | GPipe would hold 64");

    Console.WriteLine("\n[ZeRO] per-GPU training state for a 70B-parameter model, mixed-precision Adam (16 bytes/parameter), data-parallel degree 64");
    double phi = 70e9;
    foreach (var (name, st2) in new[] { ("plain data parallel", 0), ("ZeRO-1 optimizer states", 1), ("ZeRO-2 + gradients", 2), ("ZeRO-3 + parameters", 3) })
        Console.WriteLine($"  {name,-26} {ZeroMemory.PerGpu(st2, phi, 64) / 1e9,9:F1} GB");
    Console.WriteLine("  3D layout check: N_total = TP x PP x DP, e.g. 8 x 8 x 16 = " + 8 * 8 * 16 + " GPUs");
}

static void ContinualDemo(Args a)
{
    var rng = new Rng(4);
    (float[] X, int[] Y) Make(int n, bool left)
    {
        var x = new float[n * 2]; var y = new int[n];
        for (int i = 0; i < n; i++)
        {
            float x1 = (float)rng.NextDouble(), x2 = (float)(rng.NextDouble() * 2 - 1);
            if (left) x1 = -x1;
            x[i * 2] = x1; x[i * 2 + 1] = x2;
            y[i] = left ? (x2 > 0 ? 1 : 0) : (x2 < 0 ? 1 : 0); // the two regions need OPPOSITE rules
        }
        return (x, y);
    }
    var (xa, ya) = Make(3000, true); var (xb, yb) = Make(3000, false);
    var (xat, yat) = Make(1000, true); var (xbt, ybt) = Make(1000, false);

    double Acc(Network net, float[] x, int[] y)
    {
        int ok = 0, n = y.Length;
        for (int i = 0; i < n; i++) { var o = net.Forward(x.AsSpan(i * 2, 2)); if ((o[1] > o[0] ? 1 : 0) == y[i]) ok++; }
        return (double)ok / n;
    }
    var trng = new Rng(9);
    void Train(Network net, float[] x, int[] y, int steps, float[]? mx = null, int[]? my = null, int mem = 0)
    {
        var bx = new float[64 * 2]; var by = new int[64];
        for (int s = 0; s < steps; s++)
        {
            int cur = mem > 0 ? 64 - 16 : 64;
            for (int b = 0; b < 64; b++)
            {
                bool fromMem = b >= cur;
                int i = fromMem ? trng.NextInt(mem) : trng.NextInt(y.Length);
                var sx = fromMem ? mx! : x; var sy = fromMem ? my! : y;
                bx[b * 2] = sx[i * 2]; bx[b * 2 + 1] = sx[i * 2 + 1]; by[b] = sy[i];
            }
            net.TrainStepClassify(bx, by, 64);
        }
    }
    Network Fresh() => Mlp.Build(2, new[] { 32, 32 }, 2, Act.Gelu, maxBatch: 64, seed: 3, lr: 0.01f);

    Console.WriteLine("Task A: points with x1<0, class = (x2>0).  Task B: points with x1>0, class = (x2<0).  Opposite rules, one network, no task label.");
    Console.WriteLine($"{"strategy",-34} {"A after A",10} {"A after B",10} {"B after B",10}");
    void Row(string name, Network net, Action trainB)
    {
        double a1 = Acc(net, xat, yat);
        trainB();
        Console.WriteLine($"{name,-34} {a1,10:P1} {Acc(net, xat, yat),10:P1} {Acc(net, xbt, ybt),10:P1}");
    }
    var n1 = Fresh(); Train(n1, xa, ya, 400);
    Row("naive sequential", n1, () => Train(n1, xb, yb, 400));

    var n2 = Fresh(); Train(n2, xa, ya, 400);
    int mem = 200; var mx = xa.AsSpan(0, mem * 2).ToArray(); var my = ya.AsSpan(0, mem).ToArray();
    Row("replay (200 stored A samples, 25%)", n2, () => Train(n2, xb, yb, 400, mx, my, mem));

    var n3 = Fresh(); Train(n3, xa, ya, 400);
    var ewc = new Ewc(float.Parse(a.Str("lambda") ?? "5000", System.Globalization.CultureInfo.InvariantCulture)); ewc.Consolidate(n3, xa, ya, 1000);
    Row($"EWC (lambda {ewc.Lambda})", n3, () => Train(n3, xb, yb, 400));

    var n4 = Fresh();
    var xj = xa.Concat(xb).ToArray(); var yj = ya.Concat(yb).ToArray();
    Train(n4, xj, yj, 800);
    Console.WriteLine($"{"joint training (upper bound)",-34} {"-",10} {Acc(n4, xat, yat),10:P1} {Acc(n4, xbt, ybt),10:P1}");
}

static void PrintChunks(List<ChunkReport> chunks, HypothesisEnsemble ens, long early)
{
    string[] cols = { "rls-all/0.99", "nn-32x16", "nn-32x16+regime-replay" };
    Console.WriteLine($"RMSE of the {ens.Horizon}-event price change, in ticks. 'early' = first {early} events of each chunk (re-adaptation speed), 'late' = the rest.");
    Console.Write($"{"chunk",5} {"regime",6} {"known",5} |");
    Console.Write($" {"naive",6} {"naive",6} |");
    foreach (var c in cols) Console.Write($" {Short(c) + " early",-12} {"late",6} |");
    Console.WriteLine();
    foreach (var ch in chunks)
    {
        Console.Write($"{ch.Index,5} {ch.Regime,6} {ch.RegimesKnown,5} |");
        Console.Write($" {ch.Early.NaiveRmse,6:F2} {ch.Late.NaiveRmse,6:F2} |");
        foreach (var c in cols)
        {
            int i = Array.IndexOf(ch.Early.Names, c);
            Console.Write($" {(i < 0 ? double.NaN : ch.Early.Rmse(i)),12:F2} {(i < 0 ? double.NaN : ch.Late.Rmse(i)),6:F2} |");
        }
        Console.WriteLine();
    }
    static string Short(string n) => n.Replace("nn-32x16+regime-replay", "nn+replay").Replace("nn-32x16", "nn-plain").Replace("rls-all/0.99", "linear");
    Console.WriteLine($"regime detector: {ens.RegimeCount} regimes found, {ens.RegimeSwitches} label switches");
}

static void RegimeTest(Args a)
{
    long block = a.Lng("block", 8000); int blocks = (int)a.Lng("blocks", 8); long early = a.Lng("early", 500);
    double strength = a.Dbl("strength", 8);
    Console.WriteLine($"Synthetic market, {blocks} blocks of {block} events; the pressure->price relation flips sign every block (narrow-spread regime vs wide-spread regime).");
    Console.WriteLine("Plain network: sees only the last 1024 events, so it forgets the other regime. Regime-replay network: also rehearses a fixed-size memory of every regime seen.");
    var cfg = new EngineConfig();
    var (chunks, ens) = StreamEvaluator.Run(new SyntheticMarket(block * blocks, 21) { Regime = true, RegimeStrength = strength, BlockLength = (int)block, Noise = a.Dbl("noise", 0.3) }, cfg, block, early);
    PrintChunks(chunks, ens, early);
    Console.WriteLine("\nEnd of run, whole-stream RMSE:");
    Console.WriteLine(ens.Report());
}

static void Evaluate(Args a)
{
    string? f = a.Str("file");
    if (f == null) { Console.WriteLine("usage: evaluate --file recorded.jsonl [--chunk 20000] [--tick 0.01] [--lot 0.001]"); return; }
    long chunk = a.Lng("chunk", 20000), early = a.Lng("early", 2000);
    var cfg = Cfg(a, 0.01, 0.001, 4.0);
    using var rp = new JsonLinesReplay(f);
    var (chunks, ens) = StreamEvaluator.Run(rp, cfg, chunk, early);
    if (chunks.Count == 0) { Console.WriteLine($"fewer than {chunk} usable events in the file (skipped lines: {rp.Skipped}); record longer or lower --chunk."); return; }
    PrintChunks(chunks, ens, early);
    Console.WriteLine("\nWhole-file RMSE (prequential: each sample is predicted before it is learned):");
    Console.WriteLine(ens.Report());
    var s = ens.Snapshot();
    int plain = Array.IndexOf(s.Names, "nn-32x16"), rep = Array.IndexOf(s.Names, "nn-32x16+regime-replay");
    Console.WriteLine($"\nregime replay vs plain network: {s.Rmse(rep):F3} vs {s.Rmse(plain):F3} ticks ({(1 - s.Rmse(rep) / s.Rmse(plain)):P1} {(s.Rmse(rep) < s.Rmse(plain) ? "better" : "worse")}); naive baseline {s.NaiveRmse:F3}");
}

static void MakeTestData(Args a)
{
    string path = a.Str("out") ?? "synthetic.jsonl";
    long n = a.Lng("events", 200_000);
    var src = new SyntheticMarket(n, 21) { Regime = true, RegimeStrength = 8, BlockLength = 20_000, Noise = 0.3 };
    var snap = new BookSnapshot();
    var inv = System.Globalization.CultureInfo.InvariantCulture;
    using var w = new StreamWriter(path);
    string F(long v, int d) => (v / (double)FixedDecimal.Scale).ToString("F" + d, inv);
    long i = 0;
    while (src.Next(snap))
    {
        var sb = new System.Text.StringBuilder();
        sb.Append(snap.TsNs).Append('\t').Append("{\"lastUpdateId\":").Append(i++).Append(",\"bids\":[");
        for (int k = 0; k < snap.BidCount; k++) sb.Append(k > 0 ? "," : "").Append("[\"").Append(F(snap.BidPx[k], 2)).Append("\",\"").Append(F(snap.BidQty[k], 8)).Append("\"]");
        sb.Append("],\"asks\":[");
        for (int k = 0; k < snap.AskCount; k++) sb.Append(k > 0 ? "," : "").Append("[\"").Append(F(snap.AskPx[k], 2)).Append("\",\"").Append(F(snap.AskQty[k], 8)).Append("\"]");
        sb.Append("]}");
        w.WriteLine(sb.ToString());
    }
    Console.WriteLine($"wrote {i} synthetic snapshots to {path} (tick 0.01, regimes alternate every 20000 events)");
}

static void RunVision(Args a)
{
    int eps = (int)a.Lng("episodes", 6);
    var env = new PixelRoom(noise: (int)a.Lng("noise", 0), shuffleActions: a.Has("shuffle"), paletteSeed: (int)a.Lng("palette", 0));
    var agent = new VisualAgent(env.ActionCount);
    string[] dir = { "up", "right", "down", "left" };

    var first = env.Reset();
    var an = new SceneAnalyzer();
    var scene = new Scene();
    an.Analyze(first, scene);
    Console.WriteLine($"Screen {first.Width}x{first.Height} px = {first.Width * first.Height * 3} bytes. What the vision layer sees on frame 0:");
    Console.WriteLine("  class color(rgb)        blobs  total_px");
    foreach (var g in scene.Blobs.GroupBy(b => b.Cls).OrderBy(g => g.Key))
    {
        var c = an.Colors.Center(g.Key);
        Console.WriteLine($"  {g.Key,5}  ({c.R,3},{c.G,3},{c.B,3})   {g.Count(),8}  {g.Sum(b => b.Area),8}");
    }

    var log = PixelTrainer.Run(env, agent, eps);
    Console.WriteLine();
    for (int i = 0; i < log.Count; i++)
        Console.WriteLine($"episode {i + 1}: {(log[i].Solved ? "ESCAPED" : "failed ")} in {log[i].Steps,5} steps  ({log[i].Ms:F1} ms)");

    var d = agent.Discovery;
    Console.WriteLine();
    if (d.Ready)
    {
        var ac = agent.Analyzer.Colors.Center(d.AvatarClass);
        var tc = env.AvatarColor;
        Console.WriteLine($"Discovered avatar: class {d.AvatarClass} rgb({ac.R},{ac.G},{ac.B})  [truth rgb({tc.R},{tc.G},{tc.B})]  after {agent.BabbleSteps} babbling steps");
        var (sx, sy) = d.StepSize();
        Console.WriteLine($"Grid step inferred: {sx:F1} x {sy:F1} px");
        for (int act = 0; act < 4; act++)
        {
            var (tx, ty) = env.TrueMove(act);
            string learned = d.TryEffect(act, out var dx, out var dy) ? $"({dx:+0.#;-0.#;0},{dy:+0.#;-0.#;0}) px" : "never observed";
            Console.WriteLine($"  action {act}: learned {learned,-18} truth: ({tx},{ty}) tiles");
        }
    }
    else Console.WriteLine("avatar not identified");
    Console.WriteLine(agent.VisionTime.Summary("vision per frame"));
}

static void RunAgent(Args a)
{
    int eps = (int)a.Lng("episodes", 6);
    var env = new EscapeRoom();
    var agent = new ModelBasedAgent(env.ActionCount);
    Console.WriteLine("Locked room: the agent knows nothing about walls, key, door or exit.");
    var total = System.Diagnostics.Stopwatch.StartNew();
    var log = Trainer.Run(env, agent, eps);
    for (int i = 0; i < log.Count; i++)
        Console.WriteLine($"episode {i + 1}: {(log[i].Solved ? "ESCAPED" : "failed ")} in {log[i].Steps,5} steps  ({log[i].Ms:F1} ms)");
    Console.WriteLine($"total learning time {total.Elapsed.TotalMilliseconds:F0} ms; states known {agent.StatesKnown}, untried actions {agent.UntriedActions}");
}

static async Task Live(Args a)
{
    string sym = a.Str("symbol") ?? "btcusdt";
    int secs = (int)a.Lng("seconds", 60);
    bool paper = a.Has("paper");
    var cfg = Cfg(a, 0.01, 0.001, 4.0);
    using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(secs));
    Stream? rec = a.Str("record") is { } rp ? new BufferedStream(File.Create(rp), 1 << 20) : null;

    var pool = new BookSnapshot[2048];
    for (int i = 0; i < pool.Length; i++) pool[i] = new BookSnapshot();
    var ring = new SpscRing<int>(1024);
    int slot = 0;
    long recv = 0, parseFail = 0, dropped = 0, processed = 0;
    var compute = new LatencyHistogram();
    var wire = new LatencyHistogram();
    var engine = new TradingEngine(cfg);
    var ex = new PaperExchange(cfg);
    double lastMid = 0;

    var consumer = new Thread(() =>
    {
        HotThread.Prepare(1);
        long idx = 0;
        while (!cts.IsCancellationRequested || processed < recv - dropped - parseFail)
        {
            if (!ring.TryDequeue(out int s)) { Thread.SpinWait(30); continue; }
            var snap = pool[s];
            ex.OnSnapshot(snap, idx, engine);
            long t0 = Clock.Now();
            bool send = engine.Process(snap, Clock.NowNs(), out var order);
            long t1 = Clock.Now();
            compute.Record(Clock.ToNs(t1 - t0));
            wire.Record(Clock.ToNs(t1) - snap.TsNs);
            if (send && paper) ex.Submit(order, idx);
            else if (send) engine.OnReject();
            if (engine.Book.IsValid) lastMid = engine.Book.Mid / FixedDecimal.Scale;
            idx++; processed++;
        }
    }) { IsBackground = true };
    consumer.Start();

    var producer = BinanceDepthFeed.RunAsync(sym, 20, frame =>
    {
        long ts = Clock.NowNs();
        recv++;
        if (rec != null)
        {
            var hdr = Encoding.ASCII.GetBytes((DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() * 1_000_000).ToString() + "\t");
            rec.Write(hdr); rec.Write(frame); rec.WriteByte((byte)'\n');
        }
        var sn = pool[slot];
        if (!BinanceDepthParser.TryParse(frame, sn)) { parseFail++; return; }
        sn.TsNs = ts;
        if (ring.TryEnqueue(slot)) slot = (slot + 1) % pool.Length; else dropped++;
    }, cts.Token);

    var report = Task.Run(async () =>
    {
        while (!cts.IsCancellationRequested)
        {
            await Task.Delay(5000).ConfigureAwait(false);
            Console.WriteLine($"[{sym}] recv={recv} proc={processed} drop={dropped} bad={parseFail} mid={lastMid:F2} pos={engine.PositionLots} " +
                $"paperPnl={(paper ? ex.Equity(lastMid) : 0):F4} fills={ex.Fills}");
        }
    });

    try { await producer; }
    catch (OperationCanceledException) { }
    catch (Exception e) { Console.WriteLine($"feed error: {e.GetType().Name}: {e.Message}"); cts.Cancel(); }
    cts.Cancel();
    consumer.Join(3000);
    rec?.Dispose();
    Console.WriteLine(compute.Summary("compute (decision)"));
    Console.WriteLine(wire.Summary("socket-receive -> decision"));
    Console.WriteLine($"frames={recv} bad={parseFail} dropped={dropped} paperFills={ex.Fills} killed={engine.Risk.Killed}");
}

sealed class Args
{
    readonly Dictionary<string, string> _kv = new();
    readonly List<string> _pos = new();
    public string Command { get; }

    public Args(string[] a)
    {
        Command = a.Length > 0 ? a[0] : "";
        for (int i = 1; i < a.Length; i++)
        {
            if (!a[i].StartsWith("--")) { _pos.Add(a[i]); continue; }
            string k = a[i][2..];
            _kv[k] = i + 1 < a.Length && !a[i + 1].StartsWith("--") ? a[++i] : "true";
        }
    }

    public string? Pos(int i) => _pos.Count > i ? _pos[i] : null;
    public bool Has(string k) => _kv.ContainsKey(k);
    public string? Str(string k) => _kv.GetValueOrDefault(k);
    public long Lng(string k, long d) => _kv.TryGetValue(k, out var v) ? long.Parse(v) : d;
    public double Dbl(string k, double d) => _kv.TryGetValue(k, out var v) ? double.Parse(v, System.Globalization.CultureInfo.InvariantCulture) : d;
}

record ToyGpt(TransformerModel Model, BpeTokenizer Tok, int[] Ids, int Split, int T);
