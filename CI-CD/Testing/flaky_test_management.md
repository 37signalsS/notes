# Управление нестабильными тестами (Flaky Tests)

## Определения

**Flaky Test (Нестабильный тест)** — тест, который проходит и падает без изменений в тестируемом коде. Результат зависит от внешних факторов: времени, состояния сети, параллелизма, ресурсов раннера.

**Test Quarantine (Карантин тестов)** — стратегия изоляции flaky тестов: они перемещаются в отдельный набор и запускаются отдельно, не блокируя основной пайплайн.

**Test Stability Score** — метрика, отражающая стабильность теста за N последних запусков. Рассчитывается как доля успешных запусков.

**Retry Policy** — стратегия автоматического повторного запуска падающих тестов с фиксированным или экспоненциальным backoff.

**Self-Healing Tests** — тесты, которые автоматически адаптируются к изменениям (например, обновляют селекторы при изменении UI).

## Основные концепции

### Причины flaky тестов

| Категория | Примеры | Решение |
| :--- | :--- | :--- |
| **Временна́я зависимость** | `time.sleep()`, проверка даты/времени | Использовать clock mocking, фиксированные timestamp |
| **Параллелизм** | Shared state, file locks, порты | Testcontainers, isolation, random ports |
| **Сеть** | Timeout, DNS resolution,外部 API | Mock external calls, retry, timeout |
| **Ресурсы** | CPU/memory pressure в CI | Выделенные раннеры, resource limits |
| **Порядок выполнения** | Тесты зависят от предыдущих | Полная изоляция, cleanup между тестами |
| **Данные** | Shared test data,脏ые данные | Per-test data, cleanup scripts |
| **UI-тесты** | Анимации, загрузка, race conditions | Wait strategies, stable selectors |

### Метрики flaky тестов

| Метрика | Формула | Целевое значение |
| :--- | :--- | :--- |
| **Flaky Rate** | `flaky_tests / total_tests * 100` | < 1% |
| **Stability Score** | `successful_runs / total_runs` | > 0.99 |
| **Mean Time Between Flakes** | `total_time / flake_count` | > 100 запусков |
| **Quarantine Coverage** | `quarantined / known_flaky * 100` | 100% |

### Стратегии борьбы

1. **Prevention** — правильная архитектура тестов (изоляция, mocking, stable selectors)
2. **Detection** — автоматическое обнаружение через статистику запусков
3. **Quarantine** — изоляция flaky тестов в отдельный набор
4. **Retry** — автоматический retry с лимитом
5. **Root Cause Analysis** — анализ и исправление причины
6. **Removal** — удаление теста, если он не приносит ценности

---

## Практические реализации

### GitHub Actions: retry с rerun

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
          command: pytest tests/ -v
          retry_wait_seconds: 30
```

### GitLab CI: retry для отдельных стадий

```yaml
test:unit:
  stage: test
  script:
    - pytest tests/unit/ -v
  retry:
    max: 2
    when:
      - runner_system_failure
      - stuck_or_timeout_failure

test:integration:
  stage: test
  script:
    - pytest tests/integration/ -v
  retry:
    max: 2
    when:
      - script_failure
```

### Pytest: marker для flaky тестов

```python
import pytest

@pytest.mark.flaky(reruns=3, reruns_delay=5)
def test_external_api_call():
    """Тест внешнего API — может быть нестабильным из-за сети."""
    result = call_external_api()
    assert result.status == "ok"

# conftest.py
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "flaky: mark test as flaky with automatic retries"
    )
```

### Quarantine: отдельный набор тестов

```python
# pytest.ini
[pytest]
markers =
    flaky: known flaky tests (quarantined)
    stable: stable tests (main pipeline)

# conftest.py
import pytest

def pytest_collection_modifyitems(config, items):
    if config.getoption("--quarantine"):
        skip_flaky = pytest.mark.skip(reason="quarantined flaky tests")
        for item in items:
            if "flaky" in item.keywords:
                item.add_marker(skip_flaky)

# Запуск только стабильных тестов
# pytest tests/ -m "not flaky"

# Запуск только flaky тестов (для анализа)
# pytest tests/ -m flaky --quarantine
```

### Python: flaky test detection script

```python
import subprocess
import json
import os
from collections import defaultdict

RESULTS_FILE = "test-results.json"
STABILITY_THRESHOLD = 0.99

def run_tests():
    """Запуск тестов с JUnit-выводом."""
    result = subprocess.run(
        ["pytest", "tests/", "--tb=short", f"--junitxml={RESULTS_FILE}"],
        capture_output=True, text=True
    )
    return result.returncode

def analyze_stability():
    """Анализ стабильности тестов по истории запусков."""
    history_file = "test-history.json"
    
    # Загрузка истории
    if os.path.exists(history_file):
        with open(history_file) as f:
            history = json.load(f)
    else:
        history = defaultdict(lambda: {"success": 0, "total": 0})
    
    # Запуск тестов
    exit_code = run_tests()
    
    # Парсинг результатов
    import xml.etree.ElementTree as ET
    tree = ET.parse(RESULTS_FILE)
    root = tree.getroot()
    
    for testcase in root.findall(".//testcase"):
        name = testcase.get("name")
        history[name]["total"] += 1
        
        failure = testcase.find("failure")
        if failure is None:
            history[name]["success"] += 1
    
    # Сохранение истории
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)
    
    # Анализ flaky тестов
    flaky = []
    for name, stats in history.items():
        if stats["total"] >= 5:  # Минимум 5 запусков для анализа
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

### CI: quarantine workflow

```yaml
# GitLab CI: flaky test detection
flaky_detection:
  stage: test
  script:
    - python scripts/detect_flaky.py
  artifacts:
    when: always
    paths:
      - test-history.json
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

# Запуск flaky тестов отдельно (но не блокируя деплой)
quarantine_tests:
  stage: test
  script:
    - pytest tests/ -m flaky --junitxml=quarantine-results.xml
  allow_failure: true
  artifacts:
    reports:
      junit: quarantine-results.xml
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Тест падает только в CI, не локально | Разные ресурсы, порядок запуска | Использовать Testcontainers, isolated networks |
| Тест «мерцает» каждый запуск | Race condition, shared state | Добавить synchronization, cleanup |
| Retry помогает, но тест медленный | Сеть или таймауты | Увеличить timeout, mock внешние сервисы |
| Все тесты flaky после обновления зависимостей | Взаимодействие с новой версией библиотеки | Pin dependency versions, обновить тесты |
| Flaky test только при параллельном запуске | Порт-конфликты, shared files | Random ports, tmpfs, isolated volumes |

---

## Дополнительная информация

### См. также
- **[Test Reporting & Reliability](../../Github_CI/Test_Reporting_Reliability.md)** — flaky test management в GitHub Actions.
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — AI-driven flaky detection.
- **[Smoke Testing](./smoke_testing.md)** — быстрые post-deploy проверки.
- **[Feature Toggles: Testing](./feature_toggles/implementation.md)** — chaos-тестирование с флагами.

### Внешние ресурсы
- [Flaky Tests at Scale (Netflix)]https://netflixtechblog.com/flaky-test-management-at-scale-6b38e6a7faf2) — подход Netflix.
- [GitHub: Dealing with Flaky Tests](https://github.blog/2020-03-24-dealing-with-flaky-tests/) — GitHub Actions retry.
- [pytest-rerunfailures](https://pytest-rerunfailures.readthedocs.io/) — плагин для retry в Pytest.
