import asyncio
import json
import time
import urllib.request

try:
    import js
    WASM = True
except ImportError:
    WASM = False

class NetworkManager:
    def __init__(self):
        self.topic = None
        self.last_sync = int(time.time())
        self.incoming_messages = []
        self.running = False
        
    def set_topic(self, topic):
        self.topic = "chess_app_multiplayer_" + str(topic)
        self.last_sync = int(time.time()) - 3  # Start listening from slightly in the past
        self.running = True
        asyncio.create_task(self._poll_loop())

    async def send(self, data):
        if not self.topic: return
        url = f"https://ntfy.sh/{self.topic}"
        raw = json.dumps(data)
        
        if WASM:
            options = js.Object.new()
            options.method = "POST"
            options.body = raw
            # Fire and forget
            js.fetch(url, options)
        else:
            # use a thread to not block local async loop
            import threading
            def _send():
                req = urllib.request.Request(url, data=raw.encode('utf-8'), method='POST')
                try: urllib.request.urlopen(req, timeout=5)
                except Exception as e: print("Send error:", e)
            threading.Thread(target=_send, daemon=True).start()

    async def _poll_loop(self):
        while self.running:
            if not self.topic:
                await asyncio.sleep(1)
                continue
            
            url = f"https://ntfy.sh/{self.topic}/json?since={self.last_sync}&poll=1"
            
            try:
                if WASM:
                    resp = await js.fetch(url)
                    text = await resp.text()
                    lines = str(text).strip().split('\n')
                else:
                    import threading
                    result = []
                    def _fetch():
                        try:
                            req = urllib.request.Request(url)
                            with urllib.request.urlopen(req, timeout=5) as response:
                                result.append(response.read().decode('utf-8'))
                        except Exception as e:
                            pass
                    t = threading.Thread(target=_fetch, daemon=True)
                    t.start()
                    while t.is_alive():
                        await asyncio.sleep(0.1)
                    if result:
                        lines = result[0].strip().split('\n')
                    else:
                        lines = []

                for line in lines:
                    if line:
                        msg = json.loads(line)
                        if msg.get('event') == 'message':
                            if msg.get('time'):
                                self.last_sync = max(self.last_sync, msg['time'] + 1)
                            try:
                                content = json.loads(msg.get('message', '{}'))
                                self.incoming_messages.append(content)
                            except Exception as e:
                                pass
            except Exception as e:
                pass
                
            await asyncio.sleep(1)

    def get_messages(self):
        res = list(self.incoming_messages)
        self.incoming_messages.clear()
        return res

net = NetworkManager()
