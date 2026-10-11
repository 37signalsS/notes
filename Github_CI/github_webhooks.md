# GitHub Webhooks: События, доставка и обработка

**Актуально для:** GitHub.com / GitHub Enterprise Server 3.14+ (REST API, Webhook deliveries, HMAC-SHA256, gh CLI)

GitHub Webhooks — механизм асинхронной доставки событийных HTTP-уведомлений на внешние веб-серверы при возникновении изменений в репозитории, организации или GitHub App. При совершении события (коммит, создание Pull Request, запуск или завершение CI/CD job, публикация релиза) сервис доставки GitHub (Hookshot) выполняет HTTP `POST`-запрос с сериализованным JSON-пейлоадом и криптографической подписью на настроенный URL. Webhooks составляют фундамент событийно-ориентированной интеграции инфраструктуры, GitOps-контроллеров, систем мониторинга и автоматизации процессов в контуре DevOps и системного администрирования.

## Определения

- **Webhook**: Зарегистрированный в GitHub HTTP/HTTPS эндпоинт, принимающий входящие `POST`-запросы при наступлении определенных событий.
- **Событие (Event)**: Тип системного действия в GitHub (`push`, `pull_request`, `workflow_job`, `issues`, `release` и др.), инициирующий генерацию уведомления.
- **Delivery ID**: Уникальный идентификатор попытки доставки формата UUIDv4, передаваемый в HTTP-заголовке `X-GitHub-Delivery`. Ключевой элемент для обеспечения идемпотентности и сквозной трассировки.
- **HMAC Signature**: Криптографический дайджест тела запроса по алгоритму HMAC-SHA256, передаваемый в заголовке `X-Hub-Signature-256`. Вычисляется с использованием общего секрета (`Webhook Secret`) и служит единственным надежным способом аутентификации отправителя.
- **Fast-ACK (Быстрый ответ)**: Архитектурный паттерн обработки вебхуков, при котором приемник валидирует подпись, сохраняет пейлоад в локальную очередь и немедленно возвращает HTTP `200 OK` или `202 Accepted` (в пределах 500 мс), защищая соединение от жесткого 10-секундного таймаута GitHub.
- **Идемпотентность (Idempotency)**: Свойство обработчика сохранять корректное состояние системы при многократном получении одного и того же события доставки.
- **Retry Policy**: Алгоритм экспоненциального отката (exponential backoff), используемый GitHub для повторных попыток отправки при недоступности приемника или получении ответов с кодами ошибок (не-2xx).
- **Webhook Forwarding**: Проброс событий из публичного API GitHub на локальный адрес разработчика или администратора через WebSocket-соединение с помощью GitHub CLI (`gh webhook forward`).
- **Organization Webhook**: Вебхук уровня организации, агрегирующий события со всех существующих и создаваемых репозиториев организации.
- **Repository Webhook**: Вебхук уровня отдельного репозитория, изолированный в рамках единичного проекта.

## Архитектура и модель доставки

### Архитектурная схема обработки событий

При построении отказоустойчивой on-premise инфраструктуры обработки вебхуков недопустимо выполнять длительные задачи (сборка артефактов, запуск деплоя, обращение к базам данных) синхронно в HTTP-хэндлере. Архитектура разделяется на пограничный прокси, легковесный сервис приема (Fast-ACK Receiver), локальный брокер очередей и независимые фоновые воркеры.

```text
┌───────────────────────┐
│ GitHub Hookshot       │
│ (github.com / GHES)   │
└──────────┬────────────┘
           │ HTTPS POST (Timeout: 10s)
           ▼
┌────────────────────────────────────────────────────────┐
│ Edge Reverse Proxy (Nginx / HAProxy)                  │
│ - TLS Termination (Let's Encrypt / Корпоративный CA)   │
│ - Rate Limiting & DDOS Shield                          │
│ - Логирование X-GitHub-Delivery, X-GitHub-Event        │
└──────────┬─────────────────────────────────────────────┘
           │ HTTP (Unix Domain Socket / Localhost)
           ▼
┌────────────────────────────────────────────────────────┐
│ Fast-ACK Webhook Receiver (Go / Python Daemon)         │
│ 1. Проверка HMAC-SHA256 (constant-time compare)        │
│ 2. Проверка Delivery ID в Redis (дедупликация)         │
│ 3. Сохранение пейлоада в очередь брокера               │
│ 4. Немедленный возврат HTTP 202 Accepted (< 200 мс)    │
└──────────┬─────────────────────────────────────────────┘
           │ Запись в очередь
           ▼
┌────────────────────────────────────────────────────────┐
│ Local Message Broker (Redis Streams / RabbitMQ)        │
└──────────┬─────────────────────────────────────────────┘
           │ Чтение сообщений воркерами
           ▼
┌────────────────────────────────────────────────────────┐
│ Background Workers / Automation                        │
│ - Запуск локальных CI/CD пайплайнов                    │
│ - Синхронизация репозиториев и зеркалирование Git      │
│ - Аудит, нотификации и сбор метрик                     │
└────────────────────────────────────────────────────────┘
```

