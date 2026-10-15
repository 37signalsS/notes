# WireGuard: производительность и тюнинг

**Актуально для:** WireGuard (модуль ядра Linux 1.0.x, `wireguard-tools` 1.0.x; нативная поддержка в ядре Linux 5.6+); userspace-реализация wireguard-go; протокол WireGuard v1.

## Определения

**Throughput** — полезная пропускная способность (goodput) через туннель, обычно в Мбит/с. Ограничивается самым медленным звеном: физический NIC, криптография, очереди ядра или само ядро туннеля.

**Latency (RTT) / P99** — задержка прохождения пакета и её «хвост» (99-й процентиль). Для интерактивного трафика tail-latency важнее среднего: именно P99 показывает очереди и голодание ядер.

**PPS (Packets Per Second)** — число пакетов в секунду. При малом размере пакета именно PPS, а не пропускная способность, упирается в лимит обработки на ядро (~1.5–3 Mpps на одно ядро без оптимизаций).

**Kernel (модуль)** — реализация WireGuard как модуля ядра Linux (`wireguard.ko`, штатно с 5.6+). **Userspace-реализация** — wireguard-go (эталон, Go) и BoringTun (Rust, Cloudflare), работающие в пространстве пользователя через TUN-устройство.

**MTU/MSS** — максимальная единица передачи IP и максимальный размер сегмента TCP. Внутри туннеля MTU меньше физического на величину overhead (для WireGuard — 80 байт при IPv4/UDP-транспорте). Неверный MTU даёт фрагментацию и «залипания».

**RSS/RPS/XPS** — аппаратное (RSS) и программное (RPS, XPS) распределение обработки пакетов между CPU. Детали — [RSS, RPS, RFS, XPS](../Linux/Networking/Concepts/rss_rps_rfs.md).

**Threaded NAPI** — вынос обработки сетевых пакетов из контекста softirq в отдельные потоки ядра (введено в Linux 5.12). Устраняет схождение NAPI нескольких туннелей на одном ядре. Подробнее — [Оптимизация NAPI](../Linux/Networking/Concepts/napi_optimization.md).

**SoftIRQ / ksoftirqd** — контекст, в котором выполняется основная сетевая обработка. Высокая загрузка `si` в `top` и высокий CPU у `ksoftirqd/N` указывают на нехватку ресурсов на RX-пути.

**GSO/GRO** — generic segmentation/receive offload: агрегация и сегментация «суперпакетов» до 64 КБ. Для WireGuard это ключевой механизм батчинга. Основы — [Сетевая разгрузка: GRO, TSO, GSO](../Linux/Networking/Concepts/offloading.md).

## Основные концепции

### Стек обработки пакета

Пакет клиента → сетевой стек → WireGuard (шифрование ChaCha20-Poly1305, инкапсуляция в UDP) → физическая карта. На обратном пути — приём UDP, расшифровка, инъекция расшифрованного пакета в стек. Горячие точки производительности:

1. **Криптография.** ChaCha20-Poly1305 быстра и имеет SIMD-оптимизации (AVX2/AVX-512, NEON); на современных CPU её стоимость не является основным ограничением — узкое место почти всегда в очередейной архитектуре, а не в шифре.
2. **Ввод-вывод физического NIC.** Зашифрованный UDP приходит на `eth0`, обрабатывается в прерывании и softirq. Именно здесь чаще всего «узкое горло»: PPS приёма, IRQ affinity, RPS.
3. **Модель параллелизма.** Ядерный WireGuard распараллеливает шифрование между ядрами, но сохраняет порядок для каждого пира (см. ниже). Это определяет масштабирование «много пиров» vs «один пир».
4. **MTU/фрагментация.** При MTU выше допустимого внутренний TCP сталкивается с фрагментацией → потери и суперлинейное падение скорости.
5. **TCP внутри UDP.** TCP-поток в туннеле видит UDP-транспорт с потерями; поведение зависит от MTU/MSS и qdisc на концентраторе.

### Модель параллелизма WireGuard в ядре

Понимание этой модели объясняет, почему «много клиентов» и «один быстрый поток» масштабируются по-разному:

