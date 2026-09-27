# Conntrack и Policy-Based Routing (PBR)

## Определения

**Conntrack (Connection Tracking)** — подсистема ядра Linux (модуль Netfilter), отслеживающая состояния всех IP-соединений. Для PBR критична, так как соединения, маршрутизируемые через разные таблицы, могут конфликтовать в общей таблице conntrack.

**CONNMARK** — механизм Netfilter, позволяющий сохранять `fwmark` (метку PBR) в поле `ct mark` записи conntrack и восстанавливать её для ответных пакетов. Обеспечивает симметричную маршрутизацию при multi-ISP.

**Conntrack Zone** — логическая изоляция записей соединений в пределах одной таблицы conntrack. Записи в разных зонах не конфликтуют, даже если IP-адреса и порты совпадают. Критично для PBR с перекрывающимися RFC1918-пространствами.

**nf_conntrack: table full** — состояние, при котором таблица conntrack заполнена (достигнут `nf_conntrack_max`). Новые соединения отбрасываются с сообщением `nf_conntrack: table full, dropping packet`. При PBR-сценариях с несколькими ISP风险 возрастает из-за увеличения числа параллельных соединений.

Теоретические основы PBR описаны в **[главном разделе (SSoT)](./index.md)**. Общие параметры conntrack — в **[sysctl: сетевые параметры ядра](../../Networking/Settings/sysctl_network.md)** и **[NAT: обзор](../../../Networking/Concepts/nat/overview.md)**.

---

## Предпосылки

### Требования к пакетам

```bash
# Debian/Ubuntu
sudo apt install -y conntrack nftables

# RHEL/CentOS/Rocky/Alma
sudo dnf install -y conntrack-tools nftables
```

### Проверка текущего состояния conntrack

```bash
# Размер таблицы
sysctl net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_max = 262144

# Текущее количество записей
cat /proc/sys/net/netfilter/nf_conntrack_count
# → 184320

# Процент заполнения
awk 'BEGIN {printf "%.1f%%\n", ('$ (cat /proc/sys/net/netfilter/nf_conntrack_count)' / '$(cat /proc/sys/net/netfilter/nf_conntrack_max)') * 100}'
# → 70.3%

# Размер хеш-таблицы
cat /sys/module/nf_conntrack/parameters/hashsize
# → 65536

# Статистика (drop, insert_failed)
conntrack -S
# → cpu=0 found=123456 insert=123456 drop=0 insert_failed=0 ...
```

---

## Основные концепции

### Почему conntrack критичен для PBR

В стандартной конфигурации (один ISP) conntrack работает предсказуемо. При PBR с несколькими ISP возникают три ключевые проблемы:

1. **Асимметрия:** Пакет приходит через ISP1, ответ уходит через ISP2. Conntrack видит `INVALID` состояние, так как обратный путь не совпадает с прямым.
2. **Перекрытие адресов:** Два ISP используют одинаковые RFC1918-адреса (например, `10.0.0.0/8`). Conntrack не может различить соединения из разных сетей.
3. **满溢 при высокой нагрузке:** Каждый ISP удваивает число соединений в таблице. Сервер с 2 ISP и 10K соединений может нуждаться в `nf_conntrack_max=524288` вместо `262144`.

### Поток пакета через conntrack при PBR

```
Входящий пакет (ISP1, src=203.0.113.1)
    │
    ▼
PREROUTING → conntrack: NEW (create entry)
    │              ct mark = 0x1 (по iifname)
    │
    ▼
ip rule → fwmark 0x1 → table isp1_table → gateway ISP1
    │
    ▼
Ответный пакет (gateway ISP1 → src=ISP1_IP)
    │
    ▼
OUTPUT → conntrack: ESTABLISHED (match by tuple)
    │       ct mark → fwmark (восстановление)
    │
    ▼
ip rule → fwmark 0x1 → table isp1_table → через ISP1
```

### CONNMARK: сохранение меток PBR в conntrack

#### Проблема

