# Blackbox Exporter — Конфигурация модулей

## Определения

**Конфигурационный файл** `blackbox.yml` — основной файл настроек Blackbox Exporter, содержащий секцию `modules`. Актуальная версия экспортера: `0.28.0`.

**Модуль** — именованный набор параметров, описывающий конкретный тип проверки (**prober**) и её ожидаемое поведение.

**См. также:** [Обзор и концепции](./blackbox_exporter_overview.md), [Установка и настройка](./blackbox_exporter_installation_and_setup.md).

## Основные концепции

### Общая структура модуля

Каждый модуль определяет используемый пробер, таймаут и стратегию выбора протокола IP.

```yaml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [200]
      preferred_ip_protocol: "ip4"
      ip_protocol_fallback: true # Откат на ip6 при недоступности ip4
```

**Доступные типы проверок (probers):**

- **http** — проверка эндпоинтов по протоколам HTTP/HTTPS и HTTP/3 (QUIC).
- **tcp** — проверка доступности портов и сложный обмен данными («запрос-ответ»).
- **icmp** — сетевая проверка доступности (ping) через ICMP.
- **dns** — проверка разрешения имен через DNS и DNS over TLS (DoT).
- **grpc** — проверка работоспособности сервисов gRPC Health Check.

## Практические сценарии

### Проверки HTTP/HTTPS

**Базовая проверка на статус-код 200 OK:**

```yaml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200]
      method: GET
      preferred_ip_protocol: "ip4"
```

**Аутентификация (Basic Auth, Bearer и OAuth2):**

```yaml
modules:
  http_auth_complex:
    prober: http
    http:
      # Basic Auth
      basic_auth:
        username: "admin"
        password: "password123"
      # OAuth2 (v0.25.0+)
      oauth2:
        client_id: "blackbox-client"
        client_secret: "secret-key"
        token_url: "https://auth.example.com/token"
        scopes: ["read", "write"]
      valid_status_codes: [200, 201]
```

**Проверка наличия текста и заголовков в ответе:**

```yaml
modules:
  http_content_check:
    prober: http
    http:
      valid_status_codes: [200]
      fail_if_body_not_matches_regexp:
        - "Prometheus"
        - "Time Series Database"
      fail_if_header_not_matches_regexp:
        Content-Type: "application/json.*"
```

**Валидация JSON через CEL (v0.25.0+):**

**CEL (Common Expression Language)** — высокопроизводительный язык выражений для безопасной валидации данных.

```yaml
modules:
  http_json_cel:
    prober: http
    http:
      method: GET
      fail_if_body_json_not_matches_cel:
        - "json.status == 'ok'"
        - "json.results.size() >= 1"
```

**Проверка SSL/TLS сертификата и срока действия:**

```yaml
modules:
  https_ssl_expiry:
    prober: http
    http:
      tls_config:
        insecure_skip_verify: false
        server_name: "example.com" # SNI
      fail_if_not_ssl: true
      fail_if_cert_not_expiry_after: 2592000s # 30 дней
```

**Использование прокси-сервера:**

```yaml
modules:
  http_via_proxy:
    prober: http
    http:
      proxy_url: "http://proxy.internal:3128"
      skip_resolve_phase_with_proxy: true # DNS-резолвинг на стороне прокси
```

**HTTP/3 (QUIC) — v0.28.0+:**

```yaml
modules:
  http3_check:
    prober: http
    http:
      http3: true
      preferred_ip_protocol: "ip4"
```

### Проверки TCP

**Проверка SSH баннера:**

**SSH (Secure Shell)** — протокол защищенного удаленного доступа.

```yaml
modules:
  tcp_ssh:
    prober: tcp
    tcp:
      query_response:
        - expect: "^SSH-2.0-"
      preferred_ip_protocol: "ip4"
```

**Проверка SMTP (сценарий «Запрос-Ответ»):**

**SMTP (Simple Mail Transfer Protocol)** — протокол передачи почты.

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

**Проверка с использованием байтовых последовательностей (v0.25.0+):**

```yaml
modules:
  tcp_binary:
    prober: tcp
    tcp:
      query_response:
        - send: "PING"
        - expect_bytes: [0x50, 0x4f, 0x4e, 0x47] # "PONG" в hex
```

