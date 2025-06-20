from flask import Blueprint, request, jsonify
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
def authenticate_widget():
    """
    Authenticate widget and return JWT token
    POST /widget/authenticate
    """
    # Handle preflight - Flask-CORS will handle headers automatically
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['site_id', 'domain', 'nonce']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    "error": "Missing required field",
                    "field": field
                }), 400
        
        site_id = data['site_id']
        domain = data['domain']
        nonce = data['nonce']
        timestamp = data.get('timestamp', time.time())
        
        logger.info(f"Widget authentication request - site_id: {site_id}, domain: {domain}")
        
        # Get site information
        site = site_model.get_site_by_id(site_id)
        if not site:
            logger.warning(f"Authentication failed - Invalid site_id: {site_id}")
            return jsonify({
                "error": "Invalid site_id",
                "message": "Site not found"
            }), 404
        
        # Validate domain ownership
        if not domain_service.validate_domain_ownership(site_id, domain):
            logger.warning(f"Authentication failed - Domain mismatch. site_id: {site_id}, domain: {domain}, registered: {site.get('domain', 'N/A')}")
            return jsonify({
                "error": "Domain not authorized",
                "message": "Widget not authorized for this domain"
            }), 403
        
        # Check plan status
        if not site.get('plan_active', False):
            logger.warning(f"Authentication failed - Inactive plan for site_id: {site_id}")
            return jsonify({
                "error": "Plan inactive",
                "message": "Service subscription is not active"
            }), 403
        
        # Check widget toggle
        if not site.get('widget_enabled', False):
            logger.warning(f"Authentication failed - Widget disabled for site_id: {site_id}")
            return jsonify({
                "error": "Widget disabled",
                "message": "Widget has been temporarily disabled"
            }), 403
        
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
        
        return jsonify({
            "token": token,
            "expires_in": 3600,  # 1 hour
            "rate_limits": rate_limits,
            "site_config": {
                "theme": site.get('theme', 'dark'),
                "custom_config": site.get('custom_config', {})
            }
        })
        
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        return jsonify({
            "error": "Authentication failed",
            "message": "Internal authentication error"
        }), 500

@auth_bp.route('/verify', methods=['POST', 'OPTIONS'])
def verify_token():
    """
    Verify JWT token validity
    POST /widget/verify
    """
    # Handle preflight
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({
                "error": "Invalid authorization header"
            }), 401
        
        token = auth_header.replace('Bearer ', '')
        payload = jwt_service.verify_token(token)
        
        if not payload:
            return jsonify({
                "error": "Invalid token"
            }), 401
        
        return jsonify({
            "valid": True,
            "payload": payload
        })
        
    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        return jsonify({
            "error": "Token verification failed"
        }), 500

@auth_bp.route('/refresh', methods=['POST', 'OPTIONS'])
def refresh_token():
    """
    Refresh JWT token
    POST /widget/refresh
    """
    # Handle preflight
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({
                "error": "Invalid authorization header"
            }), 401
        
        old_token = auth_header.replace('Bearer ', '')
        payload = jwt_service.verify_token(old_token)
        
        if not payload:
            return jsonify({
                "error": "Invalid token"
            }), 401
        
        # Generate new token with fresh expiry
        new_token = jwt_service.generate_token({
            'site_id': payload['site_id'],
            'domain': payload['domain'],
            'nonce': payload['nonce'],
            'timestamp': time.time(),
            'plan_type': payload.get('plan_type', 'free')
        })
        
        return jsonify({
            "token": new_token,
            "expires_in": 3600
        })
        
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        return jsonify({
            "error": "Token refresh failed"
        }), 500