# Инструменты диагностики сети

## Определения

**Сетевая диагностика** — это систематический процесс выявления, анализа и устранения проблем в компьютерных сетях. Она включает в себя мониторинг доступности, измерение производительности, глубокий анализ трафика и верификацию конфигураций сетевого стека ОС и оборудования.

**Пропускная способность (Bandwidth/Throughput)** — максимальный объем данных, передаваемых по каналу в единицу времени. Измеряется в битах/сек (bps). Различают theoretical bandwidth (скорость канала) и goodput (полезная пропускная способность прикладного уровня).

**Задержка (Latency/RTT)** — время прохождения пакета от отправителя до получателя и обратно. Измеряется в миллисекундах (ms). Высокая задержка с низким jitter характерна для пропускных каналов; высокая задержка с высоким jitter — для перегруженных или нестабильных каналов.

**Потери пакетов (Packet Loss)** — процент пакетов, не достигших цели. Измеряется в %. Даже 0.1% потерь на TCP вызывают ретрансмиссии и снижение пропускной способности; на UDP — потерю данных.

**MTU (Maximum Transmission Unit)** — максимальный размер пакета (в байтах), который может быть передан по сетевому интерфейсу без фрагментации. Стандартное значение Ethernet: 1500 Б. PMTUD (Path MTU Discovery) — механизм автоматического определения минимального MTU на всем пути.

**MSS (Maximum Segment Size)** — максимальный размер сегмента данных в TCP-пакете (за вычетом заголовков). Обычно MSS = MTU - 40 (IPv4) или MTU - 60 (IPv6). Согласовывается в TCP SYN через опцию MSS.

**TCP Window Size** — размер окна приемника, определяющий, сколько данных получатель готов принять без подтверждения. Определяет скорость передачи в момент времени: `Throughput ≈ Window Size / RTT`.

**Socket Backlog** — очередь невыполненных соединений (SYN-RECV) и ожидающих `accept()` соединений (LISTEN). Ограничена `net.core.somaxconn` и параметром `listen()` в приложении.

**Conntrack (Connection Tracking)** — механизм ядра Linux (Netfilter), отслеживающий состояние всех соединений (TCP, UDP, ICMP) для реализации stateful firewall и NAT. Таблица имеет фиксированный размер (`nf_conntrack_max`).

**sk_buff (skb)** — основная структура данных ядра Linux для представления сетевого пакета в памяти. Каждый пакет, проходящий через стек, описывается цепочкой `sk_buff`. Нехватка памяти для `sk_buff` приводит к дропам на ранних этапах обработки.

**SoftIRQ / NET_RX** — программный контекст прерывания (Bottom Half), в котором выполняется основная часть сетевой обработки входящих пакетов. Для сетевого приема используется обработчик `NET_RX`. Высокая загрузка `ksoftirqd` в `top` (поле `si`) указывает на перегрузку сетевого стека.

**NAPI (New API)** — механизм ядра Linux для обработки входящих пакетов методом опроса (polling) вместо прерываний при высокой нагрузке. NAPI комбинирует обработку прерываний и активный опрос, чтобы минимизизировать нагрузку на CPU.

**RPS/RFS (Receive Packet/Flow Steering)** — программные механизмы распределения входящих пакетов по ядрам CPU. RPS распределяет пакеты после получения из драйвера NIC; RFS направляет пакет на то ядро, где выполняется приложение-получатель (CPU Cache Locality).

**RSS (Receive Side Scaling)** — аппаратный механизм NIC для распределения входящих пакетов по нескольким очередям (и ядрам CPU) на основе хеша 5-tuple (src/dst IP, ports, protocol).

**Offloading (TSO/GSO/GRO/LRO)** — механизмы разгрузки CPU путем обработки сетевых операций на NIC: segmentation (TSO/GSO) и aggregation (GRO/LRO) пакетов. При диагностике через `tcpdump` offloading может искажать вывод.

**eBPF (extended Berkeley Packet Filter)** — фреймворк для выполнения программ в ядре Linux без модификации исходного кода. Используется для трассировки пакетов (`pwru`), мониторинга функций (`retsnoop`), анализа сетевого стека (`bpftrace`).

## Основные концепции

### Методологии диагностики

Эффективная диагностика опирается на три стратегии и два методаологических подхода:

| Стратегия | Принцип | Когда применять |
| :--- | :--- | :--- |
| **Bottom-Up** | От физического уровня к приложению (L1→L2→L3→L4→L7) | Неизвестная проблема, системная диагностика |
| **Top-Down** | От приложения к физическому уровню (L7→L4→L3→L2→L1) | Известен симптом на уровне приложения |
| **Divide-and-Conquer** | Проверка середины пути (проверяем шлюз, проверяем midpoint) | Длинные маршруты, изоляция сегмента |

| Методология | Принцип | Инструменты |
| :--- | :--- | :--- |
| **USE (Utilization, Saturation, Errors)** | Для каждого ресурса: утилизация, насыщение, ошибки | `mpstat`, `ethtool -S`, `nstat`, `ip -s link` |
| **RED (Rate, Errors, Duration)** | Скорость потерь, количество ошибок, длительность проблем | `ping`, `mtr`, `nstat`, `conntrack -S` |

### Путь пакета через стек (Packet Journey)

Для эффективной диагностики важно понимать этапы прохождения пакета и точки, где могут возникать потери:

```
Прием пакета NIC
    │
    ▼
[1] NIC Ring Buffer (DMA) ── Потери: rx_missed_errors
    │
    ▼
[2] NAPI / SoftIRQ (ksoftirqd) ── Потери: softnet_stat[2], softnet_stat[3]
    │  netdev_max_backlog, netdev_budget
    ▼
[3] L3/IP: маршрутизация, фильтрация (Netfilter/nftables) ── Потери: sk_buff ENOMEM, ARP overflow
    │  rp_filter, neighbor table
    ▼
[4] L4/TCP-UDP: conntrack, socket buffers ── Потери: ListenDrops, UdpInErrors
    │  somaxconn, tcp_max_syn_backlog, rmem/wmem
    ▼
[5] Приложение: recv()/read() ── Потери: Zero Window, Recv-Q > 0
```

### Три фундаментальные метрики

1. **Пропускная способность (Bandwidth):** Максимальный объем данных, передаваемых по каналу в единицу времени. Инструменты: `iperf3`, `xfr`, `ethtool`.
2. **Задержка (Latency/RTT):** Время прохождения пакета до узла и обратно. Инструменты: `ping`, `mtr`, `tcprtt` (eBPF), `ss -ti`.
3. **Потери пакетов (Packet Loss):** Процент пакетов, не достигших цели. Инструменты: `ping`, `mtr`, `nstat`, `conntrack -S`, `ip -s link`.

### TCP State Machine (кратко)

| Состояние | Описание | Диагностическое значение |
| :--- | :--- | :--- |
| **LISTEN** | Ожидание входящих подключений | Recv-Q = ожидающие `accept()`, Send-Q = backlog |
| **SYN-SENT** | Отправлен SYN, ожидание SYN-ACK | Много записей → firewall drop или потеря пакетов |
| **SYN-RECV** | Получен SYN, отправлен SYN-ACK | Много записей → SYN-flood или недостаточный backlog |
| **ESTABLISHED** | Активная передача данных | Recv-Q = данные не прочитаны приложением |
| **FIN-WAIT-1/2** | Завершение инициатором | Долгое состояние → проблемы с Finish |
| **CLOSE-WAIT** | Удаленная сторона закрыла, локальная нет | Утечка сокетов в приложении |
| **LAST-ACK** | Ожидание финального ACK | Нормально при закрытии |
| **TIME-WAIT** | Ожидание истечения 2*MSL | Много записей → исчерпание ephemeral портов |
| **CLOSED** | Соединение полностью закрыто | Нормальное состояние |

### Ключевые параметры ядра

