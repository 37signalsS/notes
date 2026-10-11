# Rate Limits и производительность GitLab API для CI/CD

**Актуально для:** GitLab 18.6+ / 19.x, GitLab.com и self-managed

## Требования и предварительные условия

| Параметр | Значение |
| :--- | :--- |
| **Версия GitLab** | 18.6+ / 19.x |
| **Роль** | DevOps, SRE, Sysadmin |
| **Необходимые знания** | GitLab REST API, GraphQL, CI/CD переменные (`CI_JOB_TOKEN`, `PRIVATE-TOKEN`), downstream-пайплайны, Sidekiq |
| **SSoT по теме** | [API и Webhooks](../api_and_webhooks_automation.md), [Downstream-пайплайны: best practices](../Downstream_Pipelines/best_practices.md) |

**Для кого:** DevOps-инженеры, проектирующие fan-out и batch-операции; SRE, настраивающие мониторинг и алерты; Sysadmin, управляющие self-managed инстансами и очередями Sidekiq.

## Определения

**Rate Limit** — ограничение на количество запросов к GitLab API в единицу времени, применяемое для защиты инстанса от перегрузки и DoS-атак.

**Burst** — кратковременный пик запросов, превышающий среднюю частоту. GitLab разрешает burst до определенного лимита, после чего включается throttling.

**Throttling** — замедление или блокировка запросов при превышении rate limit. GitLab возвращает HTTP 429 Too Many Requests.

**Retry-After** — заголовок в ответе 429, указывающий время ожидания перед повторным запросом.

**Pipeline Triggers API** — специализированный эндпоинт (`POST /projects/:id/trigger/pipeline`) для запуска downstream-пайплайнов. Имеет собственные лимиты в дополнение к общим лимитам REST API.

**Sidekiq очередь `create_downstream_pipeline`** — внутренняя очередь GitLab для обработки задач создания downstream-пайплайнов. При высокой нагрузке эта очередь может стать bottleneck.

**`PRIVATE-TOKEN`** — заголовок аутентификации для personal/project access token. Имеет высокий лимит запросов и полный доступ к разрешенным эндпоинтам.

**`CI_JOB_TOKEN`** — временный токен, генерируемый GitLab для каждого CI/CD job. Имеет ограниченный набор эндпоинтов и более низкие лимиты по сравнению с `PRIVATE-TOKEN`. Автоматически отзывается после завершения job.

## Основные концепции

### Лимиты GitLab REST API

GitLab применяет rate limiting на нескольких уровнях:

| Эндпоинт | Лимит (GitLab.com) | Лимит (Self-managed) | Примечание |
| :--- | :--- | :--- | :--- |
| **REST API (общий)** | ~60 req/min на пользователя | Настраивается администратором | Зависит от роли и лицензии |
| **GraphQL API** | ~60 req/min на пользователя | Настраивается администратором | Зависит от сложности запроса |
| **CI Lint API** | ~30 req/min на пользователя | Настраивается администратором | Включительно `/ci/lint` и `/projects/:id/ci/lint` |
| **Pipeline Triggers API** | ~100 req/min на проект | Настраивается администратором | Отдельный лимит для `/trigger/pipeline` |
| **CI Components API** | ~30 req/min | Настраивается администратором | Для `/ci/components` |
| **Webhooks (исходящие)** | До 3 повторных попыток | Настраивается администратором | Retry с интервалом ~1 минута |

**Важно:** Лимиты для self-managed инстансов зависят от конфигурации `gitlab.rb` и могут быть увеличены администратором. Для GitLab.com лимиты фиксированы и зависят от тарифа (Free/Premium/Ultimate).

### Лимиты Sidekiq очередей

При массовом запуске downstream-пайплайнов лимитирующим фактором часто становится не REST API, а внутренняя обработка Sidekiq:

