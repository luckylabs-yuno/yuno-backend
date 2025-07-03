/**
 * Chat API Route
 * Handles chat interactions with OpenAI API and tools
 */
import { json } from "@remix-run/node";
import MCPClient from "../mcp-client";
import { saveMessage, getConversationHistory, storeCustomerAccountUrl, getCustomerAccountUrl } from "../db.server";
import AppConfig from "../services/config.server";
import { createSseStream } from "../services/streaming.server";
import { createOpenAIService } from "../services/chatgpt.server";
import { createToolService } from "../services/tool.server";
import { unauthenticated } from "../shopify.server";

/**
 * Remix loader function for handling GET requests
 */
export async function loader({ request }) {
  if (request.method === "OPTIONS") {
    return new Response(null, {
      status: 204,
      headers: getCorsHeaders(request)
    });
  }

  const url = new URL(request.url);

  if (url.searchParams.has('history') && url.searchParams.has('conversation_id')) {
    return handleHistoryRequest(request, url.searchParams.get('conversation_id'));
  }

  if (!url.searchParams.has('history') && request.headers.get("Accept") === "text/event-stream") {
    return handleChatRequest(request);
  }

  return json(
    { error: AppConfig.errorMessages.apiUnsupported },
    { status: 400, headers: getCorsHeaders(request) }
  );
}

/**
 * Remix action function for handling POST requests
 */
export async function action({ request }) {
  return handleChatRequest(request);
}

/**
 * Handle history fetch requests
 */
async function handleHistoryRequest(request, conversationId) {
  const messages = await getConversationHistory(conversationId);
  return json({ messages }, { headers: getCorsHeaders(request) });
}

/**
 * Handle chat requests (both GET and POST)
 */
async function handleChatRequest(request) {
  try {
    const body = await request.json();
    const userMessage = body.message;

    if (!userMessage) {
      return new Response(
        JSON.stringify({ error: AppConfig.errorMessages.missingMessage }),
        { status: 400, headers: getSseHeaders(request) }
      );
    }

    const conversationId = body.conversation_id || Date.now().toString();
    const promptType = body.prompt_type || AppConfig.api.defaultPromptType;

    const responseStream = createSseStream(async (stream) => {
      await handleChatSession({
        request,
        userMessage,
        conversationId,
        promptType,
        stream
      });
    });

    return new Response(responseStream, { headers: getSseHeaders(request) });
  } catch (error) {
    console.error('Error in chat request handler:', error);
    return json({ error: error.message }, {
      status: 500,
      headers: getCorsHeaders(request)
    });
  }
}

/**
 * Handle a complete chat session with efficient token management
 */
