# tcpdump — сетевой анализатор пакетов

## Определения

**`tcpdump`** — индустриальный стандарт консольных утилит для перехвата и анализа сетевого трафика. Работает на уровне ядра через библиотеку `libpcap`, захватывая «сырые» кадры непосредственно с сетевого интерфейса. Является незаменимым инструментом для отладки сетевых протоколов, анализа безопасности и траблшутинга распределенных систем.

## Основные концепции

### Принцип работы и фильтрация BPF

`tcpdump` использует механизм **BPF (Berkeley Packet Filter)**, который выполняет фильтрацию пакетов внутри ядра Linux. Это критически важно для производительности: в ядро передается только тот трафик, который соответствует фильтру, что предотвращает перегрузку CPU и потерю пакетов (drops) при интенсивном трафике. Современным развитием этой технологии является **[eBPF](../../Linux/Core/kernel/ebpf.md)**.

### Внутренняя архитектура и поток захвата

`tcpdump` работает через библиотеку `libpcap`, которая предоставляет унифицированный интерфейс к механизму захвата пакетов ядра:

1. **Открытие дескриптора:** `libpcap` открывает raw-сокет (`AF_PACKET`, `SOCK_RAW`) или использует кольцевой буфер ядра (`AF_PACKET`, `SOCK_DGRAM`) для получения кадров.
2. **Захват в userspace:** При получении пакета ядро копирует его в буфер пользовательского пространства. На высоконагруженных системах (>1M pps) используется **memory-mapped capture** (`mmap`), который позволяет `libpcap` читать пакеты напрямую из разделяемой памяти ядра, минуя системные вызовы `read()`.
3. **Применение BPF:** Перед копированием в userspace пакет проходит через BPF-фильтр. Только совпадающие пакеты копируются.
4. **Вывод и запись:** Утилита форматирует пакеты согласно запрошенным флагам (`-X`, `-A`, `-v`) и/или записывает в pcap-файл.

**Потенциальные точки потерь:**
- **Переполнение кольцевого буфера:** если `libpcap` не успевает обработать пакеты, ядро overwrite новые, и `tcpdump` теряет данные. Мониторинг: `ifconfig` или `ip -s link show` (счётчик `drop`).
- **Системный вызов `read()`:** на медленных дисках запись в файл может отставать от захвата.
- **DNS-резолв:** при отсутствии флага `-n` `tcpdump` вызывает `getnameinfo()` для каждого IP, что создает задержки и DNS-запросы, видимые в самом захвате.

### Потери пакетов и их диагностика

Потери (`drops`) являются главным ограничением `tcpdump` при диагностике высоконагруженных систем. Причины и методы диагностики:

| Причина | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Маленький буфер** | `ifconfig` показывает `RX dropped` | `ip -s link show` | Увеличить `-B 8192` или `-B 16384` |
| **Медленная запись** | Захват зависает, CPU низкий | `iostat -x 1` | Запись в tmpfs (`/dev/shm`) или удаленный сервер через SSH |
| **Слишком широкий фильтр** | Высокий CPU, потери при 100K+ pps | `top`/`htop` | Сузить BPF-фильтр; перейти на `tshark` или `dumpcap` |
| **Promiscuous mode + NIC offload** | Неожиданные `bad cksum` | `ethtool -k` | Включить `-p` или отключить offload |
| **Виртуальный интерфейс** | Потери на `veth`/`tap` | `tc -s qdisc show` | Проверить ограничения `tx_queue_len` |

**Мониторинг потерь в реальном времени:**
```bash
# Счётчик потерь на интерфейсе (watch)
watch -n 1 'ip -s link show eth0 | grep -A1 "RX:"'

# Счётчик потерь в libpcap (требует статистику)
tcpdump -i eth0 -w /dev/null -c 1000000 2>&1 | grep -i drop
```

### Ключевые параметры управления

