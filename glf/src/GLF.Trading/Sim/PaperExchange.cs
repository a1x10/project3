using GLF.Market;
using GLF.Trading.Risk;

namespace GLF.Trading.Sim;

/// <summary>
/// Simulated venue: an order submitted at event i is matched against the book at event i+LatencyEvents
/// (IOC, taker at the touch, whole lot only). Nothing here ever talks to a real exchange.
/// </summary>
public sealed class PaperExchange
{
    readonly EngineConfig _c;
    OrderIntent _order;
    bool _pending;
    long _due;

    public int LatencyEvents = 1;
    public double Cash, PositionUnits, FeesPaid;
    public long Fills, Rejects;

    public PaperExchange(EngineConfig c) => _c = c;

    public void Submit(in OrderIntent o, long eventIndex)
    {
        _order = o; _pending = true; _due = eventIndex + Math.Max(1, LatencyEvents);
    }

    public void OnSnapshot(BookSnapshot s, long eventIndex, TradingEngine engine)
    {
        if (!_pending || eventIndex < _due) return;
        _pending = false;
        long px; long avail;
        if (_order.Side > 0) { px = s.AskPx[0]; avail = s.AskQty[0]; if (_order.LimitPx < px) { Reject(engine); return; } }
        else { px = s.BidPx[0]; avail = s.BidQty[0]; if (_order.LimitPx > px) { Reject(engine); return; } }
        if (avail < _order.Qty) { Reject(engine); return; }

        double qty = (double)_order.Qty / FixedDecimal.Scale, price = (double)px / FixedDecimal.Scale;
        double notional = qty * price, fee = notional * _c.FeeBps * 1e-4;
        Cash -= _order.Side * notional + fee;
        PositionUnits += _order.Side * qty;
        FeesPaid += fee;
        Fills++;
        engine.OnFill(_order.Side, (int)(_order.Qty / _c.LotScaled));
    }

    void Reject(TradingEngine e) { Rejects++; e.OnReject(); }

    public double Equity(double midPrice) => Cash + PositionUnits * midPrice;
}
