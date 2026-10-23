namespace GLF.Agent.Vision;

/// <summary>
/// The locked-room game rendered to pixels. The agent receives only the image.
/// Optional handicaps prove that nothing is hard-coded: per-pixel noise, a shuffled colour palette,
/// and a secretly permuted action->movement mapping.
/// </summary>
public sealed class PixelRoom : IPixelEnvironment
{
    enum Role { Floor, Wall, Avatar, Key, Door, Exit }

    static readonly (byte R, byte G, byte B)[] Colors =
    {
        (30, 30, 30), (70, 70, 220), (230, 40, 40), (240, 220, 40), (150, 90, 30), (40, 200, 60),
        (200, 200, 200), (200, 60, 200), (40, 200, 200), (255, 140, 0), (120, 120, 120), (0, 100, 0),
    };

    readonly EscapeRoom _env;
    readonly int _tile, _noise;
    readonly int[] _perm = { 0, 1, 2, 3 };
    readonly (byte R, byte G, byte B)[] _pal = new (byte, byte, byte)[6];
    readonly Random _rng;

    public int ActionCount => 4;
    public int Width => _env.Map[0].Length * _tile;
    public int Height => _env.Map.Length * _tile;

    /// <summary>Ground truth, for reports only: (dx,dy) in tiles of agent-action <paramref name="a"/>.</summary>
    public (int dx, int dy) TrueMove(int a)
    {
        int e = _perm[a];
        return (e == 1 ? 1 : e == 3 ? -1 : 0, e == 2 ? 1 : e == 0 ? -1 : 0);
    }

    public (byte R, byte G, byte B) AvatarColor => _pal[(int)Role.Avatar];

    public PixelRoom(string[]? map = null, int tile = 8, int noise = 0, bool shuffleActions = false, int paletteSeed = 0, int seed = 1)
    {
        _env = new EscapeRoom(map);
        _tile = tile; _noise = noise; _rng = new Random(seed);
        var order = Enumerable.Range(0, Colors.Length).ToArray();
        if (paletteSeed != 0)
        {
            var pr = new Random(paletteSeed);
            for (int i = order.Length - 1; i > 0; i--) { int j = pr.Next(i + 1); (order[i], order[j]) = (order[j], order[i]); }
        }
        for (int r = 0; r < 6; r++) _pal[r] = Colors[order[r]];
        if (shuffleActions)
        {
            var pr = new Random(seed * 31 + 7);
            for (int i = 3; i > 0; i--) { int j = pr.Next(i + 1); (_perm[i], _perm[j]) = (_perm[j], _perm[i]); }
        }
    }

    public Frame Reset() { _env.Reset(); return Render(); }

    public (Frame, double, bool, bool) Step(int action)
    {
        var r = _env.Step(_perm[action]);
        return (Render(), r.Reward, r.Terminal, r.Truncated);
    }

    void Fill(Frame f, int x0, int y0, int w, int h, Role role)
    {
        var (cr, cg, cb) = _pal[(int)role];
        for (int y = y0; y < y0 + h; y++)
            for (int x = x0; x < x0 + w; x++)
            {
                int i = (y * f.Width + x) * 3;
                f.Rgb[i] = Px(cr); f.Rgb[i + 1] = Px(cg); f.Rgb[i + 2] = Px(cb);
            }
    }

    byte Px(int v)
    {
        if (_noise > 0) v += _rng.Next(-_noise, _noise + 1);
        return (byte)Math.Clamp(v, 0, 255);
    }

    Frame Render()
    {
        var f = new Frame(Width, Height);
        var map = _env.Map;
        int t = _tile;
        for (int y = 0; y < map.Length; y++)
            for (int x = 0; x < map[y].Length; x++)
            {
                int px = x * t, py = y * t;
                switch (map[y][x])
                {
                    case '#': Fill(f, px, py, t, t, Role.Wall); break;
                    case 'D' when !_env.HasKey: Fill(f, px, py, t, t, Role.Door); break;
                    case 'E': Fill(f, px, py, t, t, Role.Exit); break;
                    case 'K' when !_env.HasKey:
                        Fill(f, px, py, t, t, Role.Floor);
                        Fill(f, px + t / 4, py + t / 4, t / 2, t / 2, Role.Key);
                        break;
                    default: Fill(f, px, py, t, t, Role.Floor); break;
                }
            }
        Fill(f, _env.X * t + 1, _env.Y * t + 1, t - 2, t - 2, Role.Avatar);
        return f;
    }
}
