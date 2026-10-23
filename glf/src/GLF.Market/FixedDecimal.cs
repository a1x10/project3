namespace GLF.Market;

/// <summary>Zero-allocation ASCII decimal -> fixed point (1e-8) conversion. No doubles on the wire path.</summary>
public static class FixedDecimal
{
    public const long Scale = 100_000_000L;

    public static bool TryParse(ReadOnlySpan<byte> s, out long value)
    {
        value = 0;
        if (s.Length == 0) return false;
        int i = 0;
        bool neg = false;
        if (s[0] == (byte)'-') { neg = true; i++; }

        long ip = 0; int intDigits = 0;
        for (; i < s.Length && s[i] != (byte)'.'; i++)
        {
            int d = s[i] - '0';
            if ((uint)d > 9) return false;
            ip = ip * 10 + d; intDigits++;
            if (ip > 90_000_000_000L) return false;
        }

        long frac = 0; int seen = 0, used = 0;
        if (i < s.Length)
        {
            for (i++; i < s.Length; i++)
            {
                int d = s[i] - '0';
                if ((uint)d > 9) return false;
                seen++;
                if (used < 8) { frac = frac * 10 + d; used++; }
            }
        }
        if (intDigits == 0 && seen == 0) return false;
        for (; used < 8; used++) frac *= 10;

        long v = ip * Scale + frac;
        value = neg ? -v : v;
        return true;
    }
}
