namespace GLF.Agent.Vision;

/// <summary>
/// Finds "which thing on screen am I?" purely from cause and effect. For every action, any object that moved
/// rigidly (same shape, new position) is credited with that displacement. The colour class that keeps moving
/// in response to the agent's actions is the avatar, and the averaged displacements are what each action does.
/// </summary>
public sealed class AvatarDiscovery
{
    sealed class Stat
    {
        public int Moves;
        public readonly double[] Dx, Dy;
        public readonly int[] N;
        public Stat(int na) { Dx = new double[na]; Dy = new double[na]; N = new int[na]; }
    }

    readonly int _na;
    readonly Dictionary<int, Stat> _stats = new();
    public int Steps { get; private set; }
    public int AvatarClass { get; private set; } = -1;
    public bool Ready => AvatarClass >= 0;
    public int MinMoves = 4;

    public AvatarDiscovery(int actionCount) => _na = actionCount;

    static bool Same(in Blob a, in Blob b) =>
        a.Cls == b.Cls && a.Area == b.Area && a.W == b.W && a.H == b.H;

    public void Observe(Scene prev, int action, Scene cur)
    {
        Steps++;
        var pb = prev.Blobs; var cb = cur.Blobs;
        Span<bool> pm = pb.Count <= 256 ? stackalloc bool[pb.Count] : new bool[pb.Count];
        Span<bool> cm = cb.Count <= 256 ? stackalloc bool[cb.Count] : new bool[cb.Count];

        for (int i = 0; i < pb.Count; i++)
            for (int j = 0; j < cb.Count; j++)
                if (!cm[j] && Same(pb[i], cb[j]) && Math.Abs(pb[i].Cx - cb[j].Cx) < .5 && Math.Abs(pb[i].Cy - cb[j].Cy) < .5)
                { pm[i] = cm[j] = true; break; }

        for (int i = 0; i < pb.Count; i++)
        {
            if (pm[i]) continue;
            int match = -1, pc = 0, cc = 0;
            for (int k = 0; k < pb.Count; k++) if (!pm[k] && pb[k].Cls == pb[i].Cls) pc++;
            for (int j = 0; j < cb.Count; j++)
                if (!cm[j] && cb[j].Cls == pb[i].Cls) { cc++; if (Same(pb[i], cb[j])) match = j; }
            if (pc != 1 || cc != 1 || match < 0) continue; // ambiguous or not a rigid move

            if (!_stats.TryGetValue(pb[i].Cls, out var st)) _stats[pb[i].Cls] = st = new Stat(_na);
            st.Moves++; st.N[action]++;
            st.Dx[action] += cb[match].Cx - pb[i].Cx;
            st.Dy[action] += cb[match].Cy - pb[i].Cy;
        }

        if (!Ready)
        {
            int best = -1, bm = 0;
            foreach (var (cls, st) in _stats)
            {
                int acts = 0; foreach (var n in st.N) if (n > 0) acts++;
                if (st.Moves >= MinMoves && acts >= 2 && st.Moves > bm) { best = cls; bm = st.Moves; }
            }
            AvatarClass = best;
        }
    }

    /// <summary>Mean on-screen displacement (pixels) caused by <paramref name="action"/>, once observed.</summary>
    public bool TryEffect(int action, out double dx, out double dy)
    {
        dx = dy = 0;
        if (!Ready || !_stats.TryGetValue(AvatarClass, out var st) || st.N[action] == 0) return false;
        dx = st.Dx[action] / st.N[action]; dy = st.Dy[action] / st.N[action];
        return true;
    }

    /// <summary>One grid step in pixels, inferred from the smallest non-zero displacement per axis.</summary>
    public (double X, double Y) StepSize()
    {
        double sx = 0, sy = 0;
        for (int a = 0; a < _na; a++)
        {
            if (!TryEffect(a, out var dx, out var dy)) continue;
            if (Math.Abs(dx) > .5 && (sx == 0 || Math.Abs(dx) < sx)) sx = Math.Abs(dx);
            if (Math.Abs(dy) > .5 && (sy == 0 || Math.Abs(dy) < sy)) sy = Math.Abs(dy);
        }
        return (sx == 0 ? 1 : sx, sy == 0 ? 1 : sy);
    }
}
