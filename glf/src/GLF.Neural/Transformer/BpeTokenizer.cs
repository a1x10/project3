using System.Text;

namespace GLF.Neural.Transformer;

/// <summary>
/// Byte-level BPE (раздел I): the base vocabulary is the 256 byte values (so any text, Cyrillic included, is representable);
/// training repeatedly merges the most frequent adjacent pair into a new token. Text is first cut into chunks
/// (a word with its leading space, a run of digits, a run of punctuation, a newline) and merges never cross chunk borders,
/// so a prompt that ends on a word boundary is tokenised exactly like the same text inside a longer document.
/// </summary>
public sealed class BpeTokenizer
{
    readonly Dictionary<(int, int), int> _mergeId = new();
    readonly List<byte[]> _bytes = new();
    readonly Dictionary<string, int[]> _cache = new();

    public int VocabSize => _bytes.Count;

    BpeTokenizer() { for (int i = 0; i < 256; i++) _bytes.Add(new[] { (byte)i }); }

    static int Category(char c) => char.IsLetter(c) ? 0 : char.IsDigit(c) ? 1 : char.IsWhiteSpace(c) ? 2 : 3;

    public static List<string> Pretokenize(string text)
    {
        var chunks = new List<string>();
        int i = 0, n = text.Length;
        while (i < n)
        {
            int start = i;
            if (text[i] == ' ' && i + 1 < n && Category(text[i + 1]) != 2) i++;
            int cat = Category(text[i]);
            i++;
            if (cat != 2) while (i < n && Category(text[i]) == cat) i++;
            chunks.Add(text.Substring(start, i - start));
        }
        return chunks;
    }

    public static BpeTokenizer Train(string text, int vocabSize)
    {
        var tk = new BpeTokenizer();
        var freq = new Dictionary<string, int>();
        foreach (var c in Pretokenize(text)) freq[c] = freq.GetValueOrDefault(c) + 1;
        var words = freq.Select(kv => (Seq: Encoding.UTF8.GetBytes(kv.Key).Select(b => (int)b).ToList(), Count: kv.Value)).ToList();

        while (tk.VocabSize < vocabSize)
        {
            var counts = new Dictionary<(int, int), int>();
            foreach (var (seq, cnt) in words)
                for (int i = 0; i + 1 < seq.Count; i++)
                {
                    var p = (seq[i], seq[i + 1]);
                    counts[p] = counts.GetValueOrDefault(p) + cnt;
                }
            if (counts.Count == 0) break;
            var best = counts.OrderByDescending(kv => kv.Value).ThenBy(kv => kv.Key.Item1).ThenBy(kv => kv.Key.Item2).First();
            if (best.Value < 2) break;
            int id = tk._bytes.Count;
            tk._mergeId[best.Key] = id;
            tk._bytes.Add(tk._bytes[best.Key.Item1].Concat(tk._bytes[best.Key.Item2]).ToArray());
            for (int w = 0; w < words.Count; w++) words[w] = (Merge(words[w].Seq, best.Key.Item1, best.Key.Item2, id), words[w].Count);
        }
        return tk;
    }

    static List<int> Merge(List<int> seq, int a, int b, int id)
    {
        var o = new List<int>(seq.Count);
        for (int i = 0; i < seq.Count; i++)
        {
            if (i + 1 < seq.Count && seq[i] == a && seq[i + 1] == b) { o.Add(id); i++; }
            else o.Add(seq[i]);
        }
        return o;
    }

    int[] EncodeChunk(string chunk)
    {
        if (_cache.TryGetValue(chunk, out var hit)) return hit;
        var seq = Encoding.UTF8.GetBytes(chunk).Select(b => (int)b).ToList();
        while (seq.Count > 1)
        {
            int bestId = int.MaxValue; (int, int) bestPair = default;
            for (int i = 0; i + 1 < seq.Count; i++)
                if (_mergeId.TryGetValue((seq[i], seq[i + 1]), out int id) && id < bestId) { bestId = id; bestPair = (seq[i], seq[i + 1]); }
            if (bestId == int.MaxValue) break;
            seq = Merge(seq, bestPair.Item1, bestPair.Item2, bestId);
        }
        return _cache[chunk] = seq.ToArray();
    }

    public int[] Encode(string text)
    {
        var o = new List<int>();
        foreach (var c in Pretokenize(text)) o.AddRange(EncodeChunk(c));
        return o.ToArray();
    }

    public string Decode(ReadOnlySpan<int> tokens)
    {
        var bytes = new List<byte>();
        foreach (int t in tokens) bytes.AddRange(_bytes[t]);
        return Encoding.UTF8.GetString(bytes.ToArray());
    }

    public string TokenText(int id) => Encoding.UTF8.GetString(_bytes[id]);
}
