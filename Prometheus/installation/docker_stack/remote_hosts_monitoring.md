# Мониторинг удалённых хостов из Docker Stack

## Определения

**Мониторинг удалённых хостов** — это конфигурация, при которой центральный сервер Prometheus (запущенный в Docker Stack) собирает метрики с экспортеров (Node Exporter, cAdvisor), развёрнутых на внешних серверах или виртуальных машинах. В контексте Docker Stack речь идёт о сборе метрик с хостов, не входящих в локальный Compose-проеккт, но доступных по сети.

**Scrape (Сбор)** — процесс периодического опроса HTTP-эндпоинтов удалённых узлов. В Prometheus v3 поддерживается высокоэффективный сбор с использованием Native Histograms, OpenMetrics-протокола, Protobuf-кодирования и сжатие трафика.

**Service Discovery (SD)** — механизм автоматического обнаружения таргетов. Для удалённых хостов используются: `static_configs` (фиксированный список), `file_sd_configs` (файлы целей), `http_sd_configs` (внешний API инвентаризации), `relabel_configs` (трансформация меток на этапе сбора).

**Pull-модель** — Prometheus инициирует соединения к экспортёрам. Это предполагает, что экспортёры доступны из сети сервера мониторинга. Требует настройки firewall и сетевой маршрутизации на стороне удалённых хостов.

**Push-модель** — данные отправляются экспортёром или агентом на центральный сервер. В контексте удалённых хостов используется через Prometheus Agent + Remote Write 2.0, когда прямой Pull невозможен из-за сетевых ограничений.

**Basic Auth / mTLS / OAuth2** — механизмы аутентификации и авторизации на эндпоинтах экспортёров. Prometheus v3 поддерживает `basic_auth`, `tls_config` (включая mTLS), `authorization`, `oauth2` и `credentialsFile` для хранения секретов вне YAML.

**credentialsFile** — механизм Prometheus v3 для вынесения паролей и токенов из YAML во внешние файлы, что исключает попадание секретов в `/-/config` и репозитории.

**Scrape timeout** — максимальное время ожидания ответа от экспортёра. Должен быть минимум на 2–3 секунды меньше `scrape_interval`, чтобы дать запас на сетевые задержки и обработку.

**Native Histograms** — разреженные гистограммы Prometheus v3, снижающие объём хранимых данных и ускоряющие запросы. Включаются параметром `scrape_native_histograms: true`.

> **См. также:** [Node Exporter установка](../node_exporter_installation.md), [Prometheus config для Docker Stack](./prometheus_config.md).

## Основные концепции

### Архитектура взаимодействия

Центральный сервер мониторинга инициирует соединения с удалёнными хостами. Это требует настройки сетевой доступности и безопасности на стороне каждого узла. В контексте Docker Stack Prometheus работает внутри контейнера и использует встроенный DNS для разрешения имён; при работе с удалёнными хостами DNS-имена заменяются на IP-адреса или FQDNs, а безопасность обеспечивается на уровне сети и транспортного слоя.

```text
┌──────────────────────────────────────────────┐
│   Центральный сервер мониторинга (Docker)     │
│  ┌──────────────────────────────────────┐    │
│  │  Prometheus v3.13.x                   │    │
│  │  scrape (9100) ─▶ Remote Host 1       │────┼──▶ Node Exporter
│  │  scrape (8080) ─▶ Remote Host 1       │────┼──▶ cAdvisor
│  │  scrape (9100) ─▶ Remote Host 2       │────┼──▶ Node Exporter
│  │  scrape (443)  ─▶ Remote Host 3 (mTLS)│────┼──▶ Node Exporter (TLS)
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
          │                      │
          ▼                      ▼
   ┌──────────────┐      ┌──────────────┐
   │ Remote Host 1│      │ Remote Host 2│
   │ Node Exporter│      │ Node Exporter│
   │ cAdvisor     │      │ cAdvisor     │
   └──────────────┘      └──────────────┘
```

### Топологии сети

Выбор топологии зависит от политик безопасности, наличия публичного IP и сегментации сети:

