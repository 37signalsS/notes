# Виды тестирования: Unit, Integration, E2E

## 1. Определения

**Пирамида тестирования (Testing Pyramid)** — классическая модель, описывающая иерархию тестов. Основание составляют многочисленные быстрые Unit-тесты, середину — интеграционные, вершину — минимальное количество E2E-тестов.

**Тестовый трофей (Testing Trophy)** — современная модель (доминирует во Frontend: React/Vue), где основной фокус смещён на интеграционные тесты, дающие максимальный баланс между скоростью и уверенностью. В 2026 году статический анализ стал фундаментальным слоем трофея: `tsc`/ESLint/Biome ловят ошибки типов и стилистику до запуска тестов, Unit-тесты пишутся только для чистых функций и сложной логики, интеграционные составляют основную массу набора (примерно 60%), а E2E остаётся тонким слоем из критических пользовательских сценариев.

**Testing Honeycomb (Тестовая «сотовая» модель)** — модель, предложенная инженерами Spotify и применяемая в бэкенде и микросервисной архитектуре, где пирамида не работает из-за большого числа внешних связей. Фокус смещён на контрактное тестирование и тесты на границах компонентов (Contract/API-level), что позволяет верифицировать взаимодействие большого числа сервисов без запуска всей системы.

**Unit-тесты (Модульные)** — проверка минимально изолированной части кода (функции, метода) в полной изоляции с использованием дублёров (Mocks/Stubs).

**Integration-тесты (Интеграционные)** — проверка взаимодействия между несколькими компонентами (например, код + БД) или между микросервисами.

**Contract Testing (Контрактное тестирование)** — верификация совместимости между потребителем (Consumer) и поставщиком (Provider) API без запуска всей системы.

**End-to-End (E2E) тесты (Сквозные)** — имитация реальных сценариев пользователя через все слои системы (UI → API → DB).

**Smoke-тесты (Дымовые)** — минимальный набор проверок, подтверждающий, что развёрнутое приложение запускается и основные функции работают. Выполняются после деплоя или сборки артефакта.

**Sanity-тесты (Проверка работоспособности)** — узкий набор проверок после внесения небольших изменений (bug fix, минорный релиз), подтверждающий, что конкретный функционал не сломан.

**Regression-тесты (Регрессионные)** — повторный прогон тестов после изменений для подтверждения, что существующая функциональность не затронута. Включают Unit, Integration и подмножество E2E.

**Test Fixture** — подготовка окружения и данных, необходимых для выполнения теста (временная БД, конфиг, фикстуры).

**Mock / Stub / Spy** — дублёры зависимостей: Mock заменяет объект и проверяет взаимодействия; Stub возвращает фиксированные ответы; Spy оборачивает реальный объект для регистрации вызовов.

## 2. Основные концепции

### Сравнение моделей: Пирамида vs Трофей

Выбор стратегии зависит от архитектуры приложения:

| Модель | Фокус | Сценарий использования |
| :--- | :--- | :--- |
| **Пирамида** | Unit-тесты | Монолиты, сложные алгоритмы, тяжелая бизнес-логика. |
| **Трофей** | Интеграционные тесты | Frontend (React/Vue), микросервисная архитектура. |
| **Ромб (Diamond)** | Интеграционные + Unit | Сбалансированные системы с умеренным количеством внешних связей. |
| **Соты (Honeycomb, Spotify)** | Contract / API-тесты | Бэкенд с большим числом внешних связей и микросервисами. |

### Современные виды тестирования (2025–2026)

*   **Contract Testing (Pact):** Позволяет избежать "Breaking Changes" в микросервисах через верификацию взаимодействий.
    *   **Pact Broker:** Центральный узел для хранения контрактов (Pacts) и результатов их верификации. Обеспечивает визуализацию зависимостей и управление **Matrix** (матрицей совместимости версий).
    *   **Workflow (CDCT):** Consumer генерирует контракт (`pact.json`) → публикует в Broker → Provider скачивает контракт → прогоняет тесты на своей стороне → публикует результат верификации обратно в Broker.
    *   **can-i-deploy:** CLI-утилита, которая опрашивает Broker перед деплоем: «совместима ли версия Consumer X с версией Provider Y, которая сейчас в Production?». Блокирует деплой при нарушении контракта.
    *   **Bi-directional Contract Testing (BDCT):** Стандарт 2026 года для команд с разными стеками. Провайдер публикует свою OpenAPI-спецификацию, а потребитель — подмножество, которое реально использует; брокер (PactFlow) статически сравнивает их. Важно: требует **self-verification** провайдера (через Schemathesis или Drift) для подтверждения соответствия реализации схеме.