- **Среда выполнения:** Требует прав `root` или привилегий `CAP_NET_RAW` и `CAP_NET_ADMIN`. В целях безопасности утилита может сбрасывать привилегии до непривилегированного пользователя (обычно `tcpdump` или `pcap`) после открытия дескриптора интерфейса.
- **Promiscuous mode:** По умолчанию `tcpdump` переводит интерфейс в "неразборчивый" режим, позволяя захватывать все пакеты, проходящие через сегмент сети, а не только адресованные данному хосту. Опция `-p` отключает это поведение.
- **Snaplen (`-s`):** Размер захватываемой части пакета. По умолчанию (`-s 0`) захватывается весь пакет. Для анализа только заголовков (экономия места) можно использовать `-s 64`. Для TLS-анализа часто требуется `-s 0` или `-s 4096`, так как Client Hello может быть фрагментирован.
- **Буферизация (`-B`):** Размер буфера захвата в КБ. Увеличение буфера (например, `-B 4096`) помогает избежать потерь пакетов при всплесках трафика. На системах с highpps рекомендуется `-B 16384`.
- **Интерфейс `any`:** Позволяет слушать все интерфейсы сразу. **Важно:** при этом используется "Linux cooked capture" (SLL), где оригинальный Ethernet-заголовок заменяется на служебный заголовок ядра, что скрывает реальные MAC-адреса.
- **Мониторинг потерь (`-b`):** В некоторых версиях `tcpdump` поддерживается опция `-b` для вывода статистики принятых/потерянных пакетов после завершения.

### TCP-флаги в выводе tcpdump

Утилита отображает состояние TCP-сессии через буквенные обозначения в квадратных скобках:

| Флаг | Обозначение | Значение | Описание |
| :--- | :--- | :--- | :--- |
| **SYN** | `[S]` | Synchronize | Начало установки соединения. |
| **SYN-ACK** | `[S.]` | SYN + ACK | Подтверждение запроса и встречное предложение. |
| **ACK** | `[.]` | Acknowledgment | Подтверждение получения данных (пустой ACK). |
| **PSH** | `[P]` | Push | Передача данных приложению без буферизации. |
| **FIN** | `[F]` | Finish | Корректное завершение соединения. |
| **RST** | `[R]` | Reset | Аварийный разрыв (порт закрыт или ошибка стека). |
| **URG** | `[U]` | Urgent | Срочные данные (встречается редко). |

## Практические сценарии

### Базовое управление и интерфейсы

```bash
# Список всех интерфейсов и их статуса
sudo tcpdump -D

# Захват на конкретном интерфейсе без DNS-резолва (рекомендуется для скорости)
sudo tcpdump -i eth0 -nn

# Захват ограниченного количества пакетов
sudo tcpdump -i eth0 -c 100
```

### Сохранение и ротация дампов (.pcap)

```bash
# Запись в файл для последующего анализа в Wireshark
sudo tcpdump -i eth0 -w capture.pcap

# Ротация файлов: сохранять по 100 МБ, оставить последние 10 файлов
sudo tcpdump -i eth0 -w traffic.pcap -C 100 -W 10

# Чтение из файла с применением фильтров
tcpdump -r capture.pcap -nn 'tcp port 443'
```

### Продвинутая фильтрация (BPF)

```bash
# По протоколу (IPv4/IPv6/UDP/ICMP)
sudo tcpdump -i eth0 ip6
sudo tcpdump -i eth0 icmp
sudo tcpdump -i eth0 udp

# По номеру протокола (например, GRE — 47, ESP — 50)
sudo tcpdump -i eth0 proto 47
sudo tcpdump -i eth0 proto 50

# По подсети
sudo tcpdump -i eth0 net 192.168.1.0/24

# Поиск конкретного флага (например, только RST)
sudo tcpdump -i eth0 'tcp[tcpflags] & tcp-rst != 0'

# Комплексный фильтр: трафик HTTPS, исключая конкретный хост
sudo tcpdump -i eth0 'tcp port 443 and not host 10.0.0.5'
```

