# Blackbox Exporter — Конфигурация модулей

## Определения

**Конфигурационный файл** `blackbox.yml` — основной файл настроек Blackbox Exporter, содержащий секцию `modules`. В ней определяются параметры сетевых проверок и критерии их успешности.

*   **Модуль** — именованный набор настроек, описывающий конкретный тип проверки (**prober**) и её ожидаемое поведение.
*   **Prober** — исполнитель проверки (HTTP, TCP, ICMP, DNS, gRPC, Unix).
*   **CEL (Common Expression Language)** — язык выражений для сложной валидации данных (v0.25.0+).
*   **Актуальная версия:** `v0.28.0` (2025/2026).
*   **Lifecycle конфигурации:** порядок загрузки `blackbox.yml` при старте экспортера, автоматическая перезагрузка при изменении файла (`--config.enable-auto-reload`), валидация перед применением.
*   **Параметры уровня модуля:** `prober`, `timeout`, `preferred_ip_protocol`, `ip_protocol_fallback` — применяются ко всей проверке.
*   **Параметры уровня протокола:** вложенные секции (`http:`, `tcp:`, `dns:` и т.д.) — специфичны для каждого prober.

**См. также:** [Обзор и концепции](./blackbox_exporter_overview.md), [Установка и настройка](./blackbox_exporter_installation_and_setup.md), [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md).

## Основные концепции

### Жизненный цикл конфигурации

При старте Blackbox Exporter загружает `blackbox.yml`, парсит секцию `modules` и строит внутренний реестр доступных проверок. При каждом запросе `/probe` экспортер ищет модуль по имени из параметра `module`. При использовании флага `--config.enable-auto-reload` экспортер отслеживает изменения файла и перезагружает конфигурацию без перезапуска процесса. Ошибки синтаксиса в `blackbox.yml` логируются, но не приводят к падению экспортера в auto-reload режиме, что позволяет избежать прерывания проверок при некорректных правках.

### Архитектура конфигурации

```yaml
modules:
  module_name:
    prober: http|tcp|icmp|dns|grpc|unix
    timeout: 5s
    preferred_ip_protocol: "ip4"|"ip6"
    ip_protocol_fallback: true|false
    http: ...        # только для prober: http
    tcp: ...         # только для prober: tcp
    icmp: ...        # только для prober: icmp
    dns: ...         # только для prober: dns
    grpc: ...        # только для prober: grpc
    unix: ...        # только для prober: unix
```

### Общая структура модуля

Каждый модуль определяет используемый пробер, таймаут и стратегию выбора IP-протокола.

```yaml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [200]
      preferred_ip_protocol: "ip4"
      ip_protocol_fallback: true # Откат на IPv6 при недоступности IPv4
```

### Доступные типы проверок (Probers)

1.  **http** — опрос по протоколам HTTP/1.1, HTTP/2 и HTTP/3 (QUIC).
2.  **tcp** — проверка доступности портов и сложные сценарии обмена данными («запрос-ответ»).
3.  **icmp** — сетевая проверка доступности (Ping) на уровне L3.
4.  **dns** — проверка разрешения имен, включая DNS over TLS (DoT).
5.  **grpc** — проверка работоспособности сервисов gRPC Health Check.
6.  **unix** — проверка сервисов через локальные Unix Domain Sockets (v0.28.0+).

## Практические сценарии

### Полный multi-module шаблон

```yaml
# /etc/blackbox_exporter/blackbox.yml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200]
      method: GET
      preferred_ip_protocol: "ip4"
      ip_protocol_fallback: true

  tcp_connect:
    prober: tcp
    timeout: 3s
    tcp:
      preferred_ip_protocol: "ip4"

  dns_udp:
    prober: dns
    timeout: 5s
    dns:
      transport_protocol: "udp"
      query_name: "example.com"
      query_type: "A"
      valid_rcodes:
        - NOERROR
        - NXDOMAIN

  icmp_ping:
    prober: icmp
    timeout: 3s
    icmp:
      preferred_ip_protocol: "ip4"
      ip_protocol_fallback: true

  grpc_health:
    prober: grpc
    timeout: 5s
    grpc:
      service: "grpc.health.v1.Health"

  unix_socket:
    prober: unix
    timeout: 2s
    unix:
      protocol: unix
      query_response:
        - send: "PING"
        - expect: "PONG"
```

