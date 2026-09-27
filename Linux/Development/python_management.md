# Управление версиями и окружениями Python в Linux

## Определения

* **Python** — высокоуровневый интерпретируемый язык программирования. В Linux является критическим компонентом ОС (на нем базируются пакетные менеджеры `apt`, `dnf`, `zypper`).
* **GIL (Global Interpreter Lock)** — глобальная блокировка интерпретатора CPython. Гарантирует, что только один поток выполняется в Python-коде в любой момент времени, упрощая управление памятью, но ограничивая параллелизм CPU-bound задач.
* **No-GIL / Free-threaded Python (PEP 703)** — режим Python 3.13+ ( experimental ), в котором GIL удален. Позволяет истинный параллелизм потоков, но требует пересборки CPython с флагом `--disable-gil`. В 2026 году активно развивается, но многие C-расширения еще не готовы.
* **Reference counting + cyclic GC** — механизм управления памятью Python. Счетчики ссылок освобождают объекты немедленно при потере ссылки; циклический сборщик мусора (generation-based) очищает циклы раз в несколько сотен allocations.
* **`pyenv`** — классический менеджер версий, использующий механизм **shims** для переключения между интерпретаторами (CPython, PyPy, Stackless) в пользовательском пространстве.
* **`venv`** — встроенный модуль (начиная с 3.3) для создания изолированных виртуальных окружений. Основан на копировании/линковке исполняемого файла и создании собственного `site-packages`.
* **`virtualenv`** — расширенная альтернатива `venv`. Работает быстрее, поддерживает старые версии Python и более гибко настраивается.
* **`uv`** — современный (2024-2026) стандарт индустрии. Написан на Rust, объединяет функционал `pyenv`, `pip`, `pipx`, `venv` и `poetry`. Обеспечивает экстремальную скорость за счет глобального кэша и использования `reflink` (на поддерживаемых FS).
* **`pipx`** — утилита для установки CLI-приложений на Python в изолированные окружения с автоматическим созданием симлинков в `/usr/local/bin` или `~/.local/bin`.
* **`mise` / `asdf`** — универсальные менеджеры версий для множества языков (Python, Node.js, Go, Rust), использующие единый файл конфигурации `.tool-versions` или `mise.toml`.
* **`PDM` / `Poetry`** — менеджеры зависимостей и сборщики пакетов, ориентированные на работу с `pyproject.toml` и обеспечивающие строгую воспроизводимость через lock-файлы.
* **PEP 668** — спецификация «Externally Managed Environment», блокирующая `pip install` в системных директориях для защиты целостности ОС.
* **`pyproject.toml`** — современный стандарт конфигурации Python-проектов (PEP 518, 621), заменяющий `setup.py`, `requirements.txt` и конфиги различных инструментов.
* **`MALLOC_ARENA_MAX`** — переменная окружения, ограничивающая количество arenas аллокатора glibc. Критична для контейнеров: предотвращает неконтролируемый рост RSS.
* **RLIMIT_NOFILE** — максимальное количество файловых дескрипторов на процесс. Для production Python-сервисов рекомендуется 65536+.
* **`py-spy`** — инструмент профилирования Python-приложений без перезапуска и изменения кода. Работает через чтение памяти процесса (no instrumentation), оверхед < 5%.
* **Wheel (*.whl)** — предварительно скомпилированный формат дистрибуции. Ускоряет установку и избавляет от необходимости иметь build tools на целевом хосте.

## Основные концепции

### Защита системного интерпретатора
**Золотое правило SRE:** Никогда не выполняйте `sudo pip install`. Системный Python в Linux (обычно `/usr/bin/python3`) — это часть инфраструктуры ОС. Любое изменение его состава может «сломать» системные утилиты. Для работы всегда используйте пользовательские интерпретаторы (`pyenv`, `uv`, `mise`) или виртуальные окружения.

### Механизм изоляции (How it works)
Виртуальное окружение изменяет переменную окружения `PATH`. При активации (`source venv/bin/activate`) директория окружения `bin/` ставится в самое начало `PATH`. ОС находит интерпретатор именно там, а он, в свою очередь, ищет библиотеки в своем локальном `site-packages` относительно своего расположения.

