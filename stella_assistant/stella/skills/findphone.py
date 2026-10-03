"""«Найди мой телефон»: звонок через SIP-телефонию (baresip) и/или громкое push-уведомление."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading

from .base import Reply, Skill, intent


class FindPhone(Skill):
    name = "findphone"

    def sip_call(self, number: str, seconds: int) -> bool:
        """Звонок через SIP-аккаунт (Zadarma, Sipnet, Манго и т.п.) с помощью baresip."""
        account = self.cfg.get("find_phone.sip_account")  # например sip:12345@sip.zadarma.com
        password = self.cfg.get("find_phone.sip_password")
        if not (account and password and shutil.which("baresip")):
            return False
        cfg_dir = tempfile.mkdtemp(prefix="stella-sip-")
        acc = account if account.startswith("sip:") else f"sip:{account}"
        with open(os.path.join(cfg_dir, "accounts"), "w") as f:
            f.write(f"<{acc}>;auth_pass={password};regint=0\n")
        with open(os.path.join(cfg_dir, "config"), "w") as f:
            f.write("module_path /usr/lib/baresip/modules\nmodule stdio.so\nmodule g711.so\nmodule alsa.so\n"
                    "module account.so\nmodule menu.so\nmodule contact.so\naudio_player alsa,default\n"
                    "audio_source alsa,default\n")

        def run():
            try:
                subprocess.run(["baresip", "-f", cfg_dir, "-e", f"/dial {number}", "-t", str(seconds)],
                               capture_output=True, timeout=seconds + 15)
            except Exception as e:
                self.log.warning("baresip: %s", e)
            finally:
                shutil.rmtree(cfg_dir, ignore_errors=True)
        threading.Thread(target=run, daemon=True, name="sip-call").start()
        return True

    @intent(r"\b(?:найди|ищи|где)\s+(?:мой\s+)?(?:телефон|смартфон|мобильник|айфон)\b|"
            r"\b(?:позвони|набери)\s+(?:на\s+)?(?:мой\s+)?(?:телефон|мобильный|смартфон)\b|\bпотерял\w* телефон\b",
            priority=65)
    def find(self, ctx):
        number = self.cfg.get("find_phone.phone_number")
        seconds = int(self.cfg.get("find_phone.ring_seconds", 40))
        called = bool(number) and self.sip_call(number, seconds)
        if self.a.notifier.configured:
            self.a.notify("Я здесь! Ты искал свой телефон 🙂", title="📱 Стелла ищет телефон", urgent=True)
        if called:
            return Reply("Звоню на твой телефон! Слушай, где зазвонит.", emotion="joy", intensity=0.6)
        if self.a.notifier.configured:
            return Reply("Отправила громкое уведомление на телефон. Прислушайся!", emotion="joy", intensity=0.5)
        return Reply("Чтобы я могла позвонить, добавь SIP-аккаунт (find_phone) или Telegram/ntfy в настройках.",
                     emotion="sadness", intensity=0.5)
