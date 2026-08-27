## Определения

- **NetFlow (Сетевой поток)**: Протокол, разработанный компанией Cisco для сбора, учета и экспорта информации об IP-трафике. Он позволяет агрегировать пакеты в логические потоки и передавать статистику на центральный коллектор для анализа производительности и безопасности.
- **Flow (Поток)**: Однонаправленная последовательность пакетов, имеющих общие атрибуты (**5-tuple**): IP-адреса источника и назначения, порты источника и назначения (L4), а также тип протокола. Пакеты, не соответствующие ни одному существующему потоку, создают новый; пакеты, попадающие в существующий поток, обновляют его счетчики.
- **Flexible NetFlow (FnF)**: Современная реализация NetFlow (начиная с v9), позволяющая пользователю самому определять, какие поля пакета должны отслеживаться (например, заголовки L2, метки MPLS, поля IPv6) и какие данные собираться.
- **IPFIX (IP Flow Information Export)**: Стандарт IETF (RFC 7011), основанный на NetFlow v9. Является расширяемым протоколом (иногда называемым NetFlow v10), позволяющим передавать произвольные метаданные, включая кастомные поля вендоров.
- **Flow Template (Шаблон)**: Метаданные, описывающие структуру экспортируемых полей. Устройство периодически отправляет шаблон коллектору, чтобы тот знал, как декодировать потоковые данные. Шаблоны themselves are not flow data — они обновляются при изменении Record.
- **Flow Exporter (Экспортер)**: Логический компонент устройства, отвечающий за формирование и отправку UDP-дейтаграмм с потоковыми данными на адрес коллектора.
- **Flow Collector (Коллектор)**: Сервер или сервис, принимающий данные от экспортеров, декодирующий шаблоны, агрегирующий потоки и предоставляющий интерфейс для анализа (CLI, API, UI).
- **nfdump**: Стандартная open-source утилита командной строки для чтения, фильтрации и агрегации файлов формата nfcapd. Используется как движок анализа в nfsen.
- **nfsen**: Web-интерфейс и фреймворк для визуализации NetFlow-данных, построенный поверх nfdump и RRDTOOL.

> NetFlow предоставляет данные для аналитики и мониторинга, которые используются приложениями в **[архитектуре SDN](./sdn_overview.md)** для принятия решений о маршрутизации и безопасности.

---

## Основные концепции

### Архитектура Flexible NetFlow (FnF)

В современных сетях настройка NetFlow строится на трех компонентах:
1.  **Flow Record (Запись)**: Определяет "что" мы отслеживаем. Состоит из ключевых полей (Keys, например, IP-адреса) для идентификации потока и неключевых полей (Collects, например, счетчики), которые экспортируются. В Cisco IOS/XE ключевые поля определяются командой `match ...`, а собираемые — командой `collect ...`.
2.  **Flow Exporter (Экспортер)**: Определяет "куда" и "как" отправлять данные. Содержит адрес коллектора, порт (обычно UDP 2055/4739), версию протокола и таймеры.
3.  **Flow Monitor (Монитор)**: Связующее звено, которое объединяет Record и Exporter и применяется к интерфейсу. Один Monitor может использоваться несколькими интерфейсами.

### Принцип работы и таймеры

- **Flow Cache**: Таблица в памяти устройства (CAM/TCAM или software hash table), где хранятся активные потоки. При входе нового пакета устройство вычисляет хэш от 5-tuple (в Cisco используется XOR-алгоритм по полям 5-tuple) и выполняет lookup. Если поток найден — обновляются счетчики (bytes, packets). Если не найден — создается новая запись.
- **Active Timeout**: Время (по умолчанию 30 мин), по истечении которого долгоживущий поток принудительно экспортируется, чтобы статистика не "зависала". После экспорта запись сбрасывается, но поток продолжает отслеживаться.
- **Inactive Timeout**: Время неактивности (по умолчанию 15-30 сек), после которого поток считается завершенным и удаляется из кэша.
- **Flow Packet Export (template timeout)**: Шаблоны переотправляются каждые 5 минут (по умолчанию) для поддержания актуальности на стороне коллектора.

**Почему именно такие таймеры:**
- Active timeout предотвращает потерю данных о долгоживущих TCP-сессиях (backup-каналы, VPN-туннели, большие файловые передачи).
- Inactive timeout позволяет быстро освобождать слоты Flow Cache для коротких сессий (DNS-запросы, HTTP-заголовки).

