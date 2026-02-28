#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Error Handler Module
====================
Unified error handling with exponential backoff and statistics tracking.
"""

import time
import random
import logging
from typing import Callable, Any, Optional, Type
from functools import wraps
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ErrorRecord:
    """Record of an error occurrence."""
    timestamp: datetime
    error_type: str
    error_message: str
    severity: ErrorSeverity
    context: str
    retry_count: int
    resolved: bool = False


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 5
    base_delay: float = 1.0
    max_delay: float = 300.0
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_range: tuple = (0.0, 1.0)
    
    # Error classification
    retryable_errors: list = field(default_factory=list)
    fatal_errors: list = field(default_factory=list)


class ErrorHandler:
    """
    Centralized error handling with:
    - Exponential backoff
    - Error classification
    - Statistics tracking
    - Context-aware retry decisions
    """
    
    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()
        self.error_history: list[ErrorRecord] = []
        self.stats = {
            'total_errors': 0,
            'retries_attempted': 0,
            'retries_succeeded': 0,
            'retries_failed': 0,
            'fatal_errors': 0
        }
        self.logger = logging.getLogger(__name__)
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and optional jitter."""
        delay = min(
            self.config.base_delay * (self.config.exponential_base ** attempt),
            self.config.max_delay
        )
        
        if self.config.jitter:
            jitter = random.uniform(*self.config.jitter_range)
            delay = delay + jitter
        
        return delay
    
    def is_retryable(self, error: Exception) -> bool:
        """Determine if an error is retryable."""
        error_name = type(error).__name__
        
        # Check explicit retryable list
        if error_name in self.config.retryable_errors:
            return True
        
        # Check explicit fatal list
        if error_name in self.config.fatal_errors:
            return False
        
        # Default: network-related errors are retryable
        error_str = str(error).lower()
        retryable_keywords = [
            'timeout', 'connection', 'network', 'temporarily',
            'unavailable', 'too many requests', 'rate limit'
        ]
        
        return any(keyword in error_str for keyword in retryable_keywords)
    
    def is_fatal(self, error: Exception) -> bool:
        """Determine if an error is fatal (should not retry)."""
        error_name = type(error).__name__
        
        if error_name in self.config.fatal_errors:
            return True
        
        error_str = str(error).lower()
        fatal_keywords = ['authentication', 'unauthorized', 'forbidden', 'banned']
        
        return any(keyword in error_str for keyword in fatal_keywords)
    
    def classify_error(self, error: Exception) -> ErrorSeverity:
        """Classify error severity."""
        if self.is_fatal(error):
            return ErrorSeverity.CRITICAL
        
        error_str = str(error).lower()
        
        if 'timeout' in error_str:
            return ErrorSeverity.LOW
        elif 'rate limit' in error_str:
            return ErrorSeverity.MEDIUM
        elif 'connection' in error_str:
            return ErrorSeverity.MEDIUM
        
        return ErrorSeverity.LOW
    
    def record_error(
        self,
        error: Exception,
        context: str,
        retry_count: int = 0
    ) -> ErrorRecord:
        """Record an error occurrence."""
        record = ErrorRecord(
            timestamp=datetime.now(),
            error_type=type(error).__name__,
            error_message=str(error),
            severity=self.classify_error(error),
            context=context,
            retry_count=retry_count
        )
        
        self.error_history.append(record)
        self.stats['total_errors'] += 1
        
        if self.is_fatal(error):
            self.stats['fatal_errors'] += 1
        
        return record
    
    def retry_decision(
        self,
        error: Exception,
        attempt: int
    ) -> bool:
        """
        Decide whether to retry based on error type and attempt count.
        Returns True if should retry, False otherwise.
        """
        # Check attempt limit
        if attempt >= self.config.max_retries:
            self.logger.warning(
                f"Max retries ({self.config.max_retries}) reached"
            )
            self.stats['retries_failed'] += 1
            return False
        
        # Check fatal errors
        if self.is_fatal(error):
            self.logger.error(f"Fatal error - not retrying: {error}")
            return False
        
        # Check retryable
        if self.is_retryable(error):
            self.stats['retries_attempted'] += 1
            return True
        
        # Unknown error - default to retry up to limit
        self.logger.warning(f"Unknown error - attempting retry: {error}")
        self.stats['retries_attempted'] += 1
        return True
    
    def with_retry(
        self,
        context: str = "",
        on_retry: Optional[Callable] = None
    ):
        """
        Decorator for automatic retry with exponential backoff.
        
        Usage:
            @error_handler.with_retry(context="my_function")
            def my_function():
                # ... code that might fail
                pass
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                attempt = 0
                
                while True:
                    try:
                        result = func(*args, **kwargs)
                        
                        if attempt > 0:
                            self.stats['retries_succeeded'] += 1
                            self.logger.info(
                                f"Success after {attempt} retries: {context}"
                            )
                        
                        return result
                        
                    except Exception as e:
                        self.record_error(e, context, attempt)
                        
                        if not self.retry_decision(e, attempt):
                            raise
                        
                        delay = self.calculate_delay(attempt)
                        self.logger.warning(
                            f"Error in {context}: {e}. "
                            f"Retrying in {delay:.1f}s (attempt {attempt + 1})"
                        )
                        
                        if on_retry:
                            on_retry(e, attempt)
                        
                        time.sleep(delay)
                        attempt += 1
            
            return wrapper
        return decorator
    
    def get_stats(self) -> dict:
        """Get error statistics."""
        return {
            **self.stats,
            'recent_errors': len([
                e for e in self.error_history
                if (datetime.now() - e.timestamp).total_seconds() < 3600
            ])
        }
    
    def clear_history(self):
        """Clear error history."""
        self.error_history.clear()


# ============================================================================
# Specialized Error Classes
# ============================================================================

class NetworkTimeoutError(RetryableError):
    """Network timeout error."""
    pass


class APIRateLimitError(RetryableError):
    """API rate limit error."""
    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after


class AccountBannedError(FatalError):
    """Account banned error."""
    pass


class VideoGenerationError(RetryableError):
    """Video generation failed."""
    pass


class OpenClawConnectionError(RetryableError):
    """OpenClaw connection error."""
    pass


# ============================================================================
# Convenience Functions
# ============================================================================

def create_error_handler(
    max_retries: int = 5,
    base_delay: float = 5.0,
    max_delay: float = 300.0
) -> ErrorHandler:
    """Create a pre-configured error handler."""
    config = RetryConfig(
        max_retries=max_retries,
        base_delay=base_delay,
        max_delay=max_delay,
        retryable_errors=[
            'NetworkTimeoutError',
            'APIRateLimitError', 
            'VideoGenerationError',
            'OpenClawConnectionError',
            'RequestException'
        ],
        fatal_errors=[
            'AccountBannedError',
            'InvalidCredentialsError',
            'ProxyAuthenticationError'
        ]
    )
    return ErrorHandler(config)


# Default instance
default_handler = create_error_handler()
