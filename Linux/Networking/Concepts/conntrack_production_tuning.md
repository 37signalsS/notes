# Conntrack Production Tuning

## Определения

**Conntrack (Connection Tracking)** — модуль ядра Linux, отвечающий за отслеживание состояния сетевых соединений. Используется подсистемой Netfilter (iptables/nftables) для реализации stateful-фаервола, NAT (DNAT/SNAT) и функций RELATED-соединений. Каждая запись занимает ~300 байт RAM, поиск по хеш-таблице добавляет ~1-3 мкс задержки на пакет.

**nf_conntrack_max** — максимальное количество записей в таблице conntrack. При превышении ядро отбрасывает новые соединения с ошибкой `nf_conntrack: table full, dropping packet`.

**nf_conntrack_buckets** — размер хеш-таблицы. Оптимальное значение: `nf_conntrack_max / 4`. Увеличение ускоряет поиск при большом количестве соединений.

**Conntrack Zones** — механизм изоляции пространств соединений. Позволяет разным подсистемам (NAT, PBR, VPN) использовать независимые таблицы conntrack, избегая конфликтов.

## Теоретический блок

### Как conntrack обрабатывает пакеты

```
Входящий пакет
    │
    ▼
  raw (PREROUTING)  ← NOTRACK может исключить пакет
    │
    ▼
  conntrack: поиск записи
    │
    ├── Найдена → обновить состояние, пропустить
    │
    └── Не найдена → создать новую запись
         │
         ▼
       nat (PREROUTING) ← DNAT
         │
         ▼
       Маршрутизация
         │
         ▼
       filter ← Фильтрация (stateful rules)
         │
         ▼
       nat (POSTROUTING) ← SNAT
         │
         ▼
       Исходящий пакет
```

### Когда conntrack становится bottleneck

| Сценарий | Проблема | Симптомы |
|:---|:---|:---|
| **Высокий NPS (Packets Per Second)** | Каждый пакет требует поиска/создания записи | Рост CPU (`ksoftirqd`), рост latency |
| **Много коротких соединений** | Быстрое создание/удаление записей | Переполнение таблицы, `table full` в dmesg |
| **NAT на балансировщике** | Каждое соединение = запись conntrack | conntrack第一条项的增长速度超过清理速度 |
| **Неправильные таймауты** | Записи живут дольше, чем нужно | Таблица заполняется "мёртвыми" соединениями |
| **Docker/Kubernetes хост** | Много контейнеров = много соединений | 262144 (дефолт) исчерпывается при 10K+ контейнеров |

### Мониторинг состояния conntrack

```bash
# Текущее использование vs максимум
cat /proc/sys/net/netfilter/nf_conntrack_count    # текущее
cat /proc/sys/net/netfilter/nf_conntrack_max      # максимум

# Процент использования
echo "scale=1; $(cat /proc/sys/net/netfilter/nf_conntrack_count) * 100 / $(cat /proc/sys/net/netfilter/nf_conntrack_max)" | bc
# → 67.3%

# Детальная статистика
conntrack -S
# → cpu=0   found=1234567 invalid=1234 ignore=0 delete=1234 delete_list=1234 insert=1234 insert_failed=12 drop=12 early_drop=12 error=12 search_restart=12

# Размер хеш-таблицы
conntrack -C    # текущее количество записей (аналог nf_conntrack_count)

# Просмотр всех соединений
conntrack -L
conntrack -L -p tcp --dport 80    # фильтр по порту

# Мониторинг в реальном времени
watch -n 1 'echo "Count: $(cat /proc/sys/net/netfilter/nf_conntrack_count) / Max: $(cat /proc/sys/net/netfilter/nf_conntrack_max)"'
```

## Практические сценарии

### Сценарий 1: Расчёт nf_conntrack_max для production-сервера

**Формула:**
```
nf_conntrack_max = (ожидаемые_одновременные_соединения × 4) × число_интерфейсов_NAT
```

**Примеры расчёта:**

| Тип сервера | Ожидаемые соединения | Рекомендуемый max |
|:---|:---|:---|
| Веб-сервер (10K RPS) | 10 000 | 524 288 |
| Балансировщик (50K RPS) | 50 000 | 1 048 576 |
| NAT-шлюз (100K соединений) | 100 000 | 2 097 152 |
| Docker-хост (100 контейнеров) | 20 000 | 524 288 |
| Kubernetes-нода (500 подов) | 50 000 | 1 048 576 |

### Сценарий 2: Оптимизация для веб-сервера

```bash
# /etc/sysctl.d/99-conntrack-tuning.conf

# Размер таблицы
net.netfilter.nf_conntrack_max = 524288
net.netfilter.nf_conntrack_buckets = 131072

# Таймауты TCP (сокращены для высоконагруженных серверов)
net.netfilter.nf_conntrack_tcp_timeout_established = 600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_syn_sent = 30
net.netfilter.nf_conntrack_tcp_timeout_syn_recv = 15
net.netfilter.nf_conntrack_tcp_timeout_last_ack = 15

# Таймауты UDP
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 180

# Таймаут ICMP
net.netfilter.nf_conntrack_icmp_timeout = 10

# Опции
net.netfilter.nf_conntrack_tcp_be_liberal = 0
net.netfilter.nf_conntrack_tcp_loose = 1

# Применить
sysctl -p /etc/sysctl.d/99-conntrack-tuning.conf
```

### Сценарий 3: Оптимизация для Docker-хоста

Docker активно использует NAT для сетей контейнеров. Conntrack — частый bottleneck.

