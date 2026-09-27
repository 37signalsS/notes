# Wireshark — практические сценарии

> **SSoT:** Определения базовых терминов (Follow Stream, Protocol Hierarchy, Conversations, Expert Info, SSLKEYLOGFILE) — в **[Определения](./definitions.md)**. Концепции захвата — в **[Основные концепции](./core_concepts.md)**. Расшифровка TLS — в **[Методы расшифровки TLS](./tls_decryption_methods.md)**. Статистика и автоматизация — в **[Использование tshark](./tshark_usage.md)**. Профили — в **[Продвинутые функции](./advanced_features.md)**.

## Определения

**Экспорт объектов (Export Objects)** — механизм извлечения файлов (изображений, скриптов, документов), которые были переданы внутри прикладных протоколов (HTTP, SMB, TFTP, DICOM). Доступ: `File → Export Objects → HTTP/SMB/TFTP/DICOM`. Поддерживает фильтрацию по имени и типу файла.

**Синтез трафика (Traffic Reconstruction)** — процесс объединения фрагментированных данных прикладного уровня в единый логический объект для анализа. Включает реконструкцию TCP-потоков (Follow Stream),重组 фрагментированных IP-пакетов и восстановление файлов из нескольких соединений.

## Базовые концепции

### Базовый рабочий процесс анализа

1.  **Выбор интерфейса**: При запуске выберите активный адаптер (с графиком активности).
2.  **Управление захватом**: `Ctrl + E` для старта/стопа. При работе с большими объемами используйте **Capture Filter** на этапе старта (например, `host 10.0.0.5 and port 443`).
3.  **Фильтрация отображения**: Используйте **Display Filters** для сужения области поиска (например, `http.response.code >= 400`).
4.  **Сохранение**: Всегда сохраняйте в формате `.pcapng` для поддержки комментариев и метаданных.

### Настройка временных меток для диагностики

Перейдите в `View → Time Display Format`:
*   **Seconds since beginning of capture**: Поиск событий относительно начала инцидента.
*   **Seconds since previous displayed packet**: Критично для поиска задержек (Latency) между шагами протокола. Если фильтр активен, показывает время именно между отфильтрованными пакетами.
*   **Date and Time of Day**: Необходим для корреляции сетевого дампа с логами приложений и системными событиями.

### Ключевые фильтры для каждого сценария

| Сценарий | Display Filter | Назначение |
| :--- | :--- | :--- |
| **HTTP ошибки** | `http.response.code >= 400` | Все ответы с ошибками 4xx/5xx |
| **TCP потери** | `tcp.analysis.retransmission \|\| tcp.analysis.fast_retransmission` | Ретрансмиссии |
| **DNS туннель** | `dns.qry.name.len > 50` | Подозрительно длинные DNS-запросы |
| **SYN-flood** | `tcp.flags.syn==1 && tcp.flags.ack==0` | SYN без ACK = попытка подключения |
| **Slowloris** | `tcp.flags.syn==1 && tcp.window_size < 1024` | SYN с малым окном |
| **Латентность** | `frame.time_delta_displayed > 0.5` | Пакеты с задержкой > 500 мс |
| **Фрагментация** | `ip.flags.mf==1 \|\| ip.frag_offset > 0` | Фрагментированные IP-пакеты |
| **VoIP** | `sip \|\| rtp \|\| rtcp` | SIP/RTP/RTCP трафик |
| **TLS handshake** | `tls.handshake.type == 1 \|\| tls.handshake.type == 2` | Client/Server Hello |

## Практические сценарии

### Сценарий 1: Первичный аудит неизвестного дампа

Если вы получили дамп без контекста:
1.  **Protocol Hierarchy**: Проверьте, нет ли аномальных протоколов (например, много DNS-трафика может указывать на туннелирование или DDoS).
2.  **Conversations**: Отсортируйте по `Bytes`. Найдите "болтливые" узлы.
3.  **Expert Info**: Ищите всплески `TCP Retransmission` (потери в сети) или `TCP ZeroWindow` (приложение-получатель не справляется с потоком).

```bash
# tshark: быстрый обзор дампа
tshark -r unknown.pcapng -q -z conv,ip
tshark -r unknown.pcapng -q -z io,phs
tshark -r unknown.pcapng -q -z expert
```

### Сценарий 2: Глубокая отладка в Kubernetes (ksniff)

Для подов, где нет `tcpdump` (включая distroless):
1.  Установите плагин: `kubectl krew install sniff`.
2.  Запустите захват с выводом в локальный GUI:
    ```bash
    kubectl sniff <pod-name> -n <namespace>
    ```
