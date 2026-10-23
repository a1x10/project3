using GLF.Market;

namespace GLF.Trading.Sim;

/// <summary>
/// Synthetic limit-order-book generator for pipeline tests and benchmarks. A latent persistent "pressure"
/// both skews displayed depth and drives the future drift of the price, so imbalance carries information BY CONSTRUCTION.
/// Results on this data say nothing about real markets.
/// </summary>
public sealed class SyntheticMarket : ISnapshotSource
{
    const double TickSize = 0.01;
    ulong _s;
    double _fair = 1000.00 / TickSize, _pressure;
    long _i;
    readonly long _max;
    public double Kappa = 1.2;

    public SyntheticMarket(long events, ulong seed = 42) { _max = events; _s = seed * 0x9E3779B97F4A7C15UL + 1; }

    double U() { _s ^= _s << 13; _s ^= _s >> 7; _s ^= _s << 17; return (_s >> 11) * (1.0 / (1UL << 53)); }
    double N() { double u = Math.Max(U(), 1e-12), v = U(); return Math.Sqrt(-2 * Math.Log(u)) * Math.Cos(2 * Math.PI * v); }

    public bool Next(BookSnapshot s)
    {
        if (_i >= _max) return false;
        _pressure = 0.97 * _pressure + 0.25 * N();
        _fair += Kappa * _pressure + 0.8 * N();

        long bidTick = (long)Math.Floor(_fair);
        int spread = U() < 0.7 ? 1 : 2;
        double imb = Math.Tanh(_pressure + 0.4 * N());
        const long TickScaled = 1_000_000; // 0.01 in 1e-8

        s.BidCount = s.AskCount = 20;
        for (int l = 0; l < 20; l++)
        {
            double depth = 20.0 / (1 + 0.15 * l);
            s.BidPx[l] = (bidTick - l) * TickScaled;
            s.AskPx[l] = (bidTick + spread + l) * TickScaled;
            s.BidQty[l] = (long)(depth * Math.Exp(+1.2 * imb) * (0.8 + 0.4 * U()) * FixedDecimal.Scale);
            s.AskQty[l] = (long)(depth * Math.Exp(-1.2 * imb) * (0.8 + 0.4 * U()) * FixedDecimal.Scale);
        }
        s.TsNs = _i * 100_000_000L;
        _i++;
        return true;
    }
}
