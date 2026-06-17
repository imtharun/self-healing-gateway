# built-in
import asyncio
import random


async def retry_request(func, max_retries: int = 3, base_delay: float = 1.0):
    """
    Retries an async callable with exponential backoff + jitter.

    Args:
        func: async callable that makes the HTTP request (no args needed)
        max_retries: how many times to retry before giving up
        base_delay: base wait time in seconds (doubles each attempt)

    Returns:
        The result of func() on success

    Raises:
        The last exception if all retries are exhausted
    """

    last_exception = None

    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            last_exception = e

            if attempt == max_retries - 1:
                break

        delay = base_delay * (2 ** (attempt + 1))
        jitter = random.uniform(0, delay)

        await asyncio.sleep(delay + jitter)

    raise last_exception