| Параметр | Влияние | Рекомендация |
| :--- | :--- | :--- |
| `net.core.somaxconn` | Лимит backlog для listen-сокетов | 65535 для высоконагруженных сервисов |
| `net.ipv4.tcp_max_syn_backlog` | Очередь полуоткрытых соединений | 4096–65535 |
| `net.ipv4.ip_local_port_range` | Диапазон ephemeral портов | 1024 65535 (минимум) |
| `net.ipv4.tcp_tw_reuse` | Повторное использование TIME-WAIT | 1 для клиентских нагрузок |
| `net.ipv4.tcp_syncookies` | Защита от SYN-flood | 1 в production |
| `net.core.netdev_max_backlog` | Очередь пакетов для SoftIRQ | 5000–30000 для 10G/100G |
| `net.core.netdev_budget` | Бюджет пакетов на SoftIRQ-цикл | 600–2000 для 10G/100G |
| `net.netfilter.nf_conntrack_max` | Лимит таблицы conntrack | 262144–1048576 для high-load |
| `net.ipv4.conf.all.rp_filter` | Reverse Path Filtering | 2 ( loose mode) при асимметричной маршрутизации |
| `net.core.rmem_max` / `wmem_max` | Максимальный размер буферов сокетов | 16777216 (16 МБ) для 10G+ |

### Категории инструментов

| Категория | Инструменты | Назначение |
| :--- | :--- | :--- |
| **Базовая связность** | `ping`, `arping`, `ip -s link` | Проверка доступности по IP/MAC, счетчики ошибок интерфейса. |
| **Трассировка пути** | `mtr`, `traceroute`, `tracepath`, `trippy` | Поиск узких мест, потерь и MTU на маршруте. |
| **Анализ сокетов** | `ss`, `lsof`, `nstat` | Активные соединения, слушающие порты, PID процессов, счетчики ядра. |
| **Производительность** | `iperf3`, `xfr`, `ethtool` | Тест скорости, аппаратная статистика, очереди и буферы. |
| **Сканирование** | `nmap` | Обнаружение хостов и открытых портов, fingerprinting. |
| **Анализ трафика** | `tcpdump`, `termshark` | Перехват и разбор «сырых» пакетов. |
| **Прикладной уровень** | `curl`, `dig`, `resolvectl`, `doggo` | Диагностика HTTP/HTTPS и DNS. |
| **Конфигурация** | `networkctl`, `nmcli`, `ip addr`, `ip route` | Проверка состояния systemd-networkd, NetworkManager и IP-адресации. |
| **eBPF (Observability)** | `pwru`, `retsnoop`, `bpftrace`, `dropwatch` | Глубокая трассировка пакетов и функций ядра. |
| **Firewall** | `nft`, `conntrack`, `iptables` | Анализ правил фильтрации, таблицы состояний и мониторинг событий. |
| **Мониторинг (TUI)** | `iftop`, `nload`, `bmon`, `iptraf-ng`, `tcptrack`, `slurm`, `bandwhich`, `snitch`, `gping` | Real-time визуализация трафика и задержек. |
| **Альтернативные клиенты** | `xh`, `trippy` | Современные замена `curl` и `mtr` на Rust. |

Подробнее о TUI/CLI инструментах: **[Сетевые инструменты CLI и TUI](../Diagnostics/Networking/network_cli_tools.md)**. Подробнее о `nc` (netcat): **[Netcat: универсальный сетевой инструмент](../Diagnostics/Networking/netcat.md)**.

---

## Практические сценарии

### Сценарий 1: Проверка доступности порта (L4)

**Задача:** Убедиться, что порт на удаленном хосте открыт и не блокируется.

**Основные методы:**

```bash
# 1. nc (netcat) — самый универсальный инструмент
nc -zv example.com 443
# → Connection to example.com 443 port [tcp/https] succeeded!

nc -zvu -w 2 8.8.8.8 53  # UDP с таймаутом 2с

# 2. Bash built-in /dev/tcp — работает без дополнительных утилит
echo > /dev/tcp/example.com/443 && echo "Port open" || echo "Port closed"
# Или с таймаутом:
timeout 2 bash -c 'echo > /dev/tcp/example.com/443' && echo "OK" || echo "FAIL"

# 3. curl — для HTTP/HTTPS портов
curl -s -o /dev/null -w "%{http_code}" http://example.com:8080/health
# → 200

# 4. nmap — для сканирования нескольких портов
nmap -p 80,443,8080 example.com

# 5. ss — проверка локальных портов
ss -tlnp | grep :80

# 6. hping3 — TCP/UDP пинг на любой порт (обход firewall)
sudo hping3 -S -p 443 -c 3 example.com

# 7. telnet — если доступен (устарел, но иногда есть)
telnet example.com 443
```

**Интерпретация результатов:**
- `succeeded` / код 2xx: Порт открыт и сервис отвечает.
- `Connection refused`: Порт закрыт ОС сервера (сервис не запущен).
- `Timed out`: Пакеты отбрасываются (DROP) файрволом или хост недоступен.
- `No route to host`: Проблема маршрутизации.
- `Network is unreachable`: Нет маршрута до подсети.

**Валидация:**
```bash
# Пример: порт открыт
nc -zv example.com 443
# → Connection to example.com 443 port [tcp/https] succeeded!

# Пример: порт закрыт
nc -zv example.com 9999
# → nc: connect to example.com port 9999 (tcp) failed: Connection refused
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Connection refused` | Сервис не запущен или не слушает на указанном интерфейсе | `ss -tlnp \| grep :<port>`, проверить логи приложения |
| `Timed out` | Файрвол DROP, хост недоступен, маршрут отсутствует | `ip route get <host>`, `nft list ruleset`, `iptables -L -n -v` |
| `No route to host` | Отсутствует маршрут или интерфейс поднят | `ip route show`, `ip -br link` |
| `Network is unreachable` | Сеть назначения не reachable | Проверить таблицу маршрутизации, default gateway |
| `Operation now in progress` (nc -v) | Только UDP: пакет отправлен, но нет ответа | Увеличить таймаут `-w`, проверить `conntrack` |

**Best Practices:**
- Используйте `-n` утилитам для отключения DNS-резолва (скорость и стабильность).
- Для UDP всегда указывайте таймаут (`-w 2`), иначе `nc` будет висеть вечно.
- Для массовой проверки портов используйте `nmap` с `-sT` (TCP connect) или `-sS` (SYN scan, требует root).
- `hping3` полезен, когда `nc` не работает из-за firewall (имитирует SYN без установления соединения).

**Edge Cases:**
- **Localhost:** Порт может быть открыт на `127.0.0.1` но закрыт на `0.0.0.0` или внешнем IP. Всегда проверяйте адрес привязки: `ss -tlnp | grep :<port>`.
- **IPv6-only сервисы:** `nc -zv example.com 443` может подключаться по IPv6, если AAAA запись существует. Используйте `-4` для принудительного IPv4.
- **SELinux/AppArmor:** Сервис может слушать порт, но файрвол может блокировать. Проверяйте `audit.log` (`ausearch -m avc -ts recent`).
- **TIME-WAIT exhaustion:** При массовых проверках клиент может исчерпать ephemeral порты. Используйте `ss -tn state time-wait | wc -l`.

**Cleanup:**
```bash
# Нет изменений в системе для отката
```

---

### Сценарий 2: Тестирование пропускной способности (L3-L4)

**Задача:** Измерить реальную скорость между двумя узлами.

```bash
# На сервере (приёмник)
iperf3 -s

# На клиенте (отправитель), 10 потоков, 20 секунд
iperf3 -c <server_ip> -P 10 -t 20
# → [SUM]   0.00-20.00  sec  22.4 GBytes  9.62 Gbits/sec  sender

# Для современного инструмента с TUI и QUIC поддержкой рекомендуется xfr
xfr server --bind 0.0.0.0:5201

# На клиенте
xfr client <server_ip>
# → Встроенный TUI с живыми графиками throughput, RTT, retrans
```