3.  **Для привилегированных сред**: Используйте флаг `-p`, чтобы запустить под-помощник, который имеет доступ к сетевому стеку целевого контейнера.
4.  **Сценарий mTLS**: Если в кластере используется Istio/Linkerd, захватывайте трафик на интерфейсе `lo` внутри пода, чтобы увидеть данные до их шифрования sidecar-прокси.

```bash
# Захват с фильтрацией по порту
kubectl sniff <pod-name> -n <namespace> -f "tcp port 80" -w http.pcapng

# Захват через ephemeral container (без krew)
kubectl debug -it <pod-name> --image=nicolaka/netshoot -- tshark -i eth0 -w /tmp/capture.pcapng

# Копирование дампа из контейнера
kubectl cp <pod-name>:/tmp/capture.pcapng ./local_capture.pcapng
```

### Сценарий 3: Анализ производительности баз данных

Для выявления медленных запросов без доступа к логам БД:
*   **PostgreSQL**: Фильтр `pgsql.query` выводит текст SQL. Используйте `Statistics → Service Response Time → MySQL/PostgreSQL` для получения таблицы задержек (SRT) по каждому типу команды.
*   **Redis**: Фильтр `redis.command` для отслеживания `GET/SET` циклов и поиска ключей, вызывающих всплески трафика.
*   **MongoDB**: Фильтр `mongodb.query` отображает JSON-структуру запросов. Анализируйте поле `Response Time` в деталях пакета.

```bash
# tshark: PostgreSQL SRT статистика
tshark -r db_traffic.pcapng -q -z "pgsql,tree"

# tshark: MySQL SRT статистика
tshark -r db_traffic.pcapng -q -z "mysql,tree"

# tshark: все DNS запросы с временем ответа
tshark -r dns.pcapng -q -z "dns,tree"
```

### Сценарий 4: Расшифровка TLS 1.3 и QUIC (HTTP/3)

Для анализа зашифрованных gRPC или HTTPS вызовов:
1.  **Экспорт ключей**:
    ```bash
    export SSLKEYLOGFILE=~/tls-keys.log
    google-chrome --user-data-dir=/tmp/debug
    ```
2.  **Настройка Wireshark**: `Edit → Preferences → Protocols → TLS → (Pre)-Master-Secret log filename`.
3.  **Проверка**: После настройки используйте фильтры `http2` или `quic`. В нижней панели (Packet Details) появится вкладка `Decrypted TLS`, где виден чистый текст.

```bash
# tshark: расшифровка TLS через SSLKEYLOGFILE
tshark -r encrypted.pcapng -o tls.keylog_file:~/tls-keys.log -Y "http2" -T fields -e http2.headers.method -e http2.headers.status

# tshark: расшифровка QUIC (Wireshark 3.4+)
tshark -r quic.pcapng -o tls.keylog_file:~/tls-keys.log -Y "http3" -T fields -e http3.headers.method
```

Для анализа HTTP/1.1 поверх TLS (инкапсуляция, фильтрация по SNI, структура Record Layer) — см. **[Анализ HTTPS в Wireshark](./https_analysis.md)**.

### Сценарий 5: Поиск микро-всплесков (Micro-bursts)

При жалобах на «загадочные» потери в высокоскоростных сетях (10G+):
1.  Откройте `Statistics → I/O Graphs`.
2.  Установите **Tick interval** в **1 microsecond** (доступно в Wireshark 4.4+).
3.  Ищите резкие пики (Spikes) на графике. Если пик в микросекундном интервале превышает пропускную способность канала, это вызывает мгновенное переполнение буферов коммутатора (Output Drops).

```bash
# tshark: I/O Graphs с микроинтервалом
tshark -r高速.pcapng -q -z "io,stat,0.000001,AVG(frame.len),MAX(frame.len)"
```

### Сценарий 6: Использование профилей и автоматизация

1.  Создайте профиль `Security`: Настройте правила раскраски для SYN-флуда (`tcp.flags.syn==1 && tcp.flags.ack==0`) и сканирования.
2.  Создайте профиль `Web`: Добавьте колонки `http.host`, `http.request.method`, `http.response.code`.
3.  **Automatic Profile Switching**: В `Edit → Configuration Profiles` привяжите профиль к фильтру (например, переключаться на `Web`, если в дампе есть трафик на порт 80/443).

### Сценарий 7: Анализ DNS-туннелирования

