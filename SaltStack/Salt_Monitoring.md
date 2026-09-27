# Мониторинг Salt Infrastructure

## Определения

- **Salt Exporter**: Экспортер метрик для Prometheus, собирающий данные о состоянии Salt Master/Minion (количество миньонов, время выполнения заданий, статус подключений).
- **`salt-run manage.up`**: Команда для проверки доступности миньонов (возвращает список активных).
- **`salt-run manage.status`**: Команда для получения статуса всех миньонов (up/down).
- **`salt-run jobs.active`**: Команда для просмотра активных заданий.
- **`salt-run jobs.list_jobs`**: Команда для просмотра истории заданий.
- **Event Bus Monitoring**: Наблюдение за событиями Salt через `salt-run state.event` для отладки и алертинга.
- **Grafana Dashboard**: Визуализация метрик Salt в Grafana (количество миньонов, задержки, ошибки).
- **Salt Healthcheck**: Проверка работоспособности Salt infrastructure (мастер, миньоны, API).

---

## Основные концепции

### Что мониторить

| Компонент | Метрики | Инструмент |
|:---|:---|:---|
| **Salt Master** | Загрузка CPU/RAM, количество подключений, размер Job Cache | node_exporter, salt-exporter |
| **Salt Minion** | Статус (up/down), время последнего heartbeata | `manage.up`, `manage.status` |
| **Salt API** | Время ответа, количество запросов, ошибки | API logs, reverse proxy metrics |
| **Event Bus** | Количество событий, теги, ошибки | `state.event`, Event Bus logs |
| **Job Queue** | Активные задания, время выполнения, ошибки | `jobs.active`, `jobs.list_jobs` |

### Архитектура мониторинга

```
Salt Master
  │
  ├── salt-exporter → Prometheus → Grafana
  │
  ├── node_exporter → Prometheus → Grafana
  │
  ├── Salt Event Bus → Event Return → SIEM (ELK/Loki)
  │
  └── AlertManager → Мессенджер (Slack/Telegram)
```

---

## Практические сценарии

### 1. salt-exporter для Prometheus

**Установка:**

```bash
# Через pip
pip install salt-exporter

# Или из репозитория
git clone https://github.com/saltstack/salt-exporter.git
cd salt-exporter
python setup.py install
```

**Конфигурация:**

```yaml
# /etc/salt/master.d/exporter.conf
exporter:
  port: 9191
  listen_address: 0.0.0.0
```

**systemd unit:**

```ini
# /etc/systemd/system/salt-exporter.service
[Unit]
Description=Salt Exporter for Prometheus
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/salt-exporter
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Запуск:**

```bash
systemctl daemon-reload
systemctl enable --now salt-exporter

# Проверка
curl http://localhost:9191/metrics
# → salt_minions_total 150
# → salt_minions_up 148
# → salt_minions_down 2
# → salt_job_duration_seconds 12.5
```

### 2. Настройка Prometheus

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'salt-master'
    static_configs:
      - targets: ['salt-master:9191']
    scrape_interval: 30s

  - job_name: 'salt-master-node'
    static_configs:
      - targets: ['salt-master:9100']
    scrape_interval: 30s

  - job_name: 'salt-minions'
    static_configs:
      - targets:
        - 'web-01:9100'
        - 'web-02:9100'
        - 'db-01:9100'
    scrape_interval: 60s
```

### 3. Grafana Dashboard

**Метрики для дашборда:**

```json
{
  "panels": [
    {
      "title": "Salt Minions Total",
      "targets": [{"expr": "salt_minions_total"}],
      "type": "stat"
    },
    {
      "title": "Salt Minions Up",
      "targets": [{"expr": "salt_minions_up"}],
      "type": "stat"
    },
    {
      "title": "Salt Minions Down",
      "targets": [{"expr": "salt_minions_down"}],
      "type": "stat"
    },
    {
      "title": "Job Duration",
      "targets": [{"expr": "rate(salt_job_duration_seconds[5m])"}],
      "type": "graph"
    }
  ]
}
```

**Импорт дашборда:**

1. Открыть Grafana → Dashboards → Import
2. Ввести ID дашборда (например, 12345 для Salt Stack Dashboard)
3. Выбрать Prometheus datasource

### 4. Алертинг в AlertManager

```yaml
# /etc/prometheus/alertmanager.yml
route:
  group_by: ['alertname']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'slack-salt'

receivers:
  - name: 'slack-salt'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/xxx/yyy/zzz'
        channel: '#salt-alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ .Annotations.summary }}'
```

**Правила алертов:**

