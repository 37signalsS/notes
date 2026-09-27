# Анализ HTTP/2 и gRPC в Wireshark

> **SSoT:** Определения HTTP/2 и gRPC — в **[HTTP/2 и HTTP/3](../../../WebServers/Concepts/web_performance/http2_http3.md)**. Типы фреймов и HPACK — в **[Версии HTTP](../../../Networking/Protocols/HTTP/http_versions.md)**. Обзор gRPC — в **[gRPC Overview](../../../Networking/ServicesAndTools/grpc_overview.md)**. TLS расшифровка — в **[Методы расшифровки TLS](./tls_decryption_methods.md)**. Концепции захвата — в **[Основные концепции](./core_concepts.md)**.

## Определения

**HTTP/2 (RFC 9113)** — бинарный протокол уровня приложения, использующий фреймы для мультиплексирования нескольких логических потоков (Streams) поверх одного TCP-соединения. Каждый фрейм содержит заголовок 9 байт: Length (3), Type (1), Flags (1), Stream Identifier (4).

**Frame Type (Тип фрейма)** — идентификатор типа HTTP/2 фрейма: `DATA` (0x0), `HEADERS` (0x1), `PRIORITY` (0x2), `RST_STREAM` (0x3), `SETTINGS` (0x4), `PUSH_PROMISE` (0x5), `PING` (0x6), `GOAWAY` (0x7), `WINDOW_UPDATE` (0x8), `CONTINUATION` (0x9).

**Stream (Поток HTTP/2)** — логическое двунаправленное соединение внутри одного TCP-соединения. Идентифицируется уникальным `Stream ID`: нечётные — инициированы клиентом, чётные — сервером.

**HPACK (RFC 7541)** — алгоритм сжатия заголовков HTTP/2. Использует статический словарь (61 предопределённый заголовок), динамический словарь (изменяется в рамках сессии) и Huffmank-кодирование. Защита от атак: `SETTINGS_MAX_HEADER_LIST_SIZE`, `SETTINGS_MAX_HEADER_TABLE_SIZE`.

**gRPC** — высокопроизводительный RPC-фреймворк поверх HTTP/2 и Protocol Buffers. Поддерживает 4 паттерна: Unary, Server Streaming, Client Streaming, Bidirectional Streaming. Каждый gRPC-вызов — это HTTP/2 POST-запрос с `Content-Type: application/grpc` и trailers (HTTP/2 END_STREAM).

**gRPC Status Code** — код завершения RPC-вызова, передаваемый в HTTP/2 trailers: `OK` (0), `CANCELLED` (1), `UNKNOWN` (2), `DEADLINE_EXCEEDED` (4), `NOT_FOUND` (5), `UNAVAILABLE` (14), `UNAUTHENTICATED` (16).

**RST_STREAM** — HTTP/2 фрейм для принудительного завершения потока. Часто указывает на ошибку приложения, таймаут или отмену запроса.

**GOAWAY** — HTTP/2 фрейм, отправляемый сервером для уведомления клиента о завершении работы с TCP-соединением. Содержит `Last-Stream-ID`, до которого сервер обработает запросы. Используется для graceful shutdown.

## Quick-Start: Чек-лист анализа HTTP/2/gRPC

| Шаг | Действие | Как проверить |
| :--- | :--- | :--- |
| **1** | Расшифровать TLS | `SSLKEYLOGFILE` или DSB в pcapng |
| **2** | Найти SETTINGS | `http2.type == 4` — проверить согласованные лимиты |
| **3** | Проверить RST_STREAM | `http2.type == 3` — поиск ошибок потока |
| **4** | Проверить GOAWAY | `http2.type == 7` — graceful shutdown |
| **5** | Проверить WINDOW_UPDATE | `http2.type == 8` — flow control |
| **6** | Найти gRPC ошибки | `grpc.status != 0` — ошибки приложения |
| **7** | Проверить latencies | `http2.headers.method` + `http2.headers.status` |

## Основные концепции

### Ключевые Display-фильтры

