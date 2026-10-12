"""Tests for the greeting API and full stack multi-currency wallet application."""

from datetime import datetime, timedelta
from decimal import Decimal
import threading

import pytest

from app.adapter.db import db
from app.adapter.entities import GreetingRecordEntity
from app.adapter.greeting_adapter import GreetingAdapter
from app.manager.entities import (
    AcceptQuoteRequestEntity,
    GreetingRequestEntity,
    GreetingResponseEntity,
    QuoteRequestEntity,
    TransferRequestEntity,
)
from app.manager.greeting_manager import GreetingManager
from app.manager.wallet_manager import wallet_manager
from app.utils.exceptions import StepExecutionError


# ---------------------------------------------------------
# Template Greeting Tests (Regression Protection)
# ---------------------------------------------------------


def test_health(client):
    """Test health check returns status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_hello_default_salutation(client):
    """Test greeting with default salutation."""
    res = client.post("/hello", json={"name": "John Doe"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["id"] == 1
    assert data["message"] == "Hello, John Doe!"
    assert data["salutation"] == "Hello"
    assert data["name"] == "John Doe"


def test_hello_custom_salutation(client):
    """Test greeting with custom query parameter salutation."""
    res = client.post("/hello?salutation=Welcome", json={"name": "Jane Smith"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["message"] == "Welcome, Jane Smith!"
    assert data["salutation"] == "Welcome"
    assert data["name"] == "Jane Smith"


def test_hello_with_full_name_field(client):
    """Test greeting when body provides 'full_name' instead of 'name'."""
    res = client.post("/hello?salutation=Good morning", json={"full_name": "Alice Wonderland"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["message"] == "Good morning, Alice Wonderland!"
    assert data["name"] == "Alice Wonderland"


def test_hello_missing_name_in_body(client):
    """Test validation fails when name is missing in body."""
    res = client.post("/hello", json={})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_hello_invalid_type_in_body(client):
    """Test validation fails when name is not a string."""
    res = client.post("/hello", json={"name": 12345})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_hello_empty_string_name(client):
    """Test validation fails when name is an empty string."""
    res = client.post("/hello", json={"name": ""})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_hello_extra_fields_rejected(client):
    """Test validation rejects unexpected additional properties."""
    res = client.post("/hello", json={"name": "John Doe", "age": 30})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_hello_malformed_json(client):
    """Test malformed JSON payload returns 400."""
    res = client.post("/hello", data="{not json", content_type="application/json")
    assert res.status_code == 400
    data = res.get_json()
    assert "valid JSON" in data["error"]


def test_layer_entity_flow():
    """Unit test verifying Service -> Manager -> Adapter flow using single functions and contracts."""
    test_adapter = GreetingAdapter()
    test_manager = GreetingManager(adapter=test_adapter)

    request_entity = GreetingRequestEntity(name="Charlie", salutation="Greetings")
    response_entity = test_manager.greet(request_entity)

    assert isinstance(response_entity, GreetingResponseEntity)
    assert response_entity.id == 1
    assert response_entity.message == "Greetings, Charlie!"

    assert len(test_adapter.storage) == 1
    record = test_adapter.storage[0]
    assert isinstance(record, GreetingRecordEntity)
    assert record.id == response_entity.id
    assert record.name == response_entity.name
    assert record.message == response_entity.message


# ---------------------------------------------------------
# Full Stack Multi-Currency Wallet Tests
# ---------------------------------------------------------


def test_get_rates(client):
    """GET /api/v1/rates returns 200 with exchange rates list."""
    res = client.get("/api/v1/rates")
    assert res.status_code == 200
    data = res.get_json()
    assert "rates" in data
    rates = data["rates"]
    assert len(rates) > 0
    usd_eur = next((r for r in rates if r["from_currency"] == "USD" and r["to_currency"] == "EUR"), None)
    assert usd_eur is not None
    assert usd_eur["rate"] == 0.92


def test_get_users(client):
    """GET /api/v1/users returns 200 with seed users list."""
    res = client.get("/api/v1/users")
    assert res.status_code == 200
    data = res.get_json()
    assert "users" in data
    user_ids = [u["id"] for u in data["users"]]
    assert "usr_alice" in user_ids
    assert "usr_bob" in user_ids
    assert "usr_charlie" in user_ids


def test_get_user_balances(client):
    """GET /api/v1/users/<user_id>/balances returns multi-currency balances."""
    res = client.get("/api/v1/users/usr_alice/balances")
    assert res.status_code == 200
    data = res.get_json()
    assert data["user_id"] == "usr_alice"
    assert data["balances"]["USD"] == 1000.0
    assert data["balances"]["EUR"] == 500.0


def test_get_user_balances_not_found(client):
    """GET /api/v1/users/<user_id>/balances returns 404 for non-existent user."""
    res = client.get("/api/v1/users/usr_unknown/balances")
    assert res.status_code == 404
    assert res.get_json()["error"] == "Not found"


def test_create_quote_success(client):
    """POST /api/v1/quotes creates a valid 30s quote with 0.5% fee."""
    payload = {
        "user_id": "usr_alice",
        "from_currency": "USD",
        "to_currency": "EUR",
        "amount": 100.0,
    }
    res = client.post("/api/v1/quotes", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["user_id"] == "usr_alice"
    assert data["from_currency"] == "USD"
    assert data["to_currency"] == "EUR"
    assert data["from_amount"] == 100.0
    # Rate: 0.92 -> Base = 92.00, Fee (0.5%) = 0.46, Net Payout = 91.54
    assert data["exchange_rate"] == 0.92
    assert data["fee_rate"] == 0.005
    assert data["fee_amount"] == 0.46
    assert data["to_amount"] == 91.54
    assert data["status"] == "PENDING"
    assert "quote_id" in data
    assert "expires_at" in data


def test_create_quote_validation_errors(client):
    """POST /api/v1/quotes rejects invalid input payloads."""
    # Missing fields
    res = client.post("/api/v1/quotes", json={"user_id": "usr_alice"})
    assert res.status_code == 400

    # Negative amount
    res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "amount": -10},
    )
    assert res.status_code == 400

    # Same currency conversion
    res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "USD", "amount": 100},
    )
    assert res.status_code == 400


def test_create_quote_unknown_user_or_currency(client):
    """POST /api/v1/quotes returns 404 when user or rate pair does not exist."""
    # Unknown user
    res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_ghost", "from_currency": "USD", "to_currency": "EUR", "amount": 100},
    )
    assert res.status_code == 404

    # Unsupported currency pair
    res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "CAD", "amount": 100},
    )
    assert res.status_code == 404


def test_accept_quote_and_multi_step_execution(client):
    """POST /api/v1/quotes/<quote_id>/accept executes 3-step conversion and updates balances."""
    # 1. Create quote
    q_res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "amount": 100.0},
    )
    quote_id = q_res.get_json()["quote_id"]

    # 2. Accept quote
    accept_res = client.post(f"/api/v1/quotes/{quote_id}/accept", json={"user_id": "usr_alice"})
    assert accept_res.status_code == 200
    data = accept_res.get_json()
    assert data["status"] == "COMPLETED"
    assert data["from_amount"] == 100.0
    assert data["to_amount"] == 91.54
    assert data["fee_amount"] == 0.46

    # 3. Verify all 3 discrete movement steps were recorded
    steps = data["steps"]
    assert len(steps) == 3
    # Step 1: User A USD -> FX USD Pool (100.0)
    assert steps[0]["from_account_id"] == "user:usr_alice:USD"
    assert steps[0]["to_account_id"] == "system:fx_pool:USD"
    assert steps[0]["currency"] == "USD"
    assert steps[0]["amount"] == 100.0
    assert steps[0]["status"] == "COMPLETED"
    # Step 2: FX EUR Pool -> Fee EUR Pool (0.46)
    assert steps[1]["from_account_id"] == "system:fx_pool:EUR"
    assert steps[1]["to_account_id"] == "system:fee_pool:EUR"
    assert steps[1]["currency"] == "EUR"
    assert steps[1]["amount"] == 0.46
    assert steps[1]["status"] == "COMPLETED"
    # Step 3: FX EUR Pool -> User A EUR (91.54)
    assert steps[2]["from_account_id"] == "system:fx_pool:EUR"
    assert steps[2]["to_account_id"] == "user:usr_alice:EUR"
    assert steps[2]["currency"] == "EUR"
    assert steps[2]["amount"] == 91.54
    assert steps[2]["status"] == "COMPLETED"

    # 4. Verify user balances
    b_res = client.get("/api/v1/users/usr_alice/balances")
    balances = b_res.get_json()["balances"]
    assert balances["USD"] == 900.0       # 1000 - 100
    assert balances["EUR"] == 591.54      # 500 + 91.54


def test_accept_quote_expired(client):
    """POST /api/v1/quotes/<quote_id>/accept rejects expired quotes with 422."""
    q_res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "amount": 50.0},
    )
    quote_id = q_res.get_json()["quote_id"]

    # Fast forward quote expiration
    db.quotes[quote_id].expires_at = datetime.utcnow() - timedelta(seconds=1)

    accept_res = client.post(f"/api/v1/quotes/{quote_id}/accept", json={"user_id": "usr_alice"})
    assert accept_res.status_code == 422
    assert "expired" in accept_res.get_json()["message"]


def test_accept_quote_already_executed(client):
    """POST /api/v1/quotes/<quote_id>/accept rejects double acceptance with 422."""
    q_res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "amount": 50.0},
    )
    quote_id = q_res.get_json()["quote_id"]

    # First accept succeeds
    res1 = client.post(f"/api/v1/quotes/{quote_id}/accept", json={"user_id": "usr_alice"})
    assert res1.status_code == 200

    # Second accept fails
    res2 = client.post(f"/api/v1/quotes/{quote_id}/accept", json={"user_id": "usr_alice"})
    assert res2.status_code == 422
    assert "already been accepted" in res2.get_json()["message"]


def test_accept_quote_insufficient_balance(client):
    """POST /api/v1/quotes/<quote_id>/accept fails with 422 when balance is insufficient."""
    # Alice has 1000 USD; ask for 5000 USD
    q_res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "amount": 5000.0},
    )
    quote_id = q_res.get_json()["quote_id"]

    res = client.post(f"/api/v1/quotes/{quote_id}/accept", json={"user_id": "usr_alice"})
    assert res.status_code == 422
    assert "Insufficient funds" in res.get_json()["message"]


def test_transfer_p2p_success(client):
    """POST /api/v1/transfers executes 3-step P2P transfer and updates sender/recipient balances."""
    payload = {
        "sender_id": "usr_alice",
        "recipient_id": "usr_bob",
        "currency": "EUR",
        "amount": 100.0,
        "note": "Dinner split",
    }
    res = client.post("/api/v1/transfers", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["status"] == "COMPLETED"
    assert data["sender_id"] == "usr_alice"
    assert data["recipient_id"] == "usr_bob"
    assert data["amount"] == 100.0
    assert data["currency"] == "EUR"

    # Verify 3 discrete movement steps
    steps = data["steps"]
    assert len(steps) == 3
    # Step 1: Alice EUR -> Outbound Pool EUR
    assert steps[0]["from_account_id"] == "user:usr_alice:EUR"
    assert steps[0]["to_account_id"] == "system:outbound_pool:EUR"
    assert steps[0]["amount"] == 100.0
    assert steps[0]["status"] == "COMPLETED"
    # Step 2: Outbound Pool EUR -> Inbound Pool EUR
    assert steps[1]["from_account_id"] == "system:outbound_pool:EUR"
    assert steps[1]["to_account_id"] == "system:inbound_pool:EUR"
    assert steps[1]["amount"] == 100.0
    assert steps[1]["status"] == "COMPLETED"
    # Step 3: Inbound Pool EUR -> Bob EUR
    assert steps[2]["from_account_id"] == "system:inbound_pool:EUR"
    assert steps[2]["to_account_id"] == "user:usr_bob:EUR"
    assert steps[2]["amount"] == 100.0
    assert steps[2]["status"] == "COMPLETED"

    # Verify balances: Alice had 500 -> 400; Bob had 750 -> 850
    alice_b = client.get("/api/v1/users/usr_alice/balances").get_json()["balances"]
    bob_b = client.get("/api/v1/users/usr_bob/balances").get_json()["balances"]
    assert alice_b["EUR"] == 400.0
    assert bob_b["EUR"] == 850.0


def test_transfer_insufficient_balance(client):
    """POST /api/v1/transfers fails with 422 if sender has insufficient funds."""
    payload = {
        "sender_id": "usr_alice",
        "recipient_id": "usr_bob",
        "currency": "EUR",
        "amount": 9999.0,
    }
    res = client.post("/api/v1/transfers", json=payload)
    assert res.status_code == 422
    assert "Insufficient funds" in res.get_json()["message"]


def test_transfer_to_self_error(client):
    """POST /api/v1/transfers fails with 400 if sender is recipient."""
    payload = {
        "sender_id": "usr_alice",
        "recipient_id": "usr_alice",
        "currency": "EUR",
        "amount": 10.0,
    }
    res = client.post("/api/v1/transfers", json=payload)
    assert res.status_code == 400
    assert "cannot be the same user" in res.get_json()["message"]


def test_transfer_unknown_user(client):
    """POST /api/v1/transfers fails with 404 if sender or recipient does not exist."""
    payload = {
        "sender_id": "usr_alice",
        "recipient_id": "usr_nonexistent",
        "currency": "EUR",
        "amount": 10.0,
    }
    res = client.post("/api/v1/transfers", json=payload)
    assert res.status_code == 404


def test_idempotency_for_transfer(client):
    """POST /api/v1/transfers returns identical response without repeated deductions on replay."""
    payload = {
        "sender_id": "usr_alice",
        "recipient_id": "usr_bob",
        "currency": "USD",
        "amount": 50.0,
    }
    idem_key = "transfer-key-12345"

    # 1. Initial request
    res1 = client.post("/api/v1/transfers", json=payload, headers={"Idempotency-Key": idem_key})
    assert res1.status_code == 201
    data1 = res1.get_json()

    # Verify Alice USD balance dropped by 50 (1000 -> 950)
    assert client.get("/api/v1/users/usr_alice/balances").get_json()["balances"]["USD"] == 950.0

    # 2. Replay with identical key & payload
    res2 = client.post("/api/v1/transfers", json=payload, headers={"Idempotency-Key": idem_key})
    assert res2.status_code == 201
    data2 = res2.get_json()
    assert data2["transfer_id"] == data1["transfer_id"]

    # Verify balance was NOT deducted a second time
    assert client.get("/api/v1/users/usr_alice/balances").get_json()["balances"]["USD"] == 950.0

    # 3. Replay with same key but different payload returns 409 Conflict
    conflicting_payload = {
        "sender_id": "usr_alice",
        "recipient_id": "usr_bob",
        "currency": "USD",
        "amount": 99.0,  # Changed amount
    }
    res3 = client.post("/api/v1/transfers", json=conflicting_payload, headers={"Idempotency-Key": idem_key})
    assert res3.status_code == 409


def test_idempotency_for_accept_quote(client):
    """POST /api/v1/quotes/<id>/accept returns identical cached response on replay."""
    q_res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "amount": 100.0},
    )
    quote_id = q_res.get_json()["quote_id"]

    idem_key = "quote-accept-key-999"

    # 1. First accept
    res1 = client.post(
        f"/api/v1/quotes/{quote_id}/accept",
        json={"user_id": "usr_alice"},
        headers={"Idempotency-Key": idem_key},
    )
    assert res1.status_code == 200
    data1 = res1.get_json()

    # 2. Replay with same key
    res2 = client.post(
        f"/api/v1/quotes/{quote_id}/accept",
        json={"user_id": "usr_alice"},
        headers={"Idempotency-Key": idem_key},
    )
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert data2["transaction_id"] == data1["transaction_id"]

    # Alice balance: only one conversion deducted
    assert client.get("/api/v1/users/usr_alice/balances").get_json()["balances"]["USD"] == 900.0


def test_get_user_transactions(client):
    """GET /api/v1/users/<user_id>/transactions returns chronological transaction history."""
    # Execute a transfer
    client.post(
        "/api/v1/transfers",
        json={"sender_id": "usr_alice", "recipient_id": "usr_bob", "currency": "USD", "amount": 25.0},
    )

    res = client.get("/api/v1/users/usr_alice/transactions")
    assert res.status_code == 200
    data = res.get_json()
    assert data["user_id"] == "usr_alice"
    assert data["total"] >= 1
    txns = data["transactions"]
    assert txns[0]["type"] == "TRANSFER"
    assert txns[0]["status"] == "COMPLETED"
    assert len(txns[0]["steps"]) == 3


def test_multi_step_rollback_on_midway_failure(client):
    """Verify that if a multi-step transaction fails midway, all prior steps are reversed."""
    # Capture initial balances
    alice_initial_usd = db.accounts["user:usr_alice:USD"].balance
    outbound_initial = db.accounts["system:outbound_pool:USD"].balance

    # Attempt a transfer with simulated failure at Step 2
    req = TransferRequestEntity(
        sender_id="usr_alice",
        recipient_id="usr_bob",
        currency="USD",
        amount=100.0,
    )

    with pytest.raises(StepExecutionError):
        wallet_manager.transfer_money(req, simulate_failure_at_step=2)

    # Step 1 should have been executed then REVERSED
    # Verify balances were completely restored to initial values!
    assert db.accounts["user:usr_alice:USD"].balance == alice_initial_usd
    assert db.accounts["system:outbound_pool:USD"].balance == outbound_initial


def test_fine_grained_concurrency_locking(client):
    """Verify concurrent transactions execute safely without race conditions."""
    errors = []

    def run_alice_transfer():
        try:
            req = TransferRequestEntity(
                sender_id="usr_alice",
                recipient_id="usr_bob",
                currency="EUR",
                amount=10.0,
            )
            wallet_manager.transfer_money(req)
        except Exception as e:
            errors.append(e)

    def run_charlie_transfer():
        try:
            req = TransferRequestEntity(
                sender_id="usr_charlie",
                recipient_id="usr_alice",
                currency="USD",
                amount=15.0,
            )
            wallet_manager.transfer_money(req)
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=run_alice_transfer),
        threading.Thread(target=run_charlie_transfer),
        threading.Thread(target=run_alice_transfer),
        threading.Thread(target=run_charlie_transfer),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    # Alice EUR should be 500 - 20 = 480
    assert db.accounts["user:usr_alice:EUR"].balance == Decimal("480.00")
    # Alice USD should be 1000 + 30 = 1030
    assert db.accounts["user:usr_alice:USD"].balance == Decimal("1030.00")
