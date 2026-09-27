# RabbitMQ: Мониторинг и алертинг

## Операционный контекст: DevOps / SRE / Sysadmin

RabbitMQ в production на bare-metal или виртуальных машинах требует постоянного контроля за здоровьем узлов, очередью и приложениями. Этот файл является центральным справочником по настройке сбора метрик, визуализации и алертинга. Для смежных тем используйте:

- **[Обзор RabbitMQ](./overview.md)** — базовые концепции, гарантии доставки, ограничения.
- **[Установка и кластеризация RabbitMQ](./installation_and_clustering.md)** — диагностические команды, развертывание кластеров.
- **[Устранение неполадок](./troubleshooting.md)** — диагностика и решение типичных проблем.
- **[Сравнение RabbitMQ и Kafka](../Kafka/rabbitmq_vs_kafka.md)** — архитектурные различия.

## Определения

- **Мониторинг RabbitMQ (RabbitMQ Monitoring)** — совокупность методов сбора и анализа метрик для оценки здоровья брокера сообщений, включая доступность узлов, потребление ресурсов, производительность очередей и статус доставки сообщений.
- **Management Plugin** — официальный плагин RabbitMQ, предоставляющий HTTP API (порт 15672) и веб-интерфейс для просмотра метрик, управления ресурсами и диагностики.
- **Prometheus Exporter** — плагин `rabbitmq_prometheus`, экспортирующий метрик в формате Prometheus (порт 15692).
- **Alarm (Тревога)** — состояние брокера, при котором RabbitMQ блокирует публикации (publishers blocked) для предотвращения исчерпания памяти или диска.
- **Flow Control** — механизм обратной связи, при котором брокер замедляет или блокирует публикации от продюсера при переполнении памяти или каналов. Визуализируется через метрику `rabbitmq_channel_flow_blocked`.
- **Memory Pressure** — состояние, при котором потребление RAM приближается к `vm_memory_high_watermark`. Брокер переходит в режим блокировки публикаций и начинает сбрасывать метрики производительности.
- **Disk Free Limit** — минимальный объем свободного места на диске, при котором брокер переходит в alarm-режим. По умолчанию зависит от `disk_free_limit` (абсолютное значение) или вычисляется как 50% от свободного места.
- **Quorum Health** — статус кворумной очереди: `running` (есть лидер и большинство участников), `no_quorum` (недостаточно участников), `syncing` (идет репликация).
- **Consumer Utilization** — отношение сообщений `ready` к количеству активных консьюмеров. Низкий utilization при высокой глубине очереди указывает на "застрявшие" сообщения или падение консьюмеров.
- **Recording Rule** — правило Prometheus, предварительно вычисляющее часто используемый запрос (например, rate publish rate) для оптимизации производительности и сокращения повторяющихся выражений в алертах и дашбордах.
- **Health Check (HTTP API)** — набор эндпоинтов Management API (`/api/health/checks/*`), возвращающих статус `ok`, `running`, или `failed` для зависимостей брокера.
- **Retention Policy** — политика хранения метрик в Prometheus (например, 7-30 дней для RabbitMQ). Определяет объем данных, доступных для ретроспективного анализа.

## Основные концепции

### Уровни мониторинга

1. **Уровень узла (Node Level):** CPU, RAM, диск, Erlang-процессы, состояние gossip, открытые файловые дескрипторы.
2. **Уровень очереди (Queue Level):** Глубина очереди (ready/unacknowledged), скорость обработки, DLX-счетчики, состояние кворума.
3. **Уровень кластера (Cluster Level):** Кворум, сетевая связность, распределение памяти, репликация, партиционирование.
4. **Уровень приложения (Application Level):** Rate публикации, rate потребления, время доставки, ошибки publishing, подтверждения (confirms).

### Метрики здоровья

