# Интеграция миграций в CI/CD

## Определения

**Интеграция миграций в CI/CD** — это автоматизированный процесс проверки, тестирования и применения изменений схемы базы данных в рамках единого конвейера поставки ПО (CI/CD pipeline).

**Data-first Deployment** — стратегия развертывания, при которой изменения БД применяются строго до обновления кода приложения, что требует обязательной обратной совместимости (см. **[Expand-Contract](expand_contract.md)**).

**SQL Linting** — статический анализ SQL-скриптов миграций на соответствие стандартам кодирования, безопасности и производительности.

## Основные концепции

### Этапы автоматизации миграций

1. **Линтинг (Linting):** автоматическая проверка SQL на наличие опасных операций (`DROP`, `TRUNCATE`), отсутствующих индексов или нарушение правил именования.
2. **Валидация (Validation):** проверка корректности контрольных сумм и порядка выполнения миграций (Flyway/Liquibase).
3. **Dry-run / Ghost-run:** выполнение миграций на временной эфемерной БД (например, в Docker-контейнере через **[Testcontainers](../../../Testing/testcontainers_overview.md)**) для подтверждения успешности скрипта.
4. **Развертывание (Deployment):** применение изменений на целевых окружениях с использованием Kubernetes Jobs или Init-контейнеров.

### Принципы безопасности в пайплайнах

- **Изоляция секретов:** пароли от БД не должны храниться в коде или логах пайплайна. Используйте **[Vault](../../../Vault/overview.md)** или механизмы секретов CI-систем.
- **Ограничение прав CI-пользователя:** учетная запись, используемая в CI, должна иметь права только на DDL и необходимые DML операции, но не на управление пользователями или всей СУБД.
- **Блокировка Breaking Changes:** автоматическая остановка пайплайна при обнаружении несовместимых изменений без использования Expand-Contract.

## Практические сценарии

### Сценарий 1: Декларативные миграции и линтинг (Atlas + GitHub Actions)

Инструмент Atlas позволяет описывать желаемое состояние и автоматически генерировать/проверять миграции.

```yaml
# .github/workflows/db-lint.yml
name: Database CI
on: [pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ariga/setup-atlas@v0
      - name: Run Atlas Lint
        run: |
          atlas migrate lint \
            --dir "file://migrations" \
            --dev-url "docker://postgres/15/dev" \
            --latest 1
```

### Сценарий 2: Деплой через Kubernetes Job (GitLab CI)

Безопасное применение миграций перед обновлением Deployment.

```yaml
# .gitlab-ci.yml
deploy_migrations:
  stage: migrate
  image: bitnami/kubectl:latest
  script:
    - kubectl apply -f k8s/migration-job.yaml
    - kubectl wait --for=condition=complete job/db-migration --timeout=300s
  only:
    - main

deploy_app:
  stage: deploy
  script:
    - kubectl set image deployment/myapp myapp=$IMAGE_TAG
  needs: ["deploy_migrations"]
```

### Сценарий 3: Защита от опасных команд (Shell Script)

Простая проверка в пайплайне на наличие запрещенных ключевых слов.

```bash
#!/bin/bash
# pre_migrate_check.sh
# Поиск DROP или RENAME вне фазы Contract
if grep -Ei "DROP|RENAME" migrations/*.sql; then
    echo "CRITICAL: Detected destructive operation. Use Expand-Contract pattern."
    exit 1
fi
```

## Дополнительная информация

### Рекомендации

- **Идемпотентность:** убедитесь, что скрипты миграций можно запускать повторно без ошибок.
- **Ephemeral DB:** для тестирования миграций в CI используйте временные БД, поднимаемые в Docker. Это гарантирует чистоту эксперимента.
- **Версионирование образа:** при использовании миграций внутри Docker-образа приложения (через Init-контейнеры) убедитесь, что версия схемы соответствует версии кода.

### Смежные темы

- **[Принцип Expand-Contract](expand_contract.md)** — база для Zero-downtime деплоя.
- **[Мониторинг миграций](monitoring.md)** — алертинг при сбоях в пайплайне.
- **[Тестирование в CI/CD](../../../Testing/testing_cicd_integration.md)** — общие подходы к автоматизации тестов.
- **[Секреты в GitHub Actions](../../../Github_CI/secrets_management.md)** — безопасное хранение учетных данных.
