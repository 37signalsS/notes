# Программная автоматизация: API и Webhooks в GitLab CI/CD

## Определения

**Программное управление CI/CD** — это методология управления жизненным циклом разработки через внешние интерфейсы (API) и механизмы обратных вызовов (Webhooks). Это позволяет интегрировать GitLab CI/CD с внешними системами оркестрации, мониторинга и безопасности, выходя за рамки стандартных событий системы контроля версий.

**Ключевые механизмы:**

-   **REST API (v4)**: Основной интерфейс для управления ресурсами GitLab. Позволяет выполнять CRUD-операции над проектами, пайплайнами, задачами (Jobs), переменными и артефактами.
-   **GraphQL API**: Альтернативный интерфейс, позволяющий запрашивать строго определенные данные в одном запросе. Идеален для построения дашбордов и мониторинга статусов сложных пайплайнов без избыточной передачи данных.
-   **Trigger API**: Специализированный легковесный эндпоинт REST API, предназначенный исключительно для инициирования новых пайплайнов внешними системами с использованием Trigger Tokens.
-   **Webhooks (Вебхуки)**: Механизм Push-уведомлений, при котором GitLab отправляет HTTP POST запрос с JSON-нагрузкой (payload) на внешний URL при возникновении определенных событий (изменение статуса пайплайна, создание тега, обновление Merge Request).

### Типы токенов аутентификации

GitLab предоставляет несколько типов токенов для доступа к API. Выбор зависит от контекста использования — из пайплайна, из внешней системы или для управления инстансом:

| Токен | Область видимости | Где создаётся | Основной случай использования |
| :--- | :--- | :--- | :--- |
| **Personal Access Token (PAT)** | Права пользователя во всех проектах | `User Settings > Access Tokens` | Локальная разработка, личные скрипты |
| **Project Access Token** | Права в конкретном проекте | `Project Settings > Access Tokens` | CI/CD-задачи, автоматизация проекта |
| **Group Access Token** | Права на уровне группы и всех её проектов | `Group Settings > Access Tokens` | Групповая автоматизация, политики |
| **Deploy Token** | Read-only доступ к Registry и Repository | `Project Settings > Repository > Deploy Tokens` | wget/curl артефактов, pull образов |
| **Trigger Token** | Только запуск пайплайнов (не даёт доступа к данным) | `Project Settings > CI/CD > Pipeline triggers` | Внешние триггеры пайплайнов |
| **CI_JOB_TOKEN** | Автоматический, ограничен контекстом задачи | Генерируется Runner'ом автоматически | Межпроектные вызовы, Registry, Downstream |

**Важно:** Все API-вызовы требуют передачи токена через HTTP-заголовок. Для персональных и проектных токенов используется `PRIVATE-TOKEN`, для `CI_JOB_TOKEN` — `JOB-TOKEN`.

### Механизм id_tokens (OIDC)

Начиная с GitLab 16.0+ (стандарт к 2026 году) для аутентификации во внешних сервисах рекомендуется использовать `id_tokens` — временные JWT-токены, генерируемые для каждой задачи. Это механизм **Workload Identity Federation**, который полностью устраняет необходимость хранения долгоживущих секретов.

**Принцип работы:**
1.  GitLab создаёт JWT для задачи, подписывает его закрытым ключом инстанса.
2.  Задача получает токен через переменную окружения (`$VAULT_ID_TOKEN`).
3.  Внешний сервис (Vault, Kubernetes, Object Storage) проверяет JWT через OIDC-эндпоинт GitLab.

**Пример получения токена Vault через OIDC:**

```yaml
deploy:
  id_tokens:
    VAULT_ID_TOKEN:
      aud: https://vault.internal:8200
  script:
    - export VAULT_TOKEN=$(vault write -field=token auth/jwt/login role=ci-role jwt=$VAULT_ID_TOKEN)
    - vault kv get -field=db_password secret/myapp/db
```

**Преимущества перед `CI_JOB_TOKEN`:**
-   `id_tokens` могут использоваться для аутентификации в *любом* OIDC-совместимом сервисе, не только в GitLab API.
-   Время жизни токена ограничено (по умолчанию 1 час), что снижает риски компрометации.
-   Аудитория (`aud`) настраивается явно, что предотвращает reuse токена в других сервисах.

