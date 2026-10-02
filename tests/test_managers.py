"""Unit tests for the domain managers (UserAccountManager, QuoteManager, TransferManager)."""

import concurrent.futures
import time
from unittest.mock import patch
import pytest

from app.adapter.database import InMemoryDatabase
from app.adapter.quote_adapter import QuoteAdapter
from app.adapter.wallet_adapter import WalletAdapter
from app.exceptions import (
    IdempotencyConflictError,
    IdempotencyPayloadMismatchError,
    InvalidQuoteError,
    QuoteExpiredError,
    QuoteNotFoundError,
    RateNotFoundError,
    TransferExecutionError,
    UserNotFoundError,
    WalletError,
)
from app.manager.entities import (
    AcceptQuoteRequestEntity,
    CreateQuoteRequestEntity,
    GetRatesRequestEntity,
    GetTransactionHistoryRequestEntity,
    GetUserBalancesRequestEntity,
    P2PTransferRequestEntity,
)
from app.manager.quote_manager import QuoteManager
from app.manager.transfer_manager import TransferManager
from app.manager.user_account_manager import UserAccountManager


@pytest.fixture
def clean_db():
    db = InMemoryDatabase(seed=True)
    return db


@pytest.fixture
def managers(clean_db):
    w_adapter = WalletAdapter(db=clean_db)
    q_adapter = QuoteAdapter(db=clean_db)
    return {
        "user_mgr": UserAccountManager(wallet_adapter=w_adapter),
        "quote_mgr": QuoteManager(quote_adapter=q_adapter, wallet_adapter=w_adapter),
        "transfer_mgr": TransferManager(wallet_adapter=w_adapter),
        "wallet_adapter": w_adapter,
        "quote_adapter": q_adapter,
        "repo": w_adapter,
        "db": clean_db,
    }


# --- UserAccountManager Tests ---

def test_get_balances_success(managers):
    user_mgr = managers["user_mgr"]
    req = GetUserBalancesRequestEntity(user_id="usr_alice")
    res = user_mgr.get_balances(req)

    assert res.user_id == "usr_alice"
    assert res.balances == {"USD": 100000, "EUR": 50000, "GBP": 20000}


def test_get_balances_unknown_user(managers):
    user_mgr = managers["user_mgr"]
    req = GetUserBalancesRequestEntity(user_id="usr_nobody")
    with pytest.raises(UserNotFoundError):
        user_mgr.get_balances(req)


# --- QuoteManager Tests ---

def test_get_rates(managers):
    quote_mgr = managers["quote_mgr"]
    res = quote_mgr.get_rates(GetRatesRequestEntity())
    assert "USD/EUR" in res.rates
    assert res.fee_percentage == 0.01


def test_create_quote_success(managers):
    quote_mgr = managers["quote_mgr"]
    req = CreateQuoteRequestEntity(
        user_id="usr_alice",
        from_currency="USD",
        to_currency="EUR",
        from_amount=10000,  # $100.00
    )
    res = quote_mgr.create_quote(req)

    assert res.user_id == "usr_alice"
    assert res.from_currency == "USD"
    assert res.to_currency == "EUR"
    assert res.from_amount == 10000
    assert res.exchange_rate == 0.92
    assert res.gross_to_amount == 9200
    assert res.fee_amount == 92  # 1% of 9200
    assert res.net_to_amount == 9108  # 9200 - 92
    assert res.validity_seconds == 30


def test_create_quote_unsupported_pair(managers):
    quote_mgr = managers["quote_mgr"]
    req = CreateQuoteRequestEntity(
        user_id="usr_alice",
        from_currency="USD",
        to_currency="XYZ",
        from_amount=10000,
    )
    with pytest.raises(RateNotFoundError):
        quote_mgr.create_quote(req)


def test_accept_quote_success(managers):
    quote_mgr = managers["quote_mgr"]
    repo = managers["repo"]

    # 1. Create quote: 10000 USD -> EUR
    quote = quote_mgr.create_quote(
        CreateQuoteRequestEntity(
            user_id="usr_alice",
            from_currency="USD",
            to_currency="EUR",
            from_amount=10000,
        )
    )

    # 2. Accept quote
    accept_req = AcceptQuoteRequestEntity(
        quote_id=quote.quote_id,
        user_id="usr_alice",
    )
    res = quote_mgr.accept_quote(accept_req)

    assert res.status == "COMPLETED"
    assert res.debited_amount == 10000
    assert res.credited_amount == 9108
    assert res.fee_amount == 92

    # Check updated balances
    assert repo.get_account("usr_alice:USD").balance == 90000
    assert repo.get_account("usr_alice:EUR").balance == 59108
    assert repo.get_account("pool:fee:EUR").balance == 92


