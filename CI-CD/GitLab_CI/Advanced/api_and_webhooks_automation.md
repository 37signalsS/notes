# Программная автоматизация: API и Webhooks в GitLab CI/CD

**Актуально для:** GitLab CI/CD 17.x–19.4

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

Начиная с GitLab 16.0+ для аутентификации во внешних сервисах рекомендуется использовать `id_tokens` — временные JWT-токены, генерируемые для каждой задачи. Это механизм **Workload Identity Federation**, который полностью устраняет необходимость хранения долгоживущих секретов.

**Принцип работы:**
1.  GitLab создаёт JWT для задачи, подписывает его закрытым ключом инстанса.
2.  Задача получает токен через переменную окружения (`$VAULT_ID_TOKEN`).
3.  Внешний сервис (Vault, внутренний Object Storage) проверяет JWT через OIDC-эндпоинт GitLab.

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

## Предварительные требования

### Версии и поддерживаемые функции

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| REST API v4 | GitLab 17.x–19.4 | Стабильная версия API, backwards compatible |
| GraphQL API | GitLab 17.x–19.4 | Альтернативный интерфейс для сложных запросов |
| Trigger API | GitLab 17.x–19.4 | Легковесный эндпоинт для запуска пайплайнов |
| Webhooks | GitLab 17.x–19.4 | HMAC-SHA256 подпись доступна во всех версиях |
| `id_tokens` (OIDC) | GitLab 16.0+ | Глобальный `default:` — с 16.4+ |
| CI Lint API | GitLab 17.x–19.4 | Программная валидация `.gitlab-ci.yml` |
| Pipeline triggers | GitLab 17.x–19.4 | Trigger Tokens создаются в UI проекта |

### Инфраструктурные требования

-   **GitLab Instance**: Self-hosted или GitLab.com с доступом к REST/GraphQL API
-   **Сеть**: Исходящие HTTP/HTTPS-соединения из GitLab для webhook-доставки; входящие соединения для приёмника вебхуков
-   **TLS-сертификаты**: Все webhook-эндпоинты должны работать через HTTPS с валидным сертификатом
-   **Firewall**: Разрешены IP-адреса GitLab для исходящих вебхуков (см. `Admin > Settings > Network > Outbound requests`)
-   **Время**: Синхронизация времени между GitLab и внешними системами (NTP) — критична для проверки JWT-подписи

### Необходимые знания

-   REST/HTTP: методы GET/POST/PUT/DELETE, заголовки, коды состояний
-   JSON: структура payload, сериализация/десериализация
-   Bash/Python: написание скриптов для автоматизации API-вызовов
-   GitLab RBAC: роли `Guest`, `Reporter`, `Developer`, `Maintainer`, `Owner` и их права на API
-   HMAC-SHA256: принципы подписи и проверки webhook-запросов

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

# Отмена running пайплайна
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
      # Блокировка деплоя других задач через Resource Group
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

## Валидация конфигурации

Перед внедрением API-автоматизации или webhook-обработчика проверьте конфигурацию на всех уровнях:

### 1. Синтаксис и структура

```bash
# Локальная проверка YAML-файлов с вебхук-обработчиками
python3 -c "import yaml; yaml.safe_load(open('webhook_handler.yml'))"

# Для Python-скриптов
python3 -m py_compile webhook_server.py
```

### 2. CI Lint API

Программная проверка `.gitlab-ci.yml` до коммита:

```bash
curl --header "PRIVATE-TOKEN: $TOKEN" \
     --header "Content-Type: application/json" \
     --data "{\"content\": \"$(cat .gitlab-ci.yml | sed 's/\"/\\\"/g')\"}" \
     "https://gitlab.example.com/api/v4/ci/lint"
# → {"status": "valid", "errors": [], "warnings": []}
```

### 3. Тестирование Webhook-доставки

