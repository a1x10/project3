"""«Стелла, что за музыка играет?» — распознавание песни через микрофон (Shazam / AudD)."""
from __future__ import annotations

import asyncio

from ..audio import dsp
from ..audio.io import RATE
from .base import Reply, Skill, intent


class Shazam(Skill):
    name = "shazam"

    def recognize(self, wav: bytes):
        """-> (название, исполнитель) или None."""
        try:
            from shazamio import Shazam as ShazamClient

            async def run():
                return await ShazamClient(language="ru-RU", endpoint_country="RU").recognize(wav)
            out = asyncio.run(run())
            t = out.get("track") if isinstance(out, dict) else None
            if t:
                return t.get("title"), t.get("subtitle")
        except ImportError:
            self.log.info("shazamio не установлен — пробую AudD")
        except Exception as e:
            self.log.warning("Shazam: %s", e)
        token = self.cfg.get("music.audd_token")
        if token:
            try:
                r = self.a.http.post("https://api.audd.io/", data={"api_token": token},
                                     files={"file": ("clip.wav", wav, "audio/wav")}, timeout=30)
                res = r.json().get("result")
                if res:
                    return res.get("title"), res.get("artist")
            except Exception as e:
                self.log.warning("AudD: %s", e)
        return None

    @intent(r"\b(?:что (?:сейчас |это )?(?:играет|за песня|за трек|звучит|за музыка|за мелодия)|"
            r"как называется (?:эта )?(?:песня|трек|мелодия)|кто (?:это )?поет|узнай (?:песню|мелодию|трек)|"
            r"шазам\w*)\b", priority=73)
    def what_song(self, ctx):
        if ctx.source != "voice" or not self.a.mic.ok:
            return Reply("Чтобы узнать песню, мне нужно её услышать — спроси меня голосом.")
        p = self.a.player
        if p.is_playing():  # играет наша музыка — навык music уже ответил бы; на всякий случай
            cur = p.current()
            if cur and cur.source != "radio":
                return Reply(f"Это {cur.display()}.")
        self.a.say("Слушаю…", emotion="interest")
        if self.a.listener:
            self.a.listener.mute(12)
        audio = self.a.mic.record(10.0)
        if self.a.listener:
            self.a.listener.unmute()
        if len(audio) < RATE * 3:
            return Reply("Ничего не услышала.", emotion="sadness")
        res = self.recognize(dsp.wav_bytes(audio, RATE))
        if not res or not res[0]:
            return Reply("Не узнала эту песню. Сделай погромче и спроси ещё раз.", emotion="sadness")
        title, artist = res
        self.a.memory.kv_set("last_shazam", {"title": title, "artist": artist})
        return Reply(f"Это «{title}» — {artist}." if artist else f"Это «{title}».", emotion="surprise",
                     intensity=0.7, card=f"{artist} — {title}")
