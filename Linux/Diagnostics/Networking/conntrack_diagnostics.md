# Диагностика conntrack (Connection Tracking)

## Определения

**conntrack** — подсистема ядра Linux для отслеживания состояния сетевых соединений. Используется Netfilter (iptables/nftables) для stateful-фильтрации, NAT и функций RELATED. Каждая запись	conntrack занимает ~300 байт RAM.

**nf_conntrack_max** — максимальное количество записей в таблице conntrack. При превышении ядро отбрасывает новые соединения с сообщением `nf_conntrack: table full, dropping packet`.

**nf_conntrack_count** — текущее количество активных записей. Сравнивается с nf_conntrack_max для оценки загрузки.

**Conntrack zones** — механизм изоляции таблиц conntrack для разных подсистем (NAT, VPN, PBR), предотвращающий конфликт записей.

## Основные концепции

### Место conntrack в стеке

```
Входящий пакет
    │
    ▼
  raw (PREROUTING)      ← NOTRACK исключает из conntrack
    │
    ▼
  conntrack: lookup / create
    │
    ├── ESTABLISHED / RELATED → пропустить
    └── NEW → создать запись → nat (PREROUTING) → ...
```

### Состояния conntrack

| Состояние | Описание |
|:---|:---|
| **NEW** | Первый пакет соединения (SYN) |
| **ESTABLISHED** | Соединение установлено (после 3-way handshake) |
| **RELATED** | Запись связана с существующим (FTP data, ICMP error) |
| **INVALID** | Запись не соответствует известному протоколу/состоянию |

### Ключевые параметры sysctl

| Параметр | По умолчанию | Рекомендация | Описание |
|:---|:---|:---|:---|
| `nf_conntrack_max` | 262144 | 1048576+ | Максимум записей |
| `nf_conntrack_buckets` | 65536 | max/4 | Размер хеш-таблицы |
| `tcp_timeout_established` | 432000 (5 дней) | 3600-86400 | Таймаут ESTABLISHED |
| `tcp_timeout_time_wait` | 120 | 30-60 | Таймаут TIME-WAIT |
| `udp_timeout` | 30 | 30 | Таймаут UDP |
| `udp_timeout_stream` | 180 | 60-180 | Таймаут активного UDP |

## Практические сценарии

### 1. Мониторинг использования conntrack

```bash
# Текущее использование vs максимум
COUNT=$(cat /proc/sys/net/netfilter/nf_conntrack_count)
MAX=$(cat /proc/sys/net/netfilter/nf_conntrack_max)
echo "Conntrack: $COUNT / $MAX ($(echo "scale=1; $COUNT * 100 / $MAX" | bc)%)"

# Детальная статистика
conntrack -S
# → cpu=0   found=1234567 insert=12345 drop=0 insert_failed=0

# Ключевые поля:
# found         — успешные поиски (нормально)
# insert        — новые записи (нормально)
# drop          — отброшенные из-за переполнения (!= 0 → проблема)
# insert_failed — не удалось вставить (concurrent, != 0 → проблема)
# early_drop   — записи, удаленные из-за нехватки места

# Мониторинг в реальном времени
watch -n 1 'echo "Count: $(cat /proc/sys/net/netfilter/nf_conntrack_count) / Max: $(cat /proc/sys/net/netfilter/nf_conntrack_max)"'
```

### 2. Поиск соединений к конкретному сервису

```bash
# Все соединения к порту 443
conntrack -L -p tcp --dport 443

# Соединения от конкретного IP
conntrack -L -s 10.0.0.50

# Соединения в состоянии NEW (только что созданные)
conntrack -L -p tcp --state NEW

# В формате grep (для скриптов)
conntrack -L -p tcp --dport 80 | grep -c ESTABLISHED
# → 1523

# С фильтрацией по протоколу
conntrack -L -p udp --dport 53
```

### 3. Диагностика "table full"

**Симптом:** `dmesg` показывает `nf_conntrack: table full, dropping packet`.

