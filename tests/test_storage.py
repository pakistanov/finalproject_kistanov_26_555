"""Сохранность JSON при повреждении данных и ошибках записи."""

from unittest.mock import patch

from tests.helpers import StorageTestCase
from valutatrade_hub.core.exceptions import StorageError


class StorageTests(StorageTestCase):
    def test_corrupt_json_is_not_overwritten(self):
        path = self.data_dir / "users.json"
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(StorageError):
            self.service.register("alice", "1234")
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_invalid_stored_wallet_is_reported(self):
        user = self.register_and_login()
        self.storage._write(
            "portfolios.json",
            [
                {
                    "user_id": user.user_id,
                    "wallets": {"USD": {"balance": -1}},
                }
            ],
        )
        with self.assertRaises(StorageError):
            self.service.show_portfolio()

    def test_nonfinite_json_is_rejected(self):
        (self.data_dir / "rates.json").write_text('{"rate": NaN}', encoding="utf-8")
        with self.assertRaises(StorageError):
            self.storage.load_rates()

    def test_failed_replace_preserves_original_and_cleans_temporary_file(self):
        user = self.register_and_login()
        path = self.data_dir / "portfolios.json"
        original = path.read_bytes()
        portfolio = self.storage.load_portfolio(user)
        portfolio.add_currency("USD").deposit(100)
        with patch("valutatrade_hub.core.storage.os.replace", side_effect=OSError):
            with self.assertRaises(StorageError):
                self.storage.save_portfolio(portfolio)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(list(self.data_dir.glob("*.tmp")))

    def test_registration_rolls_back_portfolio_if_user_write_fails(self):
        write = self.storage._write

        def fail_users(filename, data):
            if filename == "users.json":
                raise StorageError("Ошибка записи")
            write(filename, data)

        with patch.object(self.storage, "_write", side_effect=fail_users):
            with self.assertRaises(StorageError):
                self.service.register("alice", "1234")
        self.assertEqual(self.storage.load_users(), [])
        self.assertEqual(self.storage.load_portfolio_data(), [])
