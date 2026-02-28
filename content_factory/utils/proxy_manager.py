#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proxy Manager Module
====================
IP rotation and proxy pool management for shadowban prevention.
"""

import random
import threading
import time
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class RotationStrategy(Enum):
    """Proxy rotation strategies."""
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    STICKY = "sticky"
    GEO_DISTRIBUTED = "geo_distributed"
    LEAST_USED = "least_used"


@dataclass
class Proxy:
    """Proxy configuration."""
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    protocol: str = "http"  # http, https, socks5
    country: Optional[str] = None
    is_active: bool = True
    failure_count: int = 0
    success_count: int = 0
    last_used: Optional[datetime] = None
    avg_response_time: float = 0.0


class ProxyPool:
    """Manages a pool of proxies with rotation strategies."""
    
    def __init__(
        self,
        proxies: List[Dict],
        strategy: RotationStrategy = RotationStrategy.ROUND_ROBIN,
        min_success_rate: float = 0.8
    ):
        self.strategy = strategy
        self.min_success_rate = min_success_rate
        
        # Initialize proxy list
        self.proxies: List[Proxy] = []
        for p in proxies:
            proxy = Proxy(
                host=p.get('host', ''),
                port=p.get('port', 0),
                username=p.get('username'),
                password=p.get('password'),
                protocol=p.get('protocol', 'http'),
                country=p.get('country')
            )
            self.proxies.append(proxy)
        
        # State
        self._current_index = 0
        self._lock = threading.Lock()
        self._sticky_proxy: Optional[Proxy] = None
        
        # Statistics
        self.stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0
        }
        
        self.logger = logging.getLogger(__name__)
    
    def _is_proxy_healthy(self, proxy: Proxy) -> bool:
        """Check if proxy is healthy enough to use."""
        if not proxy.is_active:
            return False
        
        # Check failure rate
        total = proxy.success_count + proxy.failure_count
        if total > 0:
            success_rate = proxy.success_count / total
            if success_rate < self.min_success_rate:
                return False
        
        return True
    
    def _select_by_strategy(self) -> Optional[Proxy]:
        """Select proxy based on rotation strategy."""
        # Filter healthy proxies
        healthy = [p for p in self.proxies if self._is_proxy_healthy(p)]
        
        if not healthy:
            self.logger.warning("No healthy proxies available")
            # Fall back to all proxies
            healthy = self.proxies
            if not healthy:
                return None
        
        with self._lock:
            if self.strategy == RotationStrategy.ROUND_ROBIN:
                proxy = healthy[self._current_index % len(healthy)]
                self._current_index += 1
                return proxy
            
            elif self.strategy == RotationStrategy.RANDOM:
                return random.choice(healthy)
            
            elif self.strategy == RotationStrategy.STICKY:
                if not self._sticky_proxy or not self._is_proxy_healthy(self._sticky_proxy):
                    self._sticky_proxy = healthy[0]
                return self._sticky_proxy
            
            elif self.strategy == RotationStrategy.LEAST_USED:
                return min(healthy, key=lambda p: p.success_count)
            
            else:
                return healthy[0]
    
    def get_proxy(self) -> Optional[Dict]:
        """Get next proxy configuration for requests."""
        proxy = self._select_by_strategy()
        
        if not proxy:
            return None
        
        # Update usage stats
        proxy.last_used = datetime.now()
        self.stats['total_requests'] += 1
        
        # Build proxy URL
        if proxy.username and proxy.password:
            auth = f"{proxy.username}:{proxy.password}@"
        else:
            auth = ""
        
        proxy_url = f"{proxy.protocol}://{auth}{proxy.host}:{proxy.port}"
        
        return {
            'http': proxy_url,
            'https': proxy_url,
            '_proxy_obj': proxy  # Keep reference for stats updates
        }
    
    def report_success(self, proxy: Proxy):
        """Report successful request using proxy."""
        proxy.success_count += 1
        proxy.failure_count = 0  # Reset on success
        self.stats['successful_requests'] += 1
        
        # Update response time (simplified)
        if proxy.last_used:
            elapsed = (datetime.now() - proxy.last_used).total_seconds()
            # Moving average
            proxy.avg_response_time = (
                0.7 * proxy.avg_response_time + 0.3 * elapsed
            )
    
    def report_failure(self, proxy: Proxy):
        """Report failed request using proxy."""
        proxy.failure_count += 1
        self.stats['failed_requests'] += 1
        
        # Disable proxy if too many failures
        if proxy.failure_count >= 5:
            proxy.is_active = False
            self.logger.warning(
                f"Proxy {proxy.host}:{proxy.port} disabled due to failures"
            )
    
    def mark_bad(self, proxy: Proxy):
        """Manually mark a proxy as bad."""
        proxy.failure_count += 3
        if proxy.failure_count >= 3:
            proxy.is_active = False
    
    def get_stats(self) -> Dict:
        """Get proxy pool statistics."""
        return {
            'total_proxies': len(self.proxies),
            'active_proxies': sum(1 for p in self.proxies if p.is_active),
            'strategy': self.strategy.value,
            'requests': self.stats
        }


class ProxyManager:
    """
    High-level proxy management with:
    - Multiple proxy pools
    - Automatic health checking
    - Geographic distribution
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.rotation_strategy = RotationStrategy(
            config.get('ip_rotation.rotation_strategy', 'round_robin')
        )
        
        # Initialize proxy pools
        proxy_list = config.get('ip_rotation.proxy_pool', [])
        self.pool = ProxyPool(
            proxies=[self._parse_proxy(p) for p in proxy_list],
            strategy=self.rotation_strategy
        )
        
        # Health check settings
        self.health_check_interval = config.get('ip_rotation.health_check_interval', 300)
        self._health_check_thread = None
        self._shutdown = threading.Event()
        
        self.logger = logging.getLogger(__name__)
    
    def _parse_proxy(self, proxy_str: str) -> Dict:
        """Parse proxy string to dict."""
        # Format: protocol://user:pass@host:port or just host:port
        # Simplified parser
        result = {'protocol': 'http'}
        
        if '@' in proxy_str:
            auth, rest = proxy_str.split('@')
            if '://' in auth:
                result['protocol'] = auth.split('://')[0]
                auth = auth.split('://')[1]
            
            if ':' in auth:
                result['username'], result['password'] = auth.split(':', 1)
            
            if ':' in rest:
                result['host'], result['port'] = rest.split(':')
                result['port'] = int(result['port'])
        else:
            if '://' in proxy_str:
                result['protocol'] = proxy_str.split('://')[0]
                proxy_str = proxy_str.split('://')[1]
            
            if ':' in proxy_str:
                result['host'], result['port'] = proxy_str.split(':')
                result['port'] = int(result['port'])
        
        return result
    
    def get_session_proxy(self) -> Optional[Dict]:
        """Get proxy for current session."""
        if not self.config.get('ip_rotation.enabled', True):
            return None
        
        return self.pool.get_proxy()
    
    def report_success(self, proxy_dict: Dict):
        """Report successful request."""
        if '_proxy_obj' in proxy_dict:
            self.pool.report_success(proxy_dict['_proxy_obj'])
    
    def report_failure(self, proxy_dict: Dict):
        """Report failed request."""
        if '_proxy_obj' in proxy_dict:
            self.pool.report_failure(proxy_dict['_proxy_obj'])
    
    def start_health_check(self):
        """Start background health check thread."""
        if self._health_check_thread is None:
            self._health_check_thread = threading.Thread(
                target=self._health_check_loop,
                daemon=True
            )
            self._health_check_thread.start()
            self.logger.info("Proxy health check started")
    
    def stop_health_check(self):
        """Stop health check thread."""
        self._shutdown.set()
        if self._health_check_thread:
            self._health_check_thread.join(timeout=5)
    
    def _health_check_loop(self):
        """Background health check loop."""
        while not self._shutdown.is_set():
            time.sleep(self.health_check_interval)
            self._perform_health_check()
    
    def _perform_health_check(self):
        """Perform health check on all proxies."""
        self.logger.info("Performing proxy health check...")
        
        for proxy in self.pool.proxies:
            # Simple health check - ping or connect test
            # In production, implement actual connectivity test
            if not proxy.is_active and proxy.failure_count < 3:
                # Try to re-enable
                proxy.is_active = True
                self.logger.info(f"Re-enabled proxy {proxy.host}:{proxy.port}")
        
        stats = self.pool.get_stats()
        self.logger.info(f"Proxy health: {stats['active_proxies']}/{stats['total_proxies']} active")
    
    def get_stats(self) -> Dict:
        """Get proxy manager statistics."""
        return self.pool.get_stats()


# ============================================================================
# Convenience Functions
# ============================================================================

def create_proxy_manager(
    proxy_list: List[str],
    strategy: str = "round_robin"
) -> ProxyManager:
    """Create a pre-configured proxy manager."""
    config = {
        'ip_rotation': {
            'enabled': True,
            'proxy_pool': proxy_list,
            'rotation_strategy': strategy
        }
    }
    return ProxyManager(config)


# Default instance
default_proxy_manager = None  # Initialize with config
