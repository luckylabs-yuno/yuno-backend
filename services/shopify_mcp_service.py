import httpx
import json
from typing import Dict, List, Optional

class ShopifyMCPService:
    def __init__(self):
        self.mcp_client = None
        
    async def connect(self, shop_domain: str) -> None:
        """Connect to Shopify store's MCP server"""
        mcp_url = f"https://{shop_domain}/api/mcp/storefront"
        self.mcp_client = httpx.AsyncClient(base_url=mcp_url)
    
    async def search_products(
        self, 
        query: str, 
        filters: Optional[Dict] = None
    ) -> Dict:
        """Search products using MCP"""
        request = {
            "tool": "search_products",
            "arguments": {
                "query": query,
                "search_fields": ["title", "description", "tags", "vendor"],
                "limit": 10
            }
        }
        
        # Add filters if provided
        if filters:
            if filters.get('price_range'):
                request["arguments"]["price_max"] = filters['price_range'].get('max')
            if filters.get('category'):
                request["arguments"]["product_type"] = filters['category']
            if filters.get('product_features'):
                request["arguments"]["tags"] = filters['product_features']
                
        response = await self.mcp_client.post("/", json=request)
        return response.json()
    
    async def get_policies(self) -> Dict:
        """Get store policies via MCP"""
        request = {
            "tool": "get_store_info",
            "arguments": {
                "include": ["policies", "shipping_zones", "contact_information"]
            }
        }
        response = await self.mcp_client.post("/", json=request)
        return response.json()
    
    async def add_to_cart(self, product_id: str, quantity: int = 1) -> Dict:
        """Add product to cart via MCP"""
        request = {
            "tool": "add_to_cart",
            "arguments": {
                "product_id": product_id,
                "quantity": quantity
            }
        }
        response = await self.mcp_client.post("/", json=request)
        return response.json()

    # In shopify_mcp_service.py, add these sync methods:

    def connect_sync(self, shop_domain: str) -> None:
        """Sync version of connect"""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.connect(shop_domain))

    def search_products_sync(self, query: str, filters: Optional[Dict] = None) -> Dict:
        """Sync version of search_products"""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.search_products(query, filters))

    def get_policies_sync(self) -> Dict:
        """Sync version of get_policies"""
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.get_policies())