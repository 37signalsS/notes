# cURL — универсальный инструмент для передачи данных

## Определения

**cURL** (Client for URLs) — мощная утилита командной строки и кроссплатформенная библиотека (libcurl) для передачи данных с использованием синтаксиса URL. Поддерживает более 20 протоколов, включая HTTP(S), FTP, SCP, SFTP, SMB, LDAP, MQTT и другие. Является промышленным стандартом для взаимодействия с API, автоматизации задач (CI/CD) и низкоуровневой диагностики сетевых сервисов.

## Предварительные требования

### Установка

| Дистрибутив | Команда |
| :--- | :--- |
| **Debian/Ubuntu** | `apt-get install -y curl` |
| **RHEL/CentOS/Rocky** | `dnf install -y curl` |
| **Alpine** | `apk add --no-cache curl` |
| **macOS** | `brew install curl` (Homebrew устанавливает актуальную версию, а не системную) |

### Проверка версии и сборки

```bash
# Версия и подключенные протоколы
curl --version
# → curl 8.7.1 (x86_64-apple-darwin25.0) libcurl/8.7.1 ...
# → Protocols: dict file ftp ftps gopher ... http https imap ... pop3 ...
# → Features: alt-svc AsynchDNS brotli GSS-API HSTS ... TLS-SRP

# Важные поля вывода:
# - Protocols: список поддерживаемых протоколов (влияет на доступные опции)
# - Features: наличие HTTP/2, HTTP/3 (HTTP3), brotli, zstd, IPv6, Unix-сокетов
#   Если HTTP3 отсутствует — сборка не поддерживает QUIC
#   Если alt-serts отсутствует — HTTP/3 через Alt-Svc недоступен
```

> **Важно для production:** На минимальных Docker-образах (Alpine, scratch) curl может отсутствовать. В healthcheck'ах и init-контейнерах проверяйте наличие утилиты в образе заранее. Если curl недоступен, альтернативой является `wget -q --spider`.

### Проверка поддержки HTTP/2 и HTTP/3

```bash
# HTTP/2: поддерживается по умолчанию в curl 7.66+
curl -v --http2 https://example.com 2>&1 | grep "ALPN"
# → * ALPN, offering h2
# → * ALPN, server accepted h2

# HTTP/3: требует специальной сборки (ngtcp2, quiche или wolfssl)
# При отсутствии поддержки curl выдаст ошибку "unknown option --http3"
# Проверка: HTTP/3 работает через UDP, а не TCP
curl -v --http3 https://example.com 2>&1 | grep "HTTP/3"
# → * Using HTTP/3
```

## Основные концепции

### Структура команды

```bash
curl [опции] [URL]
```

**Основные группы опций:**

- **Запрос:** `-X` (явное указание метода), `-H` (добавление заголовка), `-d` (отправка данных), `-F` (multipart-форма), `--json` (автоматический JSON-запрос).
- **Ответ:** `-o` (сохранить в файл), `-O` (сохранить с именем из URL), `-s` (тихий режим), `-i` (вывод заголовков ответа), `-v` (подробный лог).
- **Безопасность:** `-u` (аутентификация), `-k` (игнорировать ошибки SSL), `--cert`/`--key` (клиентские сертификаты).
- **Таймауты и повторы:** `--connect-timeout`, `--max-time`, `--retry`, `--retry-delay`.
- **Производительность:** `-Z` (параллельная загрузка нескольких ресурсов).

### Поддерживаемые протоколы

| Протокол | Описание и применение |
| :--- | :--- |
| **HTTP/HTTPS** | Работа с веб-сервисами, поддержка HTTP/1.1, HTTP/2 и HTTP/3 (QUIC). |
| **gRPC** | Поддерживается через HTTP/2 (требуется специфическая передача заголовков). |
| **FTP/FTPS** | Классическая передача файлов, включая защищенные TLS-версии. |
| **SCP/SFTP** | Безопасная передача данных поверх SSH. |
| **SMB/CIFS** | Доступ к файловым ресурсам Windows. |
| **LDAP(S)** | Взаимодействие со службами каталогов. |
| **MQTT** | Протокол для интернета вещей (IoT). |
| **SMTP/POP3/IMAP** | Протоколы работы с электронной почтой. |

### Настройка прокси-сервера

curl поддерживает прокси на уровне приложения, а также автоматически использует переменные окружения. Это критично в корпоративных средах, где прямой доступ в интернет запрещён.

**Переменные окружения (приоритет по умолчанию):**

| Переменная | Назначение |
| :--- | :--- |
| `HTTP_PROXY` / `http_proxy` | Прокси для HTTP-запросов |
| `HTTPS_PROXY` / `https_proxy` | Прокси для HTTPS-запросов |
| `NO_PROXY` / `no_proxy` | Список хостов/доменов, исключаемых из прокси (через запятую) |
| `ALL_PROXY` / `all_proxy` | Универсальный прокси для всех протоколов |

