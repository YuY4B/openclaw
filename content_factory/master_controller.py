#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Content Factory - Master Controller
=======================================
Azure-Local Swarm Orchestration for TikTok Auto-Posting

Usage:
    python master_controller.py              # Production mode
    python master_controller.py --dry-run   # Test mode (no posting)
    python master_controller.py --config custom.yaml

Author: MINIMAX Orchestrator
Version: 1.0.0
"""

import os
import sys
import json
import time
import queue
import logging
import argparse
import subprocess
import threading
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import copy

# Third-party imports (require installation)
import requests
import yaml

# ============================================================================
# Configuration Management
# ============================================================================

class Config:
    """Configuration manager with environment variable substitution."""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._config = {}
        self._load_config()
    
    def _load_config(self):
        """Load configuration from YAML file."""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)
        
        # Process environment variables
        self._config = self._process_env_vars(raw_config)
    
    def _process_env_vars(self, obj):
        """Recursively replace ${VAR} with environment variables."""
        if isinstance(obj, dict):
            return {k: self._process_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._process_env_vars(item) for item in obj]
        elif isinstance(obj, str) and obj.startswith('${') and obj.endswith('}'):
            var_name = obj[2:-1]
            return os.environ.get(var_name, obj)
        return obj
    
    def get(self, key: str, default=None):
        """Get configuration value by dot-notation key."""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value
    
    @property
    def all(self):
        return self._config


# ============================================================================
# Data Models
# ============================================================================

class JobStatus(Enum):
    """Job status enumeration."""
    PENDING = "pending"
    SCRIPT_FETCHED = "script_fetched"
    VIDEO_GENERATING = "video_generating"
    VIDEO_READY = "video_ready"
    POSTING = "posting"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class Script:
    """Script data model from Azure Agent."""
    id: str
    agent_name: str
    content: str
    duration: int  # seconds
    keywords: List[str]
    hashtags: List[str]
    voice: str
    background_images: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_response(cls, agent_name: str, response: Dict) -> 'Script':
        return cls(
            id=response.get('id', str(uuid.uuid4())),
            agent_name=agent_name,
            content=response.get('script', ''),
            duration=response.get('duration', 45),
            keywords=response.get('keywords', []),
            hashtags=response.get('hashtags', []),
            voice=response.get('voice', 'ja-JP-NanamiNeural'),
            background_images=response.get('background_images', []),
            metadata=response.get('metadata', {})
        )


@dataclass
class VideoJob:
    """Video generation job."""
    id: str
    script: Script
    status: JobStatus = JobStatus.PENDING
    output_path: Optional[str] = None
    retry_count: int = 0
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'script_id': self.script.id,
            'agent_name': self.script.agent_name,
            'status': self.status.value,
            'output_path': self.output_path,
            'retry_count': self.retry_count,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


@dataclass 
class Account:
    """Account data model."""
    id: str
    session: str
    proxy: Optional[str]
    pool_id: str
    is_active: bool = True
    daily_post_count: int = 0
    last_post_time: Optional[datetime] = None
    shadowban_count: int = 0
    
    def can_post(self, max_daily: int, min_interval: int) -> bool:
        """Check if account can post."""
        if not self.is_active:
            return False
        
        if self.daily_post_count >= max_daily:
            return False
        
        if self.last_post_time:
            elapsed = (datetime.now() - self.last_post_time).total_seconds() / 60
            if elapsed < min_interval:
                return False
        
        return True


# ============================================================================
# Error Handling
# ============================================================================

class RetryableError(Exception):
    """Base class for errors that should be retried."""
    pass


class FatalError(Exception):
    """Base class for fatal errors that should not be retried."""
    pass


class ErrorCentralHandler:
    """ized error handling with exponential backoff."""
    
    def __init__(self, config: Config):
        self.config = config
        self.max_retries = config.get('error_handling.max_retries', 5)
        self.base_delay = config.get('error_handling.base_delay', 5)
        self.max_delay = config.get('error_handling.max_delay', 300)
        self.retryable_errors = config.get('error_handling.retryable_errors', [])
        self.fatal_errors = config.get('error_handling.fatal_errors', [])
        
        # Statistics
        self.stats = {
            'total_retries': 0,
            'successful_retries': 0,
            'failed_retries': 0
        }
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay."""
        delay = min(
            self.base_delay * (2 ** attempt),
            self.max_delay
        )
        # Add jitter
        return delay + random.uniform(0, 1)
    
    def is_retryable(self, error: Exception) -> bool:
        """Check if error is retryable."""
        error_name = type(error).__name__
        return error_name in self.retryable_errors
    
    def is_fatal(self, error: Exception) -> bool:
        """Check if error is fatal."""
        error_name = type(error).__name__
        return error_name in self.fatal_errors
    
    def handle_error(self, error: Exception, context: str) -> bool:
        """Handle error and return True if should retry."""
        error_name = type(error).__name__
        
        if self.is_fatal(error):
            logging.error(f"[{context}] Fatal error: {error_name} - {str(error)}")
            return False
        
        if self.is_retryable(error):
            self.stats['total_retries'] += 1
            logging.warning(f"[{context}] Retryable error: {error_name} - {str(error)}")
            return True
        
        # Unknown error - treat as retryable up to limit
        logging.error(f"[{context}] Unknown error: {error_name} - {str(error)}")
        return True


