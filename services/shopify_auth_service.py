import os
import hmac
import hashlib
from supabase import create_client
from models.site import SiteModel
from utils.helpers import SecurityHelpers
import shopify

class ShopifyAuthService:
    def __init__(self):
        self.api_key = os.getenv('SHOPIFY_API_KEY')
        self.api_secret = os.getenv('SHOPIFY_API_SECRET')
        self.scopes = "read_products,read_inventory,read_content,write_script_tags,read_script_tags"
        self.redirect_uri = os.getenv('SHOPIFY_REDIRECT_URI', 'https://api.helloyuno.com/shopify/auth/callback')
        self.site_model = SiteModel()
        
    def get_install_url(self, shop):
        return (
            f"https://{shop}/admin/oauth/authorize?"
            f"client_id={self.api_key}&"
            f"scope={self.scopes}&"
            f"redirect_uri={self.redirect_uri}"
        )
    
    def complete_oauth(self, shop, code):
        # Exchange code for access token
        import requests
        response = requests.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id": self.api_key,
                "client_secret": self.api_secret,
                "code": code
            }
        )
        return response.json()
    
    def setup_yuno_site(self, shop, access_token):
        # Create site record
        site_id = SecurityHelpers.generate_site_id(shop)
        
        # Store in database
        from supabase import create_client
        supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
        
        # Add to sites table
        supabase.table('sites').insert({
            'site_id': site_id,
            'domain': shop,
            'plan_type': 'shopify_starter',
            'widget_enabled': True,
            'custom_config': {
                'is_shopify': True,
                'shopify_domain': shop,
                'access_token': access_token  # Encrypt this in production
            }
        }).execute()
        
        # Add to shopify_stores table
        supabase.table('shopify_stores').insert({
            'site_id': site_id,
            'shop_domain': shop,
            'access_token': access_token,
            'is_active': True
        }).execute()

        # 3) inject the widget script into the storefront via ScriptTag API
        session = shopify.Session(shop, "2025-04", access_token)
        shopify.ShopifyResource.activate_session(session)
     
        shopify.ScriptTag.create({
            "event":         "onload",
            "display_scope": "online_store",
            "src":           f"https://luckylabs-yuno.github.io/luckylabs-yuno/yuno.js?site_id={site_id}"
        })
     
        # clear the active session
        shopify.ShopifyResource.clear_session()
        
        return site_id