| Очередь | Описание | Боттлнек при |
| :--- | :--- | :--- |
| `create_downstream_pipeline` | Создание downstream-пайплайнов | Fan-out с >10 параллельными триггерами |
| `pipeline_hooks` | Обработка вебхуков пайплайнов | Массовые события в upstream-проектах |
| `ci_sync` | Синхронизация статусов Bridge Jobs | Высокая частота обновлений статусов |

**Рекомендация:** Мониторьте размер очередей Sidekiq через Admin API и настраивайте алерты при превышении порога.

### Взаимодействие rate limiting и downstream-пайплайнов

При проектировании систем с массовыми триггерами учитывайте следующие ограничения:

1. **Fan-out burst:** Если upstream-пайплайн запускает 20 downstream-проектов одновременно, каждый вызов `trigger:project` идет через Pipeline Triggers API. При лимите ~100 req/min burst из 20 запросов безопасен, но при >100 параллельных триггерах возможен 429.
2. **API polling:** Мониторинг Bridge Jobs через API (`GET /bridges`) добавляет дополнительную нагрузку. При пайплайне с 50 Bridge Jobs и polling каждые 10 секунд — 300 req/min, что превышает лимит.
3. **Webhook delivery:** При mass push в upstream-проект GitLab отправляет вебхуки на все подписанные downstream-проекты. Это создает burst входящих запросов на downstream-инстанс.

### Стратегии обработки 429 Too Many Requests

#### Exponential Backoff с jitter

Стандартный паттерн для обработки rate limiting:

```python
import time
import random
import requests

def call_pipeline_triggers_api(project_id, token, variables, max_retries=5):
    """Запуск downstream-пайплайна с обработкой 429."""
    url = f"https://gitlab.example.com/api/v4/projects/{project_id}/trigger/pipeline"
    
    for attempt in range(max_retries):
        response = requests.post(url, data={
            "token": token,
            "ref": "main",
            **variables
        })
        
        if response.status_code == 429:
            # Exponential backoff + jitter для избежания thundering herd
            base_wait = 2 ** attempt
            jitter = random.uniform(0, base_wait * 0.5)
            wait = base_wait + jitter
            print(f"Rate limited. Waiting {wait:.1f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        
        if response.status_code == 201:
            return response.json()
        
        # Другие ошибки — не повторяем
        response.raise_for_status()
    
    raise Exception(f"Pipeline trigger failed after {max_retries} retries due to rate limiting")
```

#### Circuit Breaker для каскадных failures

При массовом отказе downstream-пайплайнов из-за rate limiting используйте circuit breaker. Готовую реализацию для Pipeline Triggers API см. в **[API и Webhooks](./api_and_webhooks_automation.md#retry-и-circuit-breaker-для-pipeline-triggers-api)**.

**Использование в fan-out сценарии:**
```python
breakers = {pid: PipelineTriggerCircuitBreaker() for pid in downstream_projects}

for project_id in downstream_projects:
    try:
        result = breakers[project_id].trigger(project_id, token, {"DEPLOY_ENV": "staging"})
        print(f"Triggered {project_id}: pipeline {result['id']}")
    except Exception as e:
        print(f"Failed to trigger {project_id}: {e}")
```

#### 1. Ограничение burst через queue

```yaml
# Родительский пайплайн с контролируемым fan-out
trigger-service-a:
  stage: deploy
  trigger:
    project: 'services/service-a'
    strategy: mirror
  resource_group: deploy-lock  # Сериализуем запуск

trigger-service-b:
  stage: deploy
  trigger:
    project: 'services/service-b'
    strategy: mirror
  resource_group: deploy-lock
```

Использование `resource_group` ограничивает параллельные запуски, предотвращая burst.

#### 2. Пагинация и батчинг при массовом опросе

```bash
# Получение всех Bridge Jobs с пагинацией
page=1
while true; do
  response=$(curl -s --header "PRIVATE-TOKEN: $TOKEN" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges?per_page=100&page=$page")
  count=$(echo "$response" | jq length)
  [ "$count" -eq 0 ] && break
  echo "$response" | jq -r '.[] | select(.status == "running") | .id'
  page=$((page + 1))
done
```

#### 3. Кэширование токенов и session

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))
```

#### 4. Асинхронный fan-out через API

Для глубоких иерархий (>2 уровней) используйте API-оркестратор:

```python
import asyncio
import aiohttp

