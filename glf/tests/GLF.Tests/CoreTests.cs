using System.Text;
using GLF.Agent;
using GLF.Core;
using GLF.Market;
using GLF.Trading;
using GLF.Trading.Models;
using GLF.Trading.Risk;
using GLF.Trading.Sim;

namespace GLF.Tests;

public class CoreTests
{
    [Theory]
    [InlineData("60000.12", 6000012000000L)]
    [InlineData("0.00000001", 1L)]
    [InlineData("1", 100000000L)]
    [InlineData("12.5", 1250000000L)]
    public void FixedDecimal_parses(string s, long expected)
    {
        Assert.True(FixedDecimal.TryParse(Encoding.ASCII.GetBytes(s), out long v));
        Assert.Equal(expected, v);
    }

    [Fact]
    public void FixedDecimal_rejects_garbage() =>
        Assert.False(FixedDecimal.TryParse("1x.5"u8, out _));

    [Fact]
    public void Ladder_keeps_order_updates_and_removes()
    {
        var b = new OrderBook();
        b.SetBid(100, 5); b.SetBid(102, 3); b.SetBid(101, 4);
        b.SetAsk(105, 1); b.SetAsk(103, 2);
        Assert.Equal(102, b.BestBid);
        Assert.Equal(103, b.BestAsk);
        b.SetBid(102, 0);
        Assert.Equal(101, b.BestBid);
        b.SetAsk(103, 9);
        Assert.Equal(9, b.BestAskQty);
        Assert.True(b.IsValid);
    }

    [Fact]
    public void Parser_reads_combined_stream_frame()
    {
        var json = """{"stream":"btcusdt@depth5@100ms","data":{"lastUpdateId":1,"bids":[["60000.10","1.5"],["60000.00","2"]],"asks":[["60000.20","0.5"]]}}"""u8;
        var s = new BookSnapshot();
        Assert.True(BinanceDepthParser.TryParse(json, s));
        Assert.Equal(2, s.BidCount); Assert.Equal(1, s.AskCount);
        Assert.Equal(6000010000000L, s.BidPx[0]);
        Assert.Equal(50000000L, s.AskQty[0]);
        Assert.False(BinanceDepthParser.TryParse("{\"bids\":[[\"x\"]]}"u8, s));
    }

    [Fact]
    public void Rls_learns_linear_relation()
    {
        var m = new Rls(3, 0.999);
        var rng = new Random(1);
        Span<double> x = stackalloc double[3];
        for (int i = 0; i < 2000; i++)
        {
            x[0] = 1; x[1] = rng.NextDouble() - .5; x[2] = rng.NextDouble() - .5;
            m.Update(x, 2 + 3 * x[1] - 4 * x[2]);
        }
        Assert.InRange(m.Weights[0], 1.99, 2.01);
        Assert.InRange(m.Weights[1], 2.99, 3.01);
        Assert.InRange(m.Weights[2], -4.01, -3.99);
    }

    [Fact]
    public void Histogram_percentiles_are_ordered()
    {
        var h = new LatencyHistogram();
        for (int i = 1; i <= 1000; i++) h.Record(i * 100);
        Assert.True(h.PercentileNs(.5) <= h.PercentileNs(.99));
        Assert.InRange(h.PercentileNs(.5), 40_000, 55_000);
    }

    [Fact]
    public void Ring_is_fifo_and_bounded()
    {
        var r = new SpscRing<int>(4);
        for (int i = 0; i < 4; i++) Assert.True(r.TryEnqueue(i));
        Assert.False(r.TryEnqueue(9));
        for (int i = 0; i < 4; i++) { Assert.True(r.TryDequeue(out int v)); Assert.Equal(i, v); }
        Assert.False(r.TryDequeue(out _));
    }

    [Fact]
    public void Risk_blocks_oversize_stale_fatfinger_and_kills_on_drawdown()
    {
        var g = new RiskGate(new RiskLimits { MaxPositionLots = 1, MaxDrawdownQuote = 10 });
        g.OnMarketData(1_000);
        var o = new OrderIntent { Side = 1, Qty = 1, LimitPx = 1000 };
        Assert.True(g.Approve(o, 1000, 0, 1, 2_000));
        Assert.False(g.Approve(o, 1000, 1, 1, 3_000));                  // position limit
        Assert.False(g.Approve(o with { LimitPx = 2000 }, 1000, 0, 1, 4_000)); // fat finger
        Assert.False(g.Approve(o, 1000, 0, 1, 10_000_000_000));         // stale data
        g.UpdateEquity(100); g.UpdateEquity(80);
        Assert.True(g.Killed);
    }

    [Fact]
    public void Engine_hot_path_does_not_allocate()
    {
        var e = new TradingEngine(new EngineConfig());
        var s = new BookSnapshot();
        var src = new SyntheticMarket(60_000);
        for (int i = 0; i < 40_000; i++) { src.Next(s); e.Process(s, s.TsNs, out _); }
        long a0 = GC.GetAllocatedBytesForCurrentThread();
        while (src.Next(s)) e.Process(s, s.TsNs, out _);
        Assert.Equal(0, GC.GetAllocatedBytesForCurrentThread() - a0);
    }

    [Fact]
    public void Backtest_is_deterministic()
    {
        var a = Backtester.Run(new SyntheticMarket(50_000), new EngineConfig { FeeBps = 0 });
        var b = Backtester.Run(new SyntheticMarket(50_000), new EngineConfig { FeeBps = 0 });
        Assert.Equal(a.Pnl, b.Pnl);
        Assert.Equal(a.Fills, b.Fills);
    }

    [Fact]
    public void Agent_escapes_locked_room_and_then_takes_shortest_route()
    {
        var env = new EscapeRoom();
        var agent = new ModelBasedAgent(env.ActionCount);
        var log = Trainer.Run(env, agent, 5);
        Assert.All(log, l => Assert.True(l.Solved));
        Assert.True(log[1].Steps < log[0].Steps);
        Assert.Equal(log[1].Steps, log[4].Steps);
        Assert.True(log[4].Steps <= 70);
    }
}