| Топология | Применение | Особенности |
|---|---|---|
| **Прямой доступ** | Хосты в той же L2/L3 сети, без NAT | Простейшая конфигурация; требуется только firewall на удалённом хосте |
| **Jump Host (Bastion)** | Удалённые хосты за NAT или в другой подсети | Prometheus обращается к jump-хосту, который пробрасывает порты или проксирует запросы |
| **Reverse SSH tunnel** | Прокси-недоступность, строгий inbound firewall | Удалённый хост сам устанавливает соединение к серверу мониторинга и пробрасывает локальный порт |
| **WireGuard / IPsec** | Публичные сети, требующие шифрования L3 | Требует настройки VPN-туннеля между хостами; трафик метрик идёт через зашифрованный канал |
| **Prometheus Agent + Remote Write** | Нестабильные каналы, высокая кардинальность | Локальный Prometheus на хосте собирает метрики и отправляет их через Remote Write 2.0; центральный сервер принимает данные |

**Важно:** Prometheus сам по себе не является agent-ориентированной системой; для использования Agent Mode требуется отдельный запуск с флагом `--enable-feature=agent` и настройка `remote_write`. Подробнее: [Prometheus Remote Read/Write](../../scaling/remote_read_write.md).

### Требования к сети и безопасности

Для успешного сбора метрик сервер мониторинга должен иметь доступ к портам экспортёров. Рекомендуется ограничивать доступ на уровне IP-адресов и использовать TLS/mTLS для шифрования трафика.

| Порт | Сервис | Протокол | Направление | Назначение |
|---|---|---|---|---|
| 9100 | Node Exporter | TCP | monitoring → remote | Метрики ОС (CPU, RAM, Disk) |
| 8080 | cAdvisor | TCP | monitoring → remote | Метрики контейнеров Docker |
| 9090 | Prometheus (self) | TCP | monitoring → monitoring | Self-monitoring и federation |
| 443 | Node Exporter (TLS) | TCP | monitoring → remote | Метрики через HTTPS (рекомендуется для внешних сетей) |

### Предварительные требования

Перед настройкой убедитесь, что выполнены следующие условия:

**На сервере мониторинга (центральный Prometheus):**
- Prometheus v3.13.x запущен в Docker Stack с настроенной сетью `monitoring-net`
- Доступ к маршрутизатору и DNS для разрешения имён удалённых хостов (если используются FQDNs)
- Открытые исходящие порты `9100/tcp`, `8080/tcp`, `443/tcp` на фаerbоле сервера
- Достаточно места в TSDB: оцените кардинальность метрик (примерно 15–30 KB/sample на хост с Node Exporter + cAdvisor при стандартном наборе метрик)

**На удалённых хостах:**
- ОС Linux с kernel 5.4+ (для корректной работы cAdvisor и node-exporter)
- Docker Engine 24.x+ (если используется развёртывание через Compose)
- Доступ по SSH для первоначальной настройки (порт 22/tcp)
- Права `root` или `sudo` для создания правил firewall и установки пакетов
- Достаточно ресурсов: каждый экспортёр потребляет 10–50 MB RAM и 0.1–0.5 CPU; cAdvisor может потреблять до 200 MB RAM при большом количестве контейнеров

**Настройка Firewall на удалённых хостах:**

```bash
# UFW (Ubuntu/Debian)
# Разрешить доступ только с IP-адреса сервера мониторинга (например, 1.2.3.4)
sudo ufw allow from 1.2.3.4 to any port 9100 proto tcp
sudo ufw allow from 1.2.3.4 to any port 8080 proto tcp

# iptables (универсальный)
sudo iptables -A INPUT -p tcp -s 1.2.3.4 --dport 9100 -j ACCEPT
sudo iptables -A INPUT -p tcp -s 1.2.3.4 --dport 8080 -j ACCEPT

# Сохранение правил (Debian/Ubuntu)
sudo netfilter-persistent save

# Проверка
sudo iptables -L INPUT -n -v | grep -E '9100|8080'
```