### PEP 668 и современные дистрибутивы
Начиная с Ubuntu 23.04+, Debian 12+, Fedora 38+, попытка установки пакета глобально вызовет ошибку:
```text
error: externally-managed-environment
```
**Варианты решения:**
1.  Использовать `uv` или `venv` (рекомендуется).
2.  Использовать системные пакеты дистрибутива (например, `sudo apt install python3-requests`).
3.  Использовать флаг `--break-system-packages` (КРАЙНЕ НЕ РЕКОМЕНДУЕТСЯ, только для Docker-контейнеров).

### GIL и его влияние на production
CPython использует GIL для защиты внутреннего состояния интерпретатора. В production это проявляется так:
*   **CPU-bound задачи** в многопоточном коде не используют более 1 ядра.
*   **I/O-bound задачи** (сеть, диск) почти не страдают: GIL освобождается при ожидании I/O.
*   **Решение для CPU-bound:** `multiprocessing` (отдельные процессы), `ProcessPoolExecutor`, или переход на No-GIL Python 3.13+.

### No-GIL (PEP 703, Python 3.13+ experimental)
В Python 3.13 появилась экспериментальная поддержка free-threaded mode:
```bash
# Сборка CPython без GIL
./configure --disable-gil
make -j$(nproc)
```
**Статус 2026:** Многие популярные библиотеки (NumPy, Pandas) еще несовместимы. Используйте только в тестовых средах. Для production с высокой CPU-нагрузкой предпочитайте `multiprocessing` или Go/Rust для критических путей.

### Управление памятью: Reference Counting + Cyclic GC
Python освобождает память двумя механизмами:
1.  **Reference counting** (основной): каждый объект хранит счетчик ссылок. При обнулении — немедленное освобождение. Блокируется GIL.
2.  **Cyclic GC** (поколенческий, три поколения): очищает циклические ссылки (A → B → A). Срабатывает, когда порог allocations превышен.
**Практика для SRE:** Рост `gc.get_stats()` по поколениям без роста `len(gc.get_objects())` может указывать на циклические утечки.

### Container Awareness
Python 3.14+ улучшил чтение cgroups v2, но по умолчанию не привязан к лимитам контейнера как JVM или Go. Для production обязательно:
```bash
# Ограничение arenas glibc (предотвращает RSS growth)
MALLOC_ARENA_MAX=2
```
Без этого аллокатор может создавать десятки arenas, расходуя память на управление, а не на данные приложения.

### uv — революция производительности
`uv` кардинально меняет работу с Python:
*   **Глобальный кэш:** Пакеты скачиваются один раз и линкуются в окружения (не занимают лишнее место).
*   **Управление интерпретаторами:** `uv` сам скачивает нужные версии Python, не требуя сборки из исходников (в отличие от `pyenv`).
*   **Workspaces:** Поддержка монорепозиториев с множеством взаимозависимых пакетов.

## Практические сценарии

### Современный стек с uv (Рекомендуется)
**Установка:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Работа с проектом (основной workflow):**
```bash
uv sync            # Создаёт .venv и устанавливает ВСЕ зависимости из uv.lock
uv run pytest      # Запускает команду в виртуальном окружении
source .venv/bin/activate  # Активация для традиционной работы (опционально)
```

- **`uv sync`** — синхронизирует `.venv` с `uv.lock`: устанавливает все зависимости (включая dev-группы) и создаёт виртуальное окружение. Аналогично `pip install -r requirements.txt`, но оперативнее и на основе lock-файла.
- **`uv run <command>`** — запускает команду в `.venv` без ручной активации. Удобен в CI.
- **`uv.lock`** — детерминированный lock-файл (аналог `package-lock.json` в Node.js). Гарантирует, что все установки продакшена, CI и локальной разработки используют одинаковые версии пакетов и их транзитивные зависимости.

**Изоляция dev-зависимостей в группы:**
```bash
uv add --group dev pytest ruff          # Добавляет в группу [dependency-groups]
uv sync --group dev                      # Устанавливает и основные, и dev-зависимости
uv sync --group dev --no-default-group   # Только dev-группа
uv run --with pytest python -m pytest     # Ad-hoc запуск без установки в .venv
```

