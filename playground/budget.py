"""Monotonic run budget; HTTP attempts and semantic intents are independent."""
from __future__ import annotations
import time
import queue
import threading

MAX_SEMANTIC_CALLS = 2
MAX_REPAIRS = 1
TARGET_HTTP_REQUESTS = 1
MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL = 3
HARD_API_REQUEST_LIMIT = 10
MAX_COMPLETION_TOKENS_TOTAL = 30000
DEADLINE_SECONDS = 570


class BudgetExceeded(RuntimeError):
    pass


def call_with_timeout(function, seconds: float):
    """Bound caller wall time even if a remote server keeps a socket alive.

    A daemon worker cannot delay CLI exit. After timeout the caller must not
    launch another request and must account the reserved completion allowance.
    """
    if seconds <= 0:
        raise BudgetExceeded('Network deadline reached')
    result = queue.Queue(maxsize=1)

    def work():
        try:
            result.put((True, function()))
        except BaseException as exc:
            result.put((False, exc))

    threading.Thread(target=work, daemon=True).start()
    try:
        ok, value = result.get(timeout=seconds)
    except queue.Empty as exc:
        raise BudgetExceeded('Network deadline reached') from exc
    if not ok:
        raise value
    return value


class BudgetManager:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.semantic_calls = 0
        self.http_requests = 0
        self.repairs = 0
        self.prompt_tokens_total = 0
        self.completion_tokens_total = 0
        self.attempts_in_call = 0

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, DEADLINE_SECONDS - (self.clock() - self.started))

    @property
    def remaining_tokens(self) -> int:
        return max(0, MAX_COMPLETION_TOKENS_TOTAL - self.completion_tokens_total)

    def check_available(self, *, wait_seconds: float = 0) -> None:
        if self.remaining_seconds <= wait_seconds:
            raise BudgetExceeded('Run deadline reached')
        if self.http_requests >= HARD_API_REQUEST_LIMIT:
            raise BudgetExceeded('HTTP request budget exhausted')
        if self.remaining_tokens <= 0:
            raise BudgetExceeded('Completion token budget exhausted')

    def start_semantic(self, purpose: str) -> int:
        self.check_available()
        if purpose not in ('generation', 'repair', 'regeneration'):
            raise ValueError('Unknown semantic purpose')
        if self.semantic_calls >= MAX_SEMANTIC_CALLS:
            raise BudgetExceeded('Semantic call budget exhausted')
        if purpose == 'generation' and self.semantic_calls:
            raise BudgetExceeded('Only one generation intent is allowed')
        if purpose in ('repair', 'regeneration') and (not self.semantic_calls or self.repairs >= MAX_REPAIRS):
            raise BudgetExceeded('Repair intent unavailable')
        self.semantic_calls += 1
        self.repairs += int(purpose in ('repair', 'regeneration'))
        self.attempts_in_call = 0
        return self.semantic_calls

    def begin_http_attempt(self) -> int:
        self.check_available()
        if not self.semantic_calls:
            raise BudgetExceeded('No active semantic call')
        if self.attempts_in_call >= MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL:
            raise BudgetExceeded('HTTP attempts per semantic call exhausted')
        self.attempts_in_call += 1
        self.http_requests += 1
        return self.http_requests

    def completion_allowance(self, preferred: int = 15000) -> int:
        self.check_available()
        return min(preferred, self.remaining_tokens)

    def record_usage(self, *, prompt_tokens: int = 0, completion_tokens: int | None = None,
                     reserved_tokens: int = 0) -> None:
        self.prompt_tokens_total += max(0, int(prompt_tokens))
        self.completion_tokens_total += max(0, int(reserved_tokens if completion_tokens is None else completion_tokens))
        if self.completion_tokens_total > MAX_COMPLETION_TOKENS_TOTAL:
            raise BudgetExceeded('Provider reported completion usage above budget')

    def totals(self) -> dict:
        return dict(semantic_calls=self.semantic_calls, http_requests=self.http_requests,
                    repairs=self.repairs, prompt_tokens_total=self.prompt_tokens_total,
                    completion_tokens_total=self.completion_tokens_total,
                    elapsed_seconds_total=round(self.clock() - self.started, 6))
