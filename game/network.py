import asyncio
import json
import time

try:
    import js
    from pyodide.ffi import to_js, create_proxy
    import pyodide
    WASM = True
except ImportError:
    WASM = False

class NetworkManager:
    def __init__(self):
        self.topic = None
        self.last_sync = int(time.time())
        self.incoming_messages = []
        self.running = False
        self.source = None
        self.proxy = None

    def set_topic(self, topic):
        self.topic = "chess_app_multiplayer_" + str(topic)
        self.last_sync = int(time.time()) - 3
        self.running = True
        
        if WASM:
            if self.source:
                self.source.close()
            if self.proxy:
                self.proxy.destroy()
            
            url = "https://ntfy.sh/" + self.topic + "/sse"
            self.source = js.EventSource.new(url)
            self.proxy = create_proxy(self._handle_message)
            self.source.onmessage = self.proxy
        else:
            asyncio.ensure_future(self._poll_loop())

    def _handle_message(self, event):
        try:
            msg = json.loads(event.data)
            # ntfy SSE sends JSON objects with event, message, etc.
            if msg.get('event') == 'message':
                content = json.loads(msg.get('message', '{}'))
                self.incoming_messages.append(content)
        except Exception as e:
            print("SSE message error:", e)

    async def send(self, data):
        if not self.topic:
            return
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
        # Native polling loop (only for non-WASM)
        while self.running and not WASM:
            if not self.topic:
                await asyncio.sleep(1)
                continue

            url = "https://ntfy.sh/" + self.topic + "/json?since=" + str(self.last_sync) + "&poll=1"

            try:
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
                    await asyncio.sleep(0.05)
                lines = result[0].strip().split('\n') if result else []

                for line in lines:
                    if line.strip():
                        try:
                            msg = json.loads(line)
                            if msg.get('event') == 'message':
                                if msg.get('time'):
                                    self.last_sync = max(self.last_sync, msg['time'] + 1)
                                content = json.loads(msg.get('message', '{}'))
                                self.incoming_messages.append(content)
                        except Exception:
                            pass
            except Exception as e:
                print("Poll error:", e)

            await asyncio.sleep(0.1)  # Faster polling for native

    def get_messages(self):
        res = list(self.incoming_messages)
        self.incoming_messages.clear()
        return res

net = NetworkManager()
