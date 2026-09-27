# Backend ↔ Mobile Integration Testing

## Определения

**API Contract** — соглашение между mobile-клиентом и backend-сервисом о формате запросов и ответов. Включает эндпоинты, методы, параметры, структуру JSON/Proto, статус-коды.

**Contract Testing** — метод тестирования, проверяющий что consumer (mobile app) и provider (backend) соблюдают согласованный контракт, не запуская полную интеграцию.

**Consumer-Driven Contracts** — подход, при котором mobile-команда определяет ожидания от API, а backend-команда гарантирует их выполнение.

**Backward Compatibility** — свойство нового backend-релиза работать со старыми версиями mobile-приложения. Критично для mobile, так как пользователи могут долго не обновляться.

**Schema Migration** — изменение структуры API (поля, форматы, эндпоинты) без breaking старых клиентов. Паттерны: Expand-Contract, versioned API, deprecation headers.

**Mock Service** — имитация backend-сервиса для тестирования mobile-приложения offline. Позволяет decouple mobile-разработку от backend-релизов.

**Service Virtualization** — продвинутый mock, эмулирующий поведение реального сервиса (latency, errors, rate limiting).

**Pact** — инструмент для contract testing, генерирующий pacts между consumer и provider.

**Pact Broker** — хранилище pacts, управление версиями и статусом совместимости consumer/provider.

**Schemathesis** — инструмент для property-based testing на основе OpenAPI/GraphQL схем.

**OpenAPI** — спецификация REST API, описывающая эндпоинты, схемы, аутентификацию.

**Schema Registry** — хранилище версий API схем с историей изменений и совместимостью.

**Sunset Header** — HTTP-заголовок `Sunset`, указывающий дату deprecation эндпоинта.

**Expand-Contract** — паттерн schema migration: расширение схемы новыми полями, миграция клиентов, удаление старых полей.

**API Lifecycle** — жизненный цикл API: design → contract → implement → test → deploy → monitor → deprecate.

**Contract Artifact** — версионированный артефакт (pact file, OpenAPI spec), хранимый в artifact storage.

**Keystone Service** — критичный инфраструктурный сервис, без которого backend integration не работает (Pact Broker, Schema Registry, Mock Service).

**Toil (интеграционное тестирование)** — ручная проверка совместимости API, ручная отправка pacts, ручная проверка schema migration.

**Error Budget (API)** — допустимый процент breaking changes или несовместимых релизов backend в месяц.

**MTTR (Integration)** — среднее время от обнаружения breaking change до фикса или отката.

---

## Базовые концепции

### Mobile ↔ Backend Integration Challenges

**Особенности mobile:**
- **Slow update adoption:** Пользователи могут оставаться на старой версии приложения неделями. Backend должен поддерживать старые контракты.
- **Offline mode:** Приложение работает без сети. Должно gracefully обрабатывать недоступность backend.
- **Version skew:** Разные версии приложения одновременно в production. Backend должен поддерживать multiple contract versions.
- **Network conditions:** Мобильные сети нестабильны (3G/4G/5G, switching). API должен быть resilient к timeouts и retries.
- **App Store review:** Backend изменения могут потребовать нового релиза приложения. Минимизируйте breaking changes.

### Архитектура пайплайна: Backend Integration Lifecycle

Типовой пайплайн backend integration testing в Mobile CI/CD:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Mobile PR   │───►│   Contract   │───►│   Backend    │───►│   Pact       │───►│   Quality    │
│  (Consumer)  │    │   Test       │    │   CI (Prov)  │    │   Broker     │    │   Gate       │
│              │    │              │    │              │    │              │    │              │
│  iOS/Android │    │ Schemathesis │    │  Pact Verify │    │  Store pacts │    │  Block if    │
│  changes     │    │ Pact (CDC)   │    │  OpenAPI val │    │  Can I Deploy│    │  breaking    │
│  API client  │    │              │    │              │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
        │                   │                   │                   │                   │
        ▼                   ▼                   ▼                   ▼                   ▼
   OpenAPI/Pact        Validate            Verify              Versioning            Merge /
   spec change         contract            contract             + status              Deploy