### Заголовки версий NetFlow

**NetFlow v5** — фиксированный заголовок (24 байта) + фиксированный набор полей (48 байт на запись):
| Поле | Описание |
| :--- | :--- |
| srcaddr, dstaddr | IP-адреса источника и назначения (32 бит) |
| nexthop | IP-адрес следующего хопа |
| input, output | SNMP-индексы входящего и исходящего интерфейсов |
| dPkts, dOctets | Количество пакетов и байтов в потоке |
| first, last | Время первого и последнего пакета (в субсекундах) |
| srcport, dstport | TCP/UDP порты источника и назначения |
| pad1, tcp_flags, prot, tos, pad2 | Зарезервированные/служебные поля |

Ограничение: только IPv4, максимум 30 записей в UDP-пакете.

**NetFlow v9 / IPFIX** — шаблонная модель:
- Заголовок содержит `FlowSet ID`: числа 0–3 reserved (0 = template, 1 = options template), 256+ = данные.
- Шаблоны задаются набором `{Information Element ID, Length}` — например, `IE 8 = srcIPv4 (4 байта)`, `IE 12 = dstIPv4 (4 байта)`.
- IPFIX добавляет Enterprise-specific IE (например,Cisco NBAR2 Application ID = 95, Palo Alto App-ID = 8043).
- Максимум 20 записей в одном UDP-пакете (для v5), но шаблонная модель позволяет отправлять переменное количество.

### Сравнение протоколов мониторинга потоков

| Протокол | Модель | Тип агрегации | Транспорт | Рекомендация 2026 |
| :--- | :--- | :--- | :--- | :--- |
| **NetFlow v5** | Фиксированная | На устройстве | UDP 2055 | Не использовать (legacy). |
| **NetFlow v9** | Шаблонная | На устройстве | UDP 2055 | Для сетей на базе Cisco. |
| **IPFIX (v10)** | Шаблонная | На устройстве | UDP/TCP/SCTP 4739 | **Стандарт для мультибрендовых сетей.** |
| **sFlow** | Сэмплирование | Без агрегации | UDP 6343 | Для L2-коммутации и высоконагруженных каналов. |

**Ключевое отличие sFlow от NetFlow/IPFIX:**
- sFlow работает на уровне сэмплирования (по умолчанию 1 из 1000 пакетов), экспортируя полный заголовок пакета (L2-L4) без агрегации. Это делает его незаменимым для выявления L2-инцидентов (broadcast storms, MAC flooding), но непригодным для точного подсчета трафика.
- NetFlow/IPFIX агрегирует пакеты в потоки на устройстве, значительно снижая объем экспортируемых данных (в сотни раз по сравнению с sFlow), но теряя детализацию отдельных пакетов.

**Поддержка вендорами (актуально на 2026):**
| Вендор | NetFlow v5 | NetFlow v9 | IPFIX | sFlow | Примечания |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cisco IOS/IOS-XE** | Да | Да | Да | Да | Flexible NetFlow (FnF) — основной механизм. |
| **Cisco NX-OS** | Да | Да | Да | Да | Поддержка IPFIX для数据中心 (Nexus 9000). |
| **Juniper Junos** | Да | Да | Да | Да | term-based flow-monitoring, JTAS для IPFIX. |
| **Arista EOS** | Да | Да | Да | Да | Advanced EOS Agent для IPFIX/sFlow. |
| **Palo Alto PAN-OS** | Нет | Нет | Да | Нет | App-ID через IPFIX, Packet Buffer Recording. |
| **VyOS/Quagga/FRR** | Да | Да | Да | Да | Реализация на базе netflow с kernel. |

---

## Практические сценарии

### Сценарий 1: Настройка Flexible NetFlow (Cisco IOS-XE)

```cisco
! 1. Создание записи (Record)
flow record CUSTOM-NETFLOW
 match ipv4 source address
 match ipv4 destination address
 match ipv4 protocol
 match transport source-port
 match transport destination-port
 match interface input
 match interface output
 collect counter bytes long
 collect counter packets long
 collect counter flows
 collect timestamp sys-uptime first
 collect timestamp sys-uptime last
 collect transport tcp flags

! 2. Создание экспортера (Exporter)
flow exporter TO-COLLECTOR
 destination 10.1.1.100
 source Loopback0
 transport udp 2055
 export-protocol netflow-v9
 template data timeout 60
 option application-table timeout 300

! 3. Создание и применение монитора
flow monitor MY-MONITOR
 record CUSTOM-NETFLOW
 exporter TO-COLLECTOR
 cache timeout active 600
 cache timeout inactive 15
 cache entries 1000000

interface GigabitEthernet0/1
 ip flow monitor MY-MONITOR ingress
 ip flow monitor MY-MONITOR egress
```

