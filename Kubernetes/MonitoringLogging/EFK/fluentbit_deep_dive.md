# Fluentd vs Fluent Bit: Обзор и глубокое погружение в Fluent Bit

## 1. Назначение Fluentd и Fluent Bit: сходства и различия

Fluentd и Fluent Bit — это компоненты одной экосистемы для сбора, обработки и доставки логов. Их объединяет модель конвейера `inputs → filters → outputs`, гибкая маршрутизация по тегам и богатая поддержка форматов (JSON, лог-файлы, структурированные события). Главная идея — отделить генерацию логов от систем хранения и аналитики, добавив слой нормализации, обогащения и надежной доставки.

### Роли и архитектурные особенности

- **Fluent Bit** — легковесный агент, написанный на C. Оптимизирован для edge-сценариев: узлы Kubernetes, IoT, ограниченные ресурсы. Обычно устанавливается как DaemonSet, читает логи приложений, выполняет минимальную обработку и пересылает их дальше.
- **Fluentd** — полнофункциональный агрегатор с развитой экосистемой плагинов (написан на Ruby/C). Подходит для центральной точки маршрутизации: нормализация, обогащение, дедупликация, сложные маршруты, долгосрочные буферы и ретраи.

Оба поддерживают TLS, сжатие, повторные попытки с экспоненциальной задержкой, парсинг мультистрочных логов и базовые трансформации. Отличия проявляются в производительности, потреблении ресурсов и глубине возможностей.

### Сравнение по ключевым критериям

| Критерий | Fluent Bit | Fluentd |
| :--- | :--- | :--- |
| **Назначение** | Агент на узле, edge | Центральный агрегатор |
| **Ресурсы** | ~5–50 МБ RAM, низкий CPU | ~200–500 МБ RAM, выше CPU |
| **Язык/плагины** | C, фокус на производительности | Ruby/C, широкая экосистема |
| **Буферизация** | Память + файловый буфер (ограниченный) | Продвинутые файловые буферы, очереди |
| **Сложность маршрутов**| Базовая/средняя | Сложная логика, маршрутизация по метаданным |
| **Расширяемость** | Меньше плагинов | Очень много плагинов к хранилищам/шинам |

**Частая топология:** Fluent Bit на каждом узле собирает и нормализует логи, отправляет их по протоколу `forward` в центральный Fluentd, который распределяет события в Elasticsearch, S3, Kafka и другие системы.

---

## 2. Глубокое погружение в конфигурацию Fluent Bit

Конфигурация Fluent Bit разделена на несколько ключевых секций, которые определяют полный жизненный цикл лога от сбора до отправки.

### Секция `[SERVICE]`: Глобальные настройки

Здесь содержатся глобальные настройки для демона Fluent Bit.

```yaml
# Пример секции Service в values.yaml
config:
  service: |
    [SERVICE]
        Flush         1
        Daemon        Off
        Log_Level     info
        Parsers_File  parsers.conf
        HTTP_Server   On
        HTTP_Listen   0.0.0.0
        HTTP_Port     2020
        storage.path        /var/lib/fluent-bit/storage
        storage.sync        normal
        storage.backlog.mem_limit 128M
```

- `Flush`: Интервал в секундах для отправки собранных логов в `OUTPUT`.
- `Daemon`: `Off` указывает, что Fluent Bit не должен уходить в фоновый режим (стандарт для контейнеров).
- `Log_Level`: Уровень логирования самого Fluent Bit.
- `Parsers_File`: Путь к файлу с определениями парсеров.
- `HTTP_Server`: Включает встроенный HTTP-сервер для предоставления метрик Prometheus.
- `storage.*`: Параметры для настройки дисковой буферизации (Storage Layer), повышающей надежность доставки.

### Секция `[INPUT]`: Сбор логов

Определяет, откуда Fluent Bit будет собирать логи.

```yaml
# Пример секции Input
config:
  inputs: |
    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*.log
        Parser            docker
        Mem_Buf_Limit     10MB
        Skip_Long_Lines   On
        storage.type      filesystem

    [INPUT]
        Name              systemd
        Tag               host.*
        Systemd_Filter    _SYSTEMD_UNIT=kubelet.service
        Read_From_Tail    On
```

- **Плагин `tail` (для логов контейнеров):**
  - `Name tail`: Читает логи из файлов, подобно `tail -f`.
  - `Path /var/log/containers/*.log`: Путь к логам контейнеров в Kubernetes.
  - `Tag kube.*`: Назначает тег для последующей маршрутизации.
  - `Parser docker`: Применяет парсер `docker` (или `cri` для CRI-O/containerd).
  - `Mem_Buf_Limit`: Ограничивает буфер памяти для каждого файла.
  - `storage.type filesystem`: Включает дисковый буфер для этого входа.
- **Плагин `systemd` (для логов хоста):**
  - `Name systemd`: Сбор логов напрямую из `journald`.
  - `Tag host.*`: Назначает тег логам системных компонентов.

### Секция `[FILTER]`: Модификация и обогащение логов