```

**Этапы lifecycle:**

1. **Design:** Mobile-команда создает/обновляет OpenAPI spec или Pact contract.
2. **Contract Test:** Запускается Schemathesis или Pact consumer test на каждый PR mobile-команды.
3. **Provider Verification:** Backend CI запускает Pact provider verification на каждый PR/merge backend-команды.
4. **Broker:** Pact Broker хранит версии pacts, статус совместимости (can-i-deploy).
5. **Quality Gate:** Пайплайн блокируется при breaking change до исправления.
6. **Deploy:** При прохождении всех проверок — деплой backend и mobile.

### Keystone-компоненты инфраструктуры

Для backend integration CI/CD требуются инфраструктурные сервисы:

- **Pact Broker:** Хранилище pacts, веб-UI, API для can-i-deploy. Self-hosted (Ruby/Python) или SaaS.
- **Schema Registry:** Хранилище версий OpenAPI/GraphQL схем. Поддерживает compatibility checking.
- **Mock Service (WireMock/Prism):** Поднимается на macOS-раннерах или dedicated VM для offline-тестирования.
- **Artifact Storage:** Хранилище pact files, OpenAPI specs, mapping. Retention policy: минимум 90 дней.
- **Notification Service:** Slack/Telegram webhook при breaking change.

**Стратегия защиты keystone:**
- Разворачивайте Pact Broker на dedicated VM с hot-standby.
- Резервное копирование pact files daily.
- Мониторинг доступности отдельно от основного пайплайна.

### API Versioning Strategies

| Стратегия | Пример | Плюсы | Минусы |
|:---|:---|:---|:---|
| **URL Versioning** | `/v1/users`, `/v2/users` | Простота, явность | URL загрязнение |
| **Header Versioning** | `X-API-Version: 2` | Чистый URL | Скрыто от разработчиков |
| **Content Negotiation** | `Accept: application/vnd.company.v2+json` | RESTful | Сложность в отладке |
| **Deprecation Headers** | `Sunset: Sat, 31 Dec 2026 23:59:59 GMT` | Graceful migration | Требует клиентской поддержки |

**Рекомендация для mobile:** URL versioning (`/v1/`, `/v2/`) — самый явный и простой для поддержки в mobile-клиенте.

### Backward Compatibility Patterns

**1. Expand-Contract:**
```
Phase 1 (Expand): Backend добавляет новые поля, старые клиенты их игнорируют
Phase 2 (Migrate): Mobile обновляется, начинает использовать новые поля
Phase 3 (Contract): Backend удаляет старые поля
```

**2. Default Values:**
```json
// Новый эндпоинт с новым полем
{
  "id": 123,
  "name": "John",
  "avatar_url": "https://..."  // новое поле, defaults to null
}

// Старый клиент игнорирует новое поле, работает корректно
```

**3. Deprecation Headers:**
```http
Sunset: Sat, 31 Dec 2026 23:59:59 GMT
Deprecation: true
Link: </v2/users>; rel="successor-version"
```

**4. Feature Flags в API:**
- Backend может отдавать разные схемы в зависимости от флага
- Mobile получает compatible schema для своей версии
- Позволяет gradual migration

### Contract Testing для Mobile

**Consumer-Driven Contracts (CDC):**
1. Mobile-команда определяет expectations (Pact/Schemathesis)
2. Backend-команда validates expectations на каждом CI run
3. При breaking change — пайплайн backend падает до деплоя

**Schemathesis:**
- Генерирует тесты из OpenAPI-спецификации
- Проверяет все эндпоинты на корректность
- Property-based testing для edge cases

### Schema Migration Strategies

**Expand-Contract Pattern:**
```
T1: Old client → Old API (v1) ✓
T2: Old client → New API (v2) ✓  // backward compatible
T3: New client → New API (v2) ✓  // uses new fields
T4: Old client → v1 sunset
T5: New client → v2 only
```

**Deprecation Workflow:**
1. Add `Sunset` header to old endpoint
2. Monitor usage of old endpoint
3. Notify mobile teams via audit log
4. After grace period — remove old endpoint

### SRE-подход к Integration

- **Error Budget для API:** Договоритесь о допустимом проценте breaking changes (например, 0 в месяц). При нарушении — freeze на изменения API.
- **MTTR (Integration):** Среднее время от обнаружения breaking change до фикса. Для mobile: < 4 часа.
- **Toil Reduction:** Автоматизируйте contract testing, schema validation, compatibility checks. Измеряйте долю ручной работы.
- **Observability:** Каждое API-изменение должно иметь trace: spec change → contract test → mobile CI → backend CI → deploy.

### Sysadmin: инфраструктура для backend integration

**Pact Broker deployment:**
- Разворачивайте на dedicated VM или macOS-раннере с постоянным IP.
- Используйте systemd/launchd для управления процессом.
- Настройте backup pact files daily.
- Мониторинг: Prometheus exporter или Datadog integration.

**Mock Service infrastructure:**
- WireMock/Prism можно запускать как system service на dedicated VM.
- На macOS-раннерах: используйте `brew install wiremock` вместо Docker для снижения overhead.
- Кэшируйте commonly used mappings.
- Ограничьте ресурсы (RAM/CPU) через launchd limits.

**Artifact Storage:**
- Pact files: храните в GitLab CI artifacts или Nexus/Artifactory с retention 90 дней.
- OpenAPI specs: версионируйте в Git, tag каждый release.
- Mapping files: храните вместе с бинарниками для symbolication.

**Network simulation:**
- Для тестирования на macOS используйте `Network Link Conditioner` (из Additional Tools for Xcode).
- Или `pfctl` для управления bandwidth/queue.

---

## Практические сценарии

### 1. OpenAPI Schema Validation

**Создание OpenAPI спецификации:**
```yaml
# openapi.yaml
openapi: 3.0.3
info:
  title: Mobile API
  version: 2.0.0
