namespace GLF.Agent.Vision;

/// <summary>Raw screen: packed RGB bytes, row-major. This is all the vision agent is ever given.</summary>
public sealed class Frame
{
    public readonly int Width, Height;
    public readonly byte[] Rgb;
    public Frame(int w, int h) { Width = w; Height = h; Rgb = new byte[w * h * 3]; }
}

public interface IPixelEnvironment
{
    int ActionCount { get; }
    Frame Reset();
    (Frame Frame, double Reward, bool Terminal, bool Truncated) Step(int action);
}