## Развёртывание экспортёров на удалённых хостах

### Node Exporter (Docker Compose)

На удалённом хосте рекомендуется использовать актуальный образ Node Exporter v1.12.1 в production-ready конфигурации с security hardening.

```yaml
# remote-host/compose.yml
version: '3.8'

services:
  node-exporter:
    image: prom/node-exporter:v1.12.1
    container_name: node-exporter
    pid: host
    network_mode: host
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=128m
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
      - '--web.config.file=/etc/node-exporter/web-config.yml'
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
        reservations:
          cpus: '0.1'
          memory: 64M
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9100/metrics"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

**Объяснение параметров безопасности:**
- `user: "65534:65534"` — запуск от непривилегированного пользователя nobody
- `cap_drop: [ALL]` — отзыв всех Linux capabilities
- `security_opt: no-new-privileges:true` — запрет на повышение привилегий
- `read_only: true` — файловая система контейнера только для чтения
- `tmpfs: /tmp:noexec,nosuid` — временная файловая система в памяти без выполнения бинарников
- `pid: host` — требуется для доступа к PID хоста; не может быть заменён без потери метрик

### cAdvisor (Docker Compose)

cAdvisor требует доступа к Docker socket и предоставляет метрики контейнеров. Production-ready конфигурация:

```yaml
  cadvisor:
    image: ghcr.io/google/cadvisor:v0.60.5
    container_name: cadvisor
    pid: host
    network_mode: host
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=256m
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
    command:
      - '--housekeeping_interval=30s'
      - '--max_housekeeping_interval=60s'
      - '--event_storage_event_limit=10'
      - '--event_storage_age_limit=60s'
      - '--disable_metrics=cgroup,referenced_memory,tcp,advtcp,sched,percpu,disk,diskIO'
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.1'
          memory: 128M
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

**Важно:** Монтирование `/var/run:/var/run:ro` даёт cAdvisor доступ к `docker.sock` только для чтения. При использовании `read_only: true` убедитесь, что cAdvisor не пытается записать данные в корневую ФС. Параметр `--disable_metrics` позволяет отключить неиспользуемые коллекторы и снизить нагрузку.

### Альтернатива: systemd service (bare-metal)

Если Docker на удалённом хосте нежелателен, используйте systemd unit:

```ini
# /etc/systemd/system/node-exporter.service
[Unit]
Description=Prometheus Node Exporter
After=network-online.target
Wants=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
ExecStart=/usr/local/bin/node_exporter \
  --path.procfs=/host/proc \
  --path.sysfs=/host/sys \
  --path.rootfs=/rootfs \
  --collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/) \
  --web.config.file=/etc/node-exporter/web-config.yml
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Ограничения ресурсов (cgroup v2)
CPUQuota=50%
MemoryMax=256M

[Install]
WantedBy=multi-user.target
```

Примените конфигурацию:

```bash
# Создание пользователя
sudo useradd --no-create-home --shell /usr/sbin/nologin node_exporter

# Установка бинарника
curl -sL https://github.com/prometheus/node_exporter/releases/download/v1.12.1/node_exporter-1.12.1.linux-amd64.tar.gz | tar xz
sudo cp node_exporter-1.12.1.linux-amd64/node_exporter /usr/local/bin/
sudo chown node_exporter:node_exporter /usr/local/bin/node_exporter

# Монтирование proc/sys/rootfs
sudo mkdir -p /host/proc /host/sys /host/rootfs
sudo mount --bind /proc /host/proc
sudo mount --bind /sys /host/sys
sudo mount --bind / /host/rootfs

# Включение и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now node-exporter
```

## Практические сценарии

### Сценарий 1: static_configs и Native Histograms

Подходит для небольших стабильных сред. Включение `scrape_native_histograms` позволяет использовать преимущества Prometheus v3 для точного анализа распределений.

