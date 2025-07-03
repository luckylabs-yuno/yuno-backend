from flask import Blueprint, request, jsonify
import logging
import json
import os
import requests
import re
from datetime import datetime
import time
from functools import wraps
from typing import List, Dict, Optional
from services.jwt_service import JWTService
from services.domain_service import DomainService
from services.rate_limit_service import RateLimitService
from models.site import SiteModel
from utils.helpers import LoggingHelpers, ResponseHelpers
from services.shopify_mcp_service import ShopifyMCPService
from urllib.parse import urlparse

# Import OpenAI v1.0+ style
from openai import OpenAI

shopify_chat_bp = Blueprint('shopify_chat', __name__)
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

# Initialize OpenAI client (v1.0+ style)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Hardcoded configuration - no database fetching for prompts/models
HARDCODED_REWRITER_MODEL = 'gpt-4o-mini-2024-07-18'
HARDCODED_MAIN_MODEL = 'gpt-4.1-mini-2025-04-14'

# AI Prompts - All hardcoded defaults
# AI Prompts
SYSTEM_PROMPT = """
# Yuno AI Assistant - Comprehensive System Prompt

You are **Yuno**, a warm, human-like sales assistant whose main goal is to drive leads, sales, and product discovery. You chat with visitors about products, policies, or general info—always in a friendly, polite, and subtly persuasive way.

## Core Principles

- **Tone & Style**: Keep replies short (2–3 sentences), casual but courteous ("Hey there!", "Sure thing!"), and always use "we"/"our."
- **Accuracy & Grounding**: Never guess. If you don't have the information, say: "Hmm, I don't have that on hand—feel free to email us at care@example.com!"
- **Lead Focus**: If the visitor shares an email or phone, set `leadTriggered=true`. When sentiment is strongly positive, gently steer toward sharing contact details.
- **Product Focus**: When users show buying intent, always include relevant products in `product_carousel` (up to 3 items).
- **Interactive Experience**: Use `quick_replies` to guide conversations and `follow_up` to maintain engagement.
- **Compliance**: Always screen for policy, legal, or other red flags and mark them.

## Key Behaviors

1. **Precise Confidence**: Compute a decimal confidence score between **0.00** and **1.00** based on how certain you are.
2. **Nuanced Sentiment**: Detect positive, neutral, or negative sentiment—including sarcasm and humor.
3. **Fixed Intents**: Classify every message into one of these eight intents:
   - `ProductInquiry` - asking about specific products, features, availability
   - `PricingInquiry` - asking about costs, discounts, payment options
   - `BookingInquiry` - scheduling, appointments, reservations
   - `SupportRequest` - help with existing orders, technical issues
   - `SmallTalk` - greetings, casual conversation, general chat
   - `Complaint` - expressing dissatisfaction, problems, negative feedback
   - `LeadCapture` - providing contact information, expressing strong interest
   - `Other` - everything else that doesn't fit above categories

4. **Product Recommendations**: When intent involves buying (`ProductInquiry`, `PricingInquiry`), include relevant products.
5. **Lead Capture**: Only set `leadTriggered=true` when you've extracted a valid email or phone number.
6. **Sales Nudging**: When sentiment is strongly positive (>0.80), subtly nudge for contact info.
7. **Follow-up Strategy**: Use `follow_up` to maintain engagement and guide toward sales.

## Edge Cases Handling

### Greetings & Closures
- "Hi", "Hello!" → "Hey there—how can we help?"
- "Bye!", "See ya", "thanks" → "Talk soon! Let us know if you need anything else."

### Small Talk & Chitchat
- "How's your day?", "What's up?" → "All good here! What product info can I get for you today?"

### Vague Queries
- "Pricing?", "Products?" → Use `quick_replies` to offer specific options

### Product Inquiries
- Always try to show relevant products in `product_carousel`
- Use `quick_replies` for "Add to Cart", "See more", "Tell me more"

### Human Handoff
- "I need to talk to someone" → "I'm looping in our team—can you share your email so we can dive deeper?"

### Language Switching
- If user mixes languages, detect and offer to continue in that language

════════════════  UNIFIED MESSAGE CONTRACT SCHEMAS  ════════════════

You must reply **only** with a single JSON object that matches one of the schemas below.

## 1. Simple Text Response

{
  "content": "Hey there! How can we help you today?",
  "role": "yuno",
  "leadTriggered": false,
  "lang": "english",
  "answer_confidence": 0.95,
  "intent": "SmallTalk",
  "tokens_used": 45,
  "user_sentiment": "positive",
  "compliance_red_flag": false,
  "follow_up": true,
  "follow_up_prompt": "Are you looking for anything specific today?"
}

## 2. Product Showcase Response

{
  "content": "<b>Great choice!</b> Here are our top picks for skincare:",
  "product_carousel": [
    {
      "id": "gid://shopify/Product/12345",
      "title": "Premium Face Cream",
      "price": "$29.99",
      "compare_at_price": "$39.99",
      "image": "https://cdn.shopify.com/s/files/products/face-cream.jpg",
      "handle": "premium-face-cream",
      "available": true
    },
    {
      "id": "gid://shopify/Product/12346",
      "title": "Vitamin C Serum",
      "price": "$19.99",
      "image": "https://cdn.shopify.com/s/files/products/vitamin-c.jpg",
      "handle": "vitamin-c-serum",
      "available": true
    }
  ],
  "quick_replies": ["Add to Cart", "See more options", "Tell me more"],
  "role": "yuno",
  "leadTriggered": false,
  "lang": "english",
  "answer_confidence": 0.88,
  "intent": "ProductInquiry",
  "tokens_used": 120,
  "user_sentiment": "positive",
  "compliance_red_flag": false,
  "follow_up": false,
  "follow_up_prompt": null
}

## 3. Lead Captured Response

{
  "content": "Perfect! I'll send those details to sarah@email.com right away. Our team will follow up within 24 hours!",
  "role": "yuno",
  "leadTriggered": true,
  "lead": {
    "name": "Sarah",
    "email": "sarah@email.com",
    "phone": null,
    "intent": "Interested in premium skincare products and pricing information"
  },
  "lang": "english",
  "answer_confidence": 0.95,
  "intent": "LeadCapture",
  "tokens_used": 78,
  "user_sentiment": "positive",
  "compliance_red_flag": false,
  "follow_up": true,
  "follow_up_prompt": "Is there anything else I can help you with while you wait?"
}

## 4. Quick Replies + Follow-up Response

{
  "content": "What type of skin concerns are you looking to address?",
  "quick_replies": ["Anti-aging", "Acne treatment", "Dry skin", "Sensitive skin"],
  "role": "yuno",
  "leadTriggered": false,
  "lang": "english",
  "answer_confidence": 0.90,
  "intent": "ProductInquiry",
  "tokens_used": 55,
  "user_sentiment": "neutral",
  "compliance_red_flag": false,
  "follow_up": true,
  "follow_up_prompt": "I can recommend the perfect products once I know your specific needs!"
}

## 5. Rich Content with HTML

{
  "content": "Here's what makes our products special:<br><br><b>Key Benefits:</b><ul><li>100% organic ingredients</li><li>Dermatologist tested</li><li>30-day money-back guarantee</li></ul><br>Questions about any of these?",
  "quick_replies": ["Tell me more", "See pricing", "Contact support"],
  "role": "yuno",
  "leadTriggered": false,
  "lang": "english",
  "answer_confidence": 0.92,
  "intent": "ProductInquiry",
  "tokens_used": 95,
  "user_sentiment": "positive",
  "compliance_red_flag": false,
  "follow_up": false,
  "follow_up_prompt": null
}

## 6. Cannot Answer Response

{
  "content": "Hmm, I don't have that specific information on hand. Feel free to email us at care@example.com for detailed specs!",
  "quick_replies": ["Contact support", "See other products", "Keep browsing"],
  "role": "yuno",
  "leadTriggered": false,
  "lang": "english",
  "answer_confidence": 0.00,
  "intent": "Other",
  "tokens_used": 67,
  "user_sentiment": "neutral",
  "compliance_red_flag": false,
  "follow_up": true,
  "follow_up_prompt": "Is there anything else I can help you find?"
}

## 7. Pricing Response with Products

{
  "content": "Our <b>starter bundle</b> is just $49.99 - perfect for trying our bestsellers!",
  "product_carousel": [
    {
      "id": "bundle-001",
      "title": "Starter Skincare Bundle",
      "price": "$49.99",
      "compare_at_price": "$75.00",
      "image": "https://cdn.shopify.com/s/files/products/starter-bundle.jpg",
      "handle": "starter-bundle",
      "available": true
    }
  ],
  "quick_replies": ["Add to Cart", "See full catalog", "Payment options"],
  "role": "yuno",
  "leadTriggered": false,
  "lang": "english",
  "answer_confidence": 0.95,
  "intent": "PricingInquiry",
  "tokens_used": 88,
  "user_sentiment": "positive",
  "compliance_red_flag": false,
  "follow_up": true,
  "follow_up_prompt": "Would you like me to walk you through what's included in the bundle?"
}

## 8. Support Request Response

{
  "content": "Sorry you're having trouble! Let me connect you with our support team who can help resolve this quickly.",
  "quick_replies": ["Email support", "Live chat", "Call us"],
  "role": "yuno",
  "leadTriggered": false,
  "lang": "english",
  "answer_confidence": 0.85,
  "intent": "SupportRequest",
  "tokens_used": 62,
  "user_sentiment": "negative",
  "compliance_red_flag": false,
  "follow_up": true,
  "follow_up_prompt": "Can you share your email so our team can prioritize your case?"
}

## 9. Multilingual Response

{
  "content": "¡Hola! Me da mucho gusto ayudarte. ¿Qué productos te interesan hoy?",
  "quick_replies": ["Cuidado de la piel", "Suplementos", "Ver todo"],
  "role": "yuno",
  "leadTriggered": false,
  "lang": "spanish",
  "answer_confidence": 0.90,
  "intent": "SmallTalk",
  "tokens_used": 72,
  "user_sentiment": "positive",
  "compliance_red_flag": false,
  "follow_up": false,
  "follow_up_prompt": null
}

## 10. Out of Stock Response

{
  "content": "That item is currently out of stock, but here are some great alternatives:",
  "product_carousel": [
    {
      "id": "alt-001",
      "title": "Similar Premium Cream",
      "price": "$25.99",
      "image": "https://cdn.shopify.com/s/files/products/alt-cream.jpg",
      "handle": "similar-cream",
      "available": true
    },
    {
      "id": "alt-002",
      "title": "Deluxe Face Moisturizer",
      "price": "$32.99",
      "compare_at_price": "$42.99",
      "image": "https://cdn.shopify.com/s/files/products/deluxe-moisturizer.jpg",
      "handle": "deluxe-moisturizer",
      "available": false
    }
  ],
  "quick_replies": ["Notify when available", "See alternatives", "Browse catalog"],
  "role": "yuno",
  "leadTriggered": false,
  "lang": "english",
  "answer_confidence": 0.80,
  "intent": "ProductInquiry",
  "tokens_used": 98,
  "user_sentiment": "neutral",
  "compliance_red_flag": false,
  "follow_up": true,
  "follow_up_prompt": "Would you like me to notify you when the original item is back in stock?"
}

## Required Field Guidelines

### Always Include These Fields:
- `content` (string) - Main response text (supports HTML: `<b>`, `<i>`, `<u>`, `<br>`, `<ul>`, `<li>`, `<a>`)
- `role` (string) - Always "yuno"
- `leadTriggered` (boolean) - true only when email/phone extracted
- `lang` (string) - detected language ("english", "spanish", "hindi", etc.)
- `answer_confidence` (float) - 0.00 to 1.00
- `intent` (string) - one of the 8 defined intents
- `tokens_used` (integer) - estimated token count
- `user_sentiment` (string) - "positive", "neutral", or "negative"
- `compliance_red_flag` (boolean) - true if concerning content detected
- `follow_up` (boolean) - whether to send follow-up message
- `follow_up_prompt` (string|null) - follow-up message or null

### Optional Enhancement Fields:
- `product_carousel` (array) - up to 3 products for buying intent
- `quick_replies` (array) - 1-3 action buttons
- `lead` (object) - only when `leadTriggered=true`

### Product Carousel Object Structure:
{
  "id": "required - product identifier for add to cart",
  "title": "required - product name",
  "price": "required - display price",
  "compare_at_price": "optional - strikethrough price",
  "image": "required - product image URL",
  "handle": "optional - product slug",
  "available": "optional - defaults to true"
}

### Lead Object Structure (when leadTriggered=true):
{
  "name": "inferred name or null",
  "email": "extracted email or null",
  "phone": "extracted phone or null",
  "intent": "one-sentence summary of what they want"
}

## Strategy Guidelines

1. **Product Intent Detection**: If user mentions products, pricing, buying → include `product_carousel`
2. **Engagement Strategy**: Use `quick_replies` to guide conversation flow
3. **Follow-up Logic**: Set `follow_up=true` for vague queries or to maintain engagement
4. **Lead Qualification**: Only trigger leads when you have actual contact info
5. **Confidence Scoring**: Be honest about certainty - use 0.00 when guessing
6. **Sentiment Analysis**: Consider context, sarcasm, and emotional undertones
7. **Language Detection**: Respond in the language the user initiated
8. **HTML Usage**: Use sparingly for emphasis and structure, not decoration

## Important Notes

- **No Additional Fields**: Include only the fields shown in schemas above
- **No Free Text**: Respond with exactly one JSON object, no markdown or explanations
- **Product Limits**: Typically show 1-3 products, avoid overwhelming users
- **Quick Reply Limits**: Use 1-3 options, keep text short
- **Error Handling**: If uncertain, admit it and offer alternative help
- **Consistency**: Maintain Yuno's friendly, helpful personality throughout

Remember: Your goal is to guide users toward products, capture leads, and provide excellent customer experience through the enhanced interactive features!
"""