### Спецификация HTTP-заголовков доставки

GitHub отправляет каждый HTTP-запрос со стандартизированным набором метаданных в заголовках:

| HTTP-заголовок | Пример значения | Назначение в Sysadmin/SRE |
|---|---|---|
| `X-GitHub-Delivery` | `72d3162e-3f11-11eb-8c65-8ccb9554bf56` | UUID конкретной доставки. Используется в качестве ключа идемпотентности в Redis и сквозного `Request-ID` в логах |
| `X-GitHub-Event` | `push`, `pull_request`, `workflow_job` | Имя события. Используется для первичной маршрутизации запросов без парсинга JSON |
| `X-Hub-Signature-256` | `sha256=d5792437...` | Контрольная сумма тела запроса HMAC-SHA256. Обязательна для криптографической аутентификации |
| `X-GitHub-Hook-ID` | `123456789` | Числовой ID конфигурации вебхука в GitHub |
| `X-GitHub-Hook-Installation-Target-Type` | `repository`, `organization` | Область действия вебхука |
| `X-GitHub-Hook-Installation-Target-ID` | `987654321` | ID репозитория или организации, породившей событие |
| `User-Agent` | `GitHub-Hookshot/1a2b3c4` | Сигнатура сервиса доставки GitHub |
| `Content-Type` | `application/json` | Формат передачи данных (строго `application/json` для production) |

### Модель повторов, таймаутов и ограничений

1. **Жесткий лимит времени (Timeout: 10 секунд)**:
   - Если приемник не вернул HTTP-ответ в течение **10 секунд** с момента установки соединения, GitHub принудительно обрывает TCP-сессию и регистрирует доставку со статусом `Timed out`.
   - Любая обработка длительностью более 500 мс создает риск сетевых таймаутов при всплесках нагрузки.
2. **Экспоненциальный откат (Retry Policy)**:
   - При получении любого статуса, кроме 2xx (например, `500 Internal Server Error`, `502 Bad Gateway`, `404 Not Found`), либо при сбое соединения/таймауте, запускается цепочка повторных попыток.
   - Задержки между попытками растут экспоненциально: ~1 мин, ~2 мин, ~4 мин, ~8 мин, ~16 мин, увеличиваясь вплоть до интервала в несколько часов.
   - Общее окно повторов составляет **до 72 часов** (суммарно 10–15 попыток).
   - **Отсутствие встроенного Dead Letter Queue (DLQ)**: Если сервер недоступен более 72 часов, недоставленные события **безвозвратно отбрасываются**. На стороне GitHub нет постоянного хранилища недоставленных сообщений.
3. **Автоматическая деактивация вебхуков**:
   - Если вебхук стабильно возвращает ошибки или недоступен на протяжении длительного времени (высокий процент ошибок на протяжении нескольких дней), GitHub переводит вебхук в статус `active: false` и отправляет email-оповещение администраторам.
4. **Лимиты на размер пейлоада и усечение данных (Payload Truncation)**:
   - Максимальный размер тела запроса составляет **25 МБ**.
   - При пуше большого количества коммитов массив `commits` в событии `push` ограничивается первыми **20 коммитами**.
   - Если пуш содержал больше 20 коммитов, в пейлоаде выставляется флаг `"truncated": true`. Для получения полного списка изменений приемник обязан обращаться к GitHub REST API (`GET /repos/{owner}/{repo}/commits?sha={commit_sha}`).

### Сетевая безопасность: HMAC против IP-фильтрации

GitHub публикует диапазоны своих публичных IP-адресов через эндпоинт `/meta`:

