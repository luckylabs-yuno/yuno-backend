from flask import Blueprint, request, jsonify, redirect, abort
import logging
from services.shopify_auth_service import ShopifyAuthService
from services.shopify_mcp_service import ShopifyMCPService
from utils.helpers import ResponseHelpers

shopify_bp = Blueprint('shopify', __name__)
logger = logging.getLogger(__name__)

auth_service = ShopifyAuthService()
mcp_service = ShopifyMCPService()

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