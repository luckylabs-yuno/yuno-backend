# routes/chat_shopify.py - Simplified Shopify Chat Implementation

from flask import request, jsonify
import logging
import json
import os
import requests
import re
from datetime import datetime
from functools import wraps
from typing import List
from services.jwt_service import JWTService
from services.domain_service import DomainService
from services.rate_limit_service import RateLimitService
from models.site import SiteModel
from utils.helpers import LoggingHelpers, ResponseHelpers
import sentry_sdk
from services.shopify_mcp_service import ShopifyMCPService
from urllib.parse import urlparse

# Import OpenAI v1.0+ style
from openai import OpenAI

logger = logging.getLogger(__name__)

# Initialize services
jwt_service = JWTService()
domain_service = DomainService()
rate_limit_service = RateLimitService()
site_model = SiteModel()
shopify_mcp_service = ShopifyMCPService()

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Supabase function URL for semantic search
SUPABASE_FUNCTION_URL = f"{SUPABASE_URL}/rest/v1/rpc/yunosearch"

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Valid Shopify plan types
SHOPIFY_PLAN_TYPES = ['shopify_starter', 'shopify_pro', 'shopify_enterprise']

# Shopify-specific AI Prompts
SHOPIFY_SYSTEM_PROMPT = """
You are **Yuno**, a warm, human-like e-commerce sales assistant for a Shopify store. Your main goal is to help customers discover products, understand policies, and drive sales through engaging conversations.

## Core Principles

- **Commerce Focus**: Always think about guiding customers toward products and purchases
- **Product Discovery**: When customers show buying intent, showcase relevant products
- **Policy Help**: Provide clear information about shipping, returns, and store policies  
- **Lead Capture**: If customers share contact info, capture it appropriately
- **Tone**: Keep replies friendly, helpful, and conversational (2-3 sentences)

## Key Behaviors

1. **Product Recommendations**: When customers ask about products, always include relevant items in `product_carousel`
2. **Quick Actions**: Use `quick_replies` to guide customers toward next steps like "Add to Cart", "See more", "Compare"
3. **Policy Questions**: Provide clear answers about shipping, returns, exchanges based on store policies
4. **Lead Capture**: Only set `leadTriggered=true` when you extract valid email or phone

## Response Format

You must respond with ONLY a JSON object containing:

```json
{
  "content": "Your helpful response text",
  "role": "yuno",
  "leadTriggered": false,
  "lead": {
    "name": "inferred name or null",
    "email": "extracted email or null", 
    "phone": "extracted phone or null",
    "intent": "brief summary of what they want"
  },
  "product_carousel": [
    {
      "id": "product_variant_id",
      "title": "Product Name",
      "price": "$29.99",
      "compare_at_price": "$39.99",
      "image": "product_image_url",
      "handle": "product-handle",
      "available": true
    }
  ],
  "quick_replies": ["Add to Cart", "See more", "Compare"]
}
```

## Product Carousel Rules
- Include when customers ask about products, pricing, or show buying intent
- Use exact product data provided in context
- Maximum 3 products per response
- Include real Shopify product IDs for add-to-cart functionality

## Quick Replies Rules  
- Use for commerce actions: "Add to Cart", "See more", "Tell me more", "Compare"
- Include category options: "Show [category]", "Filter by [option]"
- Maximum 3 quick replies per response

IMPORTANT: Respond with ONLY valid JSON. No markdown, no explanations outside the JSON.
"""

