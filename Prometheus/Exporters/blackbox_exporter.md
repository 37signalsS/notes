# Blackbox Exporter

## Определения

**Blackbox Exporter** — экспортер для мониторинга систем снаружи (blackbox-мониторинг), с точки зрения пользователя. Проверяет доступность и работоспособность эндпоинтов по сети с использованием протоколов: HTTP(S), TCP, ICMP, DNS, gRPC.

* **Порт по умолчанию:** `9115`
* **Последняя стабильная версия:** `0.28.0` (декабрь 2025)
* **Репозиторий:** [prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter)
* **Установка:** [installation/blackbox_exporter_installation.md](../installation/blackbox_exporter_installation.md)

## Основные концепции

### Whitebox vs Blackbox мониторинг

| Характеристика | Whitebox | Blackbox |
| :--- | :--- | :--- |
| **Доступ** | Внутренние метрики системы | Внешняя проверка |
| **Экспортер** | Устанавливается на целевой системе | Запускается отдельно |
| **Пример** | `node_exporter`, `mysqld_exporter` | `blackbox_exporter` |
| **Метрики** | CPU, память, запросы к БД | Доступность, SSL, время ответа |

### Принцип работы

`blackbox_exporter` работает по особому принципу:

1. Prometheus опрашивает не целевую систему (например, `google.com`), а сам `blackbox_exporter` на эндпоинте `/probe`
2. Целевой адрес передаётся как параметр `?target=...`
3. Имя модуля проверки передаётся как параметр `?module=...`
4. `blackbox_exporter` выполняет проверку и возвращает метрики о результате

**Схема работы:**

```
Prometheus → http://blackbox-exporter:9115/probe?target=google.com&module=http_2xx
                                                      ↓
blackbox_exporter выполняет проверку google.com
                                                      ↓
blackbox_exporter возвращает метрики: probe_success, probe_duration_seconds, ...
```

> **Важно:** По пути `/metrics` `blackbox_exporter` отдаёт метрики о своей работе, а не результаты проверок. Результаты проверок доступны только по пути `/probe`.

## Практические сценарии

### Запуск blackbox_exporter

**Systemd:**

```bash
# Скачать последнюю версию
BLACKBOX_EXPORTER_VERSION="0.28.0"
wget https://github.com/prometheus/blackbox_exporter/releases/download/v${BLACKBOX_EXPORTER_VERSION}/blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xvfz blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
mv blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/

# Создать директорию для конфигурации
mkdir -p /etc/blackbox_exporter
cp blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox.yml /etc/blackbox_exporter/

# Создать systemd-сервис
cat <<EOF > /etc/systemd/system/blackbox_exporter.service
[Unit]
Description=Prometheus Blackbox Exporter
Documentation=https://github.com/prometheus/blackbox_exporter
After=network-online.target

[Service]
Restart=always
User=nobody
Group=nobody
EnvironmentFile=/etc/sysconfig/blackbox_exporter
ExecStart=/usr/local/bin/blackbox_exporter --config.file=/etc/blackbox_exporter/blackbox.yml
ExecReload=/bin/kill -HUP \$MAINPID

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl start blackbox_exporter
systemctl enable blackbox_exporter
```

**Docker:**

```yaml
services:
  blackbox_exporter:
    image: prom/blackbox-exporter:v0.28.0
    container_name: blackbox_exporter
    ports:
      - "9115:9115"
    volumes:
      - ./blackbox.yml:/etc/blackbox_exporter/blackbox.yml:ro
    command:
      - '--config.file=/etc/blackbox_exporter/blackbox.yml'
    restart: unless-stopped
```

### Настройка Prometheus

```yaml
scrape_configs:
  - job_name: 'blackbox'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - "http://prometheus.io"
        - "https://google.com"
    relabel_configs:
      # Копируем адрес цели в параметр __param_target
      - source_labels: [__address__]
        target_label: __param_target
      # Копируем __param_target в лейбл instance
      - source_labels: [__param_target]
        target_label: instance
      # Подменяем адрес на адрес blackbox_exporter
      - target_label: __address__
        replacement: 127.0.0.1:9115
```

Подробнее о relabeling см. в [service_discovery_and_relabeling.md](../service_discovery_and_relabeling.md).

### Конфигурация модулей

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

