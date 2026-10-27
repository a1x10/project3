"""Имитация Sony Bravia REST API для тестов и демо."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PSK = "1234"


class State:
    power = True
    volume = 12
    mute = False
    input = "extInput:hdmi?port=1"
    app = None
    pressed: list[str] = []


def make_state():
    s = State()
    s.pressed = []
    return s


def serve(state: State, port: int = 0):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.headers.get("X-Auth-PSK") != PSK:
                return self._send({}, 403)
            if self.path == "/sony/IRCC":
                state.pressed.append(body.decode().split("<IRCCCode>")[1].split("</IRCCCode>")[0])
                return self._send({})
            req = json.loads(body)
            m, p = req["method"], (req["params"] or [{}])[0]
            ok = {"id": req["id"], "result": [{}]}
            if m == "getSystemInformation":
                ok["result"] = [{"model": "KD-55X80J", "name": "BRAVIA"}]
            elif m == "getPowerStatus":
                ok["result"] = [{"status": "active" if state.power else "standby"}]
            elif m == "setPowerStatus":
                state.power = p["status"]
            elif not state.power and m not in ("getRemoteControllerInfo",):
                return self._send({"id": 1, "error": [7, "Illegal State"]})
            elif m == "getVolumeInformation":
                ok["result"] = [[{"target": "speaker", "volume": state.volume, "mute": state.mute,
                                  "maxVolume": 100, "minVolume": 0}]]
            elif m == "setAudioVolume":
                state.volume = int(p["volume"])
            elif m == "setAudioMute":
                state.mute = p["status"]
            elif m == "getCurrentExternalInputsStatus":
                ok["result"] = [[{"uri": "extInput:hdmi?port=1", "title": "HDMI 1", "connection": True},
                                 {"uri": "extInput:hdmi?port=2", "title": "HDMI 2", "connection": False}]]
            elif m == "setPlayContent":
                state.input = p["uri"]
            elif m == "getApplicationList":
                ok["result"] = [[{"uri": "com.sony.dtv.com.google.android.youtube.tv", "title": "YouTube"},
                                 {"uri": "com.sony.dtv.com.netflix.ninja", "title": "Netflix"}]]
            elif m == "setActiveApp":
                state.app = p["uri"]
            elif m == "getPlayingContentInfo":
                ok["result"] = [{"title": "Фильм", "source": state.input, "uri": state.input}]
            elif m == "getRemoteControllerInfo":
                ok["result"] = [{"bundled": True}, [{"name": n, "value": f"AAA-{n}"} for n in
                                ["Up", "Down", "Left", "Right", "Confirm", "Return", "Home", "Options",
                                 "Play", "Pause", "Prev", "Next", "ChannelUp", "ChannelDown", "VolumeUp"]]]
            else:
                return self._send({"id": 1, "error": [12, "not implemented"]})
            self._send(ok)

    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    srv = serve(make_state(), 8099)
    print("fake bravia on 8099, PSK", PSK)
    threading.Event().wait()