Для глубокой диагностики тюнинга TCP и параметров влияющих на throughput используйте **[Оптимизация TCP](./Concepts/tcp_tuning/tcp_tuning_overview.md)**. Подробнее о `iperf3` и `xfr`: **[iperf3](../Diagnostics/Networking/iperf3.md)**, **[xfr](../Diagnostics/Networking/xfr.md)**.

**Валидация:**
```bash
# Пример: 10Gbps link, ожидаем ~9.2 Gbps (с учетом overhead)
iperf3 -c 10.0.0.1 -P 4 -t 10
# → [SUM]   0.00-10.00  sec  11.2 GBytes  9.62 Gbits/sec  sender
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Throughput < 1 Gbps на 10G link | Один поток, высокий RTT | Увеличить `-P` (parallel streams), проверить BDP |
| Высокий Retransmits | Потери пакетов на L2/L3 | `ethtool -S`, `ip -s link`, `mtr` |
| Низкий throughput на UDP | `udp_mem` исчерпан, `nf_conntrack` переполнен | Увеличить `udp_mem`, проверить `conntrack -S` |
| Разница sender/receiver | Потери пакетов или dropped на приемнике | Проверить `ip -s link` на приемнике |
| xfr не подключается | Firewall блокирует 5201/UDP | Разрешить порт, проверить `nft list ruleset` |

**Best Practices:**
- Для тестирования используйте **как минимум 2 потока** (`-P 2`) на каналах 1Gbps+; для 10G+ — 4–10 потоков.
- Тест должен длиться минимум 10–20 секунд (`-t 20`) для стабилизации показаний.
- Всегда тестируйте в обе стороны (`-R` в iperf3 или bidirectional mode в xfr).
- Для оценки BDP: `BDP = Bandwidth (bps) * RTT (s)`. Размер буферов должен быть ≥ BDP.
- Отключайте offloading на время теста, если измеряете реальный goodput: `ethtool -K eth0 tso off gso off gro off`.

**Edge Cases:**
- **NAT/Firewall:** Если между клиентом и сервером есть NAT, убедитесь, что порт 5201 (iperf3) или 5201/UDP (xfr) проброшен.
- **TCP pacing:** `iperf3` может использовать TCP pacing, который ограничивает скорость. Проверяйте `ss -ti` на наличие `pacing_rate`.
- **Container networking:** В Docker/Kubernetes используйте `--network host` или правильные CNI драйверы, иначе throughput будет ограничен overlay network (VXLAN overhead).
- **Air-gapped environments:** `xfr` требует Rust toolchain для сборки. Для изолированных сред используйте `iperf3` (широко доступен в репозиториях).

**Cleanup:**
```bash
# Нет изменений в системе для отката
# Если отключали offloading:
sudo ethtool -K eth0 tso on gso on gro on rx-vlan-offload on tx-vlan-offload on
```

---

### Сценарий 3: Аппаратная диагностика и глобальные счётчики

**Задача:** Проверить счётчики ядра и сетевой карты при замедлении сети или необъяснимых потерях.

```bash
# Ошибки и дропы на программном уровне интерфейса
ip -s link show eth0
# → RX: bytes  packets  errors  dropped overrun mcast
# → 1234567    8901     12      45      0       0

# Ошибки и дропы на уровне драйвера/железа (NIC)
sudo ethtool -S eth0 | grep -E "error|drop|miss"
# → rx_dropped: 124 (сигнал о переполнении буферов)
# → rx_missed_errors: 45 (Ring Buffer переполнен)

# Проверка размера кольцевых буферов (Ring Buffers)
ethtool -g eth0
# → RX: 4096
# → TX: 4096

# Проверка многопоточности (RSS/Очереди)
ethtool -l eth0
# → Combined: 4

# Глобальная статистика TCP/IP (современная замена netstat -s)
nstat -az | grep -E "TcpExtListenDrops|TcpRetransSegs|TcpExtUDPInErrors"
# → TcpExtListenDrops 45 (очередь accept переполнена)
# → TcpRetransSegs 1203 (ретраны в сети)
# → TcpExtUDPInErrors 0

# Проверка SoftIRQ статистики
cat /proc/net/softnet_stat
# → 00000000 00000000 00000000  (столбцы: total, dropped, squeezed)
```

**Валидация:**
```bash
# Пример: чистая среда
ip -s link show eth0 | grep -A2 "RX:"
# → RX: bytes  packets  errors  dropped overrun mcast
# → 1234567    8901     0       0       0       0

ethtool -S eth0 | grep -E "rx_missed_errors|rx_dropped"
# → rx_missed_errors: 0
# → rx_dropped: 0

nstat -az | grep -E "ListenDrops|UdpInErrors"
# → (пусто или все 0)
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `rx_dropped` растет в `ip -s link` | Переполнение `netdev_max_backlog` или driver queue | Увеличить `net.core.netdev_max_backlog`, проверить `ethtool -g` |
| `rx_missed_errors` растет в `ethtool -S` | Ring Buffer NIC переполнен | Увеличить `ethtool -G eth0 rx 4096` (или 8192 для 100G) |
| `errors` растет в `ip -s link` | Ошибки на физическом уровне (кабель, SFP, duplex) | Проверить `ethtool eth0`, заменить кабель/SFP, проверить duplex |
| `overrun` растет | FIFO буфер NIC переполнен | Увеличить Ring Buffer, проверить `ethtool -l` (очереди) |
| `mcast` растет | Много multicast/broadcast трафика | Обычно нормально; проверить `tcpdump -i eth0 ether proto 0x01000e` |

**Best Practices:**
- Для 10G+ сетей: RX Ring Buffer ≥ 4096, для 100G — ≥ 8192–16384.
- Количество RSS очередед (`ethtool -l`) должно соответствовать количеству ядер CPU, обрабатывающих сетевой трафик.
- Сохраняйте настройки Ring Buffers в `.link` файл systemd-networkd для persistence.
- Мониторьте `softnet_stat` параллельно с `ethtool -S` — рост `rx_dropped` может быть программным, а не аппаратным.

**Edge Cases:**
- **Virtual interfaces (veth, tun, tap):** Счетчики `rx_dropped` могут расти из-за ограничений `tx_queue_len` или `tc` qdisc. Проверяйте `tc -s qdisc show <iface>`.
- **Bond interfaces:** Захват на `bond0` показывает только управляющий трафик (LACP). Данные видны на slave-интерфейсах (`eth0`, `eth1`).
- **Offloading effects:** Включенный GRO/LRO может вызывать рост `rx_dropped` при нестандартных размерах пакетов. Для диагностики отключайте offloading временно.

**Cleanup:**
```bash
# Если изменяли Ring Buffer:
sudo ethtool -G eth0 rx 256 tx 256

# Если изменяли offloading:
sudo ethtool -K eth0 tso on gso on gro on rx-vlan-offload on tx-vlan-offload on
```

---

### Сценарий 4: Глубокая трассировка с eBPF

**Задача:** Если пакет входит в сервер (виден в `tcpdump`), но приложение его не получает, используйте инструменты на базе eBPF, чтобы найти место дропа или ошибки внутри ядра.

```bash
# Отслеживание пути пакета до порта 80 (pwru)
sudo pwru --filter-dst-port 80
# → [timestamp] netif_receive_skb -> ip_rcv -> nft_do_chain -> [DROP]

# Отслеживание возвращаемых значений функций стека (retsnoop)
# Помогает понять, КАКАЯ функция вернула ошибку (например, -ENOMEM)
sudo retsnoop -e '*ip_rcv*'

# bpftrace для отслеживания конкретных событий
sudo bpftrace -e '
kprobe:napi_poll {
    @drops[comm] = count();
}
'

# dropwatch — классика для отслеживания дропов
sudo dropwatch -l kas
```

