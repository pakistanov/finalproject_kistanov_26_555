"""Команды с кавычками, восстановление после ошибок и коды завершения."""

import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from tests.helpers import StorageTestCase
from valutatrade_hub.cli.interface import WalletApplication, main


class CliTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.output = io.StringIO()
        self.app = WalletApplication(self.service, self.output)

    def test_full_session_with_quoted_credentials(self):
        for command in (
            'register --username "Alice Smith" --password "a b c"',
            'login --username "Alice Smith" --password "a b c"',
            "deposit --amount 10000",
            "buy --currency BTC --amount 0.05",
            "sell --currency BTC --amount 0.01",
            "show-portfolio --base EUR",
            "get-rate --from USD --to BTC",
        ):
            self.assertTrue(self.app.execute(command))
        text = self.output.getvalue()
        self.assertIn("Вы вошли как 'Alice Smith'", text)
        self.assertIn("Покупка выполнена", text)
        self.assertIn("Продажа выполнена", text)
        self.assertIn("ИТОГО:", text)
        self.assertIn("DemoStub", text)
        self.assertNotIn("Ошибка:", text)
        self.assertNotIn("a b c", text)

    def test_invalid_syntax_and_business_errors_do_not_exit(self):
        for command in (
            "buy --currency BTC --amount 1",
            "buy --currency BTC --amount nope",
            "buy --currency BTC",
            "unknown-command",
            'login --username "unclosed',
        ):
            self.assertTrue(self.app.execute(command))
        self.assertEqual(self.output.getvalue().count("Ошибка:"), 5)
        self.assertTrue(self.app.execute("get-rate --from USD --to EUR"))
        self.assertIn("Курс USD→EUR", self.output.getvalue())

    def test_help_empty_input_and_logout(self):
        with redirect_stdout(self.output):
            self.assertTrue(self.app.execute("buy --help"))
        self.assertIn("--amount", self.output.getvalue())
        self.assertTrue(self.app.execute("help"))
        self.assertTrue(self.app.execute("  "))
        self.register_and_login()
        self.assertTrue(self.app.execute("logout"))
        self.assertIsNone(self.service.current_user)
        self.assertFalse(self.app.execute("exit"))
        self.assertFalse(self.app.execute("quit"))

    def test_empty_portfolio_message(self):
        self.register_and_login()
        self.app.execute("show-portfolio")
        self.assertIn("Портфель пуст", self.output.getvalue())

    def test_one_shot_commands_and_exit_codes(self):
        with redirect_stdout(self.output), redirect_stderr(self.output):
            prefix = ["--data-dir", str(self.data_dir)]
            self.assertEqual(
                main([*prefix, "get-rate", "--from", "USD", "--to", "BTC"]), 0
            )
            self.assertEqual(main([*prefix, "show-portfolio"]), 1)
            self.assertEqual(main(["buy", "--amount", "wrong"]), 2)
            self.assertEqual(main(["--version"]), 0)
            self.assertEqual(main(["--help"]), 0)
        self.assertIn("Сначала выполните login", self.output.getvalue())

    def test_repl_eof_and_keyboard_interrupt_are_clean_exits(self):
        for interruption in (EOFError, KeyboardInterrupt):
            with patch("builtins.input", side_effect=interruption):
                self.assertEqual(self.app.run(), 0)

    def test_repl_continues_after_error(self):
        commands = iter(
            [
                "unknown",
                "register --username alice --password 1234",
                "login --username alice --password 1234",
                "deposit --amount 100",
                "exit",
            ]
        )
        with patch("builtins.input", side_effect=lambda _: next(commands)):
            self.assertEqual(self.app.run(), 0)
        self.assertEqual(self.service.show_portfolio().total_value, 100)

    def test_corrupt_storage_is_reported_without_traceback(self):
        (self.data_dir / "rates.json").write_text("{broken", encoding="utf-8")
        with redirect_stderr(self.output):
            result = main(
                [
                    "--data-dir",
                    str(self.data_dir),
                    "get-rate",
                    "--from",
                    "BTC",
                    "--to",
                    "USD",
                ]
            )
        self.assertEqual(result, 1)
        self.assertIn("Не удалось прочитать rates.json", self.output.getvalue())
        self.assertNotIn("Traceback", self.output.getvalue())
