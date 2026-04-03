import asyncio
import json
import time
import base64
import urllib.parse
import urllib.request
import threading

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

    def set_topic(self, topic):
        """
        Set the ntfy topic and start listening.
        """
        self.topic = "chess_app_multiplayer_" + str(topic).strip().upper()
        self.running = True
        self.seen_ids.clear()
        self.msg_count = 0
        self.poll_count = 0
        self.last_status = "INITIALIZING"
        print(f"Network: Connecting to room {self.topic}...")

        if WASM:
            if self._poll_task and not self._poll_task.done():
                self._poll_task.cancel()
            self._poll_task = asyncio.ensure_future(self._wasm_poll_loop())
        else:
            if not any(t.name == "NtfyListener" for t in threading.enumerate()):
                threading.Thread(target=self._listen_loop, name="NtfyListener", daemon=True).start()

    async def _wasm_poll_loop(self):
        """
        Polls ntfy via an internal Binary Tunnel (Base64) to ensure data integrity.
        Includes a persistent backend handshake retry for reliability.
        """
        # 1. Origin-Aware Paths (Essential for Vercel Routing)
        origin = str(js.window.location.origin)
        api_base = f"{origin}/api/sync"
        
        # 2. Resilient Handshake Retry Loop
        print(f"Network: Initiating handshake at {api_base}...")
        handshake_complete = False
        while not handshake_complete and self.running:
            self.last_status = "CONNECTING"
            try:
                handshake_res = await js.fetch(f"{api_base}?test=1")
                text = str(await handshake_res.text())
                if "SYNC_READY" in text:
                    print("Network: Internal Handshake SUCCESS. Tunnel is healthy.")
                    self.last_status = "SYNC READY"
                    handshake_complete = True
                else:
                    print(f"Network: Unexpected handshake response: {text[:50]}")
                    self.last_status = "RETRYING"
            except Exception as e:
                print(f"Network: Handshake Failed: {e}")
                self.last_status = f"GATE ERROR: {str(e)[:15]}"
            
            if not handshake_complete:
                await asyncio.sleep(2) # Wait before retry

        last_since = "2m"
        print("Network: WASM poll loop started (VIA BINARY TUNNEL).")

        while self.running and self.topic:
            try:
                # 1. Target ntfy URL
                ntfy_url = (
                    f"https://{self.server}/{self.topic}/json"
                    f"?poll=1&since={last_since}&t={time.time()}"
                )
                
                # 2. Binary Encoding (Base64)
                b64_url = base64.b64encode(ntfy_url.encode('utf-8')).decode('utf-8')
                proxy_url = f"{api_base}?url={urllib.parse.quote(b64_url)}"
                
                try:
                    response = await js.fetch(proxy_url)
                    status = response.status
                    
                    if status == 200:
                        text = str(await response.text())
                        self.last_status = "SYNC HEALTHY"
                    else:
                        print(f"Network: Server returned status {status}")
                        self.last_status = f"SYNC DELAY {status}"
                        await asyncio.sleep(2)
                        continue
                        
                except Exception as e:
                    print(f"Network: Fetch Exception: {e}")
                    self.last_status = "SYNC ERROR"
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
                                print(f"DEBUG: Move received at board layer: {content}")
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
        Sends move data via the tunnel (WASM) or direct (Native).
        """
        if not self.topic: return
        
        ntfy_url = f"https://{self.server}/{self.topic}"
        raw = json.dumps(data)
        
        if WASM:
            origin = str(js.window.location.origin)
            api_base = f"{origin}/api/sync"
            b64_url = base64.b64encode(ntfy_url.encode('utf-8')).decode('utf-8')
            proxy_url = f"{api_base}?url={urllib.parse.quote(b64_url)}"
            try:
                opts = to_js({
                    "method": "POST",
                    "body": raw,
                    "headers": {"Content-Type": "text/plain"}
                }, dict_converter=js.Object.fromEntries)
                
                print("Network: Transmitting move via binary tunnel...")
                response = await js.fetch(proxy_url, opts)
                if response.status == 200:
                    print("Network: Transmission SUCCESS (via Binary Tunnel).")
                else:
                    print(f"Network: Transmission failed (Status {response.status})")
            except Exception as e:
                print(f"Network: Transmit error: {e}")
        else:
            def _send():
                try:
                    req = urllib.request.Request(ntfy_url, data=raw.encode('utf-8'), method='POST')
                    urllib.request.urlopen(req, timeout=5)
                    print("Network: Transmission SUCCESS (Direct).")
                except Exception as e:
                    print("Network: Send error:", e)
            threading.Thread(target=_send, daemon=True).start()

    def _listen_loop(self):
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
                                    print(f"Network: Received direct msg")
                            except Exception: pass
            except Exception: time.sleep(2)

    def get_messages(self):
        res = list(self.incoming_messages)
        self.incoming_messages.clear()
        return res

net = NetworkManager()
