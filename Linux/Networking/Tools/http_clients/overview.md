# Обзор HTTP-клиентов в Linux

## Определения

**HTTP-клиент командной строки** — специализированная утилита для формирования и отправки сетевых запросов (HTTP/HTTPS, gRPC) и анализа ответов непосредственно из терминала. В экосистеме DevOps и SRE эти инструменты выполняют следующие задачи:
- Тестирование и отладка REST, gRPC и GraphQL API.
- Автоматизация задач в CI/CD пайплайнах (деплой, уведомления).
- Рекурсивная загрузка файлов и создание зеркал ресурсов.
- Проверка доступности (Healthchecks) и диагностика задержек на разных уровнях (DNS, TCP, TLS).

## Предварительные требования

### Установка по дистрибутивам

| Инструмент | Debian/Ubuntu | RHEL/CentOS/Rocky | Alpine | macOS | pip |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **curl** | `apt install curl` | `dnf install curl` | `apk add curl` | `brew install curl` | — |
| **wget** | `apt install wget` | `dnf install wget` | `apk add wget` | `brew install wget` | — |
| **httpie** | `apt install httpie` | `dnf install httpie` | `apk add --no-cache httpie` | `brew install httpie` | `pip install httpie` |
| **xh** | `apt install xh` | `dnf install xh` | `apk add --no-cache xh` | `brew install xh` | `cargo install xh` |

### Минимальные версии и зависимости

| Инструмент | Минимальная версия | Зависимости |
| :--- | :--- | :--- |
| **curl** | 7.28+ | libcurl, OpenSSL/GnuTLS |
| **wget** | 1.14+ | libssl, libpsl (для HTTPS) |
| **httpie** | 3.0+ | Python 3.7+, pip |
| **xh** | 0.16+ | Нет (бинарный файл) |

### BusyBox и Alpine-образы

BusyBox (стандартный в Alpine и минимальных контейнерах) содержит урезанную версию wget **без поддержки HTTPS**. Для полной функциональности:

```bash
# Alpine: установка полного wget (с HTTPS)
apk add --no-cache wget

# Проверка: BusyBox wget не поддерживает --https-only
wget --help 2>&1 | grep -q "https-only" && echo "Полная версия" || echo "BusyBox (без HTTPS)"
```

> **Для healthcheck в Docker-образах:** Используйте `curl` или `wget` из полных пакетов, а не BusyBox. Если это невозможно — используйте `curl` (есть в большинстве образов) или напишите кастомный healthcheck на Python/Go.

## Основные концепции

### Базовый стек инструментов

В стандартный набор системного инженера входят три проверенных решения, каждое из которых оптимизировано под свой рабочий процесс:

| Инструмент | Основная специализация | Поддерживаемые протоколы |
| :--- | :--- | :--- |
| **[wget](./wget.md)** | Автономная загрузка и зеркалирование | HTTP(S), FTP, HTTP/2 (в wget2) |
| **[curl](./curl.md)** | Универсальный транспорт для API и скриптов | HTTP(S), gRPC, FTP, SCP, LDAP, MQTT |
| **[httpie](./httpie.md)** | Интерактивная разработка (Human-friendly) | HTTP(S) |

### Сравнительный анализ возможностей

| Характеристика | Wget | cURL | HTTPie | xh |
| :--- | :--- | :--- | :--- | :--- |
| **Подход** | Пакетная обработка (Batch) | Универсальный интерфейс (Library-first) | Удобство пользователя (UX-first) | Удобство + скорость (Rust) |
| **Работа с JSON** | Требует ручной сборки строки | Через заголовки и флаг `-d` | Нативная поддержка (`key=val`) | Нативная поддержка (`key=val`) |
| **Визуализация** | Прогресс-бар в stderr | Необработанный поток (Raw) | Подсветка синтаксиса, форматирование | Подсветка синтаксиса, форматирование |
| **Обработка ошибок** | Ненулевой код при 4xx/5xx | Успех (0) по умолчанию (нужен `-f`) | Ошибка (4) при 4xx/5xx | Ошибка при 4xx/5xx |
| **HTTP-ошибки (по умолчанию)** | Возвращает код ошибки | Возвращает 0 даже при 500 | Возвращает ненулевой код | Возвращает ненулевой код |
| **Повторные попытки** | `--tries`, `--waitretry` | `--retry`, `--retry-delay` | Нет встроенной поддержки | `--retry`, `--retry-delay` |
| **SOCKS-прокси** | Нет | `--socks4a`, `--socks5` | Через переменные окружения | Через переменные окружения |
| **IPv6** | Автоматически | `--ipv6` или `[::1]` | Автоматически | Автоматически |
| **Keep-Alive** | Нет | `-` (по умолчанию для HTTP/1.1+) | Да (HTTP/1.1+) | Да (HTTP/1.1+) |
| **Параллелизм** | Нет (в wget2 — да) | Нет (требуется xargs/parallel) | Нет | Нет |
| **Скриптинг** | Отлично для скачивания сайтов | Отраслевой стандарт для автоматизации | Не рекомендуется (зависимость от Python) | Рекомендуется (бинарный файл) |
| **Среда выполнения** | Минимальные зависимости | Минимальные зависимости | Требует Python | Минимальные зависимости |