**Валидация:**
```bash
# pwru показывает стек вызовов с указанием функции дропа
# → [timestamp] netif_receive_skb -> ip_rcv -> nf_hook_slow -> [DROP] nf_reject
# → [timestamp] tcp_v4_rcv -> tcp_v4_do_rcv -> [DROP] tcp_validate_incoming
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Пакет виден в `tcpdump`, но нет в `ss` | Дроп в `nftables`/`iptables` или `conntrack` | `nft monitor trace`, `conntrack -E` |
| Пакет доходит до `tcp_v4_rcv`, но нет в приложении | Переполнение backlog или socket buffer | Увеличить `somaxconn`, `rmem_max` |
| `-ENOMEM` в `retsnoop` | Нехватка памяти для `sk_buff` | Проверить `dmesg`, `cat /proc/pressure/memory` |
| `nf_conntrack: table full` в `dmesg` | Переполнение conntrack | Увеличить `nf_conntrack_max`, сократить таймауты |
| Высокий `%si` в `top` | SoftIRQ перегрузка | Настроить RSS/RPS, увеличить `netdev_budget` |

**Best Practices:**
- Используйте `pwru` для быстрого поиска места дропа в production.
- `retsnoop` полезен, когда нужно увидеть код возврата функции (не только факт вызова).
- Для постоянного мониторинга рассмотрите `bpftrace` скрипты с записью в Prometheus.
- Всегда используйте BPF-фильтры (`--filter-dst-port`, `--filter-dst-ip`) для ограничения захвата.

**Edge Cases:**
- **Kernel version:** `pwru` требует ядро 5.2+ с поддержкой BTF (CONFIG_DEBUG_INFO_BTF). Проверяйте `uname -r` и `/sys/kernel/btf/vmlinux`.
- **Performance impact:** eBPF-программы добавляют минимальный overhead, но на 100G+ могут влиять на производительность. Используйте с фильтрами.
- **Container namespaces:** Для трассировки внутри контейнера используйте `nsenter -t <PID> -n` или запускайте инструмент на хосте с фильтром по PID/сокету.

**Cleanup:**
```bash
# Нет изменений в системе для отката
# Остановить фоновые bpftrace/pwru: Ctrl+C или pkill
```

---

### Сценарий 5: Диагностика DNS

**Задача:** Проверить работу DNS-резолвинга и состояние DNS-серверов.

```bash
# Проверка текущих DNS-серверов и их статуса
resolvectl status
# → Link 2 (eth0):
# →       DNS Servers: 192.168.1.1
# →                    8.8.8.8

# Прямой запрос через системный резолвер
resolvectl query google.com
# → google.com: 142.250.186.206 -- link: eth0

# Классические альтернативы
dig google.com +short
# → 142.250.186.206

dig google.com MX
# → google.com.    300    IN    MX    10 aspmx.l.google.com.

# Проверка конкретного DNS-сервера
dig @8.8.8.8 google.com +short
# → 142.250.186.206

# Проверка обратной зоны (PTR)
dig -x 8.8.8.8 +short
# → dns.google.

# Трассировка DNS-запроса (где теряется пакет)
mtr -n --no-dns -T -P 53 8.8.8.8

# nslookup (legacy, но иногда единственный вариант)
nslookup google.com 8.8.8.8

# host (простой альтернативой dig)
host google.com 8.8.8.8
```

**Валидация:**
```bash
# Пример: резолвинг работает
resolvectl query google.com
# → google.com: 142.250.186.206 -- link: eth0
# →         -- 280ms

dig google.com +short
# → 142.250.186.206
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `NXDOMAIN` или пустой ответ | Домен не существует, кэш poisoned | `dig +trace google.com`, проверить `/etc/hosts` |
| `SERVFAIL` | Проблема на authoritative DNS-сервере | `dig @<ns-server> google.com`, проверить логи BIND/Unbound |
| `TIMEOUT` | DNS-сервер недоступен, firewall блокирует UDP:53/TCP:53 | `resolvectl status`, `iptables -L -n -v` |
| Разные ответы от разных серверов | DNS-балансировщик, GeoDNS, кэширование | Использовать `dig @<specific-server>`, проверить TTL |
| `dnsmasq`/`systemd-resolved` кэш устарел | Кэширование отрицательных ответов (negative cache) | `resolvectl flush-caches`, `systemd-resolve --flush-caches` |
| Медленный резолвинг | Медленный upstream DNS, IPv6 preference | `dig +trace`, проверить `nsswitch.conf` (`hosts: files dns`) |

**Best Practices:**
- Используйте `dig +trace` для диагностики, где именно ломается резолвинг (root → TLD → authoritative).
- Всегда указывайте DNS-сервер (`dig @8.8.8.8`) при диагностике, чтобы исключить проблемы с локальным резолвером.
- Для production используйте несколько независимых DNS-серверов (не только корпоративный).
- Проверяйте как UDP, так и TCP (DNS-over-TCP) — некоторые серверы блокируют TCP.

**Edge Cases:**
- **DNS over HTTPS/TLS:** `dig` не работает с DoH/DoT напрямую. Для диагностики DoH используйте `curl -H 'accept: application/dns-json' 'https://dns.google/resolve?name=google.com&type=A'`.
- **systemd-resolved stub:** На системах с `systemd-resolved` `/etc/resolv.conf` может указывать на `127.0.0.53`. Проверяйте `resolvectl status`, а не `cat /etc/resolv.conf`.
- **DNSSEC:** При `dig` добавляйте `+dnssec` для проверки подписи. `SERVFAIL` может означать DNSSEC validation failure.
- **PTR и /etc/hosts:** Обратный резолвинг может тормозить из-за отсутствия PTR записи или медленного DNS. Используйте `dig -x` с таймаутом.

**Cleanup:**
```bash
# Нет изменений в системе для отката
# Если сбрасывали кэш:
# resolvectl flush-caches (не требует отката)
```

---

### Сценарий 6: Мониторинг файрвола (nftables)

**Задача:** Проверить, не блокирует ли файрвол легитимный трафик, и отслеживать срабатывания правил.

```bash
# Просмотр всего набора правил со счётчиками срабатываний
sudo nft list ruleset

# Мониторинг процесса обработки пакета в реальном времени (Trace)
# Позволяет увидеть, на каком именно правиле пакет был отброшен
sudo nft monitor trace

# Мониторинг событий conntrack (новые соединения, удаления)
sudo conntrack -E

# Проверка переполнения таблицы соединений
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max

# Статистика conntrack по состояниям
sudo conntrack -S
# → cpu=0   found=12345 insert=12344 drop=0 early_drop=0 error=0

# Просмотр активных соединений
sudo conntrack -L -p tcp --dport 80 | wc -l

# iptables (legacy) — просмотр правил с порядковыми номерами
sudo iptables -L -n -v --line-numbers | grep -v "0     0"
```

**Валидация:**
```bash
# Пример: правило DROP сработало 1523 раза
sudo nft list ruleset | grep drop
# → drop count 1523

# Пример: conntrack в норме
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max
# → net.netfilter.nf_conntrack_count = 45000
# → net.netfilter.nf_conntrack_max = 262144
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `nf_conntrack: table full` в `dmesg` | `nf_conntrack_max` исчерпан | Увеличить `net.netfilter.nf_conntrack_max`, сократить таймауты |
| Пакет не проходит, но правила выглядят правильными | Более общее правило выше по порядку (First-match) | Переместить разрешающее правило выше с `nft insert rule ...` |
| `conntrack -E` показывает много `DESTROY` | Высокая частота закрытия соединений | Нормально при high-load; проверять `early_drop` |
| `insert_failed > 0` в `conntrack -S` | Нехватка памяти или `nf_conntrack_max` исчерпан | Увеличить `nf_conntrack_max`, проверить `dmesg` |
| ICMP блокируется, но `ping` работает | ICMP Type 0 (Echo Reply) разрешен, а Type 11 (Time Exceeded) нет | Проверить полный список разрешенных ICMP типов |

**Best Practices:**
- Всегда используйте `--line-numbers` при просмотре правил iptables.
- Для nftables включите `meta nftrace set 1` для отладки.
- После изменений проверяйте счетчики — они должны расти для разрешающих правил и оставаться нулевыми для блокирующих (если трафик легитимный).
- Используйте `conntrack -E` для отслеживания состояния соединений в реальном времени.

**Edge Cases:**
- **VRF и conntrack:** По умолчанию conntrack не разделяет соединения по VRF — при overlapping IP в разных VRF возможны коллизии. Фильтрация: `meta l3mdev` в nftables.
- **UDP race condition:** При параллельных UDP-запросах с одного сокета возможны задержки ровно 1000 мс или 5000 мс (таймауты ретрансмиссии). Решение: `single-request-reopen`.
- **NOTRACK в raw table:** Если используется `-j NOTRACK`, conntrack не видит эти соединения, и `conntrack -E` будет пустым для них.
- **nf_defrag_ipv4:** Может вызывать задержки при фрагментированных пакетах. Отключайте осторожно: `sysctl -w net.netfilter.nf_defrag_ipv4_handlers=0`.

**Cleanup:**
```bash
# Нет изменений в конфигурации firewall для отката
# Если временно отключали conntrack:
sudo sysctl -w net.netfilter.nf_conntrack_max=262144
```

---

### Сценарий 7: Проверка конфигурации (systemd-networkd / NM)

**Задача:** Убедиться, что сетевые демоны видят интерфейс в корректном состоянии и примененные настройки соответствуют ожиданиям.

```bash
# Для systemd-networkd: проверка статуса и примененных настроек
networkctl status eth0
# → 2: eth0
# →       Linkified: yes
# →       DHCP: yes
# →       State: routable
# →       Address: 192.168.1.100/24
# →       Gateway: 192.168.1.1

