import asyncio
import json
import time

try:
    import js
    from pyodide.ffi import to_js
    import pyodide
    WASM = True
except ImportError:
    WASM = False

class NetworkManager:
    def __init__(self):
        self.client_id = str(int(time.time() * 1000))[6:] + str(int(asyncio.get_event_loop().time() * 100) % 1000)
        self.topic = None
        self.last_sync = int(time.time())
        self.incoming_messages = []
        self.running = False

    def set_topic(self, topic):
        self.topic = "chess_app_multiplayer_" + str(topic)
        self.last_sync = int(time.time()) - 3
        if not self.running:
            self.running = True
            asyncio.ensure_future(self._poll_loop())

    async def send(self, data):
        if not self.topic:
            return
        data['sender'] = self.client_id
        url = "https://ntfy.sh/" + self.topic
        raw = json.dumps(data)

        if WASM:
            try:
                opts = to_js({"method": "POST", "body": raw}, dict_converter=js.Object.fromEntries)
                await js.fetch(url, opts)
            except Exception as e:
                print("WASM send error:", e)
        else:
            import threading, urllib.request
            def _send():
                try:
                    req = urllib.request.Request(url, data=raw.encode('utf-8'), method='POST')
                    urllib.request.urlopen(req, timeout=5)
                except Exception as e:
                    print("Send error:", e)
            threading.Thread(target=_send, daemon=True).start()

    async def _poll_loop(self):
        while self.running:
            if not self.topic:
                await asyncio.sleep(1)
                continue

            url = "https://ntfy.sh/" + self.topic + "/json?since=" + str(self.last_sync) + "&poll=1"

            try:
                if WASM:
                    resp = await js.fetch(url)
                    text = await resp.text()
                    lines = str(text).strip().split('\n')
                else:
                    import threading, urllib.request
                    result = []
                    def _fetch():
                        try:
                            req = urllib.request.Request(url)
                            with urllib.request.urlopen(req, timeout=5) as response:
                                result.append(response.read().decode('utf-8'))
                        except Exception:
                            pass
                    t = threading.Thread(target=_fetch, daemon=True)
                    t.start()
                    while t.is_alive():
                        await asyncio.sleep(0.1)
                    lines = result[0].strip().split('\n') if result else []

                for line in lines:
                    if line.strip():
                        try:
                            msg = json.loads(line)
                            if msg.get('event') == 'message':
                                if msg.get('id'):
                                    self.last_sync = msg['id']
                                content = json.loads(msg.get('message', '{}'))
                                if content.get('sender') != self.client_id:
                                    self.incoming_messages.append(content)
                        except Exception:
                            pass
            except Exception as e:
                print("Poll error:", e)

            await asyncio.sleep(1.5)

    def get_messages(self):
        res = list(self.incoming_messages)
        self.incoming_messages.clear()
        return res

net = NetworkManager()
