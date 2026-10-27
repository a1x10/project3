"""Имитация Xiaomi-стиралки по протоколу miIO (UDP) для тестов и демо."""
import hashlib
import json
import socket
import struct
import threading
from pathlib import Path

sys_path = str(Path(__file__).resolve().parent.parent)
import sys
sys.path.insert(0, sys_path)
from homeguard import miio  # noqa: E402

DEVICE_ID = b"\x00\x00\x30\x39"


class Washer:
    def __init__(self):
        self.props = {(2, 1): True, (2, 2): 1, (2, 3): 1, (2, 4): 0, (2, 5): 2, (2, 6): 2, (2, 7): 4,
                      (2, 8): 0, (2, 9): 0, (2, 10): 0, (4, 1): False, (3, 1): 0, (3, 3): 0, (3, 4): True,
                      (3, 5): False, (3, 6): 0, (3, 7): True, (5, 1): 0}
        self.actions: list[tuple[int, int]] = []


def serve(washer: Washer, token_hex: str, model: str = "mibx2.washer.v1", port: int = 0):
    token = bytes.fromhex(token_hex)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    sock.settimeout(0.2)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            if data == miio.HELLO:
                head = struct.pack(">HH4s4sI", 0x2131, 32, b"\0" * 4, DEVICE_ID, 1000)
                sock.sendto(head + b"\xff" * 16, addr)
                continue
            if hashlib.md5(data[:16] + token + data[32:]).digest() != data[16:32]:
                continue  # неверный токен — устройство молчит, как настоящее
            req = json.loads(miio.decrypt(token, data[32:]).rstrip(b"\0"))
            m, p = req["method"], req["params"]
            if m == "miIO.info":
                res = {"model": model, "fw_ver": "1.0.0"}
            elif m == "get_properties":
                res = [{"did": x["did"], "siid": x["siid"], "piid": x["piid"], "code": 0,
                        "value": washer.props[(x["siid"], x["piid"])]} if (x["siid"], x["piid"]) in washer.props
                       else {"did": x["did"], "siid": x["siid"], "piid": x["piid"], "code": -4001} for x in p]
            elif m == "set_properties":
                for x in p:
                    washer.props[(x["siid"], x["piid"])] = x["value"]
                res = [{"did": x["did"], "siid": x["siid"], "piid": x["piid"], "code": 0} for x in p]
            elif m == "action":
                washer.actions.append((p["siid"], p["aiid"]))
                if (p["siid"], p["aiid"]) == (2, 1):
                    washer.props[(2, 2)] = 3
                    washer.props[(2, 10)] = 55
                res = {"code": 0, "did": p["did"], "out": []}
            else:
                payload = {"id": req["id"], "error": {"code": -9999, "message": "user ack timeout"}}
                sock.sendto(miio.build_packet(token, DEVICE_ID, 1001, json.dumps(payload).encode()), addr)
                continue
            payload = json.dumps({"id": req["id"], "result": res}).encode()
            sock.sendto(miio.build_packet(token, DEVICE_ID, 1001, payload), addr)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    class Handle:
        port = sock.getsockname()[1]

        @staticmethod
        def close():
            stop.set()
            thread.join()
            sock.close()
    return Handle


if __name__ == "__main__":
    h = serve(Washer(), "00112233445566778899aabbccddeeff", port=54399)
    print("fake washer on UDP 54399, token 00112233445566778899aabbccddeeff")
    threading.Event().wait()
