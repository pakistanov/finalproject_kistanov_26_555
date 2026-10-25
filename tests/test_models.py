"""Контракты моделей и граничные значения сумм."""

import hashlib
import unittest
from datetime import UTC, datetime

from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.models import Portfolio, User, Wallet


class UserTests(unittest.TestCase):
    def test_constructor_accepts_persisted_hash(self):
        user = User(
            1,
            "alice",
            hashlib.sha256(b"1234salt").hexdigest(),
            "salt",
            datetime.now(UTC),
        )
        self.assertTrue(user.verify_password("1234"))
        self.assertFalse(user.verify_password("wrong"))

    def test_password_change_and_public_info(self):
        user = User.create(1, " alice ", "1234")
        old_salt, old_hash = user.salt, user.hashed_password
        user.change_password("новый пароль")
        self.assertFalse(user.verify_password("1234"))
        self.assertTrue(user.verify_password("новый пароль"))
        self.assertNotEqual(old_salt, user.salt)
        self.assertNotEqual(old_hash, user.hashed_password)
        self.assertEqual(
            set(user.get_user_info()),
            {
                "user_id",
                "username",
                "registration_date",
            },
        )
        self.assertEqual(user.username, "alice")
        self.assertTrue(User.from_dict(user.to_dict()).verify_password("новый пароль"))

    def test_failed_password_or_username_change_preserves_user(self):
        user = User.create(1, "alice", "1234")
        for password in ("", "123", None, 1234):
            with self.subTest(password=password), self.assertRaises(ValueError):
                user.change_password(password)
        with self.assertRaises(ValueError):
            user.username = "  "
        self.assertEqual(user.username, "alice")
        self.assertTrue(user.verify_password("1234"))

    def test_salts_are_unique_and_identifier_is_read_only(self):
        user = User.create(1, "alice", "1234")
        other = User.create(2, "bob", "1234")
        self.assertNotEqual(user.salt, other.salt)
        self.assertNotEqual(user.hashed_password, other.hashed_password)
        with self.assertRaises(AttributeError):
            user.user_id = 2


class WalletTests(unittest.TestCase):
    def test_deposit_and_withdraw(self):
        wallet = Wallet(" btc ", 0.05)
        wallet.deposit(0.01)
        wallet.withdraw(0.02)
        self.assertEqual(wallet.currency_code, "BTC")
        self.assertAlmostEqual(wallet.balance, 0.04)
        self.assertEqual(wallet.get_balance_info()["currency_code"], "BTC")

    def test_invalid_balances_and_amounts_do_not_mutate_wallet(self):
        wallet = Wallet("USD", 100)
        for value in (-1, "1", True, None, float("nan"), float("inf")):
            with self.subTest(balance=value), self.assertRaises(ValueError):
                wallet.balance = value
            self.assertEqual(wallet.balance, 100)
        for operation in (wallet.deposit, wallet.withdraw):
            for value in (0, -1, "1", True, None, float("nan"), float("inf")):
                with self.subTest(operation=operation, amount=value):
                    with self.assertRaises(ValueError):
                        operation(value)
                    self.assertEqual(wallet.balance, 100)

    def test_insufficient_funds_and_exact_withdrawal(self):
        wallet = Wallet("USD", 10)
        with self.assertRaises(InsufficientFundsError):
            wallet.withdraw(11)
        self.assertEqual(wallet.balance, 10)
        wallet.withdraw(10)
        self.assertEqual(wallet.balance, 0)

    def test_overflow_and_unrepresentable_change(self):
        wallet = Wallet("USD", 1e308)
        for amount in (1e308, 1):
            with self.assertRaises(ValueError):
                wallet.deposit(amount)
        with self.assertRaises(ValueError):
            wallet.withdraw(1)
        self.assertEqual(wallet.balance, 1e308)


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.user = User.create(1, "alice", "1234")
        self.portfolio = Portfolio(self.user.user_id, user=self.user)

    def test_currency_uniqueness_and_dictionary_copy(self):
        self.portfolio.add_currency("btc")
        with self.assertRaises(ValueError):
            self.portfolio.add_currency(" BTC ")
        copied = self.portfolio.wallets
        copied.clear()
        self.assertEqual(self.portfolio.get_wallet("BTC").balance, 0)
        self.assertIs(self.portfolio.user, self.user)
        with self.assertRaises(AttributeError):
            self.portfolio.user = self.user

    def test_valuation_in_usd_and_another_base(self):
        self.portfolio.add_currency("USD").deposit(100)
        self.portfolio.add_currency("EUR").deposit(10)
        rates = {"USD": 1.0, "EUR": 2.0}
        self.assertEqual(self.portfolio.get_total_value("USD", rates), 120)
        self.assertEqual(self.portfolio.get_total_value("EUR", rates), 60)
        with self.assertRaises(ValueError):
            self.portfolio.get_total_value("ABC", rates)

    def test_invalid_owner_and_missing_wallet(self):
        with self.assertRaises(ValueError):
            Portfolio(2, user=self.user)
        with self.assertRaises(ValueError):
            self.portfolio.get_wallet("BTC")

    def test_empty_portfolio_and_unknown_nonzero_currency(self):
        self.assertEqual(self.portfolio.get_total_value(), 0)
        wallet = self.portfolio.add_currency("ABC")
        self.assertEqual(self.portfolio.get_total_value(), 0)
        wallet.deposit(1)
        with self.assertRaises(ValueError):
            self.portfolio.get_total_value()