- Устройство `wg0` имеет **глобальные очереди шифрования/дешифрования** и **очереди на каждого пира**.
- Исходящие пакеты получают nonce (он же sequence number) и складываются в очередь пира; затем ядро запускает обработку шифрования на разных CPU через `queue_work_on` в режиме round-robin. Так **шифрование идёт всеми ядрами сразу**, но остаётся упорядоченным.
- Передача на провод для конкретного пира **сериализована**: пакеты пира выходят из одной per-peer очереди в исходном порядке. Поэтому один пир/один поток упирается в один последовательный участок, а множество пиров хорошо распределяются по ядрам.
- На приёме расшифрованные пакеты агрегируются через GRO (`napi_gro_receive`) и затем отдаются в стек.
- Историческая проблема масштабирования: при всплеске трафика на многих туннелях NAPI нескольких устройств `wg` «съезжались» на одно ядро, и суммарная производительность не росла. Решение — **threaded NAPI**: в актуальных ядрах драйвер WireGuard включает его по умолчанию (`dev_set_threaded`), перекладывая опрос на отдельный поток ядра, который планировщик балансирует по всем ядрам.

Практический вывод: для концентратора с множеством клиентов ядерный WireGuard масштабируется хорошо «из коробки»; для единичного высокоскоростного потока потолок задаёт per-peer сериализация, и здесь выручают оффлоуды и MTU, а не «магические» sysctl.

### Kernel vs Userspace

| Аспект | Kernel (модуль) | Userspace (wireguard-go / BoringTun) |
|--------|-----------------|--------------------------------------|
| Скорость | Высокая; масштабируется по ядрам | По умолчанию ниже и с большим CPU на пакет; с TUN UDP GSO/GRO (ядро ≥ 6.2) может догонять и обгонять ядерный вариант |
| Потребление CPU | Ниже (обработка в ядре) | Выше (syscall, копирование, контекстные переключения) |
| Параллелизм | Очереди на устройство и на пир, шифрование на всех CPU | Число воркеров = логическим CPU (`GOMAXPROCS`); узкое место — единственный читатель TUN |
| Когда применяют | Linux 5.6+ / DKMS | Платформы без модуля (BSDs, macOS, Windows), контейнеры без доступа к `wireguard.ko`, отладка |

Важные оговорки:

- **Числа «в вакууме» бессмысленны.** Итог зависит от CPU, NIC (есть ли многоочередность), MTU, размера пакета и числа потоков. Опубликованные результаты различаются в разы: в одних тестах ядерный модуль быстрее, в других wireguard-go с оффлоудами выходит вперёд (так было в бенчмарках Tailscale на ядре ≥ 6.2). Не переносите чужие цифры на свой стенд — измеряйте.
- **BoringTun де-факто не развивается** как самостоятельный проект (последние релизы редки); развиваются форки. Для продакшена на Linux ориентируйтесь на ядерный модуль.
- **`WG_QUICK_USERSPACE_IMPLEMENTATION` — не «переключатель».** В `wg-quick` на Linux этот параметр учитывается только в **fallback-ветке**, то есть когда создать интерфейс ядерного типа не удалось (модуль отсутствует). Если модуль есть, переменная игнорируется, и будет использован kernel. Чтобы принудительно уйти в userspace — выгрузите/заблокируйте модуль (`modprobe -r wireguard`, blacklist) и задайте переменную.

### Оффлоуды и батчинг — где на самом деле берётся скорость

- Драйвер ядерного WireGuard помечен как поддерживающий hardware GSO: стек может отдать ему «суперпакет» ~64 КБ, а драйвер сам режет его `skb_gso_segment` на MTU-сегменты и шифрует пачками. На приёме GRO собирает расшифрованные пакеты в батчи. Это даёт выигрыш и по CPU, и по latency.
- wireguard-go получает аналогичный выигрыш от **UDP GSO/GRO на TUN-устройстве**, но это доступно только на ядре **6.2+** (virtio-расширения TUN). Именно поэтому на свежих ядрах userspace может обгонять ядерный модуль, а на старых — заметно ему проигрывать.
- В топологиях **форвардинга** (subnet router, exit node) добавьте на интерфейс приёма `rx-udp-gro-forwarding`: без этого пересылаемые UDP-пакеты не коалесцируются, и эффект GRO теряется.

