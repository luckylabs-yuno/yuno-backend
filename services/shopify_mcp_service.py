import requests
import json
from typing import Optional, Dict, Any

class ShopifyMCPClient:
    """
    Minimal synchronous client for Shopify Storefront MCP (JSON-RPC) tools.

    Usage:
        client = ShopifyMCPClient("your-shop.myshopify.com")
        search_result = client.search_catalog("snowboard", context="Customer love winter sports")
        products = search_result.get("products", [])
        details = client.get_product_details(products[0]["product_id"]) if products else {}
    """

    def __init__(self, shop_domain: str, timeout: float = 10.0):
        self.mcp_url = f"https://{shop_domain}/api/mcp"
        self.timeout = timeout

    def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        # Build JSON-RPC payload
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        # Send request
        resp = requests.post(
            self.mcp_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout
        )
        resp.raise_for_status()
        rpc = resp.json()

        # Handle top-level errors
        if rpc.get("error"):
            raise RuntimeError(f"MCP RPC error: {rpc['error']}")

        # Extract 'text' content
        content = rpc.get("result", {}).get("content", [])
        for item in content:
            if item.get("type") == "text" and item.get("text"):
                try:
                    # The 'text' field is a JSON string
                    return json.loads(item["text"])
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON in MCP text payload: {e}")

        # Fallback: return raw result
        return rpc.get("result", {})

    def search_catalog(self, query: str, context: Optional[str] = None) -> Dict[str, Any]:
        """
        Call the 'search_shop_catalog' tool.
        Returns a dict with:
          - products: List[Dict]
          - pagination: Dict
          - available_filters: List[Dict]
        """
        args: Dict[str, Any] = {"query": query}
        if context:
            args["context"] = context
        return self._call_tool("search_shop_catalog", args)

    def get_product_details(self, product_id: str) -> Dict[str, Any]:
        """
        Call the 'get_product_details' tool.
        Returns detailed product info including variants.
        """
        return self._call_tool("get_product_details", {"id": product_id})

# Example usage
if __name__ == "__main__":
    client = ShopifyMCPClient("your-shop.myshopify.com")
    # 1) Search the catalog
    search_res = client.search_catalog("snowboard", context="Customer prefers fair-trade products")
    print("Products:", search_res.get("products"))

    # 2) Fetch full details for the first product
    prods = search_res.get("products", [])
    if prods:
        first_id = prods[0].get("product_id")
        details = client.get_product_details(first_id)
        print("Details for", first_id, details)

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