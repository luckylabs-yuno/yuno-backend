from models.base import BaseModel

class ShopifyStoreModel(BaseModel):
    def __init__(self):
        super().__init__()
        self.table_name = 'shopify_stores'
    
    def get_store_by_domain(self, shop_domain):
        result = self.supabase.table(self.table_name)\
            .select("*")\
            .eq('shop_domain', shop_domain)\
            .eq('is_active', True)\
            .single()\
            .execute()
        return result.data if result.data else None
    
    def get_store_by_site_id(self, site_id):
        result = self.supabase.table(self.table_name)\
            .select("*")\
            .eq('site_id', site_id)\
            .single()\
            .execute()
        return result.data if result.data else None