```bash
# Получение актуальных CIDR-блоков серверов доставки вебхуков
gh api /meta --jq '.hooks[]'
# → 192.30.252.0/22
# → 185.199.108.0/22
# → 140.82.121.0/24
# → 2a0b:4eb7::/32
```

> [!WARNING]
> **Не полагайтесь исключительно на IP-фильтрацию firewall.** Диапазоны GitHub периодически расширяются и обновляются. Основным и достаточным механизмом безопасности является верификация заголовка `X-Hub-Signature-256`. Если корпоративные регламенты требуют сетевой изоляции, автоматизируйте обновление правил `iptables` / `nftables` по таймеру через `/meta`.

## Практические сценарии и конфигурация

### Сценарий 1: Управление жизненным циклом вебхука через GitHub CLI

Управление вебхуками репозитория с помощью утилиты `gh`:

```bash
# 1. Генерация криптографически стойкого секрета
WEBHOOK_SECRET=$(openssl rand -hex 24)
echo "Secret: ${WEBHOOK_SECRET}"
# → Secret: 4a9f8b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e

# 2. Создание вебхука для отслеживания событий push, pull_request и workflow_job
gh api -X POST /repos/my-org/core-infra/hooks \
  -f name="web" \
  -F active=true \
  -f "events[]=push" \
  -f "events[]=pull_request" \
  -f "events[]=workflow_job" \
  -f config[url]="https://webhook.infra.example.com/api/v1/github" \
  -f config[content_type]="json" \
  -f config[secret]="${WEBHOOK_SECRET}" \
  -f config[insecure_ssl]="0"
# → {
# →   "id": 482910492,
# →   "name": "web",
# →   "active": true,
# →   "events": ["push", "pull_request", "workflow_job"],
# →   "config": {
# →     "url": "https://webhook.infra.example.com/api/v1/github",
# →     "content_type": "json",
# →     "insecure_ssl": "0"
# →   }
# → }

# 3. Отправка тестового события ping для проверки доступности эндпоинта
gh api -X POST /repos/my-org/core-infra/hooks/482910492/pings
# → HTTP 204 No Content

# 4. Просмотр последних попыток доставки
gh api /repos/my-org/core-infra/hooks/482910492/deliveries --jq '.[] | {id: .id, event: .event, status_code: .status_code, delivered_at: .delivered_at}'
# → {
# →   "id": 1827492019,
# →   "event": "ping",
# →   "status_code": 200,
# →   "delivered_at": "2026-10-11T17:15:20Z"
# → }

# 5. Ручной повтор сбойной доставки (Redelivery)
gh api -X POST /repos/my-org/core-infra/hooks/482910492/deliveries/1827492019/attempts
# → HTTP 202 Accepted
```

### Сценарий 2: Production-ready Fast-ACK приемник на Python/FastAPI

Приемник выполняет валидацию подписи в постоянном времени (`constant-time`), проверяет идемпотентность через локальный Redis, складывает валидные события в очередь и немедленно отвечает `202 Accepted`.

