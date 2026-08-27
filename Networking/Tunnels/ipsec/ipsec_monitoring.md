# IPsec: мониторинг и наблюдаемость

> **Основной документ:** [IPsec (основной документ)](./ipsec.md).

Данный файл описывает методы мониторинга IPsec-туннелей (strongSwan и LibreSwan): метрики, логирование, алертинг и визуализация.

---

## Определения

**XFRM метрики** — статистика ядра Linux по IPsec-ассоциациям: счётчики пакетов, байт, ошибок аутентификации, replay-shift. Доступна через `ip -s xfrm state`.

**charon metrics** — внутренние счётчики демона strongSwan: количество IKE/CHILD SA, ошибки,资源配置. Доступны через `swanctl --stats` и плагины вывода.

**Tunnel flap** — цикл «поднялся → упал → поднялся» для IPsec-туннеля. Основная проблема для мониторинга: стабильность туннеля критична для production.

**Health check** — скрипт или агент, проверяющий доступность IPsec-туннеля и сообщающий о статусе в систему мониторинга.

---

## Основные концепции

### Архитектура мониторинга IPsec

```
+-------------------+     +-------------------+     +-------------------+
|   strongSwan      |     |   Ядро Linux      |     |   Система логов   |
|   (charon)        |     |   (XFRM)          |     |   (syslog/journald)|
+--------+----------+     +--------+----------+     +--------+----------+
         |                         |                         |
         v                         v                         v
+-------------------+     +-------------------+     +-------------------+
|   swanctl --stats |     |   ip -s xfrm      |     |   rsyslog/syslog-ng|
|   swanctl --list  |     |   state/policy     |     |   → ELK/Loki      |
+--------+----------+     +--------+----------+     +--------+----------+
         |                         |                         |
         v                         v                         v
+-------------------+     +-------------------+     +-------------------+
|   textfile        |     |   custom exporter |     |   Promtail/       |
|   collector       |     |   (ipsec_exporter)|     |   Fluent Bit      |
+--------+----------+     +--------+----------+     +--------+----------+
         |                         |                         |
         +------------+------------+------------+------------+
                      |
                      v
              +-------------------+
              |   Prometheus      |
              +--------+----------+
                       |
                       v
              +-------------------+
              |   Grafana         |
              +-------------------+
```

### Что мониторить

| Метрика | Источник | Важность | Тип |
|---------|----------|----------|-----|
| **Статус туннеля** (UP/DOWN) | `swanctl --list-sas` | Критическая | Gauge |
| **Количество IKE SA** | `swanctl --list-sas` | Высокая | Gauge |
| **Количество CHILD SA** | `swanctl --list-sas` | Высокая | Gauge |
| **Пакеты (входящие/исходящие)** | `ip -s xfrm state` | Высокая | Counter |
| **Байты (входящие/исходящие)** | `ip -s xfrm state` | Средняя | Counter |
| **Ошибки аутентификации** | `ip -s xfrm state` | Критическая | Counter |
| **Replay-shift** | `ip -s xfrm state` | Средняя | Counter |
| **CPU времени charon** | `top`/`pidstat` | Средняя | Gauge |
| **Логи ошибок** | `/var/log/charon.log` | Критическая | Event |

---

## Практические сценарии

### Сбор метрик XFRM через custom exporter

#### Bash-скрипт для Prometheus textfile collector

