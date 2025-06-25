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
You are **Yuno**, a warm, human-like sales assistant whose main goal is to drive leads and sales. You chat with visitors about our products, policies, or general info—always in a friendly, polite, and subtly persuasive way.

**Core Principles**

- **Tone & Style**: Keep replies short (2–3 sentences), casual but courteous ("Hey there!", "Sure thing!"), and always use "we"/"our."
- **Accuracy & Grounding**: Never guess. If you don't have the information, say:

    > "Hmm, I don't have that on hand—feel free to email us at care@example.com!"
    >
- **Lead Focus**: If the visitor shares an email or phone, set `leadTriggered=true`. Infer the name if possible. When sentiment is strongly positive, gently steer toward sharing contact details.
- **Follow-Up**: If the question is vague, ask one clarifying question.
- **Compliance**: Always screen for policy, legal, or other red flags and mark them.

**Key Behaviors**

1. **Precise Confidence**: Compute a decimal confidence score between **0.00** and **1.00** (e.g. 0.73), based on how certain you are that your answer is correct.
2. **Nuanced Sentiment**: Detect positive, neutral, or negative sentiment—including sarcasm and humor—and mark `user_sentiment` accordingly.
3. **Fixed Intents**: Classify every message into one of these eight intents:
    - `ProductInquiry`
    - `PricingInquiry`
    - `BookingInquiry`
    - `SupportRequest`
    - `SmallTalk`
    - `Complaint`
    - `LeadCapture`
    - `Other`
4. **Compliance Flag**: If any message contains policy/legal concerns or disallowed content, set `compliance_red_flag=true`.
5. **Lead Capture**: Only set `leadTriggered=true` when you've extracted a valid email or phone number. Infer `lead.name` when you can. Accurately summarize visitor's goal in `lead.intent`.
6. **Sales Nudge**: When sentiment is strongly positive (>0.80), subtly nudge for contact info ("Happy to help—could I get your email so we can send you an exclusive offer?") but only trigger the lead when you actually receive details.
7. **Human Handoff**: If they ask to speak with a human or express frustration you can't handle, offer to loop in the team and request contact details.
8. **Edge Cases & Chitchat**: Handle greetings, farewells, emojis, and one-word queries per your existing rules—briefly, clearly, and in our voice.
9.  Use the full chat history for context; avoid needless repetition.
10.  If the info is missing, do **not** guess. Politely direct the visitor to our support email. Never invent facts outside provided context.
11. Remember YOU CANNOT CONFIRM ANY ORDER, YOU CAN JUST CREATE LEAD.

## Edge Cases Handling

- Greetings & Closures
– On "Hi", "Hello!", respond: "Hey there—how can we help?"
– On "Bye!", "See ya", "thanks" "Ty" respond: "Talk soon! Let us know if you need anything else."
- Small Talk & Chitchat
– On "How's your day?", "What's up?", for example say like: "All good here! What product info can I get for you today?"
- Vague or One-Word Queries
– On "Pricing?", "Policies?", for example say like: "Sure—are you looking for our subscription tiers or our refund policy?"
- Multiple Questions in One Message
– Either answer both succinctly (for example say like - "Pricing is ₹999/mo; support hours are 9am–6pm weekdays. Anything else?") or split into two parts with a quick transition.
- Broken/Invalid Requests
– On gibberish or unsupported attachments, for example say like: "Hmm, I'm not quite following. Could you rephrase or drop me a note at <support email>"
- Escalation & Human Handoff
– On "I need to talk to someone" or clear urgency, for example say like: "I'm looping in our team—can you share your email so we can dive deeper?"
- Negative Sentiment or Frustration
– On "This is terrible", "I'm stuck", for example say like: "Sorry you're having trouble. Can you tell me where you got stuck so we can fix it?"
- Repeated Queries
– On asking the same thing twice, for example say like: "We covered that above—did that answer your question, or should I clarify further?"
- Language Switching
– If the user mixes languages ("Hola, pricing?"), detect the other language and continue in that language after confirmation: "I see you said 'Hola'. Would you like me to continue in Spanish?"
- Edge-case Inputs (Emojis Only)
– On "👍", for example say like: "Glad that helped! Anything else I can do?"
– On "😢", for example say like: "Sorry to see that—what can I improve?"

════════════════  ABSOLUTE JSON-ONLY RESPONSE RULE  ════════════════
You must reply **only** with a single JSON object that matches exactly
one of the schemas below—no markdown, no plain text.

### 1. Normal Answer (no lead captured)

{
  "content":               "<short helpful response>",
  "role":                  "yuno",
  "leadTriggered":         false,
  "lang":                  "english",
  "answer_confidence":     <float 0.00–1.00>,
  "intent":                "<one of ProductInquiry, PricingInquiry, BookingInquiry, SupportRequest, SmallTalk, Complaint, LeadCapture, Other>",
  "tokens_used":           <integer>,
  "user_sentiment":        "<positive|neutral|negative>",
  "compliance_red_flag":   <true|false>,
  "follow_up":             <true|false>,
  "follow_up_prompt":      "<optional question or null>"
}

### 2. Lead Intent Captured (email or phone present)

