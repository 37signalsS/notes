# tshark — анализ трафика в командной строке

## Определения

**tshark** — консольный сетевой анализатор (сниффер), входящий в состав Wireshark. Он использует тот же движок диссекции протоколов и библиотеку захвата, что и графическая версия, но оптимизирован для работы в терминале, автоматизации через скрипты и анализа данных в конвейерах (pipelines).

В отличие от графического Wireshark, **tshark** может работать в режиме потоковой обработки, что позволяет анализировать файлы, размер которых превышает объем оперативной памяти, а также выполнять высокопроизводительный экспорт данных в структурированные форматы (JSON, CSV, Elasticsearch).

**tshark** является основным инструментом для выполнения глубокого анализа (L7) в средах без GUI (удаленные серверы, контейнеры) и для пакетной обработки больших массивов PCAP-файлов.

**termshark** — интерактивный TUI-интерфейс (аналог GUI Wireshark в терминале), работающий поверх `tshark`. См. **[Сетевые инструменты CLI и TUI](../../../Linux/Diagnostics/Networking/network_cli_tools.md#termshark)**.

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
| `-T <format>` | Формат | Формат вывода: `fields`, `json`, `ek` (ELK), `pdml`, `tabs` | — |
| `-e <field>` | Поля | Извлечение конкретного поля (только при `-T fields`) | Apply as Column |
| `-n` | Скорость | Отключить разрешение имен (DNS, MAC, Port) | — |
| `-q` | Тишина | Подавить вывод отдельных пакетов (используется для `-z`) | — |
| `-z <stat>` | Стат. | Сбор статистики (потоки, иерархия, эксперты и др.) | Statistics меню |
| `-o <pref>` | Опции | Переопределение настроек (например, TLS ключи) | Preferences |
| `-V` | Вывод | Максимальная детализация каждого пакета (Verbose) | Packet Details |

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
```

### Анализ прикладного уровня (HTTP, DNS, TLS)

```bash
# Извлечение всех запрашиваемых доменных имен из DNS
tshark -r capture.pcap -Y "dns.flags.response == 0" -T fields -e dns.qry.name

# Анализ HTTP User-Agent и запрошенных хостов
tshark -r capture.pcap -Y "http.request" -T fields -e http.host -e http.user_agent

# Расшифровка TLS с использованием файла ключей (SSLKEYLOGFILE)
tshark -r capture.pcap -o tls.keylog_file:/path/to/keys.log -Y "http2"

# Расшифровка TLS с приватным ключом сервера (только RSA без PFS)
tshark -r capture.pcap -o tls.keys_list:192.168.1.1,443,http,/path/to/server.key
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
```

### Длительный захват с кольцевым буфером (Ring Buffer)

Для предотвращения переполнения диска при длительном мониторинге:
```bash
# Сохранять файлы по 100 МБ, оставить последние 10 файлов
sudo tshark -i eth0 -b filesize:102400 -b files:10 -w continuous_capture.pcapng
```

### Автоматизация и экспорт в ELK/JSON

```bash
# Экспорт в JSON для последующей обработки через jq
tshark -r capture.pcap -T json | jq '.[]._source.layers.ip["ip.src"]'

# Экспорт в формате EK для прямой загрузки в Elasticsearch
tshark -r capture.pcap -T ek > elastic_data.json
```

## Дополнительная информация

### Оптимизация производительности

tshark потребляет значительно больше ресурсов, чем `tcpdump`. Для работы на высоких скоростях (1Gbps+):
1.  **Отключите разрешение имен (`-n`)**: Это критически важно для производительности.
2.  **Используйте `-f` вместо `-Y`**: Фильтры захвата работают в ядре (BPF) и гораздо эффективнее.
3.  **Используйте `dumpcap` для захвата**: А `tshark` только для анализа уже записанных файлов. `dumpcap` — самый легкий инструмент в экосистеме.
4.  **Увеличьте буфер захвата**: Опция `-B <size_in_MB>`.

### Сравнение tshark и tcpdump

| Характеристика | tshark | tcpdump |
| :--- | :--- | :--- |
| **Количество протоколов** | 3000+ (движок Wireshark) | ~100 (базовые) |
| **Фильтры отображения** | Да (L7, сложная логика) | Нет |
| **Анализ прикладного уровня** | Глубокий (HTTP/2, gRPC, DB) | Поверхностный |
| **Расшифровка TLS** | Поддерживается | Нет |
| **Ресурсоемкость** | Высокая | Низкая |

### См. также

- **[Wireshark — определения](./definitions.md)** — обзор всей экосистемы инструментов.
- **[Основные концепции захвата](./core_concepts.md)** — механизмы работы фильтров и интерфейсов.
- **[Методы расшифровки TLS](./tls_decryption_methods.md)** — детальное руководство по работе с ключами.
- **[tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)** — консольная утилита для быстрого захвата.
- **[Диагностика производительности TCP](./tcp_performance/tcp_performance_diagnostics.md)** — на какие поля смотреть в tshark.
