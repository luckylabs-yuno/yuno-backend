import re
import hashlib
import secrets
import time
import logging
from urllib.parse import urlparse
from typing import Dict, List, Optional, Union
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class SecurityHelpers:
    """Security-related utility functions"""
    
    @staticmethod
    def generate_site_id(domain: str, length: int = 16) -> str:
        """
        Generate unique alphanumeric site_id
        
        Args:
            domain: Domain name for entropy
            length: Length of site_id (default 16)
            
        Returns:
            Unique site_id string
        """
        try:
            # Create entropy from domain + timestamp + random
            entropy = f"{domain}_{int(time.time())}_{secrets.token_hex(8)}"
            
            # Generate SHA256 hash
            hash_obj = hashlib.sha256(entropy.encode())
            hash_hex = hash_obj.hexdigest()
            
            # Take first N characters and ensure alphanumeric
            site_id = ''.join(c for c in hash_hex if c.isalnum())[:length]
            
            # Ensure minimum length by padding with random if needed
            while len(site_id) < length:
                site_id += secrets.choice('abcdefghijklmnopqrstuvwxyz0123456789')
            
            return site_id[:length]
            
        except Exception as e:
            logger.error(f"Error generating site_id: {str(e)}")
            # Fallback to pure random
            return secrets.token_urlsafe(length)[:length]
    
    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """Generate secure random token"""
        return secrets.token_urlsafe(length)
    
    @staticmethod
    def hash_string(text: str, salt: Optional[str] = None) -> str:
        """Hash string with optional salt"""
        if salt:
            text = f"{text}_{salt}"
        return hashlib.sha256(text.encode()).hexdigest()
    
    @staticmethod
    def generate_nonce() -> str:
        """Generate cryptographically secure nonce"""
        return secrets.token_hex(16)

class ValidationHelpers:
    """Data validation utility functions"""
    
    @staticmethod
    def validate_site_id(site_id: str) -> bool:
        """
        Validate site_id format
        
        Args:
            site_id: Site identifier to validate
            
        Returns:
            True if valid format
        """
        if not site_id or not isinstance(site_id, str):
            return False
        
        # Must be 12-20 characters, alphanumeric only
        if not re.match(r'^[a-zA-Z0-9]{12,20}$', site_id):
            return False
        
        return True
    
    @staticmethod
    def validate_email(email: str) -> bool:
        """Validate email address format"""
        if not email:
            return False
        
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    @staticmethod
    def validate_domain(domain: str) -> bool:
        """
        Validate domain name format
        
        Args:
            domain: Domain to validate
            
        Returns:
            True if valid domain
        """
        if not domain or len(domain) > 253:
            return False
        
        # Remove protocol if present
        if domain.startswith(('http://', 'https://')):
            parsed = urlparse(domain)
            domain = parsed.netloc
        
        # Basic domain regex
        pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$'
        return bool(re.match(pattern, domain))
    
    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate URL format"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False
    
    @staticmethod
    def sanitize_input(text: str, max_length: int = 1000) -> str:
        """
        Sanitize user input
        
        Args:
            text: Input text to sanitize
            max_length: Maximum allowed length
            
        Returns:
            Sanitized text
        """
        if not text:
            return ""
        
        # Remove null bytes and control characters
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        
        # Trim whitespace
        text = text.strip()
        
        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length]
        
        return text