| Метрика | Порог (пример) | Значение |
|:---|:---|:---|
| `rabbitmq_resident_memory_limit_bytes` | >80% лимита | Memory Pressure |
| `rabbitmq_queue_messages_ready` | Резкий рост | Консьюмеры не справляются |
| `rabbitmq_process_open_fds` | >80% от `ulimit -n` | Утечка файловых дескрипторов |
| `rabbitmq_erlang_processes` | >1M | Риск исчерпания Erlang-счетчиков |
| `rabbitmq_build_info` | Версия <4.0 | Устаревший брокер (требуется обновление) |
| `rabbitmq_channel_flow_blocked` | >0 | Брокер заблокировал публикации (flow control) |
| `rabbitmq_queue_messages_unacknowledged` | Рост при стабильном consumers | Консьюмеры не отвечают или зависли |
| `rabbitmq_disk_free_limit_bytes` | <2GB | Риск disk alarm |

### Кардинальность метрик и Resource Metrics

Каждая метрика Prometheus имеет набор labels (например, `node`, `queue`, `vhost`, `pid`). При высокой кардинальности (десятки тысяч уникальных комбинаций) Prometheus теряет эффективность. Следуйте правилам:

- Собирайте метрики на уровне очереди только для критичных vhost.
- Используйте aggregation rules для группировки (`sum by (vhost)`).
- Избегайте wildcard-скрейпинга всех очередей без фильтрации в Prometheus.

### Memory и Disk Alarms

RabbitMQ экспортирует состояние alarms через Management API и метрики:

- `rabbitmq_alarms` — текущее состояние alarms (memory, disk).
- `rabbitmq_resident_memory_bytes` — фактическое потребление RAM.
- `rabbitmq_disk_free_limit_bytes` и `rabbitmq_disk_free_bytes` — для отслеживания приближения к disk alarm.

## Практические сценарии

### 1. Включение Management Plugin и Prometheus Exporter

```bash
# Включение плагинов
sudo rabbitmq-plugins enable rabbitmq_management
sudo rabbitmq-plugins enable rabbitmq_prometheus

# Проверка слушателей
sudo rabbitmq-diagnostics ports
# → 15672 (management), 15692 (prometheus), 5672 (amqp)

# Доступ к UI
# http://<node-ip>:15672/
# Логин: guest / Пароль: guest (только для localhost)
```

### 2. Настройка Prometheus для сбора метрик

**`prometheus.yml` (добавить job):**

```yaml
scrape_configs:
  - job_name: 'rabbitmq'
    static_configs:
      - targets: ['node1:15692', 'node2:15692', 'node3:15692']
    metrics_path: '/metrics'
    scrape_interval: 15s
```

Для крупных кластеров используйте file_sd или relabeling для автоматического обнаружения новых узлов.

### 3. Recording Rules для Prometheus

Добавьте recording rules для часто используемых запросов. Это снижает нагрузку на Prometheus и ускоряет отрисовку дашбордов.

```yaml
groups:
  - name: rabbitmq.rules
    rules:
      - record: rabbitmq:queue_messages_ready:rate5m
        expr: rate(rabbitmq_queue_messages_ready[5m])

      - record: rabbitmq:queue_messages_unacknowledged:rate5m
        expr: rate(rabbitmq_queue_messages_unacknowledged[5m])

      - record: rabbitmq:node_memory_usage_pct
        expr: rabbitmq_resident_memory_bytes / rabbitmq_resident_memory_limit_bytes * 100

      - record: rabbitmq:queue_publish_rate:rate5m
        expr: sum(rate(rabbitmq_queue_messages_published[5m])) by (vhost, name)

      - record: rabbitmq:queue_deliver_rate:rate5m
        expr: sum(rate(rabbitmq_queue_messages_delivered[5m])) by (vhost, name)
```

### 4. Grafana дашборд

Рекомендуемый набор панелей:

1. **Cluster Overview:** Число узлов, состояние кворума, потребление RAM/диска.
2. **Queue Depth:** `rabbitmq_queue_messages_ready` по очередям (топ-10 по глубине).
3. **Publish Rate:** `rabbitmq:queue_publish_rate:rate5m` по vhost.
4. **Delivery Rate:** `rabbitmq:queue_deliver_rate:rate5m` по очереди.
5. **Consumer Utilization:** Соотношение `messages_ready` к `consumers` (показывает, есть ли "застрявшие" сообщения).
6. **Blocked Connections:** Число заблокированных publisher-ов из-за Memory/Flow Control (`rabbitmq_channel_flow_blocked`).
7. **File Descriptors:** `rabbitmq_process_open_fds` относительно лимита.
8. **Memory Alarm:** Состояние memory alarm (0/1) на узле.