**Ключевые параметры:**
- `cache entries 1000000` — размер Flow Cache. Для загруженных маршрутизаторов (10G+ ссылки) рекомендуется не менее 500K–1M записей. При нехватке памяти старые потоки могут вытесняться.
- `template data timeout 60` — переотправка шаблона каждые 60 секунд. Критично для коллекторов, которые теряют первые UDP-пакеты.
- `cache timeout active 600` — экспорт долгоживущих потоков каждые 10 минут (вместо 30 по умолчанию).
- `option application-table timeout 300` — опционально: экспорт таблицы NBAR2 Application ID (требует лицензии).

### Сценарий 2: Настройка NetFlow на Juniper Junos

```junos
! 1. Определение flow monitor
set services flow-monitoring NETFLOW-MONITOR template template-name V9-TPL
set services flow-monitoring NETFLOW-MONITOR template template-name template-options inactive-timeout 15
set services flow-monitoring NETFLOW-MONITOR template template-name template-options active-timeout 300
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template match source-address
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template match destination-address
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template match protocol
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template match source-port
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template match destination-port
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template match input-interface
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template match output-interface
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template collect bytes
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template collect packets
set services flow-monitoring NETFLOW-MONITOR template template-name ipv4-template collect tcp-flags

! 2. Определение collector и exporter
set services flow-monitoring NETFLOW-MONITOR collector COLLECTOR-1
set services flow-monitoring NETFLOW-MONITOR collector COLLECTOR-1 address 10.1.1.100
set services flow-monitoring NETFLOW-MONITOR collector COLLECTOR-1 port 2055
set services flow-monitoring NETFLOW-MONITOR exporter EXPORTER-1
set services flow-monitoring NETFLOW-MONITOR exporter EXPORTER-1 collector COLLECTOR-1
set services flow-monitoring NETFLOW-MONITOR exporter EXPORTER-1 source-address 10.0.0.1

! 3. Применение к интерфейсу
set interfaces ge-0/0/0 unit 0 family inet input-virtual-reassembly
set interfaces ge-0/0/0 unit 0 family inet sampling input
```

**Примечание:** На Juniper NetFlow включается через `set forwarding-options sampling` для sampler-based flow monitoring или через `services flow-monitoring` для packet-based. Sampler-based режим рекомендуется для высоконагруженных интерфейсов (10G+) для снижения нагрузки на CPU.

### Сценарий 3: Установка колLECTОРА (nfdump + nfsen на Linux)

**Предпосылки:**
- Ubuntu 22.04+ / Debian 12+
- Порты UDP 2055 (прием данных) и TCP 80/443 (web-интерфейс nfsen)
- Достаточный объем диска: ~1 ГБ/день для 10Gbps сэмплированного трафика (1:100)

```bash
# 1. Установка nfdump из исходников
sudo apt update && sudo apt install -y build-essential flex bison librrd-dev librrd8 \
    libpng-dev libbz2-dev zlib1g-dev libbz2-dev apache2 libapache2-mod-php8.1 php8.1-gd

# Клонирование и сборка nfdump (latest stable)
cd /tmp
git clone https://github.com/phaag/nfdump.git
cd nfdump
autoreconf -i
./configure --enable-sflow --enable-nfprofile --enable-nfsen
make -j$(nproc)
sudo make install
```

**Проверка установки:**
```bash
# Проверка версии
nfdump -V
# → nfdump version 1.7.x

# Проверка демона nfcapd
nfcapd -V
# → nfcapd version 1.7.x
```

**Запуск nfcapd (прием данных):**
```bash
# Запуск в фоновом режиме
nfcapd -w -D -p 2055 -l /var/nfdump/flows -S 1 -T all -t 300

# Параметры:
# -w  — запись данных
# -D  — демонизация (фоновый режим)
# -p 2055 — порт прослушивания
# -l /var/nfdump/flows — директория для хранения файлов nfcapd.*
# -S 1 — интервал rotates (секунды)
# -T all — принимать все версии NetFlow (v5, v9, IPFIX)
# -t 300 — таймаут неактивности потока (секунды)
```

