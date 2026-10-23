namespace GLF.Agent;

/// <summary>
/// Environment-agnostic learner (no neural net, no LLM): builds a world model online from raw experience
/// and plans on it. Unknown (state, action) pairs are valued optimistically until a reward has been seen, which
/// produces systematic curiosity-driven exploration; afterwards the agent plans the shortest known route to reward
/// (including intermediate sub-goals such as picking up a key, which it discovers on its own because
/// the observation changes and the exit becomes reachable).
/// </summary>
public sealed class ModelBasedAgent
{
    const int Unknown = -1, Terminal = -2;
    readonly int _na;
    readonly double _gamma;
    readonly Random _rng;
    readonly Dictionary<long, int> _ids = new();
    readonly List<int[]> _next = new();
    readonly List<double[]> _rew = new();
    readonly List<double> _v = new();
    bool _rewardSeen;

    public int StatesKnown => _ids.Count;
    public int UntriedActions { get { int n = 0; foreach (var r in _next) foreach (var t in r) if (t == Unknown) n++; return n; } }

    public ModelBasedAgent(int actionCount, double gamma = 0.97, int seed = 1)
    {
        _na = actionCount; _gamma = gamma; _rng = new Random(seed);
    }

    int Id(long obs)
    {
        if (_ids.TryGetValue(obs, out int id)) return id;
        id = _ids.Count; _ids[obs] = id;
        var n = new int[_na]; Array.Fill(n, Unknown);
        _next.Add(n); _rew.Add(new double[_na]); _v.Add(0);
        return id;
    }

    public void Observe(long obs, int action, double reward, long nextObs, bool terminal)
    {
        int s = Id(obs), s2 = Id(nextObs);
        _next[s][action] = terminal ? Terminal : s2;
        _rew[s][action] = reward;
        if (reward > 0) _rewardSeen = true;
    }

    double Q(int s, int a)
    {
        int t = _next[s][a];
        if (t == Unknown) return _rewardSeen ? 0.0 : 1.0; // optimism only while there is nothing better to chase
        if (t == Terminal) return _rew[s][a];
        return _rew[s][a] + _gamma * _v[t];
    }

    void Plan()
    {
        for (int sweep = 0; sweep < 200; sweep++)
        {
            double delta = 0;
            for (int s = 0; s < _v.Count; s++)
            {
                double best = double.MinValue;
                for (int a = 0; a < _na; a++) best = Math.Max(best, Q(s, a));
                delta = Math.Max(delta, Math.Abs(best - _v[s]));
                _v[s] = best;
            }
            if (delta < 1e-9) break;
        }
    }

    public int Act(long obs)
    {
        int s = Id(obs);
        Plan();
        double best = double.MinValue; int pick = 0, ties = 0;
        for (int a = 0; a < _na; a++)
        {
            double q = Q(s, a);
            if (q > best + 1e-12) { best = q; pick = a; ties = 1; }
            else if (Math.Abs(q - best) <= 1e-12 && _rng.Next(++ties) == 0) pick = a;
        }
        return pick;
    }
}

public static class Trainer
{
    public static List<(int Steps, bool Solved, double Ms)> Run(IEnvironment env, ModelBasedAgent agent, int episodes)
    {
        var log = new List<(int, bool, double)>();
        for (int e = 0; e < episodes; e++)
        {
            long t0 = System.Diagnostics.Stopwatch.GetTimestamp();
            long obs = env.Reset();
            int steps = 0; bool solved = false;
            while (true)
            {
                int a = agent.Act(obs);
                var r = env.Step(a);
                agent.Observe(obs, a, r.Reward, r.Obs, r.Terminal);
                obs = r.Obs; steps++;
                if (r.Terminal) solved = true;
                if (r.Done) break;
            }
            log.Add((steps, solved, System.Diagnostics.Stopwatch.GetElapsedTime(t0).TotalMilliseconds));
        }
        return log;
    }
}