### Что реально ограничивает производительность

| Узкое место | Признак | Рычаг |
|-------------|---------|-------|
| Приём на NIC (PPS/IRQ) | один CPU в softirq 100%, drops в `softnet_stat` | RSS/RPS, IRQ affinity, threaded NAPI, разгрузка |
| Один пир / один поток | не растёт при добавлении ядер | MTU, оффлоуды; рассмотреть несколько туннелей |
| Криптография | ровная загрузка многих ядер, но не «в потолок» | обычно не является лимитом; проверить CPU flags |
| Фрагментация/MTU | потери, «залипания» крупных потоков | корректный MTU/MSS, PMTUD |
| TUN (userspace) | один поток `RoutineReadFromTUN` в профиле | multi-queue TUN, UDP GSO/GRO |
| TCP-in-UDP на потерях | резкое падение при cfg-loss | qdisc (fq/fq_codel), congestion control |

## Предварительные требования

Инструменты для замеров и диагностики:

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y iperf3 ethtool iproute2 sysstat linux-tools-common \
  conntrack-tools numactl

# RHEL/CentOS/Rocky 8+
sudo dnf install -y iperf3 ethtool iproute sysstat perf conntrack-tools numactl

# Проверка
iperf3 --version        # → iperf 3.x
ethtool --version       # → ethtool version 6.x
mpstat -V               # → sysstat 12.x
```

Замеры проводите на **боевом** MTU и размере пакета, с фиксированным состоянием сети (без посторонней нагрузки), иначе результат не воспроизводим.

## Практические сценарии

### 1. Методология замеров (iperf3)

Замерять **по трафику через туннель**, а не по скорости интерфейса; обязательно снимать baseline без VPN на том же стенде:

```bash
# На сервере (внутри VPN-подсети)
iperf3 -s

# На клиенте: пропустить первые секунды прогрева (-O), держать несколько потоков (-P)
iperf3 -c 10.0.0.1 -t 30 -O 5 -P 4
# → [ ID] Interval       Transfer     Bitrate         Retr
# → [  5]  0.00-30.00 sec  2.78 GBytes  796 Mbits/sec  12

# Baseline без VPN (наружу, до VPN-сервера) — тот же размер потока и число параллелей
iperf3 -c vpn.example.com -t 30 -O 5 -P 4
```

Сравнение «baseline без VPN» с «через туннель» показывает чистый overhead шифрования, инкапсуляции и уменьшенного MTU. Результат сильно зависит от числа потоков и размера блока (`-l`): один поток часто упирается в один CPU, а `-P` показывает агрегированную ёмкость. Подробнее про утилиту и интерпретацию артефактов: [iperf3](../Linux/Diagnostics/Networking/iperf3.md).

### 2. Проверка MTU и MSS Clamping

Самый частый симптом «медленного» WireGuard — фрагментация из-за неверного MTU. Сначала проверьте MTU/PMTUD (короткая справка — [Vpn/wireguard.md](./wireguard.md), глубже — [MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md) и [PMTUD / MTU Probing](../Linux/Networking/Concepts/tcp_tuning/tcp_pmtud_mtu_probing.md)):

```bash
# Определить рабочий MTU: от 1472 вниз, зонд без фрагментации
ping -M do -s 1472 -c 1 10.0.0.1
ping -M do -s 1400 -c 1 10.0.0.1
# → рабочий размер отвечает, больший — "Message too long" / тишина

# Установка MTU на интерфейсе
sudo ip link set wg0 mtu 1420

# MSS Clamping для TCP за туннелем (обязательно, если хосты не умеют PMTUD)
sudo ip6tables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN \
  -j TCPMSS --clamp-mss-to-pmtu
