"""HTTP utilities: timeouts, retries, and resilience helpers."""

import logging
import time
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)

# Default timeouts: (connect_timeout, read_timeout)
DEFAULT_TIMEOUT = (3, 15)
API_TIMEOUT = (5, 30)


def retry_on_transient(
    func: Callable,
    max_retries: int = 2,
    backoff_factor: float = 1.0,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Lightweight retry wrapper for transient failures (429, 5xx).

    Args:
        func: Callable to retry (e.g., requests.get)
        max_retries: Number of retries on transient error
        backoff_factor: Exponential backoff multiplier (e.g., 1.0 = 1s, 2s, 4s)
        *args: Positional arguments to func
        **kwargs: Keyword arguments to func

    Returns:
        Result of func if successful

    Raises:
        Last exception if all retries exhausted
    """
    attempt = 0
    last_exception = None

    while attempt <= max_retries:
        try:
            response = func(*args, **kwargs)

            # Retry on transient errors
            if response.status_code in (429, 503, 504):
                if attempt < max_retries:
                    wait = (backoff_factor ** attempt)
                    logger.debug(
                        f"Transient error {response.status_code}, "
                        f"retrying in {wait}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                    attempt += 1
                    continue
                else:
                    return response

            return response

        except (TimeoutError, ConnectionError, OSError) as e:
            last_exception = e

            if attempt < max_retries:
                wait = (backoff_factor ** attempt)
                logger.debug(
                    f"Connection error: {e}. "
                    f"Retrying in {wait}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                attempt += 1
            else:
                raise

    if last_exception:
        raise last_exception


__all__ = [
    "DEFAULT_TIMEOUT",
    "API_TIMEOUT",
    "retry_on_transient",
]
