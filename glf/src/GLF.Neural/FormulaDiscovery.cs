using System.Text;

namespace GLF.Neural;

public sealed class Term
{
    public readonly string Name;
    public readonly Func<double[], double> Eval;
    public Term(string name, Func<double[], double> eval) { Name = name; Eval = eval; }
}

public sealed class DiscoveredFormula
{
    public required (Term Term, double Coef)[] Terms { get; init; }
    public required double R2 { get; init; }

    public double Eval(double[] x)
    {
        double s = 0;
        foreach (var (t, c) in Terms) s += c * t.Eval(x);
        return s;
    }

    public override string ToString()
    {
        if (Terms.Length == 0) return "0";
        var sb = new StringBuilder();
        foreach (var (t, c) in Terms.OrderByDescending(p => Math.Abs(p.Coef)))
        {
            if (sb.Length > 0) sb.Append(c < 0 ? " - " : " + "); else if (c < 0) sb.Append('-');
            sb.Append(Math.Abs(c).ToString("0.###", System.Globalization.CultureInfo.InvariantCulture));
            if (t.Name != "1") sb.Append('·').Append(t.Name);
        }
        return sb.ToString();
    }
}

/// <summary>
/// Turns a trained network (or any data) into a human-readable formula. Sparse regression over a library of candidate terms
/// (SINDy-style sequential thresholded ridge): fit all terms, drop the small coefficients, refit the survivors, repeat.
/// The library defines the *vocabulary* of formulas that can be found; the data decides which words are used.
/// </summary>
public static class FormulaDiscovery
{
    public static Term[] Library(string[] vars, int[]? freqs = null)
    {
        freqs ??= new[] { 1, 2, 3, 4 };
        int d = vars.Length;
        var t = new List<Term> { new("1", _ => 1.0) };
        for (int i = 0; i < d; i++)
        {
            int a = i; string n = vars[i];
            t.Add(new Term(n, x => x[a]));
            t.Add(new Term($"{n}²", x => x[a] * x[a]));
            t.Add(new Term($"{n}³", x => x[a] * x[a] * x[a]));
            t.Add(new Term($"tanh({n})", x => Math.Tanh(x[a])));
            foreach (int k in freqs)
            {
                int kk = k; string ks = k == 1 ? "" : k.ToString();
                t.Add(new Term($"sin({ks}{n})", x => Math.Sin(kk * x[a])));
                t.Add(new Term($"cos({ks}{n})", x => Math.Cos(kk * x[a])));
                for (int j = 0; j < d; j++)
                {
                    if (j == i || k == 1) continue; // sin(x)·y ≈ x·y: would only add collinear duplicates
                    int b = j; string m = vars[j];
                    t.Add(new Term($"sin({ks}{n})·{m}", x => Math.Sin(kk * x[a]) * x[b]));
                    t.Add(new Term($"cos({ks}{n})·{m}", x => Math.Cos(kk * x[a]) * x[b]));
                }
            }
            for (int j = i + 1; j < d; j++)
            {
                int b = j; string m = vars[j];
                t.Add(new Term($"{n}·{m}", x => x[a] * x[b]));
                t.Add(new Term($"{n}²·{m}", x => x[a] * x[a] * x[b]));
                t.Add(new Term($"{n}·{m}²", x => x[a] * x[b] * x[b]));
            }
        }
        return t.ToArray();
    }

    public static DiscoveredFormula Fit(Term[] lib, double[][] X, double[] y, double threshold = 0.05, double ridge = 1e-6, int iterations = 12)
    {
        int n = X.Length, p = lib.Length;
        var theta = new double[p][]; // column-major
        var scale = new double[p];
        for (int j = 0; j < p; j++)
        {
            theta[j] = new double[n];
            double ss = 0;
            for (int i = 0; i < n; i++) { double v = lib[j].Eval(X[i]); theta[j][i] = v; ss += v * v; }
            scale[j] = Math.Sqrt(ss / n) + 1e-12;
            for (int i = 0; i < n; i++) theta[j][i] /= scale[j];
        }

        var active = Enumerable.Range(0, p).ToList();
        var coef = new double[p];
        for (int it = 0; it < iterations; it++)
        {
            var c = SolveRidge(theta, y, active, ridge);
            Array.Clear(coef);
            for (int k = 0; k < active.Count; k++) coef[active[k]] = c[k] / scale[active[k]];
            var keep = active.Where(j => Math.Abs(coef[j]) >= threshold).ToList();
            if (keep.Count == active.Count) break;
            if (keep.Count == 0) { active = keep; Array.Clear(coef); break; }
            active = keep;
        }

        double my = y.Average(), sst = 0, sse = 0;
        for (int i = 0; i < n; i++)
        {
            double pred = 0;
            foreach (int j in active) pred += coef[j] * theta[j][i] * scale[j];
            sse += (y[i] - pred) * (y[i] - pred); sst += (y[i] - my) * (y[i] - my);
        }
        return new DiscoveredFormula
        {
            Terms = active.Select(j => (lib[j], coef[j])).ToArray(),
            R2 = sst > 0 ? 1 - sse / sst : 1,
        };
    }

    static double[] SolveRidge(double[][] theta, double[] y, List<int> cols, double ridge)
    {
        int m = cols.Count, n = y.Length;
        var A = new double[m, m]; var b = new double[m];
        for (int a = 0; a < m; a++)
        {
            var ca = theta[cols[a]];
            double sy = 0; for (int i = 0; i < n; i++) sy += ca[i] * y[i];
            b[a] = sy;
            for (int c = a; c < m; c++)
            {
                var cc = theta[cols[c]];
                double s = 0; for (int i = 0; i < n; i++) s += ca[i] * cc[i];
                A[a, c] = A[c, a] = s;
            }
            A[a, a] += ridge * n;
        }
        // Cholesky
        var L = new double[m, m];
        for (int i = 0; i < m; i++)
            for (int j = 0; j <= i; j++)
            {
                double s = A[i, j];
                for (int k = 0; k < j; k++) s -= L[i, k] * L[j, k];
                L[i, j] = i == j ? Math.Sqrt(Math.Max(s, 1e-14)) : s / L[j, j];
            }
        var z = new double[m];
        for (int i = 0; i < m; i++) { double s = b[i]; for (int k = 0; k < i; k++) s -= L[i, k] * z[k]; z[i] = s / L[i, i]; }
        var x = new double[m];
        for (int i = m - 1; i >= 0; i--) { double s = z[i]; for (int k = i + 1; k < m; k++) s -= L[k, i] * x[k]; x[i] = s / L[i, i]; }
        return x;
    }
}
