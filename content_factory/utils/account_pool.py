#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Account Pool Module
===================
Multi-account management with rotation, scheduling, and shadowban tracking.
"""

import random
import threading
import time
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path


class AccountStatus(Enum):
    """Account status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SHADOWBANNED = "shadowbanned"
    HARD_BANNED = "hard_banned"
    COOLDOWN = "cooldown"


@dataclass
class Account:
    """Account configuration and state."""
    id: str
    session: str
    proxy: Optional[str]
    pool_id: str
    
    # Dynamic state
    status: AccountStatus = AccountStatus.ACTIVE
    daily_post_count: int = 0
    weekly_post_count: int = 0
    total_post_count: int = 0
    
    # Timing
    first_post_time: Optional[datetime] = None
    last_post_time: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    
    # Ban tracking
    shadowban_strikes: int = 0
    hard_ban_detected: bool = False
    
    # Performance
    avg_engagement: float = 0.0
    success_rate: float = 1.0
    
    def can_post(
        self,
        max_daily: int,
        max_weekly: int,
        min_interval: int
    ) -> bool:
        """Check if account can post."""
        if self.status != AccountStatus.ACTIVE:
            return False
        
        # Check cooldown
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            return False
        
        # Check daily limit
        if self.daily_post_count >= max_daily:
            return False
        
        # Check weekly limit
        if self.weekly_post_count >= max_weekly:
            return False
        
        # Check interval
        if self.last_post_time:
            elapsed = (datetime.now() - self.last_post_time).total_seconds() / 60
            if elapsed < min_interval:
                return False
        
        return True
    
    def record_post(self):
        """Record a successful post."""
        now = datetime.now()
        
        if not self.first_post_time:
            self.first_post_time = now
        
        self.last_post_time = now
        self.daily_post_count += 1
        self.weekly_post_count += 1
        self.total_post_count += 1
    
    def record_failure(self, is_shadowban: bool = False):
        """Record a failed post."""
        if is_shadowban:
            self.shadowban_strikes += 1
            if self.shadowban_strikes >= 3:
                self.status = AccountStatus.SHADOWBANNED
    
    def set_cooldown(self, minutes: int):
        """Set cooldown period."""
        self.cooldown_until = datetime.now() + timedelta(minutes=minutes)


class AccountPool:
    """Manages a pool of accounts with rotation."""
    
    def __init__(
        self,
        pool_id: str,
        niche: str,
        max_daily: int = 5,
        max_weekly: int = 20,
        min_interval: int = 30
    ):
        self.pool_id = pool_id
        self.niche = niche
        self.max_daily = max_daily
        self.max_weekly = max_weekly
        self.min_interval = min_interval
        
        self.accounts: Dict[str, Account] = {}
        self._lock = threading.Lock()
        
        self.logger = logging.getLogger(__name__)
    
    def add_account(self, account: Account):
        """Add account to pool."""
        with self._lock:
            self.accounts[account.id] = account
            self.logger.info(f"Added account {account.id} to pool {self.pool_id}")
    
    def get_available_account(self) -> Optional[Account]:
        """Get an available account from the pool."""
        with self._lock:
            # Get active accounts
            active = [
                a for a in self.accounts.values()
                if a.status == AccountStatus.ACTIVE
            ]
            
            if not active:
                self.logger.warning(f"No active accounts in pool {self.pool_id}")
                return None
            
            # Filter by capability
            available = [
                a for a in active
                if a.can_post(self.max_daily, self.max_weekly, self.min_interval)
            ]
            
            if not available:
                # Find account with earliest cooldown
                soonest = min(active, key=lambda a: a.cooldown_until or datetime.now())
                return soonest
            
            # Select based on load balancing
            # Prefer accounts with fewer posts
            available.sort(key=lambda a: a.daily_post_count)
            return available[0]
    
    def record_post(self, account: Account):
        """Record successful post."""
        with self._lock:
            account.record_post()
    
    def record_failure(self, account: Account, is_shadowban: bool = False):
        """Record failed post."""
        with self._lock:
            account.record_failure(is_shadowban)
            
            if account.status == AccountStatus.SHADOWBANNED:
                self.logger.warning(
                    f"Account {account.id} marked as shadowbanned "
                    f"({account.shadowban_strikes} strikes)"
                )
    
    def set_cooldown(self, account: Account, minutes: int):
        """Set cooldown for account."""
        with self._lock:
            account.set_cooldown(minutes)
    
    def reset_daily_counts(self):
        """Reset daily post counts (call at midnight)."""
        with self._lock:
            for account in self.accounts.values():
                account.daily_post_count = 0
    
    def reset_weekly_counts(self):
        """Reset weekly post counts (call at week start)."""
        with self._lock:
            for account in self.accounts.values():
                account.weekly_post_count = 0
    
    def get_stats(self) -> Dict:
        """Get pool statistics."""
        with self._lock:
            active = sum(1 for a in self.accounts.values() if a.status == AccountStatus.ACTIVE)
            shadowbanned = sum(1 for a in self.accounts.values() if a.status == AccountStatus.SHADOWBANNED)
            
            return {
                'pool_id': self.pool_id,
                'niche': self.niche,
                'total_accounts': len(self.accounts),
                'active': active,
                'shadowbanned': shadowbanned,
                'total_posts_today': sum(a.daily_post_count for a in self.accounts.values()),
                'total_posts_all': sum(a.total_post_count for a in self.accounts.values())
            }
    
    def save_state(self, filepath: str):
        """Save pool state to file."""
        with self._lock:
            data = {
                'pool_id': self.pool_id,
                'niche': self.niche,
                'accounts': [
                    {
                        **asdict(acc),
                        'status': acc.status.value,
                        'first_post_time': acc.first_post_time.isoformat() if acc.first_post_time else None,
                        'last_post_time': acc.last_post_time.isoformat() if acc.last_post_time else None,
                        'cooldown_until': acc.cooldown_until.isoformat() if acc.cooldown_until else None
                    }
                    for acc in self.accounts.values()
                ]
            }
            
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Saved pool state to {filepath}")
    
    def load_state(self, filepath: str):
        """Load pool state from file."""
        if not Path(filepath).exists():
            return
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        with self._lock:
            for acc_data in data.get('accounts', []):
                acc_data['status'] = AccountStatus(acc_data['status'])
                
                # Parse datetime fields
                for field in ['first_post_time', 'last_post_time', 'cooldown_until']:
                    if acc_data.get(field):
                        acc_data[field] = datetime.fromisoformat(acc_data[field])
                    else:
                        acc_data[field] = None
                
                account = Account(**acc_data)
                self.accounts[account.id] = account
        
        self.logger.info(f"Loaded pool state from {filepath}")


