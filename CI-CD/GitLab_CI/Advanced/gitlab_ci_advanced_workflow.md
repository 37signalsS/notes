# Продвинутые рабочие процессы GitLab CI/CD

## Определения

**Продвинутые рабочие процессы (Advanced Workflows)** — это архитектурный уровень проектирования CI/CD, направленный на создание сложных, масштабируемых и самодокументированных конвейеров. Они объединяют методы динамической оркестрации, превентивной безопасности и глубокой оптимизации ресурсов.

**Ключевые инструменты и директивы:**

-   **`rules` и `workflow:rules`**: Глобальное и локальное управление жизненным циклом пайплайна. Позволяют реализовать логику Branching и Merge Request пайплайнов без дублирования. Подробности — см. **[Определения всех директив](./workflow_rules/directives_definitions.md)**.
-   **`needs` (DAG)**: Механизм построения Направленных Ациклических Графов. Устраняет бутылочное горлышко стадий, позволяя задачам запускаться асинхронно. SSoT: **[DAG с needs](./workflow_rules/dag_with_needs.md)**.
-   **`parallel:matrix`**: Динамическое размножение задач для кросс-платформенного тестирования и параллельного выполнения. SSoT: **[Матричные сборки и сериализация](./workflow_rules/matrix_builds_and_serialization.md)**.
-   **`resource_group`**: Система блокировок (mutex) на уровне GitLab для предотвращения конфликтов при одновременном доступе к ограниченным ресурсам (например, окружениям). SSoT: **[Матричные сборки и сериализация](./workflow_rules/matrix_builds_and_serialization.md)**.
-   **Pipeline Inputs (`spec:inputs`)**: Механизм типизации параметров, превращающий YAML-конфигурацию в структурированный интерфейс с валидацией типов (`string`, `number`, `boolean`) на этапе компиляции. SSoT: **[Переменные и лучшие практики](./workflow_rules/variables_best_practices.md)**.
-   **OIDC (ID tokens)**: Протокол федеративной аутентификации, позволяющий джобе получать кратковременные права доступа к внешним системам (Vault, Kubernetes, Object Storage) без статических секретов. SSoT: **[API и Webhooks: id_tokens](./api_and_webhooks_automation.md#механизм-id_tokens-oidc)**.
-   **Pipeline Execution Policies**: Корпоративный стандарт принудительного исполнения задач безопасности и комплаенса, который невозможно обойти на уровне проекта (GitLab 17.x–19.x). Данный файл является **SSoT** для этого инструмента.
-   **SLSA & SBOM**: Стандарты безопасности цепочек поставок (Software Supply Chain), обеспечивающие проверяемость происхождения кода и прозрачность состава артефактов. Данный файл является **SSoT** для архитектурного контекста; генерация артефактов описана в **[Артефакты и кэширование](./gitlab_ci_caching/gitlab_ci_artifacts.md)**.

## Основные концепции

### Оптимизация и производительность

Современные пайплайны в 2026 году ориентированы на максимальную скорость обратной связи (Feedback Loop).

1.  **Ациклические графы (DAG)**: Директива `needs` позволяет задачам игнорировать границы стадий.
    -   **`needs:optional`**: Позволяет зависеть от задачи, которая может быть не включена в текущий пайплайн (например, при селективном запуске в монорепозиториях).
2.  **Матричные сборки**: Использование `parallel:matrix`. Для оптимизации рекомендуется использовать матричную адресацию зависимостей (`needs:parallel:matrix`), связывающую сборки и тесты 1:1.
3.  **Автоматическая отмена (`workflow:auto_cancel`)**:
    -   **`on_new_commit`**: Режим `conservative` предотвращает отмену критических стадий деплоя, в то время как `interruptible: true` позволяет мгновенно высвобождать раннеры при новых коммитах.
    -   **`on_job_failure: all`**: Режим Fail-Fast, который немедленно останавливает весь пайплайн при критической ошибке, экономя бюджет вычислительных ресурсов.
4.  **Типизированный запуск через Inputs**: С версии GitLab 17.11 директива `spec:inputs` может использоваться в корневом файле, заменяя текстовые поля переменных на выпадающие списки и флажки в UI «Run Pipeline».

### Безопасность и Compliance (Supply Chain Security)

1.  **Zero Trust через ID Tokens**: Использование `id_tokens` обеспечивает модель **Workload Identity Federation**. Раннер получает JWT, аудитория (`aud`) которого проверяется внешним провайдером. Это полностью устраняет риск компрометации статических токенов доступа.
2.  **Pipeline Execution Policies**: Позволяют ИБ-инженерам внедрять обязательные стадии (сканирование на уязвимости, проверка лицензий) во все проекты группы. С версии **19.x** поддерживаются **Scheduled Execution Policies** для регулярного аудита состояния безопасности всех репозиториев.
3.  **Генерация аттестаций (SLSA)**: Автоматическое создание доказательств сборки в доверенной среде. Использование `artifacts:reports:cyclonedx` для генерации SBOM (Software Bill of Materials) в формате JSON, что является обязательным для комплаенса в современных Enterprise-средах.

### Сложные архитектуры пайплайнов

1.  **Parent-Child Pipelines**: Решение для монорепозиториев.
    -   **Изоляция**: Ошибки в одном сервисе не блокируют CI/CD других.
    -   **inputs**: Передача параметров через `trigger:inputs` (GitLab 18.0+) для валидации конфигурации дочернего пайплайна.
    -   SSoT: **[Parent-Child Pipelines](./Downstream_Pipelines/parent_child_pipelines.md)**.
2.  **Dynamic Pipeline Generation**: Программная генерация YAML через скрипты (Python/Go). Используется, когда количество окружений или задач зависит от внешнего источника данных (например, список сервисов из реестра конфигураций).
    -   SSoT: **[Динамическая генерация пайплайнов](./Downstream_Pipelines/dynamic_generation.md)**.
3.  **Programmatic Automation (API & Webhooks)**: Управление жизненным циклом пайплайна через внешние системы. Позволяет интегрировать CI/CD в общую шину автоматизации предприятия, реализуя сложные сценарии обратной связи и динамической переконфигурации.
    -   SSoT: **[Программная автоматизация: API и Webhooks](./api_and_webhooks_automation.md)**.

## Архитектурные паттерны CI/CD

Помимо базовых инструментов, существуют проверенные архитектурные паттерны, которые определяют структуру пайплайнов на уровне системы.

### Fan-in / Fan-out

**Fan-out** — запуск множества задач параллельно по одной или нескольким стадиям. **Fan-in** — сборка результатов всех задач в одной итоговой задаче.

```yaml
# Fan-out: параллельное тестирование на 4 платформах
test:fan-out:
  stage: test
  parallel:matrix:
    PLATFORM: [linux-amd64, linux-arm64, macos-x64, windows-x64]
  script: ./test.sh --platform=$PLATFORM

# Fan-in: агрегация результатов всех тестов
report:fan-in:
  stage: report
  needs: [test:fan-out]  # Зависит от ВСЕХ матричных задач
  script: ./aggregate-results.sh
  artifacts:
    reports:
      junit: report.xml
```

**Паттерн «Symmetric DAG»**: Количество задач fan-in должно совпадать с количеством задач fan-out. Если fan-out генерирует 8 задач, fan-in должен ожидать ровно 8, иначе пайплайн зависнет. Подробности — см. **[DAG с needs](./workflow_rules/dag_with_needs.md)**.

**Рекомендация**: Для fan-in используйте `needs: [job_name]` без указания конкретных индексов матрицы — GitLab автоматически соберёт зависимости от всех матричных экземпляров.

### Monorepo vs Polyrepo

| Паттерн | Стратегия CI/CD | Основной инструмент GitLab |
|:---|:---|:---|
| **Monorepo** (один репозиторий, множество сервисов) | Selective CI: запуск только затронутых сервисов | `rules:changes`, Parent-Child pipelines, `trigger:inputs` |
| **Polyrepo** (каждый сервис — отдельный репозиторий) | Multi-project pipelines: оркестрация через trigger | `trigger:project`, Downstream pipelines |
| **Mixed** (монорепо с вынесенными библиотеками) | Кэширование артефактов между проектами | `needs:project`, `needs:artifact` |

**Monorepo Selective CI:**
```yaml
# Определение затронутых сервисов через changes
deploy:auth:
  stage: deploy
  rules:
    - changes:
        - services/auth/**/*
  script: ./deploy-service.sh auth

deploy:payment:
  stage: deploy
  rules:
    - changes:
        - services/payment/**/*
  script: ./deploy-service.sh payment

# Общая задача для агрегации (fan-in)
smoke:test:
  stage: test
  needs: [deploy:auth, deploy:payment]
  script: ./smoke-test.sh
```

### Merge Queue

Merge Queue — механизм, предотвращающий breakage main-ветки при слиянии. Все MR попадают в очередь и тестируются последовательно перед вливанием.

**Включить Merge Queue в GitLab:**
1. `Settings > Merge requests > Merge method` → **Merge queue**
2. `Settings > CI/CD > General pipelines` → Enable merge queue

**Как это работает:**
1. Разработчик нажимает «Add to merge queue»
2. GitLab создаёт временный ref `refs/merge-requests/N/next`
3. Запускается CI/CD-пайплайн для этого ref
4. Если pipeline прошёл — MR вливается в main
5. Следующий MR из очереди запускается

**Связь с auto_cancel**: В merge queue отключение `auto_cancel` критично. Если `auto_cancel.on_new_commit: interruptible` активен, инициированный merge request может отменить pipeline предыдущего MR в очереди, что приведёт к dead-lock.

```yaml
# Рекомендованная конфигурация для merge queue
workflow:
  auto_cancel:
    on_new_commit: none  # Не отменять pipelines в merge queue

stages:
  - test
  - deploy

test:
  stage: test
  script: ./test.sh
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:
  stage: deploy
  script: ./deploy.sh
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### Pipeline Execution Policies

Для корпоративных сред с высокими требованиями к безопасности Pipeline Execution Policies позволяют ИБ-инженерам внедрять обязательные задачи (сканирование, комплаенс) **во все проекты группы/инстанса** без возможности отключения на уровне проекта.

**Уровни влияния:**
-   **Group-level**: Все проекты группы наследуют политику
-   **Instance-level**: Все проекты инстанса наследуют политику

**Типы политик:**
-   **Execution Policies**: Обязательные задачи, вставляемые в каждый pipeline
-   **Scheduled Execution Policies** (GitLab 19.x+): Регулярный аудит состояния безопасности (daily/weekly)

```yaml
# Пример Pipeline Execution Policy для сканирования зависимостей
include:
  - project: 'security/policies'
    file: '/templates/dependency-scan.yml'

# Внешняя конфигурация политики (управляется ИБ-инженерами):
# - project: 'security/policies'
#   file: '/templates/mandatory-sast.yml'
#   inputs:
#     severity_threshold: "HIGH"
```

## Практические сценарии

### Сценарий 1: Управление через Pipeline Inputs (GitLab 18.x)

Создание удобного интерфейса для ручного запуска деплоя с валидацией параметров.

```yaml
spec:
  inputs:
    environment:
      type: string
      default: staging
      options: [staging, production]
    perform_cleanup:
      type: boolean
      default: true

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "web"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_job:
  stage: deploy
  script:
    - echo "Deploying to $[[ inputs.environment ]]"
    - if [ "$[[ inputs.perform_cleanup ]]" = "true" ]; then ./cleanup.sh; fi
```

### Сценарий 2: Аутентификация в Vault через OIDC (Zero Trust)

Исключение использования долгоживущих секретов для доступа к HashiCorp Vault. Пайплайн получает временный токен Vault через OIDC-workload identity.

```yaml
deploy:
  stage: deploy
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.internal:8200
  script:
    - |
      # Получение временного токена Vault через OIDC
      export VAULT_TOKEN=$(vault write -field=token \
        auth/jwt/login role=gitlab-ci-role jwt=$VAULT_ID_TOKEN)
    - |
      # Извлечение секретов из Vault
      export DB_PASSWORD=$(vault kv get -field=password secret/prod/db)
      export API_KEY=$(vault kv get -field=key secret/prod/api)
    - ./deploy.sh
```

**Конфигурация Vault OIDC:**
```hcl
# Vault: OIDC Auth Method
path "auth/jwt/oidc_config" {
  config {
    oidc_discovery_url = "https://gitlab.internal"
    oidc_client_id     = "vault"
    oidc_client_secret = "vault-oidc-secret"
  }
}

# Vault: Role для GitLab CI
path "auth/jwt/role/gitlab-ci-role" {
  bound_audiences = ["vault"]
  bound_claims = {
    project_path = "infrastructure/deployments"
    ref_type     = "branch"
  }
  token_policies = ["gitlab-ci-read"]
  token_ttl      = 3600
}
```

Подробнее см. **[API и Webhooks: Механизм id_tokens](./api_and_webhooks_automation.md#механизм-id_tokens-oidc)**.

### Сценарий 3: Генерация SBOM и аттестация SLSA

Обеспечение прозрачности состава артефактов.

```yaml
build_app:
  stage: build
  script:
    - ./build.sh
    - syft . -o cyclonedx-json=bom.json
  artifacts:
    reports:
      cyclonedx: bom.json
    paths:
      - build/app.bin

sign_artifacts:
  stage: test
  needs: [build_app]
  id_tokens:
    SIGSTORE_ID_TOKEN:
      aud: sigstore
  script:
    - cosign sign-blob build/app.bin --bundle cosign.bundle --identity-token $SIGSTORE_ID_TOKEN
```

### Сценарий 4: Глобальная очередь с resource_group

Предотвращение конфликтов при деплое в одну базу данных.

```yaml
db_migrate:
  stage: deploy
  resource_group: database_cluster_prod
  resource_group_process_mode: oldest_first # Строгий FIFO порядок
  script:
    - ./run_migrations.sh
  interruptible: false # Нельзя прерывать миграцию
```

### Сценарий 5: Self-Healing через мониторинг и автоматический откат

Система мониторинга (Prometheus + Alertmanager) обнаруживает аномалию после деплоя и инициирует откат через GitLab API. Все — on-premise, без облачных сервисов.

```yaml
# Пайплайн: деплой с health-check
deploy:canary:
  stage: deploy
  script:
    - ./deploy-canary.sh
    - ./wait-for-healthcheck.sh --timeout=120
  environment:
    name: production/canary
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

deploy:full:
  stage: deploy
  needs: [deploy:canary]
  script: ./promote-canary.sh
  environment:
    name: production
  when: manual
```

**Скрипт alertmanager-webhook для отката:**
```bash
#!/bin/bash
# /opt/scripts/gitlab-rollback.sh — вызывается Alertmanager
ALERT_PAYLOAD=$1
DEPLOY_ENV=$(echo "$ALERT_PAYLOAD" | jq -r '.environment')
PROJECT_ID=$(echo "$ALERT_PAYLOAD" | jq -r '.project_id')
TOKEN=$GITLAB_API_TOKEN

# 1. Отмена активного pipeline (если ещё выполняется)
ACTIVE=$(curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.internal/api/v4/projects/$PROJECT_ID/pipelines?status=running&ref=main" \
  | jq '.[0].id // empty')

[ -n "$ACTIVE" ] && curl --request POST --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.internal/api/v4/projects/$PROJECT_ID/pipelines/$ACTIVE/cancel"

# 2. Запуск rollback-pipeline
curl --request POST \
  --form "token=$TRIGGER_TOKEN" \
  --form "ref=main" \
  --form "variables[ROLLBACK]=true" \
  --form "variables[ROLLBACK_ENV]=$DEPLOY_ENV" \
  "https://gitlab.internal/api/v4/projects/$PROJECT_ID/trigger/pipeline"

# 3. Создание Issue для инцидента
curl --request POST --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data "{\"title\":\"Auto-rollback: $DEPLOY_ENV\",\"labels\":[\"incident\"]}" \
  "https://gitlab.internal/api/v4/projects/$PROJECT_ID/issues"
```

### Сценарий 6: Миграция БД с resource_group и автоматическим уведомлением

Безопасная миграция с контролем времени выполнения и уведомлением через MR-комментарий.

```yaml
db_migrate:
  stage: deploy
  resource_group: database_cluster_prod
  resource_group_process_mode: oldest_first
  timeout: 30m
  script:
    - ./pre-checks.sh
    - ./run-migrations.sh
    - |
      if [ $? -ne 0 ]; then
        curl --request POST --header "JOB-TOKEN: $CI_JOB_TOKEN" \
          --header "Content-Type: application/json" \
          --data '{"title":"DB migration failed","labels":["incident","database"]}' \
          "https://gitlab.internal/api/v4/projects/$CI_PROJECT_ID/issues"
        exit 1
      fi
  artifacts:
    paths: [migration-log.txt]
    when: always
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### Сценарий 7: Мониторинг Runner-производительности через API

Пайплайн для еженедельного анализа использования раннеров и обнаружения проблем производительности.

```yaml
runner:report:
  stage: .pre
  script:
    - |
      # Получение статистики всех раннеров
      curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
        "https://gitlab.internal/api/v4/runners?per_page=100" | \
        jq -r '.[] | "\(.tag_list[0] // "untagged")|\(.status)|\(.active)|\(.jobs_completed)"' > runners.txt
    - |
      # Поиск неактивных раннеров
      INACTIVE=$(grep "|false|" runners.txt | wc -l)
      if [ "$INACTIVE" -gt 0 ]; then
        echo "WARNING: $INACTIVE inactive runners detected"
        curl --request POST --header "PRIVATE-TOKEN: $TOKEN" \
          --header "Content-Type: application/json" \
          --data "{\"title\":\"Inactive runners detected: $INACTIVE\",\"labels\":[\"maintenance\",\"runners\"]}" \
          "https://gitlab.internal/api/v4/projects/$CI_PROJECT_ID/issues"
      fi
    - ./generate-runner-report.sh
  artifacts:
    paths: [runners.txt, runner-report.html]
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  variables:
    TOKEN: $PROJECT_ACCESS_TOKEN
```

## Тестирование CI/CD конфигурации

Тестирование пайплайнов до коммита — критичная практика для SRE и DevOps-команд. GitLab предоставляет несколько уровней проверки.

### CI Lint API

Программная валидация YAML-конфигурации без запуска пайплайна. Используйте в pre-commit hook или в CI-стадии.

```bash
# Валидация .gitlab-ci.yml
curl --silent --request POST \
  --header "Content-Type: application/json" \
  --data @<(jq -n --arg content "$(cat .gitlab-ci.yml)" '{"content": $content}') \
  "https://gitlab.internal/api/v4/ci/lint" \
  | jq '{valid: .valid, errors: .errors, warnings: .warnings}'

# Валидация с included-файлами ( send file + project context)
curl --silent --request POST \
  --header "JOB-TOKEN: $CI_JOB_TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"content": "'"$(cat .gitlab-ci.yml)"'"}' \
  "https://gitlab.internal/api/v4/projects/$CI_PROJECT_ID/ci/lint"
```

### Статический анализ YAML перед коммитом

```yaml
# pre-commit hook (.gitlab-ci-lint.yml)
validate:config:
  stage: .pre
  image: alpine:latest
  before_script:
    - apk add --no-cache curl jq
  script:
    - |
      # Проверка синтаксиса YAML
      if ! python3 -c "import yaml; yaml.safe_load(open('.gitlab-ci.yml'))"; then
        echo "ERROR: Invalid YAML syntax"
        exit 1
      fi
    - |
      # CI Lint через API
      RESULT=$(curl --silent --request POST \
        --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        --header "Content-Type: application/json" \
        --data '{"content": "'"$(cat .gitlab-ci.yml)"'"}' \
        "https://gitlab.internal/api/v4/projects/$CI_PROJECT_ID/ci/lint")
      
      if [ "$(echo $RESULT | jq -r '.valid')" != "true" ]; then
        echo "ERROR: CI Lint failed"
        echo $RESULT | jq '.errors'
        exit 1
      fi
  rules:
    - changes:
        - .gitlab-ci.yml
        - "**/*.ci.yml"
```

### Unit-тестирование сценариев пайплайна

Для сложных пайплайнов рекомендуется тестировать критичные сценарии:

```yaml
test:pipeline:scenarios:
  stage: .pre
  script:
    - |
      # Тест 1: Проверка, что изменения в auth/ запускают deploy:auth
      python3 -c "
      import yaml
      import sys
      
      config = yaml.safe_load(open('.gitlab-ci.yml'))
      deploy_auth = config.get('deploy:auth', {})
      rules = deploy_auth.get('rules', [])
      
      has_changes = any(
        r.get('changes', []) == ['services/auth/**/*']
        for r in rules
      )
      
      if not has_changes:
          print('FAIL: deploy:auth missing changes rule')
          sys.exit(1)
      print('PASS: deploy:auth rules validated')
      "
    - |
      # Тест 2: Проверка наличия resource_group у критичных задач
      python3 -c "
      import yaml
      import sys
      
      config = yaml.safe_load(open('.gitlab-ci.yml'))
      critical_jobs = ['db_migrate', 'deploy:production']
      
      for job_name in critical_jobs:
          job = config.get(job_name, {})
          if 'resource_group' not in job:
              print(f'FAIL: {job_name} missing resource_group')
              sys.exit(1)
          print(f'PASS: {job_name} has resource_group')
      "
  rules:
    - changes:
        - .gitlab-ci.yml
        - "**/*.ci.yml"
```

## Устранение неполадок (Troubleshooting)

### Распространенные ошибки

-   **`Validation failed: spec:inputs`**: Несоответствие переданных параметров ожидаемым типам или опциям. Решение: Проверить `inputs` в UI и в YAML вызове. Убедиться, что типы совпадают (`string`, `number`, `boolean`).
-   **`OIDC identity provider rejected token`**: Ошибка в `aud` (audience) или в настройках Trust Policy на стороне OIDC-провайдера. Решение: Проверить соответствие `sub` клейма (project path, ref).
-   **Deadlock в Resource Group**: Если задача зависла и удерживает группу, последующие пайплайны будут ждать бесконечно. Решение: Ручная очистка в `CI/CD > Resource Groups` или настройка `timeout` на задаче.
-   **DAG Circular Dependency**: Задачи A и B зависят друг от друга в `needs`. Решение: Использование `stages` для разделения логики или пересмотр графа.
-   **`This project is not linked to a group`**: Использование `workflow:rules` с переменными группы без привязки проекта к группе. Решение: Убедиться, что проект находится в группе, либо использовать `CI_PROJECT_ROOT_NAMESPACE`.
-   **`included file not found`**: Неверный путь в `include:project` или `include:file`. Решение: Использовать относительные пути от корня репозитория, проверять через `CI_LINT` API.
-   **`needs [job_name] references an undefined job`**: Опечатка в имени задачи в `needs`. Решение: Проверить имена через CI Lint — он проверяет все ссылки.
-   **`workflow:rules:if: unknown variable`**: Использование переменной, которая не определена на момент проверки `workflow:rules`. Решение: Использовать только предопределённые переменные GitLab или дефолты.

### Инструменты диагностики

-   **CI Lint с симуляцией**: В Pipeline Editor обязательно выбирайте «Simulate pipeline» для проверки `rules` и `inputs`.
-   **CI_DEBUG_SERVICES**: Включите для отладки проблем с Docker-in-Docker или интеграциями. Подробности — см. **[Отладка и устранение неполадок](./debugging_and_troubleshooting.md)**.
-   **Exporting Variables**: Вывод `env | sort` (без секретов!) помогает понять иерархию приоритетов переменных.
-   **Pipeline Graph**: Визуализация зависимостей доступна в `CI/CD > Pipelines > [Pipeline ID] > Graph` — проверяйте, что DAG не содержит циклов.
-   **Resource Group Status**: Проверка текущего состояния очередей в `CI/CD > Resource Groups` — показывает, какие пайплайны ожидают доступа к ресурсу.
-   **Bridge Job Logs**: Для отладки downstream-пайплайнов проверяйте Bridge Jobs через API: `curl --header "PRIVATE-TOKEN: $TOKEN" "https://gitlab.internal/api/v4/projects/$ID/pipelines/$PID/bridges"`.

### Чек-лист: «Почему мой pipeline не запускается?»

| Проверка | Команда / Место |
|:---|:---|
| `workflow:rules` блокирует pipeline | `CI/CD > Pipelines` — нет pipelines? Проверьте `workflow:rules` через CI Lint |
| `rules` на задаче отфильтровали задачу | CI Lint > Simulate pipeline — проверьте, какие задачи видит симуляция |
| `needs` ссылаются на несуществующую задачу | CI Lint — ошибка `references an undefined job` |
| `resource_group` занят другой задачей | `CI/CD > Resource Groups` — проверьте очередь |
| `trigger:project` указывает на несуществующий проект | `Settings > CI/CD > Token Access` — проверьте, добавлен ли проект в allowlist |
| `include` не может найти файл | CI Lint — ошибка `included file not found` |

## Дополнительная информация

### Сравнение стратегий управления

| Инструмент | Уровень влияния | Основной кейс использования | SSoT-файл |
| :--- | :--- | :--- | :--- |
| **`workflow:rules`** | Пайплайн | Фильтрация триггеров (MR, Push, API) | [job_rules.md](./workflow_rules/job_rules.md) |
| **`resource_group`** | Ресурс | Предотвращение Race Conditions | [matrix_builds_and_serialization.md](./workflow_rules/matrix_builds_and_serialization.md) |
| **`spec:inputs`** | Конфигурация | Типизация и UI-формы | [variables_best_practices.md](./workflow_rules/variables_best_practices.md) |
| **`auto_cancel`** | Раннеры | Экономия ресурсов | [gitlab_ci_workflow_builder.md](./gitlab_ci_workflow_builder.md) |
| **`needs` (DAG)** | Задачи | Параллельное выполнение | [dag_with_needs.md](./workflow_rules/dag_with_needs.md) |
| **`parallel:matrix`** | Задачи | Кросс-платформенное тестирование | [matrix_builds_and_serialization.md](./workflow_rules/matrix_builds_and_serialization.md) |
| **Pipeline Execution Policies** | Пайплайн | Обязательные задачи безопасности | **Данный файл (SSoT)** |
| **SLSA / SBOM** | Артефакты | Аттестация и комплаенс | [gitlab_ci_artifacts.md](./gitlab_ci_caching/gitlab_ci_artifacts.md) |

### См. также

-   **[Определения всех директив](./workflow_rules/directives_definitions.md)** — справочная таблица с версиями GitLab для каждой директивы.
-   **[DAG с needs](./workflow_rules/dag_with_needs.md)** — глубокое погружение в графы зависимостей.
-   **[Матричные сборки и сериализация](./workflow_rules/matrix_builds_and_serialization.md)** — `parallel:matrix`, `resource_group`, `needs:parallel:matrix`.
-   **[Оптимальные переменные](./workflow_rules/variables_best_practices.md)** — приоритеты, `spec:inputs`, `id_tokens`.
-   **[Parent-Child Pipelines](./Downstream_Pipelines/parent_child_pipelines.md)** — архитектура монорепо, Bridge Jobs, strategy mirror.
-   **[Динамическая генерация пайплайнов](./Downstream_Pipelines/dynamic_generation.md)** — Trigger by Artifact, генерация YAML через скрипты.
-   **[Multi-project Pipelines](./Downstream_Pipelines/multi_project_pipelines.md)** — кросс-проектные пайплайны, fan-out/fan-in.
-   **[Лучшие практики Downstream](./Downstream_Pipelines/best_practices.md)** — CI_JOB_TOKEN,allowlist, ограничение глубины.
-   **[Программная автоматизация: API и Webhooks](./api_and_webhooks_automation.md)** — REST API, GraphQL, Webhooks, токены.
-   **[Отладка и устранение неполадок](./debugging_and_troubleshooting.md)** — `glab`, `CI_DEBUG_TRACE`, интерактивный терминал.
-   **[Конструктор рабочих процессов](./gitlab_ci_workflow_builder.md)** — базовые блоки, артефакты, кэширование.
-   **[Артефакты и кэширование](./gitlab_ci_caching/gitlab_ci_artifacts.md)** — SBOM, `cyclonedx`, артефакты отчётов.
-   **[Безопасность цепочки поставок](../../../Security/Supply_Chain_Security/overview.md)** — детализация SBOM и аттестаций.
-   **[Sigstore и OIDC](../../../Security/Tools/sigstore.md)** — подпись артефактов временными токенами.
-   **[HashiCorp Vault: Zero Trust](../../../Vault/zero_trust.md)** — беспарольный доступ через OIDC.

