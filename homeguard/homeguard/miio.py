"""Минимальный клиент локального протокола Xiaomi miIO (UDP 54321, AES-128-CBC, токен устройства)."""
import hashlib
import itertools
import json
import socket
import struct

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HELLO = bytes.fromhex("21310020" + "ff" * 28)


class MiioError(Exception):
    pass


def _keys(token: bytes) -> tuple[bytes, bytes]:
    key = hashlib.md5(token).digest()
    return key, hashlib.md5(key + token).digest()


def encrypt(token: bytes, data: bytes) -> bytes:
    key, iv = _keys(token)
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(padder.update(data) + padder.finalize()) + enc.finalize()


def decrypt(token: bytes, data: bytes) -> bytes:
    key, iv = _keys(token)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(dec.update(data) + dec.finalize()) + unpadder.finalize()


def build_packet(token: bytes, device_id: bytes, stamp: int, payload: bytes) -> bytes:
    data = encrypt(token, payload)
    head = struct.pack(">HH4s4sI", 0x2131, 32 + len(data), b"\0" * 4, device_id, stamp)
    checksum = hashlib.md5(head + token + data).digest()
    return head + checksum + data


class MiioDevice:
    def __init__(self, ip: str, token_hex: str, port: int = 54321, timeout: float = 3.0, retries: int = 2):
        try:
            self.token = bytes.fromhex(token_hex)
        except ValueError:
            raise MiioError("Токен должен быть 32 hex-символа")
        if len(self.token) != 16:
            raise MiioError("Токен должен быть 32 hex-символа")
        self.addr = (ip, port)
        self.timeout = timeout
        self.retries = retries
        self._ids = itertools.count(1)

    def _exchange(self, sock: socket.socket, packet: bytes) -> bytes:
        sock.sendto(packet, self.addr)
        data, _ = sock.recvfrom(4096)
        return data

    def call(self, method: str, params=None):
        last: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                return self._call_once(method, params if params is not None else [])
            except (socket.timeout, TimeoutError, OSError) as e:
                last = e
        raise MiioError("Устройство не отвечает: проверь IP, токен и что оно в сети") from last

    def _call_once(self, method: str, params):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.timeout)
            hello = self._exchange(sock, HELLO)
            if len(hello) < 32:
                raise MiioError("Некорректный ответ на handshake")
            device_id, stamp = hello[8:12], struct.unpack(">I", hello[12:16])[0]
            payload = json.dumps({"id": next(self._ids) % 9999 + 1, "method": method, "params": params},
                                 separators=(",", ":")).encode()
            raw = self._exchange(sock, build_packet(self.token, device_id, stamp + 1, payload))
        if len(raw) <= 32:
            raise MiioError("Пустой ответ устройства")
        try:
            body = decrypt(self.token, raw[32:]).rstrip(b"\0")
            out = json.loads(body)
        except ValueError:
            raise MiioError("Не удалось расшифровать ответ — скорее всего, неверный токен")
        if "error" in out:
            raise MiioError(f"Устройство: {out['error'].get('message', out['error'])}")
        return out.get("result")

    # ---- MIoT ----
    def info(self) -> dict:
        return self.call("miIO.info")

    def get_properties(self, props: list[tuple[int, int]], did: str = "hg") -> dict[tuple[int, int], object]:
        out = {}
        for i in range(0, len(props), 8):  # устройства режут слишком длинные запросы
            chunk = props[i:i + 8]
            res = self.call("get_properties", [{"did": did, "siid": s, "piid": p} for s, p in chunk])
            for r in res or []:
                if r.get("code") == 0:
                    out[(r["siid"], r["piid"])] = r.get("value")
        return out

    def set_property(self, siid: int, piid: int, value, did: str = "hg") -> None:
        res = self.call("set_properties", [{"did": did, "siid": siid, "piid": piid, "value": value}])
        code = (res or [{}])[0].get("code", -1)
        if code not in (0, 1):
            raise MiioError(f"Устройство отклонило значение (код {code}) — возможно, сейчас так нельзя")

    def action(self, siid: int, aiid: int, args: list | None = None, did: str = "hg") -> None:
        res = self.call("action", {"did": did, "siid": siid, "aiid": aiid, "in": args or []})
        code = (res or {}).get("code", -1)
        if code not in (0, 1):
            raise MiioError(f"Устройство отклонило команду (код {code}) — возможно, сейчас так нельзя")
