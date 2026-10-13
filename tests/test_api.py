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
from app.service.api import app
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
    """Verify that if a multi-step transaction fails midway, compensating step events are created in reverse order."""
    # Capture initial balances
    alice_initial_usd = db.accounts["user:usr_alice:USD"].balance
    outbound_initial = db.accounts["system:outbound_pool:USD"].balance
    initial_step_count = len(db.movement_steps)

    # Attempt a transfer with simulated failure at Step 2
    req = TransferRequestEntity(
        sender_id="usr_alice",
        recipient_id="usr_bob",
        currency="USD",
        amount=100.0,
    )

    with pytest.raises(StepExecutionError):
        wallet_manager.transfer_money(req, simulate_failure_at_step=2)

    # Balances were completely restored to initial values
    assert db.accounts["user:usr_alice:USD"].balance == alice_initial_usd
    assert db.accounts["system:outbound_pool:USD"].balance == outbound_initial

    # Find the reversed transaction
    reversed_txns = [t for t in db.transactions.values() if t.status == "REVERSED" and t.type == "TRANSFER"]
    assert len(reversed_txns) >= 1
    txn = reversed_txns[-1]

    # Exactly 2 step events recorded: 1 forward step + 1 compensating step event
    assert len(txn.steps) == 2
    forward_step = txn.steps[0]
    comp_step = txn.steps[1]

    # Forward step 1: Alice -> Outbound Pool (COMPLETED)
    assert forward_step.from_account_id == "user:usr_alice:USD"
    assert forward_step.to_account_id == "system:outbound_pool:USD"
    assert forward_step.amount == Decimal("100.00")
    assert forward_step.status == "COMPLETED"
    assert forward_step.is_compensating is False

    # Compensating step event: Outbound Pool -> Alice (COMPENSATING)
    assert comp_step.from_account_id == "system:outbound_pool:USD"
    assert comp_step.to_account_id == "user:usr_alice:USD"
    assert comp_step.amount == Decimal("100.00")
    assert comp_step.status == "COMPENSATING"
    assert comp_step.is_compensating is True

    # Both events persisted to global movement steps ledger
    assert forward_step.step_id in db.movement_steps
    assert comp_step.step_id in db.movement_steps
    assert len(db.movement_steps) == initial_step_count + 2


def test_multi_step_rollback_reverse_order_events(client):
    """Verify that quote conversion failure at Step 3 creates compensating events for Step 2 then Step 1 in reverse order."""
    alice_initial_usd = db.accounts["user:usr_alice:USD"].balance
    alice_initial_eur = db.accounts["user:usr_alice:EUR"].balance
    fee_initial_eur = db.accounts["system:fee_pool:EUR"].balance
    fx_initial_usd = db.accounts["system:fx_pool:USD"].balance
    fx_initial_eur = db.accounts["system:fx_pool:EUR"].balance

    # 1. Create a quote: Alice converts 100 USD to EUR
    q_res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "amount": 100.0},
    )
    assert q_res.status_code == 201
    quote_id = q_res.get_json()["quote_id"]

    # 2. Accept quote with simulated failure at Step 3 (Step 1 and Step 2 succeed, Step 3 fails)
    accept_res = client.post(
        f"/api/v1/quotes/{quote_id}/accept",
        json={"user_id": "usr_alice"},
        headers={"X-Simulate-Failure-At-Step": "3"},
    )
    assert accept_res.status_code == 500

    # 3. Verify all account balances are restored to net zero change
    assert db.accounts["user:usr_alice:USD"].balance == alice_initial_usd
    assert db.accounts["user:usr_alice:EUR"].balance == alice_initial_eur
    assert db.accounts["system:fee_pool:EUR"].balance == fee_initial_eur
    assert db.accounts["system:fx_pool:USD"].balance == fx_initial_usd
    assert db.accounts["system:fx_pool:EUR"].balance == fx_initial_eur

    # 4. Inspect the recorded reversed transaction
    reversed_txns = [t for t in db.transactions.values() if t.status == "REVERSED" and t.type == "CONVERSION"]
    assert len(reversed_txns) >= 1
    txn = reversed_txns[-1]

    # Must contain 4 steps: 2 forward steps + 2 compensating steps in reverse order
    assert len(txn.steps) == 4
    f_step1, f_step2, c_step2, c_step1 = txn.steps

    # Forward Step 1: Alice USD -> FX Pool USD
    assert f_step1.from_account_id == "user:usr_alice:USD"
    assert f_step1.to_account_id == "system:fx_pool:USD"
    assert f_step1.status == "COMPLETED"
    assert f_step1.is_compensating is False

    # Forward Step 2: FX Pool EUR -> Fee Pool EUR
    assert f_step2.from_account_id == "system:fx_pool:EUR"
    assert f_step2.to_account_id == "system:fee_pool:EUR"
    assert f_step2.status == "COMPLETED"
    assert f_step2.is_compensating is False

    # Compensating Step 1 (reverses Step 2 first): Fee Pool EUR -> FX Pool EUR
    assert c_step2.from_account_id == "system:fee_pool:EUR"
    assert c_step2.to_account_id == "system:fx_pool:EUR"
    assert c_step2.status == "COMPENSATING"
    assert c_step2.is_compensating is True
    assert c_step2.amount == f_step2.amount

    # Compensating Step 2 (reverses Step 1 second): FX Pool USD -> Alice USD
    assert c_step1.from_account_id == "system:fx_pool:USD"
    assert c_step1.to_account_id == "user:usr_alice:USD"
    assert c_step1.status == "COMPENSATING"
    assert c_step1.is_compensating is True
    assert c_step1.amount == f_step1.amount


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


