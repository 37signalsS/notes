# iperf3 — измерение пропускной способности сети

## Определения

**`iperf3`** — эталонная консольная утилита для активного измерения максимально достижимой пропускной способности IP-сетей. Она реализует клиент-серверную модель и позволяет оценивать реальную скорость передачи данных по протоколам TCP, UDP и SCTP, предоставляя детальные метрики задержки (jitter) и потерь пакетов.

**Goodput** — полезная пропускная способность, измеряемая в битах/сек полезных данных прикладного уровня (за вычетом заголовков транспортного и сетевого уровней, а также повторных передач). В отличие от raw throughput, goodput отражает реальную скорость доставки данных приложению.

**BDP (Bandwidth-Delay Product)** — произведение пропускной способности канала на Round-Trip Time (RTT). Определяет минимальный объем буферов, необходимых для полной утилизации канала: `BDP = Bandwidth (bps) × RTT (s)`.

**PMTUD (Path MTU Discovery)** — механизм автоматического определения минимального MTU на пути. Релевантен для iperf3, так как тесты с большими буферами могутFail при несоответствии MSS/MTU. См. **[MTU, PMTUD и диагностика](../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)**.

## Основные концепции

Тестирование требует наличия двух узлов:
1.  **Сервер (`-s`):** пассивно ожидает входящих соединений.
2.  **Клиент (`-c`):** инициирует поток данных и задает параметры теста.

### Измеряемые метрики

| Метрика | Описание | Протокол |
| :--- | :--- | :--- |
| **Throughput** | Реальная скорость передачи полезных данных (Goodput). | TCP, UDP, SCTP |
| **Packet Loss** | Процент потерянных датаграмм. | UDP |
| **Jitter** | Вариация задержки между пакетами. | UDP |
| **Retransmits** | Количество повторных передач сегментов. | TCP |
| **CWND** | Текущий размер окна перегрузки (Congestion Window). | TCP |

### Основные флаги и аргументы

- `-s` / `-c <адрес>`: выбор режима (сервер/клиент).
- `-p <порт>`: порт (по умолчанию **5201**).
- `-t <сек>`: длительность теста (стандартно 10 сек).
- `-i <сек>`: интервал промежуточных отчетов.
- `-P <n>`: число параллельных потоков (необходимо для 10GbE+ или при высокой латентности).
- `-w <размер>`: размер TCP-окна / сокетного буфера (например, `2M`).
- `-A <n>`: привязка процесса к конкретному ядру CPU (Affinity).
- `-4` / `-6`: принудительное использование IPv4 или IPv6.
- `-R`: реверсивный режим (сервер передает, клиент принимает).
- `--bidir`: двунаправленный режим (Full-Duplex, одновременная передача в обе стороны).
- `-J`: вывод в формате JSON.
- `--json-streaming`: потоковый JSON для длинных тестов.
- `--one-off`: сервер завершает работу после одного теста.
- `--logfile <path>`: запись вывода в файл.
- `-M <mss>`: установка MSS (Maximum Segment Size) для диагностики MTU.
- `-l <размер>`: размер буфера/пакета (по умолчанию 128KB для TCP).
- `-u -b <полоса>`: UDP тест с указанием целевой полосы.

### Параметры ядра, влияющие на тестирование

Для получения релевантных результатов необходимо настроить сетевой стек до начала тестирования. Неправильные параметры могут искусственно ограничивать пропускную способность.

#### Буферы сокетов

```bash
# Максимальный размер буферов приема/отправки
sudo sysctl -w net.core.rmem_max=67108864
sudo sysctl -w net.core.wmem_max=67108864

# Диапазоны буферов TCP (min default max)
sudo sysctl -w net.ipv4.tcp_rmem="4096 87380 67108864"
sudo sysctl -w net.ipv4.tcp_wmem="4096 65536 67108864"

# Память, выделяемая под TCP-сокеты (в страницах по 4KB)
sudo sysctl -w net.ipv4.tcp_mem="8388608 12582912 16777216"
```

#### Очереди соединений

```bash
# Максимальный размер очереди полностью установленных соединений
sudo sysctl -w net.core.somaxconn=65535

# Очередь полуоткрытых соединений (SYN-RECV)
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=16384

# Очередь пакетов на уровне интерфейса
sudo sysctl -w net.core.netdev_max_backlog=5000
```

#### Дополнительные параметры

```bash
# Включение TCP Fast Open для снижения задержки handshake
sudo sysctl -w net.ipv4.tcp_fastopen=3

# Для чистого измерения (ТОЛЬКО изолированные стенды!)
sudo sysctl -w net.ipv4.tcp_congestion_control=cubic

# Автотюнинг буферов
sudo sysctl -w net.ipv4.tcp_moderate_rcvbuf=1
```