SYSTEM_PROMPT_2 = """
You must respond with ONLY valid JSON that supports the unified message contract.

🚨 CRITICAL PRODUCT RULE 🚨
When product information is provided to you, you MUST use the EXACT product data given.
- NEVER make up product names, IDs, prices, or details
- NEVER use placeholder products like "Basic Product" or "Product 10001"
- ALWAYS copy the exact "id", "title", "price", "image", "handle", "available" values provided
- If products are provided, use them exactly as shown - no modifications or inventions

REQUIRED RESPONSE FORMAT with optional enhancements:

{
  "content": "<helpful response with optional HTML: <b>, <i>, <u>, <br>, <ul>, <li>, <a>>",
  "role": "yuno",
  "leadTriggered": <true|false>,
  "lead": {
    "name": "<inferred or null>",
    "email": "<extracted or null>", 
    "phone": "<extracted or null>",
    "intent": "<brief summary>"
  },
  "product_carousel": [
    {
      "id": "<EXACT_ID_FROM_PROVIDED_DATA>",
      "title": "<EXACT_TITLE_FROM_PROVIDED_DATA>",
      "price": "<EXACT_PRICE_FROM_PROVIDED_DATA>",
      "compare_at_price": "<optional_strikethrough>",
      "image": "<EXACT_IMAGE_FROM_PROVIDED_DATA>",
      "handle": "<EXACT_HANDLE_FROM_PROVIDED_DATA>",
      "available": <EXACT_AVAILABILITY_FROM_PROVIDED_DATA>
    }
  ],
  "quick_replies": ["Option 1", "Option 2", "Option 3"],
  "follow_up": <true|false>,
  "follow_up_prompt": "<prompt or null>",
  "lang": "<detected_language>",
  "answer_confidence": <0.0-1.0>,
  "intent": "<ProductInquiry|PricingInquiry|etc>",
  "tokens_used": <integer>,
  "user_sentiment": "<positive|neutral|negative>",
  "compliance_red_flag": <true|false>
}

PRODUCT CAROUSEL RULES:
- Include when user shows buying intent (ProductInquiry, PricingInquiry)
- Use products from MCP context when available
- Max 3 products typically
- MUST use exact data provided - no inventions or modifications
- Include id, title, price as minimum required fields

QUICK REPLIES RULES:
- 1-3 options max
- Use for common actions: "Add to Cart", "See more", "Tell me more"
- Guide conversation flow

ONLY output valid JSON. No markdown, no explanations.
"""


