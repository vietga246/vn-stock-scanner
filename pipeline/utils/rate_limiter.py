"""
rate_limiter.py — Shared Rate Limiting Utilities

Hai loại rate limiter cho các use cases khác nhau:

1. AdaptiveRateLimiter: Single-threaded, sliding window
   - Dùng cho: bootstrap_prices, daily_prices, daily_foreign_flow
   - Tự động slowdown khi gần limit

2. GlobalRateController: Multi-threaded, interval-based
   - Dùng cho: quarterly_financials (multi-worker)
   - Thread-safe với global cooldown
"""

from collections import deque
from typing import Optional
import threading
import logging
import time
import re
import sys

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════
# ADAPTIVE RATE LIMITER (Single-threaded)
# ════════════════════════════════════════════════════════════════════════════

class AdaptiveRateLimiter:
    """
    Sliding window rate limiter with soft slowdown.
    
    Khi số request gần đạt limit, tự động delay để tránh hit hard limit.
    Phù hợp cho single-threaded collectors.
    
    Usage:
        limiter = AdaptiveRateLimiter(rpm=60, safety_ratio=0.9)
        for item in items:
            limiter.acquire()
            fetch(item)
    """
    
    def __init__(self, rpm: int, safety_ratio: float = 0.9):
        """
        Args:
            rpm: Maximum requests per minute
            safety_ratio: Start slowing down at this % of rpm (default 90%)
        """
        self.rpm = rpm
        self.threshold = int(rpm * safety_ratio)
        self.window = 60  # seconds
        self.requests: deque = deque()
    
    def acquire(self) -> None:
        """
        Acquire permission to make a request.
        Blocks if necessary to stay within rate limit.
        """
        now = time.time()
        
        # Remove expired timestamps (older than window)
        while self.requests and now - self.requests[0] > self.window:
            self.requests.popleft()
        
        current = len(self.requests)
        
        # HARD LIMIT — wait until slot available
        if current >= self.rpm:
            sleep_time = self.window - (now - self.requests[0]) + 0.1
            log.info("[RateLimiter] Hard limit reached → sleep %.2fs", sleep_time)
            time.sleep(sleep_time)
            return self.acquire()  # Retry after sleep
        
        # SOFT SLOWDOWN — gradually delay when approaching limit
        if current >= self.threshold:
            overload = current - self.threshold
            dynamic_delay = overload * (60 / self.rpm)
            log.debug("[RateLimiter] Near limit (%d/%d) → delay %.3fs", 
                     current, self.rpm, dynamic_delay)
            time.sleep(dynamic_delay)
        
        self.requests.append(time.time())
    
    def reset(self) -> None:
        """Clear all tracked requests. Call after rate limit error."""
        self.requests.clear()
    
    @property
    def current_usage(self) -> int:
        """Current number of requests in the window."""
        now = time.time()
        while self.requests and now - self.requests[0] > self.window:
            self.requests.popleft()
        return len(self.requests)


# ════════════════════════════════════════════════════════════════════════════
# GLOBAL RATE CONTROLLER (Multi-threaded)
# ════════════════════════════════════════════════════════════════════════════

