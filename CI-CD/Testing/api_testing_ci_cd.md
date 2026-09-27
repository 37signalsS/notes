# API Тестирование в CI/CD

## Определения

**API Тестирование** — проверка корректности функционирования программных интерфейсов (REST, gRPC, GraphQL) на уровне запрос-ответ, без проверки пользовательского интерфейса.

**Contract Testing (Контрактное тестирование)** — проверка соответствия ожиданиям потребителя API (Consumer) и поведению поставщика (Producer). Подробнее см. в **[Контрактное тестирование](./contract_testing_ci_cd.md)**.

**Schema Validation** — валидация структуры ответа API (JSON Schema, OpenAPI Spec) на соответствие определенной спецификации.

**Newman** — CLI-обертка над Postman-коллекциями для запуска API-тестов в CI/CD без GUI.

**Testcontainers** — библиотека для запуска эфемерных зависимостей (базы данных, брокеры сообщений) в Docker-контейнерах во время тестов. Подробнее см. в **[Testcontainers Overview](../../Testing/testcontainers_overview.md)**.

## Основные концепции и архитектура

### Уровни API-тестирования

API-тесты существуют на разных уровнях зоны тестирования. Выбор уровня зависит от скорости, изоляции и покрытия.

| Уровень | Что проверяется | Инструменты | Характеристики |
| :--- | :--- | :--- | :--- |
| **Unit (Handler/Controller)** | Логика обработки запроса без сети | Go `httptest`, Python `FastAPI TestClient`, Java `MockMvc` | Быстрый, изолированный, без внешних зависимостей |
| **Integration (Service + DB)** | Полный стек: handler → service → DB | Testcontainers + HTTP-клиент | Средняя скорость, проверяет реальные взаимодействия |
| **Contract** | Соответствие спецификации OpenAPI/Protobuf | Pact, Schemathesis, Dredd | Гарантирует совместимость Consumer и Producer |
| **E2E (Full Stack)** | API через реальный HTTP из внешней среды | Postman/Newman, curl, k6 | Медленный, проверяет полный путь в инфраструктуре |

### Что проверять в API-тестах

- **Статус-коды:** 200, 201, 400, 401, 403, 404, 500
- **Структура ответа:** JSON Schema, обязательные поля, типы данных
- **Бизнес-логика:** правильность вычислений, валидация данных
- **Пагинация:** offset, cursor, total count
- **Аутентификация и авторизация:** Bearer token, API key
- **Rate limiting:** 429 Too Many Requests
- **Границы:** empty body, missing fields, special characters

### Жизненный цикл API-теста в CI/CD

1. **Trigger:** push, merge request, schedule, manual
2. **Environment provisioning:** поднятие зависимостей (Testcontainers, docker-compose)
3. **Execution:** запуск тестов с фиксацией артефактов (JUnit, coverage, HTML-отчеты)
4. **Quality Gate:** проверка pass rate, порогов покрытия, отсутствие критических утечек
5. **Reporting:** публикация артефактов, уведомления, метрики в мониторинг
6. **Cleanup:** остановка контейнеров, удаление временных файлов

## Практические сценарии

### Python: интеграционные API-тесты с Testcontainers

```python
import pytest
import requests
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="module")
def api_base_url():
    """Запуск API-сервера с тестовой БД."""
    with PostgresContainer("postgres:16") as postgres:
        import subprocess, time, os
        env = {
            "DATABASE_URL": postgres.get_connection_url(),
            "PORT": "8080"
        }
        proc = subprocess.Popen(
            ["python", "-m", "uvicorn", "main:app", "--port", "8080"],
            env={**os.environ, **env}
        )
        time.sleep(5)
        yield "http://localhost:8080"
        proc.terminate()

class TestProductsAPI:
    def test_list_products(self, api_base_url):
        resp = requests.get(f"{api_base_url}/api/products")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)
    
    def test_create_product_validation(self, api_base_url):
        resp = requests.post(f"{api_base_url}/api/products", json={})
        assert resp.status_code == 422
    
    def test_create_product(self, api_base_url):
        resp = requests.post(f"{api_base_url}/api/products", json={
            "name": "Test Product",
            "price": 29.99
        })
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test Product"
    
    def test_get_nonexistent_product(self, api_base_url):
        resp = requests.get(f"{api_base_url}/api/products/99999")
        assert resp.status_code == 404
```

### Go: API-тесты с `httptest`

