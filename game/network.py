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
        
        # Diagnostics
        self.msg_count = 0      # Total message events processed
        self.poll_count = 0     # How many successful polls made
        self.last_status = "IDLE"

        # Native SSE (non-WASM only)
        self.source = None
        self.proxy = None

    def set_topic(self, topic):
        """
        Set the ntfy.sh topic and start listening.
        In WASM: schedules a non-blocking async poll loop and returns immediately.
        In native: starts a background SSE listener thread.
        """
        self.topic = "chess_app_multiplayer_" + str(topic).strip().upper()
        self.running = True
        self.seen_ids.clear()
        self.msg_count = 0
        self.poll_count = 0
        self.last_status = "CONNECTING"
        print(f"Network: Connecting to room {self.topic}...")

        if WASM:
            # Cancel any previous poll task
            if self._poll_task and not self._poll_task.done():
                self._poll_task.cancel()
            # Schedule the poll loop as a background asyncio task.
            self._poll_task = asyncio.ensure_future(self._wasm_poll_loop())
        else:
            import threading
            if not any(t.name == "NtfyListener" for t in threading.enumerate()):
                threading.Thread(
                    target=self._listen_loop,
                    name="NtfyListener",
                    daemon=True
                ).start()

    # ------------------------------------------------------------------
    # WASM: async polling loop (runs as a background asyncio task)
    # ------------------------------------------------------------------
    async def _wasm_poll_loop(self):
        """
        Polls ntfy.sh using js.fetch.
        Uses message IDs for 'since' parameter to avoid clock skew issues.
        """
        # Start by fetching recently cached messages (last 2 minutes)
        # to ensure no moves are missed during join.
        last_since = "2m"
        retry_delay = 1.5
        print("Network: WASM poll loop started.")

        while self.running and self.topic:
            try:
                # Add cache-busting timestamp 't' to the URL
                url = (
                    f"https://ntfy.sh/{self.topic}/json"
                    f"?poll=1&since={last_since}&t={time.time()}"
                )
                
                opts = to_js({"method": "GET"}, dict_converter=js.Object.fromEntries)
                response = await js.fetch(url, opts)
                status = response.status
                self.last_status = f"HTTP {status}"

                if status == 429:
                    print(f"Network: Rate limited. Retrying in {retry_delay}s...")
                    self.last_status = "RATE-LIMIT"
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)
                    continue

                if status != 200:
                    print(f"Network: Poll failed with status {status}")
                    await asyncio.sleep(2)
                    continue

                self.poll_count += 1
                retry_delay = 1.5
                text = str(await response.text())
                
                if not text.strip():
                    await asyncio.sleep(1.5)
                    continue

                for line in text.strip().split('\n'):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        msg_id = msg.get('id')
                        
                        # Process only new message events
                        if msg_id and msg_id not in self.seen_ids:
                            self.seen_ids.add(msg_id)
                            # Keep seen_ids from growing infinitely
                            if len(self.seen_ids) > 200:
                                sorted_ids = sorted(list(self.seen_ids))
                                self.seen_ids = set(sorted_ids[100:])
                            
                            # Update 'since' to the latest ID we've seen
                            last_since = msg_id
                            
                            if msg.get('event') == 'message':
                                content = json.loads(msg.get('message', '{}'))
                                self.incoming_messages.append(content)
                                self.msg_count += 1
                                print(f"Network: Received msg ID {msg_id}")
                    except Exception as e:
                        print(f"Network: Msg parse error: {e}")

            except asyncio.CancelledError:
                print("Network: Poll loop cancelled.")
                break
            except Exception as e:
                print(f"Network: Poll loop error: {e}")
                self.last_status = "ERROR"

            # Wait before next poll
            await asyncio.sleep(1.5)

        print("Network: WASM poll loop stopped.")
        self.last_status = "STOPPED"

    # ------------------------------------------------------------------
    # Shared: send a message
    # ------------------------------------------------------------------
    async def send(self, data):
        if not self.topic:
            return

        url = "https://ntfy.sh/" + self.topic
        raw = json.dumps(data)
        print(f"Network: Transmitting to {self.topic}...")

        if WASM:
            try:
                opts = to_js(
                    {"method": "POST", "body": raw},
                    dict_converter=js.Object.fromEntries
                )
                response = await js.fetch(url, opts)
                if response.status == 200:
                    print(f"Network: Message successfully transmitted.")
                else:
                    print(f"Network: Transmission failed (Status {response.status}).")
            except Exception as e:
                print("WASM transmit error:", e)
        else:
            import threading, urllib.request
            def _send():
                try:
                    req = urllib.request.Request(
                        url, data=raw.encode('utf-8'), method='POST'
                    )
                    urllib.request.urlopen(req, timeout=5)
                except Exception as e:
                    print("Send error:", e)
            threading.Thread(target=_send, daemon=True).start()

    # ------------------------------------------------------------------
    # Native: SSE streaming loop (background thread)
    # ------------------------------------------------------------------
    def _listen_loop(self):
        """Persistent SSE stream — native (non-WASM) only."""
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
                    retry_delay = 1
                    for line in response:
                        if not self.running:
                            break
                        if line.strip():
                            try:
                                msg = json.loads(line.decode('utf-8'))
                                if msg.get('event') == 'message':
                                    content = json.loads(msg.get('message', '{}'))
                                    self.incoming_messages.append(content)
                                    self.msg_count += 1
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
                time.sleep(1)

    # ------------------------------------------------------------------
    # Consume pending messages
    # ------------------------------------------------------------------
    def get_messages(self):
        res = list(self.incoming_messages)
        self.incoming_messages.clear()
        return res

net = NetworkManager()