Подробнее см. **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)**.

## Принципы работы и архитектура

### REST vs GraphQL в контексте CI/CD

| Характеристика | REST API | GraphQL |
| :--- | :--- | :--- |
| **Стиль запросов** | Ресурсный (эндпоинты под каждый тип) | Декларативный (одна точка входа) |
| **Объем данных** | Часто избыточен (Over-fetching) | Строго по запросу |
| **Использование в CI** | Удобен для триггеров и управления файлами | Удобен для сбора метрик и сложных связей |
| **Аутентификация** | Header/Token/OAuth2 | Header/Token/OAuth2 |

### Жизненный цикл события Webhook

1.  **Триггер**: В GitLab происходит событие (например, `Pipeline success`).
2.  **Формирование Payload**: GitLab собирает контекст (ID проекта, ветка, статус, автор) в JSON-объект.
3.  **Отправка**: GitLab выполняет асинхронный HTTP POST запрос на настроенный URL.
4.  **Обработка**: Внешний сервис принимает запрос. **Важно**: GitLab ожидает ответ (обычно 200 OK) в течение 10 секунд.
5.  **Retry Policy**: Если внешний сервис недоступен или вернул ошибку, GitLab может повторить попытку (зависит от настроек инстанса).

## Работа с GitLab REST API

### 1. Программное создание пайплайнов (Pipeline Triggers)

Для запуска пайплайна внешней системой (например, после успешной сборки образа в другом репозитории или по сигналу мониторинга) используется Trigger API.

**Базовый вызов через `curl`:**

```bash
curl --request POST \
     --form token="GLPT_xxxxxxxxxxxxx" \
     --form ref="main" \
     --form "variables[DEPLOY_ENV]=production" \
     --form "variables[DEBUG]=true" \
     "https://gitlab.example.com/api/v4/projects/123/trigger/pipeline"
# → {"id": 456, "status": "pending", ...}
```

**Особенности безопасности:**
-   **Trigger Token**: Создается в `Settings > CI/CD > Pipeline triggers`. Не дает доступа к данным проекта, только на запуск.
-   **`CI_JOB_TOKEN`**: Внутри пайплайна можно использовать встроенный токен для запуска Downstream-пайплайнов, но его права ограничены (см. [Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)).

### 2. Управление переменными проекта

Используется для динамической ротации секретов, обновления версий зависимостей или изменения параметров инфраструктуры.

**Обновление существующей переменной:**

```bash
curl --request PUT \
     --header "PRIVATE-TOKEN: <your_access_token>" \
     --header "Content-Type: application/json" \
     --data '{"value": "new_secret_value", "protected": true, "masked": true}' \
     "https://gitlab.example.com/api/v4/projects/123/variables/DB_PASSWORD"
```

### 3. Валидация конфигурации (CI Lint API)

Позволяет проверить корректность `.gitlab-ci.yml` программно до того, как изменения будут запушены в репозиторий.

```bash
curl --header "PRIVATE-TOKEN: <token>" \
     --header "Content-Type: application/json" \
     --data "{\"content\": \"$(cat .gitlab-ci.yml | sed 's/"/\\"/g')\"}" \
     "https://gitlab.example.com/api/v4/ci/lint"
```

## Версионирование и пагинация API

### Версионирование

GitLab API использует URL-based versioning: `/api/v4/...`. Текущая стабильная версия — **v4**. При выходе новой версии API (например, v5) старая версия поддерживается минимум 3 года, но новые функции появляются только в актуальной.

**Рекомендация:** Явно указывайте версию API во всех вызовах. Не используйте `latest` — это может сломать автоматизацию при обновлении инстанса.

### Пагинация

GitLab API возвращает максимум **20 записей** на страницу по умолчанию (максимум — 100). Для получения всех данных используйте параметры `page` и `per_page`:

```bash
#!/bin/bash
# Получение всех проектов группы с пагинацией
page=1
while true; do
  response=$(curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
    "https://gitlab.example.com/api/v4/groups/123/projects?per_page=100&page=$page")
  count=$(echo "$response" | jq length)
  if [ "$count" -eq 0 ]; then
    break
  fi
  echo "$response" | jq -r '.[].path_with_namespace'
  page=$((page + 1))
done
```

