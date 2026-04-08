# Wireshark: Использование tshark (командная строка)

## Определения

**tshark** — консольная версия Wireshark. Поддерживает capture/display-фильтры, экспорт данных в CSV/JSON, статистический анализ. Работает на той же кодовой базе, что и Wireshark GUI, поэтому обеспечивает идентичную диссекцию протоколов.

**TUI-альтернатива:** для интерактивного анализа трафика в терминале — **[termshark](../../../Linux/Diagnostics/Networking/network_cli_tools.md#termshark-tui)** — TUI-обёртка над tshark с навигацией в стиле Wireshark.

## Основные концепции

### Установка

| ОС | Команда |
|---|---|
| **Debian/Ubuntu** | `sudo apt install tshark` (или входит в пакет `wireshark`) |
| **Fedora/RHEL** | `sudo dnf install wireshark-cli` |
| **macOS** | `brew install wireshark` (включает tshark) |

### Ключевые флаги

| Флаг | Тип | Описание | Аналог в Wireshark |
|---|---|---|---|
| `-i <iface>` | Capture | Интерфейс захвата | Выбор интерфейса на старте |
| `-c <count>` | Capture | Остановить после N пакетов | — |
| `-w <file>` | Capture | Запись в файл (pcap/pcapng) | `File → Save As` |
| `-r <file>` | Input | Чтение из файла | `File → Open` |
| `-f "..."` | Capture | Capture-фильтр (синтаксис tcpdump) | Capture Filter |
| `-Y "..."` | Display | Display-фильтр (синтаксис Wireshark) | Display Filter |
| `-D` | Info | Список интерфейсов | Список на стартовом экране |
| `-T fields -e ...` | Output | Экспорт выбранных полей | Apply as Column |
| `-T json` | Output | Экспорт в JSON | — |
| `-q -z <stat>` | Stats | Статистика (conv, phs, io, ...) | Statistics меню |
| `-o key=value` | Options | Настройки (TLS keylog, preferences) | Edit → Preferences |
| `-V` | Output | Полная детализация пакета (verbose) | Packet Details |
| `-x` | Output | HEX-дампе пакета (в сочетании с `-V`) | Packet Bytes |

### Синтаксис фильтров

Capture-фильтры (`-f`) и display-фильтры (`-Y`) используют тот же синтаксис, что и Wireshark GUI:

```bash
# Capture filter (tcpdump-синтаксис)
-f "host 192.168.1.1 and port 443"

# Display filter (Wireshark-синтаксис)
-Y "ip.addr == 192.168.1.1 && tcp.port == 443"
-Y "http.request.method == POST"
-Y "tls.handshake.type == 1"
```

Подробное описание различий: **[Фильтрация трафика](./core_concepts.md#фильтрация-трафика)**.

## Практические сценарии

### Сценарий 1: Захват трафика на сервере без GUI

```bash
# Список интерфейсов
sudo tshark -D

# Захват 100 пакетов с сохранением в файл
sudo tshark -i eth0 -c 100 -w capture.pcapng

# Захват только HTTP (capture filter — экономия места)
sudo tshark -i eth0 -f "tcp port 80" -w http.pcap

# Захват всего, фильтрация при выводе (display filter)
sudo tshark -i eth0 -Y "ip.addr == 10.0.0.5" -w filtered.pcapng
```

> **Правило:** capture filter (`-f`) — для уменьшения размера файла, display filter (`-Y`) — для анализа. При записи с `-Y` пакеты, не прошедшие фильтр, не сохраняются.

### Сценарий 2: Чтение и анализ существующего дампа

```bash
# Чтение файла с display-фильтром
tshark -r capture.pcapng -Y "http.request"

# Показать только IP-адреса источников и назначений
tshark -r capture.pcapng -Y "ip.addr == 10.0.0.1" -T fields -e ip.src -e ip.dst

# Подробная детализация каждого пакета
tshark -r capture.pcapng -Y "tcp.port == 443" -V

# HEX-дампе содержимого пакетов
tshark -r capture.pcapng -Y "dns" -x
```

### Сценарий 3: Экспорт данных для обработки

```bash
# Экспорт в CSV: src IP, dst IP, длина пакета
tshark -r capture.pcapng -T fields \
  -e ip.src -e ip.dst -e frame.len \
  -E header=y -E separator=, -E quote=d \
  > packets.csv

# Экспорт в JSON (для jq, Python, и т.д.)
tshark -r capture.pcapng -T json > packets.json

# Извлечение HTTP URI
tshark -r capture.pcapng -Y "http.request" -T fields -e http.request.full_uri

# Извлечение DNS-запросов
tshark -r capture.pcapng -Y "dns.flags.response == 0" -T fields -e dns.qry.name
```

### Сценарий 4: Статистический анализ

```bash
# Топ диалогов по IP (conversations)
tshark -r capture.pcapng -q -z conv,ip

# Топ диалогов по TCP-портам
tshark -r capture.pcapng -q -z conv,tcp

# Иерархия протоколов (какие протоколы присутствуют)
tshark -r capture.pcapng -q -z io,phs

# HTTP-статистика (методы, коды ответов)
tshark -r capture.pcapng -q -z http,tree

# DNS-статистика (топ запрашиваемых доменов)
tshark -r capture.pcapng -q -z dns,tree

# IO Graph — трафик во времени (1-секундные интервалы)
tshark -r capture.pcapng -q -z io,stat,1
```

### Сценарий 5: Расшифровка TLS-трафика

```bash
# С использованием SSLKEYLOGFILE
tshark -r capture.pcapng \
  -o tls.keylog_file:/path/to/tls-keys.log \
  -Y "http2"

# С приватным ключом сервера (RSA, без PFS)
tshark -r capture.pcapng \
  -o tls.keys_list:192.168.1.100,443,http,/path/to/server.key
```

Полное руководство по методам расшифровки: **[Методы расшифровки TLS](./tls_decryption_methods.md)**.

### Сценарий 6: Непрерывный захват с ротацией файлов

Для продакшен-серверов с ограничением дискового пространства:

```bash
# Ротация по размеру (100 МБ на файл, максимум 10 файлов)
sudo tshark -i eth0 \
  -b filesize:100000 -b files:10 \
  -w /var/log/capture/capture.pcapng

# Ротация по времени (1 файл в час, максимум 24)
sudo tshark -i eth0 \
  -b duration:3600 -b files:24 \
  -w /var/log/capture/capture.pcapng
```

Старые файлы автоматически удаляются при достижении лимита.

## Дополнительная информация

### Сравнение с tcpdump

| Критерий | tshark | tcpdump |
|---|---|---|
| **Диссекция протоколов** | 2000+ протоколов | ~100 базовых |
| **Display-фильтры** | Полный синтаксис Wireshark | Только BPF (capture) |
| **Экспорт** | CSV, JSON, XML, текст | Текст, pcap |
| **Статистика** | `-z` (conversations, hierarchy, IO) | Нет |
| **Расшифровка TLS** | Да (SSLKEYLOGFILE, RSA keys) | Нет |
| **Размер** | ~50 МБ (зависимости) | ~500 КБ |
| **Применение** | Глубокий анализ | Быстрый захват |

### Связанные документы

- **[Определения Wireshark](./definitions.md)** — инструменты, форматы, сравнение
- **[Основные концепты](./core_concepts.md)** — фильтры, инкапсуляция, name resolution
- **[Практические сценарии](./practical_scenarios.md)** — GUI-анализ, протоколы, время
- **[Методы расшифровки TLS](./tls_decryption_methods.md)** — SSLKEYLOGFILE, MITM
- **[tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)** — консольный захват, BPF-фильтры
- **[termshark](../../../Linux/Diagnostics/Networking/network_cli_tools.md#termshark-tui)** — TUI-интерфейс для tshark
