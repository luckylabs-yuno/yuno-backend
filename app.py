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

# Import routes
from routes.auth import auth_bp
from routes.chat import chat_bp

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

# FIXED CORS CONFIGURATION - Allow your GitHub Pages domain
CORS(app, 
     origins=[
         "*",  # Allow all for development - you can restrict this later
         "https://luckylabs-yuno.github.io",  # Your specific GitHub Pages domain
         "https://*.github.io",  # All GitHub Pages domains
         "https://*.vercel.app",  # Vercel domains
         "http://localhost:*",  # Local development
         "https://localhost:*"  # Local HTTPS
     ],
     methods=['POST', 'GET', 'OPTIONS', 'PUT', 'DELETE'],
     allow_headers=[
         'Content-Type', 
         'Authorization', 
         'X-Requested-With',
         'Accept',
         'Origin'
     ],
     supports_credentials=False,
     expose_headers=['Content-Range', 'X-Content-Range']
)

# Rate limiter setup
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=REDIS_URL,
    default_limits=["1000 per hour"]
)

# Custom rate limit key function for site-based limiting
def get_site_id_key():
    """Extract site_id for rate limiting"""
    try:
        if request.is_json:
            return request.get_json().get('site_id', get_remote_address())
        return get_remote_address()
    except:
        return get_remote_address()

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/widget')
app.register_blueprint(chat_bp, url_prefix='/')

# Add explicit CORS handling for preflight requests
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With, Accept, Origin')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        response.headers.add('Access-Control-Max-Age', '86400')
        return response

# Health check endpoint
@app.route('/')
def health():
    response = jsonify({
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
        "cors_enabled": True
    })
    
    # Add CORS headers to health check too
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

# CORS test endpoint
@app.route('/cors-test', methods=['GET', 'POST', 'OPTIONS'])
def cors_test():
    """Test endpoint for CORS functionality"""
    response = jsonify({
        "message": "CORS test successful",
        "method": request.method,
        "origin": request.headers.get('Origin'),
        "user_agent": request.headers.get('User-Agent'),
        "timestamp": datetime.utcnow().isoformat()
    })
    
    # Explicit CORS headers
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    
    return response

# Global error handlers with CORS headers
@app.errorhandler(429)
def rate_limit_handler(e):
    response = jsonify({
        "error": "Rate limit exceeded",
        "message": "Too many requests. Please wait before trying again.",
        "retry_after": getattr(e, 'retry_after', 60)
    })
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 429

@app.errorhandler(401)
def unauthorized_handler(e):
    response = jsonify({
        "error": "Unauthorized",
        "message": "Invalid or missing authentication token"
    })
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 401

@app.errorhandler(403)
def forbidden_handler(e):
    response = jsonify({
        "error": "Forbidden", 
        "message": "Access denied for this domain or site"
    })
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 403

@app.errorhandler(500)
def internal_error_handler(e):
    logging.error(f"Internal server error: {e}")
    response = jsonify({
        "error": "Internal server error",
        "message": "Something went wrong on our end"
    })
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response, 500

# Backward compatibility endpoint (keeping the old /ask route structure)
@app.route('/ask', methods=['POST', 'OPTIONS'])
def legacy_ask_endpoint():
    """
    Legacy /ask endpoint for backward compatibility
    Redirects to the new secured endpoint
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    # Check for Authorization header
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        response = jsonify({
            "error": "Authorization required",
            "message": "This endpoint now requires widget authentication. Please use the /widget/authenticate endpoint first.",
            "upgrade_guide": {
                "step1": "Call /widget/authenticate with site_id and domain",
                "step2": "Use the returned token in Authorization header",
                "step3": "Make requests to /ask with Bearer token"
            }
        })
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 401
    
    # If we have a token, forward to the new endpoint
    # This allows existing widgets to work during transition
    from routes.chat import advanced_ask_endpoint
    return advanced_ask_endpoint()

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)
