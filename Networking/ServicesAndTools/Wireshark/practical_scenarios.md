# Wireshark: Практические Сценарии

## Определения

**Follow Stream** — функция Wireshark, воссоздающая полный диалог клиент-сервер из пакетов одного TCP/UDP/HTTP потока в читаемом виде.

**Conversations** — агрегированный список всех сетевых взаимодействий в дампе с метриками (байты, пакеты, длительность).

**Protocol Hierarchy** — статистика распределения трафика по протоколам в захваченном дампе.

**Export Objects** — извлечение файлов (изображения, скрипты, документы), переданных внутри HTTP-трафика.

## Основные концепции

### Установка и права

| ОС | Команда | Права |
|---|---|---|
| **Debian/Ubuntu** | `sudo apt install wireshark` | `sudo usermod -aG wireshark $USER` + перелогин |
| **Fedora/RHEL** | `sudo dnf install wireshark` | `sudo usermod -aG wireshark $USER` + перелогин |

При установке на Debian/Ubuntu ответьте `Yes` на вопрос «Should non-superusers be able to capture packets?» — это настроит `POSIX capabilities` на `dumpcap`.

### Базовый рабочий процесс (GUI)

1. Запустите Wireshark → выберите активный интерфейс (подсвечен графикм активности)
2. Нажмите синюю кнопку (акулий плавник) или `Ctrl+E` — захват начат
3. Примените display-фильтр: `dns`, `http`, `tcp.port == 443`
4. Остановите захват (`Ctrl+E` или красная кнопка)
5. Сохраните: `File → Save As...` (`.pcapng`)

### Работа со временем

Временные метки — ключевой инструмент поиска задержек. Настройка: `View → Time Display Format`.

| Формат | Применение |
|---|---|
| `Seconds since beginning of capture` | По умолчанию, относительное время |
| `Seconds since previous displayed packet` | Измерение задержек между пакетами |
| `Date and Time of Day` | Сопоставление с логами других систем |
| `Time Reference` | Произвольная нулевая точка (ПКМ → `Set Time Reference`) |

**Полезный приём:** добавьте столбец `Time delta from previous displayed packet` (ПКМ по полю в Frame → `Apply as Column`) — постоянная видимость интервалов между пакетами.

## Практические сценарии

### Сценарий 1: Быстрый анализ дампа — что происходит?

Последовательность для первичного знакомства с неизвестным дампом:

1. `Statistics → Protocol Hierarchy` — какие протоколы присутствуют
2. `Statistics → Conversations` → сортировка по `Bytes` — кто больше всего передаёт
3. Примените фильтр по топ-протоколу из hierarchy (клик правой кнопкой → `Apply as Filter`)
4. `Statistics → Expert Information` — встроенный анализ аномалий (ретрансмиты, warnings)

### Сценарий 2: Восстановление диалога (Follow Stream)

Для анализа содержимого соединения:

1. Найдите пакет интересующего соединения
2. ПКМ → `Follow → TCP Stream` (или `UDP Stream`, `HTTP Stream`)
3. Откроется окно с полным диалогом в текстовом виде
4. Переключайте формат: Raw Hex, ASCII, EBCDIC, UTF-8
5. Кнопка `Save as` — экспорт потока в файл

Wireshark автоматически применит display-фильтр `tcp.stream eq N`, отфильтровав весь остальной трафик.

### Сценарий 3: Динамическое добавление столбцов

Для быстрого обзора полей протокола без написания фильтров:

1. Раскройте нужное поле в «Packet Details» (например, `http.request.uri`)
2. ПКМ → `Apply as Column`
3. Новый столбец появится в главном окне для всех пакетов

Полезные поля для столбцов: `http.request.uri`, `tcp.port`, `kafka.topic`, `pgsql.query`, `dns.qry.name`.

### Сценарий 4: Извлечение файлов из HTTP-трафика

`File → Export Objects → HTTP` — список всех переданных файлов с MIME-типами и размерами. Полезно для:
- Анализа загруженных/скачанных файлов
- Поиска подозрительных исполняемых файлов в трафике
- Извлечения контента без реконструкции вручную

### Сценарий 5: Анализ специфичных протоколов

#### Kafka (порт 9092)