```yaml
# prometheus/prometheus.yml
scrape_configs:
  - job_name: 'remote-nodes'
    scrape_interval: 15s
    scrape_timeout: 10s
    scrape_native_histograms: true # Включение поддержки v3 гистограмм
    static_configs:
      - targets:
          - '192.168.1.101:9100'
          - '192.168.1.102:9100'
        labels:
          env: 'production'
          site: 'dc-west'

  - job_name: 'remote-cadvisor'
    scrape_interval: 20s
    scrape_timeout: 15s
    static_configs:
      - targets:
          - '192.168.1.101:8080'
          - '192.168.1.102:8080'
        labels:
          env: 'production'
```

### Сценарий 2: file_sd_configs (Гибкое управление)

Позволяет изменять список хостов без перезагрузки и изменения основного конфига Prometheus. Prometheus проверяет директорию каждые 2 минуты (по умолчанию) и подгружает новые/удалённые таргеты автоматически.

**1. Создайте файл целей `prometheus/targets/remote-nodes.yml`:**
```yaml
- targets:
    - '192.168.1.101:9100'
    - '192.168.1.102:9100'
  labels:
    env: 'production'
    role: 'app-server'
```

**2. Настройте `prometheus.yml` для сканирования директории:**
```yaml
scrape_configs:
  - job_name: 'remote-nodes'
    file_sd_configs:
      - files:
          - '/etc/prometheus/targets/*.yml'
        refresh_interval: 2m
```

### Сценарий 3: http_sd_config (Modern Discovery)

Современный способ интеграции с внешними системами инвентаризации (CMDB, Ansible, Terraform). HTTP SD эндпоинт должен возвращать JSON в формате Prometheus.

```json
[
  {
    "targets": ["192.168.1.101:9100", "192.168.1.102:9100"],
    "labels": {
      "env": "production",
      "role": "app-server"
    }
  }
]
```

Конфигурация в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'inventory-api-sd'
    http_sd_configs:
      - url: 'http://inventory.local:8080/api/v1/prometheus/targets'
        refresh_interval: 5m
        basic_auth:
          username: 'prometheus-read'
          password: '${INVENTORY_API_PASSWORD}'
```

### Сценарий 4: Защита эндпоинтов (Basic Auth + TLS)

**1. Настройка на удалённом хосте (`/etc/node-exporter/web-config.yml`):**

```yaml
basic_auth_users:
  prom_user: "$2y$10$h.p.V..." # bcrypt хэш
tls_server_config:
  cert_file: /etc/node-exporter/certs/server.crt
  key_file: /etc/node-exporter/certs/server.key
  client_ca_file: /etc/node-exporter/certs/ca.crt
  client_auth_type: RequireAndVerifyClientCert # mTLS
```

Запуск экспортера: `./node_exporter --web.config.file=/etc/node-exporter/web-config.yml`

**2. Настройка в Prometheus (поддержка переменных окружения в v3):**

```yaml
scrape_configs:
  - job_name: 'secure-remote'
    scrape_interval: 15s
    scrape_timeout: 10s
    basic_auth:
      username: 'prom_user'
      password: '${SCRAPE_PASSWORD}'
    tls_config:
      ca_file: '/etc/prometheus/certs/ca.crt'
      cert_file: '/etc/prometheus/certs/client.crt'
      key_file: '/etc/prometheus/certs/client.key'
      insecure_skip_verify: false # Не отключайте в production
    static_configs:
      - targets: ['192.168.1.101:443']
        labels:
          env: 'production'
          tls: 'enabled'
```

**Альтернатива: credentialsFile (Prometheus v3):**

```yaml
scrape_configs:
  - job_name: 'secure-remote-v3'
    basic_auth:
      username: 'prom_user'
      password: credentialsFile("/run/secrets/scrape-password")
    static_configs:
      - targets: ['192.168.1.101:443']
```

Файл `/run/secrets/scrape-password` должен содержать только пароль без символов новой строки, с правами `600` и владельцем `prometheus:prometheus`.

### Сценарий 5: Scrape Protocols (OpenMetrics / Protobuf)

Prometheus v3 поддерживает несколько протоколов сбора данных. Для удалённых хостов с высокой кардинальностью рекомендуется использовать Protobuf для снижения нагрузки на сеть и CPU.

```yaml
scrape_configs:
  - job_name: 'remote-nodes-protobuf'
    scrape_protocols:
      - OpenMetricsText1_0_0
      - Protobuf
    scrape_interval: 15s
    scrape_timeout: 10s
    static_configs:
      - targets: ['192.168.1.101:443']