```python
# app.py
import hashlib
import hmac
import json
import os
import sys
import redis
from fastapi import FastAPI, Header, HTTPException, Request, Response, status

app = FastAPI(title="GitHub Webhook Ingress Gateway")

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode("utf-8")
if not WEBHOOK_SECRET:
    sys.exit("CRITICAL: GITHUB_WEBHOOK_SECRET environment variable is missing")

# Подключение к локальному серверу очередей Redis
r_pool = redis.ConnectionPool(host="127.0.0.1", port=6379, db=0, decode_responses=False)
redis_client = redis.Redis(connection_pool=r_pool)

DEDUPLICATION_TTL_SECONDS = 7 * 86400  # 7 дней (покрывает окно повторов GitHub 72h)

def verify_github_signature(payload_body: bytes, signature_header: str | None) -> bool:
    """Проверка подписи HMAC-SHA256 с защитой от атак по времени."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    mac = hmac.new(WEBHOOK_SECRET, msg=payload_body, digestmod=hashlib.sha256)
    expected_signature = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected_signature, signature_header)

@app.post("/api/v1/github")
async def handle_github_webhook(
    request: Request,
    response: Response,
    x_github_event: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
    x_hub_signature_256: str | None = Header(None),
):
    # 1. Чтение сырого тела запроса (до парсинга JSON)
    raw_body = await request.body()

    # 2. Криптографическая проверка подлинности
    if not verify_github_signature(raw_body, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing HMAC-SHA256 signature",
        )

    # 3. Валидация обязательных заголовков
    if not x_github_delivery or not x_github_event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required GitHub delivery headers",
        )

    # Обработка проверочного пинга
    if x_github_event == "ping":
        return {"status": "pong", "delivery_id": x_github_delivery}

    # 4. Проверка идемпотентности: SETNX ключа доставки в Redis
    dedup_key = f"github:dedup:{x_github_delivery}".encode("utf-8")
    is_new_delivery = redis_client.set(dedup_key, b"1", nx=True, ex=DEDUPLICATION_TTL_SECONDS)
    
    if not is_new_delivery:
        # Дубликат уже был принят ранее, подтверждаем без повторного выполнения задач
        return {"status": "ignored", "reason": "duplicate_delivery", "delivery_id": x_github_delivery}

    # 5. Асинхронное помещение задания в локальную очередь
    queue_item = json.dumps({
        "delivery_id": x_github_delivery,
        "event": x_github_event,
        "payload": json.loads(raw_body),
    }).encode("utf-8")
    
    redis_client.rpush("github:events:incoming", queue_item)

    # 6. Немедленный возврат Fast-ACK
    response.status_code = status.HTTP_202_ACCEPTED
    return {"status": "enqueued", "delivery_id": x_github_delivery}

@app.get("/healthz")
def health_check():
    """Liveness probe эндпоинт для локальных систем мониторинга."""
    redis_client.ping()
    return {"status": "healthy"}
```

### Сценарий 3: Высокопроизводительный Fast-ACK приемник на Go

Реализация на Go с минимальным потреблением оперативной памяти, безопасной проверкой подписи и внутренней очередью через каналы:

```go
// main.go
package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

var webhookSecret []byte

func verifySignature(payload []byte, signatureHeader string) bool {
	if !strings.HasPrefix(signatureHeader, "sha256=") {
		return false
	}
	mac := hmac.New(sha256.New, webhookSecret)
	mac.Write(payload)
	expectedMAC := "sha256=" + hex.EncodeToString(mac.Sum(nil))
	return hmac.Equal([]byte(signatureHeader), []byte(expectedMAC))
}

func webhookHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method Not Allowed", http.StatusMethodNotAllowed)
		return
	}

	// 1. Ограничение чтения тела во избежание DoS (максимум 25 МБ)
	r.Body = http.MaxBytesReader(w, r.Body, 25<<20)
	payload, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "Payload Too Large or Read Error", http.StatusRequestEntityTooLarge)
		return
	}
	defer r.Body.Close()

	// 2. Валидация HMAC подписи
	sig := r.Header.Get("X-Hub-Signature-256")
	if !verifySignature(payload, sig) {
		http.Error(w, "Unauthorized: Invalid Signature", http.StatusUnauthorized)
		return
	}

	deliveryID := r.Header.Get("X-GitHub-Delivery")
	eventType := r.Header.Get("X-GitHub-Event")

	if deliveryID == "" || eventType == "" {
		http.Error(w, "Bad Request: Missing Headers", http.StatusBadRequest)
		return
	}

	// 3. Быстрая обработка пинга
	if eventType == "ping" {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"pong"}`))
		return
	}

	// 4. Помещение задачи в буферизированный канал воркеров
	// (В продакшене: публикация в Redis / RabbitMQ / Unix Socket)
	log.Printf("[INGRESS] Accepted event=%s delivery=%s bytes=%d", eventType, deliveryID, len(payload))

	// 5. Немедленный ответ 202 Accepted
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)
	w.Write([]byte(`{"status":"accepted","delivery_id":"` + deliveryID + `"}`))
}

func main() {
	secretStr := os.Getenv("GITHUB_WEBHOOK_SECRET")
	if secretStr == "" {
		log.Fatal("CRITICAL: GITHUB_WEBHOOK_SECRET environment variable is empty")
	}
	webhookSecret = []byte(secretStr)

	mux := http.NewServeMux()
	mux.HandleFunc("/api/v1/github", webhookHandler)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	})

	server := &http.Server{
		Addr:         "127.0.0.1:8080",
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 5 * time.Second,
	}

	log.Println("Starting Webhook Ingress Server on 127.0.0.1:8080...")
	log.Fatal(server.ListenAndServe())
}
```

### Сценарий 4: Конфигурация Nginx Reverse Proxy для вебхуков

Пограничный Nginx принимает запросы от GitHub, проверяет TLS, ограничивает частоту запросов (rate limiting) и проксирует трафик на локальный сервис с пробросом специфичных заголовков.

```nginx
# /etc/nginx/conf.d/github-webhook.conf