> На Linux/macOS приоритет у переменных в нижнем регистре, если заданы оба варианта.

**Явное указание прокси через опции curl:**

```bash
# HTTP/HTTPS прокси
curl --proxy http://proxy.corp:8080 https://api.example.com
curl -x socks5://proxy.corp:1080 https://api.example.com

# Аутентификация на прокси
curl --proxy http://proxy.corp:8080 --proxy-user admin:password https://api.example.com

# Исключение хостов из прокси (--noproxy)
curl --noproxy '*.internal.corp,localhost' https://api.example.com
# Эквивалент: export no_proxy="*.internal.corp,localhost"

# SOCKS5 с DNS-резолвингом на стороне прокси (важно для конфиденциальности)
curl --socks5-hostname proxy.corp:1080 https://api.example.com
# --socks5-hostname: DNS разрешается прокси
# --socks5: DNS разрешается локально (менее безопасно)
```

**Валидация работы прокси:**

```bash
# Проверка, что curl использует прокси
curl -v --proxy http://proxy.corp:8080 https://example.com 2>&1 | grep "proxy"
# → * Uses proxy env variable HTTPS_PROXY = 'proxy.corp:8080'

# Проверка внешнего IP через прокси (должен вернуть IP прокси, а не хоста)
curl -s --proxy http://proxy.corp:8080 https://ifconfig.me
```

### Верификация сертификатов и собственный CA

В корпоративных средах часто используется внутренний CA (Certificate Authority), который не входит в стандартный набор доверенных корневых сертификатов. curl по умолчанию проверяет сертификаты сервера и завершается с ошибкой (exit code 60) при несоответствии.

**Настройка доверия к внутреннему CA:**

```bash
# Указать файл с сертификатом CA (PEM-формат)
curl --cacert /etc/ssl/certs/internal-ca.crt https://internal.service.corp/api

# Указать директорию с сертификатами CA (Debian/Ubuntu)
curl --capath /etc/ssl/certs/ https://internal.service.corp/api

# Использовать системный набор сертификатов + дополнительный файл
curl --cacert /etc/ssl/certs/internal-ca.crt --cacert /etc/ssl/certs/public-ca.crt https://example.com
# Примечание: несколько --cacert не поддерживаются; используйте --capath или объедините CA в один файл
```

**Межсертификатная аутентификация (mTLS):**

```bash
# Клиентский сертификат + ключ для аутентификации на сервере
curl --cert client.crt --key client.key https://service.corp/api

# Если ключ защищён паролем
curl --cert client.crt --key client.key --pass "my-passphrase" https://service.corp/api

# Формат PKCS#12 (.pfx/.p12)
curl --cert-type P12 --cert client.pfx:password https://service.corp/api
```

> **Важно:** Флаг `-k` (`--insecure`) отключает проверку сертификатов сервера. Использование в production-скриптах запрещено — это делает соединение уязвимым для MitM-атак. Допустимо только для временной отладки.

### Управление редиректами

По умолчанию curl **не следует** HTTP-редиректам (3xx ответы). Это критично для скриптов, работающих с API, которые используют редиректы при авторизации или миграции эндпоинтов.

```bash
# Следовать всем редиректам (Location заголовок)
curl -L https://example.com/old-endpoint

# Ограничить максимальное количество редиректов (предотвращение бесконечных циклов)
curl -L --max-redirs 10 https://example.com/api

# Запретить редиректы (полезно для тестирования)
curl --max-redirs 0 https://example.com/api
# → Вернёт 3xx ответ с заголовком Location

# Сохранять метод запроса при 307/308 (POST остаётся POST)
curl -L --post307 --post308 -X POST -d '{}' https://example.com/api
# По умолчанию при 301/302 curl меняет POST на GET
```

---

## Практические сценарии

### Сценарий 1: Безопасная работа в скриптах и CI/CD

В скриптах крайне важно обрабатывать ошибки сервера и ограничивать время ожидания.

```bash
# -f (--fail): возвращает код 22 при HTTP 4xx/5xx (без него curl вернет 0)
# -s (--silent): подавляет вывод прогресса (мусор в логах CI)
# -S (--show-error): показывает ошибку даже в тихом режиме
curl -fsS https://api.example.com/health || exit 1

# Настройка надежных таймаутов
curl -f --max-time 10 --connect-timeout 5 https://api.example.com/api
```

### Сценарий 2: Работа с JSON API

**Современный способ (curl 7.82.0+):**
Опция `--json` автоматически добавляет заголовки `Content-Type: application/json` и `Accept: application/json`, а также устанавливает метод POST (если не указано иное).

