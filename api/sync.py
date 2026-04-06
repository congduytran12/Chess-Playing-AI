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

        # 3. Decode Target URL (Base64)
        encoded_url = query.get('url', [None])[0]
        if not encoded_url:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing url parameter")
            return
            
        try:
            # Fix potential Base64 padding issues
            missing_padding = len(encoded_url) % 4
            if missing_padding:
                encoded_url += '=' * (4 - missing_padding)
            target_url = base64.b64decode(encoded_url).decode('utf-8')
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Encoding error: {str(e)}".encode())
            return
            
        # 4. Proxy the Request (urllib)
        try:
            req = urllib.request.Request(target_url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Vercel-Proxy) Chess-App/1.0')
            req.add_header('Accept', 'application/x-ndjson')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read()
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                self.wfile.write(content)
        except urllib.error.HTTPError as e:
            # Propagate the actual status from ntfy
            self.send_response(e.code)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(500)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(f"Proxy error: {str(e)}".encode())


    def do_POST(self):
        # 1. Parse Query Params
        parsed_url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_url.query)
        
        # 2. Decode Target URL (Base64)
        encoded_url = query.get('url', [None])[0]
        if not encoded_url:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing url parameter")
            return
            
        try:
            # Fix potential Base64 padding issues
            missing_padding = len(encoded_url) % 4
            if missing_padding:
                encoded_url += '=' * (4 - missing_padding)
            target_url = base64.b64decode(encoded_url).decode('utf-8')
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"Encoding error: {str(e)}".encode())
            return
            
        # 3. Read Body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        # 4. Proxy the POST (urllib)
        try:
            req = urllib.request.Request(target_url, data=body, method='POST')
            req.add_header('Content-Type', 'text/plain')
            req.add_header('User-Agent', 'Mozilla/5.0 (Vercel-Proxy) Chess-App/1.0')
            
            with urllib.request.urlopen(req, timeout=5) as response:
                content = response.read()
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(content)
        except urllib.error.HTTPError as e:
            # Propagate the actual status from ntfy
            self.send_response(e.code)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(500)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(f"Proxy error: {str(e)}".encode())