**Миграция с pip (requirements.txt → pyproject.toml):**
При переходе с классического `pip` + `requirements.txt`/`requirements-dev.txt` на `uv`:
```bash
# 1. Создаём pyproject.toml из существующих файлов
uv init                # Или: uv init my_project

# 2. Переносим зависимости из requirements.txt
uv add -r requirements.txt

# 3. Переносим dev-зависимости в отдельную группу
uv add --group dev -r requirements-dev.txt

# 4. Генерируем uv.lock
uv lock
```
*Поведение:* `requirements.txt` → `[project.dependencies]`, `requirements-dev.txt` → `[dependency-groups] dev`. Список групп можно переключать флагом `--group name` при `uv sync` или `uv run`.

**Управление инструментами (Замена pipx):**
```bash
uv tool install ansible # Установка CLI-утилиты в изоляции
uv tool run ruff check  # Запуск без установки (ad-hoc)
```

### Аудит безопасности (Security)
Для проверки зависимостей на известные уязвимости (CVE):
```bash
# Через стандартный pip-audit
pip install pip-audit
pip-audit -r requirements.txt

# С использованием uv
uv run pip-audit
```

### Отладка путей (Debugging Environments)
Если пакеты «не видны», проверьте, где Python ищет библиотеки:
```bash
python3 -c "import sys; print('\n'.join(sys.path))"
# → Выведет список директорий поиска (включая site-packages окружения)

which python
# → Проверка, какой именно интерпретатор используется (системный или venv)
```

### Настройка pyenv (Legacy/Source build)
Если нужна специфическая сборка (например, с отладочными символами), используйте `pyenv`.

