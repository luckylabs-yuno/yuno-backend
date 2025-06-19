import os
import logging
from supabase import create_client, Client
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class SiteModel:
    def __init__(self):
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")
        
        self.supabase: Client = create_client(supabase_url, supabase_key)
        
        # Rate limit configurations by plan
        self.plan_rate_limits = {
            'free': {
                'requests_per_minute': 30,
                'requests_per_hour': 200,
                'requests_per_day': 500,
                'monthly_limit': 1000
            },
            'basic': {
                'requests_per_minute': 60,
                'requests_per_hour': 500,
                'requests_per_day': 2000,
                'monthly_limit': 10000
            },
            'pro': {
                'requests_per_minute': 120,
                'requests_per_hour': 1000,
                'requests_per_day': 5000,
                'monthly_limit': 50000
            },
            'enterprise': {
                'requests_per_minute': 300,
                'requests_per_hour': 2500,
                'requests_per_day': 15000,
                'monthly_limit': 200000
            }
        }
    
    def get_site_by_id(self, site_id: str) -> Optional[Dict]:
        """
        Get site information by site_id
        
        Args:
            site_id: Site identifier
            
        Returns:
            Site data or None if not found
        """
        try:
            response = self.supabase.table('sites').select('*').eq('site_id', site_id).execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]
            
            logger.warning(f"Site not found for site_id: {site_id}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting site by ID {site_id}: {str(e)}")
            return None
    
    def get_all_active_sites(self) -> List[Dict]:
        """
        Get all active sites
        
        Returns:
            List of active site data
        """
        try:
            response = self.supabase.table('sites').select('*').eq('plan_active', True).execute()
            return response.data or []
            
        except Exception as e:
            logger.error(f"Error getting active sites: {str(e)}")
            return []
    
    def create_site(self, site_data: Dict) -> Optional[str]:
        """
        Create new site record
        
        Args:
            site_data: Site information
            
        Returns:
            Site ID if created successfully
        """
        try:
            response = self.supabase.table('sites').insert(site_data).execute()
            
            if response.data and len(response.data) > 0:
                site_id = response.data[0]['site_id']
                logger.info(f"Created new site: {site_id}")
                return site_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error creating site: {str(e)}")
            return None
    
    def update_site(self, site_id: str, updates: Dict) -> bool:
        """
        Update site information
        
        Args:
            site_id: Site identifier
            updates: Fields to update
            
        Returns:
            True if updated successfully
        """
        try:
            response = self.supabase.table('sites').update(updates).eq('site_id', site_id).execute()
            
            if response.data:
                logger.info(f"Updated site {site_id}: {list(updates.keys())}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error updating site {site_id}: {str(e)}")
            return False
    
    def get_sites_by_domain(self, domain: str) -> List[Dict]:
        """
        Get sites by domain
        
        Args:
            domain: Domain name
            
        Returns:
            List of sites with matching domain
        """
        try:
            response = self.supabase.table('sites').select('*').eq('domain', domain).execute()
            return response.data or []
            
        except Exception as e:
            logger.error(f"Error getting sites by domain {domain}: {str(e)}")
            return []
    
    def get_site_by_user_id(self, user_id: str) -> Optional[Dict]:
        """
        Get site by user ID
        
        Args:
            user_id: User identifier
            
        Returns:
            Site data or None
        """
        try:
            response = self.supabase.table('sites').select('*').eq('user_id', user_id).execute()
            
            if response.data and len(response.data) > 0:
                return response.data[0]
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting site by user ID {user_id}: {str(e)}")
            return None
    
    def is_site_active(self, site_id: str) -> bool:
        """
        Check if site is active (plan active and widget enabled)
        
        Args:
            site_id: Site identifier
            
        Returns:
            True if site is active
        """
        try:
            site = self.get_site_by_id(site_id)
            if not site:
                return False
            
            return site.get('plan_active', False) and site.get('widget_enabled', False)
            
        except Exception as e:
            logger.error(f"Error checking site status {site_id}: {str(e)}")
            return False
    
    def toggle_widget(self, site_id: str, enabled: bool) -> bool:
        """
        Toggle widget enabled status
        
        Args:
            site_id: Site identifier
            enabled: Enable or disable widget
            
        Returns:
            True if toggled successfully
        """
        try:
            return self.update_site(site_id, {'widget_enabled': enabled})
            
        except Exception as e:
            logger.error(f"Error toggling widget for site {site_id}: {str(e)}")
            return False
    
    def update_plan_status(self, site_id: str, active: bool, plan_type: Optional[str] = None) -> bool:
        """
        Update plan status for site
        
        Args:
            site_id: Site identifier
            active: Plan active status
            plan_type: Plan type (optional)
            
        Returns:
            True if updated successfully
        """
        try:
            updates = {'plan_active': active}
            if plan_type:
                updates['plan_type'] = plan_type
            
            return self.update_site(site_id, updates)
            
        except Exception as e:
            logger.error(f"Error updating plan status for site {site_id}: {str(e)}")
            return False
    
    def get_rate_limits_for_plan(self, plan_type: str) -> Dict:
        """
        Get rate limits for plan type
        
        Args:
            plan_type: Plan type
            
        Returns:
            Rate limit configuration
        """
        return self.plan_rate_limits.get(plan_type, self.plan_rate_limits['free'])
    
    def get_site_usage_stats(self, site_id: str) -> Dict:
        """
        Get usage statistics for site
        
        Args:
            site_id: Site identifier
            
        Returns:
            Usage statistics
        """
        try:
            # Get chat message count for today
            response = self.supabase.rpc('get_site_usage', {
                'p_site_id': site_id,
                'p_date': 'today'
            }).execute()
            
            return response.data[0] if response.data else {}
            
        except Exception as e:
            logger.error(f"Error getting usage stats for site {site_id}: {str(e)}")
            return {}
    
    def validate_site_access(self, site_id: str, domain: str) -> Dict:
        """
        Validate site access with comprehensive checks
        
        Args:
            site_id: Site identifier
            domain: Requesting domain
            
        Returns:
            Validation result with details
        """
        try:
            site = self.get_site_by_id(site_id)
            
            if not site:
                return {
                    'valid': False,
                    'reason': 'site_not_found',
                    'message': 'Site not found'
                }
            
            # Check plan status
            if not site.get('plan_active', False):
                return {
                    'valid': False,
                    'reason': 'plan_inactive',
                    'message': 'Plan is not active'
                }
            
            # Check widget toggle
            if not site.get('widget_enabled', False):
                return {
                    'valid': False,
                    'reason': 'widget_disabled',
                    'message': 'Widget is disabled'
                }
            
            # Check domain match (will be done by DomainService)
            return {
                'valid': True,
                'site': site,
                'plan_type': site.get('plan_type', 'free')
            }
            
        except Exception as e:
            logger.error(f"Error validating site access {site_id}: {str(e)}")
            return {
                'valid': False,
                'reason': 'validation_error',
                'message': 'Validation error occurred'
            }