```bash
# Все HTTP/2 фреймы
http2

# Только DATA фреймы (полезная нагрузка)
http2.type == 0

# Только HEADERS фреймы (заголовки запроса/ответа)
http2.type == 1

# SETTINGS (согласование параметров)
http2.type == 4

# RST_STREAM (ошибки потока)
http2.type == 3

# GOAWAY (завершение соединения)
http2.type == 7

# WINDOW_UPDATE (flow control)
http2.type == 8

# HTTP/2 запросы (метод + URI)
http2.headers.method && http2.headers.path

# HTTP/2 ответы (статус-код)
http2.headers.status

# Все HTTP/2 ошибки (4xx/5xx)
http2.headers.status >= 400

# gRPC-вызовы (POST с Content-Type: application/grpc)
http2.headers.method == "POST" && http2.headers.content_type == "application/grpc"

# gRPC ошибки (в trailers)
grpc.status != 0
```

### Извлечение полей через tshark

```bash
# Метод, URI и статус HTTP/2
tshark -r capture.pcap -Y "http2" -T fields \
  -e frame.number -e http2.headers.method -e http2.headers.path \
  -e http2.headers.status -e http2.streamid

# Статистика HTTP/2 кодов ответов
tshark -r capture.pcap -Y "http2.headers.status" -T fields \
  -e http2.headers.status | sort | uniq -c | sort -rn

# Анализ gRPC-вызовов с задержками
tshark -r capture.pcap -Y "http2.headers.method == \"POST\" && http2.headers.content_type == \"application/grpc\"" \
  -T fields -e frame.time_relative -e ip.src -e ip.dst \
  -e http2.headers.path -e grpc.status -e tcp.analysis.ack_rtt

# Поиск RST_STREAM с указанием потока
tshark -r capture.pcap -Y "http2.type == 3" -T fields \
  -e frame.number -e http2.streamid -e http2.rst_stream.errorcode

# GOAWAY с Last-Stream-ID
tshark -r capture.pcap -Y "http2.type == 7" -T fields \
  -e frame.number -e http2.goaway.laststreamid -e http2.goaway.errorcode

# Настройка окна (SETTINGS)
tshark -r capture.pcap -Y "http2.type == 4" -T fields \
  -e frame.number -e http2.settings.header_table_size \
  -e http2.settings.max_concurrent_streams \
  -e http2.settings.initial_window_size
```

### Типы фреймов и их диагностика

| Тип | Код | Назначение | Типичная проблема |
| :--- | :--- | :--- | :--- |
| **DATA** | 0x0 | Полезная нагрузка | Потери, задержки |
| **HEADERS** | 0x1 | Заголовки запроса/ответа | HPACK ошибки |
| **PRIORITY** | 0x2 | Приоритет потока | Деприцирован в RFC 9113 |
| **RST_STREAM** | 0x3 | Принудительное завершение | Ошибка приложения, таймаут |
| **SETTINGS** | 0x4 | Согласование параметров | Конфликт лимитов |
| **PUSH_PROMISE** | 0x5 | Серверный push | Деприцирован |
| **PING** | 0x6 | Проверка соединения | RTT измерение |
| **GOAWAY** | 0x7 | Завершение соединения | Graceful shutdown |
| **WINDOW_UPDATE** | 0x8 | Изменение окна | Flow control deadlock |
| **CONTINUATION** | 0x9 | Продолжение заголовков | Большие заголовки |

### Диагностика через Expert Info

Wireshark автоматически помечает аномалии HTTP/2:

```bash
# Все экспертные сообщения для HTTP/2
tshark -r capture.pcap -Y "http2 && tcp.analysis.flags" -T fields \
  -e frame.number -e tcp.analysis.flags -e http2.type -e http2.streamid

# Поиск пакетов с ошибками в конкретном потоке
tshark -r capture.pcap -Y "http2.streamid == 5 && tcp.analysis.retransmission" -T fields \
  -e frame.number -e frame.time_relative -e tcp.analysis.retransmission
```

## Практические сценарии

### Сценарий 1: Анализ RST_STREAM — поиск ошибок gRPC

RST_STREAM фрейм содержит код ошибки, который помогает локализовать проблему:

```bash
# Все RST_STREAM с кодами ошибок
tshark -r capture.pcap -Y "http2.type == 3" -T fields \
  -e frame.number -e http2.streamid -e http2.rst_stream.errorcode -e ip.src -e ip.dst

# Коды ошибок RST_STREAM:
# 0x0 = NO_ERROR          → graceful cancel
# 0x1 = PROTOCOL_ERROR    → нарушение протокола
# 0x2 = INTERNAL_ERROR    → внутренняя ошибка сервера
# 0x3 = FLOW_CONTROL_ERROR → нарушение flow control
# 0x4 = SETTINGS_TIMEOUT  → таймаутSETTINGS
# 0x8 = CANCEL            → клиент отменил запрос
# 0xa = ENHANCE_YOUR_CALM → клиент слишком агрессивен
# 0xb = INADEQUATE_SECURITY → недостаточная безопасность TLS

# Статистика RST_STREAM по кодам
tshark -r capture.pcap -Y "http2.type == 3" -T fields \
  -e http2.rst_stream.errorcode | sort | uniq -c | sort -rn
```

**Интерпретация:**
- Много `CANCEL` (0x8) → клиент отменяет запросы (таймаут приложения)
- Много `INTERNAL_ERROR` (0x2) → проблема на сервере
- Много `ENHANCE_YOUR_CALM` (0xb) → клиент генерирует слишком много потоков
- Много `FLOW_CONTROL_ERROR` (0x3) → deadlock flow control

### Сценарий 2: Анализ GOAWAY — graceful shutdown

GOAWAY содержит `Last-Stream-ID` — сервер обработает запросы с ID ≤ этого значения:

```bash
# Поиск GOAWAY
tshark -r capture.pcap -Y "http2.type == 7" -T fields \
  -e frame.number -e http2.goaway.laststreamid -e http2.goaway.errorcode \
  -e ip.src -e tcp.srcport

# Коды ошибок GOAWAY:
# 0x0 = NO_ERROR          → graceful shutdown
# 0x1 = PROTOCOL_ERROR    → нарушение протокола
# 0x2 = INTERNAL_ERROR    → внутренняя ошибка

# Проверка: есть ли запросы с ID > Last-Stream-ID после GOAWAY
tshark -r capture.pcap -Y "http2.streamid > <LAST_STREAM_ID> && frame.time_relative > <GOAWAY_TIME>" \
  -T fields -e frame.number -e http2.streamid -e http2.headers.path
```

### Сценарий 3: Анализ flow control — WINDOW_UPDATE

```bash
# Все WINDOW_UPDATE фреймы
tshark -r capture.pcap -Y "http2.type == 8" -T fields \
  -e frame.number -e http2.streamid -e http2.window_update_increment

# Потоки с нулевым окном (deadlock risk)
tshark -r capture.pcap -Y "http2.type == 8 && http2.window_update_increment == 0" -T fields \
  -e frame.number -e http2.streamid

# Проверка SETTINGS_MAX_FRAME_SIZE и INITIAL_WINDOW_SIZE
tshark -r capture.pcap -Y "http2.type == 4" -T fields \
  -e http2.settings.max_frame_size -e http2.settings.initial_window_size
```

### Сценарий 4: Диагностика HPACK Bomb/Flood

Атака через экспансию динамического словаря HPACK:

```bash
# Поиск SETTINGS с аномальными размерами HPACK
tshark -r capture.pcap -Y "http2.type == 4" -T fields \
  -e http2.settings.header_table_size -e http2.settings.max_header_list_size

# Нормальные значения:
# header_table_size: 4096 (по умолчанию)
# max_header_list_size: не ограничен или > 8192

# Поиск HEADERS с подозрительно большими заголовками
tshark -r capture.pcap -Y "http2.type == 1 && http2.headers.length > 4096" -T fields \
  -e frame.number -e http2.streamid -e http2.headers.length
```

### Сценарий 5: Мультиплексирование и head-of-line blocking

```bash
# Все потоки в одном TCP-соединении
tshark -r capture.pcap -Y "http2" -T fields \
  -e http2.streamid | sort -u | wc -l

# Потоки с ретрансмиссиями (TCP-level HOL blocking)
tshark -r capture.pcap -Y "http2 && tcp.analysis.retransmission" -T fields \
  -e http2.streamid | sort | uniq -c | sort -rn

# Среднее количество активных потоков
tshark -r capture.pcap -Y "http2.type == 1" -q \
  -z "io,stat,1,COUNT(http2.streamid)http2.streamid"
```