paths:
  /v1/users:
    get:
      summary: Get user profile
      responses:
        '200':
          description: User profile
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/User'
components:
  schemas:
    User:
      type: object
      required: [id, name]
      properties:
        id:
          type: integer
        name:
          type: string
        avatar_url:
          type: string
          nullable: true
        created_at:
          type: string
          format: date-time
```

**Schemathesis: Автоматические тесты из OpenAPI:**
```bash
# Установка
pip install schemathesis

# Запуск тестов
st run https://api.company.com/openapi.yaml \
  --checks all \
  --report-mime text \
  --output report.txt
# → 100 passed, 0 failed
```

**GitLab CI:**
```yaml
stages:
  - contract-test

api_contract_validation:
  stage: contract-test
  script:
    - pip install schemathesis
    - st run https://api.company.com/openapi.yaml \
        --checks all \
        --output contract-report.txt
```

### 2. Pact Contract Testing

**Mobile (Consumer) — Pact:**
```javascript
// pact-consumer.js
const { Pact } = require('@pact-foundation/pact');

const provider = new Pact({
  consumer: 'MobileApp',
  provider: 'MobileAPI',
  port: 1234
});

describe('Mobile API Contract', () => {
  beforeAll(() => provider.setup());
  afterAll(() => provider.finalize());

  it('should get user profile', async () => {
    await provider.addInteraction({
      state: 'user 123 exists',
      uponReceiving: 'a request for user 123',
      withRequest: {
        method: 'GET',
        path: '/v1/users/123',
        headers: {
          'Authorization': 'Bearer token'
        }
      },
      willRespondWith: {
        status: 200,
        headers: {
          'Content-Type': 'application/json'
        },
        body: {
          id: 123,
          name: 'John Doe',
          avatar_url: like('https://example.com/avatar.png')
        }
      }
    });

    // Mobile app делает запрос
    const response = await fetch('http://localhost:1234/v1/users/123', {
      headers: { 'Authorization': 'Bearer token' }
    });
    const data = await response.json();

    expect(data.id).toBe(123);
    expect(data.name).toBe('John Doe');
  });
});
```

**Backend (Provider) — Pact Verification:**
```bash
# Загрузка pact и verification
pact-broker publish \
  --consumer-app-version=1.0.0 \
  --branch=main \
  ./pacts \
  --broker-base-url=https://pact-broker.company.com

# Provider verification
pact-broker can-i-deploy \
  --pacticipant=MobileAPI \
  --version=v2.0.0 \
  --to-environment=production
# → YES
```

### 3. Mock Service: WireMock

**Запуск WireMock (self-hosted, без Docker):**
```bash
# macOS через Homebrew
brew install wiremock

