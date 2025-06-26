# routes/__init__.py

# This file ensures proper importing of the routes modules
# Add this if it doesn't exist, or update existing one

from .auth import auth_bp
from .chat import chat_bp
from .onboarding import onboarding_bp
from .dashboard import dashboard_bp
from .shopify import shopify_bp
from .chat_shopify import shopify_ask_endpoint

__all__ = [
    'auth_bp',
    'chat_bp', 
    'onboarding_bp',
    'dashboard_bp',
    'shopify_bp',
    'shopify_ask_endpoint'
]