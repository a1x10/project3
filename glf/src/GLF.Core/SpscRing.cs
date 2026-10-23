namespace GLF.Core;

/// <summary>Lock-free single-producer/single-consumer ring. Capacity must be a power of two.</summary>
public sealed class SpscRing<T>
{
    readonly T[] _buf;
    readonly int _mask;
    long _head; // consumer
    long _tail; // producer

    public SpscRing(int capacityPow2)
    {
        if (capacityPow2 < 2 || (capacityPow2 & (capacityPow2 - 1)) != 0)
            throw new ArgumentException("capacity must be a power of two", nameof(capacityPow2));
        _buf = new T[capacityPow2];
        _mask = capacityPow2 - 1;
    }

    public bool TryEnqueue(in T item)
    {
        long t = _tail;
        if (t - Volatile.Read(ref _head) >= _buf.Length) return false;
        _buf[t & _mask] = item;
        Volatile.Write(ref _tail, t + 1);
        return true;
    }

    public bool TryDequeue(out T item)
    {
        long h = _head;
        if (h == Volatile.Read(ref _tail)) { item = default!; return false; }
        item = _buf[h & _mask];
        Volatile.Write(ref _head, h + 1);
        return true;
    }
}
