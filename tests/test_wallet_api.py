"""End-to-end integration and unit tests for the Multi-Currency Wallet."""

from datetime import datetime, timedelta, timezone
import pytest

from app.adapter.exchange_rate_adapter import exchange_rate_adapter
from app.adapter.quote_adapter import quote_adapter
from app.adapter.transaction_adapter import transaction_adapter
from app.adapter.user_wallet_adapter import user_wallet_adapter


@pytest.fixture(autouse=True)
def reset_all_adapters():
    """Reset all in-memory adapters before each test."""
    user_wallet_adapter.reset()
    quote_adapter.reset()
    transaction_adapter.reset()
    exchange_rate_adapter.reset()


# =========================================================================
# 1. Balances Tests
# =========================================================================

def test_get_balances_success(client):
    """Test querying balances for Alice (user_1)."""
    res = client.get("/users/user_1/balances")
    assert res.status_code == 200
    data = res.get_json()
    assert data["user_id"] == "user_1"
    assert data["balances"] == {
        "USD": 100000,
        "EUR": 50000,
        "GBP": 10000,
    }


def test_get_balances_user_not_found(client):
    """Test querying balances for a non-existent user returns 404."""
    res = client.get("/users/unknown_user/balances")
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "USER_NOT_FOUND"


# =========================================================================
# 2. Quote Generation Tests
# =========================================================================

def test_create_quote_success(client):
    """Test generating a guaranteed 30s quote (10000 USD -> EUR at 0.9200)."""
    payload = {
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    }
    res = client.post("/quotes", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["user_id"] == "user_1"
    assert data["from_currency"] == "USD"
    assert data["to_currency"] == "EUR"
    assert data["from_amount"] == 10000
    assert data["exchange_rate"] == "0.9200"
    # gross = round(10000 * 0.92) = 9200, fee = round(9200 * 0.005) = 46, net = 9154
    assert data["fee_amount"] == 46
    assert data["to_amount"] == 9154
    assert data["status"] == "PENDING"
    assert "quote_id" in data
    assert "expires_at" in data

    # Verify 30-second expiry window
    created_at = datetime.fromisoformat(data["created_at"])
    expires_at = datetime.fromisoformat(data["expires_at"])
    diff = (expires_at - created_at).total_seconds()
    assert diff == pytest.approx(30.0, 1.0)


def test_create_quote_identical_currencies(client):
    """Test quote creation fails if currencies are identical."""
    payload = {
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "USD",
        "from_amount": 10000,
    }
    res = client.post("/quotes", json=payload)
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "IDENTICAL_CURRENCIES"


def test_create_quote_invalid_amount(client):
    """Test quote creation fails with invalid or non-integer amounts."""
    # Zero amount
    res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 0,
    })
    assert res.status_code == 400

    # String amount (schema validation expects integer minor units)
    res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": "100.00",
    })
    assert res.status_code == 400
    assert res.get_json()["error"] == "VALIDATION_ERROR"


def test_create_quote_user_not_found(client):
    """Test quote creation fails if user does not exist."""
    res = client.post("/quotes", json={
        "user_id": "ghost_user",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 5000,
    })
    assert res.status_code == 404
    assert res.get_json()["error"] == "USER_NOT_FOUND"


# =========================================================================
# 3. Quote Acceptance & Conversion Tests
# =========================================================================

def test_accept_quote_success(client):
    """Test successful quote acceptance, atomic balance swap, and ledger creation."""
    # 1. Create quote: 10000 USD -> EUR
    quote_res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    })
    assert quote_res.status_code == 201
    quote_id = quote_res.get_json()["quote_id"]

    # 2. Accept quote
    accept_res = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"})
    assert accept_res.status_code == 200
    accept_data = accept_res.get_json()
    assert accept_data["status"] == "ACCEPTED"
    assert accept_data["from_amount"] == 10000
    assert accept_data["to_amount"] == 9154
    assert accept_data["fee_amount"] == 46

    # 3. Verify user's updated balances: USD 100000 - 10000 = 90000; EUR 50000 + 9154 = 59154
    assert accept_data["balances"]["USD"] == 90000
    assert accept_data["balances"]["EUR"] == 59154
    assert accept_data["balances"]["GBP"] == 10000

    # 4. Verify persisted balances match
    bal_res = client.get("/users/user_1/balances")
    assert bal_res.get_json()["balances"]["USD"] == 90000
    assert bal_res.get_json()["balances"]["EUR"] == 59154


def test_accept_quote_expired(client):
    """Test accepting a quote after expiration (> 30s) fails with QUOTE_EXPIRED."""
    quote_res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    })
    quote_id = quote_res.get_json()["quote_id"]

    # Backdate quote expiry to simulate time passing
    quote = quote_adapter.get_quote(quote_id)
    quote.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()

    accept_res = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"})
    assert accept_res.status_code == 400
    assert accept_res.get_json()["error"] == "QUOTE_EXPIRED"


def test_accept_quote_insufficient_funds(client):
    """Test accepting quote fails when user has insufficient source balance."""
    # Charlie (user_3) only has 5000 USD. Request quote for 10000 USD.
    quote_res = client.post("/quotes", json={
        "user_id": "user_3",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    })
    assert quote_res.status_code == 201
    quote_id = quote_res.get_json()["quote_id"]

    accept_res = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_3"})
    assert accept_res.status_code == 400
    data = accept_res.get_json()
    assert data["error"] == "INSUFFICIENT_FUNDS"