При подозрении на DNS-туннель (Exfiltration или C2-канал):
```bash
# Поиск подозрительно длинных DNS-имен
tshark -r traffic.pcapng -Y "dns.qry.name.len > 50" -T fields -e dns.qry.name | sort | uniq -c | sort -rn | head -20

# Подсчет уникальных DNS-запросов по домену
tshark -r traffic.pcapng -Y "dns.flags.response == 0" -T fields -e dns.qry.name | cut -d. -f2- | sort | uniq -c | sort -rn

# Поиск DNS TXT-запросы (частый транспорт для туннелей)
tshark -r traffic.pcapng -Y "dns.qry.type == 16" -T fields -e dns.qry.name
```

**Признаки DNS-туннеля:**
*   Высокий объем TXT-запросов (type 16)
*   Длинные поддомены (>50 символов)
*   Много уникальных поддоменов одного базового домена
*   Регулярные интервалы запросов (beaconing)
*   Высокий ratio запросов к ответам

### Сценарий 8: Обнаружение DDoS-атак

```bash
# SYN-flood: количество SYN без ACK
tshark -r attack.pcapng -Y "tcp.flags.syn==1 && tcp.flags.ack==0" | wc -l

# UDP-flood: топ IP-источников
tshark -r attack.pcapng -Y "udp" -T fields -e ip.src | sort | uniq -c | sort -rn | head -10

# DNS-amplification: поиск large UDP DNS ответов
tshark -r attack.pcapng -Y "dns.flags.response == 1 && udp.length > 512" -T fields -e ip.src -e udp.length | sort -t$'\t' -k2 -rn | head -20

# HTTP-flood: количество HTTP GET/POST запросов
tshark -r attack.pcapng -Y "http.request" -T fields -e http.request.method | sort | uniq -c | sort -rn
```

### Сценарий 9: Анализ L2-проблем (STP, VLAN, MAC)

```bash
# Spanning Tree Protocol: поиск_topology changes
tshark -r network.pcapng -Y "stp" -T fields -e stp.type -e stp.root_bridge -e stp.root_cost

# VLAN-tagged трафик: проверка правильности тегирования
tshark -r network.pcapng -Y "vlan.id" -T fields -e vlan.id -e ip.src -e ip.dst

# ARP-конфликты и спуфинг
tshark -r network.pcapng -Y "arp.duplicate-address-detected || arp.duplicate-address-frame" -T fields -e arp.src.hw_mac -e arp.src.proto_ipv4

# Поиск MAC-адресов (поиск неизвестных устройств)
tshark -r network.pcapng -q -z conv,eth | sort -k5 -rn | head -10
```

### Сценарий 10: Анализ фрагментации и重组

```bash
# Поиск фрагментированных IP-пакетов
tshark -r fragmented.pcapng -Y "ip.flags.mf==1 || ip.frag_offset > 0" -T fields -e ip.src -e ip.dst -e ip.id -e ip.frag_offset

# Анализ MTU-проблем (пакеты > 1500 байт)
tshark -r capture.pcapng -Y "frame.len > 1500" -T fields -e frame.len -e ip.src -e ip.dst

# Поиск IP-фрагментов с уникальными ID
tshark -r fragmented.pcapng -Y "ip.flags.mf==1" -T fields -e ip.id | sort -u | wc -l
```

### Сценарий 11: Анализ VoIP-трафика

```bash
# SIP-сессии: список звонков
tshark -r voip.pcapng -Y "sip.Method == INVITE" -T fields -e sip.from -e sip.to -e sip.CSeq.method

# RTP-потоки: список媒體-потоков
tshark -r voip.pcapng -q -z rtp,streams

# Качество RTP: jitter и packet loss
tshark -r voip.pcapng -q -z rtp,stat

# Экспорт аудио из RTP
tshark -r voip.pcapng -z rtp,streams -q
# Затем в Wireshark: Telephony → RTP → RTP Streams → Analyze & Save
```

### Сценарий 12: Анализ WiFi (802.11)

```bash
# Сканеры WiFi: список SSID и BSSID
tshark -r wifi.pcapng -Y "wlan.fc.type_subtype == 0x08" -T fields -e wlan.mgt.ssid -e wlan.bssid -e wlan_radio.signal_dbm

# Аутентификация: попытки подключения
tshark -r wifi.pcapng -Y "wlan.fc.type_subtype == 0x0b || wlan.fc.type_subtype == 0x0c" -T fields -e wlan.sa -e wlan.da -e wlan.fixed.status_code

# Deauthentication-атаки
tshark -r wifi.pcapng -Y "wlan.fc.type_subtype == 0x0c" -T fields -e wlan.sa -e wlan.da -e wlan.fixed.reason_code

# Throughput по SSID
tshark -r wifi.pcapng -q -z conv,wlan
```