async def trigger_pipeline(session, project_id, token, variables):
    async with session.post(
        f"https://gitlab.example.com/api/v4/projects/{project_id}/trigger/pipeline",
        data={"token": token, "ref": "main", **variables}
    ) as resp:
        if resp.status == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            await asyncio.sleep(retry_after)
            return await trigger_pipeline(session, project_id, token, variables)
        return await resp.json()

async def fan_out(projects, token):
    async with aiohttp.ClientSession() as session:
        tasks = [trigger_pipeline(session, pid, token, {}) for pid in projects]
        return await asyncio.gather(*tasks, return_exceptions=True)
```

## Практические сценарии

### Сценарий 1: Мониторинг rate limiting в production

Настройка алертов на превышение rate limit:

```bash
# Проверка статуса лимитов через response headers
curl -s -I "https://gitlab.example.com/api/v4/projects/123/pipelines" \
  -H "PRIVATE-TOKEN: $TOKEN" | grep -i "x-ratelimit"

# Ожидаемые заголовки:
# X-RateLimit-Limit: 60
# X-RateLimit-Remaining: 58
# X-RateLimit-Reset: 1709174400
```

**Алерт Prometheus:**
```yaml
groups:
  - name: gitlab_api
    rules:
      - alert: GitLabAPIRateLimitHigh
        expr: gitlab_http_requests_total{status="429"} > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GitLab API rate limit exceeded"
```

### Сценарий 2: Тюнинг Sidekiq очередей для high-volume триггеров

```bash
# Проверка размера очереди create_downstream_pipeline
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/admin/sidekiq/queues" | \
  jq '.[] | select(.name == "create_downstream_pipeline") | {name, size, latency}'

# Увеличение количества воркеров Sidekiq (self-managed)
# В gitlab.rb:
# sidekiq['concurrency'] = 25
# sidekiq['queues'] = ['create_downstream_pipeline', 'pipeline_hooks', ...]
```

### Сценарий 3: Batch-валидация пайплайнов без превышения лимитов

```bash
#!/bin/bash
# batch_validate.sh — валидация пайплайнов с задержкой между запросами

BRANCHES=("main" "develop" "staging" "release/v2.0")
DELAY=2  # секунды между запросами

for BRANCH in "${BRANCHES[@]}"; do
  echo "--- Ветка: $BRANCH ---"
  
  # Базовая валидация
  RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    --request POST \
    --header "PRIVATE-TOKEN: $TOKEN" \
    --header "Content-Type: application/json" \
    --data "{\"content\": \"$(cat .gitlab-ci.yml | sed 's/\"/\\\"/g')\"}" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/ci/lint")
  
  if [ "$RESPONSE" == "429" ]; then
    echo "Rate limited. Waiting 60s..."
    sleep 60
    continue
  fi
  
  sleep $DELAY
done
```

### Сценарий 4: Retry с экспоненциальной задержкой для Pipeline Triggers API

```python
import time
import random
import requests

def trigger_with_backoff(project_id, token, variables, max_retries=5):
    url = f"https://gitlab.example.com/api/v4/projects/{project_id}/trigger/pipeline"
    
    for attempt in range(max_retries):
        resp = requests.post(url, data={
            "token": token,
            "ref": "main",
            **variables
        })
        
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            jitter = random.uniform(0, retry_after * 0.3)
            wait = retry_after + jitter
            print(f"429 Too Many Requests. Waiting {wait:.1f}s")
            time.sleep(wait)
            continue
        
        if resp.status_code == 201:
            return resp.json()
        
        resp.raise_for_status()
    
    raise Exception(f"Failed after {max_retries} retries")