# Для NetworkManager: детальная информация об устройстве
nmcli device show eth0
# → GENERAL.DEVICE:                         eth0
# → GENERAL.TYPE:                           ether
# → GENERAL.CONNECTION:                     Wired connection 1
# → IP4.ADDRESS[1]:                         192.168.1.100/24
# → IP4.GATEWAY:                            192.168.1.1

# Проверка всех интерфейсов (краткий формат)
networkctl list
# → IDX LINK   TYPE     OPERATIONAL SETUP
# →   1 lo     loopback carrier     unmanaged
# →   2 eth0   ether    routable    configured

# Проверка routing таблицы (systemd-networkd)
networkctl status eth0 | grep -A5 "Routing"
```

**Валидация:**
```bash
# Пример: интерфейс в состоянии routable
networkctl status eth0
# → State: routable
# → Address: 192.168.1.100/24
# → Gateway: 192.168.1.1
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `State: degraded` или `carrier` | Нет линка (кабель отключен, SFP нерабочий) | Проверить `ethtool eth0`, заменить кабель/SFP |
| `State: routable` но нет ping | Нет default gateway или маршрут | `ip route show`, `networkctl status` |
| `Address: n/a` | DHCP не выдал адрес, или статический IP не применен | Проверить DHCP-сервер, логи `journalctl -u systemd-networkd` |
| NM `unavailable` | NM не управляет интерфейсом (ignored в config) | `nmcli device set eth0 managed yes` |
| Два демона конфликтуют | systemd-networkd и NM одновременно управляют интерфейсом | Отключить один из демонов, использовать `networkctl` или `nmcli` |

**Best Practices:**
- Используйте `networkctl` на системах с `systemd-networkd`; `nmcli` на системах с NetworkManager.
- Не запускайте оба демона одновременно на одном интерфейсе.
- Проверяйте логи: `journalctl -u systemd-networkd -u NetworkManager -f`.

**Edge Cases:**
- **Docker/macvlan:** Контейнерные интерфейсы могут отображаться как `unmanaged` в NM. Это нормально.
- **VPN (WireGuard/OpenVPN):** Виртуальные интерфейсы создаются демоном VPN, не network-manager.
- **Hotplug:** При замене кабеля интерфейс может не подняться автоматически. Проверяйте `networkctl list` после физического изменения.

**Cleanup:**
```bash
# Нет изменений в конфигурации для отката
```

---

### Сценарий 8: Углубленный анализ tcpdump (L2–L7)

**Задача:** Захватить и проанализировать трафик для диагностики проблем на уровнях L2–L7.

```bash
# Базовый захват без DNS-резолва
sudo tcpdump -i eth0 -nn -c 100

# Захват с сохранением в файл для Wireshark
sudo tcpdump -i eth0 -w /tmp/capture.pcap -C 100 -W 5

# Чтение файла с фильтром
tcpdump -r /tmp/capture.pcap -nn 'tcp port 443'

# Продвинутая фильтрация BPF
sudo tcpdump -i eth0 -nn 'tcp port 443 and not host 10.0.0.5'
sudo tcpdump -i eth0 -nn 'icmp[0] == 3 and icmp[1] == 4'  # ICMP PTB
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0'  # только SYN

# Анализ TCP handshake
sudo tcpdump -i eth0 -nn -s 0 'tcp port 443' | grep -E "\[S\]|\[S\.\]|\[\.\]"

# DNS-захват
sudo tcpdump -i eth0 -nn -s 0 port 53

# DHCP-захват
sudo tcpdump -i eth0 -nn -s 0 udp port 67 or port 68 -vv

# Удаленный захват через SSH
ssh user@remote "sudo tcpdump -s 0 -U -n -w - -i eth0 not port 22" | wireshark -k -i -
```