### Сценарий 6: Анализ gRPC Streaming

```bash
# Server Streaming: один запрос, много ответов
tshark -r capture.pcap -Y "http2.headers.method == \"POST\" && grpc.method == \"server_streaming\"" \
  -T fields -e http2.streamid -e http2.headers.path

# Bidirectional Streaming: поток DATA фреймов в обоих направлениях
tshark -r capture.pcap -Y "http2.streamid == <STREAM_ID> && http2.type == 0" -T fields \
  -e frame.time_relative -e ip.src -e tcp.len

# trailers (END_STREAM на последнем DATA)
tshark -r capture.pcap -Y "http2.streamid == <STREAM_ID> && http2.flags == 0x1" -T fields \
  -e frame.number -e http2.flags
```

### Сценарий 7: Извлечение payload из gRPC через Export Objects

```bash
# Экспорт HTTP/2 объектов через GUI: File → Export Objects → HTTP/2
# Или через tshark:
tshark -r capture.pcap -Y "http2.type == 0 && http2.streamid == 5" -T fields \
  -e http2.data.data | head -20

# Декодирование Protobuf (требуется .proto файл):
# Используйте Wireshark: правый клик на DATA → Decode As → Protobuf
```

## Дополнительная информация

### Сравнение HTTP/1.1 и HTTP/2 в Wireshark

| Характеристика | HTTP/1.1 | HTTP/2 |
| :--- | :--- | :--- |
| **Соединения** | По одному на запрос (Keep-Alive) | Одно соединение, мультиплексирование |
| **Формат** | Текстовый | Бинарный |
| **Заголовки** | Сжатие не предусмотрено | HPACK |
| **Приоритеты** | Нет | Stream prioritization |
| **Flow Control** | Нет (только TCP RWND) | Собственный (WINDOW_UPDATE) |
| **Filtri в Wireshark** | `http`, `http.request`, `http.response` | `http2`, `http2.type`, `http2.streamid` |

Подробный разбор анализа HTTP/1.1 поверх TLS (включая инкапсуляцию, фильтрацию по SNI и расшифровку) — в **[Анализ HTTPS в Wireshark](./https_analysis.md)**.

### Типичные проблемы HTTP/2/gRPC

| Проблема | Симптом в Wireshark | Фильтр | Решение |
| :--- | :--- | :--- | :--- |
| **RST_STREAM CANCEL** | Клиент отменяет запросы | `http2.rst_stream.errorcode == 8` | Увеличить таймауты клиента |
| **RST_STREAM INTERNAL_ERROR** | Сервер сбрасывает потоки | `http2.rst_stream.errorcode == 2` | Проверить логи сервера |
| **GOAWAY** | Сервер завершает соединение | `http2.type == 7` | Проверить graceful shutdown |
| **Flow Control Deadlock** | Потоки зависают | `http2.window_update_increment == 0` | Увеличить INITIAL_WINDOW_SIZE |
| **HPACK Bomb** | Высокий CPU на декодировании | `http2.headers.length > 8192` | `max_headers 100` |
| **TCP HOL Blocking** | Ретрансмиссии затрагивают все потоки | `tcp.analysis.retransmission && http2` | Перейти на HTTP/3 (QUIC) |
| **SETTINGS Timeout** | `SETTINGS_TIMEOUT` RST_STREAM | `http2.rst_stream.errorcode == 4` | Увеличить таймаут на SETTINGS ACK |

### См. также
- **[Определения Wireshark](./definitions.md)** — базовые термины
- **[Методы расшифровки TLS](./tls_decryption_methods.md)** — расшифровка HTTP/2 трафика
- **[Использование tshark](./tshark_usage.md)** — CLI-команды для анализа
- **[HTTP/2 и HTTP/3](../../../WebServers/Concepts/web_performance/http2_http3.md)** — теория протоколов
- **[Версии HTTP](../../../Networking/Protocols/HTTP/http_versions.md)** — типы фреймов и HPACK
- **[gRPC Overview](../../../Networking/ServicesAndTools/grpc_overview.md)** — обзор gRPC
- **[Service Mesh Analysis](./service_mesh_analysis.md)** — анализ mTLS трафика
