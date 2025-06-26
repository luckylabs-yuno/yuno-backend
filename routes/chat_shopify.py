from flask import Blueprint, request, jsonify
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

shopify_chat_bp = Blueprint('shopify_chat', __name__)
logger = logging.getLogger(__name__)

# Initialize services
jwt_service = JWTService()
domain_service = DomainService()
rate_limit_service = RateLimitService()
site_model = SiteModel()
shopify_mcp_service = ShopifyMCPService()  # ADD THIS LINE

# Environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MIXPANEL_TOKEN = os.getenv("MIXPANEL_TOKEN")

# Supabase function URL for semantic search
SUPABASE_FUNCTION_URL = f"{SUPABASE_URL}/rest/v1/rpc/yunosearch"

# Initialize OpenAI client (v1.0+ style)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize Mixpanel if token is available
mp = None
if MIXPANEL_TOKEN:
    try:
        from mixpanel import Mixpanel
        mp = Mixpanel(MIXPANEL_TOKEN)
    except ImportError:
        logger.warning("Mixpanel not available - install with: pip install mixpanel")


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
    site_id, session_id, user_id, page_url,
    role, content,
    raw_json_output=None,
    *,  # everything after * is optional & named
    lang=None,
    confidence=None,
    intent=None,
    tokens_used=None,
    follow_up=None,
    follow_up_prompt=None,
    sentiment=None,
    compliance_flag=None
):
    """Write one chat turn into chat_history (Supabase)"""
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

        # Core JSON blob for audit
        if raw_json_output is not None:
            payload["raw_json_output"] = raw_json_output

        # New analytic columns (insert only if not None)
        if lang is not None: 
            payload["lang"] = lang
        if confidence is not None: 
            payload["answer_confidence"] = confidence
        if intent is not None: 
            payload["intent"] = intent
        if tokens_used is not None: 
            payload["tokens_used"] = tokens_used
        if follow_up is not None: 
            payload["follow_up"] = follow_up
        if follow_up_prompt is not None: 
            payload["follow_up_prompt"] = follow_up_prompt
        if sentiment is not None: 
            payload["user_sentiment"] = sentiment
        if compliance_flag is not None: 
            payload["compliance_red_flag"] = compliance_flag

        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }

        logger.debug("Inserting chat message into Supabase: %s", payload)
        sentry_sdk.set_extra(f"supabase_chat_insert_{role}", payload)

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
        logger.debug("Inserting lead: %s", lead_data)
        sentry_sdk.set_extra("supabase_lead_data", lead_data)

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
    Enhanced query rewriter with better intent detection
    """
    try:
        chat_log = "\n".join([
            f"{'You' if m['role'] in ['assistant', 'yuno', 'bot'] else 'User'}: {m['content']}"
            for m in history
        ])

        # FIXED PROMPT with better examples and clearer instructions
        enhanced_prompt = f"""
        You are a JSON-only query analysis service. Analyze the user's query and determine intent, language, and data routing needs.

        CRITICAL RULES:
        1. Focus on the ACTUAL user intent, not assumed context
        2. Product questions = product_search (even if asking "do you have", "show me", "what are")
        3. Only classify as order_status if explicitly asking about existing orders or tracking
        4. Rewrite queries to be clearer but keep the original intent

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
        - price_range: {{"max": 2000}} if mentioned
        - category: "trimmer" if identifiable

        Language Detection:
        Detect the user's LATEST message language: english, spanish, hindi, bengali, arabic, french, german, portuguese, italian

        Chat History:
        {chat_log}

        User's Latest Message:
        {latest}

        ANALYZE THE QUERY CAREFULLY. Respond with valid JSON only:

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

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a precise query classifier. Focus on the user's actual intent, not assumed context. Product questions should always be classified as product_search."
                },
                {
                    "role": "user", 
                    "content": enhanced_prompt
                }
            ],
            temperature=0.1  # Lower temperature for more consistent classification
        )

        result_text = response.choices[0].message.content.strip()
        
        # Extract JSON
        match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if match:
            try:
                result_json = json.loads(match.group(0))
                
                # Log the classification for debugging
                logger.info(f"🔍 Query Classification:")
                logger.info(f"🔍   Original: '{latest}'")
                logger.info(f"🔍   Rewritten: '{result_json.get('rewritten_prompt', latest)}'")
                logger.info(f"🔍   Type: {result_json.get('query_type', 'unknown')}")
                logger.info(f"🔍   Language: {result_json.get('ques_lang', 'unknown')}")
                logger.info(f"🔍   Needs MCP: {result_json.get('needs_mcp', False)}")
                
                return {
                    "rewritten_prompt": result_json.get("rewritten_prompt", latest),
                    "ques_lang": result_json.get("ques_lang", "english"),
                    "query_type": result_json.get("query_type", "general_chat"),
                    "needs_mcp": result_json.get("needs_mcp", False),
                    "needs_embeddings": result_json.get("needs_embeddings", True),
                    "search_parameters": result_json.get("search_parameters", {})
                }
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse rewriter JSON: {e}")
                logger.error(f"Raw response: {result_text}")
                # Fallback with manual classification
                return classify_query_manually(latest)
        else:
            logger.error("No JSON found in rewriter response")
            return classify_query_manually(latest)
            
    except Exception as e:
        logger.warning("Enhanced query rewrite failed: %s", str(e))
        return classify_query_manually(latest)

def classify_query_manually(query: str) -> dict:
    """Manual fallback classification for when AI fails"""
    query_lower = query.lower()
    
    # Simple keyword-based classification
    if any(word in query_lower for word in ['trimmer', 'product', 'buy', 'price', 'cost', 'have', 'sell', 'available']):
        query_type = "product_search"
        needs_mcp = True
        needs_embeddings = False
        
        # Extract price if mentioned
        search_params = {}
        price_match = re.search(r'under\s+(\d+)', query_lower)
        if price_match:
            search_params["price_range"] = {"max": int(price_match.group(1))}
        
        # Extract product features
        features = []
        if 'trimmer' in query_lower:
            features.append('trimmer')
        if 'beard' in query_lower:
            features.append('beard')
        
        if features:
            search_params["product_features"] = features
            search_params["category"] = features[0]  # Use first feature as category
        
    elif any(word in query_lower for word in ['order', 'track', 'delivery', 'shipped']):
        query_type = "order_status"
        needs_mcp = True
        needs_embeddings = False
        search_params = {}
        
    elif any(word in query_lower for word in ['policy', 'return', 'shipping', 'warranty']):
        query_type = "policy_question"
        needs_mcp = True
        needs_embeddings = False
        search_params = {}
        
    else:
        query_type = "general_chat"
        needs_mcp = False
        needs_embeddings = True
        search_params = {}
    
    logger.info(f"🔍 Manual Classification: '{query}' → {query_type}")
    
    return {
        "rewritten_prompt": query,  # Keep original
        "ques_lang": "english",
        "query_type": query_type,
        "needs_mcp": needs_mcp,
        "needs_embeddings": needs_embeddings,
        "search_parameters": search_params
    }

