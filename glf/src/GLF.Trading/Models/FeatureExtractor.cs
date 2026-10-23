using GLF.Market;

namespace GLF.Trading.Models;

/// <summary>Microstructure features from the book. x[0] is a bias term.</summary>
public sealed class FeatureExtractor
{
    public const int Dim = 7;
    readonly double _tick;
    bool _has;
    long _pb, _pa, _pbq, _paq;
    double _prevMid, _ofi, _ret;

    /// <param name="tickScaled">tick size in 1e-8 fixed point</param>
    public FeatureExtractor(double tickScaled) => _tick = tickScaled;

    public void Compute(OrderBook b, Span<double> x)
    {
        long bid = b.BestBid, ask = b.BestAsk, bq = b.BestBidQty, aq = b.BestAskQty;
        double mid = b.Mid;

        double e = 0, r = 0;
        if (_has)
        {
            if (bid >= _pb) e += bq;
            if (bid <= _pb) e -= _pbq;
            if (ask <= _pa) e -= aq;
            if (ask >= _pa) e += _paq;
            double norm = (double)bq + aq + _pbq + _paq;
            e = norm > 0 ? 2 * e / norm : 0;
            r = (mid - _prevMid) / _tick;
        }
        _ofi = 0.8 * _ofi + e;
        _ret = 0.7 * _ret + r;
        _has = true; _pb = bid; _pa = ask; _pbq = bq; _paq = aq; _prevMid = mid;

        double sum1 = (double)bq + aq;
        double d5b = OrderBook.Depth(b.Bids, 5), d5a = OrderBook.Depth(b.Asks, 5);
        x[0] = 1.0;
        x[1] = (bq - aq) / sum1;
        x[2] = (d5b - d5a) / (d5b + d5a);
        x[3] = (b.Microprice - mid) / _tick;
        x[4] = _ofi;
        x[5] = _ret;
        x[6] = (ask - bid) / _tick;
    }
}