```bash
# POST с JSON данными
curl --json '{"user_id":42, "status":"active"}' https://api.example.com/v1/update
```

**Классический способ:**
```bash
# GET с аутентификацией и заголовком
curl -H 'Accept: application/json' -H "Authorization: Bearer $TOKEN" https://api.example.com/data

# POST с данными из строки
curl -X POST -H 'Content-Type: application/json' -d '{"name":"test"}' https://api.example.com/resource

# PATCH (частичное обновление)
curl -X PATCH -H 'Content-Type: application/merge-patch+json' -d '{"active":false}' https://api.example.com/resource/1
```

### Сценарий 3: Передача файлов и форм

```bash
# multipart/form-data (загрузка файла через форму)
curl -F 'user=John' -F 'avatar=@/path/to/photo.jpg' https://api.example.com/upload

# Отправка "сырых" бинарных данных (например, для S3 или объектных хранилищ)
curl --data-binary @archive.zip https://api.example.com/storage

# Загрузка нескольких файлов одновременно
curl -F 'files=@f1.txt' -F 'files=@f2.txt' https://api.example.com/upload
```

### Сценарий 4: Работа с Cookies и сессиями

```bash
# Сохранить полученные cookies в файл (cookie jar)
curl -c cookies.txt https://example.com/login

# Загрузить cookies из файла для выполнения авторизованного запроса
curl -b cookies.txt https://example.com/profile

# Совместное использование (чтение и запись обновлений)
curl -b cookies.txt -c cookies.txt https://example.com/api
```

### Сценарий 5: Методы аутентификации

```bash
# Базовая аутентификация (Basic Auth)
curl -u user:password https://api.example.com/protected

# Bearer токен (OAuth2 / JWT)
curl -H "Authorization: Bearer $TOKEN" https://api.example.com/api/resource

# Использование .netrc (наиболее безопасно для паролей)
# Файл ~/.netrc должен иметь права 600 и содержать:
# machine api.example.com login user password pass
curl --netrc https://api.example.com/protected
```

### Сценарий 6: Отладка и диагностика

```bash
# Подробный лог TLS-рукопожатия и заголовков
curl -v https://example.com

# Получение только заголовков (HEAD запрос)
curl -I https://example.com

# Полный дамп обмена в текстовом формате
curl --trace-ascii debug.log https://example.com

# Форматированный вывод временных метрик
curl -o /dev/null -s -w \
  "DNS: %{time_namelookup}s\n\
   TCP: %{time_connect}s\n\
   TLS: %{time_appconnect}s\n\
   Server: %{time_starttransfer}s\n\
   Total: %{time_total}s\n" \
  https://example.com
```
*Для глубокого анализа см. [Диагностика задержек curl](../../../Diagnostics/Networking/curl_network_diagnostics.md).*

### Сценарий 7: Определение публичного IP-адреса

```bash
# Быстрая проверка внешнего IP
curl -s ifconfig.me
curl -s icanhazip.com
curl -s ipinfo.io/ip
```

### Сценарий 8: Обход DNS и тестирование через SNI

```bash
# Принудительное сопоставление домена и IP (тестирование ноды за балансировщиком)
curl --resolve example.com:443:93.184.216.34 https://example.com

# Тестирование локальных виртуальных хостов
curl --resolve site.local:80:127.0.0.1 http://site.local
```

### Сценарий 9: Работа с большими файлами и повторы

```bash
# Продолжение прерванной загрузки (Resume)
curl -C - -O https://example.com/huge-file.zip

# Ограничение скорости (шейпинг) до 500 КБ/с
curl --limit-rate 500K -O https://example.com/file.zip

# Логика повторов при сетевых сбоях
# --retry-connrefused: повторять даже если соединение отклонено
curl --retry 5 --retry-delay 2 --retry-connrefused https://api.example.com/unstable
```

### Сценарий 10: Обработка JSON через jq

Интеграция curl и jq позволяет строить мощные конвейеры обработки данных.

```bash
# Красивое форматирование JSON
curl -s https://api.github.com/repos/curl/curl | jq .

# Выборка конкретных полей
curl -s https://api.example.com/users | jq '.[].email'

# Сложная фильтрация
curl -s https://api.example.com/orders | jq '.[] | select(.status == "failed") | .id'
```

### Сценарий 11: Проверка версий протокола (HTTP/2 и HTTP/3)

```bash
# Проверка поддержки HTTP/2
curl -I --http2 https://example.com/

# Проверка HTTP/3 (требуется поддержка QUIC в сборке curl)
curl -I --http3 https://example.com/
```

### Сценарий 12: Healthcheck в Docker и Kubernetes

Контейнеры часто не содержат curl. В healthcheck'ах и init-контейнерах критично проверять наличие инструмента и выбирать правильную стратегию.

**Dockerfile — healthcheck с curl:**