# Формат лога с фиксацией заголовков доставки и времени ответа
log_format webhook_audit '$remote_addr - [$time_local] "$request" '
                         'status=$status bytes=$body_bytes_sent '
                         'duration=$request_time '
                         'event="$http_x_github_event" '
                         'delivery="$http_x_github_delivery" '
                         'agent="$http_user_agent"';

# Ограничение частоты запросов для защиты от DDoS
limit_req_zone $binary_remote_addr zone=webhook_ratelimit:10m rate=30r/s;

server {
    listen 443 ssl http2;
    server_name webhook.infra.example.com;

    # TLS-сертификаты
    ssl_certificate /etc/ssl/certs/webhook_bundle.crt;
    ssl_certificate_key /etc/ssl/private/webhook.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Максимальный размер пейлоада GitHub — 25 МБ
    client_max_body_size 30M;
    client_body_buffer_size 1M;

    access_log /var/log/nginx/webhook_access.log webhook_audit;
    error_log /var/log/nginx/webhook_error.log warn;

    location /api/v1/github {
        # Применение rate-limiting с запасом всплеска (burst)
        limit_req zone=webhook_ratelimit burst=50 nodelay;

        # Разрешены только POST-запросы для вебхука
        limit_except POST {
            deny all;
        }

        # Проксирование на локальный Fast-ACK приемник
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;

        # Передача оригинальных заголовков
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Проброс критичных заголовков GitHub
        proxy_set_header X-GitHub-Event $http_x_github_event;
        proxy_set_header X-GitHub-Delivery $http_x_github_delivery;
        proxy_set_header X-Hub-Signature-256 $http_x_hub_signature_256;

        # Таймауты проксирования (с запасом внутри лимита GitHub 10с)
        proxy_connect_timeout 3s;
        proxy_send_timeout 5s;
        proxy_read_timeout 5s;
    }

    # Эндпоинт проверки здоровья для мониторинга
    location /healthz {
        proxy_pass http://127.0.0.1:8080/healthz;
        access_log off;
    }
}
```

### Сценарий 5: Развертывание сервиса приемника через systemd с Security Hardening

Юнит systemd обеспечивает автоматический перезапуск приемника и изоляцию процесса от операционной системы:

```ini
# /etc/systemd/system/github-webhook.service
[Unit]
Description=GitHub Webhook Fast-ACK Ingress Daemon
After=network.target redis-server.service
Wants=redis-server.service

[Service]
Type=simple
User=webhook-svc
Group=webhook-svc
WorkingDirectory=/opt/github-webhook
EnvironmentFile=/etc/default/github-webhook
ExecStart=/opt/github-webhook/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8080 --workers 4

Restart=always
RestartSec=5s
LimitNOFILE=65535

# Настройки изоляции и безопасности (Security Sandboxing)
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
```

Управление сервисом:

```bash
# 1. Создание файла переменных окружения с правами доступа 0600
sudo bash -c 'cat <<EOF > /etc/default/github-webhook
GITHUB_WEBHOOK_SECRET=4a9f8b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e
EOF'
sudo chmod 0600 /etc/default/github-webhook

# 2. Загрузка конфигурации и старт демона
sudo systemctl daemon-reload
sudo systemctl enable --now github-webhook.service

# 3. Проверка статуса сервиса
sudo systemctl status github-webhook.service
# → ● github-webhook.service - GitHub Webhook Fast-ACK Ingress Daemon
# →      Loaded: loaded (/etc/systemd/system/github-webhook.service; enabled)
# →      Active: active (running) since Sun 2026-10-11 17:30:15 UTC
```

### Сценарий 6: Локальная отладка и воспроизведение запросов через curl

Для тестирования обработчика без настройки публичного белого IP-адреса и домена:

#### Способ А: Проброс вебхука через GitHub CLI

```bash
# Проброс событий репозитория на локальный порт разработчика
gh webhook forward --repo=my-org/core-infra --events=push,pull_request --url=http://127.0.0.1:8080/api/v1/github
# → Ready! Forwarding https://api.github.com/... to http://127.0.0.1:8080/api/v1/github
```

#### Способ Б: Ручная эмуляция вызова с генерацией HMAC через OpenSSL

```bash
# 1. Определение параметров эмуляции
SECRET="4a9f8b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e"
PAYLOAD='{"action":"opened","issue":{"number":101,"title":"Bug in backup job"}}'
DELIVERY_ID=$(uuidgen)

