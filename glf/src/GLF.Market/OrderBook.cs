namespace GLF.Market;

/// <summary>Sorted price ladder in flat arrays. Keys ascend; best level is index 0 (bids store -price).</summary>
public sealed class Ladder
{
    public readonly long[] Key;
    public readonly long[] Qty;
    public int Count;

    public Ladder(int capacity) { Key = new long[capacity]; Qty = new long[capacity]; }

    public void Clear() => Count = 0;

    int LowerBound(long key)
    {
        int lo = 0, hi = Count;
        while (lo < hi)
        {
            int mid = (lo + hi) >> 1;
            if (Key[mid] < key) lo = mid + 1; else hi = mid;
        }
        return lo;
    }

    /// <summary>qty &lt;= 0 removes the level.</summary>
    public void Set(long key, long qty)
    {
        int i = LowerBound(key);
        if (i < Count && Key[i] == key)
        {
            if (qty > 0) { Qty[i] = qty; return; }
            int tail = Count - i - 1;
            if (tail > 0) { Array.Copy(Key, i + 1, Key, i, tail); Array.Copy(Qty, i + 1, Qty, i, tail); }
            Count--;
            return;
        }
        if (qty <= 0 || i >= Key.Length) return;
        int move = Count - i;
        if (Count == Key.Length) move--; // worst level falls off
        if (move > 0) { Array.Copy(Key, i, Key, i + 1, move); Array.Copy(Qty, i, Qty, i + 1, move); }
        Key[i] = key; Qty[i] = qty;
        if (Count < Key.Length) Count++;
    }
}

public sealed class OrderBook
{
    public readonly Ladder Bids = new(256);
    public readonly Ladder Asks = new(256);

    public bool IsValid => Bids.Count > 0 && Asks.Count > 0 && BestBid < BestAsk;
    public long BestBid => -Bids.Key[0];
    public long BestAsk => Asks.Key[0];
    public long BestBidQty => Bids.Qty[0];
    public long BestAskQty => Asks.Qty[0];
    public double Mid => (BestBid + BestAsk) * 0.5;

    public void SetBid(long px, long qty) => Bids.Set(-px, qty);
    public void SetAsk(long px, long qty) => Asks.Set(px, qty);

    public void Load(BookSnapshot s)
    {
        Bids.Clear(); Asks.Clear();
        for (int i = 0; i < s.BidCount; i++) Bids.Set(-s.BidPx[i], s.BidQty[i]);
        for (int i = 0; i < s.AskCount; i++) Asks.Set(s.AskPx[i], s.AskQty[i]);
    }

    public static double Depth(Ladder l, int levels)
    {
        int n = Math.Min(levels, l.Count);
        double sum = 0;
        for (int i = 0; i < n; i++) sum += l.Qty[i];
        return sum;
    }

    public double Microprice
    {
        get
        {
            double b = BestBidQty, a = BestAskQty;
            return (BestBid * a + BestAsk * b) / (a + b);
        }
    }
}
