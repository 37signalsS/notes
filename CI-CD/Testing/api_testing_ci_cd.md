# API Тестирование в CI/CD

## Определения

**API Тестирование** — проверка корректности функционирования программных интерфейсов (REST, gRPC, GraphQL) на уровне запрос-ответ, без проверки пользовательского интерфейса.

**Contract Testing (Контрактное тестирование)** — проверка соответствия ожиданиям потребителя API (Consumer) и поведению поставщика (Producer). Подробнее см. в **[Контрактное тестирование](./contract_testing_ci_cd.md)**.

**Schema Validation** — валидация структуры ответа API (JSON Schema, OpenAPI Spec) на соответствие определенной спецификации.

**Newman** — CLI-обертка над Postman-коллекциями для запуска API-тестов в CI/CD без GUI.

## Основные концепции

### Уровни API-тестирования

| Уровень | Что проверяется | Инструменты |
| :--- | :--- | :--- |
| **Unit (Handler/Controller)** | Логика обработки запроса без сети | Go `httptest`, Python `FastAPI TestClient`, Java `MockMvc` |
| **Integration (Service + DB)** | Полный стек: handler → service → DB | Testcontainers + HTTP-клиент |
| **Contract** | Соответствие спецификации OpenAPI/Protobuf | Pact, Schemathesis, Dredd |
| **E2E (Full Stack)** | API через реальный HTTP из внешней среды | Postman/Newman, curl, k6 |

### Что проверять в API-тестах

- Статус-коды (200, 201, 400, 401, 403, 404, 500)
- Структура ответа (JSON Schema, обязательные поля)
- Бизнес-логика (правильность вычислений, валидация данных)
- Пагинация (offset, cursor, total count)
- Аутентификация и авторизация (Bearer token, API key)
- Rate limiting (429 Too Many Requests)
- Границы (empty body, missing fields, special characters)

---

## Практические реализации

### Python: интеграционные API-тесты с Testcontainers

```python
import pytest
import requests
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="module")
def api_base_url():
    """Запуск API-сервера с тестовой БД."""
    with PostgresContainer("postgres:16") as postgres:
        # Настройка и запуск API-сервера
        import subprocess, time
        env = {
            "DATABASE_URL": postgres.get_connection_url(),
            "PORT": "8080"
        }
        proc = subprocess.Popen(
            ["python", "-m", "uvicorn", "main:app", "--port", "8080"],
            env={**os.environ, **env}
        )
        time.sleep(5)  # Ожидание запуска
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
        assert resp.status_code == 422  # Validation error
    
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

# Проверка health
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

---

### GitLab CI: API-тесты

```yaml
stages:
  - build
  - test
  - api_test

api_integration:
  stage: api_test
  image: python:3.12-slim
  services:
    - postgres:16
  variables:
    DATABASE_URL: "postgresql://test:test@postgres/testdb"
  script:
    - pip install -r requirements-test.txt
    - pytest tests/api/ --junitxml=results/api-results.xml --tb=short
  artifacts:
    reports:
      junit: results/api-results.xml

newman_api:
  stage: api_test
  image: postman/newman:latest
  script:
    - newman run collections/api-tests.json \
        --environment collections/env-ci.json \
        --reporters cli,junit \
        --reporter-junit-export results/newman.xml
  artifacts:
    reports:
      junit: results/newman.xml
```

### GitHub Actions: API-тесты

```yaml
name: API Tests
on: [pull_request]

jobs:
  api:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: testdb
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports: ['5432:5432']
    steps:
      - uses: actions/checkout@v4
      
      - name: Run API integration tests
        run: |
          pip install -r requirements-test.txt
          DATABASE_URL=postgresql://test:test@localhost:5432/testdb \
            pytest tests/api/ -v --tb=short
      
      - name: Run Newman
        run: |
          npm install -g newman
          newman run collections/api-tests.json \
            --environment collections/env-ci.json
```

---

## Schema Validation: OpenAPI в тестах

### Schemathesis: автоматическая генерация тестов из OpenAPI

```bash
# Установка
pip install schemathesis

# Запуск автоматических тестов из OpenAPI-спецификации
st run http://localhost:8080/openapi.json \
  --checks all \
  --hypothesis-max-examples=100 \
  --junitxml=results/schemathesis.xml
```

### Python: валидация JSON Schema

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

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| API test падает с `Connection refused` | Сервис еще не запущен | Добавить wait-for-it или health-check перед тестами |
| `401 Unauthorized` в тестах | Отсутствует тестовый токен | Настроить test user / API key в CI-переменных |
| Тесты проходят локально, падают в CI | Разные окружения (env vars, ports) | Использовать Testcontainers для изоляции |
| Newman падает с timeout | Медленный API в CI | Увеличить `--timeout-request` до 30 сек |
| Schema validation ошибки | API возвращает лишние поля | Обновить OpenAPI-спецификацию или исправить API |
| Race condition в параллельных тестах | Тесты используют одни и те же данные | Каждый тест создает и удаляет свои данные |

---

## Дополнительная информация

### См. также
- **[Контрактное тестирование](./contract_testing_ci_cd.md)** — Pact, PactFlow, consumer-driven contracts.
- **[Тестирование типов: Unit, Integration, E2E](../../Testing/testing_types_unit_integration_e2e.md)** — пирамида тестирования.
- **[Testcontainers](../../Testing/testcontainers_overview.md)** — изолированные контейнеры для тестов.
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — Quality Gates, TIA.
- **[gRPC Overview](../../Networking/ServicesAndTools/grpc_overview.md)** — gRPC, grpcurl, health checking.

### Внешние ресурсы
- [Postman Newman](https://learning.postman.com/docs/running-collections/using-newman-cli/command-line-integration/) — CLI для Postman-коллекций.
- [Schemathesis](https://schemathesis.readthedocs.io/) — автоматическое тестирование API из OpenAPI.
- [Prism](https://stoplight.io/open-source/prism) — mock-сервер из OpenAPI-спецификации.
