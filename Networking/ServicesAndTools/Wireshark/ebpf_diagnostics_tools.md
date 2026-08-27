# eBPF-инструменты как дополнение к Wireshark

> **SSoT:** eBPF в ядре Linux — в **[eBPF Kernel](../../../Linux/Core/kernel/ebpf.md)**. XDP — в **[eBPF/XDP](../../../Networking/Concepts/sdn/ebpf_xdp.md)**. Потери пакетов — в **[Network Stack Packet Loss](../../../Linux/Networking/network_stack_packet_loss.md)**. Blind spots — в **[Сетевые потери и offloading](./tcp_performance/tcp_network_losses_and_offloading.md)**. Inspektor Gadget — в **[eBPF в Kubernetes](../../../Kubernetes/Networking/Network/CNI/ebpf.md)**.

## Определения

**eBPF (extended Berkeley Packet Filter)** — технология выполнения沙盒-программ в пространстве ядра Linux без модуля ядра. Позволяет перехватывать системные вызовы, сетевые пакеты и внутренние структуры ядра для мониторинга, фильтрации и безопасности.

**pwru (Packet Wheel Up)** — eBPF-инструмент для трассировки пути пакета в ядре Linux. Показывает конкретную функцию ядра, где пакет был обработан, модифицирован или отброшен. Аналог Wireshark, но на уровне ядра.

**bpftrace** — язык и интерпретатор для написания eBPF-программ в стиле awk/tracing. Использует tracepoint, kprobe, uprobe для трассировки событий в ядре и пользовательском пространстве.

**tcpflow** — утилита для реконструкции TCP-потоков из pcap-файлов. Восстанавливает полные данные каждого соединения в отдельные файлы. Полезна для извлечения payload без GUI Wireshark.

**tcptrace** — утилита для анализа TCP-соединений в pcap-файлах. Генерирует графики Sequence Numbers, Window Size, RTT. Эквивалент TCP Stream Graphs Wireshark в CLI.

**dropwatch** — утилита для мониторинга drop-событий в ядре Linux. Использует kprobe для перехвата функций `kfree_skb` и показывает, где пакеты отбрасываются.

**Inspektor Gadget** — eBPF-инструмент для Kubernetes. Предоставляет трассировку системных вызовов, сетевых соединений и файловых операций контейнеров без модификации Pod'ов.

**XDP (eXpress Data Path)** — ранний хук в сетевом стеке Linux (до выделения `sk_buff`). Позволяет обрабатывать пакеты на уровне драйвера NIC со скоростью ~24Mpps на ядро.

## Quick-Start: Какой инструмент выбрать

| Задача | Инструмент | Когда использовать |
| :--- | :--- | :--- |
| **Пакет исчезает в ядре** | `pwru` | tcpdump видит пакет на входе, но приложение не получает |
| **Системный вызов блокируется** | `bpftrace` | Задержка на `read()`, `write()`, `accept()` |
| **Реконструкция потока в файл** | `tcpflow` | Извлечение payload HTTP/gRPC без Wireshark GUI |
| **Графики TCP в CLI** | `tcptrace` | Анализ Sequence/Window/RTT на сервере без GUI |
| **Кто дропает пакеты?** | `dropwatch` / `pwru` | Поиск функции ядра с DROP |
| **Мониторинг контейнеров** | `Inspektor Gadget` | Kubernetes, нет tcpdump в поде |
| **DDoS/XDP фильтрация** | `xdp-dump` | Анализ XDP-программ |

## Основные концепции

###pwru: Трассировка пути пакета в ядре

pwru показывает, через какие функции ядра прошёл пакет и где был отброшен:

```bash
# Установка (через go install или бинарник)
go install github.com/cilium/pwru@latest

# Трассировка всех TCP-пакетов
sudo pwru --filter 'tcp'

# Трассировка конкретного потока
sudo pwru --filter 'tcp.port == 8080 && ip.dst == 10.0.0.1'

# С фильтрацией по направлению
sudo pwru --filter 'ip.src == 10.0.0.5 && tcp.dstport == 443'

# С указанием output
sudo pwru --output /tmp/pwru.log --filter 'tcp'
```

**Вывод pwru:**
```
SKB    CPU    PROCESS    func
0xffff...  0    curl       ip_rcv → ip_rcv_finish → nf_hook_slow → nft_do_chain → tcp_v4_rcv
```

Если пакет исчезает на конкретной функции — это место DROP. Например:
- `nft_do_chain` → файрвол (iptables/nftables) отбросил
- `nf_conntrack_in` → conntrack table full
- `br_handle_frame` → bridge не пропустил

### bpftrace: Трассировка syscall и сетевых событий

