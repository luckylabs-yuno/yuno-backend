# shopify_mcp_service.py - CORRECT IMPLEMENTATION

import httpx
import json
import logging
from typing import Dict, List, Optional
import asyncio

logger = logging.getLogger(__name__)

class ShopifyMCPService:
    def __init__(self):
        self.mcp_client = None
        
    async def connect(self, shop_domain: str) -> None:
        """Connect to Shopify store's MCP server"""
        # CORRECT URL - just /api/mcp without any authentication
        mcp_url = f"https://{shop_domain}/api/mcp"
        
        # No authentication headers needed for MCP!
        self.mcp_client = httpx.AsyncClient(
            base_url=mcp_url,
            headers={"Content-Type": "application/json"},
            timeout=30.0
        )
        
        logger.info(f"MCP client initialized for {shop_domain}")
    
    async def search_products(
        self, 
        query: str, 
        filters: Optional[Dict] = None,
        context: str = ""
    ) -> Dict:
        """Search products using Shopify MCP with JSON-RPC"""
        
        # Build JSON-RPC request
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": "search_shop_catalog",
                "arguments": {
                    "query": query,
                    "context": context or f"Searching for {query}"
                }
            }
        }
        
        # Add filters if provided
        if filters:
            if filters.get('price_range'):
                # Add price filters to arguments
                if 'max' in filters['price_range']:
                    request["params"]["arguments"]["price_max"] = filters['price_range']['max']
                if 'min' in filters['price_range']:
                    request["params"]["arguments"]["price_min"] = filters['price_range']['min']
            
            if filters.get('available'):
                request["params"]["arguments"]["available"] = filters['available']
                
        try:
            logger.debug(f"Sending MCP request: {json.dumps(request, indent=2)}")
            
            response = await self.mcp_client.post("", json=request)
            
            logger.debug(f"MCP Response status: {response.status_code}")
            logger.debug(f"MCP Response headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                logger.error(f"MCP error: {response.text}")
                return {"products": [], "error": f"HTTP {response.status_code}"}
            
            # Parse JSON-RPC response
            data = response.json()
            logger.debug(f"MCP Response: {json.dumps(data, indent=2)[:500]}...")
            
            if "error" in data:
                logger.error(f"JSON-RPC error: {data['error']}")
                return {"products": [], "error": data["error"]}
            
            # Extract products from the result
            products = []
            if "result" in data and "content" in data["result"]:
                # The content is an array with a text item containing JSON
                for content_item in data["result"]["content"]:
                    if content_item["type"] == "text":
                        # Parse the nested JSON string
                        product_data = json.loads(content_item["text"])
                        
                        # Extract products
                        if "products" in product_data:
                            for product in product_data["products"]:
                                products.append({
                                    "id": product["product_id"],
                                    "title": product["title"],
                                    "description": product["description"],
                                    "price": float(product["price_range"]["min"]),
                                    "price_max": float(product["price_range"]["max"]),
                                    "currency": product["price_range"]["currency"],
                                    "inStock": any(v["available"] for v in product.get("variants", [])),
                                    "image": product["image_url"],
                                    "image_alt": product["image_alt_text"],
                                    "product_type": product["product_type"],
                                    "tags": product["tags"],
                                    "variants": product.get("variants", [])
                                })
                        
                        # Store pagination info if needed
                        self.pagination = product_data.get("pagination", {})
                        self.available_filters = product_data.get("available_filters", [])
            
            logger.info(f"Found {len(products)} products via MCP")
            return {
                "products": products,
                "pagination": getattr(self, 'pagination', {}),
                "filters": getattr(self, 'available_filters', [])
            }
            
        except httpx.ReadTimeout:
            logger.error("MCP request timed out")
            return {"products": [], "error": "Request timed out"}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            if 'response' in locals():
                logger.error(f"Raw response: {response.text[:500]}")
            return {"products": [], "error": "Invalid JSON response"}
        except Exception as e:
            logger.error(f"MCP search error: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"products": [], "error": str(e)}
    
    async def get_product_details(self, product_id: str) -> Dict:
        """Get detailed product information"""
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 2,
            "params": {
                "name": "get_product_details",
                "arguments": {
                    "id": product_id
                }
            }
        }
        
        try:
            response = await self.mcp_client.post("", json=request)
            data = response.json()
            
            if "error" in data:
                return {"error": data["error"]}
                
            # Parse product details from response
            if "result" in data and "content" in data["result"]:
                for content_item in data["result"]["content"]:
                    if content_item["type"] == "text":
                        return json.loads(content_item["text"])
            
            return {"error": "No product details found"}
            
        except Exception as e:
            logger.error(f"Get product details error: {e}")
            return {"error": str(e)}
    
    async def get_policies(self) -> Dict:
        """Get store policies via MCP"""
        # Note: Based on the MCP docs, there might be a specific tool for this
        # For now, we can search for policy-related content
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 3,
            "params": {
                "name": "search_shop_catalog",
                "arguments": {
                    "query": "policy shipping return refund",
                    "context": "Customer asking about store policies"
                }
            }
        }
        
        try:
            response = await self.mcp_client.post("", json=request)
            data = response.json()
            
            # For now, return empty policies
            # You might need to implement a specific MCP tool for policies
            return {"policies": {}}
            
        except Exception as e:
            logger.error(f"Policy fetch error: {e}")
            return {"policies": {}, "error": str(e)}

    # Sync wrapper methods
    def connect_sync(self, shop_domain: str) -> None:
        """Sync version of connect - NO ACCESS TOKEN NEEDED!"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.connect(shop_domain))
            logger.info(f"Successfully connected to MCP for {shop_domain}")
        except Exception as e:
            logger.error(f"Failed to connect to MCP: {e}")
            raise

    def search_products_sync(self, query: str, filters: Optional[Dict] = None) -> Dict:
        """Sync version of search_products"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.search_products(query, filters))
            return result
        except Exception as e:
            logger.error(f"Sync product search failed: {e}")
            return {"products": [], "error": str(e)}

    def get_policies_sync(self) -> Dict:
        """Sync version of get_policies"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(self.get_policies())
        except Exception as e:
            logger.error(f"Sync policy fetch failed: {e}")
            return {"policies": {}, "error": str(e)}        return loop.run_until_complete(self.get_policies())