class GlobalRateController:
    """
    Thread-safe interval-based rate limiter with global cooldown.
    
    Đảm bảo minimum interval giữa các requests từ tất cả workers.
    Khi server báo rate limit, trigger global cooldown cho tất cả workers.
    
    Usage:
        controller = GlobalRateController(rpm=40)
        
        def worker(symbol):
            controller.acquire()
            data = fetch(symbol)
            return data
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = executor.map(worker, symbols)
    """
    
    def __init__(self, rpm: int):
        """
        Args:
            rpm: Maximum requests per minute (interval = 60/rpm seconds)
        """
        self.min_interval = 60.0 / rpm
        self.lock = threading.Lock()
        self.last_call = 0.0
        self.pause_until = 0.0
        self._server_wait: Optional[int] = None
    
    def acquire(self) -> None:
        """
        Acquire permission to make a request.
        Thread-safe, blocks if necessary.
        """
        while True:
            with self.lock:
                now = time.time()
                
                # Check global cooldown
                if now < self.pause_until:
                    sleep_time = self.pause_until - now
                else:
                    # Calculate next allowed request time
                    next_allowed = self.last_call + self.min_interval
                    if now >= next_allowed:
                        # Slot available - acquire it
                        self.last_call = now
                        # Reset server_wait if cooldown has passed
                        if self._server_wait and now > self.pause_until:
                            self._server_wait = None
                        return
                    sleep_time = next_allowed - now
            
            # Sleep in chunks to prevent GitHub Actions timeout
            self._chunked_sleep(sleep_time)
    
    def set_server_wait(self, seconds: int) -> None:
        """
        Set wait time parsed from server error message.
        Called by stdout capture when rate limit detected.
        """
        with self.lock:
            self._server_wait = seconds
    
    def trigger_cooldown(self, fallback: int = 65) -> int:
        """
        Trigger global cooldown for all workers.
        
        Args:
            fallback: Default wait time if server wait not available
            
        Returns:
            Actual wait time in seconds
        """
        with self.lock:
            now = time.time()
            
            # Use server wait time if available, else fallback
            seconds = self._server_wait if self._server_wait else fallback
            new_pause = now + seconds
            
            if new_pause > self.pause_until:
                # First worker to trigger cooldown
                self.pause_until = new_pause
                self.last_call = new_pause  # Stagger after cooldown
                log.info("[RateController] Global cooldown: %ds", seconds)
            else:
                # Cooldown already active, use remaining time
                seconds = max(1, int(self.pause_until - now))
            
            return seconds
    
    def reset(self) -> None:
        """Reset all state. Use with caution in multi-threaded context."""
        with self.lock:
            self.pause_until = 0.0
            self.last_call = 0.0
            self._server_wait = None
    
    def _chunked_sleep(self, seconds: float, chunk: float = 10) -> None:
        """
        Sleep in chunks with progress logging.
        Prevents GitHub Actions from killing process due to no output.
        """
        remaining = seconds
        while remaining > 0:
            t = min(chunk, remaining)
            time.sleep(t)
            remaining -= t
            if remaining > 0:
                log.info("[RateController] Waiting... %.0fs remaining", remaining)
                sys.stdout.flush()


# ════════════════════════════════════════════════════════════════════════════
# STDOUT CAPTURE (for vnstock rate limit messages)
# ════════════════════════════════════════════════════════════════════════════

class WaitTimeCapture:
    """
    Wrapper for sys.stdout to capture wait time from vnstock rate limit messages.
    
    vnstock prints messages like "Chờ 27 giây" before raising SystemExit.
    This captures and parses those messages.
    
    Usage:
        controller = GlobalRateController(rpm=40)
        sys.stdout = WaitTimeCapture(sys.stdout, controller)
    """
    
    PATTERNS = [
        r'Ch[oờ]\s*(\d+)\s*gi[aâ]y',   # Vietnamese: "Chờ 27 giây"
        r'[Ww]ait\s*(\d+)\s*second',    # English: "Wait 27 seconds"
        r'retry\s*after\s*(\d+)',       # "retry after 27"
    ]
    
    def __init__(self, real_stdout, controller: Optional[GlobalRateController] = None):
        self._real = real_stdout
        self._controller = controller
    
    def write(self, s: str) -> None:
        self._real.write(s)
        
        if self._controller is None:
            return
        
        # Try to parse wait time from output
        for pattern in self.PATTERNS:
            match = re.search(pattern, s, re.IGNORECASE)
            if match:
                wait = int(match.group(1)) + 5  # Add buffer
                self._controller.set_server_wait(wait)
                break
    
    def flush(self) -> None:
        self._real.flush()
    
    def __getattr__(self, name):
        return getattr(self._real, name)