### Современные высокопроизводительные альтернативы

Инструменты на базе Rust и Go обеспечивают скорость curl при удобстве интерфейса HTTPie:

- **xh**: Написан на Rust. Самая быстрая альтернатива HTTPie, полностью совместимая по синтаксису, но работающая как единый бинарный файл без внешних зависимостей.
- **curlie**: Написан на Go. Обертка над curl, которая добавляет форматирование вывода в стиле HTTPie, сохраняя возможность использовать все флаги и мощь curl.
- **grpcurl**: Специализированный инструмент для взаимодействия с gRPC серверами. Позволяет вызывать методы gRPC так же просто, как curl вызывает HTTP-методы.

### Поддержка современных протоколов (HTTP/2 и HTTP/3)

- **HTTP/2**: Поддерживается всеми современными версиями curl и wget2. Позволяет мультиплексировать запросы в одном TCP-соединении.
- **HTTP/3 (QUIC)**: Требует специальной сборки curl (с поддержкой библиотек ngtcp2 или quiche). Обеспечивает устойчивость к потерям пакетов в нестабильных сетях.

## Практические сценарии

### Выбор инструмента под задачу

1. **Использование `wget` оправдано, когда:**
   - Требуется рекурсивное скачивание (зеркалирование) сайта (`wget -r`).
   - Необходимо продолжение прерванной загрузки (флаг `-c`).
   - Загрузка должна выполняться в фоновом режиме без активной сессии пользователя.

2. **Использование `curl` необходимо, когда:**
   - Пишется переносимый bash-скрипт или шаг в CI/CD (curl есть почти в каждом Docker-образе).
   - Нужна прецизионная диагностика таймингов запроса (см. [Диагностика HTTP-задержек](../../../Diagnostics/Networking/curl_network_diagnostics.md)).
   - Требуется использование специфических аутентификаций (OAuth2, Kerberos) или протоколов (SFTP, gRPC).

3. **Использование `httpie` или `xh` эффективно, когда:**
   - Выполняется ручное исследование API.
   - Нужно быстро отправить POST-запрос с вложенными JSON-структурами без экранирования кавычек в терминале.

### Примеры синтаксиса для типовых операций

**Отправка POST-запроса с JSON-телом:**
```bash
# curl (требует явного указания заголовков)
curl -f -X POST -H 'Content-Type: application/json' -d '{"user_id":42, "status":"active"}' https://api.example.com/v1/users

# httpie / xh (автоматически определяет JSON и формирует тело)
http POST https://api.example.com/v1/users user_id:=42 status=active
```

**Проверка работоспособности сервиса (Healthcheck):**
```bash
# curl (обязателен флаг -f для корректного кода возврата в скриптах)
curl -fsS https://api.example.com/health || exit 1

# wget (режим --spider проверяет только существование ресурса)
wget --spider -q https://api.example.com/health
```

**Проверка SSL-сертификата:**
```bash
# curl (получение информации о сертификате)
curl -vI https://api.example.com 2>&1 | grep -E "expire|subject|issuer"

# openssl (проверка даты истечения)
echo | openssl s_client -connect api.example.com:443 2>/dev/null | openssl x509 -noout -dates

# wget (проверка сертификата с указанием CA)
wget --ca-certificate=/etc/ssl/certs/ca-certificates.crt https://api.example.com -O /dev/null
```

**Скачивание с аутентификацией:**
```bash
# curl (Basic Auth)
curl -u admin:password https://api.example.com/backup/db.sql -o backup.sql

# curl (Bearer Token)
curl -H "Authorization: Bearer $TOKEN" https://api.example.com/data -o data.json

# wget (Basic Auth)
wget --user=admin --password=password https://api.example.com/backup/db.sql

# httpie (Basic Auth)
http -a admin:password https://api.example.com/backup/db.sql
```

