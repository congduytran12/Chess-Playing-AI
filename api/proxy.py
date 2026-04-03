from flask import Flask, request, Response
import requests

app = Flask(__name__)

@app.route('/api/proxy', methods=['GET', 'POST', 'OPTIONS'])
def proxy():
    # Handle CORS preflight (though not needed for same-origin, good for safety)
    if request.method == 'OPTIONS':
        response = Response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    url = request.args.get('url')
    if not url:
        return "Missing url parameter", 400
    
    try:
        if request.method == 'POST':
            # Forward the raw body to the target URL
            resp = requests.post(url, data=request.get_data(), headers={'Content-Type': 'text/plain'})
        else:
            # Forward the GET request
            resp = requests.get(url)
            
        # Create a response that forwards the data back to the browser
        response = Response(resp.content, status=resp.status_code)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        # ntfy.sh returns JSON lines, so we indicate that
        response.headers['Content-Type'] = 'application/json'
        return response
    except Exception as e:
        return str(e), 500