# Запуск
wiremock --port 8080 --root-mappings ./mappings
# → Running on http://localhost:8080
```

**Создание mock mappings:**
```json
{
  "request": {
    "method": "GET",
    "url": "/v1/users/123"
  },
  "response": {
    "status": 200,
    "headers": {
      "Content-Type": "application/json"
    },
    "jsonBody": {
      "id": 123,
      "name": "John Doe",
      "avatar_url": "https://example.com/avatar.png"
    }
  }
}
```

**Record/Replay:**
```bash
# Запись реальных запросов
curl -X POST http://localhost:8080/__admin/record/start \
  -H "Content-Type: application/json" \
  -d '{"targetBaseUrl": "https://api.company.com"}'

# Остановка записи
curl -X POST http://localhost:8080/__admin/record/stop
```

### 4. Prism: OpenAPI Mock Server

**Запуск Prism (self-hosted, без Docker):**
```bash
# macOS через Homebrew
brew install stoplight/prism/prism

# Запуск mock из OpenAPI
prism mock openapi.yaml --port 4010
# → http://localhost:4010
```

**Тестирование против mock:**
```bash
curl http://localhost:4010/v1/users/123
# → {"id": 123, "name": "John Doe", ...}

# Negative testing
curl -X POST http://localhost:4010/v1/users \
  -H "Content-Type: application/json" \
  -d '{"invalid": "data"}'
# → 422 Unprocessable Entity (schema validation failed)
```

### 5. Backward Compatibility Testing

**Multi-version API Testing:**
```bash
# Тестирование old client против new API
curl -H "X-Client-Version: 2.0.0" \
  https://api.company.com/v1/users/123
# → 200 OK (backward compatible)

curl -H "X-Client-Version: 1.0.0" \
  https://api.company.com/v2/users/123
# → 200 OK (new API поддерживает old client)
```

**Automated Compatibility Check:**
```yaml
stages:
  - compatibility

api_backward_compatibility:
  stage: compatibility
  image: python:3.11
  rules:
    - changes:
        - 'api/**'
        - openapi.yaml
  script:
    - pip install schemathesis
    - st run openapi.yaml \
        --checks all \
        --output compatibility-report.txt
    # Проверка нет breaking changes
    - if grep -q "BREAKING" compatibility-report.txt; then
        echo "Breaking changes detected!";
        exit 1;
      fi
```

### 6. Offline Mode Testing

**macOS: Network Link Conditioner**
```bash
# Установка Network Link Conditioner из Additional Tools for Xcode
# System Preferences → Network Link Conditioner → включить

# Или через pfctl (современный аналог ipfw)
echo "dummynet-anchor \"nlcm\"" | sudo pfctl -f -
echo "anchor \"nlcm\"" | sudo pfctl -f -
echo "dummynet out pipe 1 ip from any to any" | sudo pfctl -a nlcm -f -
echo "pipe 1 config bw 384Kbit/s delay 100ms" | sudo pfctl -a nlcm -f -
```

**Android: Emulator Network Throttling**
```bash
# Эмулятор: Settings → Network → Speed → GSM
# Или через ADB
adb shell svc wifi disable
adb shell svc data enable

# Проверка offline поведения
adb shell am force-stop com.company.app
adb shell am start -n com.company.app/.MainActivity
# Приложение должно работать в degraded mode
```

**Fastlane: Offline Testing Lane:**
```ruby
lane :offline_tests do
  # Запуск тестов в offline режиме
  run_tests(
    scheme: "MyAppTests",
    devices: ["iPhone 16"],
    only_testing: ["OfflineTests"]
  )
end
```

### 7. Schema Migration Validation

**Expand-Contract Migration Example:**
```json
// T1: Old schema
{
  "id": 123,
  "name": "John"
}

// T2: New schema (expand phase)
{
  "id": 123,
  "name": "John",
  "avatar_url": null,  // новое поле, nullable
  "created_at": null   // новое поле, nullable
}

// T3: New schema (contract phase)
{
  "id": 123,
  "name": "John",
  "avatar_url": "https://...",
  "created_at": "2026-09-26T10:30:00Z"
}
```

**Migration Validation Script:**
```bash
#!/bin/bash
# validate_migration.sh

OLD_SCHEMA="schemas/v1/user.json"
NEW_SCHEMA="schemas/v2/user.json"