# ============================================================================
# Azure Agent Client
# ============================================================================

class AzureAgentClient:
    """Client for Azure Functions (Markdown Agents)."""
    
    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.get('azure.base_url', '')
        self.api_key = config.get('azure.api_key', '')
        self.timeout = config.get('azure.timeout', 30)
        self.agents = config.get('azure.agents', {})
        self.rate_limit = config.get('azure.requests_per_minute', 20)
        
        # Rate limiting
        self._request_times = []
        self._lock = threading.Lock()
        
        # Setup headers
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
    
    def _rate_limit_wait(self):
        """Wait if rate limit would be exceeded."""
        now = time.time()
        with self._lock:
            # Remove old requests (older than 1 minute)
            self._request_times = [t for t in self._request_times if now - t < 60]
            
            if len(self._request_times) >= self.rate_limit:
                # Wait until oldest request is older than 1 minute
                wait_time = 60 - (now - self._request_times[0])
                if wait_time > 0:
                    logging.info(f"Rate limit reached, waiting {wait_time:.1f}s")
                    time.sleep(wait_time)
            
            self._request_times.append(time.time())
    
    def fetch_script(self, agent_name: str, topic: str = None) -> Script:
        """Fetch script from Azure Agent."""
        endpoint = self.agents.get(agent_name)
        if not endpoint:
            raise ValueError(f"Unknown agent: {agent_name}")
        
        url = f"{self.base_url}{endpoint}"
        
        # Build request payload
        payload = {}
        if topic:
            payload['topic'] = topic
        payload['timestamp'] = datetime.now().isoformat()
        
        self._rate_limit_wait()
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            return Script.from_response(agent_name, data)
            
        except requests.exceptions.Timeout as e:
            raise RetryableError(f"Azure API timeout: {e}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 429:
                raise RetryableError(f"Azure API rate limited: {e}")
            raise RetryableError(f"Azure API error: {e}")
        except requests.exceptions.RequestException as e:
            raise RetryableError(f"Azure API request failed: {e}")
    
    def fetch_all_agents(self) -> List[Script]:
        """Fetch scripts from all configured agents."""
        scripts = []
        
        for agent_name in self.agents.keys():
            try:
                script = self.fetch_script(agent_name)
                scripts.append(script)
                logging.info(f"Fetched script from {agent_name}: {script.id}")
            except Exception as e:
                logging.error(f"Failed to fetch from {agent_name}: {e}")
        
        return scripts


# ============================================================================
# Video Generator
# ============================================================================

class VideoGenerator:
    """Wrapper for video_creator.py script."""
    
    def __init__(self, config: Config):
        self.config = config
        self.script_path = config.get('video.script_path', 'video_creator.py')
        self.output_dir = config.get('video.output_dir', './output/videos')
        self.default_voice = config.get('video.default_voice', 'ja-JP-NanamiNeural')
        
        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate(self, job: VideoJob) -> str:
        """Generate video from script job."""
        script = job.script
        
        # Build command
        # Note: This assumes video_creator.py accepts JSON input
        cmd = [
            sys.executable,
            self.script_path,
            '--script', script.content,
            '--voice', script.voice,
            '--duration', str(script.duration),
            '--output', self.output_dir
        ]
        
        if script.background_images:
            cmd.extend(['--images', ','.join(script.background_images)])
        
        if script.hashtags:
            cmd.extend(['--hashtags', ' '.join(script.hashtags)])
        
        logging.info(f"Generating video for script {script.id}")
        logging.debug(f"Command: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes max
            )
            
            if result.returncode != 0:
                raise Exception(f"Video generation failed: {result.stderr}")
            
            # Parse output for video path
            output = result.stdout.strip()
            # Assume output contains the video path
            video_path = os.path.join(self.output_dir, f"{script.id}.mp4")
            
            if not os.path.exists(video_path):
                raise Exception(f"Video file not found: {video_path}")
            
            return video_path
            
        except subprocess.TimeoutExpired:
            raise RetryableError("Video generation timeout")
        except Exception as e:
            if "retry" not in str(e).lower():
                raise RetryableError(f"Video generation error: {e}")
            raise


# ============================================================================
# OpenClaw Poster
# ============================================================================

class OpenClawPoster:
    """Wrapper for openclaw_poster.py script."""
    
    def __init__(self, config: Config):
        self.config = config
        self.cli_path = config.get('openclaw.cli_path', 'openclaw')
        self.session_dir = config.get('openclaw.session_dir', '~/.openclaw/sessions')
        self.timeout = config.get('openclaw.connection_timeout', 60)
        self.verify = config.get('openclaw.verify_post', True)
    
    def post(self, video_path: str, account: Account, hashtags: List[str]) -> bool:
        """Post video using OpenClaw."""
        caption = f"Check this out! #fyp #viral"
        if hashtags:
            caption += " " + " ".join(hashtags)
        
        # Build command
        cmd = [
            self.cli_path,
            'message', 'send',
            '--session', account.session,
            '--video', video_path,
            '--caption', caption
        ]
        
        logging.info(f"Posting video {video_path} with account {account.id}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            if result.returncode != 0:
                raise Exception(f"Post failed: {result.stderr}")
            
            if self.verify:
                # Wait and verify post was successful
                time.sleep(5)
                # Add verification logic here
            
            return True
            
        except subprocess.TimeoutExpired:
            raise RetryableError("OpenClaw post timeout")
        except Exception as e:
            if "banned" in str(e).lower():
                raise FatalError(f"Account {account.id} may be banned: {e}")
            raise RetryableError(f"OpenClaw post error: {e}")


# ============================================================================
# Account Pool Manager
# ============================================================================

class AccountPoolManager:
    """Manages account pools and rotation."""
    
    def __init__(self, config: Config):
        self.config = config
        self.pools = {}
        self._load_accounts()
    
    def _load_accounts(self):
        """Load accounts from configuration."""
        pools_config = self.config.get('accounts.pools', [])
        
        for pool_config in pools_config:
            pool_id = pool_config['pool_id']
            accounts = []
            
            for acc_config in pool_config.get('accounts', []):
                account = Account(
                    id=acc_config['id'],
                    session=acc_config['session'],
                    proxy=acc_config.get('proxy'),
                    pool_id=pool_id,
                    is_active=True
                )
                accounts.append(account)
            
            self.pools[pool_id] = {
                'niche': pool_config.get('niche', 'general'),
                'accounts': accounts,
                'max_daily': pool_config.get('max_daily_posts', 5),
                'min_interval': pool_config.get('min_interval', 30)
            }
    
    def get_available_account(self, pool_id: str) -> Optional[Account]:
        """Get an available account from a pool."""
        pool = self.pools.get(pool_id)
        if not pool:
            return None
        
        accounts = pool['accounts']
        max_daily = pool['max_daily']
        min_interval = pool['min_interval']
        
        # Shuffle for variety
        random.shuffle(accounts)
        
        for account in accounts:
            if account.can_post(max_daily, min_interval):
                return account
        
        return None
    
    def get_pool_for_niche(self, niche: str) -> Optional[str]:
        """Get pool ID for a given niche."""
        for pool_id, pool in self.pools.items():
            if pool['niche'] == niche:
                return pool_id
        return None
    
    def record_post(self, account: Account):
        """Record a successful post for an account."""
        account.daily_post_count += 1
        account.last_post_time = datetime.now()
    
    def mark_shadowban(self, account: Account):
        """Mark account as potentially shadowbanned."""
        account.shadowban_count += 1
        if account.shadowban_count >= 3:
            account.is_active = False
            logging.warning(f"Account {account.id} disabled due to shadowban")
    
    def reset_daily_counts(self):
        """Reset daily post counts (call at midnight)."""
        for pool in self.pools.values():
            for account in pool['accounts']:
                account.daily_post_count = 0


# ============================================================================
# Proxy Manager
# ============================================================================

class ProxyManager:
    """Manages proxy rotation for IP dispersion."""
    
    def __init__(self, config: Config):
        self.config = config
        self.proxies = config.get('protection.ip_rotation.proxy_pool', [])
        self.strategy = config.get('protection.ip_rotation.rotation_strategy', 'round_robin')
        self._current_index = 0
        self._lock = threading.Lock()
        
        if not self.proxies:
            logging.warning("No proxies configured - running without proxy rotation")
    
    def get_proxy(self) -> Optional[Dict]:
        """Get next proxy from pool."""
        if not self.proxies:
            return None
        
        with self._lock:
            if self.strategy == 'round_robin':
                proxy = self.proxies[self._current_index]
                self._current_index = (self._current_index + 1) % len(self.proxies)
            elif self.strategy == 'random':
                proxy = random.choice(self.proxies)
            else:  # sticky
                proxy = self.proxies[0]
        
        # Format for requests
        return {
            'http': proxy,
            'https': proxy
        }


# ============================================================================
# Job Queue
# ============================================================================

class JobQueue:
    """Thread-safe job queue for video generation and posting."""
    
    def __init__(self, config: Config):
        self.config = config
        self.max_size = config.get('video.max_queue_size', 50)
        self._queue = queue.PriorityQueue(maxsize=self.max_size)
        self._jobs = {}  # job_id -> VideoJob
        self._lock = threading.Lock()
        
        # Statistics
        self.stats = {
            'total_jobs': 0,
            'completed': 0,
            'failed': 0
        }
    
    def add_job(self, job: VideoJob) -> bool:
        """Add job to queue."""
        with self._lock:
            if self._queue.full():
                logging.warning("Job queue is full")
                return False
            
            # Priority: lower number = higher priority
            priority = 0 if job.status == JobStatus.PENDING else 1
            self._queue.put((priority, job.id))
            self._jobs[job.id] = job
            self.stats['total_jobs'] += 1
            
            logging.info(f"Added job {job.id} to queue")
            return True
    
    def get_job(self, timeout: float = 1.0) -> Optional[VideoJob]:
        """Get next job from queue."""
        try:
            _, job_id = self._queue.get(timeout=timeout)
            job = self._jobs.get(job_id)
            return job
        except queue.Empty:
            return None
    
    def update_job(self, job: VideoJob):
        """Update job status."""
        with self._lock:
            job.updated_at = datetime.now()
            self._jobs[job.id] = job
            
            if job.status == JobStatus.COMPLETED:
                self.stats['completed'] += 1
            elif job.status == JobStatus.FAILED:
                self.stats['failed'] += 1
    
    def get_pending_count(self) -> int:
        """Get count of pending jobs."""
        return self._queue.qsize()


# ============================================================================
# Master Controller (Main Orchestrator)
# ============================================================================

class MasterController:
    """Main orchestrator for the content factory."""
    
    def __init__(self, config: Config, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        
        # Initialize components
        self.error_handler = ErrorHandler(config)
        self.agent_client = AzureAgentClient(config)
        self.video_generator = VideoGenerator(config)
        self.openclaw_poster = OpenClawPoster(config)
        self.account_manager = AccountPoolManager(config)
        self.proxy_manager = ProxyManager(config)
        self.job_queue = JobQueue(config)
        
        # Execution settings
        self.cycle_interval = config.get('execution.cycle_interval', 60)
        self.adaptive = config.get('execution.adaptive_interval', True)
        self.health_check_interval = config.get('execution.health_check_interval', 300)
        
        # Shutdown flag
        self._shutdown = threading.Event()
        
        # Threading
        self._worker_threads = []
        self._num_workers = config.get('video.worker_threads', 3)
        
        # Setup logging
        self._setup_logging()
        
        # Daily reset timer
        self._last_daily_reset = datetime.now()
    
    def _setup_logging(self):
        """Setup logging configuration."""
        log_level = self.config.get('logging.level', 'INFO')
        log_format = self.config.get('logging.format', 'json')
        log_output = self.config.get('logging.output', 'both')
        
        # Create logs directory
        log_dir = self.config.get('logging.log_dir', './logs')
        os.makedirs(log_dir, exist_ok=True)
        
        # Configure root logger
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f"{log_dir}/controller.log"),
                logging.StreamHandler()
            ]
        )
        
        logging.info(f"Master Controller initialized (dry_run={self.dry_run})")
    
    def _fetch_scripts_cycle(self):
        """Fetch scripts from all Azure Agents."""
        logging.info("=== Starting script fetch cycle ===")
        
        scripts = self.agent_client.fetch_all_agents()
        
        for script in scripts:
            # Get matching pool
            pool_id = self.account_manager.get_pool_for_niche(script.agent_name)
            if not pool_id:
                pool_id = self.account_manager.get_pool_for_niche('general')
            
            if not pool_id:
                logging.warning(f"No pool found for agent {script.agent_name}")
                continue
            
            # Create job
            job = VideoJob(
                id=str(uuid.uuid4()),
                script=script,
                status=JobStatus.SCRIPT_FETCHED
            )
            
            self.job_queue.add_job(job)
            logging.info(f"Created job {job.id} for script {script.id}")
        
        logging.info(f"=== Script fetch complete: {len(scripts)} scripts ===")
    
    def _process_video_job(self, job: VideoJob):
        """Process a single video job."""
        job.status = JobStatus.VIDEO_GENERATING
        self.job_queue.update_job(job)
        
        # Generate video
        try:
            output_path = self.video_generator.generate(job)
            job.output_path = output_path
            job.status = JobStatus.VIDEO_READY
            self.job_queue.update_job(job)
            
        except Exception as e:
            job.error_message = str(e)
            
            if self.error_handler.is_retryable(e) and job.retry_count < 3:
                job.status = JobStatus.RETRYING
                job.retry_count += 1
                self.job_queue.add_job(job)  # Re-queue
                logging.warning(f"Job {job.id} retrying (attempt {job.retry_count})")
            else:
                job.status = JobStatus.FAILED
                logging.error(f"Job {job.id} failed: {e}")
            
            self.job_queue.update_job(job)
    
    def _post_video_job(self, job: VideoJob):
        """Post a video job to TikTok."""
        if job.status != JobStatus.VIDEO_READY:
            return
        
        # Get account
        pool_id = self.account_manager.get_pool_for_niche(job.script.agent_name)
        if not pool_id:
            job.status = JobStatus.FAILED
            job.error_message = "No matching pool"
            self.job_queue.update_job(job)
            return
        
        account = self.account_manager.get_available_account(pool_id)
        if not account:
            # Re-queue for later
            time.sleep(30)
            self.job_queue.add_job(job)
            return
        
        job.status = JobStatus.POSTING
        self.job_queue.update_job(job)
        
        # Dry run mode - skip actual posting
        if self.dry_run:
            logging.info(f"[DRY RUN] Would post {job.output_path} with account {account.id}")
            job.status = JobStatus.COMPLETED
            self.job_queue.update_job(job)
            return
        
        # Post using OpenClaw
        try:
            success = self.openclaw_poster.post(
                job.output_path,
                account,
                job.script.hashtags
            )
            
            if success:
                self.account_manager.record_post(account)
                job.status = JobStatus.COMPLETED
                logging.info(f"Job {job.id} posted successfully")
            else:
                job.status = JobStatus.FAILED
                job.error_message = "Post verification failed"
                
        except FatalError as e:
            self.account_manager.mark_shadowban(account)
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            logging.error(f"Shadowban detected for account {account.id}")
            
        except Exception as e:
            job.error_message = str(e)
            
            if self.error_handler.is_retryable(e):
                job.status = JobStatus.VIDEO_READY
                self.job_queue.add_job(job)
            else:
                job.status = JobStatus.FAILED
        
        self.job_queue.update_job(job)
    
    def _worker_loop(self, worker_id: int):
        """Worker thread main loop."""
        logging.info(f"Worker {worker_id} started")
        
        while not self._shutdown.is_set():
            try:
                job = self.job_queue.get_job(timeout=1.0)
                
                if job is None:
                    continue
                
                # Process based on job status
                if job.status == JobStatus.SCRIPT_FETCHED:
                    self._process_video_job(job)
                elif job.status == JobStatus.VIDEO_READY:
                    self._post_video_job(job)
                elif job.status == JobStatus.RETRYING:
                    self._process_video_job(job)
                    
            except Exception as e:
                logging.error(f"Worker {worker_id} error: {e}")
        
        logging.info(f"Worker {worker_id} stopped")
    
    def _health_check(self):
        """Perform health check."""
        queue_size = self.job_queue.get_pending_count()
        stats = self.job_queue.stats
        
        logging.info(
            f"Health: queue={queue_size}, "
            f"total={stats['total_jobs']}, "
            f"completed={stats['completed']}, "
            f"failed={stats['failed']}"
        )
        
        # Check for daily reset
        now = datetime.now()
        if now.date() > self._last_daily_reset.date():
            self.account_manager.reset_daily_counts()
            self._last_daily_reset = now
            logging.info("Daily counters reset")
    
    def run(self):
        """Main execution loop."""
        logging.info("Starting Master Controller")
        
        # Start worker threads
        for i in range(self._num_workers):
            t = threading.Thread(target=self._worker_loop, args=(i,), daemon=True)
            t.start()
            self._worker_threads.append(t)
        
        health_counter = 0
        
        try:
            while not self._shutdown.is_set():
                # Fetch new scripts
                self._fetch_scripts_cycle()
                
                # Wait for next cycle
                for _ in range(int(self.cycle_interval)):
                    if self._shutdown.is_set():
                        break
                    
                    health_counter += 1
                    if health_counter >= self.health_check_interval:
                        self._health_check()
                        health_counter = 0
                    
                    time.sleep(1)
                    
        except KeyboardInterrupt:
            logging.info("Received interrupt signal")
        finally:
            self._shutdown.set()
            
            # Wait for workers
            for t in self._worker_threads:
                t.join(timeout=5)
            
            logging.info("Master Controller stopped")
    
    def stop(self):
        """Signal shutdown."""
        logging.info("Shutting down...")
        self._shutdown.set()


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="AI Content Factory - Master Controller"
    )
    parser.add_argument(
        '--config', '-c',
        default='config.yaml',
        help='Path to configuration file'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run in test mode (no actual posting)'
    )
    parser.add_argument(
        '--log-level',
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = Config(args.config)
    
    # Override log level if specified
    if args.log_level:
        config._config['logging']['level'] = args.log_level
    
    # Create and run controller
    controller = MasterController(config, dry_run=args.dry_run)
    
    try:
        controller.run()
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
