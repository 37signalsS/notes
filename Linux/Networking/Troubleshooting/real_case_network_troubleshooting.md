# Реальные сценарии траблшутинга сети

## Определения

**Production Troubleshooting** — методология диагностики и устранения сетевых проблем в рабочей среде. В отличие от лабораторных тестов, требует минимального влияния на сервисы, быстрого определения корневой причины и документирования действий.

**Root Cause Analysis (RCA)** — методология определения истинной причины инцидента, а не его симптомов. Ключевой принцип: сначала собрать данные, затем анализировать, затем исправлять.

**Blast Radius** — область воздействия проблемы. При траблшутинге важно ограничить blast radius, не усугубляя ситуацию.

## Теоретический блок

### Методология траблшутинга (USE/LOAF)

```
┌─────────────────────────────────────────────────────────┐
│ 1. СОБРАТЬ ДАННЫЕ (без изменений!)                      │
│    - Метрики (Prometheus/Grafana)                       │
│    - Логи (journalctl, dmesg)                           │
│    - Состояние (ss, conntrack, ip neigh)                │
├─────────────────────────────────────────────────────────┤
│ 2. ОГРАНИЧИТЬ BLast RADIUS                              │
│    - Не менять конфигурацию пока не понята причина      │
│    - Использовать read-only команды                     │
├─────────────────────────────────────────────────────────┤
│ 3. АНАЛИЗИРОВАТЬ ПО OSI (снизу вверх)                   │
│    L1 → L2 → L3 → L4 → L7                             │
├─────────────────────────────────────────────────────────┤
│ 4. ИСПРАВИТЬ и проверить                                │
│    - Одно изменение за раз                              │
│    - Зафиксировать каждое действие                      │
├─────────────────────────────────────────────────────────┤
│ 5. ЗАДОКУМЕНТИРОВАТЬ                                     │
│    - Timeline, причина, решение, предотвращение         │
└─────────────────────────────────────────────────────────┘
```

### Приоритет диагностики по OSI

| Уровень | Инструменты | Что проверять |
|:---|:---|:---|
| **L1** | `ip link`, `ethtool`, `dmesg` | Состояние линка, скорость, дуплекс, ошибки NIC |
| **L2** | `ip neigh`, `bridge`, `arp` | ARP-таблица, MAC-адреса, VLAN |
| **L3** | `ip route`, `ping`, `traceroute` | Маршрутизация, MTU, фрагментация |
| **L4** | `ss`, `conntrack`, `nstat` | Соединения, таймауты, ретрансмиссии |
| **L7** | `curl`, `dig`, `tcpdump` | Прикладной протокол, заголовки, TLS |

## Практические сценарии

### Кейс 1: Высокий latency на веб-сервере

**Симптом:** Пользователи жалуются на медленную загрузку страниц. p99 latency вырос с 200ms до 2s.

**Сбор данных (read-only):**

```bash
# 1. Проверка сетевых интерфейсов
ip -s link show eth0
# → errors, drops, overruns — сравнить с baseline

# 2. TCP-статистика
nstat -az | grep -E 'Retrans|InErrs|OutRsts|TcpLoss'
# → RetransSegs растёт = проблема с доставкой пакетов

# 3. Conntrack
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max
# → Если > 80% — проблема

# 4. Состояние соединений
ss -s
# → SYN-RECV > 100 = возможная атака или проблемы с бэкендами

# 5. Проверка дропов на интерфейсе
cat /proc/net/dev | grep eth0
# → rx_drops, tx_drops растут = NIC не успевает
```

**Анализ:**

```bash
# Проверка interrupt coalescing
ethtool -c eth0
# → If rx-usecs слишком высок = задержка на уровне NIC

# Проверка RSS
ethtool -x eth0
# → Неравномерное распределение по ядрам

# Проверка TCP retransmissiondest
ss -ti | grep -E 'retrans|rto'
# → retrans > 0 на большинстве соединений = сетевая проблема

# Проверка dmesg на ошибки NIC
dmesg | grep -i -E 'eth0|nic|link|error|timeout'
```

**Решение (пример):**

```bash
# Причина: NIC обрабатывает меньше пакетов, чем приходит
# Решение: включение interrupt coalescing + RSS

ethtool -C eth0 rx-usecs 50 rx-frames 64
# → Снижение частоты прерываний, увеличение батчей

# Проверка через 5 минут
ip -s link show eth0
# → drops.stop increasing
```

**Escalation:** Если проблема сохраняется — проверить upstream (провайдер, коммутатор), возможно асимметричная маршрутизация.

---

### Кейс 2: Packet loss на��оконагруженном сервере

**Симптом:** ~5% входящих пакетов отбрасываются. Сервер обрабатывает 50K RPS.

**Сбор данных:**