### Диагностика L2 и VLAN

```bash
# Просмотр Ethernet-заголовков (MAC-адреса)
sudo tcpdump -i eth0 -e -nn

# Захват трафика конкретного VLAN
sudo tcpdump -i eth0 -e vlan 100

# Захват вложенных VLAN (QinQ)
sudo tcpdump -i eth0 -e vlan and vlan
```

### Анализ содержимого и TLS SNI

```bash
# Вывод данных в ASCII (поиск строк в HTTP/SMTP)
sudo tcpdump -i eth0 -A port 80

# Вывод в HEX + ASCII (удобно для бинарных протоколов)
sudo tcpdump -i eth0 -X port 53

# Поиск имени домена (SNI) в TLS Client Hello
sudo tcpdump -i eth0 -X 'tcp port 443' | grep -E "0x00[0-9a-f]{2}:"
```

### Работа с Sequence Numbers

По умолчанию `tcpdump` показывает относительные номера последовательности TCP. Для отладки проблем с конкретными сегментами могут потребоваться абсолютные значения:

```bash
# Использование абсолютных номеров последовательности
sudo tcpdump -i eth0 -S -nn
```

### Диагностика по протоколам

#### DNS (UDP/TCP 53)

```bash
# Захват всех DNS-запросов и ответов
sudo tcpdump -i eth0 -n port 53

# Только запросы (QR=0)
sudo tcpdump -i eth0 -n 'udp port 53 and udp[10] & 0x80 == 0'

# Только ответы (QR=1)
sudo tcpdump -i eth0 -n 'udp port 53 and udp[10] & 0x80 != 0'

# AXFR (полная зона, TCP 53)
sudo tcpdump -i eth0 -n tcp port 53

# Поиск конкретного домена в запросе (DNS over UDP)
sudo tcpdump -i eth0 -n -A port 53 | grep -i "example.com"

# Захват для анализа в Wireshark с ограничением
sudo tcpdump -i eth0 -n port 53 -c 500 -w /tmp/dns.pcap
```

**Интерпретация:** В выводе `tcpdump` DNS-заголовок начинается с 12 байт (ID, flags, qdcount, ancount, nscount, arcount). Флаг QR (Query/Response) — бит 7 в байте 2 (offset 2, mask `0x80`).

#### DHCP (UDP 67/68)

```bash
# Захват всех DHCP-пакетов с детализацией
sudo tcpdump -i eth0 -n udp port 67 or port 68 -vv

# Только DISCOVER/OFFER (первый этап DORA)
sudo tcpdump -i eth0 -n "udp port 67 and (udp[8:1] == 1 or udp[8:1] == 2)"

# Только REQUEST/ACK (второй этап DORA)
sudo tcpdump -i eth0 -n "udp port 67 and (udp[8:1] == 3 or udp[8:1] == 5)"

# Проверка прохождения через Relay (фильтрация по giaddr)
sudo tcpdump -i any -n "udp port 67 and ip[24:4] != 0"

# DHCPDECLINE (тип = 4)
sudo tcpdump -i any -n "udp port 67 and udp[8:1] == 4"

# DHCPNAK (тип = 6)
sudo tcpdump -i any -n "udp port 67 and udp[8:1] == 6"

# DHCPv6 (UDP 546/547)
sudo tcpdump -i eth0 -n udp port 546 or port 547 -vv

# Запись в pcap-файл (300 пакетов)
sudo tcpdump -i eth0 -n udp port 67 or port 68 -c 300 -w /tmp/dhcp.pcap
```

**Интерпретация:** Байт 8 в UDP-пейлоаде DHCP соответствует `dhcp.message_type` (1=DISCOVER, 2=OFFER, 3=REQUEST, 5=ACK, 6=NAK). Поля `giaddr` (gateway IP address) находятся в байтах 24-27 DHCP-заголовка.

#### ICMP и IPv6 NDP