**Заголовки пагинации:** GitLab возвращает метаданные пагинации в HTTP-заголовках:
-   `X-Next-Page` — номер следующей страницы (пусто, если данных больше нет)
-   `X-Total` — общее количество записей
-   `X-Total-Pages` — общее количество страниц

Эти заголовки позволяют оптимизировать логику без лишних запросов.

## API внутри пайплайна: паттерны использования

Вызов GitLab API изнутри CI/CD-задачи — распространённый паттерн для автоматизации, который выходит за рамки стандартных директив YAML. Это позволяет реализовывать динамическую логику, недоступную через декларативную конфигурацию.

### Когда использовать API внутри задач

| Сценарий | Пример | Рекомендуемый токен |
| :--- | :--- | :--- |
| Динамическое создание окружений | Регистрация нового review-app в справочнике | `CI_JOB_TOKEN` |
| Публикация результатов анализа | Загрузка SBOM-отчёта как артефакт MR | `CI_JOB_TOKEN` |
| Управление переменными | Ротация секрета после деплоя | Project Access Token |
| Очистка ресурсов | Удаление временных веток/тегов | `CI_JOB_TOKEN` |
| Интеграция с внешними системами | Отправка уведомления в Slack/Matrix | Project Access Token |
| Валидация состояния | Проверка, что MR одобрен перед деплоем | `CI_JOB_TOKEN` |

### Паттерн: Динамическое окружение через API

```yaml
create_environment:
  stage: deploy
  script:
    - |
      # Регистрируем окружение через API
      ENV_ID=$(curl --silent --request POST \
        --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        --header "Content-Type: application/json" \
        --data "{\"name\": \"review-$CI_MERGE_REQUEST_IID\", \"external_url\": \"https://review-$CI_MERGE_REQUEST_IID.example.com\"}" \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/environments" | jq '.id')
      echo "Created environment ID: $ENV_ID"
    - ./deploy.sh
  environment:
    name: review/$CI_MERGE_REQUEST_IID
    url: https://review-$CI_MERGE_REQUEST_IID.example.com
    on_stop: stop_review
  rules:
    - if: $CI_MERGE_REQUEST_IID

stop_review:
  stage: cleanup
  script:
    # Остановка окружения и связанных ресурсов
    - curl --silent --request POST \
        --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/environments/$ENV_ID/stop"
  when: manual
  environment:
    name: review/$CI_MERGE_REQUEST_IID
    action: stop
```

### Паттерн: Публикация результатов анализа в MR

```yaml
security_scan:
  stage: test
  script:
    - ./run-trivy-scan.sh --format json --output results.json
    - |
      # Публикация результатов как комментарий к MR
      if [ -n "$CI_MERGE_REQUEST_IID" ]; then
        SCAN_RESULT=$(cat results.json | jq -r '.Results[0].Vulnerabilities | length')
        BODY="## Security Scan Results\n\nVulnerabilities found: $SCAN_RESULT\n\n\`\`\`json\n$(cat results.json | jq '.Results[0].Vulnerabilities[:5]')\n\`\`\`"
        curl --silent --request POST \
          --header "JOB-TOKEN: $CI_JOB_TOKEN" \
          --header "Content-Type: application/json" \
          --data "{\"body\": \"$BODY\"}" \
          "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes"
      fi
  artifacts:
    paths: [results.json]
    reports:
      container_scanning: results.json
```

**Важные ограничения `CI_JOB_TOKEN` в API:**
-   Токен доступен только в пределах текущей задачи и истекает при её завершении.
-   Права токена ограничены: он может обращаться к API только проекта, в котором запущена задача.
-   Для кросс-проектных вызовов требует явного добавления целевого проекта в **Inbound Allowlist** (см. [Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)).

## Управление пайплайнами через API

REST API позволяет управлять жизненным циклом пайплайнов программно — это критично для автоматизации откатов, повторных запусков и мониторинга.

### Основные операции

