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

chat_bp = Blueprint('chat', __name__)
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

⚠️ CRITICAL: When product_carousel data is provided in the context, you MUST use the EXACT product information given. Do NOT create, modify, or hallucinate any product details.

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
      "id": "<EXACT_ID_FROM_CONTEXT>",
      "title": "<EXACT_TITLE_FROM_CONTEXT>",
      "price": "<EXACT_PRICE_FROM_CONTEXT>",
      "compare_at_price": "<EXACT_COMPARE_PRICE_FROM_CONTEXT>",
      "image": "<EXACT_IMAGE_FROM_CONTEXT>",
      "handle": "<EXACT_HANDLE_FROM_CONTEXT>",
      "available": <EXACT_AVAILABILITY_FROM_CONTEXT>
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

🚨 PRODUCT CAROUSEL CRITICAL RULES:
- NEVER create fake products or modify provided product data
- Use ONLY the exact product information from the context
- Copy product details EXACTLY as provided (id, title, price, image, handle, available)
- If no products provided, do NOT include product_carousel field
- Max 3 products typically

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

def get_shopify_primary_image(images):
    """Get the primary product image URL from Shopify images array"""
    if not images:
        return ""
    
    # Handle different image structures
    first_image = images[0]
    if isinstance(first_image, dict):
        return first_image.get('url', first_image.get('src', ''))
    return str(first_image)

def map_shopify_products_to_carousel(mcp_response, max_products=3):
    """Map REAL Shopify MCP response to unified contract product_carousel format"""
    if not mcp_response or not mcp_response.get('products'):
        return []
    
    products = mcp_response['products']
    carousel_products = []
    
    for product in products[:max_products]:
        # Use the REAL API structure
        product_id = product.get('product_id', '')
        title = product.get('title', 'Unknown Product')
        
        # Handle REAL price structure
        price_range = product.get('price_range', {})
        price_display = format_shopify_price_range(price_range)
        
        # Handle REAL variants structure  
        variants = product.get('variants', [])
        first_variant = variants[0] if variants else {}
        variant_id = first_variant.get('variant_id', product_id)
        available = first_variant.get('available', True)
        
        # Build carousel product with REAL data structure
        carousel_product = {
            "id": variant_id or product_id,  # Use variant_id for add-to-cart
            "title": title,
            "price": price_display,
            "image": product.get('image_url', ''),  # Real field name
            "handle": extract_handle_from_url(product.get('url', '')),
            "available": available,
            "product_url": product.get('url', '')  # Store full URL for navigation
        }
        
        carousel_products.append(carousel_product)
        
        # Log the mapped product for debugging
        logger.debug(f"🛍️ Mapped product: {title} - {price_display} (Available: {available})")
    
    return carousel_products

def format_shopify_price_range(price_range):
    """Format REAL Shopify price_range object to display string"""
    if not price_range:
        return "Price not available"
    
    min_price = price_range.get('min', '0')
    max_price = price_range.get('max', '0')
    currency = price_range.get('currency', 'INR')
    
    try:
        min_val = float(min_price)
        max_val = float(max_price)
        
        # Format based on currency
        if currency == 'INR':
            if min_val == max_val:
                return f"₹{min_val:,.0f}"
            else:
                return f"₹{min_val:,.0f} - ₹{max_val:,.0f}"
        elif currency == 'USD':
            if min_val == max_val:
                return f"${min_val:.2f}"
            else:
                return f"${min_val:.2f} - ${max_val:.2f}"
        else:
            if min_val == max_val:
                return f"{currency} {min_val:.2f}"
            else:
                return f"{currency} {min_val:.2f} - {max_val:.2f}"
                
    except (ValueError, TypeError):
        return f"{currency} {min_price}"

def extract_handle_from_url(url):
    """Extract product handle from full Shopify URL"""
    if not url:
        return ""
    
    # Extract handle from URL like: https://store.com/products/product-handle
    if '/products/' in url:
        return url.split('/products/')[-1].split('?')[0]
    
    return ""

