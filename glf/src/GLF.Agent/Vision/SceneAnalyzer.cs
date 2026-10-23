namespace GLF.Agent.Vision;

public struct Blob
{
    public int Cls, Area, MinX, MinY, MaxX, MaxY;
    public double Cx, Cy;
    public int W => MaxX - MinX + 1;
    public int H => MaxY - MinY + 1;
}

public sealed class Scene
{
    public readonly List<Blob> Blobs = new();
}

/// <summary>Learns colour classes on the fly: a pixel joins the nearest known class, or founds a new one.</summary>
public sealed class ColorClusters
{
    readonly List<(int R, int G, int B)> _c = new();
    readonly int _thr2;
    public int Count => _c.Count;
    public (int R, int G, int B) Center(int cls) => _c[cls];

    public ColorClusters(int threshold = 50) => _thr2 = threshold * threshold;

    public int Classify(int r, int g, int b)
    {
        int best = -1, bd = int.MaxValue;
        for (int i = 0; i < _c.Count; i++)
        {
            int dr = r - _c[i].R, dg = g - _c[i].G, db = b - _c[i].B;
            int d = dr * dr + dg * dg + db * db;
            if (d < bd) { bd = d; best = i; }
        }
        if (best >= 0 && bd <= _thr2) return best;
        _c.Add((r, g, b));
        return _c.Count - 1;
    }
}

/// <summary>Pixels -> colour classes -> connected regions ("objects") with area, bounding box and centroid.</summary>
public sealed class SceneAnalyzer
{
    public readonly ColorClusters Colors = new();
    public int MinArea = 4;
    int[] _cls = Array.Empty<int>();
    bool[] _seen = Array.Empty<bool>();
    int[] _stack = Array.Empty<int>();

    public void Analyze(Frame f, Scene scene)
    {
        int w = f.Width, h = f.Height, n = w * h;
        if (_cls.Length != n) { _cls = new int[n]; _seen = new bool[n]; _stack = new int[n]; }
        else Array.Clear(_seen);
        scene.Blobs.Clear();

        for (int i = 0; i < n; i++)
            _cls[i] = Colors.Classify(f.Rgb[i * 3], f.Rgb[i * 3 + 1], f.Rgb[i * 3 + 2]);

        for (int start = 0; start < n; start++)
        {
            if (_seen[start]) continue;
            int cls = _cls[start], sp = 0;
            var b = new Blob { Cls = cls, MinX = int.MaxValue, MinY = int.MaxValue, MaxX = -1, MaxY = -1 };
            double sx = 0, sy = 0;
            _stack[sp++] = start; _seen[start] = true;
            while (sp > 0)
            {
                int p = _stack[--sp], x = p % w, y = p / w;
                b.Area++; sx += x; sy += y;
                if (x < b.MinX) b.MinX = x; if (x > b.MaxX) b.MaxX = x;
                if (y < b.MinY) b.MinY = y; if (y > b.MaxY) b.MaxY = y;
                if (x > 0 && !_seen[p - 1] && _cls[p - 1] == cls) { _seen[p - 1] = true; _stack[sp++] = p - 1; }
                if (x < w - 1 && !_seen[p + 1] && _cls[p + 1] == cls) { _seen[p + 1] = true; _stack[sp++] = p + 1; }
                if (y > 0 && !_seen[p - w] && _cls[p - w] == cls) { _seen[p - w] = true; _stack[sp++] = p - w; }
                if (y < h - 1 && !_seen[p + w] && _cls[p + w] == cls) { _seen[p + w] = true; _stack[sp++] = p + w; }
            }
            if (b.Area < MinArea) continue;
            b.Cx = sx / b.Area; b.Cy = sy / b.Area;
            scene.Blobs.Add(b);
        }
    }
}
