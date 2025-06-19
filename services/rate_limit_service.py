import redis
import time
import logging
import os
from typing import Dict, Optional
import json

logger = logging.getLogger(__name__)

class RateLimitService:
    def __init__(self):
        redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
        try:
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            self.redis_client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Redis connection failed: {str(e)}")
            self.redis_client = None
        
        # Rate limit configurations by plan
        self.rate_limits = {
            'free': {
                'requests_per_minute': 30,
                'requests_per_hour': 200,
                'requests_per_day': 500
            },
            'basic': {
                'requests_per_minute': 60,
                'requests_per_hour': 500,
                'requests_per_day': 2000
            },
            'pro': {
                'requests_per_minute': 120,
                'requests_per_hour': 1000,
                'requests_per_day': 5000
            },
            'enterprise': {
                'requests_per_minute': 300,
                'requests_per_hour': 2500,
                'requests_per_day': 15000
            }
        }
    
    def get_rate_limits(self, plan_type: str) -> Dict:
        """Get rate limits for plan type"""
        return self.rate_limits.get(plan_type, self.rate_limits['free'])
    
    def _get_redis_key(self, site_id: str, time_window: str) -> str:
        """Generate Redis key for rate limiting"""
        timestamp = int(time.time())
        
        if time_window == 'minute':
            window = timestamp // 60
        elif time_window == 'hour':
            window = timestamp // 3600
        elif time_window == 'day':
            window = timestamp // 86400
        else:
            window = timestamp
        
        return f"rate_limit:{site_id}:{time_window}:{window}"
    
    def check_rate_limit(self, site_id: str, plan_type: str) -> bool:
        """
        Check if site_id is within rate limits
        
        Args:
            site_id: Site identifier
            plan_type: Plan type (free, basic, pro, enterprise)
            
        Returns:
            True if within limits, False if exceeded
        """
        if not self.redis_client:
            logger.warning("Redis not available, allowing request")
            return True
        
        try:
            limits = self.get_rate_limits(plan_type)
            
            # Check each time window
            time_windows = [
                ('minute', limits['requests_per_minute']),
                ('hour', limits['requests_per_hour']),
                ('day', limits['requests_per_day'])
            ]
            
            for window, limit in time_windows:
                key = self._get_redis_key(site_id, window)
                current_count = self.redis_client.get(key)
                
                if current_count and int(current_count) >= limit:
                    logger.warning(f"Rate limit exceeded for site_id {site_id} in {window} window: {current_count}/{limit}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking rate limit for site_id {site_id}: {str(e)}")
            return True  # Allow request on error
    
    def increment_usage(self, site_id: str, plan_type: str) -> Dict:
        """
        Increment usage counters for site_id
        
        Args:
            site_id: Site identifier
            plan_type: Plan type
            
        Returns:
            Current usage counts
        """
        if not self.redis_client:
            return {}
        
        try:
            limits = self.get_rate_limits(plan_type)
            usage = {}
            
            # Increment counters for each time window
            time_windows = [
                ('minute', limits['requests_per_minute'], 60),
                ('hour', limits['requests_per_hour'], 3600),
                ('day', limits['requests_per_day'], 86400)
            ]
            
            for window, limit, ttl in time_windows:
                key = self._get_redis_key(site_id, window)
                
                # Use pipeline for atomic operations
                pipe = self.redis_client.pipeline()
                pipe.incr(key)
                pipe.expire(key, ttl)
                results = pipe.execute()
                
                current_count = results[0]
                usage[window] = {
                    'current': current_count,
                    'limit': limit,
                    'remaining': max(0, limit - current_count)
                }
            
            return usage
            
        except Exception as e:
            logger.error(f"Error incrementing usage for site_id {site_id}: {str(e)}")
            return {}
    
    def get_usage_stats(self, site_id: str, plan_type: str) -> Dict:
        """
        Get current usage statistics for site_id
        
        Args:
            site_id: Site identifier
            plan_type: Plan type
            
        Returns:
            Usage statistics
        """
        if not self.redis_client:
            return {}
        
        try:
            limits = self.get_rate_limits(plan_type)
            usage = {}
            
            time_windows = [
                ('minute', limits['requests_per_minute']),
                ('hour', limits['requests_per_hour']),
                ('day', limits['requests_per_day'])
            ]
            
            for window, limit in time_windows:
                key = self._get_redis_key(site_id, window)
                current_count = self.redis_client.get(key)
                current = int(current_count) if current_count else 0
                
                usage[window] = {
                    'current': current,
                    'limit': limit,
                    'remaining': max(0, limit - current),
                    'percentage': (current / limit * 100) if limit > 0 else 0
                }
            
            return usage
            
        except Exception as e:
            logger.error(f"Error getting usage stats for site_id {site_id}: {str(e)}")
            return {}
    
    def reset_rate_limit(self, site_id: str) -> bool:
        """
        Reset rate limits for site_id (admin function)
        
        Args:
            site_id: Site identifier
            
        Returns:
            True if reset successful
        """
        if not self.redis_client:
            return False
        
        try:
            # Get all rate limit keys for this site
            pattern = f"rate_limit:{site_id}:*"
            keys = self.redis_client.keys(pattern)
            
            if keys:
                self.redis_client.delete(*keys)
                logger.info(f"Reset rate limits for site_id: {site_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error resetting rate limits for site_id {site_id}: {str(e)}")
            return False
    
    def get_time_until_reset(self, site_id: str, time_window: str) -> Optional[int]:
        """
        Get seconds until rate limit window resets
        
        Args:
            site_id: Site identifier
            time_window: Time window (minute, hour, day)
            
        Returns:
            Seconds until reset or None
        """
        if not self.redis_client:
            return None
        
        try:
            key = self._get_redis_key(site_id, time_window)
            ttl = self.redis_client.ttl(key)
            
            return ttl if ttl > 0 else None
            
        except Exception as e:
            logger.error(f"Error getting TTL for site_id {site_id}: {str(e)}")
            return None
    
    def is_rate_limited(self, site_id: str, plan_type: str) -> Dict:
        """
        Check if site is rate limited and return details
        
        Args:
            site_id: Site identifier
            plan_type: Plan type
            
        Returns:
            Rate limit status with details
        """
        try:
            limits = self.get_rate_limits(plan_type)
            usage = self.get_usage_stats(site_id, plan_type)
            
            # Check if any window is exceeded
            for window in ['minute', 'hour', 'day']:
                if window in usage:
                    if usage[window]['remaining'] <= 0:
                        reset_time = self.get_time_until_reset(site_id, window)
                        return {
                            'limited': True,
                            'window': window,
                            'limit': usage[window]['limit'],
                            'current': usage[window]['current'],
                            'reset_in_seconds': reset_time
                        }
            
            return {
                'limited': False,
                'usage': usage
            }
            
        except Exception as e:
            logger.error(f"Error checking rate limit status for site_id {site_id}: {str(e)}")
            return {'limited': False}