# Utility Functions (reused from core)
def get_embedding(text: str) -> List[float]:
    """Generate OpenAI embedding for text"""
    try:
        response = openai_client.embeddings.create(
            input=text, 
            model="text-embedding-3-large"
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Error generating embedding: {str(e)}")
        raise

def semantic_search(query_embedding: List[float], site_id: str) -> List[dict]:
    """Perform semantic search using Supabase function"""
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "query_embedding": query_embedding,
            "site_id": site_id,
            "max_distance": 0.3
        }
        
        response = requests.post(
            SUPABASE_FUNCTION_URL, 
            headers=headers, 
            data=json.dumps(payload)
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Semantic search failed: {str(e)}")
        return []

def insert_chat_message(site_id, session_id, user_id, page_url, role, content, raw_json_output=None):
    """Write chat message to database"""
    try:
        payload = {
            "site_id": site_id,
            "session_id": session_id,
            "user_id": user_id,
            "page_url": page_url,
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        }

        if raw_json_output is not None:
            payload["raw_json_output"] = raw_json_output

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
        response.raise_for_status()
        
    except Exception as e:
        logger.error(f"Error inserting chat message: {str(e)}")

def insert_lead(lead_data):
    """Insert lead data into Supabase"""
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/leads", 
            headers=headers, 
            data=json.dumps(lead_data)
        )
        response.raise_for_status()
        
    except Exception as e:
        logger.error(f"Error inserting lead: {str(e)}")

def classify_query_type(query: str) -> dict:
    """Simple query classification for Shopify"""
    query_lower = query.lower()
    
    # Product-related queries
    if any(word in query_lower for word in ['product', 'buy', 'price', 'cost', 'show me', 'looking for', 'need', 'want', 'available']):
        return {
            "query_type": "product_search",
            "needs_mcp": True,
            "needs_rag": False
        }
    
    # Policy-related queries  
    elif any(word in query_lower for word in ['policy', 'return', 'shipping', 'exchange', 'refund', 'warranty', 'delivery']):
        return {
            "query_type": "policy_question", 
            "needs_mcp": True,
            "needs_rag": True  # Also search RAG for policy info
        }
    
    # General queries
    else:
        return {
            "query_type": "general_chat",
            "needs_mcp": False,
            "needs_rag": True
        }

def map_mcp_products_to_carousel(mcp_response, max_products=3):
    """Transform MCP product response to carousel format"""
    if not mcp_response or not mcp_response.get('products'):
        return []
    
    products = mcp_response['products']
    carousel_products = []
    
    for product in products[:max_products]:
        try:
            # Extract variant information (use first available variant)
            variants = product.get('variants', [])
            first_variant = variants[0] if variants else {}
            
            # Build carousel product object
            carousel_product = {
                "id": first_variant.get('id') or product.get('id', ''),
                "title": product.get('title', 'Unknown Product'),
                "price": f"${product.get('price', 0):.2f}",
                "image": product.get('image', ''),
                "handle": product.get('handle', ''),
                "available": first_variant.get('available', True)
            }
            
            # Add compare price if available
            if product.get('price_max') and product.get('price_max') > product.get('price', 0):
                carousel_product["compare_at_price"] = f"${product.get('price_max'):.2f}"
            
            carousel_products.append(carousel_product)
            
        except Exception as e:
            logger.error(f"Error transforming product: {e}")
            continue
    
    return carousel_products

def generate_quick_replies(query_type: str, has_products: bool = False) -> List[str]:
    """Generate contextual quick replies"""
    if query_type == "product_search" and has_products:
        return ["Add to Cart", "See more", "Compare"]
    elif query_type == "product_search":
        return ["Browse products", "See categories", "Get help"]
    elif query_type == "policy_question":
        return ["Shipping info", "Return policy", "Contact support"]
    else:
        return ["Browse products", "Get help", "Contact us"]