### Интеграция с Prometheus scrape и relabeling

Blackbox Exporter использует паттерн multi-target: один инстанс проверяет множество целей, переданных через параметр `target` в запросе `/probe`. Для корректного сопоставления модуля и цели используются `params` и `relabel_configs`.

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'blackbox-http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - http://app.example.com/health
        - http://api.example.com/ready
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: blackbox-exporter.monitoring.svc:9115 # адрес инстанса экспортера

  - job_name: 'blackbox-tcp'
    metrics_path: /probe
    params:
      module: [tcp_connect]
    static_configs:
      - targets:
        - db.example.com:5432
        - redis.example.com:6379
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: blackbox-exporter.monitoring.svc:9115
```

### Проверки HTTP/HTTPS

**Базовая проверка на статус-код 200 OK:**
```yaml
modules:
  http_2xx:
    prober: http
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200]
      method: GET
      preferred_ip_protocol: "ip4"
      ip_protocol_fallback: true
```

**Аутентификация и OAuth2 (v0.25.0+):**
```yaml
modules:
  http_auth_complex:
    prober: http
    http:
      basic_auth:
        username: "admin"
        password: "password123"
      oauth2:
        client_id: "blackbox-client"
        client_secret: "secret-key"
        token_url: "https://auth.example.com/token"
        scopes: ["read", "write"]
```

**Кастомные заголовки и сжатие (v0.28.0+):**
```yaml
modules:
  http_custom_headers:
    prober: http
    http:
      headers:
        Accept: "application/json"
        X-Custom-Header: "value"
      compression: "gzip"
      follow_redirects: true
```

**Валидация тела ответа через regexp:**
```yaml
modules:
  http_body_regexp:
    prober: http
    http:
      fail_if_body_matches_regexp:
        - "error"
        - "maintenance"
      fail_if_body_not_matches_regexp:
        - "status:ok"
```

**Валидация JSON через CEL (v0.28.0+):**
CEL позволяет выполнять логические проверки структуры ответа без использования регулярных выражений.
```yaml
modules:
  http_json_cel:
    prober: http
    http:
      method: GET
      fail_if_body_json_matches_cel:
        - "obj.status == 'MAINTENANCE'"
      fail_if_body_json_not_matches_cel:
        - "obj.version.startsWith('v2') && obj.active == true"
```

**Проверка SSL/TLS сертификата и SNI:**
```yaml
modules:
  https_ssl_expiry:
    prober: http
    http:
      tls_config:
        insecure_skip_verify: false
        server_name: "example.com"
      fail_if_not_ssl: true
      fail_if_cert_not_expiry_after: 2592000s # 30 дней в секундах
```

**HTTP/3 (QUIC) — v0.28.0+:**
```yaml
modules:
  http3_check:
    prober: http
    http:
      enable_http3: true
      preferred_ip_protocol: "ip4"
```

### Проверки TCP

**Проверка SSH баннера:**
```yaml
modules:
  tcp_ssh:
    prober: tcp
    tcp:
      query_response:
        - expect: "^SSH-2.0-"
```

**Проверка SMTP (Сценарий «Запрос-Ответ»):**
```yaml
modules:
  tcp_smtp:
    prober: tcp
    tcp:
      query_response:
        - expect: "^220"
        - send: "EHLO blackbox_exporter"
        - expect: "^250"
        - send: "QUIT"
```

**STARTTLS сценарий (IMAP/POP3/SMTP):**
```yaml
modules:
  tcp_starttls:
    prober: tcp
    tcp:
      starttls: true
      query_response:
        - expect: "^220"
        - send: "EHLO blackbox_exporter"
        - expect: "^250 STARTTLS"
```

**Использование исходного IP-адреса:**
```yaml
modules:
  tcp_source_ip:
    prober: tcp
    tcp:
      source_ip_address: "10.0.0.5"
      query_response:
        - expect: "^220"
```

**Проверка с использованием байтовых последовательностей (v0.25.0+):**
```yaml
modules:
  tcp_binary:
    prober: tcp
    tcp:
      query_response:
        - send: "PING"
        - expect_bytes: [0x50, 0x4f, 0x4e, 0x47]
```

### Проверки ICMP (Ping)

```yaml
modules:
  icmp_ping:
    prober: icmp
    icmp:
      preferred_ip_protocol: "ip4"
      ip_protocol_fallback: true
      dont_fragment: true
      payload_size: 56
      source_ip_address: "10.0.0.10"
