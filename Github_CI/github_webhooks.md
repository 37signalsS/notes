# GitHub Webhooks: События, доставка и обработка

**Актуально для:** GitHub Webhooks, октябрь 2026 (repository/org webhooks, webhook forwarding, event types, retry policy, HMAC); для GitHub Enterprise Server — 3.14+

GitHub Webhooks — это механизм доставки событийных уведомлений на внешние URL. Когда в репозитории или организации происходит событие (push, PR, issue, release и др.), GitHub отправляет HTTP `POST`-запрос с JSON-пейлоадом на настроенный URL. Webhooks — основной способ интеграции GitHub с внешними системами (CI/CD, ticketing, мониторинг).

## Определения

- **Webhook**: HTTP-эндпоинт, зарегистрированный в GitHub (Settings → Webhooks), на который доставляются события.
- **Событие (Event)**: Тип действия, который триггерит доставку webhook (push, pull_request, issues, release, workflow_run, check_run и др. — более 40 типов).
- **Delivery ID**: Уникальный UUID каждой доставки (`X-GitHub-Delivery` заголовок). Используется для idempotency.
- **HMAC Signature**: HMAC-SHA256 подпись тела (`X-Hub-Signature-256`), вычисляемая с `Webhook secret`. Единственный надёжный способ верификации подлинности доставки.
- **Retry Policy**: Экспоненциальный back-off, с которым GitHub повторяет доставку при недоступности endpoint.
- **Webhook Forwarding**: GitHub App webhook forwarding — перехват webhook-событий в локальную среду для разработки (smee.io аналог).
- **Organization Webhook**: Webhook на уровне организации — доставляет события со всех репозиториев org.
- **Repository Webhook**: Webhook на уровне репозитория — доставляет только выбранные типы событий из этого репозитория.

## Архитектура и модель доставки

### Механизм доставки

```text
GitHub Event (push, PR, issue, etc.)
    │
    1. Событие попадает в очередь webhook-доставок
    │
    2. POST → https://webhook.example.com/github
    │   Headers:
    │   - X-GitHub-Event: push
    │   - X-GitHub-Delivery: UUID
    │   - X-Hub-Signature-256: sha256=<HMAC>
    │   - Content-Type: application/json
    │   Body: JSON пейлоад события
    │
    3. Если endpoint returns != 2xx → exponential backoff retry
    │
    4. Через ~72 hours / ~10-15 попыток → delivery прекращается
    │   (нет Dead Letter Queue)
```

### Retry Policy (exponential backoff)

| Попытка | Задержка (примерно) |
|---|---|
| 1 | 1 минута |
| 2 | 2 минуты |
| 3 | 4 минуты |
| 4 | 8 минут |
| 5 | 16 минут |
| ... | экспоненциально, до ~72 часов |
| 10-15 | финальные попытки, затем delivery прекращается |

- **Важно**: после исчерпивания всех попыток событие **теряется** (нет DLQ, нет dead-letter очереди). Для надёжности используйте внешнюю очередь (Kafka, SQS, Azure Queue) или webhook forwarding для разработки.
- **Idempotency**: повторные доставки возможны даже при успешном `200 OK` (GitHub может доставить событие дважды при сбое на стороне GitHub после вашего ответа). Используйте `X-GitHub-Delivery` в качестве idempotency key.

### IP-адреса доставки

