"""Unit tests for the domain managers (UserAccountManager, QuoteManager, TransferManager)."""

import time
from unittest.mock import patch
import pytest

from app.adapter.database import InMemoryDatabase
from app.adapter.quote_adapter import QuoteAdapter
from app.adapter.wallet_adapter import WalletAdapter
from app.exceptions import (
    IdempotencyConflictError,
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