### Проверки ICMP (ping)

```yaml
modules:
  icmp_ping:
    prober: icmp
    icmp:
      preferred_ip_protocol: "ip4"
      dont_fragment: true # Запрет фрагментации (проверка MTU)
      payload_size: 56
```

### Проверки DNS

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

### Проверки gRPC

```yaml
modules:
  grpc_health:
    prober: grpc
    grpc:
      service: "grpc.health.v1.Health" # Стандартный сервис Health Check
      tls: true
      metadata:
        x-api-key: "my-secret-token"
```

## Дополнительная информация

### Сводная таблица параметров

#### Параметры HTTP

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `method` | string | HTTP-метод (`GET`, `POST`, `HEAD`, `PUT`, `DELETE`) |
| `headers` | map | Статические заголовки запроса |
| `http_headers` | object | Заголовки с поддержкой `secrets` и `files` |
| `valid_status_codes` | list[int] | Допустимые статус-коды (по умолчанию `[2xx]`) |
| `valid_http_versions` | list[string] | Допустимые версии HTTP |
| `follow_redirects` | bool | Следовать перенаправлениям (по умолчанию `true`) |
| `fail_if_ssl` / `fail_if_not_ssl` | bool | Проверка наличия/отсутствия SSL |
| `fail_if_body_matches_regexp` | list[string] | Ошибка при совпадении тела с регулярным выражением |
| `fail_if_body_not_matches_regexp` | list[string] | Ошибка при отсутствии совпадения тела с регулярным выражением |
| `fail_if_body_json_matches_cel` | list[string] | Валидация JSON через CEL-выражения |
| `tls_config` | object | Настройки TLS (ca_file, cert_file, key_file, server_name) |
| `oauth2` | object | Конфигурация OAuth2 (client_id, client_secret, token_url) |
| `proxy_url` | string | URL прокси-сервера |
| `http3` | bool | Использовать HTTP/3 (QUIC) |
| `compression` | string | Алгоритм сжатия (`gzip`, `br`, `deflate`) |

#### Параметры TCP

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `query_response` | list[obj] | Сценарий обмена данными |
| `query_response[].expect` | string | Ожидаемое регулярное выражение |
| `query_response[].expect_bytes` | list[byte] | Ожидаемая последовательность байт (в hex) |
| `query_response[].send` | string | Данные для отправки |
| `query_response[].starttls` | bool | Инициировать процедуру STARTTLS |
| `tls` | bool | Использовать TLS после установления соединения |
| `source_ip_address` | string | Исходящий IP-адрес источника |

#### Параметры DNS

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `query_name` | string | Доменное имя для проверки (обязательно) |
| `query_type` | string | Тип записи (`A`, `AAAA`, `MX`, `ANY`, `TXT`, `SRV`) |
| `transport_protocol` | string | Протокол (`udp` или `tcp`) |
| `dns_over_tls` | bool | Использовать DoT (требует `transport_protocol: tcp`) |
| `validate_answer_rrs` | object | Регулярные выражения для проверки секции Answer |
| `valid_rcodes` | list[string] | Допустимые коды ответа (по умолчанию `[NOERROR]`) |

#### Параметры gRPC

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `service` | string | Имя сервиса (обычно `grpc.health.v1`) |
| `tls` | bool | Использовать TLS для gRPC-запроса |
| `tls_config` | object | Настройки TLS для gRPC |
| `metadata` | map | Дополнительные метаданные (заголовки) gRPC |

### Устранение типичных ошибок

1. **Несоответствие таймаутов:** Таймаут в модуле (`timeout`) должен быть меньше `scrape_timeout` в Prometheus. Рекомендуемая разница — минимум 500мс.
2. **Права на ICMP:** Для ICMP-проверок без root используйте capability: `setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter`.
3. **Ошибки TLS (SNI):** При проверке нескольких доменов на одном IP обязательно указывайте `server_name` в `tls_config` модуля для корректной передачи SNI.
4. **Валидация JSON:** CEL-выражения чувствительны к типам данных. Используйте `json.results.size()` вместо `.length`.

**См. также:**

- [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
- [Relabeling в Prometheus](../../service_discovery_and_relabeling.md)
- [Prometheus Operator — Probe CRD](../../kubernetes/operator/crd/probe.md)
