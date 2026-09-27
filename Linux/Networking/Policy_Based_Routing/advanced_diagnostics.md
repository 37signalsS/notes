# Продвинутая диагностика Policy-Based Routing (PBR)

## Определения

**Продвинутая диагностика PBR** — комплексный подход к поиску проблем маршрутизации на основе политик, включающий eBPF-трассировку пакетов через ядро, BPF-фильтры tcpdump, логирование nftables и анализ таблицы conntrack. В отличие от базовой диагностики (`ip route get`, `ip rule show`), продвинутые методы позволяют увидеть **реальный путь пакета** через RPDB, а не эмуляцию.

**eBPF (extended Berkeley Packet Filter)** — технология ядра Linux, позволяющая выполнять произвольные программы в ядре без перезагрузки. Для диагностики PBR используется через инструменты `pwru` ( Packet Wehicle Routing Utility), `bpftrace` и BCC-утилиты.

**pwru (Packet Wehicle Routing Utility)** — eBPF-инструмент для трассировки пути конкретного пакета через сетевой стек ядра. Показывает каждый хук Netfilter, каждое правило RPDB, которое обрабатывает пакет, и причину дропа.

**BPF-фильтр (tcpdump)** — расширенный фильтр захвата пакетов, основанный на BPF(Bytecode). Позволяет фильтровать по атрибутам L3/L4 (from, iif, fwmark) для захвата только PBR-релевантного трафика.

Базовая диагностика описана в **[Администрирование PBR](./administration.md)**.

---

## Предпосылки

### Требования к ядру

Для eBPF-инструментов необходимо ядро 4.9+ с включёнными опциями:

```bash
grep -E "CONFIG_BPF|CONFIG_BPF_SYSCALL|CONFIG_DEBUG_INFO_BTF" /boot/config-$(uname -r)
# → CONFIG_BPF=y
# → CONFIG_BPF_SYSCALL=y
# → CONFIG_DEBUG_INFO_BTF=y (для bpftrace)
```

### Установка инструментов

```bash
# Debian/Ubuntu
sudo apt install -y bpfcc-tools bpftrace linux-headers-$(uname -r) tcpdump conntrack

# RHEL/CentOS/Rocky/Alma
sudo dnf install -y bcc-tools bpftrace kernel-headers tcpdump conntrack-tools

# pwru (установка из исходников или бинарника)
# GitHub: https://github.com/cilium/pwru
wget https://github.com/cilium/pwru/releases/latest/download/pwru-linux-amd64.tar.gz
tar xzf pwru-linux-amd64.tar.gz
sudo mv pwru /usr/local/bin/
```

---

## Основные концепции

### Уровни диагностики PBR

| Уровень | Инструмент | Что показывает | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Эмуляция** | `ip route get` | Какое решение примет ядро для пакета с указанными атрибутами | Первичная проверка, быстрая валидация |
| **Захват** | `tcpdump` | Реальные пакеты на интерфейсе (вход/выход) | Проверка симметрии, поиск丢失 пакетов |
| **Фильтрация** | `tcpdump -i ... icmp` | Конкретный тип трафика (по протоколу, порту, адресу) | Целенаправленный поиск |
| **Трассировка ядра** | `pwru`, `bpftrace` | Путь пакета через хуки Netfilter, RPDB, conntrack | Сложные инциденты,找不到 причины дропа |
| **Статистика** | `conntrack -S`, `nft list ruleset` | Счётчики правил, drop-причины | Мониторинг, выявление узких мест |
| **Логирование** | `nft log`, `conntrack -E` | Логи в реальном времени для каждого пакета | Временная отладка (нагрузка!) |

### Место PBR в пути обработки пакета

Для диагностики важно понимать, в каком порядке ядро обрабатывает пакет:

```
Входящий пакет
    │
    ▼
1. Netfilter PREROUTING (mangle, nat, filter)
    │  ← fwmark устанавливается ЗДЕСЬ
    ▼
2. Routing Decision (RPDB → ip rule → table lookup)
    │  ← PBR-правиларабатывают ЗДЕСЬ
    ▼
3. Netfilter OUTPUT (mangle, nat, filter)
    │  ← fwmark для локально генерируемых пакетов
    ▼
4. Netfilter POSTROUTING (mangle, nat, filter)
    │  ← Маркировка ЗДЕСЬ НЕ работает для PBR
    ▼
5. Выход на интерфейс
```

---

## Практические сценарии

### Сценарий 1: Трассировка пакета через pwru

#### Задача

Пакет от `192.168.1.50` к `8.8.8.8` должен идти через таблицу `isp1_table`, но идёт через `main`. Найти, где именно пакет "сбивается".

