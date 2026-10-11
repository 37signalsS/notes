# Миграции баз данных в CI/CD

> **Актуально для:** self-hosted CI/CD (GitLab CI, GitHub Actions, Jenkins) 2024–2026
>
> Область применения: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развёрнутых систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, не рассматриваются.

> **Важно:** данный файл содержит краткие практические сценарии для конкретных CI-платформ. Основная теория, определения, архтектурные паттерны, обработка дрейфа, SRE-рекомендации и сравнительная таблица инструментов вынесены в hub-документ **[Database CI/CD: Автоматизация миграций и GitOps для БД](../../Databases/Concepts/migrations/database-ci-cd.md)**. Перед работой с файлами ознакомьтесь с ним.

## Определения

- **Миграция базы данных (Database Migration)** — автоматизированное изменение схемы или данных БД, управляемое версионными скриптами, интегрированное в конвейер доставки.
- **Schema Migration** — изменение структуры БД (таблицы, индексы, constraints).
- **Data Migration** — изменение содержимого БД (миграция данных, заполнение новых колонок).
- **Idempotent Migration** — миграция, которая может быть безопасно применена несколько раз без побочных эффектов.
- **Zero-downtime Migration** — миграция, не прерывающая обслуживание приложения.
- **Expand/Contract** — паттерн обратно-совместимых миграций: расширение схемы → обновление кода → удаление устаревших полей.
- **Migration Lint** — статическая проверка миграционных скриптов на синтаксис и обратную совместимость.
- **Drift Detection** — автоматическое обнаружение расхождений между схемой в Git и реальной схемой в БД.
- **Database CI/CD** — практика интеграции изменений схемы и данных БД в общий конвейер доставки, обеспечивающая их версионирование, тестирование и автоматический деплой.
- **Database-as-Code** — подход, при котором эталонное состояние БД описывается декларативно в Git и автоматически синхронизируется с инстансами через CI/CD.

## Практические сценарии: CI-платформы

### Сценарий 1: Flyway в GitLab CI (PostgreSQL)

#### Предпосылки
- PostgreSQL 11+.
- Миграции в формате SQL.
- Требуется idempotent migrations и rollback.

#### Структура
```
db/
├── migrations/
│   ├── V20260817120000__init.sql
│   ├── V20260817120100__add_users_table.sql
│   ├── V20260817120200__add_email_column.sql
│   └── V20260817120300__add_index_on_email.sql
└── rollback/
    ├── U20260817120200__rollback_add_email.sql
    └── U20260817120300__rollback_add_index.sql
```

#### .gitlab-ci.yml
```yaml
stages:
  - validate
  - migrate
  - test

validate_migrations:
  stage: validate
  image: flyway/flyway:13.5.0
  script:
    - flyway -url=$DB_URL -user=$DB_USER -password=$DB_PASS validate
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

migrate_staging:
  stage: migrate
  image: flyway/flyway:13.5.0
  script:
    - flyway -url=$STAGING_DB_URL -user=$DB_USER -password=$DB_PASS migrate
  environment:
    name: staging
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

migrate_prod:
  stage: migrate
  image: flyway/flyway:13.5.0
  script:
    - flyway -url=$PROD_DB_URL -user=$DB_USER -password=$DB_PASS migrate
  environment:
    name: production
  when: manual
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

test_migration:
  stage: test
  image: flyway/flyway:13.5.0
  script:
    - flyway -url=$TEST_DB_URL -user=$DB_USER -password=$DB_PASS clean
    - flyway -url=$TEST_DB_URL -user=$DB_USER -password=$DB_PASS migrate
    - flyway -url=$TEST_DB_URL -user=$DB_USER -password=$DB_PASS info
```

#### Валидация
- `flyway info` показывает `Success` напротив применённых версий.
- При провале миграции пайплайн останавливается, деплой не происходит.
- Rollback: `flyway -target=V20260817120100 undo` (требует Flyway Teams/Enterprise) или откат к предыдущему образу приложения.

---

### Сценарий 2: GitHub Actions + Liquibase (Expand/Contract, MySQL)

#### Предпосылки
- MySQL 8.0.12+.
- GitHub Actions self-hosted runner.
- Требуется обратно-совместимая миграция без downtime.

#### Структура
```
db/
├── changelog/
│   ├── master.xml
│   ├── V1_add_column.yaml
│   ├── V2_populate_column.yaml
│   └── V3_drop_old_column.yaml
```

#### master.xml
```xml
<databaseChangeLog
  xmlns="http://www.liquibase.org/xml/ns/dbchangelog"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.liquibase.org/xml/ns/dbchangelog
                      http://www.liquibase.org/xml/ns/dbchangelog/dbchangelog-4.24.xsd">

  <changeSet id="V1_add_column" author="dba">
    <addColumn tableName="users">
      <column name="email_new" type="VARCHAR(255)"/>
    </addColumn>
  </changeSet>

  <changeSet id="V2_populate_column" author="dba">
    <update tableName="users">
      <column name="email_new" valueComputed="email"/>
    </update>
  </changeSet>

  <changeSet id="V3_drop_old_column" author="dba">
    <dropColumn tableName="users" columnName="email"/>
  </changeSet>

</databaseChangeLog>
```

