import asyncio
import sys
import json
import time
import base64
import urllib.parse
import sys
import os
import re
import urllib.request
import threading
from collections import deque

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
    js.eval('''
        // no Python callbacks here: a proxy per send would never be freed
        window._ntfy_blocked_until = 0;

        window.js_send_msg = function(url, raw) {
            var now = Date.now();
            if (now < window._ntfy_blocked_until) {
                var wait = ((window._ntfy_blocked_until - now) / 1000).toFixed(0);
                console.warn("Network: Send suppressed (rate-limited, " + wait + "s remaining).");
                return;
            }
            fetch(url, {
                method: "POST",
                body: raw,
            }).then(function(r) {
                if (r.status === 429) {
                    r.headers.get("Retry-After");
                    var backoff = 10;
                    try { backoff = Math.max(5, parseFloat(r.headers.get("Retry-After") || "10") || 10); } catch(e) {}
                    window._ntfy_blocked_until = Date.now() + backoff * 1000;
                    console.warn("Network: 429 Too Many Requests — backing off " + backoff + "s.");
                } else {
                    console.log("Network: Move Transmitted SUCCESS (Direct WASM).");
                }
            }).catch(function(e) { console.warn("Network: Send error (Direct WASM):", String(e)); });
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


SESSION_FILE = os.path.join(os.path.expanduser("~"), ".chess-playing-ai-session.json")  # desktop only
SESSION_MAX_AGE = 12 * 3600  # seconds; ntfy.sh keeps messages about this long
SEEN_IDS_KEPT = 200  # newest ntfy message ids remembered for deduplication
SEND_RATE_LIMIT_S = 5.0  # ntfy.sh free tier: ~1 message per 5 s; back off after a 429

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
        self._generation = 0  # bumped by set_topic; a listener from an older generation stops
        self._lock = threading.Lock()  # the native listener thread and the game loop share the queue and ids
        self.seen_ids = set()   # Track processed message IDs to avoid duplicates
        self._seen_order = deque()  # the same ids, oldest first, so the oldest are forgotten first
        self.server_time = 0  # latest ntfy server time of any message in the room, our own included

        self.server = "ntfy.sh"
        # the desktop game's relay; CHESS_NTFY_URL points it at another ntfy-compatible server (tools/e2e_online.py
        # runs two games against one of its own). The browser build always uses ntfy.sh (see JS_HELPERS).
        self.base_url = os.environ.get('CHESS_NTFY_URL', '').rstrip('/') or "https://" + self.server
        
        # Diagnostics
        self.msg_count = 0      # Total message events processed
        self.poll_count = 0     # How many successful polls made
        self.latency = 0        # Speed in ms
        self.poll_in_progress = False
        self.last_since = "2m"  # WASM default: catch last 2min of moves on join
        self.base_interval = 3.0 # Guerilla Polling Base (v12)
        self.current_interval = self.base_interval
        self.last_status = "IDLE"
        self._send_blocked_until = 0  # epoch seconds: a 429 response backs off until this time




    def set_topic(self, topic):
        """
        Set the ntfy topic and start listening.
        Safely tears down any existing listener before starting a new one.
        """
        # Stop any running listener first
        self.running = False
        self._generation += 1

        self.topic = "chess_app_multiplayer_" + roomName(topic)
        self.running = True
        with self._lock:
            self.seen_ids.clear()
            self._seen_order.clear()
            self.incoming_messages.clear()
            self.server_time = 0
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
                    if msg.get('event') == 'message' and self._accept(msg):
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
        Respects a 429 backoff: if ntfy returned Too Many Requests, messages are
        silently dropped until the Retry-After window has passed.
        """
        if not self.topic: return

        # honour the 429 backoff (native only; WASM fire-and-forget)
        if not WASM and time.time() < self._send_blocked_until:
            remaining = self._send_blocked_until - time.time()
            print(f"Network: Send suppressed (rate-limited, {remaining:.0f}s remaining).")
            return

        ntfy_url = f"{self.base_url}/{self.topic}"
        raw = json.dumps(data)
        
        if WASM:
            js.window.js_send_msg(ntfy_url, raw)
        else:
            def _send():
                try:
                    req = urllib.request.Request(ntfy_url, data=raw.encode('utf-8'), method='POST')
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        _ = resp.read()
                    print("Network: Transmission SUCCESS (Direct).")
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        retry_after = SEND_RATE_LIMIT_S
                        try:
                            retry_after = max(retry_after, float(e.headers.get('Retry-After', SEND_RATE_LIMIT_S)))
                        except (TypeError, ValueError):
                            pass
                        self._send_blocked_until = time.time() + retry_after
                        print(f"Network: 429 Too Many Requests — backing off {retry_after:.0f}s.")
                    else:
                        print("Network: Send error:", e)
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
        generation = self._generation  # a rejoin of the same room starts a new generation, so this thread stops
        while self.running and self._generation == generation:
            since = self.last_since
            url = f"{self.base_url}/{topic_snapshot}/json?since={since}"
            self.last_status = "CONNECTING"
            print(f"Network: Opening stream connection (since={since})...")
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/x-ndjson"})
                with urllib.request.urlopen(req, timeout=90) as response:
                    self.last_status = "SYNC HEALTHY"
                    self.poll_count += 1
                    for raw_line in response:
                        if not self.running or self._generation != generation:
                            break
                        raw_line = raw_line.strip()
                        if not raw_line:
                            continue
                        try:
                            msg = json.loads(raw_line.decode('utf-8'))
                            msg_id = msg.get('id')
                            # only 'message' events are stored by ntfy, so only their ids work as a 'since' cursor
                            if msg.get('event') != 'message' or not msg_id:
                                continue
                            self.last_since = msg_id  # reconnects continue from here instead of replaying
                            if self._accept(msg, generation):
                                self.msg_count += 1
                                print(f"Network: Received msg #{self.msg_count} (id={msg_id})")
                        except Exception as line_err:
                            print(f"Network: Failed to parse line: {line_err}")
            except Exception as conn_err:
                self.last_status = "RETRYING"
                print(f"Network: Stream error ({conn_err}), retrying in 3s...")
                time.sleep(3)
        print("Network: Native listener thread exited.")

    def _accept(self, msg, generation=None):
        """
        Queues the game message carried by an ntfy 'message' event, unless it was seen before or isn't
        a JSON object (the topic is public, so anything can arrive). Returns True when it was queued.
        """
        msg_id = msg.get('id')
        try:
            content = json.loads(msg.get('message') or '')
        except (ValueError, TypeError):
            print(f"Network: Ignoring a message that isn't JSON (id={msg_id})")
            return False
        if not isinstance(content, dict):
            print(f"Network: Ignoring a message that isn't a JSON object (id={msg_id})")
            return False
        with self._lock:
            if generation is not None and generation != self._generation:
                return False  # this listener belongs to a room that was left
            if msg_id:
                if msg_id in self.seen_ids:
                    return False
                self.seen_ids.add(msg_id)
                self._seen_order.append(msg_id)
                if len(self._seen_order) > SEEN_IDS_KEPT:
                    self.seen_ids.discard(self._seen_order.popleft())
            # when ntfy received it (server clock, seconds), so players can tell how recently the other sent
            # something without trusting each other's clocks; also replaces any '_time' the sender put in
            server_time = msg.get('time')
            content['_time'] = server_time if isinstance(server_time, (int, float)) else None
            if content['_time'] is not None:
                self.server_time = max(self.server_time, server_time)
            self.incoming_messages.append(content)
        return True

    def get_messages(self):
        with self._lock:
            res = self.incoming_messages
            self.incoming_messages = []
        return res

    def save_session(self, room, role, color=None):
        """
        Remembers the room and role (and the color last played: a rematch swaps it) so the player can rejoin after a
        page refresh or restart.
        """
        data = json.dumps({'room': room, 'role': role, 'color': color or ('w' if role == 'host' else 'b'),
                           'time': time.time()})
        try:
            if WASM:
                js.eval("localStorage.setItem('chess_ai_session', %s)" % json.dumps(data))
            else:
                with open(SESSION_FILE, "w") as f:
                    f.write(data)
        except Exception as e:
            print("Network: Could not save session -", e)

    def load_session(self):
        """
        Returns {'room', 'role'} of the last online game if it is recent enough to rejoin, else None.
        """
        try:
            if WASM:
                data = js.eval("localStorage.getItem('chess_ai_session') || ''")
            else:
                if not os.path.exists(SESSION_FILE):
                    return None
                with open(SESSION_FILE) as f:
                    data = f.read()
            session = json.loads(str(data)) if data else None
        except Exception as e:
            print("Network: Could not load session -", e)
            return None
        if not isinstance(session, dict) or session.get('role') not in ('host', 'client') or not session.get('room'):
            return None
        if time.time() - float(session.get('time', 0)) > SESSION_MAX_AGE:
            return None
        return session

def roomName(room):
    """
    The room code as it goes into the ntfy topic, which only allows letters, digits, - and _.
    """
    return re.sub(r'[^A-Z0-9_-]', '', str(room).strip().upper())


net = NetworkManager()