# 2. Вычисление сигнатуры HMAC-SHA256
SIGNATURE="sha256=$(printf '%s' "${PAYLOAD}" | openssl dgst -sha256 -hmac "${SECRET}" | awk '{print $2}')"
echo "Signature: ${SIGNATURE}"
# → Signature: sha256=174f85e82b7d51f28b493863414842183c27e8a946b539fa9dfbdc9557458145

# 3. Отправка POST-запроса через curl
curl -i -X POST http://127.0.0.1:8080/api/v1/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: issues" \
  -H "X-GitHub-Delivery: ${DELIVERY_ID}" \
  -H "X-Hub-Signature-256: ${SIGNATURE}" \
  -d "${PAYLOAD}"
# → HTTP/1.1 202 Accepted
# → Content-Type: application/json
# → {"status":"enqueued","delivery_id":"8a97b2d1-5612-421f-82bb-762957f12384"}
```

## Команды и API-операции

### REST API эндпоинты управления вебхуками

| Действие | Метод и URL | Назначение |
|---|---|---|
| Создать хук репозитория | `POST /repos/{owner}/{repo}/hooks` | Регистрация нового эндпоинта и подписок |
| Список хуков репозитория | `GET /repos/{owner}/{repo}/hooks` | Просмотр существующих хуков с их `id` и `config` |
| Получить параметры хука | `GET /repos/{owner}/{repo}/hooks/{hook_id}` | Детальная конфигурация хука |
| Изменить хук | `PATCH /repos/{owner}/{repo}/hooks/{hook_id}` | Включение/выключение (`active`), смена URL или секретов |
| Удалить хук | `DELETE /repos/{owner}/{repo}/hooks/{hook_id}` | Полное удаление вебхука |
| Отправить тестовый пинг | `POST /repos/{owner}/{repo}/hooks/{hook_id}/pings` | Проверка сетевой связности |
| История доставок | `GET /repos/{owner}/{repo}/hooks/{hook_id}/deliveries` | Список последних попыток (до 100 записей за 72 часа) |
| Детали попытки доставки | `GET /repos/{owner}/{repo}/hooks/{hook_id}/deliveries/{delivery_id}` | Полный request/response лог (заголовки, код ответа, тело) |
| Повторить доставку | `POST /repos/{owner}/{repo}/hooks/{hook_id}/deliveries/{delivery_id}/attempts` | Инициация немедленного повтора отправки |
| Создать хук организации | `POST /orgs/{org}/hooks` | Создание org-level хука для всех репозиториев компании |
| Список хуков организации | `GET /orgs/{org}/hooks` | Просмотр корпоративных вебхуков |

### Основные типы событий (Webhook Events) в DevOps

| Имя события | Ключевые действия (`action`) | Типичное применение в SRE/DevOps |
|---|---|---|
| `push` | — | Запуск автономных контуров CI/CD, зеркалирование веток |
| `pull_request` | `opened`, `synchronize`, `closed`, `reopened` | Автоматическая проверка кода, динамические стенды |
| `workflow_job` | `queued`, `in_progress`, `completed` | Масштабирование self-hosted раннеров, учет очередей CI |
| `workflow_run` | `requested`, `completed` | Отправка отчетов в корпоративные каналы, деплой релизов |
| `check_run` / `check_suite` | `created`, `completed`, `rerequested` | Управление блокировками мерджа и статусными проверками |
| `release` | `published`, `prereleased`, `deleted` | Развертывание в production, сборка и подпись образов |
| `issues` / `issue_comment` | `opened`, `edited`, `created` | Интеграция с локальными трекерами задач (Jira, Redmine) |
| `repository` | `created`, `archived`, `deleted` | Автоматическое применение базовых правил защиты веток (Rulesets) |
| `ping` | — | Первичная проверка при настройке эндпоинта |

## Мониторинг и наблюдаемость (SRE)

Приемник вебхуков является критическим звеном инфраструктуры автоматизации. При его сбое нарушается синхронизация GitOps и триггеры CI/CD.

### Ключевые метрики Prometheus

Сервис приема вебхуков должен экспортировать следующие метрики в формате Prometheus:

```text
# Метрика общего числа полученных доставок по событиям и HTTP кодам
github_webhook_deliveries_total{event="push",status="202"} 1420
github_webhook_deliveries_total{event="pull_request",status="202"} 380
github_webhook_deliveries_total{event="push",status="401"} 2