```bash
# Все ICMP-пакеты
sudo tcpdump -i eth0 -n icmp

# ICMP Type/Code: Echo Request (ping) и Echo Reply
sudo tcpdump -i eth0 -n 'icmp[0] == 8 or icmp[0] == 0'

# ICMP Destination Unreachable (Type 3)
sudo tcpdump -i eth0 -n 'icmp[0] == 3'

# ICMP Time Exceeded (traceroute)
sudo tcpdump -i eth0 -n 'icmp[0] == 11'

# IPv6 NDP: Neighbor Solicitation (Type 135) и Advertisement (136)
sudo tcpdump -i eth0 -n "icmp6 && (ip6[40] == 135 || ip6[40] == 136)"

# Router Advertisement (Type 134)
sudo tcpdump -i eth0 -n "icmp6 and ip6[40] == 134" -vv

# ICMP PTB (Packet Too Big) — ключевой для PMTUD
sudo tcpdump -i eth0 'icmp[0] == 3 and icmp[1] == 4' -nn

# ICMPv6 Packet Too Big (Type 2)
sudo tcpdump -i eth0 'icmp6[0] == 2' -nn
```

#### iSCSI (TCP 3260)

```bash
# Захват всего iSCSI-трафика на интерфейсе
sudo tcpdump -i eth1 port 3260 -w iscsi_debug.pcap

# Ограничение размера файла (1000 пакетов)
sudo tcpdump -i eth1 port 3260 -w /tmp/iscsi_debug.pcap -c 1000

# Захват только SYN-пакетов (проверка TCP Handshake)
sudo tcpdump -i eth1 port 3260 -nn 'tcp[tcpflags] & tcp-syn != 0' -c 20

# Захват только RST-пакетов (сброс соединений — индикатор проблем)
sudo tcpdump -i eth1 port 3260 -nn 'tcp[tcpflags] & tcp-rst != 0'

# Фильтрация по конкретному хосту
sudo tcpdump -i eth1 host 192.168.200.20 and port 3260 -w /tmp/iscsi_host.pcap

# Анализ без записи в файл (консольный вывод)
sudo tcpdump -i eth1 port 3260 -v 2>&1 | grep -iE "login|read|write|reject|reset"
```

#### IPsec (UDP 500/4500, ESP proto 50)

```bash
# Просмотр процесса согласования IKE (Фаза 1 и 2)
sudo tcpdump -n -i any port 500 or port 4500

# Детальный захват для конкретного пира
sudo tcpdump -n -i any host 10.0.255.1 -w ipsec_debug.pcap

# Просмотр зашифрованного трафика (ESP — IP protocol 50)
sudo tcpdump -n -i any proto 50

# Анализ дампа в Wireshark
wireshark ipsec_debug.pcap
```

**Примечание:** ESP-трафик нерасшифрован в `tcpdump`. Для расшифровки используется Wireshark с ключами IKE.

#### GRE и VXLAN/Geneve

```bash
# GRE (IP protocol 47)
sudo tcpdump -i eth0 proto 47 -nn

# VXLAN (UDP port 4789)
sudo tcpdump -i eth0 -nn port 4789

# Geneve (UDP port 6081)
sudo tcpdump -i eth0 -nn port 6081

# Захват инкапсулированного VXLAN трафика с VNI
sudo tcpdump -i eth0 -nn port 4789 -v
# → VXLAN vni=100

# Деинкапсулированный трафик на OVS bridge
sudo tcpdump -i br-int -nn

# Фильтрация по VNI (требует Wireshark/tshark для декодирования)
sudo tcpdump -i eth0 -nn port 4789 -w /tmp/vxlan.pcap

# Захват QinQ (двойной тег)
sudo tcpdump -i eth0 -e -nn 'vlan and vlan'
```

### Захват трафика в Kubernetes

В современных K8s-кластерах для диагностики сетевых проблем часто используются эфемерные контейнеры (debug containers):