def test_accept_quote_expired(managers):
    quote_mgr = managers["quote_mgr"]

    quote = quote_mgr.create_quote(
        CreateQuoteRequestEntity(
            user_id="usr_alice",
            from_currency="USD",
            to_currency="EUR",
            from_amount=10000,
        )
    )

    # Artificially expire the quote
    record = managers["quote_adapter"].get_quote(quote.quote_id)
    record.expires_at = "2020-01-01T00:00:00Z"

    with pytest.raises(QuoteExpiredError):
        quote_mgr.accept_quote(
            AcceptQuoteRequestEntity(quote_id=quote.quote_id, user_id="usr_alice")
        )

    # Ensure status was updated to EXPIRED
    assert record.status == "EXPIRED"


def test_accept_quote_insufficient_funds_compensation(managers):
    quote_mgr = managers["quote_mgr"]
    repo = managers["repo"]

    # Quote for more USD than Alice has (Alice has 100000)
    quote = quote_mgr.create_quote(
        CreateQuoteRequestEntity(
            user_id="usr_alice",
            from_currency="USD",
            to_currency="EUR",
            from_amount=500000,
        )
    )

    with pytest.raises(TransferExecutionError):
        quote_mgr.accept_quote(
            AcceptQuoteRequestEntity(quote_id=quote.quote_id, user_id="usr_alice")
        )

    # Alice balance must remain intact
    assert repo.get_account("usr_alice:USD").balance == 100000
    assert repo.get_account("pool:outbound:USD").balance == 0


# --- TransferManager Tests ---

def test_p2p_transfer_success(managers):
    transfer_mgr = managers["transfer_mgr"]
    repo = managers["repo"]

    req = P2PTransferRequestEntity(
        sender_user_id="usr_alice",
        recipient_user_id="usr_bob",
        currency="USD",
        amount=2500,  # $25.00
    )
    res = transfer_mgr.transfer(req)

    assert res.status == "COMPLETED"
    assert res.legs_executed == 3

    assert repo.get_account("usr_alice:USD").balance == 97500
    assert repo.get_account("usr_bob:USD").balance == 52500
    # Intermediate pools must net to zero
    assert repo.get_account("pool:outbound:USD").balance == 0
    assert repo.get_account("pool:inbound:USD").balance == 0


def test_p2p_transfer_self_transfer_rejected(managers):
    transfer_mgr = managers["transfer_mgr"]
    req = P2PTransferRequestEntity(
        sender_user_id="usr_alice",
        recipient_user_id="usr_alice",
        currency="USD",
        amount=1000,
    )
    with pytest.raises(WalletError):
        transfer_mgr.transfer(req)


def test_p2p_transfer_unknown_recipient(managers):
    transfer_mgr = managers["transfer_mgr"]
    req = P2PTransferRequestEntity(
        sender_user_id="usr_alice",
        recipient_user_id="usr_ghost",
        currency="USD",
        amount=1000,
    )
    with pytest.raises(UserNotFoundError):
        transfer_mgr.transfer(req)


def test_p2p_transfer_compensation_on_intermediate_failure(managers):
    """
    Simulate failure on Leg 3 (Inbound -> Recipient).
    Verifies that Leg 2 (Inbound -> Outbound) and Leg 1 (Outbound -> Sender)
    are executed in reverse order, restoring sender balance to original state.
    """
    transfer_mgr = managers["transfer_mgr"]
    repo = managers["repo"]

    initial_alice = repo.get_account("usr_alice:USD").balance

    # Mock execute_transfer_leg so that step 3 raises an exception
    orig_execute = repo.execute_transfer_leg

    def mock_execute(leg):
        if leg.step_number == 3 and not leg.is_reversal:
            raise RuntimeError("Simulated failure at Inbound -> Recipient step")
        return orig_execute(leg)

    with patch.object(repo, "execute_transfer_leg", side_effect=mock_execute):
        with pytest.raises(TransferExecutionError) as exc_info:
            transfer_mgr.transfer(
                P2PTransferRequestEntity(
                    sender_user_id="usr_alice",
                    recipient_user_id="usr_bob",
                    currency="USD",
                    amount=5000,
                )
            )
        assert exc_info.value.reversed is True

    # Alice balance must be fully restored!
    assert repo.get_account("usr_alice:USD").balance == initial_alice
    assert repo.get_account("pool:outbound:USD").balance == 0
    assert repo.get_account("pool:inbound:USD").balance == 0