```go
package handlers_test

import (
    "net/http"
    "net/http/httptest"
    "testing"
    "encoding/json"
    "github.com/stretchr/testify/assert"
)

func TestGetHealth(t *testing.T) {
    req := httptest.NewRequest("GET", "/health", nil)
    w := httptest.NewRecorder()
    
    handler(w, req)
    
    assert.Equal(t, http.StatusOK, w.Code)
    
    var body map[string]string
    json.Unmarshal(w.Body.Bytes(), &body)
    assert.Equal(t, "ok", body["status"])
}

func TestCreateOrder_ValidationError(t *testing.T) {
    req := httptest.NewRequest("POST", "/api/orders", strings.NewReader(`{}`))
    req.Header.Set("Content-Type", "application/json")
    w := httptest.NewRecorder()
    
    handler(w, req)
    
    assert.Equal(t, http.StatusUnprocessableEntity, w.Code)
}
```

### Newman: запуск Postman-коллекций в CI

```bash
# Установка Newman
npm install -g newman

# Запуск коллекции
newman run collections/api-tests.json \
  --environment collections/env-staging.json \
  --reporters cli,html \
  --reporter-html-export results/newman-report.html \
  --timeout-request 10000

# Проверка exit code
if [ $? -ne 0 ]; then
  echo "API tests failed"
  exit 1
fi
```

### curl: smoke-тесты для API

```bash
#!/bin/bash
set -euo pipefail
BASE_URL="${API_URL:-http://localhost:8080}"

assert_status() {
  local method=$1 path=$2 expected=$3 body=${4:-}
  
  if [ -n "$body" ]; then
    actual=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" \
      -H "Content-Type: application/json" -d "$body" "${BASE_URL}${path}")
  else
    actual=$(curl -s -o /dev/null -w "%{http_code}" -X "$method" "${BASE_URL}${path}")
  fi
  
  if [ "$actual" != "$expected" ]; then
    echo "FAIL: $method $path → $actual (expected $expected)"
    exit 1
  fi
  echo "OK: $method $path → $actual"
}

assert_status GET /health 200
assert_status GET /api/products 200
assert_status GET /api/products/1 200
assert_status GET /api/products/99999 404
assert_status POST /api/products 401
assert_status POST /api/products 201 '{"name":"Test","price":10}'
assert_status POST /api/products 422 '{}'
```

### Schema Validation: OpenAPI в тестах

#### Schemathesis: автоматическая генерация тестов из OpenAPI

```bash
# Установка
pip install schemathesis

# Запуск автоматических тестов из OpenAPI-спецификации
st run http://localhost:8080/openapi.json \
  --checks all \
  --hypothesis-max-examples=100 \
  --junitxml=results/schemathesis.xml
```

#### Python: валидация JSON Schema

```python
import jsonschema
import requests

def test_product_schema():
    resp = requests.get("http://localhost:8080/api/products/1")
    
    schema = {
        "type": "object",
        "required": ["id", "name", "price"],
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string", "minLength": 1},
            "price": {"type": "number", "minimum": 0}
        }
    }
    
    jsonschema.validate(instance=resp.json(), schema=schema)
```

## Операции и команды

### CLI-инструменты для API-тестирования

| Инструмент | Назначение | Основные команды |
| :--- | :--- | :--- |
| **Newman** | Запуск Postman-коллекций в CI | `newman run <collection.json> --environment <env.json> --reporters cli,junit` |
| **curl** | HTTP-запросы для smoke-тестов | `curl -s -o /dev/null -w "%{http_code}" -X GET <url>` |
| **httpie** | Удобная альтернатива curl | `http GET <url> Authorization:"Bearer <token>"` |
| **grpcurl** | gRPC-эквивалент curl | `grpcurl -plaintext localhost:50051 list` |
| **Schemathesis** | Property-based тесты из OpenAPI | `st run <openapi.json> --checks all --hypothesis-max-examples=100` |
| **Dredd** | Валидация API по Blueprint/OpenAPI | `dredd <api-url> <spec-file> --namespaces "*"` |
| **Prism** | Mock-сервер из OpenAPI | `prism mock openapi.yaml --port 4010` |
| **wait-for-it** | Ожидание доступности сервиса | `wait-for-it.sh localhost:8080 -- timeout 30` |