**Валидация:**
```bash
# Пример: успешный TCP handshake
sudo tcpdump -i eth0 -nn -c 3 'tcp port 443'
# → 12:00:01.000000 IP 192.168.1.10.54321 > 142.250.186.206.443: Flags [S], seq 12345
# → 12:00:01.050000 IP 142.250.186.206.443 > 192.168.1.10.54321: Flags [S.], seq 9876, ack 12346
# → 12:00:01.050100 IP 192.168.1.10.54321 > 142.250.186.206.443: Flags [.], ack 9877
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `bad cksum` в выводе | NIC offload (TSO/GRO/checksum) | `ethtool -K eth0 tso off gso off gro off` |
| Нет VLAN-тегов | `rx-vlan-offload` включен | Отключить offload временно или использовать `-e` |
| `tcpdump: packet buffer overflow` | Переполнение кольцевого буфера libpcap | Увеличить `-B 8192`, писать в tmpfs (`/dev/shm`) |
| Захват тормозит, CPU низкий | Медленная запись на диск | Запись в `/dev/shm` или по SSH в память удаленного хоста |
| Видны только `* * *` в traceroute | ICMP заблокирован на промежуточных хостах | Использовать TCP-зондирование (`traceroute -T -p 443`) |
| Дублирующие MAC | Порт коммутатора в Access вместо Trunk | Перевести порт в trunk, проверить VLAN |

**Best Practices:**
- Всегда используйте `-n` в скриптах (отключает DNS-резолв).
- Сужайте BPF-фильтр как можно раньше для снижения overhead.
- Используйте `-s 0` для глубокого анализа; для быстрого поиска портов достаточно `-s 96`.
- Записывайте в `tmpfs` (`/dev/shm`) при высокой нагрузке.
- Используйте `-U` при записи в pipe (например, в Wireshark по SSH).
- Для L2-диагностики НЕ используйте `-i any` (теряются MAC-адреса и VLAN-теги).
- Комбинируйте с `tshark` для post-processing (display filters, reassembly).

**Edge Cases:**
- **Jumbo Frames (MTU > 1500):** При захвате увеличьте snaplen (`-s 0`) или получите усеченные пакеты.
- **Высокоскоростные сети (10G/40G/100G):** `tcpdump` может не справлять с >500K pps. Рассмотрите `dumpcap` (часть Wireshark) или eBPF-инструменты (`pwru`).
- **VXLAN decapsulation offload:** Некоторые NIC скрывают инкапсуляцию от `tcpdump`. Отключайте через `ethtool`.
- **Контейнеры:** Используйте `nsenter -t <PID> -n` или `docker exec` для захвата внутри namespace.

**Cleanup:**
```bash
# Удалить временные pcap-файлы
rm -f /tmp/*.pcap /tmp/*.pcap.gz

# Остановить фоновый захват
pkill -f "tcpdump"

# Вернуть offloading (если отключали)
sudo ethtool -K eth0 tso on gso on gro on rx-vlan-offload on tx-vlan-offload on
```

---

### Сценарий 9: Диагностика сокетов и TCP-метрик (ss, nstat)

**Задача:** Быстро оценить состояние сокетного стека, выявить утечки, переполнения backlog и проблемы с буферами.

```bash
# Сводная статистика по протоколам
ss -s
# → Total: 156 (kernel 180)
# → TCP:   24 (estab 1, closed 1, orphaned 0, timewait 0)
# → UDP:   12

# Все слушающие порты с PID
sudo ss -tulpn
# → tcp    LISTEN  0       128     0.0.0.0:22          0.0.0.0:*          users:(("sshd",pid=1234))

# Детальная TCP-статистика для соединения
ss -tin dst 1.1.1.1
# → cubic wscale:7,7 rto:204 rtt:15.2/0.5 ato:40 mss:1448
# → cwnd:10 bytes_acked:15002048 retrans:0/125 delivery_rate 120Mbps

# Потребление памяти сокетами
ss -tm
# → skmem:(r0,rb212992,t0,tb212992,f0,w0,o0,bl0,d0)

# Таймеры сокетов (keepalive, retransmit)
sudo ss -to dst 1.1.1.1

# Принудительное закрытие зависших соединений
sudo ss -K dst 1.2.3.4

# Глобальные счетчики ядра (замена netstat -s)
nstat -az | grep -E "ListenDrops|TCPRetransSegs|UdpInErrors"
# → TcpExtListenDrops 45
# → TcpRetransSegs 1203
# → TcpExtUDPInErrors 0

# Внутри network namespace
sudo ip netns exec production ss -tulpn
```

**Валидация:**
```bash
# Пример: нормальное состояние
ss -s
# → Total: 156 (kernel 180)
# → TCP:   24 (estab 1, closed 1, orphaned 0, timewait 0)

ss -ltnp | grep :443
# → tcp    LISTEN  0       511     0.0.0.0:443  0.0.0.0:*    users:(("nginx",pid=5678))
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Connection Refused` | Приложение не слушает или backlog переполнен | `ss -ltnp \| grep :<port>`, `nstat -az \| grep ListenDrops` |
| `TIME-WAIT > 10000` | Много коротких соединений, исчерпание ephemeral портов | Включить `tcp_tw_reuse=1`, connection pooling |
| `CLOSE-WAIT растет` | Утечка сокетов в приложении | Исправить код приложения, перезапустить процесс |
| `Zero Window` в `ss -tin` | Приложение медленно читает | Увеличить `rmem`, оптимизировать приложение |
| `SYN-RECV > 500` | SYN-flood или firewall drop | Включить `tcp_syncookies=1`, увеличить backlog |
| `orphaned > 100` | Приложение закрывает сокеты без shutdown() | Исправить приложение, увеличить `tcp_max_orphans` |

**Best Practices:**
- Используйте `ss -n` для скорости (отключает DNS-резолв).
- `ss -p` требует `sudo` или `CAP_NET_ADMIN` / `CAP_SYS_PTRACE`.
- В контейнерах без `NET_ADMIN` `ss` работает, но не показывает процессы.
- Для постоянного мониторинга добавьте скрипт в `cron` или `systemd-timer`.

**Edge Cases:**
- **SO_REUSEPORT:** Создает отдельные listen-сокеты на каждый поток — будете видеть несколько строк для одного порта.
- **Namespace isolation:** Каждый контейнер имеет свой network namespace. Используйте `ip netns exec <ns> ss ...`.
- **High-connection count:** При тысячах соединений `ss -a` генерирует мегабайты вывода. Используйте фильтрацию.

**Cleanup:**
```bash
# Нет изменений в системе для отката
# Если закрывали сокеты принудительно:
# Соединения будут закрыты — при необходимости перезапустите приложение
```

---

### Сценарий 10: Аппаратная диагностика NIC (ethtool)

**Задача:** Проверить состояние сетевой карты, параметры линка и offloading.

```bash
# Статус линка (скорость, duplex, auto-negotiation)
sudo ethtool eth0
# → Speed: 1000Mb/s
# → Duplex: Full
# → Auto-negotiation: on
# → Link detected: yes

# Статистика драйвера (ошибки, дропы, miss)
sudo ethtool -S eth0 | grep -E "error|drop|miss|fifo"
# → rx_missed_errors: 0
# → rx_fifo_errors: 0
# → tx_fifo_errors: 0

# Проверка offloading (TSO, GRO, checksum)
sudo ethtool -k eth0
# → tcp-segmentation-offload: on
# → generic-receive-offload: on
# → tx-checksumming: on

# Проверка количества очередей (RSS)
sudo ethtool -l eth0
# → Combined: 4

# Включение/отключение offloading для диагностики
sudo ethtool -K eth0 tso off gso off gro off rx-vlan-offload off tx-vlan-offload off
# → [вернуть после диагностики]
sudo ethtool -K eth0 tso on gso on gro on rx-vlan-offload on tx-vlan-offload on

# Коалесценция прерываний
sudo ethtool -c eth0
# → rx-usecs: 100
# → rx-frames: 0
```

**Валидация:**
```bash
# Пример: 10G link, full duplex
sudo ethtool eth0 | grep -E "Speed|Duplex|Link detected"
# → Speed: 10000Mb/s
# → Duplex: Full
# → Link detected: yes
```

**Типичные ошибки и решения:**

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Link detected: no` | Кабель отключен, SFP нерабочий, порт выключен | Проверить кабель, SFP, `ethtool eth0` autoneg |
| `Speed: 10Mb/s` на gigabit link | Duplex mismatch или autoneg отключен | Включить autoneg: `ethtool -s eth0 speed 1000 duplex full autoneg on` |
| `rx_fifo_errors` растет | Переполнение внутреннего FIFO-буфера NIC | Увеличить Ring Buffer (`ethtool -G eth0 rx 4096`) |
| `rx_crc_errors` растет | Плохой кабель, SFP или interference | Заменить кабель/SFP, проверить на соседнем порту |
| `tx_carrier_errors` растет | Проблемы с линком ( duplex mismatch ) | Проверить duplex на обеих сторонах |

**Best Practices:**
- Для 10G+ сетей: RX Ring Buffer ≥ 4096, для 100G — ≥ 8192–16384.
- Количество RSS очередед должно соответствовать количеству ядер CPU.
- При диагностике MTU/фрагментации/checksum временно отключайте offloading.
- Сохраняйте настройки в `.link` файлы systemd-networkd для persistence.

**Edge Cases:**
- **Virtual interfaces (veth, tap):** `ethtool` работает, но `Speed` часто показывает `Unknown`. Это нормально.
- **Bond interfaces:** Настраивайте offloading на slave-интерфейсах, не на bond-master.
- **SR-IOV / VF:** Для Virtual Functions используйте `ethtool` на хостовом интерфейсе (`pf`) или внутри VM (`ethtool eth0` на VF).

**Cleanup:**
```bash
# Вернуть стандартные настройки offloading
sudo ethtool -K eth0 tso on gso on gro on rx-vlan-offload on tx-vlan-offload on

# Вернуть стандартный размер Ring Buffer (если изменяли)
sudo ethtool -G eth0 rx 256 tx 256
```

---

### Сценарий 11: Сводный SRE health-check скрипт

**Задача:** Быстрая автоматизированная проверка здоровья сетевого стека для использования в мониторинге.

```bash
#!/bin/bash
# network_health.sh — быстрая проверка здоровья сетевого стека
# Использование: ./network_health.sh [interface]

IFACE="${1:-eth0}"
EXIT_CODE=0

check() {
    local name="$1"
    local result="$2"
    local expected="$3"
    if [ "$result" != "$expected" ]; then
        echo "FAIL: $name = $result (ожидалось: $expected)"
        EXIT_CODE=1
    else
        echo "OK: $name = $result"
    fi
}

echo "=== Network Stack Health Check: $IFACE ==="

# 1. Проверка ошибок интерфейса
RX_DROPPED=$(ip -s link show "$IFACE" | awk '/RX:/ {print $5}')
check "ip.rx_dropped" "$RX_DROPPED" "0"

# 2. Проверка softnet
SOFTNET_DROPPED=$(awk '{print $2}' /proc/net/softnet_stat | paste -sd+ | bc)
check "softnet.dropped" "$SOFTNET_DROPPED" "0"

SOFTNET_SQUEEZED=$(awk '{print $3}' /proc/net/softnet_stat | paste -sd+ | bc)
check "softnet.squeezed" "$SOFTNET_SQUEEZED" "0"

# 3. Проверка Ring Buffer
RX_MISSED=$(ethtool -S "$IFACE" 2>/dev/null | grep rx_missed_errors | awk '{print $2}')
check "nic.rx_missed_errors" "$RX_MISSED" "0"

# 4. Проверка conntrack
CONNTRACK_COUNT=$(sysctl -n net.netfilter.nf_conntrack_count 2>/dev/null || echo "0")
CONNTRACK_MAX=$(sysctl -n net.netfilter.nf_conntrack_max 2>/dev/null || echo "1")
if [ "$CONNTRACK_COUNT" -gt "$((CONNTRACK_MAX * 90 / 100))" ]; then
    echo "WARN: conntrack usage = ${CONNTRACK_COUNT}/${CONNTRACK_MAX}"
    EXIT_CODE=1
else
    echo "OK: conntrack = ${CONNTRACK_COUNT}/${CONNTRACK_MAX}"
fi

# 5. Проверка UDP ошибок
UDP_ERRORS=$(nstat -az | grep UdpInErrors | awk '{print $2}')
check "udp.in_errors" "$UDP_ERRORS" "0"

# 6. Проверка ListenOverflows
LISTEN_OVERFLOWS=$(nstat -az | grep ListenOverflows | awk '{print $2}')
check "tcp.listen_overflows" "$LISTEN_OVERFLOWS" "0"

# 7. Проверка TCP retrans
TCP_RETRANS=$(nstat -az | grep TcpRetransSegs | awk '{print $2}')
check "tcp.retrans_segs" "$TCP_RETRANS" "0"

# 8. Проверка TIME-WAIT
TIMEWAIT=$(ss -tn state time-wait | wc -l)
if [ "$TIMEWAIT" -gt 10000 ]; then
    echo "WARN: time-wait = $TIMEWAIT (>10000)"
    EXIT_CODE=1
else
    echo "OK: time-wait = $TIMEWAIT"
fi

# 9. Проверка CLOSE-WAIT
CLOSEWAIT=$(ss -tn state close-wait | wc -l)
if [ "$CLOSEWAIT" -gt 100 ]; then
    echo "WARN: close-wait = $CLOSEWAIT (>100)"
    EXIT_CODE=1
else
    echo "OK: close-wait = $CLOSEWAIT"
fi

exit $EXIT_CODE
```

**Валидация:**
```bash
chmod +x /etc/scripts/network_health.sh
/etc/scripts/network_health.sh eth0
# → OK: ip.rx_dropped = 0
# → OK: softnet.dropped = 0
# → OK: softnet.squeezed = 0
# → OK: nic.rx_missed_errors = 0
# → OK: conntrack = 45000/1048576
# → OK: udp.in_errors = 0
# → OK: tcp.listen_overflows = 0
# → OK: tcp.retrans_segs = 0
# → OK: time-wait = 245
# → OK: close-wait = 0
```

**Best Practices:**
- Добавьте скрипт в `cron` или `systemd-timer` для периодической проверки.
- Интегрируйте с `logger` или alertmanager для оповещения при `FAIL`.
- Для Kubernetes используйте `node-exporter` textfile collector или DaemonSet.

**Cleanup:**
```bash
# Нет изменений в системе для отката
```

---

## Порядок комплексной диагностики

При возникновении проблемы следуйте алгоритму (Bottom-up):

1.  **`networkctl status`** — Общий статус сети (для систем с systemd).
2.  **`ip -br link`** — Поднят ли интерфейс (UP/LOWER_UP)?
3.  **`ip -s link show`** — Есть ли ошибки (errors) или отброшенные пакеты (dropped) на L1/L2?
4.  **`ip -c addr`** — Назначен ли корректный IP?
5.  **`ping -c 3 <gateway_ip>`** — Виден ли шлюз (L3 связность)?
6.  **`resolvectl query google.com`** — Работает ли DNS (L7/Application)?
7.  **`nc -zv <target_ip> <port>`** — Доступен ли порт приложения (L4)?
8.  **`mtr -rwzc 100 <target_ip>`** — Где начинаются потери или задержки на пути?
9.  **`ss -tulpn`** — Слушает ли приложение порт на нужном интерфейсе и в нужном состоянии?
10. **`tcpdump` / `pwru`** — Если все вышеперечисленное в норме, но связи нет — переходите к захвату и трассировке пакетов.

**Валидация:**
```bash
# Пример: пошаговая диагностика недоступности сайта
ip -br link
# → eth0            UP             192.168.1.100/24

ip -s link show eth0 | grep -A2 "RX:"
# → RX: bytes  packets  errors  dropped overrun mcast
# → 1234567    8901     0       0       0       0

ping -c 3 192.168.1.1
# → 3 packets transmitted, 3 received, 0% packet loss

resolvectl query google.com
# → google.com: 142.250.186.206 -- link: eth0

nc -zv 142.250.186.206 443
# → Connection to 142.250.186.206 443 port [tcp/https] succeeded!
```

---

## Мониторинг и алертинг

### Prometheus правила

```yaml
# /etc/prometheus/rules/network_stack.yml
groups:
  - name: network_stack_alerts
    rules:
      - alert: HighSoftnetDrops
        expr: rate(node_netstat_Softnet_Drops[5m]) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Потери пакетов в softnet ({{ $labels.instance }})"
          description: "Rate дропов в softnet: {{ $value }}"

      - alert: HighSoftnetSqueezed
        expr: rate(node_netstat_Softnet_Squeezed[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Исчерпание netdev_budget ({{ $labels.instance }})"
          description: "Rate squeezed: {{ $value }}"

      - alert: HighListenOverflows
        expr: rate(node_netstat_TcpExt_TCPListenOverflows[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Переполнение Accept backlog"
          description: "Rate переполнений: {{ $value }}"

      - alert: ConntrackTableFull
        expr: node_netfilter_nf_conntrack_count / node_netfilter_nf_conntrack_max > 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Таблица conntrack заполнена >90%"
          description: "Использовано {{ $value | humanizePercentage }}"

      - alert: HighUDPInErrors
        expr: rate(node_netstat_Udp_InErrors[5m]) > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "UDP пакеты отбрасываются"
          description: "Rate UdpInErrors: {{ $value }}"

      - alert: HighTCPRetrans
        expr: rate(node_netstat_Tcp_RetransSegs[5m]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокий rate TCP ретрансмиссий"
          description: "Retrans rate: {{ $value }}"

      - alert: HighTimeWaitSockets
        expr: node_sockstat_TCP_tw > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High TIME-WAIT sockets on {{ $labels.instance }}"
          description: "TIME-WAIT count is {{ $value }}."
```

**Автоматизация через systemd-timer:**

```bash
# /etc/systemd/system/network-health.service
[Unit]
Description=Network Health Check

[Service]
Type=oneshot
ExecStart=/usr/local/bin/network_health.sh eth0

# /etc/systemd/system/network-health.timer
[Unit]
Description=Run network health check every 5 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Активация
sudo systemctl daemon-reload
sudo systemctl enable --now network-health.timer

# Проверка статуса
systemctl list-timers | grep network-health
```

---

## Дополнительная информация

### Связанные инструменты (подробно)

- **[ss](../Diagnostics/Networking/ss.md)** — глубокий анализ сокетов и TCP-метрик (RTT, cwnd).
- **[tcpdump](../Diagnostics/Networking/tcpdump.md)** — захват и фильтрация трафика.
- **[traceroute и mtr](../Diagnostics/Networking/traceroute_mtr.md)** — детальный анализ маршрута.
- **[Альтернативы ping](../../Networking/Troubleshooting/ping_alternatives.md)** — проверка доступности без ICMP (TCP-пинг).
- **[nmap](../Diagnostics/Networking/nmap.md)** — сканирование сетей.
- **[Сетевые инструменты CLI и TUI](../Diagnostics/Networking/network_cli_tools.md)** — `iftop`, `snitch`, `iptraf-ng`.
- **[ethtool](../../Linux/Networking/Tools/ethtool.md)** — диагностика NIC, offloading, ring buffers.
- **[iperf3](../Diagnostics/Networking/iperf3.md)** — измерение пропускной способности.
- **[xfr](../Diagnostics/Networking/xfr.md)** — современная альтернатива iperf3 на Rust.

### Связанные концепции

- **[Диагностика потерь пакетов в стеке](./network_stack_packet_loss.md)** — глубокий анализ дропов в ядре, NAPI, SoftIRQ, sk_buff.
- **[Порядок диагностики сети](./network_troubleshooting_order.md)** — пошаговый SSoT алгоритм.
- **[TCP tuning overview](./Concepts/tcp_tuning/tcp_tuning_overview.md)** — решение проблем производительности.
- **[Оптимизация NAPI и netdev_budget](./Concepts/napi_optimization.md)** — лимиты обработки пакетов.
- **[RSS, RPS, RFS: Многопоточность](./Concepts/rss_rps_rfs.md)** — балансировка нагрузки по ядрам.

### Протоколы

- **[ICMP](../../Networking/Protocols/ICMP/icmp_overview.md)** — основа работы `ping` и `mtr`.
- **[ARP](../../Networking/Protocols/arp.md)** — связка IP и MAC в локальной сети.
- **[UDP](../../Networking/Protocols/udp.md)** — специфика потерь и буферов.

### Утилиты управления (iproute2)

- **[iproute2 overview](./Tools/iproute2/overview.md)** — замена `net-tools`.
- **[tc](./Tools/iproute2/tc.md)** — имитация задержек и потерь для тестов.
- **[ip-netns](./Tools/iproute2/ip_netns.md)** — управление сетевыми namespace.

### Best Practices (2026)

1.  **Проактивный мониторинг:** Настройте алерты на `softnet.dropped`, `ListenOverflows`, `UdpInErrors`, `conntrack` usage и `TcpRetransSegs`.
2.  **Постепенное изменение:** Увеличивайте параметры постепенно, а не сразу до максимальных значений. Мониторьте влияние на задержки (`si%` в `mpstat`).
3.  **Постоянство:** Сохраняйте изменения в `/etc/sysctl.d/99-*.conf`, а не только временно через `sysctl -w`.
4.  **Валидация после изменений:** Всегда проверяйте счетчики (`nstat`, `softnet_stat`, `ethtool -S`) после применения настроек.
5.  **Изоляция проблем:** Используйте `pwru` или `bpftrace` для точного определения места дропа, а не перебирайте параметры наугад.
6.  **Учет аппаратных ограничений:** Для 10G+ NIC настраивайте Ring Buffers и количество очередей через `ethtool`. Для 100G+ используйте Threaded NAPI (ядро 5.12+).
7.  **Безопасный откат:** Всегда имейте скрипт отката настроек. Используйте версионирование конфигурации (`/etc/sysctl.d/`).
8.  **Отключение offloading при диагностике:** При анализе через `tcpdump` отключайте TSO/GRO (`ethtool -K eth0 tso off gro off`), иначе пакеты отображаются в неразделанном виде.
9.  **Методология USE/RED:** Для каждого компонента сети проверяйте Utilization, Saturation, Errors (или Rate, Errors, Duration).
10. **Bottom-Up подход:** Диагностируйте от физического уровня к приложению, исключая каждый уровень последовательно.

### Типичные ошибки при диагностике

- **Смешение аппаратных и программных потерь:** `rx_dropped` в `ip -s link` может расти из-за переполнения `netdev_max_backlog` (программный уровень), а не только из-за Ring Buffer NIC.
- **Игнорирование Memory Pressure:** Даже если `softnet_stat` нулевой, пакеты могут отбрасываться на уровне `sk_buff` allocation. Проверяйте `dmesg | grep -i napi` и slab-память.
- **Неучет cgroups/containers:** В Docker/Kubernetes параметры `sysctl` могут быть переопределены на уровне Pod security context. Проверяйте приоритет настроек.
- **Асимметричная маршрутизация и rp_filter:** Значение `net.ipv4.conf.all.rp_filter = 1` (Strict) может отбрасывать легитимные пакеты при асимметричной маршрутизации. Проверяйте `sysctl -a | grep rp_filter`.
- **DNS-резолв в инструментах:** Использование `ping hostname` вместо `ping IP` добавляет зависимость от DNS. Всегда используйте `-n` или IP-адреса при диагностике.
- **Зависание traceroute на IPv6:** Если AAAA запись существует, но IPv6 не работает, используйте `-4` для принудительного IPv4.
- **Отключение syncookies при отладке:** `tcp_syncookies=0` убирает защиту от SYN-flood. Не отключайте в production.

### Сводная таблица симптомов → инструмент

| Симптом | Первичный инструмент | Вторичный инструмент |
| :--- | :--- | :--- |
| Нет связности с хостом | `ping -c 3 <ip>` | `ip route get <ip>` |
| Порт закрыт / filtered | `nc -zv <host> <port>` | `ss -tlnp \| grep <port>` |
| Высокий latency / jitter | `mtr -n -c 100 <host>` | `ping -c 100 <host>` |
| Низкий throughput | `iperf3 -c <server> -P 4` | `ethtool -S <iface>` |
| Потери на интерфейсе | `ip -s link show <iface>` | `ethtool -S <iface>` |
| Пакет доходит, но приложение не получает | `tcpdump -i <iface>` | `pwru --filter-dst-port <port>` |
| DNS не резолвит | `dig +trace <domain>` | `resolvectl query <domain>` |
| Firewall блокирует трафик | `nft list ruleset` | `conntrack -E` |
| Accept queue переполнен | `ss -lnt` | `nstat -az \| grep ListenDrops` |
| UDP пакеты отбрасываются | `nstat -az \| grep UdpInErrors` | `ss -unmp` |
| conntrack переполнен | `conntrack -S` | `dmesg \| grep conntrack` |
| Потери на промежуточных хостах | `mtr -n -c 100 <host>` | `tcpdump -i <iface> icmp` |

### Связанные документы

- **[Порядок диагностики сети](./network_troubleshooting_order.md)** — методология «снизу вверх» с расширенными сценариями.
- **[Диагностика потерь пакетов в стеке](./network_stack_packet_loss.md)** — глубокий анализ дропов в ядре, NAPI, SoftIRQ.
- **[Сетевые инструменты CLI и TUI](../Diagnostics/Networking/network_cli_tools.md)** — `iftop`, `snitch`, `iptraf-ng`.
- **[ss](../Diagnostics/Networking/ss.md)** — глубокий анализ сокетов и TCP-метрик (RTT, cwnd).
- **[tcpdump](../Diagnostics/Networking/tcpdump.md)** — захват и фильтрация трафика.
- **[traceroute и mtr](../Diagnostics/Networking/traceroute_mtr.md)** — детальный анализ маршрута.
- **[ethtool](../../Linux/Networking/Tools/ethtool.md)** — диагностика NIC, offloading, ring buffers.
- **[iproute2 overview](../../Linux/Networking/Tools/iproute2/overview.md)** — замена `net-tools`.
- **[Оптимизация TCP](./Concepts/tcp_tuning/tcp_tuning_overview.md)** — решение проблем производительности.
- **[ICMP](../../Networking/Protocols/ICMP/icmp_overview.md)** — основа работы `ping` и `mtr`.
- **[ARP](../../Networking/Protocols/arp.md)** — связка IP и MAC в локальной сети.