def test_transfer_idempotency_replay(managers):
    transfer_mgr = managers["transfer_mgr"]
    repo = managers["repo"]

    req = P2PTransferRequestEntity(
        sender_user_id="usr_alice",
        recipient_user_id="usr_bob",
        currency="USD",
        amount=1000,
        idempotency_key="idemp_key_999",
    )
    res1 = transfer_mgr.transfer(req)
    assert res1.status == "COMPLETED"

    # Send exact same request with same key
    res2 = transfer_mgr.transfer(req)
    assert res2.transaction_id == res1.transaction_id
    assert res2.amount == res1.amount

    # Balance debited only once!
    assert repo.get_account("usr_alice:USD").balance == 99000
    assert repo.get_account("usr_bob:USD").balance == 51000


def test_concurrent_manager_transfers(managers):
    """Verify concurrent transfers across multiple threads at the manager level."""
    import concurrent.futures

    transfer_mgr = managers["transfer_mgr"]
    repo = managers["repo"]

    initial_alice = repo.get_account("usr_alice:USD").balance
    initial_bob = repo.get_account("usr_bob:USD").balance

    num_transfers = 10
    amount = 500

    def run_alice_to_bob(i):
        req = P2PTransferRequestEntity(
            sender_user_id="usr_alice",
            recipient_user_id="usr_bob",
            currency="USD",
            amount=amount,
        )
        return transfer_mgr.transfer(req)

    def run_bob_to_alice(i):
        req = P2PTransferRequestEntity(
            sender_user_id="usr_bob",
            recipient_user_id="usr_alice",
            currency="USD",
            amount=amount,
        )
        return transfer_mgr.transfer(req)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        f_a = [executor.submit(run_alice_to_bob, i) for i in range(num_transfers)]
        f_b = [executor.submit(run_bob_to_alice, i) for i in range(num_transfers)]

        for f in concurrent.futures.as_completed(f_a + f_b):
            res = f.result()
            assert res.status == "COMPLETED"

    # Since Alice sent 10 x 500 and Bob sent 10 x 500, final balances should equal initial balances
    assert repo.get_account("usr_alice:USD").balance == initial_alice
    assert repo.get_account("usr_bob:USD").balance == initial_bob
    assert repo.get_account("pool:outbound:USD").balance == 0
    assert repo.get_account("pool:inbound:USD").balance == 0


def test_transfer_idempotency_payload_mismatch_rejected(managers):
    """Verify TransferManager rejects reused Idempotency-Key if payload differs."""
    transfer_mgr = managers["transfer_mgr"]
    repo = managers["repo"]

    key = "idem_key_mismatch_manager"
    req1 = P2PTransferRequestEntity(
        sender_user_id="usr_alice",
        recipient_user_id="usr_bob",
        currency="USD",
        amount=1000,
        idempotency_key=key,
    )
    res1 = transfer_mgr.transfer(req1)
    assert res1.status == "COMPLETED"

    # Re-send with same key but different amount
    req2 = P2PTransferRequestEntity(
        sender_user_id="usr_alice",
        recipient_user_id="usr_bob",
        currency="USD",
        amount=2500,
        idempotency_key=key,
    )
    with pytest.raises(IdempotencyPayloadMismatchError) as exc_info:
        transfer_mgr.transfer(req2)
    assert "Idempotency-Key reused with different request payload" in str(exc_info.value)

    # Re-send with same key but different recipient
    req3 = P2PTransferRequestEntity(
        sender_user_id="usr_alice",
        recipient_user_id="usr_charlie",
        currency="USD",
        amount=1000,
        idempotency_key=key,
    )
    with pytest.raises(IdempotencyPayloadMismatchError) as exc_info:
        transfer_mgr.transfer(req3)
    assert "Idempotency-Key reused with different request payload" in str(exc_info.value)