#### Захват пакета

```bash
# Трассировка всех пакетов от конкретного IP-источника
sudo pwru --filter "src host 192.168.1.50 and dst host 8.8.8.8"
# → Показывает каждый хук ядра для пакета:
# → [prerouting] ... mark=0x0
# → [rpdb_lookup] ... table=main (ожидалась isp1_table!)
# → [routing_decision] ... dev=eth0
```

#### Анализ

pwru покажет, что в `rpdb_lookup` ядро выбрало таблицу `main` вместо `isp1_table`. Это значит, что PBR-правило не совпало с атрибутами пакета.

#### Проверка

```bash
# Эмуляция с теми же параметрами
ip route get 8.8.8.8 from 192.168.1.50
# → 8.8.8.8 via 192.168.1.1 dev eth0 src 192.168.1.50 uid 0
#     cache ← таблица main!

# Проверка правила
ip rule show | grep "from 192.168.1.0/24"
# → Пусто! Правило не добавлено или имеет другой приоритет.
```

#### Решение

Добавить или исправить PBR-правило:

```bash
sudo ip rule add from 192.168.1.0/24 table isp1_table priority 100
```

---

### Сценарий 2: Захват tcpdump с BPF-фильтром для PBR

#### Фильтрация по входящему интерфейсу

```bash
# Захват трафика, приходящего через ISP1 (eth1)
sudo tcpdump -i eth1 -n -c 10 'src net 192.168.1.0/24'

# Захват только HTTP-трафика через ISP2 (eth2)
sudo tcpdump -i eth2 -n -c 10 'tcp port 80 or tcp port 443'

# Захват ICMP-трафика (для проверки симметрии)
sudo tcpdump -i eth0 -n 'icmp' &
sudo tcpdump -i eth1 -n 'icmp' &
ping -c 10 -I 192.168.1.50 8.8.8.8
```

#### Проверка симметрии через tcpdump

```bash
# Одновременный захват на обоих ISP
sudo tcpdump -i eth1 -n 'host 8.8.8.8' -w /tmp/isp1.pcap &
sudo tcpdump -i eth2 -n 'host 8.8.8.8' -w /tmp/isp2.pcap &
PID1=$!
PID2=$!

# Генерация трафика
curl -s https://ifconfig.me > /dev/null

sleep 5
kill $PID1 $PID2

# Анализ: ответы должны быть только на том же интерфейсе
tcpdump -r /tmp/isp1.pcap -n | head -5
tcpdump -r /tmp/isp2.pcap -n | head -5
```

#### BPF-фильтр для конкретного fwmark

Если интерфейсы пересекаются (bridge, bond), BPF-фильтр по fwmark:

```bash
# Захват пакетов с определенным DSCP (аналог fwmark на L3)
sudo tcpdump -i any -n 'ip and (ip[1] & 0xfc) >> 2 = 46'
# → DSCP = 46 (EF) — VoIP-трафик
```

---

### Сценарий 3: Логирование PBR-правил через nftables

#### Временное логирование

```bash
# Логирование пакетов, попадающих под PBR (mark 0x1)
nft add rule inet filter prerouting meta mark 0x1 log prefix "PBR-HIT-ISP1: " level info

# Логирование пакетов, НЕ попадающих ни под одно PBR-правило
nft add rule inet filter prerouting meta mark 0x0 log prefix "PBR-MISS: " level warning

# Ограничение логирования (1 пакет в секунду для избежания лог-спама)
nft add rule inet filter prerouting meta mark 0x0 limit rate 1/second log prefix "PBR-MISS: " level warning
```

#### Чтение логов

```bash
# Логи nftables в dmesg
dmesg | grep "PBR-HIT-ISP1:" | tail -10
# → [12345.678] PBR-HIT-ISP1: IN=eth1 OUT= SRC=192.168.1.50 DST=8.8.8.8 ...

# Логи в syslog
grep "PBR-" /var/log/syslog | tail -20
```

#### Удаление временных правил логирования

```bash
# Просмотр правил с handle
nft -a list chain inet filter prerouting | grep "PBR-"

# Удаление по handle
nft delete rule inet filter prerouting handle 42
```

---

### Сценарий 4: Мониторинг через conntrack в реальном времени

```bash
# Мониторинг новых соединений с фильтрацией по порту
conntrack -E -p tcp --dport 443
# → [NEW] tcp 6 120 SYN_SENT src=10.0.0.5 dst=8.8.8.8 sport=43210 dport=443 ...

# Мониторинг изменений ct mark
conntrack -E --mask-mark 0xff
# → [UPDATE] ... mark=0x1 ...
```

---

## Диагностика и устранение неисправностей

