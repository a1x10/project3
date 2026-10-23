using System.Text.Json;

namespace GLF.Market;

/// <summary>
/// Allocation-free parser for Binance partial-depth payloads
/// ({"bids":[["px","qty"],...],"asks":[...]} also inside a combined-stream "data" wrapper).
/// </summary>
public static class BinanceDepthParser
{
    public static bool TryParse(ReadOnlySpan<byte> json, BookSnapshot snap)
    {
        snap.Clear();
        var r = new Utf8JsonReader(json);
        try
        {
            while (r.Read())
            {
                if (r.TokenType != JsonTokenType.PropertyName) continue;
                bool bids = r.ValueTextEquals("bids"u8);
                if (!bids && !r.ValueTextEquals("asks"u8)) continue;
                if (!r.Read() || r.TokenType != JsonTokenType.StartArray) return false;

                int n = 0;
                while (r.Read() && r.TokenType == JsonTokenType.StartArray)
                {
                    if (!r.Read() || r.TokenType != JsonTokenType.String || !FixedDecimal.TryParse(r.ValueSpan, out long px)) return false;
                    if (!r.Read() || r.TokenType != JsonTokenType.String || !FixedDecimal.TryParse(r.ValueSpan, out long qty)) return false;
                    if (!r.Read() || r.TokenType != JsonTokenType.EndArray) return false;
                    if (n < BookSnapshot.MaxLevels)
                    {
                        if (bids) { snap.BidPx[n] = px; snap.BidQty[n] = qty; }
                        else { snap.AskPx[n] = px; snap.AskQty[n] = qty; }
                        n++;
                    }
                }
                if (bids) snap.BidCount = n; else snap.AskCount = n;
            }
        }
        catch (JsonException) { return false; }
        return snap.BidCount > 0 && snap.AskCount > 0;
    }
}
