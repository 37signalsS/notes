# Контрактное тестирование в CI/CD

## Определения

**Contract Testing (Контрактное тестирование)** — проверка взаимодействия между сервисами на основе формализованного соглашения (контракта). Гарантирует, что поставщик (Producer) удовлетворяет ожиданиям потребителя (Consumer) без полного развёртывания всех сервисов.

**Consumer-Driven Contract (CDC)** — контракт, определяемый потребителем API. Потребитель описывает свои ожидания (запросы и ответы), а поставщик обязан их выполнять.

**Pact** — открытый инструмент для CDC-тестирования. Потребитель генерирует контракт, Pact Broker хранит и валидирует его, поставщик проверяет соответствие.

**Bi-directional Contract Testing (BDCT)** — двунаправленное контрактное тестирование (PactFlow). Контракты проверяются в обе стороны: потребитель проверяет ожидания, а поставщик — стабы потребителя.

**Pact Broker** — сервер для хранения, версионирования и проверки контрактов. Интегрируется с CI/CD через `can-i-deploy`.

## Основные концепции

### Зачем контрактное тестирование

| Проблема | Решение |
| :--- | :--- |
| Микросервис A изменил API, сервис B сломался | CDC-контракт гарантирует обратную совместимость |
| Интеграционные тесты требуют все сервисы одновременно | Контракты проверяются без деплоя всех сервисов |
| Несколько потребителей одного API | Pact Broker показывает, какие контракты нарушены |
| Деплой без согласования | `can-i-deploy` блокирует деплой при нарушении контракта |

### Жизненный цикл CDC в CI/CD

1. **Consumer** пишет тест, описывающий ожидания от API
2. **Consumer CI** генерирует контракт (Pact file)
3. **Pact Broker** хранит контракт и проверяет версии
4. **Provider CI** запускает `pact-provider-verifier` для проверки контракта
5. **`can-i-deploy`** проверяет, безопасно ли деплоить consumer/provider

### Сравнение инструментов

| Инструмент | Тип | Язык | Особенности |
| :--- | :--- | :--- | :--- |
| **Pact** | CDC | JS, Ruby, Java, Go, Python | Стандарт де-факто, Pact Broker, `can-i-deploy` |
| **PactFlow** | CDC + BDCT | Multi-language | Commerical, Pact в обе стороны, GitHub Actions |
| **Specmatic** | CDC + Stub | Multi-language | OpenAPI → контракт, stub-сервер |
| **Spring Cloud Contract** | CDC | Java | Встроенный в Spring, Verifier |
| **Dredd** | API Blueprint / OpenAPI | Multi-language | Валидация по спецификации |

---

## Практические реализации

### Pact:.consumer-тест (JavaScript)

```javascript
const { Pact } = require('@pact-foundation/pact');
const axios = require('axios');

describe('Consumer Pact Test', () => {
  const provider = new Pact({
    consumer: 'FrontendApp',
    provider: 'UserService',
    port: 1234,
  });

  beforeAll(() => provider.setup());
  afterAll(() => provider.finalize());

  describe('get user by ID', () => {
    beforeEach(() => {
      return provider.addInteraction({
        state: 'user with ID 123 exists',
        uponReceiving: 'a request for user 123',
        withRequest: {
          method: 'GET',
          path: '/users/123',
          headers: { Accept: 'application/json' },
        },
        willRespondWith: {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
          body: {
            id: 123,
            name: 'John Doe',
            email: 'john@example.com',
          },
        },
      });
    });

    it('returns user data', async () => {
      const response = await axios.get('http://localhost:1234/users/123');
      expect(response.data).toEqual({
        id: 123,
        name: 'John Doe',
        email: 'john@example.com',
      });
    });
  });
});
```

### Pact: provider-тест (Python)

```python
import pytest
from pact import Verifier

PACT_BROKER_URL = "http://pact-broker:9292"
PROVIDER_NAME = "UserService"
PROVIDER_BASE_URL = "http://localhost:8080"

def test_pact_provider():
    """Проверка всех контрактов из Pact Broker."""
    verifier = Verifier(
        provider=PROVIDER_NAME,
        provider_base_url=PROVIDER_BASE_URL,
        publish_verification_results=True,
        provider_version="1.0.0",
    )
    
    output, _ = verifier.verify_pacts(
        f"{PACT_BROKER_URL}/pacts/provider/{PROVIDER_NAME}/latest",
        enable_pending=True,
        verbose=True,
    )
    assert output == 0
```

### Pact Broker: can-i-deploy

```bash
# Проверка: можно ли деплоить consumer v1.2.3?
pact-broker can-i-deploy \
  --pacticipant FrontendApp \
  --version 1.2.3 \
  --broker-base-url http://pact-broker:9292

# Проверка между двумя версиями
pact-broker can-i-deploy \
  --pacticipant FrontendApp \
  --version 1.2.3 \
  --to-environment production

# Деплой с пометкой в Pact Broker
pact-broker record-deployment \
  --pacticipant FrontendApp \
  --version 1.2.3 \
  --environment production
```