```dockerfile
# Минимальный образ с curl
FROM alpine:3.19
RUN apk add --no-cache curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8080/health || exit 1
# -f: вернуть код 22 при HTTP 4xx/5xx (обязательно для корректного статуса unhealthy)
# -s: подавить прогресс-бар
# -S: показать ошибку в выводе (для docker inspect)
```

**Dockerfile — healthcheck с wget (если curl недоступен):**

```dockerfile
# wget есть в Alpine "из коробки"
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q --spider http://localhost:8080/health || exit 1
# --spider: не скачивать контент, только проверить доступность
```

**Kubernetes — HTTP-проверка в Pod spec:**

```yaml
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: app
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 10
      failureThreshold: 3
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 15
      periodSeconds: 20
      timeoutSeconds: 5
      failureThreshold: 3
    startupProbe:
      httpGet:
        path: /health
        port: 8080
      failureThreshold: 30
      periodSeconds: 2
      # startupProbe даёт приложению время на инициализацию
      # livenessProbe не запускается до завершения startupProbe
```

**Валидация healthcheck изнутри контейнера:**

```bash
# Проверка из кластера (BusyBox не содержит curl, используйте wget или установите curl)
kubectl exec -it my-pod -- curl -fsS http://localhost:8080/health
# Если curl отсутствует:
kubectl exec -it my-pod -- wget -qO- http://localhost:8080/health
```

### Сценарий 13: Работа через прокси-сервер

В корпоративных сетях прямой доступ в интернет часто запрещён. curl поддерживает HTTP/HTTPS и SOCKS5 прокси.

```bash
# Автоматическое использование прокси из переменных окружения
export https_proxy=http://proxy.corp:8080
export http_proxy=http://proxy.corp:8080
export no_proxy=localhost,127.0.0.1,*.internal.corp
curl https://api.example.com  # → трафик идёт через proxy.corp:8080

# Явное указание прокси
curl --proxy http://proxy.corp:8080 https://api.example.com

# Аутентификация на прокси
curl --proxy http://proxy.corp:8080 --proxy-user admin:password https://api.example.com

# SOCKS5 прокси (DNS-резолвинг на стороне прокси — рекомендуется)
curl --socks5-hostname proxy.corp:1080 https://api.example.com

# Игнорирование прокси для внутренних хостов
curl --noproxy '*.internal.corp,localhost' https://internal.service.corp/api
```

**Типичная ошибка — циклический редирект через прокси:**

```bash
# Симптом: HTTP 301 → 301 → 301 → ... (обычно HTTP → HTTPS)
# Решение: убедиться, что URL указывает на правильный протокол
curl -v --proxy http://proxy.corp:8080 https://api.example.com
# При необходимости используйте -L для следования редиректам
```

### Сценарий 14: Mutual TLS (mTLS) — клиентские сертификаты

mTLS используется для аутентификации клиента на сервере (в отличие от стандартного TLS, где аутентифицируется только сервер). Типичные сценарии: внутренние API-сервисы, service mesh без sidecar, доступ к безопасным реестрам образов.

```bash
# Клиентский сертификат + ключ (PEM-формат)
curl --cert client.crt --key client.key https://service.corp/api

# Если ключ защищён паролем
curl --cert client.crt --key client.key --pass "my-passphrase" https://service.corp/api

# Самоподписанный серверный сертификат + клиентский сертификат
curl --cacert ca.crt --cert client.crt --key client.key https://self-signed.service.corp/api

# PKCS#12 (.pfx/.p12) — единый файл с сертификатом, ключом и цепочкой
curl --cert-type P12 --cert client.pfx:password https://service.corp/api
```

**Генерация тестового клиентского сертификата (для отладки):**

```bash
# Генерация CA
openssl req -x509 -newkey rsa:4096 -keyout ca.key -out ca.crt -days 365 -nodes \
  -subj "/CN=Test CA"

# Генерация клиентского сертификата
openssl req -newkey rsa:2048 -keyout client.key -out client.csr -nodes \
  -subj "/CN=client.service.corp"
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out client.crt -days 365

# Использование
curl --cacert ca.crt --cert client.crt --key client.key https://self-signed.service.corp/api
```

### Сценарий 15: Unix-сокеты — прямое взаимодействие с демонами

Для доступа к локальным сервисам через Unix-сокеты (Docker, etcd, Prometheus, systemd) curl использует опцию `--unix-socket`.

```bash
# Docker Engine API (без TCP-порта, напрямую через сокет)
curl --unix-socket /var/run/docker.sock http://localhost/containers/json
curl --unix-socket /var/run/docker.sock http://localhost/info | jq .ContainersRunning

# Docker Compose — проверка статуса сервисов
curl --unix-socket /var/run/docker.sock http://localhost/containers/my-app/json | jq .State.Status

# Prometheus метрики (через unix-socket прокси)
curl --unix-socket /run/prometheus/prometheus.sock http://localhost/metrics | head -20

# Systemd (через socket-activated сервис)
curl --unix-socket /run/systemd/journal/io.systemd.journal http://localhost/entries
```