```bash
# Шаг 1: Подтверждение проблемы
dmesg -T | grep -i "conntrack\|table full"
# → [Tue Sep 16 10:23:45 2025] nf_conntrack: table full, dropping packet

# Шаг 2: Текущее использование
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max
# → 262144 / 262144  ← переполнение!

# Шаг 3: Статистика по CPU
conntrack -S | awk '{sum+=$3; drop+=$7} END{print "Inserts:", sum, "Drops:", drop}'
# → Inserts: 1234567 Drops: 45230  ← много дропов

# Шаг 4: Решение — увеличить максимум
sudo sysctl -w net.netfilter.nf_conntrack_max=1048576
sudo sysctl -w net.netfilter.nf_conntrack_buckets=262144

# Шаг 5: Постоянная настройка
echo "net.netfilter.nf_conntrack_max=1048576" | sudo tee /etc/sysctl.d/99-conntrack.conf
echo "net.netfilter.nf_conntrack_buckets=262144" | sudo tee -a /etc/sysctl.d/99-conntrack.conf
```

### 4. Ускорение очистки устаревших записей

```bash
# Уменьшить таймаут ESTABLISHED (по умолчанию 5 дней!)
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=3600
# → 1 час вместо 5 дней

# Уменьшить таймаут TIME-WAIT
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30

# Уменьшить таймаут CLOSE-WAIT (потенциально зависшие соединения)
sudo sysctl -w net.netfilter.nf_conntrack_tcp_timeout_close_wait=60

# Проверка текущих таймаутов
sysctl net.netfilter.nf_conntrack_tcp_timeout_established
```

### 5. Исключение трафика из conntrack (NOTRACK)

Для высокопроизводительных балансировщиков/прокси:

```bash
# Через raw таблицу (iptables)
sudo iptables -t raw -A PREROUTING -p tcp --dport 80 -j NOTRACK
sudo iptables -t raw -A OUTPUT -p tcp --sport 80 -j NOTRACK

# Через nftables
sudo nft add rule ip raw prerouting tcp dport 80 notrack
sudo nft add rule ip raw output tcp sport 80 notrack

# Проверка
conntrack -L -p tcp --dport 80
# → пусто (соединения не отслеживаются)

# ⚠️ ВНИМАНИЕ: NOTRACK отключает stateful-фильтрацию!
# Правила с -m state --state ESTABLISHED,RELATED НЕ БУДУТ работать.
```

### 6. Diagnostics через tcpdump

```bash
# Захват conntrack-связанного трафика
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-syn != 0 and port 443' -c 10

# Проверка, создается ли conntrack-запись
sudo conntrack -E -p tcp --dport 443
# → [NEW] tcp 6 120 SYN_SENT src=10.0.0.1 dst=93.184.216.34 sport=43210 dport=443 ...
# → [UPDATE] tcp 6 60 ESTABLISHED src=10.0.0.1 dst=93.184.216.34 sport=43210 dport=443 ...
```

## Дополнительная информация

### Интеграция с Prometheus

```yaml
# node_exporter экспортирует:
# node_nf_conntrack_entries      — текущее количество
# node_nf_conntrack_entries_limit — максимум
# node_nf_conntrack_stat_found   — успешные поиски
# node_nf_conntrack_stat_insert  — новые записи
# node_nf_conntrack_stat_drop    — отброшенные

groups:
  - name: conntrack_alerts
    rules:
      - alert: ConntrackTableAlmostFull
        expr: node_nf_conntrack_entries / node_nf_conntrack_entries_limit > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Conntrack table > 80% full"

      - alert: ConntrackDropsDetected
        expr: rate(node_nf_conntrack_stat_drop[5m]) > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Conntrack drops detected"
```

### Связанные инструменты

- **[conntrack production tuning](../../Networking/Concepts/conntrack_production_tuning.md)** — полная оптимизация (SSoT).
- **[NAT overview](../../../Networking/Concepts/nat/overview.md)** — обзор NAT и взаимодействие с conntrack.
- **[conntrack bypass](../../../Networking/Concepts/nat/conntrack_bypass.md)** — исключение трафика через NOTRACK.
- **[firewall troubleshooting](./firewall_troubleshooting.md)** — диагностика firewall.
- **[Docker conntrack](../../../Docker/Docker_performance_tuning.md)** — conntrack в контейнерах.
