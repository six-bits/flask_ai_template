"""Concurrency and race condition tests for Multi-Currency Wallet."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import pytest

from app.adapter.idempotency_adapter import idempotency_adapter
from app.adapter.quote_adapter import quote_adapter
from app.adapter.transaction_adapter import transaction_adapter
from app.adapter.user_wallet_adapter import user_wallet_adapter
from app.manager.lock_manager import lock_manager
from app.service.api import app


@pytest.fixture(autouse=True)
def reset_all():
    """Reset all state before each concurrency test."""
    user_wallet_adapter.reset()
    quote_adapter.reset()
    transaction_adapter.reset()
    idempotency_adapter.reset()
    lock_manager.reset()


def test_concurrent_transfers_from_same_user_exhausts_balance_without_overdraft():
    """Test that 20 concurrent transfer threads competing for Alice's balance

    never cause double-spending or negative balance overdrafts.
    Alice has 100,000 USD cents ($1000.00). 20 threads try to transfer 10,000 cents ($100.00).
    Exactly 10 must succeed; exactly 10 must fail with INSUFFICIENT_FUNDS.
    """
    def do_transfer():
        c = app.test_client()
        return c.post("/transfers", json={
            "from_user_id": "user_1",
            "to_user_id": "user_2",
            "currency": "USD",
            "amount": 10000,
        })

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(do_transfer) for _ in range(20)]
        for f in as_completed(futures):
            results.append(f.result())

    successes = [r for r in results if r.status_code == 200]
    failures = [r for r in results if r.status_code == 400]

    assert len(successes) == 10
    assert len(failures) == 10

    for fail in failures:
        assert fail.get_json()["error"] == "INSUFFICIENT_FUNDS"

    # Alice's balance must be exactly 0 cents (never negative!)
    c = app.test_client()
    bal_res_alice = c.get("/users/user_1/balances")
    assert bal_res_alice.get_json()["balances"]["USD"] == 0

    # Bob's balance started at 25,000 + 10 * 10,000 = 125,000 cents
    bal_res_bob = c.get("/users/user_2/balances")
    assert bal_res_bob.get_json()["balances"]["USD"] == 125000

    # Transit clearing pools must have zero drift
    pools = user_wallet_adapter.get_transit_pool_balances()
    assert pools["outbound"]["USD"] == 0
    assert pools["inbound"]["USD"] == 0


def test_bidirectional_concurrent_transfers_no_deadlock():
    """Test that concurrent transfers in opposite directions (Alice -> Bob and Bob -> Alice)

    execute without circular deadlocks due to lexicographical lock acquisition.
    """
    def transfer_alice_to_bob():
        c = app.test_client()
        return c.post("/transfers", json={
            "from_user_id": "user_1",
            "to_user_id": "user_2",
            "currency": "USD",
            "amount": 1000,
        })

    def transfer_bob_to_alice():
        c = app.test_client()
        return c.post("/transfers", json={
            "from_user_id": "user_2",
            "to_user_id": "user_1",
            "currency": "USD",
            "amount": 1000,
        })

    tasks = []
    for _ in range(10):
        tasks.append(transfer_alice_to_bob)
        tasks.append(transfer_bob_to_alice)

    results = []
    # If deadlock occurs, this executor would hang indefinitely
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fn) for fn in tasks]
        for f in as_completed(futures, timeout=10.0):
            results.append(f.result())

    assert len(results) == 20
    for res in results:
        assert res.status_code == 200

    # Balances must be conserved
    c = app.test_client()
    bal_alice = c.get("/users/user_1/balances").get_json()["balances"]["USD"]
    bal_bob = c.get("/users/user_2/balances").get_json()["balances"]["USD"]

    assert bal_alice == 100000
    assert bal_bob == 25000


def test_concurrent_quote_acceptance_race():
    """Test that concurrent attempts to accept the exact same quote allow exactly 1 success."""
    c = app.test_client()
    q_res = c.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    })
    quote_id = q_res.get_json()["quote_id"]

    def accept():
        thread_c = app.test_client()
        return thread_c.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"})

    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(accept) for _ in range(5)]
        for f in as_completed(futures):
            results.append(f.result())

    successes = [r for r in results if r.status_code == 200]
    failures = [r for r in results if r.status_code == 400]

    assert len(successes) == 1
    assert len(failures) == 4

    for f in failures:
        assert f.get_json()["error"] == "QUOTE_ALREADY_ACCEPTED"

    # Alice was debited exactly once
    bal = c.get("/users/user_1/balances").get_json()["balances"]["USD"]
    assert bal == 90000
