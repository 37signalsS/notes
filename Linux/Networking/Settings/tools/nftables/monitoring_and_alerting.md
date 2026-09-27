# nftables — мониторинг и алертинг

## Определения

**nflog** — механизм ядра Linux, позволяющий направлять копии пакетов, обработанных nftables, в пользовательские пространства через netlink-сокет. Используется для передачи данных в системы анализа трафика (tcpdump, ulogd2, Suricata).

**ulogd2** — демон для логирования сетевых событий из nflog в различные бэкенды: файлы, базы данных (SQLite, PostgreSQL, MySQL), PostgreSQL + JSON, Kafka.

**Prometheus** — система мониторинга и алертинга, собирающая метрики по HTTP в формате time series. nftables-метрики доступны через `node_exporter` (metрики conntrack) и кастомные экспортеры.

**node_exporter** — стандартный экспортер Prometheus для Linux, предоставляющий метрики системы, включая `node_nf_conntrack_entries`, `node_nf_conntrack_max`, `node_nf_conntrack_stat_guest`.

**Conntrack metric** — метрика, отражающая текущее использование таблицы отслеживания соединений. Критична для обнаружения conntrack exhaustion.

**Группа алертов (Alert group)** — логическая группировка правил алертинга в Prometheus/Alertmanager по функциональному назначению (connectivity, security, performance).

## Основные концепции

### Архитектура мониторинга nftables

Мониторинг nftables строится на трех уровнях:

1. **Счетчики правил (Counter objects)** — встроенные в nftables счетчики пакетов и байт для каждого правила. Первичный источник данных для анализа эффективности правил.
2. **Conntrack метрики** — статистика таблицы отслеживания соединений, доступная через `/proc/net/stat/nf_conntrack` и `conntrack -S`.
3. **Логирование через nflog** — детальная информация о каждом пакете, включая заголовки, вердикт и время обработки.

### Источники метрик

| Источник | Тип данных | Формат | Доступ |
|:---|:---|:---|:---|
| `nft list ruleset` | Счетчики правил | pkts/bytes per rule | CLI |
| `nft -j list ruleset` | Счетчики в JSON | Структурированные данные | CLI |
| `/proc/net/stat/nf_conntrack` | Статистика conntrack | Hex-encoded counters | Файловая система |
| `/proc/sys/net/netfilter/nf_conntrack_count` | Текущее использование | Число | sysctl |
| `/proc/sys/net/netfilter/nf_conntrack_max` | Максимум conntrack | Число | sysctl |
| `conntrack -S` | Детальная статистика | human-readable | CLI |
| `nflog` | События пакетов | raw/JSON | netlink |

### Экспорт метрик в Prometheus

**node_exporter** уже предоставляет базовые метрики conntrack:

```bash
# Просмотр conntrack-метрик node_exporter
curl -s http://localhost:9100/metrics | grep conntrack
# → node_nf_conntrack_entries 128
# → node_nf_conntrack_max 262144
# → node_nf_conntrack_stat_layer2 0
# → node_nf_conntrack_stat_layer3 128
# → node_nf_conntrack_stat_layer4 96
```

Для экспорта счетчиков nftables (dropped packets per chain, sets size) необходим кастомный экспортер или скрипт-парсер.

### Архитектура логирования через nflog

```
Пакет → nftables (verdict: log) → nflog → ulogd2 → Бэкенды
                                                ├── Файл (/var/log/nftables.json)
                                                ├── PostgreSQL
                                                ├── Kafka
                                                └── Prometheus (через exporter)
```

## Предварительные требования

### Программные требования

| Компонент | Назначение | Проверка |
|:---|:---|:---|
| **nftables** | Фильтрация пакетов | `nft --version` |
| **node_exporter** | Метрики conntrack | `curl localhost:9100/metrics` |
| **Prometheus** | Сбор метрик | `prometheus --version` |
| **ulogd2** | Логирование nflog | `ulogd2 --version` |
| **Grafana** | Визуализация | `grafana-server --version` |
| **conntrack-tools** | Диагностика | `conntrack --version` |

## Практические сценарии

### 1. Экспорт счетчиков nftables в Prometheus (скрипт)

Создание скрипта, который парсит вывод `nft -j list ruleset` и генерирует метрики Prometheus:

```bash
#!/usr/bin/env bash
# /usr/local/bin/nftables_exporter.sh
# Экспортер счетчиков nftables для Prometheus

set -euo pipefail

OUTPUT_FILE="/var/lib/node_exporter/nftables.prom"
TMP_FILE=$(mktemp)

# Генерация метрик из nftables JSON
nft -j list ruleset | python3 -c "
import json, sys

data = json.load(sys.stdin)
metrics = []

for table in data.get('nftables', []):
    if 'table' not in table:
        continue
    family = table['table']['family']
    name = table['table']['name']

    for obj in data['nftables']:
        if 'ruleset' in obj:
            for rule in obj['ruleset']:
                if 'rule' not in rule:
                    continue
                r = rule['rule']
                if r.get('table') != name or r.get('family') != family:
                    continue

                # Извлечение handle и счетчиков
                handle = r.get('handle', 0)
                chain = r.get('chain', 'unknown')

                # Поиск counter expressions
                for expr in r.get('expr', []):
                    if 'counter' in expr:
                        pkts = expr['counter'].get('packets', 0)
                        bytes_ = expr['counter'].get('bytes', 0)
                        metrics.append(
                            f'nftables_rule_packets{{family=\"{family}\",'
                            f'table=\"{name}\",chain=\"{chain}\",'
                            f'handle=\"{handle}\"}} {pkts}'
                        )
                        metrics.append(
                            f'nftables_rule_bytes{{family=\"{family}\",'
                            f'table=\"{name}\",chain=\"{chain}\",'
                            f'handle=\"{handle}\"}} {bytes_}'
                        )

# Conntrack метрики
import subprocess
try:
    result = subprocess.run(['conntrack', '-S'], capture_output=True, text=True)
    for line in result.stdout.strip().split('\n'):
        if '=' in line:
            parts = line.split()
            for part in parts:
                if '=' in part:
                    key, val = part.split('=')
                    metrics.append(f'nftables_conntrack_{key} {val}')
except FileNotFoundError:
    pass

print('\n'.join(metrics))
" > "$TMP_FILE"

# Атомарная замена файла
mv "$TMP_FILE" "$OUTPUT_FILE"
```

**Настройка cron:**
```bash
# Запуск каждые 30 секунд
echo '* * * * * root /usr/local/bin/nftables_exporter.sh' > /etc/cron.d/nftables_exporter
```

**Настройка node_exporter:**
```bash
# Добавление текстового collector для nftables
# В systemd unit node_exporter:
# --collector.textfile.directory=/var/lib/node_exporter
```

### 2. Настройка ulogd2 для логирования через nflog

**Установка:**
```bash
sudo apt install ulogd2
```

**Конфигурация `/etc/ulogd.conf`:**
```ini
# Секция для nflog
[log1]
group=1
 nflog_uid=1
 buffer_size=50000

[json1]
group=1
json=1
# Бэкенд: вывод в файл
file=/var/log/nftables.json
mode=600
sync=1

# Бэкенд: вывод в Prometheus (через nftables_nflog exporter)
[prometheus]
group=1
json=1
```

**Правило nftables с nflog:**
```bash
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif "lo" accept

        # Логирование drop-пакетов через nflog (group 1)
        log prefix "NFT_DROP: " nflog group 1 drop
    }
}
```

**Запуск ulogd2:**
```bash
sudo systemctl enable --now ulogd2
# Проверка логов
tail -f /var/log/nftables.json
```

### 3. Настройка Prometheus для nftables-метрик

**prometheus.yml:**
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  # Стандартные метрики node_exporter (conntrack)
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
    # Фильтрация только conntrack-метрик
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: 'node_nf_conntrack.*'
        action: keep

  # Кастомные метрики nftables
  - job_name: 'nftables'
    static_configs:
      - targets: ['localhost:9115']
    # Если используете nftables_exporter
