using System.Net.WebSockets;
using System.Text;

namespace GLF.Market;

public interface ISnapshotSource
{
    /// <summary>Fills <paramref name="snap"/> with the next event; false at end of stream.</summary>
    bool Next(BookSnapshot snap);
}

/// <summary>Replays frames recorded by <see cref="BinanceDepthFeed"/> ("ts_ns\tjson" per line).</summary>
public sealed class JsonLinesReplay : ISnapshotSource, IDisposable
{
    readonly StreamReader _r;
    byte[] _buf = new byte[1 << 16];
    public long Skipped;

    public JsonLinesReplay(string path) => _r = new StreamReader(path);

    public bool Next(BookSnapshot snap)
    {
        string? line;
        while ((line = _r.ReadLine()) != null)
        {
            int tab = line.IndexOf('\t');
            if (tab <= 0 || !long.TryParse(line.AsSpan(0, tab), out long ts)) { Skipped++; continue; }
            int max = Encoding.UTF8.GetMaxByteCount(line.Length - tab - 1);
            if (_buf.Length < max) _buf = new byte[max];
            int n = Encoding.UTF8.GetBytes(line.AsSpan(tab + 1), _buf);
            if (BinanceDepthParser.TryParse(_buf.AsSpan(0, n), snap)) { snap.TsNs = ts; return true; }
            Skipped++;
        }
        return false;
    }

    public void Dispose() => _r.Dispose();
}

/// <summary>Public market-data only (no keys, no orders): Binance partial book depth over WebSocket.</summary>
public static class BinanceDepthFeed
{
    public delegate void FrameHandler(ReadOnlySpan<byte> frame);

    public static async Task RunAsync(string symbol, int levels, FrameHandler onFrame, CancellationToken ct)
    {
        var uri = new Uri($"wss://stream.binance.com:9443/ws/{symbol.ToLowerInvariant()}@depth{levels}@100ms");
        using var ws = new ClientWebSocket();
        await ws.ConnectAsync(uri, ct).ConfigureAwait(false);
        var buf = new byte[1 << 16];
        while (!ct.IsCancellationRequested && ws.State == WebSocketState.Open)
        {
            int len = 0;
            WebSocketReceiveResult res;
            do
            {
                if (len == buf.Length) Array.Resize(ref buf, buf.Length * 2);
                res = await ws.ReceiveAsync(new ArraySegment<byte>(buf, len, buf.Length - len), ct).ConfigureAwait(false);
                if (res.MessageType == WebSocketMessageType.Close) return;
                len += res.Count;
            } while (!res.EndOfMessage);
            onFrame(buf.AsSpan(0, len));
        }
    }
}
