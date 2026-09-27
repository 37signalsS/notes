# Samba: Мониторинг и Observability

## Определения

**samba_exporter** — внешний экспортер метрик для Prometheus, собирающий данные о сессиях, файлах и производительности Samba через утилиты `smbstatus` и `smbclient`.

**node_exporter textfile collector** — механизм node_exporter для приема пользовательских метрик из текстовых файлов. Позволяет создавать кастомные метрики без написания собственного экспортера.

**Prometheus Alertmanager** — компонент стека Prometheus, отвечающий за маршрутизацию и группировку алертов. Поддерживает email, Telegram, Slack, PagerDuty.

**SLI (Service Level Indicator)** — количественная метрика качества сервиса. Для Samba: доступность шар, время отклика, количество активных сессий.

**SLO (Service Level Objective)** — целевое значение SLI. Например: 99.9% доступности шар в месяц.

**Error Budget** — допустимый объем простоев, вычисляемый как `1 - SLO`. Если Error Budget исчерпан —.freeze изменений.

**Grafana Dashboard** — визуализация метрик Prometheus в реальном времени. Для Samba: сессии, производительность диска, ошибки аутентификации.

**Loki** — система агрегации логов от Grafana Labs. Легче ELK, индексирует только метаданные (labels), а не полный текст логов.

## Базовые концепции

### Архитектура мониторинга Samba

```
┌─────────────────────────────────────────────────────────┐
│                     Samba Server(s)                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │  smbd    │  │ winbindd │  │  CTDB    │  │  NSS    │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬────┘ │
│       │              │              │              │      │
│  ┌────▼──────────────▼──────────────▼──────────────▼──┐  │
│  │         textfile collector / samba_exporter         │  │
│  └────────────────────────┬───────────────────────────┘  │
└───────────────────────────┼──────────────────────────────┘
                            │ :9102/textfile
                     ┌──────▼──────┐
                     │  Prometheus │
                     └──────┬──────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
        ┌─────▼─────┐ ┌────▼────┐ ┌──────▼──────┐
        │  Grafana  │ │ Loki   │ │ Alertmanager│
        └───────────┘ └────────┘ └─────────────┘
```

### Ключевые метрики Samba

| Метрика | Источник | Описание | SLO |
| :--- | :--- | :--- | :--- |
| `samba_sessions_active` | smbstatus | Количество активных сессий | -- |
| `samba_shares_available` | smbclient | Доступность шар | >= 99.9% |
| `samba_auth_failures_total` | journalctl | Неудачные попытки входа | -- |
| `samba_uptime_seconds` | systemctl | Время работы сервиса | >= 99.9% |
| `samba_disk_usage_percent` | df | Заполненность диска | < 85% |
| `ctdb_node_status` | ctdb status | Статус узла кластера | 1 (OK) |

### Сбор логов

Samba использует системный журнал (journalctl) и собственные лог-файлы:

| Источник | Тип | Назначение |
| :--- | :--- | :--- |
| `journalctl -u smbd` | Structured | Ошибки демона, аутентификация |
| `journalctl -u winbindd` | Structured | Маппинг SID/UID, Kerberos |
| `/var/log/samba/log.smbd` | Text | Детальные логи (при `log level > 1`) |
| `/var/log/samba/audit.log` | Text | Аудит операций (VFS full_audit) |

## Практические сценарии

### 1. Экспорт метрик через textfile collector

```bash
# Установка node_exporter textfile collector
sudo mkdir -p /var/lib/node_exporter/textfile_collector

# Скрипт сбора метрик
cat <<'EOF' > /usr/local/bin/samba_metrics.sh
#!/bin/bash
METRICS_DIR="/var/lib/node_exporter/textfile_collector"
TMP_FILE="$METRICS_DIR/samba.prom.$$"

# Количество активных сессий
SESSIONS=$(sudo smbstatus -b 2>/dev/null | grep -c "^[0-9]" || echo "0")
echo "samba_sessions_active $SESSIONS" > "$TMP_FILE"

# Доступность шар (тест подключения)
SHARES_OK=0
SHARES_TOTAL=0
for share in $(sudo smbclient -L localhost -N 2>/dev/null | awk '/Disk/{print $1}'); do
    SHARES_TOTAL=$((SHARES_TOTAL + 1))
    if sudo smbclient //localhost/"$share" -N -c "ls" &>/dev/null; then
        SHARES_OK=$((SHARES_OK + 1))
    fi
done
echo "samba_shares_total $SHARES_TOTAL" >> "$TMP_FILE"
echo "samba_shares_available $SHARES_OK" >> "$TMP_FILE"

# Время работы smbd
UPTIME=$(systemctl show smbd --property=ActiveEnterTimestamp --value 2>/dev/null | xargs -I{} date -d "{}" +%s 2>/dev/null || echo "0")
echo "samba_smbd_start_time $UPTIME" >> "$TMP_FILE"

# Статус winbind
if systemctl is-active --quiet winbind; then
    echo "samba_winbind_status 1" >> "$TMP_FILE"
else
    echo "samba_winbind_status 0" >> "$TMP_FILE"
fi

# Статус CTDB (если кластер)
if command -v ctdb &>/dev/null; then
    CTDB_STATUS=$(sudo ctdb status 2>/dev/null | grep "THIS NODE" | awk '{print $NF}')
    [[ "$CTDB_STATUS" == "OK" ]] && echo "samba_ctdb_node_status 1" >> "$TMP_FILE" || echo "samba_ctdb_node_status 0" >> "$TMP_FILE"
fi

mv "$TMP_FILE" "$METRICS_DIR/samba.prom"
EOF
chmod +x /usr/local/bin/samba_metrics.sh
```

