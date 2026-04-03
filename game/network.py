import asyncio
import json
import time
import urllib.parse

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
        self.incoming_messages = []
        self.running = False
        self._poll_task = None  # asyncio background task (WASM only)
        self.seen_ids = set()   # Track processed message IDs to avoid duplicates
        
        self.server = "ntfy.sh"
        
        # Diagnostics
        self.msg_count = 0      # Total message events processed
        self.poll_count = 0     # How many successful polls made
        self.last_status = "IDLE"

        # Native SSE (non-WASM only)
        self.source = None
        self.proxy = None

    def set_topic(self, topic):
        """
        Set the ntfy topic and start listening.
        """
        self.topic = "multiplayer_" + str(topic).strip().upper()
        self.running = True
        self.seen_ids.clear()
        self.msg_count = 0
        self.poll_count = 0
        self.last_status = "CONNECTING"
        print(f"Network: Connecting to room {self.topic}...")

        if WASM:
            if self._poll_task and not self._poll_task.done():
                self._poll_task.cancel()
            self._poll_task = asyncio.ensure_future(self._wasm_poll_loop())
        else:
            import threading
            if not any(t.name == "NtfyListener" for t in threading.enumerate()):
                threading.Thread(target=self._listen_loop, name="NtfyListener", daemon=True).start()

    async def _wasm_poll_loop(self):
        """
        Polls ntfy.sh using a CORS Proxy to bypass browser security restrictions.
        """
        last_since = "2m"
        print("Network: WASM poll loop started (VIA PROXY).")

        while self.running and self.topic:
            try:
                # 1. Construct the target ntfy URL
                ntfy_url = (
                    f"https://{self.server}/{self.topic}/json"
                    f"?poll=1&since={last_since}&t={time.time()}"
                )
                
                # 2. Wrap it in the AllOrigins CORS Proxy
                # This bypasses the No 'Access-Control-Allow-Origin' header error.
                proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(ntfy_url)}"
                
                try:
                    # Simple GET with no custom headers to keep it as a 'Simple Request'
                    response = await js.fetch(proxy_url)
                    status = response.status
                    
                    if status == 200:
                        # AllOrigins returns the ntfy response in the 'contents' field
                        wrapper = await response.json()
                        text = str(wrapper.contents)
                        self.last_status = "API OK"
                    else:
                        print(f"Network: Proxy returned status {status}")
                        self.last_status = f"PROXY ERROR {status}"
                        await asyncio.sleep(2)
                        continue
                        
                except Exception as e:
                    print(f"Network: Fetch Exception (Proxy): {e}")
                    self.last_status = "FETCH ERROR"
                    await asyncio.sleep(2)
                    continue
                
                self.poll_count += 1
                
                if not text.strip():
                    await asyncio.sleep(1.5)
                    continue

                for line in text.strip().split('\n'):
                    line = line.strip()
                    if not line: continue
                    try:
                        msg = json.loads(line)
                        msg_id = msg.get('id')
                        if msg_id and msg_id not in self.seen_ids:
                            self.seen_ids.add(msg_id)
                            if len(self.seen_ids) > 200:
                                sorted_ids = sorted(list(self.seen_ids))
                                self.seen_ids = set(sorted_ids[100:])
                            last_since = msg_id
                            if msg.get('event') == 'message':
                                content = json.loads(msg.get('message', '{}'))
                                self.incoming_messages.append(content)
                                self.msg_count += 1
                                print(f"Network: Received msg ID {msg_id}")
                    except Exception: pass

            except asyncio.CancelledError: break
            except Exception as e:
                print(f"Network: Poll loop error: {e}")
                self.last_status = "ERROR"

            await asyncio.sleep(1.5)

    async def send(self, data):
        """
        Sends move data using navigator.sendBeacon() to bypass CORS.
        """
        if not self.topic: return
        
        url = f"https://{self.server}/{self.topic}"
        raw = json.dumps(data)
        
        if WASM:
            try:
                # navigator.sendBeacon is 'fire-and-forget' and bypasses CORS pre-flight.
                # It is designed specifically for background telemetry and cross-origin tasks.
                success = js.navigator.sendBeacon(url, raw)
                if success:
                    print("Network: Message queued for transmit (via Beacon).")
                else:
                    print("Network: Beacon failed to queue.")
            except Exception as e:
                print(f"Network: Beacon error: {e}")
        else:
            import threading, urllib.request
            def _send():
                try:
                    req = urllib.request.Request(url, data=raw.encode('utf-8'), method='POST')
                    urllib.request.urlopen(req, timeout=5)
                except Exception: pass
            threading.Thread(target=_send, daemon=True).start()

    def _listen_loop(self):
        import urllib.request
        while self.running:
            if not self.topic:
                time.sleep(1)
                continue
            url = f"https://{self.server}/{self.topic}/json"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=60) as response:
                    for line in response:
                        if not self.running: break
                        if line.strip():
                            try:
                                msg = json.loads(line.decode('utf-8'))
                                if msg.get('event') == 'message':
                                    content = json.loads(msg.get('message', '{}'))
                                    self.incoming_messages.append(content)
                                    self.msg_count += 1
                            except Exception: pass
            except Exception: time.sleep(2)

    def get_messages(self):
        res = list(self.incoming_messages)
        self.incoming_messages.clear()
        return res

net = NetworkManager()