```

**Приоритет протоколов:** Prometheus пробует первый указанный протокол; если экспортёр его не поддерживает, переходит к следующему. `OpenMetricsText1_0_0` обеспечивает совместимость со старыми экспортёрами, `Protobuf` даёт максимальную производительность.

### Сценарий 6: Blackbox Exporter (Synthetic Monitoring)

Для проверки доступности эндпоинтов и HTTP-availability используйте Blackbox Exporter на удалённом хосте или центральном сервере.

```yaml
# remote-host/blackbox-compose.yml
services:
  blackbox-exporter:
    image: prom/blackbox-exporter:v0.25.0
    container_name: blackbox-exporter
    network_mode: host
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=64m
    volumes:
      - ./blackbox.yml:/config/blackbox.yml:ro
    command:
      - '--config.file=/config/blackbox.yml'
    restart: unless-stopped
```

Конфигурация модулей (`blackbox.yml`):

```yaml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
      valid_status_codes: [200, 301, 302]
  tcp_connect:
    prober: tcp
    timeout: 5s
  icmp:
    prober: icmp
    timeout: 5s
    icmp:
      preferred_network: ip4
```

Конфигурация scrape в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'blackbox-remote'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - http://192.168.1.101:9100/metrics
          - http://192.168.1.102:9100/metrics
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - target_label: __address__
        replacement: 192.168.1.101:9115 # Адрес blackbox-exporter
```

## Продвинутый Relabeling

Используйте для нормализации имен инстансов и фильтрации данных на этапе сбора. Для удалённых хостов особенно важно унифицировать лейблы `instance`, `site` и `hostname`, чтобы дашборды и алерты работали единообразно.

```yaml
scrape_configs:
  - job_name: 'remote-nodes'
    file_sd_configs:
      - files: ['/etc/prometheus/targets/*.yml']
    relabel_configs:
      # Убираем порт из метки instance для чистоты дашбордов
      - source_labels: [__address__]
        regex: '([^:]+):.*'
        target_label: instance
        replacement: '${1}'
      # Добавляем префикс к именам в зависимости от подсети
      - source_labels: [instance]
        regex: '10\.(\d+)\.1\.(\d+)'
        target_label: hostname
        replacement: 'srv-prod-${1}-${2}'
      # Фильтруем метрики по региону
      - source_labels: [__meta_dns_name]
        regex: '.*dc-east\\.corp\\.local.*'
        target_label: dc
        replacement: 'east'
      # Исключаем нежелательные метрики на этапе сбора
      - source_labels: [__name__]
        regex: 'go_.*'
        target_label: __metrics_path__
        replacement: ''
        action: drop
```

### Метрики и кардинальность для удалённых хостов

Стандартный набор метрик от Node Exporter + cAdvisor на одном хосте составляет 4 000–8 000 временных рядов. При масштабировании на 100 хостов это даёт 400 000–800 000 рядов. Для контроля кардинальности используйте:

- `sample_limit` — лимит семплов на один scrape
- `label_limit` — лимит лейблов на одну метрику
- `target_limit` — лимит таргетов в job
- `metric_relabel_configs` — удаление нежелательных метрик на этапе ingest

## Операционные процедуры

### Добавление нового хоста

1. Подготовьте хост: обновите ОС, установите Docker, откройте SSH
2. Разверните экспортёры через Compose или systemd (см. раздел выше)
3. Настройте firewall на хосте
4. Добавьте хост в targets:
   - Для `static_configs`: отредактируйте `prometheus.yml` и перезапустите Prometheus
   - Для `file_sd_configs`: создайте/обновите YAML-файл в `/etc/prometheus/targets/`
   - Для `http_sd_configs`: обновите запись в CMDB/инвентарной системе
