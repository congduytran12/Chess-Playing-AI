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
            self.send_error(400, "Missing url parameter")
            return
            
        try:
            target_url = base64.b64decode(encoded_url).decode('utf-8')
        except Exception as e:
            self.send_error(400, f"Encoding error: {str(e)}")
            return
            
        # 4. Proxy the Request (urllib)
        try:
            req = urllib.request.Request(target_url)
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
            
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read()
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Proxy error: {str(e)}")

    def do_POST(self):
        # 1. Parse Query Params
        parsed_url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_url.query)
        
        # 2. Decode Target URL (Base64)
        encoded_url = query.get('url', [None])[0]
        if not encoded_url:
            self.send_error(400, "Missing url parameter")
            return
            
        try:
            target_url = base64.b64decode(encoded_url).decode('utf-8')
        except Exception as e:
            self.send_error(400, f"Encoding error: {str(e)}")
            return
            
        # 3. Read Body
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        
        # 4. Proxy the POST (urllib)
        try:
            req = urllib.request.Request(target_url, data=body, method='POST')
            req.add_header('Content-Type', 'text/plain')
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                content = response.read()
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(content)
        except Exception as e:
            self.send_error(500, f"Proxy error: {str(e)}")