```bash
# Ручная отправка тестового вебхука
curl --request POST \
     --header "X-Gitlab-Token: $WEBHOOK_SECRET" \
     --header "X-Gitlab-Event: Pipeline Hook" \
     --header "Content-Type: application/json" \
     --data '{"object_attributes": {"status": "failed"}}' \
     "https://webhook-receiver.internal/webhook"

# Проверка доставки через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/123/hooks" \
     | jq '.[] | {id, url, last_delivery_at, last_error_message}'
```

### 4. Валидация HMAC-подписи

```python
import hmac
import hashlib

def test_signature():
    secret = "test_secret"
    payload = b'{"test": true}'
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    print(f"Expected signature: {signature}")
    # Сравните с X-Gitlab-Signature-256 заголовком
```

### 5. Проверка прав токена

```bash
# Проверка Project Access Token
curl --header "PRIVATE-TOKEN: $TOKEN" \
     "https://gitlab.example.com/api/v4/projects/123"
# → 200 OK = токен имеет доступ к проекту

# Проверка CI_JOB_TOKEN внутри пайплайна
curl --header "JOB-TOKEN: $CI_JOB_TOKEN" \
     "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID"
# → 200 OK = токен действителен
```

### 6. Dry-run через переменные

```bash
# Тест Trigger API без реального запуска
curl --request POST \
     --form token="GLPT_xxxxxxxxxxxxx" \
     --form ref="main" \
     --form "variables[DRY_RUN]=true" \
     "https://gitlab.example.com/api/v4/projects/123/trigger/pipeline"
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

### Retry и Circuit Breaker для Pipeline Triggers API

Pipeline Triggers API (`POST /projects/:id/trigger/pipeline`) особенно чувствителен к rate limiting при массовом fan-out. Рекомендуется использовать circuit breaker для предотвращения каскадных отказов:

```python
import time
import random
import requests

class PipelineTriggerCircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def trigger(self, project_id, token, variables, max_retries=3):
        if self.state == "OPEN":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker OPEN — too many 429 errors")
        
        url = f"https://gitlab.example.com/api/v4/projects/{project_id}/trigger/pipeline"
        
        for attempt in range(max_retries):
            resp = requests.post(url, data={
                "token": token,
                "ref": "main",
                **variables
            })
            
            if resp.status_code == 429:
                self.on_failure()
                base_wait = 2 ** attempt
                jitter = random.uniform(0, base_wait * 0.5)
                wait = base_wait + jitter
                print(f"429 on trigger. Waiting {wait:.1f}s")
                time.sleep(wait)
                continue
            
            if resp.status_code == 201:
                self.on_success()
                return resp.json()
            
            # Другие ошибки (403, 404, 500) — не повторяем через circuit breaker
            resp.raise_for_status()
        
        raise Exception(f"Pipeline trigger failed after {max_retries} retries")
    
    def on_success(self):
        self.failures = 0
        self.state = "CLOSED"
    
    def on_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.failure_threshold:
            self.state = "OPEN"
```

**Использование в fan-out сценарии:**
```python
breakers = {pid: PipelineTriggerCircuitBreaker() for pid in downstream_projects}

for project_id in downstream_projects:
    try:
        result = breakers[project_id].trigger(project_id, token, {"DEPLOY_ENV": "staging"})
        print(f"Triggered {project_id}: pipeline {result['id']}")
    except Exception as e:
        print(f"Failed to trigger {project_id}: {e}")
        # Логируем ошибку, продолжаем для других проектов
```

### Batch API и оптимизация массовых операций

Для массовых операций (валидация конфигурации, опрос пайплайнов) используйте:

```python
import asyncio
import aiohttp

async def batch_trigger(session, project_id, token, variables, semaphore):
    async with semaphore:  # Ограничиваем параллельные запросы
        url = f"https://gitlab.example.com/api/v4/projects/{project_id}/trigger/pipeline"
        async with session.post(url, data={"token": token, "ref": "main", **variables}) as resp:
            if resp.status == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                await asyncio.sleep(retry_after)
                return await batch_trigger(session, project_id, token, variables, semaphore)
            if resp.status == 201:
                data = await resp.json()
                return {"project": project_id, "pipeline_id": data["id"]}
            raise Exception(f"HTTP {resp.status}")