```

MTU `1420` — авто-значение `wg-quick` для пути 1500 при IPv4-транспорте (1500 − 80). Таблицу значений для PPPoE, IPsec и IPv6-транспорта см. в [Vpn/wireguard.md](./wireguard.md).

### 3. Параллелизм: threaded NAPI, IRQ affinity, RPS

Ядерный WireGuard на актуальных ядрах уже использует threaded NAPI и многоядерное шифрование, поэтому «разгон» сводится к равномерной обработке зашифрованного UDP на **физическом** интерфейсе.

```bash
# 1. Threaded NAPI для wg0.
#    На актуальных ядрах включён по умолчанию; на более старых — задать вручную:
for i in /sys/class/net/wg*/threaded; do echo 1 | sudo tee "$i"; done

# 2. Сколько очередей у физического NIC
ethtool -l eth0 | grep -i combined
# → Combined: 4

# 3. IRQ affinity очередей NIC (см. /proc/interrupts для имён eth0-rx-N)
grep eth0-rx /proc/interrupts
# 4. RPS на физическом интерфейсе: распределить обработку приёма по CPU
echo ffffffff | sudo tee /sys/class/net/eth0/queues/rx-0/rps_cpus
```

Полноценная настройка очередей, NUMA-привязки и RFS — [RSS, RPS, RFS, XPS](../Linux/Networking/Concepts/rss_rps_rfs.md); механизм threaded NAPI и бюджеты — [Оптимизация NAPI](../Linux/Networking/Concepts/napi_optimization.md). RSS применим только к многоочередным физическим картам; на виртуальном `wg0` его нет — там работает threaded NAPI и параллелизм самого драйвера.

### 4. Оффлоуды для WireGuard

```bash
# Физический интерфейс: убедиться, что GRO/GSO включены (обычно так и есть)
ethtool -k eth0 | grep -E 'generic-receive-offload|generic-segmentation-offload'
# → generic-receive-offload: on
# → generic-segmentation-offload: on

# Форвардинг (subnet router / exit node): разрешить UDP GRO для пересылаемых пакетов
sudo ethtool -K eth0 rx-udp-gro-forwarding on
```

Для **userspace**-реализации UDP GSO/GRO включается внутри wireguard-go автоматически, но требует ядра **6.2+** (иначе оффлоуд не задействуется). Общие принципы GRO/TSO/GSO, артефакты в `tcpdump` и постоянная конфигурация — [Сетевая разгрузка](../Linux/Networking/Concepts/offloading.md).

### 5. Диагностика загрузки: softirq, очереди, дропы

```bash
# Картина по ядрам: искать перекос — одно ядро почти целиком в %soft
mpstat -P ALL 1
# → CPU  %usr  %sys  %irq  %soft  %idle
# →   2  0.00 12.30  0.00  85.10   2.60   (перекос обработки на одном ядре)

# Отдельно поток ksoftirqd
top -H -b -n1 | grep -E 'ksoftirqd|PID'
# → PID USER  %CPU COMMAND   (высокий ksoftirqd/N — нехватка бюджета NAPI)

# Переполнение backlog и «сжатие» (squeezed) NAPI
nstat -az | grep -E 'TcpExt|Udp|IpExt|backlog|Drop'
# → UdpInErrors ... (растущий счётчик = переполнение буферов сокета)
cat /proc/net/softnet_stat   # 2-й столбец — dropped backlog, 3-й — squeezed

# Счётчики самого NIC (ring buffer, missed)
ethtool -S eth0 | grep -E 'rx_missed|rx_dropped|rx_errors'
```

Пакетные потери и их уровни (NIC → NAPI → backlog → сокет) разобраны в [Сетевые потери](../Linux/Networking/network_stack_packet_loss.md) и [nstat](../Linux/Diagnostics/Networking/nstat_diagnostics.md). Очереди qdisc и BQL на концентраторе снижают RTT и потери: [TCP Queueing Disciplines](../Linux/Networking/Concepts/tcp_tuning/tcp_queueing_disciplines.md), [TC Diagnostics](../Linux/Diagnostics/Networking/tc_diagnostics.md).

### 6. Сетевой sysctl-тюнинг концентратора

Для высоконагруженного шлюза (много пиров, высокий PPS) имеют смысл буферы UDP-сокетов, backlog и форвардинг. Меняйте осознанно — большая часть тюнинга WireGuard сводится к MTU/MSS и очередям, а не к «магическим» флагам:

```bash
# Буферы сокетов UDP (per-socket). На Linux 6.18+ rmem_max/wmem_max уже 4 МБ по умолчанию;
# на старых ядрах дефолт 212992 Б, и его имеет смысл поднять:
sudo sysctl -w net.core.rmem_max=4194304
sudo sysctl -w net.core.wmem_max=4194304
sudo sysctl -w net.core.rmem_default=262144
sudo sysctl -w net.core.wmem_default=262144