```bash
# Cron каждые 60 секунд
* * * * * /usr/local/bin/samba_metrics.sh
```

### 2. Текстовый экспортер для аудит-логов

```bash
cat <<'EOF' > /usr/local/bin/samba_audit_metrics.sh
#!/bin/bash
METRICS_DIR="/var/lib/node_exporter/textfile_collector"
TMP_FILE="$METRICS_DIR/samba_audit.prom.$$"

# Ошибки аутентификации за последние 5 минут
AUTH_ERRORS=$(journalctl -u smbd --since "5 min ago" 2>/dev/null | grep -c "NT_STATUS_LOGON_FAILURE" || echo "0")
echo "samba_auth_failures_5m $AUTH_ERRORS" > "$TMP_FILE"

# Ошибки доступа за последние 5 минут
ACCESS_ERRORS=$(journalctl -u smbd --since "5 min ago" 2>/dev/null | grep -c "NT_STATUS_ACCESS_DENIED" || echo "0")
echo "samba_access_denied_5m $ACCESS_ERRORS" >> "$TMP_FILE"

# Заполненность диска (корневая ФС шар)
DISK_USAGE=$(df /srv/samba 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')
echo "samba_disk_usage_percent $DISK_USAGE" >> "$TMP_FILE"

mv "$TMP_FILE" "$METRICS_DIR/samba_audit.prom"
EOF
chmod +x /usr/local/bin/samba_audit_metrics.sh
```

```bash
# Cron каждые 5 минут
*/5 * * * * /usr/local/bin/samba_audit_metrics.sh
```

### 3. Конфигурация Prometheus

```yaml
# /etc/prometheus/prometheus.yml
scrape_configs:
  - job_name: 'samba'
    static_configs:
      - targets: ['samba1:9100', 'samba2:9100']
    metrics_path: /metrics
    scrape_interval: 60s

  - job_name: 'samba_textfile'
    static_configs:
      - targets: ['samba1:9100', 'samba2:9100']
    metrics_path: /metrics
    params:
      collect[]:
        - textfile
    scrape_interval: 60s
```

### 4. Правила алертинга

```yaml
# /etc/prometheus/rules/samba_alerts.yml
groups:
  - name: samba_alerts
    rules:
      # Шара недоступна
      - alert: SambaShareDown
        expr: samba_shares_available < samba_shares_total
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Samba share {{ $labels.instance }} is down"
          description: "Available: {{ $value }}"

      # Много ошибок аутентификации
      - alert: SambaAuthFailuresHigh
        expr: rate(samba_auth_failures_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High auth failure rate on {{ $labels.instance }}"
          description: "Rate: {{ $value }}/s"

      # Диск заполнен
      - alert: SambaDiskAlmostFull
        expr: samba_disk_usage_percent > 85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Samba disk usage {{ $value }}%"

      # Сервис не работает
      - alert: SambaServiceDown
        expr: samba_uptime_seconds == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Samba service down on {{ $labels.instance }}"

      # CTDB узел забанен
      - alert: CTDBNodeUnhealthy
        expr: samba_ctdb_node_status == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "CTDB node unhealthy on {{ $labels.instance }}"
```

### 5. Настройка Alertmanager

```yaml
# /etc/alertmanager/alertmanager.yml
route:
  group_by: ['alertname', 'instance']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'telegram'

receivers:
  - name: 'telegram'
    telegram_configs:
      - bot_token: 'YOUR_BOT_TOKEN'
        chat_id: -1001234567890
        parse_mode: 'HTML'
        message: |
          <b>{{ .GroupLabels.alertname }}</b>
          <i>{{ .CommonLabels.instance }}</i>
          {{ range .Alerts }}
          {{ .Annotations.summary }}
          {{ .Annotations.description }}
          {{ end }}

  - name: 'email'
    email_configs:
      - to: 'ops@example.com'
        from: 'alertmanager@example.com'
        smarthost: 'smtp.example.com:587'
        auth_username: 'alertmanager@example.com'
        auth_password: 'password'
```