```

**Примечание:** Для работы ICMP без root выполните `setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter`. В контейнере добавьте capability `NET_RAW`.

### Проверки DNS

**Базовая проверка UDP:**
```yaml
modules:
  dns_udp:
    prober: dns
    dns:
      transport_protocol: "udp"
      query_name: "example.com"
      query_type: "A"
      valid_rcodes:
        - NOERROR
        - NXDOMAIN
      preferred_ip_protocol: "ip4"
```

**DNS over TLS (DoT):**
```yaml
modules:
  dns_over_tls:
    prober: dns
    dns:
      transport_protocol: "tcp"
      dns_over_tls: true
      query_name: "prometheus.io"
      query_type: "A"
      tls_config:
        insecure_skip_verify: false
      valid_rcodes:
        - NOERROR
```

**Проверка MX-записей и валидация ответа:**
```yaml
modules:
  dns_mx_check:
    prober: dns
    dns:
      query_name: "gmail.com"
      query_type: "MX"
      validate_answer_rrs:
        fail_if_matches_regexp: [".*NXDOMAIN.*"]
```

**Валидация ответа по регулярному выражению:**
```yaml
modules:
  dns_validate:
    prober: dns
    dns:
      query_name: "example.com"
      query_type: "A"
      validate_answer_rrs:
        fail_if_matches_regexp: ["^$"] # ошибка, если ответ пустой
        fail_if_not_matches_regexp: ["^\\d+\\.\\d+\\.\\d+\\.\\d+$"] # ожидается IPv4
```

### Проверки gRPC

**gRPC Health Check с метаданными (v0.28.0+):**
```yaml
modules:
  grpc_health_auth:
    prober: grpc
    grpc:
      service: "grpc.health.v1.Health"
      metadata:
        authorization: "Bearer secret-token"
        x-client-id: "blackbox-exporter"
      tls: true
```

**gRPC Health Check с TLS и client certs:**
```yaml
modules:
  grpc_health_tls:
    prober: grpc
    grpc:
      service: "grpc.health.v1.Health"
      tls: true
      tls_config:
        ca_file: "/etc/blackbox_exporter/ca.crt"
        cert_file: "/etc/blackbox_exporter/client.crt"
        key_file: "/etc/blackbox_exporter/client.key"
        insecure_skip_verify: false
```

### Проверки Unix Domain Sockets (v0.28.0+)

```yaml
modules:
  unix_socket:
    prober: unix
    unix:
      protocol: unix # варианты: unix, unixgram, unixpacket
      query_response:
        - send: "PING"
        - expect: "PONG"
```
*Примечание: В качестве target в Prometheus указывается абсолютный путь к сокету: `target: "/var/run/docker.sock"`.*

## Валидация и отладка конфигурации

### Предварительная валидация YAML

Перед применением изменений проверьте синтаксис `blackbox.yml`:
```bash
# Проверка синтаксиса YAML
python3 -c "import yaml; yaml.safe_load(open('/etc/blackbox_exporter/blackbox.yml'))"