async function handleChatSession({
  request,
  userMessage,
  conversationId,
  promptType,
  stream
}) {
  const openaiService = createOpenAIService();
  const toolService = createToolService();

  // Hardcoded for testing with suta.in
  const shopDomain = "https://www.mcaffeine.com";
  const shopId = "www.mcaffeine.com";
  const customerMcpEndpoint = "https://www.mcaffeine.com/account/customer/api/mcp";
  const mcpClient = new MCPClient(shopDomain, conversationId, shopId, customerMcpEndpoint);

  try {
    stream.sendMessage({ type: 'id', conversation_id: conversationId });

    // Connect to MCP servers
    let storefrontMcpTools = [], customerMcpTools = [];
    try {
      storefrontMcpTools = await mcpClient.connectToStorefrontServer();
      customerMcpTools = await mcpClient.connectToCustomerServer();
      console.log(`Connected to MCP with ${storefrontMcpTools.length + customerMcpTools.length} tools`);
    } catch (error) {
      console.warn('Failed to connect to MCP servers:', error.message);
    }

    let productsToDisplay = [];

    // Save user message
    await saveMessage(conversationId, 'user', userMessage);

    // Get truncated conversation history (last 3 turns only)
    let conversationHistory = await getTruncatedHistory(conversationId);
    
    // Add current user message
    conversationHistory.push({ role: 'user', content: userMessage });

    // Execute conversation loop with proper tool result handling
    let maxIterations = 10; // Prevent infinite loops
    let iteration = 0;

    while (iteration < maxIterations) {
      iteration++;
      
      const response = await openaiService.streamConversation(
        {
          messages: conversationHistory,
          promptType,
          tools: mcpClient.tools
        },
        {
          onText: (textDelta) => {
            stream.sendMessage({
              type: 'chunk',
              chunk: textDelta
            });
          },

          onMessage: (message) => {
            // Add assistant message to history
            conversationHistory.push(message);
            
            // Save assistant message
            saveMessage(conversationId, message.role, JSON.stringify(message.content || message.tool_calls))
              .catch(error => console.error("Error saving message:", error));

            stream.sendMessage({ type: 'message_complete' });
          },

          onToolUse: async (content) => {
            const toolName = content.name;
            const toolArgs = content.input;
            const toolUseId = content.id;

            stream.sendMessage({
              type: 'tool_use',
              tool_use_message: `Calling tool: ${toolName} with arguments: ${JSON.stringify(toolArgs)}`
            });

            // Call the tool
            const toolUseResponse = await mcpClient.callTool(toolName, toolArgs);

            let toolResultContent;

            // Handle tool response
            if (toolUseResponse.error) {
              toolResultContent = `Error: ${toolUseResponse.error.data}`;
              
              if (toolUseResponse.error.type === "auth_required") {
                stream.sendMessage({ type: 'auth_required' });
              }
            } else {
              // Process successful tool response
              if (toolName === 'search_shop_catalog') {
                productsToDisplay.push(...toolService.processProductSearchResult(toolUseResponse));
              }
              
              // Format tool response content properly
              if (toolUseResponse.content && Array.isArray(toolUseResponse.content)) {
                // Extract text from content array
                const textContent = toolUseResponse.content
                  .filter(item => item.type === 'text')
                  .map(item => item.text)
                  .join('\n');
                toolResultContent = textContent;
              } else {
                toolResultContent = typeof toolUseResponse.content === 'string' 
                  ? toolUseResponse.content 
                  : JSON.stringify(toolUseResponse.content);
              }
            }

            // Add tool result to conversation history in OpenAI format
            conversationHistory.push({
              role: 'tool',
              tool_call_id: toolUseId,
              content: toolResultContent
            });

            // Save tool result to database
            await saveMessage(conversationId, 'tool', JSON.stringify({
              tool_call_id: toolUseId,
              content: toolResultContent
            }));

            stream.sendMessage({ type: 'new_message' });
          }
        }
      );

      // If the response doesn't have tool calls, we're done
      if (!response.tool_calls || response.tool_calls.length === 0) {
        break;
      }
    }

    stream.sendMessage({ type: 'end_turn' });

    if (productsToDisplay.length > 0) {
      stream.sendMessage({
        type: 'product_results',
        products: productsToDisplay
      });
    }
  } catch (error) {
    throw error;
  }
}

/**
 * Get truncated conversation history (last 3 message turns only)
 * Returns only: previous user message, previous bot reply
 * Excludes: system prompts, tool calls, tool results
 */
async function getTruncatedHistory(conversationId) {
  try {
    const allMessages = await getConversationHistory(conversationId);
    
    // Filter out system messages, tool calls, and tool results
    // Only keep user and assistant messages with actual content
    const userAndAssistantMessages = allMessages.filter(msg => {
      if (msg.role === 'system' || msg.role === 'tool') return false;
      
      try {
        const content = JSON.parse(msg.content);
        
        // Skip assistant messages that only contain tool calls
        if (msg.role === 'assistant' && Array.isArray(content) && 
            content.every(c => c.type === 'tool_use')) {
          return false;
        }
        
        // Skip user messages that are tool results
        if (msg.role === 'user' && Array.isArray(content) && 
            content.some(c => c.type === 'tool_result')) {
          return false;
        }
      } catch (e) {
        // If not JSON, it's likely a regular text message
      }
      
      return msg.role === 'user' || msg.role === 'assistant';
    });

    // Get last 4 messages (2 complete turns = user + assistant pairs)
    const lastMessages = userAndAssistantMessages.slice(-4);
    
    // Format for OpenAI
    return lastMessages.map(msg => {
      let content;
      try {
        content = JSON.parse(msg.content);
        // For assistant messages, extract just the text content
        if (msg.role === 'assistant' && typeof content === 'string') {
          return { role: msg.role, content };
        }
        // For simple string content
        if (typeof content === 'string') {
          return { role: msg.role, content };
        }
        // If content is complex, stringify it
        return { role: msg.role, content: JSON.stringify(content) };
      } catch (e) {
        // If parsing fails, use content as-is
        return { role: msg.role, content: msg.content };
      }
    });
  } catch (error) {
    console.error('Error getting truncated history:', error);
    return [];
  }
}

function getCorsHeaders(request) {
  const origin = request.headers.get("Origin") || "*";
  const requestHeaders = request.headers.get("Access-Control-Request-Headers") || "Content-Type, Accept";

  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": requestHeaders,
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Max-Age": "86400"
  };
}

function getSseHeaders(request) {
  const origin = request.headers.get("Origin") || "*";

  return {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET,OPTIONS,POST",
    "Access-Control-Allow-Headers": "X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version"
  };
}