from flask import Blueprint, request, jsonify
import logging
import json
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
import os
import sentry_sdk
from openai import OpenAI, RateLimitError, InvalidRequestError

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
MIXPANEL_TOKEN = os.getenv("MIXPANEL_TOKEN")


# Supabase function URL for semantic search
SUPABASE_FUNCTION_URL = f"{SUPABASE_URL}/rest/v1/rpc/yunosearch"
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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
  "lang":                  "<two-letter code, e.g. \"en\">",
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
  "lang":                  "<two-letter code>",
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
  "lang":                  "<two-letter code>",
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

REWRITER_PROMPT = """
You are an assistant that rewrites a user's query using recent chat history.
Your goal is to combine the current user message and past conversation into
a clear, standalone query. Use complete language. Do not mention the history.

For eg -
User - Tell me about your services?
You - We offer MBA, BBA, MTech
User - Wow, tell me about second one?

so in this case you will respond with this type of query - "Wow can you tell me more about your BBA services"

The idea is we will use this for RAG based vector search, so we will need exact query so that query is as meaningful as possible.
IF You think that latest User message is not related to previous conversation and it would make sense for RAG search to just use the latest message, so just rewrite the latest message properly.
Just output the rewritten query as a single sentence.

Chat History:
{history}

User's New Message:
{latest}

Rewritten Query:
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

  "lang":                  "<two-letter code>",
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
    try:
        if not openai_client:
            raise Exception("OpenAI client not initialized")
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

def rewrite_query_with_context(history: List[dict], latest: str) -> str:
    """Rewrite user query with chat history context for better RAG search"""
    try:
        chat_log = "\n".join([
            f"{'You' if m['role'] in ['assistant', 'yuno', 'bot'] else 'User'}: {m['content']}"
            for m in history
        ])

        prompt = REWRITER_PROMPT.format(history=chat_log, latest=latest)

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",  # Use same model as main chat
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("Query rewrite failed: %s", str(e))
        return latest

# JWT Token Authentication Decorator
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

# Enhanced /ask endpoint with advanced features
@chat_bp.route('/ask', methods=['POST'])
@require_widget_token
def advanced_ask_endpoint():
    """
    Advanced chat endpoint with JWT authentication, semantic search, 
    lead capture, analytics tracking, and comprehensive logging
    """
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
        
        # Rewrite query with context for better RAG search
        rewritten_query = rewrite_query_with_context(recent_history, latest_user_query)
        
        if mp:
            mp.track(distinct_id, "query_rewritten", {
                "site_id": site_id,
                "session_id": session_id,
                "original_query": latest_user_query,
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
        
        # Perform semantic search
        matches = semantic_search(embedding, site_id)
        sentry_sdk.set_extra("vector_search_results", matches[:3])
        
        if mp:
            mp.track(distinct_id, "vector_search_performed", {
                "site_id": site_id,
                "session_id": session_id,
                "match_count": len(matches),
                "top_matches": matches[:2]
            })
        
        # Build context from search results
        context = "\n\n".join(
            match.get("detail") or match.get("text") or "" 
            for match in matches if match
        )
        
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
        
        # Build focused prompt with context
        focused_prompt = f"{latest_user_query}\n\nRelevant website content:\n{context}"
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
        
        sentry_sdk.set_extra("gpt_prompt", focused_prompt)
        
        if mp:
            mp.track(distinct_id, "gpt_prompt_sent", {
                "site_id": site_id,
                "session_id": session_id,
                "full_prompt": focused_prompt
            })
        
        # Call OpenAI
        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",
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
            lang=lang,
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
                "lead_triggered": reply_json.get("leadTriggered", False)
            })
        
        logger.info(f"Chat response generated for site_id: {site_id}")
        
        return jsonify(reply_json)
        
    except RateLimitError:
        logger.error("OpenAI rate limit exceeded")
        return jsonify({
            "error": "Service temporarily unavailable",
            "message": "Please try again in a moment"
        }), 503
        
    except InvalidRequestError as e:
        logger.error(f"OpenAI invalid request: {str(e)}")
        return jsonify({
            "error": "Invalid request",
            "message": "Unable to process your message"
        }), 400
        
    except Exception as e:
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
@chat_bp.route('/health', methods=['GET'])
def chat_health():
    """Health check for chat service"""
    return jsonify({
        "status": "healthy",
        "service": "chat",
        "timestamp": datetime.utcnow().isoformat()
    })

# REMOVE THE DUPLICATE SECTION AT THE BOTTOM
# Keep only ONE set of debug endpoints - use this cleaned version:

# Replace the entire debug_components function with this properly indented version:

@chat_bp.route('/debug', methods=['GET'])
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
    
    # Test imports
    imports_to_test = [
        ('openai', 'from openai import OpenAI'),
        ('supabase', 'from supabase import create_client'),
        ('mixpanel', 'from mixpanel import Mixpanel'),
        ('sentry_sdk', 'import sentry_sdk'),
        ('redis', 'import redis')
    ]
    
    for name, import_statement in imports_to_test:
        try:
            exec(import_statement)
            debug_info["imports"][name] = "OK"
        except Exception as e:
            debug_info["imports"][name] = f"ERROR: {str(e)}"
            debug_info["errors"].append(f"Import {name}: {str(e)}")
    
    # Test services initialization
    try:
        jwt_secret = jwt_service.secret_key
        debug_info["services"]["jwt_service"] = "OK" if jwt_secret else "No secret key"
    except Exception as e:
        debug_info["services"]["jwt_service"] = f"ERROR: {str(e)}"
        debug_info["errors"].append(f"JWT Service: {str(e)}")
    
    try:
        if rate_limit_service.redis_client:
            rate_limit_service.redis_client.ping()
            debug_info["services"]["redis"] = "OK - Connected"
        else:
            debug_info["services"]["redis"] = "No Redis client"
    except Exception as e:
        debug_info["services"]["redis"] = f"ERROR: {str(e)}"
        debug_info["errors"].append(f"Redis: {str(e)}")
    
    # Test OpenAI connection (PROPERLY INDENTED)
    try:
        if OPENAI_API_KEY:
            if not openai_client:
                debug_info["connections"]["openai"] = "Client not initialized"
            else:
                # Test with actual API call
                test_response = openai_client.chat.completions.create(
                    model="gpt-4o-mini-2024-07-18",
                    messages=[{"role": "user", "content": "Say 'test successful'"}],
                    max_tokens=10
                )
                # If we get here, the API call was successful
                debug_info["connections"]["openai"] = "API call successful"
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

@chat_bp.route('/debug/auth', methods=['GET'])
def debug_auth():
    """Debug authentication flow"""
    return jsonify({
        "message": "This endpoint tests if JWT service is working",
        "jwt_service_available": hasattr(jwt_service, 'secret_key'),
        "jwt_secret_set": bool(jwt_service.secret_key) if hasattr(jwt_service, 'secret_key') else False,
        "test_site_id": "test123",
        "instructions": "Use POST /widget/authenticate to get a token first"
    })

@chat_bp.route('/debug/ask-simple', methods=['POST'])
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
            
            if not openai_client:
                raise Exception("OpenAI client not initialized")
            
            debug_steps.append("5. ✅ OpenAI key set")
            
            # Test with a simple completion
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

@chat_bp.route('/debug/embedding', methods=['POST'])
@require_widget_token  
def debug_embedding():
    """Test embedding generation specifically"""
    try:
        data = request.get_json()
        test_text = data.get('text', 'test embedding')
        
        # Test embedding generation
        embedding = get_embedding(test_text)
        
        return jsonify({
            "status": "success",
            "text": test_text,
            "embedding_length": len(embedding),
            "embedding_preview": embedding[:5],
            "embedding_type": type(embedding).__name__
        })
        
    except Exception as e:
        return jsonify({
            "error": "Embedding generation failed",
            "error_type": type(e).__name__,
            "error_message": str(e)
        }), 500

@chat_bp.route('/debug/supabase', methods=['POST'])
@require_widget_token
def debug_supabase():
    """Test Supabase connection and search"""
    try:
        data = request.get_json()
        site_id = request.token_data.get('site_id')
        test_query = data.get('query', 'test query')
        
        # Test embedding generation
        embedding = get_embedding(test_query)
        
        # Test semantic search
        results = semantic_search(embedding, site_id)
        
        return jsonify({
            "status": "success", 
            "query": test_query,
            "site_id": site_id,
            "embedding_generated": True,
            "search_results_count": len(results),
            "search_results": results[:2] if results else []
        })
        
    except Exception as e:
        return jsonify({
            "error": "Supabase search failed",
            "error_type": type(e).__name__,
            "error_message": str(e)
        }), 500