def test_accept_quote_double_accept_fails(client):
    """Test accepting the same quote twice fails."""
    quote_res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 5000,
    })
    quote_id = quote_res.get_json()["quote_id"]

    # First accept succeeds
    res1 = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"})
    assert res1.status_code == 200

    # Second accept fails
    res2 = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"})
    assert res2.status_code == 400
    assert res2.get_json()["error"] == "QUOTE_ALREADY_ACCEPTED"


def test_accept_quote_ownership_mismatch(client):
    """Test accepting someone else's quote fails."""
    quote_res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 5000,
    })
    quote_id = quote_res.get_json()["quote_id"]

    # Bob (user_2) tries to accept Alice's quote
    res = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_2"})
    assert res.status_code == 400
    assert res.get_json()["error"] == "QUOTE_OWNERSHIP_MISMATCH"


# =========================================================================
# 4. P2P Transfer Tests
# =========================================================================

def test_transfer_success(client):
    """Test peer-to-peer transfer between Alice and Bob."""
    # Alice (user_1) transfers 5000 USD to Bob (user_2)
    payload = {
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 5000,
    }
    res = client.post("/transfers", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["from_user_id"] == "user_1"
    assert data["to_user_id"] == "user_2"
    assert data["currency"] == "USD"
    assert data["amount"] == 5000
    assert data["from_user_balance"] == 95000  # 100000 - 5000

    # Verify Bob's updated balance: 25000 + 5000 = 30000 USD
    bob_bal = client.get("/users/user_2/balances").get_json()
    assert bob_bal["balances"]["USD"] == 30000


def test_transfer_insufficient_funds(client):
    """Test transfer fails if sender lacks sufficient funds."""
    payload = {
        "from_user_id": "user_2",  # Bob only has 25000 USD
        "to_user_id": "user_1",
        "currency": "USD",
        "amount": 50000,
    }
    res = client.post("/transfers", json=payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "INSUFFICIENT_FUNDS"


def test_transfer_self_transfer_rejected(client):
    """Test self-transfer returns 400 SELF_TRANSFER_NOT_ALLOWED."""
    payload = {
        "from_user_id": "user_1",
        "to_user_id": "user_1",
        "currency": "USD",
        "amount": 1000,
    }
    res = client.post("/transfers", json=payload)
    assert res.status_code == 400
    assert res.get_json()["error"] == "SELF_TRANSFER_NOT_ALLOWED"


def test_transfer_unknown_recipient(client):
    """Test transfer to non-existent user returns 404."""
    payload = {
        "from_user_id": "user_1",
        "to_user_id": "nonexistent_recipient",
        "currency": "USD",
        "amount": 1000,
    }
    res = client.post("/transfers", json=payload)
    assert res.status_code == 404
    assert res.get_json()["error"] == "USER_NOT_FOUND"


# =========================================================================
# 5. Transaction Ledger Tests
# =========================================================================

def test_transaction_ledger(client):
    """Test that conversions and transfers reflect accurately in user transaction history."""
    # 1. Execute a transfer: Alice -> Bob 5000 USD
    client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 5000,
    })

    # 2. Execute a conversion for Alice: 10000 USD -> EUR
    q_res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    })
    q_id = q_res.get_json()["quote_id"]
    client.post(f"/quotes/{q_id}/accept", json={"user_id": "user_1"})

    # 3. Check Alice's ledger
    alice_txs = client.get("/users/user_1/transactions").get_json()["transactions"]
    assert len(alice_txs) == 2
    # Newest first: conversion is first, then transfer sent
    assert alice_txs[0]["type"] == "CONVERSION"
    assert alice_txs[0]["from_amount"] == 10000
    assert alice_txs[0]["to_amount"] == 9154
    assert alice_txs[0]["fee_amount"] == 46

    assert alice_txs[1]["type"] == "TRANSFER_SENT"
    assert alice_txs[1]["amount"] == 5000
    assert alice_txs[1]["related_user_id"] == "user_2"

    # 4. Check Bob's ledger
    bob_txs = client.get("/users/user_2/transactions").get_json()["transactions"]
    assert len(bob_txs) == 1
    assert bob_txs[0]["type"] == "TRANSFER_RECEIVED"
    assert bob_txs[0]["amount"] == 5000
    assert bob_txs[0]["related_user_id"] == "user_1"


# =========================================================================
# 6. Write-Ahead Log (WAL) & Transit Pools Verification
# =========================================================================

def test_transit_pools_on_transfer(client):
    """Test transit clearing pools return to zero drift after P2P transfer."""
    res = client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 5000,
    })
    assert res.status_code == 200

    # Verify zero-drift: system transit pools are completely settled (all 0)
    pools = user_wallet_adapter.get_transit_pool_balances()
    assert pools["outbound"]["USD"] == 0
    assert pools["inbound"]["USD"] == 0


def test_transit_pools_on_conversion(client):
    """Test transit clearing pools return to zero drift and fee pool captured fees on quote conversion."""
    q_res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    })
    quote_id = q_res.get_json()["quote_id"]
    accept_res = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"})
    assert accept_res.status_code == 200

    # Verify transit clearing pools are empty and fee pool captured 46 EUR
    pools = user_wallet_adapter.get_transit_pool_balances()
    assert pools["outbound"]["USD"] == 0
    assert pools["inbound"]["EUR"] == 0
    assert pools["fees"]["EUR"] == 46
