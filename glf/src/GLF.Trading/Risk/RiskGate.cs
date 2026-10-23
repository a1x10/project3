namespace GLF.Trading.Risk;

public struct OrderIntent
{
    public int Side;      // +1 buy, -1 sell
    public long Qty;      // 1e-8 fixed point
    public long LimitPx;  // IOC limit, 1e-8 fixed point
    public long TsNs;
}

public sealed class RiskLimits
{
    public int MaxPositionLots = 1;
    public int MaxOrdersPerSecond = 20;
    public long MaxStaleNs = 2_000_000_000;
    public double MaxDeviationBps = 50;
    public double MaxDrawdownQuote = 1_000;
}

/// <summary>Pre-trade checks and kill switch. Every order passes through here, no exceptions.</summary>
public sealed class RiskGate
{
    readonly RiskLimits _l;
    readonly long[] _stamps;
    int _stampPos;
    long _lastDataNs;
    double _peak = double.MinValue;

    public bool Killed { get; private set; }
    public string KillReason { get; private set; } = "";
    public long Rejected { get; private set; }

    public RiskGate(RiskLimits limits)
    {
        _l = limits;
        _stamps = new long[Math.Max(1, limits.MaxOrdersPerSecond)];
    }

    public void OnMarketData(long tsNs) => _lastDataNs = tsNs;

    public void Kill(string reason) { Killed = true; KillReason = reason; }

    public void UpdateEquity(double equity)
    {
        if (equity > _peak) _peak = equity;
        if (_peak - equity > _l.MaxDrawdownQuote) Kill($"drawdown {_peak - equity:F2} > {_l.MaxDrawdownQuote:F2}");
    }

    public bool Approve(in OrderIntent o, double midScaled, int positionLots, int deltaLots, long nowNs)
    {
        long oldest = _stamps[_stampPos];
        bool ok = !Killed
            && nowNs - _lastDataNs <= _l.MaxStaleNs
            && Math.Abs(positionLots + deltaLots) <= _l.MaxPositionLots
            && Math.Abs(o.LimitPx - midScaled) / midScaled * 1e4 <= _l.MaxDeviationBps
            && (oldest == 0 || nowNs - oldest >= 1_000_000_000);
        if (!ok) { Rejected++; return false; }
        _stamps[_stampPos] = nowNs;
        _stampPos = (_stampPos + 1) % _stamps.Length;
        return true;
    }
}