> **Важно:** Изменения через `sysctl -w` временные (до перезагрузки). Для постоянного применения добавьте параметры в `/etc/sysctl.d/99-network-benchmark.conf`.

### Аппаратная оптимизация (NIC)

```bash
# Увеличение размеров кольцевых буферов (Ring Buffers)
sudo ethtool -G eth0 rx 4096 tx 4096

# Проверка offloading (для тестов с маленькими пакетами может давать ложные результаты)
ethtool -k eth0 | grep -E "scatter|tx-checksum|gro|gso|tso"

# Включение multi-queue (если NIC поддерживает)
sudo ethtool -L eth0 combined 8

# Отключение прерываний (Coalescing) для снижения задержек
sudo ethtool -C eth0 rx-usecs 0 tx-usecs 0
```

### Порты и файрволы

По умолчанию `iperf3` использует порт **5201/tcp** (и 5201/udp для UDP-тестов). На сервере убедитесь, что порт открыт:

```bash
# ufw
sudo ufw allow 5201/tcp
sudo ufw allow 5201/udp

# firewalld
sudo firewall-cmd --add-port=5201/tcp --permanent
sudo firewall-cmd --add-port=5201/udp --permanent
sudo firewall-cmd --reload

# iptables (временное правило)
sudo iptables -A INPUT -p tcp --dport 5201 -j ACCEPT
sudo iptables -A INPUT -p udp --dport 5201 -j ACCEPT
```

## Практические сценарии

### Базовый TCP тест (Upload)

Проверка скорости отдачи от клиента к серверу.

```bash
# На сервере (192.168.1.10)
iperf3 -s

# На клиенте
iperf3 -c 192.168.1.10
# → [ ID] Interval           Transfer     Bandwidth       Retr  Cwnd
# → [  5]   0.00-10.00  sec  1.10 GBytes   945 Mbits/sec    0    256 KBytes
```

### Реверсивный тест (Download)

Проверка скорости приема сервером (клиент получает данные).

```bash
# На сервере
iperf3 -s

# На клиенте
iperf3 -c 192.168.1.10 -R
# → Bandwidth: XX Mbits/sec (Receiver)
```

### Двунаправленный тест (Full-Duplex)

Одновременная передача данных в обе стороны.

```bash
# На сервере
iperf3 -s

# На клиенте
iperf3 -c 192.168.1.10 --bidir
# → Показывает отдельно Upload и Download
```

### Тестирование UDP (Качество канала)

UDP тест требует указания целевой полосы (`-b`), так как протокол не имеет встроенного контроля перегрузки.

```bash
# Тест канала 100 Мбит/с с проверкой потерь
iperf3 -c 192.168.1.10 -u -b 100M
# → [ ID] Interval           Transfer     Bandwidth      Jitter    Lost/Total
# → [  5]   0.00-10.00  sec   119 MBytes   100 Mbits/sec  0.025 ms  0/86184 (0%)
```

### Тестирование SCTP

SCTP (Stream Control Transmission Protocol) обеспечивает надежную доставку с сохранением границ сообщений.

```bash
# Запуск теста SCTP
iperf3 -c 192.168.1.10 --sctp
```

### Настройка TCP-окна для LFN (Long Fat Networks)

В сетях с высокой пропускной способностью и большой задержкой (например, транспланетарные линки) стандартные буферы ОС могут ограничивать скорость.

```bash
# Установка размера сокетного буфера 4 МБ
iperf3 -c 192.168.1.10 -w 4M
```

### Диагностика MTU и MSS

Помогает выявить проблемы "зависания" пакетов в туннелях (VPN/VxLAN).

```bash
# Установка конкретного размера MSS (Maximum Segment Size)
# TCP-заголовок (20) + IP (20) + MSS (1460) = MTU 1500
iperf3 -c 192.168.1.10 -M 1460

# Поиск оптимального MSS (сравнение пропускной способности):
for mss in 1360 1380 1400 1420 1440 1460; do
  echo "=== MSS $mss ==="
  iperf3 -c 192.168.1.10 -M $mss -t 3 -P 1 2>&1 | grep -E "sender|receiver|Bitrate"
done
```

> **Примечание:** Для детального анализа MTU/PMTUD см. **[MTU, PMTUD и диагностика](../../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)**.

### Оптимизация через привязку к CPU (Affinity)

Уменьшение контекстных переключений для тестов на 40GbE/100GbE.

```bash
# Привязка к 0-му ядру CPU
iperf3 -c 192.168.1.10 -A 0
```

### Авторизация и безопасность

Для предотвращения несанкционированного использования сервера в публичных сетях.

```bash
# Генерация файла паролей (формат: user,sha256_password)
echo "admin,$(echo -n 'secret' | sha256sum | awk '{print $1}')" > credentials.csv

# Запуск сервера с авторизацией
iperf3 -s --rsa-private-key server_key.pem --authorized-users credentials.csv

# Подключение клиента
iperf3 -c 192.168.1.10 --username admin --rsa-public-key server_pub.pem
```