# Ошибки валидации подписи HMAC (возможная атака или рассинхронизация секрета)
github_webhook_signature_failures_total 2

# Число отброшенных повторных доставок (дубликатов)
github_webhook_duplicates_ignored_total 15

# Гистограмма задержки обработки Fast-ACK (должна быть < 500ms)
github_webhook_handler_latency_seconds_bucket{le="0.1"} 1750
github_webhook_handler_latency_seconds_bucket{le="0.5"} 1798
github_webhook_handler_latency_seconds_bucket{le="1.0"} 1800

# Текущая глубина локальной очереди сообщений
github_webhook_queue_depth{queue="incoming"} 4
```

### Правила оповещений (Alertmanager Rules)

```yaml
# /etc/prometheus/rules/github_webhooks_alerts.yml
groups:
  - name: github_webhooks_alerts
    rules:
      - alert: GitHubWebhookDeliveryFailuresHigh
        expr: rate(github_webhook_deliveries_total{status=~"5.."}[5m]) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Высокий процент сбоев обработки вебхуков GitHub"
          description: "Более 5% доставок вебхуков завершаются кодами 5xx. Риск потери триггеров CI/CD."

      - alert: GitHubWebhookSignatureErrorsSpike
        expr: rate(github_webhook_signature_failures_total[5m]) > 0.1
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Всплеск ошибок проверки подписи HMAC вебхуков"
          description: "Возможна компрометация секрета или рассинхронизация настроек в репозитории."

      - alert: GitHubWebhookQueueBacklog
        expr: github_webhook_queue_depth > 500
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Рост очереди необработанных событий вебхуков"
          description: "Глубина очереди {{ $value }} превышает порог 500. Воркеры не успевают обрабатывать нагрузку."
```

## Диагностика и устранение неполадок

| Симптом | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| `Timed out` (код ответа отсутствует, доставка завершается сбоем) | Хэндлер выполняет тяжелую задачу синхронно, превышая лимит 10 с | Проверить `$request_time` в `webhook_access.log` Nginx | Внедрить Fast-ACK: возвращать `202 Accepted` сразу, передавая задачу в очередь Redis |
| HTTP `401 Unauthorized` / Signature Mismatch | Секрет в GitHub не совпадает с переменной окружения; парсинг JSON перед вычислением HMAC | Сравнить секреты; проверить код вычисления хэша на сырых байтах | Вычислять HMAC исключительно от исходного бинарного тела запроса (`raw bytes`), использовать `hmac.compare_digest` |
| Повторная обработка одних и тех же задач | Сетевой сбой между ответом 200 OK и приемом подтверждения GitHub | Проверить совпадение `X-GitHub-Delivery` в логах | Реализовать дедупликацию по ключу `X-GitHub-Delivery` в Redis с `SET NX` на 7 суток |
| HTTP `502 Bad Gateway` в логах GitHub | Приемник упал или перегружен | `sudo systemctl status github-webhook.service` | Настроить перезапуск `Restart=always` в systemd, увеличить число воркеров uvicorn/Go |
| `SSL certificate problem` при отправке с GHES | GitHub Enterprise Server не доверяет корпоративному CA приемника | Проверить цепочку сертификатов: `openssl s_client -connect webhook.infra.example.com:443` | Установить корневой CA приемника в хранилище GHES через утилиту `ghe-ssl-ca-certificate-install` |
| Вебхук внезапно перестал получать события | Вебхук деактивирован GitHub из-за множественных ошибок | `gh api /repos/.../hooks/{id} --jq '.active'` | Устранить причину сбоев на сервере и выполнить PATCH-запрос: `gh api -X PATCH /repos/.../hooks/{id} -F active=true` |
| `truncated: true` в push-событии (пропущены коммиты) | В пуше передано более 20 коммитов, GitHub ограничил массив `commits` | Проверить поле `"truncated"` в JSON пейлоада | Если `truncated == true`, запросить полный список коммитов через REST API по SHA ветки |
| Запросы блокируются брандмауэром | Сервер блокирует входящие IP GitHub через Fail2ban или iptables | `sudo iptables -L -n -v \| grep DROP` | Добавить CIDR-диапазоны из `gh api /meta --jq '.hooks[]'` в белый список |

### Команды системной диагностики на сервере

```bash
# 1. Проверка входящего сетевого трафика вебхуков на сетевом интерфейсе
sudo tcpdump -nn -i eth0 'tcp port 443 and (src 140.82.121.0/24 or src 192.30.252.0/22)' -c 10
# → IP 140.82.121.34.42110 > 10.0.1.15.443: Flags [P.], seq 1:1420, ack 1, win 502, length 1419