# JWT Authentication (same as core)
def require_widget_token(f):
    """Decorator to require valid JWT token"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            return jsonify({'status': 'ok'}), 200
            
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
        
        request.token_data = payload
        return f(*args, **kwargs)
    
    return decorated_function

# Main Shopify Chat Endpoint
@require_widget_token
def shopify_ask_endpoint():
    """
    Shopify-specific chat endpoint with MCP integration and product carousels
    """
    try:
        # Get token data
        site_id = request.token_data['site_id']
        token_domain = request.token_data['domain']
        plan_type = request.token_data.get('plan_type', 'free')
        
        # Validate this is a Shopify plan
        if plan_type not in SHOPIFY_PLAN_TYPES:
            logger.warning(f"Non-Shopify plan accessing /shopify/ask: {plan_type}")
            return jsonify({
                "error": "Invalid plan type",
                "message": "This endpoint requires a Shopify plan",
                "upgrade_url": "https://helloyuno.com/shopify"
            }), 403
        
        # Check rate limits (higher for Shopify)
        if not rate_limit_service.check_rate_limit(site_id, plan_type):
            logger.warning(f"Rate limit exceeded for Shopify site: {site_id}")
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
        
        # Extract required fields
        messages = data.get("messages")
        page_url = data.get("page_url")
        session_id = data.get("session_id")
        user_id = data.get("user_id")
        
        if not all([messages, page_url, session_id]):
            return jsonify({
                "error": "Missing required fields",
                "message": "messages, page_url, and session_id are required"
            }), 400
        
        # Domain validation
        request_domain = domain_service.extract_domain_from_url(page_url)
        if not domain_service.domains_match(request_domain, token_domain):
            logger.warning(f"Domain mismatch - Token: {token_domain}, Request: {request_domain}")
            return jsonify({
                "error": "Domain mismatch",
                "message": "Request domain doesn't match token domain"
            }), 403
        
        # Get latest user message
        latest_user_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
        if not latest_user_msg:
            return jsonify({"error": "No user message found"}), 400
        
        latest_user_query = latest_user_msg["content"]
        
        # Insert user message
        insert_chat_message(site_id, session_id, user_id, page_url, "user", latest_user_query)
        
        # Classify query type
        classification = classify_query_type(latest_user_query)
        query_type = classification["query_type"]
        needs_mcp = classification["needs_mcp"]
        needs_rag = classification["needs_rag"]
        
        logger.info(f"Shopify query classified as: {query_type}, MCP: {needs_mcp}, RAG: {needs_rag}")
        
        # Get Shopify store info
        site_info = site_model.get_site_by_id(site_id)
        shopify_domain = None
        if site_info and site_info.get('custom_config'):
            shopify_domain = site_info['custom_config'].get('shopify_domain')
        
        if not shopify_domain:
            logger.error(f"No Shopify domain found for site: {site_id}")
            return jsonify({
                "error": "Shopify configuration missing",
                "message": "Store configuration not found"
            }), 500
        
        # Initialize context variables
        mcp_context = {}
        rag_context = ""
        
        # MCP Integration (Primary for products/policies)
        if needs_mcp:
            try:
                logger.info(f"Connecting to Shopify MCP: {shopify_domain}")
                shopify_mcp_service.connect_sync(shopify_domain)
                
                if query_type == "product_search":
                    logger.info("Executing MCP product search")
                    mcp_response = shopify_mcp_service.search_products_sync(
                        latest_user_query,
                        context=f"Customer searching for: {latest_user_query}"
                    )
                    
                    if not mcp_response.get('error'):
                        mcp_context = mcp_response
                        logger.info(f"MCP product search successful: {len(mcp_response.get('products', []))} products")
                    else:
                        logger.warning(f"MCP product search failed: {mcp_response['error']}")
                        needs_rag = True  # Fallback to RAG
                
                elif query_type == "policy_question":
                    logger.info("Executing MCP policy search")
                    mcp_response = shopify_mcp_service.get_policies_sync(latest_user_query)
                    
                    if not mcp_response.get('error'):
                        mcp_context = mcp_response
                        logger.info("MCP policy search successful")
                    else:
                        logger.warning(f"MCP policy search failed: {mcp_response['error']}")
                        # Continue with RAG anyway for policies
                        
            except Exception as e:
                logger.error(f"MCP integration failed: {e}")
                needs_rag = True  # Fallback to RAG
        
        # RAG Integration (Secondary/Fallback)
        if needs_rag:
            try:
                logger.info("Executing RAG search")
                embedding = get_embedding(latest_user_query)
                matches = semantic_search(embedding, site_id)
                
                rag_context = "\n\n".join(
                    match.get("detail") or match.get("text") or "" 
                    for match in matches if match
                )
                logger.info(f"RAG search returned {len(matches)} matches")
                
            except Exception as e:
                logger.error(f"RAG search failed: {e}")
        
        # Build combined context
        context_parts = []
        
        # Add MCP product data
        if mcp_context.get('products'):
            products = mcp_context['products']
            context_parts.append(f"**AVAILABLE PRODUCTS:**")
            for i, product in enumerate(products[:3]):
                context_parts.append(f"{i+1}. {product.get('title', 'Unknown')} - ${product.get('price', 0):.2f}")
        
        # Add MCP policy data
        if mcp_context.get('policies'):
            context_parts.append(f"**STORE POLICIES:**")
            policies = mcp_context['policies']
            if isinstance(policies, dict):
                for policy_type, policy_content in policies.items():
                    content = str(policy_content)[:200] + "..." if len(str(policy_content)) > 200 else str(policy_content)
                    context_parts.append(f"- {policy_type}: {content}")
        
        # Add RAG context
        if rag_context:
            context_parts.append(f"**ADDITIONAL INFO:**")
            context_parts.append(rag_context[:500] + "..." if len(rag_context) > 500 else rag_context)
        
        combined_context = "\n".join(context_parts)
        
        # Get custom prompt
        custom_prompt = ""
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            resp = supabase.table("custom_detail").select("site_prompt").eq("site_id", site_id).single().execute()
            custom_prompt = resp.data.get("site_prompt") if resp.data else ""
        except Exception:
            pass  # Custom prompt is optional
        
        # Build final prompt
        final_prompt = f"""
        Customer Query: {latest_user_query}
        
        Context Information:
        {combined_context}
        
        Custom Store Instructions:
        {custom_prompt}
        
        Respond with helpful information about the products or policies. If showing products, include them in the product_carousel array.
        """
        
        # Call OpenAI
        messages_for_gpt = [
            {"role": "system", "content": SHOPIFY_SYSTEM_PROMPT},
            {"role": "user", "content": final_prompt}
        ]
        
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=messages_for_gpt,
            temperature=0.7
        )
        
        raw_reply = completion.choices[0].message.content.strip()
        
        # Extract JSON from response
        match = re.search(r"\{.*\}", raw_reply, re.DOTALL)
        if not match:
            logger.error(f"Model returned invalid JSON: {raw_reply}")
            return jsonify({
                "content": "I'm here to help! How can I assist you today?",
                "role": "yuno",
                "leadTriggered": False
            })
        
        try:
            reply_json = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            return jsonify({
                "content": "I'm here to help! How can I assist you today?",
                "role": "yuno", 
                "leadTriggered": False
            })
        
        # Enhance response with MCP data
        if mcp_context.get('products') and not reply_json.get('product_carousel'):
            # Add product carousel from MCP data
            reply_json['product_carousel'] = map_mcp_products_to_carousel(mcp_context)
        
        # Add quick replies if not present
        if not reply_json.get('quick_replies'):
            reply_json['quick_replies'] = generate_quick_replies(
                query_type, 
                bool(reply_json.get('product_carousel'))
            )
        
        # Validate and clean response
        assistant_content = reply_json.get("content", "I'm here to help!")
        
        # Insert assistant response
        insert_chat_message(
            site_id, session_id, user_id, page_url,
            "assistant", assistant_content,
            raw_json_output=json.dumps(reply_json)
        )
        
        # Handle lead capture (keep existing logic)
        if reply_json.get("leadTriggered"):
            lead = reply_json.get("lead", {})
            lead_data = {
                "site_id": site_id,
                "session_id": session_id,
                "user_id": user_id,
                "page_url": page_url,
                "name": lead.get("name"),
                "email": lead.get("email"),
                "phone": lead.get("phone"),
                "message": latest_user_query,
                "intent": lead.get("intent")
            }
            insert_lead(lead_data)
        
        # Update rate limit counter
        rate_limit_service.increment_usage(site_id, plan_type)
        
        logger.info(f"Shopify chat response generated for site: {site_id}")
        return jsonify(reply_json)
        
    except Exception as e:
        logger.exception("Exception in Shopify /ask endpoint")
        sentry_sdk.capture_exception(e)
        
        return jsonify({
            "error": "Internal server error",
            "message": "Something went wrong processing your request"
        }), 500