### Сценарий 13: Анализ TCP в Wireshark: рукопожатие, передача данных и разрыв соединения

**Задача:** Визуально разобрать полный цикл жизни TCP-сессии — 3-way handshake, передачу HTTP-данных и штатный разрыв соединения — на примере загрузки сайта по незашифрованному HTTP.

**Шаги:**

1. Запустите захват в Wireshark и откройте в браузере сайт по HTTP (например, `http://networks.ru`). Поскольку трафик не зашифрован, вы увидите все прикладные данные.
2. Браузер при загрузке открывает несколько параллельных TCP-соединений к порту `80` сервера. В дампе появятся пары ephemeral-порт → `80`.
3. Чтобы сузить область анализа, примените Display Filter по IP-адресу сервера:
   ```bash
   ip.addr == <server_ip>
   ```
4. Выберите одно из соединений (например, ephemeral-порт `57704` → `80`) и последовательно разберите каждый сегмент.

**Анализ 3-way handshake:**

- **Сегмент 1 — SYN (клиент → сервер):**
  - Порт отправителя: `57704` (назначен ОС автоматически), порт получателя: `80`.
  - `Sequence Number = 0` (относительный; Wireshark показывает смещение от ISN).
  - `Acknowledgment Number = 0` (поле неактивно, флаг ACK не установлен).
  - Флаги: `SYN`.
  - Размер окна: значение, объявленное клиентом.
  - Опции (передаются только в SYN):
    - `MSS = 1460` — максимальный размер полезной нагрузки.
    - `Window Scale = 256` — множитель для размера окна (`2^8 = 256`).
    - `SACK Permitted` — разрешение выборочных подтверждений.

- **Сегмент 2 — SYN + ACK (сервер → клиент):**
  - Порт отправителя: `80`, порт получателя: `57704`.
  - `Sequence Number = 0` (относительный ISN сервера).
  - `Acknowledgment Number = 1` — номер следующего байта, который сервер ожидает от клиента (подтверждает `ISN_client + 1`).
  - Флаги: `SYN`, `ACK`.
  - Сервер также объявляет свои опции (MSS, SACK OK, Window Scale).

- **Сегмент 3 — ACK (клиент → сервер):**
  - Порт отправителя: `57704`, порт получателя: `80`.
  - `Sequence Number = 1` (первый байт данных клиента будет иметь номер `ISN_client + 1`).
  - `Acknowledgment Number = 1` (подтверждает `ISN_server + 1`).
  - Флаги: только `ACK`.
  - После этого сегмента соединение переходит в состояние `ESTABLISHED`.

**Анализ передачи данных:**

Для загрузки ресурсов браузер использует второе параллельное соединение (например, порт `57705` → `80`).

- **HTTP-запрос (клиент → сервер):**
  - Флаги: `ACK`, `PSH` (Push — запрос немедленной доставки данных приложению).
  - `Sequence Number` и `Acknowledgment Number` — текущие смещения в потоке.
  - Размер данных TCP (payload): `484` байта — полный HTTP-запрос, поместившийся в один сегмент. Флаг `PSH` установлен, потому что в сегменте есть всё необходимое для работы прикладного протокола.

- **HTTP-ответ (сервер → клиент):**
  Сервер отправляет ответ, разбитый на несколько TCP-сегментов (в примере пакеты `1363` и `1364`). Wireshark автоматически объединяет их в единый поток (реконструкция потока, reassembly) и отображает полный HTTP-ответ.
  - В каждом сегменте:
    - Флаги: `ACK`, `PSH`.
    - `Sequence Number` — смещение данных в потоке.
    - `Acknowledgment Number` — остаётся неизменным, так как клиент не отправлял новых данных.
    - Опции: `Timestamps` (TSval / TSecr) — нужны для точного расчёта RTT и защиты от PAWS.
    - Данные: фрагмент HTTP-ответа.

**Разрыв соединения (4-way teardown):**

Пока браузер открыт, для поддержания соединения могут периодически передаваться сообщения **TCP Keepalive**.

После закрытия браузера соединение разрывается в четыре шага:

1. **Клиент → Сервер:** `FIN + ACK`. Запрос на разрыв соединения от клиента.
2. **Сервер → Клиент:** `ACK`. Подтверждение запроса. Соединение half-closed (сервер ещё может отправлять данные).
3. **Сервер → Клиент:** `FIN + ACK`. Запрос на разрыв от сервера.
4. **Клиент → Сервер:** `ACK`. Подтверждение. Соединение полностью закрыто.

