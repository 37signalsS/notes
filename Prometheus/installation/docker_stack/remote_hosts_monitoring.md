# Мониторинг удалённых хостов из Docker Stack

## Определения

**Мониторинг удалённых хостов** — это конфигурация, при которой центральный сервер Prometheus (запущенный в Docker Stack) собирает метрики с экспортеров (Node Exporter, cAdvisor), развёрнутых на внешних серверах или виртуальных машинах.

**Scrape (Сбор)** — процесс периодического опроса HTTP-эндпоинтов удалённых узлов. В 2026 году Prometheus v3 поддерживает высокоэффективный сбор с использованием Native Histograms и сжатие трафика.

> **См. также:** [Node Exporter установка](../node_exporter_installation.md), [Prometheus config для Docker Stack](./prometheus_config.md).

## Основные концепции

### Архитектура взаимодействия

Центральный сервер мониторинга инициирует соединения с удалёнными хостами. Это требует настройки сетевой доступности и безопасности на стороне каждого узла.

```text
┌──────────────────────────────────────────────┐
│   Центральный сервер мониторинга (Docker)     │
│  ┌──────────────────────────────────────┐    │
│  │  Prometheus v3.13.x                   │    │
│  │  scrape (9100) ─▶ Remote Host 1       │────┼──▶ Node Exporter
│  │  scrape (8080) ─▶ Remote Host 1       │────┼──▶ cAdvisor
│  │  scrape (9100) ─▶ Remote Host 2       │────┼──▶ Node Exporter
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

### Требования к сети и безопасность

Для успешного сбора метрик сервер мониторинга должен иметь доступ к портам экспортеров. Рекомендуется ограничивать доступ на уровне IP-адресов.

| Порт | Сервис | Протокол | Направление | Назначение |
|---|---|---|---|---|
| 9100 | Node Exporter | TCP | monitoring → remote | Метрики ОС (CPU, RAM, Disk) |
| 8080 | cAdvisor | TCP | monitoring → remote | Метрики контейнеров Docker |

**Настройка Firewall на удалённых хостах:**

```bash
# UFW (Ubuntu/Debian)
# Разрешить доступ только с IP-адреса сервера мониторинга (например, 1.2.3.4)
sudo ufw allow from 1.2.3.4 to any port 9100 proto tcp
sudo ufw allow from 1.2.3.4 to any port 8080 proto tcp

# iptables
sudo iptables -A INPUT -p tcp -s 1.2.3.4 --dport 9100 -j ACCEPT
sudo iptables -A INPUT -p tcp -s 1.2.3.4 --dport 8080 -j ACCEPT
```

### Развёртывание Node Exporter (Docker Compose)

На удалённом хосте рекомендуется использовать актуальный образ Node Exporter v1.12.1.

```yaml
# remote-host/compose.yml
services:
  node-exporter:
    image: prom/node-exporter:v1.12.1
    container_name: node-exporter
    pid: host
    network_mode: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    restart: unless-stopped
```

## Практические сценарии

### Сценарий 1: static_configs и Native Histograms

Подходит для небольших стабильных сред. Включение `scrape_native_histograms` позволяет использовать преимущества Prometheus v3 для точного анализа распределений.

```yaml
# prometheus/prometheus.yml
scrape_configs:
  - job_name: 'remote-nodes'
    scrape_interval: 15s
    scrape_native_histograms: true # Включение поддержки v3 гистограмм
    static_configs:
      - targets:
          - '192.168.1.101:9100'
          - '192.168.1.102:9100'
        labels:
          env: 'production'
          site: 'dc-west'

  - job_name: 'remote-cadvisor'
    static_configs:
      - targets:
          - '192.168.1.101:8080'
          - '192.168.1.102:8080'
        labels:
          env: 'production'
```

### Сценарий 2: file_sd_configs (Гибкое управление)

Позволяет изменять список хостов без перезагрузки и изменения основного конфига Prometheus.

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

В 2026 году это основной способ интеграции с внешними системами инвентаризации.

```yaml
scrape_configs:
  - job_name: 'inventory-api-sd'
    http_sd_configs:
      - url: 'https://inventory.local/api/v1/prometheus/targets'
        refresh_interval: 5m
```

### Сценарий 4: Защита эндпоинтов (Basic Auth)

**1. Настройка на удалённом хосте (`web-config.yml`):**
```yaml
basic_auth_users:
  prom_user: "$2y$10$h.p.V..." # bcrypt хэш
```
Запуск экспортера: `./node_exporter --web.config.file=web-config.yml`

**2. Настройка в Prometheus (поддержка переменных окружения в v3):**
```yaml
scrape_configs:
  - job_name: 'secure-remote'
    basic_auth:
      username: 'prom_user'
      password: '${SCRAPE_PASSWORD}'
    static_configs:
      - targets: ['192.168.1.101:9100']
```

## Продвинутый Relabeling

Используйте для нормализации имен инстансов и фильтрации данных на этапе сбора.

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
```

## Устранение неполадок

| Проблема | Причина | Решение |
|---|---|---|
| **Target DOWN (Connection refused)** | Сервис не запущен или неверный порт | Выполните `ss -tunlp | grep 9100` на удаленном хосте. |
| **Target DOWN (No route to host)** | Блокировка Firewall или сетевой сбой | Проверьте правила UFW/iptables и `telnet 1.2.3.4 9100` с сервера мониторинга. |
| **Scrape Timeout** | Высокая сетевая задержка или перегрузка экспортера | Увеличьте `scrape_timeout` (по умолчанию 10s) или проверьте MTU туннеля. |
| **401 Unauthorized** | Неверные данные Basic Auth | Проверьте bcrypt хэш в `web-config.yml` и соответствие пароля в Prometheus. |
| **Метрики отсутствуют в Grafana** | Несоответствие лейблов (job/instance) | Проверьте соответствие меток в конфигурации Prometheus и в PromQL-запросах Grafana. |

## Дополнительная информация

### Связанные темы

* [Node Exporter установка](../node_exporter_installation.md) — установка на bare-metal/VM.
* [Конфигурация Prometheus](./prometheus_config.md) — детализация scrape-целей в Docker.
* [Service Discovery и Relabeling](../../service_discovery_and_relabeling.md) — глубокое погружение в SD.
* [Prometheus Remote Write](../../scaling/remote_write.md) — передача данных в централизованные хранилища.

### Безопасность и масштабирование

1.  **VPN/Туннелирование:** Для передачи метрик через публичные сети используйте WireGuard или Tailscale для создания защищенного L3-канала.
2.  **mTLS:** Для Enterprise-сред настройте взаимную аутентификацию по сертификатам (`tls_config`).
3.  **Prometheus Agent:** В случае нестабильных каналов установите локальный Prometheus в режиме `Agent` на удалённом хосте. Это обеспечит буферизацию данных и их передачу через Remote Write 2.0 (экономия трафика до 60%).