class DateTimeHelpers:
    """Date and time utility functions"""
    
    @staticmethod
    def get_current_timestamp() -> str:
        """Get current UTC timestamp in ISO format"""
        return datetime.utcnow().isoformat()
    
    @staticmethod
    def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
        """Parse ISO timestamp string to datetime object"""
        try:
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except Exception:
            return None
    
    @staticmethod
    def is_timestamp_expired(timestamp_str: str, expiry_minutes: int = 60) -> bool:
        """Check if timestamp is expired"""
        try:
            timestamp = DateTimeHelpers.parse_timestamp(timestamp_str)
            if not timestamp:
                return True
            
            expiry_time = timestamp + timedelta(minutes=expiry_minutes)
            return datetime.utcnow() > expiry_time
            
        except Exception:
            return True
    
    @staticmethod
    def get_time_until_reset(window: str) -> int:
        """Get seconds until rate limit window resets"""
        now = int(time.time())
        
        if window == 'minute':
            next_reset = ((now // 60) + 1) * 60
        elif window == 'hour':
            next_reset = ((now // 3600) + 1) * 3600
        elif window == 'day':
            next_reset = ((now // 86400) + 1) * 86400
        else:
            return 3600  # Default 1 hour
        
        return max(0, next_reset - now)

class ResponseHelpers:
    """API response formatting utilities"""
    
    @staticmethod
    def success_response(data: Dict = None, message: str = "Success") -> Dict:
        """Format success response"""
        response = {
            "success": True,
            "message": message,
            "timestamp": DateTimeHelpers.get_current_timestamp()
        }
        
        if data:
            response["data"] = data
        
        return response
    
    @staticmethod
    def error_response(message: str, error_code: str = None, details: Dict = None) -> Dict:
        """Format error response"""
        response = {
            "success": False,
            "error": message,
            "timestamp": DateTimeHelpers.get_current_timestamp()
        }
        
        if error_code:
            response["error_code"] = error_code
        
        if details:
            response["details"] = details
        
        return response
    
    @staticmethod
    def rate_limit_response(window: str, limit: int, reset_in: int) -> Dict:
        """Format rate limit exceeded response"""
        return {
            "success": False,
            "error": "Rate limit exceeded",
            "error_code": "RATE_LIMIT_EXCEEDED",
            "details": {
                "window": window,
                "limit": limit,
                "reset_in_seconds": reset_in
            },
            "timestamp": DateTimeHelpers.get_current_timestamp()
        }

class LoggingHelpers:
    """Logging and monitoring utilities"""
    
    @staticmethod
    def log_security_event(event_type: str, site_id: str = None, details: Dict = None):
        """Log security-related events"""
        log_data = {
            "event_type": event_type,
            "timestamp": DateTimeHelpers.get_current_timestamp(),
            "site_id": site_id,
            "details": details or {}
        }
        
        logger.warning(f"Security Event: {json.dumps(log_data)}")
    
    @staticmethod
    def log_api_request(method: str, endpoint: str, site_id: str = None, 
                       status_code: int = None, response_time: float = None):
        """Log API request details"""
        log_data = {
            "method": method,
            "endpoint": endpoint,
            "site_id": site_id,
            "status_code": status_code,
            "response_time_ms": response_time,
            "timestamp": DateTimeHelpers.get_current_timestamp()
        }
        
        logger.info(f"API Request: {json.dumps(log_data)}")
    
    @staticmethod
    def log_rate_limit_hit(site_id: str, window: str, current: int, limit: int):
        """Log rate limit violations"""
        LoggingHelpers.log_security_event(
            "RATE_LIMIT_EXCEEDED",
            site_id=site_id,
            details={
                "window": window,
                "current_requests": current,
                "limit": limit
            }
        )

class ConfigHelpers:
    """Configuration and environment utilities"""
    
    @staticmethod
    def get_plan_config(plan_type: str) -> Dict:
        """Get configuration for plan type"""
        plans = {
            'free': {
                'requests_per_minute': 30,
                'requests_per_hour': 200,
                'requests_per_day': 500,
                'monthly_limit': 1000,
                'features': ['basic_chat', 'standard_support']
            },
            'basic': {
                'requests_per_minute': 60,
                'requests_per_hour': 500,
                'requests_per_day': 2000,
                'monthly_limit': 10000,
                'features': ['basic_chat', 'priority_support', 'analytics']
            },
            'pro': {
                'requests_per_minute': 120,
                'requests_per_hour': 1000,
                'requests_per_day': 5000,
                'monthly_limit': 50000,
                'features': ['advanced_chat', 'priority_support', 'analytics', 'custom_branding']
            },
            'enterprise': {
                'requests_per_minute': 300,
                'requests_per_hour': 2500,
                'requests_per_day': 15000,
                'monthly_limit': 200000,
                'features': ['advanced_chat', 'dedicated_support', 'analytics', 'custom_branding', 'sla']
            }
        }
        
        return plans.get(plan_type, plans['free'])
    
    @staticmethod
    def validate_environment_vars(required_vars: List[str]) -> Dict[str, bool]:
        """Validate required environment variables"""
        import os
        
        results = {}
        for var in required_vars:
            results[var] = bool(os.getenv(var))
        
        return results

class DataHelpers:
    """Data processing and formatting utilities"""
    
    @staticmethod
    def clean_domain_for_storage(domain: str) -> str:
        """Clean domain for consistent storage"""
        if not domain:
            return ""
        
        # Remove protocol
        if domain.startswith(('http://', 'https://')):
            domain = urlparse(domain).netloc
        
        # Remove www. prefix
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Remove trailing slash and path
        domain = domain.split('/')[0]
        
        # Remove port
        domain = domain.split(':')[0]
        
        # Convert to lowercase
        return domain.lower().strip()
    
    @staticmethod
    def extract_domain_from_url(url: str) -> str:
        """Extract clean domain from full URL"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            
            # Remove www. prefix
            if domain.startswith('www.'):
                domain = domain[4:]
            
            return domain.lower()
        except Exception:
            return ""
    
    @staticmethod
    def mask_sensitive_data(data: str, mask_char: str = "*", show_last: int = 4) -> str:
        """Mask sensitive data for logging"""
        if not data or len(data) <= show_last:
            return mask_char * len(data) if data else ""
        
        masked_length = len(data) - show_last
        return mask_char * masked_length + data[-show_last:]
    
    @staticmethod
    def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
        """Truncate text with suffix"""
        if not text or len(text) <= max_length:
            return text
        
        return text[:max_length - len(suffix)] + suffix

# Convenience function exports
def generate_site_id(domain: str) -> str:
    """Generate unique site ID for domain"""
    return SecurityHelpers.generate_site_id(domain)

def validate_request_data(data: Dict, required_fields: List[str]) -> tuple[bool, str]:
    """Validate request contains required fields"""
    if not data:
        return False, "Request data is required"
    
    for field in required_fields:
        if field not in data or data[field] is None:
            return False, f"Missing required field: {field}"
        
        # Additional validation for specific fields
        if field == 'site_id' and not ValidationHelpers.validate_site_id(data[field]):
            return False, "Invalid site_id format"
        
        if field == 'domain' and not ValidationHelpers.validate_domain(data[field]):
            return False, "Invalid domain format"
        
        if field == 'email' and not ValidationHelpers.validate_email(data[field]):
            return False, "Invalid email format"
    
    return True, ""

def clean_and_validate_domain(domain: str) -> tuple[str, bool]:
    """Clean domain and validate"""
    cleaned = DataHelpers.clean_domain_for_storage(domain)
    valid = ValidationHelpers.validate_domain(cleaned)
    return cleaned, valid

def log_security_event(event_type: str, **kwargs):
    """Convenience function for logging security events"""
    LoggingHelpers.log_security_event(event_type, **kwargs)