# Backlog очереди SoftIRQ (дефолт 1000; растёт при переполнении backlog)
sudo sysctl -w net.core.netdev_max_backlog=10000

# Форвардинг IPv4/IPv6
sudo sysctl -w net.ipv4.ip_forward=1
sudo sysctl -w net.ipv6.conf.all.forwarding=1
```

Сделать постоянными через `/etc/sysctl.d/99-wireguard.conf`. Подбор бюджета NAPI, `netdev_budget` и связанных параметров — [Оптимизация NAPI](../Linux/Networking/Concepts/napi_optimization.md).

### 7. Запуск userspace-реализации (когда ядерный модуль недоступен)

```bash
# На Linux wg-quick сначала пытается создать интерфейс ядерного типа.
# Переменная учитывается только в fallback (когда модуля нет):
export WG_QUICK_USERSPACE_IMPLEMENTATION=wireguard-go
sudo wg-quick up wg0

# Проверка, что работает именно userspace (нет модуля wireguard.ko)
lsmod | grep wireguard || echo "kernel module not loaded"
```

Чтобы принудительно использовать userspace при наличии модуля — выгрузите его (`sudo modprobe -r wireguard`) и добавьте в blacklist. Перед принятием на продакшн измерьте разницу через iperf3: на старых ядрах (без TUN UDP GSO/GRO) userspace заметно дороже по CPU.

### 8. Имитация плохой сети: `tc netem` для проверки VPN

Перед продвижением клиента в «нестабильный» офис полезно загнать туннель в условия задержек и потерь локально (проверка тюнинга TCP/MTU):

```bash
# На сервере: 30 мс задержки + 0.5% потерь на eth0 (входящий путь)
sudo tc qdisc add dev eth0 root netem delay 30ms loss 0.5%

# Через туннель: сравнить throughput (при потерях падение сверхлинейное)
iperf3 -c 10.0.0.1 -t 30
# → при 0.5% потерь TCP-поток в туннеле просядет сильнее, чем без туннеля

