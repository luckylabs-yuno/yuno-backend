# shopify_mcp_service.py - COMPLETE SIMPLIFIED VERSION WITH ALL TOOLS

import requests
import json
import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

class ShopifyMCPService:
    """
    Simplified Shopify MCP client using standard HTTP requests.
    Based on the shop-chat-agent repository patterns.
    """
    
    def __init__(self):
        self.shop_domain = None
        self.mcp_url = None
        
    def connect_sync(self, shop_domain: str) -> None:
        """Initialize MCP connection - just sets the URL"""
        self.shop_domain = shop_domain
        self.mcp_url = f"https://{shop_domain}/api/mcp"
        logger.info(f"MCP URL set to: {self.mcp_url}")
    
    def _call_mcp_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """
        Generic method to call any MCP tool.
        
        All MCP tools use the same JSON-RPC format:
        - jsonrpc: "2.0"
        - method: "tools/call"
        - params.name: The tool name
        - params.arguments: Tool-specific arguments
        """
        if not self.mcp_url:
            raise ValueError("MCP not connected. Call connect_sync first.")
        
        # Build JSON-RPC request
        request_body = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        try:
            logger.debug(f"Calling MCP tool '{tool_name}' with: {json.dumps(arguments, indent=2)}")
            
            # Simple POST request - no auth needed for storefront MCP!
            response = requests.post(
                self.mcp_url,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            logger.debug(f"MCP Response Status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"MCP HTTP error: {response.status_code} - {response.text[:500]}")
                return {"error": f"HTTP {response.status_code}"}
            
            # Parse JSON-RPC response
            data = response.json()
            
            if "error" in data:
                logger.error(f"MCP error: {data['error']}")
                return {"error": data["error"]}
            
            # Extract the actual content from the nested response structure
            if "result" in data and "content" in data["result"]:
                for content_item in data["result"]["content"]:
                    if content_item.get("type") == "text":
                        # Parse the nested JSON string
                        try:
                            return json.loads(content_item["text"])
                        except json.JSONDecodeError:
                            # Sometimes the text might not be JSON
                            return {"text": content_item["text"]}
            
            # If we get here, return the raw result
            return data.get("result", {"error": "Unexpected response format"})
            
        except requests.exceptions.Timeout:
            logger.error("MCP request timed out")
            return {"error": "Request timed out"}
        except requests.exceptions.RequestException as e:
            logger.error(f"MCP request failed: {e}")
            return {"error": str(e)}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse MCP response: {e}")
            return {"error": "Invalid JSON response"}
        except Exception as e:
            logger.error(f"Unexpected MCP error: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}
    
    # ===========================================================================
    # MCP TOOLS FOUND IN SHOPIFY DOCUMENTATION
    # ===========================================================================
    
    def search_products_sync(self, query: str, filters: Optional[Dict] = None, context: str = "") -> Dict:
        """
        Tool: search_shop_catalog
        Search for products in the shop catalog.
        
        Arguments:
        - query: Search query string
        - context: Additional context for the search (optional)
        - filters: Optional filters like price_range, availability
        
        Returns: Products list with pagination and available filters
        """
        arguments = {
            "query": query,
            "context": context or f"Customer searching for: {query}"
        }
        
        # Add optional filters
        if filters:
            if filters.get('price_range'):
                if 'min' in filters['price_range']:
                    arguments["price_min"] = filters['price_range']['min']
                if 'max' in filters['price_range']:
                    arguments["price_max"] = filters['price_range']['max']
            if 'available' in filters:
                arguments["available"] = filters['available']
            if filters.get('product_type'):
                arguments["product_type"] = filters['product_type']
            if filters.get('vendor'):
                arguments["vendor"] = filters['vendor']
            if filters.get('tags'):
                arguments["tags"] = filters['tags']
        
        result = self._call_mcp_tool("search_shop_catalog", arguments)
        
        # Transform products to our standardized format
        products = []
        if "products" in result:
            for product in result["products"]:
                products.append({
                    "id": product.get("product_id", ""),
                    "title": product.get("title", "Unknown"),
                    "description": product.get("description", ""),
                    "price": float(product["price_range"]["min"]) if "price_range" in product else 0,
                    "price_max": float(product["price_range"]["max"]) if "price_range" in product else 0,
                    "currency": product.get("price_range", {}).get("currency", "INR"),
                    "inStock": any(v.get("available", False) for v in product.get("variants", [])),
                    "image": product.get("image_url", ""),
                    "image_alt": product.get("image_alt_text", ""),
                    "tags": product.get("tags", []),
                    "product_type": product.get("product_type", ""),
                    "vendor": product.get("vendor", ""),
                    "variants": product.get("variants", [])
                })
        
        return {
            "products": products,
            "pagination": result.get("pagination", {}),
            "filters": result.get("available_filters", []),
            "error": result.get("error")
        }
    
    def get_product_details_sync(self, product_id: str) -> Dict:
        """
        Tool: get_product_details
        Get detailed information about a specific product.
        
        Arguments:
        - id: Product ID (e.g., "gid://shopify/Product/123456")
        
        Returns: Detailed product information including all variants
        """
        result = self._call_mcp_tool("get_product_details", {"id": product_id})
        return result
    
    def update_cart_sync(self, items: List[Dict], action: str = "add") -> Dict:
        """
        Tool: update_cart
        Add, update, or remove items from the cart.
        
        Arguments:
        - items: List of items with product_id/variant_id and quantity
          Example: [{"variant_id": "gid://shopify/ProductVariant/123", "quantity": 2}]
        - action: "add", "update", or "remove" (optional, defaults to "add")
        
        Returns: Updated cart with checkout URL
        """
        arguments = {
            "items": items
        }
        if action and action != "add":
            arguments["action"] = action
            
        result = self._call_mcp_tool("update_cart", arguments)
        return result
    
    def get_cart_sync(self) -> Dict:
        """
        Tool: get_cart (if available)
        Get current cart contents.
        
        Returns: Current cart items and totals
        """
        result = self._call_mcp_tool("get_cart", {})
        return result
    
    def get_shop_info_sync(self) -> Dict:
        """
        Tool: get_shop_info (if available)
        Get general shop information including policies.
        
        Returns: Shop name, policies, contact info, etc.
        """
        result = self._call_mcp_tool("get_shop_info", {})
        return result
    
    def get_shipping_rates_sync(self, address: Dict) -> Dict:
        """
        Tool: get_shipping_rates (if available)
        Get shipping rates for a given address.
        
        Arguments:
        - address: Dictionary with country, province/state, zip
        
        Returns: Available shipping methods and rates
        """
        result = self._call_mcp_tool("get_shipping_rates", {"address": address})
        return result
    
    # ===========================================================================
    # HELPER METHODS
    # ===========================================================================
    
    def get_policies_sync(self) -> Dict:
        """
        Try to get store policies.
        Note: This might be part of get_shop_info or require a search query.
        """
        # First try dedicated shop info tool
        shop_info = self.get_shop_info_sync()
        if not shop_info.get('error') and shop_info.get('policies'):
            return {"policies": shop_info['policies']}
        
        # Fallback: Try searching for policy information
        policy_search = self.search_products_sync(
            "shipping return refund policy",
            context="Customer asking about store policies"
        )
        
        # For now, return empty if no specific policy tool exists
        return {"policies": {}}
    
    def check_inventory_sync(self, variant_id: str) -> Dict:
        """
        Check inventory for a specific variant.
        This might be part of get_product_details.
        """
        # Try to get product details which should include inventory
        if variant_id.startswith("gid://shopify/ProductVariant/"):
            # Extract product ID from variant ID if possible
            # For now, return a not implemented response
            return {"error": "Inventory check not directly available via MCP"}
        
        return {"error": "Invalid variant ID format"}

# ===========================================================================
# MCP TOOLS SUMMARY
# Based on Shopify documentation and shop-chat-agent repository:
#
# CONFIRMED TOOLS:
# 1. search_shop_catalog - Search products with filters
#    - Arguments: query, context, price_min, price_max, available, product_type, vendor, tags
#    - Returns: products[], pagination{}, available_filters[]
#
# 2. get_product_details - Get specific product info
#    - Arguments: id (product ID)
#    - Returns: Full product details with variants
#
# 3. update_cart - Manage cart items
#    - Arguments: items[] (with variant_id, quantity), action
#    - Returns: Updated cart, checkout URL
#
# LIKELY AVAILABLE (mentioned in docs):
# 4. get_cart - Get current cart
# 5. get_shop_info - Shop details and policies
# 6. get_shipping_rates - Calculate shipping
#
# CUSTOMER ACCOUNT TOOLS (require authentication):
# - get_order_history
# - get_customer_info
# - update_customer_address
# ===========================================================================