#### .github/workflows/db-migrate.yml
```yaml
name: Database Migration
on:
  push:
    branches: [ main ]
  workflow_dispatch:

jobs:
  validate:
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - uses: liquibase/setup-liquibase@v1
        with:
          liquibase-version: '5.0.0'
      - run: liquibase --changeLogFile=db/changelog/master.xml validate

  migrate-staging:
    needs: validate
    runs-on: self-hosted
    steps:
      - uses: actions/checkout@v4
      - uses: liquibase/setup-liquibase@v1
        with:
          liquibase-version: '5.0.0'
      - run: liquibase --changeLogFile=db/changelog/master.xml update
        env:
          LIQUIBASE_URL: ${{ secrets.STAGING_DB_URL }}
          LIQUIBASE_USERNAME: ${{ secrets.DB_USER }}
          LIQUIBASE_PASSWORD: ${{ secrets.DB_PASS }}

  migrate-prod:
    needs: migrate-staging
    runs-on: self-hosted
    environment:
      name: production
    steps:
      - uses: actions/checkout@v4
      - uses: liquibase/setup-liquibase@v1
        with:
          liquibase-version: '5.0.0'
      - run: liquibase --changeLogFile=db/changelog/master.xml update
        env:
          LIQUIBASE_URL: ${{ secrets.PROD_DB_URL }}
          LIQUIBASE_USERNAME: ${{ secrets.DB_USER }}
          LIQUIBASE_PASSWORD: ${{ secrets.DB_PASS }}
```

#### Валидация
- Миграция V1 добавляет колонку `email_new` без удаления `email` (оба колонки совместимы со старой версией кода).
- После деплоя кода v2 (который пишет в `email_new`) запускается миграция V3.
- При откате кода v1 колонка `email` восстанавливается, `email_new` игнорируется.
- Liquibase v5+: рекомендуется использовать `setup-liquibase` action; старые micro-actions поддерживаются до v4.x.

---

### Сценарий 3: goose + idempotent migrations (Go)

#### Предпосылки
- Go-приложение.
- Требуется простой инструмент без Java-зависимостей.

#### Структура
```
db/
├── migrations/
│   ├── 20260817120000_init.up.sql
│   ├── 20260817120000_init.down.sql
│   ├── 20260817120100_add_users.up.sql
│   └── 20260817120100_add_users.down.sql
└── seed/
    └── 20260817120200_insert_data.sql
```

#### 20260817120000_init.up.sql
```sql
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(255) NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);
```

#### .gitlab-ci.yml
```yaml
migrate:
  stage: migrate
  image: goose:1.25.0
  script:
    - goose -dir db/migrations postgres "$DB_URL" up
  environment:
    name: production
  when: manual
```

#### Валидация
- `goose status` показывает применённые миграции.
- Idempotent: повторный запуск `20260817120000_init.up.sql` не вызывает ошибки.
- Timestamp-based naming предотвращает коллизии при merge нескольких веток.

---

### Сценарий 4: Zero-downtime миграция (Shadow) в CI/CD

#### Предпосылки
- Большая таблица (>10M строк).
- ALTER TABLE блокирует таблицу на минуты.
- Требуется интеграция с Canary или Rolling Update.

#### Подход
1. Добавить новую колонку `email_new` (NULL, без NOT NULL).
2. Наполнять `email_new` параллельно с `email` в коде.
3. После завершения наполнения сделать `email_new` NOT NULL.
4. Удалить старую колонку `email`.

#### Скрипт миграции (V1)
```sql
-- V20260817120000_add_email_new_column.sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_new VARCHAR(255);
-- Не делаем NOT NULL здесь — это заблокирует таблицу
```

#### Скрипт миграции (V2)
```sql
-- V20260817120100_populate_email_new.sql
UPDATE users SET email_new = email WHERE email_new IS NULL;
-- Запускать в фоне, батчами по 10000 строк
-- Важно: миграция должна быть идемпотентной (повторный запуск не ломает данные)
```

#### Скрипт миграции (V3)
```sql
-- V20260817120200_make_email_new_not_null.sql
ALTER TABLE users ALTER COLUMN email_new SET NOT NULL;
-- Безопасно: все строки заполнены
```

#### Скрипт миграции (V4)
```sql
-- V20260817120300_drop_old_column.sql
ALTER TABLE users DROP COLUMN email;
```

#### Интеграция с Canary
- V1 и V2 применяются до деплоя (Pre-deployment).
- V3 и V4 применяются после стабилизации canary (Post-deployment).
- При откате canary на старые поды фаза Contract не выполняется; колонка `email_new` остаётся неиспользуемой.

#### Валидация
- Каждая миграция обратно совместима со старой версией кода.
- Миграции применяются поэтапно, без блокировки таблицы.
- При откате кода на любой из промежуточных этапов схема остаётся совместимой.

---

### Сценарий 5: Деплой через Kubernetes Job (Pre-upgrade)

