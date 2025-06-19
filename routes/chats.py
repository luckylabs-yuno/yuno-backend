from flask import Blueprint, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import logging
import json
import openai
import requests
from datetime import datetime
from functools import wraps
from services.jwt_service import JWTService
from services.domain_service import DomainService
from services.rate_limit_service import RateLimitService
from models.site import SiteModel
import os

chat_bp = Blueprint('chat', __name__)
logger = logging.getLogger(__name__)

# Initialize services
jwt_service = JWTService()
domain_service = DomainService()
rate_limit_service = RateLimitService()
site_model = SiteModel()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

def require_widget_token(f):
    """Decorator to require valid JWT token"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            logger.warning("Missing or invalid authorization header")
            return jsonify({
                "error": "Authorization required",
                "message": "Valid token required for chat access"
            }), 401
        
        token = auth_header.replace('Bearer ', '')
        payload = jwt_service.verify_token(token)
        
        if not payload:
            logger.warning("Invalid JWT token provided")
            return jsonify({
                "error": "Invalid token",
                "message": "Token is invalid or expired"
            }), 401
        
        # Add token payload to request for use in route
        request.token_data = payload
        return f(*args, **kwargs)
    
    return decorated_function

def get_rate_limit_key():
    """Get rate limit key based on site_id from token"""
    try:
        if hasattr(request, 'token_data'):
            return f"site:{request.token_data['site_id']}"
        return get_remote_address()
    except:
        return get_remote_address()

@chat_bp.route('/ask', methods=['POST'])
@require_widget_token
def chat_endpoint():
    """
    Main chat endpoint with JWT authentication and rate limiting
    POST /ask
    """
    try:
        # Get token data
        site_id = request.token_data['site_id']
        token_domain = request.token_data['domain']
        plan_type = request.token_data.get('plan_type', 'free')
        
        # Check rate limits based on plan
        if not rate_limit_service.check_rate_limit(site_id, plan_type):
            logger.warning(f"Rate limit exceeded for site_id: {site_id}")
            return jsonify({
                "error": "Rate limit exceeded",
                "message": "Too many requests. Please wait before trying again."
            }), 429
        
        # Get request data
        data = request.get_json()
        if not data:
            return jsonify({
                "error": "Invalid request",
                "message": "JSON data required"
            }), 400
        
        # Validate required fields
        required_fields = ['page_url', 'messages']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    "error": "Missing required field",
                    "field": field
                }), 400
        
        page_url = data['page_url']
        messages = data['messages']
        session_id = data.get('session_id', 'unknown')
        user_id = data.get('user_id', 'unknown')
        
        # Additional domain validation from page_url
        request_domain = domain_service.extract_domain_from_url(page_url)
        if not domain_service.domains_match(request_domain, token_domain):
            logger.warning(f"Domain mismatch - Token: {token_domain}, Request: {request_domain}")
            return jsonify({
                "error": "Domain mismatch",
                "message": "Request domain doesn't match token domain"
            }), 403
        
        # Log the chat request
        logger.info(f"Chat request - site_id: {site_id}, domain: {request_domain}")
        
        # Get the latest user message
        user_messages = [msg for msg in messages if msg.get('role') == 'user']
        if not user_messages:
            return jsonify({
                "error": "No user message found"
            }), 400
        
        latest_user_query = user_messages[-1]['content']
        
        # Insert user message into chat history
        insert_chat_message(
            site_id, session_id, user_id, page_url,
            "user", latest_user_query
        )
        
        # Prepare context for AI search
        search_payload = {
            "site_id": site_id,
            "query": latest_user_query,
            "limit": 5
        }
        
        # Search knowledge base
        search_response = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/yunosearch",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps(search_payload)
        )
        
        context_chunks = []
        if search_response.status_code == 200:
            search_results = search_response.json()
            context_chunks = [chunk.get('chunk_text', '') for chunk in search_results[:3]]
        
        # Prepare messages for OpenAI
        system_prompt = """You are Yuno, a helpful assistant for this website. Use the provided context to answer questions accurately and concisely. If you don't know something, say so politely."""
        
        context_text = "\n\n".join(context_chunks) if context_chunks else "No relevant context found."
        
        openai_messages = [
            {"role": "system", "content": f"{system_prompt}\n\nContext:\n{context_text}"},
            {"role": "user", "content": latest_user_query}
        ]
        
        # Call OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=openai_messages,
            max_tokens=500,
            temperature=0.7
        )
        
        assistant_content = response.choices[0].message.content
        
        # Insert assistant response
        insert_chat_message(
            site_id, session_id, user_id, page_url,
            "assistant", assistant_content
        )
        
        # Update rate limit counter
        rate_limit_service.increment_usage(site_id, plan_type)
        
        logger.info(f"Chat response generated for site_id: {site_id}")
        
        return jsonify({
            "content": assistant_content,
            "timestamp": datetime.utcnow().isoformat(),
            "tokens_used": response.usage.total_tokens if response.usage else 0
        })
        
    except openai.error.RateLimitError:
        logger.error("OpenAI rate limit exceeded")
        return jsonify({
            "error": "Service temporarily unavailable",
            "message": "Please try again in a moment"
        }), 503
        
    except openai.error.InvalidRequestError as e:
        logger.error(f"OpenAI invalid request: {str(e)}")
        return jsonify({
            "error": "Invalid request",
            "message": "Unable to process your message"
        }), 400
        
    except Exception as e:
        logger.error(f"Chat endpoint error: {str(e)}")
        return jsonify({
            "error": "Internal server error",
            "message": "Something went wrong processing your request"
        }), 500

def insert_chat_message(site_id, session_id, user_id, page_url, role, content, **kwargs):
    """Insert chat message into Supabase"""
    try:
        payload = {
            "site_id": site_id,
            "session_id": session_id,
            "user_id": user_id,
            "page_url": page_url,
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            **kwargs
        }
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/chat_history",
            headers=headers,
            data=json.dumps(payload)
        )
        
        if response.status_code not in [200, 201]:
            logger.error(f"Failed to insert chat message: {response.text}")
            
    except Exception as e:
        logger.error(f"Error inserting chat message: {str(e)}")

@chat_bp.route('/health', methods=['GET'])
def chat_health():
    """Health check for chat service"""
    return jsonify({
        "status": "healthy",
        "service": "chat",
        "timestamp": datetime.utcnow().isoformat()
    })