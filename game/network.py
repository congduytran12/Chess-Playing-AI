import asyncio
import sys
import json
import time
import base64
import urllib.parse
import sys
import os
import urllib.request
import threading

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

        window.start_ntfy_sse = function(topic, since, cb, eb) {
            if (window.__ntfy_es) {
                window.__ntfy_es.close();
            }
            const url = `https://ntfy.sh/${topic}/sse?since=${since}`;
            window.__ntfy_es = new EventSource(url);
            window.__ntfy_es.onmessage = (e) => {
                cb(e.data);
            };
            window.__ntfy_es.onerror = (e) => {
                eb("SSE Error or Reconnecting");
            };
        }

        window.stop_ntfy_sse = function() {
            if (window.__ntfy_es) {
                window.__ntfy_es.close();
                window.__ntfy_es = null;
            }
        }
    ''')


print(f"DEBUG: sys.platform={sys.platform}, WASM={WASM}, modules={'js' in sys.modules}")
print("Network: v13.0 Loaded (Proxy-Unified)")

class NetworkManager:
    def __init__(self):
        self.topic = None
        self.incoming_messages = []
        self.running = False
        self._sse_cb = None
        self._sse_eb = None
        self._listener_thread = None  # native background thread
        self.seen_ids = set()   # Track processed message IDs to avoid duplicates
        
        self.server = "ntfy.sh"
        
        # Diagnostics
        self.msg_count = 0      # Total message events processed
        self.poll_count = 0     # How many successful polls made
        self.latency = 0        # Speed in ms
        self.poll_in_progress = False
        self.last_since = "2m"  # WASM default: catch last 2min of moves on join
        self.base_interval = 3.0 # Guerilla Polling Base (v12)
        self.current_interval = self.base_interval
        self.last_status = "IDLE"




    def set_topic(self, topic):
        """
        Set the ntfy topic and start listening.
        Safely tears down any existing listener before starting a new one.
        """
        # Stop any running listener first
        self.running = False
        
        self.topic = "chess_app_multiplayer_" + str(topic).strip().upper()
        self.running = True
        self.seen_ids.clear()
        self.incoming_messages.clear()
        self.msg_count = 0
        self.poll_count = 0
        self.last_since = "30m"  # wide window so late-joining clients catch all moves
        self.last_status = "INITIALIZING"
        print(f"Network: Connecting to room {self.topic}...")

        if WASM:
            js.window.stop_ntfy_sse()
            if self._sse_cb: self._sse_cb.destroy()
            if self._sse_eb: self._sse_eb.destroy()
            
            def on_sse_msg(data):
                if not self.running: return
                self.msg_count += 1
                try:
                    msg = json.loads(data)
                    msg_id = msg.get('id')
                    if msg_id and msg_id not in self.seen_ids:
                        self.seen_ids.add(msg_id)
                        if len(self.seen_ids) > 200:
                            self.seen_ids = set(sorted(list(self.seen_ids))[100:])
                        if msg.get('event') == 'message':
                            content = json.loads(msg.get('message', '{}'))
                            self.incoming_messages.append(content)
                            print(f"Network: WASM received msg #{self.msg_count} id={msg_id}")
                except Exception as e:
                    print(f"Network: SSE Parse error - {e}")
                    
            def on_sse_err(err):
                if not self.running: return
                self.last_status = "SYNC RECONNECTING"
                
            self._sse_cb = create_proxy(on_sse_msg)
            self._sse_eb = create_proxy(on_sse_err)
            
            print("Network: Starting Direct SSE Connection...")
            self.last_status = "SYNC HEALTHY"
            js.window.start_ntfy_sse(self.topic, self.last_since, self._sse_cb, self._sse_eb)
        else:
            # Always start a fresh thread; old one will exit because self.running was set to False
            t = threading.Thread(target=self._listen_loop, name="NtfyListener", daemon=True)
            self._listener_thread = t
            t.start()

    async def send(self, data):

        """
        Sends move data via the tunnel (WASM) or direct (Native).
        """
        if not self.topic: return
        
        ntfy_url = f"https://{self.server}/{self.topic}"
        raw = json.dumps(data)
        
        if WASM:
            def on_send_success(text):
                print("Network: Move Transmitted SUCCESS (Direct WASM).")
            def on_send_error(err):
                print(f"Network: Send error (Direct WASM): {err}")
            
            s_proxy = create_proxy(on_send_success)
            e_proxy = create_proxy(on_send_error)
            
            options = to_js({
                "method": "POST",
                "body": raw,
                "headers": {"Content-Type": "text/plain"} 
            })
            
            js.window.js_fetch_text(ntfy_url, options, s_proxy, e_proxy)
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
        """
        Native Python streaming listener for ntfy.sh.
        Uses ?since= to avoid replaying old messages after reconnects.
        Implements seen_ids deduplication so duplicate deliveries are ignored.
        """
        print("Network: Native listener thread started.")
        topic_snapshot = self.topic  # capture topic at thread start
        while self.running and self.topic == topic_snapshot:
            since = self.last_since
            url = f"https://{self.server}/{topic_snapshot}/json?since={since}"
            self.last_status = "CONNECTING"
            print(f"Network: Opening stream connection (since={since})...")
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/x-ndjson"})
                with urllib.request.urlopen(req, timeout=90) as response:
                    self.last_status = "SYNC HEALTHY"
                    self.poll_count += 1
                    for raw_line in response:
                        if not self.running or self.topic != topic_snapshot:
                            break
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            msg = json.loads(raw_line.decode('utf-8'))
                            msg_id = msg.get('id')
                            # Advance 'since' cursor so reconnects don't replay
                            if msg_id:
                                self.last_since = msg_id
                                if msg_id in self.seen_ids:
                                    continue
                                self.seen_ids.add(msg_id)
                                # Keep seen_ids bounded
                                if len(self.seen_ids) > 200:
                                    sorted_ids = sorted(self.seen_ids)
                                    self.seen_ids = set(sorted_ids[100:])
                            if msg.get('event') == 'message':
                                try:
                                    content = json.loads(msg.get('message', '{}'))
                                    self.incoming_messages.append(content)
                                    self.msg_count += 1
                                    print(f"Network: Received msg #{self.msg_count} (id={msg_id})")
                                except Exception as parse_err:
                                    print(f"Network: Failed to parse message body: {parse_err}")
                        except Exception as line_err:
                            print(f"Network: Failed to parse line: {line_err}")
            except Exception as conn_err:
                self.last_status = "RETRYING"
                print(f"Network: Stream error ({conn_err}), retrying in 3s...")
                time.sleep(3)
        print("Network: Native listener thread exited.")

    def get_messages(self):
        res = list(self.incoming_messages)
        self.incoming_messages.clear()
        return res

net = NetworkManager()