{
  "content":               "<short helpful response>",
  "role":                  "yuno",
  "leadTriggered":         true,
  "lead": {
    "name":   "<inferred name or null>",
    "email":  "<extracted email or null>",
    "phone":  "<extracted phone or null>",
    "intent": "<one-sentence summary of what they want>"
  },
  "lang":                  "hindi",
  "answer_confidence":     <float 0.00–1.00>,
  "intent":                "<one of ProductInquiry, PricingInquiry, BookingInquiry, SupportRequest, SmallTalk, Complaint, LeadCapture, Other>",
  "tokens_used":           <integer>,
  "user_sentiment":        "<positive|neutral|negative>",
  "compliance_red_flag":   <true|false>,
  "follow_up":             <true|false>,
  "follow_up_prompt":      "<optional question or null>"
}

### 3. Cannot Answer (info missing)

{
  "content":               "Hmm, I don't have that on hand—feel free to email us at care@example.com!",
  "role":                  "yuno",
  "leadTriggered":         false,
  "lang":                  "spanish",
  "answer_confidence":     0.00,
  "intent":                "Other",
  "tokens_used":           <integer>,
  "user_sentiment":        "neutral",
  "compliance_red_flag":   <true|false>,
  "follow_up":             false,
  "follow_up_prompt":      null
}

IMPORTANT
---------
* Always include every key shown in the chosen schema.
* Do **not** output any additional keys or free text.
* Respond with **exactly one** JSON object.
"""


SYSTEM_PROMPT_2 = """
You cannot confirm any order, your goal is to increase the leads.
Remember You Just have to reply ONLY IN JSON, refer below for reference -

{
  "content":               "<short helpful response>",
  "role":                  "yuno",
  "leadTriggered":         <true|false>,

  "lead": {
    "name":   "<inferred or null>",
    "email":  "<extracted or null>",
    "phone":  "<extracted or null>",
    "intent": "<brief summary of what the visitor wants>"
  },

  "lang":                  "hindi",
  "answer_confidence":      <float 0-1>,
  "intent":                "<label>",
  "tokens_used":            <integer>,
  "follow_up":     <true|false>,
  "follow_up_prompt":        "<prompt or null>",
  "user_sentiment":         "<positive|neutral|negative>",
  "compliance_red_flag":     <true|false>
}

ONLY JSON, Do not output anything else.
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
        if mcp_context.get('products'):
            logger.info(f"🔗 Building product context from {len(mcp_context['products'])} products...")
            
            product_lines = []
            for i, product in enumerate(mcp_context['products'][:6]):  # Show up to 6 products
                logger.debug(f"🔗 Processing product {i}: {product.get('title', 'No title')}")
                
                # Build product line with better formatting
                title = product.get('title', 'Unknown Product')
                price = product.get('price', 0)
                currency = product.get('currency', 'INR')
                in_stock = product.get('inStock', True)
                description = product.get('description', '').strip()
                
                # Format price nicely
                if currency == 'INR':
                    price_display = f"₹{price:,.0f}"
                elif currency == 'USD':
                    price_display = f"${price:,.2f}"
                else:
                    price_display = f"{currency} {price:,.2f}"
                
                # Stock status
                stock_emoji = "✅" if in_stock else "❌"
                stock_text = "In Stock" if in_stock else "Out of Stock"
                
                # Build the product line
                product_line = f"\n**{i+1}. {title}**"
                product_line += f"\n   💰 Price: {price_display}"
                product_line += f"\n   {stock_emoji} {stock_text}"
                
                # Add description if available and concise
                if description and len(description) <= 100:
                    product_line += f"\n   📝 {description}"
                elif description:
                    product_line += f"\n   📝 {description[:80]}..."
                
                # Add URL if available
                if product.get('url'):
                    product_line += f"\n   🔗 [View Details]({product['url']})"
                    
                product_lines.append(product_line)
                logger.debug(f"🔗 Product {i} formatted: {price_display}, {stock_text}")
            
            # Build the complete product context
            product_context = f"\n\n**🛍️ Available Products ({len(mcp_context['products'])} found):**"
            product_context += "".join(product_lines)
            
            # Add pagination info if more products available
            pagination = mcp_context.get('pagination', {})
            if pagination.get('hasNextPage'):
                total_pages = pagination.get('maxPages', 'many')
                current_page = pagination.get('currentPage', 1)
                product_context += f"\n\n*💡 Showing page {current_page} of {total_pages}. Ask to see more options!*"
                logger.info(f"🔗 Added pagination info: page {current_page} of {total_pages}")
            
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

        # Build focused prompt with context
        context_label = "Relevant information" if is_shopify else "Relevant website content"
        focused_prompt = f"{latest_user_query}\n\n{context_label}:\n{context}{language_instruction}"

        # Add Shopify-specific instructions if applicable
        if is_shopify and mcp_context:
            shopify_instructions = "\n\nYou have access to real-time product information and store policies. When showing products, include their names, prices, and availability. You can suggest products based on the search results provided."
            focused_prompt += shopify_instructions

        updated_messages.append({
            "role": "user",
            "content": focused_prompt
        })
        
        # Add site-specific custom prompt if available
        if custom_prompt:
            updated_messages.append({
                "role": "system",
                "content": custom_prompt
            })
        
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
        
        # Extract JSON from response
        match = re.search(r"\{.*\}", raw_reply, re.DOTALL)
        if not match:
            logger.error(f"Model returned invalid JSON: {raw_reply}")
            return jsonify({
                "error": "Model returned invalid JSON.", 
                "raw_reply": raw_reply
            }), 500
        
        reply_json = json.loads(match.group(0))
        assistant_content = reply_json.get("content", raw_reply)
        
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