Пример панели Consumer Utilization (PromQL):

```promql
sum(rabbitmq_queue_messages_ready) by (vhost, name)
/
sum(rabbitmq_queue_consumers) by (vhost, name)
```

### 5. Алерты Prometheus / Alertmanager

```yaml
groups:
  - name: rabbitmq_alerts
    rules:
      - alert: RabbitMQMemoryPressure
        expr: rabbitmq_resident_memory_limit_bytes / rabbitmq_resident_memory_bytes > 0.8
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Высокое потребление памяти RabbitMQ"
          description: "Память >80% лимита на {{ $labels.instance }}"

      - alert: RabbitMQQueueDepthHigh
        expr: rabbitmq_queue_messages_ready > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Большая глубина очереди {{ $labels.queue }}"
          description: "Очередь {{ $labels.queue }} имеет {{ $value }} неподтвержденных сообщений"

      - alert: RabbitMQNoQuorum
        expr: rabbitmq_queue_members_health{status="no_quorum"} > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Кворум потерян для очереди {{ $labels.queue }}"
          description: "Очередь {{ $labels.queue }} на {{ $labels.instance }} потеряла кворум"

      - alert: RabbitMQFileDescriptorsHigh
        expr: rabbitmq_process_open_fds / rabbitmq_process_open_fds_limit > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокое число файловых дескрипторов"
          description: "Использовано {{ $value | humanizePercentage }} FDs на {{ $labels.instance }}"

      - alert: RabbitMQDiskFreeLow
        expr: rabbitmq_disk_free_bytes < 5368709120
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Мало свободного места на диске RabbitMQ"
          description: "Свободно {{ $value | humanize1024 }} на {{ $labels.instance }}"

      - alert: RabbitMQFlowControlBlocked
        expr: rabbitmq_channel_flow_blocked > 0
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Flow Control активен на {{ $labels.instance }}"
          description: "Брокер блокирует публикации из-за давления памяти или каналов"
```

### 6. Alertmanager: группировка, маршрутизация и ингибиition

Алерты из RabbitMQ часто связаны между собой: Memory Pressure ведет к Flow Control, который ведет к росту очередей. Настройте ингибиition, чтобы подавить вторичные алерты:

```yaml
route:
  receiver: 'pagerduty-rabbitmq'
  group_by: ['alertname', 'cluster', 'vhost']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 1h

  routes:
    - match:
        severity: critical
      receiver: 'pagerduty-rabbitmq'
      continue: true

inhibit_rules:
  - source_match:
      alertname: RabbitMQMemoryPressure
    target_match_re:
      alertname: RabbitMQ(QueueDepthHigh|FlowControlBlocked)
    equal: ['instance']
```

### 7. Интеграция с Grafana OnCall / PagerDuty

```yaml
receivers:
  - name: 'pagerduty-rabbitmq'
    pagerduty_configs:
      - service_key: '<your-service-key>'
        description: '{{ .CommonAnnotations.summary }}'
        severity: '{{ .CommonLabels.severity }}'

  - name: 'slack-rabbitmq-alerts'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX'
        channel: '#alerts-rabbitmq'
        title: '{{ .CommonAnnotations.summary }}'
        text: '{{ .CommonAnnotations.description }}'
```

Для escalation policy добавьте route с `continue: true` и разными `group_wait` для critical- и warning-северностей.

### 8. Health Checks через Management API

Management API предоставляет эндпоинты для проверки здоровья брокера и его зависимостей. Используйте их в Kubernetes probes или внешних мониторинговых системах:

```bash
# Общий статус здоровья
curl -s -u guest:guest http://localhost:15672/api/health/checks/alarms
# → {"status":"ok","alarms":[]}

# Проверка здоровья кластера
curl -s -u guest:guest http://localhost:15672/api/health/checks/cluster
# → {"status":"ok","cluster_alarms":[]}

# Проверка конкретного vhost
curl -s -u guest:guest http://localhost:15672/api/health/checks/vhosts
# → {"status":"ok","vhosts":[{"name":"/","status":"ok"}]}

# Проверка listeners
curl -s -u guest:guest http://localhost:15672/api/health/checks/listeners
# → {"status":"ok"}
```

