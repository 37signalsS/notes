# tshark — анализ трафика в командной строке

## Определения

**tshark** — консольный анализатор сетевых протоколов, входящий в состав Wireshark. Он позволяет захватывать пакеты с сетевого интерфейса или разбирать существующие файлы дампов (pcap/pcapng).

**tshark** использует ту же кодовую базу и движок диссекции, что и графическая версия Wireshark, обеспечивая идентичный уровень детализации при анализе трафика.

**TUI-альтернатива:** для интерактивного анализа в терминале (аналог GUI Wireshark) рекомендуется использовать **[termshark](../../../Linux/Diagnostics/Networking/network_cli_tools.md#termshark)**.

## Основные концепции

### Установка

| ОС | Команда |
| :--- | :--- |
| **Debian / Ubuntu** | `sudo apt install tshark` |
| **Fedora / RHEL** | `sudo dnf install wireshark-cli` |
| **macOS** | `brew install wireshark` |

### Ключевые флаги и параметры

| Флаг | Тип | Описание | Аналог в GUI |
| :--- | :--- | :--- | :--- |
| `-i <iface>` | Захват | Выбор сетевого интерфейса | Список на старте |
| `-c <count>` | Захват | Остановка после захвата N пакетов | — |
| `-w <file>` | Захват | Запись «сырых» пакетов в файл | `File → Save As` |
| `-r <file>` | Ввод | Чтение данных из файла (pcap/pcapng) | `File → Open` |
| `-f "..."` | Фильтр | Фильтр захвата (BPF-синтаксис tcpdump) | Capture Filter |
| `-Y "..."` | Фильтр | Фильтр отображения (синтаксис Wireshark) | Display Filter |
| `-D` | Инфо | Список доступных интерфейсов | — |
| `-T fields -e ...` | Вывод | Экспорт конкретных полей протокола | Apply as Column |
| `-T json` | Вывод | Экспорт всей структуры пакета в JSON | — |
| `-q -z <stat>` | Стат. | Сбор статистики (потоки, иерархия и др.) | Statistics меню |
| `-o key=value` | Опции | Переопределение настроек (например, TLS ключи) | Preferences |
| `-V` | Вывод | Максимальная детализация (Verbose) | Packet Details |

### Работа с фильтрами

В tshark разделяются два типа фильтрации:

1. **Capture Filter (`-f`)**: Применяется библиотекой `libpcap` до записи на диск. Экономит ресурсы и место.
2. **Display Filter (`-Y`)**: Применяется движком Wireshark к уже захваченным или считанным данным. Поддерживает всю мощь логики диссекции.

Подробнее о синтаксисе: **[Фильтрация в Wireshark](./core_concepts.md#фильтрация-трафика)**.

## Практические сценарии

### Сценарий 1: Захват трафика на удалённом сервере

```bash
# Список интерфейсов с индексами
tshark -D

# Захват первых 100 пакетов с интерфейса eth0 в файл
sudo tshark -i eth0 -c 100 -w capture.pcapng

# Захват только трафика HTTP (порт 80) с использованием фильтра захвата
sudo tshark -i eth0 -f "tcp port 80" -w http_only.pcap
```

### Сценарий 2: Анализ и извлечение данных из дампа

```bash
# Чтение файла с фильтром отображения
tshark -r capture.pcapng -Y "http.request"

# Вывод только IP-адресов отправителя и получателя в консоль
tshark -r capture.pcapng -T fields -e ip.src -e ip.dst

# Полная расшифровка одного пакета (например, DNS)
tshark -r capture.pcapng -Y "dns" -V -c 1
```

### Сценарий 3: Экспорт данных для автоматизации

```bash
# Экспорт в CSV: IP источника, IP назначения и длина кадра
tshark -r capture.pcapng -T fields \
  -e ip.src -e ip.dst -e frame.len \
  -E header=y -E separator=, -E quote=d > report.csv

# Извлечение всех запрашиваемых доменных имён из DNS-трафика
tshark -r capture.pcapng -Y "dns.flags.response == 0" -T fields -e dns.qry.name

# Получение списка всех HTTP User-Agent
tshark -r capture.pcapng -Y "http.user_agent" -T fields -e http.user_agent | sort | uniq
```

### Сценарий 4: Сбор сетевой статистики

```bash
# Иерархия протоколов (процентное соотношение трафика)
tshark -r capture.pcapng -q -z io,phs

# Список всех IP-диалогов (Conversations)
tshark -r capture.pcapng -q -z conv,ip

# Статистика ответов HTTP (коды состояний)
tshark -r capture.pcapng -q -z http,tree
```

### Сценарий 5: Расшифровка защищённого трафика (TLS)

```bash
# Использование файла с сессионными ключами SSLKEYLOGFILE
tshark -r capture.pcapng -o tls.keylog_file:/path/to/keys.log -Y "http2"

# Расшифровка с использованием приватного ключа (только RSA без PFS)
tshark -r capture.pcapng -o tls.keys_list:192.168.1.10,443,http,/path/to/server.key
```

Методология расшифровки: **[Методы расшифровки TLS](./tls_decryption_methods.md)**.

### Сценарий 6: Непрерывный захват с ротацией файлов

Используется для мониторинга инцидентов на высоконагруженных серверах без переполнения диска:

```bash
# Создавать новый файл каждые 100 МБ, хранить последние 10 файлов
sudo tshark -i eth0 -b filesize:100000 -b files:10 -w /tmp/rotation.pcapng
```

## Дополнительная информация

### Сравнение tshark и tcpdump

| Характеристика | tshark | tcpdump |
| :--- | :--- | :--- |
| **Количество протоколов** | 3000+ (движок Wireshark) | ~100 (базовые) |
| **Фильтры отображения** | Да (сложная логика) | Нет |
| **Анализ прикладного уровня** | Глубокий (L7) | Поверхностный |
| **Расшифровка TLS** | Поддерживается | Нет |
| **Ресурсоёмкость** | Высокая | Низкая |

### См. также

- **[Определения и инструменты Wireshark](./definitions.md)** — обзор всей экосистемы.
- **[Основные концепты захвата](./core_concepts.md)** — детали работы фильтров и интерфейсов.
- **[Методы расшифровки TLS](./tls_decryption_methods.md)** — подробнее о работе с ключами.
- **[tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)** — инструмент для быстрого захвата.
- **[termshark](../../../Linux/Diagnostics/Networking/network_cli_tools.md#termshark)** — интерактивный TUI для tshark.
