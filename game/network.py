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
        print(f"Network: Connecting to room {self.topic}...")
        
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
            import threading
            if not any(t.name == "NtfyListener" for t in threading.enumerate()):
                threading.Thread(target=self._listen_loop, name="NtfyListener", daemon=True).start()

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

    def _listen_loop(self):
        # Native streaming loop (one persistent connection, zero polling)
        import urllib.request
        retry_delay = 1
        
        while self.running:
            if not self.topic:
                time.sleep(1)
                continue

            url = f"https://ntfy.sh/{self.topic}/json"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=60) as response:
                    retry_delay = 1 # Reset on success
                    for line in response:
                        if not self.running: break
                        if line.strip():
                            try:
                                msg = json.loads(line.decode('utf-8'))
                                if msg.get('event') == 'message':
                                    content = json.loads(msg.get('message', '{}'))
                                    self.incoming_messages.append(content)
                            except Exception:
                                pass
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    print(f"Network: Rate limited. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)
                else:
                    time.sleep(1)
            except Exception:
                time.sleep(1) # General reconnect delay

    async def _poll_loop(self):
        # Legacy placeholder (no longer used, replaced by _listen_loop)
        pass

    def get_messages(self):
        res = list(self.incoming_messages)
        self.incoming_messages.clear()
        return res

net = NetworkManager()