```bash
#!/bin/bash
# /usr/local/bin/ipsec_metrics.sh
# Собирает XFRM метрики и выводит в формате Prometheus

OUTPUT_FILE="/var/lib/prometheus/textfile/ipsec.prom"
TMP_FILE=$(mktemp)

# Заголовок
cat > "$TMP_FILE" << 'EOF'
# HELP ipsec_xfrm_state_packets_total Total packets processed by XFRM state
# TYPE ipsec_xfrm_state_packets_total counter
# HELP ipsec_xfrm_state_bytes_total Total bytes processed by XFRM state
# TYPE ipsec_xfrm_state_bytes_total counter
# HELP ipsec_xfrm_state_errors_total Total errors in XFRM state
# TYPE ipsec_xfrm_state_errors_total counter
# HELP ipsec_xfrm_state_replay_window_size Current replay window size
# TYPE ipsec_xfrm_state_replay_window_size gauge
# HELP ipsec_tunnel_up Whether IPsec tunnel is up (1) or down (0)
# TYPE ipsec_tunnel_up gauge
EOF

# Парсинг XFRM state
ip -s xfrm state | awk '
/^[0-9a-f]+:/ {
    spi=$2; proto=$4; src=$6; dst=$8;
    label="proto=\""proto"\",src=\""src"\",dst=\""dst"\"";
}
/replay-window/ {
    window=$2;
    print "ipsec_xfrm_state_replay_window_size{"label"} " window;
}
/packets/ {
    packets=$2;
    print "ipsec_xfrm_state_packets_total{"label"} " packets;
}
/bytes/ {
    bytes=$2;
    print "ipsec_xfrm_state_bytes_total{"label"} " bytes;
}
/integrity-error/ {
    errors=$2;
    print "ipsec_xfrm_state_errors_total{"label"} " errors;
}
' >> "$TMP_FILE"

# Проверка статуса туннелей (strongSwan)
if command -v swanctl &>/dev/null; then
    SA_COUNT=$(swanctl --list-sas 2>/dev/null | grep -c "ESTABLISHED")
    echo "# HELP ipsec_swan_tunnel_up Whether strongSwan tunnel is up" >> "$TMP_FILE"
    echo "# TYPE ipsec_swan_tunnel_up gauge" >> "$TMP_FILE"
    echo "ipsec_swan_tunnel_up $SA_COUNT" >> "$TMP_FILE"
fi

# Проверка статуса туннелей (LibreSwan)
if command -v ipsec &>/dev/null; then
    SA_COUNT=$(ipsec status 2>/dev/null | grep -c "ESTABLISHED")
    echo "# HELP ipsec_pluto_tunnel_up Whether LibreSwan tunnel is up" >> "$TMP_FILE"
    echo "# TYPE ipsec_pluto_tunnel_up gauge" >> "$TMP_FILE"
    echo "ipsec_pluto_tunnel_up $SA_COUNT" >> "$TMP_FILE"
fi

# Безопасная запись (атомарная)
mv "$TMP_FILE" "$OUTPUT_FILE"
```

```bash
# Установка
sudo chmod +x /usr/local/bin/ipsec_metrics.sh

# Добавить в crontab (каждые 30 секунд)
# crontab -e
* * * * * /usr/local/bin/ipsec_metrics.sh
* * * * * sleep 30 && /usr/local/bin/ipsec_metrics.sh
```

#### Конфигурация Prometheus

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'ipsec'
    static_configs:
      - targets: ['gateway1:9100', 'gateway2:9100']
    # Если используется node_exporter с textfile collector
    # Файлы .prom в /var/lib/prometheus/textfile/
```

#### Настройка textfile collector (node_exporter)

```bash
# Установка node_exporter
sudo useradd --no-create-home --shell /bin/false node_exporter
wget https://github.com/prometheus/node_exporter/releases/latest/download/node_exporter-*.linux-amd64.tar.gz
tar xzf node_exporter-*.linux-amd64.tar.gz
sudo cp node_exporter-*/node_exporter /usr/local/bin/

# Systemd unit
cat << 'EOF' | sudo tee /etc/systemd/system/node_exporter.service
[Unit]
Description=Node Exporter
After=network.target

[Service]
User=node_exporter
ExecStart=/usr/local/bin/node_exporter \
    --collector.textfile.directory=/var/lib/prometheus/textfile
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```

### Health-check скрипт

```bash
#!/bin/bash
# /usr/local/bin/ipsec_healthcheck.sh
# Проверка состояния IPsec и алертинг

LOG_FILE="/var/log/ipsec_healthcheck.log"
ALERT_WEBHOOK="${ALERT_WEBHOOK:-}"  # Slack/Discord/Telegram webhook

check_tunnel() {
    local conn_name=$1
    local remote_ip=$2

    # Проверка 1: strongSwan SA
    if command -v swanctl &>/dev/null; then
        SA_STATUS=$(swanctl --list-sas 2>/dev/null | grep "$conn_name" | grep -c "ESTABLISHED")
        if [ "$SA_STATUS" -gt 0 ]; then
            echo "OK: strongSwan tunnel $conn_name is UP"
            return 0
        fi
    fi

    # Проверка 2: LibreSwan SA
    if command -v ipsec &>/dev/null; then
        SA_STATUS=$(ipsec status 2>/dev/null | grep "$conn_name" | grep -c "ESTABLISHED")
        if [ "$SA_STATUS" -gt 0 ]; then
            echo "OK: LibreSwan tunnel $conn_name is UP"
            return 0
        fi
    fi

    # Проверка 3: ESP-трафик
    ESP_TRAFFIC=$(ip -s xfrm state 2>/dev/null | grep -c "proto esp")
    if [ "$ESP_TRAFFIC" -gt 0 ]; then
        echo "OK: ESP traffic detected"
        return 0
    fi

    # Проверка 4: Ping через туннель (опционально)
    if [ -n "$remote_ip" ]; then
        if ping -c 1 -W 2 "$remote_ip" &>/dev/null; then
            echo "OK: Remote $remote_ip is reachable"
            return 0
        fi
    fi

    echo "CRITICAL: Tunnel $conn_name is DOWN"
    return 1
}