**Контроль полосы пропускания и ретраи:**
```bash
# wget (ограничение скорости + повторные попытки)
wget --limit-rate=1m --tries=3 --waitretry=5 https://large-file.example.com/data.tar.gz

# curl (ограничение скорости + повторные попытки)
curl --limit-rate 1M --retry 3 --retry-delay 5 https://large-file.example.com/data.tar.gz -o data.tar.gz
```

**Пакетные запросы:**
```bash
# curl (массовая проверка эндпоинтов)
for endpoint in users posts comments; do
  curl -fsS "https://api.example.com/$endpoint" >/dev/null && echo "$endpoint: OK" || echo "$endpoint: FAIL"
done

# httpie (массовая проверка)
for endpoint in users posts comments; do
  http -b --check-status "https://api.example.com/$endpoint" >/dev/null && echo "$endpoint: OK" || echo "$endpoint: FAIL"
done
```

### DevOps-сценарии: Docker, Kubernetes, systemd

#### Healthcheck в Dockerfile

```dockerfile
# Вариант 1: curl (рекомендуется — есть в большинстве образов)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -fsS http://localhost:8080/health || exit 1

# Вариант 2: wget (только полная версия, НЕ BusyBox)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget -q --spider http://localhost:8080/health || exit 1

# Вариант 3: custom script (если curl/wget недоступны)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1
```

> **CMD vs CMD-SHELL:** `CMD ["curl", ...]` не работает с pipe (`|`). Используйте `CMD curl ... || exit 1` или `CMD ["/bin/sh", "-c", "curl ... || exit 1"]`.

#### Healthcheck в docker-compose.yml

```yaml
services:
  api:
    image: my-api:latest
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
```

#### Healthcheck в Kubernetes

```yaml
apiVersion: v1
kind: Pod
spec:
  containers:
    - name: api
      image: my-api:latest
      livenessProbe:
        httpGet:
          path: /health
          port: 8080
        initialDelaySeconds: 10
        periodSeconds: 30
        timeoutSeconds: 5
        failureThreshold: 3
      readinessProbe:
        httpGet:
          path: /ready
          port: 8080
        initialDelaySeconds: 5
        periodSeconds: 10
        timeoutSeconds: 3
      startupProbe:
        httpGet:
          path: /health
          port: 8080
        failureThreshold: 30
        periodSeconds: 10
```

#### Скачивание зависимостей при сборке образа

```dockerfile
# wget для скачивания артефактов (с ретраями)
RUN wget --tries=3 --waitretry=5 \
    https://releases.example.com/app-v1.2.3.tar.gz -O /tmp/app.tar.gz && \
    tar -xzf /tmp/app.tar.gz -C /opt/ && \
    rm /tmp/app.tar.gz

# curl для скачивания и распаковки за одну команду
RUN curl -fsSL https://releases.example.com/app-v1.2.3.tar.gz | tar -xz -C /opt/
```

#### Интеграция с systemd

```ini
# /etc/systemd/system/app-check.service
[Unit]
Description=Pre-start health check for API
After=network.target

[Service]
Type=oneshot
ExecStartPre=/usr/bin/curl -fsS http://localhost:8080/health
ExecStart=/usr/bin/systemctl start app

[Install]
WantedBy=multi-user.target
```

```bash
# Проверка перед деплоем (в скрипте)
#!/bin/bash
set -e

echo "Waiting for service to become healthy..."
for i in $(seq 1 30); do
  if curl -fsS http://localhost:8080/health >/dev/null 2>&1; then
    echo "Service is healthy after ${i}s"
    exit 0
  fi
  sleep 1
done

echo "Service failed to become healthy after 30s"
exit 1
```

## Дополнительная информация

### Устранение неисправностей

| Симптом | Инструмент | Вероятная причина | Решение |
| :--- | :--- | :--- | :--- |
| `curl: (6) Could not resolve host` | curl | DNS не настроен или недоступен | Проверить `/etc/resolv.conf`, `dig`, `nslookup` |
| `curl: (7) Failed to connect` | curl | Сервис не запущен или неверный порт | `ss -tlnp`, проверить статус сервиса |
| `curl: (35) SSL connect error` | curl | Проблема с SSL/TLS | `--tlsv1.2`, обновить OpenSSL, `--insecure` (dev only) |
| `curl: (28) Operation timed out` | curl | Слишком долгий ответ сервера | Увеличить `--timeout=60`, проверить сеть |
| `wget: unable to resolve host` | wget | DNS не настроен | Проверить DNS-резолвер |
| `wget: ERROR: SSL certificate problem` | wget | Самоподписанный сертификат | `--no-check-certificate` (dev) или `--ca-certificate` |
| `httpie: ModuleNotFoundError` | httpie | Python окружение не настроено | `pip install httpie`, проверить `python3 --version` |
| `xh: command not found` | xh | Утилита не установлена | `apt install xh` или `cargo install xh` |