**Валидация доступности сокета:**

```bash
# Проверка существования сокета
ls -la /var/run/docker.sock
# → srw-rw---- 1 root docker 0 ... /var/run/docker.sock

# Проверка прав доступа (текущий пользователь должен быть в группе docker)
groups
# → docker sudo

# Проверка через curl (ожидаем JSON-ответ)
curl -sf --unix-socket /var/run/docker.sock http://localhost/version | jq .Version
# → "24.0.7"
```

### Сценарий 16: Тестирование вебхуков и колбэков

При разработке и отладке webhook-обработчиков (CI/CD, Payment gateway, Telegram Bot API) необходимо отправлять тестовые запросы с произвольными заголовками и телом.

```bash
# Имитация webhook-запроса от GitLab/GitHub
curl -X POST \
  -H "Content-Type: application/json" \
  -H "X-Gitlab-Event: Push Hook" \
  -H "X-Gitlab-Token: $WEBHOOK_SECRET" \
  -d '{
    "ref": "refs/heads/main",
    "project": {"name": "my-repo"},
    "commits": [{"message": "test commit"}]
  }' \
  https://my-server.com/webhook/gitlab

# Тест Telegram Bot webhook
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1,
    "message": {
      "chat": {"id": 123456},
      "text": "/start"
    }
  }' \
  https://api.telegram.org/bot$BOT_TOKEN/setWebhook?url=https://my-server.com/webhook/tg

# Проверка ответа обработчика (ожидаем 200 OK)
curl -fsS -X POST -H "Content-Type: application/json" \
  -d '{"event":"test"}' https://my-server.com/webhook
# → exit code 0 (успех) или 22 (HTTP 4xx/5xx)
```

**Отладка webhook'ов:**

```bash
# Подробный вывод для анализа проблемы
curl -v -X POST -H "Content-Type: application/json" \
  -d '{"test":true}' https://my-server.com/webhook 2>&1

# Проверка только HTTP-кода (быстрая валидация)
curl -o /dev/null -s -w "%{http_code}" \
  -X POST -H "Content-Type: application/json" \
  -d '{"test":true}' https://my-server.com/webhook
# → 200
```

### Сценарий 17: GraphQL запросы

GraphQL-серверы принимают все запросы через POST на один эндпоинт (обычно `/graphql`). Тело запроса содержит JSON с полем `query`.

```bash
# Простой query
curl -s -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "{ users { id name email } }"}' | jq .

# Query с аргументами
curl -s -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "query": "query GetUser($id: ID!) { user(id: $id) { id name role } }",
    "variables": {"id": "123"}
  }' | jq .

# Mutation (создание данных)
curl -s -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "mutation { createUser(input: {name: \"Ivan\", email: \"ivan@example.com\"}) { id name } }"
  }' | jq .

# Интроспекция (получение схемы — полезно для отладки)
curl -s -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __schema { queryType { name } mutationType { name } types { name kind } } }"}' | jq .

# Pagination через cursor в GraphQL
curl -s -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -d '{
    "query": "query { users(first: 20, after: \"eyJpZCI6MTIzfQ==\") { edges { node { id name } } pageInfo { hasNextCursor endCursor } } }"
  }' | jq .
```

**Валидация:**
```bash
# Проверка, что сервер поддерживает GraphQL (интроспекция)
curl -s -X POST https://api.example.com/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ __typename }"}' | jq -r '.data.__typename'
# → Query (или имя схемы)
```

> **Отличие от REST:** В GraphQL нет множества эндпоинтов — все запросы идут на один URL. Это упрощает проксирование, но осложняет rate limiting (нужно анализировать тело запроса).

### Сценарий 18: Тестирование WebSocket

curl поддерживает WebSocket начиная с версии 7.86. Протокол инициируется через HTTP Upgrade handshake.

```bash
# Проверка поддержки WebSocket в сборке curl
curl --version | grep -i websocket
# → Protocols: ... ws wss ...

# Базовый WebSocket handshake (только проверка Upgrade)
curl -i -N \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Version: 13" \
  https://ws.example.com/socket
# → HTTP/1.1 101 Switching Protocols (при успехе)

# WebSocket с аутентификацией через заголовок
curl -i -N \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Authorization: Bearer $TOKEN" \
  https://ws.example.com/socket
```

> **Важно:** curl не поддерживает полноценный двусторонний обмен данными по WebSocket (отправка и чтение фреймов). Для тестирования WebSocket API используйте `websocat` (CLI) или `k6/ws` (load testing).

