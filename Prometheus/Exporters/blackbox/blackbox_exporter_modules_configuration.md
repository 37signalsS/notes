# Blackbox Exporter — Конфигурация модулей

## Определения

**Конфигурационный файл** `blackbox.yml` — основной файл настроек Blackbox Exporter, содержащий секцию `modules`.

**Модуль** — именованный набор параметров, описывающий конкретный тип проверки (**prober**) и её ожидаемое поведение.

**См. также:** [Обзор и концепции](./blackbox_exporter_overview.md), [Установка и настройка](./blackbox_exporter_installation_and_setup.md).

## Основные концепции

### Общая структура модуля

Каждый модуль определяет используемый пробер и таймаут операции.

```yaml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [200]
      preferred_ip_protocol: "ip4"
```

**Доступные типы проверок (probers):**

- **http** — проверка доступности эндпоинтов по протоколу HTTP/HTTPS (HyperText Transfer Protocol).
- **tcp** — проверка доступности портов и обмен данными по TCP (Transmission Control Protocol).
- **icmp** — сетевая проверка доступности (ping) через ICMP (Internet Control Message Protocol).
- **dns** — проверка разрешения имен через DNS (Domain Name System).
- **grpc** — проверка работоспособности сервисов gRPC (gRPC Remote Procedure Calls).

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

**Проверка с авторизацией:**

```yaml
modules:
  http_auth:
    prober: http
    timeout: 5s
    http:
      method: POST
      headers:
        Authorization: "Bearer my-secret-token"
        Content-Type: "application/json"
      valid_status_codes: [200, 201]
```

**Проверка наличия текста в ответе:**

```yaml
modules:
  http_prometheus:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [200]
      fail_if_body_not_matches_regexp:
        - "Prometheus"
        - "Time Series Database"
```

**Проверка SSL/TLS сертификата:**

**SSL (Secure Sockets Layer)** и **TLS (Transport Layer Security)** — протоколы защищенного соединения.

```yaml
modules:
  https_ssl:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [200]
      tls_config:
        insecure_skip_verify: false
      fail_if_ssl: true
      fail_if_not_ssl: true
```

**Проверка срока действия сертификата:**

```yaml
modules:
  https_ssl_expiry:
    prober: http
    timeout: 5s
    http:
      tls_config:
        insecure_skip_verify: false
      fail_if_cert_not_expiry_after: 2592000s  # 30 дней
```

**Проверка перенаправлений (redirect):**

```yaml
modules:
  http_redirect:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [301, 302]
      follow_redirects: true
```

**HTTP/3 (QUIC) — v0.28.0+:**

**QUIC (Quick UDP Internet Connections)** — современный протокол на базе UDP.

```yaml
modules:
  http3_check:
    prober: http
    timeout: 5s
    http:
      preferred_ip_protocol: "ip4"
      http3: true
```

### Проверки TCP

**Базовая проверка доступности порта:**

```yaml
modules:
  tcp_port:
    prober: tcp
    timeout: 5s
    tcp:
      preferred_ip_protocol: "ip4"
```

**Проверка SSH баннера:**

**SSH (Secure Shell)** — протокол защищенного удаленного доступа.

```yaml
modules:
  tcp_ssh:
    prober: tcp
    timeout: 5s
    tcp:
      query_response:
        - expect: "^SSH-2.0-"
      preferred_ip_protocol: "ip4"
```

**Проверка SMTP:**

**SMTP (Simple Mail Transfer Protocol)** — протокол передачи почты.

```yaml
modules:
  tcp_smtp:
    prober: tcp
    timeout: 5s
    tcp:
      query_response:
        - expect: "^220"
        - send: "EHLO blackbox_exporter"
        - expect: "^250"
```

**Проверка через Unix Domain Sockets:**

```yaml
modules:
  tcp_unix:
    prober: tcp
    timeout: 5s
    tcp:
      address: /var/run/docker.sock
```

### Проверки ICMP (ping)

```yaml
modules:
  icmp_ping:
    prober: icmp
    timeout: 5s
    icmp:
      preferred_ip_protocol: "ip4"
```

**Важно:** Для выполнения ICMP-проверок экспортеру требуются права `root` или наличие capability `CAP_NET_RAW`.

### Проверки DNS

**Базовая проверка разрешения имени:**

```yaml
modules:
  dns_google:
    prober: dns
    timeout: 5s
    dns:
      query_name: "google.com"
      query_type: "A"
      preferred_ip_protocol: "ip4"
```

