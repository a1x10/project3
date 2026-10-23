using System.Text;
using GLF.Agent;
using GLF.Agent.Vision;
using GLF.Core;
using GLF.Neural;
using GLF.Neural.Transformer;
using GLF.Market;
using GLF.Trading;
using GLF.Trading.Sim;

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