```yaml
# /etc/prometheus/rules/salt.yml
groups:
  - name: salt
    rules:
      - alert: SaltMinionDown
        expr: salt_minions_down > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Salt minion is down"
          description: "{{ $value }} minions are down"

      - alert: SaltJobDurationHigh
        expr: rate(salt_job_duration_seconds[5m]) > 300
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Salt job duration is high"
          description: "Job duration is {{ $value }} seconds"

      - alert: SaltMasterHighLoad
        expr: node_load15 / node_cpu_cores > 2
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Salt master high load"
          description: "Load average is {{ $value }}"
```

### 5. Event Bus мониторинг

```bash
# Просмотр событий в реальном времени
salt-run state.event pretty=True

# Фильтрация по тегу
salt-run state.event pretty=True tag='salt/job/*'

# Логирование событий в файл
salt-run state.event --out=raw >> /var/log/salt/events.log

# Просмотр событий через grep
salt-run state.event | grep 'salt/minion'
```

**Event Return в SIEM:**

```yaml
# /etc/salt/master
event_return: elasticsearch

elasticsearch:
  host: elasticsearch.example.com
  port: 9200
  index: salt-events
  protocol: https
```

### 6. Проверка здоровья Salt

```bash
# Проверка доступности миньонов
salt-run manage.up | wc -l
# → 150

# Проверка статуса
salt-run manage.status
# → up: [web-01, web-02, ...]
# -> down: [old-server]

# Проверка активных заданий
salt-run jobs.active
# → {}

# Проверка Job Cache
salt-run jobs.list_jobs | head -20

# Проверка API
curl -s https://salt-master:8000/login -k | jq .
```

### 7. Автоматический healthcheck

```bash
#!/bin/bash
# /usr/local/bin/salt_healthcheck.sh

# Проверка мастера
if ! systemctl is-active --quiet salt-master; then
    echo "CRITICAL: salt-master is not running"
    exit 2
fi

# Проверка количества миньонов
MINIONS_UP=$(salt-run manage.up | wc -l)
MINIONS_DOWN=$(salt-run manage.status | grep 'down:' | wc -w)

if [ "$MINIONS_DOWN" -gt 10 ]; then
    echo "WARNING: $MINIONS_DOWN minions are down"
    exit 1
fi

echo "OK: $MINIONS_UP minions up, $MINIONS_DOWN down"
exit 0
```

### 8. Сбор метрик с миньонов

```bash
# Установка node_exporter на миньоны
salt '*' pkg.installed:
  - name: prometheus-node-exporter

# Настройка сервиса
salt '*' service.running:
  - name: prometheus-node-exporter
  - enable: True
```

```yaml
# /etc/salt/prometheus/node_exporter.sls
node_exporter_package:
  pkg.installed:
    - name: prometheus-node-exporter

node_exporter_service:
  service.running:
    - name: prometheus-node-exporter
    - enable: True
    - require:
      - pkg: node_exporter_package
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `salt-exporter не запускается` | Порт занят или неверный конфиг | Проверить порт 9191, логи |
| `Prometheus не скрейпит` | Неверный target | Проверить `prometheus.yml`, `curl localhost:9191/metrics` |
| `Grafana не показывает данные` | Неверный datasource | Проверить Prometheus datasource |
| `Event Return не работает` | Неверный конфиг ext_job_cache | Проверить `event_return` в master config |
| `manage.up не отвечает` | Master перегружен | Проверить load, memory, количество миньонов |
| `Алерты не приходят` | AlertManager недоступен | Проверить AlertManager, webhook URL |
| `Метрики дублируются` | Несколько экземпляров exporter | Один exporter на мастер |

### Best practices

1. **Один exporter**: Один salt-exporter на мастер.
2. **node_exporter**: На каждом миньоне для системных метрик.
3. **Алертинг**: Настройте алерты на `salt_minions_down > 0`.
4. **Дашборд**: Создайте Grafana dashboard для Salt infrastructure.
5. **Event Return**: Направляйте события в SIEM для аудита.
6. **Healthcheck**: Автоматические проверки здоровья Salt.
7. **Логирование**: Централизуйте логи master/minion в ELK/Loki.
8. **Ретеншн**: Храните метрики достаточно долго для анализа.

### Версии и совместимость

| Версия Salt | Особенности мониторинга |
|:---|:---|
| 3006 LTS | `manage.up`, `manage.status`, basic metrics |
| 3007 STS | Улучшенные метрики jobs |
| 3008 LTS | Интеграция с Prometheus, Event Bus optimization |

### См. также

- [Архитектура SaltStack](Architecture.md) — monitoring overview
- [Backup и восстановление](Backup_Restore.md) — backup Salt infrastructure
- [Безопасность SaltStack](Security_Approaches.md) — audit logging
