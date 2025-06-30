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
                
                # Ensure tags is a list of strings
                tags = product.get("tags", [])
                if not isinstance(tags, list):
                    tags = []
                tags = [str(t) for t in tags]
                
                # Ensure product_type is a string
                product_type = product.get("product_type", "")
                if not isinstance(product_type, str):
                    product_type = str(product_type)
                
                # Ensure all values in transformed_product are of the correct type
                # id, title, description, image, url, product_type: str
                # price, price_max: float or None
                # currency: str
                # inStock: bool
                # tags: list of str
                # variants: list
                # If any value is a dict, convert to string or set to default
                
                id_val = product.get("product_id", f"unknown-{i}")
                if isinstance(id_val, dict):
                    id_val = str(id_val)
                title_val = product.get("title", "Unknown Product")
                if isinstance(title_val, dict):
                    title_val = str(title_val)
                description_val = product.get("description", "")
                if isinstance(description_val, dict):
                    description_val = str(description_val)
                image_val = product.get("image_url", "")
                if isinstance(image_val, dict):
                    image_val = str(image_val)
                url_val = product_url
                if isinstance(url_val, dict):
                    url_val = str(url_val)
                
                transformed_product = {
                    "id": id_val,
                    "title": title_val,
                    "description": description_val,
                    "price": min_price,
                    "price_max": max_price if max_price != min_price else None,
                    "currency": currency,
                    "inStock": in_stock,
                    "image": image_val,
                    "url": url_val,
                    "tags": tags,
                    "product_type": product_type,
                    "variants": variants if isinstance(variants, list) else []
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

    def update_cart_sync(self, merchandise_id: str, quantity: int = 1) -> Dict:
        """
        Update cart using MCP update_cart tool
        
        Args:
            merchandise_id: Shopify product variant ID (e.g., "gid://shopify/Product/123")
            quantity: Quantity to add (1 to add, 0 to remove)
        
        Returns:
            Dict with cart data and checkout_url
        """
        try:
            logger.info(f"🛒 Updating cart: {merchandise_id} x {quantity}")
            
            # Build MCP arguments for update_cart tool
            arguments = {
                "lines": [
                    {
                        "merchandise_id": merchandise_id,
                        "quantity": quantity
                    }
                ]
            }
            
            logger.info(f"🛒 MCP cart arguments: {json.dumps(arguments, indent=2)}")
            
            # Call the MCP tool (same way as search_shop_catalog)
            result = self._call_mcp_tool("update_cart", arguments)
            
            if result["error"]:
                logger.error(f"🛒 Cart update failed: {result['error']}")
                return {
                    "success": False,
                    "error": result["error"],
                    "cart": None,
                    "checkout_url": None
                }
            
            # Parse the MCP response
            data = result["data"]
            
            if not data or not data.get("content"):
                logger.warning("🛒 No cart data returned from MCP")
                return {
                    "success": False,
                    "error": "No cart data returned",
                    "cart": None,
                    "checkout_url": None
                }
            
            # Extract cart information from MCP response
            content = data.get("content", [])
            cart_data = None
            checkout_url = None
            
            # Parse the text content which contains JSON
            for item in content:
                if item.get("type") == "text":
                    try:
                        text_content = item.get("text", "{}")
                        parsed_content = json.loads(text_content)
                        
                        # Extract cart data
                        cart_data = parsed_content.get("cart", {})
                        # Extract and sanitize checkout_url
                        checkout_url_val = cart_data.get("checkout_url")
                        if isinstance(checkout_url_val, str) or checkout_url_val is None:
                            checkout_url = checkout_url_val
                        else:
                            checkout_url = str(checkout_url_val)
                        # Also ensure cart_data['checkout_url'] is a string or None
                        if "checkout_url" in cart_data and not (isinstance(cart_data["checkout_url"], str) or cart_data["checkout_url"] is None):
                            cart_data["checkout_url"] = str(cart_data["checkout_url"])
                        
                        logger.info(f"🛒 ✅ Cart updated successfully")
                        logger.info(f"🛒 Checkout URL: {checkout_url}")
                        logger.info(f"🛒 Cart total: {cart_data.get('cost', {}).get('total_amount', {}).get('amount', '0')}")
                        
                        break
                        
                    except json.JSONDecodeError as e:
                        logger.error(f"🛒 Failed to parse cart response: {e}")
                        continue
            
            # Aggressive sanitizer for cart_data
            def sanitize_value(v):
                if isinstance(v, (str, int, float, bool)) or v is None:
                    return v
                else:
                    return str(v)
            import json as _json
            sanitized_cart_data = None
            if cart_data:
                sanitized_cart_data = {k: sanitize_value(v) for k, v in cart_data.items()}
            cart_str = _json.dumps(sanitized_cart_data) if sanitized_cart_data is not None else None
            return {
                "success": True,
                "error": None,
                "cart": cart_str,
                "checkout_url": checkout_url,
                "merchandise_id": merchandise_id,
                "quantity": quantity
            }
            
        except Exception as e:
            logger.error(f"🛒 Cart update exception: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "cart": None,
                "checkout_url": None
            }    

    def tools_list_sync(self) -> dict:
        """
        Get the list of available tools from the MCP server.
        """
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
                logger.error(f"🔧 HTTP Error {response.status_code}: {response.text}")
                return {"error": f"HTTP {response.status_code}", "tools": []}
            data = response.json()
            if "error" in data:
                logger.error(f"🔧 MCP Error: {data['error']}")
                return {"error": data["error"], "tools": []}
            tools = data.get("result", {}).get("tools", [])
            return {"error": None, "tools": tools}
        except Exception as e:
            logger.error(f"🔧 MCP tools/list failed: {e}")
            return {"error": str(e), "tools": []}    