# Blackbox Exporter — Установка и настройка

## Определения

**Blackbox Exporter** — официальный инструмент Prometheus для внешнего мониторинга (blackbox-мониторинг) сетевых сервисов. Он позволяет проверять доступность и производительность эндпоинтов по протоколам HTTP, HTTPS, DNS, TCP, ICMP и gRPC, имитируя поведение клиента.

*   **Порт по умолчанию:** `9115`
*   **Актуальная версия:** `v0.28.0` (релиз 2025/2026).
*   **web-config.yml** — файл конфигурации для защиты эндпоинтов самого экспортера (TLS и Basic Auth), реализованный через `exporter-toolkit`.
*   **Lifecycle конфигурации:** порядок загрузки `blackbox.yml` при старте экспортера, автоматическая перезагрузка при изменении файла (`--config.enable-auto-reload`), валидация перед применением.

**См. также:**
*   [Обзор и основные концепции](./blackbox_exporter_overview.md)
*   [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
*   [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
*   [Grafana-дашборды](./blackbox_exporter_grafana_dashboards.md)
*   [Масштабирование и HA](./blackbox_exporter_scaling_and_ha.md)

## Основные концепции

### Способы установки

| Способ | Сценарий использования | Плюсы / Минусы |
| :--- | :--- | :--- |
| **Binary + systemd** | Bare-metal, виртуальные машины | Полный контроль, работа с ICMP без ограничений |
| **Docker / Compose** | Контейнеризированные среды | Изоляция, быстрый запуск; требуется настройка для ICMP |
| **Podman / Quadlet** | Контейнеризированные среды без Docker daemon | Rootless-совместимость, нативная systemd-интеграция |
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

## Предварительные требования

### Аппаратные требования

*   Минимум 1 CPU core и 128 MiB RAM для развертывания до 500 целей с интервалом проверки 15s.
*   Для >1000 целей или интервала <10s рекомендуется 2+ cores и 256 MiB RAM.
*   Сеть: доступность целевых портов (обычно 80, 443, 53, 5432 и др.) из хоста, где размещен экспортер.

### Программные требования

*   ОС: Linux (Debian/Ubuntu, RHEL/CentOS, Alpine) или любая ОС, поддерживающая контейнеризацию.
*   Права: доступ для установки бинарника в `/usr/local/bin` и создания пользователя `blackbox`. Для ICMP — возможность установки `cap_net_raw`.
*   Инструменты: `curl`, `dig` или `nslookup` для диагностики DNS, `nc` или `telnet` для проверки TCP-портов.

### Проверка среды перед установкой

```bash
# Проверка разрешения DNS (экспортер должен резолвить имена целей)
dig +short example.com

# Проверка TCP-соединения к цели
nc -zv target-host 443

# Проверка доступности порта 9115 (если экспортер уже запущен)
curl -s -o /dev/null -w "%{http_code}" http://localhost:9115/metrics
# → 200
```

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

# Проверка установленной capability
getcap /usr/local/bin/blackbox_exporter
# → /usr/local/bin/blackbox_exporter cap_net_raw+ep
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
RestartSec=5s
# Capabilities для работы ICMP под пользователями
AmbientCapabilities=CAP_NET_RAW

[Install]
WantedBy=multi-user.target
```

**Включение и запуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now blackbox_exporter

# Проверка статуса
systemctl status blackbox_exporter
# → active (running)

# Просмотр логов в реальном времени
journalctl -u blackbox_exporter -f
```

**Жёсткая маршрутизация логов (опционально):**
```ini
# /etc/systemd/system/blackbox_exporter.service
[Service]
# Ограничение размера логов
LogRateLimitIntervalSec=1s
LogRateLimitBurst=10000

# Запись в отдельный файл
StandardOutput=journal
StandardError=journal
SyslogIdentifier=blackbox_exporter
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
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9115/metrics"]
      interval: 30s
      timeout: 5s
      retries: 3
```

**Запуск:**
```bash
docker compose up -d blackbox

# Проверка статуса
docker compose ps blackbox
# → blackbox_exporter  running

# Просмотр логов
docker compose logs -f blackbox
```

**Podman Compose (совместимость):**
```bash
# Podman поддерживает Compose Spec, большинство файлов работают как есть
podman compose up -d blackbox

# Проверка capability (Podman часто использует rootless-режим)
podman exec blackbox_exporter getcap /bin/blackbox_exporter
```

### 3. Развёртывание в Kubernetes через Helm

Рекомендуемый метод для управления в K8s.

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
# Установка с базовыми настройками
helm install blackbox prometheus-community/prometheus-blackbox-exporter
```

**Расширенная конфигурация через `values.yaml`:**
```yaml
# values.yaml
prometheus:
  prometheusSpec:
    serviceMonitor:
      namespace: monitoring
      enabled: true
      additionalLabels:
        release: prometheus

config:
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
    icmp_ping:
      prober: icmp
      timeout: 3s
      icmp:
        preferred_ip_protocol: "ip4"
        ip_protocol_fallback: true
```

```bash
helm install blackbox prometheus-community/prometheus-blackbox-exporter \
  -f values.yaml \
  --namespace monitoring --create-namespace
```

#### Развёртывание через Flux HelmRelease (GitOps)

В GitOps-подходе (Flux CD) развёртывание blackbox exporter выполняется через `HelmRelease` — декларативный CRD, управляемый `helm-controller`. Манифесты хранятся в Git и применяются автоматически, исключяя ручные `helm install`.

**Расположение в репозитории:**
- `HelmRelease` — в слое `base/monitoring/exporters/blackbox-exporter/`
- `Probe` и `PrometheusRule` — в слое `spoke/monitoring/` (отдельная Kustomization `dev-monitoring-spoke`)

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: blackbox-exporter
  namespace: observability
spec:
  chart:
    spec:
      chart: prometheus-blackbox-exporter
      version: ">= 11.0.0"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
  interval: 1h
  values:
    config:
      modules:
        http_2xx:
          prober: http
          timeout: 10s
          http:
            valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
            valid_status_codes: [200, 301, 302]
            follow_redirects: true
            tls_config:
              insecure_skip_verify: false
        http_2xx_insecure:
          prober: http
          timeout: 10s
          http:
            valid_status_codes: [200]
            tls_config:
              insecure_skip_verify: true
        tcp_connect:
          prober: tcp
          timeout: 5s
    serviceMonitor:
      enabled: true
      labels:
        release: kube-prom-stack  # должен совпадать с serviceMonitorSelector в ресурсе Prometheus
```

Два HTTP-модуля: `http_2xx` для эндпоинтов с публичными сертификатами и `http_2xx_insecure` для внутренних сервисов с самоподписанными сертификатами. Подробнее о модулях: [Конфигурация модулей](./blackbox_exporter_modules_configuration.md).

> **Версия чарта:** Текущая версия `prometheus-blackbox-exporter` — 11.20.0 (октябрь 2026), `appVersion` `v0.28.0`. Ограничение `>= 11.0.0` согласуется с текущей линией версий. В production рекомендуется pinning конкретной версии.

#### Порядок развёртывания: отдельная Kustomization для мониторинга

Объекты `Probe` и `PrometheusRule` зависят от CRD `Probe`, который устанавливается вместе с `kube-prom-stack`. Если Kustomization мониторинга запустится одновременно с базовым слоем (`dev-spoke`), объекты `Probe` могут быть применены до создания CRD — это вызовит ошибку реконсиляции (`probe.monitoring.coreos.com not found`).

Параметр `dependsOn` в ресурсе `Kustomization` (Flux CD) формирует детерминированный граф развертывания: зависимый объект не начнёт реконсиляцию, пока родительский не перейдёт в `Ready=True`.

```yaml
# Kustomization dev-monitoring-spoke
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: dev-monitoring-spoke
  namespace: flux-system
spec:
  interval: 10m
  path: ./fluxcd/projects/dev/kustomization/spoke/monitoring/
  dependsOn:
    - name: dev-spoke
      namespace: dev
  sourceRef:
    kind: GitRepository
    name: fleet-infra
```

Это гарантирует, что слой `spoke/monitoring/` (включая установку `kube-prom-stack` через `dev-spoke`) применяется **до** создания `Probe` и `PrometheusRule`. Подробнее о `dependsOn`: [Flux — обзор и ключевые концепции](../../../GitOps/flux.md).

#### Отладка ошибок проб через port-forward

Для отладки обращайтесь к blackbox exporter напрямую через `port-forward`, чтобы увидеть, что именно он возвращает:

```bash
# Проверить URL через модуль http_2xx
kubectl port-forward -n observability svc/blackbox-exporter 9115:9115
curl "http://localhost:9115/probe?module=http_2xx&target=https://example.com"

# Проверить внутренний TCP-endpoint через модуль tcp_connect
curl "http://localhost:9115/probe?module=tcp_connect&target=elasticsearch-master.elasticsearch.svc.cluster.local:9200"
```

Вывод — сырой Prometheus text format. `probe_success 1` — проверка прошла, `probe_success 0` — нет, остальные метрики объясняют причину.

### 4. Интеграция с Prometheus Operator (Probe CRD)

Для интеграции с **Prometheus Operator** используется ресурс `Probe`:
```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: external-website-check
  namespace: monitoring
spec:
  jobName: blackbox-http
  module: http_2xx
  prober:
    url: blackbox-exporter.monitoring.svc.cluster.local:9115
  targets:
    staticConfig:
      static:
        - https://prometheus.io
        - https://api.example.com
  interval: 30s
  timeout: 10s
  labels:
    env: production
```

### 5. Настройка безопасности (web-config.yml)

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

**Генерация пароля:**
```bash
# Установка apache2-utils (Debian/Ubuntu)
sudo apt install apache2-utils
htpasswd -nB admin
# → Введите пароль, скопируйте хеш в web-config.yml
```

**Запуск с файлом безопасности:**
```bash
blackbox_exporter --web.config.file=/etc/blackbox_exporter/web-config.yml
```

**Проверка защиты:**
```bash
# Без авторизации — должен вернуть 401
curl -s -o /dev/null -w "%{http_code}" http://localhost:9115/metrics
# → 401

# С авторизацией — 200
curl -s -u admin:password -o /dev/null -w "%{http_code}" http://localhost:9115/metrics
# → 200
```

### Автоматическое управление TLS через cert-manager (Kubernetes)

Для автоматической выдачи и ротации TLS-сертификатов используйте cert-manager:

**1. Создание Certificate (Issuer + Certificate):**

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: blackbox-exporter-issuer
  namespace: monitoring
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: blackbox-exporter-tls
  namespace: monitoring
spec:
  secretName: blackbox-exporter-tls
  issuerRef:
    name: blackbox-exporter-issuer
  dnsNames:
    - blackbox-exporter.monitoring.svc.cluster.local
    - blackbox-exporter.monitoring.svc
  duration: 2160h    # 90 дней
  renewBefore: 360h  # Обновление за 15 дней до истечения
```

**2. Монтирование сертификата в Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: blackbox-exporter
  namespace: monitoring
spec:
  replicas: 2
  selector:
    matchLabels:
      app: blackbox-exporter
  template:
    spec:
      containers:
        - name: blackbox
          image: prom/blackbox-exporter:v0.28.0
          args:
            - "--config.file=/etc/blackbox_exporter/blackbox.yml"
            - "--web.config.file=/etc/blackbox_exporter/web-config.yml"
            - "--config.enable-auto-reload"
          ports:
            - containerPort: 9115
          volumeMounts:
            - name: tls-certs
              mountPath: /etc/blackbox_exporter/tls
              readOnly: true
            - name: config
              mountPath: /etc/blackbox_exporter/blackbox.yml
              subPath: blackbox.yml
            - name: web-config
              mountPath: /etc/blackbox_exporter/web-config.yml
              subPath: web-config.yml
      volumes:
        - name: tls-certs
          secret:
            secretName: blackbox-exporter-tls
        - name: config
          configMap:
            name: blackbox-config
        - name: web-config
          configMap:
            name: blackbox-web-config
```

**3. web-config.yml с сертификатами cert-manager:**

```yaml
# /etc/blackbox_exporter/web-config.yml
tls_server_config:
  cert_file: /etc/blackbox_exporter/tls/tls.crt
  key_file: /etc/blackbox_exporter/tls/tls.key
  client_auth_type: RequireAndVerifyClientCert
  client_ca_file: /etc/blackbox_exporter/tls/ca.crt

basic_auth_users:
  monitoring: "$2y$12$..."
```

**Проверка автоматической ротации:**
```bash
# Статус сертификата
kubectl get certificate -n monitoring
# → blackbox-exporter-tls   True   blackbox-exporter-tls   20h

# Проверка даты истечения
kubectl get secret blackbox-exporter-tls -n monitoring -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -dates
# → notAfter=Sep 15 12:00:00 2026 GMT
```

## Интеграция с Prometheus (scrape config)

Поскольку адрес цели передается как параметр, в конфигурации Prometheus используется механизм `relabel_configs` для динамической подмены адреса скрейпинга:

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
        replacement: 127.0.0.1:9115

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
        replacement: 127.0.0.1:9115
```

**Интеграция с Kubernetes Service Discovery:**
```yaml
scrape_configs:
  - job_name: 'kubernetes-services-blackbox'
    metrics_path: /probe
    params:
      module: [http_2xx]
    kubernetes_sd_configs:
      - role: service
    relabel_configs:
      - source_labels: [__meta_kubernetes_service_annotation_blackbox_exporter]
        regex: true
        action: keep
      - source_labels: [__meta_kubernetes_service_annotation_blackbox_exporter_module]
        target_label: __param_module
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: blackbox-exporter.monitoring.svc.cluster.local:9115
```

## Проверка работоспособности (Ad-hoc)

После запуска можно выполнить ручную проверку через `curl`:
```bash
# Проверка доступности сайта через модуль http_2xx
curl "http://localhost:9115/probe?target=google.com&module=http_2xx"
# → probe_success 1

# Проверка DNS-резолвинга
curl "http://localhost:9115/probe?target=8.8.8.8&module=dns_google"
# → probe_success 1

# Проверка TCP-порта
curl "http://localhost:9115/probe?target=example.com:443&module=tcp_connect"
# → probe_success 1

# Проверка внутренних метрик экспортера
curl -s http://localhost:9115/metrics | grep -E "blackbox_|up"
# → blackbox_exporter_build_info{...} 1
# → blackbox_exporter_config_last_reload_successful 1
# → up 1
```

## Жёсткие требования и ограничения

### ICMP в контейнерах

При работе в Docker или Podman ICMP требует явного включения capability:
```yaml
cap_add:
  - NET_RAW
```
В Kubernetes для Pod Security Standards (restricted) используйте `securityContext.capabilities.add: ["NET_RAW"]`.

### Таймауты

Таймаут в модуле (`timeout` в `blackbox.yml`) должен быть **меньше**, чем `scrape_timeout` в конфигурации Prometheus. Рекомендуемая разница — 500мс-1с. Например, если `scrape_timeout: 10s`, используйте `timeout: 9s` в модуле.

### Проксирование HTTP-запросов

Blackbox Exporter поддерживает переменные окружения `HTTP_PROXY`, `HTTPS_PROXY` и `NO_PROXY` для маршрутизации HTTP-проверок через прокси. Конфигурация прокси в `blackbox.yml` отсутствует.

## Лучшие практики

*   **Размещение:** Размещайте экспортер в той же сети, что и большинство целей. Для внешних проверок используйте географически распределенные инстансы.
*   **Масштабирование:** Один инстанс может обслуживать тысячи целей, но ограничьте частоту проверок до разумного минимума (обычно 15s, 30s или 60s) чтобы не создавать DDoS-эффект.
*   **Безопасность:**
    *   Никогда не открывайте порт 9115 в публичную сеть без TLS и Basic Auth.
    *   Используйте `web-config.yml` с валидными сертификатами.
    *   Ограничьте доступ на уровне фаерволла только IP Prometheus.
*   **Таймауты:** Всегда настраивайте `timeout` в модуле меньше, чем `scrape_timeout` в Prometheus.
*   **Мониторинг самого экспортера:** Добавьте в Prometheus проверку эндпоинта `/metrics` экспортера с помощью `up{job="blackbox_exporter"}`.
*   **Версионирование конфигурации:** Храните `blackbox.yml` в системе контроля версий (Git). При использовании `--config.enable-auto-reload` убедитесь, что ошибки конфигурации не приводят к падению экспортера.

## Типичные проблемы и их решение

1.  **Ошибка `socket: permission denied`**: Недостаточно прав для ICMP. Убедитесь, что выполнена команда `setcap` или в контейнере добавлен `cap_add: [NET_RAW]`.
2.  **Ошибка `Invalid module`**: Модуль, указанный в параметре `module`, отсутствует в файле `blackbox.yml`.
3.  **Несоответствие таймаутов**: Таймаут в модуле (`timeout` в `blackbox.yml`) должен быть **меньше**, чем `scrape_timeout` в конфигурации Prometheus.
4.  **DNS-резолвинг не работает**: Проверьте `/etc/resolv.conf` в контейнере или на хосте.
5.  **TLS-ошибки**: Убедитесь, что целевой сервер поддерживает TLS 1.2+, кор rectный SNI передаётся через `server_name`.
6.  **Метрики `probe_success` постоянно `0` при доступном сервисе**: Проверьте, что модуль соответствует протоколу цели, и включены `follow_redirects: true` для HTTP.

## Очистка и деинсталляция

### systemd

```bash
sudo systemctl stop blackbox_exporter
sudo systemctl disable blackbox_exporter
sudo rm /etc/systemd/system/blackbox_exporter.service
sudo rm /usr/local/bin/blackbox_exporter
sudo rm -rf /etc/blackbox_exporter
sudo userdel blackbox
sudo systemctl daemon-reload
```

### Docker Compose

```bash
docker compose down blackbox
docker volume rm <project>_blackbox_data # если использовались volumes
```

### Kubernetes (Helm)

```bash
helm uninstall blackbox -n monitoring
kubectl delete probe --all -n monitoring # если создавались ресурсы Probe
```