# Проверка через promtool (если установлен Prometheus)
promtool check rules /etc/prometheus/rules/*.yml
```

### Dry-run и тестовый запуск экспортера

```bash
# Запуск экспортера в фоне для тестирования конфигурации
./blackbox_exporter --config.file=/etc/blackbox_exporter/blackbox.yml --config.enable-auto-reload &
EXPORTER_PID=$!

# Проверка модуля через curl
curl "http://localhost:9115/probe?target=http://example.com&module=http_2xx"
curl "http://localhost:9115/probe?target=db.example.com:5432&module=tcp_connect"
curl "http://localhost:9115/probe?target=example.com&module=dns_udp"

# Проверка метрик экспортера
curl "http://localhost:9115/metrics" | grep blackbox_exporter_

# Остановка тестового процесса
kill $EXPORTER_PID
```

### Диагностика через логи

```bash
# Запуск с debug-логированием
./blackbox_exporter --config.file=/etc/blackbox_exporter/blackbox.yml --log.level=debug

# Просмотр логов systemd
journalctl -u blackbox_exporter -f

# Проверка статуса reload конфигурации
systemctl status blackbox_exporter
```

## Производительность и ограничения

*   **Масштабирование:** Один инстанс Blackbox Exporter может обслуживать тысячи целей, но при росте количества модулей и частоты проверок рекомендуется ограничивать частоту до 1-2 проверок в секунду на один модуль.
*   **Параллелизм:** Экспортер обрабатывает проверки параллельно. Убедитесь, что `ulimit -n` (открытые файлы) достаточен для одновременных TCP-соединений.
*   **Таймауты:** `timeout` в модуле должен быть меньше `scrape_timeout` в Prometheus на 500мс-1с. Рекомендуемые значения: HTTP — 5с, TCP — 3с, ICMP — 3с, DNS — 5с.
*   **Ресурсы:** При нагрузке до 500 проверок в минуту ожидаемое потребление — CPU 100-300m, RAM 64-128Mi.
*   **ICMP ограничения:** Многие операционные системы и сетевые экраны ограничивают частоту ICMP-запросов. Используйте `payload_size` с осторожностью на каналах с низким MTU.

### Edge cases и известные ограничения

*   **ICMP и фаерволлы:** На уровне хоста или сети ICMP часто блокируется. Для проверки доступности хоста используйте TCP-проверки на порт 80 или 443.
*   **HTTP/3 (QUIC):** Поддержка HTTP/3 требует, чтобы целевой сервер поддерживал протокол QUIC (обычно на порту 443/UDP). Если сервер не поддерживает QUIC, экспортер автоматически откатится на HTTP/2.
*   **DNS-резолвинг:** Blackbox Exporter использует системный резолвер. Для проверки конкретных DNS-серверов укажите их в `static_configs` Prometheus и передавайте в `target` IP-адрес резолвера.
*   **Unix сокеты:** Проверка Unix Domain Sockets работает только при запуске экспортера на том же хосте, что и целевой сокет. Для распределённых проверок используйте Node Exporter и текстовая коллекция.
*   **gRPC без стандартного Health Check:** Если целевой сервис не реализует `grpc.health.v1.Health`, необходимо создать кастомный модуль с CEL-валидацией ответа или использовать TCP-проверку на порт gRPC.

## Дополнительная информация

### Справочник параметров

#### Параметры уровня модуля

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `prober` | string | Тип проверки: `http`, `tcp`, `icmp`, `dns`, `grpc`, `unix`. |
| `timeout` | duration | Максимальное время выполнения проверки. Должно быть меньше `scrape_timeout` в Prometheus. |
| `preferred_ip_protocol` | string | Приоритет IP-протокола: `ip4` или `ip6`. |
| `ip_protocol_fallback` | bool | Разрешить откат на альтернативный IP-протокол при недоступности предпочтительного (по умолчанию `true`). |

#### Параметры HTTP

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `method` | string | HTTP-метод (`GET`, `POST`, `HEAD`, `PUT`, `DELETE`). |
| `headers` | map | Статические заголовки запроса. |
| `valid_status_codes` | list[int] | Список допустимых статус-кодов (по умолчанию `[2xx]`). |
| `valid_http_versions` | list[string] | Допустимые версии HTTP (`HTTP/1.1`, `HTTP/2.0`, `HTTP/3.0`). |
| `follow_redirects` | bool | Следовать перенаправлениям (по умолчанию `true`). |
| `compression` | string | Алгоритм сжатия (`gzip`, `br`, `deflate`). |
| `basic_auth` | object | Basic Auth: `username`, `password`. |
| `oauth2` | object | OAuth2: `client_id`, `client_secret`, `token_url`, `scopes`. |
| `fail_if_body_matches_regexp` | list[string] | Ошибка при совпадении тела с регулярным выражением. |
| `fail_if_body_not_matches_regexp` | list[string] | Ошибка, если тело НЕ совпадает с регулярным выражением. |
| `fail_if_body_json_matches_cel` | list[string] | Валидация JSON через CEL (v0.28.0+). |
| `fail_if_body_json_not_matches_cel` | list[string] | Валидация JSON через CEL — ошибка при несовпадении (v0.28.0+). |
| `fail_if_not_ssl` | bool | Ошибка, если соединение не использует TLS. |
| `fail_if_cert_not_expiry_after` | duration | Ошибка, если сертификат истечёт раньше указанного срока. |
| `tls_config` | object | Настройки TLS (`ca_file`, `cert_file`, `key_file`, `server_name`, `insecure_skip_verify`). |
| `enable_http3` | bool | Использовать HTTP/3 (QUIC). |

#### Параметры TCP

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `query_response` | list[obj] | Сценарий обмена данными (`send`, `expect`, `expect_bytes`). |
| `tls` | bool | Использовать TLS после установления соединения. |
| `starttls` | bool | Инициировать процедуру STARTTLS (например, для SMTP/IMAP). |
| `source_ip_address` | string | Исходящий IP-адрес источника проверки. |
| `tls_config` | object | Настройки TLS для STARTTLS или явного TLS. |

#### Параметры DNS

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `query_name` | string | Доменное имя для проверки (обязательно). |
| `query_type` | string | Тип записи (`A`, `MX`, `TXT`, `SRV`, `AAAA`, `ANY`). |
| `transport_protocol` | string | Протокол (`udp` или `tcp`). |
| `valid_rcodes` | list[string] | Допустимые DNS-коды ответа (`NOERROR`, `NXDOMAIN`, `SERVFAIL`, `REFUSED`). |
| `prefer_aaaa` | bool | Предпочитать AAAA-записи при наличии (по умолчанию `false`). |
| `dns_over_tls` | bool | Использовать DoT (требует `transport_protocol: tcp`). |
| `tls_config` | object | Настройки TLS для DoT. |
| `validate_answer_rrs` | object | Валидация ответных записей (`fail_if_matches_regexp`, `fail_if_not_matches_regexp`). |

#### Параметры ICMP

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `preferred_ip_protocol` | string | Приоритет протокола (`ip4` или `ip6`). |
| `ip_protocol_fallback` | bool | Откат на альтернативный протокол при недоступности. |
| `dont_fragment` | bool | Запрет фрагментации для проверки MTU канала. |
| `payload_size` | int | Размер полезной нагрузки в байтах (по умолчанию 56). |
| `source_ip_address` | string | Исходный IP-адрес для отправки ICMP-запросов. |

#### Параметры gRPC

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `service` | string | Имя gRPC-сервиса для проверки здоровья (например, `grpc.health.v1.Health`). |
| `metadata` | map | Кастомные метаданные для запроса (например, `authorization`, `x-client-id`). |
| `tls` | bool | Использовать TLS для соединения. |
| `tls_config` | object | Настройки TLS (`ca_file`, `cert_file`, `key_file`, `insecure_skip_verify`). |

#### Параметры Unix

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `protocol` | string | Тип сокета: `unix`, `unixgram`, `unixpacket`. |
| `query_response` | list[obj] | Сценарий обмена данными (`send`, `expect`, `expect_bytes`). |

### Расширение Blackbox Exporter: кастомные prober'ы

Blackbox Exporter поддерживает создание пользовательских prober'ов через Plugin SDK (Go). Это позволяет добавлять поддержку протоколов, которых нет в стандартной поставке.

**Архитектура плагина:**

```
┌─────────────────────────────────────┐
│         Blackbox Exporter           │
│  ┌──────────────────────────────┐   │
│  │  Встроенные prober'ы         │   │
│  │  http, tcp, icmp, dns,      │   │
│  │  grpc, unix                 │   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │  Plugin SDK (Go)            │   │
│  │  ┌────────────────────────┐  │   │
│  │  │ Кастомный prober       │  │   │
│  │  │ (ваш код)              │  │   │
│  │  └────────────────────────┘  │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
```

**Пример: реализация кастомного prober для проверки Redis:**

```go
package main

import (
    "github.com/prometheus/blackbox_exporter/config"
    "github.com/prometheus/client_golang/prometheus"
    "net/http"
)

// RedisProber реализует проверку Redis через PING
type RedisProber struct{}

func (p *RedisProber) Probe(ctx context.Context, target string, config config.Module, registry *prometheus.Registry) (bool, error) {
    // 1. Установить TCP-соединение с Redis
    conn, err := net.DialTimeout("tcp", target, config.Timeout)
    if err != nil {
        return false, err
    }
    defer conn.Close()

    // 2. Отправить PING
    conn.Write([]byte("PING\r\n"))
    buf := make([]byte, 1024)
    n, _ := conn.Read(buf)
    response := string(buf[:n])

    // 3. Проверить ответ +PONG
    return strings.Contains(response, "+PONG"), nil
}

func (p *RedisProber) Name() string { return "redis" }

func init() {
    // Регистрация плагина
    config.RegisterProber("redis", &RedisProber{})
}
```

**Пример модуля для кастомного prober:**

```yaml
modules:
  redis_ping:
    prober: redis  # Имя кастомного prober
    timeout: 3s
    redis:
      password: ""  # Кастомные параметры
      db: 0
```

**Альтернативный подход: TCP prober с query_response**

Для многих сценариев кастомный prober не требуется — достаточно расширенного использования TCP prober:

```yaml
# Проверка Redis PING без кастомного prober
modules:
  redis_ping:
    prober: tcp
    timeout: 3s
    tcp:
      query_response:
        - send: "PING"
        - expect: "\\+PONG"

# Проверка PostgreSQL (protocol-level)
modules:
  postgres_check:
    prober: tcp
    timeout: 5s
    tcp:
      query_response:
        - expect: "PGSQL"

# Проверка Memcached
modules:
  memcached_stats:
    prober: tcp
    timeout: 3s
    tcp:
      query_response:
        - send: "stats"
        - expect: "STAT pid"

# Проверка RabbitMQ (AMQP)
modules:
  rabbitmq_amqp:
    prober: tcp
    timeout: 3s
    tcp:
      query_response:
        - expect: "AMQP"
```

**Когда нужен кастомный prober:**
- Протокол требует сложной логики (handshake, аутентификация)
- Нужны специфические метрики (размер очереди Redis, replication lag)
- Нестандартный формат ответа, не поддающийся regexp/CEL

**Когда достаточно TCP prober:**
- Простой check "порт открыт / соединение установлен"
- Протокол поддерживает текстовый query_response (Redis, Memcached, SMTP)
- Базовая проверка баннера или приветствия

### Устранение типичных ошибок

1.  **Несоответствие таймаутов:** Таймаут в модуле (`timeout`) ДОЛЖЕН быть меньше `scrape_timeout` в Prometheus. Рекомендуемая разница — 500мс-1с.
2.  **Права на ICMP:** Для работы пробера `icmp` без root используйте: `setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter`.
3.  **SNI в виртуальных хостах:** При мониторинге HTTPS-сайтов на серверах с общим IP всегда указывайте `server_name` в `tls_config` для передачи корректного SNI.
4.  **CEL vs Regex:** Для проверки API предпочтительнее использовать CEL-выражения, так как они работают со структурой JSON, снижая риск ложноположительных срабатываний на текстовом уровне.
5.  **Ошибка `Invalid module`:** Модуль, указанный в параметре `module`, отсутствует в файле `blackbox.yml` или опечатка в имени. Проверьте конфигурацию: `grep -A5 'http_2xx:' /etc/blackbox_exporter/blackbox.yml`.
6.  **Ошибка `socket: permission denied`:** Недостаточно прав для ICMP. Выполните `setcap` или добавьте `NET_RAW` capability в контейнере.
7.  **Ошибка `x509: certificate signed by unknown authority`:** В `tls_config` добавлен `ca_file` или установите `insecure_skip_verify: false` только при наличии доверенного корневого сертификата.
8.  **HTTP/3 не работает:** Убедитесь, что целевой сервер слушает на порту 443/UDP и поддерживает QUIC. Проверьте наличие открытого UDP-порта 443 в фаерволле.
9.  **DNS-проверки возвращают `SERVFAIL`:** Проверьте, что целевой DNS-сервер доступен из сети экспортера и не блокирует запросы. Убедитесь в корректности `query_name` и `query_type`.

### Ссылки

Для детальной диагностики DNS-интеграции используйте [Мониторинг DNS](../../../Networking/Protocols/DNS/dns_monitoring.md). Для диагностики ICMP-проверок — [ICMP мониторинг](../../../Networking/Protocols/ICMP/icmp_monitoring.md). Интеграцию с relabeling и Service Discovery см. в [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md). Использование Probe CRD в Kubernetes описано в [Probe CRD](../../kubernetes/operator/crd/probe.md).

**См. также:**
*   [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
*   [Grafana-дашборды](./blackbox_exporter_grafana_dashboards.md) — визуализация результатов проверок модулей
*   [Предотвращение истечения SSL](../../../Kubernetes/Operations/ssl_expiration_prevention.md)