Для systemd или Kubernetes добавьте в скрипт:

```bash
#!/bin/bash
STATUS=$(curl -s -u guest:guest http://localhost:15672/api/health/checks/alarms | jq -r '.status')
if [ "$STATUS" != "ok" ]; then
  echo "RabbitMQ alarm active"
  exit 1
fi
exit 0
```

### 9. Мониторинг consumer lag и throughput

Consumer lag — разница между скоростью публикации и скоростью потребления. Отслеживайте его для предотвращения накопления сообщений:

```promql
# Consumer lag для конкретной очереди (сообщения, опубликованные, но не доставленные)
sum(rabbitmq_queue_messages_published{name="my_queue"}) by (vhost, name)
-
sum(rabbitmq_queue_messages_delivered{name="my_queue"}) by (vhost, name)
```

Для долгосрочного анализа используйте recording rule:

```yaml
- record: rabbitmq:queue_consumer_lag:rate1h
  expr: sum(increase(rabbitmq_queue_messages_published[1h])) by (vhost, name)
    - sum(increase(rabbitmq_queue_messages_delivered[1h])) by (vhost, name)
```

Алерт на критический lag:

```yaml
- alert: RabbitMQConsumerLagHigh
  expr: rabbitmq:queue_consumer_lag:rate1h > 50000
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Высокий consumer lag для {{ $labels.queue }}"
    description: "Lag = {{ $value }} сообщений за час"
```

### 10. Обнаружение connection storm

Connection storm — массовое установление TCP-соединений, приводящее к исчерпанию файловых дескрипторов или Erlang-процессов. Мониторьте:

```promql
# Рост числа подключений за 1 минуту
rate(rabbitmq_connections_total[1m]) > 50
```

Алерт:

```yaml
- alert: RabbitMQConnectionStorm
  expr: rate(rabbitmq_connections_total[1m]) > 50
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Connection storm на {{ $labels.instance }}"
    description: "Новые подключения: {{ $value | humanize }}/сек"
```

### 11. Мониторинг disk и memory alarms

Алармы брокера не всегда транслируются в алерты Prometheus. Добавьте проверку состояния alarms через Management API:

```bash
# Проверка текущих alarms
curl -s -u guest:guest http://localhost:15672/api/alarms
# → {"alarms":[]} или [{"node":"rabbit@node1","resource":"memory","value":...}]
```

Для автоматизации добавьте blackbox_exporter или отдельный job в Prometheus, опрашивающий `/api/health/checks/alarms`:

```yaml
scrape_configs:
  - job_name: 'rabbitmq-health'
    metrics_path: '/api/health/checks/alarms'
    static_configs:
      - targets: ['node1:15672', 'node2:15672']
    bearer_token: '<management-token>'
```

### 12. Логирование и аудит

**Настройка логирования в `rabbitmq.conf`:**

```ini
log.console = true
log.console.level = info
log.file = true
log.file.level = info
log.file.path = /var/log/rabbitmq/rabbit@node1.log
log.exchange.type = direct
log.exchange.key = rabbitmq.logs
```

**Ключевые паттерны логов для мониторинга:**

- `memory limit exceeded` — приближение к memory alarm.
- `disk free limit exceeded` — approaching disk alarm.
- `closing connection` — массовые отключения клиентов.
- `connection started` — burst новых подключений.
- `channel blocked` — flow control сработал на уровне канала.

**Интеграция с Loki (через promtail):**

```yaml
scrape_configs:
  - job_name: rabbitmq
    static_configs:
      - targets:
          - node1
        labels:
          job: rabbitmq
          __path__: /var/log/rabbitmq/*.log
```

Создайте Loki alert rules для быстрого реагирования на критические паттерны:

