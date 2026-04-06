import os
import base64
import json
import urllib.request
import urllib.parse
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        # 1. Parse Query Params
        parsed_url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_url.query)
        
        # 2. Handshake Test
        if 'test' in query:
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b"SYNC_READY")
            return

        # 3. Resolve Target URL
        encoded_url = query.get('url', [None])[0]
        topic = query.get('topic', [None])[0]
        since = query.get('since', ['2m'])[0]
        
        target_url = None
        if topic:
            # Topic-Based Proxy (Final stable v8)
            target_url = f"https://ntfy.sh/{topic}/json?poll=1&since={since}&t={time.time()}"
        elif encoded_url:
            # Legacy Base64 Fallback
            try:
                missing_padding = len(encoded_url) % 4
                if missing_padding: encoded_url += '=' * (4 - missing_padding)
                target_url = base64.b64decode(encoded_url).decode('utf-8')
            except: pass

        if not target_url:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing topic or url parameter")
            return
            
        # 4. Proxy the Request with Retries (Robustness for v8)
        for attempt in range(3):
            try:
                req = urllib.request.Request(target_url)
                req.add_header('User-Agent', 'Mozilla/5.0 (Vercel-Sync-Proxy) Chess-App/1.0')
                req.add_header('Accept', 'application/x-ndjson')
                
                with urllib.request.urlopen(req, timeout=10) as response:
                    content = response.read()
                    self.send_response(response.status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.end_headers()
                    self.wfile.write(content)
                    return # Success
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(e.read())
                return # NTFY reported an error (429/403/404)
            except Exception as e:
                if attempt == 2: # Last try
                    self.send_response(500)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(f"Proxy error: {str(e)}".encode())
                else:
                    time.sleep(0.1 * (attempt + 1)) # Backoff



    def do_POST(self):
        # 1. Parse Query Params
        parsed_url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_url.query)
        
        # 2. Resolve Target URL
        encoded_url = query.get('url', [None])[0]
        topic = query.get('topic', [None])[0]
        
        target_url = None
        if topic:
            target_url = f"https://ntfy.sh/{topic}"
        elif encoded_url:
            try:
                missing_padding = len(encoded_url) % 4
                if missing_padding: encoded_url += '=' * (4 - missing_padding)
                target_url = base64.b64decode(encoded_url).decode('utf-8')
            except: pass

        if not target_url:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing topic or url parameter")
            return
            
        # 3. Read Body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        # 4. Proxy the POST (urllib)
        for attempt in range(3):
            try:
                req = urllib.request.Request(target_url, data=body, method='POST')
                req.add_header('Content-Type', 'text/plain')
                req.add_header('User-Agent', 'Mozilla/5.0 (Vercel-Sync-Proxy) Chess-App/1.0')
                
                with urllib.request.urlopen(req, timeout=5) as response:
                    content = response.read()
                    self.send_response(response.status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(content)
                    return
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(e.read())
                return
            except Exception as e:
                if attempt == 2:
                    self.send_response(500)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(f"Proxy error: {str(e)}".encode())
                else:
                    time.sleep(0.1 * (attempt + 1))