Фильтры позволяют изменять проходящие через них логи. Самый важный фильтр в контексте Kubernetes — `kubernetes`.

```yaml
# Пример секции Filter
config:
  filters: |
    [FILTER]
        Name                kubernetes
        Match               kube.*
        Kube_URL            https://kubernetes.default.svc:443
        Merge_Log           On
        Keep_Log            Off
        K8S-Logging.Parser  On
        K8S-Logging.Exclude On
```

- `Name kubernetes`: Название встроенного фильтра для обогащения логов метаданными из Kubernetes API (имя пода, namespace, лейблы, аннотации).
- `Match kube.*`: Применяет фильтр ко всем логам с тегом `kube.*`.
- `Merge_Log On`: Если поле `log` содержит валидный JSON, его поля "поднимаются" на верхний уровень записи.
- `Keep_Log Off`: После успешного `Merge_Log` исходное поле `log` удаляется.
- `K8S-Logging.Parser On`: Позволяет переопределить парсер для логов пода через аннотацию `fluentbit.io/parser: <имя_парсера>`.
- `K8S-Logging.Exclude On`: Позволяет исключить логи пода из сбора через аннотацию `fluentbit.io/exclude: "true"`.

### Секция `[OUTPUT]`: Отправка логов

Определяет, куда Fluent Bit будет отправлять обработанные логи.

```yaml
# Пример секции Output
config:
  outputs: |
    [OUTPUT]
        Name               es
        Match              kube.*
        Host               elasticsearch-master.logging.svc.cluster.local
        Port               9200
        Logstash_Format    On
        Logstash_Prefix    kube
        Replace_Dots       On
        Retry_Limit        False
```

- `Name es`: Использует плагин для вывода в Elasticsearch.
- `Match`: Указывает, какие логи (по тегу) отправлять в этот `OUTPUT`.
- `Host`, `Port`: Адрес сервиса Elasticsearch.
- `Logstash_Format On`: Создает имена индексов в формате `<Logstash_Prefix>-YYYY.MM.DD`.
- `Replace_Dots On`: **Важный параметр.** Заменяет точки в именах полей (например, в лейблах Kubernetes) на `_`, чтобы избежать конфликтов маппинга в Elasticsearch.
- `Retry_Limit False`: Указывает Fluent Bit бесконечно пытаться повторно отправить логи в случае недоступности Elasticsearch.

---

## 3. Парсинг логов

Парсинг — это преобразование сырой строки лога в структурированную запись с полями и корректным временем события. От того, как реализован парсинг, зависят корректность поиска, агрегирования и маршрутизации логов, а также нагрузка на хранилище. 

### Типы плагинов и место парсинга
- **Входные плагины:**
  - **Fluent Bit**: `tail`, `systemd`, `tcp`, `forward`.
  - **Fluentd**: `in_tail`, `in_tcp`, `in_forward`, `in_syslog`.
- **Парсеры:**
  - **Fluent Bit**: секции `[PARSER]` и `[MULTILINE_PARSER]`, указываются в `[INPUT]` (директивы `Parser`, `Multiline.Parser`).
  - **Fluentd**: секция `<parse>` внутри входного плагина или фильтр `<filter>` с `@type parser` для повторного/условного парсинга.

Опорные задачи парсинга: выделение времени (`time`), тегирование, разбор структуры (ключ-значение), обработка многострочных сообщений, декодирование вложенного JSON.

### Распространённые форматы и парсеры

| Формат | Fluent Bit (Parser) | Fluentd (@type) | Примечание |
| :--- | :--- | :--- | :--- |
| **JSON** | `json` | `json` | Быстрый и надёжный при корректном JSON |
| **Docker (JSON file)** | `docker` | `json` | Ключ `log` содержит строку приложения |
| **CRI (K8s containerd)** | `cri` | `regexp` | Раскладывает `ts/stream/log` |
| **Регулярные выражения** | `regex` | `regexp` | Гибкость для произвольных форматов |
| **LTSV** | `ltsv` | `ltsv` | Лог с `key:value` парами |
| **CSV** | `csv` | `csv` | Требует определения колонок |
| **Syslog** | `syslog` | `syslog` | Может идти как input и как parse |

### Пример: парсинг CRI и многострочных стектрейсов Java в Fluent Bit

Для логов контейнеров в Kubernetes целесообразно использовать встроенный парсер `cri` и включить правила склейки многострочных сообщений, например, для Java стектрейсов.

```yaml
config:
  customParsers: |
    [PARSER]
        Name        docker
        Format      json
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%L
    
    [PARSER]
        Name        cri
        Format      regex
        Regex       ^(?<time>[^ ]+) (?<stream>stdout|stderr) (?<logtag>[^ ]*) (?<log>.*)$
        Time_Key    time
        Time_Format %Y-%m-%dT%H:%M:%S.%L%z

    [MULTILINE_PARSER]
        Name          java_stack
        Type          regex
        Flush_Timeout 5000
        Rule          "start_state"   "/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d+Z/."  "cont"
        Rule          "cont"          "/^\s+at\s+|^\s*Caused by:/."                   "cont"

  inputs: |
    [INPUT]
        Name                tail
        Path                /var/log/containers/*.log
        Tag                 kube.*
        Parser              cri
        Multiline           On
        Multiline.Parser    java_stack
```
Здесь `Parser cri` разбирает стандартный формат логов CRI, а `Multiline.Parser java_stack` "склеивает" строки, относящиеся к одному Java-исключению.

