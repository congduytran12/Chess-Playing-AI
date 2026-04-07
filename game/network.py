import asyncio
import sys
import json
import time
import base64
import urllib.parse
import sys
import os
import urllib.request

WASM = False
try:
    import js
    import pyodide
    from pyodide.ffi import to_js, create_proxy
    WASM = True
except:
    if sys.platform == 'emscripten' or 'pyodide' in sys.modules:
        WASM = True
    else:
        WASM = False
        js = None

if WASM:
    # Helper to chain fetch().then(r => r.text()).then(cb) in JS to avoid await PromiseWrapper
    js.eval('''
        window.js_fetch_text = function(url, options, cb, eb) {
            fetch(url, options)
                .then(r => r.text())
                .then(t => cb(t))
                .catch(e => eb(String(e)));
        }
    ''')


print(f"DEBUG: sys.platform={sys.platform}, WASM={WASM}, modules={'js' in sys.modules}")
print("Network: v11.1 Loaded (Latency Fixed)")

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
        self.latency = 0        # Speed in ms
        self.poll_in_progress = False
        self.last_since = "2m"
        self.base_interval = 1.2
        self.current_interval = self.base_interval
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
            self._poll_task = asyncio.create_task(self._wasm_poll_loop())
        else:
            if not any(t.name == "NtfyListener" for t in threading.enumerate()):
                threading.Thread(target=self._listen_loop, name="NtfyListener", daemon=True).start()

    async def _wasm_poll_loop(self):
        """
        Polls ntfy via callback-based fetch to avoid PromiseWrapper issues.
        """
        origin = str(js.window.location.origin)
        api_base = f"{origin}/api/sync"
        
        def on_poll_success(text):
            self.poll_in_progress = False
            self.poll_count += 1
            self.last_status = "SYNC HEALTHY"
            # Reset backoff on success
            self.current_interval = self.base_interval
            if not text: return

            
            for line in str(text).strip().split('\n'):
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
                        self.last_since = msg_id
                        if msg.get('event') == 'message':
                            content = json.loads(msg.get('message', '{}'))
                            self.incoming_messages.append(content)
                            self.msg_count += 1
                except: pass

        def on_poll_error(err):
            self.poll_in_progress = False
            self.last_status = "SYNC ERROR"
            # Exponential Backoff on error (Rate Limit fix v10)
            self.current_interval = min(self.current_interval * 2, 15.0)
            print(f"Network: Poll Error (Backing off to {self.current_interval:.1f}s): {err}")

        success_proxy = create_proxy(on_poll_success)
        error_proxy = create_proxy(on_poll_error)

        print("Network: Starting Isolated Messaging Tunnel (Adaptive)...")

        while self.running and self.topic:
            if not self.poll_in_progress:
                self.poll_in_progress = True
                # Topic-Based Request (v8+)
                proxy_url = f"{api_base}?topic={self.topic}&since={self.last_since}"
                js.window.js_fetch_text(proxy_url, to_js({}), success_proxy, error_proxy)
            
            await asyncio.sleep(self.current_interval)


            
        success_proxy.destroy()
        error_proxy.destroy()

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
            proxy_url = f"{api_base}?topic={self.topic}"
            
            def on_send_success(text):
                print("Network: Move Transmitted SUCCESS.")
            def on_send_error(err):
                print(f"Network: Send error: {err}")
            
            s_proxy = create_proxy(on_send_success)
            e_proxy = create_proxy(on_send_error)
            
            options = to_js({
                "method": "POST",
                "body": raw,
                "headers": {"Content-Type": "text/plain"}
            })
            
            js.window.js_fetch_text(proxy_url, options, s_proxy, e_proxy)






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
                                    print(f"Network: Local Received msg")
                            except Exception: pass
            except Exception: time.sleep(2)

    def get_messages(self):
        res = list(self.incoming_messages)
        self.incoming_messages.clear()
        return res

net = NetworkManager()