def test_accept_quote_idempotency_replay_and_mismatch(managers):
    """Verify QuoteManager handles idempotency replay and rejects payload mismatch."""
    quote_mgr = managers["quote_mgr"]

    q1 = quote_mgr.create_quote(
        CreateQuoteRequestEntity(
            user_id="usr_alice",
            from_currency="USD",
            to_currency="EUR",
            from_amount=5000,
        )
    )
    q2 = quote_mgr.create_quote(
        CreateQuoteRequestEntity(
            user_id="usr_alice",
            from_currency="USD",
            to_currency="EUR",
            from_amount=5000,
        )
    )

    key = "idem_quote_accept_key"
    res1 = quote_mgr.accept_quote(
        AcceptQuoteRequestEntity(
            quote_id=q1.quote_id,
            user_id="usr_alice",
            idempotency_key=key,
        )
    )
    assert res1.status == "COMPLETED"

    # Replay with same quote_id and user_id -> returns cached response
    res2 = quote_mgr.accept_quote(
        AcceptQuoteRequestEntity(
            quote_id=q1.quote_id,
            user_id="usr_alice",
            idempotency_key=key,
        )
    )
    assert res2.transaction_id == res1.transaction_id
    assert res2.debited_amount == res1.debited_amount

    # Reuse same key with different quote_id -> raises IdempotencyPayloadMismatchError
    with pytest.raises(IdempotencyPayloadMismatchError) as exc_info:
        quote_mgr.accept_quote(
            AcceptQuoteRequestEntity(
                quote_id=q2.quote_id,
                user_id="usr_alice",
                idempotency_key=key,
            )
        )
    assert "Idempotency-Key reused with different request payload" in str(exc_info.value)


def test_concurrent_quote_acceptance_race_prevented_by_quote_lock(managers):
    """
    Verify that concurrent threads attempting to accept the SAME quote are serialized
    by quote.lock, so exactly 1 thread succeeds and all other threads are rejected.
    """
    quote_mgr = managers["quote_mgr"]
    wallet = managers["wallet_adapter"]

    # 1. Create a quote for Alice (10,000 USD to EUR)
    quote = quote_mgr.create_quote(
        CreateQuoteRequestEntity(
            user_id="usr_alice",
            from_currency="USD",
            to_currency="EUR",
            from_amount=10000,
        )
    )

    initial_alice_usd = wallet.get_account("usr_alice:USD").balance
    initial_alice_eur = wallet.get_account("usr_alice:EUR").balance

    num_threads = 10
    results = []
    errors = []

    def attempt_accept(i: int):
        try:
            # Each thread uses a distinct idempotency key so we test quote locking, not idempotency replay
            res = quote_mgr.accept_quote(
                AcceptQuoteRequestEntity(
                    quote_id=quote.quote_id,
                    user_id="usr_alice",
                    idempotency_key=f"concurrent_accept_key_{i}",
                )
            )
            return ("SUCCESS", res)
        except InvalidQuoteError as e:
            return ("INVALID_QUOTE", str(e))
        except Exception as e:
            return ("OTHER_ERROR", str(e))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(attempt_accept, i) for i in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            status, payload = f.result()
            if status == "SUCCESS":
                results.append(payload)
            else:
                errors.append((status, payload))

    # Exactly 1 thread must succeed
    assert len(results) == 1
    assert results[0].status == "COMPLETED"

    # All other 9 threads must be rejected with InvalidQuoteError
    assert len(errors) == num_threads - 1
    for err_type, err_msg in errors:
        assert err_type == "INVALID_QUOTE"
        assert "already" in err_msg  # e.g. "already PROCESSING" or "already ACCEPTED"

    # Verify Alice's balance was debited and credited ONLY ONCE
    final_alice_usd = wallet.get_account("usr_alice:USD").balance
    final_alice_eur = wallet.get_account("usr_alice:EUR").balance
    assert final_alice_usd == initial_alice_usd - 10000
    assert final_alice_eur == initial_alice_eur + results[0].credited_amount


