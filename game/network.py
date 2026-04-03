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
        Polls ntfy.sh via an internal Vercel Proxy to avoid CORS and ad-blockers.
        """
        last_since = "2m"
        print("Network: WASM poll loop started (VIA VERCEL GATEWAY).")

        while self.running and self.topic:
            try:
                # 1. Target URL
                ntfy_url = (
                    f"https://{self.server}/{self.topic}/json"
                    f"?poll=1&since={last_since}&t={time.time()}"
                )
                
                # 2. Gate to Vercel Gateway (Internal)
                # Since this is the SAME ORIGIN, ad-blockers will not block it.
                proxy_url = f"/api/sync?url={urllib.parse.quote(ntfy_url)}"
                
                try:
                    # Use standard fetch- same origin needs no complex options
                    response = await js.fetch(proxy_url)
                    status = response.status
                    
                    if status == 200:
                        text = str(await response.text())
                        self.last_status = "GATEWAY OK"
                    else:
                        print(f"Network: Gateway returned status {status}")
                        self.last_status = f"GATE ERROR {status}"
                        await asyncio.sleep(2)
                        continue
                        
                except Exception as e:
                    print(f"Network: Fetch Exception (Gateway): {e}")
                    self.last_status = "GATE ERROR"
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
        Sends move data via the internal Vercel Gateway to bypass client-side blockers.
        """
        if not self.topic: return
        
        ntfy_url = f"https://{self.server}/{self.topic}"
        proxy_url = f"/api/sync?url={urllib.parse.quote(ntfy_url)}"
        raw = json.dumps(data)
        
        if WASM:
            try:
                # Use standard fetch to send the move to the gateway
                opts = to_js({
                    "method": "POST",
                    "body": raw,
                    "headers": {"Content-Type": "text/plain"}
                }, dict_converter=js.Object.fromEntries)
                
                print("Network: Transmitting move via Vercel Gateway...")
                response = await js.fetch(proxy_url, opts)
                if response.status == 200:
                    print("Network: Gateway Transmission successful.")
                else:
                    print(f"Network: Gateway Transmission status {response.status}")
            except Exception as e:
                print(f"Network: Gateway Transmit error: {e}")
        else:
            import threading, urllib.request
            def _send():
                try:
                    req = urllib.request.Request(ntfy_url, data=raw.encode('utf-8'), method='POST')
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