### Пошаговый алгоритм диагностики

```
1. Эмуляция (ip route get)
   ├── Таблица верная? → Правило работает, проблема в маршруте
   └── Таблица неверная? → Перейти к шагу 2

2. Проверка правила (ip rule show)
   ├── Правило существует? → Проверить приоритет и селектор
   └── Правило отсутствует? → Добавить или проверить персистентность

3. Проверка фильтрации (nft/iptables)
   ├── fwmark устанавливается? → Перейти к шагу 4
   └── fwmark не устанавливается? → Проверить цепочку (PREROUTING vs POSTROUTING)

4. Трассировка (pwru / bpftrace)
   ├── Пакет попадает в PREROUTING? → fwmark.set проблема
   └── Пакет попадает в OUTPUT? → Локальный трафик, проверить iif lo

5. Проверка conntrack
   ├── Соединение ESTABLISHED? → ct mark восстанавливает fwmark
   └── Соединение NEW/INVALID? → CONNMARK не настроен
```

### Типичные проблемы и диагностика

| Симптом | Инструмент диагностики | Что смотреть |
| :--- | :--- | :--- |
| **Пакет дропается без ICMP** | `pwru` | Смотреть последний хук перед drop: `nf_hook_slow` → `nft_do_chain` |
| **Пакет идёт не в ту таблицу** | `ip route get` + `pwru` | Сравнить `rpdb_lookup` с ожидаемой таблицей |
| **fwmark не устанавливается** | `nft monitor` + `tcpdump` | Проверить, что правила в `PREROUTING` (не `POSTROUTING`) |
| **Симметрия нарушена** | `tcpdump` на обоих ISP | Ответные пакеты уходят через другой интерфейс |
| **DNS не работает через VPN** | `conntrack -L -p udp --dport 53` | DNS-запрос уходит не через VPN-интерфейс |
| **Высокий latency при PBR** | `tcpdump -tttt` + `mtr` | Задержка на конкретном хопе |

### Безопасность при диагностике

- **Не оставляйте `nft log` в production** — логирование каждого пакета создаёт нагрузку на CPU и диск.
- **Используйте `limit rate`** для ограничения логирования: `limit rate 1/second`.
- **Ограничивайте `pwru` фильтром** — без фильтра pwru обрабатывает ВСЕ пакеты и может нагрузить систему.
- **Удаляйте временные правила логирования** после отладки.

---

## Лучшие практики

1. **Начинайте с `ip route get`** — это быстрее eBPF и покрывает 80% случаев.
2. **Используйте `pwru` только для сложных случаев** — он требует root и может влиять на производительность.
3. **Ограничивайте `tcpdump` количеством пакетов** (`-c 100`) и временем (`timeout 10`).
4. **Логируйте только при отладке** — `nft log` в production создает нагрузку.
5. **Сравнивайте эмуляцию и реальность** — `ip route get` vs `pwru` для одного и того же пакета.
6. **Документируйте фильтры tcpdump** — BPF-фильтры сложны для восприятия, сохраняйте их в скриптах.
7. **Используйте `conntrack -S` для быстрой оценки** — `drop` и `insert_failed` сразу показывают проблемы.

---

## Дополнительная информация

### Сравнение инструментов

| Инструмент | Overhead | Детализация | Удобство | Production-safe |
| :--- | :--- | :--- | :--- | :--- |
| `ip route get` | Минимальный | Решение ядра (эмуляция) | Отличное | Да |
| `tcpdump` | Средний | L2-L4 пакеты | Хорошее | Осторожно |
| `nft log` | Высокий | Каждый пакет в лог | Среднее | Только для отладки |
| `pwru` | Средний | Путь через ядро | Среднее | Осторожно |
| `bpftrace` | Низкий | Произвольные хуки ядра | Низкое (нужен BPF) | Да (с фильтрами) |
| `conntrack -E` | Средний | События соединений | Среднее | Осторожно |

### Связанные документы

- **[Администрирование PBR](./administration.md)** — базовая диагностика (`ip route get`, troubleshooting table).
- **[Практические сценарии PBR](./scenarios.md)** — сценарии с валидацией.
- **[Conntrack и PBR](./conntrack_pbr.md)** — conntrack tuning, CONNMARK, zones.
- **[Потеря пакетов в сетевом стеке Linux](../../Networking/network_stack_packet_loss.md)** — анализ drop на разных уровнях.
- **[Порядок сетевой диагностики](../../Networking/network_troubleshooting_order.md)** — bottom-up подход.
- **[pwru — трассировка пакетов](../../../Networking/ServicesAndTools/Wireshark/ebpf_diagnostics_tools.md)** — eBPF-инструменты для сети.
