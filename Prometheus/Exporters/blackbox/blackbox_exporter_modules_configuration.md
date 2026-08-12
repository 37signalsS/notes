# Blackbox Exporter — Конфигурация модулей

## Определения

**Конфигурационный файл** `blackbox.yml` — основной файл настроек Blackbox Exporter, содержащий секцию `modules`. В ней определяются параметры сетевых проверок и критерии их успешности.

*   **Модуль** — именованный набор настроек, описывающий конкретный тип проверки (**prober**) и её ожидаемое поведение.
*   **Prober** — исполнитель проверки (HTTP, TCP, ICMP, DNS, gRPC, Unix).
*   **CEL (Common Expression Language)** — язык выражений для сложной валидации данных (v0.25.0+).
*   **Актуальная версия:** `v0.28.0` (2025/2026).

**См. также:** [Обзор и концепции](./blackbox_exporter_overview.md), [Установка и настройка](./blackbox_exporter_installation_and_setup.md), [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md).

## Основные концепции

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
```

**Аутентификация и OAuth2 (v0.25.0+):**
```yaml
modules:
  http_auth_complex:
    prober: http
    http:
      # Basic Auth
      basic_auth:
        username: "admin"
        password: "password123"
      # OAuth2
      oauth2:
        client_id: "blackbox-client"
        client_secret: "secret-key"
        token_url: "https://auth.example.com/token"
        scopes: ["read", "write"]
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
        - "obj.status == 'MAINTENANCE'" # Ошибка, если статус "обслуживание"
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
        server_name: "example.com" # Передача SNI для виртуальных хостов
      fail_if_not_ssl: true
      fail_if_cert_not_expiry_after: 2592000s # 30 дней в секундах
```

**HTTP/3 (QUIC) — v0.28.0+:**
```yaml
modules:
  http3_check:
    prober: http
    http:
      enable_http3: true # Активация поддержки QUIC
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
        - expect: "^SSH-2.0-" # Проверка версии протокола в баннере
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

**Проверка с использованием байтовых последовательностей (v0.25.0+):**
```yaml
modules:
  tcp_binary:
    prober: tcp
    tcp:
      query_response:
        - send: "PING"
        - expect_bytes: [0x50, 0x4f, 0x4e, 0x47] # "PONG" в hex формате
```

### Проверки ICMP (Ping)

```yaml
modules:
  icmp_ping:
    prober: icmp
    icmp:
      preferred_ip_protocol: "ip4"
      dont_fragment: true # Запрет фрагментации для проверки MTU канала
      payload_size: 56    # Размер полезной нагрузки
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

**gRPC Health Check с метаданными (v0.28.0+):**
```yaml
modules:
  grpc_health_auth:
    prober: grpc
    grpc:
      service: "grpc.health.v1.Health" # Стандартный сервис проверки здоровья
      metadata:
        authorization: "Bearer secret-token"
        x-client-id: "blackbox-exporter"
      tls: true
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

## Дополнительная информация

### Справочник параметров

#### Параметры HTTP
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `method` | string | HTTP-метод (`GET`, `POST`, `HEAD`, `PUT`, `DELETE`). |
| `headers` | map | Статические заголовки запроса. |
| `valid_status_codes` | list[int] | Список допустимых статус-кодов (по умолчанию `[2xx]`). |
| `follow_redirects` | bool | Следовать перенаправлениям (по умолчанию `true`). |
| `fail_if_body_matches_regexp` | list[string] | Ошибка при совпадении тела с регулярным выражением. |
| `fail_if_body_json_matches_cel` | list[string] | Валидация JSON через CEL (v0.28.0+). |
| `tls_config` | object | Настройки TLS (ca_file, cert_file, key_file, server_name). |
| `enable_http3` | bool | Использовать HTTP/3 (QUIC). |
| `compression` | string | Алгоритм сжатия (`gzip`, `br`, `deflate`). |

#### Параметры TCP
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `query_response` | list[obj] | Сценарий обмена данными (`send`, `expect`, `expect_bytes`). |
| `tls` | bool | Использовать TLS после установления соединения. |
| `starttls` | bool | Инициировать процедуру STARTTLS (например, для SMTP/IMAP). |
| `source_ip_address` | string | Исходящий IP-адрес источника проверки. |

#### Параметры DNS
| Параметр | Тип | Описание |
| :--- | :--- | :--- |
| `query_name` | string | Доменное имя для проверки (обязательно). |
| `query_type` | string | Тип записи (`A`, `MX`, `TXT`, `SRV`, `AAAA`, `ANY`). |
| `transport_protocol` | string | Протокол (`udp` или `tcp`). |
| `dns_over_tls` | bool | Использовать DoT (требует `transport_protocol: tcp`). |

### Устранение типичных ошибок

1.  **Несоответствие таймаутов:** Таймаут в модуле (`timeout`) ДОЛЖЕН быть меньше `scrape_timeout` в Prometheus. Рекомендуемая разница — 500мс-1с.
2.  **Права на ICMP:** Для работы пробера `icmp` без root используйте: `setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter`.
3.  **SNI в виртуальных хостах:** При мониторинге HTTPS-сайтов на серверах с общим IP всегда указывайте `server_name` в `tls_config` для передачи корректного SNI.
4.  **CEL vs Regex:** Для проверки API предпочтительнее использовать CEL-выражения, так как они работают со структурой JSON, снижая риск ложноположительных срабатываний на текстовом уровне.

**См. также:**
*   [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
*   [Relabeling в Prometheus](../../service_discovery_and_relabeling.md)
*   [Probe CRD (Prometheus Operator)](../../kubernetes/operator/crd/probe.md)
*   [Предотвращение истечения SSL](../../../Kubernetes/Operations/ssl_expiration_prevention.md)