```

### 4. Настройка Grafana-дашборда

**Импорт дашборда (ID: 14570 для conntrack):**

```json
{
  "dashboard": {
    "title": "nftables / Conntrack Monitoring",
    "panels": [
      {
        "title": "Conntrack Utilization",
        "type": "gauge",
        "targets": [{
          "expr": "node_nf_conntrack_entries / node_nf_conntrack_max * 100",
          "legendFormat": "Usage %"
        }],
        "thresholds": {
          "steps": [
            {"value": 0, "color": "green"},
            {"value": 70, "color": "yellow"},
            {"value": 90, "color": "red"}
          ]
        }
      },
      {
        "title": "Conntrack Entries Over Time",
        "type": "timeseries",
        "targets": [{
          "expr": "node_nf_conntrack_entries",
          "legendFormat": "Current entries"
        }]
      },
      {
        "title": "Dropped Packets Rate",
        "type": "timeseries",
        "targets": [{
          "expr": "rate(nftables_rule_packets{chain=\"input\"}[5m])",
          "legendFormat": "Dropped pkts/s"
        }]
      }
    ]
  }
}
```

### 5. Настройка алертинга в Prometheus

**rules/nftables_alerts.yml:**
```yaml
groups:
  - name: nftables
    rules:
      # Conntrack почти заполнен
      - alert: ConntrackNearExhaustion
        expr: |
          node_nf_conntrack_entries / node_nf_conntrack_max > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Conntrack {{ $value | humanizePercentage }} full"
          description: "Таблица conntrack заполнена более чем на 85%."

      # Conntrack заполнен
      - alert: ConntrackExhaustion
        expr: |
          node_nf_conntrack_entries / node_nf_conntrack_max > 0.95
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "CRITICAL: Conntrack {{ $value | humanizePercentage }} full"
          description: "Таблица conntrack заполнена более чем на 95%. Новые соединения могут отбрасываться."

      # Резкий рост drop-пакетов
      - alert: HighDropRate
        expr: |
          rate(nftables_rule_packets{action="drop"}[5m]) > 1000
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Высокий rate drop-пакетов: {{ $value }}/s"
          description: "Количество отброшенных пакетов превышает 1000/сек в течение 3 минут."

      # Conntrack stat anomalies
      - alert: ConntrackStatGuestHigh
        expr: |
          node_nf_conntrack_stat_guest > 10000
        for: 10m
        labels:
          severity: info
        annotations:
          summary: "Высокое количество guest-соединений: {{ $value }}"
```

**Настройка Alertmanager (`/etc/alertmanager/alertmanager.yml`):**
```yaml
route:
  group_by: ['alertname']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'slack-notifications'

receivers:
  - name: 'slack-notifications'
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/xxx/yyy/zzz'
        channel: '#alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
```

### 6. Экспорт nflog в Kafka (для анализа в реальном времени)

**Конфигурация ulogd2 с Kafka-бэкендом:**
```ini
[kafka1]
group=2
json=1
topic=nftables-logs
brokers=kafka1:9092,kafka2:9092
```

**Правило nftables:**
```bash
# Логирование всех пакетов (для анализа)
table inet monitor {
    chain log_all {
        type filter hook input priority -150; policy accept;
        log nflog group 2
    }
}
```

### 7. Мониторинг через conntrack-tools

**Детальная статистика:**
```bash
# Текущая статистика
sudo conntrack -S
# → cpu=0   found=12850 invalid=120 ignore=0 delete=0 insert=0 drop=0 error=0 search_restart=0
# → cpu=1   found=9840  invalid=90  ignore=0 delete=0 insert=0 drop=0 error=0 search_restart=0

# Мониторинг в реальном времени
sudo conntrack -E
# → [NEW] tcp      6 120 SYN_SENT src=10.0.0.5 dst=203.0.113.10 sport=52182 dport=443 [UNREPLIED] src=203.0.113.10 dst=10.0.0.5 sport=443 dport=52182

# Количество записей
sudo conntrack -C
# → 128
```

**Экспорт в Prometheus через custom_exporter:**
```bash
#!/usr/bin/env python3
"""Простой экспортер conntrack-статистики для Prometheus."""
from prometheus_client import start_http_server, Gauge
import subprocess, time

drop_counter = Gauge('nftables_conntrack_drop', 'Conntrack drops per CPU')
invalid_counter = Gauge('nftables_conntrack_invalid', 'Conntrack invalid packets per CPU')
found_counter = Gauge('nftables_conntrack_found', 'Conntrack found entries per CPU')

def collect():
    result = subprocess.run(['conntrack', '-S'], capture_output=True, text=True)
    for line in result.stdout.strip().split('\n'):
        if '=' not in line:
            continue
        parts = line.split()
        cpu = None
        for p in parts:
            if p.startswith('cpu='):
                cpu = int(p.split('=')[1])
            elif '=' in p:
                k, v = p.split('=', 1)
                if k == 'drop' and cpu is not None:
                    drop_counter.labels(cpu=cpu).set(int(v))
                elif k == 'invalid' and cpu is not None:
                    invalid_counter.labels(cpu=cpu).set(int(v))
                elif k == 'found' and cpu is not None:
                    found_counter.labels(cpu=cpu).set(int(v))

if __name__ == '__main__':
    start_http_server(9116)
    while True:
        collect()
        time.sleep(30)