# ---------------------------------------------------------
# Concurrency Correctness E2E Tests
# ---------------------------------------------------------


def test_concurrent_competing_transfers_overdraft_prevention(client):
    """E2E Test 1: Competing transfers attempting to overdraw Alice must not both succeed."""
    # Alice has 500 EUR initially; set balance to exactly 100 EUR
    db.accounts["user:usr_alice:EUR"].balance = Decimal("100.00")

    results = []

    def make_transfer(recipient_id):
        thread_client = app.test_client()
        payload = {
            "sender_id": "usr_alice",
            "recipient_id": recipient_id,
            "currency": "EUR",
            "amount": 80.0,
        }
        res = thread_client.post("/api/v1/transfers", json=payload)
        results.append(res.status_code)

    t1 = threading.Thread(target=make_transfer, args=("usr_bob",))
    t2 = threading.Thread(target=make_transfer, args=("usr_charlie",))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one succeeded (201) and one failed (422)
    assert sorted(results) == [201, 422]
    # Balance must remain exactly 100 - 80 = 20 EUR
    assert db.accounts["user:usr_alice:EUR"].balance == Decimal("20.00")


def test_concurrent_quote_double_acceptance(client):
    """E2E Test 2: Concurrent requests accepting the same quote cannot double-convert."""
    q_res = client.post(
        "/api/v1/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "amount": 100.0},
    )
    quote_id = q_res.get_json()["quote_id"]

    results = []

    def accept():
        thread_client = app.test_client()
        res = thread_client.post(f"/api/v1/quotes/{quote_id}/accept", json={"user_id": "usr_alice"})
        results.append(res.status_code)

    t1 = threading.Thread(target=accept)
    t2 = threading.Thread(target=accept)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one must succeed (200) and one must be rejected (422 Quote already accepted)
    assert sorted(results) == [200, 422]
    # Alice USD balance deducted exactly once: 1000 - 100 = 900 USD
    assert db.accounts["user:usr_alice:USD"].balance == Decimal("900.00")


