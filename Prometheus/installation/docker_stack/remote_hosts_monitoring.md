# Мониторинг удалённых хостов из Docker Stack

## Definitions

**Мониторинг удалённых хостов из Docker Stack** — сценарий, при котором Prometheus запущен в Docker-контейнере на центральном сервере, а экспортеры (Node Exporter, cAdvisor) работают на удалённых машинах. Prometheus собирает метрики по сети через `static_configs` или `file_sd_configs`.

> **См. также:** [Node Exporter установка](../node_exporter_installation.md), [Prometheus config для Docker Stack](./prometheus_config.md).

## Basic Concepts

### Архитектура

```
┌─────────────────────────────────────────────┐
│  Central Monitoring Server (Docker Stack)    │
│  ┌─────────────────────────────────────┐    │
│  │  Prometheus (контейнер)              │    │
│  │  scrape → remote-host-1:9100         │────┼──→ Node Exporter
│  │  scrape → remote-host-2:9100         │────┼──→ Node Exporter
│  │  scrape → remote-host-1:8080         │────┼──→ cAdvisor
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
         │                      │
         ▼                      ▼
  ┌──────────────┐      ┌──────────────┐
  │ remote-host-1│      │ remote-host-2│
  │ Node Exporter│      │ Node Exporter│
  │ cAdvisor     │      │ cAdvisor     │
  └──────────────┘      └──────────────┘
```

### Требования к сети

| Порт | Протокол | Направление | Назначение |
|---|---|---|---|
| 9100 | TCP | monitoring → remote | Node Exporter scrape |
| 8080 | TCP | monitoring → remote | cAdvisor scrape |

**Firewall правила на удалённых хостах:**

```bash
# UFW (Ubuntu)
ufw allow from <MONITORING_SERVER_IP> to any port 9100 proto tcp
ufw allow from <MONITORING_SERVER_IP> to any port 8080 proto tcp

# iptables
iptables -A INPUT -p tcp -s <MONITORING_SERVER_IP> --dport 9100 -j ACCEPT
iptables -A INPUT -p tcp -s <MONITORING_SERVER_IP> --dport 8080 -j ACCEPT
```

### Node Exporter на удалённом хосте

**Docker-способ** (если на удалённом хосте тоже есть Docker):

```yaml
# docker-compose.yml на remote-host
services:
  node-exporter:
    image: prom/node-exporter:v1.10.2
    container_name: node-exporter
    pid: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "9100:9100"
    restart: unless-stopped
    network_mode: host  # Рекомендуется для Node Exporter
```

**Systemd-способ** (без Docker, рекомендуется для production):

```bash
# Установка Node Exporter
# См. полную инструкцию: [Node Exporter установка](../node_exporter_installation.md)

# Запуск
systemctl enable --now node_exporter
```

> **Рекомендация:** Для production-сред предпочтителен systemd-способ — меньше зависимостей, ниже overhead.

## Practical Scenarios

### Способ 1: static_configs (простые среды)

Добавьте IP-адреса удалённых хостов в `prometheus/prometheus.yml` на центральном сервере:

```yaml
scrape_configs:
  - job_name: 'remote-nodes'
    static_configs:
      - targets:
          - '192.168.1.101:9100'
          - '192.168.1.102:9100'
          - '192.168.1.103:9100'
        labels:
          env: production
          role: app-server

  - job_name: 'remote-cadvisor'
    static_configs:
      - targets:
          - '192.168.1.101:8080'
          - '192.168.1.102:8080'
        labels:
          env: production
```

**Перезагрузка Prometheus:**

```bash
# Hot reload (без перезапуска контейнера)
docker exec prometheus wget -q --post-data '' http://localhost:9090/-/reload

# Или restart
docker compose restart prometheus
```

> **Минус:** при изменении списка хостов нужно менять `prometheus.yml` и делать reload.

### Способ 2: file_sd_configs (динамические среды)

`file_sd_configs` позволяет добавлять/удалять хосты без перезагрузки Prometheus — он автоматически перечитывает файл каждые 5 минут.

**На центральном сервере создайте файл `prometheus/targets/remote-nodes.yml`:**

