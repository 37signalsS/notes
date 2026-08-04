# Интеграция миграций в CI/CD

## Определения

- **Интеграция миграций в CI/CD** — это автоматизированный процесс проверки, тестирования и применения изменений схемы базы данных в рамках единого конвейера поставки ПО.
- **Data-first Deployment** — стратегия развертывания, при которой изменения БД применяются строго до обновления кода приложения. Требует обеспечения обратной совместимости через паттерн **[Expand-Contract](expand_contract.md)**.
- **SQL Linting** — статический анализ SQL-скриптов на соответствие стандартам производительности (отсутствие блокирующих операций), безопасности и стиля.
- **Migration Drift** — состояние, при котором фактическая схема БД отличается от описанной в системе контроля версий.

## Основные концепции

### Этапы автоматизации миграций в пайплайне

1.  **Валидация и Линтинг (Static Analysis):**
    - Проверка синтаксиса SQL.
    - Анализ на "опасные" операции (например, `ALTER TABLE` на больших таблицах без `CONCURRENTLY`).
    - Использование специализированных линтеров: **Squawk**, **Atlas Lint**.
2.  **Эфемерное тестирование (Ephemeral Testing):**
    - Запуск миграций на чистой временной БД (Docker/Testcontainers).
    - Проверка корректности применения и (опционально) отката.
    - Валидация схемы: сравнение итогового состояния с эталонным дампом.
3.  **Безопасное развертывание (Continuous Deployment):**
    - Использование **Kubernetes Jobs** для изоляции процесса миграции от жизненного цикла подов приложения.
    - Настройка **Init-контейнеров** для легковесных миграций (подходит только для простых DDL).
    - Интеграция с инструментами GitOps (Argo CD, Flux).

### Стратегии управления миграциями

- **Version-based (Change-based):** Последовательность версионированных файлов (`V1__init.sql`, `V2__add_col.sql`). Стандарт для Flyway и Liquibase.
- **State-based (Declarative):** Описание желаемого состояния схемы (например, в HCL или SQL-дампе). Инструмент (Atlas, Prisma) сам вычисляет дифференциал и генерирует план миграции.

## Практические сценарии

### Сценарий 1: Проверка на опасные операции (GitHub Actions + Atlas)

Автоматическая остановка Pull Request при обнаружении DDL, блокирующих таблицу.

```yaml
name: Database CI
on: [pull_request]
jobs:
  atlas-lint:
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

### Сценарий 2: Деплой через Kubernetes Job (Helm)

Использование `helm install` с ожиданием завершения миграции. Это предотвращает запуск нового кода до того, как БД будет готова.

```yaml
# templates/migration-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "myapp.fullname" . }}-migration
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "5"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      containers:
        - name: migrate
          image: myapp-migrate:latest
          command: ["/bin/sh", "-c", "flyway migrate"]
      restartPolicy: Never
```

### Сценарий 3: Автоматизированный откат при сбое (Rollback)

Если шаг деплоя приложения провалился после миграции, пайплайн должен инициировать процедуру восстановления.

```yaml
# gitlab-ci.yml
deploy:
  stage: deploy
  script:
    - kubectl apply -f k8s/deployment.yaml
  after_script:
    - >
      if [ $CI_JOB_STATUS == 'failed' ]; then
        echo "Deployment failed, initiating database investigation...";
        # ВНИМАНИЕ: Автоматический откат схемы (Undo) опасен потерей данных.
        # Рекомендуется: оповещение и ручной разбор.
      fi
```

## Дополнительная информация

### Рекомендации SRE

- **Migration War Room:** Для критических миграций используйте отдельные дашборды, отображающие прогресс и лаг репликации в реальном времени. См. **[Мониторинг миграций](monitoring.md)**.
- **Изоляция прав:** CI-пользователь не должен иметь прав на `DROP DATABASE` или `GRANT`. Используйте принцип наименьших привилегий.
- **Branching Strategy:** Избегайте конфликтов миграций при слиянии веток. Рекомендуется использовать семантическое версионирование или временные метки (timestamp) в именах файлов.
- **Dry-run на проде:** Перед применением миграции в продакшене, пайплайн должен выводить SQL-план в логи (без выполнения) для финального ревью DBA.

### Смежные темы

- **[Принцип Expand-Contract](expand_contract.md)** — основа безопасных изменений.
- **[Мониторинг миграций](monitoring.md)** — отслеживание здоровья БД в CI/CD.
- **[Стратегии отката (Rollback)](rollback_strategies.md)** — технические способы возврата состояния.
- **[Безопасные массовые операции](../safe_large_scale_data_modification.md)** — выполнение тяжелых DML в автоматизированном режиме.
- **[Управление секретами в CI/CD](../../../CI-CD/DevSecOps/artifact_management.md)** — хранение учетных данных БД.