class AccountPoolManager:
    """Manages multiple account pools."""
    
    def __init__(self):
        self.pools: Dict[str, AccountPool] = {}
        self._lock = threading.Lock()
        
        self.logger = logging.getLogger(__name__)
    
    def create_pool(
        self,
        pool_id: str,
        niche: str,
        max_daily: int = 5,
        max_weekly: int = 20,
        min_interval: int = 30
    ) -> AccountPool:
        """Create a new pool."""
        with self._lock:
            pool = AccountPool(pool_id, niche, max_daily, max_weekly, min_interval)
            self.pools[pool_id] = pool
            return pool
    
    def add_account_to_pool(self, pool_id: str, account: Account):
        """Add account to pool."""
        pool = self.pools.get(pool_id)
        if not pool:
            raise ValueError(f"Pool {pool_id} not found")
        pool.add_account(account)
    
    def get_available_account(self, pool_id: str) -> Optional[Account]:
        """Get available account from pool."""
        pool = self.pools.get(pool_id)
        if not pool:
            return None
        return pool.get_available_account()
    
    def get_pool_for_niche(self, niche: str) -> Optional[str]:
        """Get pool ID for niche."""
        for pool_id, pool in self.pools.items():
            if pool.niche == niche:
                return pool_id
        return None
    
    def get_all_stats(self) -> List[Dict]:
        """Get statistics for all pools."""
        return [pool.get_stats() for pool in self.pools.values()]
    
    def reset_daily_all(self):
        """Reset daily counts for all pools."""
        for pool in self.pools.values():
            pool.reset_daily_counts()
    
    def save_all_state(self, directory: str):
        """Save state for all pools."""
        for pool_id, pool in self.pools.items():
            pool.save_state(f"{directory}/{pool_id}.json")
    
    def load_all_state(self, directory: str):
        """Load state for all pools."""
        for pool_id, pool in self.pools.items():
            pool.load_state(f"{directory}/{pool_id}.json")


# ============================================================================
# Convenience Functions
# ============================================================================

def create_account_pool_manager(config: Dict) -> AccountPoolManager:
    """Create account pool manager from config."""
    manager = AccountPoolManager()
    
    for pool_config in config.get('accounts.pools', []):
        pool = manager.create_pool(
            pool_id=pool_config['pool_id'],
            niche=pool_config.get('niche', 'general'),
            max_daily=pool_config.get('max_daily_posts', 5),
            max_weekly=pool_config.get('max_weekly_posts', 20),
            min_interval=pool_config.get('min_interval', 30)
        )
        
        # Add accounts
        for acc_config in pool_config.get('accounts', []):
            account = Account(
                id=acc_config['id'],
                session=acc_config['session'],
                proxy=acc_config.get('proxy'),
                pool_id=pool_id
            )
            pool.add_account(account)
    
    return manager