```bash
# Запуск отладочного контейнера с tcpdump внутри пода
kubectl debug -it pod_name --image=nicolaka/netshoot -- tcpdump -i any -nn
```

### Захват в namespace и контейнерах

Для захвата трафика внутри конкретного namespace или контейнера без модификации пода:

```bash
# Через nsenter (по PID контейнера)
PID=$(docker inspect -f '{{.State.Pid}}' <container_id>)
sudo nsenter -t $PID -n tcpdump -i any -nn port 53

# Docker exec (если tcpdump установлен в образе)
docker exec -it <container_id> tcpdump -i eth0 -nn port 80

# Kubernetes: временный контейнер с привилегиями
kubectl debug -it <pod_name> --image=nicolaka/netshoot --share-processes --privileged -- tcpdump -i any -nn

# Захват на виртуальном интерфейсе контейнера (veth)
HOST_IF=$(sudo ip netns exec <ns_name> ip route show default | awk '{print $5}')
sudo tcpdump -i $HOST_IF -nn
```

### Удаленный захват и анализ в реальном времени

Для анализа трафика с удаленного сервера в графическом интерфейсе Wireshark на локальной машине:

```bash
# Передача дампа через SSH в Wireshark
ssh user@remote_host "sudo tcpdump -s 0 -U -n -w - -i eth0 not port 22" | wireshark -k -i -

# Сжатие через gzip для экономии bandwidth
ssh user@remote_host "sudo tcpdump -s 0 -U -n -w - -i eth0 not port 22" | gzip -c > /tmp/remote.pcap.gz
gunzip -c /tmp/remote.pcap.gz | wireshark -k -i -
```

### Мониторинг безопасности

```bash
# Поиск сканирования портов (SYN-флуд с множества源)
sudo tcpdump -i eth0 -nn 'tcp[tcpflags] & tcp-syn != 0' | awk '{print $3}' | sort | uniq -c | sort -rn | head

# Обнаружение ARP-spoofing (два ARP Reply с разным MAC для одного IP)
sudo tcpdump -i eth0 -n arp | awk '/arp reply/ {print $4, $5}' | sort | uniq -d

# Обнаружение необычного ICMP-трафика (потенциальная разведка)
sudo tcpdump -i eth0 -n icmp | awk '{print $3}' | sort | uniq -c | sort -rn | head

# Обнаружение неожиданного HTTP-трафика на нестандартных портах
sudo tcpdump -i eth0 -n -A port 80 | grep -iE "GET|POST|Host:" | head

# Обнаружение DNS-туннелирования (длинные TXT-записи, подозрительные домены)
sudo tcpdump -i eth0 -n -A port 53 | grep -E "TXT|\\x00\\x10" | head
```

## Производительность и Hardware Offloading

Современные сетевые карты (NIC) могут искажать картину захвата из-за функций оптимизации:
- **TSO/GSO:** Вы видите исходящие пакеты размером 60КБ+, хотя в сеть уходят стандартные 1500Б.
- **GRO/LRO:** Входящие пакеты "склеиваются" до передачи в tcpdump.
- **Checksum Offloading:** `tcpdump` может показывать `bad cksum` для исходящих пакетов, так как контрольная сумма вычисляется позже на уровне NIC.
- **VLAN offload:** При включённом `rx-vlan-offload` ядро удаляет тег до передачи в `tcpdump`, поэтому теги могут не отображаться на физическом интерфейсе.

**Решение для точной диагностики MTU и фрагментации:**
```bash
# Временно отключить разгрузку для проверки
sudo ethtool -K eth0 tso off gso off gro off rx-vlan-offload off tx-vlan-offload off

# ... диагностика ...

# Вернуть стандартные настройки
sudo ethtool -K eth0 tso on gso on gro on rx-vlan-offload on tx-vlan-offload on
```
Подробнее: **[Network Offloading](../../Linux/Networking/Concepts/offloading.md)**.

## Диагностика и устранение неполадок