### Specmatic: OpenAPI → контракт

```bash
# Установка
npm install -g @specmatic/specmatic

# Генерация stub из OpenAPI
specmatic stub --port 8080 openapi.yaml

# Проверка контракта
specmatic test openapi.yaml --host localhost --port 8080

# Проверка контракта в CI
specmatic test openapi.yaml \
  --host api.example.com \
  --port 443 \
  --https \
  --result-json results/specmatic.json
```

---

### GitLab CI: Pact workflow

```yaml
stages:
  - test
  - contract
  - deploy

# Consumer: генерация контракта
pact_consumer:
  stage: contract
  image: node:20
  script:
    - npm ci
    - npm run test:pact
    - npx @pact-foundation/pact-cli publish ./pacts \
        --consumer-app-version=${CI_COMMIT_SHA} \
        --broker-base-url=${PACT_BROKER_URL}
  artifacts:
    paths:
      - pacts/

# Provider: проверка контракта
pact_provider:
  stage: contract
  image: python:3.12
  services:
    - postgres:16
  script:
    - pip install -r requirements.txt
    - python -m uvicorn main:app --port 8080 &
    - sleep 5
    - |
      docker run --rm \
        --network host \
        pactfoundation/pact-verification-service:latest \
        --provider-app-url=http://localhost:8080 \
        --pact-url=http://pact-broker:9292/pacts/provider/UserService/latest \
        --provider-version=${CI_COMMIT_SHA} \
        --publish-verification-results=true

# can-i-deploy
can_i_deploy:
  stage: deploy
  image: pactfoundation/pact-cli:latest
  script:
    - pact-broker can-i-deploy \
        --pacticipant FrontendApp \
        --version ${FRONTEND_SHA} \
        --broker-base-url=${PACT_BROKER_URL} || exit 1
    - pact-broker can-i-deploy \
        --pacticipant UserService \
        --version ${CI_COMMIT_SHA} \
        --broker-base-url=${PACT_BROKER_URL} || exit 1
```

### GitHub Actions: Pact + PactFlow

```yaml
name: Contract Tests
on: [pull_request]

jobs:
  consumer:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci && npm run test:pact
      - uses: pact-foundation/actions-pact-broker/publish-pact-docker-action@v2.0.0
        with:
          pact-files: 'pacts/'
          pact-broker-url: ${{ secrets.PACTFLOW_URL }}
          pact-broker-token: ${{ secrets.PACTFLOW_TOKEN }}
          consumer-app-version: ${{ github.sha }}
  
  provider:
    runs-on: ubuntu-latest
    needs: consumer
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: python -m uvicorn main:app --port 8080 &
      - uses: pact-foundation/actions-pact-broker/verify-contract-docker-action@v2.0.0
        with:
          provider: UserService
          provider-base-url: http://localhost:8080
          pact-broker-url: ${{ secrets.PACTFLOW_URL }}
          pact-broker-token: ${{ secrets.PACTFLOW_TOKEN }}
          provider-app-version: ${{ github.sha }}
  
  can-i-deploy:
    runs-on: ubuntu-latest
    needs: [consumer, provider]
    steps:
      - uses: pact-foundation/actions-pact-broker/can-i-deploy-docker-action@v2.0.0
        with:
          pacticipant: FrontendApp
          version: ${{ github.sha }}
          to-environment: staging
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `can-i-deploy` говорит "no" | Контракт нарушён или отсутствует | Проверить Pact Broker UI, исправить provider или consumer |
| Provider verification fails | Provider изменил API без обновления контракта | Обновить контракт в consumer, перезапустить provider verification |
| Pact Broker не доступен из CI | Сетевая проблема / неправильный URL | Проверить DNS, firewall, `--broker-base-url` |
| Контракт устарел (stale) | Consumer не обновляет контракт | Настроить `--enable-pending` для игнорирования старых контрактов |
| Consumer тесты проходят, но provider падает | Стейты (states) не реализованы на provider | Реализовать все `state` handlers на provider |
| Pact verification doesn't publish results | Нет `--publish-verification-results` | Добавить флаг и `--provider-version` |

---

## Дополнительная информация

### См. также
- **[API Тестирование](./api_testing_ci_cd.md)** — REST/gRPC тесты, Newman, Schema Validation.
- **[Тестирование типов: Unit, Integration, E2E](../../Testing/testing_types_unit_integration_e2e.md)** — Pact workflow, BDCT.
- **[TDD/BDD Overview](./tdd_bdd_overview.md)** — CDC в контексте TDD/BDD.
- **[Event-Driven Architecture](../../Concepts/event-driven-architecture.md)** — Spring Cloud Contract.

### Внешние ресурсы
- [Pact Documentation](https://docs.pact.io/) — официальная документация Pact.
- [PactFlow](https://pactflow.io/) — commercial Pact-сервис.
- [Specmatic](https://specmatic.in/) — OpenAPI → контракт.
- [Spring Cloud Contract](https://spring.io/projects/spring-cloud-contract) — CDC для Spring.