### Граничные случаи

**Файлы >4GB:**
```bash
# wget (корректно обрабатывает файлы >4GB)
wget https://example.com/large-backup.tar.gz

# curl (ограничение: 32-bit off_t на 32-bit системах)
curl https://example.com/large-backup.tar.gz -o large-backup.tar.gz
# На 32-bit системах использовать wget или полную версию curl с --enable-ares
```

**Работа через прокси:**
```bash
# curl (нативная поддержка прокси)
curl --proxy http://proxy.corp:8080 https://api.example.com/data
curl --proxy socks5://proxy.corp:1080 https://api.example.com/data

# wget (через переменные окружения)
export http_proxy=http://proxy.corp:8080
wget https://example.com/file.zip

# httpie (через переменные окружения)
export https_proxy=http://proxy.corp:8080
http api.example.com/users
```

**IPv6-соединения:**
```bash
# curl (явное указание IPv6)
curl -6 http://[::1]:8080/health

# curl (предпочтение IPv6)
curl --ipv6 https://api.example.com/users

# wget (автоматически)
wget http://[::1]:8080/health
```

**Keep-Alive и повторное использование соединений:**
```bash
# curl (Keep-Alive включен по умолчанию для HTTP/1.1+)
# Для отключения: --no-keepalive
curl https://api.example.com/users

# wget (не поддерживает Keep-Alive)
# Каждый запрос создает новое TCP-соединение
```

### Рекомендации по безопасности

1.  **Защита секретов**: Категорически запрещено передавать API-ключи, токены или пароли непосредственно в строке команды (флаги `-H 'Authorization: Bearer ...'`). Эти данные сохраняются в `history` оболочки и видны в списке процессов (`ps`).
    - **Решение**: Используйте переменные окружения, файлы конфигурации (`.netrc`) или чтение данных из файлов/stdin (флаг `@file` в curl).
2.  **Проверка сертификатов**: Никогда не используйте `-k` (curl) или `--no-check-certificate` (wget) в Production-скриптах. Это отключает проверку подлинности сервера и делает соединение уязвимым для MitM-атак.
3.  **Обработка ошибок в пайплайнах**: В скриптах всегда используйте `set -e` и проверяйте коды возврата. Помните, что по умолчанию curl возвращает `0` (успех), даже если сервер ответил `500 Internal Server Error` (исправляется флагом `--fail`).

### Полезные ресурсы для отладки

- **[httpbin.org](https://httpbin.org)**: Универсальный эндпоинт для тестирования любых типов запросов, заголовков и методов аутентификации.
- **[badssl.com](https://badssl.com)**: Набор поддоменов с некорректными SSL-конфигурациями для проверки устойчивости клиентов к проблемам безопасности.

### Связанные заметки

- **[cURL — универсальный инструмент](./curl.md)** — глубокое погружение в возможности curl (включая GraphQL, WebSocket, Vault/Consul/Elasticsearch API).
- **[Wget — скачивание и зеркалирование](./wget.md)** — сценарии рекурсивной загрузки.
- **[HTTPie — интерактивная отладка](./httpie.md)** — детальный UX справочник.
- **[Инструменты диагностики сети](../../network_diagnostics_tools.md)** — обзор L3/L4 инструментов.
- **[Жизненный цикл веб-запроса](../../../../Networking/Concepts/web_request_lifecycle.md)** — теоретическая база работы HTTP.
- **[Rate Limiting и устойчивость](../../../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — 429, Retry-After, circuit breaker, exponential backoff, jitter.
- **[Connection Pooling](../../../../Networking/Concepts/connection_pooling.md)** — переиспользование соединений, TCP keepalive vs HTTP keep-alive, pgBouncer.
- **[HTTP-кэширование](../../../../Networking/Protocols/HTTP/http_caching.md)** — ETag, Cache-Control, условные запросы.
- **[REST API](../../../../Networking/Protocols/HTTP/http_rest_api.md)** — проектирование API, пагинация, HATEOAS, RFC 9457.