**Проверка конкретного DNS-сервера:**

```yaml
modules:
  dns_server:
    prober: dns
    timeout: 5s
    dns:
      query_name: "prometheus.io"
      query_type: "A"
      transport_protocol: "tcp"
      preferred_ip_protocol: "ip4"
      validate_answer_rrs:
        fail_if_matches_regexp: [".*NXDOMAIN.*"]
```

**Проверка почтовых записей (MX):**

**MX (Mail Exchanger)** — тип DNS-записи для почтовых серверов.

```yaml
modules:
  dns_mx:
    prober: dns
    timeout: 5s
    dns:
      query_name: "gmail.com"
      query_type: "MX"
```

### Проверки gRPC (v0.28.0+)

```yaml
modules:
  grpc_health:
    prober: grpc
    timeout: 5s
    grpc:
      preferred_ip_protocol: "ip4"
      tls: true
      tls_config:
        insecure_skip_verify: false
```

## Дополнительная информация

### Сводная таблица параметров проверок

#### Параметры HTTP

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `method` | string | HTTP-метод (`GET`, `POST`, `HEAD`, `PUT`, `DELETE`) |
| `headers` | map | Пользовательские заголовки запроса |
| `valid_status_codes` | list[int] | Допустимые статус-коды (по умолчанию `[200]`) |
| `valid_http_versions` | list[string] | Допустимые версии HTTP |
| `follow_redirects` | bool | Следовать перенаправлениям (по умолчанию `true`) |
| `fail_if_ssl` | bool | Ошибка, если используется SSL |
| `fail_if_not_ssl` | bool | Ошибка, если SSL не используется |
| `fail_if_body_matches_regexp` | list[string] | Ошибка при совпадении тела ответа с регулярным выражением |
| `fail_if_body_not_matches_regexp` | list[string] | Ошибка при отсутствии совпадения тела ответа с регулярным выражением |
| `fail_if_header_matches_regexp` | map | Ошибка при совпадении заголовка с регулярным выражением |
| `tls_config` | object | Настройки TLS (`insecure_skip_verify`, `ca_file`, `cert_file`, `key_file`) |
| `preferred_ip_protocol` | string | Предпочтительный протокол IP (`ip4` или `ip6`) |
| `ip_protocol_fallback` | bool | Использовать альтернативный протокол при неудаче |
| `http3` | bool | Использовать протокол HTTP/3 (QUIC) |
| `body` | string | Тело запроса (для методов POST/PUT) |
| `compression` | string | Алгоритм сжатия (`gzip`, `deflate`, `br`, `identity`) |

#### Параметры TCP

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `tls` | bool | Использовать защищенное соединение TLS |
| `tls_config` | object | Настройки TLS |
| `preferred_ip_protocol` | string | Предпочтительный протокол IP |
| `source_ip_address` | string | Локальный IP-адрес источника |
| `query_response` | list[object] | Сценарий обмена данными (ожидание/отправка) |
| `query_response[].expect` | string | Регулярное выражение ожидаемого ответа |
| `query_response[].send` | string | Строка данных для отправки |
| `query_response[].starttls` | bool | Инициировать процедуру STARTTLS |

#### Параметры ICMP

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `preferred_ip_protocol` | string | Предпочтительный протокол IP |
| `payload_size` | int | Размер передаваемых данных (по умолчанию `56` байт) |
| `ttl` | int | Время жизни пакета (Time-To-Live) |
| `source_ip_address` | string | Локальный IP-адрес источника |

#### Параметры DNS

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `query_name` | string | Доменное имя для проверки (обязательно) |
| `query_type` | string | Тип DNS-записи (`A`, `AAAA`, `CNAME`, `MX`, `NS`, `SOA`, `TXT`, `SRV`) |
| `transport_protocol` | string | Протокол передачи (`udp` или `tcp`) |
| `preferred_ip_protocol` | string | Предпочтительный протокол IP |
| `validate_answer_rrs` | object | Правила валидации записей в ответе |
| `valid_rcodes` | list[string] | Допустимые коды ответа (по умолчанию `[NOERROR]`) |

#### Параметры gRPC

| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `tls` | bool | Использовать TLS |
| `tls_config` | object | Настройки TLS |
| `preferred_ip_protocol` | string | Предпочтительный протокол IP |
| `service` | string | Имя сервиса для проверки (обычно `grpc.health.v1`) |
| `metadata` | map | Дополнительные метаданные запроса |

**См. также:**

- [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
- [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md)
