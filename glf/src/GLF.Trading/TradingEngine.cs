using GLF.Core;
using GLF.Market;
using GLF.Trading.Models;
using GLF.Trading.Risk;

namespace GLF.Trading;

public sealed class EngineConfig
{
    public double TickSize = 0.01;
    public double LotQty = 1.0;          // base-asset units per lot
    public int Horizon = 10;             // events
    public double FeeBps = 1.0;          // taker fee per side
    public double Margin = 1.0;          // required edge in units of hypothesis disagreement
    public double ExitFrac = 0.25;       // exit when forecast falls below this fraction of round-trip cost
    public int MaxHoldEvents = 40;
    public double SlippageTicks = 2;     // IOC limit tolerance beyond the touch
    public bool UseNeural = true;        // add online neural hypotheses to the ensemble
    public RiskLimits Risk = new();

    public long TickScaled => (long)Math.Round(TickSize * FixedDecimal.Scale);
    public long LotScaled => (long)Math.Round(LotQty * FixedDecimal.Scale);
}

/// <summary>
/// The hot path: snapshot -> book -> features -> hypothesis ensemble -> decision -> risk gate -> order.
/// After construction it performs no heap allocation.
/// </summary>
public sealed class TradingEngine
{
    readonly EngineConfig _c;
    readonly FeatureExtractor _fx;
    readonly double[] _x = new double[FeatureExtractor.Dim];
    bool _inFlight;
    int _held;

    public readonly OrderBook Book = new();
    public readonly HypothesisEnsemble Ensemble;
    public readonly RiskGate Risk;
    public int PositionLots { get; private set; }
    public Forecast LastForecast { get; private set; }

    public TradingEngine(EngineConfig c)
    {
        _c = c;
        _fx = new FeatureExtractor(c.TickScaled);
        Ensemble = new HypothesisEnsemble(c.Horizon, c.UseNeural);
        Risk = new RiskGate(c.Risk);
    }

    public bool Process(BookSnapshot s, long nowNs, out OrderIntent order)
    {
        order = default;
        Book.Load(s);
        if (!Book.IsValid) return false;

        double tick = _c.TickScaled;
        double mid = Book.Mid;
        _fx.Compute(Book, _x);
        var f = Ensemble.Step(_x, mid / tick);
        LastForecast = f;
        Risk.OnMarketData(s.TsNs);
        if (PositionLots != 0) _held++;
        if (!f.Ready || _inFlight) return false;

        double spreadTicks = (Book.BestAsk - Book.BestBid) / tick;
        double feeTicks = _c.FeeBps * 1e-4 * mid / tick;
        double cost = spreadTicks + 2 * feeTicks;
        int target = Decide(f, cost);
        if (target == PositionLots) return false;

        int delta = target - PositionLots;
        int side = Math.Sign(delta);
        long slip = (long)(_c.SlippageTicks * tick);
        order = new OrderIntent
        {
            Side = side,
            Qty = Math.Abs(delta) * _c.LotScaled,
            LimitPx = side > 0 ? Book.BestAsk + slip : Book.BestBid - slip,
            TsNs = nowNs,
        };
        if (!Risk.Approve(order, mid, PositionLots, delta, nowNs)) return false;
        _inFlight = true;
        return true;
    }

    int Decide(in Forecast f, double cost)
    {
        double enter = cost + _c.Margin * f.Disagreement;
        double exit = _c.ExitFrac * cost;
        if (PositionLots == 0)
            return f.Mean > enter ? 1 : f.Mean < -enter ? -1 : 0;
        bool stop = _held > _c.MaxHoldEvents;
        if (PositionLots > 0) return stop || f.Mean < exit ? 0 : 1;
        return stop || f.Mean > -exit ? 0 : -1;
    }

    public void OnFill(int side, int lots)
    {
        PositionLots += side * lots;
        if (PositionLots == 0) _held = 0;
        _inFlight = false;
    }

    public void OnReject() => _inFlight = false;
}