# Проверка что все old fields присутствуют в new schema
for field in id name email; do
  if ! jq -e ".properties.$field" "$NEW_SCHEMA" > /dev/null; then
    echo "ERROR: Required field $field missing in new schema"
    exit 1
  fi
done

# Проверка backward compatibility
echo "Schema migration is backward compatible"
```

### 8. Pact Broker: CI Integration

**Установка Pact Broker (self-hosted):**
```bash
# Через Docker (для тестирования)
docker run -d \
  --name pact-broker \
  -p 8080:8080 \
  -e PACT_BROKER_DATABASE_URL=postgres://... \
  pactfoundation/pact-broker

# Или self-hosted на macOS
brew install pact-foundation/tap/pact-broker
pact-broker start --port 8080
```

**GitLab CI: Contract Testing Workflow:**
```yaml
stages:
  - consumer-tests
  - provider-verification

consumer_tests:
  stage: consumer-tests
  tags:
    - macos
    - arm64
  script:
    - npm install
    - npm run test:pact
  allow_failure: true

provider_verification:
  stage: provider-verification
  needs: ["consumer_tests"]
  script:
    - curl -o pacts.zip https://pact-broker.company.com/pacts/provider/MobileAPI/latest/master
    - unzip pacts.zip -d pacts/
    - pact-broker can-i-deploy \
        --pacticipant=MobileAPI \
        --version=$CI_COMMIT_SHA \
        --to-environment=production
```

### 9. Artifact Retention для Contracts

**GitLab CI:**
```yaml
# .gitlab-ci.yml
contract_tests:
  stage: test
  script:
    - npm run test:pact
  artifacts:
    paths:
      - pacts/
    expire_in: 90 days