def generate_dynamic_quick_replies(mcp_response, intent, query_type):
    """Generate contextual quick replies from REAL MCP available_filters"""
    quick_replies = []
    
    # Add product-specific actions if we have products
    if mcp_response.get('products'):
        quick_replies.extend(["Add to Cart", "See details"])
        
        # Add filter-based options from available_filters (REAL structure)
        available_filters = mcp_response.get('available_filters', [])
        
        for filter_group in available_filters:
            filter_label = filter_group.get('label', '')
            values = filter_group.get('values', {})
            
            if filter_label == 'Category' and len(quick_replies) < 3:
                # Get category options
                labels = values.get('label', [])[:2]  # First 2 categories
                for label in labels:
                    if len(quick_replies) < 3 and len(label) <= 20:
                        quick_replies.append(f"Show {label}")
    
    # Add pagination option if more results available
    pagination = mcp_response.get('pagination', {})
    if pagination.get('hasNextPage') and len(quick_replies) < 3:
        quick_replies.append("See more")
    
    # Ensure we have fallback options
    if len(quick_replies) < 2:
        fallback_options = ["Browse products", "Get help", "Contact sales"]
        for option in fallback_options:
            if len(quick_replies) < 3:
                quick_replies.append(option)
    
    return quick_replies[:3]

def generate_intelligent_follow_up(mcp_response, user_query, intent):
    """Generate context-aware follow-up prompts based on REAL MCP results"""
    products = mcp_response.get('products', [])
    pagination = mcp_response.get('pagination', {})
    
    # No products found
    if not products:
        return {
            "follow_up": True,
            "follow_up_prompt": "I couldn't find exactly what you're looking for. Could you describe what you need in more detail?"
        }
    
    # Products found but many more available
    max_pages = pagination.get('maxPages', 0)
    current_page = pagination.get('currentPage', 1)
    
    if pagination.get('hasNextPage') and max_pages > 10:
        return {
            "follow_up": True, 
            "follow_up_prompt": f"I found {len(products)} products from page {current_page} of {max_pages}. Would you like to see more or filter these results?"
        }
    
    # Perfect amount of products - ask for refinement
    if len(products) <= 3:
        return {
            "follow_up": True,
            "follow_up_prompt": "Do any of these catch your eye, or would you like me to find something more specific?"
        }
    
    # Many products - suggest filtering
    if len(products) > 3:
        return {
            "follow_up": True,
            "follow_up_prompt": f"I found {len(products)} great options! Would you like me to help you narrow them down by price range or category?"
        }
    
    # Default follow-up
    return {
        "follow_up": True,
        "follow_up_prompt": "Would you like more details about any of these products?"
    }

def format_products_for_llm_context(mcp_response):
    """Format REAL MCP products for LLM context with structured data"""
    if not mcp_response or not mcp_response.get('products'):
        return ""
    
    products = mcp_response['products']
    context_lines = [f"\n**🛍️ AVAILABLE PRODUCTS FOR RECOMMENDATION:**"]
    
    for i, product in enumerate(products[:6]):  # Limit to 6 products
        title = product.get('title', 'Unknown Product')
        price_range = product.get('price_range', {})
        price_display = format_shopify_price_range(price_range)
        
        variants = product.get('variants', [])
        first_variant = variants[0] if variants else {}
        available = first_variant.get('available', True)
        variant_id = first_variant.get('variant_id', product.get('product_id', ''))
        
        stock_status = "✅ In Stock" if available else "❌ Out of Stock"
        
        context_lines.append(f"""
          Product {i+1}:
          - ID: {variant_id}
          - Title: {title}
          - Price: {price_display}
          - Stock: {stock_status}
          - Image: {product.get('image_url', '')}
          - URL: {product.get('url', '')}""")
    
    context_lines.append(f"\n**IMPORTANT:** When recommending products, include them in 'product_carousel' array with exact ID, title, price format from above.")
    
    return "\n".join(context_lines)

