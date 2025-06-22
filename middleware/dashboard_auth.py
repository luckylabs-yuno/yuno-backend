from functools import wraps
from flask import request, jsonify, g
import jwt
from datetime import datetime, timedelta
import logging
from services.jwt_service import JWTService

logger = logging.getLogger(__name__)

class DashboardAuthMiddleware:
    def __init__(self, app=None):
        self.app = app
        self.jwt_service = JWTService()
        
    def init_app(self, app):
        self.app = app
    
    def require_dashboard_auth(self, f):
        """
        Decorator to require valid JWT token for dashboard access
        """
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                # Get token from Authorization header
                auth_header = request.headers.get('Authorization', '')
                if not auth_header.startswith('Bearer '):
                    return jsonify({
                        'error': 'Authorization header required',
                        'code': 'AUTH_REQUIRED'
                    }), 401
                
                token = auth_header.replace('Bearer ', '')
                
                # Verify token
                payload = self.jwt_service.verify_token(token)
                if not payload:
                    return jsonify({
                        'error': 'Invalid or expired token',
                        'code': 'TOKEN_INVALID'
                    }), 401
                
                # Check if token is for dashboard access
                if payload.get('token_type') != 'access' and payload.get('token_type') != 'dashboard':
                    return jsonify({
                        'error': 'Invalid token type for dashboard access',
                        'code': 'TOKEN_TYPE_INVALID'
                    }), 401
                
                # Store user info in g for use in route handlers
                g.current_user = {
                    'user_id': payload.get('sub') or payload.get('user_id'),
                    'email': payload.get('email'),
                    'token_payload': payload
                }
                
                return f(*args, **kwargs)
                
            except jwt.ExpiredSignatureError:
                return jsonify({
                    'error': 'Token has expired',
                    'code': 'TOKEN_EXPIRED'
                }), 401
            except jwt.InvalidTokenError:
                return jsonify({
                    'error': 'Invalid token',
                    'code': 'TOKEN_INVALID'
                }), 401
            except Exception as e:
                logger.error(f"Dashboard auth error: {str(e)}")
                return jsonify({
                    'error': 'Authentication failed',
                    'code': 'AUTH_FAILED'
                }), 401
        
        return decorated_function
    
    def get_current_user(self):
        """Get current authenticated user from g"""
        return getattr(g, 'current_user', None)