# Blackbox Exporter — Установка и настройка

## Определения

**Blackbox Exporter** — официальный экспортер Prometheus для мониторинга доступности внешних сервисов (blackbox-мониторинг) по протоколам HTTP, HTTPS, DNS, TCP, ICMP и gRPC. Порт по умолчанию: `9115`. Актуальная версия: `0.28.0`.

**web-config.yml** — файл конфигурации для защиты самого экспортера (TLS и Basic Auth) на эндпоинтах `/metrics` и `/probe`. Реализован через `exporter-toolkit`.

**См. также:** [Обзор и концепции](./blackbox_exporter_overview.md), [Конфигурация модулей](./blackbox_exporter_modules_configuration.md).

## Основные концепции

### Способы установки

| Способ | Когда использовать | Плюсы / Минусы |
| :--- | :--- | :--- |
| **Binary + systemd** | Bare-metal, виртуальные машины (VM) | Полный контроль, работа с ICMP без контейнеризации |
| **Docker / Compose** | Микросервисная архитектура, CI/CD | Быстрый старт, изоляция; сложность с ICMP (NET_RAW) |
| **Kubernetes (Helm)** | Стандартные K8s кластеры | Простота управления через Helm-чарт |
| **Prometheus Operator** | Kubernetes (GitOps подход) | Декларативное описание через `Probe` CRD |

### Структура конфигурации

1.  **`blackbox.yml`**: Основной файл с описанием модулей проверок. Подробнее: [Конфигурация модулей](./blackbox_exporter_modules_configuration.md).
2.  **`web-config.yml`**: Опциональный файл для настройки HTTPS и аутентификации доступа к самому экспортеру.

### Ключевые параметры запуска

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `--config.file` | `blackbox.yml` | Путь к основному файлу конфигурации |
| `--web.config.file` | | Путь к настройкам TLS и Auth (v0.19.0+) |
| `--web.listen-address` | `:9115` | Адрес и порт прослушивания |
| `--config.enable-auto-reload` | `false` | Авто-перезагрузка при изменении конфига (v0.28.0+) |
| `--log.level` | `info` | Уровень логов (`debug`, `info`, `warn`, `error`) |

## Практические сценарии

### 1. Установка на Linux (systemd)

**Загрузка бинарных файлов:**

```bash
BLACKBOX_EXPORTER_VERSION="0.28.0"
wget https://github.com/prometheus/blackbox_exporter/releases/download/v${BLACKBOX_EXPORTER_VERSION}/blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xvfz blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64.tar.gz
mv blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/

# Создание инфраструктуры
mkdir -p /etc/blackbox_exporter
cp blackbox_exporter-${BLACKBOX_EXPORTER_VERSION}.linux-amd64/blackbox.yml /etc/blackbox_exporter/
useradd --no-create-home --shell /bin/false nobody || true
chown -R nobody:nobody /etc/blackbox_exporter
```

**Настройка ICMP без root:**
```bash
setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter
```

**Systemd-юнит** `/etc/systemd/system/blackbox_exporter.service`:
Использование `AmbientCapabilities` позволяет процессу сохранить права на сырые сокеты даже при запуске от пользователя `nobody`.

```ini
[Unit]
Description=Prometheus Blackbox Exporter
Documentation=https://github.com/prometheus/blackbox_exporter
After=network-online.target

[Service]
Restart=always
User=nobody
Group=nobody
EnvironmentFile=/etc/default/blackbox_exporter
ExecStart=/usr/local/bin/blackbox_exporter $OPTIONS
ExecReload=/bin/kill -HUP $MAINPID
# Capabilities для работы ICMP (ping)
AmbientCapabilities=CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_RAW
TimeoutStopSec=20s

[Install]
WantedBy=multi-user.target
```

**Файл параметров** `/etc/default/blackbox_exporter`:
```bash
OPTIONS="--config.file=/etc/blackbox_exporter/blackbox.yml \
--web.listen-address=:9115 \
--config.enable-auto-reload"
```

### 2. Установка через Docker и Docker Compose