**Анализ данных через nfdump:**
```bash
# Базовый анализ: топ-10 источников по объему трафика за период
nfdump -r /var/nfdump/flows/nfcapd.202608251200 -t 2026/08/25.12:00:00-2026/08/25.12:05:00 \
       -s srcip -c 10

# → IP ADDRESSES        FLOWS   PACKETS   BYTES     PACKETS/FLOW  BYTES/FLOW
# → 10.1.1.50              123    45000    67500000  366           548780
# → 10.1.1.51               89    23000    34500000  258           387640
# → ...

# Фильтрация по протоколу и порту: поиск SSH-сессий
nfdump -r /var/nfdump/flows/nfcapd.202608251200 -t 2026/08/25.12:00:00-2026/08/25.12:05:00 \
       -P -nn 'proto tcp and dst port 22'

# → Get flows from file
# → flows processed: 12345, flows selected: 234
# → ...

# Агрегация по протоколам: распределение трафика
nfdump -r /var/nfdump/flows/nfcapd.202608251200 -t 2026/08/25.12:00:00-2026/08/25.12:05:00 \
       -s proto -a

# → PROTOCOL     FLOWS   PACKETS   BYTES     PACKETS/FLOW  BYTES/FLOW
# → TCP (6)         890    456000   680000000  512           764044
# → UDP (17)        210     34000    51000000  162           242857
# → ICMP (1)         45      1200      120000   27            2666
```

**Настройка systemd-сервиса для nfcapd:**
```ini
# /etc/systemd/system/nfcapd.service
[Unit]
Description=NetFlow Capture Daemon
After=network.target

[Service]
Type=forking
ExecStart=/usr/local/bin/nfcapd -w -D -p 2055 -l /var/nfdump/flows -S 1 -T all -t 300 -I router1
PIDFile=/var/run/nfcapd/nfcapd.pid
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Активация и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now nfcapd
sudo systemctl status nfcapd
# → Active: active (running)
```

### Сценарий 4: Настройка IPFIX на Palo Alto PAN-OS

На Palo Alto IPFIX работает через **Packet Buffer Recording** и **Application-ID export**:

1. **В web-интерфейсе:** Device > Setup > Services > NetFlow
2. **Настройка Collector:**
   - Name: `COLLECTOR-1`
   - Server IP: `10.1.1.100`
   - Port: `2055`
   - Protocol: `UDP`
3. **Привязка к Security Profile:**
   - Policies > Security > [Rule] > Actions > Log at Session End → включить
   - Device > Log Settings > NetFlow → привязать Collector
4. **Включение Packet Buffer Recording (опционально, для глубокого анализа):**
   - Device > Setup > Management > Packet Buffer Recording → Enable

**Примечание:** Palo Alto экспортирует Application-ID (App-ID) через IE 8043 в IPFIX. Коллектор должен поддерживать декодирование этого IE для отображения имен приложений (web-browsing, ssl, dns, ssh и т.д.).

### Сценарий 5: Безопасность — поиск Lateral Movement

Сетевые потоки — основной инструмент для обнаружения перемещения злоумышленника внутри сети.

**Признаки (Indicators of Compromise):**
1. **Аномальный объем**: Внезапная передача большого объема данных между двумя рабочими станциями (не серверами).
2. **Сканирование портов**: Один источник открывает множество кратковременных сессий на разные IP по порту 445 (SMB) или 22 (SSH).
3. **Horizontal movement**: Множество unsuccessful TCP-сессий (flag `SYN` без `SYN-ACK`) к разным хостам на один порт — признак портирования.
4. **DNS-туннелирование**: Аномально длинные DNS-запросы ( TXT-записи >200 байт) или высокий volume DNS-трафика от одного хоста.
5. **Data exfiltration**: Резкий рост исходящего трафика в нерабочее время на внешние IP.