```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `429 Too Many Requests` | Превышен rate limit API | Используйте exponential backoff, уменьшите частоту запросов, добавьте задержки между batch-операциями. |
| `503 Service Unavailable` | Sidekiq очередь переполнена | Увеличьте количество воркеров Sidekiq, добавьте очередь или используйте fire-and-forget для некритичных триггеров. |
| Downstream-пайплайн не создается | Очередь `create_downstream_pipeline` задержана | Мониторьте latency очереди через Admin API, увеличьте `concurrency` Sidekiq. |
| `Retry-After` заголовок отсутствует | GitLab возвращает 429 без заголовка | Используйте стандартную задержку 60 секунд при отсутствии `Retry-After`. |
| Mass cancellation downstream | Rate limit на отмену пайплайнов | Сериализуйте отмены через `resource_group` или добавьте задержки. |

## Валидация и диагностика

### Проверка rate limit headers

```bash
# Проверка текущих лимитов через response headers
curl -s -I "https://gitlab.example.com/api/v4/projects/123/pipelines" \
  -H "PRIVATE-TOKEN: $TOKEN" | grep -i "x-ratelimit"

# Ожидаемые заголовки:
# X-RateLimit-Limit: 60
# X-RateLimit-Remaining: 58
# X-RateLimit-Reset: 1709174400
```

### Проверка лимитов через Admin API (self-managed)

```bash
# Получение текущих настроек rate limits (self-managed)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/application/rate_limits"
```

### Проверка очередей Sidekiq

```bash
# Размер и latency очередей
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/admin/sidekiq/queues" | \
  jq '.[] | select(.name == "create_downstream_pipeline") | {name, size, latency}'
```

### Валидация пайплайна через CI Lint API

```bash
# Проверка конфигурации без создания пайплайна
curl --request POST \
  --header "PRIVATE-TOKEN: $TOKEN" \
  --header "Content-Type: application/json" \
  --data "{\"content\": \"$(cat .gitlab-ci.yml | sed 's/\"/\\\"/g')\"}" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/ci/lint"
```

### Проверка статуса пайплайнов и Bridge Jobs

```bash
# Получение всех Bridge Jobs с пагинацией
page=1
while true; do
  response=$(curl -s --header "PRIVATE-TOKEN: $TOKEN" \
    "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/bridges?per_page=100&page=$page")
  count=$(echo "$response" | jq length)
  [ "$count" -eq 0 ] && break
  echo "$response" | jq -r '.[] | select(.status == "running") | .id'
  page=$((page + 1))