**Зависимости для сборки (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install -y make build-essential libssl-dev zlib1g-dev \
libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev \
xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
```

**Установка версии:**
```bash
pyenv install 3.11.9
pyenv local 3.11.9    # Создает .python-version
```

### Универсальное управление версиями через mise
Если вы работаете с несколькими языками, `mise` удобнее, чем `pyenv`.

**Настройка:**
```bash
curl https://mise.jdx.dev/install.sh | sh
echo 'eval "$(mise activate bash)"' >> ~/.bashrc
```

**Использование:**
```bash
mise use python@3.12    # Установка и активация версии в текущей папке
mise ls-remote python   # Список всех доступных версий
```

## OS-интеграция и systemd

Стабильная работа Python-сервиса на Linux требует корректной настройки лимитов ОС и systemd-юнита.

**Лимиты процессов (ulimit):**
```bash
# Проверка текущих лимитов для процесса
cat /proc/<PID>/limits | grep -E "Max open files|Max processes"

# Ключевые лимиты для Python:
# - nofile (open files): 65536+ (сеть, файлы, сокеты)
# - nproc (max user processes): 4096+ (для asyncio/multiprocessing)
# - memlock: unlimited (если используется libmemcached или аналоги)
```

**Пример systemd-юнита:**
```ini
# /etc/systemd/system/python-app.service
[Unit]
Description=Python Application
After=network.target

[Service]
Type=exec
User=app
Group=app
WorkingDirectory=/opt/python-app
Environment="PATH=/opt/python-app/.venv/bin"
Environment="PYTHONUNBUFFERED=1"
Environment="MALLOC_ARENA_MAX=2"

ExecStart=/opt/python-app/.venv/bin/gunicorn \
    --workers 4 \
    --bind unix:/opt/python-app/app.sock \
    --timeout 30 \
    --max-requests 1000 \
    --access-logfile /var/log/python-app/access.log \
    --error-logfile /var/log/python-app/error.log \
    main:app

Restart=on-failure
RestartSec=5
LimitNOFILE=65536
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
```

**sysctl параметры для хоста:**
```bash
# /etc/sysctl.d/90-python-app.conf
# Увеличивает количество разрешенных файловых дескрипторов
fs.file-max = 100000

# Улучшает TCP-производительность для asyncio/aiohttp
net.core.somaxconn = 4096
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15

# Применение
sysctl --system
```

**Валидация:**
```bash
# Проверка лимитов сервиса
systemctl show python-app -p LimitNOFILE -p LimitNPROC
# → LimitNOFILE=65536
# → LimitNPROC=4096

# Проверка MALLOC_ARENA_MAX
cat /proc/$(pgrep -f gunicorn)/environ | tr '\0' '\n' | grep MALLOC_ARENA_MAX
# → MALLOC_ARENA_MAX=2
```

## Профилирование и диагностика

### py-spy (zero-overhead, production-safe)
Профилирование без остановки приложения и без изменения кода:
```bash
# Просмотр "top" функций в реальном времени
py-spy top --pid <PID>

# Генерация Flame Graph на 30 секунд
py-spy record -o flamegraph.svg --duration 30 --pid <PID>

# Профилирование по имени процесса
py-spy top -- python app.py
```

**В Docker-контейнере:**
```bash
# Найти PID процесса в контейнере
docker inspect --format '{{.State.Pid}}' <container_name>

# Профилирование из хостовой системы
py-spy top --pid <PID>
```

### cProfile и memory_profiler
```bash
# CPU-профилирование (встроенное)
python -m cProfile -s cumulative app.py

# Профилирование памяти
pip install memory_profiler
python -m memory_profiler app.py

# Построчный анализ памяти
@profile
def leaky_function():
    ...

python -m memory_profiler script.py
```

### Утечка файловых дескрипторов
```bash
# Подсчет открытых FD процесса
ls /proc/<PID>/fd | wc -l
# → 1245

# Просмотр лимита
cat /proc/<PID>/limits | grep "Max open files"
# → Max open files  65536  65536  files

# Поиск утечек: сокеты vs файлы
ls -la /proc/<PID>/fd | grep -c socket
ls -la /proc/<PID>/fd | grep -c pipe

# Мониторинг в реальном времени
watch -n 1 "ls /proc/<PID>/fd | wc -l"
```

**Типичные причины утечек FD:**
*   Открытие файлов/сокетов без `close()` в блоке `finally`.
*   Логирование в файл без ротации.
*   Незакрытые подключения к БД или HTTP-сессии.

### GIL Contention
```bash
# Проверка contention через GIL-статистику
python -c "
import sys
import time
from concurrent.futures import ThreadPoolExecutor

def cpu_bound():
    return sum(range(1000000))

with ThreadPoolExecutor(max_workers=4) as pool:
    start = time.time()
    results = list(pool.map(lambda _: cpu_bound(), range(4)))
    print(f'Duration: {time.time() - start:.2f}s')
    print('Если > 1x single-core — GIL contention')
"
```

## Работа в изолированных средах (air-gapped)

В контурах без доступа к интернету предварительная подготовка пакетов обязательна.

**Сценарий 1: pip download + внутренний репозиторий**
```bash
# На машине с интернетом
pip download -r requirements.txt -d ./packages

# Перенос архива в закрытый контур
scp -r ./packages user@internal:/opt/pypi-mirror/

# Установка из локального кэша
pip install --no-index --find-links=/opt/pypi-mirror/packages -r requirements.txt
```

**Сценарий 2: uv offline mode**
```bash
# На машине с интернетом
uv pip compile requirements.txt -o uv.lock
uv pip sync --frozen

# В закрытом контуре
UV_INDEX_URL=https://nexus.internal/repository/pypi-proxy/simple \
  uv sync --frozen
```

**Сценарий 3: Внутренний PyPI-репозитор**
Для enterprise-сред разверните Nexus, Artifactory или devpi. Настройте клиенты:
```bash
# pip
pip install --index-url https://pypi.internal/simple/ --trusted-host pypi.internal package

# uv
uv --index-url https://pypi.internal/simple/ sync --frozen
```

## Логирование в production

### Структурированное логирование (JSON)
Используйте `python-json-logger` для машинного парсинга:
```python
import logging
from pythonjsonlogger import jsonlogger

logger = logging.getLogger()
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(message)s')
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

logger.info("Request processed", extra={"user_id": 42, "duration_ms": 12})
# → {"asctime": "...", "levelname": "INFO", "message": "Request processed", "user_id": 42, "duration_ms": 12}
```

### Интеграция с journald
Python пишет в `stdout/stderr`, `journald` собирает автоматически. Настройте идентификацию:
```ini
# /etc/systemd/system/python-app.service
[Service]
SyslogIdentifier=python-app
StandardOutput=journal
StandardError=journal
```

```bash
# Просмотр логов
journalctl -u python-app -f --output=json
# → {"SYSLOG_IDENTIFIER":"python-app","MESSAGE":"Request processed...","_PID":1234}
```

### Ротация логов
Для файлового вывода используйте `logrotate`:
```bash
# /etc/logrotate.d/python-app
/var/log/python-app/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl reload python-app
    endscript
}
```

## Типичные проблемы и решения

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **GIL Contention** | CPU-bound задачи в потоках | `py-spy top --pid <PID>`; время CPU > количество ядер | Переход на `ProcessPoolExecutor` или `multiprocessing` |
| **Memory Leak** | Утечка в C-расширениях или циклические ссылки | `memory_profiler`; `tracemalloc`; рост RSS без причины | Найти утечку через `objgraph`; обновить/заменить проблемную библиотеку |
| **Too many open files** | RLIMIT_NOFILE исчерпан | `ls /proc/<PID>/fd \| wc -l`; `cat /proc/<PID>/limits` | Увеличить `LimitNOFILE=` в systemd; проверить на утечку FD |
| **OOMKilled** | Потребление памяти > лимит cgroups | `dmesg \| grep -i "oom\|killed"`; `docker stats` | Уменьшить `MALLOC_ARENA_MAX`; увеличить лимит; оптимизировать аллокации |
| **ModuleNotFoundError** | PYTHONPATH не включает site-packages venv | `python -c "import sys; print(sys.path)"` | Активировать venv; проверить `python -m pip list` |
| **Slow pip install** | Отсутствие pre-built wheels (Alpine) | `pip install` компилирует из исходников | Использовать `slim` вместо `Alpine`; кэшировать wheels |
| **SIGTERM ignored** | Python не PID 1 или нет обработчика | `docker stop` ждет 10с, затем SIGKILL | Добавить `tini`/`dumb-init`; реализовать `signal.signal(signal.SIGTERM, ...)` |
| **Zombie processes** | Multiprocessing без `if __name__ == '__main__'` | `ps aux \| grep defunct` | Добавить `if __name__ == '__main__':`; использовать `multiprocessing.set_start_method('spawn')` |

### Проверка работоспособности после изменений
```bash
# Проверка что интерпретатор из venv
/opt/python-app/.venv/bin/python --version
# → Python 3.12.x