```

**GitLab CI:**
```yaml
# .gitlab-ci.yml
pact_artifacts:
  stage: deploy
  script:
    - echo "Pact artifacts retained below"
  artifacts:
    paths:
      - pacts/*.json
    expire_in: 90 days
```

---

## Операции и команды

### API Contract Validation

```bash
# Schemathesis: валидация OpenAPI
st run https://api.company.com/openapi.yaml --checks all

# Pact: verification provider
pact-broker publish ./pacts --consumer-app-version=1.0.0
pact-broker can-i-deploy --pacticipant=MobileAPI --version=v2.0.0

# OpenAPI validation
swagger-cli validate openapi.yaml
# → openapi.yaml is valid

# openapi-diff: проверка breaking changes
openapi-diff https://api.company.com/openapi-v1.yaml \
  https://api.company.com/openapi-v2.yaml
# → BREAKING: field 'email' removed
```

### Mock Service Management

```bash
# WireMock: запуск (self-hosted)
brew install wiremock
wiremock --port 8080 --root-mappings ./mappings
# → Running on http://localhost:8080

# WireMock: загрузка mappings
curl -X POST http://localhost:8080/__admin/mappings \
  -H "Content-Type: application/json" \
  -d @mapping.json

# Prism: запуск mock из OpenAPI (self-hosted)
brew install stoplight/prism/prism
prism mock openapi.yaml --port 4010
# → http://localhost:4010

# Prism: запуск через Docker
docker run -d --name prism -p 4010:4010 stoplight/prism:latest \
  mock -h 0.0.0.0 -p 4010 ./openapi.yaml
```

### Schema Migration Testing

```bash
# Проверка compatibility
openapi-diff https://api.company.com/openapi-v1.yaml \
  https://api.company.com/openapi-v2.yaml
# → BREAKING: field 'email' removed

# Или custom script
python scripts/validate_schema_migration.py v1 v2
# → Migration is backward compatible
```

### Pact Broker Management

```bash
# Публикация pact
pact-broker publish ./pacts \
  --consumer-app-version=1.0.0 \
  --branch=main \
  --broker-base-url=https://pact-broker.company.com

# Проверка can-i-deploy
pact-broker can-i-deploy \
  --pacticipant=MobileAPI \
  --version=v2.0.0 \
  --to-environment=production
# → YES

# Получение pacts для provider
pact-broker fetch \
  --pacticipant=MobileAPI \
  --version=v2.0.0 \
  ./pacts/
```

### Network Simulation (macOS)

```bash
# Network Link Conditioner (GUI, из Additional Tools for Xcode)
# System Preferences → Network Link Conditioner → включить

# pfctl (современный CLI, macOS 10.13+)
echo "dummynet-anchor \"nlcm\"" | sudo pfctl -f -
echo "anchor \"nlcm\"" | sudo pfctl -f -
echo "dummynet out pipe 1 ip from any to any" | sudo pfctl -a nlcm -f -
echo "pipe 1 config bw 384Kbit/s delay 100ms" | sudo pfctl -a nlcm -f -

# Проверка правил
sudo pfctl -a nlcm -s rules
# → dummynet out pipe 1 ip from any to any

# Очистка
echo "dummynet-anchor \"nlcm\"" | sudo pfctl -f -
echo "anchor \"nlcm\"" | sudo pfctl -f -
```

---

## Устранение проблем

| Ошибка | Причина | Решение |
|:---|:---|:---|
| **Contract test failed** | Backend изменил schema без уведомления | Откатите изменения или обновите contract, согласуйте с mobile командой |
| **Backward compatibility broken** | Удалено поле, изменен тип данных | Используйте Expand-Contract pattern, никогда не удаляйте поля без deprecation |
| **Schema validation failed** | Mobile отправляет невалидные данные | Добавьте валидацию на клиенте, исправьте backend schema |
| **Mock server out of sync** | Mock устарел относительно реального API | Автоматически генерируйте mock из OpenAPI spec |
| **Pact verification failed** | Provider не соответствует expectations | Обновите Pact или исправьте backend |
| **Offline mode broken** | Приложение падает без сети | Добавьте fallback values, кэширование, degraded mode |
| **API versioning confusion** | Несколько версий API одновременно | Документируйте версионирование, используйте sunset headers |
| **Breaking change in production** | Непротестированное изменение API | Добавьте contract testing в CI, настройте alerting |
| **Slow API response** | Backend regression, network issues | Добавьте timeout и retry на клиенте, мониторьте backend performance |
| **Data format mismatch** | Date format, encoding differences | Стандартизируйте форматы (ISO 8601, UTF-8) |
| **Pact Broker unavailable** | Сервис упал или недоступен | Настройте monitoring, запустите failover instance |
| **WireMock/Prism port conflict** | Порт занят другим процессом | Остановите предыдущий инстанс или измените порт |
| **Schema Registry sync failed** | Проблема с сетью или авторизацией | Проверьте credentials, обновите registry client |
| **Contract artifact missing** | Не настроено сохранение pacts в CI | Добавьте upload artifact в пайплайн с retention 90 дней |
| **Can-I-Deploy returns NO** | Несовместимые pacts, breaking change | Проверьте pact status в broker, исправьте backend или mobile |

---

## Рекомендации

### Best Practices

- **Contract Testing:** Внедрите CDC или Schemathesis для всех критических API. Запускайте на каждом PR.
- **OpenAPI First:** Разрабатывайте API на основе OpenAPI spec. Генерируйте mock и тесты из spec.
- **Backward Compatibility:** Никогда не делайте breaking changes без deprecation period. Используйте Expand-Contract pattern.
- **API Versioning:** Используйте URL versioning для clarity. Sunset старые версии после grace period.
- **Offline by Default:** Проектируйте API с учетом offline mode. Добавьте caching, retry, fallback.
- **Error Budget:** Установите 0 breaking changes per release cycle. При нарушении — freeze на API изменения.
- **Toil Reduction:** Автоматизируйте contract testing, schema validation, compatibility checks.
- **Documentation:** Сопровождайте OpenAPI spec комментариями, примерами, migration guides.
- **Keystone Protection:** Pact Broker и Schema Registry — критичные сервисы. Разворачивайте с hot-standby и мониторингом.
- **Artifact Retention:** Храните pacts и OpenAPI specs минимум 90 дней для compliance и debugging.

### Edge Cases и ограничения

1. **GraphQL schema evolution:** GraphQL требует особого подхода к versioning (no breaking changes, field deprecation).
2. **Binary protocols (Protobuf):** Contract testing сложнее, чем для REST. Используйте schema registry.
3. **Third-party APIs:** Ограниченный контроль над changes. Добавьте adapter layer для изоляции.
4. **WebSocket/SSE:** Stateful protocols требуют special handling для contract testing.
5. **Rate limiting:** Mock должен эмулировать rate limits. Тестируйте retry logic.
6. **Network edge cases:** Packet loss, high latency, DNS failures. Тестируйте в CI.
7. **Time-based logic:** Работа с временными зонами, daylight saving. Стандартизируйте UTC.
8. **Large payloads:** Mobile имеет ограничения по памяти. Тестируйте с большими ответами.
9. **iOS ipfw removal:** Начиная с macOS 10.13, `ipfw` удален. Используйте `pfctl` или `Network Link Conditioner` app.
10. **Docker overhead:** На macOS-раннерах Docker Desktop потребляет значительные ресурсы. Для WireMock/Prism используйте self-hosted binaries.

### SRE-подход к Backend Integration

- **Error Budget для API:** 0 breaking changes per release cycle. При нарушении — freeze на API изменения.
- **MTTR (Integration):** Среднее время от обнаружения breaking change до фикса. Цель: < 4 часа.
- **Toil Reduction:** Автоматизируйте contract testing, schema validation, compatibility checks. Измеряйте долю ручной работы.
- **Observability:** Каждое API-изменение должно иметь trace: spec change → contract test → mobile CI → backend CI → deploy.
- **Runbook:** Создайте runbook для типичных scenarios: "Contract test failed", "Breaking change in production", "Pact Broker down".

### Sysadmin: инфраструктура для backend integration

- **Pact Broker:** Разворачивайте на dedicated VM. Используйте systemd/launchd. Настройте backup daily.
- **Mock Services:** Разворачивайте WireMock/Prism на dedicated VM или macOS-раннерах. Ограничьте ресурсы через launchd.
- **Artifact Storage:** Настройте хранилище pacts/OpenAPI specs с retention 90 дней.
- **Network Simulation:** Настройте Network Link Conditioner или pfctl для тестирования на macOS-раннерах.
- **Certificate Management:** Pact Broker и Schema Registry могут требовать TLS. Управляйте сертификатами через Let's Encrypt или внутренний CA.

---

## Мониторинг и Observability

**Ключевые метрики:**
- **Contract Test Pass Rate:** % успешных contract тестов (цель: 100%)
- **API Breaking Changes:** количество breaking changes per release (цель: 0)
- **Backward Compatibility:** % old clients, поддерживаемых новым API
- **API Latency:** время ответа API (p50, p95, p99)
- **Error Rate:** % ошибок 4xx/5xx
- **Pact Broker Availability:** доступность Pact Broker (цель: 99.9%)
- **Schema Registry Sync:** успешность синхронизации schemas (цель: 100%)
- **Mock Service Uptime:** доступность mock сервисов (цель: 99.5%)

**Alert Rules:**
```yaml
groups:
  - name: api_contract_alerts
    rules:
      - alert: ContractTestFailed
        expr: contract_test_failures_total > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Contract test failed"
      
      - alert: BreakingChangeDetected
        expr: api_breaking_changes_total > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Breaking change detected in API"
      
      - alert: BackwardCompatibilityBroken
        expr: api_backward_compatible == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Backward compatibility broken"
      
      - alert: APIHighLatency
        expr: histogram_quantile(0.95, api_request_duration_seconds) > 0.5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API p95 latency exceeds 500ms"

      - alert: PactBrokerDown
        expr: up{job="pact-broker"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Pact Broker is down"

      - alert: SchemaRegistrySyncFailed
        expr: schema_registry_sync_total{status="failed"} > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Schema Registry sync failed"
```

**Quality Gates:**
- Все contract тесты проходят перед merge
- Нет breaking changes в OpenAPI spec
- Backward compatibility verified для каждого API изменения
- Pact Broker can-i-deploy возвращает YES
- Mock server автоматически генерируется из OpenAPI spec
- Все pacts сохранены в artifact storage

---

## Дополнительная информация

- **[Mobile CI/CD Overview](./index.md)** — архитектура пайплайнов, macOS-раннеры, SRE-подход.
- **[Testing Mobile](./testing-mobile.md)** — XCUITest, Espresso, Appium, device farm.
- **[Deployment Strategies для мобильных приложений](./deployment-strategies-mobile.md)** — Phased Release, Staged Rollout.
- **[Feature Flags в мобильных приложениях](./feature-flags-mobile.md)** — Kill Switch, progressive delivery.