#### Предпосылки
- Образ приложения содержит CLI миграций и скрипты.
- Настроен RBAC для создания Jobs в K8s.
- Helm chart с hooks.

#### job-db-migration.yaml
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration-v20260817
  annotations:
    "helm.sh/hook": pre-upgrade,pre-install
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded,hook-failed
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migrate
        image: registry.internal/db-migrate:v2.4.0
        env:
        - name: DB_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
        command: ["flyway", "migrate"]
```

#### Валидация
- `kubectl get jobs -l app=myapp` показывает `COMPLETIONS=1`.
- Helm upgrade продолжится только после успешного завершения Job.

---

### Сценарий 6: Тестирование миграций в CI/CD (Testcontainers)

#### Предпосылки
- Требуется гарантия, что миграции не ломают приложение.
- Требуется проверка обратной совместимости.

#### Паттерн: Testcontainers + Flyway
```yaml
test_migrations:
  stage: test
  image: golang:1.23
  services:
    - postgres:15
  script:
    - go test -v -run TestMigrations ./db/
```

#### test_migrations.go
```go
package db

import (
    "context"
    "fmt"
    "os/exec"
    "testing"
    "time"

    "github.com/testcontainers/testcontainers-go"
    "github.com/testcontainers/testcontainers-go/wait"
)

func TestMigrations(t *testing.T) {
    ctx := context.Background()

    // Запуск PostgreSQL в контейнере
    req := testcontainers.ContainerRequest{
        Image:        "postgres:15-alpine",
        Env:          map[string]string{"POSTGRES_DB": "test", "POSTGRES_PASSWORD": "test"},
        ExposedPorts: []string{"5432/tcp"},
        WaitingFor:   wait.ForLog("database system is ready").WithStartupTimeout(30 * time.Second),
    }
    pg, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{ContainerRequest: req})
    if err != nil {
        t.Fatal(err)
    }
    defer pg.Terminate(ctx)

    port, _ := pg.MappedPort(ctx, "5432")
    dsn := fmt.Sprintf("postgres://test:test@localhost:%s/test?sslmode=disable", port.Port())

    // Применение миграций
    cmd := exec.Command("flyway", "-url="+dsn, "-user=test", "-password=test", "migrate")
    if out, err := cmd.CombinedOutput(); err != nil {
        t.Fatalf("migration failed: %s", out)
    }

    // Проверка: приложение стартует с новой схемой
    cmd = exec.Command("./myapp", "-db="+dsn, "-migrate-check")
    if out, err := cmd.CombinedOutput(); err != nil {
        t.Fatalf("app failed to start with new schema: %s", out)
    }
}
```

#### Дополнительные проверки
- **Idempotency test:** Двойной запуск миграций на той же БД не вызывает ошибок.
- **Rollback test:** `down`-скрипт выполняется без потерь данных на staging-дампе.
- **Drift detection test:** Сравнение `atlas schema inspect` production с Git-версией.

#### Валидация
- Миграции применяются к чистой БД.
- Приложение стартует с новой схемой.
- Откат миграции не ломает приложение.

## См. также

- **[Database CI/CD: Автоматизация миграций](../../Databases/Concepts/migrations/database-ci-cd.md)** — hub-документ с теорией, паттернами и SRE-рекомендациями.
- **[Обратно-совместимые миграции](../../Databases/Concepts/migrations/expand_contract.md)** — архитектура Zero-downtime релизов.
- **[Стратегии отката данных](../../Databases/Concepts/rollback_strategies.md)** — откат stateful-слоя.
- **[Flyway: Практическое руководство](../../Databases/Concepts/migrations/tools/flyway_practical_guide.md)** — SQL-first подход.
- **[Liquibase: Практическое руководство](../../Databases/Concepts/migrations/tools/liquibase_practical_guide.md)** — Enterprise-стандарт.
- **[Мониторинг миграций](../../Databases/Concepts/migrations/monitoring.md)** — алертинг и метрики прогресса.
- **[Лучшие практики миграций](../../Databases/Concepts/migrations/migration_practices.md)** — стандарты именования и безопасности.
- **[Миграции баз данных: Основы](../../Databases/Concepts/migrations/migration_basics.md)** — парадигмы и выбор инструментов.
- **[Типовые сценарии миграций](../../Databases/Concepts/migrations/scenarios.md)** — готовые SQL-рецепты.
- **[GitLab CI: продвинутые workflow](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_advanced_workflow.md)** — `resource_group` и уведомления.
- **[Развёртывание: Rolling Update](../../CI-CD/Deployment_Strategies/rolling_update.md)** — координация с миграциями.
- **[Развёртывание: Canary](../../CI-CD/Deployment_Strategies/canary_deployment.md)** — безопасный деплой с миграциями.
- **[Deployment Health Checks and Rollback](../../CI-CD/Deployment_Strategies/deployment_health_checks_and_rollback.md)** — откат в CI/CD.
- **[DORA Metrics](../../CI-CD/Core_Concepts/dora_metrics.md)** — измерение скорости и стабильности миграций.
- **[Change Management](../../CI-CD/Core_Concepts/change_management.md)** — CAB и approval workflow.
