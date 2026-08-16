# Программная автоматизация: API и Webhooks в GitLab CI/CD

## Определения

**Программное управление CI/CD** — это методология управления жизненным циклом разработки через внешние интерфейсы (API) и механизмы обратных вызовов (Webhooks). Это позволяет интегрировать GitLab CI/CD с внешними системами оркестрации, мониторинга и безопасности, выходя за рамки стандартных событий системы контроля версий.

**Ключевые механизмы:**

-   **REST API (v4)**: Основной интерфейс для управления ресурсами GitLab. Позволяет выполнять CRUD-операции над проектами, пайплайнами, задачами (Jobs), переменными и артефактами.
-   **GraphQL API**: Альтернативный интерфейс, позволяющий запрашивать строго определенные данные в одном запросе. Идеален для построения дашбордов и мониторинга статусов сложных пайплайнов без избыточной передачи данных.
-   **Trigger API**: Специализированный легковесный эндпоинт REST API, предназначенный исключительно для инициирования новых пайплайнов внешними системами с использованием Trigger Tokens.
-   **Webhooks (Вебхуки)**: Механизм Push-уведомлений, при котором GitLab отправляет HTTP POST запрос с JSON-нагрузкой (payload) на внешний URL при возникновении определенных событий (изменение статуса пайплайна, создание тега, обновление Merge Request).

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

**Алгоритм проверки токена (Python):**

```python
import hmac
from flask import Flask, request, abort

app = Flask(__name__)
GITLAB_SECRET = "your_shared_secret"

@app.route('/webhook', methods=['POST'])
def handle_gitlab_event():
    # Проверка секретного токена
    token = request.headers.get('X-Gitlab-Token')
    if not token or token != GITLAB_SECRET:
        abort(403)
    
    data = request.json
    event_type = request.headers.get('X-Gitlab-Event')
    
    if event_type == 'Pipeline Hook' and data['object_attributes']['status'] == 'failed':
        process_failure(data)
        
    return 'OK', 200
```

## Продвинутые сценарии автоматизации

### 1. Внешние Quality Gates (Quality Gate as a Service)

Пайплайн останавливается на задаче с `when: manual` или ожидает подтверждения через API. Внешняя система (например, анализатор безопасности или AI-агент) проводит проверку и отправляет команду на продолжение:

```bash
# Разблокировка ручной задачи (Play job)
curl --request POST \
     --header "PRIVATE-TOKEN: <token>" \
     "https://gitlab.example.com/api/v4/projects/123/jobs/456/play"
```

### 2. Сценарий «Self-Healing Configuration»

Если система мониторинга (например, Prometheus) обнаруживает рост ошибок 5xx после деплоя, она через Webhook вызывает оркестратор, который:
1.  Меняет переменную `TRAFFIC_WEIGHT` на `0` через API.
2.  Перезапускает пайплайн для отката изменений.
3.  Создает инцидент в Jira с логами из GitLab API.

### 3. Автоматизация динамических окружений

Использование вебхуков события `Merge Request closed` для вызова внешнего скрипта очистки, который удаляет не только Review App, но и связанные облачные ресурсы (S3 бакеты, DNS записи, БД), которые не управляются напрямую через Runner.

## Устранение неполадок

### Типичные ошибки API и их причины

-   **401 Unauthorized**: Истек или неверно указан токен доступа. Убедитесь, что используете заголовок `PRIVATE-TOKEN` для персональных токенов и `JOB-TOKEN` для токенов пайплайна.
-   **403 Forbidden**: Недостаточно прав. Для управления переменными или запуска задач обычно требуется роль `Maintainer` или `Owner`.
-   **404 Not Found**: Неверный ID проекта (иногда требует URL-кодирования пути `group%2Fproject`) или ресурс удален.
-   **429 Too Many Requests**: Превышен Rate Limit. GitLab ограничивает количество запросов в секунду/минуту для защиты от DoS.

### Стратегии обработки Rate Limiting

При автоматизации массовых операций используйте **Exponential Backoff**:

```python
import time
import requests

def call_gitlab_api(url, headers):
    retries = 5
    for i in range(retries):
        response = requests.get(url, headers=headers)
        if response.status_code == 429:
            wait = (2 ** i) # Экспоненциальное ожидание
            time.sleep(wait)
            continue
        return response
    return None
```

## Практические рекомендации и Best Practices

-   **Асинхронность**: Всегда отвечайте `200 OK` на вебхук мгновенно, перенося тяжелую логику обработки в фоновые задачи (Celery, Redis).
-   **Минимизация прав**: Используйте Project Access Tokens с минимально необходимыми scope (`api` для управления, `read_api` для мониторинга) вместо Personal Access Tokens.
-   **Маскирование**: Всегда устанавливайте флаг `masked: true` для переменных, создаваемых через API, чтобы они не попали в логи.
-   **Валидация Payload**: Не доверяйте данным из вебхука без проверки `Secret Token`.

## Дополнительная информация

-   **[Продвинутые рабочие процессы](./gitlab_ci_advanced_workflow.md)** — архитектура пайплайнов.
-   **[Динамическая генерация пайплайнов](./Downstream_Pipelines/dynamic_generation.md)** — генерация YAML через скрипты.
-   **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — безопасность и приоритеты.
