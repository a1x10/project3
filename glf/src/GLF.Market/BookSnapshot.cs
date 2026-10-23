namespace GLF.Market;

/// <summary>Preallocated top-N book snapshot (best level first). Prices/quantities are 1e-8 fixed point.</summary>
public sealed class BookSnapshot
{
    public const int MaxLevels = 32;
    public readonly long[] BidPx = new long[MaxLevels], BidQty = new long[MaxLevels];
    public readonly long[] AskPx = new long[MaxLevels], AskQty = new long[MaxLevels];
    public int BidCount, AskCount;
    public long TsNs;

    public void Clear() { BidCount = AskCount = 0; }
}
