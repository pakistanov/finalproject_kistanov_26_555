# finalproject_kistanov_26_555

Консольное приложение для управления виртуальным валютным портфелем:
регистрация, вход, покупка и продажа валют, просмотр балансов и курсов.

**Технологии:** Python 3.14, uv, requests, PrettyTable, Ruff. Данные хранятся в JSON.

## Установка и запуск

```powershell
uv sync --locked
uv run finalproject_kistanov_26_555
```

## Команды

После запуска введите команды в консоли приложения:

```text
register --username alice --password 1234
login --username alice --password 1234
deposit --amount 10000
update-rates
buy --currency BTC --amount 0.05
sell --currency BTC --amount 0.01
show-portfolio
show-portfolio --base EUR
get-rate --from USD --to BTC
show-rates --top 2
show-rates --currency RUB
show-rates --base EUR
currencies
logout
help
exit
```

Новый портфель пуст; `deposit` пополняет виртуальный USD-баланс.
Покупка списывает USD, продажа начисляет USD. `amount` — количество валюты.
Для торговли выполните `login` и последующие команды в одном сеансе.
Пароль должен содержать не менее 4 символов. Справка по команде: `buy --help`.

## Сервис парсинга

Курсы загружаются из CoinGecko и ExchangeRate-API. Скопируйте `.env.example`
в `.env` в корне проекта (если файла ещё нет) и укажите ключи:

```dotenv
EXCHANGERATE_API_KEY=ваш_ключ
COINGECKO_API_KEY=ваш_Demo_ключ
```

Приложение читает `.env` автоматически; переменные окружения имеют приоритет.
`.env` исключён из Git и сборки. Для сдачи используется `.env.example`;
проверяющий заполняет свой `.env`. При необходимости ключ передаётся отдельно.

Ключи: [ExchangeRate-API](https://www.exchangerate-api.com/docs/standard-requests),
[CoinGecko Demo](https://docs.coingecko.com/demo/reference/authentication).
Для обновления одного источника: `update-rates --source coingecko`
или `update-rates --source exchangerate`.

Периодическое обновление запускается отдельной командой; остановка — Ctrl+C:

```powershell
uv run python -m valutatrade_hub.parser_service.scheduler --interval 300
```

## Хранение данных

Файлы создаются автоматически в `data/` и исключены из Git:

- `users.json` — пользователи, хеши паролей и соли.
- `portfolios.json` — портфели и балансы кошельков.
- `rates.json` — кэш курсов со временем обновления.
- `exchange_rates.json` — история измерений с уникальными идентификаторами.

Core читает только локальный кэш. Срок свежести по умолчанию — 5 минут;
устаревший курс требует `update-rates`. `show-rates` помечает устаревшие записи.
Время записи — время получения ответа; время источника сохраняется в метаданных.

## Настройки и логи

Настройки находятся в `[tool.valutatrade]` файла `pyproject.toml`: каталог
и имена JSON-файлов, `rates_ttl_seconds`, `default_base_currency` и параметры
логирования. Параметры API и списки валют — в `parser_service/config.py`,
переопределения — в `[tool.valutatrade]`. `SettingsLoader` и `DatabaseManager` — Singleton.

Операции `buy`, `sell` и запросы курсов записываются в `logs/actions.log`
в формате JSON. Уровень — `INFO`, ротация — 1 МБ и 3 резервных файла.
`log_verbose = true` добавляет балансы до и после сделки; `log_level = "DEBUG"`
включает отладочный уровень. Каталог логов исключён из Git.
Обновления и ошибки API записываются отдельно в `logs/parser.log`.

## Ошибки

- `buy`, `sell`: при нехватке средств выводятся доступная и требуемая суммы.
- `buy`, `sell`, `get-rate`: при неизвестной валюте выводится список кодов.
- При сбое получения курса предлагается повторить запрос или проверить сеть.
- Если один API недоступен, сохраняются результаты остальных источников.

## Структура проекта

```text
valutatrade_hub/
├── logging_config.py   # настройка и ротация логов
├── decorators.py       # log_action
├── core/
│   ├── currencies.py   # Currency, FiatCurrency, CryptoCurrency
│   ├── exceptions.py   # пользовательские исключения
│   ├── models.py       # User, Wallet, Portfolio
│   ├── utils.py        # валидация данных
│   ├── usecases.py     # бизнес-логика
│   ├── storage.py      # работа с JSON
│   └── rates.py        # получение курсов
├── infra/
│   ├── settings.py     # SettingsLoader
│   └── database.py     # DatabaseManager
├── parser_service/
│   ├── config.py       # API и параметры обновления
│   ├── api_clients.py  # клиенты CoinGecko и ExchangeRate-API
│   ├── updater.py      # обновление курсов
│   ├── storage.py      # история и снимок курсов
│   └── scheduler.py    # периодический запуск
└── cli/
    └── interface.py    # командный интерфейс
main.py                 # запуск приложения
pyproject.toml          # настройки и зависимости
uv.lock                 # версии зависимостей
```

## Проверка кода и сборка

```powershell
uv run ruff check .
uv run ruff format --check .
uv --no-cache build
```

Собранный пакет находится в `dist/`.

## Gitflow

- `main` — стабильные выпуски; `develop` — разработка.
- `feature/*` создаются от `develop` и сливаются в неё через `--no-ff`.
- `release/*` — подготовка выпусков; `hotfix/*` — срочные исправления.