def test_concurrent_simultaneous_duplicate_idempotency_keys(client):
    """E2E Test 3: Multiple concurrent requests with the identical Idempotency-Key execute once."""
    idem_key = "concurrent-idem-key-777"
    payload = {
        "sender_id": "usr_alice",
        "recipient_id": "usr_bob",
        "currency": "EUR",
        "amount": 50.0,
    }
    results = []
    transfer_ids = []

    def send_transfer():
        thread_client = app.test_client()
        res = thread_client.post("/api/v1/transfers", json=payload, headers={"Idempotency-Key": idem_key})
        results.append(res.status_code)
        if res.status_code == 201:
            transfer_ids.append(res.get_json()["transfer_id"])

    threads = [threading.Thread(target=send_transfer) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 5 requests returned 201 with the exact same transfer_id
    assert results == [201, 201, 201, 201, 201]
    assert len(set(transfer_ids)) == 1

    # Alice EUR balance deducted only once: 500 - 50 = 450 EUR
    assert db.accounts["user:usr_alice:EUR"].balance == Decimal("450.00")


def test_concurrent_bidirectional_transfers_deadlock_freedom(client):
    """E2E Test 4: Mutual concurrent transfers between counterparties never deadlock."""
    # Alice has 500 EUR, Bob has 750 EUR
    errors = []

    def alice_to_bob():
        thread_client = app.test_client()
        res = thread_client.post(
            "/api/v1/transfers",
            json={"sender_id": "usr_alice", "recipient_id": "usr_bob", "currency": "EUR", "amount": 10.0},
        )
        if res.status_code != 201:
            errors.append(res.get_json())

    def bob_to_alice():
        thread_client = app.test_client()
        res = thread_client.post(
            "/api/v1/transfers",
            json={"sender_id": "usr_bob", "recipient_id": "usr_alice", "currency": "EUR", "amount": 10.0},
        )
        if res.status_code != 201:
            errors.append(res.get_json())

    threads = []
    for _ in range(10):
        threads.append(threading.Thread(target=alice_to_bob))
        threads.append(threading.Thread(target=bob_to_alice))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    # 10 transfers each way net out to 0 balance change
    assert db.accounts["user:usr_alice:EUR"].balance == Decimal("500.00")
    assert db.accounts["user:usr_bob:EUR"].balance == Decimal("750.00")


def test_concurrent_fan_in_transfers(client):
    """E2E Test 5: Multiple concurrent senders transferring to the same recipient."""
    statuses = []

    def alice_sends():
        thread_client = app.test_client()
        res = thread_client.post(
            "/api/v1/transfers",
            json={"sender_id": "usr_alice", "recipient_id": "usr_charlie", "currency": "USD", "amount": 10.0},
        )
        statuses.append(res.status_code)

    def bob_sends():
        thread_client = app.test_client()
        res = thread_client.post(
            "/api/v1/transfers",
            json={"sender_id": "usr_bob", "recipient_id": "usr_charlie", "currency": "GBP", "amount": 5.0},
        )
        statuses.append(res.status_code)

    threads = []
    for _ in range(5):
        threads.append(threading.Thread(target=alice_sends))
        threads.append(threading.Thread(target=bob_sends))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(s == 201 for s in statuses)
    # Charlie USD: initial 300 + (5 * 10) = 350
    assert db.accounts["user:usr_charlie:USD"].balance == Decimal("350.00")
    # Charlie GBP: initial 0 + (5 * 5) = 25
    assert db.accounts["user:usr_charlie:GBP"].balance == Decimal("25.00")


def test_concurrent_multi_step_failure_rollback_under_load(client):
    """E2E Test 6: In-flight step failure rollback executes cleanly while concurrent transfers run."""
    statuses = []

    def failing_transfer():
        thread_client = app.test_client()
        # Uses Approach 1 header hook to trigger rollback at Step 2
        res = thread_client.post(
            "/api/v1/transfers",
            json={"sender_id": "usr_alice", "recipient_id": "usr_bob", "currency": "EUR", "amount": 50.0},
            headers={"X-Simulate-Failure-At-Step": "2"},
        )
        statuses.append(("failing", res.status_code))

    def successful_transfer():
        thread_client = app.test_client()
        # Charlie sends 20 USD to Alice concurrently
        res = thread_client.post(
            "/api/v1/transfers",
            json={"sender_id": "usr_charlie", "recipient_id": "usr_alice", "currency": "USD", "amount": 20.0},
        )
        statuses.append(("successful", res.status_code))

    t1 = threading.Thread(target=failing_transfer)
    t2 = threading.Thread(target=successful_transfer)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    status_dict = dict(statuses)
    # Failing transfer returned 500
    assert status_dict["failing"] == 500
    # Successful transfer returned 201
    assert status_dict["successful"] == 201

    # Alice EUR must be completely restored by rollback to initial 500.00 EUR
    assert db.accounts["user:usr_alice:EUR"].balance == Decimal("500.00")
    # Clearing pool must be clean
    assert db.accounts["system:outbound_pool:EUR"].balance == Decimal("0.00")
    # Successful transfer was properly credited to Alice USD: 1000 + 20 = 1020 USD
    assert db.accounts["user:usr_alice:USD"].balance == Decimal("1020.00")


