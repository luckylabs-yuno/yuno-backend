# shopify_mcp_service.py - SIMPLIFIED VERSION

import requests
import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class ShopifyMCPService:
    def __init__(self):
        self.shop_domain = None
        self.mcp_url = None
        
    def connect_sync(self, shop_domain: str) -> None:
        """Initialize MCP connection - just sets the URL"""
        self.shop_domain = shop_domain
        self.mcp_url = f"https://{shop_domain}/api/mcp"
        logger.info(f"MCP URL set to: {self.mcp_url}")
    
    def _call_mcp_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """Generic method to call any MCP tool"""
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
            
            # Simple POST request - no special auth needed!
            response = requests.post(
                self.mcp_url,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            logger.debug(f"MCP Response Status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"MCP HTTP error: {response.status_code} - {response.text}")
                return {"error": f"HTTP {response.status_code}", "products": []}
            
            # Parse JSON-RPC response
            data = response.json()
            
            if "error" in data:
                logger.error(f"MCP error: {data['error']}")
                return {"error": data["error"], "products": []}
            
            # Extract the actual content from the response
            if "result" in data and "content" in data["result"]:
                for content_item in data["result"]["content"]:
                    if content_item["type"] == "text":
                        # Parse the nested JSON
                        return json.loads(content_item["text"])
            
            return {"error": "Unexpected response format", "products": []}
            
        except requests.exceptions.Timeout:
            logger.error("MCP request timed out")
            return {"error": "Request timed out", "products": []}
        except requests.exceptions.RequestException as e:
            logger.error(f"MCP request failed: {e}")
            return {"error": str(e), "products": []}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse MCP response: {e}")
            return {"error": "Invalid JSON response", "products": []}
        except Exception as e:
            logger.error(f"Unexpected MCP error: {type(e).__name__}: {e}")
            return {"error": str(e), "products": []}
    
    def search_products_sync(self, query: str, filters: Optional[Dict] = None, context: str = "") -> Dict:
        """Search products using MCP"""
        arguments = {
            "query": query,
            "context": context or f"Customer searching for: {query}"
        }
        
        # Add filters if provided
        if filters:
            if filters.get('price_range') and 'max' in filters['price_range']:
                arguments["price_max"] = filters['price_range']['max']
            if filters.get('available'):
                arguments["available"] = filters['available']
        
        result = self._call_mcp_tool("search_shop_catalog", arguments)
        
        # Transform products to our format
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
                    "tags": product.get("tags", []),
                    "product_type": product.get("product_type", "")
                })
        
        return {
            "products": products,
            "pagination": result.get("pagination", {}),
            "filters": result.get("available_filters", []),
            "error": result.get("error")
        }
    
    def get_product_details_sync(self, product_id: str) -> Dict:
        """Get detailed product information"""
        result = self._call_mcp_tool("get_product_details", {"id": product_id})
        return result
    
    def update_cart_sync(self, items: List[Dict]) -> Dict:
        """Update cart with items"""
        # Example: [{"product_id": "gid://shopify/Product/123", "quantity": 2}]
        result = self._call_mcp_tool("update_cart", {"items": items})
        return result
    
    def get_policies_sync(self) -> Dict:
        """Try to get store policies - might need a different approach"""
        # Note: The shop-chat-agent repo suggests policies might be available
        # through search or a specific tool. For now, return empty.
        return {"policies": {}}