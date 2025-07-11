from flask import Blueprint, request, jsonify
from flask_cors import CORS
import openai
import os
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime

# Configure logging for production
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

mcp_chat_bp = Blueprint('mcp_chat', __name__)
CORS(mcp_chat_bp)  # Enable CORS for this blueprint

# Initialize OpenAI client with error handling
try:
    openai_api_key = os.getenv('OPENAI_API_KEY')
    if not openai_api_key:
        logger.error("OPENAI_API_KEY environment variable not found")
        raise ValueError("OpenAI API key is required")
    
    client = openai.OpenAI(api_key=openai_api_key)
    logger.info("OpenAI client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize OpenAI client: {e}")
    client = None

class MCPChatRequest:
    """Data model for MCP chat requests"""
    def __init__(self, data: Dict[str, Any]):
        self.message = data.get('message', '')
        self.mcp_servers = data.get('mcp_servers', [])
        self.user_id = data.get('user_id')
        self.session_id = data.get('session_id')
        self.model = data.get('model', 'gpt-4.1')
        self.conversation_history = data.get('conversation_history', [])
        
    def validate(self) -> Optional[str]:
        """Validate request data"""
        if not self.message:
            return "Message is required"
        if not self.mcp_servers:
            return "At least one MCP server must be specified"
        
        for server in self.mcp_servers:
            if not server.get('server_url'):
                return "server_url is required for all MCP servers"
            if not server.get('server_label'):
                return "server_label is required for all MCP servers"
                
        return None

def build_mcp_tools(mcp_servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build MCP tools configuration from server list"""
    tools = []
    
    for server in mcp_servers:
        tool_config = {
            "type": "mcp",
            "server_label": server['server_label'],
            "server_url": server['server_url'],
            "require_approval": server.get('require_approval', 'never')
        }
        
        # Add authentication headers if provided
        if server.get('headers'):
            tool_config['headers'] = server['headers']
        elif server.get('auth_token'):
            tool_config['headers'] = {
                "Authorization": f"Bearer {server['auth_token']}"
            }
            
        # Add allowed tools filter if specified
        if server.get('allowed_tools'):
            tool_config['allowed_tools'] = server['allowed_tools']
            
        tools.append(tool_config)
    
    return tools

def format_conversation_input(message: str, history: List[Dict] = None) -> str:
    """Format conversation with history for better context"""
    if not history:
        return message
    
    # Build conversation context
    context_parts = []
    for item in history[-5:]:  # Keep last 5 exchanges for context
        if item.get('role') == 'user':
            context_parts.append(f"User: {item.get('content', '')}")
        elif item.get('role') == 'assistant':
            context_parts.append(f"Assistant: {item.get('content', '')}")
    
    context_parts.append(f"User: {message}")
    return "\n".join(context_parts)

@mcp_chat_bp.route('/mcp-chat/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "mcp-chat-backend"
    })

@mcp_chat_bp.route('/mcp-chat/chat', methods=['POST'])
def chat_with_mcp():
    """Main chat endpoint with MCP server integration"""
    if not client:
        return jsonify({
            "error": "OpenAI client not initialized",
            "status": "error"
        }), 500
        
    try:
        # Parse and validate request
        req_data = MCPChatRequest(request.json or {})
        validation_error = req_data.validate()
        
        if validation_error:
            return jsonify({
                "error": validation_error,
                "status": "error"
            }), 400

        # Build MCP tools configuration
        mcp_tools = build_mcp_tools(req_data.mcp_servers)
        
        # Format input with conversation history
        formatted_input = format_conversation_input(
            req_data.message, 
            req_data.conversation_history
        )
        
        logger.info(f"Processing chat request for user {req_data.user_id}")
        logger.info(f"Using {len(mcp_tools)} MCP servers: {[t['server_label'] for t in mcp_tools]}")
        
        # Call OpenAI Responses API with MCP tools
        response = client.responses.create(
            model=req_data.model,
            tools=mcp_tools,
            input=formatted_input
        )
        
        # Extract tools that were actually used
        tools_used = []
        mcp_calls = []
        
        # Parse response outputs for MCP tool usage
        if hasattr(response, 'output') and response.output:
            for output_item in response.output:
                if output_item.get('type') == 'mcp_call':
                    tools_used.append({
                        "tool_name": output_item.get('name'),
                        "server_label": output_item.get('server_label'),
                        "status": "success" if not output_item.get('error') else "error",
                        "error": output_item.get('error')
                    })
                    mcp_calls.append(output_item)
        
        # Build response
        response_data = {
            "response": response.output_text,
            "tools_used": tools_used,
            "mcp_calls": mcp_calls,
            "status": "success",
            "model_used": req_data.model,
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": req_data.session_id
        }
        
        logger.info(f"Chat completed successfully. Tools used: {len(tools_used)}")
        return jsonify(response_data)
        
    except openai.APIError as e:
        logger.error(f"OpenAI API error: {e}")
        return jsonify({
            "error": f"OpenAI API error: {str(e)}",
            "status": "error",
            "error_type": "openai_api_error"
        }), 500
        
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({
            "error": f"Internal server error: {str(e)}",
            "status": "error",
            "error_type": "internal_error"
        }), 500

@mcp_chat_bp.route('/mcp-chat/servers/validate', methods=['POST'])
def validate_mcp_servers():
    """Endpoint to validate MCP server configurations"""
    try:
        servers = request.json.get('servers', [])
        if not servers:
            return jsonify({"error": "No servers provided"}), 400
            
        # Test each server by attempting to list tools
        validation_results = []
        
        for server in servers:
            try:
                # Attempt to get tools list from MCP server
                test_response = client.responses.create(
                    model="gpt-4.1",
                    tools=[{
                        "type": "mcp",
                        "server_label": server.get('server_label', 'test'),
                        "server_url": server.get('server_url'),
                        "headers": server.get('headers', {}),
                        "require_approval": "never"
                    }],
                    input="test connection"
                )
                
                validation_results.append({
                    "server_label": server.get('server_label'),
                    "server_url": server.get('server_url'),
                    "status": "valid",
                    "tools_available": True
                })
                
            except Exception as e:
                validation_results.append({
                    "server_label": server.get('server_label'),
                    "server_url": server.get('server_url'),
                    "status": "invalid",
                    "error": str(e),
                    "tools_available": False
                })
        
        return jsonify({
            "validation_results": validation_results,
            "status": "success"
        })
        
    except Exception as e:
        logger.error(f"Server validation error: {e}")
        return jsonify({
            "error": f"Validation failed: {str(e)}",
            "status": "error"
        }), 500

@mcp_chat_bp.route('/mcp-chat/models', methods=['GET'])
def get_available_models():
    """Get list of available OpenAI models that support MCP"""
    return jsonify({
        "models": [
            {"id": "gpt-4.1", "name": "GPT-4.1", "supports_mcp": True},
            {"id": "gpt-4o", "name": "GPT-4o", "supports_mcp": True},
            {"id": "o1", "name": "o1 Reasoning", "supports_mcp": True},
            {"id": "o1-mini", "name": "o1-mini", "supports_mcp": True}
        ],
        "default": "gpt-4.1"
    }) 