# Управление нестабильными тестами (Flaky Tests)

## Определения

**Flaky Test (Нестабильный тест)** — тест, который проходит и падает без изменений в тестируемом коде. Результат зависит от внешних факторов: времени, состояния сети, параллелизма, ресурсов раннера или порядка выполнения.

**Test Quarantine (Карантин тестов)** — стратегия изоляции flaky тестов: они перемещаются в отдельный набор и запускаются отдельно, не блокируя основной пайплайн.

**Test Stability Score** — метрика, отражающая стабильность теста за N последних запусков. Рассчитывается как доля успешных запусков.

**Retry Policy** — стратегия автоматического повторного запуска падающих тестов с фиксированным или экспоненциальным backoff.

**Root Cause Analysis (RCA)** — системный анализ первопричины нестабильности: среда, код, данные, инфраструктура.

**Quarantine TTL** — обязательный срок истечения карантина, после которого тест автоматически возвращается в основной набор или пайплайн получает алерт.

**Noisy Neighbor** — соседний процесс или pod на shared-раннере, потребляющий disproportional количество CPU/RAM/disk I/O и вызывающий нестабильность тестов.

**Test History** — персистентное хранилище результатов прогонов (JUnit XML, JSON, SQLite/PostgreSQL) для построения метрик стабильности во времени.

**Reproducibility** — возможность воспроизвести падение теста локально или в изолированном окружении с теми же условиями, что и в CI.

**Idempotent Retry** — повторный запуск теста, который безопасен с точки зрения побочных эффектов: не создаёт дублирующих записей в БД, не отправляет повторных уведомлений, не запускает двойной деплой.

## Основные концепции и архитектура

### Причины flaky тестов

| Категория | Примеры | Решение |
| :--- | :--- | :--- |
| **Временна́я зависимость** | `time.sleep()`, проверка даты/времени, timezone drift | Clock mocking, фиксированные timestamp, UTC everywhere |
| **Параллелизм** | Shared state, file locks, порты, race conditions | Testcontainers, isolation, random ports, `@serial` |
| **Сеть** | Timeout, DNS resolution, внешние API, flaky DNS кэш | Mock external calls, retry, timeout, `/etc/hosts` статика |
| **Ресурсы** | CPU/memory pressure в CI, noisy neighbor, OOMKill | Выделенные раннеры, resource limits, cgroup tuning |
| **Порядок выполнения** | Тесты зависят от предыдущих | Полная изоляция, cleanup между тестами, random order |
| **Данные** | Shared test data, dirty state, leftover fixtures | Per-test data, cleanup scripts, ephemeral DB schema |
| **UI-тесты** | Анимации, загрузка, race conditions | Wait strategies, stable selectors, disable animations |
| **Инфраструктура** | DNS TTL, NTP drift, container restart, disk full | Pre-flight checks, monitoring, resource alerts |
| **Идемпотентность** | Retry создаёт дубли, side effects | Idempotent operations, deduplication keys, transactional rollback |

### Жизненный цикл управления flaky тестами

```
Обнаружение → Классификация → Карантин (с TTL) → Retry (с лимитом) → 
RCA → Исправление → Валидация → Возврат в основной набор
```

1. **Detection** — автоматическое обнаружение через статистику прогонов (Stability Score < 0.99, Flaky Rate > 1%).
2. **Classification** — категоризация причины (сеть, время, ресурсы, код) на основе логов, артефактов и воспроизведения.
3. **Quarantine** — перемещение в отдельный набор с TTL и обязательным issue-тикетом.
4. **Retry** — временный автоматический повтор с лимитом (обычно 2–3 попытки), только для идемпотентных операций.
5. **Root Cause Analysis** — воспроизведение в изоляции, анализ артефактов (логи, трассировки, метрики раннера).
6. **Fix** — исправление кода теста, окружения или инфраструктуры.
7. **Validation** — 3+ успешных прогона подряд в production-like условиях.
8. **Return** — возврат в основной набор, удаление из карантина.

### Интеграция с CI/CD

Flaky test management не является отдельным stage, а пронизывает весь pipeline:

- **Trigger:** каждый пайплайн собирает метрики стабильности.
- **Gate:** основной набор тестов должен быть stable; flaky тесты карантинятся и не блокируют merge.
- **Feedback:** метрики Flaky Rate и Quarantine Coverage экспортируются в dashboard CI.
- **Automation:** детекция, карантин и retry автоматизированы; RCA — ручная или semi-automatic.

