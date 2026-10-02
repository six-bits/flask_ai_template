"""Unit tests for the WalletAdapter and QuoteAdapter layers."""

import concurrent.futures
import pytest

from app.adapter.database import InMemoryDatabase
from app.adapter.entities import LedgerLegRecordEntity, QuoteRecordEntity
from app.adapter.quote_adapter import QuoteAdapter
from app.adapter.wallet_adapter import WalletAdapter
from app.exceptions import AccountNotFoundError, InsufficientFundsError


@pytest.fixture
def custom_adapters():
    test_db = InMemoryDatabase(seed=True)
    w_adapter = WalletAdapter(db=test_db)
    q_adapter = QuoteAdapter(db=test_db)
    return {"wallet": w_adapter, "quote": q_adapter, "db": test_db}


def test_base_seed_state(custom_adapters):
    """Verify preloaded users, balances, pools, and exchange rates across adapters."""
    wallet = custom_adapters["wallet"]
    quote = custom_adapters["quote"]

    assert wallet.user_exists("usr_alice")
    assert wallet.user_exists("usr_bob")
    assert wallet.user_exists("usr_charlie")
    assert not wallet.user_exists("usr_nonexistent")

    alice_balances = wallet.get_user_balances("usr_alice")
    assert alice_balances == {"USD": 100000, "EUR": 50000, "GBP": 20000}

    bob_balances = wallet.get_user_balances("usr_bob")
    assert bob_balances == {"USD": 50000, "EUR": 100000, "GBP": 10000}

    charlie_balances = wallet.get_user_balances("usr_charlie")
    assert charlie_balances == {"USD": 25000, "EUR": 25000, "JPY": 5000000}

    # System pools initialized to 0
    assert wallet.get_account("pool:outbound:USD").balance == 0
    assert wallet.get_account("pool:inbound:USD").balance == 0
    assert wallet.get_account("pool:fee:USD").balance == 0

    # Rates table via quote adapter
    assert quote.get_rate("USD", "EUR") == 0.92
    assert quote.get_rate("EUR", "USD") == 1.087
    assert quote.get_rate("USD", "USD") == 1.0


def test_wallet_adapter_execute_transfer_leg_success(custom_adapters):
    """Verify WalletAdapter executes atomic debit and credit between accounts."""
    wallet = custom_adapters["wallet"]
    leg = LedgerLegRecordEntity(
        leg_id="leg_001",
        transaction_id="tx_001",
        step_number=1,
        from_account_id="usr_alice:USD",
        to_account_id="pool:outbound:USD",
        currency="USD",
        amount=5000,
    )
    executed = wallet.execute_transfer_leg(leg)
    assert executed.status == "COMPLETED"

    assert wallet.get_account("usr_alice:USD").balance == 95000
    assert wallet.get_account("pool:outbound:USD").balance == 5000


def test_wallet_adapter_execute_transfer_leg_insufficient_funds(custom_adapters):
    """Verify WalletAdapter prevents overdrawing user accounts."""
    wallet = custom_adapters["wallet"]
    leg = LedgerLegRecordEntity(
        leg_id="leg_002",
        transaction_id="tx_002",
        step_number=1,
        from_account_id="usr_alice:USD",
        to_account_id="pool:outbound:USD",
        currency="USD",
        amount=200000,  # Alice only has 100000
    )
    with pytest.raises(InsufficientFundsError):
        wallet.execute_transfer_leg(leg)

    # Balance remains untouched
    assert wallet.get_account("usr_alice:USD").balance == 100000


def test_wallet_adapter_execute_transfer_leg_unknown_source_account(custom_adapters):
    """Verify exception when source account cannot be found."""
    wallet = custom_adapters["wallet"]
    leg = LedgerLegRecordEntity(
        leg_id="leg_003",
        transaction_id="tx_003",
        step_number=1,
        from_account_id="usr_unknown:USD",
        to_account_id="usr_bob:USD",
        currency="USD",
        amount=100,
    )
    with pytest.raises(AccountNotFoundError):
        wallet.execute_transfer_leg(leg)


def test_quote_adapter_lifecycle(custom_adapters):
    """Verify QuoteAdapter can save, retrieve, and update quote status."""
    quote = custom_adapters["quote"]

    record = QuoteRecordEntity(
        quote_id="qt_test_001",
        user_id="usr_alice",
        from_currency="USD",
        to_currency="EUR",
        from_amount=10000,
        exchange_rate=0.92,
        gross_to_amount=9200,
        fee_percentage=0.01,
        fee_amount=92,
        net_to_amount=9108,
        expires_at="2026-10-03T03:00:00Z",
        status="PENDING",
    )
    saved = quote.save_quote(record)
    assert saved.quote_id == "qt_test_001"

    retrieved = quote.get_quote("qt_test_001")
    assert retrieved is not None
    assert retrieved.status == "PENDING"

    quote.update_quote_status("qt_test_001", "ACCEPTED")
    assert quote.get_quote("qt_test_001").status == "ACCEPTED"


def test_wallet_adapter_idempotency_lifecycle(custom_adapters):
    """Verify check_or_reserve_idempotency and save_idempotency_response in WalletAdapter."""
    wallet = custom_adapters["wallet"]
    key = "idem-test-123"

    res1 = wallet.check_or_reserve_idempotency(key)
    assert res1 is None

    res2 = wallet.check_or_reserve_idempotency(key)
    assert res2 is not None
    assert res2.status == "PROCESSING"

    wallet.save_idempotency_response(key, 200, {"success": True})

    res3 = wallet.check_or_reserve_idempotency(key)
    assert res3 is not None
    assert res3.status == "COMPLETED"
    assert res3.response_code == 200
    assert res3.response_data == {"success": True}


def test_concurrent_transfers_thread_safety(custom_adapters):
    """Verify thread-safe concurrent transfers between accounts in WalletAdapter."""
    wallet = custom_adapters["wallet"]
    initial_alice = wallet.get_account("usr_alice:USD").balance
    initial_bob = wallet.get_account("usr_bob:USD").balance

    num_threads = 20
    transfer_amount = 100  # 100 cents each

    def perform_transfer(i):
        from_acc = "usr_alice:USD" if i % 2 == 0 else "usr_bob:USD"
        to_acc = "usr_bob:USD" if i % 2 == 0 else "usr_alice:USD"
        leg = LedgerLegRecordEntity(
            leg_id=f"concurrent_leg_{i}",
            transaction_id=f"concurrent_tx_{i}",
            step_number=1,
            from_account_id=from_acc,
            to_account_id=to_acc,
            currency="USD",
            amount=transfer_amount,
        )
        return wallet.execute_transfer_leg(leg)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(perform_transfer, i) for i in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            assert res.status == "COMPLETED"

    assert wallet.get_account("usr_alice:USD").balance == initial_alice
    assert wallet.get_account("usr_bob:USD").balance == initial_bob