```yaml
groups:
  - name: rabbitmq_log_alerts
    rules:
      - alert: RabbitMQMemoryLimitExceeded
        expr: |
          sum by (instance) (count_over_time({job="rabbitmq"} |= "memory limit exceeded"[5m])) > 0
        labels:
          severity: critical
        annotations:
          summary: "RabbitMQ достиг лимита памяти на {{ $labels.instance }}"

      - alert: RabbitMQDiskLimitExceeded
        expr: |
          sum by (instance) (count_over_time({job="rabbitmq"} |= "disk free limit exceeded"[5m])) > 0
        labels:
          severity: critical
        annotations:
          summary: "RabbitMQ достиг лимита диска на {{ $labels.instance }}"
```

### 13. rabbitmqadmin для кастомных метрик

Management API позволяет собирать кастомные метрики через `rabbitmqadmin` CLI. Используйте это, когда стандартного экспорта недостаточно:

```bash
# Список очередей с depth
rabbitmqadmin -u guest -p guest list queues name messages messages_ready messages_unacknowledged consumers

# Список подключений с состоянием
rabbitmqadmin list connections name state channels

# Экспорт в JSON для программной обработки
rabbitmqadmin list queues name vhost messages_ready messages_unacknowledged consumers --formatter json | jq .
```

Для интеграции с внешними системами (например, Zabbix, Datadog) создайте скрипт:

```bash
#!/bin/bash
# rabbitmq_custom_metrics.sh
RESULT=$(rabbitmqadmin list queues name messages_ready messages_unacknowledged consumers --formatter json)
echo "rabbitmq_queue_depth_total $(echo $RESULT | jq '[.[].messages_ready] | add')"
```

## Устранение неполадок мониторинга

### Проблема: Метрики не отображаются в Prometheus

**Диагностика:**
```bash
curl -s http://localhost:15692/metrics | head -20
# → Должен вернуть текстовый формат Prometheus
```

**Решение:**
- Убедитесь, что порт 15692 открыт в файрволе.
- Проверьте, что `rabbitmq_prometheus` плагин включен: `sudo rabbitmq-plugins list`.

### Проблема: Alertmanager не отправляет алерты

**Диагностика:**
```bash
# Проверка конфигурации Alertmanager
amtool config show --alertmanager.url=http://localhost:9093
```

**Решение:**
- Проверьте receiver и route в `alertmanager.yml`.
- Убедитесь, что PagerDuty service_key действителен.

### Проблема: Метрики устарели или отсутствуют для конкретной очереди

**Симптомы:** В Grafana нет данных по конкретному vhost/очереди, хотя очередь активна.

**Диагностика:**
```bash
# Проверьте, что очередь существует
curl -s -u guest:guest http://localhost:15672/api/queues | jq '.[] | select(.name=="my_queue")'

# Проверьте labels в Prometheus UI (http://prometheus:9090/graph)
# Ищите `rabbitmq_queue_messages_ready{queue="my_queue"}`
```

**Решение:**
- Убедитесь, что метрика включена в экспорт (некоторые метрики требуют explicit enabling в новых версиях).
- Проверьте retention: если очередь создана недавно, а scrape interval большой, данных может еще не быть.
- Для queues с `auto_delete: true` метрики исчезнут после удаления очереди.

### Проблема: Management API не отвечает или отвечает с задержкой

**Симптомы:** `curl http://localhost:15672/api/health` таймаут, Grafana показывает gaps.

**Диагностика:**
```bash
# Проверка портов
sudo rabbitmq-diagnostics ports

# Проверка логов на ошибки аутентификации или переполнения
sudo journalctl -u rabbitmq-server --since "10 minutes ago" | grep -i "management"
```

**Решение:**
- Увеличьте лимит воркеров Management Plugin: `management.http_worker_pool_size = 16` в `rabbitmq.conf`.
- Проверьте, не заблокирован ли Management UI firewall-ом или fail2ban.
- Для высоконагруженных кластеров вынесите Management API на отдельный узел.

### Проблема: Алерты flapping (мерцают)

**Симптомы:** Алерт срабатывает и отключается каждые несколько минут.

**Диагностика:**
```bash
# Проверьте, нет ли краткосрочных всплесков
# В Prometheus UI проверьте график метрики за окном `for` и `repeat_interval`
```