PBR-правило `ip rule add fwmark 0x1 table isp1_table` работает только для **исходящих** пакетов. Ответные пакеты (от удалённого сервера) приходят без `fwmark` и маршрутизируются через таблицу `main`, что ломает симметрию.

#### Решение через CONNMARK

```bash
# 1. При входе: сохранить метку в conntrack
nft add rule inet filter prerouting \
    iifname "eth1" ct mark set 0x1

# 2. При исходе: восстановить метку из conntrack в fwmark
nft add rule inet filter output \
    ct mark 0x1 meta mark set 0x1

# 3. PBR-правило по fwmark
ip rule add fwmark 0x1 table isp1_table priority 1000
```

Для второго ISP:

```bash
nft add rule inet filter prerouting \
    iifname "eth2" ct mark set 0x2

nft add rule inet filter output \
    ct mark 0x2 meta mark set 0x2

ip rule add fwmark 0x2 table isp2_table priority 1001
```

#### Сохранение reply-path через CONNMARK target

Для полной симметрии (чтобы ответные пакеты тоже помечались):

```bash
# Сохранение ORIGINAL Direction mark
nft add rule inet filter prerouting \
    iifname "eth1" ct mark set 0x1 \
    counter

# Восстановление REPLY Direction mark (для ответов)
nft add rule inet filter output \
    ct mark 0x1 meta mark set 0x1 \
    counter
```

### Conntrack zones для PBR с перекрывающимися адресами

Когда два ISP используют одну RFC1918-адресацию (например, оба выдают `10.0.0.0/8` клиентам), conntrack не может различить соединения. Conntrack zones решают эту проблему:

```bash
# ISP1: zone 1
nft add rule ip nat prerouting iifname "eth1" ct zone set 1
nft add rule ip filter prerouting iifname "eth1" ct zone set 1

# ISP2: zone 2
nft add rule ip nat prerouting iifname "eth2" ct zone set 2
nft add rule ip filter prerouting iifname "eth2" ct zone set 2

# Просмотр записей по зонам
conntrack -L --zone 1
conntrack -L --zone 2
```

Схема:

```
Клиент A (10.0.0.5) ──► ISP1 (eth1) ──► Conntrack Zone 1
Клиент B (10.0.0.5) ──► ISP2 (eth2) ──► Conntrack Zone 2
                      ↑
            Записи не конфликтуют
```

---

## Практические сценарии

### Сценарий 1: Оптимизация conntrack для PBR-шлюза с 2 ISP

#### Задача

Сервер с двумя ISP обрабатывает 50K одновременных соединений. Текущий `nf_conntrack_max=262144` (дефолт) приводит к `table full` при всплесках нагрузки.

#### Решение

```bash
# /etc/sysctl.d/99-conntrack-pbr.conf

# Размер таблицы: 4x от ожидаемого числа соединений
net.netfilter.nf_conntrack_max = 1048576

# Хеш-таблица: nf_conntrack_max / 4
net.netfilter.nf_conntrack_buckets = 262144

# Таймауты (снижены для ускорения очистки)
net.netfilter.nf_conntrack_tcp_timeout_established = 3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait = 30
net.netfilter.nf_conntrack_tcp_timeout_close_wait = 15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait = 30
net.netfilter.nf_conntrack_udp_timeout = 30
net.netfilter.nf_conntrack_udp_timeout_stream = 120
net.netfilter.nf_conntrack_icmp_timeout = 30

# Логирование при满溢 (для алертинга)
net.netfilter.nf_conntrack_log_invalid = 1
```

```bash
# Применение
sudo sysctl --system

# Проверка
sysctl net.netfilter.nf_conntrack_max
cat /sys/module/nf_conntrack/parameters/hashsize
# → 262144
```

#### Мониторинг滿溢