```bash
# /etc/sysctl.d/99-docker-conntrack.conf

net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144

# Агрессивные таймауты для Docker
net.netfilter.nf_conntrack_tcp_timeout_established = 600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_udp_timeout = 15
net.netfilter.nf_conntrack_udp_timeout_stream = 60
```

**Проверка:**
```bash
# Мониторинг во время нагрузки
watch -n 1 'conntrack -C; cat /proc/sys/net/netfilter/nf_conntrack_max'

# Логирование table full
dmesg | grep "nf_conntrack: table full"
journalctl -k | grep conntrack
```

### Сценарий 4: Conntrack bypass для высоконагруженных сервисов

Для балансировщиков и reverse-proxy conntrack часто не нужен — они сами отслеживают соединения.

```bash
# Исключение трафика nginx/haproxy из conntrack через raw table (nftables)
nft add rule ip raw prerouting iif eth0 ip daddr 10.0.0.100 tcp dport { 80, 443 } notrack

# Или через iptables
iptables -t raw -A PREROUTING -p tcp -d 10.0.0.100 --dport 80 -j NOTRACK
iptables -t raw -A PREROUTING -p tcp -d 10.0.0.100 --dport 443 -j NOTRACK

# Обратите внимание: для NOTRACK-трафика НЕ работают:
# - stateful-правила (-m conntrack --ctstate)
# - Автоматический обратный DNAT/SNAT
# - Модули RELATED (ftp, sip)
```

### Сценарий 5: Conntrack zones для изоляции

```bash
# Zone 1: для VPN-трафика
nft add rule ip nat prerouting iif tun0 ct zone set 1
nft add rule ip nat postrouting oif tun0 ct zone set 1

# Zone 2: для Docker-контейнеров
nft add rule ip nat prerouting iif docker0 ct zone set 2

# Просмотр записей по зонам
conntrack -L --zone 1
conntrack -L --zone 2
```

### Сценарий 6: Диагностика problèmes conntrack

```bash
# 1. Проверка текущего использования
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max
# → Если count/max > 0.8 — проблема скоро наступит

# 2. Проверка статистики ошибок
conntrack -S
# → insert_failed > 0: проблема с хеш-таблицей, увеличьте buckets
# → drop > 0: таблица переполнена или early_drop срабатывает
# → search_restart > 0: неоптимальный размер buckets

# 3. Поиск "мёртвых" соединений
conntrack -L -o extended | awk '{if($4=="TIME_WAIT" || $4=="CLOSE_WAIT") count++} END{print count}'
# → Много TIME_WAIT/CLOSE_WAIT = таймауты слишком длинные

# 4. Мониторинг в реальном времени
conntrack -E
# → Показывает события создания/удаления записей

# 5. Проверка是否有 table full ошибок
dmesg | grep -i conntrack | tail -20
journalctl -k --since "1 hour ago" | grep conntrack
```

## Диагностика и устранение неполадок

| Проблема | Симптом | Решение |
|:---|:---|:---|
| `nf_conntrack: table full, dropping packet` | Новые соединения отброшены | Увеличить `nf_conntrack_max`, сократить таймауты |
| Высокий CPU на `ksoftirqd` | Много пакетов обрабатывается conntrack | Увеличить `nf_conntrack_buckets`, рассмотреть NOTRACK |
| `insert_failed > 0` | Конфликты хеш-таблицы | Увеличить `nf_conntrack_buckets` до `max/4` |
| Много TIME_WAIT записей | Длинные таймауты | Уменьшить `nf_conntrack_tcp_timeout_time_wait` |
|_conntrack вызывает latency | Задержки на high PPS | Использовать NOTRACK для трафика proxy/balancer |
| Docker-контейнеры теряют связь | conntrack table full на хосте | Увеличить max + оптимизировать таймауты UDP |

## Дополнительная информация

### Параметры ядра для тонкой настройки

| Параметр | По умолчанию | Описание | Рекомендация |
|:---|:---|:---|:---|
| `nf_conntrack_max` | 262144 | Максимум записей | Рассчитать по формуле |
| `nf_conntrack_buckets` | max/4 | Размер хеш-таблицы | max/4 |
| `nf_conntrack_tcp_timeout_established` | 432000 (5 дней) | Таймаут ESTABLISHED | 600 (10 мин) |
| `nf_conntrack_tcp_timeout_time_wait` | 120 | Таймаут TIME_WAIT | 30 |
| `nf_conntrack_tcp_timeout_close_wait` | 60 | Таймаут CLOSE_WAIT | 15 |
| `nf_conntrack_tcp_timeout_fin_wait` | 120 | Таймаут FIN_WAIT | 15 |
| `nf_conntrack_udp_timeout` | 30 | Таймаут UDP | 15-30 |
| `nf_conntrack_udp_timeout_stream`` | 180 | Таймаут UDP-стрига | 60-180 |
| `nf_conntrack_icmp_timeout` | 10 | Таймаут ICMP | 10 |
| `nf_conntrack_tcp_be_liberal` | 0 | Режим проверки | 0 (строгий) |
| `nf_conntrack_tcp_loose` | 1 | Проверка без полного handshake | 1 |

### См. также

- [Conntrack Bypass (NOTRACK)](../../Networking/Concepts/nat/conntrack_bypass.md) — исключение из conntrack
- [Conntrack Helpers (ALG)](../../Networking/Concepts/nat/conntrack_helpers.md) — модули для протоколов
- [nftables — производительность](../../Linux/Networking/Settings/tools/nftables/performance_tuning.md) — flowtable, XDP
- [Docker Performance Tuning](../../Docker/Docker_performance_tuning.md) — conntrack для Docker
- [Network Monitoring Stack](../Monitoring/network_monitoring_stack.md) — мониторинг conntrack через Prometheus