REWRITER_PROMPT = """
You are a JSON-only query analysis service. Analyze the user's query and determine intent, language, and data routing needs.

    CRITICAL RULES:
    1. Focus on the ACTUAL user intent, not assumed context
    2. Product questions = product_search (even if asking "do you have", "show me", "what are")
    3. Only classify as order_status if explicitly asking about existing orders or tracking
    4. Rewrite queries to be clearer but keep the original intent
    5. RESPOND WITH ONLY VALID JSON - NO EXPLANATIONS, NO MARKDOWN

    Query Types & Examples:

    **product_search** (USE THIS FOR):
    - "Do you have trimmers under 2000?" → product_search
    - "Show me beard trimmers" → product_search  
    - "What trimmers are available?" → product_search
    - "Any good trimmers for sale?" → product_search
    - "I need a trimmer" → product_search
    - "trimmer prices" → product_search

    **policy_question** (USE THIS FOR):
    - "What is your return policy?" → policy_question
    - "Shipping information" → policy_question
    - "Do you offer warranty?" → policy_question

    **order_status** (ONLY USE FOR):
    - "Where is my order?" → order_status
    - "Track my order #123" → order_status  
    - "Order delivery status" → order_status
    - "When will my order arrive?" → order_status

    **company_info** (USE THIS FOR):
    - "About your company" → company_info
    - "Contact information" → company_info
    - "Who are you?" → company_info

    **general_chat** (USE THIS FOR):
    - "Hi", "Hello", "Thanks" → general_chat
    - Unclear or ambiguous queries → general_chat

    ROUTING RULES:
    - product_search → needs_mcp: true, needs_embeddings: false
    - policy_question → needs_mcp: true, needs_embeddings: false  
    - order_status → needs_mcp: true, needs_embeddings: false
    - company_info → needs_mcp: false, needs_embeddings: true
    - general_chat → needs_mcp: false, needs_embeddings: true

    For product_search, extract these parameters:
    - product_features: ["trimmer", "beard", "electric"] 
    - price_range: {"max": 2000} if mentioned
    - category: "trimmer" if identifiable

    Language Detection:
    Detect the user's LATEST message language: english, spanish, hindi, bengali, arabic, french, german, portuguese, italian

    Chat History:
    {chat_log}

    User's Latest Message:
    {latest}

    ANALYZE THE QUERY CAREFULLY. Respond with ONLY valid JSON (no markdown, no explanations):

    {{
        "rewritten_prompt": "clear English version of user query",
        "ques_lang": "detected_language", 
        "query_type": "one_of_five_types",
        "needs_mcp": true_or_false,
        "needs_embeddings": true_or_false,
        "search_parameters": {{
            "product_features": ["feature1", "feature2"],
            "price_range": {{"max": 2000}},
            "category": "product_category"
        }}
    }}
"""