### Метрики

| Метрика | Формула | Целевое значение |
| :--- | :--- | :--- |
| **Flaky Rate** | `flaky_tests / total_tests * 100` | < 1% |
| **Stability Score** | `successful_runs / total_runs` | > 0.99 |
| **Mean Time Between Flakes** | `total_time / flake_count` | > 100 запусков |
| **Quarantine Coverage** | `quarantined / known_flaky * 100` | 100% |
| **Retry Rate** | `retried_tests / total_tests * 100` | < 0.5% |
| **MTTR (Test)** | `time_to_fix / flaky_incidents` | Снижается с каждым релизом |

### Компоненты системы

| Компонент | Назначение | Реализация |
| :--- | :--- | :--- |
| **Detector** | Обнаружение flaky по истории | Скрипт анализа JUnit/JSON, ReportPortal, Allure TestOps |
| **Quarantine Store** | Хранилище списка flaky тестов | Файл `quarantine.txt`, DB, или marker в коде |
| **Test History DB** | Персистентное хранение результатов | JSON-файл, SQLite, PostgreSQL, объектное хранилище |
| **Dashboard** | Визуализация метрик | Grafana, CI-native insights, ReportPortal |
| **Policy Engine** | Применение retry/quarantine правил | CI-конфиг, pytest markers, custom script |

## Практические сценарии

### Pytest: marker и retry через плагин

```python
# pytest.ini
[pytest]
markers =
    flaky: известные нестабильные тесты (карантин)
    stable: стабильные тесты (основной набор)

# conftest.py
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "flaky: mark test as flaky with automatic retries"
    )

def pytest_collection_modifyitems(config, items):
    if config.getoption("--quarantine"):
        skip_flaky = pytest.mark.skip(reason="quarantined flaky tests")
        for item in items:
            if "flaky" in item.keywords:
                item.add_marker(skip_flaky)

# test_module.py
import pytest

@pytest.mark.flaky(reruns=3, reruns_delay=5)
def test_external_api_call():
    """Тест внешнего API — может быть нестабильным из-за сети."""
    result = call_external_api()
    assert result.status == "ok"

# Запуск только стабильных тестов
# pytest tests/ -m "not flaky"

# Запуск только flaky тестов (для анализа)
# pytest tests/ -m flaky --quarantine
```

Установка плагина:
```bash
pip install pytest-rerunfailures
```

### Python: скрипт детекции flaky тестов

```python
import subprocess
import json
import os
from collections import defaultdict
from datetime import datetime

RESULTS_FILE = "test-results.xml"
HISTORY_FILE = "test-history.json"
STABILITY_THRESHOLD = 0.99
MIN_RUNS = 5

def run_tests():
    """Запуск тестов с JUnit-выводом."""
    result = subprocess.run(
        ["pytest", "tests/", "--tb=short", f"--junitxml={RESULTS_FILE}"],
        capture_output=True, text=True
    )
    return result.returncode

def load_history():
    """Загрузка истории запусков."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return defaultdict(lambda: {"success": 0, "total": 0, "last_seen": None})

def save_history(history):
    """Сохранение истории."""
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def analyze_stability():
    """Анализ стабильности тестов по истории запусков."""
    history = load_history()
    
    # Запуск тестов
    exit_code = run_tests()
    
    # Парсинг JUnit XML
    import xml.etree.ElementTree as ET
    tree = ET.parse(RESULTS_FILE)
    root = tree.getroot()
    
    today = datetime.utcnow().isoformat()
    
    for testcase in root.findall(".//testcase"):
        name = testcase.get("name")
        history[name]["total"] += 1
        history[name]["last_seen"] = today
        
        failure = testcase.find("failure")
        if failure is None:
            history[name]["success"] += 1
    
    save_history(history)
    
    # Анализ flaky тестов
    flaky = []
    for name, stats in history.items():
        if stats["total"] >= MIN_RUNS:
            stability = stats["success"] / stats["total"]
            if stability < STABILITY_THRESHOLD:
                flaky.append({
                    "name": name,
                    "stability": stability,
                    "total": stats["total"],
                    "failed": stats["total"] - stats["success"]
                })
    
    if flaky:
        print("FLAKY TESTS DETECTED:")
        for t in sorted(flaky, key=lambda x: x["stability"]):
            print(f"  {t['name']}: {t['stability']:.2%} ({t['failed']}/{t['total']} failures)")
        return 1
    
    print("All tests are stable")
    return 0

if __name__ == "__main__":
    exit(analyze_stability())
```

