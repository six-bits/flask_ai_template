import concurrent.futures
import json
import pytest

from app.adapter.quote_adapter import quote_adapter


def test_get_rates_api(client):
    res = client.get("/rates")
    assert res.status_code == 200
    data = res.get_json()
    assert "rates" in data
    assert data["rates"]["USD/EUR"] == 0.92
    assert data["fee_percentage"] == 0.01


def test_get_user_balances_api_success(client):
    res = client.get("/users/usr_alice/balances")
    assert res.status_code == 200
    data = res.get_json()
    assert data["user_id"] == "usr_alice"
    assert data["balances"]["USD"] == 100000
    assert data["balances"]["EUR"] == 50000
    assert data["balances"]["GBP"] == 20000


def test_get_user_balances_api_not_found(client):
    res = client.get("/users/usr_does_not_exist/balances")
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"


def test_create_quote_api_success(client):
    payload = {
        "user_id": "usr_alice",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    }
    res = client.post("/quotes", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["quote_id"].startswith("qt_")
    assert data["user_id"] == "usr_alice"
    assert data["from_amount"] == 10000
    assert data["exchange_rate"] == 0.92
    assert data["gross_to_amount"] == 9200
    assert data["fee_amount"] == 92
    assert data["net_to_amount"] == 9108
    assert data["validity_seconds"] == 30
    assert "expires_at" in data


def test_create_quote_api_float_amount_rejected(client):
    """Monetary amounts must be minor units as integer/long, rejecting floats."""
    payload = {
        "user_id": "usr_alice",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10.50,  # Float rejected
    }
    res = client.post("/quotes", json=payload)
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_create_quote_api_invalid_currency_pair(client):
    payload = {
        "user_id": "usr_alice",
        "from_currency": "USD",
        "to_currency": "ZZZ",
        "from_amount": 10000,
    }
    res = client.post("/quotes", json=payload)
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"


def test_accept_quote_api_success(client):
    # 1. Create quote
    q_res = client.post(
        "/quotes",
        json={
            "user_id": "usr_alice",
            "from_currency": "USD",
            "to_currency": "EUR",
            "from_amount": 10000,
        },
    )
    quote_id = q_res.get_json()["quote_id"]

    # 2. Accept quote using /quotes/accept schema (requires quote_id and user_id)
    accept_res = client.post(
        "/quotes/accept",
        json={"quote_id": quote_id, "user_id": "usr_alice"},
        headers={"Idempotency-Key": "accept-quote-101"},
    )
    assert accept_res.status_code == 200
    data = accept_res.get_json()
    assert data["status"] == "COMPLETED"
    assert data["debited_amount"] == 10000
    assert data["credited_amount"] == 9108
    assert data["fee_amount"] == 92

    # Check updated balances
    bal_res = client.get("/users/usr_alice/balances")
    balances = bal_res.get_json()["balances"]
    assert balances["USD"] == 90000
    assert balances["EUR"] == 59108


def test_accept_quote_api_missing_quote_id_in_schema(client):
    """Accept quote schema must accept and require quote_id."""
    res = client.post("/quotes/accept", json={"user_id": "usr_alice"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_accept_quote_api_expired(client):
    q_res = client.post(
        "/quotes",
        json={
            "user_id": "usr_alice",
            "from_currency": "USD",
            "to_currency": "EUR",
            "from_amount": 10000,
        },
    )
    quote_id = q_res.get_json()["quote_id"]

    # Artificially expire quote in repository
    record = quote_adapter.get_quote(quote_id)
    record.expires_at = "2020-01-01T00:00:00Z"

    accept_res = client.post(
        "/quotes/accept",
        json={"quote_id": quote_id, "user_id": "usr_alice"},
    )
    assert accept_res.status_code == 422
    data = accept_res.get_json()
    assert data["error"] == "Quote Expired"


def test_p2p_transfer_api_success(client):
    payload = {
        "sender_user_id": "usr_alice",
        "recipient_user_id": "usr_bob",
        "currency": "USD",
        "amount": 5000,  # $50.00
    }
    res = client.post(
        "/transfers",
        json=payload,
        headers={"Idempotency-Key": "transfer-api-201"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "COMPLETED"
    assert data["legs_executed"] == 3
    assert data["amount"] == 5000

    # Balances verification
    alice_bal = client.get("/users/usr_alice/balances").get_json()["balances"]
    bob_bal = client.get("/users/usr_bob/balances").get_json()["balances"]
    assert alice_bal["USD"] == 95000
    assert bob_bal["USD"] == 55000


def test_p2p_transfer_api_idempotency_replay(client):
    payload = {
        "sender_user_id": "usr_alice",
        "recipient_user_id": "usr_bob",
        "currency": "USD",
        "amount": 2000,
    }
    key_headers = {"Idempotency-Key": "transfer-idem-key-888"}

    res1 = client.post("/transfers", json=payload, headers=key_headers)
    assert res1.status_code == 200
    tx_id_1 = res1.get_json()["transaction_id"]

    # Replay with same key
    res2 = client.post("/transfers", json=payload, headers=key_headers)
    assert res2.status_code == 200
    tx_id_2 = res2.get_json()["transaction_id"]

    assert tx_id_1 == tx_id_2

    # Balances deducted only once
    alice_bal = client.get("/users/usr_alice/balances").get_json()["balances"]
    assert alice_bal["USD"] == 98000


def test_p2p_transfer_api_self_transfer_bad_request(client):
    payload = {
        "sender_user_id": "usr_alice",
        "recipient_user_id": "usr_alice",
        "currency": "USD",
        "amount": 1000,
    }
    res = client.post("/transfers", json=payload)
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Bad Request"


def test_p2p_transfer_api_insufficient_funds(client):
    payload = {
        "sender_user_id": "usr_alice",
        "recipient_user_id": "usr_bob",
        "currency": "USD",
        "amount": 9999999,  # Way more than Alice holds
    }
    res = client.post("/transfers", json=payload)
    assert res.status_code == 422
    data = res.get_json()
    assert data["error"] == "Transfer Failed"
    assert data["status"] == "REVERSED"


def test_get_user_transactions_api(client):
    # Perform a transfer
    client.post(
        "/transfers",
        json={
            "sender_user_id": "usr_alice",
            "recipient_user_id": "usr_bob",
            "currency": "USD",
            "amount": 1000,
        },
    )

    res = client.get("/users/usr_alice/transactions")
    assert res.status_code == 200
    data = res.get_json()
    assert data["user_id"] == "usr_alice"
    assert len(data["transactions"]) >= 1

    tx = data["transactions"][0]
    assert tx["type"] == "P2P_TRANSFER"
    assert tx["status"] == "COMPLETED"
    assert len(tx["legs"]) == 3
    # Check intermediate legs
    assert tx["legs"][0]["from_account"] == "usr_alice:USD"
    assert tx["legs"][0]["to_account"] == "pool:outbound:USD"
    assert tx["legs"][1]["from_account"] == "pool:outbound:USD"
    assert tx["legs"][1]["to_account"] == "pool:inbound:USD"
    assert tx["legs"][2]["from_account"] == "pool:inbound:USD"
    assert tx["legs"][2]["to_account"] == "usr_bob:USD"


def test_p2p_transfer_api_idempotency_payload_mismatch_bad_request(client):
    """Reusing Idempotency-Key with different payload in /transfers returns 400 Bad Request."""
    key_headers = {"Idempotency-Key": "idem-api-transfer-mismatch"}
    payload1 = {
        "sender_user_id": "usr_alice",
        "recipient_user_id": "usr_bob",
        "currency": "USD",
        "amount": 2000,
    }
    res1 = client.post("/transfers", json=payload1, headers=key_headers)
    assert res1.status_code == 200

    # Same key, altered amount
    payload2 = {
        "sender_user_id": "usr_alice",
        "recipient_user_id": "usr_bob",
        "currency": "USD",
        "amount": 5000,
    }
    res2 = client.post("/transfers", json=payload2, headers=key_headers)
    assert res2.status_code == 400
    data = res2.get_json()
    assert data["error"] == "Bad Request"
    assert "Idempotency-Key reused with different request payload" in data["message"]

    # Verify Alice balance was only debited for the first transfer (2000 minor units)
    bal_res = client.get("/users/usr_alice/balances")
    assert bal_res.get_json()["balances"]["USD"] == 98000


def test_accept_quote_api_idempotency_payload_mismatch_bad_request(client):
    """Reusing Idempotency-Key with different payload in /quotes/accept returns 400 Bad Request."""
    # Create two different quotes
    q1 = client.post(
        "/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "from_amount": 5000},
    ).get_json()["quote_id"]

    q2 = client.post(
        "/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "from_amount": 5000},
    ).get_json()["quote_id"]

    key_headers = {"Idempotency-Key": "idem-api-quote-mismatch"}

    res1 = client.post(
        "/quotes/accept",
        json={"quote_id": q1, "user_id": "usr_alice"},
        headers=key_headers,
    )
    assert res1.status_code == 200

    # Re-send with same key but different quote_id
    res2 = client.post(
        "/quotes/accept",
        json={"quote_id": q2, "user_id": "usr_alice"},
        headers=key_headers,
    )
    assert res2.status_code == 400
    data = res2.get_json()
    assert data["error"] == "Bad Request"
    assert "Idempotency-Key reused with different request payload" in data["message"]


def test_accept_quote_api_5_legs_and_concurrency_race(client):
    """
    Verify:
    1. FX conversion creates 5 currency-conserved legs.
    2. Concurrent requests to accept the same quote result in exactly 1 success and 422 for the other.
    """
    # Create quote
    q_res = client.post(
        "/quotes",
        json={"user_id": "usr_alice", "from_currency": "USD", "to_currency": "EUR", "from_amount": 10000},
    )
    assert q_res.status_code == 201
    quote_id = q_res.get_json()["quote_id"]

    results = []

    def accept_call(i):
        # We test with different idempotency keys to ensure quote locking is the gating mechanism
        return client.post(
            "/quotes/accept",
            json={"quote_id": quote_id, "user_id": "usr_alice"},
            headers={"Idempotency-Key": f"api-race-key-{i}"},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(accept_call, i) for i in range(5)]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            results.append((res.status_code, res.get_json()))

    # Exactly one request got 200 OK
    status_codes = [r[0] for r in results]
    assert status_codes.count(200) == 1
    assert status_codes.count(422) == 4

    # Verify transaction history has 5 legs
    tx_res = client.get("/users/usr_alice/transactions")
    assert tx_res.status_code == 200
    txs = tx_res.get_json()["transactions"]
    fx_tx = next(t for t in txs if t["type"] == "FX_CONVERSION")
    assert len(fx_tx["legs"]) == 5
    assert fx_tx["legs"][0]["currency"] == "USD"
    assert fx_tx["legs"][1]["currency"] == "USD"
    assert fx_tx["legs"][2]["currency"] == "EUR"
    assert fx_tx["legs"][3]["currency"] == "EUR"
    assert fx_tx["legs"][4]["currency"] == "EUR"