### Параметры Newman

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `--environment` | Файл окружения с переменными | `--environment env/ci.json` |
| `--reporters` | Форматы отчета | `--reporters cli,junit,html` |
| `--reporter-html-export` | Путь к HTML-отчету | `--reporter-html-export results/report.html` |
| `--timeout-request` | Таймаут запроса (мс) | `--timeout-request 30000` |
| `--delay-request` | Задержка между запросами (мс) | `--delay-request 100` |
| `--iteration-count` | Количество итераций | `--iteration-count 5` |
| `--bail` | Остановка при первой ошибке | `--bail` |
| `--exit-code` | Установить exit code при ошибках | `--exit-code 1` |

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Connection refused` на localhost | Сервис еще не запущен | Использовать `wait-for-it.sh` или health-check перед тестами |
| `401 Unauthorized` в тестах | Отсутствует тестовый токен | Настроить test user / API key в CI-переменных секретах |
| Тесты проходят локально, падают в CI | Разные окружения (env vars, ports, network policies) | Использовать Testcontainers для полной изоляции окружения |
| Newman падает с timeout | Медленный API в CI, ресурсный contention | Увеличить `--timeout-request`, добавить retry с backoff |
| Schema validation ошибки | API возвращает лишние/отсутствующие поля | Обновить OpenAPI-спецификацию или исправить API |
| Race condition в параллельных тестах | Тесты используют одни и те же данные | Каждый тест создает и удаляет свои данные через fixtures |
| `429 Too Many Requests` | Rate limiting включен в API | Использовать уникальные идентификаторы, настройка лимитов в тестовом окружении |
| `SSL certificate verify failed` | Самоподписанный сертификат в тестовом окружении | Добавить `-k` в curl или настроить `NODE_TLS_REJECT_UNAUTHORIZED=0` для Newman |

### Диагностика в air-gapped средах

При отсутствии доступа к внешним репозиториям:

```bash
# Проверка DNS-резолвинга внутренних сервисов
nslookup api.internal.company.local

# Проверка доступности порта
nc -zv api.internal.company.local 8080

# Проверка TLS-сертификата
openssl s_client -connect api.internal.company.local:443 -servername api.internal.company.local
```

## Best Practices

### Проектирование тестов

- **Изоляция:** каждый тест создает и удаляет свои данные; нет разделения состояния между тестами
- **Идемпотентность:** повторный запуск того же теста дает тот же результат
- **Стабильность:** избегайте sleep(); используйте явные ожидания (polling) на готовность сервиса
- **Скорость:** unit-тесты < 50ms, integration < 2s, E2E < 10s на тест

### Pipeline

- **Quality Gates:** fail-fast на unit-уровне, progressive testing (сначала быстрые, потом медленные)
- **Параллелизм:** запуск независимых тестовых файлов параллельно
- **Кэширование:** зависимостей (pip, npm) и артефактов между стадиями
- **Retry policy:** не более 2-3 повторений для flaky-тестов с экспоненциальным backoff
- **Artifacts:** сохранение JUnit, HTML-отчетов, логов на каждой стадии

### Observability

- **Pass rate tracking:** SLO на pass rate API-тестов (например, 99% за 7 дней)
- **Flaky detection:** автоматическое помещение тестов с нестабильным результатом в карантин
- **Performance baseline:** отслеживание latency P95/P99 по эндпоинтам
- **Alerting:** paging при падении pass rate ниже порога

### Безопасность

- **Секреты:** хранение API-ключей и токенов в CI-секретах, never in code
- **Network segmentation:** размещение CI-раннеров в отдельном VLAN с минимально необходимыми доступом
- **Test data:** использование синтетических данных, never production data
- **Rate limits в тестах:** настройка отдельного rate limit для тестового API-ключа

### Air-gapped среды

- **Offline dependencies:** локальные кэши модулей (pip, npm, Go modules)
- **Internal registry:** размещение образов Testcontainers во внутреннем registry
- **Mirroring:** зеркалирование документации OpenAPI и stub-сервисов

## Дополнительная информация

### См. также

* **[Контрактное тестирование](./contract_testing_ci_cd.md)** — Pact, consumer-driven contracts.
* **[Testcontainers Overview](../../Testing/testcontainers_overview.md)** — изолированные контейнеры для тестов.
* **[Тестирование типов: Unit, Integration, E2E](../../Testing/testing_types_unit_integration_e2e.md)** — пирамида тестирования.

### Внешние ресурсы

* [Postman Newman](https://learning.postman.com/docs/running-collections/using-newman-cli/command-line-integration/) — CLI для Postman-коллекций.
* [Schemathesis](https://schemathesis.readthedocs.io/) — автоматическое тестирование API из OpenAPI.
* [Prism](https://stoplight.io/open-source/prism) — mock-сервер из OpenAPI-спецификации.
