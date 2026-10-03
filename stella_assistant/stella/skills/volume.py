"""Громкость: «громче», «тише», «громкость 7» (шкала 0–10 как у Алисы), «выключи звук»."""
from __future__ import annotations

from .base import Reply, Skill, intent


class Volume(Skill):
    name = "volume"

    @intent(r"^(?:сделай\s+)?(?:громче|погромче|еще громче|прибавь(?: звук| громкость)?|увеличь (?:звук|громкость))"
            r"(?: на (\d+))?(?: пожалуйста)?$", priority=72)
    def louder(self, ctx):
        steps = int(ctx.group(1) or 1)
        v = self.a.volume.change(10 * steps)
        return Reply(f"Громкость {round(v / 10)}.", emotion="joy", intensity=0.3)

    @intent(r"^(?:сделай\s+)?(?:тише|потише|еще тише|убавь(?: звук| громкость)?|уменьши (?:звук|громкость))"
            r"(?: на (\d+))?(?: пожалуйста)?$", priority=72)
    def quieter(self, ctx):
        steps = int(ctx.group(1) or 1)
        v = self.a.volume.change(-10 * steps)
        return Reply(f"Громкость {round(v / 10)}.")

    @intent(r"\bгромкост\w*\s+(?:на\s+)?(\d+)(?:\s*(процент\w*|%))?\b|\bпоставь громкость (?:на )?(\d+)\b", priority=71)
    def set_level(self, ctx):
        val = int(ctx.group(1) or ctx.group(3) or 5)
        pct = val if (ctx.group(2) or val > 10) else val * 10
        v = self.a.volume.set(pct)
        return Reply(f"Громкость {round(v / 10)}.", emotion="confidence", intensity=0.3)

    @intent(r"\b(?:максимальн\w* громкость|громкость на максимум|на полную(?: громкость)?|максимально громко)\b",
            priority=71)
    def max(self, ctx):
        self.a.volume.set(100)
        return Reply("Громкость на максимум!", emotion="surprise", intensity=0.6)

    @intent(r"^(?:выключи звук|без звука|отключи звук|мьют|замьють|беззвучный режим)$", priority=72)
    def mute(self, ctx):
        self.a.volume.mute(True)
        return Reply("", speak=False)

    @intent(r"^(?:включи звук|верни звук|включи обратно звук)$", priority=72)
    def unmute(self, ctx):
        self.a.volume.mute(False)
        return Reply("Звук включён.")

    @intent(r"\bкакая (?:сейчас )?громкость\b|\bна какой громкости\b", priority=70)
    def which(self, ctx):
        return Reply(f"Громкость {round(self.a.volume.get() / 10)} из 10.")