| Поле | Описание |
|---|---|
| `kafka.topic` | Имя топика |
| `kafka.value` | Содержимое сообщения |
| `kafka.api_key` | Тип операции (Produce, Fetch, Metadata...) |

**Типичная проблема:** Producer пишет в один топик, Consumer читает из другого. Добавление `kafka.topic` в столбец сразу выявляет несоответствие.

#### PostgreSQL (порт 5432)

| Поле | Описание |
|---|---|
| `pgsql.query` | Текст SQL-запроса |
| `pgsql.row_count` | Количество затронутых строк |

Добавьте `pgsql.query` в столбец — видны все SELECT/INSERT/UPDATE/DELETE. Полезно для отладки ORM.

#### MS SQL / TDS (порт 1433)

| Поле | Описание |
|---|---|
| `tds.procname` | Имя хранимой процедуры |
| `tds.paramname` / `tds.paramvalue` | Параметры процедуры |
| `tds.sql_batch` | Текст SQL-батча |

#### MongoDB (порт 27017)

| Поле | Описание |
|---|---|
| `mongodb.op_code` | Тип операции (OP_QUERY, OP_INSERT, OP_MSG) |
| `mongodb.query` | JSON-запрос |
| `mongodb.document` | Содержимое документа |

### Сценарий 6: Настройка временной точки отсчёта

При длительном захвате удобно «привязать» время к конкретному событию:

1. Найдите пакет-маркер (например, первый HTTP-запрос к проблемному сервису)
2. ПКМ → `Set Time Reference`
3. Переключите формат: `View → Time Display Format → Seconds since Reference`

Теперь все временные метки показывают время относительно выбранного события. Можно установить несколько точек — последняя применяется.

### Сценарий 7: Фильтры для распространённых протоколов

Подробное описание TCP-флагов и механизмов фильтрации: **[Основные концепты](./core_concepts.md#фильтрация-трафика)**.

Краткая справка по display-фильтрам:

| Протокол | Фильтр | Что показывает |
|---|---|---|
| **ICMP** | `icmp` | Echo request/reply, RTT, потери |
| **DNS** | `dns` | Запросы/ответы, типы записей (A, AAAA, CNAME, MX) |
| **DNS** | `dns.flags.authoritative == 1` | Только авторитетные ответы |
| **DNS** | `dns.qry.name contains "example"` | Запросы с подстрокой |
| **TCP** | `tcp.flags.syn == 1 && tcp.flags.ack == 0` | Новые соединения (SYN) |
| **TCP** | `tcp.flags.fin == 1` | Завершение соединений |
| **HTTP** | `http.request.method == "POST"` | POST-запросы |
| **HTTP** | `http.response.code == 500` | Серверные ошибки |

### Сценарий 8: Диагностика производительности TCP

Полный разбор: **[Диагностика производительности TCP](tcp_performance/tcp_performance_diagnostics.md)**.

Краткий чек-лист:

| Проблема | Признаки в Wireshark | Инструмент |
|---|---|---|
| **Тормозит сервер** | RTT стабильный (μs), большой Delta Time на сервере | Time-Sequence Graph |
| **Тормозит клиент** | Высокий RTT (ms), TCP Window Full/Zero Window | Window Scaling Graph |
| **Потери в сети** | Retransmit > 1%, DupACK, провалы скорости | IO Graphs, Expert Information |
| **Offloading** | «Bad checksum» но скорость стабильна | [Диагностика offloading](tcp_performance/tcp_network_losses_and_offloading.md) |

## Дополнительная информация

### Связанные документы

- **[Определения Wireshark](./definitions.md)** — инструменты, форматы, области применения
- **[Основные концепты](./core_concepts.md)** — механизмы захвата, фильтры, инкапсуляция
- **[Дополнительные возможности](./advanced_features.md)** — coloring rules, flow graph, комментарии, hotkeys
- **[Диагностика производительности TCP](tcp_performance/tcp_performance_diagnostics.md)** — полный разбор узких мест
- **[Методы расшифровки TLS](./tls_decryption_methods.md)** — SSLKEYLOGFILE, MITM, обход SSL Pinning
- **[Использование tshark](./tshark_usage.md)** — консольные команды, экспорт данных