```bash
# websocat — полноценный WebSocket-клиент для терминала
# Установка: cargo install websocat
websocat wss://ws.example.com/socket
# Отправка сообщения:
echo '{"action":"subscribe","channel":"metrics"}' | websocat wss://ws.example.com/socket
```

### Сценарий 19: REST API паттерны — pagination и filtering

```bash
# Offset-based pagination (первые 20 записей, пропустив 40)
curl -s "https://api.example.com/users?limit=20&offset=40" \
  -H "Authorization: Bearer $TOKEN" | jq '.[].id'

# Автоматическая пагинация (получить ВСЕ записи)
PAGE=0
LIMIT=100
while true; do
  RESPONSE=$(curl -s "https://api.example.com/users?limit=$LIMIT&offset=$((PAGE * LIMIT))")
  COUNT=$(echo "$RESPONSE" | jq 'length')
  [ "$COUNT" -eq 0 ] && break
  echo "$RESPONSE" | jq -r '.[].id'
  PAGE=$((PAGE + 1))
done

# Cursor-based pagination (курсор из предыдущего ответа)
RESPONSE=$(curl -s "https://api.example.com/events?limit=50")
echo "$RESPONSE" | jq -r '.next_cursor'
# → "eyJpZCI6MTIzfQ=="
NEXT_CURSOR=$(echo "$RESPONSE" | jq -r '.next_cursor')
curl -s "https://api.example.com/events?limit=50&after=$NEXT_CURSOR" | jq .

# Filtering (фильтрация по параметрам)
curl -s "https://api.example.com/orders?status=active&created_after=2026-01-01&sort=-created_at" \
  -H "Authorization: Bearer $TOKEN" | jq '.total'

# Filtering с массивом значений
curl -s "https://api.example.com/users?role=admin,operator&status=active" | jq '.[].email'

# Поиск (full-text)
curl -s "https://api.example.com/search?q=database+connection&limit=10" | jq '.results[].title'
```

**Валидация:**
```bash
# Проверка общего количества записей (через заголовок или мета-поле)
curl -sI "https://api.example.com/users?limit=1" | grep -i "x-total-count"
# → X-Total-Count: 1547

# Или через тело ответа
curl -s "https://api.example.com/users?limit=1" | jq '.meta.total'
# → 1547
```

### Сценарий 20: Типичные API-вызовы в инфраструктуре

#### HashiCorp Vault

```bash
# Авторизация (AppRole)
curl -s -X POST https://vault.internal:8200/v1/auth/approle/login \
  -d '{"role_id":"'$ROLE_ID'","secret_id":"'$SECRET_ID'"}' | jq -r '.auth.client_token'
# → s.xxxxxxxx

# Чтение секрета (KV v2)
TOKEN=$(curl -s -X POST https://vault.internal:8200/v1/auth/approle/login \
  -d '{"role_id":"'$ROLE_ID'","secret_id":"'$SECRET_ID'"}' | jq -r '.auth.client_token')
curl -s -H "X-Vault-Token: $TOKEN" \
  https://vault.internal:8200/v1/secret/data/myapp/database | jq '.data.data'
# → {"username":"admin","password":"s3cret"}

# Запись секрета
curl -s -X POST -H "X-Vault-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  https://vault.internal:8200/v1/secret/data/myapp/api \
  -d '{"data":{"api_key":"new-key-123"}}'

# Генерация временного креденшила (Database secret engine)
curl -s -X POST -H "X-Vault-Token: $TOKEN" \
  https://vault.internal:8200/v1/database/creds/my-role | jq '.data'
# → {"username":"v-token-abc123","password":"A1b2-C3d4","ttl":3600}

# Проверка статуса Vault
curl -s https://vault.internal:8200/v1/sys/health | jq '.initialized,.sealed'
```

#### Consul

```bash
# Регистрация сервиса
curl -s -X PUT http://consul.internal:8500/v1/agent/service/register \
  -H "Content-Type: application/json" \
  -d '{
    "ID": "web-1",
    "Name": "web",
    "Tags": ["v2.1.0","production"],
    "Address": "10.0.1.10",
    "Port": 8080,
    "Check": {
      "HTTP": "http://10.0.1.10:8080/health",
      "Interval": "10s",
      "Timeout": "3s"
    }
  }'

# Запрос здоровых инстансов сервиса
curl -s http://consul.internal:8500/v1/health/service/web?passing=true | \
  jq '.[].Service.Address'
# → "10.0.1.10"
# → "10.0.1.11"

# Чтение ключа из KV
curl -s http://consul.internal:8500/v1/kv/config/myapp/database?raw | jq .
# → {"host":"db.internal","port":5432}

# Запись ключа
curl -s -X PUT http://consul.internal:8500/v1/kv/config/myapp/cache_ttl \
  -d '300'

# Блокирующий запрос (long poll — ждёт изменения ключа до 30 сек)
curl -s "http://consul.internal:8500/v1/kv/config/myapp/database?index=12345&wait=30s" | jq '.[0].ModifyIndex'

# DNS-резолвинг сервиса
dig @127.0.0.1 web.service.consul SRV +short
# → 1 10 8080 web-1.node.consul.
```