```bash
# Получение списка пайплайнов проекта
curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/123/pipelines?status=failed&per_page=10" \
  | jq '.[].id'
# → 456 457 458

# Повторный запуск неудачного пайплайна
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/123/pipelines/456/retry"
# → {"id":456,"status":"pending",...}

# Отмена.running пайплайна
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/123/pipelines/456/cancel"
# → {"id":456,"status":"canceling",...}

# Удаление пайплайна и его артефактов
curl --request DELETE \
  --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/123/pipelines/456"
# → 204 No Content
```

### Получение артефактов пайплайна

```bash
# Скачивание артефактов конкретной задачи
curl --header "JOB-TOKEN: $CI_JOB_TOKEN" \
  --output artifacts.zip \
  "https://gitlab.example.com/api/v4/projects/123/jobs/789/artifacts"
```

### Мониторинг Bridge Jobs (Downstream-пайплайны)

Для отслеживания статуса дочерних пайплайнов, запущенных через `trigger`, используется эндпоинт bridges:

```bash
# Получение статуса всех Bridge Jobs пайплайна
curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/123/pipelines/456/bridges" \
  | jq '.[] | {id: .id, status: .status, trigger: .trigger}'
# → {"id":789,"status":"success","trigger":{"project":"group/child-project"}}
```

Этот эндпоинт критичен для обнаружения deadlock в downstream-пайплайнах и мониторинга глубины цепочек. Подробнее — см. **[Downstream-пайплайны: лучшие практики](./Downstream_Pipelines/best_practices.md)**.

## Использование GraphQL для мониторинга

GraphQL позволяет эффективно запрашивать состояние пайплайнов, избегая N+1 запросов в REST.

**Пример запроса статуса пайплайна и задач:**

```graphql
query {
  project(fullPath: "group/project") {
    pipeline(iid: "456") {
      status
      duration
      jobs {
        nodes {
          name
          status
          allowFailure
        }
      }
    }
  }
}
```

## Системные Webhooks для реактивной автоматизации

Вебхуки превращают GitLab в активный узел событийной архитектуры.

### Типы событий и ключевые поля Payload

-   **Pipeline Events**: Срабатывает при изменении статуса (`pending`, `running`, `success`, `failed`, `canceled`).
-   **Merge Request Events**: Уведомляет о создании, закрытии или слиянии MR.
-   **Job Events**: Детальные уведомления о каждой задаче (полезно для мгновенного логирования сбоев).

### Безопасная обработка вебхуков

**Ключевые угрозы:**
-   **Подделка запроса (Webhook Spoofing):** Злоумышленник отправляет POST-запрос на эндпоинт приёмника без валидной подписи. Если приёмник не проверяет подпись — любой может инициировать пайплайн или изменить конфигурацию.
-   **Перехват payloads:** При передаче по HTTP (без TLS) данные (включая токены и секреты) могут быть перехвачены.
-   **Replay-атаки:** Повторная отправка перехваченного запроса с валидной подписью.

**Алгоритм проверки HMAC-SHA256 подписи (Python):**

GitLab подписывает каждый вебхук секретным ключом, настроенным в `Settings > Webhooks`. Подпись передаётся в заголовке `X-Gitlab-Token` (для shared secret) или `X-Gitlab-Signature` (для HMAC).

```python
import hmac
import hashlib
from flask import Flask, request, abort

app = Flask(__name__)
GITLAB_WEBHOOK_SECRET = "your_shared_secret_key"

def verify_gitlab_signature(payload_body, secret, signature_header):
    """Проверка HMAC-SHA256 подписи GitLab."""
    if not signature_header:
        return False
    expected = hmac.new(
        secret.encode('utf-8'),
        payload_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)

@app.route('/webhook', methods=['POST'])
def handle_gitlab_event():
    # Проверка подписи HMAC
    signature = request.headers.get('X-Gitlab-Token')
    if not verify_gitlab_signature(request.data, GITLAB_WEBHOOK_SECRET, signature):
        abort(403, description="Invalid signature")

    data = request.json
    event_type = request.headers.get('X-Gitlab-Event')

    if event_type == 'Pipeline Hook':
        status = data['object_attributes']['status']
        if status == 'failed':
            process_failure(data)
        elif status == 'success':
            process_success(data)

    return 'OK', 200
```

