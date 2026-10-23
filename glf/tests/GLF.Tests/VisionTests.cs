using GLF.Agent.Vision;

namespace GLF.Tests;

public class VisionTests
{
    static readonly string[] OtherMap =
    {
        "#########",
        "#S.....E#",
        "#.#####.#",
        "#.#K#D#.#",
        "#.......#",
        "#########",
    };

    [Theory]
    [InlineData(0)]
    [InlineData(12)]
    public void Scene_has_expected_objects_even_with_noise(int noise)
    {
        var env = new PixelRoom(noise: noise);
        var an = new SceneAnalyzer(); var sc = new Scene();
        an.Analyze(env.Reset(), sc);
        Assert.Equal(6, an.Colors.Count);
        Assert.Equal(7, sc.Blobs.Count);       // wall, 2x floor regions, avatar, key, door, exit
        Assert.Contains(sc.Blobs, b => b.Area == 36); // avatar 6x6
    }

    [Fact]
    public void Avatar_and_action_effects_are_discovered_with_shuffled_actions()
    {
        var env = new PixelRoom(shuffleActions: true, paletteSeed: 5, noise: 8);
        var agent = new VisualAgent(4);
        PixelTrainer.Run(env, agent, 1);
        var d = agent.Discovery;
        Assert.True(d.Ready);
        var (sx, sy) = d.StepSize();
        Assert.Equal(8, sx, 1); Assert.Equal(8, sy, 1);
        for (int a = 0; a < 4; a++)
        {
            if (!d.TryEffect(a, out var dx, out var dy)) continue;
            var (tx, ty) = env.TrueMove(a);
            Assert.Equal(tx * 8, dx, 1); Assert.Equal(ty * 8, dy, 1);
        }
        var c = agent.Analyzer.Colors.Center(d.AvatarClass);
        var t = env.AvatarColor;
        Assert.True(Math.Abs(c.R - t.R) < 40 && Math.Abs(c.G - t.G) < 40 && Math.Abs(c.B - t.B) < 40);
    }

    [Theory]
    [InlineData(0, false, 0, null)]
    [InlineData(12, true, 3, null)]
    [InlineData(12, true, 9, "other")]
    public void Visual_agent_escapes_from_pixels_only(int noise, bool shuffle, int palette, string? map)
    {
        var env = new PixelRoom(map == null ? null : OtherMap, noise: noise, shuffleActions: shuffle, paletteSeed: palette);
        var agent = new VisualAgent(4);
        var log = PixelTrainer.Run(env, agent, 6);
        Assert.All(log, l => Assert.True(l.Solved));
        Assert.True(log[5].Steps < log[0].Steps || log[0].Steps <= 20);
        Assert.Equal(log[4].Steps, log[5].Steps);
    }
}
