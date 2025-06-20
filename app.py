# CORS Fix for app.py

# 1. UPDATE YOUR CORS CONFIGURATION IN app.py
from flask import Flask, request, jsonify
from flask_cors import CORS, cross_origin
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Flask app initialization
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('JWT_SECRET')

# IMPROVED CORS CONFIGURATION
CORS(app, 
     origins=[
         "*",  # Temporarily allow all for debugging
         "https://luckylabs-yuno.github.io",
         "https://*.github.io",
         "https://*.vercel.app",
         "http://localhost:*",
         "https://localhost:*"
     ],
     methods=['POST', 'GET', 'OPTIONS', 'PUT', 'DELETE'],
     allow_headers=[
         'Content-Type', 
         'Authorization', 
         'X-Requested-With',
         'Accept',
         'Origin',
         'Access-Control-Request-Method',
         'Access-Control-Request-Headers'
     ],
     supports_credentials=False,
     expose_headers=['Content-Range', 'X-Content-Range'],
     max_age=86400  # Cache preflight for 24 hours
)

# CRITICAL: Add explicit CORS handling for ALL requests
@app.after_request
def after_request(response):
    # Get the origin from the request
    origin = request.headers.get('Origin')
    
    # Allow all origins for now (you can restrict this later)
    response.headers.add('Access-Control-Allow-Origin', origin or '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With, Accept, Origin')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'false')
    response.headers.add('Access-Control-Max-Age', '86400')
    
    return response

# ENHANCED preflight handling
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = jsonify({'status': 'ok'})
        
        # Get the requesting origin
        origin = request.headers.get('Origin', '*')
        
        # Set CORS headers for preflight
        response.headers.add('Access-Control-Allow-Origin', origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With, Accept, Origin')
        response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        response.headers.add('Access-Control-Max-Age', '86400')
        response.headers.add('Access-Control-Allow-Credentials', 'false')
        
        return response, 200

# Import routes AFTER CORS setup
from routes.auth import auth_bp
from routes.chat import chat_bp

# Register blueprints
app.register_blueprint(auth_bp, url_prefix='/widget')
app.register_blueprint(chat_bp, url_prefix='/')

# Health check endpoint with explicit CORS
@app.route('/')
@cross_origin()
def health():
    response = jsonify({
        "status": "healthy",
        "service": "Yuno API",
        "version": "2.0.0",
        "cors_enabled": True,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    return response

# CORS test endpoint
@app.route('/cors-test', methods=['GET', 'POST', 'OPTIONS'])
@cross_origin()
def cors_test():
    """Test endpoint for CORS functionality"""
    return jsonify({
        "message": "CORS test successful",
        "method": request.method,
        "origin": request.headers.get('Origin'),
        "user_agent": request.headers.get('User-Agent'),
        "headers": dict(request.headers)
    })

# Update all error handlers to include CORS headers
@app.errorhandler(429)
def rate_limit_handler(e):
    response = jsonify({
        "error": "Rate limit exceeded",
        "message": "Too many requests. Please wait before trying again.",
        "retry_after": getattr(e, 'retry_after', 60)
    })
    return response, 429

@app.errorhandler(401)
def unauthorized_handler(e):
    response = jsonify({
        "error": "Unauthorized",
        "message": "Invalid or missing authentication token"
    })
    return response, 401

@app.errorhandler(403)
def forbidden_handler(e):
    response = jsonify({
        "error": "Forbidden", 
        "message": "Access denied for this domain or site"
    })
    return response, 403

@app.errorhandler(500)
def internal_error_handler(e):
    logging.error(f"Internal server error: {e}")
    response = jsonify({
        "error": "Internal server error",
        "message": "Something went wrong on our end"
    })
    return response, 500

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_ENV') == 'development', host='0.0.0.0', port=5000)