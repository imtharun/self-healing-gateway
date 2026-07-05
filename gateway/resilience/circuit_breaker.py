# default
import time
from enum import Enum


class CircuitStatus(Enum):
    closed = "CLOSED"
    open = "OPEN"
    half_open = "HALF_OPEN"


class CircuitBreaker:
    def __init__(
        self, name: str, failure_threshold: int = 5, recovery_timeout: int = 30
    ):
        self.name = name
        self.state: CircuitStatus = CircuitStatus.closed
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.opened_at = None

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = CircuitStatus.closed
        self.opened_at = None

    def record_failure(self) -> None:
        self.failure_count += 1
        if (
            self.state == CircuitStatus.half_open
            or self.failure_count >= self.failure_threshold
        ):
            self.state = CircuitStatus.open
            self.opened_at = time.time()

    @property
    def current_state(self) -> CircuitStatus:
        if self.state == CircuitStatus.open:
            if (time.time() - self.opened_at) >= self.recovery_timeout:
                return CircuitStatus.half_open
        return self.state

    def is_open(self) -> bool:
        current = self.current_state
        if current == CircuitStatus.closed:
            return False
        elif current == CircuitStatus.half_open:
            self.state = CircuitStatus.half_open
            return False
        return True

    def __repr__(self) -> str:
        return f"CircuitBreaker(name={self.name}, state={self.state.value}, failures={self.failure_count}/{self.failure_threshold})"