# Убрать эмуляцию (обязательно после теста)
sudo tc qdisc del dev eth0 root
```

Синтаксис `netem` и комбинации с `tbf`/`htb` — [tc netem — эмуляция сети](../Linux/Networking/Tools/iproute2/tc_netem.md). Тест полезен и для проверки поведения RTT-чувствительного трафика в туннеле, что пригодится при диагностике HA ([wireguard-ha.md](./wireguard-ha.md)).

## Типичные ошибки и диагностика

| Симптом | Вероятная причина | Проверка / решение |
|---------|-------------------|--------------------|
| Скорость как у 100 Мбит, но NIC гигабитный | перекос softirq/IRQ на одном ядре | `mpstat -P ALL 1`; IRQ affinity, RPS, threaded NAPI |
| Большие потоки «залипают», мелкие идут | фрагментация из-за MTU | `ping -M do -s`, MSS Clamping, снизить MTU |
| Потери растут при всплесках | переполнение backlog/буферов | `softnet_stat`, `nstat`; поднять `netdev_max_backlog`, буферы |
| Скорость падает на потерях сильнее, чем ждёте | TCP-in-UDP + плохой qdisc | qdisc `fq_codel`/`fq`, congestion control (BBR) |
| userspace-реализация медленнее ядра | нет TUN UDP GSO/GRO (ядро < 6.2) | вернуться на ядерный модуль либо обновить ядро |
| Один клиент не разгоняется на многих ядрах | per-peer сериализация | это нормально; помогает MTU/оффлоуды, а не число ядер |

## Лучшие практики

- **Сначала MTU/MSS, потом всё остальное.** Неверный MTU имитирует «медленный VPN» и не лечится sysctl.
- **Замеряйте baseline и через туннель на одном стенде**, с одинаковыми `-P`/`-l`/`-O`; иначе выводы недостоверны.
- **Для концентратора** держите ядерный модуль, следите за перекосом softirq и своевременно обновляйте ядро — оно приносит threaded NAPI и UDP GSO.
- **Форвардинг** — включайте `rx-udp-gro-forwarding` на принимающем интерфейсе.
- **Не «крутите всё подряд»**: большинство ядерных параметров даёт эффект только при подтверждённом соответствующем узком месте (см. §5).
- **Планируйте CPU-бюджет**: шифрование и обработка UDP стоят CPU; при высокой нагрузке отделяйте сетевую обработку от приложений (IRQ affinity, изоляция ядер).

## Граничные случаи и ограничения

- **Один пир — не масштабируется по ядрам на передаче.** Per-peer сериализация — свойство протокола, а не дефект настройки.
- **Userspace требует свежего ядра для скорости.** Без TUN UDP GSO/GRO (ядро < 6.2) wireguard-go проигрывает ядерному модулю.
- **Контейнеры и cgroups.** Число воркеров и доступные CPU могут различаться; учитывайте `GOMAXPROCS` и CPU-лимиты контейнера.
- **Older kernels.** Параметры `rmem_max`/`wmem_max`, threaded NAPI и UDP GSO зависят от версии ядра; проверяйте фактическое состояние (`sysctl`, `/sys/class/net/.../threaded`).
- **Виртуализация.** В ВМ с `virtio-net` оффлоуды эмулируются и не дают линейной скорости; разгрузку даёт SR-IOV ([Сетевая разгрузка](../Linux/Networking/Concepts/offloading.md)).
- **Измерения на localhost.** Тесты «контейнер к контейнеру» на одной машине показывают нереалистично высокие числа (нет реального NIC и провода) — не переносите их на прод.

## Дополнительная информация

- **[Vpn/wireguard.md](./wireguard.md)** — MTU-таблица, MSS Clamping, мониторинг через `wg show`
- **[WireGuard: защита концентратора](./wireguard-security.md)** — anti-DDoS, hardening, связь с производительностью под флудом
- **[WireGuard: резервирование (HA)](./wireguard-ha.md)** — отказоустойчивость концентратора
- **[MTU и VPN](../Networking/OSI_TCP_IP_Model/Network_layer/mtu_and_vpn.md)** — расчёт overhead всех стеков
- **[PMTUD / MTU Probing](../Linux/Networking/Concepts/tcp_tuning/tcp_pmtud_mtu_probing.md)** — MSS Clamping и probing
- **[iperf3](../Linux/Diagnostics/Networking/iperf3.md)** — замер пропускной способности и задержки
- **[RSS/RPS/RFS/XPS](../Linux/Networking/Concepts/rss_rps_rfs.md)** — распределение обработки пакетов между CPU
- **[Оптимизация NAPI и netdev_budget](../Linux/Networking/Concepts/napi_optimization.md)** — threaded NAPI, бюджеты, softirq
- **[Сетевая разгрузка: GRO, TSO, GSO](../Linux/Networking/Concepts/offloading.md)** — оффлоуды и их влияние
- **[Сетевые потери и стек ядра](../Linux/Networking/network_stack_packet_loss.md)** — уровни drops (NIC → NAPI → backlog → сокет)
- **[TCP Queueing Disciplines](../Linux/Networking/Concepts/tcp_tuning/tcp_queueing_disciplines.md)** — qdisc и BQL на концентраторе
- **[Алгоритмы управления перегрузкой TCP](../Linux/Networking/Concepts/tcp_tuning/tcp_congestion_algorithms.md)** — cubic/BBR для трафика в туннеле
- **[tc netem — эмуляция сети](../Linux/Networking/Tools/iproute2/tc_netem.md)** — задержки и потери для тестов VPN
