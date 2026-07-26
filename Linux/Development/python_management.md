# Управление версиями и окружениями Python в Linux

## Определения

* **Python** — высокоуровневый, универсальный, интерпретируемый язык программирования, являющийся стандартом для автоматизации и SRE-задач.
* **`pyenv`** — классический менеджер версий Python, позволяющий устанавливать несколько версий интерпретатора (CPython, PyPy, Anaconda) и переключаться между ними.
* **`venv`** — встроенный модуль Python (начиная с 3.3), предназначенный для создания легковесных виртуальных окружений.
* **`virtualenv`** — сторонняя библиотека для создания виртуальных окружений, обладающая расширенным функционалом по сравнению с `venv` (поддержка старых версий Python, более высокая скорость работы).
* **`pipx`** — утилита для установки и запуска Python-приложений (CLI-инструментов) в изолированных окружениях, чтобы избежать конфликтов с системными пакетами.
* **`uv`** — современный, сверхбыстрый менеджер Python (написан на Rust), который заменяет `pip`, `venv`, `pyenv`, `pipx` и `poetry`.
* **PEP 668** — спецификация, запрещающая использование `pip install` в системном окружении дистрибутивов Linux для предотвращения поломки системных утилит.

## Основные концепции

### Безопасность системного Python
Python является критическим компонентом большинства дистрибутивов Linux (на нём написаны пакетные менеджеры `apt`, `dnf`, `yum`). **Запрещено изменять или удалять системный Python**, так как это приведет к потере работоспособности ОС. Любая разработка или установка сторонних библиотек должна происходить в изолированных окружениях.

### PEP 668 — Externally Managed Environment
В современных дистрибутивах (Debian 12+, Ubuntu 23.04+) при попытке выполнить `pip install <package>` возникнет ошибка `externally-managed-environment`. Это механизм защиты, который требует использования виртуальных окружений или системных пакетов (`apt install python3-<package>`).

### Принцип работы shims в pyenv
`pyenv` перехватывает команды Python с помощью «прокладок» (shims), вставленных в начало переменной `PATH`. Когда вы запускаете `python`, вызывается shim, который проверяет текущую активную версию (через переменную `PYENV_VERSION`, файл `.python-version` или глобальную настройку) и прозрачно перенаправляет вызов реальному исполняемому файлу.

### Переход к All-in-one инструментам (uv)
К 2026 году наблюдается массовый переход от связки `pyenv + pip + venv` к инструменту `uv`. Он работает в разы быстрее (благодаря реализации на Rust и агрессивному кэшированию) и упрощает рабочий процесс, объединяя управление версиями интерпретатора и зависимостями проекта в одном интерфейсе.

## Практические сценарии

### Настройка pyenv
`pyenv` собирает Python из исходных кодов, поэтому необходимо установить зависимости для компиляции.

**1. Установка зависимостей сборки:**
```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y make build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev \
  xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

# RHEL 8/9 / AlmaLinux / Rocky Linux
sudo dnf groupinstall "Development Tools" -y
sudo dnf install -y git gcc make zlib-devel bzip2-devel readline-devel \
  sqlite-devel openssl-devel tk-devel libffi-devel xz-devel libuuid-devel libnsl2
```

**2. Установка и инициализация:**
```bash
curl https://pyenv.run | bash

# Добавление в ~/.bashrc
export PYENV_ROOT="$HOME/.pyenv"
[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
eval "$(pyenv virtualenv-init -)"
```

**3. Управление версиями:**
```bash
pyenv install 3.12.5    # Установка версии
pyenv global 3.12.5     # Глобальная версия для пользователя
pyenv local 3.11.9      # Версия только для текущей директории (создает .python-version)
```

### Изоляция проектов через venv
Использование стандартного модуля для создания окружения:
```bash
python3 -m venv .venv   # Создание окружения в папке .venv
source .venv/bin/activate # Активация окружения (в PATH добавляется путь к .venv/bin)
# → (venv) user@host:~/project$ 
pip install requests     # Установка пакета внутри окружения
deactivate              # Выход из окружения
```

### Установка CLI-утилит (pipx)
Для инструментов вроде `ansible`, `black`, `flake8`:
```bash
pipx install ansible    # Ansible будет установлен в свое изолированное venv
pipx list               # Список установленных инструментов
pipx run ruff check .   # Одноразовый запуск инструмента без установки
```

### Современный стек с uv
`uv` позволяет полностью отказаться от других инструментов.

**1. Установка uv:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**2. Полный цикл работы над проектом:**
```bash
uv python install 3.13  # uv сам скачает и установит нужный Python
uv init my-project      # инициализация проекта с pyproject.toml
uv add requests         # добавление зависимости (автоматически создаст venv и lock-файл)
uv run main.py          # запуск скрипта (uv сам активирует venv)
```

**3. Замена pipx через uv:**
```bash
uv tool install ansible # аналог pipx install
uv tool run ansible-playbook site.yml
```

### Диагностика и типичные ошибки
* **`ModuleNotFoundError` после активации venv**: Вероятно, пакет был установлен до активации окружения или в другую версию Python. Проверьте `which pip` и `which python`.
* **Ошибка компиляции в pyenv**: Проверьте наличие `libssl-dev` и `libffi-dev`. В новых дистрибутивах (Ubuntu 24.04) может потребоваться установка `libnsl-dev`.
* **Broken Shims**: Если `python` ведет себя странно после удаления версии, выполните `pyenv rehash`.
* **`uv` и кэширование**: Если пакеты не обновляются, используйте `uv pip install --no-cache-dir`.

## Дополнительная информация

### Сравнительная таблица менеджеров

| Инструмент | Скорость | Управление версиями | Управление пакетами | Lock-файлы |
| :--- | :--- | :--- | :--- | :--- |
| **pip + venv** | Средняя | Нет | Базовое | Нет (только freeze) |
| **Poetry** | Медленная | Нет | Продвинутое | Да (`poetry.lock`) |
| **pyenv** | Средняя | Да | Нет | Нет |
| **uv** | **Экстремальная** | **Да** | **Продвинутое** | **Да (`uv.lock`)** |

### Полезные ссылки
* [Файлы версий (Version Files)](../../Git/version_files.md) — обзор `.python-version` и `.tool-versions`.
* [Официальная документация uv](https://docs.astral.sh/uv/)
* [Python Packaging User Guide](https://packaging.python.org/en/latest/) — актуальные стандарты упаковки ПО на Python.
* [Dockerfile: Лучшие практики для Python](../../Docker/Dockerfile/Docker_best_practices/python.md) — специфика использования `uv` и `venv` в контейнерах.
