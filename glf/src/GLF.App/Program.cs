using System.Text;
using GLF.Agent;
using GLF.Agent.Vision;
using GLF.Core;
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
    case "live": await Live(a); break;
    default:
        Console.WriteLine("""
        GLF - low-latency trading core + model-based agent

          bench     [--events N]                       hot-path latency + allocation check on synthetic data
          backtest  [--events N] [--fee bps] [--latency events] [--file f.jsonl --tick 0.01 --lot 0.001]
          sweep     [--events N]                       PnL vs fee and latency (synthetic)
          agent     [--episodes N]                     model-based agent escapes a locked room it knows nothing about
          vision    [--episodes N] [--noise 12] [--shuffle] [--palette 3]   agent learns the room from raw pixels
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
    Console.WriteLine(hist.Summary("snapshot->book->features->6 hypotheses->decision->risk"));
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
            var cfg = new EngineConfig { FeeBps = fee };
            var r = Backtester.Run(new SyntheticMarket(n), cfg, lat);
            Console.WriteLine($"{fee,7:F1} {lat,7} {r.Fills,7} {r.Pnl,10:F2}");
        }
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
    public string Command { get; }

    public Args(string[] a)
    {
        Command = a.Length > 0 ? a[0] : "";
        for (int i = 1; i < a.Length; i++)
        {
            if (!a[i].StartsWith("--")) continue;
            string k = a[i][2..];
            _kv[k] = i + 1 < a.Length && !a[i + 1].StartsWith("--") ? a[++i] : "true";
        }
    }

    public bool Has(string k) => _kv.ContainsKey(k);
    public string? Str(string k) => _kv.GetValueOrDefault(k);
    public long Lng(string k, long d) => _kv.TryGetValue(k, out var v) ? long.Parse(v) : d;
    public double Dbl(string k, double d) => _kv.TryGetValue(k, out var v) ? double.Parse(v, System.Globalization.CultureInfo.InvariantCulture) : d;
}
