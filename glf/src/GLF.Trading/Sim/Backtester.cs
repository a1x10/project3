using GLF.Core;
using GLF.Market;

namespace GLF.Trading.Sim;

public sealed class BacktestResult
{
    public long Events;
    public double Pnl, Fees, MaxDrawdown;
    public long Fills, Rejects, RiskRejects;
    public bool Killed;
    public string KillReason = "";
    public readonly LatencyHistogram Compute = new();

    public override string ToString() =>
        $"events={Events} fills={Fills} rejects={Rejects} riskRejects={RiskRejects} pnl={Pnl:F2} fees={Fees:F2} maxDD={MaxDrawdown:F2}"
        + (Killed ? $" KILLED({KillReason})" : "");
}

public static class Backtester
{
    public static BacktestResult Run(ISnapshotSource src, EngineConfig cfg, int latencyEvents = 1)
    {
        var engine = new TradingEngine(cfg);
        var ex = new PaperExchange(cfg) { LatencyEvents = latencyEvents };
        var res = new BacktestResult();
        var snap = new BookSnapshot();
        double peak = 0;
        long i = 0;

        while (src.Next(snap))
        {
            ex.OnSnapshot(snap, i, engine);

            long t0 = Clock.Now();
            bool send = engine.Process(snap, snap.TsNs, out var order);
            res.Compute.Record(Clock.ToNs(Clock.Now() - t0));
            if (send) ex.Submit(order, i);

            double mid = engine.Book.IsValid ? engine.Book.Mid / FixedDecimal.Scale : 0;
            if (mid > 0)
            {
                double eq = ex.Equity(mid);
                engine.Risk.UpdateEquity(eq);
                if (eq > peak) peak = eq;
                if (peak - eq > res.MaxDrawdown) res.MaxDrawdown = peak - eq;
                res.Pnl = eq;
            }
            i++;
        }
        res.Events = i; res.Fees = ex.FeesPaid; res.Fills = ex.Fills; res.Rejects = ex.Rejects;
        res.RiskRejects = engine.Risk.Rejected; res.Killed = engine.Risk.Killed; res.KillReason = engine.Risk.KillReason;
        return res;
    }
}