```bash
# 1. Детальная статистика интерфейса
ip -s -s link show eth0
# → RX errors, RX dropped, RX missed, RX no buffer

# 2. Проверка ring buffer
ethtool -g eth0
# → RX ring size: если маленький (256) при высоком NPS — проблема

# 3. Проверка NAPI и softirq
cat /proc/net/softnet_stat
# →第二列 = dropped (если растёт = CPU не успевает обрабатывать)

# 4. Проверка socket buffer overflow
nstat -az | grep -E 'TcpRcvQueueDrop|UdpRcvQueueDrop|ListenDrops'
# → RcvQueueDrop > 0 = приложение не читает сокет

# 5. Проверка conntrack
conntrack -S | grep -E 'drop|insert_failed'
# → drop > 0 = таблица переполнена
```

**Анализ:**

```bash
# Проверка softirq распределения по CPU
mpstat -P ALL 1 5
# → Если CPU0 (или один core) на 100% по softirq — проблема с RSS/RPS

# Проверка NAPI polling
cat /proc/net/softnet_stat | awk '{print $1, $2, $3}'
# → Формат: processed dropped time_squeeze
# → dropped > 0 = ядро не успевает

# Проверка socket receive queue
ss -tlnp | grep ':80'
# → Recv-Q > 0 = приложение не читает
```

**Решение (пример):**

```bash
# Причина 1: Маленький ring buffer
ethtool -G eth0 rx 4096
# → Увеличение аппаратного буфера NIC

# Причина 2: RSS не распределяет равномерно
ethtool -X eth0 equal 8
# → Распределение по 8 ядрам

# Причина 3: conntrack table full
sysctl -w net.netfilter.nf_conntrack_max=1048576
sysctl -w net.netfilter.nf_conntrack_buckets=262144

# Причина 4: socket buffer overflow
sysctl -w net.core.rmem_max=16777216
sysctl -w net.core.netdev_max_backlog=30000
```

---

### Кейс 3: Conntrack table full на Docker-хосте

**Симптом:** Контейнеры периодически теряют связь. В dmesg: `nf_conntrack: table full, dropping packet`.

**Сбор данных:**

```bash
# 1. Проверка текущего использования
cat /proc/sys/net/netfilter/nf_conntrack_count
cat /proc/sys/net/netfilter/nf_conntrack_max
# → 262144 / 262144 = 100% — таблица заполнена

# 2. Статистика conntrack
conntrack -S
# → drop > 0 = подтверждение

# 3. Проверка таймаутов
sysctl net.netfilter.nf_conntrack_tcp_timeout_established
# → 432000 (5 дней) — слишком долго для Docker

# 4. Проверка «мёртвых» соединений
conntrack -L | awk '{print $4}' | sort | uniq -c | sort -rn
# → TIME_WAIT: 200000 = большинство соединений в TIME_WAIT
```

**Решение:**

```bash
# 1. Увеличение max
sysctl -w net.netfilter.nf_conntrack_max=1048576
sysctl -w net.netfilter.nf_conntrack_buckets=262144

# 2. Сокращение таймаутов
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=600
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
sysctl -w net.netfilter.nf_conntrack_tcp_timeout_close_wait=15

# 3. Проверка
cat /proc/sys/net/netfilter/nf_conntrack_count
# → Начинает снижаться

# 4. Персистентность
cat >> /etc/sysctl.d/99-conntrack-docker.conf <<'EOF'
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144
net.netfilter.nf_conntrack_tcp_timeout_established = 600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
EOF
```

---

### Кейс 4: Асимметричная маршрутизация

**Симптом:** Пакеты теряются только в одну сторону. `ping` с одного хоста работает, с другого — нет.

**Сбор данных:**

```bash
# 1. Проверка маршрутов в обе стороны
ip route get 10.0.0.2
# → через какой интерфейс и gateway

# С другого хоста:
ip route get 10.0.0.1
# → через другой интерфейс = асимметрия

# 2. Проверка rp_filter
sysctl net.ipv4.conf.all.rp_filter
sysctl net.ipv4.conf.eth0.rp_filter
# → 1 (strict) = пакеты с «неправильного» интерфейса отбрасываются

# 3. Трассировка маршрута
traceroute -n 10.0.0.2
traceroute -n -I 10.0.0.2  # ICMP

# 4. Проверка таблицы маршрутизации
ip route show table all | grep -E 'default|10.0.0'
# → Возможны маршруты с different metrics
```

**Анализ:**

```bash
# Проверка reverse path filtering
cat /proc/sys/net/ipv4/conf/all/rp_filter
# → Если = 1 и маршрутизация асимметричная — пакеты отбрасываются

# Проверка conntrack при асимметрии
conntrack -L | grep 10.0.0.1
# → Записи могут отсутствовать для одного направления
```

**Решение:**

```bash
# Вариант 1: Исправить маршрутизацию (предпочтительно)
ip route add 10.0.0.0/24 via 10.0.0.254 dev eth0

# Вариант 2: Loose mode (если асимметрия легитимна)
sysctl -w net.ipv4.conf.all.rp_filter=2

# Вариант 3: Для specific интерфейса
sysctl -w net.ipv4.conf.eth0.rp_filter=2
```

---

### Кейс 5: DNS-резолвинг занимает 5+ секунд

**Симптом:** Приложения подолгу стартуют. `curl` к сервисам по имени зависает на 5 секунд.

**Сбор данных:**