### GitLab CI: quarantine workflow

```yaml
stages:
  - test
  - quarantine

# Детекция flaky тестов
flaky_detection:
  stage: test
  script:
    - python scripts/detect_flaky.py
  artifacts:
    when: always
    paths:
      - test-history.json
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Запуск flaky тестов отдельно (не блокируя деплой)
quarantine_tests:
  stage: quarantine
  script:
    - pytest tests/ -m flaky --junitxml=quarantine-results.xml
  allow_failure: true
  artifacts:
    when: always
    reports:
      junit: quarantine-results.xml
    expire_in: 14 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### GitHub Actions: retry и quarantine

```yaml
name: Tests
on: [pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests with retry
        uses: nick-fields/retry@v3
        with:
          timeout_minutes: 10
          max_attempts: 3
          retry_wait_seconds: 20
          warning_on_retry: true
          command: pytest tests/ -v

  quarantine:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
      - name: Run quarantined tests
        run: |
          TODAY=$(date -u +%F)
          while IFS='|' read -r spec expiry; do
            [ -z "$spec" ] && continue
            if [[ "$expiry" < "$TODAY" ]]; then
              echo "::error::Карантин истёк для $spec — верните тест или продлите"
              exit 1
            fi
            grep -qxF "$spec" .github/quarantine.txt && TESTS_TO_RUN="$TESTS_TO_RUN $spec"
          done < .github/quarantine.txt
          npx jest $TESTS_TO_RUN
```

### Bash: анализ истории тестов

```bash
# Извлечение статистики из JUnit XML
python3 -c "
import xml.etree.ElementTree as ET
import sys

tree = ET.parse('test-results.xml')
root = tree.getroot()

failures = 0
total = 0
for testsuite in root.findall('.//testsuite'):
    total += int(testsuite.get('tests', 0))
    failures += int(testsuite.get('failures', 0)) + int(testsuite.get('errors', 0))

print(f'Total: {total}, Failures: {failures}, Rate: {failures/total*100:.2f}%')
"

# Поиск flaky тестов по истории (JSON)
python3 -c "
import json
from collections import defaultdict

with open('test-history.json') as f:
    history = json.load(f)

flaky = []
for name, stats in history.items():
    if stats['total'] >= 5:
        stability = stats['success'] / stats['total']
        if stability < 0.99:
            flaky.append((name, stability))

print('Flaky tests:')
for name, stability in sorted(flaky, key=lambda x: x[1]):
    print(f'  {name}: {stability:.2%}')
"

# Проверка quarantine TTL
TODAY=$(date -u +%F)
while IFS='|' read -r spec expiry; do
  [ -z "$spec" ] && continue
  if [[ "$expiry" < "$TODAY" ]]; then
    echo "EXPIRED: $spec (was $expiry)"
  fi
done < .github/quarantine.txt
```

## Операции и команды

### CLI-инструменты для управления flaky тестами

| Инструмент | Назначение | Основные команды |
| :--- | :--- | :--- |
| **pytest** | Запуск тестов с маркерами и retry | `pytest tests/ -m "not flaky"` |
| **pytest-rerunfailures** | Автоматический retry упавших тестов | `pytest --reruns 3 --reruns-delay 5 tests/` |
| **jq** | Парсинг JSON-истории тестов | `jq '.["test_name"].stability' history.json` |
| **xmlstarlet** | Парсинг JUnit XML | `xmlstarlet sel -t -v "//testsuite/@tests" results.xml` |
| **gh** | Управление GitHub Actions rerun | `gh api repos/{owner}/{repo}/actions/runs/{id}/rerun-failed-jobs -X POST` |
| **gitlab** | Управление GitLab CI retry | `glci retry` или нативный `retry:` в конфиге |
| **sqlite3** | Анализ истории тестов в БД | `sqlite3 history.db "SELECT name, stability FROM tests WHERE stability < 0.99"` |

### Основные параметры pytest-rerunfailures

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `--reruns` | Количество повторных запусков | `--reruns 3` |
| `--reruns-delay` | Задержка между повторными запусками (секунды) | `--reruns-delay 5` |
| `--only-rerun` | Повторять только указанные коды ошибок | `--only-rerun AssertionError` |
| `--ignore-glob` | Игнорировать файлы при rerun | `--ignore-glob "*integration*"` |

### Основные параметры pytest для управления flaky

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `-m, --markers` | Фильтр по маркерам | `-m "not flaky"` |
| `--tb` | Формат traceback | `--tb=short`, `--tb=no` |
| `--junitxml` | JUnit XML вывод | `--junitxml=results.xml` |
| `-x` | Остановка после первой ошибки | `-x` |
| `--maxfail` | Максимум ошибок перед остановкой | `--maxfail=5` |
| `--randomly-seed` | Фиксированный seed для рандомизации | `--randomly-seed=42` |

### Bash-паттерны для анализа

```bash
# Подсчёт общего количества и failure rate из JUnit XML
FAILURES=$(xmlstarlet sel -t -v "sum(//testsuite/@failures)" results.xml)
ERRORS=$(xmlstarlet sel -t -v "sum(//testsuite/@errors)" results.xml)
TOTAL=$(xmlstarlet sel -t -v "sum(//testsuite/@tests)" results.xml)
RATE=$(echo "scale=2; ($FAILURES + $ERRORS) / $TOTAL * 100" | bc)
echo "Failure rate: ${RATE}%"

# Фильтрация flaky тестов из истории
jq 'to_entries | map(select(.value.stability < 0.99)) | from_entries' history.json

# Проверка Stability Score для конкретного теста
python3 -c "
import json
name = 'test_auth_login'
with open('history.json') as f:
    h = json.load(f)
stats = h.get(name, {'success': 0, 'total': 0})
print(f'{name}: {stats[\"success\"]/stats[\"total\"]:.2%}')
"

# Экспорт списка flaky тестов в quarantine.txt
python3 -c "
import json
with open('history.json') as f:
    h = json.load(f)
with open('quarantine.txt', 'w') as out:
    for name, stats in h.items():
        if stats.get('total', 0) >= 5:
            stability = stats['success'] / stats['total']
            if stability < 0.99:
                expiry = '2026-12-31'  # TTL по умолчанию
                out.write(f'{name}|{expiry}\n')
"
```

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Тест падает только в CI, не локально | Разные ресурсы, порядок запуска, timezone | Использовать Testcontainers, UTC, isolated networks |
| Тест «мерцает» каждый запуск | Race condition, shared state, timing | Добавить synchronization, cleanup, stable waits |
| Retry помогает, но тест медленный | Сеть или таймауты, external API | Увеличить timeout, mock внешние сервисы, retry с backoff |
| Все тесты flaky после обновления зависимостей | Взаимодействие с новой версией библиотеки | Pin dependency versions, обновить тесты, проверить changelog |
| Flaky test только при параллельном запуске | Порт-конфликты, shared files, DB locks | Random ports, tmpfs, isolated volumes, per-test DB |
| Тест падает ночью, проходит днём | Timezone, NTP drift, resource scheduling | Использовать UTC, фиксированные timestamps, dedicated runners |
| DNS-related flakiness | DNS TTL, кэш, resolver | Статический `/etc/hosts`, longer TTL, local DNS |
| OOMKill на раннере | Недостаток памяти, memory leak | Увеличить лимит, добавить swap, проверить heap |
| Flaky только на shared runner | Noisy neighbor, noisy I/O | Перейти на self-hosted runner, resource limits |
| Quarantine растёт бесконтрольно | Нет TTL, нет RCA, нет автоматического возврата | Внедрить TTL, alert при истечении, issue tracker |
| Retry маскирует регрессию | Детерминированный тест тоже ретраится | Ограничить retry только flaky-маркированными тестами |
| База flaky растёт после релиза | Новая функциональность без изоляции | Добавить Testcontainers, cleanup, isolation |

### Диагностика в CI/CD

```bash
# Проверка доступности сервиса перед нагрузкой
curl -sf https://api.example.com/health || exit 1

# Проверка ресурсов раннера
cat /proc/meminfo | grep -E "MemTotal|MemAvailable|SwapTotal"
cat /proc/cpuinfo | grep -E "processor|model name" | head -4
df -h /tmp /var/lib/docker

# Проверка DNS
dig +short api.example.com
cat /etc/resolv.conf

# Проверка NTP
timedatectl status || ntpq -p

# Просмотр логов раннера (GitLab)
cat /var/log/gitlab-runner/system.log | tail -50

# Быстрый smoke-тест перед полным прогоном
pytest tests/ -k "smoke" --tb=short -q

# Воспроизведение с фиксированным seed
pytest tests/test_flaky.py --randomly-seed=last --tb=long -v
```

## Best Practices

### Проектирование тестов

- **Изоляция:** каждый тест работает с собственными данными, схемой БД, портами и временными директориями. Никакого shared state между тестами.
- **Idempotency:** тесты должны быть безопасными для повторного запуска. Используйте transactional rollback, deduplication keys, idempotency keys в API.
- **Wait strategies:** избегайте `time.sleep()`; используйте explicit waits (polling с backoff, `await.element()`, health checks).
- **Clock mocking:** фиксируйте время через `freezegun` (Python), `@Clock` (Java), `sinon.useFakeTimers` (JS). Все даты в UTC.
- **External calls:** мокируйте внешние API; если мок невозможен — используйте contract testing (Pact) или dedicated test instance.

### Retry Policy

- **Лимит:** не более 2–3 попыток для flaky тестов с экспоненциальным backoff (5s, 10s, 20s).
- **Scope:** retry применяется только к заведомо flaky или внешне-зависимым тестам, не к детерминированным.
- **Visibility:** каждый retry должен быть виден в логах (`warning_on_retry: true` в GitHub Actions, `reruns` в pytest).
- **Idempotency check:** перед включением retry убедитесь, что операция идемпотентна (нет side effects).

### Quarantine

- **TTL mandatory:** каждый quarantined тест имеет дату истечения. По истечении — алерт и автоматический возврат в основной набор или продление через MR.
- **Issue tracker:** каждый quarantined тест имеет связанный тикет с причиной и планом исправления.
- **Coverage target:** Quarantine Coverage должна стремиться к 0%. Растущий quarantine — сигнал проблем в кодовой базе или окружении.
- **Run quarantine отдельно:** quarantined тесты запускаются в отдельной задаче (`continue-on-error: true`), не блокируя основной пайплайн.

### Runner-ы и окружение

- **Выделенные раннеры:** используйте self-hosted runners для критических тестов. Shared runners ненадёжны из-за noisy neighbors.
- **Resource limits:** задавайте `limits` и `requests` для контейнеров с тестами (CPU, memory). Мониторьте OOMKill.
- **Isolation:** каждый pipeline использует отдельный стенд или namespace. Никаких shared state между параллельными запусками.
- **Ephemeral окружения:** после каждого прогона окружение уничтожается. Никаких «горячих» стендов между джобами.
- **Pre-flight checks:** перед запуском тестов проверяйте DNS, NTP, диск, память, доступность зависимостей.

### Baseline и Regression Detection

- **Test History DB:** сохраняйте историю прогонов в персистентное хранилине (файл, SQLite, PostgreSQL). Minimum 30 дней для анализа трендов.
- **Stability Score threshold:** < 0.99 за 5+ запусков — сигнал к карантину.
- **Automated detection:** детекция flaky тестов должна быть частью pipeline, а не ручным действием.
- **Failure clustering:** группируйте падения по stacktrace и ошибкам для быстрого выявления общей причины.

### Безопасность

- **Секреты:** никогда не хардкодьте API-ключи, токены в тестах. Используйте переменные окружения CI.
- **Sensitive data:** не логируйте тела запросов/ответов с PII. Используйте `--quiet` или фильтры.
- **mTLS:** для production-like стендов используйте клиентские сертификаты.

## Дополнительная информация

### См. также

* **[Тест-отчёты и надёжность в GitHub Actions](../../Github_CI/Test_Reporting_Reliability.md)** — ретраи, карантин, авто-rerun и публикация отчётов в GitHub.
* **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — quality gates, TIA, эфемерные окружения.
* **[Изоляция и надёжность тестов](../../Testing/testing_types_unit_integration_e2e.md)** — Testcontainers, изоляция состояния, принцип FIRST.

### Внешние ресурсы

* [pytest-rerunfailures](https://pytest-rerunfailures.readthedocs.io/) — плагин для автоматического retry в Pytest.
* [Flaky Tests at Scale (Netflix)](https://netflixtechblog.com/flaky-test-management-at-scale-6b38e6a7faf2) — подход Netflix к управлению нестабильностью.
* [GitHub: Dealing with Flaky Tests](https://github.blog/2020-03-24-dealing-with-flaky-tests/) — стратегии GitHub для борьбы с flaky тестами.
