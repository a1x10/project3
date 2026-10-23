namespace GLF.Neural;

public enum LossKind { Mse, Huber, Bce }

/// <summary>Losses return the batch-mean value and write dL/dprediction (already divided by batch).</summary>
public static class Loss
{
    public static float Compute(LossKind kind, ReadOnlySpan<float> pred, ReadOnlySpan<float> target, Span<float> grad, int batch, int dim, float delta = 1f)
    {
        int n = batch * dim;
        float inv = 1f / batch, total = 0;
        for (int i = 0; i < n; i++)
        {
            float p = pred[i], t = target[i], e = p - t;
            switch (kind)
            {
                case LossKind.Mse:
                    total += 0.5f * e * e; grad[i] = e * inv; break;
                case LossKind.Huber:
                    if (MathF.Abs(e) <= delta) { total += 0.5f * e * e; grad[i] = e * inv; }
                    else { total += delta * (MathF.Abs(e) - 0.5f * delta); grad[i] = delta * MathF.Sign(e) * inv; }
                    break;
                case LossKind.Bce: // pred = logit
                {
                    float s = 1f / (1f + MathF.Exp(-p));
                    total += MathF.Max(p, 0) - p * t + MathF.Log(1f + MathF.Exp(-MathF.Abs(p)));
                    grad[i] = (s - t) * inv;
                    break;
                }
            }
        }
        return total * inv;
    }

    /// <summary>Softmax + cross entropy over class logits [batch, classes].</summary>
    public static float SoftmaxCrossEntropy(ReadOnlySpan<float> logits, ReadOnlySpan<int> labels, Span<float> grad, int batch, int classes)
    {
        float total = 0, inv = 1f / batch;
        for (int b = 0; b < batch; b++)
        {
            var l = logits.Slice(b * classes, classes);
            float max = l[0]; for (int c = 1; c < classes; c++) if (l[c] > max) max = l[c];
            float sum = 0; for (int c = 0; c < classes; c++) sum += MathF.Exp(l[c] - max);
            float logSum = MathF.Log(sum) + max;
            total += logSum - l[labels[b]];
            for (int c = 0; c < classes; c++)
                grad[b * classes + c] = (MathF.Exp(l[c] - logSum) - (c == labels[b] ? 1f : 0f)) * inv;
        }
        return total * inv;
    }
}