*   **Visual Regression Testing:** Проверка визуальной целостности интерфейса путем сравнения скриншотов с эталоном (Baseline). Подробное руководство по настройке в CI/CD: **[Visual Regression в CI/CD](../CI-CD/Testing/visual-regression-cicd.md)**.
*   **Trace-based Testing (Observability-driven):** Использование OpenTelemetry для проверки "внутренностей" процесса. Тест проверяет не только HTTP-ответ, но и наличие конкретных спанов (spans) в трейсе (например, "был ли сделан запрос к БД").

### Сравнение уровней тестирования

| Критерий | Unit | Integration | E2E | Contract | Visual |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Объект** | Функция / Класс | Группа модулей | Бизнес-сценарий | API Интерфейс | UI Layout |
| **Зависимости** | Дублёры (Mocks) | Реальные (Docker) | Полный стек | Спецификации | Браузер / эталоны |
| **Скорость** | Миллисекунды | Секунды | Минуты | Секунды | Секунды |
| **Надёжность** | Детерминированная | Высокая | Flaky (высокий) | Высокая | Средняя (диффы) |
| **Инструменты** | pytest, Jest | Testcontainers | Playwright | Pact, PactFlow | Applitools, Percy |

### Стратегия тестовых окружений

Для DevOps/SRE критично, чтобы тесты выполнялись в окружении, максимально приближённом к production:

*   **Паритет сред (Environment Parity):** Конфигурация ОС, версии зависимостей (БД, брокеры) и параметры запуска в CI должны совпадать с staging/production. Для контейнеров это означает фиксированные теги образов (`postgres:16.3`, а не `:latest`).
*   **Эфемерные окружения (Ephemeral Environments):** Вместо разделения одного стейджинга создаётся изолированное окружение на каждый Merge Request или ветку. После закрытия MR окружение автоматически уничтожается. Это исключает "оно работало на стейджинге, потому что там грязные данные от другого теста".
*   **Изоляция данных:** Каждый тестовый прогон работает с уникальной базой или схемой. Для PostgreSQL используется отдельная база на тест (`CREATE DATABASE test_${CI_PIPELINE_ID}`); для Kubernetes — отдельный namespace (`test-${CI_COMMIT_REF_SLUG}`).
*   **Очистка ресурсов:** Тестовые контейнеры, ВМ и записи в БД должны удаляться независимо от исхода теста (`finally`, `after_all`, `when: always`). Неочищенные ресурсы приводят к утечкам и ложным ошибкам следующего прогона.

### Управление тестовыми данными

Надёжность тестов зависит от качества и изоляции данных:

*   **Фабрики (Factories):** Вместо хардкода создавайте объекты через фабрики с вариативными полями (Faker, FactoryBot). Это исключает хрупкие тесты, зависящие от конкретных ID или значений.
*   **Симуляция времени (Time Mocking):** Для детерминированных тестов фиксируйте время через `freezegun` (Python), `@Clock` (Java) или `sinon.useFakeTimers` (JS). Зависимость от `Date.now()` делает тест flaky.
*   **Очистка между тестами:** Используйте `@Transactional` с `rollback` (Java) или `session.rollback()` (pytest) для отката изменений БД после каждого теста. Для интеграционных тестов без транзакций — удаление схемы или базы в `teardown`.
*   **Внешние зависимости:** Если тест обращается к внешнему API, используйте WireMock или Mock Server. Реальные внешние вызовы в CI делают тест зависимым от доступности стороннего сервиса.

## 3. Практические сценарии

### Интеграционный тест с БД (Python + Testcontainers)

Вместо моков используется реальная БД в контейнере, что повышает достоверность теста.

```python
from testcontainers.postgres import PostgresContainer
import sqlalchemy

def test_user_persistence():
    with PostgresContainer("postgres:18") as postgres:
        engine = sqlalchemy.create_engine(postgres.get_connection_url())
        # Логика проверки записи в реальную БД
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("CREATE TABLE users (name TEXT)"))
            conn.execute(sqlalchemy.text("INSERT INTO users VALUES ('admin')"))
            result = conn.execute(sqlalchemy.text("SELECT name FROM users")).scalar()
            assert result == "admin"
```

> Версия образа `postgres:18` соответствует текущему стабильному релизу PostgreSQL 18 (сентябрь 2025); анонс 19 ожидается в сентябре 2026.