### Тестирование в контейнере (Docker/Podman)

```bash
# Сервер (host network для доступа к физическим интерфейсам)
docker run -d --name iperf3-srv --network host --cap-add NET_RAW iperf3 -s

# Клиент
docker run --rm --network host iperf3 -c 192.168.1.10 -t 30 -P 4

# Podman (аналогично)
podman run -d --name iperf3-srv --network host iperf3 -s
```

> **Примечание:** Без `--network host` Docker применяет собственный стек, что измеряет производительность моста/оверлея, а не физического канала. Для тестирования через сам контейнерный интерфейс уберите `--network host` и используйте внутренний IP контейнера.

### NUMA-aware тестирование

На системах с несколькими сокетами (NUMA) важно привязывать процессы и прерывания к одному узлу для избежания доступа к удаленной памяти.

```bash
# Проверка топологии NUMA
numactl --hardware

# Запуск сервера на NUMA-node 0
numactl --cpunodebind=0 --membind=0 iperf3 -s

# Запуск клиента на NUMA-node 0
numactl --cpunodebind=0 --membind=0 iperf3 -c 192.168.1.10 -P 8
```

### systemd-сервис для постоянного сервера

```ini
# /etc/systemd/system/iperf3-server.service
[Unit]
Description=iperf3 Bandwidth Server
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/iperf3 -s
Restart=on-failure
RestartSec=5

# Ограничения ресурсов (опционально)
CPUAffinity=0 1
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now iperf3-server
```

### Многоместное тестирование (mesh)

```bash
#!/usr/bin/env bash
# bench-mesh.sh — тестирование пропускной способности между всеми узлами кластера
HOSTS=(192.168.1.10 192.168.1.11 192.168.1.12)

for src in "${HOSTS[@]}"; do
  for dst in "${HOSTS[@]}"; do
    if [ "$src" != "$dst" ]; then
      echo "=== $src -> $dst ==="
      ssh "$src" "iperf3 -c $dst -t 20 -P 4 -J" | tee "bench-${src}-${dst}.json"
    fi
  done
done
```

### Валидация изменений сети (Pre/Post Change)

Методология сравнения baseline и post-change производительности:

```bash
#!/usr/bin/env bash
# network-baseline.sh — фиксация baseline до изменений
TARGET=192.168.1.10
BASELINE_FILE="/var/tmp/iperf3_baseline_$(date +%Y%m%d).json"

echo "Запуск baseline-теста (30 сек, 8 потоков)..."
iperf3 -c $TARGET -t 30 -P 8 -J > $BASELINE_FILE

echo "Baseline сохранен: $BASELINE_FILE"
echo "Средняя полоса:"
jq '.end.sum_sent.bits_per_second' $BASELINE_FILE | awk '{print $0/1e6 " Mbps"}'
```

После внесения изменений (обновление firmware, смена кабеля, настройка QoS) повторите тест и сравните:

```bash
#!/usr/bin/env bash
# compare-baseline.sh
BASELINE=$1
CURRENT=$2

if [ -z "$BASELINE" ] || [ -z "$CURRENT" ]; then
  echo "Usage: $0 <baseline.json> <current.json>"
  exit 1
fi

BASE_BW=$(jq '.end.sum_sent.bits_per_second' $BASELINE)
CURR_BW=$(jq '.end.sum_sent.bits_per_second' $CURRENT)
DIFF=$(echo "scale=2; ($CURR_BW - $BASE_BW) / $BASE_BW * 100" | bc)

echo "Baseline: $(echo $BASE_BW | awk '{print $0/1e6 " Mbps"}')"
echo "Current:  $(echo $CURR_BW | awk '{print $0/1e6 " Mbps"}')"
echo "Diff:     ${DIFF}%"

if (( $(echo "$DIFF < -5" | bc -l) )); then
  echo "РЕГРЕССИЯ: пропускная способность упала более чем на 5%"
  exit 1
else
  echo "OK: изменение в пределах допуска"
fi
```

## Дополнительная информация

### Интерпретация результатов

- **Retransmits > 0 (TCP):** сигнал о потерях на физическом уровне, переполнении буферов коммутаторов или некорректном шейпинге.
- **Асимметрия:** если `Upload >> Download` (тест с `-R`), проверьте настройки дуплекса на портах или политики провайдера.
- **CPU Bound:** если в отчете JSON поле `cpu_utilization_percent` близко к 100%, результат теста ограничен производительностью процессора.
- **JSON Streaming:** при выполнении очень длинных тестов используйте `--json-streaming` для получения результатов по мере их готовности.

### Throughput vs Goodput

