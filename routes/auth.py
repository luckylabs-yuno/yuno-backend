# Update your routes/auth.py

from flask import Blueprint, request, jsonify
from flask_cors import cross_origin
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging
import time
from services.jwt_service import JWTService
from services.domain_service import DomainService
from models.site import SiteModel

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

# Initialize services
jwt_service = JWTService()
domain_service = DomainService()
site_model = SiteModel()

@auth_bp.route('/authenticate', methods=['POST', 'OPTIONS'])
@cross_origin(origins="*", methods=['POST', 'OPTIONS'], 
              allow_headers=['Content-Type', 'Authorization'])
def authenticate_widget():
    """
    Authenticate widget and return JWT token
    POST /widget/authenticate
    """
    # Handle preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        return response, 200
    
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['site_id', 'domain', 'nonce']
        for field in required_fields:
            if not data.get(field):
                response = jsonify({
                    "error": "Missing required field",
                    "field": field
                })
                return response, 400
        
        site_id = data['site_id']
        domain = data['domain']
        nonce = data['nonce']
        timestamp = data.get('timestamp', time.time())
        
        logger.info(f"Widget authentication request - site_id: {site_id}, domain: {domain}")
        
        # Get site information
        site = site_model.get_site_by_id(site_id)
        if not site:
            logger.warning(f"Authentication failed - Invalid site_id: {site_id}")
            response = jsonify({
                "error": "Invalid site_id",
                "message": "Site not found"
            })
            return response, 404
        
        # Validate domain ownership
        if not domain_service.validate_domain_ownership(site_id, domain):
            logger.warning(f"Authentication failed - Domain mismatch. site_id: {site_id}, domain: {domain}, registered: {site.get('domain', 'N/A')}")
            response = jsonify({
                "error": "Domain not authorized",
                "message": "Widget not authorized for this domain"
            })
            return response, 403
        
        # Check plan status
        if not site.get('plan_active', False):
            logger.warning(f"Authentication failed - Inactive plan for site_id: {site_id}")
            response = jsonify({
                "error": "Plan inactive",
                "message": "Service subscription is not active"
            })
            return response, 403
        
        # Check widget toggle
        if not site.get('widget_enabled', False):
            logger.warning(f"Authentication failed - Widget disabled for site_id: {site_id}")
            response = jsonify({
                "error": "Widget disabled",
                "message": "Widget has been temporarily disabled"
            })
            return response, 403
        
        # Generate JWT token
        token_payload = {
            'site_id': site_id,
            'domain': domain,
            'nonce': nonce,
            'timestamp': timestamp,
            'plan_type': site.get('plan_type', 'free')
        }
        
        token = jwt_service.generate_token(token_payload)
        
        # Get rate limits based on plan
        rate_limits = site_model.get_rate_limits_for_plan(site.get('plan_type', 'free'))
        
        logger.info(f"Widget authentication successful - site_id: {site_id}")
        
        response_data = {
            "token": token,
            "expires_in": 3600,  # 1 hour
            "rate_limits": rate_limits,
            "site_config": {
                "theme": site.get('theme', 'dark'),
                "custom_config": site.get('custom_config', {})
            }
        }
        
        response = jsonify(response_data)
        return response
        
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        response = jsonify({
            "error": "Authentication failed",
            "message": "Internal authentication error"
        })
        return response, 500

@auth_bp.route('/verify', methods=['POST', 'OPTIONS'])
@cross_origin(origins="*", methods=['POST', 'OPTIONS'], 
              allow_headers=['Content-Type', 'Authorization'])
def verify_token():
    """
    Verify JWT token validity
    POST /widget/verify
    """
    # Handle preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        return response, 200
    
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            response = jsonify({
                "error": "Invalid authorization header"
            })
            return response, 401
        
        token = auth_header.replace('Bearer ', '')
        payload = jwt_service.verify_token(token)
        
        if not payload:
            response = jsonify({
                "error": "Invalid token"
            })
            return response, 401
        
        response = jsonify({
            "valid": True,
            "payload": payload
        })
        return response
        
    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        response = jsonify({
            "error": "Token verification failed"
        })
        return response, 500

@auth_bp.route('/refresh', methods=['POST', 'OPTIONS'])
@cross_origin(origins="*", methods=['POST', 'OPTIONS'], 
              allow_headers=['Content-Type', 'Authorization'])
def refresh_token():
    """
    Refresh JWT token
    POST /widget/refresh
    """
    # Handle preflight
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        return response, 200
    
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            response = jsonify({
                "error": "Invalid authorization header"
            })
            return response, 401
        
        old_token = auth_header.replace('Bearer ', '')
        payload = jwt_service.verify_token(old_token)
        
        if not payload:
            response = jsonify({
                "error": "Invalid token"
            })
            return response, 401
        
        # Generate new token with fresh expiry
        new_token = jwt_service.generate_token({
            'site_id': payload['site_id'],
            'domain': payload['domain'],
            'nonce': payload['nonce'],
            'timestamp': time.time(),
            'plan_type': payload.get('plan_type', 'free')
        })
        
        response = jsonify({
            "token": new_token,
            "expires_in": 3600
        })
        return response
        
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        response = jsonify({
            "error": "Token refresh failed"
        })
        return response, 500