**Решение:**
- Увеличьте `for:` duration (например, с 1m до 5m).
- Настройте `keep_child_for: 1h` в Alertmanager для предотвращения преждевременного закрытия.
- Добавьте hysteresis: алерт снимается только если значение остается ниже порога в течение N периодов.

## Стек мониторинга для production

### Компоненты

1. **Prometheus:** Сбор метрик через плагин `rabbitmq_prometheus`
2. **Grafana:** Визуализация дашбордов и аналитика
3. **Alertmanager:** Алерты на критичные события
4. **Loki (опционально):** Централизованное логирование

### Ключевые PromQL запросы

```promql
# Memory pressure (>80% лимита)
rabbitmq_resident_memory_limit_bytes / rabbitmq_resident_memory_bytes > 0.8

# Queue depth (>10000 сообщений)
rabbitmq_queue_messages_ready > 10000

# No quorum (потеря кворума)
rabbitmq_queue_members_health{status="no_quorum"} > 0

# Consumer lag (>50000 сообщений в час)
rabbitmq:queue_consumer_lag:rate1h > 50000

# Flow control активен
rabbitmq_channel_flow_blocked > 0

# Disk space low (<2GB)
rabbitmq_disk_free_limit_bytes < 5368709120

# File descriptors high (>80%)
rabbitmq_process_open_fds / rabbitmq_process_open_fds_limit > 0.8
```

### Recording Rules для оптимизации

```yaml
groups:
  - name: rabbitmq.rules
    rules:
      - record: rabbitmq:queue_messages_ready:rate5m
        expr: rate(rabbitmq_queue_messages_ready[5m])

      - record: rabbitmq:queue_messages_unacknowledged:rate5m
        expr: rate(rabbitmq_queue_messages_unacknowledged[5m])

      - record: rabbitmq:node_memory_usage_pct
        expr: rabbitmq_resident_memory_bytes / rabbitmq_resident_memory_limit_bytes * 100

      - record: rabbitmq:queue_consumer_lag:rate1h
        expr: |
          sum(increase(rabbitmq_queue_messages_published[1h])) by (vhost, name)
          - sum(increase(rabbitmq_queue_messages_delivered[1h])) by (vhost, name)
```

## Дополнительная информация

### См. также

- **[Установка и кластеризация RabbitMQ](./installation_and_clustering.md)** — практическое руководство по развертыванию.
- **[Обзор RabbitMQ](./overview.md)** — базовые концепции, гарантии доставки.
- **[Мониторинг Kafka](../Kafka/kafka_for_monitoring.md)** — сравнение подходов.
- **[CLI-команды](./cli_reference.md)** — справочник диагностических команд.
- **[Конфигурация](./configuration_reference.md)** — настройка параметров мониторинга.


### Лучшие практики

1. **Используйте отдельный vhost для мониторинга** — не давайте Management UI доступ к production vhost.
2. **Ограничьте retention метрик** в Prometheus (7-30 дней для RabbitMQ метрик).
3. **Настройте алерты на `no_quorum`** — это критическое состояние, требующее немедленного вмешательства.
4. **Мониторите `file descriptors`** — RabbitMQ может открывать тысячи файлов при высокой нагрузке.
5. **Настраивайте recording rules** для rate-метрик — это снижает нагрузку на Prometheus и ускоряет дашборды.
6. **Добавьте health checks Management API** в monitoring stack — они дают быстрый feedback о состоянии alarms без экспорта метрик.
7. **Группируйте алерты по vhost и cluster** — при массовом сбое вы получите один алерт вместо сотен.
8. **Настройте ингибition rules** между Memory Pressure, Flow Control и Queue Depth — это уменьшит шум.
9. **Мониторьте consumer lag**, а не только depth — очередь может быть глубокой, но консьюмеры обрабатывают сообщения стабильно.
10. **Логируйте memory и disk alarm transitions** — они являются первыми признаками проблем и позволяют предотвратить падение брокера.
11. **Используйте rabbitmqadmin для внешних систем** — когда Prometheus недостаточно, экспортируйте метрики через HTTP API.