| Показатель | Описание | Типичное соотношение |
| :--- | :--- | :--- |
| **Throughput** | Общий объем переданных бит, включая заголовки Ethernet, IP, TCP/UDP и повторные передачи. | 100% (эталон) |
| **Goodput** | Полезная пропускная способность прикладного уровня. Для TCP goodput обычно на 5-15% ниже throughput из-за overhead и ретрансмиссий. | 85-95% от throughput |

### Оценка CPU Bound

```bash
# Во время теста в другом терминале
mpstat -P ALL 1
# → Если %usr + %sys接近 100% на всех ядрах — тест ограничен CPU, не сетью

# Проверка утилизации через JSON
iperf3 -c 192.168.1.10 -J | jq '.end.sum_sent.cpu_utilization_percent'
```

### Типичные артефакты и интерпретация

| Артефакт | Причина | Действие |
| :--- | :--- | :--- |
| **Retransmits > 0** | Потери пакетов на L2/L3, переполнение буферов коммутаторов | Проверьте `ethtool -S`, `tc qdisc`, замените кабель |
| **CPU utilization > 90%** | Ограничение производительностью процессора (часто на 10GbE+) | Используйте `numactl`, `taskset`, проверьте `mpstat` |
| **Асимметрия Upload/Download** | Неправильная настройка дуплекса на портах, политики провайдера | Проверьте `ethtool eth0` (duplex), тестируйте в обе стороны |
| **Jitter > 1ms (UDP)** | Перегрузка очередей (Bufferbloat), ECN-marking | Настройте `fq_codel` qdisc, проверьте `tc -s qdisc` |
| **Дискретность результатов (±10%)** | Вариабельность фоновой нагрузки, turbo boost | Зафиксируйте частоту CPU (`cpufreq-set`), отключите hyper-threading |
| **Низкий throughput на 10GbE+** | Недостаточные буферы или однопоточность | Увеличить `rmem_max`/`wmem_max`, добавить потоки `-P` |
| **Потери при 0% retransmits (UDP)** | Приемный буфер переполняется | Увеличить `net.core.rmem_max`, проверить `netstat -su` |

### Коды возврата (Exit Codes)

Понимание кодов завершения важно для автоматизации и скриптов:
- `0` — Успех (получен хотя бы один ответ).
- `1` — Ошибка (запросы отправлены, но ответов нет — 100% loss).
- `2` — Системная ошибка (неверные параметры, проблемы с DNS, отсутствие прав).
- `3` — Ошибка создания сокета (недостаточно прав или ресурсов).

### Сравнение iperf3 и xfr

| Характеристика | iperf3 | xfr |
| :--- | :--- | :--- |
| **Язык** | C | Rust |
| **Архитектура** | Однопоточная | Многопоточная (Tokio) |
| **Параллельные тесты** | Нет (очередь) | Да (одновременно) |
| **QUIC / MPTCP** | Нет | Да |
| **Графики (TUI)** | Нет | Встроены |
| **Автообнаружение** | Нет | mDNS |
| **Анализ различий** | Внешние скрипты | Команда `diff` |

> **Примечание:** Для современных протоколов (QUIC, MPTCP) и multi-client сценариев рассмотрите **[xfr](./xfr.md)**.

### Сравнение с другими инструментами

| Инструмент | Язык | Особенности | Когда использовать |
| :--- | :--- | :--- | :--- |
| **iperf3** | C | Эталон, широко распространен, SCTP | Базовые тесты, совместимость |
| **nuttcp** | C | Детальная статистика, поддержка multicast | Тесты с фиксированным размером пакета |
| **netperf** | C | Тесты request/response (TCP_RR, UDP_RR) | Оценка latency под высокой нагрузкой |
| **xfr** | Rust | QUIC, MPTCP, TUI, multi-client | Современные протоколы, визуализация |

### Связанные инструменты

- **[xfr](./xfr.md)** — современная альтернатива на Rust.
- **[network_diagnostics_tools.md](../../../Linux/Networking/network_diagnostics_tools.md)** — методология сетевой диагностики.
- **[Оптимизация TCP](../../../Linux/Networking/Concepts/tcp_tuning/tcp_tuning_overview.md)** — тюнинг параметров для высокой скорости.
- **[MTU, PMTUD и диагностика](../../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — диагностика MTU через iperf3 MSS тесты.
- **[IPsec: производительность](../../../Networking/Tunnels/ipsec/ipsec_performance.md)** — iperf3 через туннели IPsec.
- **[tc netem](../../../Linux/Networking/Tools/iproute2/tc_netem.md)** — эмуляция сетевых проблем с валидацией через iperf3.

### Ссылки

- **Официальный репозиторий:** [esnet/iperf](https://github.com/esnet/iperf)
- **Документация по флагам:** `man iperf3`
