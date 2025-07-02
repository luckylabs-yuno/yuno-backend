# routes/responses_api_backend.py
from flask import Blueprint, request, jsonify
import logging
import os
import json
from services.jwt_service import JWTService
from services.shopify_mcp_service import ShopifyMCPService
from functools import wraps
from openai import OpenAI
from datetime import datetime

responses_api_bp = Blueprint('responses_api', __name__)
logger = logging.getLogger(__name__)

# Environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MCP_SHOP_DOMAIN = "www.suta.in"  # For www.suta.in/api/mcp

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Initialize services
jwt_service = JWTService()
shopify_mcp_service = ShopifyMCPService()

# --- Auth Decorator (reuse from chat_shopify if possible) ---
def require_widget_token(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            return jsonify({'status': 'ok'}), 200
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({"error": "Authorization required", "message": "Valid token required for access"}), 401
        token = auth_header.replace('Bearer ', '')
        payload = jwt_service.verify_token(token)
        if not payload:
            return jsonify({"error": "Invalid token", "message": "Token is invalid or expired"}), 401
        request.token_data = payload
        return f(*args, **kwargs)
    return decorated_function

# --- Helper: Get tool list from MCP ---
def get_mcp_tools():
    shopify_mcp_service.connect_sync(MCP_SHOP_DOMAIN)
    return shopify_mcp_service.list_tools()

# --- Helper: Call a tool by name and args ---
def call_mcp_tool(tool_name, tool_args):
    shopify_mcp_service.connect_sync(MCP_SHOP_DOMAIN)
    return shopify_mcp_service._call_mcp_tool(tool_name, tool_args)

# --- Endpoint: Health check ---
@responses_api_bp.route('/health', methods=['GET', 'OPTIONS'])
def health():
    return jsonify({"status": "healthy", "service": "responses_api", "timestamp": datetime.utcnow().isoformat()})

# --- Endpoint: Main chat (POST) ---
@responses_api_bp.route('/ask', methods=['POST', 'OPTIONS'])
def ask():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid request", "message": "JSON data required"}), 400
        user_input = data.get("input")
        previous_response_id = data.get("previous_response_id")
        if not user_input and not previous_response_id:
            return jsonify({"error": "Missing input", "message": "'input' or 'previous_response_id' required"}), 400

        # --- First turn: get tools, decide, call, pass to LLM ---
        if not previous_response_id:
            tools = get_mcp_tools()
            # For demo: just call 'search_shop_catalog' if user_input contains 'product' (expand logic as needed)
            tool_calls = []
            if 'product' in user_input.lower():
                tool_calls.append({
                    "type": "function",
                    "function": {
                        "name": "search_shop_catalog",
                        "arguments": {"query": user_input, "context": f"Customer searching for: {user_input}", "limit": 3}
                    }
                })
            # Format for OpenAI Responses API
            response = openai_client.responses.create(
                model="gpt-4o-mini",  # or another supported model
                input=user_input,
                tools=tools,
                tool_choice="auto",
            )
            # If tool call needed, run it and pass result to LLM
            output = response.output
            # (In real use: parse output, run tool, pass tool result to LLM, see OpenAI docs)
            return jsonify({"response": output, "response_id": response.id})
        else:
            # --- Second turn: continue with previous response_id ---
            response = openai_client.responses.create(
                model="gpt-4o-mini",
                input=user_input,
                previous_response_id=previous_response_id
            )
            output = response.output
            return jsonify({"response": output, "response_id": response.id})
    except Exception as e:
        logger.exception("Error in /ask")
        return jsonify({"error": "Internal server error", "message": str(e)}), 500 