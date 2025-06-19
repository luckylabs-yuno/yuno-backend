import jwt
import time
import os
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class JWTService:
    def __init__(self):
        self.secret_key = os.getenv('JWT_SECRET')
        if not self.secret_key:
            raise ValueError("JWT_SECRET environment variable is required")
        
        self.algorithm = 'HS256'
        self.default_expiry = 3600  # 1 hour
        
    def generate_token(self, payload: Dict, expiry_seconds: Optional[int] = None) -> str:
        """
        Generate JWT token with given payload
        
        Args:
            payload: Token payload data
            expiry_seconds: Token expiry time in seconds (default: 1 hour)
            
        Returns:
            JWT token string
        """
        try:
            current_time = time.time()
            expiry = expiry_seconds or self.default_expiry
            
            token_payload = {
                **payload,
                'iat': current_time,  # Issued at
                'exp': current_time + expiry,  # Expiration
                'aud': 'yuno-widget',  # Audience
                'iss': 'yuno-api'  # Issuer
            }
            
            token = jwt.encode(token_payload, self.secret_key, algorithm=self.algorithm)
            
            logger.debug(f"Generated JWT token for site_id: {payload.get('site_id')}")
            return token
            
        except Exception as e:
            logger.error(f"Error generating JWT token: {str(e)}")
            raise Exception("Token generation failed")
    
    def verify_token(self, token: str) -> Optional[Dict]:
        """
        Verify and decode JWT token
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload or None if invalid
        """
        try:
            payload = jwt.decode(
                token, 
                self.secret_key, 
                algorithms=[self.algorithm],
                audience='yuno-widget',
                issuer='yuno-api'
            )
            
            logger.debug(f"Verified JWT token for site_id: {payload.get('site_id')}")
            return payload
            
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token has expired")
            return None
            
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {str(e)}")
            return None
            
        except Exception as e:
            logger.error(f"Error verifying JWT token: {str(e)}")
            return None
    
    def decode_token_unsafe(self, token: str) -> Optional[Dict]:
        """
        Decode token without verification (for debugging)
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload or None
        """
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload
        except Exception as e:
            logger.error(f"Error decoding JWT token: {str(e)}")
            return None
    
    def is_token_expired(self, token: str) -> bool:
        """
        Check if token is expired without full verification
        
        Args:
            token: JWT token string
            
        Returns:
            True if expired, False otherwise
        """
        try:
            payload = self.decode_token_unsafe(token)
            if not payload:
                return True
            
            current_time = time.time()
            exp_time = payload.get('exp', 0)
            
            return current_time >= exp_time
            
        except Exception:
            return True
    
    def get_token_payload(self, token: str) -> Optional[Dict]:
        """
        Get token payload without verification (for extracting site_id, etc.)
        
        Args:
            token: JWT token string
            
        Returns:
            Token payload or None
        """
        return self.decode_token_unsafe(token)
    
    def refresh_token(self, old_token: str) -> Optional[str]:
        """
        Refresh an existing token with new expiry
        
        Args:
            old_token: Existing JWT token
            
        Returns:
            New JWT token or None if refresh failed
        """
        try:
            # Verify old token first
            payload = self.verify_token(old_token)
            if not payload:
                return None
            
            # Create new token with same payload but fresh expiry
            new_payload = {
                'site_id': payload['site_id'],
                'domain': payload['domain'],
                'nonce': payload['nonce'],
                'timestamp': time.time(),
                'plan_type': payload.get('plan_type', 'free')
            }
            
            return self.generate_token(new_payload)
            
        except Exception as e:
            logger.error(f"Error refreshing token: {str(e)}")
            return None
    
    def validate_token_for_domain(self, token: str, domain: str) -> bool:
        """
        Validate that token is valid and matches the given domain
        
        Args:
            token: JWT token string
            domain: Domain to validate against
            
        Returns:
            True if valid and domain matches
        """
        try:
            payload = self.verify_token(token)
            if not payload:
                return False
            
            token_domain = payload.get('domain', '')
            return token_domain.lower() == domain.lower()
            
        except Exception:
            return False