def test_fx_currency_conservation_and_pool_netting(managers):
    """
    Verify 5-leg currency conservation:
    1. Every leg operates on identical source and destination currency.
    2. pool:outbound:USD and pool:inbound:EUR net out to 0.
    3. pool:fx:USD and pool:fx:EUR hold exact counterparty treasury positions.
    """
    quote_mgr = managers["quote_mgr"]
    wallet = managers["wallet_adapter"]

    quote = quote_mgr.create_quote(
        CreateQuoteRequestEntity(
            user_id="usr_alice",
            from_currency="USD",
            to_currency="EUR",
            from_amount=10000,
        )
    )

    res = quote_mgr.accept_quote(
        AcceptQuoteRequestEntity(
            quote_id=quote.quote_id,
            user_id="usr_alice",
        )
    )
    assert res.status == "COMPLETED"

    tx = wallet.get_transaction(res.transaction_id)
    assert tx is not None
    assert len(tx.legs) == 5

    # Check Leg 1: Alice(USD) -> pool:outbound:USD [USD]
    assert tx.legs[0].from_account_id == "usr_alice:USD"
    assert tx.legs[0].to_account_id == "pool:outbound:USD"
    assert tx.legs[0].currency == "USD"
    assert tx.legs[0].amount == 10000

    # Check Leg 2: pool:outbound:USD -> pool:fx:USD [USD]
    assert tx.legs[1].from_account_id == "pool:outbound:USD"
    assert tx.legs[1].to_account_id == "pool:fx:USD"
    assert tx.legs[1].currency == "USD"
    assert tx.legs[1].amount == 10000

    # Check Leg 3: pool:fx:EUR -> pool:inbound:EUR [EUR]
    assert tx.legs[2].from_account_id == "pool:fx:EUR"
    assert tx.legs[2].to_account_id == "pool:inbound:EUR"
    assert tx.legs[2].currency == "EUR"
    assert tx.legs[2].amount == 9200

    # Check Leg 4: pool:inbound:EUR -> pool:fee:EUR [EUR]
    assert tx.legs[3].from_account_id == "pool:inbound:EUR"
    assert tx.legs[3].to_account_id == "pool:fee:EUR"
    assert tx.legs[3].currency == "EUR"
    assert tx.legs[3].amount == 92

    # Check Leg 5: pool:inbound:EUR -> usr_alice:EUR [EUR]
    assert tx.legs[4].from_account_id == "pool:inbound:EUR"
    assert tx.legs[4].to_account_id == "usr_alice:EUR"
    assert tx.legs[4].currency == "EUR"
    assert tx.legs[4].amount == 9108

    # Verify pool balances
    outbound_usd = wallet.get_account("pool:outbound:USD")
    inbound_eur = wallet.get_account("pool:inbound:EUR")
    fx_usd = wallet.get_account("pool:fx:USD")
    fx_eur = wallet.get_account("pool:fx:EUR")
    fee_eur = wallet.get_account("pool:fee:EUR")

    assert outbound_usd.balance == 0   # Netted clean
    assert inbound_eur.balance == 0    # Netted clean
    assert fx_usd.balance == 10000     # Bank absorbed 10,000 USD
    assert fx_eur.balance == -9200     # Bank disbursed 9,200 EUR
    assert fee_eur.balance == 92       # Fee earned


def test_decimal_bankers_rounding_precision(managers):
    """
    Verify that rate conversions and fees use Decimal banker's rounding (ROUND_HALF_EVEN)
    without IEEE-754 binary floating-point truncation.
    """
    quote_mgr = managers["quote_mgr"]
    quote_adapter = managers["quote_adapter"]
    wallet = managers["wallet_adapter"]

    # Inject a custom rate with potential float truncation (e.g. rate 1.15)
    quote_adapter.db.rates["USD/XYZ"] = 1.15
    quote_adapter.db.accounts["usr_alice:XYZ"] = wallet.get_or_create_account(
        "usr_alice", "XYZ", is_pool=False
    )

    # 100 * 1.15 in float is 114.99999999999999 -> int() would truncate to 114
    # With Decimal quantize ROUND_HALF_EVEN, 100 * 1.15 is exactly 115!
    quote = quote_mgr.create_quote(
        CreateQuoteRequestEntity(
            user_id="usr_alice",
            from_currency="USD",
            to_currency="XYZ",
            from_amount=100,
        )
    )
    assert quote.gross_to_amount == 115
    assert quote.fee_amount == 1  # 1% of 115 = 1.15 -> rounds to 1
    assert quote.net_to_amount == 114



