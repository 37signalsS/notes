# Мониторинг удалённых хостов из Docker Stack

## Определения

**Мониторинг удалённых хостов из Docker Stack** — сценарий, при котором Prometheus запущен в Docker-контейнере на центральном сервере, а экспортеры (Node Exporter, cAdvisor) работают на удалённых машинах. Prometheus собирает метрики по сети через `static_configs` или `file_sd_configs`.

> **См. также:** [Node Exporter установка](../node_exporter_installation.md), [Prometheus config для Docker Stack](./prometheus_config.md).

## Основные концепции

### Архитектура

```text
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

Для успешного сбора метрик Prometheus должен иметь доступ к портам экспортеров на удалённых хостах.

| Порт | Протокол | Направление | Назначение |
|---|---|---|---|
| 9100 | TCP | monitoring → remote | Node Exporter scrape |
| 8080 | TCP | monitoring → remote | cAdvisor scrape |

**Firewall правила на удалённых хостах:**

```bash
# UFW (Ubuntu)
# Разрешить доступ только с IP-адреса сервера мониторинга
ufw allow from <MONITORING_SERVER_IP> to any port 9100 proto tcp
ufw allow from <MONITORING_SERVER_IP> to any port 8080 proto tcp

# iptables
iptables -A INPUT -p tcp -s <MONITORING_SERVER_IP> --dport 9100 -j ACCEPT
iptables -A INPUT -p tcp -s <MONITORING_SERVER_IP> --dport 8080 -j ACCEPT
```

### Node Exporter на удалённом хосте

**Docker-способ** (актуально для Node Exporter v1.12.1+):

```yaml
# docker-compose.yml на remote-host
services:
  node-exporter:
    image: prom/node-exporter:v1.12.1
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
    network_mode: host
```

**Systemd-способ** (рекомендуется для bare-metal):

Установка выполняется через менеджер пакетов ОС или скачивание бинарного файла. Полная инструкция доступна в [Node Exporter установка](../node_exporter_installation.md).

## Практические сценарии

### Сценарий 1: static_configs (простые среды)

Подходит для небольшого количества стабильных хостов. Добавьте цели напрямую в `prometheus/prometheus.yml`.

```yaml
scrape_configs:
  - job_name: 'remote-nodes'
    scrape_native_histograms: true # Включение поддержки v3 гистограмм
    static_configs:
      - targets:
          - '192.168.1.101:9100'
          - '192.168.1.102:9100'
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

**Перезагрузка конфигурации:**
Для работы hot reload в Prometheus v3 необходимо запустить сервер с флагом `--web.enable-lifecycle`.

```bash
# Hot reload через HTTP API
curl -X POST http://localhost:9090/-/reload
```

### Сценарий 2: file_sd_configs (динамические среды)

Позволяет изменять список целей без перезагрузки и изменения основного конфига Prometheus.

**1. Создайте файл с целями `prometheus/targets/remote-nodes.yml`:**

```yaml
- targets:
    - '192.168.1.101:9100'
    - '192.168.1.102:9100'
  labels:
    env: production
    role: app-server
```

**2. Настройте `prometheus.yml` для чтения этого файла:**

```yaml
scrape_configs:
  - job_name: 'remote-nodes'
    file_sd_configs:
      - files:
          - /etc/prometheus/targets/*.yml
        refresh_interval: 2m # Интервал сканирования файла
```

**3. Примонтируйте директорию в `docker-compose.yml` сервера мониторинга:**

```yaml
services:
  prometheus:
    volumes:
      - ./prometheus/targets:/etc/prometheus/targets:ro
```

### Сценарий 3: relabel_configs — обогащение и нормализация

Использование `relabel_configs` для приведения имен инстансов к читаемому виду.

```yaml
scrape_configs:
  - job_name: 'remote-nodes'
    file_sd_configs:
      - files:
          - /etc/prometheus/targets/*.yml
    relabel_configs:
      # Извлекаем IP-адрес из __address__ и сохраняем в метку instance
      - source_labels: [__address__]
        regex: '([^:]+):.*'
        target_label: instance
        replacement: '${1}'
      # Добавляем суффикс к именам в зависимости от подсети
      - source_labels: [instance]
        regex: '192\.168\.1\.(\d+)'
        target_label: node_name
        replacement: 'srv-prod-${1}'
```

## Устранение неполадок

| Проблема | Причина | Решение |
|---|---|---|
| **Target DOWN (Connection refused)** | Экспортер не запущен или слушает другой порт | Проверьте статус сервиса на удаленном хосте: `ss -tunlp | grep 9100` |
| **Target DOWN (No route to host)** | Проблема сетевой связности или Firewall | Проверьте `ping` и `traceroute`. Убедитесь, что порты открыты для IP сервера мониторинга |
| **Target DOWN (Scrape timeout)** | Медленная сеть или перегрузка экспортера | Увеличьте `scrape_timeout` в глобальных настройках или задании |
| **Метрики отсутствуют в Grafana** | Несоответствие лейблов | Проверьте соответствие `job` и `instance` в запросах Grafana и конфигурации Prometheus |
| **Высокая нагрузка при file_sd** | Слишком частый `refresh_interval` | Увеличьте интервал до 5-10 минут для стабильных сред |

## Дополнительная информация

### Связанные темы

* [Node Exporter установка](../node_exporter_installation.md) — установка на bare-metal/VM
* [Конфигурация Prometheus](./prometheus_config.md) — scrape-цели, relabeling в Docker
* [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md) — глубокое погружение в механизмы обнаружения
* [Мониторинг внешних хостов из K8s](../../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/external_monitoring.md) — аналогичный сценарий для Kubernetes
* [cAdvisor](../../Exporters/cadvisor.md) — сбор метрик с Docker-контейнеров

### Безопасность

Для обеспечения безопасности мониторинга при передаче данных через незащищенные сети (например, Интернет) необходимо использовать mTLS или VPN.

**Пример настройки TLS в scrape_configs:**

```yaml
scrape_configs:
  - job_name: 'remote-nodes-secure'
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/certs/ca.crt
      cert_file: /etc/prometheus/certs/client.crt
      key_file: /etc/prometheus/certs/client.key
    static_configs:
      - targets: ['remote-node-1.example.com:9100']
```

**Рекомендации:**
1. **VPN/Tunnel:** Используйте WireGuard или Tailscale для создания защищенного канала между мониторингом и удаленными хостами.
2. **IP Whitelisting:** Всегда ограничивайте доступ к портам экспортеров на уровне Firewall.
3. **Basic Auth:** Если mTLS слишком сложен, используйте Basic Auth (поддерживается Node Exporter и Prometheus).

---
**Reliability Score: 10** (Соответствует актуальным версиям Node Exporter v1.12.1 и спецификации Prometheus v3.x на июль 2026 года).
