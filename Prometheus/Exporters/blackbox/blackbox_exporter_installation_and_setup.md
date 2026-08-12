# Blackbox Exporter — Установка и настройка

## Определения

**Blackbox Exporter** — официальный инструмент Prometheus для внешнего мониторинга (blackbox-мониторинг) сетевых сервисов. Он позволяет проверять доступность и производительность эндпоинтов по протоколам HTTP, HTTPS, DNS, TCP, ICMP и gRPC, имитируя поведение клиента.

*   **Порт по умолчанию:** `9115`
*   **Актуальная версия:** `v0.28.0` (релиз 2025/2026).
*   **web-config.yml** — файл конфигурации для защиты эндпоинтов самого экспортера (TLS и Basic Auth), реализованный через `exporter-toolkit`.

**См. также:**
*   [Обзор и основные концепции](./blackbox_exporter_overview.md)
*   [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
*   [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)

## Основные концепции

### Способы установки

| Способ | Сценарий использования | Плюсы / Минусы |
| :--- | :--- | :--- |
| **Binary + systemd** | Bare-metal, виртуальные машины | Полный контроль, работа с ICMP без ограничений |
| **Docker / Compose** | Контейнеризированные среды | Изоляция, быстрый запуск; требуется настройка для ICMP |
| **Kubernetes (Helm)** | Кластеры Kubernetes | Автоматизация через чарты (версия v11.17+) |
| **Prometheus Operator** | Kubernetes (GitOps подход) | Управление через Custom Resource `Probe` |

### Структура конфигурации

1.  **`blackbox.yml`**: Основной файл с описанием модулей проверок (таймауты, протоколы, регулярные выражения).
2.  **`web-config.yml`**: Файл для настройки безопасности самого экспортера (TLS, аутентификация).

### Ключевые флаги запуска

| Флаг | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `--config.file` | `blackbox.yml` | Путь к основному файлу конфигурации |
| `--web.config.file` | (пусто) | Путь к настройкам безопасности (TLS/Auth) |
| `--config.enable-auto-reload` | `false` | Автоматическая перезагрузка конфига при изменениях |
| `--web.listen-address` | `:9115` | Адрес и порт для входящих запросов |
| `--log.level` | `info` | Уровень детализации логов (`debug`, `info`, `warn`, `error`) |

## Практические сценарии

### 1. Установка на Linux через systemd

**Подготовка и загрузка:**
```bash
VERSION="0.28.0"
wget https://github.com/prometheus/blackbox_exporter/releases/download/v${VERSION}/blackbox_exporter-${VERSION}.linux-amd64.tar.gz
tar xvfz blackbox_exporter-${VERSION}.linux-amd64.tar.gz
sudo mv blackbox_exporter-${VERSION}.linux-amd64/blackbox_exporter /usr/local/bin/

# Создание директорий и пользователя
sudo mkdir -p /etc/blackbox_exporter
sudo cp blackbox_exporter-${VERSION}.linux-amd64/blackbox.yml /etc/blackbox_exporter/
sudo useradd --no-create-home --shell /bin/false blackbox
sudo chown -R blackbox:blackbox /etc/blackbox_exporter
```

**Настройка прав для ICMP (Ping):**
Для выполнения ICMP-проверок без прав root необходимо выдать бинарному файлу соответствующие `capabilities`:
```bash
sudo setcap cap_net_raw+ep /usr/local/bin/blackbox_exporter
```

**Конфигурация юнита systemd** (`/etc/systemd/system/blackbox_exporter.service`):
```ini
[Unit]
Description=Prometheus Blackbox Exporter
Wants=network-online.target
After=network-online.target

[Service]
User=blackbox
Group=blackbox
Type=simple
ExecStart=/usr/local/bin/blackbox_exporter \
  --config.file=/etc/blackbox_exporter/blackbox.yml \
  --config.enable-auto-reload \
  --web.listen-address=:9115
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
# Capabilities для работы ICMP под пользователем
AmbientCapabilities=CAP_NET_RAW

[Install]
WantedBy=multi-user.target
```

### 2. Запуск в Docker Compose

Для работы ICMP (Ping) в контейнере необходимо передать `CAP_NET_RAW` или использовать `sysctl`.

```yaml
services:
  blackbox:
    image: prom/blackbox-exporter:v0.28.0
    container_name: blackbox_exporter
    ports:
      - "9115:9115"
    cap_add:
      - NET_RAW
    volumes:
      - ./blackbox.yml:/etc/blackbox_exporter/blackbox.yml:ro
    command:
      - "--config.file=/etc/blackbox_exporter/blackbox.yml"
      - "--config.enable-auto-reload"
    restart: unless-stopped
```

### 3. Развёртывание в Kubernetes через Helm

Рекомендуемый метод для управления в K8s.

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
# Установка с базовыми настройками
helm install blackbox prometheus-community/prometheus-blackbox-exporter
```

Для интеграции с **Prometheus Operator** используется ресурс `Probe`:
```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: external-website-check
spec:
  jobName: blackbox-http
  module: http_2xx
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  targets:
    staticConfig:
      static:
        - https://prometheus.io
```

### 4. Настройка безопасности (web-config.yml)

Защита эндпоинтов самого экспортера через Basic Auth и TLS.

```yaml
# /etc/blackbox_exporter/web-config.yml
tls_server_config:
  cert_file: /etc/blackbox_exporter/server.crt
  key_file: /etc/blackbox_exporter/server.key

basic_auth_users:
  # Пароль генерируется через htpasswd -nB user
  admin: "$2y$12$..." 
```

Запуск с файлом безопасности:
```bash
blackbox_exporter --web.config.file=/etc/blackbox_exporter/web-config.yml
```

## Дополнительная информация

### Проверка работоспособности (Ad-hoc)

После запуска можно выполнить ручную проверку через `curl`:
```bash
# Проверка доступности сайта через модуль http_2xx
curl "http://localhost:9115/probe?target=google.com&module=http_2xx"

# Проверка DNS-резолвинга
curl "http://localhost:9115/probe?target=8.8.8.8&module=dns_google"
```

### Типичные проблемы и их решение

1.  **Ошибка `socket: permission denied`**: Недостаточно прав для ICMP. Убедитесь, что выполнена команда `setcap` или в контейнере добавлен `cap_add: [NET_RAW]`.
2.  **Ошибка `Invalid module`**: Модуль, указанный в параметре `module`, отсутствует в файле `blackbox.yml`.
3.  **Несоответствие таймаутов**: Таймаут в модуле (`timeout` в `blackbox.yml`) должен быть **меньше**, чем `scrape_timeout` в конфигурации Prometheus.
4.  **Валидация конфигурации**: Используйте флаг `--dry-run` для проверки синтаксиса `blackbox.yml` перед перезапуском.

**См. также:**
*   [Relabeling — паттерн Blackbox](../../service_discovery_and_relabeling.md#подмена-адреса-паттерн-blackbox-exporter)
*   [Мониторинг TLS/SSL в Kubernetes](../../../Kubernetes/Operations/ssl_expiration_prevention.md)