#### Elasticsearch

```bash
# Проверка кластера
curl -s https://elastic.internal:9200/_cluster/health | jq '{status,cluster_name,number_of_nodes}'
# → {"status":"green","cluster_name":"prod-logs","number_of_nodes":5}

# Поиск документов (POSIX-синтаксис)
curl -s -X GET "https://elastic.internal:9200/logs-*/_search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": {
      "bool": {
        "must": [
          {"match": {"level": "error"}},
          {"range": {"@timestamp": {"gte": "now-1h"}}}
        ]
      }
    },
    "size": 10,
    "sort": [{"@timestamp": {"order": "desc"}}]
  }' | jq '.hits.total.value, .hits.hits[]._source.message'

# Индексация документа
curl -s -X POST "https://elastic.internal:9200/events/_doc" \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "service": "api-gateway",
    "level": "info",
    "message": "Request processed",
    "duration_ms": 42
  }' | jq '.result'
# → "created"

# Агрегация (количество ошибок по сервисам за час)
curl -s -X GET "https://elastic.internal:9200/logs-*/_search" \
  -H "Content-Type: application/json" \
  -d '{
    "size": 0,
    "query": {"bool": {"must": [
      {"term": {"level": "error"}},
      {"range": {"@timestamp": {"gte": "now-1h"}}}
    ]}},
    "aggs": {
      "by_service": {
        "terms": {"field": "service.keyword", "size": 10}
      }
    }
  }' | jq '.aggregations.by_service.buckets[] | {key, doc_count}'

# Шаблон индекса (ILM +rollover)
curl -s -X PUT "https://elastic.internal:9200/_index_template/logs-template" \
  -H "Content-Type: application/json" \
  -d '{
    "index_patterns": ["logs-*"],
    "template": {
      "settings": {
        "number_of_shards": 3,
        "index.lifecycle.name": "logs-policy",
        "index.lifecycle.rollover_alias": "logs"
      }
    }
  }' | jq '.acknowledged'
# → true
```

---

## Дополнительная информация

### 1. Конфигурация через .curlrc

Чтобы не указывать повторяющиеся опции (например, таймауты или User-Agent), используйте файл `~/.curlrc`.

```ini
# Пример ~/.curlrc
--connect-timeout 10
--max-time 30
--fail
--show-error
--user-agent "SRE-Monitoring-Bot/1.2"
```

### 2. Безопасность и передача секретов

**Никогда не передавайте токены в строке команды**, так как они сохраняются в `history` и видны в списке процессов (`ps`).

- **Безопасно:** Чтение данных из stdin или файла:
  ```bash
  curl -X POST -H "Authorization: Bearer $(cat token.txt)" -d @payload.json https://api.io
  ```
- **HSTS:** Начиная с версии 7.74.0, curl поддерживает кэширование политик HSTS (`--hsts hsts-cache.txt`).

### 3. Таймауты и предотвращение зависаний

| Опция | Описание |
| :--- | :--- |
| `--connect-timeout <sec>` | Время на установку TCP-соединения. |
| `--max-time <sec>` | Общее время на всю операцию (включая передачу данных). |
| `--speed-time` / `--speed-limit` | Прервать, если скорость ниже лимита в течение N секунд. |

### 4. Основные коды возврата (Exit Codes)

| Код | Значение | Рекомендация |
| :--- | :--- | :--- |
| **0** | Успех | — |
| **6** | Could not resolve host | Проверить DNS или наличие интернета. |
| **7** | Failed to connect | Проверить порт, firewall или статус сервиса. |
| **22** | HTTP page not retrieved | Возникает при `-f`, если сервер вернул статус >= 400. |
| **28** | Operation timeout | Превышен `--max-time`. Увеличить лимит или проверить задержки. |
| **35** | SSL/TLS connect error | Ошибка рукопожатия. Проверить версии TLS или сертификаты. |
| **52** | Empty reply from server | Сервер закрыл соединение без данных (возможен сбой приложения). |
| **56** | Failure in receiving network data | Соединение разорвано во время приёма данных (reset, таймаут на стороне сервера). |
| **60** | CA certificate or SSL problem | Сертификат сервера не доверен. Проверить `--cacert` или установить корневой сертификат. |
| **67** | Authentication error | Неверные учётные данные (Basic Auth, Digest). Проверить `-u user:pass`. |
| **92** | HTTP/2 stream error | Ошибка потока HTTP/2 (например, RST_STREAM от сервера). Проверить ALPN и конфигурацию сервера. |