```bash
# 1. Проверка времени резолвинга
time getent hosts example.com
# → real    0m5.012s = DNS таймаут

# 2. Проверка /etc/resolv.conf
cat /etc/resolv.conf
# → nameserver 10.0.0.53 — возможно, этот сервер недоступен

# 3. Проверка доступности DNS
dig @10.0.0.53 example.com
# →如果 таймаут — DNS-сервер недоступен

# 4. Проверка /etc/nsswitch.conf
grep hosts /etc/nsswitch.conf
# → hosts: files dns — если DNS недоступен, ищет в files

# 5. Проверка /etc/hosts
grep example.com /etc/hosts
# → Если нет записи и DNS недоступен = таймаут
```

**Анализ:**

```bash
# Проверка systemd-resolved
resolvectl status
# → Если Active: inactive — используется传统的 resolv.conf

# Проверка DNS через systemd-resolved
resolvectl query example.com
# → Если работает быстро = проблема в /etc/resolv.conf指向另一个 сервер

# Проверка connectivity до DNS
ping -c 3 10.0.0.53
# → Если丢失 = DNS-сервер недоступен
```

**Решение:**

```bash
# Быстрое решение: исправить /etc/resolv.conf
echo "nameserver 8.8.8.8" > /etc/resolv.conf

# Персистентное решение
cat > /etc/systemd/resolved.conf <<'EOF'
[Resolve]
DNS=8.8.8.8 1.1.1.1
FallbackDNS=8.8.4.4
DNSSEC=allow-downgrade
DNSOverTLS=opportunistic
EOF
systemctl restart systemd-resolved

# Проверка
time getent hosts example.com
# → real    0m0.003s
```

---

### Кейс 6: TCP-соединения застряли в TIME_WAIT

**Симптом:** `ss -s` показывает 50K+ соединений в TIME_WAIT. Новые соединения отклоняются.

**Сбор данных:**

```bash
# 1. Подсчёт соединений по состояниям
ss -s
# → TCP:   65535 (estab 1000, closed 64000, orphaned 500, timewait 63000)

# 2. Детализация
ss -tan state time-wait | wc -l
# → 63000 — много

# 3. Проверка sysctl
sysctl net.ipv4.tcp_tw_reuse
sysctl net.ipv4.tcp_fin_timeout
sysctl net.ipv4.tcp_max_tw_buckets
# → tcp_tw_reuse=0, tcp_fin_timeout=60, max_tw_buckets=262144

# 4. Источники TIME_WAIT
ss -tan state time-wait | awk '{print $4}' | cut -d: -f1 | sort | uniq -c | sort -rn | head
# → Показывает с каких IP больше TIME_WAIT
```

**Решение:**

```bash
# 1. Включить reuse (если безопасно для приложения)
sysctl -w net.ipv4.tcp_tw_reuse=1

# 2. Уменьшить fin_timeout
sysctl -w net.ipv4.tcp_fin_timeout=15

# 3. Ограничить max_tw_buckets
sysctl -w net.ipv4.tcp_max_tw_buckets=50000

# 4. Если приложение создает много коротких соединений
# Рассмотреть connection pooling (HTTP keep-alive, DB pooling)
```

## Диагностика и устранение неполадок

### Чек-лист快速诊断

```bash
# === L1/L2 ===
ip link show                              # Состояние линка
ethtool eth0                              # Скорость, дуплекс, ошибки
dmesg | tail -20                          # Ошибки NIC/ядра

# === L3 ===
ip route show                             # Маршрутизация
ip neigh show                             # ARP-таблица
ping -c 3 <gateway>                       # Связность с шлюзом
traceroute <destination>                   # Маршрут

# === L4 ===
ss -s                                     # Общая статистика соединений
ss -tan state established | wc -l         # Активные соединения
conntrack -S                              # Статистика conntrack
nstat -az | grep -E 'Retrans|Errs|Drop'  # TCP-ошибки

# === L7 ===
curl -w "dns: %{time_namelookup}s\ntcp: %{time_connect}s\nssl: %{time_appconnect}s\ntotal: %{time_total}s\n" -o /dev/null -s <url>
dig @<dns-server> <domain>                # DNS-резолвинг
```

### Эскалация

| Уровень | Действие | Кому |
|:---|:---|:---|
| L1/L2 | Проверить кабель, коммутатор, порт | Сетевой инженер |
| L3 | Проверить маршрутизацию, BGP-сессии | Сетевой инженер |
| L4 | Проверить firewall, conntrack, load balancer | Sysadmin / SRE |
| L7 | Проверить приложение, БД, DNS | Developer / SRE |

## Дополнительная информация

### См. также

- [DNS-мисконфигурация (кейс)](../../../Networking/Troubleshooting/real_case_troubleshooting_dns_misconfig.md) — реальный кейс с DNS
- [Kafka + PostgreSQL (кейс)](../../../Networking/Troubleshooting/real_case_troubleshooting_kafka_db.md) — распределённая диагностика
- [Network Troubleshooting Order](../network_troubleshooting_order.md) — порядок диагностики
- [Network Diagnostics Tools](../network_diagnostics_tools.md) — полный список инструментов
- [Conntrack Production Tuning](../Concepts/conntrack_production_tuning.md) — настройка conntrack
