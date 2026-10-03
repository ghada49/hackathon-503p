import pytest
from playground.budget import BudgetExceeded, BudgetManager
from playground.budget import call_with_timeout
import threading


def test_retry_counters_independent():
    b = BudgetManager()
    b.start_semantic('generation')
    for _ in range(3):
        b.begin_http_attempt()
    assert (b.semantic_calls, b.http_requests, b.repairs) == (1, 3, 0)
    with pytest.raises(BudgetExceeded):
        b.begin_http_attempt()
    b.start_semantic('repair')
    b.begin_http_attempt()
    assert (b.semantic_calls, b.http_requests, b.repairs) == (2, 4, 1)
    with pytest.raises(BudgetExceeded):
        b.start_semantic('repair')


def test_hard_request_ceiling():
    b = BudgetManager()
    b.start_semantic('generation')
    b.http_requests = 10
    with pytest.raises(BudgetExceeded):
        b.begin_http_attempt()


def test_tokens_and_deadline():
    now = [0.0]
    b = BudgetManager(clock=lambda: now[0])
    b.record_usage(prompt_tokens=12, completion_tokens=30000)
    with pytest.raises(BudgetExceeded):
        b.start_semantic('generation')
    b = BudgetManager(clock=lambda: now[0])
    now[0] = 570
    with pytest.raises(BudgetExceeded):
        b.start_semantic('generation')


def test_wait_must_fit_deadline():
    now = [0.0]
    b = BudgetManager(clock=lambda: now[0])
    now[0] = 569
    with pytest.raises(BudgetExceeded):
        b.check_available(wait_seconds=2)


def test_failed_attempt_conservatively_accounts_reserved_tokens():
    b = BudgetManager()
    b.start_semantic('generation')
    b.begin_http_attempt()
    b.record_usage(completion_tokens=None, reserved_tokens=10000)
    assert b.completion_tokens_total == 10000
    assert b.completion_allowance() == 15000


def test_total_wall_time_bound_even_if_transport_keeps_waiting():
    release = threading.Event()
    try:
        with pytest.raises(BudgetExceeded):
            call_with_timeout(lambda: release.wait(5), 0.02)
    finally:
        release.set()


def test_bounded_call_propagates_result_and_exception():
    assert call_with_timeout(lambda: 4, 1) == 4
    def fail():
        raise ValueError('underlying failure')
    with pytest.raises(ValueError, match='underlying failure'):
        call_with_timeout(fail, 1)