**Примеры nfdump-запросов для обнаружения:**
```bash
# 1. Поиск хостов, обращающихся к более чем 50 уникальным IP за 5 минут
nfdump -r /var/nfdump/flows/nfcapd.202608251200 -t 2026/08/25.12:00:00-2026/08/25.12:05:00 \
       -s srcip -O tflows -c 50

# → Описание: Показывает source IP с количеством уникальных destination IP.
# → Если один IP обращается к >50 уникальным — признак сканирования или lateral movement.

# 2. Поиск неуспешных TCP-подключений (SYN без ответа)
nfdump -r /var/nfdump/flows/nfcapd.202608251200 -t 2026/08/25.12:00:00-2026/08/25.12:05:00 \
       -P 'proto tcp and (flags & 0x02) != 0 and (flags & 0x12) == 0x02'

# → Описание: Фильтр по TCP flags — SYN установлен (0x02), но SYN-ACK (0x12) отсутствует.
# → Указывает на сканирование (port scanning) или заблокированные попытки подключения.

# 3. Поиск аномально больших потоков (возможная exfiltration)
nfdump -r /var/nfdump/flows/nfcapd.202608251200 -t 2026/08/25.00:00:00-2026/08/25.23:59:59 \
       -s dstip -O bytes -c 20

# → Описание: Топ-20 destination IP по объему принятых данных за сутки.
# → Если один внешний IP получил >10 ГБ — подозрительно для non-backup traffic.

# 4. Поиск DNS-туннелирования
nfdump -r /var/nfdump/flows/nfcapd.202608251200 -t 2026/08/25.12:00:00-2026/08/25.12:05:00 \
       'proto udp and dst port 53 and bytes > 200'

# → Описание: DNS-запросы с payload >200 байт — подозрительно на DNS-туннель.
```

**Рекомендуемые пороги алертов (пример):**
| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| Уникальные dst IP от одного src за 5 минут | >50 | Investigation |
| SYN без SYN-ACK к разным портам за 1 минуту | >100 | Alert + Block IP |
| Исходящий трафик на внешний IP за ночь | >5 ГБ | Investigation |
| DNS-запросы >200 байт от одного хоста за час | >10 | Investigation |

---

## Диагностика и устранение неполадок

### Частые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Потеря пакетов на коллекторе** | UDP не гарантирует доставку; переполнение буфера接收а | Увеличить `net.core.rmem_max` (Linux); настроить `flow exporter` с `transport udp` и мониторить `show flow exporter statistics` (Cisco). |
| **Template mismatch** | Коллектор не получил актуальный шаблон | Уменьшить `template data timeout` (например, 60 сек); проверить `show flow exporter templates` (Cisco). |
| **Flow Cache exhaustion** | Недостаточный размер кэша для числа активных потоков | Увеличить `cache entries` (до лимита платформы); увеличить `active timeout` для ускорения освобождения слотов. |
| **Нет данных от устройства** | Interfейс не привязан к Flow Monitor | Проверить `show flow monitor MY-MONITOR cache format table`; проверить `ip flow monitor ... ingress/egress` на интерфейсах. |
| **Дублирование потоков** | Ingress и egress мониторинг на одном интерфейсе | Использовать `sampler` на ingress для снижения нагрузки; либо включать только ingress (для простого анализа трафика). |

### Команды верификации (Cisco IOS-XE)

```bash
# 1. Проверка, что Flow Monitor применяется к интерфейсу
show running interface GigabitEthernet0/1 | include flow
# → ip flow monitor MY-MONITOR ingress

# 2. Просмотр текущего содержимого Flow Cache
show flow monitor MY-MONITOR cache format table
# → Содержит: Protocol, Src IP, Dst IP, Src Port, Dst Port, Packets, Bytes, etc.

# 3. Статистика экспорта (проверка отправки)
show flow exporter TO-COLLECTOR statistics
# → Sent: 12345 records, Failed: 0, Dropped: 0

# 4. Просмотр активных шаблонов
show flow exporter TO-COLLECTOR templates
# → Template ID: 256, Fields: 12, Last sent: 30 seconds ago

# 5. Проверка размера Flow Cache и использования
show flow monitor MY-MONITOR cache
# → Cache contains 450000 active flows (45% of 1000000 entries)

# 6. Очистка Flow Cache (остановит запись новых потоков на несколько секунд!)
clear flow monitor MY-MONITOR cache
# → WARNING: This will disrupt flow monitoring. Use with caution.
```

### Диагностические команды (Linux / nfdump)

```bash
# Проверка, что nfcapd слушает UDP 2055
sudo ss -ulnp | grep 2055
# → UNCONN  0  0  0.0.0.0:2055  0.0.0.0:*  users:(("nfcapd",pid=1234,fd=5))

# Проверка наличия данных в файлах
ls -lh /var/nfdump/flows/
# → nfcapd.202608251200  15M
# → nfcapd.202608251205  12M

# Просмотр ошибок nfcapd
journalctl -u nfcapd --since "1 hour ago"
# → nfcapd: Max flow entries exceeded, dropping new flows
```