# 2. Мониторинг последних записей в аудит-логе Nginx с фильтрацией по событию
sudo tail -f /var/log/nginx/webhook_access.log | grep --line-buffered "event="
# → 140.82.121.34 - [11/Oct/2026:17:42:01 +0000] "POST /api/v1/github HTTP/2.0" status=202 bytes=64 duration=0.042 event="push" delivery="6d1b24e0-3f20-11eb-98d1-0f723b1a82f1" agent="GitHub-Hookshot/7a3b4c"

# 3. Просмотр логов сервиса приема через journalctl
sudo journalctl -u github-webhook.service -n 50 --no-pager
```

## Лучшие практики

1. **Криптографическая верификация HMAC обязательна**: Всегда проверяйте заголовок `X-Hub-Signature-256`. Никогда не полагайтесь исключительно на проверку IP-адресов.
2. **Безопасное сравнение подписей (Constant-Time)**: Используйте функции защиты от атак по времени (`hmac.compare_digest` в Python, `hmac.Equal` в Go, `crypto.timingSafeEqual` в Node.js), чтобы предотвратить утечку секрета через тайминг-атаки.
3. **Строгое соблюдение Fast-ACK**: Ответ должен отдаваться клиенту за время < 200–500 мс. Любая фоновая автоматизация должна передаваться в брокер сообщений (Redis, RabbitMQ).
4. **Хранение ключа дедупликации >= 7 дней**: Идентификатор `X-GitHub-Delivery` должен кэшироваться на срок не менее 7 дней (168 часов), что с запасом перекрывает 72-часовое окно повторов GitHub.
5. **Принцип минимальных привилегий для событий**: Подписывайтесь только на строго необходимые события (не используйте `Send me everything` / wildcard `*`). Это снижает нагрузку на приемник и уменьшает объем передаваемых данных.
6. **Ротация секретов без простоя (Dual-secret)**: При необходимости плановой смены секрета реализуйте в коде приемника проверку подписи по двум секретам (текущему и новому) перед обновлением настроек в GitHub.
7. **Мониторинг глубины очереди и алертинг**: Отслеживайте накопление необработанных задач в брокере сообщений. Падение воркеров не должно приводить к переполнению оперативной памяти приемника.
8. **Изоляция процесса приемника**: Запускайте демон вебхука от непривилегированного пользователя с включенными директивами песочницы (`ProtectSystem=strict`, `NoNewPrivileges=true`).

## Дополнительная информация

- **[GitHub Apps](./github_apps.md)** — Специфика приема вебхуков для приложений GitHub App, жизненный цикл токенов и обработка событий инсталляции.
- **[GitHub REST API](./github_api.md)** — Аутентификация, пагинация, работа с rate limits при выборке данных, усеченных в вебхуках.
- **[GitHub Deployments API](./github_deployments_api.md)** — Прием и валидация событий развертывания (`deployment`, `deployment_status`).
- **[Управление секретами](./secrets_management.md)** — Безопасное хранение, ротация и монтирование секретов вебхуков в инфраструктуре.
- **Официальная документация GitHub**:
  - [About webhooks](https://docs.github.com/en/webhooks/about-webhooks)
  - [Webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
  - [Validating webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
  - [Testing webhooks with GitHub CLI](https://docs.github.com/en/webhooks/using-webhooks/testing-webhooks)