5. Проверьте появление таргета в `http://localhost:9090/targets`
6. Проверьте наличие метрик: `up{job="remote-nodes", instance="<new-host>:9100"}`

### Удаление хоста

1. Удалите хост из `static_configs` или файла целей
2. Остановите экспортёры на хосте: `docker compose down` или `systemctl stop node-exporter`
3. Убедитесь, что метрики помечены как `stale` (значение `NaN`) в течение `--query.lookback-delta` (по умолчанию 5 минут)
4. При необходимости выполните `docker volume prune` на удалённом хосте для очистки данных

### Обновление экспортёров (Rolling Update)

Для инфраструктуры с большим количеством хостов выполните обновление пакетно:

```bash
#!/bin/bash
# update-exporters.sh
# Обновление Node Exporter на удалённых хостах

HOSTS=("192.168.1.101" "192.168.1.102" "192.168.1.103")
NEW_VERSION="v1.12.1"

for host in "${HOSTS[@]}"; do
  echo "Updating $host..."
  ssh -o ConnectTimeout=5 root@$host "
    docker compose -f /opt/node-exporter/compose.yml pull &&
    docker compose -f /opt/node-exporter/compose.yml up -d --force-recreate &&
    docker image prune -f
  "
  # Проверка после обновления
  sleep 10
  curl -s -o /dev/null -w "%{http_code}" http://$host:9100/metrics | grep -q '200' && echo "$host: OK" || echo "$host: FAIL"
done
```

### Резервное копирование и восстановление

Создание снапшотов конфигурации на сервере мониторинга:

```bash
# Бэкап targets и правил
tar czf /backup/prometheus_targets_$(date +%F).tar.gz -C /etc/prometheus targets rules

# Бэкап базы данных Prometheus
docker compose stop prometheus
docker run --rm -v monitoring_prometheus_data:/data -v /backup:/backup alpine tar czf /backup/prometheus_data_$(date +%F).tar.gz -C /data ./
docker compose start prometheus
```

Восстановление:

```bash
docker compose stop prometheus
docker run --rm -v monitoring_prometheus_data:/data -v /backup:/backup alpine tar xzf /backup/prometheus_data_2026-09-17.tar.gz -C /data
docker compose up -d prometheus
```

### Валидация подключения

Проверка доступности экспортёров с сервера мониторинга:

```bash
# Проверка порта
nc -zv 192.168.1.101 9100
# → Connection to 192.168.1.101 9100 port [tcp/*] succeeded!

# Проверка эндпоинта метрик
curl -s http://192.168.1.101:9100/metrics | head -n 5
# → # HELP node_cpu_seconds_total ...
# → # TYPE node_cpu_seconds_total counter
# → node_cpu_seconds_total{cpu="0",mode="idle"} 12345.67

# Проверка с TLS
curl -s --cacert /etc/prometheus/certs/ca.crt --cert /etc/prometheus/certs/client.crt --key /etc/prometheus/certs/client.key https://192.168.1.101:443/metrics | head -n 5

# Проверка Basic Auth
curl -s -u prom_user:password http://192.168.1.101:9100/metrics | head -n 5
```

## Устранение неполадок