#### HTTP-проверки

**Базовая проверка на 200 OK:**

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

**Проверка SSL-сертификата:**

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

**Проверка срока действия SSL-сертификата:**

```yaml
metrics:
  http:
    tls_config:
      insecure_skip_verify: false
    fail_if_cert_not_expiry_after: 2592000s  # 30 дней
```

**Проверка redirect:**

```yaml
modules:
  http_redirect:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [301, 302]
      follow_redirects: true
```

#### TCP-проверки

**Базовая проверка порта:**

```yaml
modules:
  tcp_port:
    prober: tcp
    timeout: 5s
    tcp:
      preferred_ip_protocol: "ip4"
```

**Проверка SSH-баннера:**

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

**Проверка через Unix Socket:**

```yaml
modules:
  tcp_unix:
    prober: tcp
    timeout: 5s
    tcp:
      address: /var/run/docker.sock
```

#### ICMP-проверки (ping)

**Базовый ping:**

```yaml
modules:
  icmp_ping:
    prober: icmp
    timeout: 5s
    icmp:
      preferred_ip_protocol: "ip4"
```

**Ping с указанием количества пакетов:**

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

#### DNS-проверки

**Базовая проверка DNS:**

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

**Проверка DNS-сервера:**

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

**Проверка MX-записей:**

```yaml
modules:
  dns_mx:
    prober: dns
    timeout: 5s
    dns:
      query_name: "gmail.com"
      query_type: "MX"
```

#### gRPC-проверки (новая функция v0.28.0)

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

### Основные метрики

```
probe_success                              # 1 если проверка успешна, 0 если нет
probe_duration_seconds                     # Время выполнения проверки
probe_dns_lookup_time_seconds              # Время DNS-запроса
probe_connect_duration_seconds             # Время подключения
probe_ssl_earliest_cert_expiry             # Время истечения SSL-сертификата
probe_tls_version_info{version="TLSv1.3"}  # Версия TLS
probe_http_status_code                     # HTTP статус код
probe_http_duration_seconds                # Время HTTP-запроса
probe_ip_addr_protocol                     # Протокол IP (ipv4/ipv6)
probe_icmp_round_trip_seconds              # Время ICMP ping
```

### Алертинг

**Эндпоинт недоступен:**

```yaml
- alert: BlackboxProbeFailed
  expr: probe_success == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Проверка {{ $labels.instance }} не удалась"
    description: "Blackbox-проверка не удалась более 5 минут"
```

**Высокое время ответа:**

```yaml
- alert: BlackboxSlowResponse
  expr: probe_duration_seconds > 2
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Медленный ответ от {{ $labels.instance }}"
    description: "Время ответа превышает 2 секунды"
```

**SSL-сертификат истекает:**

```yaml
- alert: BlackboxSSLCertExpiring
  expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 30
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "SSL-сертификат истекает на {{ $labels.instance }}"
    description: "До истечения SSL-сертификата осталось менее 30 дней"
```

### Примеры использования

**Проверка URL в браузере:**

```bash
# HTTP-проверка
curl "localhost:9115/probe?module=http_2xx&target=http://prometheus.io"

# ICMP ping
curl "localhost:9115/probe?module=icmp_ping&target=google.com"

# DNS-проверка
curl "localhost:9115/probe?module=dns_google&target=8.8.8.8"

# TCP-проверка
curl "localhost:9115/probe?module=tcp_ssh&target=127.0.0.1:22"
```

## Дополнительная информация

### Новые возможности v0.28.0

* **HTTP/3 (QUIC) prober** — поддержка нового протокола
* **gRPC metadata** — передача метаданных в gRPC-проверках
* **Byte matching в TCP** — проверка бинарных данных
* **Unix domain sockets** — проверка через локальные сокеты
* **Автоматическая перезагрузка конфига** — флаг `--config.enable-auto-reload`

### Связанные темы

* [Service Discovery и Relabeling](../service_discovery_and_relabeling.md)
* [Alertmanager](../alertmanager.md)
* [Правила оповещений](../rules.md)

### Официальные ресурсы

* [GitHub Repository](https://github.com/prometheus/blackbox_exporter)
* [Official Documentation](https://prometheus.io/docs/guides/blackbox-exporter/)
* [Default Port Allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