### Практические ориентиры
- Предпочтителен изначально структурированный лог (JSON, LTSV).
- Указывайте `time_key` и `time_format`, чтобы избежать смещения временной шкалы.
- Включайте объединение многострочных записей для стектрейсов.
- Сохраняйте часть «сырого» сообщения в отдельном поле для отладки.
- Нормализуйте ключи и уровни логирования (`level`, `service`, `env`) для совместимости дашбордов.
- Избегайте чрезмерно сложных регулярных выражений на горячих путях.

---

## 4. Буферизация и маршрутизация

Буферизация и маршрутизация — ключевые механизмы, определяющие надежность доставки и гибкость отправки логов.

### Буферизация: модели и параметры

**Fluentd** использует чанк-ориентированный буфер (`<buffer>`) для каждого output-плагина.
- `memory`: минимальная задержка, но риск потерь при перезапуске.
- `file`: устойчивость к рестартам, гарантии доставки "at-least-once".
- Ключевые параметры: `chunk_limit_size`, `total_limit_size`, `flush_interval`, `retry_type`.

**Fluent Bit** буферизует записи в памяти с возможностью выгрузки на диск (Storage Layer).
- Глобально в `[SERVICE]`: `storage.path`, `storage.sync`, `storage.backlog.mem_limit`.
- На входе `[INPUT]`: `storage.type filesystem` для долговременного буфера и `Mem_Buf_Limit` для контроля памяти.

### Маршрутизация: теги и правила

- **Fluentd**: Маршрутизация через `<match>` с шаблонами тегов (`app.**`). Поддерживает копирование (`@type copy`) и сложные графы через метки (`@label`).
- **Fluent Bit**: Каждый `[OUTPUT]` имеет `Match` или `Match_Regex` для выбора логов по тегу.

### Сравнение механизмов

| Аспект | Fluentd | Fluent Bit |
| :--- | :--- | :--- |
| **Буфер по умолчанию** | `file`/`memory` на каждый output | `memory` + опциональный `filesystem` |
| **Управление перегрузкой** | `overflow_action`, backpressure | `Mem_Buf_Limit`, `storage.backlog.mem_limit` |
| **Гибкость маршрутизации** | `@label`, `copy`, сложные графы | Простые правила `Match`/`Match_Regex` |
| **Надежность доставки** | Высокая с `file`-буфером | Высокая с `storage.type=filesystem` |

---

## 5. Сравнение с Fluentd

Хотя Fluent Bit является стандартом де-факто для сбора логов в Kubernetes, понимание Fluentd полезно для проектирования централизованного слоя агрегации.

- **Конфигурация Fluentd**: Использует более декларативный синтаксис с блоками `<source>`, `<filter>`, `<match>`.
- **Парсинг в Fluentd**: Поддерживает сложные парсеры, такие как `@type multi_format`, который может пробовать несколько форматов (например, JSON и regex) для одной строки.
- **Буферизация в Fluentd**: Предлагает более гранулярное управление буферами (чанки, лимиты, переполнение) для каждого выхода (`<buffer>`). Это позволяет, например, настроить короткий интервал отправки в Elasticsearch и длинный — для архивации в S3.

**Пример конфигурации Fluentd (агрегация и маршрутизация):**
```bash
<source>
  @type tail
  path /var/log/app.log
  tag app.log
</source>

<match app.**>
  @type copy

  <store>
    @type elasticsearch
    host es
    port 9200
    <buffer tag,time>
      @type file
      path /var/lib/fluentd/buffer/es
      chunk_limit_size 5m
      total_limit_size 1g
      flush_interval 5s
      retry_forever true
    </buffer>
  </store>

  <store>
    @type s3
    s3_bucket logs-archive
    <buffer tag>
      @type file
      path /var/lib/fluentd/buffer/s3
      chunk_limit_size 10m
      flush_interval 60s
    </buffer>
  </store>
</match>
```
В этом примере плагин `@type copy` дублирует входящие логи в два разных хранилища (Elasticsearch и S3) с независимыми настройками буферизации.

---

## 6. Критерии выбора

- **Fluent Bit**: Идеален для роли агента на узлах Kubernetes. Он производителен, потребляет мало ресурсов и покрывает 99% задач по сбору, базовой обработке и обогащению логов.
- **Fluentd**: Незаменим в роли центрального агрегатора, если требуется сложная маршрутизация, дедупликация, тяжелые трансформации или интеграция с экзотическими системами, для которых плагины есть только у Fluentd.
- **Гибридный подход**: Самый распространенный и надежный сценарий. **Fluent Bit** на всех узлах кластера собирает логи и отправляет их в единый сервис-агрегатор на базе **Fluentd**, который уже отвечает за сложную логику и доставку в конечные системы хранения.
