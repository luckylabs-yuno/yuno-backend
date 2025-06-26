# Add this to your existing shopify.py file

from flask import Blueprint, request, jsonify, redirect, abort
import logging
from services.shopify_auth_service import ShopifyAuthService
from services.shopify_mcp_service import ShopifyMCPService
from utils.helpers import ResponseHelpers

# Import the chat functionality from chat_shopify.py
from routes.chat_shopify import shopify_ask_endpoint

shopify_bp = Blueprint('shopify', __name__)
logger = logging.getLogger(__name__)

auth_service = ShopifyAuthService()
mcp_service = ShopifyMCPService()

# Existing endpoints (keep as they are)
@shopify_bp.route('/install', methods=['GET'])
def install():
    shop = request.args.get('shop')
    if not shop:
        return jsonify(ResponseHelpers.error_response("Shop parameter required")), 400
    
    auth_url = auth_service.get_install_url(shop)
    return jsonify({"auth_url": auth_url})

@shopify_bp.route('/auth/callback', methods=['GET'])
def auth_callback():
    try:
        shop = request.args.get('shop')
        code = request.args.get('code')
        
        result = auth_service.complete_oauth(shop, code)
        # Auto-create site and inject widget
        site_id = auth_service.setup_yuno_site(shop, result['access_token'])
        
        return jsonify({
            "success": True,
            "site_id": site_id,
            "redirect": f"https://{shop}/admin/apps/yuno-ai"
        })
    except Exception as e:
        logger.error(f"OAuth error: {e}")
        return jsonify(ResponseHelpers.error_response(str(e))), 500

@shopify_bp.route('/webhooks/uninstall', methods=['POST'])
def handle_uninstall():
    # Webhook handler for app uninstalls
    pass

# NEW: Shopify-specific chat endpoint
@shopify_bp.route('/ask', methods=['POST', 'OPTIONS'])
def shopify_chat():
    """
    Shopify-specific chat endpoint that handles:
    - MCP integration for product/policy searches
    - Product carousel generation
    - Quick replies for commerce actions
    - RAG fallback for policy queries and MCP failures
    """
    return shopify_ask_endpoint()

# Health check for Shopify services
@shopify_bp.route('/health', methods=['GET', 'OPTIONS'])
def shopify_health():
    """Health check for Shopify services"""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        health_status = {
            "status": "healthy",
            "service": "shopify",
            "timestamp": datetime.utcnow().isoformat(),
            "endpoints": {
                "chat": "/shopify/ask",
                "install": "/shopify/install",
                "callback": "/shopify/auth/callback",
                "health": "/shopify/health"
            }
        }
        
        # Test MCP service availability
        try:
            mcp_test = ShopifyMCPService()
            health_status["mcp_service"] = "available"
        except Exception as e:
            health_status["mcp_service"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
        
        status_code = 200 if health_status["status"] == "healthy" else 503
        return jsonify(health_status), status_code
        
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "service": "shopify",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 503