| Симптом | Причина | Диагностика через tcpdump | Решение |
| :--- | :--- | :--- | :--- |
| **Потеря пакетов** | Буфер переполнен, широкий фильтр, медленное устройство | `ip -s link show` (drop), `-b` статистика | Увеличить `-B`, сузить фильтр, писать в `/dev/shm` |
| **`bad cksum`** | NIC offload (TSO/GRO/checksum) | `ethtool -k eth0` | Отключить offload: `ethtool -K eth0 tso off gso off gro off` |
| **Нет SYN-ACK** | Файрвол DROP, сервис не слушает | `tcpdump -i eth0 -nn 'tcp port 80 and tcp-syn'` | Проверить `ss -tlnp`, `iptables -L` |
| **RST вместо ответа** | Порт закрыт (REJECT) или сервис упал | `tcpdump -i eth0 -nn 'tcp port 80 and tcp-rst'` | Проверить `ss -tlnp`, логи приложения |
| **Не видно VLAN-тегов** | `rx-vlan-offload` включён | `tcpdump -i eth0 -e vlan` — тегов нет | Отключить offload временно |
| **Дублирующие MAC** | Порт коммутатора в Access вместо Trunk | `tcpdump -i eth0 -e vlan` — нет тегов | Перевести порт в trunk |
| **MTU/fragmentation issues** | PMTU Black Hole, ICMP заблокирован | `tcpdump 'icmp[0] == 3 and icmp[1] == 4'` | Разрешить ICMP, настроить MSS Clamping |
| **Потеря пакетов в контейнере** | `veth` ограничения, `tc` qdisc | `tc -s qdisc show vethXXX` | Увеличить `tx_queue_len`, проверить `tc` правила |
| **TLS handshake не завершается** | TLS-версия mismatch, cipher, SNI | `tcpdump -i eth0 -nn -s 0 -vvv port 443` | Проверить `openssl s_client`, обновить cipher suites |
| **Зависание захвата** | Переполнение буфера, ошибка libpcap | `dmesg | grep -i pcap`, `-b` вывод | Увеличить буфер, сузить фильтр, перезапустить |

## Рекомендации и очистка

### Best Practices

1. **Всегда используйте `-n` в скриптах:** Отключает DNS-резолв, который замедляет захват и создает артефакты (собственные DNS-запросы в дампе).
2. **Сужайте фильтр как можно раньше:** Чем уже BPF-фильтр, тем меньше overhead. Избегайте захвата `any` без фильтра в production.
3. **Используйте `-s 0` для глубокого анализа:** Полный пакет позволяет анализировать TLS, фрагментацию, L7-протоколы. Для быстрого поиска портов достаточно `-s 96` (заголовки L3+L4).
4. **Записывайте в `tmpfs` при высокой нагрузке:** `/tmp` может быть на slow disk. Используйте `/dev/shm` (tmpfs) для временных pcap.
5. **Ротация файлов:** Для длительного мониторинга используйте `-C` и `-W`. Для автоматической ротации можно использовать `logrotate` с `copytruncate` или `kill -USR1`.
6. **Ограничивайте количество пакетов (`-c`)** при диагностике, чтобы не заполнить диск.
7. **Используйте `-U`** при записи в pipe (например, в Wireshark по SSH), чтобы каждый пакет сбрасывался немедленно.
8. **Проверяйте offload перед диагностикой MTU/fragmentation/checksum:** Отключайте TSO/GSO/GRO/VLAN offload временно.
9. **Не используйте `-i any` для L2-диагностики:** На `any` теряются MAC-адреса и VLAN-теги. Используйте конкретный физический интерфейс.
10. **Комбинируйте с `tshark`:** `tcpdump` для захвата, `tshark` для post-processing (display filters, статистика, reassembly).

### Очистка

```bash
# Удалить временные pcap-файлы
rm -f /tmp/*.pcap /tmp/*.pcap.gz

# Остановить фоновый захват (если запущен через nohup/screen/tmux)
pkill -f "tcpdump"

# Очистить кольцевой буфер /dev/shm (если использовался)
rm -f /dev/shm/*.pcap
```