GitHub доставляет webhook-ы с диапазонов IP, публикованных в [meta API](https://api.github.com/meta):

```bash
# Получить текущие IP-адреса GitHub
gh api /meta --jq '.hooks | @csv'
# → "192.30.252.0/22","185.199.108.0/22","140.82.121.0/25",...
```

> **Рекомендация**: вместо IP-фильтрации используйте HMAC-подпись (`X-Hub-Signature-256`) — IP-диапазоны GitHub регулярно меняются.

## Практические сценарии

### Сценарий 1: Настройка webhook для репозитория

Через UI: Settings → Webhooks → Add webhook →:
- **Payload URL**: `https://webhook.example.com/github`
- **Content type**: `application/json`
- **Secret**: случайная строка (HMAC key)
- **SSL**: Verify SSL (рекомендуется)
- **Events**: выбрать нужные типы (push, pull_request, issues, release, etc.)

Через API:

```bash
# Создать webhook для репозитория
gh api -X POST /repos/{owner}/{repo}/hooks \
  -f name="web" \
  -f active=true \
  -f url="https://webhook.example.com/github" \
  -f content_type="json" \
  -f secret="super-secret-webhook-secret" \
  -f "events[]=[push,pull_request,issues,release,workflow_run]" \
  -f push_events=true

# Проверить конфигурацию
gh api /repos/{owner}/{repo}/hooks --jq '.[] | {id: .id, url: .config.url, events: .events}'

# Включить/выключить webhook
gh api -X PATCH /repos/{owner}/{repo}/hooks/{hook_id} -f active=true
```

- **Валидация**: отправьте `ping` webhook через UI (Settings → Webhooks → ... → Send a ping) или `gh api -X POST /repos/{owner}/{repo}/hooks/{id}/pings`.

### Сценарий 2: Обработка webhook с HMAC-верификацией (Python)

```python
import hmac
import hashlib
import json
import os
from fastapi import FastAPI, Request, Header, HTTPException

app = FastAPI()
WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"].encode()

@app.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None),
    x_github_delivery: str = Header(None),
    x_hub_signature_256: str = Header(None)
):
    body = await request.body()

    # 1. Verify HMAC signature
    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET, body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256 or ""):
        raise HTTPException(401, "Invalid signature")

    # 2. Parse event
    event = json.loads(body)
    event_type = x_github_event
    delivery_id = x_github_delivery  # idempotency key

    # 3. Idempotency: skip duplicate deliveries
    # (save delivery_id in Redis/DB с TTL ≥ 7 дней)
    # ...

    # 4. Route по типу события
    if event_type == "push":
        handle_push(event)
    elif event_type == "pull_request":
        handle_pull_request(event)
    elif event_type == "ping":
        return {"status": "pong", "delivery": delivery_id}

    return {"status": "ok", "delivery": delivery_id}
```

### Сценарий 3: Обработка webhook на Go (production-grade)

```go
package main

import (
    "crypto/hmac"
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "net/http"
    "os"
)

func verifySignature(payload []byte, signature, secret string) bool {
    mac := hmac.New(sha256.New, []byte(secret))
    mac.Write(payload)
    expected := "sha256=" + hex.EncodeToString(mac.Sum(nil))
    return hmac.Equal([]byte(signature), []byte(expected))
}

func webhookHandler(w http.ResponseWriter, r *http.Request) {
    payload, _ := r.Body.(*io.ReadCloser)
    defer payload.Close()
    body, _ := io.ReadAll(payload)

    signature := r.Header.Get("X-Hub-Signature-256")
    if !verifySignature(body, signature, os.Getenv("WEBHOOK_SECRET")) {
        http.Error(w, "Unauthorized", http.StatusUnauthorized)
        return
    }

    var event map[string]interface{}
    json.Unmarshal(body, &event)
    eventType := r.Header.Get("X-GitHub-Event")

    // Route and process...
    w.WriteHeader(http.StatusOK)
    w.Write([]byte("ok"))
}
```

### Сценарий 4: Webhook Forwarding для локальной разработки

`gh webhook forward` (или `smee.io`) перехватывает production webhook и пересылает в локальную среду:

```bash
# 1. Запустить webhook forwarding
gh webhook forward --repo {owner}/{repo} --url http://localhost:8080/github

# 2. Локальный сервер получает реальные события
# → POST /github  (X-GitHub-Event: push, X-Hub-Signature-256: ...)

# 3. Разработка и тестирование без публичного endpoint
```

### Сценарий 5: Удаление и диагностика webhook

```bash
# Удалить webhook
gh api -X DELETE /repos/{owner}/{repo}/hooks/{hook_id}

# Просмотр recent deliveries
gh api /repos/{owner}/{repo}/hooks/{hook_id}/deliveries --jq '.[] | {id: .id, status: .status, event: .event, created_at: .created_at}'

# Redeliver specific delivery
gh api -X POST /repos/{owner}/{repo}/hooks/{hook_id}/deliveries/{delivery_id}/attempts

# Проверить статус последней доставки
gh api /repos/{owner}/{repo}/hooks/{hook_id}/deliveries --jq '.[0] | .status'
```

## Команды и API-операции

### Управление webhook-ами через API

| Операция | Endpoint |
|---|---|
| Создать webhook | `POST /repos/{owner}/{repo}/hooks` |
| Список webhooks | `GET /repos/{owner}/{repo}/hooks` |
| Получить webhook | `GET /repos/{owner}/{repo}/hooks/{hook_id}` |
| Обновить webhook | `PATCH /repos/{owner}/{repo}/hooks/{hook_id}` |
| Удалить webhook | `DELETE /repos/{owner}/{repo}/hooks/{hook_id}` |
| Send ping | `POST /repos/{owner}/{repo}/hooks/{hook_id}/pings` |
| Список deliveries | `GET /repos/{owner}/{repo}/hooks/{hook_id}/deliveries` |
| Redeliver | `POST /repos/{owner}/{repo}/hooks/{hook_id}/deliveries/{delivery_id}/attempts` |

### Основные события (Events)

| Событие | Описание |
|---|---|
| `push` | Пуш в ветку или тег |
| `pull_request` | Create/close/reopen/edit/assign/unassign PR; subtype в `action` |
| `pull_request_review` | Submit review (approve/comment/request changes) |
| `pull_request_review_comment` | Comment на конкретную строку |
| `issues` | Create/close/reopen/edit/assign issue |
| `issue_comment` | Comment на issue/PR |
| `release` | Published/unpublished released/prereleased |
| `workflow_run` | Завершение workflow run |
| `check_run` | Создание/обновление/удаление check_run (CI статус) |
| `check_suite` | Запуск/завершение check suite |
| `repository` | Настройки репозитория (transfer, rename) |
| `member` | Добавление/удаление участника |
| `fork` | Форк репозитория |
| `star` | Поставить/ убрать звезду |
| `ping` | Тестовое событие при настройке webhook |
| `delete` / `create` | Удаление/создание ветки или тега |
| `repository_vulnerability_alert` | Уязвимость в транзитивной зависимости |

Более 40 типов событий поддерживается. Полный список — в [Webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads).

## Устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| Webhook не доставляется (нет deliveries) | URL недоступен (firewall, DNS, TLS) | `curl -v <URL>`; проверить сертификат SSL; firewall egress |
| `401` в ответе сервера | HMAC signature mismatch | Синхронизировать `Webhook secret` в Settings и в env переменной обработчика |
| `X-Hub-Signature-256` mismatch на этапе | Секрет в Settings ≠ переменная в обработчике | Скопировать secret заново; проверить encoding (raw bytes, не base64) |
| Duplicate events | Retry policy GitHub после `200 OK` сбоя на их стороне | Использовать `X-GitHub-Delivery` как idempotency key; save в Redis с TTL |
| `404` в deliveries | Webhook удалён или выключен | `gh api /repos/.../hooks` — проверить `active: true` |
| Payload слишком большой (>25MB) | Push с большим diff | Использовать GitHub API (pagination) вместо webhook payload |
| Fork webhook не работает | Webhook не наследуется из fork в upstream | Настраивать webhook на каждом fork отдельно |
| `content_type` не выбран | Webhook требует `application/json` | Установить content type в Settings → Webhooks → Edit |

## Лучшие практики

1. **HMAC-верификация обязательна**: используйте `X-Hub-Signature-256` с `Webhook secret`. Никогда не полагайтесь на IP-фильтр — диапазлоны GitHub меняются.
2. **Idempotency по `X-GitHub-Delivery`**: сохраняйте delivery ID в Redis/DB с TTL ≥ 7 дней (больше retry window). Это устраняет duplicate processing.
3. **200 OK быстро**: ответ должен быть ≤ 10 секунд. Долгие обработки выносите в очередь (Kafka, SQS, GitHub Actions).
4. **Webhook forwarding для dev**: используйте `gh webhook forward` или `smee.io` вместо публичного endpoint в dev-среде.
5. **Organization webhooks для мониторинга**: создавайте org-level webhook с минимальными событиями для централизованного audit/migration.
6. **Payload filtering**: в workflow используйте `types:` для сужения webhook events (например, `issues: [opened, closed]`).
7. **Monitoring и alerting**: используйте `GET /hooks/{id}/deliveries` для проверки, что delivery статус `OK`; настройте alert на `status: "Failed"` > 5 раз в час.
8. **Redelivery**: GitHub сохраняет deliveries 72 часа; используйте `POST .../attempts` для ручного redelivery при проблемах с endpoint.
9. **GitHub App webhooks** (для ботов и CI/CD): отдельный lifecycle — см. [GitHub Apps](./github_apps.md) для HMAC, App-level delivery и обработки событий `repository`, `installation`.

## Дополнительная информация

- **[GitHub Apps](./github_apps.md)** — App webhook delivery, HMAC verification, retry policy (App-specific).
- **[GitHub API](./github_api.md)** — общий REST/GraphQL API, rate limits.
- **[Управление секретами](./secrets_management.md)** — хранение webhook secret и других секретов.
- **Официальная документация**: [Webhooks](https://docs.github.com/en/webhooks), [Webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads), [Webhook forwarding](https://docs.github.com/en/webhooks/using-github-actions-in-webhooks).
