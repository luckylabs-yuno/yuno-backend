import requests
import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class ShopifyMCPService:
    def __init__(self):
        self.shop_domain = None
        self.mcp_url = None
        self.call_count = 0
        
    def connect_sync(self, shop_domain: str) -> None:
        """Initialize MCP connection"""
        if shop_domain.startswith(('http://', 'https://')):
            from urllib.parse import urlparse
            shop_domain = urlparse(shop_domain).netloc
        
        self.shop_domain = shop_domain
        self.mcp_url = f"https://{shop_domain}/api/mcp"
        
        logger.info(f"🔧 MCP URL set to: {self.mcp_url}")
    
    def _call_mcp_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """Generic method to call any MCP tool following Shopify schema"""
        if not self.mcp_url:
            raise ValueError("MCP not connected. Call connect_sync first.")
        
        self.call_count += 1
        
        request_body = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": self.call_count,
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        try:
            logger.info(f"🔧 Calling MCP tool: {tool_name}")
            logger.info(f"🔧 Arguments: {json.dumps(arguments, indent=2)}")
            
            response = requests.post(
                self.mcp_url,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=30,
                verify=True
            )
            
            logger.info(f"🔧 Response Status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"🔧 HTTP Error {response.status_code}: {response.text}")
                return {"error": f"HTTP {response.status_code}", "data": None}
            
            # Parse JSON-RPC response
            data = response.json()
            
            if "error" in data:
                logger.error(f"🔧 MCP Error: {data['error']}")
                return {"error": data["error"], "data": None}
            
            # Extract content from nested response
            if "result" in data and "content" in data["result"]:
                for content_item in data["result"]["content"]:
                    if content_item["type"] == "text":
                        try:
                            text_content = content_item["text"]
                            parsed_content = json.loads(text_content)
                            
                            logger.info(f"🔧 Successfully parsed MCP response")
                            return {"error": None, "data": parsed_content}
                            
                        except json.JSONDecodeError as e:
                            logger.error(f"🔧 JSON Parse Error: {e}")
                            logger.error(f"🔧 Raw content: {text_content}")
                            
                            # Handle non-JSON responses gracefully
                            if text_content.strip():
                                return {"error": None, "data": {"message": text_content}}
                            else:
                                return {"error": "Empty response", "data": None}
            
            logger.error("🔧 Unexpected response structure")
            return {"error": "Unexpected response format", "data": None}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"🔧 Request failed: {e}")
            return {"error": str(e), "data": None}
        except Exception as e:
            logger.error(f"🔧 Unexpected error: {e}")
            return {"error": str(e), "data": None}
    
    def search_products_sync(self, query: str, filters: Optional[Dict] = None, context: str = "") -> Dict:
        """
        Search products using correct Shopify MCP schema
        
        Schema: search_shop_catalog
        Required: query, context
        Optional: filters, country, language, limit, after
        """
        logger.info(f"🛍️ Searching products: '{query}'")
        
        # ✅ CORRECT: Use only schema-defined parameters
        arguments = {
            "query": query,
            "context": context or f"Customer searching for: {query}",
            "limit": 10  # Optional but useful
        }
        
        # ✅ CORRECT: Add optional parameters only if defined in schema
        if filters and isinstance(filters, list):
            # Only add filters if they're in the correct format from previous responses
            arguments["filters"] = filters
            logger.info(f"🛍️ Added filters: {filters}")
        
        # Add country/language if available (you can enhance this based on user location)
        # arguments["country"] = "IN"  # For Indian rupees
        # arguments["language"] = "EN"
        
        logger.info(f"🛍️ Final MCP arguments: {json.dumps(arguments, indent=2)}")
        
        result = self._call_mcp_tool("search_shop_catalog", arguments)
        
        if result["error"]:
            logger.error(f"🛍️ Product search failed: {result['error']}")
            return {
                "products": [],
                "pagination": {},
                "filters": [],
                "error": result["error"]
            }
        
        data = result["data"]
        
        if not data:
            logger.warning("🛍️ No data returned from MCP")
            return {
                "products": [],
                "pagination": {},
                "filters": [],
                "error": "No data returned"
            }
        
        # Transform products to our format
        products = []
        raw_products = data.get("products", [])
        
        logger.info(f"🛍️ Processing {len(raw_products)} products from MCP")
        
        for i, product in enumerate(raw_products):
            try:
                # Extract price information
                price_range = product.get("price_range", {})
                min_price = float(price_range.get("min", 0)) if price_range.get("min") else 0
                max_price = float(price_range.get("max", 0)) if price_range.get("max") else min_price
                currency = price_range.get("currency", "INR")
                
                # Check availability
                variants = product.get("variants", [])
                in_stock = any(v.get("available", False) for v in variants) if variants else True
                
                # Build product URL
                product_url = product.get("url", "")
                if not product_url and self.shop_domain:
                    product_id = product.get("product_id", "")
                    if "Product/" in product_id:
                        numeric_id = product_id.split("Product/")[-1]
                        product_url = f"https://{self.shop_domain}/products/{numeric_id}"
                
                transformed_product = {
                    "id": product.get("product_id", f"unknown-{i}"),
                    "title": product.get("title", "Unknown Product"),
                    "description": product.get("description", ""),
                    "price": min_price,
                    "price_max": max_price if max_price != min_price else None,
                    "currency": currency,
                    "inStock": in_stock,
                    "image": product.get("image_url", ""),
                    "url": product_url,
                    "tags": product.get("tags", []),
                    "product_type": product.get("product_type", ""),
                    "variants": variants
                }
                
                products.append(transformed_product)
                logger.debug(f"🛍️ Transformed product: {transformed_product['title']}")
                
            except Exception as e:
                logger.error(f"🛍️ Error transforming product {i}: {e}")
                continue
        
        result_data = {
            "products": products,
            "pagination": data.get("pagination", {}),
            "filters": data.get("available_filters", []),
            "error": None
        }
        
        logger.info(f"🛍️ Search complete: {len(products)} products found")
        return result_data
    
    def get_product_details_sync(self, product_id: str, options: Optional[Dict] = None) -> Dict:
        """
        Get product details using correct schema
        
        Schema: get_product_details
        Required: product_id
        Optional: options
        """
        logger.info(f"🔍 Getting product details: {product_id}")
        
        arguments = {"product_id": product_id}
        if options:
            arguments["options"] = options
            
        result = self._call_mcp_tool("get_product_details", arguments)
        return result
    
    def get_policies_sync(self, query: str = "return policy shipping") -> Dict:
        """
        Get store policies using correct schema
        
        Schema: search_shop_policies_and_faqs  
        Required: query
        Optional: context
        """
        logger.info(f"📋 Searching policies: '{query}'")
        
        arguments = {
            "query": query,
            "context": "Customer asking about store policies and terms"
        }
        
        result = self._call_mcp_tool("search_shop_policies_and_faqs", arguments)
        
        if result["error"]:
            logger.error(f"📋 Policy search failed: {result['error']}")
            return {"policies": {}, "error": result["error"]}
        
        data = result["data"]
        
        # Handle different response formats for policies
        if isinstance(data, dict):
            logger.info(f"📋 Policy search successful")
            return {"policies": data, "error": None}
        elif isinstance(data, str):
            logger.info(f"📋 Received text response: {data}")
            return {"policies": {"message": data}, "error": None}
        else:
            logger.warning(f"📋 Unexpected policy data type: {type(data)}")
            return {"policies": {"raw": str(data)}, "error": None}
    
    def update_cart_sync(self, cart_id: Optional[str] = None, add_items: Optional[List[Dict]] = None) -> Dict:
        """
        Update cart using correct schema
        
        Schema: update_cart
        Required: (none - all optional)
        Optional: cart_id, add_items, update_items, remove_line_ids, etc.
        """
        logger.info(f"🛒 Updating cart")
        
        arguments = {}
        if cart_id:
            arguments["cart_id"] = cart_id
        if add_items:
            arguments["add_items"] = add_items
            
        result = self._call_mcp_tool("update_cart", arguments)
        return result
    
    def get_cart_sync(self, cart_id: str) -> Dict:
        """
        Get cart using correct schema
        
        Schema: get_cart
        Required: cart_id
        """
        logger.info(f"🛒 Getting cart: {cart_id}")
        
        arguments = {"cart_id": cart_id}
        result = self._call_mcp_tool("get_cart", arguments)
        return result

    def search_with_filters(self, query: str, available_filters: List[Dict], price_max: Optional[int] = None) -> Dict:
        """
        Perform a filtered search using available filters from previous search
        This is the CORRECT way to filter according to Shopify MCP schema
        """
        logger.info(f"🔍 Performing filtered search for: '{query}'")
        
        # Build filters array using available_filters structure
        filters_to_apply = []
        
        if price_max and available_filters:
            # Look for price filter in available_filters
            for filter_item in available_filters:
                if filter_item.get("label") == "Price":
                    # Use the exact filter structure from available_filters
                    price_filter = {
                        "price": {
                            "min": 0,
                            "max": price_max
                        }
                    }
                    filters_to_apply.append(price_filter)
                    logger.info(f"🔍 Added price filter: max {price_max}")
                    break
        
        # Perform search with filters
        arguments = {
            "query": query,
            "context": f"Filtered search for: {query}",
            "limit": 10
        }
        
        if filters_to_apply:
            arguments["filters"] = filters_to_apply
        
        result = self._call_mcp_tool("search_shop_catalog", arguments)
        
        # Process result same as search_products_sync
        if result["error"]:
            return {
                "products": [],
                "pagination": {},
                "filters": [],
                "error": result["error"]
            }
        
        # Transform and return (same logic as search_products_sync)
        # Use the same transformation as in search_products_sync
        data = result["data"]
        if not data:
            logger.warning("🛍️ No data returned from MCP")
            return {
                "products": [],
                "pagination": {},
                "filters": [],
                "error": "No data returned"
            }
        products = []
        raw_products = data.get("products", [])
        logger.info(f"🛍️ Processing {len(raw_products)} products from MCP (filtered)")
        for i, product in enumerate(raw_products):
            try:
                price_range = product.get("price_range", {})
                min_price = float(price_range.get("min", 0)) if price_range.get("min") else 0
                max_price = float(price_range.get("max", 0)) if price_range.get("max") else min_price
                currency = price_range.get("currency", "INR")
                variants = product.get("variants", [])
                in_stock = any(v.get("available", False) for v in variants) if variants else True
                product_url = product.get("url", "")
                if not product_url and self.shop_domain:
                    product_id = product.get("product_id", "")
                    if "Product/" in product_id:
                        numeric_id = product_id.split("Product/")[-1]
                        product_url = f"https://{self.shop_domain}/products/{numeric_id}"
                transformed_product = {
                    "id": product.get("product_id", f"unknown-{i}"),
                    "title": product.get("title", "Unknown Product"),
                    "description": product.get("description", ""),
                    "price": min_price,
                    "price_max": max_price if max_price != min_price else None,
                    "currency": currency,
                    "inStock": in_stock,
                    "image": product.get("image_url", ""),
                    "url": product_url,
                    "tags": product.get("tags", []),
                    "product_type": product.get("product_type", ""),
                    "variants": variants
                }
                products.append(transformed_product)
                logger.debug(f"🛍️ Transformed product: {transformed_product['title']}")
            except Exception as e:
                logger.error(f"🛍️ Error transforming product {i}: {e}")
                continue
        result_data = {
            "products": products,
            "pagination": data.get("pagination", {}),
            "filters": data.get("available_filters", []),
            "error": None
        }
        logger.info(f"🛍️ Filtered search complete: {len(products)} products found")
        return result_data

    def list_tools(self) -> list:
        """List available tools from the MCP server (tools/list)"""
        if not self.mcp_url:
            raise ValueError("MCP not connected. Call connect_sync first.")
        self.call_count += 1
        request_body = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": self.call_count,
            "params": {}
        }
        try:
            response = requests.post(
                self.mcp_url,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=30,
                verify=True
            )
            if response.status_code != 200:
                logger.error(f"tools/list HTTP Error {response.status_code}: {response.text}")
                return []
            data = response.json()
            if "result" in data and "tools" in data["result"]:
                return data["result"]["tools"]
            else:
                logger.error(f"Unexpected tools/list response: {data}")
                return []
        except Exception as e:
            logger.error(f"Exception in tools/list: {e}")
            return []    