## Пограничные случаи и ограничения

1. **IPv6 и Extension Headers:** BPF-фильтры для IPv6 extension headers сложнее. Например, `ip6 proto 44` для Fragmentation Header, но сам фрагментированный payload требует `ip6[40]` смещений.
2. **Фрагментация и Reassembly:** `tcpdump` не выполняет автоматическую реконструкцию фрагментированных пакетов на L3. Для этого используйте Wireshark/tshark.
3. **Тоннели (VXLAN/GRE):** На `any` или `tun` интерфейсе виден только инкапсулированный или деинкапсулированный трафик. Для both levels используйте физический интерфейс + `-e` для VLAN/VXLAN тегов.
4. **Jumbo Frames (MTU > 1500):** При захвате увеличьте snaplen (`-s 0`) или получите усечённые пакеты. Проверьте MTU интерфейса: `ip link show eth0 | grep mtu`.
5. **Высокоскоростные сети (10G/40G/100G):** `tcpdump` может не справляться с >500K pps. Рассмотрите `dumpcap` (часть Wireshark), `tshark` с `-b` buffer, или eBPF-инструменты (`pwru`, `bcc`).
6. **Виртуальные среды:** В KVM/QEMU используйте `-i any` или захват на `virbr0`. В Docker — `docker exec` или `nsenter`. В Kubernetes — `kubectl debug`.
7. **Запись на slow storage:** USB-накопители и NFS не выдерживают high pps. Используйте `tmpfs` или запись по SSH в память удалённого хоста.
8. **Capturing on bonded interfaces:** При захвате на bond-master (`bond0`) виден только управляющий трафик (LACP). Данные видно на slave-интерфейсах (`eth0`, `eth1`).
9. **VXLAN decapsulation offload:** Некоторые NIC поддерживают VXLAN decap offload, что скрывает инкапсуляцию от `tcpdump`. Отключайте через `ethtool` если нужно видеть raw VXLAN.
10. **`tcpdump` и `conntrack`/`nf_conntrack`:** `tcpdump` видит пакеты до или после NAT, но не знает о состоянии соединения в conntrack. Для анализа NAT-преобразований используйте `conntrack -E` или `nft monitor`.

## Дополнительная информация

### Диагностика 3-way Handshake

Типичный паттерн успешного соединения:
1. `IP A.12345 > B.80: Flags [S]`
2. `IP B.80 > A.12345: Flags [S.]`
3. `IP A.12345 > B.80: Flags [.]`

Если вы видите только `[S]`, но нет ответа `[S.]` — пакеты блокируются Firewall на стороне сервера или сервер не слушает порт.

### Полезные флаги вывода

#### Детализация
- `-v`, `-vv`, `-vvv`: уровни детализации (TTL, ID пакетов, опции TCP).
- `-l`: строчная буферизация (позволяет делать `tcpdump ... | grep ...`).

#### Форматы времени
| Флаг | Описание |
| :--- | :--- |
| `-t` | Не выводить метку времени. |
| `-tt` | Вывод в формате Unix timestamp. |
| `-ttt` | Вывод дельты (разницы во времени) между текущим и предыдущим пакетом. |
| `-tttt` | Вывод в формате даты и времени (гггг-мм-дд чч:мм:сс.мс). |

### Связанные инструменты

- **[Wireshark](../../../Networking/ServicesAndTools/Wireshark/definitions.md)** — графический анализ и расшифровка протоколов.
- **[ss](./ss.md)** — быстрая проверка состояния сокетов без захвата трафика.
- **[termshark](https://termshark.io/)** — TUI-интерфейс для работы с pcap-файлами в терминале.
- **[pwru](https://github.com/cilium/pwru)** — отслеживание пакетов внутри ядра (eBPF) при загадочных потерях (drops).