# JWT Token Authentication Decorator
def require_widget_token(f):
    """Decorator to require valid JWT token"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Handle preflight requests
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
        
        # Add token payload to request for use in route
        request.token_data = payload
        return f(*args, **kwargs)
    
    return decorated_function

def generate_intelligent_follow_up(mcp_response, user_query, intent):
    """Generate context-aware follow-up prompts based on MCP results"""
    products = mcp_response.get('products', [])
    pagination = mcp_response.get('pagination', {})
    available_filters = mcp_response.get('available_filters', [])
    
    # No products found
    if not products:
        return {
            "follow_up": True,
            "follow_up_prompt": "I couldn't find exactly what you're looking for. Could you describe what you need in more detail?"
        }
    
    # Products found but many more available
    total_count = pagination.get('totalCount', 0)
    if pagination.get('hasNextPage') and total_count > 10:
        return {
            "follow_up": True, 
            "follow_up_prompt": f"I found {len(products)} products from {total_count} total. Would you like to see more or filter these results?"
        }
    
    # Perfect amount of products - ask for refinement
    if len(products) <= 3:
        return {
            "follow_up": True,
            "follow_up_prompt": "Do any of these catch your eye, or would you like me to find something more specific?"
        }
    
    # Many products - suggest filtering based on available filters
    if len(products) > 3 and available_filters:
        filter_suggestions = []
        for filter_group in available_filters[:2]:
            filter_type = filter_group.get('type', '')
            if filter_type == 'productType':
                filter_suggestions.append("product type")
            elif filter_type == 'vendor':
                filter_suggestions.append("brand")
            elif filter_type == 'variantOption':
                filter_suggestions.append("style or color")
            elif filter_type == 'price':
                filter_suggestions.append("price range")
        
        if filter_suggestions:
            suggestion_text = " or ".join(filter_suggestions[:2])
            return {
                "follow_up": True,
                "follow_up_prompt": f"I found several great options! Would you like me to filter by {suggestion_text}?"
            }
    
    # Default follow-up for other cases
    return {
        "follow_up": True,
        "follow_up_prompt": "Would you like more details about any of these products?"
    }
################################### NEW FILES ################################
# Replace these functions in chat_shopify.py

def map_shopify_products_to_carousel(mcp_response, max_products=3):
    """Map Shopify MCP response to unified contract product_carousel format"""
    if not mcp_response or not mcp_response.get('products'):
        return []
    
    products = mcp_response['products']
    carousel_products = []
    
    for product in products[:max_products]:
        # FIXED: Handle the actual MCP format, not Shopify variants
        # MCP format: product has direct price, currency, etc.
        
        # Extract price information directly from product
        price = product.get('price', 0)
        price_max = product.get('price_max')
        currency = product.get('currency', 'INR')
        
        # Format price properly
        if currency == 'INR':
            price_display = f"₹{price:,.0f}"
            compare_price_display = f"₹{price_max:,.0f}" if price_max and price_max != price else None
        elif currency == 'USD':
            price_display = f"${price:.2f}"
            compare_price_display = f"${price_max:.2f}" if price_max and price_max != price else None
        else:
            price_display = f"{currency} {price}"
            compare_price_display = f"{currency} {price_max}" if price_max and price_max != price else None
        
        # Build carousel product with correct data
        carousel_product = {
            "id": product.get('id', ''),
            "title": product.get('title', 'Unknown Product'),
            "price": price_display,
            "image": product.get('image', ''),
            "handle": product.get('url', '').split('/')[-1] if product.get('url') else '',
            "available": product.get('inStock', True)
        }
        
        # Add compare_at_price if we have a price range
        if compare_price_display:
            carousel_product["compare_at_price"] = compare_price_display
        
        carousel_products.append(carousel_product)
    
    return carousel_products

def format_products_for_llm(mcp_products):
    """Format MCP products for LLM context with structured product data"""
    if not mcp_products:
        return ""
    
    product_data = []
    for i, product in enumerate(mcp_products[:6]):  # Limit to 6 products
        # FIXED: Extract data from MCP format correctly
        price = product.get('price', 0)
        currency = product.get('currency', 'INR')
        
        # Format price properly
        if currency == 'INR':
            price_display = f"₹{price:,.0f}"
        elif currency == 'USD':
            price_display = f"${price:.2f}"
        else:
            price_display = f"{currency} {price}"
        
        product_info = {
            "id": product.get('id', f"product_{i}"),
            "title": product.get('title', 'Unknown Product'),
            "price": price,
            "price_display": price_display,
            "currency": currency,
            "inStock": product.get('inStock', True),
            "description": product.get('description', ''),
            "image": product.get('image', ''),
            "url": product.get('url', '')
        }
        product_data.append(product_info)
    
    # Create structured context for LLM
    context_lines = [f"\n**🛍️ AVAILABLE PRODUCTS FOR RECOMMENDATION:**"]
    
    for i, product in enumerate(product_data):
        # Stock status
        stock_status = "✅ In Stock" if product['inStock'] else "❌ Out of Stock"
        
        context_lines.append(f"""
        Product {i+1}:
        - ID: {product['id']}
        - Title: {product['title']}
        - Price: {product['price_display']}
        - Stock: {stock_status}
        - Description: {product['description'][:100]}...
        - Image: {product['image']}
        - URL: {product['url']}""")
    
    context_lines.append(f"\n**IMPORTANT:** When recommending products, include them in 'product_carousel' array with exact ID, title, price format from above.")
    
    return "\n".join(context_lines)

# REMOVE these functions as they're designed for different data format:
# - get_shopify_primary_image() 
# - format_shopify_price()

# Replace generate_dynamic_quick_replies to be simpler
def generate_dynamic_quick_replies(mcp_response, intent, query_type):
    """Generate contextual quick replies from MCP context"""
    quick_replies = []
    
    # Add product-specific actions if we have products
    if mcp_response.get('products'):
        quick_replies.extend(["Add to Cart", "See details"])
        
        # Add pagination option if more results available
        pagination = mcp_response.get('pagination', {})
        if pagination.get('hasNextPage') and len(quick_replies) < 3:
            quick_replies.append("See more")
    
    # Fallback options based on intent
    if len(quick_replies) < 2:
        if intent in ['ProductInquiry', 'PricingInquiry']:
            fallback_options = ["Browse products", "Get help", "Contact sales"]
        elif intent == 'SupportRequest':
            fallback_options = ["Email support", "Live chat", "Call us"]
        else:
            fallback_options = ["Help me choose", "See options", "Contact support"]
        
        # Add fallback options to fill up to 3 total
        for option in fallback_options:
            if len(quick_replies) < 3 and option not in quick_replies:
                quick_replies.append(option)
    
    return quick_replies[:3]  # Ensure max 3 replies

# Add debugging function to log product data transformation
def debug_product_mapping(mcp_context, carousel_products):
    """Debug function to log product mapping"""
    logger.info(f"🔍 ===== PRODUCT MAPPING DEBUG =====")
    
    mcp_products = mcp_context.get('products', [])
    logger.info(f"🔍 MCP Products Count: {len(mcp_products)}")
    
    for i, product in enumerate(mcp_products[:3]):
        logger.info(f"🔍 MCP Product {i+1}:")
        logger.info(f"🔍   - ID: {product.get('id')}")
        logger.info(f"🔍   - Title: {product.get('title')}")
        logger.info(f"🔍   - Price: {product.get('price')} {product.get('currency')}")
        logger.info(f"🔍   - InStock: {product.get('inStock')}")
        logger.info(f"🔍   - Image: {product.get('image', '')[:50]}...")
    
    logger.info(f"🔍 Carousel Products Count: {len(carousel_products)}")
    
    for i, product in enumerate(carousel_products):
        logger.info(f"🔍 Carousel Product {i+1}:")
        logger.info(f"🔍   - ID: {product.get('id')}")
        logger.info(f"🔍   - Title: {product.get('title')}")
        logger.info(f"🔍   - Price: {product.get('price')}")
        logger.info(f"🔍   - Available: {product.get('available')}")
        logger.info(f"🔍   - Image: {product.get('image', '')[:50]}...")
    
    logger.info(f"🔍 ===== PRODUCT MAPPING DEBUG END =====")

# Add this function to chat_shopify.py:

def validate_llm_products(llm_response, filtered_products):
    """Validate that LLM used the correct products and fix if needed"""
    if not llm_response.get("product_carousel") or not filtered_products:
        return llm_response
    
    llm_products = llm_response["product_carousel"]
    provided_product_ids = {p["id"] for p in filtered_products}
    
    logger.info(f"🔍 Validating LLM products...")
    logger.info(f"🔍 Expected product IDs: {provided_product_ids}")
    
    valid_products = []
    invalid_count = 0
    
    for i, llm_product in enumerate(llm_products):
        llm_id = llm_product.get("id", "")
        logger.info(f"🔍 LLM Product {i+1} ID: {llm_id}")
        
        if llm_id in provided_product_ids:
            # Valid product - LLM used correct data
            valid_products.append(llm_product)
            logger.info(f"🔍 ✅ Valid product: {llm_product.get('title')}")
        else:
            # Invalid product - LLM hallucinated
            invalid_count += 1
            logger.warning(f"🔍 ❌ Invalid product (hallucinated): {llm_product.get('title')} with ID {llm_id}")
            
            # Replace with correct product if available
            if i < len(filtered_products):
                correct_product = filtered_products[i]
                valid_products.append(correct_product)
                logger.info(f"🔍 🔧 Replaced with correct product: {correct_product.get('title')}")
    
    if invalid_count > 0:
        logger.warning(f"🔍 Fixed {invalid_count} hallucinated products")
        llm_response["product_carousel"] = valid_products
        
        # Update content to reflect correct products
        if valid_products:
            product_names = [p["title"] for p in valid_products[:2]]
            if len(product_names) == 1:
                llm_response["content"] = f"<b>Great choice!</b> We have the {product_names[0]} available under ₹2000!"
            else:
                llm_response["content"] = f"<b>Perfect!</b> Here are our {' and '.join(product_names)} under ₹2000!"
    
    return llm_response


# Enhanced /shopify/ask endpoint
@shopify_chat_bp.route('/ask', methods=['POST', 'OPTIONS'])
@require_widget_token
def shopify_ask_endpoint():  # Rename function too for clarity
    """
    Advanced chat endpoint with JWT authentication, semantic search, 
    lead capture, analytics tracking, and comprehensive logging
    """
    # Handle preflight
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get token data from middleware
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
        
        # Log incoming request
        logger.debug("Incoming /ask request: %s", json.dumps(data, indent=2))
        sentry_sdk.set_extra("incoming_request_data", data)
        
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
        
        # Additional domain validation from page_url
        request_domain = domain_service.extract_domain_from_url(page_url)
        if not domain_service.domains_match(request_domain, token_domain):
            logger.warning(f"Domain mismatch - Token: {token_domain}, Request: {request_domain}")
            return jsonify({
                "error": "Domain mismatch",
                "message": "Request domain doesn't match token domain"
            }), 403
        
        # Set up analytics tracking
        distinct_id = user_id or session_id or "anonymous"
        
        # Track with Mixpanel if available
        if mp:
            mp.track(distinct_id, "chat_history_received", {
                "site_id": site_id,
                "session_id": session_id,
                "chat_history": messages
            })
        
        # Set Sentry context
        with sentry_sdk.configure_scope() as scope:
            scope.set_tag("site_id", site_id)
            scope.set_tag("session_id", session_id)
            scope.set_user({"id": session_id})
        
        # Initialize analytic flags
        lang = None
        confidence = None
        intent_label = None
        tokens_used = None
        follow_up = None
        follow_up_prompt = None
        sentiment = None
        compliance_flag = None
        
        # Get latest user message
        latest_user_msg = next((m for m in reversed(messages) if m["role"] == "user"), None)
        if not latest_user_msg:
            return jsonify({"error": "No user message found"}), 400
        
        latest_user_query = latest_user_msg["content"]
        sentry_sdk.set_extra("user_query", latest_user_query)
        
        # Track user message
        if mp:
            mp.track(distinct_id, "user_message_received", {
                "site_id": site_id,
                "session_id": session_id,
                "page_url": page_url,
                "message": latest_user_query
            })
        
        # Insert user message into chat history
        insert_chat_message(site_id, session_id, user_id, page_url, "user", latest_user_query)
        
        # Prepare context for query rewriting
        recent_history = [m for m in messages if m["role"] in ("user", "assistant", "yuno")][-6:]
        
        # Track rewriter context
        if mp:
            mp.track(distinct_id, "rewriter_context", {
                "site_id": site_id,
                "session_id": session_id,
                "original_query": latest_user_query,
                "context_used": [
                    {
                        "role": "You" if m["role"] in ("assistant", "yuno") else "User",
                        "content": m["content"]
                    } for m in recent_history
                ]
            })
        

        # NEW: Rewrite query with context, detect language, and determine routing
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
            # Get site configuration
            site_info = site_model.get_site_by_id(site_id)
            if site_info and site_info.get('custom_config'):
                is_shopify = site_info['custom_config'].get('is_shopify', False)
                shopify_domain = site_info['custom_config'].get('shopify_domain')
        except Exception as e:
            logger.warning(f"Could not fetch site config for {site_id}: {e}")
        
        if mp:
            mp.track(distinct_id, "query_rewritten", {
                "site_id": site_id,
                "session_id": session_id,
                "original_query": latest_user_query,
                "detected_language": detected_language,
                "rewritten_query": rewritten_query,
                "chat_context_used": [
                    {
                        "role": "You" if m["role"] in ("assistant", "yuno") else "User",
                        "content": m["content"]
                    }
                    for m in recent_history
                ]
            })
        
        sentry_sdk.set_extra("rewritten_query", rewritten_query)
        
        # Generate embedding for semantic search
        embedding = get_embedding(rewritten_query)
        sentry_sdk.set_extra("embedding_vector_partial", embedding[:5])
        
        if mp:
            mp.track(distinct_id, "embedding_generated", {
                "original_query": latest_user_query,
                "rewritten_query": rewritten_query,
                "site_id": site_id,
                "embedding_preview": str(embedding[:5])
            })
        
        # Initialize context holders
        matches = []
        mcp_context = {}

        # Perform semantic search if needed
        if needs_embeddings:
            matches = semantic_search(embedding, site_id)
            sentry_sdk.set_extra("vector_search_results", matches[:3])
            
            if mp:
                mp.track(distinct_id, "vector_search_performed", {
                    "site_id": site_id,
                    "session_id": session_id,
                    "match_count": len(matches),
                    "top_matches": matches[:2]
                })
        else:
            logger.info(f"Skipping embeddings search for query type: {query_type}")



        # ===== ENHANCED MCP INTEGRATION WITH DETAILED LOGGING =====
        if is_shopify and needs_mcp and shopify_domain:
            logger.info("🛍️ ===== SHOPIFY MCP INTEGRATION START =====")
            logger.info(f"🛍️ Shopify store detected: {shopify_domain}")
            logger.info(f"🛍️ Query type: {query_type}")
            logger.info(f"🛍️ Original user query: '{latest_user_query}'")
            logger.info(f"🛍️ Rewritten query: '{rewritten_query}'")
            logger.info(f"🛍️ Search parameters: {json.dumps(search_parameters, indent=2)}")
            logger.info(f"🛍️ Needs embeddings: {needs_embeddings}")
            logger.info(f"🛍️ User language: {detected_language}")
            
            try:
                logger.info(f"🛍️ Attempting MCP connection...")
                
                # Ensure domain format is correct for MCP
                mcp_domain = shopify_domain
                original_domain = mcp_domain
                
                # Log domain processing
                logger.info(f"🛍️ Original domain from config: '{original_domain}'")
                
                # DON'T convert to .myshopify.com - use as-is for custom domains
                logger.info(f"🛍️ Using domain as-is for MCP: '{mcp_domain}'")
                logger.info(f"🛍️ Expected MCP URL: https://{mcp_domain}/api/mcp")
                
                # Connect to MCP
                logger.info(f"🛍️ Connecting to MCP server...")
                shopify_mcp_service.connect_sync(mcp_domain)
                logger.info(f"🛍️ MCP connection established")
                
                if query_type == 'product_search':
                    logger.info(f"🛍️ ===== PRODUCT SEARCH FLOW =====")
                    logger.info(f"🛍️ Processing product search request...")
                    logger.info(f"🛍️ Search query: '{rewritten_query}'")
                    
                    # Build context from search parameters with detailed logging
                    context_parts = []
                    logger.info(f"🛍️ Building search context...")
                    
                    if search_parameters.get('product_features'):
                        features = search_parameters['product_features']
                        context_part = f"Looking for {', '.join(features)}"
                        context_parts.append(context_part)
                        logger.info(f"🛍️ Added features to context: {features}")
                    
                    if search_parameters.get('price_range', {}).get('max'):
                        max_price = search_parameters['price_range']['max']
                        context_part = f"Budget up to {max_price}"
                        context_parts.append(context_part)
                        logger.info(f"🛍️ Added price limit to context: {max_price}")
                    
                    if search_parameters.get('category'):
                        category = search_parameters['category']
                        context_parts.append(f"Category: {category}")
                        logger.info(f"🛍️ Added category to context: {category}")
                    
                    context = ". ".join(context_parts) if context_parts else ""
                    logger.info(f"🛍️ Final search context: '{context}'")
                    
                    # Log the MCP call parameters
                    logger.info(f"🛍️ Calling MCP search_products_sync with:")
                    logger.info(f"🛍️   - query: '{rewritten_query}'")
                    logger.info(f"🛍️   - search_parameters: {search_parameters}")
                    logger.info(f"🛍️   - context: '{context}'")
                    
                    # Make the MCP call
                    logger.info(f"🛍️ Making MCP product search call...")
                    mcp_response = shopify_mcp_service.search_products_sync(
                        rewritten_query,
                        search_parameters,
                        context=context
                    )
                    logger.info(f"🛍️ MCP product search call completed")
                    
                    # Log the response in detail
                    logger.info(f"🛍️ MCP Response Analysis:")
                    logger.info(f"🛍️   - Has error: {mcp_response.get('error') is not None}")
                    logger.info(f"🛍️   - Error: {mcp_response.get('error')}")
                    logger.info(f"🛍️   - Products count: {len(mcp_response.get('products', []))}")
                    logger.info(f"🛍️   - Has pagination: {bool(mcp_response.get('pagination'))}")
                    logger.info(f"🛍️   - Has filters: {bool(mcp_response.get('filters'))}")
                    
                    # Log first few products for debugging
                    products = mcp_response.get('products', [])
                    if products:
                        logger.info(f"🛍️ First {min(3, len(products))} products:")
                        for i, product in enumerate(products[:3]):
                            title = product.get('title', 'No title')
                            price = product.get('price', 'No price')
                            currency = product.get('currency', '')
                            in_stock = product.get('inStock', 'Unknown')
                            logger.info(f"🛍️   {i+1}. '{title}' - {currency} {price} (Stock: {in_stock})")
                    
                    if mcp_response.get('error'):
                        logger.warning(f"🛍️ MCP product search failed: {mcp_response['error']}")
                        logger.info(f"🛍️ Falling back to embeddings search...")
                        
                        # Fallback to embeddings if MCP fails
                        if not matches:
                            logger.info(f"🛍️ No embeddings matches available, performing semantic search...")
                            matches = semantic_search(embedding, site_id)
                            logger.info(f"🛍️ Semantic search returned {len(matches)} matches")
                    else:
                        # Success! Store the MCP data
                        mcp_context['products'] = mcp_response.get('products', [])
                        mcp_context['pagination'] = mcp_response.get('pagination', {})
                        mcp_context['filters'] = mcp_response.get('filters', [])
                        
                        logger.info(f"🛍️ ✅ MCP product search successful!")
                        logger.info(f"🛍️ Stored {len(mcp_context['products'])} products in context")
                        
                        # Log pagination info
                        pagination = mcp_context.get('pagination', {})
                        if pagination:
                            current_page = pagination.get('currentPage', 1)
                            max_pages = pagination.get('maxPages', 'unknown')
                            has_next = pagination.get('hasNextPage', False)
                            logger.info(f"🛍️ Pagination: page {current_page} of {max_pages}, has_next: {has_next}")
                        
                        # Log filter info
                        filters = mcp_context.get('filters', [])
                        if filters:
                            logger.info(f"🛍️ Available filters: {len(filters)}")
                            for filter_item in filters:
                                filter_label = filter_item.get('label', 'Unknown')
                                logger.info(f"🛍️   - {filter_label}")
                    
                    # Track analytics
                    if mp:
                        mp.track(distinct_id, "mcp_product_search_detailed", {
                            "site_id": site_id,
                            "session_id": session_id,
                            "shopify_domain": mcp_domain,
                            "original_query": latest_user_query,
                            "rewritten_query": rewritten_query,
                            "search_parameters": search_parameters,
                            "context_used": context,
                            "product_count": len(mcp_context.get('products', [])),
                            "has_pagination": bool(mcp_context.get('pagination')),
                            "has_filters": bool(mcp_context.get('filters')),
                            "error": mcp_response.get('error'),
                            "query_type": query_type,
                            "detected_language": detected_language
                        })
                        
                elif query_type == 'policy_question':
                    logger.info(f"🛍️ ===== POLICY SEARCH FLOW =====")
                    logger.info(f"🛍️ Processing policy question...")
                    logger.info(f"🛍️ Policy query: '{rewritten_query}'")
                    
                    logger.info(f"🛍️ Calling MCP get_policies_sync...")
                    mcp_response = shopify_mcp_service.get_policies_sync(rewritten_query)
                    logger.info(f"🛍️ MCP policy search completed")
                    
                    # Log policy response
                    logger.info(f"🛍️ Policy Response Analysis:")
                    logger.info(f"🛍️   - Has error: {mcp_response.get('error') is not None}")
                    logger.info(f"🛍️   - Error: {mcp_response.get('error')}")
                    
                    policies = mcp_response.get('policies', {})
                    if policies:
                        logger.info(f"🛍️   - Policies found: {len(policies) if isinstance(policies, dict) else type(policies)}")
                        if isinstance(policies, dict):
                            for policy_key in policies.keys():
                                logger.info(f"🛍️     - {policy_key}")
                    
                    if mcp_response.get('error'):
                        logger.warning(f"🛍️ MCP policy search failed: {mcp_response['error']}")
                        logger.info(f"🛍️ Falling back to embeddings search...")
                        
                        # Fallback to embeddings
                        if not matches:
                            logger.info(f"🛍️ Performing semantic search for policy info...")
                            matches = semantic_search(embedding, site_id)
                            logger.info(f"🛍️ Semantic search returned {len(matches)} matches")
                    else:
                        mcp_context['policies'] = policies
                        logger.info(f"🛍️ ✅ MCP policy search successful!")
                    
                    # Track policy analytics
                    if mp:
                        mp.track(distinct_id, "mcp_policy_search_detailed", {
                            "site_id": site_id,
                            "session_id": session_id,
                            "shopify_domain": mcp_domain,
                            "policy_query": rewritten_query,
                            "policies_found": list(policies.keys()) if isinstance(policies, dict) else [],
                            "error": mcp_response.get('error'),
                            "query_type": query_type
                        })
                
                else:
                    logger.info(f"🛍️ Query type '{query_type}' does not require MCP processing")
                        
            except Exception as e:
                logger.error(f"🛍️ ===== MCP INTEGRATION EXCEPTION =====")
                logger.error(f"🛍️ Exception type: {type(e).__name__}")
                logger.error(f"🛍️ Exception message: {str(e)}")
                logger.error(f"🛍️ Shopify domain: {shopify_domain}")
                logger.error(f"🛍️ Query type: {query_type}")
                logger.error(f"🛍️ Search parameters: {search_parameters}")
                
                # Log full traceback
                import traceback
                logger.error(f"🛍️ Full traceback:")
                for line in traceback.format_exc().split('\n'):
                    if line.strip():
                        logger.error(f"🛍️   {line}")
                
                sentry_sdk.capture_exception(e)
                
                # Always fallback to embeddings if MCP fails
                logger.info(f"🛍️ Falling back to embeddings after exception...")
                if not matches:
                    logger.info(f"🛍️ Performing emergency semantic search...")
                    matches = semantic_search(embedding, site_id)
                    logger.info(f"🛍️ Emergency semantic search returned {len(matches)} matches")
                    
                if mp:
                    mp.track(distinct_id, "mcp_integration_exception", {
                        "site_id": site_id,
                        "shopify_domain": shopify_domain,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "query_type": query_type,
                        "search_parameters": search_parameters,
                        "fallback_matches": len(matches)
                    })
            
            logger.info(f"🛍️ ===== SHOPIFY MCP INTEGRATION END =====")
            logger.info(f"🛍️ Final MCP context: products={len(mcp_context.get('products', []))}, policies={bool(mcp_context.get('policies'))}")
        
        else:
            # Log why MCP was skipped
            if not is_shopify:
                logger.info(f"🛍️ Skipping MCP: Not a Shopify store")
            elif not needs_mcp:
                logger.info(f"🛍️ Skipping MCP: Query type '{query_type}' doesn't need MCP")
            elif not shopify_domain:
                logger.info(f"🛍️ Skipping MCP: No Shopify domain configured")
            else:
                logger.info(f"🛍️ Skipping MCP: Unknown reason (is_shopify={is_shopify}, needs_mcp={needs_mcp}, shopify_domain={shopify_domain})")



        if mp:
            mp.track(distinct_id, "vector_search_performed", {
                "site_id": site_id,
                "session_id": session_id,
                "match_count": len(matches),
                "top_matches": matches[:2]
            })
        
        
        # ===== CONTEXT BUILDING WITH DETAILED LOGGING =====
        logger.info(f"🔗 ===== CONTEXT BUILDING START =====")
        logger.info(f"🔗 Embedding matches: {len(matches)}")
        logger.info(f"🔗 MCP products: {len(mcp_context.get('products', []))}")
        logger.info(f"🔗 MCP policies: {bool(mcp_context.get('policies'))}")
        
        # Build context from search results and MCP data
        embedding_context = "\n\n".join(
            match.get("detail") or match.get("text") or "" 
            for match in matches if match
        )
        logger.info(f"🔗 Embedding context length: {len(embedding_context)} characters")

        # Enhanced product context for Shopify with detailed logging
        product_context = ""
        structured_product_data = None
        if mcp_context.get('products'):
            logger.info(f"🔗 Building product context from {len(mcp_context['products'])} products...")
            
            # Create both display context and structured data for LLM
            product_context = format_products_for_llm(mcp_context['products'])
            structured_product_data = mcp_context['products']  # Keep raw data for LLM access
            
            logger.info(f"🔗 Product context built: {len(product_context)} characters")

        # Policy context (if available)
        policy_context = ""
        if mcp_context.get('policies'):
            logger.info(f"🔗 Building policy context...")
            
            policy_lines = []
            policies = mcp_context['policies']
            
            if isinstance(policies, dict):
                for policy_type, policy_data in policies.items():
                    logger.debug(f"🔗 Processing policy: {policy_type}")
                    
                    if isinstance(policy_data, dict) and policy_data.get('content'):
                        content = policy_data['content'][:200] + "..." if len(policy_data['content']) > 200 else policy_data['content']
                        policy_lines.append(f"**{policy_type}**: {content}")
                    elif isinstance(policy_data, str):
                        content = policy_data[:200] + "..." if len(policy_data) > 200 else policy_data
                        policy_lines.append(f"**{policy_type}**: {content}")
            
            if policy_lines:
                policy_context = "\n\n**📋 Store Policies:**\n" + "\n".join(policy_lines)
                logger.info(f"🔗 Policy context built: {len(policy_context)} characters")

        # Combine all contexts
        context = embedding_context + product_context + policy_context
        logger.info(f"🔗 Total context length: {len(context)} characters")
        logger.info(f"🔗 Context breakdown: embeddings={len(embedding_context)}, products={len(product_context)}, policies={len(policy_context)}")
        logger.info(f"🔗 ===== CONTEXT BUILDING END =====")



        # Prepare messages for OpenAI
        updated_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add recent conversation history
        recent_turns = [m for m in messages if m["role"] in ("user", "yuno", "assistant")][-4:]
        for m in recent_turns:
            updated_messages.append({
                "role": "user" if m["role"] == "user" else "assistant",
                "content": m["content"]
            })
        
        # Fetch custom prompt for this site
        try:
            from supabase import create_client
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            resp = supabase\
                .table("custom_detail")\
                .select("site_prompt")\
                .eq("site_id", site_id)\
                .single()\
                .execute()
            custom_prompt = resp.data.get("site_prompt") if resp.data else None
        except Exception as e:
            logger.warning(f"Couldn't load custom_detail for site {site_id}: {e}")
            custom_prompt = None
        
        language_instruction = ""
        if detected_language != "english":
            language_map = {
                "spanish": "Spanish",
                "hindi": "Hindi", 
                "bengali": "Bengali",
                "arabic": "Arabic",
                "french": "French",
                "german": "German",
                "portuguese": "Portuguese",
                "italian": "Italian"
            }
            lang_name = language_map.get(detected_language, detected_language.title())
            language_instruction = f"\n\nIMPORTANT: The user wrote their message in {lang_name}. You MUST respond in {lang_name}. Write your entire 'content' field response in {lang_name}."


        # Build focused prompt with enhanced MCP intelligence
        context_label = "Relevant information" if is_shopify else "Relevant website content"
        focused_prompt = f"{latest_user_query}\n\n{context_label}:\n{context}{language_instruction}"


        # Enhanced Shopify-specific instructions with MCP intelligence
        if is_shopify and mcp_context:
            shopify_instructions = "\n\nYou have access to real-time product information and store policies."
            
            if mcp_context.get('products'):
                # Generate intelligent product carousel from MCP data
                carousel_products = map_shopify_products_to_carousel(mcp_context)
                
                # ADD DEBUG LOGGING HERE
                debug_product_mapping(mcp_context, carousel_products)
                
                # Generate dynamic quick replies based on available filters
                dynamic_quick_replies = generate_dynamic_quick_replies(
                    mcp_context, intent_label, query_type
                )
                
                # Generate intelligent follow-up based on result context
                follow_up_data = generate_intelligent_follow_up(
                    mcp_context, latest_user_query, intent_label
                )
                
                # Log the generated intelligence
                logger.info(f"🛍️ Generated {len(carousel_products)} carousel products")
                logger.info(f"🛍️ Generated quick replies: {dynamic_quick_replies}")
                logger.info(f"🛍️ Generated follow-up: {follow_up_data}")
                
                # IMPORTANT: Filter products by price if user specified budget
                filtered_products = carousel_products
                if search_parameters.get('price_range', {}).get('max'):
                    max_budget = search_parameters['price_range']['max']
                    logger.info(f"🔍 Filtering products by budget: ₹{max_budget}")
                    
                    filtered_products = []
                    for product in carousel_products:
                        # Extract numeric price from formatted string
                        price_str = product.get('price', '0')
                        if price_str.startswith('₹'):
                            try:
                                price_num = float(price_str.replace('₹', '').replace(',', ''))
                                if price_num <= max_budget:
                                    filtered_products.append(product)
                                    logger.info(f"🔍 ✅ Included: {product['title']} at ₹{price_num}")
                                else:
                                    logger.info(f"🔍 ❌ Excluded: {product['title']} at ₹{price_num} (over budget)")
                            except ValueError:
                                logger.warning(f"🔍 ⚠️ Could not parse price: {price_str}")
                                # Include anyway if we can't parse
                                filtered_products.append(product)
                
                logger.info(f"🔍 Final filtered products: {len(filtered_products)}")

                shopify_instructions += f"""

                🛍️ CRITICAL: USE ONLY THESE EXACT PRODUCTS - DO NOT MAKE UP ANY PRODUCTS

                YOU MUST USE THESE EXACT PRODUCTS (copy exactly as shown):
                {json.dumps(filtered_products, indent=2)}

                MANDATORY INSTRUCTIONS:
                1. You MUST use the exact "id", "title", "price", "image", "handle", "available" values from above
                2. You MUST NOT create any new product IDs or names
                3. You MUST NOT use placeholder products like "Basic Beard Trimmer" or "Product 10001"
                4. You MUST copy the product data exactly as provided above
                5. If you show products, they MUST be from the list above - no exceptions

                EXAMPLE CORRECT RESPONSE (use real data from above):
                {{
                  "product_carousel": [
                    {{
                      "id": "gid://shopify/Product/8406627549338",
                      "title": "Pro Beard Trimmer", 
                      "price": "₹1,000",
                      "image": "https://cdn.shopify.com/s/files/1/0459/6563/9834/files/pro_beard_kkk_32141c74-9f77-4950-8147-b277f74ed0c6.png?v=1748865085",
                      "handle": "pro-beard-trimmer",
                      "available": true
                    }}
                  ]
                }}

                QUICK REPLIES TO USE:
                {json.dumps(dynamic_quick_replies)}

                FOLLOW-UP:
                - follow_up: {follow_up_data['follow_up']}
                - follow_up_prompt: "{follow_up_data['follow_up_prompt']}"

                SEARCH CONTEXT:
                - Total products available: {mcp_context.get('pagination', {}).get('totalCount', 'unknown')}
                - Products matching budget: {len(filtered_products)} out of {len(carousel_products)}
                - User budget limit: ₹{search_parameters.get('price_range', {}).get('max', 'no limit')}

                CRITICAL REMINDER: Use ONLY the products listed above. Do not invent any product names, IDs, or details.
                """
                
            if mcp_context.get('policies'):
                shopify_instructions += f"""

                📋 STORE POLICIES AVAILABLE:
                You have access to store policy information including:
                {list(mcp_context['policies'].keys()) if isinstance(mcp_context.get('policies'), dict) else 'Policy data available'}
                """
            
            focused_prompt += shopify_instructions

        # Add site-specific custom prompt if available
        if custom_prompt:
            updated_messages.append({
                "role": "system",
                "content": custom_prompt
            })

        # Log the final enhanced prompt
        logger.info(f"🔗 Enhanced prompt built with MCP intelligence")
        logger.info(f"🔗 Prompt length: {len(focused_prompt)} characters")
        if mcp_context.get('products'):
            logger.info(f"🔗 Includes {len(carousel_products)} products for carousel")
        if mcp_context.get('available_filters'):
            logger.info(f"🔗 Includes {len(mcp_context['available_filters'])} filter groups")

        
        # Add final system prompt to ensure JSON response
        updated_messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT_2
        })
        # Add final language prompt to ensure JSON response
        updated_messages.append({
            "role": "system",
            "content": language_instruction
        })
        
        sentry_sdk.set_extra("gpt_prompt", focused_prompt)
        
        if mp:
            mp.track(distinct_id, "gpt_prompt_sent", {
                "site_id": site_id,
                "session_id": session_id,
                "full_prompt": focused_prompt
            })
        
        # Call OpenAI (v1.0+ syntax)
        completion = openai_client.chat.completions.create(
            model="gpt-4.1-mini-2025-04-14",
            messages=updated_messages,
            temperature=0.5
        )
        
        raw_reply = completion.choices[0].message.content.strip()
        sentry_sdk.set_extra("gpt_raw_reply", raw_reply)
        
        if mp:
            mp.track(distinct_id, "gpt_response_received", {
                "site_id": site_id,
                "session_id": session_id,
                "raw_reply": raw_reply
            })

        # Extract JSON from response with better error handling
        match = re.search(r"\{.*\}", raw_reply, re.DOTALL)
        if not match:
            logger.error(f"Model returned invalid JSON: {raw_reply}")
            return jsonify({
                "error": "Model returned invalid JSON.", 
                "raw_reply": raw_reply
            }), 500

        try:
            reply_json = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}, Raw: {raw_reply}")
            return jsonify({
                "error": "Invalid JSON response from AI",
                "raw_reply": raw_reply
            }), 500

        # ADD THIS VALIDATION HERE:
        if is_shopify and mcp_context.get('products'):
            reply_json = validate_llm_products(reply_json, filtered_products)

        # Validate required fields
        if not reply_json.get("content"):
            logger.error(f"Missing required 'content' field in response: {reply_json}")
            reply_json["content"] = "I'm here to help! How can I assist you today?"

        assistant_content = reply_json.get("content", raw_reply)

        # Log enhanced features usage
        if reply_json.get("product_carousel"):
            logger.info(f"🛍️ Response includes {len(reply_json['product_carousel'])} products in carousel")
            
        if reply_json.get("quick_replies"):
            logger.info(f"💬 Response includes {len(reply_json['quick_replies'])} quick replies: {reply_json['quick_replies']}")
            
        if reply_json.get("follow_up"):
            logger.info(f"🔄 Response includes follow-up: {reply_json.get('follow_up_prompt')}")

# Add this logging right after the LLM response is processed, around line 1650:

        # Enhanced logging to debug product issues
        if reply_json.get("product_carousel"):
            logger.info(f"🔍 ===== LLM PRODUCT RESPONSE DEBUG =====")
            llm_products = reply_json.get("product_carousel", [])
            logger.info(f"🔍 LLM returned {len(llm_products)} products:")
            
            for i, product in enumerate(llm_products):
                logger.info(f"🔍 LLM Product {i+1}:")
                logger.info(f"🔍   - ID: {product.get('id')}")
                logger.info(f"🔍   - Title: {product.get('title')}")
                logger.info(f"🔍   - Price: {product.get('price')}")
                logger.info(f"🔍   - Available: {product.get('available')}")
                logger.info(f"🔍   - Image: {product.get('image', '')[:50]}...")
            
            # Compare with original MCP data
            mcp_products = mcp_context.get('products', [])[:3]
            logger.info(f"🔍 Original MCP data (first 3):")
            for i, product in enumerate(mcp_products):
                logger.info(f"🔍 MCP Product {i+1}:")
                logger.info(f"🔍   - ID: {product.get('id')}")
                logger.info(f"🔍   - Title: {product.get('title')}")
                logger.info(f"🔍   - Price: {product.get('price')} {product.get('currency')}")
                logger.info(f"🔍   - InStock: {product.get('inStock')}")
            
            logger.info(f"🔍 ===== LLM PRODUCT RESPONSE DEBUG END =====")

# Also add this validation after JSON parsing:

        # Validate product data quality
        if reply_json.get("product_carousel"):
            products = reply_json["product_carousel"]
            for i, product in enumerate(products):
                # Check for required fields
                required_fields = ['id', 'title', 'price']
                missing_fields = [field for field in required_fields if not product.get(field)]
                
                if missing_fields:
                    logger.warning(f"🔍 Product {i+1} missing fields: {missing_fields}")
                    logger.warning(f"🔍 Product data: {product}")
                
                # Check for placeholder or generic data
                title = product.get('title', '')
                if any(placeholder in title.lower() for placeholder in ['unknown', 'placeholder', 'example']):
                    logger.warning(f"🔍 Product {i+1} has placeholder title: {title}")
                
                # Check price format
                price = product.get('price', '')
                if not price or price == '$0.00' or price == '₹0':
                    logger.warning(f"🔍 Product {i+1} has invalid price: {price}")
        
        # Add this check to see what the LLM actually received
        logger.info(f"🔍 LLM received prompt length: {len(focused_prompt)} characters")
        if "PRODUCTS TO INCLUDE IN CAROUSEL" in focused_prompt:
            # Extract the JSON section that was sent to LLM
            start = focused_prompt.find("PRODUCTS TO INCLUDE IN CAROUSEL")
            end = focused_prompt.find("SUGGESTED QUICK_REPLIES", start)
            if start != -1 and end != -1:
                products_section = focused_prompt[start:end]
                logger.info(f"🔍 Products section sent to LLM:")
                logger.info(f"🔍 {products_section[:500]}...")  # First 500 chars
       
        # Extract analytic flags from response
        lang = reply_json.get("lang")
        confidence = reply_json.get("answer_confidence")
        intent_label = reply_json.get("intent")
        tokens_used = reply_json.get("tokens_used")
        follow_up = reply_json.get("follow_up")
        follow_up_prompt = reply_json.get("follow_up_prompt")
        sentiment = reply_json.get("user_sentiment")
        compliance_flag = reply_json.get("compliance_red_flag")
        
        # Insert assistant response into chat history
        insert_chat_message(
            site_id, session_id, user_id, page_url,
            "assistant", assistant_content,
            raw_json_output=json.dumps(reply_json),
            lang=detected_language,  # Store detected language
            confidence=confidence,
            intent=intent_label,
            tokens_used=tokens_used,
            follow_up=follow_up,
            follow_up_prompt=follow_up_prompt,
            sentiment=sentiment,
            compliance_flag=compliance_flag
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
            
            if mp:
                mp.track(distinct_id, "lead_captured", lead_data)
        
        # Update rate limit counter
        rate_limit_service.increment_usage(site_id, plan_type)
        
        # Final tracking
        sentry_sdk.set_extra("frontend_response_payload", reply_json)
        


        if mp:
            mp.track(distinct_id, "bot_reply_sent", {
                "session_id": session_id,
                "site_id": site_id,
                "content": assistant_content,
                "lead_triggered": reply_json.get("leadTriggered", False),
                "is_shopify": is_shopify,
                "query_type": query_type,
                "used_mcp": needs_mcp and is_shopify,
                "used_embeddings": needs_embeddings
            })
        
        # Track enhanced features usage
        if mp:
            mp.track(distinct_id, "enhanced_features_used", {
                "site_id": site_id,
                "session_id": session_id,
                "has_product_carousel": bool(reply_json.get("product_carousel")),
                "product_count": len(reply_json.get("product_carousel", [])),
                "has_quick_replies": bool(reply_json.get("quick_replies")),
                "quick_replies_count": len(reply_json.get("quick_replies", [])),
                "has_follow_up": reply_json.get("follow_up", False),
                "intent": reply_json.get("intent"),
                "confidence": reply_json.get("answer_confidence"),
                "is_shopify": is_shopify,
                "used_mcp_products": bool(mcp_context.get('products'))
            })

        return jsonify(reply_json)
        
    except Exception as e:
        # Updated exception handling for OpenAI v1.0+
        if "rate_limit" in str(e).lower():
            logger.error("OpenAI rate limit exceeded")
            return jsonify({
                "error": "Service temporarily unavailable",
                "message": "Please try again in a moment"
            }), 503
        elif "invalid" in str(e).lower():
            logger.error(f"OpenAI invalid request: {str(e)}")
            return jsonify({
                "error": "Invalid request",
                "message": "Unable to process your message"
            }), 400
        else:
            sentry_sdk.capture_exception(e)
            if mp:
                mp.track(distinct_id, "server_error", {
                    "site_id": site_id,
                    "error": str(e),
                    "lang": lang,
                    "intent": intent_label
                })
            logger.exception("Exception in /ask")
            return jsonify({
                "error": "Internal server error",
                "message": "Something went wrong processing your request"
            }), 500

# Health check endpoint
@shopify_chat_bp.route('/health', methods=['GET', 'OPTIONS'])
def shopify_chat_health():
    """Health check for chat service"""
    return jsonify({
        "status": "healthy",
        "service": "chat",
        "timestamp": datetime.utcnow().isoformat()
    })

# Debug endpoints
@shopify_chat_bp.route('/debug', methods=['GET', 'OPTIONS'])
def shopify_debug_components():
    """Debug endpoint to test all components and environment"""
    debug_info = {
        "timestamp": datetime.utcnow().isoformat(),
        "env_vars": {},
        "imports": {},
        "services": {},
        "connections": {},
        "errors": []
    }
    
    # Check environment variables
    env_vars_to_check = [
        'SUPABASE_URL', 'SUPABASE_KEY', 'OPENAI_API_KEY', 
        'JWT_SECRET', 'REDIS_URL', 'MIXPANEL_TOKEN', 'SENTRY_DSN'
    ]
    
    for var in env_vars_to_check:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if 'KEY' in var or 'SECRET' in var or 'DSN' in var:
                debug_info["env_vars"][var] = f"SET (***{value[-4:]})"
            else:
                debug_info["env_vars"][var] = f"SET ({value[:20]}...)"
        else:
            debug_info["env_vars"][var] = "MISSING"
    
    # Test OpenAI connection
    try:
        if OPENAI_API_KEY:
            if OPENAI_API_KEY.startswith('sk-'):
                debug_info["connections"]["openai"] = "API Key format OK"
            else:
                debug_info["connections"]["openai"] = "Invalid API key format"
        else:
            debug_info["connections"]["openai"] = "No API key"
    except Exception as e:
        debug_info["connections"]["openai"] = f"ERROR: {str(e)}"
        debug_info["errors"].append(f"OpenAI: {str(e)}")
    
    # Test Supabase connection
    try:
        if SUPABASE_URL and SUPABASE_KEY:
            from supabase import create_client
            supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
            debug_info["connections"]["supabase"] = "Client created OK"
        else:
            debug_info["connections"]["supabase"] = "Missing credentials"
    except Exception as e:
        debug_info["connections"]["supabase"] = f"ERROR: {str(e)}"
        debug_info["errors"].append(f"Supabase: {str(e)}")
    
    # Summary
    debug_info["summary"] = {
        "total_errors": len(debug_info["errors"]),
        "critical_missing": [var for var, status in debug_info["env_vars"].items() 
                           if status == "MISSING" and var in ['OPENAI_API_KEY', 'SUPABASE_URL', 'SUPABASE_KEY']],
        "status": "READY" if len(debug_info["errors"]) == 0 else "ISSUES_FOUND"
    }
    
    return jsonify(debug_info)

@shopify_chat_bp.route('/debug/ask-simple', methods=['POST', 'OPTIONS'])
@require_widget_token
def shopify_debug_ask_simple():
    """Simplified ask endpoint with detailed error logging"""
    debug_steps = []
    
    try:
        # Step 1: Get request data
        debug_steps.append("1. Getting request data...")
        data = request.get_json()
        debug_steps.append(f"1. ✅ Request data received: {list(data.keys()) if data else 'None'}")
        
        if not data:
            return jsonify({
                "error": "No JSON data",
                "debug_steps": debug_steps
            }), 400
        
        # Step 2: Extract token data
        debug_steps.append("2. Extracting token data...")
        site_id = request.token_data.get('site_id')
        token_domain = request.token_data.get('domain')
        plan_type = request.token_data.get('plan_type', 'free')
        debug_steps.append(f"2. ✅ Token data: site_id={site_id}, domain={token_domain}, plan={plan_type}")
        
        # Step 3: Test rate limiting
        debug_steps.append("3. Testing rate limiting...")
        try:
            rate_check = rate_limit_service.check_rate_limit(site_id, plan_type)
            debug_steps.append(f"3. ✅ Rate limit check: {rate_check}")
        except Exception as e:
            debug_steps.append(f"3. ❌ Rate limit error: {str(e)}")
            return jsonify({
                "error": "Rate limiting failed",
                "debug_steps": debug_steps,
                "rate_limit_error": str(e)
            }), 500
        
        # Step 4: Validate required fields
        debug_steps.append("4. Validating required fields...")
        required_fields = ['messages', 'page_url', 'session_id']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            debug_steps.append(f"4. ❌ Missing fields: {missing_fields}")
            return jsonify({
                "error": "Missing required fields",
                "missing_fields": missing_fields,
                "debug_steps": debug_steps
            }), 400
        
        debug_steps.append("4. ✅ All required fields present")
        
        # Step 5: Test OpenAI
        debug_steps.append("5. Testing OpenAI...")
        try:
            if not OPENAI_API_KEY:
                raise Exception("OPENAI_API_KEY not set")
            
            debug_steps.append("5. ✅ OpenAI key set")
            
            # Test with a simple completion (v1.0+ syntax)
            test_response = openai_client.chat.completions.create(
                model="gpt-4o-mini-2024-07-18",
                messages=[{"role": "user", "content": "Say 'test successful'"}],
                max_tokens=10
            )
            
            debug_steps.append("5. ✅ OpenAI API call successful")
            
        except Exception as e:
            debug_steps.append(f"5. ❌ OpenAI error: {str(e)}")
            return jsonify({
                "error": "OpenAI API failed",
                "debug_steps": debug_steps,
                "openai_error": str(e)
            }), 500
        
        # Step 6: Return success
        debug_steps.append("6. ✅ All tests passed!")
        
        return jsonify({
            "status": "success",
            "message": "All components working correctly",
            "debug_steps": debug_steps,
            "test_data": {
                "site_id": site_id,
                "messages_count": len(data.get("messages", [])),
                "openai_test": test_response.choices[0].message.content if 'test_response' in locals() else "Not tested"
            }
        })
        
    except Exception as e:
        debug_steps.append(f"❌ FATAL ERROR: {str(e)}")
        logger.exception("Debug ask simple failed")
        
        return jsonify({
            "error": "Internal server error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "debug_steps": debug_steps
        }), 500