```bash
# Установка
sudo apt install bpftrace  # или bcc-tools

# Трассировка всех TCP connect() syscall
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_connect { printf("%s %d\n", comm, pid); }'

# Задержка на accept() (поиск bottleneck в listener)
sudo bpftrace -e '
kprobe:tcp_accept {
    @start[tid] = nsecs;
}
kretprobe:tcp_accept /@start[tid]/ {
    printf("accept latency: %d us\n", (nsecs - @start[tid]) / 1000);
    delete(@start[tid]);
}'

# Мониторинг TCP retransmissions на уровне ядра
sudo bpftrace -e 'kprobe:tcp_retransmit_skb { @[comm, pid] = count(); }'

# Время выполнения send/recv
sudo bpftrace -e '
kprobe:tcp_sendmsg { @send_start[tid] = nsecs; }
kretprobe:tcp_sendmsg /@send_start[tid]/ {
    @send_us = hist((nsecs - @send_start[tid]) / 1000);
    delete(@send_start[tid]);
}'

# Мониторинг conntrack insert_failed
sudo bpftrace -e 'kprobe:nf_conntrack_insert_failed { @drops = count(); }'
```

### tcpflow: Реконструкция TCP-потоков

```bash
# Реконструкция всех потоков
tcpflow -r capture.pcap

# Реконструкция конкретного потока
tcpflow -r capture.pcap 'host 10.0.0.1 and port 80'

# С сохранением порядка
tcpflow -r capture.pcap -C  # optional checksums

# Результат: файлы 010.000.000.001.00080-10.000.000.002.12345
# Содержимое: полный payload HTTP/gRPC/... без заголовков TCP/IP
```

### tcptrace: Анализ TCP в CLI

```bash
# Установка
sudo apt install tcptrace

# Базовый анализ
tcptrace capture.pcap

# Графики (в формате xplot или text)
tcptrace -x capture.pcap

# Потоки с потерями
tcptrace -l capture.pcap | grep -E "retrans|loss"

# Статистика по потокам
tcptrace -c capture.pcap
# → Shows: packets, bytes, RTT, loss rate per connection
```

### dropwatch: Мониторинг drop-событий

```bash
# Установка
sudo apt install dropwatch

# Запуск (показывает функции ядра с drop)
sudo dropwatch -l kas

# Пример вывода:
# drop at: nf_hook_slow+0xb3 (0xffffffff815a3c73)   aql饮酒 22
# drop at: tcp_v4_rcv+0x2c5 (0xffffffff8161ab25)   aql饮酒 5
# → nf_hook_slow: файрвол отбросил 22 пакета
# → tcp_v4_rcv: TCP стек отбросил 5 пакетов (bad checksum, invalid state)
```

## Практические сценарии

### Сценарий 1: Пакет исчезает между NIC и приложением

**Симптом:** tcpdump видит SYN, но приложение не получает соединение.

```bash
# 1. pwru: где пакет был отброшен?
sudo pwru --filter 'tcp.dstport == 8080 && tcp.flags.syn == 1'

# Вывод покажет функцию:
# → nft_do_chain: файрвол блокирует порт 8080
# → nf_conntrack_in: conntrack table full
# → __inet_lookup_skb: сокет не слушает порт
# → tcp_v4_conn_request: backlog queue переполнен
```

### Сценарий 2: Высокая задержка на syscall

**Симптом:** Приложение медленно обрабатывает запросы, но сеть быстрая.

```bash
# 1. bpftrace: замер времени accept()
sudo bpftrace -e '
kprobe:tcp_accept { @start[tid] = nsecs; }
kretprobe:tcp_accept /@start[tid]/ {
    printf("accept: %d us\n", (nsecs - @start[tid]) / 1000);
    delete(@start[tid]);
}'

# 2. bpftrace: замер времени read()
sudo bpftrace -e '
kprobe:tcp_recvmsg { @start[tid] = nsecs; }
kretprobe:tcp_recvmsg /@start[tid]/ {
    printf("recv: %d us\n", (nsecs - @start[tid]) / 1000);
    delete(@start[tid]);
}'

# Если latency > 10 мс → проблема на уровне приложения (GC, lock, IO)
# Если latency < 1 мс → проблема в сети (RTT,丢了)
```

### Сценарий 3: Анализ XDP-программ (Cilium, Calico)

```bash
# Проверка XDP-программ на интерфейсе
ip link show dev eth0 | grep xdp
# → xdp

# Просмотр XDP-программ
sudo bpftool prog show | grep xdp
# → id 42 type xdp name cilium_xdp ...

# Статистика drop по XDP-программе
sudo bpftool map dump name cilium_xdp_stats

# XDP_DROP = 10-100x быстрее iptables DROP
# Если XDP отбрасывает пакеты — tcpdump их не увидит
# Решение: xdp-dump или pwru для анализа
```

