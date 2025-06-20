from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import logging
from dotenv import load_dotenv
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
import redis
from datetime import datetime

# Load environment variables
load_dotenv()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SENTRY_DSN = os.getenv("SENTRY_DSN")
JWT_SECRET = os.getenv("JWT_SECRET")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MIXPANEL_TOKEN = os.getenv("MIXPANEL_TOKEN")

# Sentry setup
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=1.0,
        send_default_pii=True
    )

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Flask app initialization
app = Flask(__name__)
app.config['SECRET_KEY'] = JWT_SECRET

# Rate limiter setup
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=REDIS_URL,
    default_limits=["1000 per hour"]
)

# CORS CONFIGURATION - Apply to all routes
CORS(app, 
     origins="*",
     methods=['POST', 'GET', 'OPTIONS', 'PUT', 'DELETE'],
     allow_headers=['Content-Type', 'Authorization', 'X-Requested-With', 'Accept', 'Origin'],
     supports_credentials=False,
     max_age=86400
)

# EXPLICIT CORS HANDLER - This ensures CORS works on all responses
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = '*'
    
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, Accept, Origin'
    response.headers['Access-Control-Max-Age'] = '86400'
    return response

# Custom rate limit key function for site-based limiting
def get_site_id_key():
    """Extract site_id for rate limiting"""
    try:
        if request.is_json:
            return request.get_json().get('site_id', get_remote_address())
        return get_remote_address()
    except:
        return get_remote_address()

# Import and register blueprints AFTER CORS setup
from routes.auth import auth_bp
from routes.chat import chat_bp

app.register_blueprint(auth_bp, url_prefix='/widget')
app.register_blueprint(chat_bp, url_prefix='/')

# Preflight handler
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = jsonify({'status': 'ok'})
        return response, 200

# Health check endpoint
@app.route('/')
def health():
    return jsonify({
        "status": "healthy",
        "service": "Yuno API",
        "version": "2.0.0",
        "features": [
            "Widget Authentication",
            "Advanced Chat with RAG",
            "Lead Capture",
            "Analytics Tracking",
            "Rate Limiting",
            "Semantic Search"
        ],
        "cors_enabled": True,
        "timestamp": datetime.utcnow().isoformat()
    })

# Debug endpoint specifically for the ask route
@app.route('/debug/ask-test', methods=['POST', 'OPTIONS'])
def debug_ask_test():
    """Debug version of ask endpoint"""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Basic request info
        debug_info = {
            "method": request.method,
            "headers": dict(request.headers),
            "has_json": request.is_json,
            "content_type": request.content_type,
            "origin": request.headers.get('Origin'),
            "authorization": request.headers.get('Authorization', '')[:20] + "..." if request.headers.get('Authorization') else None
        }
        
        # Try to get JSON data
        try:
            data = request.get_json()
            debug_info["json_data"] = data
        except Exception as e:
            debug_info["json_error"] = str(e)
        
        return jsonify({
            "status": "debug_success",
            "debug_info": debug_info,
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        return jsonify({
            "error": "Debug failed",
            "error_message": str(e),
            "error_type": type(e).__name__
        }), 500

# Global error handlers
@app.errorhandler(429)
def rate_limit_handler(e):
    return jsonify({
        "error": "Rate limit exceeded",
        "message": "Too many requests. Please wait before trying again.",
        "retry_after": getattr(e, 'retry_after', 60)
    }), 429

@app.errorhandler(401)
def unauthorized_handler(e):
    return jsonify({
        "error": "Unauthorized",
        "message": "Invalid or missing authentication token"
    }), 401

@app.errorhandler(403)
def forbidden_handler(e):
    return jsonify({
        "error": "Forbidden", 
        "message": "Access denied for this domain or site"
    }), 403

@app.errorhandler(500)
def internal_error_handler(e):
    logging.error(f"Internal server error: {e}")
    return jsonify({
        "error": "Internal server error",
        "message": "Something went wrong on our end"
    }), 500

# Legacy endpoint for backward compatibility
@app.route('/ask', methods=['POST', 'OPTIONS'])
def legacy_ask_endpoint():
    """Legacy /ask endpoint for backward compatibility"""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    # Check for Authorization header
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({
            "error": "Authorization required",
            "message": "This endpoint now requires widget authentication. Please use the /widget/authenticate endpoint first.",
            "upgrade_guide": {
                "step1": "Call /widget/authenticate with site_id and domain",
                "step2": "Use the returned token in Authorization header",
                "step3": "Make requests to /ask with Bearer token"
            }
        }), 401
    
    # Forward to the chat blueprint endpoint
    from routes.chat import advanced_ask_endpoint
    return advanced_ask_endpoint()

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)