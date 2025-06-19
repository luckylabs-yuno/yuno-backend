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
def get_allowed_origins():
    """Get allowed origins from database dynamically"""
    from services.domain_service import get_all_registered_domains
    try:
        domains = get_all_registered_domains()
        origins = []
        for domain in domains:
            origins.extend([
                f"https://{domain}",
                f"https://www.{domain}",
                f"http://{domain}",  # For development
                f"http://www.{domain}"
            ])
        # Add localhost for development
        origins.extend([
            "http://localhost:3000",
            "http://localhost:8000",
            "http://127.0.0.1:3000"
        ])
        return origins
    except Exception as e:
        logging.error(f"Error getting allowed origins: {e}")
        return ["*"]  # Fallback, but not ideal for production

CORS(app, 
     origins=get_allowed_origins(),
     methods=['POST', 'GET', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization'])

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

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)