### 6. Dashboard в Grafana

Основные панели для Samba-дашборда:

```json
{
  "panels": [
    {
      "title": "Active Sessions",
      "type": "stat",
      "targets": [{"expr": "samba_sessions_active"}]
    },
    {
      "title": "Shares Available",
      "type": "gauge",
      "targets": [{"expr": "samba_shares_available"}],
      "max": 10
    },
    {
      "title": "Auth Failures (5m)",
      "type": "timeseries",
      "targets": [{"expr": "samba_auth_failures_5m"}]
    },
    {
      "title": "Disk Usage",
      "type": "gauge",
      "targets": [{"expr": "samba_disk_usage_percent"}],
      "max": 100,
      "thresholds": {"steps": [
        {"value": 0, "color": "green"},
        {"value": 70, "color": "yellow"},
        {"value": 85, "color": "red"}
      ]}
    },
    {
      "title": "CTDB Cluster Status",
      "type": "stat",
      "targets": [{"expr": "samba_ctdb_node_status"}],
      "valueMappings": [
        {"value": 0, "text": "UNHEALTHY"},
        {"value": 1, "text": "OK"}
      ]
    }
  ]
}
```

### 7. Сбор логов через Loki

```yaml
# /etc/promtail/config.yml
scrape_configs:
  - job_name: samba
    static_configs:
      - targets:
          - localhost
        labels:
          job: samba
          host: samba1
          __path__: /var/log/samba/log.smbd

    pipeline_stages:
      - regex:
          expression: 'NT_STATUS_(?P<status>\w+)'
      - labels:
          status:

  - job_name: samba_audit
    static_configs:
      - targets:
          - localhost
        labels:
          job: samba_audit
          host: samba1
          __path__: /var/log/samba/audit.log
```

### 8. Запросы в Grafana для Loki

```logql
# Все ошибки аутентификации
{job="samba"} |~ "NT_STATUS_LOGON_FAILURE"

# Ошибки доступа по IP
{job="samba"} |~ "NT_STATUS_ACCESS_DENIED" | json | ip="192.168.1.100"

# Аудит удаления файлов
{job="samba_audit"} |~ "unlink"
```

### 9. Автоматизация через systemd timer

```ini
# /etc/systemd/system/samba-metrics.service
[Unit]
Description=Samba Prometheus Metrics Collector
After=network.target smbd.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/samba_metrics.sh
User=root
```

```ini
# /etc/systemd/system/samba-metrics.timer
[Unit]
Description=Run Samba metrics collection every minute

[Timer]
OnBootSec=60
OnUnitActiveSec=60

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now samba-metrics.timer
```

## Мониторинг и диагностика

### Быстрая проверка здоровья Samba

```bash
# Проверка сервисов
systemctl status smbd winbind

# Проверка доступности шар
smbclient -L //localhost -N

# Проверка сессий
smbstatus

# Проверка CTDB (если кластер)
sudo ctdb status

# Просмотр последних ошибок
journalctl -u smbd -u winbind -p err..emerg --since "1 hour ago"
```

### Интеграция с существующим стеком мониторинга

Если у вас уже настроен Prometheus + Grafana:
1. Добавьте scrape-конфиг для Samba-серверов
2. Импортируйте дашборд (ID: 12345 в Grafana.com или создайте свой)
3. Настройте алерты в Alertmanager
4. Подключите Loki для сбора логов

## Типовые ошибки мониторинга

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Метрики не обновляются | Cron/timer не работает | `systemctl status samba-metrics.timer` |
| `smbstatus` требует root | Пользователь не в группе | Добавьте в `adm` или используйте sudo |
| Loki не индексирует логи | Промтай не настроен | Проверьте конфигурацию promtail |
| Алерты не приходят | Alertmanager не настроен | Проверьте receiver и route |

## Дополнительная информация

- [Обзор Samba](./index.md) — архитектура и стандарты.
- [Настройка сервера](./samba_setup.md) — базовые параметры.
- [Устранение неполадок](./samba_troubleshooting.md) — анализ ошибок.

## См. также

- [Prometheus: Обзор](../../../../Prometheus/overview.md) — архитектура и концепции.
- [Grafana: Основы](../../../../Grafana/basics.md) — настройка дашбордов.
- [Loki: Обзор](../../../../Loki/loki_overview.md) — сбор логов.
- [Оптимизация TCP](../../../Networking/Concepts/tcp_tuning/tcp_tuning_overview.md) — тюнинг для мониторинга.
