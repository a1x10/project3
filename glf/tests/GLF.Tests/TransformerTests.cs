using GLF.Neural;
using GLF.Neural.Transformer;

namespace GLF.Tests;

public class TransformerTests
{
    static TransformerModel Tiny(ulong seed = 3) =>
        new(new TransformerConfig(Vocab: 11, DModel: 8, Layers: 2, Heads: 4, KvHeads: 2, FfnDim: 12, MaxSeq: 8), seed);

    [Fact]
    public void Gradients_of_the_whole_transformer_match_numerical()
    {
        var m = Tiny();
        // perturb the gains so their gradients are non-trivial too
        var r = new Rng(1);
        foreach (var p in m.Params) if (p.Name.StartsWith("l") && p.Name.Contains(".g") || p.Name == "gf") for (int i = 0; i < p.W.Length; i++) p.W[i] = 1f + 0.2f * r.NextGaussian();
        int[] tok = { 1, 4, 2, 4, 7, 0 }, tgt = { 4, 2, 4, 7, 0, 3 };
        int T = tok.Length;

        m.ZeroGrads();
        m.Forward(tok, T); m.Loss(tgt, T, 1f / T); m.Backward(tok, T);

        const float eps = 1e-2f;
        int checkedCount = 0;
        foreach (var p in m.Params)
        {
            int step = Math.Max(1, p.W.Length / 9);
            for (int i = 0; i < p.W.Length; i += step)
            {
                float w = p.W[i];
                p.W[i] = w + eps; float lp = m.Evaluate(tok, tgt);
                p.W[i] = w - eps; float lm = m.Evaluate(tok, tgt);
                p.W[i] = w;
                float num = (lp - lm) / (2 * eps), ana = p.G[i];
                Assert.True(Math.Abs(num - ana) < 2e-3f || Math.Abs(num - ana) / (Math.Abs(num) + Math.Abs(ana)) < 0.05f,
                    $"{p.Name}[{i}] numeric={num} analytic={ana}");
                checkedCount++;
            }
        }
        Assert.True(checkedCount > 100);
    }

    [Fact]
    public void KvCache_decoding_equals_full_forward_and_attention_cost_grows_linearly()
    {
        var m = Tiny(5);
        int[] tok = { 2, 9, 1, 1, 5, 7, 3 };
        m.Forward(tok, tok.Length);
        var full = m.Logits.ToArray();
        var dec = new KvDecoder(m);
        long first = 0, last = 0;
        for (int t = 0; t < tok.Length; t++)
        {
            var l = dec.Step(tok[t]);
            for (int v = 0; v < 11; v++) Assert.Equal(full[t * 11 + v], l[v], 3);
            if (t == 0) first = dec.LastStepAttentionMacs;
            last = dec.LastStepAttentionMacs;
        }
        Assert.Equal(first * tok.Length, last); // step at position N costs N times the first step
    }

    [Fact]
    public void Rope_makes_attention_scores_depend_only_on_relative_offset()
    {
        var m = new TransformerModel(new TransformerConfig(5, 16, 1, 1, 1, 8, 64));
        var rng = new Rng(4);
        var q0 = new float[16]; var k0 = new float[16];
        for (int i = 0; i < 16; i++) { q0[i] = rng.NextGaussian(); k0[i] = rng.NextGaussian(); }
        float Score(int mq, int nk)
        {
            var q = (float[])q0.Clone(); var k = (float[])k0.Clone();
            m.Rope(q, mq, 1, false); m.Rope(k, nk, 1, false);
            return VecOps.Dot(q, k);
        }
        Assert.Equal(Score(10, 7), Score(30, 27), 3);
        Assert.Equal(Score(3, 3), Score(40, 40), 3);
        Assert.NotEqual(Score(10, 7), Score(10, 6), 2);
        // rotation preserves norm (orthogonal)
        var x = (float[])q0.Clone(); m.Rope(x, 17, 1, false);
        Assert.Equal(VecOps.Dot(q0, q0), VecOps.Dot(x, x), 3);
    }

    [Fact]
    public void Causal_mask_future_tokens_do_not_change_earlier_logits()
    {
        var m = Tiny(7);
        int[] a = { 1, 2, 3, 4, 5, 6 }, b = { 1, 2, 3, 9, 9, 9 };
        m.Forward(a, 6); var la = m.Logits.ToArray();
        m.Forward(b, 6); var lb = m.Logits.ToArray();
        for (int i = 0; i < 3 * 11; i++) Assert.Equal(la[i], lb[i], 5);
        Assert.NotEqual(la[3 * 11], lb[3 * 11]);
    }

    [Fact]
    public void Transformer_overfits_a_tiny_sequence()
    {
        var m = new TransformerModel(new TransformerConfig(8, 16, 2, 2, 1, 32, 12), 2);
        var opt = new Adam(0.01f, clipNorm: 1f);
        int[] tok = { 1, 2, 3, 4, 5, 6, 7, 1, 2, 3 }, tgt = { 2, 3, 4, 5, 6, 7, 1, 2, 3, 4 };
        float loss = 0;
        for (int i = 0; i < 300; i++) loss = m.TrainBatch(new[] { (tok, tgt) }, opt);
        Assert.True(loss < 0.05f, $"loss {loss}");
    }

    [Fact]
    public void Bpe_roundtrips_text_including_cyrillic_and_compresses()
    {
        string text = string.Concat(Enumerable.Repeat("Агент ищет ключ. Агент открывает дверь. ", 30));
        var tk = BpeTokenizer.Train(text, 300);
        var ids = tk.Encode(text);
        Assert.Equal(text, tk.Decode(ids));
        Assert.True(ids.Length < System.Text.Encoding.UTF8.GetByteCount(text) / 3);
        string unseen = "ключ и дверь";
        Assert.Equal(unseen, tk.Decode(tk.Encode(unseen)));
        Assert.All(ids, i => Assert.InRange(i, 0, tk.VocabSize - 1));
    }

    [Fact]
    public void Sampler_greedy_topk_and_topp_behave()
    {
        float[] logits = { 5f, 4f, 3f, 0f, -2f };
        var rng = new Rng(1);
        Assert.Equal(0, Sampler.Sample(logits, 0f, 0, 1f, ref rng));
        for (int i = 0; i < 300; i++) Assert.InRange(Sampler.Sample(logits, 1f, 2, 1f, ref rng), 0, 1);       // top-k
        for (int i = 0; i < 300; i++) Assert.InRange(Sampler.Sample(logits, 1f, 0, 0.5f, ref rng), 0, 0);     // nucleus: first token alone has p>0.5
        var hi = new int[5]; var lo = new int[5];
        for (int i = 0; i < 2000; i++) { hi[Sampler.Sample(logits, 3f, 0, 1f, ref rng)]++; lo[Sampler.Sample(logits, 0.3f, 0, 1f, ref rng)]++; }
        Assert.True(lo[0] > hi[0]);            // low temperature: more deterministic
        Assert.True(hi[2] + hi[3] + hi[4] > lo[2] + lo[3] + lo[4]); // high temperature: wider spread
    }
}
