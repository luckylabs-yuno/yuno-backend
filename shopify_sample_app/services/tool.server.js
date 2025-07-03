/**
 * Tool Service
 * Manages tool execution and processing for OpenAI function calling
 */
import { saveMessage } from "../db.server";
import AppConfig from "./config.server";

/**
 * Creates a tool service instance
 * @returns {Object} Tool service with methods for managing tools
 */
export function createToolService() {
  /**
   * Handles a tool error response
   */
  const handleToolError = async (toolUseResponse, toolName, toolUseId, conversationHistory, sendMessage, conversationId) => {
    if (toolUseResponse.error.type === "auth_required") {
      console.log("Auth required for tool:", toolName);
      await addToolResultToHistory(conversationHistory, toolUseId, toolUseResponse.error.data, conversationId);
      sendMessage({ type: 'auth_required' });
    } else {
      console.log("Tool use error", toolUseResponse.error);
      await addToolResultToHistory(conversationHistory, toolUseId, toolUseResponse.error.data, conversationId);
    }
  };

  /**
   * Handles a successful tool response
   */
  const handleToolSuccess = async (toolUseResponse, toolName, toolUseId, conversationHistory, productsToDisplay, conversationId) => {
    // Check if this is a product search result
    if (toolName === 'search_shop_catalog') {
      productsToDisplay.push(...processProductSearchResult(toolUseResponse));
    }

    // Format the tool result content properly
    let toolResultContent;
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

    addToolResultToHistory(conversationHistory, toolUseId, toolResultContent, conversationId);
  };

  /**
   * Processes product search results
   */
  const processProductSearchResult = (toolUseResponse) => {
    try {
      console.log("Processing product search result");
      let products = [];

      if (toolUseResponse.content && toolUseResponse.content.length > 0) {
        // Extract text content from the response
        const content = toolUseResponse.content.find(item => item.type === 'text')?.text;

        if (content) {
          try {
            let responseData;
            if (typeof content === 'object') {
              responseData = content;
            } else if (typeof content === 'string') {
              responseData = JSON.parse(content);
            }

            if (responseData?.products && Array.isArray(responseData.products)) {
              products = responseData.products
                .slice(0, AppConfig.tools.maxProductsToDisplay || 10)
                .map(formatProductData);

              console.log(`Found ${products.length} products to display`);
            }
          } catch (e) {
            console.error("Error parsing product data:", e);
            console.log("Raw content:", content);
          }
        }
      }

      return products;
    } catch (error) {
      console.error("Error processing product search results:", error);
      return [];
    }
  };

  /**
   * Formats a product data object
   */
  const formatProductData = (product) => {
    const price = product.price_range
      ? `${product.price_range.currency} ${product.price_range.min}`
      : (product.variants && product.variants.length > 0
        ? `${product.variants[0].currency} ${product.variants[0].price}`
        : 'Price not available');

    return {
      id: product.product_id || `product-${Math.random().toString(36).substring(7)}`,
      title: product.title || 'Product',
      price: price,
      image_url: product.image_url || '',
      description: product.description || '',
      url: product.url || ''
    };
  };

  /**
   * Adds a tool result to the conversation history in OpenAI format
   * Note: Tool results are saved to DB but NOT included in truncated history
   * to maintain efficient token usage
   */
  const addToolResultToHistory = async (conversationHistory, toolUseId, content, conversationId) => {
    // Create OpenAI-formatted tool result message
    const toolResultMessage = {
      role: 'tool',
      tool_call_id: toolUseId,
      content: typeof content === 'string' ? content : JSON.stringify(content)
    };

    // Save to database for record keeping
    if (conversationId) {
      try {
        await saveMessage(conversationId, 'tool', JSON.stringify({
          tool_call_id: toolUseId,
          content: content
        }));
      } catch (error) {
        console.error('Error saving tool result to database:', error);
      }
    }

    // Note: We don't add tool results to conversationHistory here
    // because our truncated history excludes tool calls/results for efficiency
    // Only user/assistant messages are kept in the working history
  };

  return {
    handleToolError,
    handleToolSuccess,
    processProductSearchResult,
    addToolResultToHistory
  };
}

export default {
  createToolService
};