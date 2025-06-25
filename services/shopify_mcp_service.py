import requests
import json
import logging
from typing import Dict, List, Optional
import time

logger = logging.getLogger(__name__)

class ShopifyMCPService:
    def __init__(self):
        self.shop_domain = None
        self.mcp_url = None
        self.call_count = 0
        
    def connect_sync(self, shop_domain: str) -> None:
        """Initialize MCP connection with detailed logging"""
        logger.info("🔧 ===== MCP CONNECTION SETUP =====")
        logger.info(f"🔧 Input domain: '{shop_domain}'")
        logger.info(f"🔧 Domain type: {type(shop_domain)}")
        
        # Clean up the domain
        original_domain = shop_domain
        if shop_domain.startswith(('http://', 'https://')):
            from urllib.parse import urlparse
            parsed = urlparse(shop_domain)
            shop_domain = parsed.netloc
            logger.info(f"🔧 Extracted domain from URL: '{original_domain}' -> '{shop_domain}'")
        
        # Store the original domain for MCP URL
        self.shop_domain = shop_domain
        self.mcp_url = f"https://{shop_domain}/api/mcp"
        
        logger.info(f"🔧 Final shop domain: {self.shop_domain}")
        logger.info(f"🔧 MCP URL: {self.mcp_url}")
        logger.info(f"🔧 SSL verification: Enabled")
        logger.info("🔧 ===== MCP CONNECTION READY =====")
    
    def _call_mcp_tool(self, tool_name: str, arguments: Dict) -> Dict:
        """Generic method to call any MCP tool with extensive logging"""
        self.call_count += 1
        call_id = self.call_count
        
        logger.info(f"🔧 ===== MCP CALL #{call_id} START =====")
        logger.info(f"🔧 Tool: {tool_name}")
        logger.info(f"🔧 MCP URL: {self.mcp_url}")
        logger.info(f"🔧 Arguments count: {len(arguments)}")
        
        if not self.mcp_url:
            logger.error("🔧 MCP not connected! Call connect_sync first.")
            raise ValueError("MCP not connected. Call connect_sync first.")
        
        # Log all arguments in detail
        for key, value in arguments.items():
            if isinstance(value, str) and len(value) > 100:
                logger.info(f"🔧 Argument '{key}': '{value[:100]}...' (truncated)")
            else:
                logger.info(f"🔧 Argument '{key}': {repr(value)}")
        
        # Build JSON-RPC request
        request_body = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": call_id,
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        logger.info(f"🔧 Request body size: {len(json.dumps(request_body))} characters")
        logger.debug(f"🔧 Full request body: {json.dumps(request_body, indent=2)}")
        
        # Record timing
        start_time = time.time()
        
        try:
            logger.info(f"🔧 Sending POST request to: {self.mcp_url}")
            logger.info(f"🔧 Request headers: Content-Type: application/json")
            logger.info(f"🔧 Timeout: 30 seconds")
            
            response = requests.post(
                self.mcp_url,
                json=request_body,
                headers={"Content-Type": "application/json"},
                timeout=30,
                verify=True
            )
            
            response_time = time.time() - start_time
            logger.info(f"🔧 Response received in {response_time:.3f} seconds")
            logger.info(f"🔧 Response status: {response.status_code}")
            logger.info(f"🔧 Response headers: {dict(response.headers)}")
            logger.info(f"🔧 Response size: {len(response.content)} bytes")
            
            if response.status_code != 200:
                logger.error(f"🔧 HTTP ERROR DETAILS:")
                logger.error(f"🔧 Status: {response.status_code}")
                logger.error(f"🔧 Reason: {response.reason}")
                logger.error(f"🔧 Response text: {response.text}")
                logger.error(f"🔧 Response headers: {dict(response.headers)}")
                return {"error": f"HTTP {response.status_code}: {response.reason}", "data": None}
            
            # Parse JSON-RPC response
            try:
                data = response.json()
                logger.info(f"🔧 JSON parsing successful")
                logger.info(f"🔧 Response JSON keys: {list(data.keys())}")
                
                # Log response structure
                if "result" in data:
                    result = data["result"]
                    logger.info(f"🔧 Result keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
                    
                    if isinstance(result, dict) and "content" in result:
                        content = result["content"]
                        logger.info(f"🔧 Content items: {len(content) if isinstance(content, list) else type(content)}")
                        
                        if isinstance(content, list):
                            for i, item in enumerate(content):
                                if isinstance(item, dict):
                                    logger.info(f"🔧 Content[{i}] keys: {list(item.keys())}")
                                    logger.info(f"🔧 Content[{i}] type: {item.get('type', 'unknown')}")
                                    
                                    if item.get("type") == "text" and "text" in item:
                                        text_content = item["text"]
                                        logger.info(f"🔧 Content[{i}] text length: {len(text_content)} characters")
                                        logger.debug(f"🔧 Content[{i}] text preview: {text_content[:200]}...")
                
                logger.debug(f"🔧 Full response JSON: {json.dumps(data, indent=2)}")
                
            except json.JSONDecodeError as e:
                logger.error(f"🔧 JSON parsing failed: {e}")
                logger.error(f"🔧 Raw response content: {response.text}")
                logger.error(f"🔧 Content type: {response.headers.get('content-type', 'unknown')}")
                return {"error": f"Invalid JSON response: {e}", "data": None}
            
            # Check for JSON-RPC errors
            if "error" in data:
                error_info = data["error"]
                logger.error(f"🔧 JSON-RPC ERROR:")
                logger.error(f"🔧 Error: {json.dumps(error_info, indent=2)}")
                return {"error": error_info, "data": None}
            
            # Extract the actual content from the nested response
            if "result" in data and "content" in data["result"]:
                logger.info(f"🔧 Extracting content from result...")
                
                for i, content_item in enumerate(data["result"]["content"]):
                    logger.info(f"🔧 Processing content item {i}: {content_item.get('type', 'unknown')}")
                    
                    if content_item["type"] == "text":
                        try:
                            text_content = content_item["text"]
                            logger.info(f"🔧 Parsing nested JSON content ({len(text_content)} chars)")
                            
                            # Parse the nested JSON content
                            parsed_content = json.loads(text_content)
                            logger.info(f"🔧 Nested JSON keys: {list(parsed_content.keys())}")
                            
                            # Log specific important data
                            if "products" in parsed_content:
                                products = parsed_content["products"]
                                logger.info(f"🔧 Products found: {len(products)}")
                                
                                for j, product in enumerate(products[:3]):  # Log first 3 products
                                    title = product.get("title", "No title")
                                    price_range = product.get("price_range", {})
                                    price = price_range.get("min", "No price")
                                    logger.info(f"🔧 Product[{j}]: '{title}' - {price}")
                            
                            if "pagination" in parsed_content:
                                pagination = parsed_content["pagination"]
                                logger.info(f"🔧 Pagination: {pagination}")
                            
                            if "available_filters" in parsed_content:
                                filters = parsed_content["available_filters"]
                                logger.info(f"🔧 Available filters: {len(filters)} types")
                                for f in filters:
                                    logger.info(f"🔧 Filter: {f.get('label', 'Unknown')}")
                            
                            logger.info(f"🔧 ===== MCP CALL #{call_id} SUCCESS =====")
                            return {"error": None, "data": parsed_content}
                            
                        except json.JSONDecodeError as e:
                            logger.error(f"🔧 Failed to parse nested JSON: {e}")
                            logger.error(f"🔧 Nested content preview: {content_item['text'][:500]}...")
                            return {"error": f"Invalid nested JSON: {e}", "data": None}
            
            logger.warning(f"🔧 Unexpected response structure - no extractable content")
            logger.warning(f"🔧 Response structure: {list(data.keys())}")
            logger.info(f"🔧 ===== MCP CALL #{call_id} FAILED =====")
            return {"error": "Unexpected response format", "data": None}
            
        except requests.exceptions.SSLError as e:
            logger.error(f"🔧 SSL/Certificate error:")
            logger.error(f"🔧 URL: {self.mcp_url}")
            logger.error(f"🔧 Error: {e}")
            logger.error(f"🔧 Suggestion: Store may not support MCP or has certificate issues")
            logger.info(f"🔧 ===== MCP CALL #{call_id} SSL ERROR =====")
            return {"error": f"SSL certificate error - store may not support MCP", "data": None}
            
        except requests.exceptions.ConnectionError as e:
            logger.error(f"🔧 Connection error:")
            logger.error(f"🔧 URL: {self.mcp_url}")
            logger.error(f"🔧 Error: {e}")
            logger.error(f"🔧 Suggestion: Store may not have MCP enabled")
            logger.info(f"🔧 ===== MCP CALL #{call_id} CONNECTION ERROR =====")
            return {"error": "Cannot connect to store - MCP may not be available", "data": None}
            
        except requests.exceptions.Timeout:
            logger.error(f"🔧 Request timeout after 30 seconds")
            logger.error(f"🔧 URL: {self.mcp_url}")
            logger.info(f"🔧 ===== MCP CALL #{call_id} TIMEOUT =====")
            return {"error": "Request timed out", "data": None}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"🔧 Request exception:")
            logger.error(f"🔧 Type: {type(e).__name__}")
            logger.error(f"🔧 Error: {e}")
            logger.error(f"🔧 URL: {self.mcp_url}")
            logger.info(f"🔧 ===== MCP CALL #{call_id} REQUEST ERROR =====")
            return {"error": str(e), "data": None}
            
        except Exception as e:
            logger.error(f"🔧 Unexpected error:")
            logger.error(f"🔧 Type: {type(e).__name__}")
            logger.error(f"🔧 Error: {e}")
            logger.error(f"🔧 URL: {self.mcp_url}")
            import traceback
            logger.error(f"🔧 Traceback: {traceback.format_exc()}")
            logger.info(f"🔧 ===== MCP CALL #{call_id} UNEXPECTED ERROR =====")
            return {"error": str(e), "data": None}
    
    def search_products_sync(self, query: str, filters: Optional[Dict] = None, context: str = "") -> Dict:
        """Search products using MCP with detailed logging"""
        logger.info("🛍️ ===== PRODUCT SEARCH START =====")
        logger.info(f"🛍️ Search query: '{query}'")
        logger.info(f"🛍️ Query length: {len(query)} characters")
        logger.info(f"🛍️ Context: '{context}'")
        logger.info(f"🛍️ Filters provided: {filters is not None}")
        
        if filters:
            logger.info(f"🛍️ Filters detail: {json.dumps(filters, indent=2)}")
        
        # Build arguments
        arguments = {
            "query": query,
            "context": context or f"Customer searching for: {query}"
        }
        
        # Add filters if provided (log each addition)
        if filters:
            logger.info(f"🛍️ Processing filters...")
            
            if filters.get('price_range'):
                price_range = filters['price_range']
                logger.info(f"🛍️ Price range filter: {price_range}")
                
                if 'max' in price_range:
                    arguments["price_max"] = price_range['max']
                    logger.info(f"🛍️ Added price_max: {price_range['max']}")
                
                if 'min' in price_range:
                    arguments["price_min"] = price_range['min']
                    logger.info(f"🛍️ Added price_min: {price_range['min']}")
            
            if filters.get('category'):
                arguments["category"] = filters['category']
                logger.info(f"🛍️ Added category filter: {filters['category']}")
            
            if filters.get('available') is not None:
                arguments["available"] = filters['available']
                logger.info(f"🛍️ Added availability filter: {filters['available']}")
        
        # Add standard parameters
        arguments["limit"] = 10
        logger.info(f"🛍️ Set limit to: 10")
        
        logger.info(f"🛍️ Final arguments: {json.dumps(arguments, indent=2)}")
        logger.info(f"🛍️ Calling MCP search_shop_catalog...")
        
        # Make the MCP call
        result = self._call_mcp_tool("search_shop_catalog", arguments)
        
        logger.info(f"🛍️ MCP call completed")
        logger.info(f"🛍️ Has error: {result['error'] is not None}")
        
        if result["error"]:
            logger.error(f"🛍️ MCP search failed: {result['error']}")
            logger.info("🛍️ ===== PRODUCT SEARCH FAILED =====")
            return {
                "products": [],
                "pagination": {},
                "filters": [],
                "error": result["error"]
            }
        
        data = result["data"]
        logger.info(f"🛍️ Data received: {data is not None}")
        
        if not data:
            logger.error("🛍️ No data returned from MCP")
            logger.info("🛍️ ===== PRODUCT SEARCH NO DATA =====")
            return {
                "products": [],
                "pagination": {},
                "filters": [],
                "error": "No data returned"
            }
        
        # Log raw data structure
        logger.info(f"🛍️ Raw data keys: {list(data.keys())}")
        
        # Transform products to consistent format
        products = []
        raw_products = data.get("products", [])
        
        logger.info(f"🛍️ Raw products count: {len(raw_products)}")
        logger.info(f"🛍️ Starting product transformation...")
        
        for i, product in enumerate(raw_products):
            logger.debug(f"🛍️ Transforming product {i}...")
            logger.debug(f"🛍️ Product {i} keys: {list(product.keys()) if isinstance(product, dict) else type(product)}")
            
            try:
                # Extract and log each field
                product_id = product.get("product_id", f"unknown-{i}")
                title = product.get("title", "Unknown Product")
                description = product.get("description", "")
                product_type = product.get("product_type", "")
                tags = product.get("tags", [])
                
                logger.debug(f"🛍️ Product {i} title: '{title}'")
                logger.debug(f"🛍️ Product {i} type: '{product_type}'")
                logger.debug(f"🛍️ Product {i} tags: {tags}")
                
                # Extract price information
                price_range = product.get("price_range", {})
                logger.debug(f"🛍️ Product {i} price_range: {price_range}")
                
                min_price = 0
                max_price = 0
                currency = "INR"
                
                if price_range:
                    try:
                        min_price_str = price_range.get("min", "0")
                        max_price_str = price_range.get("max", "0")
                        currency = price_range.get("currency", "INR")
                        
                        min_price = float(min_price_str) if min_price_str else 0
                        max_price = float(max_price_str) if max_price_str else min_price
                        
                        logger.debug(f"🛍️ Product {i} price: {currency} {min_price}-{max_price}")
                        
                    except (ValueError, TypeError) as e:
                        logger.warning(f"🛍️ Failed to parse price for product {i}: {e}")
                        logger.warning(f"🛍️ Price data: {price_range}")
                
                # Check availability from variants
                variants = product.get("variants", [])
                logger.debug(f"🛍️ Product {i} variants: {len(variants)}")
                
                in_stock = True  # Default
                if variants:
                    available_variants = [v for v in variants if v.get("available", False)]
                    in_stock = len(available_variants) > 0
                    logger.debug(f"🛍️ Product {i} available variants: {len(available_variants)}/{len(variants)}")
                
                # Build product URL
                product_url = product.get("url", "")
                if not product_url and "Product/" in product_id:
                    numeric_id = product_id.split("Product/")[-1]
                    product_url = f"https://{self.shop_domain}/products/{numeric_id}"
                    logger.debug(f"🛍️ Product {i} constructed URL: {product_url}")
                
                # Create transformed product
                transformed_product = {
                    "id": product_id,
                    "title": title,
                    "description": description,
                    "price": min_price,
                    "price_max": max_price if max_price != min_price else None,
                    "currency": currency,
                    "inStock": in_stock,
                    "image": product.get("image_url", ""),
                    "url": product_url,
                    "tags": tags,
                    "product_type": product_type,
                    "variants": variants
                }
                
                products.append(transformed_product)
                logger.info(f"🛍️ ✅ Product {i} transformed: '{title}' - {currency} {min_price}")
                
            except Exception as e:
                logger.error(f"🛍️ ❌ Error transforming product {i}: {e}")
                logger.error(f"🛍️ Product {i} raw data: {json.dumps(product, indent=2)}")
                continue
        
        # Build final result
        result_data = {
            "products": products,
            "pagination": data.get("pagination", {}),
            "filters": data.get("available_filters", []),
            "error": None
        }
        
        logger.info(f"🛍️ Transformation complete: {len(products)}/{len(raw_products)} products")
        logger.info(f"🛍️ Pagination available: {bool(result_data['pagination'])}")
        logger.info(f"🛍️ Filters available: {len(result_data['filters'])}")
        
        # Log pagination details if available
        pagination = result_data['pagination']
        if pagination:
            logger.info(f"🛍️ Pagination details: page {pagination.get('currentPage', '?')} of {pagination.get('maxPages', '?')}")
            logger.info(f"🛍️ Has next page: {pagination.get('hasNextPage', False)}")
        
        # Log filter details
        filters_list = result_data['filters']
        if filters_list:
            for f in filters_list:
                filter_label = f.get('label', 'Unknown')
                filter_values = f.get('values', {})
                logger.info(f"🛍️ Filter available: {filter_label}")
        
        logger.info("🛍️ ===== PRODUCT SEARCH SUCCESS =====")
        return result_data
    
    def get_product_details_sync(self, product_id: str, options: Optional[Dict] = None) -> Dict:
        """Get detailed product information with logging"""
        logger.info(f"🔍 Getting product details for: {product_id}")
        
        arguments = {"product_id": product_id}
        if options:
            arguments["options"] = options
            logger.info(f"🔍 Options provided: {options}")
            
        result = self._call_mcp_tool("get_product_details", arguments)
        logger.info(f"🔍 Product details result: {result['error'] is None}")
        return result
    
    def get_policies_sync(self, query: str = "return policy shipping") -> Dict:
        """Get store policies with logging"""
        logger.info(f"📋 Getting policies with query: '{query}'")
        
        arguments = {
            "query": query,
            "context": "Customer asking about store policies and terms"
        }
        
        result = self._call_mcp_tool("search_shop_policies_and_faqs", arguments)
        
        if result["error"]:
            logger.error(f"📋 Policy search failed: {result['error']}")
            return {"policies": {}, "error": result["error"]}
        
        logger.info(f"📋 Policies retrieved successfully")
        return {
            "policies": result["data"],
            "error": None
        }