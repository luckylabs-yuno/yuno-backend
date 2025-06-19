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

# CORS configuration - Dynamic based on registered domains
CORS(app, 
     origins=["*"],  # Allow all for now - fix later
     methods=['POST', 'GET', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization'],
     supports_credentials=False)


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

# Health check endpoint
@app.route('/')
def health():
    return jsonify({
        "status": "healthy",
        "service": "Yuno API",
        "version": "2.0.0"
    })

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

@app.route('/widget/authenticate', methods=['POST', 'OPTIONS'])
def authenticate_widget():
    """Widget authentication endpoint"""
    
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    try:
        data = request.get_json()
        
        # Basic validation
        if not data:
            return jsonify({"error": "Invalid request"}), 400
        
        site_id = data.get('site_id')
        domain = data.get('domain')
        nonce = data.get('nonce')
        
        if not site_id or not domain or not nonce:
            return jsonify({"error": "Missing required fields"}), 400
        
        # For now, allow test123 and any .vercel.app or .github.io domain
        if site_id == 'test123' and (domain.endswith('.vercel.app') or domain.endswith('.github.io') or domain == 'example.com'):
            
            import jwt
            import time
            
            jwt_secret = os.getenv('JWT_SECRET', 'fallback-secret-key')
            
            payload = {
                'site_id': site_id,
                'domain': domain,
                'nonce': nonce,
                'timestamp': time.time(),
                'plan_type': 'free',
                'iat': time.time(),
                'exp': time.time() + 3600,
                'aud': 'yuno-widget',
                'iss': 'yuno-api'
            }
            
            token = jwt.encode(payload, jwt_secret, algorithm='HS256')
            
            response = jsonify({
                "token": token,
                "expires_in": 3600,
                "rate_limits": {
                    "requests_per_minute": 30,
                    "requests_per_hour": 200,
                    "requests_per_day": 500
                },
                "site_config": {
                    "theme": "dark",
                    "custom_config": {}
                }
            })
            
            # Add CORS headers
            response.headers.add('Access-Control-Allow-Origin', '*')
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
            return response
        else:
            response = jsonify({"error": "Site not authorized"})
            response.headers.add('Access-Control-Allow-Origin', '*')
            return response, 404
        
    except Exception as e:
        logging.error(f"Authentication error: {str(e)}")
        response = jsonify({"error": "Authentication failed", "message": str(e)})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)