**Дополнительные меры безопасности:**
-   **TLS-обязателен:** Все webhook-эндпоинты должны работать через HTTPS. GitLab не отправляет вебхуки на HTTP (кроме `localhost` в development-режиме).
-   **IP-фильтрация:** GitLab публикует список IP-адресов для исходящих вебхуков (доступно в `Admin > Settings > Network > Outbound requests`). Настройте файрвол для ограничения доступа.
-   **Таймаут ответа:** GitLab ожидает HTTP 200 OK в течение **10 секунд**. Если сервис не отвечает — запрос считается неуспешным и может быть повторён (зависит от настроек retry policy инстанса).
-   **Retry Policy:** По умолчанию GitLab повторяет неуспешные вебхуки до **3 раз** с интервалом ~1 минута. Настройки retry доступны для администраторов инстанса в `Admin > Settings > General > Webhooks`.

## Продвинутые сценарии автоматизации

### 1. Внешние Quality Gates (Quality Gate as a Service)

Пайплайн останавливается на задаче с `when: manual` или ожидает подтверждения через API. Внешняя система (статический анализатор безопасности, линтер конфигураций) проводит проверку и отправляет команду на продолжение:

```bash
# Разблокировка ручной задачи (Play job)
curl --request POST \
     --header "PRIVATE-TOKEN: <token>" \
     "https://gitlab.example.com/api/v4/projects/123/jobs/456/play"
# → 200 OK
```

**Сценарий:** Пайплайн выполняет `terraform plan`, результат загружается как артефакт. Внешний OPA-сервер (Open Policy Agent) анализирует план на соответствие политикам. Если план безопасен — OPA вызывает API для разблокировки задачи `terraform apply`.

### 2. Self-Healing: автоматический откат при росте ошибок

Система мониторинга (Prometheus + Alertmanager) обнаруживает аномалию после деплоя и инициирует откат через GitLab API:

```bash
#!/bin/bash
# Скрипт, вызываемый Alertmanager через webhook
# Получение данных из payload алерта
DEPLOY_ENV=$(echo "$ALERT_PAYLOAD" | jq -r '.environment')
PROJECT_ID=$(echo "$ALERT_PAYLOAD" | jq -r '.project_id')

# 1. Отмена активного пайплайна деплоя (если ещё выполняется)
ACTIVE_PIPELINE=$(curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines?ref=main&status=running" \
  | jq '.[0].id')

if [ "$ACTIVE_PIPELINE" != "null" ]; then
  curl --request POST --header "PRIVATE-TOKEN: $TOKEN" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$ACTIVE_PIPELINE/cancel"
fi

# 2. Запуск пайплайна отката
curl --request POST \
  --form token="TRIGGER_TOKEN" \
  --form ref="main" \
  --form "variables[ROLLBACK]=true" \
  --form "variables[ROLLBACK_ENV]=$DEPLOY_ENV" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/trigger/pipeline"

# 3. Создание инцидента через GitLab Issues API
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data '{
    "title": "Auto-rollback triggered for '"$DEPLOY_ENV"'",
    "description": "## Incident\n\n**Severity:** Critical\n\n**Trigger:** Error rate exceeded 5% threshold.\n\n**Action:** Automatic rollback initiated via pipeline trigger.\n\n**Logs:** [Pipeline '$ACTIVE_PIPELINE'](https://gitlab.example.com/'"$PROJECT_ID"'/pipelines/'"$ACTIVE_PIPELINE"')",
    "labels": ["incident", "auto-rollback", "'"$DEPLOY_ENV"'"]
  }' \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/issues"
```

### 3. Автоматизация ротации секретов

Внешний менеджер секретов (Vault, SOPS) генерирует новый пароль и обновляет его в GitLab через API:

```bash
#!/bin/bash
# Ротация секрета с уведомлением в Audit Events
NEW_SECRET=$(vault kv get -field=new_password secret/prod/db)

# Обновление переменной в GitLab
curl --request PUT \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data "{\"value\": \"$NEW_SECRET\", \"protected\": true, \"masked\": true}" \
  "https://gitlab.example.com/api/v4/projects/123/variables/DB_PASSWORD"

# Проверка, что переменная обновилась
VERIFY=$(curl --silent --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/123/variables/DB_PASSWORD" \
  | jq '.protected')
echo "Variable protected: $VERIFY"
# → Variable protected: true

# Создание Issue для команды
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data '{"title": "DB password rotated", "description": "Secret DB_PASSWORD rotated at '"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'. Next rotation scheduled in 30 days.", "labels": ["security", "secret-rotation"]}' \
  "https://gitlab.example.com/api/v4/projects/123/issues"
```

