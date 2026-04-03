from flask import Flask, request, Response
import requests
import base64

app = Flask(__name__)

@app.route('/api/sync', methods=['GET', 'POST', 'OPTIONS'])
def sync():
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = Response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    # 1. Handshake Test
    if request.args.get('test'):
        response = Response("SYNC_READY", status=200)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    # 2. Decode the target URL (Base64 to prevent scrambling)
    encoded_url = request.args.get('url')
    if not encoded_url:
        return "Missing url parameter", 400
        
    try:
        # Pad and decode
        url = base64.b64decode(encoded_url).decode('utf-8')
    except Exception as e:
        return f"Encoding error: {e}", 400
    
    try:
        # Use a realistic User-Agent to avoid IP throttling
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Content-Type': 'text/plain'
        }
        
        if request.method == 'POST':
            # Forward the move with a 10s timeout
            resp = requests.post(url, data=request.get_data(), headers=headers, timeout=10)
        else:
            # Forward the poll with a 15s timeout
            resp = requests.get(url, headers=headers, timeout=15)
            
        # Create a response that forwards the data back to the browser
        response = Response(resp.content, status=resp.status_code)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Content-Type'] = 'application/json'
        # Add a cache-busting header
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response
        
    except requests.exceptions.Timeout:
        return "Target timeout", 504
    except Exception as e:
        return str(e), 500