### Сценарий 4: Извлечение HTTP-данных без Wireshark GUI

```bash
# tcpflow: реконструкция всех HTTP-потоков
tcpflow -r web_traffic.pcap 'tcp port 80'

# Результат: файлы с payload каждого соединения
cat 010.000.001.000.00080-10.000.001.001.45678
# → HTTP/1.1 200 OK
#   Content-Type: text/html
#   ...
#   <html>...</html>

# Извлечение только POST-данных
tcpflow -r api_traffic.pcap 'tcp port 443'
# После расшифровки TLS:
# Каждый файл = один HTTP-запрос/ответ
```

### Сценарий 5: Анализ TCP через tcptrace на сервере

```bash
# Статистика по всем соединениям
tcptrace -c web_capture.pcap
# →shows packets, bytes, RTT, retransmissions per connection

# Поиск соединений с высоким RTT
tcptrace -l web_capture.pcap | awk '$5 > 100 {print}'

# Потоки с потерями > 1%
tcptrace -l web_capture.pcap | awk '$7 > 1 {print}'
```

### Сценарий 6: Inspektor Gadget в Kubernetes

```bash
# Установка Inspektor Gadget
kubectl gadget deploy

# Трассировка TCP-соединений пода
kubectl gadget trace tcp -n <namespace> -c <container>

# Трассировка DNS-запросов
kubectl gadget trace dns -n <namespace> -c <container>

# Трассировка системных вызовов
kubectl gadget trace syscall -n <namespace> -c <container> -F open
kubectl gadget trace syscall -n <namespace> -c <container> -F connect

# Сниффиинг (аналог tcpdump)
kubectl gadget sni -n <namespace>  # SNI из TLS ClientHello
```

## Дополнительная информация

### Сравнение инструментов

| Инструмент | Уровень | Overhead | Без GUI | Kubernetes | Разрешения |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Wireshark** | L2-L7 | Средний | Да | Да (ksniff) | root / CAP_NET_RAW |
| **tcpdump** | L2-L4 | Низкий | Да | Да (ephemeral) | root / CAP_NET_RAW |
| **pwru** | Ядро (functions) | Средний | Да | Да | root / CAP_BPF |
| **bpftrace** | Ядро (syscall) | Средний | Да | Да | root / CAP_BPF |
| **tcpflow** | L4-L7 | Низкий | Да | Да | Любой |
| **tcptrace** | L4 | Низкий | Да | Да | Любой |
| **dropwatch** | Ядро (drop) | Низкий | Да | Ограниченно | root |
| **Inspektor Gadget** | Ядро + L7 | Низкий | Да | Да | root |

### Когда использовать eBPF вместо Wireshark

| Сценарий | Wireshark | eBPF |
| :--- | :--- | :--- |
| Анализ протоколов L7 | ✅ Лучший выбор | ❌ Ограничен |
| Поиск DROP в ядре | ❌ Не видит | ✅ pwru/dropwatch |
| Мониторинг syscall | ❌ Не видит | ✅ bpftrace |
| Захват в контейнере | ⚠️ Требует setup | ✅ Inspektor Gadget |
| Высокоскоростная сеть (10G+) | ⚠️ Перегрузка CPU | ✅ XDP |
| Анализ application latency | ❌ Не видит | ✅ bpftrace uprobe |
| Извлечение payload | ✅ Export Objects | ✅ tcpflow |

### Интеграция eBPF + Wireshark

```bash
# 1. pwru находит DROP → Wireshark анализирует остаток трафика
sudo pwru --filter 'tcp.port == 8080' --output /tmp/pwru.log
# → DROP на nft_do_chain: правило файрвола

# 2. Извлечение pcap из Containers
kubectl debug -it <pod> --image=nicolaka/netshoot -- tshark -i eth0 -w /tmp/capture.pcapng

# 3. Анализ через tcptrace, затем детализация в Wireshark
tcptrace -c capture.pcap  # обзор
wireshark capture.pcap     # детали
```

### См. также
- **[eBPF Kernel](../../../Linux/Core/kernel/ebpf.md)** — основы eBPF
- **[eBPF/XDP](../../../Networking/Concepts/sdn/ebpf_xdp.md)** — XDP и сетевые программы
- **[Network Stack Packet Loss](../../../Linux/Networking/network_stack_packet_loss.md)** — потери в сетевом стеке
- **[Сетевые потери и offloading](./tcp_performance/tcp_network_losses_and_offloading.md)** — blind spots Wireshark
- **[Основные концепции](./core_concepts.md)** — захват трафика
- **[Service Mesh Analysis](./service_mesh_analysis.md)** — анализ sidecar через eBPF
