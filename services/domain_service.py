import re
import logging
from urllib.parse import urlparse
from typing import List, Optional
from models.site import SiteModel

logger = logging.getLogger(__name__)

class DomainService:
    def __init__(self):
        self.site_model = SiteModel()
    
    def clean_domain(self, domain: str) -> str:
        """
        Clean and normalize domain name
        
        Args:
            domain: Raw domain input
            
        Returns:
            Cleaned domain name
        """
        try:
            # Remove protocol if present
            if domain.startswith(('http://', 'https://')):
                domain = urlparse(domain).netloc
            
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            
            # Remove trailing slash and path
            domain = domain.split('/')[0]
            
            # Remove port if present
            domain = domain.split(':')[0]
            
            # Convert to lowercase
            domain = domain.lower().strip()
            
            return domain
            
        except Exception as e:
            logger.error(f"Error cleaning domain {domain}: {str(e)}")
            return domain.lower().strip()
    
    def extract_domain_from_url(self, url: str) -> str:
        """
        Extract domain from full URL
        
        Args:
            url: Full URL
            
        Returns:
            Domain name
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            
            return domain.lower()
            
        except Exception as e:
            logger.error(f"Error extracting domain from URL {url}: {str(e)}")
            return ""
    
    def validate_domain_format(self, domain: str) -> bool:
        """
        Validate domain format using regex
        
        Args:
            domain: Domain to validate
            
        Returns:
            True if valid domain format
        """
        try:
            # Basic domain regex pattern
            pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
            
            if not domain or len(domain) > 253:
                return False
            
            return bool(re.match(pattern, domain))
            
        except Exception as e:
            logger.error(f"Error validating domain format {domain}: {str(e)}")
            return False
    
    def domains_match(self, domain1: str, domain2: str) -> bool:
        """
        Check if two domains match (with subdomain support)
        
        Args:
            domain1: First domain
            domain2: Second domain
            
        Returns:
            True if domains match
        """
        try:
            clean1 = self.clean_domain(domain1)
            clean2 = self.clean_domain(domain2)
            
            # Exact match
            if clean1 == clean2:
                return True
            
            # Subdomain support - check if one is subdomain of other
            if clean1.endswith(f'.{clean2}') or clean2.endswith(f'.{clean1}'):
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error matching domains {domain1} and {domain2}: {str(e)}")
            return False
    
    def validate_domain_ownership(self, site_id: str, domain: str) -> bool:
        """
        Validate that site_id owns the given domain
        
        Args:
            site_id: Site identifier
            domain: Domain to validate
            
        Returns:
            True if site owns domain
        """
        try:
            site = self.site_model.get_site_by_id(site_id)
            if not site:
                logger.warning(f"Site not found for site_id: {site_id}")
                return False
            
            registered_domain = site.get('domain', '')
            if not registered_domain:
                logger.warning(f"No domain registered for site_id: {site_id}")
                return False
            
            return self.domains_match(domain, registered_domain)
            
        except Exception as e:
            logger.error(f"Error validating domain ownership for site_id {site_id}: {str(e)}")
            return False
    
    def get_all_registered_domains(self) -> List[str]:
        """
        Get all registered domains from database
        
        Returns:
            List of registered domains
        """
        try:
            sites = self.site_model.get_all_active_sites()
            domains = []
            
            for site in sites:
                domain = site.get('domain')
                if domain:
                    domains.append(self.clean_domain(domain))
            
            return list(set(domains))  # Remove duplicates
            
        except Exception as e:
            logger.error(f"Error getting registered domains: {str(e)}")
            return []
    
    def is_subdomain_allowed(self, site_id: str, subdomain: str) -> bool:
        """
        Check if subdomain is allowed for given site
        
        Args:
            site_id: Site identifier
            subdomain: Subdomain to check
            
        Returns:
            True if subdomain is allowed
        """
        try:
            site = self.site_model.get_site_by_id(site_id)
            if not site:
                return False
            
            # Check if subdomain support is enabled for this site
            subdomain_enabled = site.get('subdomain_support', True)  # Default to true
            
            if not subdomain_enabled:
                return False
            
            # Extract base domain from subdomain
            parts = subdomain.split('.')
            if len(parts) < 2:
                return False
            
            base_domain = '.'.join(parts[-2:])  # Get last two parts (domain.tld)
            registered_domain = site.get('domain', '')
            
            return self.domains_match(base_domain, registered_domain)
            
        except Exception as e:
            logger.error(f"Error checking subdomain {subdomain} for site_id {site_id}: {str(e)}")
            return False
    
    def validate_cors_origin(self, origin: str) -> bool:
        """
        Validate CORS origin against registered domains
        
        Args:
            origin: Origin header value
            
        Returns:
            True if origin is allowed
        """
        try:
            if not origin:
                return False
            
            # Extract domain from origin
            domain = self.extract_domain_from_url(origin)
            
            # Check against all registered domains
            registered_domains = self.get_all_registered_domains()
            
            for registered_domain in registered_domains:
                if self.domains_match(domain, registered_domain):
                    return True
            
            # Allow localhost for development
            if domain in ['localhost', '127.0.0.1'] or domain.startswith('localhost:'):
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error validating CORS origin {origin}: {str(e)}")
            return False
            
            if not domain or len(domain) > 253:
                return False
            
            return bool(re.match(pattern, domain))
            
        except Exception as e:
            logger.error(f"Error validating domain format {domain}: {str(e)}")
            return False
    
    def domains_match(self, domain1: str, domain2: str) -> bool:
        """
        Check if two domains match (with subdomain support)
        
        Args:
            domain1: First domain
            domain2: Second domain
            
        Returns:
            True if domains match
        """
        try:
            clean1 = self.clean_domain(domain1)
            clean2 = self.clean_domain(domain2)
            
            # Exact match
            if clean1 == clean2:
                return True
            
            # Subdomain support - check if one is subdomain of other
            if clean1.endswith(f'.{clean2}') or clean2.endswith(f'.{clean1}'):
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error matching domains {domain1} and {domain2}: {str(e)}")
            return False
    
    def validate_domain_ownership(self, site_id: str, domain: str) -> bool:
        """
        Validate that site_id owns the given domain
        
        Args:
            site_id: Site identifier
            domain: Domain to validate
            
        Returns:
            True if site owns domain
        """
        try:
            site = self.site_model.get_site_by_id(site_id)
            if not site:
                logger.warning(f"Site not found for site_id: {site_id}")
                return False
            
            registered_domain = site.get('domain', '')
            if not registered_domain:
                logger.warning(f"No domain registered for site_id: {site_id}")
                return False
            
            return self.domains_match(domain, registered_domain)
            
        except Exception as e:
            logger.error(f"Error validating domain ownership for site_id {site_id}: {str(e)}")
            return False
    
    def get_all_registered_domains(self) -> List[str]:
        """
        Get all registered domains from database
        
        Returns:
            List of registered domains
        """
        try:
            sites = self.site_model.get_all_active_sites()
            domains = []
            
            for site in sites:
                domain = site.get('domain')
                if domain:
                    domains.append(self.clean_domain(domain))
            
            return list(set(domains))  # Remove duplicates
            
        except Exception as e:
            logger.error(f"Error getting registered domains: {str(e)}")
            return []
    
    def is_subdomain_allowed(self, site_id: str, subdomain: str) -> bool:
        """
        Check if subdomain is allowed for given site
        
        Args:
            site_id: Site identifier
            subdomain: Subdomain to check
            
        Returns:
            True if subdomain is allowed
        """
        try:
            site = self.site_model.get_site_by_id(site_id)
            if not site:
                return False
            
            # Check if subdomain support is enabled for this site
            subdomain_enabled = site.get('subdomain_support', True)  # Default to true
            
            if not subdomain_enabled:
                return False
            
            # Extract base domain from subdomain
            parts = subdomain.split('.')
            if len(parts) < 2:
                return False
            
            base_domain = '.'.join(parts[-2:])  # Get last two parts (domain.tld)
            registered_domain = site.get('domain', '')
            
            return self.domains_match(base_domain, registered_domain)
            
        except Exception as e:
            logger.error(f"Error checking subdomain {subdomain} for site_id {site_id}: {str(e)}")
            return False
    
    def validate_cors_origin(self, origin: str) -> bool:
        """
        Validate CORS origin against registered domains
        
        Args:
            origin: Origin header value
            
        Returns:
            True if origin is allowed
        """
        try:
            if not origin:
                return False
            
            # Extract domain from origin
            domain = self.extract_domain_from_url(origin)
            
            # Check against all registered domains
            registered_domains = self.get_all_registered_domains()
            
            for registered_domain in registered_domains:
                if self.domains_match(domain, registered_domain):
                    return True
            
            # Allow localhost for development
            if domain in ['localhost', '127.0.0.1'] or domain.startswith('localhost:'):
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error validating CORS origin {origin}: {str(e)}")
            return False