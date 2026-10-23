namespace GLF.Agent;

public readonly record struct StepResult(long Obs, double Reward, bool Terminal, bool Truncated)
{
    public bool Done => Terminal || Truncated;
}

/// <summary>Anything the agent can be dropped into: it only sees opaque observations, rewards and a number of actions.</summary>
public interface IEnvironment
{
    int ActionCount { get; }
    long Reset();
    StepResult Step(int action);
}

/// <summary>
/// A closed room: the exit is behind a locked door, the key is far away in another corridor.
/// The agent is not told any of this; it sees only an opaque observation id and a reward at the exit.
/// </summary>
public sealed class EscapeRoom : IEnvironment
{
    public static readonly string[] DefaultMap =
    {
        "###########",
        "#S..#.....#",
        "#.#.#.###.#",
        "#.#...#K#.#",
        "#.#####.#.#",
        "#.....#.#.#",
        "#####.#.#.#",
        "#E.D..#...#",
        "###########",
    };

    readonly string[] _map;
    readonly int _maxSteps;
    int _x, _y, _steps;
    bool _key;

    public EscapeRoom(string[]? map = null, int maxSteps = 3000) { _map = map ?? DefaultMap; _maxSteps = maxSteps; }
    public int ActionCount => 4;
    public string[] Map => _map;
    public int X => _x;
    public int Y => _y;
    public bool HasKey => _key;

    long Obs() => ((long)_x << 16) | ((long)_y << 1) | (_key ? 1L : 0L);

    public long Reset()
    {
        for (int y = 0; y < _map.Length; y++)
            for (int x = 0; x < _map[y].Length; x++)
                if (_map[y][x] == 'S') { _x = x; _y = y; }
        _key = false; _steps = 0;
        return Obs();
    }

    public StepResult Step(int a)
    {
        _steps++;
        int nx = _x + (a == 1 ? 1 : a == 3 ? -1 : 0), ny = _y + (a == 2 ? 1 : a == 0 ? -1 : 0);
        char c = _map[ny][nx];
        bool blocked = c == '#' || (c == 'D' && !_key);
        if (!blocked) { _x = nx; _y = ny; }
        if (c == 'K' && !blocked) _key = true;
        if (c == 'E' && !blocked) return new StepResult(Obs(), 1.0, true, false);
        return new StepResult(Obs(), 0.0, false, _steps >= _maxSteps);
    }
}