Для работы ICMP в Docker необходимо разрешить `NET_RAW` или настроить `sysctl`.

**Docker Compose:**
```yaml
services:
  blackbox_exporter:
    image: prom/blackbox-exporter:v0.28.0
    container_name: blackbox_exporter
    ports:
      - "9115:9115"
    cap_add:
      - NET_RAW
    volumes:
      - ./blackbox.yml:/etc/blackbox_exporter/blackbox.yml:ro
      - ./web-config.yml:/etc/blackbox_exporter/web-config.yml:ro
    command:
      - '--config.file=/etc/blackbox_exporter/blackbox.yml'
      - '--web.config.file=/etc/blackbox_exporter/web-config.yml'
    restart: unless-stopped
```

### 3. Развёртывание в Kubernetes

**Использование Helm-чарта:**
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus-blackbox-exporter prometheus-community/prometheus-blackbox-exporter
```

**Интеграция с Prometheus Operator (Probe CRD):**
Вместо ручного описания `scrape_configs` создаётся ресурс `Probe`:
```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: example-com-check
spec:
  jobName: blackbox-http
  module: http_2xx
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  targets:
    staticConfig:
      static:
        - https://example.com
```
Подробнее: [Probe — Концепции (CRD)](../../kubernetes/operator/crd/probe.md).

### 4. Настройка безопасности (web-config.yml)

Защита доступа к метрикам и веб-интерфейсу экспортера.

```yaml
# /etc/blackbox_exporter/web-config.yml
tls_server_config:
  cert_file: /etc/blackbox_exporter/tls.crt
  key_file: /etc/blackbox_exporter/tls.key

basic_auth_users:
  # Хеш генерируется через htpasswd -nB user
  admin: "$2a$12$6g5f3MZriVtoOZ7GrCEwzuTBxnPQwHurpktXTXUu1neg/XZeHzipy"
```

### 5. Конфигурация Prometheus

При использовании защиты на экспортере, добавьте параметры аутентификации в `scrape_config`.

```yaml
scrape_configs:
  - job_name: 'blackbox'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - "https://prometheus.io"
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: 127.0.0.1:9115
    
    # Настройки для доступа к защищенному экспортеру
    scheme: https
    basic_auth:
      username: admin
      password: "mypassword"
```

## Дополнительная информация

### Проверка работы (Ad-hoc)

| Тип проверки | Команда curl | Описание |
| :--- | :--- | :--- |
| **HTTP 200** | `curl "localhost:9115/probe?target=google.com&module=http_2xx"` | Простая проверка доступности сайта |
| **DNS A** | `curl "localhost:9115/probe?target=8.8.8.8&module=dns_google"` | Проверка DNS-сервера Google |
| **TCP Port** | `curl "localhost:9115/probe?target=127.0.0.1:22&module=tcp_connect"` | Проверка открытого SSH порта |
| **gRPC Health** | `curl "localhost:9115/probe?target=my-service:50051&module=grpc_health"` | Проверка gRPC Health Check (v0.28.0+) |

### Устранение неполадок

1.  **Ошибка `socket: permission denied` (ICMP):**
    *   Проверьте `setcap` на бинарном файле.
    *   В Docker Compose добавьте `cap_add: [NET_RAW]`.
    *   Проверьте `sysctl net.ipv4.ping_group_range="0 2147483647"`.
2.  **Ошибка `Invalid module`:**
    *   Убедитесь, что модуль определен в `blackbox.yml`.
    *   Проверьте регистр имен (case-sensitive).
3.  **Таймауты:**
    *   `timeout` в модуле `blackbox.yml` должен быть меньше, чем `scrape_timeout` в Prometheus.
4.  **Валидация конфига:**
    *   `blackbox_exporter --config.file=blackbox.yml --dry-run`.

**См. также:**

- [Обзор и концепции](./blackbox_exporter_overview.md)
- [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
- [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
- [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md)
- [Relabeling — паттерн Blackbox](../../service_discovery_and_relabeling.md#подмена-адреса-паттерн-blackbox-exporter)
