# Redis Exporter — Практический гайд

## Определения

**Redis Exporter** (`oliver006/redis_exporter`) — внешний агент для сбора метрик Redis в формат Prometheus. Поддерживает standalone Redis, кластеры, Sentinel и ACL. Собирает метрики о производительности, памяти, соединениях, репликации и ключах.

*   **Порт по умолчанию:** `9121`
*   **Актуальная версия:** `v1.63.0` (2026)
*   **Репозиторий:** [oliver006/redis_exporter](https://github.com/oliver006/redis_exporter)

**См. также:** [Обзор экспортеров](./overview.md), [Redis Overview](../../Databases/redis_overview.md).

## Предварительные требования

*   **Redis:** 6.0+ (для ACL), 7.0+ (для метрик `latency-histogram`).
*   **Пользователь Redis:** Для полного набора метрик необходим пользователь с правами `INFO`, `CONFIG GET`, `SLOWLOG GET`, `CLIENT LIST` (при ACL — роли `monitoring` или `read`).
*   **Сеть:** Порт `9121` доступен для Prometheus. Порт Redis (по умолчанию `6379`) доступен для экспортера.
*   **Ресурсы:** ~50m CPU, 64Mi RAM на экземпляр.

## Основные концепции

### Ключевые метрики

| Метрика | Тип | Описание |
|:---|:---|:---|
| `redis_up` | Gauge | Доступность Redis (`1` — OK, `0` — недоступен). |
| `redis_connected_clients` | Gauge | Количество активных клиентских соединений. |
| `redis_used_memory_bytes` | Gauge | Используемый объем памяти (`used_memory`). |
| `redis_used_memory_peak_bytes` | Gauge | Пиковый объем использованной памяти. |
| `redis_maxmemory_bytes` | Gauge | Лимит памяти (`maxmemory`). `0` — без лимита. |
| `redis_evicted_keys_total` | Counter | Количество удаленных ключей из-за лимита памяти. |
| `redis_keyspace_hits_total` | Counter | Количество успешных поисков ключей. |
| `redis_keyspace_misses_total` | Counter | Количество промахов при поиске ключей. |
| `redis_connected_slaves` | Gauge | Количество активных реплик. |
| `redis_repl_offset_diff` | Gauge | Разница offset'а между master и replica. |
| `redis_commands_processed_total` | Counter | Общее количество обработанных команд. |
| `redis_command_duration_seconds_total` | Counter | Суммарное время выполнения команд (по типам). |
| `redis_keyspace_hit_ratio` | Gauge | Доля попаданий в кэш (`hits / (hits + misses)`). |
| `redis_blocked_clients` | Gauge | Количество клиентов, заблокированных на `BLPOP`, `BRPOP` и т.д. |

### Типы подключения

| Тип | Флаги | Когда использовать |
|:---|:---|:---|
| **Standalone** | `--redis.addr=redis://host:6379` | Один инстанс Redis |
| **Sentinel** | `--redis.addr=redis://host:26379 --redis.sentinel.master=mymaster` | Высокая доступность через Sentinel |
| **Cluster** | `--redis.addr=redis://host1:6379,redis://host2:6379` | Redis Cluster (автообнаружение нод) |
| **ACL (Redis 6+)** | `--redis.user=monitor --redis.password=...` | ACL-аутентификация |

### Детализация по ключам (Key-space Analysis)

Redis Exporter может собирать метрики по отдельным ключам через `--check-keys` или `--check-single-keys`. Это полезно для мониторинга критичных ключей (очереди, лимиты):

```bash
# Мониторинг размера конкретных ключей
redis_exporter \
  --redis.addr=redis://localhost:6379 \
  --check-single-keys="queue:pending,queue:processing,rate_limit:*" \
  --check-key-groups="queue:.*,cache:.*"
```

**Важно:** Слишком много отслеживаемых ключей (`>1000`) увеличивает нагрузку на Redis и кардинальность в Prometheus.

## Практические сценарии

### Systemd (bare-metal/VMs)

```ini
[Unit]
Description=Redis Exporter
After=network.target redis.service
Wants=redis.service

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/redis_exporter \
  --redis.addr=redis://127.0.0.1:6379 \
  --redis.password-file=/etc/redis_exporter/.redis_password \
  --web.listen-address=0.0.0.0:9121
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

### Docker Compose

```yaml
services:
  redis-exporter:
    image: oliver006/redis_exporter:v1.63.0
    container_name: redis-exporter
    restart: unless-stopped
    ports:
      - "9121:9121"
    environment:
      REDIS_ADDR: "redis://redis:6379"
      REDIS_PASSWORD: "${REDIS_PASSWORD}"
    networks:
      - monitoring

  redis:
    image: redis:7-alpine
    container_name: redis
    ports:
      - "6379:6379"
    command: redis-server --requirepass ${REDIS_PASSWORD}
    networks:
      - monitoring

networks:
  monitoring:
    driver: bridge
```

### Kubernetes (Sidecar)

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: redis
  serviceName: redis
  replicas: 1
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
        - name: redis
          image: redis:7-alpine
          ports:
            - containerPort: 6379
          volumeMounts:
            - name: data
              mountPath: /data
        - name: redis-exporter
          image: oliver006/redis_exporter:v1.63.0
          ports:
            - containerPort: 9121
              name: metrics
          env:
            - name: REDIS_ADDR
              value: "redis://127.0.0.1:6379"
          volumeMounts:
            - name: redis-password
              mountPath: /etc/redis_exporter
              readOnly: true
      volumes:
        - name: redis-password
          secret:
            secretName: redis-secret
            items:
              - key: password
                path: .redis_password
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: redis-exporter
  namespace: monitoring
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: redis
  endpoints:
    - port: metrics
      interval: 30s
```

### Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'redis'
    static_configs:
      - targets: ['redis-host:9121']
    scrape_interval: 15s
    scrape_timeout: 10s
```

## Алертинг

```yaml
groups:
  - name: redis_alerts
    rules:
      # Redis недоступен
      - alert: RedisDown
        expr: redis_up == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Redis {{ $labels.instance }} недоступен"
          description: "redis_up == 0 более 2 минут."

      # Использование памяти > 80% от maxmemory
      - alert: RedisHighMemoryUsage
        expr: redis_used_memory_bytes / redis_maxmemory_bytes > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое использование памяти Redis"
          description: "Использование {{ $value | humanizePercentage }} от лимита."

      # Доля попаданий в кэш < 80%
      - alert: RedisLowHitRatio
        expr: redis_keyspace_hit_ratio < 0.8
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Низкая доля попаданий в кэш Redis"
          description: "Hit ratio: {{ $value | humanizePercentage }}."

      # Удаление ключей из-за лимита памяти
      - alert: RedisEvictingKeys
        expr: rate(redis_evicted_keys_total[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Redis удаляет ключи из-за нехватки памяти"
          description: "{{ $value }}/сек удалено."

      # Задержка репликации
      - alert: RedisReplicationLag
        expr: redis_repl_offset_diff > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Задержка репликации Redis"
          description: "Разница offset: {{ $value }}."

      # Клиенты заблокированы
      - alert: RedisBlockedClients
        expr: redis_blocked_clients > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Много заблокированных клиентов Redis"
          description: "{{ $value }} клиентов ждут ответа."
```

## Типичные ошибки и устранение неполадок

| Проблема | Причина | Решение |
|:---|:---|:---|
| `redis_up == 0` | Неверный адрес, пароль или порт | Проверьте `--redis.addr`, credentials и доступность Redis |
| Метрики `redis_commands_*` отсутствуют | Redis < 7.0 или нет `--check-commands` | Обновите Redis или добавьте флаг `--include-command-metrics` |
| `keyspace_hit_ratio` = 0 | Нет данных по `keyspace_hits`/`keyspace_misses` | Убедитесь, что Redis собирает статистику (`CONFIG SET statistics yes`) |
| Высокая нагрузка на Redis | Много `--check-keys` | Уменьшите количество отслеживаемых ключей |
| `redis_connected_slaves` = 0 | Репликация не настроена | Проверьте конфигурацию репликации Redis |

## Лучшие практики

1.  **Отдельный пользователь:** Создайте пользователя Redis только для чтения (`MONITOR`, `INFO`, `CONFIG GET`, `SLOWLOG GET`).
2.  **`maxmemory`:** Всегда задавайте лимит памяти в Redis для предотвращения OOM.
3.  **Slow Log:** Мониторьте `redis_slowlog_length` для обнаружения медленных команд.
4.  **Cluster:** Для Redis Cluster используйте `--redis.addr` с указанием всех нод — экспортер автоматически обнаружит слоты.
5.  **Scrape interval:** 15s для production, 30s для staging.
6.  **Cardinality:** Избегайте мониторинга слишком большого количества ключей через `--check-keys` — это создаёт высококардинальные метрики.

## См. также

*   [Redis Overview](../../Databases/redis_overview.md) — архитектура Redis
*   [Textfile Collector](./extensibility/textfile_collector.md) — для кастомных Redis-метрик через скрипты
*   [Node Exporter](./node_exporter.md) — мониторинг хоста с Redis