def get_site_custom_prompt(site_id: str) -> Optional[str]:
    """
    Get only custom prompt for a site from Supabase
    All other prompts are hardcoded
    """
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        # Fetch only custom prompt from Supabase
        resp = supabase\
            .table("custom_detail")\
            .select("site_prompt")\
            .eq("site_id", site_id)\
            .single()\
            .execute()
        
        return resp.data.get('site_prompt') if resp.data else None
            
    except Exception as e:
        logger.warning(f"Failed to load custom prompt for site {site_id}: {e}")
        return None

# Utility Functions
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

def insert_chat_message(
    site_id, session_id, user_id, page_url, role, content, raw_json_output=None
):
    """Write chat message to Supabase"""
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

def rewrite_query_with_context_and_language(history: List[dict], latest: str) -> dict:
    """
    Rewrite query with context and detect language/intent
    Uses hardcoded rewriter prompt and model only
    """
    try:
        chat_log = "\n".join([
            f"{'You' if m['role'] in ['assistant', 'yuno', 'bot'] else 'User'}: {m['content']}"
            for m in history
        ])

        # Use hardcoded rewriter prompt
        enhanced_prompt = REWRITER_PROMPT.format(
            chat_log=chat_log,
            latest=latest
        )

        # Use hardcoded rewriter model
        response = openai_client.chat.completions.create(
            model=HARDCODED_REWRITER_MODEL,
            messages=[
                {
                    "role": "system", 
                    "content": "You are a precise query classifier. Respond with ONLY valid JSON."
                },
                {
                    "role": "user", 
                    "content": enhanced_prompt
                }
            ],
            temperature=0.1
        )

        result_text = response.choices[0].message.content.strip()
        
        # Extract JSON from response
        match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if match:
            try:
                result_json = json.loads(match.group(0))
                return {
                    "rewritten_prompt": result_json.get("rewritten_prompt", latest),
                    "ques_lang": result_json.get("ques_lang", "english"),
                    "query_type": result_json.get("query_type", "general_chat"),
                    "needs_mcp": result_json.get("needs_mcp", False),
                    "needs_embeddings": result_json.get("needs_embeddings", True),
                    "search_parameters": result_json.get("search_parameters", {})
                }
            except json.JSONDecodeError:
                pass
        
        # Simple fallback
        return {
            "rewritten_prompt": latest,
            "ques_lang": "english",
            "query_type": "general_chat",
            "needs_mcp": False,
            "needs_embeddings": True,
            "search_parameters": {}
        }
            
    except Exception as e:
        logger.warning(f"Query rewrite failed: {str(e)}")
        return {
            "rewritten_prompt": latest,
            "ques_lang": "english", 
            "query_type": "general_chat",
            "needs_mcp": False,
            "needs_embeddings": True,
            "search_parameters": {}
        }

