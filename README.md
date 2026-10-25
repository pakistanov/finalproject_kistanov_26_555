# finalproject_kistanov_26_555

ValutaTrade Hub — консольный валютный портфель: регистрация, вход, покупка,
продажа и просмотр курсов. Python 3.14+, uv; данные хранятся в JSON.

## Установка и запуск

```powershell
git clone https://github.com/pakistanov/finalproject_kistanov_26_555.git
cd finalproject_kistanov_26_555
uv sync --locked
uv run finalproject_kistanov_26_555
```

Скопируйте `.env.example` в `.env` и заполните `EXCHANGERATE_API_KEY`
([ExchangeRate-API](https://www.exchangerate-api.com/)).
`COINGECKO_API_KEY` — необязательный Demo-ключ CoinGecko.
Приложение читает `.env` автоматически; файл исключён из Git.

## Команды

В одном сеансе приложения:

```text
update-rates
register --username alice --password 1234
login --username alice --password 1234
buy --currency BTC --amount 0.05
sell --currency BTC --amount 0.01
show-portfolio --base USD
get-rate --from USD --to BTC
show-rates --top 3
show-rates --currency RUB --base EUR
logout
exit
```

Новый портфель пуст. Упрощённая модель: `buy` увеличивает баланс валюты,
`sell` уменьшает; USD используется только для оценки. Пароль — от 4 символов.
Повторный `login` заменяет пользователя, неудачный — сбрасывает сессию.
Справка: `help` или `buy --help`.

## Структура

```text
valutatrade_hub/
├── core/            # модели, валюты, исключения, сценарии, утилиты
├── infra/           # настройки и JSON-хранилище
├── parser_service/  # API-клиенты, обновление, история, планировщик
├── cli/             # интерфейс
├── decorators.py
└── logging_config.py
data/                # users.json, portfolios.json, rates.json, exchange_rates.json
demo/                # запись работы
main.py              # точка входа
pyproject.toml        # зависимости и настройки
uv.lock
Makefile
```

## Кэш и проверка

`update-rates` загружает курсы CoinGecko и ExchangeRate-API.
Для одного источника: `update-rates --source coingecko` или `--source exchangerate`.
Кэш — `data/rates.json`, история — `data/exchange_rates.json`.
TTL — 300 секунд; при устаревании выполните `update-rates`.
Настройки — `[tool.valutatrade]` в `pyproject.toml`, логи — `logs/`.

```powershell
uv run ruff check .
uv run ruff format --check .
uv build
```

Сборки — в `dist/`. С GNU Make: `make install`, `make run`,
`make check`, `make build`, `make package-install`.

## Демонстрация

[Asciinema](demo/demo.cast) · [GIF](demo/demo.gif)