# Enhanced /ask endpoint
@chat_bp.route('/ask', methods=['POST', 'OPTIONS'])
@require_widget_token
def advanced_ask_endpoint():
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


        # ===== CORRECTED MCP INTEGRATION FOR REAL SHOPIFY API =====
        if is_shopify and needs_mcp and shopify_domain:
            logger.info("🛍️ ===== SHOPIFY MCP INTEGRATION START =====")
            logger.info(f"🛍️ Shopify store detected: {shopify_domain}")
            logger.info(f"🛍️ Query type: {query_type}")
            logger.info(f"🛍️ Original user query: '{latest_user_query}'")
            logger.info(f"🛍️ Rewritten query: '{rewritten_query}'")
            logger.info(f"🛍️ Search parameters: {json.dumps(search_parameters, indent=2)}")
            logger.info(f"🛍️ User language: {detected_language}")
            
            try:
                logger.info(f"🛍️ Connecting to MCP server...")
                shopify_mcp_service.connect_sync(shopify_domain)
                logger.info(f"🛍️ MCP connection established")
                
                if query_type == 'product_search':
                    logger.info(f"🛍️ ===== PRODUCT SEARCH WITH REAL API =====")
                    
                    # Build enhanced context for personalization
                    context_parts = []
                    if search_parameters.get('product_features'):
                        features = search_parameters['product_features']
                        context_parts.append(f"Looking for {', '.join(features)}")
                    
                    if search_parameters.get('price_range', {}).get('max'):
                        max_price = search_parameters['price_range']['max']
                        context_parts.append(f"Budget up to {max_price}")
                    
                    if search_parameters.get('category'):
                        category = search_parameters['category']
                        context_parts.append(f"Category: {category}")
                    
                    user_context = f"User query: '{rewritten_query}'. "
                    if context_parts:
                        user_context += ". ".join(context_parts) + ". "
                    user_context += "Help find the best products for their needs."
                    
                    # Use the REAL Shopify MCP tool with correct parameters
                    mcp_call_params = {
                        "query": rewritten_query,
                        "context": user_context,
                        "limit": 10,
                        "country": "IN",  # India for INR currency
                        "language": "EN"
                    }
                    
                    logger.info(f"🛍️ Calling search_shop_catalog with REAL API params:")
                    logger.info(f"🛍️   {json.dumps(mcp_call_params, indent=2)}")
                    
                    # Make the MCP call using the correct method
                    mcp_response = shopify_mcp_service.call_tool("search_shop_catalog", mcp_call_params)
                    logger.info(f"🛍️ MCP search_shop_catalog call completed")
                    
                    # Parse the REAL response structure
                    if isinstance(mcp_response, dict) and 'content' in mcp_response:
                        # Extract from the content wrapper
                        content = mcp_response['content']
                        if isinstance(content, list) and len(content) > 0:
                            content_text = content[0].get('text', '{}')
                            try:
                                parsed_response = json.loads(content_text)
                                mcp_response = parsed_response
                            except json.JSONDecodeError:
                                logger.error(f"🛍️ Failed to parse MCP response JSON")
                                mcp_response = {}
                    
                    # Log the REAL response structure
                    logger.info(f"🛍️ REAL MCP Response Analysis:")
                    logger.info(f"🛍️   - Has error: {mcp_response.get('error') is not None}")
                    logger.info(f"🛍️   - Products count: {len(mcp_response.get('products', []))}")
                    logger.info(f"🛍️   - Has pagination: {bool(mcp_response.get('pagination'))}")
                    logger.info(f"🛍️   - Has available_filters: {bool(mcp_response.get('available_filters'))}")
                    
                    # Log sample products with REAL structure
                    products = mcp_response.get('products', [])
                    if products:
                        logger.info(f"🛍️ First 3 REAL products:")
                        for i, product in enumerate(products[:3]):
                            title = product.get('title', 'No title')
                            price_range = product.get('price_range', {})
                            price_display = format_shopify_price_range(price_range)
                            
                            variants = product.get('variants', [])
                            available = variants[0].get('available', True) if variants else True
                            
                            logger.info(f"🛍️   {i+1}. '{title}' - {price_display} (Available: {available})")
                    
                    if mcp_response.get('error'):
                        logger.warning(f"🛍️ MCP product search failed: {mcp_response['error']}")
                        
                        # Fallback to embeddings
                        if not matches:
                            matches = semantic_search(embedding, site_id)
                            logger.info(f"🛍️ Fallback semantic search returned {len(matches)} matches")
                    else:
                        # Success! Store the REAL MCP data
                        mcp_context.update({
                            'products': products,
                            'available_filters': mcp_response.get('available_filters', []),
                            'pagination': mcp_response.get('pagination', {}),
                            'instructions': mcp_response.get('instructions', '')
                        })
                        
                        logger.info(f"🛍️ ✅ REAL MCP product search successful!")
                        logger.info(f"🛍️ Stored {len(products)} products")
                        logger.info(f"🛍️ Available filter groups: {len(mcp_context['available_filters'])}")
                        
                        # Log pagination with REAL structure
                        pagination = mcp_context.get('pagination', {})
                        if pagination:
                            current_page = pagination.get('currentPage', 1)
                            max_pages = pagination.get('maxPages', 'unknown')
                            has_next = pagination.get('hasNextPage', False)
                            logger.info(f"🛍️ Pagination: page {current_page} of {max_pages}, hasNext={has_next}")
                        
                        # Log available filters with REAL structure
                        available_filters = mcp_context.get('available_filters', [])
                        if available_filters:
                            logger.info(f"🛍️ Available filter types:")
                            for filter_group in available_filters:
                                filter_label = filter_group.get('label', 'unknown')
                                values = filter_group.get('values', {})
                                value_count = len(values.get('label', []))
                                logger.info(f"🛍️   - {filter_label}: {value_count} options")
                    
                    # Enhanced analytics with REAL data
                    if mp:
                        mp.track(distinct_id, "real_mcp_product_search", {
                            "site_id": site_id,
                            "session_id": session_id,
                            "shopify_domain": shopify_domain,
                            "original_query": latest_user_query,
                            "rewritten_query": rewritten_query,
                            "search_parameters": search_parameters,
                            "context_used": user_context,
                            "product_count": len(products),
                            "filter_groups": len(mcp_context.get('available_filters', [])),
                            "has_pagination": bool(mcp_context.get('pagination', {}).get('hasNextPage')),
                            "max_pages": mcp_context.get('pagination', {}).get('maxPages', 0),
                            "error": mcp_response.get('error'),
                            "query_type": query_type
                        })
                                
                elif query_type == 'policy_question':
                    logger.info(f"🛍️ ===== POLICY SEARCH WITH REAL API =====")
                    
                    policy_params = {
                        "query": rewritten_query,
                        "context": f"User is asking about: {latest_user_query}"
                    }
                    
                    logger.info(f"🛍️ Calling search_shop_policies_and_faqs...")
                    mcp_response = shopify_mcp_service.call_tool("search_shop_policies_and_faqs", policy_params)
                    
                    # Parse policy response (similar structure handling)
                    if isinstance(mcp_response, dict) and 'content' in mcp_response:
                        content = mcp_response['content']
                        if isinstance(content, list) and len(content) > 0:
                            content_text = content[0].get('text', '{}')
                            try:
                                parsed_response = json.loads(content_text)
                                mcp_response = parsed_response
                            except json.JSONDecodeError:
                                mcp_response = {}
                    
                    logger.info(f"🛍️ Policy search completed")
                    
                    if mcp_response.get('error'):
                        logger.warning(f"🛍️ MCP policy search failed: {mcp_response['error']}")
                        if not matches:
                            matches = semantic_search(embedding, site_id)
                    else:
                        mcp_context['policies'] = mcp_response.get('policies', {})
                        logger.info(f"🛍️ ✅ MCP policy search successful!")
                
                else:
                    logger.info(f"🛍️ Query type '{query_type}' does not require MCP processing")
                            
            except Exception as e:
                logger.error(f"🛍️ ===== MCP INTEGRATION EXCEPTION =====")
                logger.error(f"🛍️ Exception: {str(e)}")
                
                import traceback
                logger.error(f"🛍️ Traceback:")
                for line in traceback.format_exc().split('\n'):
                    if line.strip():
                        logger.error(f"🛍️   {line}")
                
                sentry_sdk.capture_exception(e)
                
                # Fallback to embeddings
                if not matches:
                    matches = semantic_search(embedding, site_id)
                        
                if mp:
                    mp.track(distinct_id, "mcp_integration_exception", {
                        "site_id": site_id,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "query_type": query_type
                    })
            
            logger.info(f"🛍️ ===== SHOPIFY MCP INTEGRATION END =====")
            logger.info(f"🛍️ Final context: products={len(mcp_context.get('products', []))}, policies={bool(mcp_context.get('policies'))}")

        else:
            # Log why MCP was skipped
            logger.info(f"🛍️ Skipping MCP: is_shopify={is_shopify}, needs_mcp={needs_mcp}, shopify_domain={shopify_domain}")
     

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
                
                shopify_instructions += f"""

        🛍️ ENHANCED PRODUCT RECOMMENDATION WITH REAL MCP DATA:

        PRODUCTS TO INCLUDE IN CAROUSEL (use exact data):
        {json.dumps(carousel_products, indent=2)}

        SUGGESTED QUICK_REPLIES:
        {json.dumps(dynamic_quick_replies)}

        FOLLOW-UP STRATEGY:
        - follow_up: {follow_up_data['follow_up']}
        - follow_up_prompt: "{follow_up_data['follow_up_prompt']}"

        SEARCH CONTEXT:
        - Total products available: {mcp_context.get('pagination', {}).get('totalCount', 'unknown')}
        - Filter options available: {len(mcp_context.get('available_filters', []))} filter groups
        - Has more pages: {mcp_context.get('pagination', {}).get('hasNextPage', False)}

        INSTRUCTIONS:
        1. Use the EXACT product data above in your product_carousel response
        2. Use the suggested quick_replies to guide user interaction
        3. Apply the follow_up strategy for continued engagement  
        4. If user asks for more products, mention pagination availability
        5. Reference total count when relevant to set expectations
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

# Add this new endpoint to chat.py

@chat_bp.route('/api/mcp', methods=['POST', 'OPTIONS'])
@require_widget_token
def mcp_add_to_cart():
    """Add product to cart via MCP API - COMPLETE IMPLEMENTATION"""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get token data from middleware
        site_id = request.token_data['site_id']
        
        # Get request data
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON data required"}), 400
        
        merchandise_id = data.get('merchandise_id')
        quantity = data.get('quantity', 1)
        product_title = data.get('product_title', 'Product')
        
        if not merchandise_id:
            return jsonify({"error": "merchandise_id required"}), 400
        
        logger.info(f"🛒 MCP Cart Add Request:")
        logger.info(f"🛒   Site ID: {site_id}")
        logger.info(f"🛒   Product ID: {merchandise_id}")
        logger.info(f"🛒   Quantity: {quantity}")
        logger.info(f"🛒   Title: {product_title}")
        
        # Check if this is a Shopify store
        try:
            site_info = site_model.get_site_by_id(site_id)
            if not site_info or not site_info.get('custom_config', {}).get('is_shopify'):
                logger.warning(f"🛒 Not a Shopify store: {site_id}")
                return jsonify({"error": "Not a Shopify store"}), 400
            
            shopify_domain = site_info['custom_config'].get('shopify_domain')
            if not shopify_domain:
                logger.warning(f"🛒 No Shopify domain configured for: {site_id}")
                return jsonify({"error": "Shopify domain not configured"}), 400
            
            logger.info(f"🛒 Shopify domain: {shopify_domain}")
                
        except Exception as e:
            logger.error(f"🛒 Error checking site config: {e}")
            return jsonify({"error": "Site configuration error"}), 500
        
        # Connect to MCP and add to cart
        try:
            logger.info(f"🛒 Connecting to MCP for domain: {shopify_domain}")
            shopify_mcp_service.connect_sync(shopify_domain)
            logger.info(f"🛒 MCP connection established")
            
            # Use MCP update_cart tool with CORRECT parameters based on the API doc
            cart_params = {
                "lines": [  # Use "lines" not "add_items" based on the API example
                    {
                        "merchandise_id": merchandise_id,
                        "quantity": quantity
                    }
                ]
            }
            
            logger.info(f"🛒 Calling MCP update_cart with params:")
            logger.info(f"🛒   {json.dumps(cart_params, indent=2)}")
            
            # Call the MCP tool using the correct method from shopify_mcp_service.py
            mcp_response = shopify_mcp_service._call_mcp_tool("update_cart", cart_params)
            logger.info(f"🛒 MCP update_cart completed")
            
            # Handle MCP response based on the new _call_mcp_tool format
            if mcp_response.get("error"):
                logger.error(f"🛒 MCP cart operation failed: {mcp_response['error']}")
                return jsonify({
                    "error": "Cart service unavailable", 
                    "message": "Unable to add item to cart. Please try again.",
                    "details": mcp_response["error"]
                }), 503
            
            # Parse successful response
            cart_data = mcp_response.get("data", {})
            if not cart_data:
                logger.error(f"🛒 Empty cart data in MCP response")
                return jsonify({
                    "error": "Invalid response from cart service",
                    "message": "Please try again"
                }), 500
            
            # Extract cart information from real MCP response structure
            cart_info = cart_data.get('cart', {})
            checkout_url = cart_info.get('checkout_url', '')
            total_quantity = cart_info.get('total_quantity', quantity)
            cost_info = cart_info.get('cost', {})
            total_amount = cost_info.get('total_amount', {})
            
            # Build success response
            response_data = {
                "success": True,
                "message": f"Added {product_title} to cart",
                "cart": {
                    "id": cart_info.get('id', ''),
                    "checkout_url": checkout_url,
                    "total_quantity": total_quantity,
                    "total_amount": total_amount.get('amount', '0'),
                    "currency": total_amount.get('currency', 'INR')
                }
            }
            
            logger.info(f"🛒 ✅ Cart update successful!")
            logger.info(f"🛒   Checkout URL: {checkout_url}")
            logger.info(f"🛒   Total items: {total_quantity}")
            
            # Track analytics if available
            if mp:
                mp.track(data.get('session_id', 'anonymous'), "mcp_cart_add_success", {
                    "site_id": site_id,
                    "product_title": product_title,
                    "merchandise_id": merchandise_id,
                    "quantity": quantity,
                    "total_quantity": total_quantity,
                    "checkout_url_available": bool(checkout_url)
                })
            
            return jsonify(response_data)
                        
        except Exception as mcp_error:
            logger.error(f"🛒 MCP cart operation failed: {str(mcp_error)}")
            logger.error(f"🛒 MCP error type: {type(mcp_error).__name__}")
            
            # Track MCP failure
            if mp:
                mp.track(data.get('session_id', 'anonymous'), "mcp_cart_add_failure", {
                    "site_id": site_id,
                    "error": str(mcp_error),
                    "error_type": type(mcp_error).__name__,
                    "merchandise_id": merchandise_id
                })
            
            return jsonify({
                "error": "Cart service unavailable",
                "message": "Unable to add item to cart. Please try again or add manually.",
                "details": str(mcp_error) if logger.level <= logging.DEBUG else None
            }), 503
            
    except Exception as e:
        logger.error(f"🛒 Cart endpoint error: {str(e)}")
        logger.exception("Full cart endpoint traceback:")
        
        # Track general failure
        if mp:
            mp.track('anonymous', "cart_endpoint_error", {
                "error": str(e),
                "error_type": type(e).__name__
            })
        
        return jsonify({
            "error": "Internal server error",
            "message": "Something went wrong processing your cart request"
        }), 500

# Health check endpoint
@chat_bp.route('/health', methods=['GET', 'OPTIONS'])
def chat_health():
    """Health check for chat service"""
    return jsonify({
        "status": "healthy",
        "service": "chat",
        "timestamp": datetime.utcnow().isoformat()
    })

# Debug endpoints
@chat_bp.route('/debug', methods=['GET', 'OPTIONS'])
def debug_components():
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

@chat_bp.route('/debug/ask-simple', methods=['POST', 'OPTIONS'])
@require_widget_token
def debug_ask_simple():
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