done
```

## Граничные случаи и ограничения

### Различия GitLab.com и self-managed

- **GitLab.com:** Лимиты фиксированы и зависят от тарифного плана (Free/Premium/Ultimate). Начиная с 2026 года GitLab внедряет plan-aware rate limiting: Premium и Ultimate получают более высокие лимиты, чем Free.
- **Self-managed:** Лимиты настраиваются администратором через `gitlab.rb` и зависят от ресурсов инстанса (CPU, RAM, количество пользователей).

### CI_JOB_TOKEN vs PRIVATE-TOKEN

- `CI_JOB_TOKEN` имеет строго ограниченный набор разрешенных эндпоинтов и обычно более низкие лимиты, чем `PRIVATE-TOKEN`.
- `CI_JOB_TOKEN` не работает с GraphQL (начиная с GitLab 17.x).
- `CI_JOB_TOKEN` автоматически отзывается после завершения job.

### GraphQL complexity

- GraphQL-запросы ограничены по сложности (`complexity` points). Сложные запросы с большим количеством связанных данных (пайплайны + задачи + статусы) могут быть отклонены даже при наличии remaining quota.

### Webhooks

- Исходящие вебхуки имеют лимит до 3 повторных попыток с интервалом ~1 минута. Входящие вебхуки (доставка событий на downstream-инстанс) не считаются против rate limit отправителя, но создают burst входящих запросов.

### Mass cancellation

- Массовая отмена пайплайнов через API (`DELETE /projects/:id/pipelines`) учитывается против rate limit отдельно от обычных запросов.

### First request after reset

- При первом запросе после сброса лимита (`X-RateLimit-Reset`) возможна короткая задержка (seconds) из-за Propagation delay на распределенных инстансах GitLab.com.

## Best Practices

### Проектирование CI/CD (DevOps)

1. **Ограничьте fan-out burst:** Используйте `resource_group` или последовательные стадии для массовых триггеров. Не запускайте >20 downstream-пайплайнов одновременно без контроля.
2. **Используйте fire-and-forget для некритичных задач:** Для фоновых задач не используйте `strategy: mirror` — это уменьшает нагрузку на Runner'ы и API.
3. **Выбирайте правильный токен:** Для автоматизации внутри пайплайнов используйте `CI_JOB_TOKEN` для разрешенных эндпоинтов; для административных и скриптовых вызовов — `PRIVATE-TOKEN` с минимально необходимыми правами. `CI_JOB_TOKEN` не работает с GraphQL и имеет более низкие лимиты.
4. **Кэшируйте токены:** Повторно используйте `PRIVATE-TOKEN` и `CI_JOB_TOKEN` в рамках одного пайплайна вместо получения новых токенов для каждого запроса.
5. **Батчите API-вызовы:** При массовой валидации или опросе пайплайнов используйте пагинацию и batch-запросы.
6. **Учитывайте plan-aware лимиты на GitLab.com:** Для Premium/Ultimate инстансов лимиты выше, чем для Free. При превышении лимитов рассмотрите апгрейд тарифа или оптимизацию запросов.

### Производительность (Sysadmin/SRE)

1. **Мониторьте rate limit headers:** В скриптах автоматизации проверяйте `X-RateLimit-Remaining` и адаптируйте частоту запросов.
2. **Настраивайте алерты на 429:** Превышение rate limit — сигнал о необходимости оптимизации архитектуры или увеличения лимитов.
3. **Мониторьте Sidekiq очереди:** Размер очереди `create_downstream_pipeline` > 100 — сигнал о перегрузке. Увеличьте воркеры или оптимизируйте fan-out.
4. **Используйте GraphQL для сложных запросов:** GraphQL снижает количество запросов при получении связанных данных (пайплайн + задачи + статусы).
5. **Настройте retry budget:** Ограничьте количество повторных попыток (max 3-5) и используйте jitter для избежания thundering herd.

### Управление инстансом (Sysadmin)

1. **Настройте лимиты под нагрузку:** Для self-managed инстансов увеличьте лимиты REST API и Pipeline Triggers API при высокой нагрузке. Конфигурация в `gitlab.rb`.
2. **Мониторьте очереди Sidekiq:** Настройте алерты на размер очередей и latency. Для high-volume сценариев выделите отдельные воркеры для `create_downstream_pipeline`.
3. **Используйте reverse proxy rate limiting:** Настройте nginx для ограничения частоты запросов к чувствительным эндпоинтам (Trigger API, CI Lint).
4. **Резервные Runner'ы:** Для downstream-пайплайнов настройте Runner'ы с высокой доступностью, так как rate limiting на API не влияет на Runner'ы напрямую, но может задержать создание пайплайнов.

## Дополнительная информация

### См. также

- **[API и Webhooks](./api_and_webhooks_automation.md)** — REST API, GraphQL, вебхуки, exponential backoff.
- **[Downstream-пайплайны: best practices](./Downstream_Pipelines/best_practices.md)** — мониторинг Bridge Jobs, предотвращение deadlock.
- **[Self-managed инсталляции Downstream](./Downstream_Pipelines/multi_project_pipelines.md#self-managed-инсталляции)** — мониторинг Sidekiq, PostgreSQL.
- **[Отладка и устранение неполадок](./debugging_and_troubleshooting.md)** — диагностика проблем CI/CD.