```bash
# Фильтр для поиска FIN-пакетов с ACK
tshark -r capture.pcapng -Y "tcp.flags.fin == 1 && tcp.flags.ack == 1"

# Статистика по TCP-соединениям
tshark -r capture.pcapng -q -z conv,tcp

# Просмотр reassembled-потока (ASCII)
tshark -r capture.pcapng -q -z follow,tcp,ascii,0
```

**Ожидаемый результат:**
- В списке пакетов последовательно появятся `SYN → SYN-ACK → ACK → данные → FIN/ACK → ACK → FIN/ACK → ACK`.
- Поля `Sequence Number` и `Acknowledgment Number` будут строго привязаны к порядку байт в потоке.
- При использовании `Follow → TCP Stream` Wireshark покажет reassembled HTTP-ответ, объединённый из нескольких сегментов.

## Дополнительная информация

### Удаленный анализ через SSH-пайп

Если на сервере нет места для хранения дампа:
```bash
ssh root@remote-server "tcpdump -i eth0 -U -s0 -w - 'not port 22'" | wireshark -k -i -
```
*   `-U`: немедленная отправка пакетов в поток (unbuffered).
*   `not port 22`: исключение трафика самой SSH-сессии, чтобы избежать рекурсии.

```bash
# Удаленный захват с ring buffer через tshark
ssh root@remote-server "sudo tshark -i eth0 -b filesize:102400 -b files:10 -w /tmp/remote.pcapng" &
# Сбор файлов через 5 минут
scp root@remote-server:/tmp/remote*.pcapng ./
```

### Типичные ошибки при анализе

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Bad Checksum` | Checksum Offload | Отключить в настройках протокола или `ethtool -K` |
| `Spurious retransmission` | LRO/GRO | `ethtool -K eth0 gro off lro off` |
| `Packets look truncated` | Малый snaplen | `-s 0` (полный захват) |
| `TLS encrypted, can't decrypt` | Нет ключей | Настроить SSLKEYLOGFILE или использовать DSB |
| `Follow Stream shows garbage` | Шифрование (TLS/QUIC) | Расшифровать через SSLKEYLOGFILE |
| `High latency in graph` | Неправильный time format | Использовать `seconds since previous displayed packet` |
| `DNS queries missing` | Capture Filter слишком узкий | Расширить фильтр или убрать |

### Платформы захвата

| Платформа | Инструмент | Особенности |
| :--- | :--- | :--- |
| **Linux** | `dumpcap`, `tcpdump`, `tshark` | `CAP_NET_RAW`, AF_PACKET/XDP |
| **Windows** | `Npcap` + Wireshark | Требует установки Npcap, UAC |
| **macOS** | `dumpcap` + Wireshark | BPF, ограниченный promiscuous |
| **Docker** | `nsenter`, `netshoot` | Network namespace захват |
| **Kubernetes** | `kubectl debug`, `ksniff` | Ephemeral containers |

### См. также
*   **[Определения и форматы](./definitions.md)** — обзор PCAP/PCAPNG, Expert Info, SRT.
*   **[Основные концепции захвата](./core_concepts.md)** — механизмы фильтров, AF_PACKET/XDP, multi-iface.
*   **[Методы расшифровки TLS](./tls_decryption_methods.md)** — расширенное руководство по SSLKEYLOGFILE, DSB, QUIC.
*   **[Справочник по tshark](./tshark_usage.md)** — автоматизация сценариев в CLI.
*   **[Продвинутые функции](./advanced_features.md)** — профили, колонки, расширенная статистика.
*   **[Диагностика TCP](./tcp_performance/tcp_performance_diagnostics.md)** — анализ throughput и задержек.
*   **[Влияние offloading](./tcp_performance/tcp_network_losses_and_offloading.md)** — проблема LRO/GRO/TSO.
*   **[HTTP/2 и gRPC](./http2_grpc_analysis.md)** — анализ HTTP/2/gRPC трафика.
*   **[Service Mesh](./service_mesh_analysis.md)** — mTLS, sidecar, Envoy, Istio.
*   **[NAT, conntrack, файрволы](./nat_conntrack_firewall_analysis.md)** — NAT translation, conntrack drops.
*   **[eBPF-инструменты](./ebpf_diagnostics_tools.md)** — pwru, bpftrace, tcpflow.
*   **[Lua-скрипты](./lua_scripting.md)** — автоматизация и кастомные диссекторы.
*   **[sysctl — TCP параметры](./sysctl_tcp_cheatsheet.md)** — sysctl для диагностики.