---

## Современный ландшафт (2025–2026)

### Наблюдаемость в Cloud Native (eBPF и Hubble)

В Kubernetes-средах классический NetFlow заменяется или дополняется инструментами на базе **eBPF** (например, **Cilium Hubble**).
- **Контекст**: В отличие от обычного NetFlow, Hubble видит не только IP-адреса, но и метаданные K8s (Namespace, Pod, Label).
- **Видимость L7**: Возможность отслеживать HTTP-заголовки, gRPC-методы и задержки API на уровне потоков.

> Hubble работает на уровне ядра (eBPF), что обеспечивает нулевую задержку и минимальный overhead. См. подробности в **[Cilium: Hubble](../../../Kubernetes/Networking/Network/CNI/cilium.md#наблюдаемость-hubble-и-timescape)**.

### Интеграция с OpenTelemetry (OTel)

Современные коллекторы (например, **OTel Collector**) поддерживают ресиверы для IPFIX и NetFlow. Это позволяет объединять сетевые потоки с трассировками приложений в единой системе (Grafana, Honeycomb).

**Пример конфигурации OTel Collector для приема NetFlow:**
```yaml
# otel-collector-config.yaml
receivers:
  netflow:
    protocol: netflow
    port: 2055
    template_cache_timeout: 5m
  ipfix:
    protocol: ipfix
    port: 4739

processors:
  batch:
    timeout: 10s
    send_batch_size: 10000

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
  clickhouse:
    endpoint: "clickhouse-cluster:9000"
    database: "network_flows"
    logs_table_name: "netflow_raw"

service:
  pipelines:
    netflow:
      receivers: [netflow, ipfix]
      processors: [batch]
      exporters: [prometheus, clickhouse]
```

### Streaming Telemetry

Постепенный переход от модели "Push по таймеру" к потоковой телеметрии (gNMI/gRPC), где данные об интерфейсах и трафике передаются в реальном времени с околонулевой задержкой.

**Сравнение моделей:**
| Характеристика | NetFlow/IPFIX (Push) | gNMI Streaming |
| :--- | :--- | :--- |
| Частота обновлений | По таймеру (5-300 сек) | В реальном времени (мс) |
| Протокол транспорта | UDP (lossy) | gRPC (TCP-based, reliable) |
| Формат данных | Бинарный (TLV) | Protobuf/YANG |
| Использование | Анализ трафика, billed traffic | Конфигурация,监控 интерфейсов |

### VPC Flow Logs (Cloud Providers)

В облачных средах классический NetFlow дополняется **VPC Flow Logs** — средством мониторинга трафика на уровне виртуальной сети.

| Провайдер | Механизм | Протокол экспорта | Особенности |
| :--- | :--- | :--- | :--- |
| **AWS** | VPC Flow Logs | S3 / CloudWatch Logs / Kinesis Firehose | Aggregation interval 1-10 минут; поддержка IPFIX в Transit Gateway. |
| **Azure** | NSG Flow Logs | Storage Account / Event Hub / Log Analytics | Version 2 ( richer fields); интеграция с Traffic Analytics. |
| **GCP** | VPC Flow Logs | Cloud Logging / Pub/Sub | Включается per-subnet; автоматическое включение для GKE. |

> VPC Flow Logs — это облачный аналог NetFlow, адаптированный для виртуальных сетей. См. также **[Cloud Networking](../cloud_networking.md)**.

### Packetbeat (ELK Stack)

Для централизованного анализа NetFlow-данных в экосистеме Elastic Stack используется **Packetbeat** — lightweight агент, агрегирующий сетевые соединения в формате "Flows":

```yaml
# packetbeat.yml
packetbeat.flows:
  enabled: true
  timeout: 30s
  period: 10s

packetbeat.protocols:
  - type: dns
    ports: [53]
    include_authorities: true
    include_additionals: true
  - type: http
    ports: [80, 8080, 8000]
    send_headers: true
  - type: tls
    ports: [443, 8443]
```

Packetbeat агрегирует TCP/UDP-соединения и экспортирует их в Elasticsearch. Это lightweight-альтернатива полному NetFlow-коллектору для небольших сред.

> Подробнее: **[Packetbeat Flows](../../../ELK_Stack/Elasticsearch/beats_family.md#flows-netflow-like)**.

---

## Дополнительная информация

- **Sampling (Сэмплирование)**: На каналах 100G+ часто используется `sampled netflow` (например, 1 пакет из 1000), чтобы не перегружать CPU маршрутизатора. Пример на Cisco: `ip flow monitor MY-MONITOR sampler MY-SAMPLER ingress`, где `flow sampler MY-SAMPLER mode random one-out-of 1000`. **Trade-off:** Сэмплирование снижает точность подсчета (особенно для коротких потоков), но критически важно для масштабируемых сетей. Для биллинга (billing) рекомендуется использовать полный сбор (no sampling).
- **NetFlow Lite**: Упрощенная версия для доступа (Access layer), часто реализованная программно. Поддерживает только базовые поля (5-tuple + counters), но работает без аппаратной поддержки.
- **Memory considerations**: Flow Cache размером 1M записей ≈ 200-400 МБ памяти (в зависимости от платформы). При нехватке памяти на маршрутизаторе страдает forwarding plane — критический риск. Всегда проверяйте ограничения платформы перед увеличением `cache entries`.
- **UDP Reliability**: NetFlow/IPFIX по умолчанию использует UDP, что означает потерю данных при переполнении буфера приема или сетевых проблемах. Для критичных сценариев (биллинг, compliance) рассмотрите IPFIX over TCP или SCTP (поддерживается в IPFIX, не в NetFlow v9).

### Tcpdump в overlay сетях (VXLAN/Geneve)

В overlay сетях (VXLAN, Geneve) важно уметь ловить пакеты как на уровне underlay (инкапсулированные), так и на уровне overlay (деинкапсулированные).

```bash
# 1. Tcpdump на underlay (ловим инкапсулированные VXLAN пакеты)
# Порт VXLAN: 4789, Geneve: 6081
sudo tcpdump -i eth0 -nn port 4789
# → 10:30:01.123456 IP 10.0.0.1.12345 > 10.0.0.2.4789: UDP, length 1450
# →   VXLAN vni=100
# →   IP 10.0.1.10.80 > 10.0.2.20.45678: Flags [S.], ...

# 2. Tcpdump на overlay интерфейсе (деинкапсулированные пакеты)
# Для OVS/OVN:
sudo tcpdump -i br-int -nn
# → 10:30:01.123456 IP 10.0.1.10.80 > 10.0.2.20.45678: Flags [S.], ...

# 3. Tcpdump на поде (Kubernetes)
kubectl exec -it <pod> -- tcpdump -i eth0 -nn
# → 10:30:01.123456 IP 10.0.2.20.45678 > 10.0.1.10.80: Flags [S], ...

# 4. Tcpdump с фильтрацией по VXLAN VNI
sudo tcpdump -i eth0 -nn port 4789 -v
# → IP 10.0.0.1.12345 > 10.0.0.2.4789: UDP, length 1450
# →   VXLAN vni=100                          ← VNI
# →   IP 10.0.1.10.80 > 10.0.2.20.45678: Flags [S.], ...

# 5. Tcpdump с фильтрацией по IP в overlay
sudo tcpdump -i eth0 -nn port 4789 and host 10.0.1.10
# → Только VXLAN пакеты от/к 10.0.1.10

# 6. Анализ VXLAN через Wireshark
# Фильтр: vxlan.vni == 100
# Или: udp.port == 4789 && vxlan.vni == 100
```**Связанные темы:**
- **[Архитектура SDN](./sdn_overview.md)** — контекст управления потоками в программируемых сетях.
- **[VXLAN/Geneve (Overlay Networks)](./vxlan_geneve.md)** — overlay troubleshooting и tcpdump.
- **[eBPF/XDP (Hubble)](./ebpf_xdp.md)** — eBPF-based flow monitoring (Cilium Hubble).
- **[Open vSwitch (OVS)](../../ServicesAndTools/open_vswitch.md)** — экспорт потоков из виртуальных коммутаторов (OVS поддерживает IPFIX natively через `ovs-vsctl set bridge br0 netflow=@nf`).
- **[ClickHouse для мониторинга](../../Databases/ClickHouse/clickhouse.md)** — идеальное хранилище для терабайтов NetFlow-логов (столбчатый формат, высокая скорость агрегации).
- **[OpenFlow](./openflow.md)** — управление потоками (в отличие от NetFlow, который их мониторит).
- **[Network Automation](./network_automation.md)** — автоматизация NetFlow настройки.
