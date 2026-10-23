using GLF.Core;

namespace GLF.Agent.Vision;

/// <summary>
/// Pixels in, actions out. Pipeline per frame:
///   colour classes -> objects -> (who am I? what do my actions do?) -> object-centric state
///   (my grid cell + which object types still exist) -> the same model-based planner as before.
/// Until the avatar is identified the agent "babbles": it tries actions at random to see what moves.
/// </summary>
public sealed class VisualAgent
{
    readonly int _na;
    readonly SceneAnalyzer _an = new();
    readonly AvatarDiscovery _disc;
    readonly ModelBasedAgent _planner;
    readonly Random _rng;
    Scene _prev = new(), _cur = new();
    bool _havePrev, _pending;
    int _lastAction;
    long _lastObs;
    int _babble;

    public int MaxBabble = 80;
    public readonly LatencyHistogram VisionTime = new();
    public AvatarDiscovery Discovery => _disc;
    public SceneAnalyzer Analyzer => _an;
    public ModelBasedAgent Planner => _planner;
    public int BabbleSteps => _babble;

    public VisualAgent(int actionCount, int seed = 1)
    {
        _na = actionCount;
        _disc = new AvatarDiscovery(actionCount);
        _planner = new ModelBasedAgent(actionCount, seed: seed);
        _rng = new Random(seed);
    }

    public void BeginEpisode() { _havePrev = false; _pending = false; }

    public int Act(Frame frame)
    {
        Look(frame);
        int a;
        if (!_disc.Ready && _babble < MaxBabble)
        {
            a = _babble < _na * 3 ? _babble % _na : _rng.Next(_na); // systematic first, then random
            _babble++;
            _pending = false;
        }
        else
        {
            long obs = Encode(_cur);
            a = _planner.Act(obs);
            _lastObs = obs; _pending = true;
        }
        _lastAction = a;
        return a;
    }

    public void Feed(Frame next, double reward, bool terminal)
    {
        (_prev, _cur) = (_cur, _prev);
        long t0 = Clock.Now();
        _an.Analyze(next, _cur);
        VisionTime.Record(Clock.ToNs(Clock.Now() - t0));
        _disc.Observe(_prev, _lastAction, _cur);
        if (_pending) _planner.Observe(_lastObs, _lastAction, reward, Encode(_cur), terminal);
    }

    void Look(Frame frame)
    {
        if (_havePrev) return; // already analysed by Feed
        long t0 = Clock.Now();
        _an.Analyze(frame, _cur);
        VisionTime.Record(Clock.ToNs(Clock.Now() - t0));
        _havePrev = true;
    }

    /// <summary>Object-centric state: avatar grid cell + bitmask of object types that currently exist.</summary>
    public long Encode(Scene s)
    {
        if (!_disc.Ready) return FallbackHash(s);
        var (sx, sy) = _disc.StepSize();
        long cx = -1, cy = -1, mask = 0;
        foreach (var b in s.Blobs)
        {
            if (b.Cls == _disc.AvatarClass) { cx = (long)Math.Floor(b.Cx / sx); cy = (long)Math.Floor(b.Cy / sy); }
            else if (b.Cls < 38) mask |= 1L << b.Cls;
        }
        return (mask << 24) | ((cx & 0xFFF) << 12) | (cy & 0xFFF);
    }

    static long FallbackHash(Scene s)
    {
        long h = 1469598103934665603L;
        foreach (var b in s.Blobs) { h = (h ^ b.Cls) * 1099511628211L; h = (h ^ (long)(b.Cx * 4)) * 1099511628211L; h = (h ^ (long)(b.Cy * 4)) * 1099511628211L; }
        return h;
    }
}

public static class PixelTrainer
{
    public static List<(int Steps, bool Solved, double Ms)> Run(IPixelEnvironment env, VisualAgent agent, int episodes)
    {
        var log = new List<(int, bool, double)>();
        for (int e = 0; e < episodes; e++)
        {
            long t0 = System.Diagnostics.Stopwatch.GetTimestamp();
            agent.BeginEpisode();
            var frame = env.Reset();
            int steps = 0; bool solved = false;
            while (true)
            {
                int a = agent.Act(frame);
                var (f, r, term, trunc) = env.Step(a);
                agent.Feed(f, r, term);
                frame = f; steps++;
                if (term) solved = true;
                if (term || trunc) break;
            }
            log.Add((steps, solved, System.Diagnostics.Stopwatch.GetElapsedTime(t0).TotalMilliseconds));
        }
        return log;
    }
}
