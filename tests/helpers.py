"""Изолированное хранилище для каждого теста."""

import tempfile
import unittest
from pathlib import Path

from valutatrade_hub.core.storage import JsonStorage
from valutatrade_hub.core.usecases import TradingService


class StorageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data_dir = Path(temporary.name)
        self.storage = JsonStorage(self.data_dir)
        self.service = TradingService(self.storage)

    def register_and_login(self, username: str = "alice", password: str = "1234"):
        user = self.service.register(username, password)
        self.service.login(username, password)
        return user