| Проблема | Причина | Решение |
|---|---|---|
| **Target DOWN (Connection refused)** | Сервис не запущен или неверный порт | Выполните `ss -tunlp | grep 9100` на удаленном хосте. |
| **Target DOWN (No route to host)** | Блокировка Firewall или сетевой сбой | Проверьте правила UFW/iptables и `telnet 1.2.3.4 9100` с сервера мониторинга. |
| **Scrape Timeout** | Высокая сетевая задержка или перегрузка экспортера | Увеличьте `scrape_timeout` (по умолчанию 10s) или проверьте MTU туннеля. |
| **401 Unauthorized** | Неверные данные Basic Auth | Проверьте bcrypt хэш в `web-config.yml` и соответствие пароля в Prometheus. |
| **Метрики отсутствуют в Grafana** | Несоответствие лейблов (job/instance) | Проверьте соответствие меток в конфигурации Prometheus и в PromQL-запросах Grafana. |
| **TLS handshake failure** | Неверный сертификат или CA | Проверьте срок действия сертификатов: `openssl s_client -connect 192.168.1.101:443 -showcerts`. Убедитесь, что `ca.crt` на Prometheus подписан тем же CA. |
| **High cardinality alert** | Слишком много label combinations | Установите `sample_limit`, `label_limit`, `target_limit` в job. Используйте `metric_relabel_configs` для удаления лишних лейблов. |
| **Stale metrics persisting** | `staleNaN` не генерируется | Проверьте `--query.lookback-delta` и `--scrape.interval`; stale-marking происходит через 5 минут без данных. |
| **cAdvisor 0 metrics** | Нет доступа к `docker.sock` | Проверьте монтирование `/var/run:/var/run:ro`. Убедитесь, что Docker daemon запущен. |
| **Scrape fails after host reboot** | systemd unit не стартует автоматически | Проверьте `systemctl is-enabled node-exporter`. Убедитесь, что bind mounts (proc, sys, rootfs) создаются в fstab или скрипте. |
| **Duplicate metrics** | Один и тот же таргет указан в нескольких jobs | Проверьте `target` в `/targets`; используйте `relabel_configs` с `action: drop` или уникальные метки `job`. |
| **Prometheus OOM on remote scrape** | Слишком много хостов или высокая частота | Увеличьте `scrape_interval`, добавьте `sample_limit`, добавьте лимиты памяти в `deploy` Prometheus. |
| **Retention не применяется** | Параметр задан в `prometheus.yml`, а не в CLI | Переместите `--storage.tsdb.retention.time` в `command:` compose-сервиса. |

## Дополнительная информация

### Связанные темы

* [Node Exporter установка](../node_exporter_installation.md) — установка на bare-metal/VM.
* [Конфигурация Prometheus](./prometheus_config.md) — детализация scrape-целей в Docker.
* [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md) — глубокое погружение в SD.
* [Prometheus Remote Read/Write](../../scaling/remote_read_write.md) — передача данных в централизованные хранилища.
* [Безопасность Prometheus](../../security.md) — TLS, mTLS, OAuth2, credential management.
* [Конфигурация Docker Compose](./docker-compose_config.md) — production-ready compose для локального стека.

### Безопасность и масштабирование

1.  **VPN/Туннелирование:** Для передачи метрик через публичные сети используйте WireGuard или IPsec для создания защищённого L3-канала. Tailscale подходит для небольших сред, но не рекомендуется для production из-за зависимостей от внешних координаторов.
2.  **mTLS:** Для Enterprise-сред настройте взаимную аутентификацию по сертификатам (`tls_config`). Генерация сертификатов описана в [Безопасность Prometheus](../../security.md). Ротацию сертификатов автоматизируйте через ACME или Vault PKI.
3.  **Prometheus Agent:** В случае нестабильных каналов установите локальный Prometheus в режиме `Agent` на удалённом хосте. Это обеспечит буферизацию данных и их передачу через Remote Write 2.0 (экономия трафика до 60%). Agent не хранит данные локально и не выполняет запросы, что снижает потребление ресурсов.
4.  **Сетевая сегментация:** Используйте отдельную VLAN или VRF для трафика мониторинга. Применяйте rate limiting на firewall для защиты от DoS-атак на экспортёры.
5.  **Аудит доступа:** Включите аудит входящих соединений на экспортёрах через journald или syslog. Для Node Exporter в Docker используйте `logging:` секцию compose для сбора логов централизованно.
6.  **fail2ban:** Для защиты от брутфорса Basic Auth настройте fail2ban на мониторинг логов nginx/traefik, если экспортёры доступны через reverse proxy.
7.  **Мониторинг самосостояния:** Создайте алерты на `up{job="remote-nodes"} == 0` с задержкой `for: 5m`, чтобы исключить false-positive при перезагрузках хостов. Используйте `absent()` для обнаружения полной потери связи с сайтом.
