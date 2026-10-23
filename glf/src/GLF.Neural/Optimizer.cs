namespace GLF.Neural;

/// <summary>AdamW with global-norm gradient clipping.</summary>
public sealed class Adam
{
    public float Lr, Beta1 = 0.9f, Beta2 = 0.999f, Eps = 1e-8f, WeightDecay, ClipNorm;
    long _t;

    public Adam(float lr = 1e-3f, float weightDecay = 0f, float clipNorm = 5f) { Lr = lr; WeightDecay = weightDecay; ClipNorm = clipNorm; }

    public float Step(List<Param> ps)
    {
        double sq = 0;
        foreach (var p in ps) foreach (var g in p.G) sq += (double)g * g;
        float norm = (float)Math.Sqrt(sq);
        float scale = ClipNorm > 0 && norm > ClipNorm ? ClipNorm / norm : 1f;

        _t++;
        float c1 = 1f - MathF.Pow(Beta1, _t), c2 = 1f - MathF.Pow(Beta2, _t);
        foreach (var p in ps)
        {
            var w = p.W; var g = p.G; var m = p.M; var v = p.V;
            for (int i = 0; i < w.Length; i++)
            {
                float gi = g[i] * scale;
                m[i] = Beta1 * m[i] + (1f - Beta1) * gi;
                v[i] = Beta2 * v[i] + (1f - Beta2) * gi * gi;
                float upd = (m[i] / c1) / (MathF.Sqrt(v[i] / c2) + Eps);
                if (!p.NoDecay && WeightDecay > 0) upd += WeightDecay * w[i];
                w[i] -= Lr * upd;
            }
        }
        return norm;
    }
}