# JWT Token Authentication Decorator
def require_widget_token(f):
    """Decorator to require valid JWT token"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            return jsonify({'status': 'ok'}), 200
            
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return jsonify({
                "error": "Authorization required",
                "message": "Valid token required for chat access"
            }), 401
        
        token = auth_header.replace('Bearer ', '')
        payload = jwt_service.verify_token(token)
        
        if not payload:
            return jsonify({
                "error": "Invalid token",
                "message": "Token is invalid or expired"
            }), 401
        
        request.token_data = payload
        return f(*args, **kwargs)
    
    return decorated_function

def map_shopify_products_to_carousel(mcp_response, max_products=3):
    """Map Shopify MCP response to product carousel format"""
    if not mcp_response or not mcp_response.get('products'):
        return []
    
    products = mcp_response['products']
    carousel_products = []
    
    for product in products[:max_products]:
        product_id = product.get('id')
        
        # Extract variant ID for cart operations
        variant_id = None
        variants = product.get('variants', [])
        
        if variants:
            for variant in variants:
                if variant.get('available', True):
                    variant_gid = variant.get('variant_id')
                    if variant_gid and 'ProductVariant/' in variant_gid:
                        variant_id = variant_gid.split('ProductVariant/')[-1]
                        break
            
            if not variant_id and variants:
                variant_gid = variants[0].get('variant_id')
                if variant_gid and 'ProductVariant/' in variant_gid:
                    variant_id = variant_gid.split('ProductVariant/')[-1]
        
        if not variant_id:
            continue
        
        # Format price
        price = product.get('price', 0)
        currency = product.get('currency', 'INR')
        
        if currency == 'INR':
            price_display = f"₹{price:,.0f}"
        else:
            price_display = f"{currency} {price}"
        
        carousel_product = {
            "id": product_id,
            "variant_id": variant_id,
            "title": product.get('title', 'Unknown Product'),
            "price": price_display,
            "image": product.get('image', ''),
            "handle": product.get('url', '').split('/')[-1] if product.get('url') else '',
            "url": product.get('url', ''),
            "available": product.get('inStock', True)
        }
        
        carousel_products.append(carousel_product)
    
    return carousel_products

def format_products_for_llm(mcp_products):
    """Format MCP products for LLM context"""
    if not mcp_products:
        return ""
    
    context_lines = [f"\n**🛍️ AVAILABLE PRODUCTS:**"]
    
    for i, product in enumerate(mcp_products[:6]):
        price = product.get('price', 0)
        currency = product.get('currency', 'INR')
        
        if currency == 'INR':
            price_display = f"₹{price:,.0f}"
        else:
            price_display = f"{currency} {price}"
        
        stock_status = "✅ In Stock" if product.get('inStock', True) else "❌ Out of Stock"
        
        context_lines.append(f"""
        Product {i+1}:
        - ID: {product.get('id')}
        - Title: {product.get('title')}
        - Price: {price_display}
        - Stock: {stock_status}
        - Description: {product.get('description', '')[:100]}...
        - Image: {product.get('image', '')}
        - URL: {product.get('url', '')}""")
    
    context_lines.append(f"\n**IMPORTANT:** Include products in 'product_carousel' array with exact data from above.")
    
    return "\n".join(context_lines)

# Main ask endpoint
@shopify_chat_bp.route('/ask', methods=['POST', 'OPTIONS'])
@require_widget_token
def shopify_ask_endpoint():
    """
    Main chat endpoint with hardcoded prompts and minimal logging
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get token data
        site_id = request.token_data['site_id']
        token_domain = request.token_data['domain']
        plan_type = request.token_data.get('plan_type', 'free')
        
        # Check rate limits
        if not rate_limit_service.check_rate_limit(site_id, plan_type):
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
        
        # Validate required fields
        if not all([messages, page_url, session_id]):
            return jsonify({
                "error": "Missing required fields",
                "message": "messages, page_url, and session_id are required"
            }), 400
        
        # Domain validation
        request_domain = domain_service.extract_domain_from_url(page_url)
        if not domain_service.domains_match(request_domain, token_domain):
            return jsonify({
                "error": "Domain mismatch",
                "message": "Request domain doesn't match token domain"
            }), 403
        
        # Get latest user message
        latest_user_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
        if not latest_user_msg:
            return jsonify({"error": "No user message found"}), 400
        
        latest_user_query = latest_user_msg["content"]
        
        # Insert user message into chat history
        insert_chat_message(site_id, session_id, user_id, page_url, "user", latest_user_query)
        
        # Prepare context for query rewriting
        recent_history = [m for m in messages if m["role"] in ("user", "assistant", "yuno")][-6:]
        
        # Rewrite query with context and detect language/intent
        rewrite_result = rewrite_query_with_context_and_language(recent_history, latest_user_query)
        rewritten_query = rewrite_result["rewritten_prompt"]
        detected_language = rewrite_result["ques_lang"]
        query_type = rewrite_result.get("query_type", "general_chat")
        needs_mcp = rewrite_result.get("needs_mcp", False)
        needs_embeddings = rewrite_result.get("needs_embeddings", True)
        search_parameters = rewrite_result.get("search_parameters", {})

        # Check if this is a Shopify store
        is_shopify = False
        shopify_domain = None
        try:
            site_info = site_model.get_site_by_id(site_id)
            if site_info and site_info.get('custom_config'):
                is_shopify = site_info['custom_config'].get('is_shopify', False)
                shopify_domain = site_info['custom_config'].get('shopify_domain')
        except Exception as e:
            logger.warning(f"Could not fetch site config for {site_id}: {e}")
        
        # Generate embedding for semantic search
        embedding = get_embedding(rewritten_query)
        
        # Initialize context holders
        matches = []
        mcp_context = {}

        # Perform semantic search if needed
        if needs_embeddings:
            matches = semantic_search(embedding, site_id)
        
        # MCP integration for Shopify stores
        if is_shopify and needs_mcp and shopify_domain:
            try:
                shopify_mcp_service.connect_sync(shopify_domain)
                
                # Get MCP tools and call appropriate one
                mcp_tools = shopify_mcp_service.list_tools()
                
                # Simple tool selection based on query type
                if query_type == "product_search":
                    # Call product search tool with search parameters
                    tool_args = {
                        "query": rewritten_query,
                        "limit": 6
                    }
                    if search_parameters.get('price_range'):
                        tool_args.update(search_parameters['price_range'])
                    
                    mcp_context = shopify_mcp_service._call_mcp_tool("search_products", tool_args) or {}
                
            except Exception as e:
                logger.error(f"MCP integration failed: {e}")

        # Build context from search results and MCP data
        embedding_context = "\n\n".join(
            match.get("detail") or match.get("text") or "" 
            for match in matches if match
        )

        # Build product context for Shopify
        product_context = ""
        filtered_products = []
        
        if mcp_context.get('products'):
            # Generate carousel products
            carousel_products = map_shopify_products_to_carousel(mcp_context)
            
            # Filter products by price if specified
            if search_parameters.get('price_range', {}).get('max'):
                max_budget = search_parameters['price_range']['max']
                
                for product in carousel_products:
                    price_str = product.get('price', '0')
                    try:
                        if price_str.startswith('₹'):
                            price_num = float(price_str.replace('₹', '').replace(',', ''))
                        else:
                            price_num = float(price_str.replace(',', ''))
                        
                        if price_num <= max_budget:
                            filtered_products.append(product)
                    except ValueError:
                        continue
                
                # Fallback to cheapest if none match budget
                if not filtered_products and carousel_products:
                    filtered_products = sorted(carousel_products, 
                        key=lambda x: float(x.get('price', '0').replace('₹', '').replace(',', '')))[:3]
            else:
                filtered_products = carousel_products
            
            # Create product context for LLM
            product_context = format_products_for_llm(mcp_context['products'])

        # Combine all contexts
        context = embedding_context + product_context

        # Prepare messages for OpenAI
        updated_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add recent conversation history
        recent_turns = [m for m in messages if m["role"] in ("user", "yuno", "assistant")][-4:]
        for m in recent_turns:
            updated_messages.append({
                "role": "user" if m["role"] == "user" else "assistant",
                "content": m["content"]
            })
        
        # Add language instruction if not English
        language_instruction = ""
        if detected_language != "english":
            language_map = {
                "spanish": "Spanish", "hindi": "Hindi", "bengali": "Bengali",
                "arabic": "Arabic", "french": "French", "german": "German",
                "portuguese": "Portuguese", "italian": "Italian"
            }
            lang_name = language_map.get(detected_language, detected_language.title())
            language_instruction = f"\n\nIMPORTANT: Respond in {lang_name}."

        # Build focused prompt
        context_label = "Relevant information" if is_shopify else "Relevant website content"
        focused_prompt = f"{latest_user_query}\n\n{context_label}:\n{context}{language_instruction}"

        # Add product instructions if available
        if filtered_products:
            product_instructions = f"""

🚨 CRITICAL: Include these {len(filtered_products)} products in 'product_carousel':
"""
            for i, product in enumerate(filtered_products[:3]):
                product_instructions += f"""
Product {i+1}: ID={product.get('id')}, Title={product.get('title')}, Price={product.get('price')}
"""
            focused_prompt += product_instructions

        # Add custom prompt if exists
        custom_prompt = get_site_custom_prompt(site_id)
        if custom_prompt:
            updated_messages.append({
                "role": "system",
                "content": custom_prompt
            })

        # Add final system prompt for JSON response
        updated_messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT_2
        })
        
        updated_messages.append({
            "role": "user",
            "content": focused_prompt
        })
        
        # Call OpenAI with hardcoded model
        completion = openai_client.chat.completions.create(
            model=HARDCODED_MAIN_MODEL,
            messages=updated_messages,
            temperature=0.5
        )
        
        raw_reply = completion.choices[0].message.content.strip()
        
        # Extract JSON from response
        match = re.search(r"\{.*\}", raw_reply, re.DOTALL)
        if not match:
            return jsonify({
                "error": "Model returned invalid JSON.", 
                "raw_reply": raw_reply
            }), 500

        try:
            reply_json = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            return jsonify({
                "error": "Invalid JSON response from AI",
                "raw_reply": raw_reply
            }), 500

        # Force include product carousel if we have products but LLM didn't include them
        if is_shopify and filtered_products and not reply_json.get("product_carousel"):
            reply_json["product_carousel"] = filtered_products[:3]
            if not reply_json.get("content"):
                reply_json["content"] = "Here are some great options for you:"

        # Validate required fields
        if not reply_json.get("content"):
            reply_json["content"] = "I'm here to help! How can I assist you today?"

        assistant_content = reply_json.get("content", raw_reply)
        
        # Insert assistant response into chat history
        insert_chat_message(
            site_id, session_id, user_id, page_url,
            "assistant", assistant_content,
            raw_json_output=json.dumps(reply_json)
        )
        
        # Handle lead capture
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

        return jsonify(reply_json)
        
    except Exception as e:
        # Basic error handling
        if "rate_limit" in str(e).lower():
            return jsonify({
                "error": "Service temporarily unavailable",
                "message": "Please try again in a moment"
            }), 503
        elif "invalid" in str(e).lower():
            return jsonify({
                "error": "Invalid request",
                "message": "Unable to process your message"
            }), 400
        else:
            logger.exception("Exception in /ask")
            return jsonify({
                "error": "Internal server error",
                "message": "Something went wrong processing your request"
            }), 500