### 5. Устранение неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `SSL certificate problem: unable to get local issuer certificate` | Внутренний CA не входит в системный набор сертификатов | `--cacert /path/to/ca.crt` или `--capath /etc/ssl/certs/` |
| `Connection refused` (exit 7) | Сервис не запущен, неверный порт, firewall | Проверить `ss -tlnp \| grep <port>`, статус сервиса, iptables |
| `Could not resolve host` (exit 6) | DNS-сервер недоступен или имя не существует | Проверить `/etc/resolv.conf`, `dig`, `nslookup` |
| `Operation timeout` (exit 28) | Медленный сервер, проблемы с сетью | Увеличить `--max-time`; проверить тайминги через `-w` |
| `HTTP/2 stream 0 was not closed cleanly` (exit 92) | Некорректная реализация HTTP/2 на сервере | Попробовать `--http1.1` для принудительного использования HTTP/1.1 |
| `Connection reset by peer` (exit 56) | Сервер разорвал соединение (firewall, IDS, crash) | Проверить серверные логи; попробовать другой IP через `--resolve` |
| `GnuTLS recv error` / `SSL_read` | Несовместимость версий TLS, проблемы с SNI | Указать `--tls-max 1.2` или `--tlsv1.3`; проверить `openssl s_client` |
| `No such file or directory` при `--cert` или `--key` | Неверный путь к файлам сертификата | Проверить права доступа и пути; файлы должны быть PEM-формата |
| `Unsupported protocol` | Запрошенный протокол не поддерживается в сборке | Проверить `curl --version` → строка `Protocols:` |

### 6. Граничные случаи и особенности поведения

**Потоковые ответы (Server-Sent Events, NDJSON):**

```bash
# Стриминг SSE (Server-Sent Events) — без буферизации
curl -N -H "Accept: text/event-stream" https://api.example.com/events
# -N (--no-buffer): отключает буферизацию вывода, данные поступают в реальном времени

# NDJSON (Newline Delimited JSON) — построчное чтение
curl -s --raw https://api.example.com/stream | while IFS= read -r line; do
  echo "$line" | jq .
done
```

**Загрузка очень больших файлов (>4GB):**

```bash
# Кодировка длины контента: при --data-binary @largefile curl автоматически
# определяет размер. Для файлов >4GB может потребоваться 64-битная сборка curl.
# Прогресс-бар: по умолчанию выводится в stderr
curl -T largefile.zip https://storage.example.com/upload --progress-bar
# Или подавить прогресс и показать только итог
curl -T largefile.zip https://storage.example.com/upload -s -w "Uploaded: %{size_upload} bytes\n"
```

**Keep-Alive и повторное использование соединений:**

```bash
# Keep-Alive (включен по умолчанию для HTTP/1.1+)
# Управление временем жизни соединения
curl --keepalive-time 60 https://api.example.com
# Соединение будет держаться 60 секунд после последнего запроса

# HTTP/1.0: Keep-Alive не поддерживается по умолчанию
# Для HTTP/1.0 серверов: добавить заголовок вручную
curl -H "Connection: keep-alive" --http1.0 https://old-api.example.com
```

**Привязка к сетевому интерфейсу:**

```bash
# Привязка к конкретному интерфейсу (multi-homed серверы)
curl --interface eth1 https://api.example.com
# Или по имени интерфейса
curl --interface tun0 https://internal.service.corp/api
```

**IPv4 vs IPv6:**

```bash
# Принудительный IPv4 (при проблемах с DNS AAAA-записями)
curl -4 https://api.example.com

# Принудительный IPv6
curl -6 https://api.example.com

# Тест: какой адрес будет использован
curl -v --connect-timeout 3 https://api.example.com 2>&1 | grep "Connected to"
# → Connected to api.example.com (1.2.3.4) port 443
```

### 7. Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie.
- **[Диагностика задержек curl](../../../Diagnostics/Networking/curl_network_diagnostics.md)** — глубокий анализ производительности.
- **[Инструменты диагностики сети](../../network_diagnostics_tools.md)** — контекст применения в траблшутинге.
- **[Методы HTTP](../../../../Networking/Protocols/HTTP/http_methods.md)** — описание семантики методов.
- **[REST API](../../../../Networking/Protocols/HTTP/http_rest_api.md)** — проектирование REST API, пагинация, HATEOAS.
- **[Rate Limiting и устойчивость](../../../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — 429, Retry-After, circuit breaker, exponential backoff.
- **[Connection Pooling](../../../../Networking/Concepts/connection_pooling.md)** — переиспользование соединений, TCP keepalive vs HTTP keep-alive.
- **[HTTP-кэширование](../../../../Networking/Protocols/HTTP/http_caching.md)** — ETag, Cache-Control, условные запросы через curl.