```bash
# Проверка заполнения
watch -n 1 'echo "count/max: $(cat /proc/sys/net/netfilter/nf_conntrack_count)/$(cat /proc/sys/net/netfilter/nf_conntrack_max) = $(awk "BEGIN {printf \"%.1f%%\", ($(cat /proc/sys/net/netfilter/nf_conntrack_count) / $(cat /proc/sys/net/netfilter/nf_conntrack_max)) * 100}")"'

# Логирование table full
dmesg | grep "nf_conntrack: table full"

# Статистика (drop, insert_failed)
conntrack -S
# → Если insert_failed > 0: увеличить nf_conntrack_max и hashsize
```

---

### Сценарий 2: CONNMARK для симметричной маршрутизации через 2 ISP

#### Задача

Сервер получает входящий трафик через оба ISP. Ответы должны уходить через тот же ISP, через который пришел запрос.

#### Конфигурация nftables

```bash
# /etc/nftables.d/pbr-connmark.nft

table inet pbr_connmark {
    chain prerouting {
        type filter hook prerouting priority mangle; policy accept;

        # Маркировка по входящему интерфейсу + сохранение в ct mark
        iifname "eth1" ct mark set 0x1 comment "ISP1 traffic"
        iifname "eth2" ct mark set 0x2 comment "ISP2 traffic"
    }

    chain output {
        type filter hook output priority mangle; policy accept;

        # Восстановление fwmark из ct mark для ответных пакетов
        ct mark 0x1 meta mark set 0x1
        ct mark 0x2 meta mark set 0x2
    }
}
```

#### Конфигурация PBR

```bash
# Таблицы
echo "100 isp1_table" | sudo tee -a /etc/iproute2/rt_tables
echo "200 isp2_table" | sudo tee -a /etc/iproute2/rt_tables

# Маршруты
ip route add default via 192.168.1.1 dev eth1 table isp1_table
ip route add default via 192.168.2.1 dev eth2 table isp2_table

# PBR-правила
ip rule add fwmark 0x1 table isp1_table priority 1000
ip rule add fwmark 0x2 table isp2_table priority 1001
```

#### Валидация

```bash
# Проверка правил
ip rule show | grep "fwmark"
# → 1000:	from all fwmark 0x1 lookup isp1_table
# → 1001:	from all fwmark 0x2 lookup isp2_table

# Мониторинг ct mark
nft monitor | head -20
# → При новом соединении будет видно: ct mark set 0x1

# Проверка статистики
nft list chain inet pbr_connmark prerouting
# → counter packets 1234 bytes 567890
```

---

### Сценарий 3: Диагностика conntrack-проблем при PBR

#### Проблема: Соединения в состоянии INVALID

```bash
# Проверка INVALID-соединений
conntrack -L -o extended | grep INVALID | wc -l
# → 42 (если много — проблема с симметрией)

# Детали
conntrack -L -o extended | grep INVALID | head -5
# → tcp 6 29 SYN_SENT src=10.0.0.5 dst=8.8.8.8 sport=43210 dport=443 [UNREPLIED] src=8.8.8.8 dst=203.0.113.1 sport=443 dport=33456 mark=0 ...
```

**Причина:** Ответный пакет приходит через другой ISP, не совпадает с ожидаемым обратным путём.

**Решение:** Включить CONNMARK (Сценарий 2) или установить `rp_filter=2` (Loose mode).

#### Проблема: conntrack滿溢 при PBR failover

При падении ISP1 весь трафик переключается на ISP2, что удваивает нагрузку на conntrack:

```bash
# Мониторинг в реальном времени
watch -n 0.5 'conntrack -C'

# Если count приближается к max —紧急增加
sudo sysctl -w net.netfilter.nf_conntrack_max=2097152
echo $((2097152/4)) | sudo tee /sys/module/nf_conntrack/parameters/hashsize
```

#### Проблема: DNS-запросы не возвращаются через тот же ISP

```bash
# Проверка: DNS идёт через eth1, ответ приходит через eth2
conntrack -L -p udp --dport 53 | grep "10.0.0.5"

# Решение: правило для DNS-трафика
ip rule add ipproto udp dport 53 table isp1_table priority 50
```

