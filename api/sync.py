import os
import time
import requests
from flask import Flask, request, Response

app = Flask(__name__)

# Use a global session for connection pooling (Performance + socket recycling)
session = requests.Session()

@app.route('/api/sync', methods=['GET', 'POST', 'OPTIONS'])
def sync_proxy():
    # 1. Handle CORS (CVD)
    if request.method == 'OPTIONS':
        return Response(status=204, headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        })

    # 2. Extract Params
    topic = request.args.get('topic')
    since = request.args.get('since', '2m')
    encoded_url = request.args.get('url') # Legacy fallback

    # 3. Handshake Test
    if request.args.get('test') == '1':
        return Response("SYNC_READY", content_type="text/plain", headers={'Access-Control-Allow-Origin': '*'})

    # 4. Resolve Target URL
    target_url = None
    is_poll = False
    if topic:
        if request.method == 'GET':
            target_url = f"https://ntfy.sh/{topic}/json?poll=1&since={since}"
            is_poll = True
        else:
            target_url = f"https://ntfy.sh/{topic}"
    
    if not target_url:
        return Response("Missing topic parameter", status=400, headers={'Access-Control-Allow-Origin': '*'})

    # 5. Proxy the Request with Industry-Standard Robustness
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Vercel-Flask-Sync) Chess-App/1.0',
            'Accept': 'application/x-ndjson'
        }
        
        if request.method == 'POST':
            # Use a shorter timeout for POSTs to prevent UI hangs
            res = session.post(target_url, data=request.data, headers=headers, timeout=5)
        else:
            # Stay under Vercel's 10s function limit
            res = session.get(target_url, headers=headers, timeout=8)

        print(f"[sync] {request.method} {target_url} → {res.status_code}, {len(res.text)} bytes")

        # 6. Stream Response back to Client
        return Response(
            res.text,
            status=res.status_code,
            content_type="application/json",
            headers={
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'X-Sync-Proxy': 'Flask-Stable'
            }
        )

    except requests.exceptions.Timeout:
        # TIMEOUT IS NOT AN ERROR in long-polling. 
        # Return 204 No Content to tell the client to just try again.
        return Response("", status=204, headers={'Access-Control-Allow-Origin': '*', 'X-Sync-Status': 'Timeout-Poll'})
    except Exception as e:
        # Return 500 only on real infrastructure crashes
        return Response(f"Proxy Crash: {str(e)}", status=500, headers={'Access-Control-Allow-Origin': '*'})

# Vercel needs 'app' but sometimes it expects 'handler' for custom runtimes. 
# For the Python runtime using Flask, 'app' is standard.
handler = app
