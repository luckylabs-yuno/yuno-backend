/**
 * OpenAI Service
 * Manages interactions with the OpenAI API (ChatGPT 4o mini)
 */
import OpenAI from 'openai';
import AppConfig from "./config.server";
import systemPrompts from "../prompts/prompts.json";

/**
 * Creates an OpenAI service instance
 * @param {string} apiKey - OpenAI API key
 * @returns {Object} OpenAI service with methods for interacting with OpenAI API
 */
export function createOpenAIService(apiKey = process.env.OPENAI_API_KEY) {
  // Initialize OpenAI client
  const openai = new OpenAI({ apiKey });

  /**
   * Streams a conversation with ChatGPT
   * @param {Object} params - Stream parameters
   * @param {Array} params.messages - Conversation history (truncated to last 3 turns)
   * @param {string} params.promptType - The type of system prompt to use
   * @param {Array} params.tools - Available tools for ChatGPT
   * @param {Object} streamHandlers - Stream event handlers
   * @param {Function} streamHandlers.onText - Handles text chunks
   * @param {Function} streamHandlers.onMessage - Handles complete messages
   * @param {Function} streamHandlers.onToolUse - Handles tool use requests
   * @returns {Promise<Object>} The final message
   */
  const streamConversation = async ({
    messages,
    promptType = AppConfig.api.defaultPromptType,
    tools
  }, streamHandlers) => {
    // Get system prompt from configuration
    const systemInstruction = getSystemPrompt(promptType);
    
    // Prepare messages with system prompt and truncated history
    const formattedMessages = [
      { role: 'system', content: systemInstruction },
      ...messages
    ];

    // Format tools for OpenAI function calling
    const formattedTools = tools && tools.length > 0 ? formatToolsForOpenAI(tools) : undefined;

    console.log('Sending to OpenAI:', {
      messageCount: formattedMessages.length,
      toolCount: formattedTools?.length || 0,
      lastMessage: formattedMessages[formattedMessages.length - 1]
    });

    // Create stream
    const stream = await openai.chat.completions.create({
      model: 'gpt-4.1-nano-2025-04-14',
      max_tokens: AppConfig.api.maxTokens,
      messages: formattedMessages,
      tools: formattedTools,
      tool_choice: formattedTools ? 'auto' : undefined,
      stream: true
    });

    let assistantMessage = { role: 'assistant', content: '' };
    let toolCalls = [];

    // Process stream chunks
    for await (const chunk of stream) {
      const delta = chunk.choices[0]?.delta;
      
      if (delta?.content) {
        assistantMessage.content += delta.content;
        if (streamHandlers.onText) {
          streamHandlers.onText(delta.content);
        }
      }

      if (delta?.tool_calls) {
        for (const toolCall of delta.tool_calls) {
          if (!toolCalls[toolCall.index]) {
            toolCalls[toolCall.index] = {
              id: toolCall.id,
              type: 'function',
              function: { name: '', arguments: '' }
            };
          }
          
          if (toolCall.function?.name) {
            toolCalls[toolCall.index].function.name = toolCall.function.name;
          }
          
          if (toolCall.function?.arguments) {
            toolCalls[toolCall.index].function.arguments += toolCall.function.arguments;
          }
        }
      }

      if (chunk.choices[0]?.finish_reason) {
        break;
      }
    }

    // Add tool calls to the message if they exist
    if (toolCalls.length > 0) {
      assistantMessage.tool_calls = toolCalls;
    }

    console.log('OpenAI response:', {
      hasContent: !!assistantMessage.content,
      hasToolCalls: toolCalls.length > 0,
      toolCallsCount: toolCalls.length
    });

    // Handle message completion
    if (streamHandlers.onMessage) {
      streamHandlers.onMessage(assistantMessage);
    }

    // Process tool calls
    if (streamHandlers.onToolUse && toolCalls.length > 0) {
      for (const toolCall of toolCalls) {
        try {
          const args = JSON.parse(toolCall.function.arguments);
          await streamHandlers.onToolUse({
            id: toolCall.id,
            name: toolCall.function.name,
            input: args
          });
        } catch (error) {
          console.error('Error parsing tool arguments:', error);
        }
      }
    }

    return {
      ...assistantMessage,
      stop_reason: toolCalls.length > 0 ? 'tool_use' : 'end_turn'
    };
  };

  /**
   * Formats tools from MCP format to OpenAI function calling format
   * @param {Array} mcpTools - Tools in MCP format
   * @returns {Array} Tools formatted for OpenAI
   */
  const formatToolsForOpenAI = (mcpTools) => {
    return mcpTools.map(tool => ({
      type: 'function',
      function: {
        name: tool.name,
        description: tool.description,
        parameters: tool.input_schema
      }
    }));
  };

  /**
   * Gets the system prompt content for a given prompt type
   * @param {string} promptType - The prompt type to retrieve
   * @returns {string} The system prompt content
   */
  const getSystemPrompt = (promptType) => {
    return systemPrompts.systemPrompts[promptType]?.content ||
      systemPrompts.systemPrompts[AppConfig.api.defaultPromptType].content;
  };

  return {
    streamConversation,
    getSystemPrompt,
    formatToolsForOpenAI
  };
}

export default {
  createOpenAIService
};