```yaml
- targets:
    - '192.168.1.101:9100'
    - '192.168.1.102:9100'
    - '192.168.1.103:9100'
  labels:
    env: production
    role: app-server
```

**В `prometheus/prometheus.yml`:**

```yaml
scrape_configs:
  - job_name: 'remote-nodes'
    file_sd_configs:
      - files:
          - /etc/prometheus/targets/*.yml
        refresh_interval: 5m
```

**Bind mount в `docker-compose.yml` (добавить к сервису prometheus):**

```yaml
volumes:
  - ./prometheus/targets:/etc/prometheus/targets:ro
```

**Преимущества:**

| Характеристика | static_configs | file_sd_configs |
|---|---|---|
| Изменение targets | Reload Prometheus | Edit файл, auto-discovery через 5m |
| Risk при reload | Есть (ошибка конфига = падение) | Нет (Prometheus не перезапускается) |
| Автоматизация | Сложнее | Легко — Ansible/Cron пишут YAML |

### Способ 3: relabel_configs — обогащение меток

Добавление меток на основе IP-адреса для удобной фильтрации в Grafana:

```yaml
scrape_configs:
  - job_name: 'remote-nodes'
    file_sd_configs:
      - files:
          - /etc/prometheus/targets/*.yml
    relabel_configs:
      # Извлекаем IP из __address__ в метку ip_address
      - source_labels: [__address__]
        regex: '(.+):\d+'
        target_label: ip_address
        replacement: '${1}'
      # Создаём читаемое имя хоста из IP
      - source_labels: [ip_address]
        regex: '192\.168\.1\.(\d+)'
        target_label: hostname
        replacement: 'app-server-${1}'
```

### Проверка подключения

```bash
# С сервера мониторинга — проверка доступности Node Exporter
curl -s http://192.168.1.101:9100/metrics | head -5

# В Prometheus UI — проверка targets
# http://localhost:9090/targets — все remote-цели должны быть UP

# Через API
curl -s 'http://localhost:9090/api/v1/targets?state=active' | \
  jq '.data.active[] | select(.labels.job=="remote-nodes") | {instance, health}'
```

### Troubleshooting

| Проблема | Причина | Решение |
|---|---|---|
| **Target DOWN** | Firewall блокирует порт 9100 | Проверьте `ufw status` на remote, `telnet <IP> 9100` с monitoring |
| **Target DOWN** | Node Exporter не запущен | `systemctl status node_exporter` или `docker ps` на remote |
| **Все target DOWN** | Prometheus не имеет маршрута к сети remote | `ip route`, ping с контейнера: `docker exec prometheus ping <IP>` |
| **Метрики без лейблов** | Нет `labels` в static_configs | Добавьте `env`, `role`, `dc` для фильтрации в Grafana |
| **High cardinality** | Слишком много уника лейблов | Избегайте лейблов с high cardinality (IP, hostname без агрегации) |

## Additional Information

### Связанные темы

* [Node Exporter установка](../node_exporter_installation.md) — установка на bare-metal/VM
* [Prometheus config для Docker Stack](./prometheus_config.md) — scrape-цели, relabeling
* [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md) — file_sd_configs, relabel_configs
* [External monitoring в Kubernetes](../../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/external_monitoring.md) — мониторинг внешних хостов из K8s
* [Blackbox Exporter](../Blackbox_Exporter/index.md) — blackbox-мониторинг (HTTP, TCP, ICMP)
* [cAdvisor](../../Exporters/cadvisor.md) — метрики Docker-контейнеров

### Security-рекомендации

| Мера | Описание |
|---|---|
| **Ограничение по IP** | Разрешайте scrape только с IP сервера мониторинга |
| **mTLS** | Для sensitive-сред используйте `scheme: https` + `tls_config` в scrape_configs |
| **Не expose в internet** | Никогда не открывайте порты 9100/8080 в публичный интернет |
| **VPN/WireGuard** | Для мониторинга через публичные сети используйте VPN-туннель |

**Пример mTLS в scrape_configs:**

```yaml
scrape_configs:
  - job_name: 'remote-nodes-secure'
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/tls/ca.crt
      cert_file: /etc/prometheus/tls/client.crt
      key_file: /etc/prometheus/tls/client.key
    static_configs:
      - targets: ['192.168.1.101:9100']
```