### Полный воркфлоу Pact (Consumer-Driven) в CI/CD

Взаимодействие Consumer (Frontend) и Provider (Backend) через Pact Broker.

```bash
# 1. Consumer: Запуск тестов и генерация контракта
npm test # -> создает pacts/frontend-backend.json

# 2. Consumer: Публикация контракта в Broker
pact-broker publish ./pacts --broker-base-url $PACT_BROKER_URL --app-version $GIT_SHA

# 3. Provider: Верификация контракта (запускается в пайплайне бэкенда)
# Провайдер скачивает контракт, прогоняет его против своей реализации и публикует результат
pytest tests/pact_verification.py --publish-verification-results

# 4. Проверка перед деплоем (Quality Gate)
pact-broker can-i-deploy \
  --pacticipant FrontendApp --version $GIT_SHA \
  --to-environment production \
  --broker-base-url $PACT_BROKER_URL
# -> EXIT 0: можно деплоить / EXIT 1: деплой заблокирован (сломан контракт)
```

### Контрактное тестирование: Bi-directional (BDCT) с PactFlow

Для случаев, когда провайдер предоставляет OpenAPI схему, а потребитель фиксирует свои ожидания.

```bash
# Провайдер: self-verification реализации против спецификации (например, Schemathesis),
# затем публикация спецификации как "проверенного контракта"
pactflow publish-provider-contract openapi.yaml \
  --provider OrdersAPI \
  --provider-app-version "${GIT_SHA}" \
  --branch "${GIT_BRANCH}" \
  --content-type application/yaml \
  --verification-exit-code 0 \
  --verification-results schemathesis-report.json \
  --verifier schemathesis
```

### Unit-тесты в CI: практический пайплайн

Unit-тесты должны выполняться на каждом коммите. Для ускорения прогона применяется параллелизм и кэширование зависимостей.

**Python + pytest + GitHub Actions:**

```yaml
name: Unit Tests
on: [pull_request, push]

jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run unit tests with coverage
        run: |
          pytest tests/unit/ \
            --junitxml=reports/junit.xml \
            --cov=src --cov-report=xml \
            -n auto  # pytest-xdist: параллелизм по ядрам CPU
      - name: Upload JUnit report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: unit-junit
          path: reports/junit.xml
          retention-days: 14
```

**JavaScript + Jest:**

```yaml
- name: Run Jest unit tests
  run: npx jest --coverage --maxWorkers=2 --reporters=jest-junit
  env:
    JEST_JUNIT_OUTPUT: reports/junit.xml
```

**Go:**

```bash
go test ./... -coverprofile=coverage.out -json | gotestsum --junitfile reports/junit.xml -
```

### Интеграционные тесты: Docker Compose и Testcontainers

Интеграционные тесты требуют реальных зависимостей. Два подхода:

**Подход 1: Docker Compose (статичный стек)**

Для стабильных зависимостей (БД + кэш) удобен `docker-compose.yml`:

```yaml
# docker-compose.test.yml
services:
  postgres:
    image: postgres:16.3
    environment:
      POSTGRES_DB: testdb
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test"]
      interval: 2s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

```bash
# Запуск зависимостей
docker compose -f docker-compose.test.yml up -d --wait

# Выполнение тестов
pytest tests/integration/ --junitxml=reports/junit.xml

# Очистка
docker compose -f docker-compose.test.yml down -v
```

**Подход 2: Testcontainers (программный)**

Для динамических сценариев (несколько изолированных баз в одном прогоне) — Testcontainers. Детали: **[Testcontainers: обзор](./testcontainers_overview.md)**.

### E2E-тесты: Playwright в CI

Сквозные тесты имитируют пользователя через все слои. Для стабильности требуется:

*   **Фиксированные версии браузеров:** Используйте Docker-образ `mcr.microsoft.com/playwright:v1.49.0-noble` с предустановленными Chromium/Firefox/WebKit.
*   **Шардирование (Sharding):** Разделите тесты по нескольким джобам для ускорения прогона.
*   **Артефакты:** Сохраняйте видео, скриншоты и трассировки при падениях.

```yaml
name: E2E Tests
on: [pull_request]

jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Playwright shard 1/2
        run: npx playwright test --shard=1/2 --reporter=junit --output=reports
        env:
          BASE_URL: https://staging.example.com
      - name: Upload artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: e2e-shard-1
          path: |
            reports/*.xml
            playwright-report/
            test-results/
```

**Важно:** E2E-тесты должны запускаться против окружения, максимально похожего на production (staging с production-данными или production-подобными). Запуск против `localhost` с локальной БД даёт ложное чувство безопасности.

### Инфраструктурное тестирование (Sysadmin/SRE перспектива)

Помимо тестирования кода, SRE/сисадмин проверяет корректность развёртывания и конфигурации инфраструктуры:

**Тестирование systemd-сервисов:**

```bash
# Проверка: сервис стартует, listen на порту, отвечает healthcheck
systemctl start myapp.service
systemctl is-active --quiet myapp.service && echo "OK" || echo "FAIL"

# Проверка health endpoint
curl -sf http://localhost:8080/healthz || systemctl status myapp.service

# Очистка
systemctl stop myapp.service
```

**Тестирование idempotency (Ansible/Molecule концепция):**

Конфигурация должна применима многократно без изменения результата. Проверка:

```bash
# Первый прогон
ansible-playbook playbook.yml

# Второй прогон — idempotency check
ansible-playbook playbook.yml --diff | grep -q "changed" && echo "NOT IDEMPOTENT" || echo "IDEMPOTENT"
```

**Тестирование в изолированных сетевых пространствах (network namespaces):**

```bash
# Создание изолированного namespace для теста
ip netns add test-ns
ip netns exec test-ns ip link set lo up

# Запуск приложения в namespace и проверка связности
ip netns exec test-ns curl -sf http://internal-service:8080/health || echo "FAIL"

# Удаление namespace
ip netns del test-ns
```

### Тестирование в air-gapped средах

В инфраструктурах с ограниченным доступом к интернету (банк, госсектор, оборонные контуры) тестовые окружения не могут скачивать образы или зависимости во время прогона:

*   **Pre-staging артефактов:** Все Docker-образы, пакеты и зависимости скачиваются на внутренний registry (Nexus, Artifactory, Harbor) заранее.
*   **Offline-режимы инструментов:** Playwright собирается с `--with-deps` на машине с доступом в сеть, затем копируется на изолированный раннер. `pytest` и плагины упаковываются в wheelhouse.
*   **Верификация доступности:** Перед прогоном проверяйте `curl -sf http://registry.local/v2/` — если registry недоступен, пайплайн должен завершиться с понятной ошибкой, а не зависнуть на `docker pull`.

### Визуальное регрессионное тестирование (Visual Regression)

Для обеспечения визуальной целостности интерфейса и предотвращения поломок верстки, которые не обнаруживаются функциональными тестами, используется визуальное регрессионное тестирование.

**Практическое руководство и примеры (Playwright, Percy, Docker):** **[Visual Regression в CI/CD](../CI-CD/Testing/visual-regression-cicd.md)**.

## 4. Дополнительная информация

### Управление состоянием и изоляция тестов

Неизолированные тесты — основная причина flaky-результатов и невоспроизводимых багов:

*   **Изоляция на уровне БД:** Для интеграционных тестов используйте отдельную схему или базу на каждый тестовый класс/метод. В pytest — фикстура с `scope="function"` и `DROP SCHEMA` в `teardown`. В JUnit — `@Transactional` с автоматическим rollback.
*   **Изоляция на уровне файловой системы:** Пишите во временные директории (`tmp_path` в pytest, `java.nio.file.Files.createTempDirectory`), never в рабочий каталог проекта.
*   **Изоляция на уровне сети:** Используйте динамические порты (Testcontainers делает это автоматически). Для ручной настройки — `socket.getFreePort()` или аналоги.
*   **Параллелизм без конфликтов:** При запуске в нескольких процессах (pytest-xdist, Jest workers) убедитесь, что тесты не делят файлы, порты или записи БД. Если тест не может быть параллельным — пометьте его `@serial` или вынесите в отдельную джобу.
*   **Очистка ресурсов:** Используйте контекстные менеджеры (`with`, `try/finally`, `@Container`) для гарантированного удаления контейнеров, ВМ и временных файлов даже при падении теста.

### Принципы надёжности (FIRST)

Каждый качественный тест должен соответствовать принципам **FIRST**. Подробное описание и примеры см. в разделе **[Принципы качественных тестов](../CI-CD/Testing/tdd_bdd_overview.md#принципы-качественных-тестов)**.

---

### См. также

*   **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — ворота качества, TIA, эфемерные окружения.
*   **[Testcontainers: обзор](./testcontainers_overview.md)** — стандарт интеграционного тестирования.
*   **[Pact Foundation Documentation](https://docs.pact.io/)** — детальное руководство по контрактному тестированию.
