"""Кэш курсов: свежесть, инверсия, кросс-курсы и недоступный провайдер."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from tests.helpers import StorageTestCase
from valutatrade_hub.core.exceptions import RateUnavailableError
from valutatrade_hub.core.rates import RateService, StubRateProvider


class RateTests(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 10, 25, 12, tzinfo=UTC)
        self.provider = StubRateProvider()
        self.rates = RateService(self.storage, self.provider, clock=lambda: self.now)

    def cache(self, pair, rate, *, age=0):
        data = self.storage.load_rates()
        data[pair] = {
            "rate": rate,
            "updated_at": (self.now - timedelta(seconds=age)).isoformat(),
        }
        data["source"] = "ParserService"
        self.storage.save_rates(data)

    def test_fresh_direct_and_inverse_avoid_provider(self):
        self.cache("BTC_USD", 60000, age=120)
        with patch.object(self.provider, "get_usd_rate", side_effect=AssertionError):
            direct = self.rates.get_rate("btc", "usd")
            inverse = self.rates.get_rate("USD", "BTC")
        self.assertEqual(direct.rate, 60000)
        self.assertAlmostEqual(inverse.rate, 1 / 60000)
        self.assertEqual(direct.source, "ParserService")
        self.assertEqual(direct.updated_at, self.now - timedelta(seconds=120))

    def test_cross_rate_uses_older_of_two_fresh_timestamps(self):
        self.cache("EUR_USD", 2, age=100)
        self.cache("BTC_USD", 60000, age=200)
        with patch.object(self.provider, "get_usd_rate", side_effect=AssertionError):
            quote = self.rates.get_rate("BTC", "EUR")
        self.assertEqual(quote.rate, 30000)
        self.assertEqual(quote.updated_at, self.now - timedelta(seconds=200))

    def test_cache_at_ttl_boundary_is_refreshed(self):
        self.cache("BTC_USD", 1, age=300)
        quote = self.rates.get_rate("BTC", "USD")
        self.assertEqual(quote.rate, 59337.21)
        self.assertEqual(quote.updated_at, self.now)
        self.assertEqual(self.storage.load_rates()["source"], "DemoStub")

    def test_future_or_invalid_cache_entry_is_not_used(self):
        for rate, age in ((1, -60), (-1, 0), (True, 0), ("1", 0)):
            with self.subTest(rate=rate, age=age):
                self.cache("BTC_USD", rate, age=age)
                self.assertEqual(self.rates.get_rate("BTC", "USD").rate, 59337.21)

    def test_unavailable_stale_currency_does_not_update_cache(self):
        self.cache("DOGE_USD", 0.1, age=301)
        before = (self.data_dir / "rates.json").read_bytes()
        with self.assertRaises(RateUnavailableError):
            self.rates.get_rate("DOGE", "USD")
        self.assertEqual((self.data_dir / "rates.json").read_bytes(), before)

    def test_fresh_custom_currency_can_be_combined_with_stub(self):
        self.cache("DOGE_USD", 0.1)
        self.assertAlmostEqual(self.rates.get_rate("DOGE", "EUR").rate, 0.1 / 1.0786)

    def test_empty_provider_can_use_cache_but_cannot_invent_rates(self):
        rates = RateService(self.storage, StubRateProvider({}), clock=lambda: self.now)
        with self.assertRaises(RateUnavailableError):
            rates.get_rate("USD", "BTC")
        self.cache("BTC_USD", 50000)
        self.assertEqual(rates.get_rate("BTC", "USD").rate, 50000)

    def test_identical_currency_and_invalid_codes(self):
        self.assertEqual(self.rates.get_rate("USD", "USD").rate, 1)
        with self.assertRaises(RateUnavailableError):
            self.rates.get_rate("ABC", "ABC")
        for code in ("", " ", "USD/EUR", None):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.rates.get_rate(code, "USD")