```

### 8. Логирование в journald с структурированными метками

**Правило nftables с информативным префиксом:**
```bash
table inet logging {
    chain input {
        type filter hook input priority 0; policy drop;

        ct state established,related accept
        iif "lo" accept

        # Логирование SSH-попыток
        tcp dport 22 ct state new log prefix "NFT_SSH_NEW: " limit rate 10/minute accept

        # Логирование ICMP
        icmp type echo-request log prefix "NFT_PING: " limit rate 5/second accept

        # Логирование drop
        log prefix "NFT_DROP_INPUT: " limit rate 10/minute drop
    }
}
```

**Просмотр логов:**
```bash
# Через journalctl
journalctl -t nftables -f
# → Sep 15 10:23:45 server nftables: NFT_SSH_NEW: IN=eth0 ... SRC=203.0.113.5 ...

# Фильтрация по префиксу
journalctl -t nftables | grep "NFT_DROP"
```

**Парсинг в JSON через journald:**
```bash
journalctl -t nftables -o json-pretty | jq '.MESSAGE'
# → "NFT_SSH_NEW: IN=eth0 OUT= MAC=... SRC=203.0.113.5 DST=10.0.0.1 ..."
```

## Валидация результатов

### Проверка экспорта метрик

```bash
# Проверка node_exporter
curl -s http://localhost:9100/metrics | grep conntrack
# → node_nf_conntrack_entries 128
# → node_nf_conntrack_max 262144

# Проверка кастомного экспортера
curl -s http://localhost:9116/metrics | grep nftables
# → nftables_rule_packets{family="inet",table="filter",chain="input",handle="5"} 1542
```

### Проверка логирования

```bash
# Проверка ulogd2
tail -f /var/log/nftables.json | jq .
# → {"timestamp":"2026-09-15T10:23:45","src":"203.0.113.5","dst":"10.0.0.1",...}

# Проверка nflog через tcpdump
sudo tcpdump -i any -n nflog group 1 -c 5
```

### Проверка алертов

```bash
# Тестирование алерта ConntrackNearExhaustion
# Временное увеличение нагрузки или снижение max
sudo sysctl -w net.netfilter.nf_conntrack_max=1000
# → Ожидание алерта в Prometheus (через 5 минут)

# Возврат
sudo sysctl -w net.netfilter.nf_conntrack_max=262144
```

## Диагностика и устранение неполадок

| Проблема | Признак | Диагностика | Решение |
|:---|:---|:---|:---|
| **node_exporter не показывает conntrack** | Метрики отсутствуют | `curl localhost:9100/metrics \| grep conntrack` | Убедитесь, что `nf_conntrack` модуль загружен |
| **nflog не логирует** | Пустой `/var/log/nftables.json` | `conntrack -S` — есть ли drop? | Проверьте `nflog group` в правиле и ulogd2 |
| **Prometheus не скрейпает** | Нет данных в Grafana | `curl localhost:9090/api/v1/targets` | Проверьте `scrape_configs` в prometheus.yml |
| **Высокий CPU на логировании** | `top` показывает high softirq | Уменьшите `limit rate` для `log` | Используйте `limit rate 10/minute` |
| **Дублирование логов** | Один пакет залогирован несколько раз | `nft list ruleset \| grep log` | Удалите дублирующие `log` правила |
| **Kafka не получает данные** | Пустой топик | `kafka-console-consumer --topic nftables-logs` | Проверьте `brokers` и `topic` в ulogd2 |

## Best Practices

1. **Ограничивайте логирование** — всегда используйте `limit rate` с `log`, чтобы избежать заполнения диска при DDoS.

2. **Используйтеnflog** вместо `log` для production — nflog позволяет направлять логи в ulogd2 без нагрузки на disk I/O.

3. **Conntrack — primary metric** — мониторьте `node_nf_conntrack_entries / node_nf_conntrack_max` в первую очередь.

4. **Алертинг по порогам** — настраивайте алерты на 85% (warning) и 95% (critical) использования conntrack.

5. **Версионируйте правила алертинга** — храните `nftables_alerts.yml` в Git.

6. **Используйте Grafana** для визуализации — готовые дашборды доступны на grafana.com (IDs: 14570, 14348).

7. **Не логируйте весь трафик** — используйте `log` только для `drop` и аномалий.

8. **Ротация логов** — настройте `logrotate` для файлов ulogd2 или `journald` retention.

## См. также

- **[nftables — архитектура и основные концепции](./architecture_and_concepts.md)** — счетчики и nftrace.
- **[nftables — тестирование и верификация правил](./firewall_testing.md)** — nftrace для отладки.
- **[nftables — практические сценарии](./practical_scenarios.md)** — интеграция с Prometheus.
- **[Prometheus](../../../../../../Monitoring/Prometheus/prometheus.md)** — настройка сбора метрик.
- **[Grafana](../../../../../../Monitoring/Grafana/grafana.md)** — визуализация метрик.