### 4. Миграция БД через API-оркестрацию

Сценарий безопасной миграции базы данных: запуск migration-задачи с контролем времени выполнения и автоматическим откатом:

```yaml
db_migration:
  stage: deploy
  script:
    - |
      # Блокировка деплоя其它 задач через Resource Group
      echo "Starting migration..."
      ./run-migration.sh
      MIGRATION_EXIT=$?
    - |
      if [ $MIGRATION_EXIT -ne 0 ]; then
        # Создание инцидента через API
        curl --request POST \
          --header "JOB-TOKEN: $CI_JOB_TOKEN" \
          --header "Content-Type: application/json" \
          --data '{"title": "DB migration failed", "labels": ["incident", "database"]}' \
          "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/issues"
        exit 1
      fi
    - |
      # Уведомление об успехе
      curl --request POST \
        --header "JOB-TOKEN: $CI_JOB_TOKEN" \
        --header "Content-Type: application/json" \
        --data "{\"body\": \"Migration completed successfully at $(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/merge_requests/$CI_MERGE_REQUEST_IID/notes"
  resource_group: database_migration
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
  timeout: 30m
```

## Устранение неполадок

### Типичные ошибки API и их причины

-   **401 Unauthorized**: Истек или неверно указан токен доступа. Убедитесь, что используете заголовок `PRIVATE-TOKEN` для персональных/проектных токенов и `JOB-TOKEN` для токенов пайплайна. Проверьте, не истёк ли токен в `Settings > Access Tokens`.
-   **403 Forbidden**: Недостаточно прав. Для управления переменными или запуска задач обычно требуется роль `Maintainer` или `Owner`. Для `CI_JOB_TOKEN` — проверьте, добавлен ли целевой проект в Inbound Allowlist (Settings > CI/CD > Token Access).
-   **404 Not Found**: Неверный ID проекта (иногда требует URL-кодирования пути `group%2Fproject`) или ресурс удален. Используйте `path_with_namespace` вместо числового ID для читаемости.
-   **409 Conflict**: Конфликт состояний — например, попытка создать переменную, которая уже существует. Используйте `PUT` вместо `POST` для обновления.
-   **422 Unprocessable Entity**: Невалидные данные запроса. Проверьте JSON-структуру тела запроса. Частая причина — отсутствие обязательных полей (`key`, `value`, `ref`).
-   **429 Too Many Requests**: Превышен Rate Limit. GitLab ограничивает количество запросов в секунду/минуту для защиты от DoS. Лимиты зависят от версии инстанса (по умолчанию ~60 запросов/минуту для API, ~60 для GraphQL).
-   **500 Internal Server Error**: Серверная ошибка GitLab. Проверьте статус инстанса (`/help`), повторите запрос через несколько минут.

### Стратегии обработки Rate Limiting

При автоматизации массовых операций используйте **Exponential Backoff** с jitter:

```python
import time
import requests
import random

def call_gitlab_api(url, headers, method='GET', data=None, max_retries=5):
    """Вызов API с exponential backoff и jitter."""
    for attempt in range(max_retries):
        response = requests.request(method, url, headers=headers, json=data)

        if response.status_code == 429:
            # Базовое ожидание + случайный jitter для избежания thundering herd
            base_wait = 2 ** attempt
            jitter = random.uniform(0, base_wait * 0.5)
            wait = base_wait + jitter
            print(f"Rate limited. Waiting {wait:.1f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue

        return response

    raise Exception(f"API call failed after {max_retries} retries")
```

**Оптимизация массовых операций:**
-   Используйте **Batch API** (если доступен на вашей версии GitLab) для обработки нескольких ресурсов за один запрос.
-   Кэшируйте результаты запросов, которые не меняются часто (списки проектов, группы).
-   Выполняйте операции в **off-peak hours** (ночные часы) для критичных массовых обновлений.

