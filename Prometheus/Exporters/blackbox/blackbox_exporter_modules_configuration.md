# Blackbox Exporter — Конфигурация модулей

## 1. Общая структура

Конфигурационный файл `blackbox.yml` содержит `modules`. Каждый модуль описывает тип проверки (`prober`) и её параметры.

**Общая структура:**

```yaml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [200]
      preferred_ip_protocol: "ip4"
```

---

## 2. HTTP-проверки

### Базовая проверка на 200 OK

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

### Проверка с авторизацией

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

### Проверка наличия текста в ответе

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

### Проверка SSL-сертификата

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

### Проверка срока действия SSL-сертификата

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

### Проверка redirect

```yaml
modules:
  http_redirect:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [301, 302]
      follow_redirects: true
```

---

## 3. TCP-проверки

### Базовая проверка порта

```yaml
modules:
  tcp_port:
    prober: tcp
    timeout: 5s
    tcp:
      preferred_ip_protocol: "ip4"
```

### Проверка SSH-баннера

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

### Проверка SMTP

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

### Проверка через Unix Socket

```yaml
modules:
  tcp_unix:
    prober: tcp
    timeout: 5s
    tcp:
      address: /var/run/docker.sock
```

---

## 4. ICMP-проверки (ping)

### Базовый ping

```yaml
modules:
  icmp_ping:
    prober: icmp
    timeout: 5s
    icmp:
      preferred_ip_protocol: "ip4"
```

### Ping с указанием количества пакетов

```yaml
modules:
  icmp_verbose:
    prober: icmp
    timeout: 5s
    icmp:
      preferred_ip_protocol: "ip4"
      ip_protocol: 4
```

> **Важно:** Для ICMP-проверок требуется запуск от `root` или с capability `CAP_NET_RAW`.

---

## 5. DNS-проверки

### Базовая проверка DNS

```yaml
modules:
  dns_google:
    prober: dns
    timeout: 5s
    dns:
      query_name: "google.com"
      query_type: "A"
      preferred_ip_protocol: "ip4"
      dns_over_https: false
```

### Проверка DNS-сервера

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

### Проверка MX-записей

```yaml
modules:
  dns_mx:
    prober: dns
    timeout: 5s
    dns:
      query_name: "gmail.com"
      query_type: "MX"
```

---

## 6. gRPC-проверки (новая функция v0.28.0)

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

---

## 7. Связанные документы

- **[Обзор и концепции](./blackbox_exporter_overview.md)** — базовые определения
- **[Установка и настройка](./blackbox_exporter_installation_and_setup.md)** — запуск и конфигурация
- **[Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)** — метрики и правила оповещений
