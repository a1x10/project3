using GLF.Market;
using GLF.Trading.Models;

namespace GLF.Trading.Sim;

public sealed record ChunkReport(int Index, int Regime, int RegimesKnown, AccuracySnapshot Early, AccuracySnapshot Late);

/// <summary>
/// Streams snapshots (synthetic or a recorded file) through the forecasting ensemble only - no trading - and reports prequential accuracy
/// per chunk of events: the error in the first <c>earlyWindow</c> events of the chunk (how fast the models re-adapt after a change)
/// and in the rest.
/// </summary>
public static class StreamEvaluator
{
    public static (List<ChunkReport> Chunks, HypothesisEnsemble Ensemble) Run(ISnapshotSource src, EngineConfig cfg, long chunk, long earlyWindow)
    {
        var book = new OrderBook();
        var snap = new BookSnapshot();
        var fx = new FeatureExtractor(cfg.TickScaled);
        var ens = new HypothesisEnsemble(cfg.Horizon, cfg.UseNeural, cfg.RegimeReplay);
        var x = new double[FeatureExtractor.Dim];
        var chunks = new List<ChunkReport>();
        AccuracySnapshot start = ens.Snapshot(), mid = start;
        long i = 0; int idx = 0; bool midTaken = false;
        double tick = cfg.TickScaled;
        while (src.Next(snap))
        {
            book.Load(snap);
            if (book.IsValid)
            {
                fx.Compute(book, x);
                ens.Step(x, book.Mid / tick);
            }
            i++;
            long pos = i % chunk;
            if (!midTaken && pos == earlyWindow) { mid = ens.Snapshot(); midTaken = true; }
            if (pos == 0)
            {
                var end = ens.Snapshot();
                chunks.Add(new ChunkReport(idx++, ens.CurrentRegime, ens.RegimeCount, mid - start, end - mid));
                start = end; midTaken = false;
            }
        }
        return (chunks, ens);
    }
}
