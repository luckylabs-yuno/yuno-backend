import requests
import json
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class ShopifyMCPService:
    """
    Simplified Shopify MCP Service - No Auth Required!
    
    This service connects directly to any Shopify store's public MCP endpoint
    without requiring OAuth tokens or Admin API access.
    """
    
    def __init__(self):
        self.shop_domain = None
        self.mcp_url = None
        
    def connect_sync(self, shop_domain: str) -> None:
        """
        Initialize MCP connection - just sets the URL
        No authentication needed for public MCP endpoints!
        """
        # Clean up domain format
        if not shop_domain.endswith('.myshopify.com'):
            shop_domain = f"{shop_domain}.myshopify.com"
            
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
            
            # Simple POST request - no auth headers needed!
            response = requests.post(
                self.mcp_url,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            logger.debug(f"MCP Response Status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"MCP HTTP error: {response.status_code} - {response.text}")
                return {"error": f"HTTP {response.status_code}", "data": None}
            
            # Parse JSON-RPC response
            data = response.json()
            
            if "error" in data:
                logger.error(f"MCP error: {data['error']}")
                return {"error": data["error"], "data": None}
            
            # Extract the actual content from the nested response
            if "result" in data and "content" in data["result"]:
                for content_item in data["result"]["content"]:
                    if content_item["type"] == "text":
                        # Parse the nested JSON content
                        parsed_content = json.loads(content_item["text"])
                        return {"error": None, "data": parsed_content}
            
            return {"error": "Unexpected response format", "data": None}
            
        except requests.exceptions.Timeout:
            logger.error("MCP request timed out")
            return {"error": "Request timed out", "data": None}
        except requests.exceptions.RequestException as e:
            logger.error(f"MCP request failed: {e}")
            return {"error": str(e), "data": None}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse MCP response: {e}")
            return {"error": "Invalid JSON response", "data": None}
        except Exception as e:
            logger.error(f"Unexpected MCP error: {type(e).__name__}: {e}")
            return {"error": str(e), "data": None}
    
    def search_products_sync(self, query: str, filters: Optional[Dict] = None, context: str = "") -> Dict:
        """
        Search products using MCP
        Returns: {"products": [...], "pagination": {...}, "filters": [...], "error": None}
        """
        arguments = {
            "query": query,
            "context": context or f"Customer searching for: {query}"
        }
        
        # Add optional filters
        if filters:
            if filters.get('price_range'):
                if 'max' in filters['price_range']:
                    arguments["limit"] = 10  # Standard limit
            if filters.get('category'):
                arguments["query"] = f"{query} {filters['category']}"
        
        result = self._call_mcp_tool("search_shop_catalog", arguments)
        
        if result["error"]:
            return {
                "products": [],
                "pagination": {},
                "filters": [],
                "error": result["error"]
            }
        
        data = result["data"]
        
        # Transform products to consistent format
        products = []
        if "products" in data:
            for product in data["products"]:
                # Extract price information
                price_range = product.get("price_range", {})
                min_price = float(price_range.get("min", 0)) if price_range.get("min") else 0
                max_price = float(price_range.get("max", 0)) if price_range.get("max") else min_price
                currency = price_range.get("currency", "INR")
                
                # Check availability from variants
                variants = product.get("variants", [])
                in_stock = any(v.get("available", False) for v in variants) if variants else True
                
                products.append({
                    "id": product.get("product_id", ""),
                    "title": product.get("title", "Unknown Product"),
                    "description": product.get("description", ""),
                    "price": min_price,
                    "price_max": max_price if max_price != min_price else None,
                    "currency": currency,
                    "inStock": in_stock,
                    "image": product.get("image_url", ""),
                    "url": product.get("url", ""),
                    "tags": product.get("tags", []),
                    "product_type": product.get("product_type", ""),
                    "variants": variants
                })
        
        return {
            "products": products,
            "pagination": data.get("pagination", {}),
            "filters": data.get("available_filters", []),
            "error": None
        }
    
    def get_product_details_sync(self, product_id: str, options: Optional[Dict] = None) -> Dict:
        """Get detailed product information"""
        arguments = {"product_id": product_id}
        if options:
            arguments["options"] = options
            
        result = self._call_mcp_tool("get_product_details", arguments)
        return result
    
    def get_policies_sync(self, query: str = "return policy shipping") -> Dict:
        """
        Get store policies by searching for policy-related content
        Since there's no direct policy tool, we search for policy information
        """
        arguments = {
            "query": query,
            "context": "Customer asking about store policies and terms"
        }
        
        result = self._call_mcp_tool("search_shop_policies_and_faqs", arguments)
        
        if result["error"]:
            return {"policies": {}, "error": result["error"]}
        
        return {
            "policies": result["data"],
            "error": None
        }
    
    def update_cart_sync(self, cart_id: Optional[str] = None, add_items: Optional[List[Dict]] = None) -> Dict:
        """
        Update cart with items
        Example: add_items = [{"variant_id": "gid://shopify/ProductVariant/123", "quantity": 2}]
        """
        arguments = {}
        
        if cart_id:
            arguments["cart_id"] = cart_id
        if add_items:
            arguments["add_items"] = add_items
            
        result = self._call_mcp_tool("update_cart", arguments)
        return result
    
    def get_cart_sync(self, cart_id: str) -> Dict:
        """Get current cart information"""
        arguments = {"cart_id": cart_id}
        result = self._call_mcp_tool("get_cart", arguments)
        return result

    @staticmethod
    def is_shopify_domain(domain: str) -> bool:
        """Check if a domain is a Shopify store"""
        # Simple heuristic - you might want to enhance this
        shopify_indicators = [
            '.myshopify.com',
            'shopify' in domain.lower(),
            # You could add more sophisticated detection here
        ]
        return any(indicator in domain for indicator in shopify_indicators)
    
    @staticmethod
    def extract_shop_domain(url_or_domain: str) -> Optional[str]:
        """Extract shop domain from URL or domain string"""
        try:
            if url_or_domain.startswith(('http://', 'https://')):
                parsed = urlparse(url_or_domain)
                domain = parsed.netloc
            else:
                domain = url_or_domain
            
            # Handle different Shopify domain formats
            if '.myshopify.com' in domain:
                return domain
            elif domain.endswith('.com') and not domain.endswith('.myshopify.com'):
                # This might be a custom domain - you'd need additional logic
                # For now, return None and handle custom domains separately
                return None
            else:
                # Assume it's a shop name
                return f"{domain}.myshopify.com"
                
        except Exception as e:
            logger.error(f"Error extracting shop domain from {url_or_domain}: {e}")
            return None