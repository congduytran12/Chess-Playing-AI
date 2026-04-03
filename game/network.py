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
        self.incoming_messages = []
        self.running = False
        self._poll_task = None  # asyncio background task (WASM only)
        self.seen_ids = set()   # Track processed message IDs to avoid duplicates
        
        # Messaging Servers (Rotation for CORS Failover)
        self.servers = ["ntfy.sh", "ntfy.net"]
        self.server_idx = 0
        
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
        self.topic = "chess_app_multiplayer_" + str(topic).strip().upper()
        self.running = True
        self.seen_ids.clear()
        self.msg_count = 0
        self.poll_count = 0
        self.last_status = "CONNECTING"
        print(f"Network: Connecting to room {self.topic}...")
        print(f"DEBUG: Initial Server: {self.servers[self.server_idx]}")

        if WASM:
            if self._poll_task and not self._poll_task.done():
                self._poll_task.cancel()
            self._poll_task = asyncio.ensure_future(self._wasm_poll_loop())
        else:
            import threading
            if not any(t.name == "NtfyListener" for t in threading.enumerate()):
                threading.Thread(target=self._listen_loop, name="NtfyListener", daemon=True).start()

    async def _wasm_poll_loop(self):
        last_since = "2m"
        retry_delay = 1.5
        print("Network: WASM poll loop started.")

        while self.running and self.topic:
            try:
                server = self.servers[self.server_idx]
                url = (
                    f"https://{server}/{self.topic}/json"
                    f"?poll=1&since={last_since}&t={time.time()}"
                )
                
                # Use absolute simplest fetch to avoid CORS pre-flight
                # No headers, mode: cors, cache: no-store
                opts = to_js({
                    "method": "GET",
                    "mode": "cors",
                    "cache": "no-store",
                    "credentials": "omit"
                }, dict_converter=js.Object.fromEntries)
                
                try:
                    response = await js.fetch(url, opts)
                    status = response.status
                except Exception as e:
                    # In some environments, a CORS block results in a generic Type Error
                    print(f"Network: Fetch Exception (Likely CORS Block): {e}")
                    status = 0
                
                self.last_status = f"HTTP {status}"

                if status == 0 or (status >= 400 and status != 429):
                    self.server_idx = (self.server_idx + 1) % len(self.servers)
                    print(f"Network: Status {status}. Switching to backup server: {self.servers[self.server_idx]}")
                    self.last_status = "SWITCHING"
                    await asyncio.sleep(2)
                    continue

                if status == 429:
                    self.last_status = "RATE-LIMIT"
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)
                    continue

                self.poll_count += 1
                retry_delay = 1.5
                text = str(await response.text())
                
                if text.strip():
                    print(f"DEBUG: Raw Network Receive ({server}): {text.strip()}")
                
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
                    except Exception: pass

            except asyncio.CancelledError: break
            except Exception as e:
                print(f"Network: Poll loop error: {e}")
                self.last_status = "ERROR"

            await asyncio.sleep(1.5)

    async def send(self, data):
        if not self.topic: return
        
        server = self.servers[self.server_idx]
        url = f"https://{server}/{self.topic}"
        raw = json.dumps(data)
        
        if WASM:
            try:
                # Use simple POST with no custom headers to bypass CORS pre-flight
                opts = to_js({
                    "method": "POST",
                    "body": raw,
                    "mode": "cors",
                    "credentials": "omit"
                }, dict_converter=js.Object.fromEntries)
                
                print(f"Network: Transmitting move to {server}...")
                response = await js.fetch(url, opts)
                if response.status == 200:
                    print("Network: Transmission successful.")
                else:
                    print(f"Network: Transmission status {response.status}")
            except Exception as e:
                print(f"Network: Transmit error: {e}")
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
            server = self.servers[self.server_idx]
            url = f"https://{server}/{self.topic}/json"
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
