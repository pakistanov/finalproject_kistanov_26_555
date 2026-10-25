.PHONY: install run lint format check build package-install

install:
	uv sync --locked

run:
	uv run finalproject_kistanov_26_555

lint:
	uv run --no-sync ruff check .

format:
	uv run --no-sync ruff format .

check: lint
	uv run --no-sync ruff format --check .

build:
	uv build

package-install: build
	uv venv --allow-existing .venv-install
	uv run --no-sync python -c "import subprocess,tomllib; from pathlib import Path; p=tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']; w=Path('dist')/(p['name'].replace('-','_')+'-'+p['version']+'-py3-none-any.whl'); subprocess.run(['uv','pip','install','--python','.venv-install','--reinstall',str(w)],check=True)"