---

## Диагностика и устранение неисправностей

### Типичные проблемы

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`nf_conntrack: table full`** | `nf_conntrack_max` слишком мал | `conntrack -S` → `drop` > 0 | Увеличить `nf_conntrack_max`, уменьшить таймауты |
| **Соединения в INVALID** | Асимметричная маршрутизация без CONNMARK | `conntrack -L \| grep INVALID` | Включить CONNMARK или `rp_filter=2` |
| **DNS-таймауты через VPN** | DNS-запрос уходит не через VPN | `conntrack -L -p udp --dport 53` | `ip rule add ipproto udp dport 53 table vpn_table` |
| **insert_failed > 0** | Хеш-таблица слишком мала | `conntrack -S \| grep insert_failed` | Увеличить `hashsize` (nf_conntrack_max / 4) |
| **Долгая очистка соединений** | `tcp_timeout_established` = 5 дней | `sysctl net.netfilter.nf_conntrack_tcp_timeout_established` | Снизить до 3600–7200 |
| **_conntrack满溢 при failover** | Все трафик на один ISP | Мониторинг `nf_conntrack_count` при failover | Увеличить `nf_conntrack_max` с запасом |

### Статистика conntrack

```bash
# Статистика по CPU
conntrack -S
# → cpu=0 found=123456 insert=123456 drop=0 insert_failed=0 early_drop=0 ...

# Просмотр всех соединений
conntrack -L

# Соединения для конкретного IP
conntrack -L -s 10.0.0.5

# Соединения для конкретного порта
conntrack -L -p tcp --dport 443

# Соединения в определенной зоне
conntrack -L --zone 1

# Удаление всех записей (ОСТОРОЖНО!)
conntrack -F
```

---

## Лучшие практики

1. **Рассчитывайте `nf_conntrack_max` с запасом:** Ожидаемое число соединений × 4. Для PBR с N ISP — умножайте на N.
2. **Настройте `hashsize`:** `nf_conntrack_max / 4` для баланса между памятью и производительностью.
3. **Снижайте таймауты:** `tcp_timeout_established=3600` вместо 432000 (5 дней) ускоряет очистку.
4. **Используйте CONNMARK для симметрии:** Без него PBR с несколькими ISP приводит к INVALID-соединениям.
5. **Используйте conntrack zones при перекрытии RFC1918:** Обязательно для multi-ISP с одинаковой адресацией.
6. **Мониторьте `insert_failed`:** Если > 0 — увеличивайте `hashsize`.
7. **Логируйте `table full`:** `dmesg | grep conntrack` для своевременного обнаружения满溢.
8. **Отключайте conntrack дляetrics-heavy трафика:** Если PBR направляет только маршрутизируемый трафик (без NAT), conntrack не нужен. Отключение: `notrack` в nftables.

---

## Дополнительная информация

### Память, потребляемая conntrack

Каждая запись conntrack занимает ~300 байт. При `nf_conntrack_max=1048576` потребление памяти:

```
1048576 × 300 байт = ~300 МБ
```

Для серверов с 16+ ГБ RAM это приемлемо. Для серверов с ограниченной памятью — уменьшайте `nf_conntrack_max`.

### Связанные документы

- **[Policy-Based Routing (PBR) — Обзор](./index.md)** — архитектура и база данных правил RPDB.
- **[Практические сценарии PBR](./scenarios.md)** — CONNMARK-сценарий (Сценарий 4).
- **[Администрирование PBR](./administration.md)** — conntrack tuning в разделе sysctl.
- **[sysctl: сетевые параметры ядра](../../Networking/Settings/sysctl_network.md)** — conntrack sizing и таймауты.
- **[NAT: обзор](../../../Networking/Concepts/nat/overview.md)** — conntrack zones и трансляция.
- **[Reverse Path Filtering (RPF/uRPF)](../../../Networking/Protocols/rpf_urpf.md)** — rp_filter и PBR.
