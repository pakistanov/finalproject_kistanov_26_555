"""Проверки сессий, расчётов и отсутствия частично сохранённых сделок."""

from unittest.mock import patch

from tests.helpers import StorageTestCase
from valutatrade_hub.core.exceptions import (
    AuthenticationError,
    InsufficientFundsError,
    RateUnavailableError,
    StorageError,
)
from valutatrade_hub.core.usecases import TradingService


class UseCaseTests(StorageTestCase):
    def test_registration_creates_empty_portfolio_and_hides_password(self):
        user = self.service.register("alice", "1234")
        self.assertIsNone(self.service.current_user)
        self.assertEqual(self.storage.load_portfolio(user).wallets, {})
        stored = self.storage.load_users()[0]
        self.assertTrue(stored.verify_password("1234"))
        self.assertNotEqual(stored.hashed_password, "1234")
        self.assertNotIn("password", stored.to_dict())

    def test_duplicate_username_and_invalid_registration_leave_data_unchanged(self):
        self.service.register("alice", "1234")
        for name, password in ((" alice ", "4321"), ("", "1234"), ("bob", "123")):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.service.register(name, password)
        self.assertEqual(len(self.storage.load_users()), 1)
        self.assertEqual(len(self.storage.load_portfolio_data()), 1)
        self.assertEqual(self.service.register("bob", "1234").user_id, 2)

    def test_login_failure_clears_previous_session(self):
        self.register_and_login()
        with self.assertRaisesRegex(AuthenticationError, "Неверный пароль"):
            self.service.login("alice", "wrong")
        self.assertIsNone(self.service.current_user)
        with self.assertRaisesRegex(AuthenticationError, "не найден"):
            self.service.login("nobody", "1234")
        self.service.login("alice", "1234")
        self.service.logout()
        self.assertIsNone(self.service.current_user)

    def test_all_portfolio_operations_require_login(self):
        for operation, arguments in (
            (self.service.show_portfolio, ()),
            (self.service.deposit, ("USD", 100)),
            (self.service.buy, ("BTC", 0.01)),
            (self.service.sell, ("BTC", 0.01)),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(
                    AuthenticationError, "Сначала выполните login"
                ):
                    operation(*arguments)
        self.assertGreater(self.service.get_rate("BTC", "USD").rate, 0)

    def test_buy_sell_conserves_value_and_survives_service_restart(self):
        self.register_and_login()
        self.service.deposit("USD", 10000)
        purchase = self.service.buy("btc", 0.05)
        self.assertAlmostEqual(purchase.usd_balance, 10000 - 0.05 * 59337.21)
        self.assertAlmostEqual(purchase.balance, 0.05)
        sale = self.service.sell("BTC", 0.01)
        self.assertAlmostEqual(sale.usd_balance, 10000 - 0.04 * 59337.21)
        self.assertAlmostEqual(sale.balance, 0.04)
        restarted = TradingService(self.storage)
        self.assertIsNone(restarted.current_user)
        restarted.login("alice", "1234")
        usd_view = restarted.show_portfolio()
        self.assertAlmostEqual(usd_view.total_value, 10000)
        eur_view = restarted.show_portfolio("EUR")
        self.assertAlmostEqual(eur_view.total_value, 10000 / 1.0786)
        self.assertAlmostEqual(
            sum(row.value for row in eur_view.wallets), eur_view.total_value
        )

    def test_empty_portfolio_and_unknown_base(self):
        self.register_and_login()
        view = self.service.show_portfolio()
        self.assertEqual(view.wallets, ())
        self.assertEqual(view.total_value, 0)
        with self.assertRaisesRegex(ValueError, "Неизвестная базовая валюта"):
            self.service.show_portfolio("ABC")

    def test_insufficient_usd_does_not_create_target_wallet(self):
        user = self.register_and_login()
        with self.assertRaises(InsufficientFundsError):
            self.service.buy("BTC", 1)
        self.assertEqual(self.storage.load_portfolio(user).wallets, {})
        self.service.deposit("USD", 100)
        original = (self.data_dir / "portfolios.json").read_bytes()
        with self.assertRaises(InsufficientFundsError):
            self.service.buy("BTC", 1)
        self.assertEqual((self.data_dir / "portfolios.json").read_bytes(), original)

    def test_overselling_and_missing_wallet_preserve_balances(self):
        self.register_and_login()
        with self.assertRaisesRegex(ValueError, "нет кошелька"):
            self.service.sell("BTC", 1)
        self.service.deposit("USD", 1000)
        self.service.buy("BTC", 0.01)
        original = (self.data_dir / "portfolios.json").read_bytes()
        with self.assertRaises(InsufficientFundsError):
            self.service.sell("BTC", 0.02)
        self.assertEqual((self.data_dir / "portfolios.json").read_bytes(), original)

    def test_unavailable_rate_cannot_partially_save_sale(self):
        user = self.register_and_login()
        portfolio = self.storage.load_portfolio(user)
        portfolio.add_currency("ABC").deposit(10)
        self.storage.save_portfolio(portfolio)
        original = (self.data_dir / "portfolios.json").read_bytes()
        with self.assertRaises(RateUnavailableError):
            self.service.sell("ABC", 1)
        self.assertEqual((self.data_dir / "portfolios.json").read_bytes(), original)

    def test_failed_trade_save_leaves_persisted_balances_unchanged(self):
        self.register_and_login()
        self.service.deposit("USD", 1000)
        original = (self.data_dir / "portfolios.json").read_bytes()
        with patch.object(self.storage, "save_portfolio", side_effect=StorageError):
            with self.assertRaises(StorageError):
                self.service.buy("BTC", 0.01)
        self.assertEqual((self.data_dir / "portfolios.json").read_bytes(), original)
        self.assertEqual(self.service.show_portfolio().total_value, 1000)

    def test_users_cannot_access_each_others_balances(self):
        self.register_and_login()
        self.service.deposit("USD", 1000)
        self.service.register("bob", "4321")
        self.service.login("bob", "4321")
        self.assertEqual(self.service.show_portfolio().total_value, 0)
        self.service.deposit("USD", 20)
        self.service.login("alice", "1234")
        self.assertEqual(self.service.show_portfolio().total_value, 1000)

    def test_invalid_amounts_and_usd_self_trades_are_rejected(self):
        self.register_and_login()
        self.service.deposit("USD", 1000)
        original = (self.data_dir / "portfolios.json").read_bytes()
        for operation in (self.service.buy, self.service.sell):
            for amount in (0, -1, True, "1", float("nan"), float("inf")):
                with self.subTest(operation=operation, amount=amount):
                    with self.assertRaises(ValueError):
                        operation("BTC", amount)
            with self.assertRaises(ValueError):
                operation("USD", 1)
        with self.assertRaises(ValueError):
            self.service.deposit("BTC", 1)
        self.assertEqual((self.data_dir / "portfolios.json").read_bytes(), original)