### Диагностика вебхуков

```bash
# Проверка последних доставок вебхуков через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/123/hooks" \
  | jq '.[] | {id: .id, url: .url, active: .active, last_delivery_at: .last_delivery_at}'

# Повторная отправка конкретного вебхука (debug)
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/123/hooks/456/test"
# → 200 OK если доставка успешна
```

### Типичные ошибки вебхуков

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Вебхук не доставляется | URL недоступен из сети GitLab | Проверьте файрвол, DNS, TLS-сертификат |
| Payload пустой или обрезан | Лимит размера тела запроса (10 МБ) | Уменьшите объём данных в payload или используйте API для получения полных данных |
| Дублирующиеся уведомления | Retry policy сработала повторно | Сделайте обработку **идемпотентной** (проверяйте `idempotency_key` или `object_attributes.id`) |
| Webhook доставляется с задержкой | Очередь доставки GitLab перегружена | Проверьте статус инстанса; для критичных событий дублируйте через API polling |

## Практические рекомендации и Best Practices

### Аутентификация и безопасность

-   **Минимизация прав**: Используйте Project Access Tokens с минимально необходимыми scope (`api` для управления, `read_api` для мониторинга) вместо Personal Access Tokens. PAT даёт доступ ко всем проектам пользователя — это нарушает принцип наименьших привилегий (POLP).
-   **`CI_JOB_TOKEN` для CI/CD-задач**: Внутри пайплайна всегда предпочитайте `CI_JOB_TOKEN` внешним токенам. Токен автоматически истекает при завершении задачи, что исключает компрометацию при утечке логов.
-   **OIDC вместо статических секретов**: Для интеграции с Vault, Kubernetes и внешними сервисами используйте `id_tokens` вместо хранения долгоживущих паролей в переменных. См. раздел [Механизм id_tokens (OIDC)](#механизм-id_tokens-oidc).
-   **Валидация Payload**: Не доверяйте данным из вебхука без проверки HMAC-SHA256 подписи (`X-Gitlab-Token` заголовок). См. раздел [Безопасная обработка вебхуков](#безопасная-обработка-вебхуков).
-   **Маскирование**: Всегда устанавливайте флаг `masked: true` для переменных, создаваемых через API, чтобы они не попали в логи.

### Производительность и надёжность

-   **Асинхронность**: Всегда отвечайте `200 OK` на вебхук мгновенно, перенося тяжелую логику обработки в фоновые задачи (Celery, Redis, Sidekiq). GitLab ждёт ответа не более 10 секунд.
-   **Идемпотентность**: Реализуйте повторную обработку webhook-событий без побочных эффектов. Используйте `object_attributes.id` как уникальный ключ для дедупликации.
-   **Кэширование**: Для часто запрашиваемых данных (списки проектов, группы, переменные) кэшируйте результаты API-вызовов. Время жизни кэша — не более 5 минут для данных, которые могут измениться.
-   **Пагинация**: Всегда обрабатывайте пагинацию при получении списков. Не предполагайте, что все данные помещаются в один ответ.

### Диагностика и мониторинг

-   **Логирование API-вызовов**: Записывайте URL, статус-код и время ответа каждого вызова для последующего анализа.
-   **Алерты на Rate Limit**: Настройте уведомления при получении HTTP 429 — это сигнал о необходимости оптимизации частоты запросов.
-   **Healthcheck webhook-приёмника**: Регулярно проверяйте доступность эндпоинта через GitLab API (`POST /projects/:id/hooks/:hook_id/test`).

### Обратная совместимость

-   **Версионирование**: Явно указывайте версию API (`/api/v4/`) во всех вызовах. Не используйте relative paths без указания версии.
-   **Депрекация**: При использовании deprecated-эндпоинтов (например, registration tokens в v16.0+) планируйте миграцию заранее. GitLab предоставляет minimum 1 год deprecated-периода.

## Дополнительная информация

-   **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — безопасность `CI_JOB_TOKEN`, `id_tokens` (OIDC), приоритеты переменных.
-   **[Downstream-пайплайны: лучшие практики](./Downstream_Pipelines/best_practices.md)** — мониторинг Bridge Jobs через API, обнаружение deadlock, управление цепочками.