send_alert() {
    local message=$1
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    echo "[$timestamp] $message" >> "$LOG_FILE"

    if [ -n "$ALERT_WEBHOOK" ]; then
        curl -s -X POST -H 'Content-type: application/json' \
            --data "{\"text\": \"IPsec Alert: $message\"}" \
            "$ALERT_WEBHOOK" >/dev/null 2>&1
    fi
}

# Основной цикл
TUNNELS=("site-to-site:203.0.113.2" "backup-tunnel:203.0.113.3")

for tunnel in "${TUNNELS[@]}"; do
    IFS=':' read -r name remote <<< "$tunnel"
    if ! check_tunnel "$name" "$remote"; then
        send_alert "TUNNEL DOWN: $name (remote: $remote)"
    fi
done
```

### Централизованные логи

#### Настройка rsyslog для IPsec

```bash
# /etc/rsyslog.d/50-ipsec.conf
# Логирование strongSwan/LibreSwan в отдельный файл
:programname, isequal, "charon" /var/log/charon.log
:programname, isequal, "pluto" /var/log/pluto.log

# Отправка в централизованный сервер
*.* @@syslog-server:514
```

#### Фильтрация в ELK (Elasticsearch)

```json
// Kibana query для IPsec
programname: "charon" AND message: "ESTABLISHED"
programname: "charon" AND message: "FAILED"
programname: "charon" AND message: "ERROR"
```

#### Фильтрация в Grafana Loki

```logql
# Loki query
{job="ipsec"} |= "ESTABLISHED"
{job="ipsec"} |= "FAILED"
{job="ipsec"} |= "ERROR"
```

### Dashboards в Grafana

Рекомендуемые панели для IPsec-дашборда:

| Панель | Тип | Метрика | Вопрос |
|--------|-----|---------|--------|
| **Tunnel Status** | Stat | `ipsec_tunnel_up` | Туннель UP/DOWN |
| **Active Tunnels** | Gauge | `ipsec_swan_tunnel_up` | Количество активных туннелей |
| **Throughput** | Graph | `rate(ipsec_xfrm_state_bytes_total)` | Пропускная способность |
| **Packet Loss** | Graph | `rate(ipsec_xfrm_state_errors_total)` | Потери пакетов |
| **Replay Events** | Graph | `rate(ipsec_xfrm_state_replay_window_size)` | Replay-атаки |
| **Log Errors** | Table | Loki query | Последние ошибки |

---

## Типовые проблемы мониторинга

| Проблема | Причина | Решение |
|----------|---------|---------|
| Метрики не обновляются | Crontab не работает | Проверить `crontab -l`, права на скрипт |
| Prometheus не скрейпивает | Порт закрыт | Проверить firewall, `curl localhost:9100/metrics` |
| Нет логов charon | Логирование отключено | Раскомментировать `filelog` в `strongswan.conf` |
| Grafana не показывает данные | Нет datasource | Добавить Prometheus/Loki в Grafana |
| False positive алерты | DPD срабатывает | Увеличить `dpd_delay`/`dpd_timeout` |

---

## Дополнительная информация

### Рекомендуемые порты агентов

| Агент | Порт | Назначение |
|-------|------|------------|
| node_exporter | 9100 | System metrics + textfile |
| ipsec_exporter (custom) | 9110 | IPsec-specific metrics |
| Prometheus | 9090 | Scraping |
| Grafana | 3000 | Визуализация |

### Связанные документы

- **[IPsec (основной документ)](./ipsec.md)** — архитектура IKEv2, настройка strongSwan.
- **[Диагностика IPsec (legacy)](./ipsec_troubleshooting.md)** — отладка KAME/racoon.
- **[Высокая доступность IPsec](./ipsec_ha.md)** — failover и кластеризация.
- **[Производительность IPsec](./ipsec_performance.md)** — оптимизация и нагрузка.