async def fan_out_async(projects, token, max_concurrent=5):
    semaphore = asyncio.Semaphore(max_concurrent)
    async with aiohttp.ClientSession() as session:
        tasks = [batch_trigger(session, pid, token, {}, semaphore) for pid in projects]
        return await asyncio.gather(*tasks, return_exceptions=True)
```

**Оптимизация массовых операций:**
- Ограничивайте параллельные запросы через `Semaphore` (рекомендуется `max_concurrent=5` для Pipeline Triggers API).
- Кэшируйте результаты запросов, которые не меняются часто (списки проектов, группы).
- Выполняйте операции в **off-peak hours** (ночные часы) для критичных массовых обновлений.

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

## Best Practices

### Аутентификация и безопасность

-   **Минимизация прав**: Используйте Project Access Tokens с минимально необходимыми scope (`api` для управления, `read_api` для мониторинга) вместо Personal Access Tokens. PAT даёт доступ ко всем проектам пользователя — это нарушает принцип наименьших привилегий (POLP).
-   **`CI_JOB_TOKEN` для CI/CD-задач**: Внутри пайплайна всегда предпочитайте `CI_JOB_TOKEN` внешним токенам. Токен автоматически истекает при завершении задачи, что исключает компрометацию при утечке логов.
-   **OIDC вместо статических секретов**: Для интеграции с Vault и внешними сервисами используйте `id_tokens` вместо хранения долгоживущих паролей в переменных. См. раздел [Механизм id_tokens (OIDC)](#механизм-id_tokens-oidc).
-   **Валидация Payload**: Не доверяйте данным из вебхука без проверки HMAC-SHA256 подписи (`X-Gitlab-Token` заголовок). См. раздел [Безопасная обработка вебхуков](#безопасная-обработка-вебхуков).
-   **Маскирование**: Всегда устанавливайте флаг `masked: true` для переменных, создаваемых через API, чтобы они не попали в логи.

### Производительность и надёжность

-   **Асинхронность**: Всегда отвечайте `200 OK` на вебхук мгновенно, перенося тяжелую логику обработки в фоновые задачи (Celery, Redis, Sidekiq). GitLab ждёт ответа не более 10 секунд.
-   **Идемпотентность**: Реализуйте повторную обработку webhook-событий без побочных эффектов. Используйте `object_attributes.id` как уникальный ключ для дедупликации.
-   **Кэширование**: Для часто запрашиваемых данных (списки проектов, группы, переменные) кэшируйте результаты API-вызовов. Время жизни кэша — не более 5 минут для данных, которые могут измениться.
-   **Пагинация**: Всегда обрабатывайте пагинацию при получении списков. Не предполагайте, что все данные помещаются в один ответ.

### Диагностика и мониторинг (SRE)

-   **Логирование API-вызовов**: Записывайте URL, статус-код и время ответа каждого вызова для последующего анализа.
-   **Алерты на Rate Limit**: Настройте уведомления при получении HTTP 429 — это сигнал о необходимости оптимизации частоты запросов.
-   **Healthcheck webhook-приёмника**: Регулярно проверяйте доступность эндпоинта через GitLab API (`POST /projects/:id/hooks/:hook_id/test`).
-   **Мониторинг доставки вебхуков**: Настройте алерт на `last_delivery_at` старше 5 минут для критичных вебхуков.
-   **Аудит токенов**: Периодически перечисляйте активные токены через API и удаляйте неиспользуемые.

### Управление инстансом (Sysadmin)

-   **IP-фильтрация**: Ограничьте исходящие IP GitLab для вебхуков файрволом. Публичный список IP-адресов доступен в `Admin > Settings > Network > Outbound requests`.
-   **Rate limiting на входе**: Настройте反向代理 (nginx, Apache) для ограничения частоты запросов к webhook-приёмнику.
-   **Ротация секретов**: Периодически меняйте `GITLAB_WEBHOOK_SECRET` и обновляйте его у всех потребителей.
-   **Мониторинг очереди доставки**: GitLab помещает неудачные вебхуки в очередь. Мониторьте размер очереди через Admin API.

### Обратная совместимость

-   **Версионирование**: Явно указывайте версию API (`/api/v4/`) во всех вызовах. Не используйте relative paths без указания версии.
-   **Депрекация**: При использовании deprecated-эндпоинтов (например, registration tokens в GitLab 16.0+) планируйте миграцию заранее. GitLab предоставляет минимум 1 год deprecated-периода.

## Граничные условия и ограничения (Edge Cases)

### Версионная совместимость

-   **`id_tokens` в `default:`**: Глобальный блок `id_tokens` в `default:` доступен только с GitLab 16.4+. В более старых версиях определяйте токен в каждой задаче отдельно.
-   **Trigger Tokens**: В GitLab 19.x Trigger Tokens поддерживают только запуск пайплайнов. Для управления пайплайнами (отмена, перезапуск) используйте Project Access Token.
-   **GraphQL depth limit**: GitLab ограничивает глубину запросов GraphQL. При получении ошибки `depth limit exceeded` упростите запрос или используйте REST API.
-   **CI_JOB_TOKEN и cross-project**: По умолчанию `CI_JOB_TOKEN` работает только внутри проекта. Для кросс-проектных вызовов добавьте целевой проект в Inbound Allowlist (`Settings > CI/CD > Token Access`).

### Ограничения механизмов

-   **Webhook retry**: GitLab повторяет неуспешные вебхуки до 3 раз с интервалом ~1 минута. После 3 неудачных попыток доставка прекращается. Для критичных событий реализуйте API polling как fallback.
-   **Payload size**: Максимальный размер webhook payload — 10 МБ. При превышении GitLab обрезает payload и добавляет заголовок `X-Gitlab-Event-Undelivered`.
-   **Rate Limit**: По умолчанию ~60 запросов/минуту для REST API и ~60 для GraphQL. Для инстансов с высокой нагрузкой лимиты могут быть увеличены администратором.
-   **Batch API**: Доступен не во всех версиях GitLab. Проверьте наличие в документации вашей версии перед использованием.

### Специфические сценарии

-   **Self-hosted Runner без исходящего интернета**: Если Runner находится в изолированной сети, убедитесь, что он может доставить запросы к GitLab API и OIDC-эндпоинту.
-   **Высокая частота вебхуков**: При массовых событиях (например, bulk push) GitLab может дедуплицировать вебхуки. Не полагайтесь на получение одного вебхука на каждое событие.
-   **Webhook и Fork-репозитории**: Для Fork MR вебхуки отправляются только при включённом настройке `pipeline events` в `Settings > Webhooks > Trigger on fork events`.
-   **Запуск пайплайна из пайплайна**: При использовании `CI_JOB_TOKEN` для Trigger API убедитесь, что целевой проект добавлен в Inbound Allowlist. Иначе вернётся 403 Forbidden.

### Ограничения инфраструктуры

-   **Сетевая задержка**: Webhook-приёмник должен отвечать за 10 секунд. При высокой задержки между GitLab и приёмником увеличьте таймаут на стороне приёмника или используйте асинхронную обработку.
-   **TLS-сертификаты**: GitLab не отправляет вебхуки на HTTP (кроме `localhost` в development-режиме). Убедитесь, что сертификат приёмника валиден и не истёк.
-   **DNS**: GitLab кэширует DNS на 5 минут. При смене IP webhook-приёмника старый IP может использоваться до истечения кэша.
-   **Файрвол**: Если GitLab и приёмник находятся в разных сегментах сети, откройте порт 443/8443 в обоих направлениях.

## Дополнительная информация

-   **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — безопасность `CI_JOB_TOKEN`, `id_tokens` (OIDC), приоритеты переменных.
-   **[Downstream-пайплайны: лучшие практики](./Downstream_Pipelines/best_practices.md)** — мониторинг Bridge Jobs через API, обнаружение deadlock, управление цепочками.