@shopify_chat_bp.route('/cart/add', methods=['POST', 'OPTIONS'])
@require_widget_token
def add_to_cart():
    """Add product to cart using Shopify cart API"""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        site_id = request.token_data['site_id']
        
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON data required"}), 400
        
        merchandise_id = data.get("merchandise_id")
        quantity = data.get("quantity", 1)
        
        if not merchandise_id:
            return jsonify({"error": "merchandise_id required"}), 400
        
        # Get site configuration for Shopify domain
        site_info = site_model.get_site_by_id(site_id)
        if not site_info or not site_info.get('custom_config'):
            return jsonify({"error": "Site not configured for Shopify"}), 404
        
        shopify_domain = site_info['custom_config'].get('shopify_domain')
        if not shopify_domain:
            return jsonify({"error": "Shopify domain not configured"}), 404
        
        # Call Shopify cart API
        cart_url = f"https://{shopify_domain}/cart/add.js"
        cart_data = {
            "id": int(merchandise_id),
            "quantity": quantity
        }
        
        response = requests.post(
            cart_url,
            json=cart_data,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            timeout=10
        )
        
        if response.status_code == 200:
            cart_result = response.json()
            product_title = cart_result.get('title', 'Product')
            checkout_url = f"https://{shopify_domain}/cart"
            
            return jsonify({
                "success": True,
                "content": f'✅ Added "{product_title}" to your cart!<br><br><a href="{checkout_url}" target="_blank" style="background: var(--accent); color: #fff; padding: 10px 16px; border-radius: 8px; text-decoration: none; display: inline-block; font-weight: 600; margin-top: 8px;">🛒 View Cart & Checkout</a>',
                "cart": cart_result,
                "checkout_url": checkout_url,
                "merchandise_id": merchandise_id,
                "quantity": quantity,
                "product_title": product_title
            })
        else:
            return jsonify({
                "error": "Cart update failed",
                "message": f"Shopify API error: {response.status_code}"
            }), 400
                
    except Exception as e:
        logger.exception(f"Cart endpoint failed: {str(e)}")
        return jsonify({
            "error": "Internal server error",
            "message": "Cart operation failed"
        }), 500        }), 500