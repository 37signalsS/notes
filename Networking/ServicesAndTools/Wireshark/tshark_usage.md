# tshark — анализ трафика в командной строке

## Определения

**tshark** — консольный сетевой анализатор (сниффер), входящий в состав Wireshark. Он использует тот же движок диссекции протоколов и библиотеку захвата, что и графическая версия, но оптимизирован для работы в терминале, автоматизации через скрипты и анализа данных в конвейерах (pipelines).

В отличие от графического Wireshark, **tshark** может работать в режиме потоковой обработки, что позволяет анализировать файлы, размер которых превышает объем оперативной памяти, а также выполнять высокопроизводительный экспорт данных в структурированные форматы (JSON, CSV, Elasticsearch).

**tshark** является основным инструментом для выполнения глубокого анализа (L7) в средах без GUI (удаленные серверы, контейнеры) и для пакетной обработки больших массивов PCAP-файлов.

**termshark** — интерактивный TUI-интерфейс (аналог GUI Wireshark в терминале), работающий поверх `tshark`. Предоставляет дерево протоколов, фильтры и навигацию по пакетам. См. **[Сетевые инструменты CLI и TUI](../../../Linux/Diagnostics/Networking/network_cli_tools.md#termshark)**.

**dumpcap** — низкоуровневая утилита для захвата пакетов, используемая Wireshark и tshark. Требует только `CAP_NET_RAW`. См. **[Определения Wireshark](./definitions.md)**.

## Базовые концепции

### Установка

| Дистрибутив | Команда |
| :--- | :--- |
| **Debian / Ubuntu** | `sudo apt install tshark` |
| **Fedora / RHEL** | `sudo dnf install wireshark-cli` |
| **Arch Linux** | `sudo pacman -S wireshark-cli` |
| **macOS** | `brew install wireshark` |

### Ключевые флаги и параметры

| Флаг | Тип | Описание | Аналог в GUI |
| :--- | :--- | :--- | :--- |
| `-i <iface>` | Захват | Выбор сетевого интерфейса (или `-i -` для STDIN) | Список интерфейсов |
| `-f "..."` | Фильтр | Фильтр захвата (BPF-синтаксис tcpdump) | Capture Filter |
| `-Y "..."` | Фильтр | Фильтр отображения (синтаксис Wireshark) | Display Filter |
| `-r <file>` | Ввод | Чтение данных из файла (pcap, pcapng, gz) | File → Open |
| `-w <file>` | Вывод | Запись сырых пакетов в файл | File → Save |
| `-c <count>` | Лимит | Остановка после захвата N пакетов | — |
| `-T <format>` | Формат | Формат вывода: `fields`, `json`, `ek` (ELK), `pdml`, `psml`, `tabs` | — |
| `-e <field>` | Поля | Извлечение конкретного поля (только при `-T fields`) | Apply as Column |
| `-n` | Скорость | Отключить разрешение имен (DNS, MAC, Port) | — |
| `-N <encap>` | Кодировка | Ограничение раскрытия имен: `m` (MAC), `d` (DNS), `v` (VLAN) | — |
| `-q` | Тишина | Подавить вывод отдельных пакетов (используется для `-z`) | — |
| `-z <stat>` | Стат. | Сбор статистики (потоки, иерархия, эксперты и др.) | Statistics меню |
| `-o <pref>` | Опции | Переопределение настроек (например, TLS ключи) | Preferences |
| `-V` | Вывод | Максимальная детализация каждого пакета (Verbose) | Packet Details |
| `-x` | Декод | Декодировать пакеты (hex + ASCII) | Packet Bytes |
| `-l` | Режим | Буферизация строк (line buffered) — для вывода в реальном времени | — |
| `-t ad` | Время | Абсолютный формат времени (YYYY-MM-DD HH:MM:SS) | — |
| `-t <fmt>` | Время | Формат времени: `ad` (abs), `d` (delta), `e` (epoch), `r` (relative) | — |
| `-a <stop>` | Авто-стоп | Условия остановки захвата: `duration:S`, `filesize:KB`, `packets:N` | Stop Capture |
| `-b <ring>` | Кольцо | Кольцевой буфер: `filesize:KB`, `files:N`, `duration:S` | Ring Buffer |
| `-B <MB>` | Буфер | Размер буфера захвата в МБ (по умолчанию 2 МБ) | Buffer Size |
| `-G <pcapng>` | pcapng | Запись в формат pcapng (с метаданными интерфейсов) | — |
| `-E <opt>` | Экспорт | Параметры экспорта: `header=y`, `separator=,`, `quote=d` | — |

### Работа с фильтрами

В tshark разделяются два типа фильтрации:
1.  **Capture Filter (`-f`)**: Применяется библиотекой `libpcap` до записи на диск. Экономит ресурсы процессора и место на диске. Использует синтаксис `tcpdump`.
2.  **Display Filter (`-Y`)**: Применяется движком Wireshark к уже захваченным или считанным данным. Поддерживает всю мощь логики диссекции L7.

Подробнее о синтаксисе: **[Фильтрация в Wireshark](./core_concepts.md#фильтрация-трафика)**.

## Практические сценарии

### Захват и удаленный анализ

```bash
# Список доступных интерфейсов с индексами
tshark -D

# Захват 100 пакетов с интерфейса eth0 и запись в pcapng
sudo tshark -i eth0 -c 100 -w capture.pcapng

# Удаленный захват через SSH с локальным анализом (через конвейер)
ssh user@remote-host "sudo dumpcap -i eth0 -w -" | tshark -r - -Y "http.request"

# Захват с фильтрацией по протоколу и порту (BPF)
sudo tshark -i eth0 -f "tcp port 443" -w tls_traffic.pcapng

# Авто-остановка через 60 секунд или при достижении 100 МБ
sudo tshark -i eth0 -a duration:60 -a filesize:102400 -w capture.pcapng
```

### Извлечение данных и арифметика полей (Wireshark 4.x+)

Начиная с версии 4.x, tshark поддерживает арифметические и логические операции прямо в параметрах `-e`:

```bash
# Расчет размера полезной нагрузки TCP (длина IP-пакета - заголовок IP - заголовок TCP)
tshark -r capture.pcap -T fields -e "ip.len - ip.hdr_len - tcp.hdr_len"

# Логическая проверка: задержка кадра более 100мс
tshark -r capture.pcap -T fields -e "frame.time_delta > 0.1"

# Извлечение среза данных (первые 4 байта нагрузки UDP)
tshark -r capture.pcap -T fields -e "udp.payload[0:4]"

# Извлечение нескольких полей в CSV формате с заголовком
tshark -r capture.pcap -T fields -e frame.number -e ip.src -e ip.dst -e frame.len -E header=y -E separator=, > report.csv

# Экспорт с кавычками и разделителем табуляции
tshark -r capture.pcap -T fields -e frame.number -e ip.src -e ip.dst -E header=y -E separator=$'\t' -E quote=d > report.tsv
```

### Анализ прикладного уровня (HTTP, DNS, TLS)

```bash
# Извлечение всех запрашиваемых доменных имен из DNS
tshark -r capture.pcap -Y "dns.flags.response == 0" -T fields -e dns.qry.name

# Анализ HTTP User-Agent и запрошенных хостов
tshark -r capture.pcap -Y "http.request" -T fields -e http.host -e http.user_agent

# Статистика HTTP-методов (GET, POST, PUT и т.д.)
tshark -r capture.pcap -Y "http.request" -T fields -e http.request.method | sort | uniq -c | sort -rn

# Расшифровка TLS с использованием файла ключей (SSLKEYLOGFILE)
tshark -r capture.pcap -o tls.keylog_file:/path/to/keys.log -Y "http2"

# Расшифровка TLS с приватным ключом сервера (только RSA без PFS)
tshark -r capture.pcap -o tls.keys_list:192.168.1.1,443,http,/path/to/server.key

# Анализ TLS-хендшейков (ClientHello/ServerHello)
tshark -r capture.pcap -Y "tls.handshake.type == 1" -T fields -e ip.src -e ip.dst -e tls.handshake.extensions_server_name
```

### Диагностика TCP-проблем

```bash
# Ретрансмиссии (потерянные пакеты)
tshark -r capture.pcap -Y "tcp.analysis.retransmission" -T fields -e frame.time -e ip.src -e tcp.srcport -e ip.dst -e tcp.dstport

# Быстрые ретрансмиссии (3 DupACK)
tshark -r capture.pcap -Y "tcp.analysis.fast_retransmission"

# Ложные ретрансмиссии (ACK пришел позже таймера)
tshark -r capture.pcap -Y "tcp.analysis.spurious_retransmission"

# DupACK (сигнал о потере)
tshark -r capture.pcap -Y "tcp.analysis.duplicate_ack" -T fields -e frame.time -e ip.src -e ip.dst -e tcp.ack

# Zero Window (приёмник переполнен)
tshark -r capture.pcap -Y "tcp.analysis.zero_window" -T fields -e frame.time -e ip.src -e ip.dst

# Window Full (отправитель заполнил окно)
tshark -r capture.pcap -Y "tcp.analysis.window_full"

# Out-of-Order (нарушение порядка)
tshark -r capture.pcap -Y "tcp.analysis.out_of_order"

# SACK-блоки (избирательное подтверждение)
tshark -r capture.pcap -Y "tcp.options.sack" -T fields -e tcp.sack.left_edge -e tcp.sack.right_edge

# Timestamps для измерения RTT
tshark -r capture.pcap -Y "tcp.options.timestamp" -T fields -e tcp.options.ts_val -e tcp.options.ts_ecr

# Полная диагностика TCP: все аномалии
tshark -r capture.pcap -Y "tcp.analysis.flags" -T fields -e frame.time -e ip.src -e ip.dst -e tcp.analysis.flags
```

### Сбор сетевой статистики (`-z`)

```bash
# Иерархия протоколов (процентное распределение трафика)
tshark -r capture.pcap -q -z io,phs

# Список всех IP-диалогов (Conversations)
tshark -r capture.pcap -q -z conv,ip

# Сводка экспертной информации (Retransmissions, Zero Window и др.)
tshark -r capture.pcap -q -z expert

# Список конечных узлов (Endpoints) с объемами данных
tshark -r capture.pcap -q -z endpoints,ip

# Реконструкция TCP-потока (Follow Stream) в ASCII
tshark -r capture.pcap -q -z follow,tcp,ascii,0

# Статистика ввода-вывода: байты/секунду за интервалы по 1 сек
tshark -r capture.pcap -q -z io,stat,1

# Статистика с фильтром: только HTTP-трафик
tshark -r capture.pcap -q -z io,stat,1,"http"

# Статистика с счетчиком: количество пакетов и байт
tshark -r capture.pcap -q -z io,stat,1,"COUNT(frame)frame","SUM(frame.len)frame"

# DNS-запросы и ответы
tshark -r capture.pcap -q -z dns,tree

# HTTP-статистика (коды ответов)
tshark -r capture.pcap -q -z http,tree
```

### Длительный захват с кольцевым буфером (Ring Buffer)

Для предотвращения переполнения диска при длительном мониторинге:
```bash
# Сохранять файлы по 100 МБ, оставить последние 10 файлов
sudo tshark -i eth0 -b filesize:102400 -b files:10 -w continuous_capture.pcapng

# Ротация каждые 60 секунд, максимум 24 файла (сутки)
sudo tshark -i eth0 -b duration:60 -b files:24 -w daily_capture_%Y%m%d_%H%M%S.pcapng

# Авто-остановка через 7 дней
sudo tshark -i eth0 -b filesize:102400 -b files:100 -a duration:604800 -w week_capture.pcapng
```

### Автоматизация и экспорт в ELK/JSON

```bash
# Экспорт в JSON для последующей обработки через jq
tshark -r capture.pcap -T json | jq '.[]._source.layers.ip["ip.src"]'

# Экспорт в формате EK для прямой загрузки в Elasticsearch
tshark -r capture.pcap -T ek > elastic_data.json

# Фильтрация JSON по условию
tshark -r capture.pcap -T json | jq '.[] | select(.layers.ip["ip.src"] == "10.0.0.1")'

# Пакетная обработка нескольких файлов
for f in *.pcap; do
  tshark -r "$f" -T ek >> all_traffic.json
done

# Обработка gzip-сжатых дампов
zcat *.pcap.gz | tshark -r - -T ek > decompressed.json
```

### Работа в контейнерах и Kubernetes

```bash
# Захват внутри контейнера (nsenter)
nsenter -t $(docker inspect -f '{{.State.Pid}}' <container_id>) -n tshark -i eth0 -w - | tshark -r -

# Захват через kubectl debug
kubectl debug -it <pod_name> --image=nicolaka/netshoot -- tshark -i eth0 -w /tmp/capture.pcapng

# Извлечение pcap из временного контейнера
kubectl debug -it <pod_name> --image=nicolaka/netshoot -- tar -cf - /tmp/capture.pcapng | tar -xf - -C /local/path/

# Анализ traffic в Istio/Linkerd (mTLS)
# Захват на loopback до шифрования sidecar
kubectl exec -it <pod_name> -c istio-proxy -- tshark -i lo -f "tcp port 8080" -w /dev/stdout | tshark -r -
```

### Интеграция с другими инструментами

```bash
# Комбинация с grep для быстрого поиска
tshark -r capture.pcap -T fields -e ip.src -e ip.dst | grep "10.0.0.1" | sort | uniq -c

# Комбинация с awk для агрегации
tshark -r capture.pcap -T fields -e ip.src -e frame.len | awk '{sum[$1]+=$2} END {for (k in sum) print k, sum[k]}' | sort -k2 -rn

# Потоковая обработка: захват → фильтрация → запись
sudo tshark -i eth0 -f "tcp port 80" -w - | tshark -r - -Y "http.request" -T fields -e http.host | sort | uniq -c

# Мониторинг в реальном времени с обновлением каждую секунду
tshark -i eth0 -z io,stat,1 -q -l | tr '\r' '\n' | tail -1
```

## Дополнительная информация

### Оптимизация производительности

tshark потребляет значительно больше ресурсов, чем `tcpdump`. Для работы на высоких скоростях (1Gbps+):
1.  **Отключите разрешение имен (`-n`)**: Это критически важно для производительности. Без `-n` tshark будет выполнять DNS-запросы для каждого IP-адреса.
2.  **Используйте `-f` вместо `-Y`**: Фильтры захвата работают в ядре (BPF) и гораздо эффективнее фильтров отображения.
3.  **Используйте `dumpcap` для захвата**: А `tshark` только для анализа уже записанных файлов. `dumpcap` — самый легкий инструмент в экосистеме.
4.  **Увеличьте буфер захвата**: Опция `-B <size_in_MB>`. По умолчанию 2 МБ — часто недостаточно. Рекомендуется 16-64 МБ для высокоскоростных сетей.
5.  **Отключите offloading на хосте**: `ethtool -K eth0 gro off lro off tso off gso off` — предотвращает искажение размеров пакетов и ложные ретрансмиссии.
6.  **Используйте `-T fields` вместо `-T json`**: JSON-формат создает значительно больше нагрузки на CPU и память.

### Сравнение tshark и tcpdump

| Характеристика | tshark | tcpdump |
| :--- | :--- | :--- |
| **Количество протоколов** | 3000+ (движок Wireshark) | ~100 (базовые) |
| **Фильтры отображения** | Да (L7, сложная логика) | Нет |
| **Анализ прикладного уровня** | Глубокий (HTTP/2, gRPC, DB) | Поверхностный |
| **Расшифровка TLS** | Поддерживается | Нет |
| **Ресурсоемкость** | Высокая | Низкая |
| **Формат вывода** | JSON, CSV, XML, EK | Текст |
| **Арифметика полей** | Да (Wireshark 4.x+) | Нет |

### Типичные ошибки и их решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `tshark: Lua: ...` | Ошибка в Lua-скрипте | Отключите скрипты: `-o lua_script:` |
| `Can't get hex offset` | Неверное имя поля | Проверьте через `-G fields` |
| `Permission denied` | Нет прав на интерфейс | `sudo` или `CAP_NET_RAW` |
| `No buffer space` | Малый буфер захвата | Увеличьте `-B 64` |
| `Broadcast filter` | Адаптер отбрасывает broadcast | Включите promiscuous: `-i eth0 -p` |
| `Kernel filter full` | Ядерный фильтр переполнен | Упростите BPF-фильтр или отключите `-f ""` |
| `Message too long` | Paket больше буфера | Увеличьте snaplen: `-s 0` |

### Версионные особенности

| Версия | Ключевые возможности |
| :--- | :--- |
| **Wireshark 3.0+** | DSB (Decryption Secrets Block) в pcapng |
| **Wireshark 3.4+** | Расшифровка QUIC через SSLKEYLOGFILE |
| **Wireshark 4.0+** | Арифметика полей в `-e`, улучшенная производительность |
| **Wireshark 4.2+** | TLS Keylog Launcher, автоматический запуск браузеров |
| **Wireshark 4.4+** | PQC (Post-Quantum Cryptography), сжатие LZ4, интервал 1 мкс в I/O Graphs |

### Управление памятью

Для работы с большими дампами (>1 ГБ):
```bash
# Потоковая обработка без загрузки всего файла в память
tshark -r large_file.pcap -T fields -e ip.src -e ip.dst | head -1000

# Ограничение глубины декодирования (экономия памяти)
tshark -r capture.pcap -T fields -e ip.src -e tcp.dstport  # Не декодировать HTTP/TLS

# Использование gzip для сжатия вывода
tshark -r capture.pcap -T fields -e ip.src -e ip.dst | gzip > output.txt.gz

# Анализ только заголовков (без payload)
tshark -r capture.pcap -T fields -e frame.number -e ip.src -e ip.dst -e tcp.srcport -e tcp.dstport -e tcp.flags
```

### См. также

- **[Wireshark — определения](./definitions.md)** — обзор всей экосистемы инструментов.
- **[Основные концепции захвата](./core_concepts.md)** — механизмы работы фильтров и интерфейсов.
- **[Методы расшифровки TLS](./tls_decryption_methods.md)** — детальное руководство по работе с ключами.
- **[tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)** — консольная утилита для быстрого захвата.
- **[Диагностика производительности TCP](./tcp_performance/tcp_performance_diagnostics.md)** — на какие поля смотреть в tshark.
- **[HTTP/2 и gRPC](./http2_grpc_analysis.md)** — tshark-команды для HTTP/2 и gRPC.
- **[Lua-скрипты](./lua_scripting.md)** — автоматизация анализа через Lua.
- **[eBPF-инструменты](./ebpf_diagnostics_tools.md)** — pwru, bpftrace, tcpflow как доп. к tshark.