# Проверка site-packages
/opt/python-app/.venv/bin/python -c "import sys; print(sys.path)"
# → ['/opt/python-app/.venv/lib/python3.12/site-packages', ...]

# Проверка что Gunicorn запущен
ps aux | grep gunicorn
# → app  12345  0.5  2.1  ... gunicorn: master [main:app]

# Проверка лимитов
cat /proc/12345/limits | grep "Max open files"
# → Max open files  65536  65536  files
```

## Дополнительная информация

### См. также
* **[Dockerfile: Лучшие практики для Python](../../Docker/Dockerfile/Docker_best_practices/python.md)** — multi-stage, uv в Docker, безопасность.
* **[Развертывание Python-приложения с Ansible](../../Ansible/examples/example_python_app_deployment.md)** — systemd, Nginx, Gunicorn, rolling update.
* **[Файлы версий (.python-version)](../../Git/version_files.md)** — как инструменты читают конфигурацию версий.

### Справочные ресурсы
* [Astral.sh (uv)](https://astral.sh/uv) — официальный сайт и документация.
* [Real Python: Virtual Environments](https://realpython.com/python-virtual-environments-a-primer/) — глубокий разбор механизмов изоляции.
* [Python.org: PEP 668](https://peps.python.org/pep-0668/) — технические детали защиты системного Python.
* [Python.org: PEP 703 (No-GIL)](https://peps.python.org/pep-0703/) — детали free-threaded режима.
* [py-spy documentation](https://github.com/benfred/py-spy) — профилирование без остановки.
