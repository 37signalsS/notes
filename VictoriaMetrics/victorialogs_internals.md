# Внутреннее устройство VictoriaLogs: хранение и обработка данных

## Определения

**VictoriaLogs** — это специализированное решение для хранения и анализа логов, входящее в экосистему VictoriaMetrics. Оно ориентировано на высокую производительность, эффективное сжатие и минимальные накладные расходы на индексацию.

**Поток (Stream)** — группа логов с идентичным набором полей потока (например, `host`, `app`, `container`). VictoriaLogs хранит логи одного потока рядом, что обеспечивает высокую степень сжатия и скорость запросов.

**Суточный раздел (Partition)** — базовая единица организации данных на диске, соответствующая одному календарному дню (UTC).

**Сегмент (Part)** — неизменяемый самодостаточный набор данных внутри раздела, доступный для поиска.

**Блок (Block)** — минимальная единица упаковки логов внутри сегмента. Содержит строки одного потока, отсортированные по времени.

## Базовые концепции

### 1. Schema-less подход
VictoriaLogs не требует предварительного описания схемы (mapping) или создания индексов.
-   **Автоматическое обнаружение полей:** любые поля в JSON-записи автоматически становятся доступными для поиска.
-   **Высокая кардинальность:** система оптимизирована для хранения и поиска по полям с миллионами уникальных значений (`trace_id`, `user_id`, IP-адреса) без деградации производительности индекса, свойственной Elasticsearch или Loki.

### 2. Жизненный цикл записи лога
Процесс приема данных (Ingestion Pipeline) спроектирован для обеспечения максимальной пропускной способности и немедленной доступности данных для поиска:
1.  **Прием данных:** VictoriaLogs поддерживает широкий спектр протоколов, включая Elasticsearch Bulk API, Grafana Loki, OpenTelemetry, Syslog, Splunk HEC (добавлено в 2026 году) и простые JSON lines.
2.  **Идентификация потока:** Входящие логи группируются в потоки на основе уникального набора меток (labels). Это обеспечивает "локальность потока" (stream locality), когда данные одного источника хранятся физически рядом, что критично для сжатия.
3.  **Гарантия сохранности (WAL):** Перед обработкой данные записываются в Write-Ahead Log (WAL), что обеспечивает устойчивость системы к сбоям.
4.  **Буферизация в памяти (InMemoryParts):** Логи попадают в структуру, аналогичную memtable в LSM-деревьях. В версиях 2026 года этот этап оптимизирован для параллельной обработки на многоядерных системах (100+ ядер).
5.  **Сброс на диск (Flush):** При заполнении буфера или по таймеру данные превращаются в неизменяемые сегменты (Parts) и записываются в соответствующие суточные разделы.

### 3. Кластерная архитектура и масштабирование
VictoriaLogs поставляется единым бинарным файлом, который может выполнять три роли (настраивается флагами):
-   **`vlinsert`**: Принимает логи и распределяет их по узлам хранения. Масштабируется при нехватке скорости приёма (CPU-bound). Поддерживает тонкую настройку лимитов памяти (`memory.allowedPercent`) и размеров входящих строк (`insert.maxLineSizeBytes`).
-   **`vlstorage`**: Хранит данные и выполняет локальный поиск. Масштабируется при росте объема данных (Disk-bound). Позволяет задавать жесткие лимиты на дисковое пространство (`retention.maxDiskSpaceUsageBytes`) и период хранения (`retentionPeriod`).
-   **`vlselect`**: Агрегирует результаты с узлов хранения и выполняет финальную обработку LogsQL. Масштабируется при росте числа или сложности запросов (Memory/CPU-bound).

*Рекомендуется использовать **vmauth** как точку входа перед кластером для реализации мультитенантности и разграничения прав доступа.*

### 4. Интеграция с мониторингом

#### Алертинг (Alerting)
Статистику запросов LogsQL можно использовать для генерации оповещений через связку с `vmalert`:
1.  **VictoriaLogs**: Выполняет запрос LogsQL.
2.  **vmalert**: Регулярно запрашивает данные, проверяет условия (например, число ошибок > 10) и отправляет алерт в Alertmanager.
3.  **Alertmanager**: Маршрутизирует уведомления в Slack, PagerDuty или почту.

#### Логи в метрики (Log-to-Metrics)
Правила записи (`recording rules`) позволяют превращать результаты агрегации логов в метрики временных рядов:
-   Результаты LogsQL регулярно сохраняются в VictoriaMetrics (Metrics Database).
-   Это позволяет строить долгосрочные тренды, дашборды в Grafana и планировать мощности без необходимости хранить все исходные логи бесконечно.

## Организация хранения

### 1. Иерархия данных
VictoriaLogs использует иерархическую структуру хранения, оптимизированную для быстрого поиска и эффективной ротации данных.

#### Суточные разделы
Данные разбиты по дням в каталоге `partitions/YYYYMMDD`. Это позволяет:
-   **Дешево удалять данные:** Очистка по сроку хранения (`-retentionPeriod`) сводится к удалению каталогов целых дней.
-   **Оптимизировать запросы:** Система открывает только те разделы, которые пересекаются с временным диапазоном запроса.
-   **Облачное хранение (Tiering):** С 2026 года поддерживается оффлоадинг старых разделов в S3-совместимые объектные хранилища, что обеспечивает практически неограниченную глубину архива при низких затратах.

#### Типы сегментов
-   **In-memory parts:** Самые свежие данные, еще не записанные на диск.
-   **Small parts:** Малые сегменты на диске. Используют кэш страниц ОС для быстрого повторного чтения.
-   **Big parts:** Большие сегменты (до 1 ТБ), образующиеся при слиянии (merge) малых в фоновом режиме. При записи обходят кэш страниц, чтобы не вытеснять "горячие" данные.

### 2. Структура сегмента (Part)
VictoriaLogs использует два ключевых приема для ускорения поиска и экономии места:

#### Группировка по потокам и времени
Блоки внутри сегмента упорядочены сначала по идентификатору потока, затем по времени. Заголовки блоков содержат метаданные (поток, `min/max timestamp`), что позволяет пропускать ненужные блоки без чтения их содержимого. Блоки имеют размер около 2 МБ, что позволяет им целиком помещаться в кэш L2 процессора.

#### Колоночное хранение (Columnar Storage)
Вместо построчного хранения, каждое поле лога выносится в отдельную **колонку**.
-   **Эффективность чтения:** Запрос читает только те колонки, которые указаны в фильтрах или через пайп `| fields`.
-   **Сжатие:** Значения одного типа (IP-адреса, статус-коды, уровни логирования) хранятся рядом и сжимаются специализированными алгоритмами.
-   **Шардирование колонок:** Данные распределяются по шардам (до 128 пар файлов `values.binN` / `bloom.binN`). Если в сегменте более 128 уникальных полей, они циклически распределяются по имеющимся шардам.

## Оптимизация и ускорение работы

### Практические сценарии

#### Оптимизация полей потока
Поля потока (`_stream_fields`) должны быть **низкокардинальными** (стабильными): `host`, `app`, `pod`.
Высококардинальные данные (`trace_id`, `user_id`, `request_id`) следует оставлять обычными полями. Неправильный выбор полей потока приводит к созданию слишком большого числа мелких потоков (High Cardinality), что снижает эффективность сжатия и замедляет поиск.

#### Ускорение запросов
1.  **Фильтрация по времени:** Всегда ограничивайте запрос временным диапазоном (`_time:5m`), чтобы VictoriaLogs сканировал минимум разделов и сегментов.
2.  **Выбор колонок:** Используйте `| fields _time, host, _msg` в конце запроса. Это позволит системе не извлекать с диска данные всех полей каждой строки, а прочитать только нужные колонки.
3.  **Полнотекстовый поиск:** Благодаря фильтрам Блума поиск по ключевым словам в поле `_msg` выполняется очень быстро, так как система мгновенно отсекает блоки, не содержащие искомых токенов.

## Техническое описание файлов сегмента

Каждый сегмент в каталоге `datadb` состоит из набора файлов, каждый из которых выполняет свою роль в обеспечении производительности:

| Файл | Описание |
| :--- | :--- |
| `metadata.json` | Сводная информация: число строк, блоков, временной диапазон и количество шардов. |
| `index.bin` | Заголовки всех блоков сегмента (ссылки на данные и метаданные). |
| `metaindex.bin` | Индекс поверх индекса (для быстрого позиционирования в `index.bin`). |
| `timestamps.bin` | Выделенная колонка с метками времени (`_time`) всех строк, сжатая дельта-кодированием. |
| `values.binN` | Шарды со значениями полей (кроме `_msg`). До 128 пар файлов. |
| `bloom.binN` | Фильтры Блума для соответствующих шардов значений, ускоряющие поиск токенов. |
| `message_values.bin` | Отдельное специализированное хранилище для данных основного поля сообщения `_msg`. |
| `message_bloom.bin` | Фильтр Блума специально для полнотекстового поиска в поле `_msg`. |
| `column_names.bin` | Словарь всех уникальных имен полей в сегменте с их внутренними идентификаторами. |
| `column_idxs.bin` | Карта соответствия имен полей их физическим шардам (`values.binN`). |
| `columns_header.bin` | Заголовки колонок внутри блоков (типы данных, смещения, размеры). |

### Алгоритм фильтрации данных
1.  **Проверка разделов (Partition Check):** Отсечение дней, не попадающих в диапазон `_time`.
2.  **Проверка метаданных (Metadata Check):** Проверка пересечения временного диапазона запроса с `min/max timestamp` сегмента.
3.  **Использование индексов (Metaindex & Index):** Поиск блоков, соответствующих фильтрам по потокам и времени.
4.  **Фильтр Блума (Bloom Filter):** Проверка наличия искомых слов в нужных колонках блока без их распаковки.
5.  **Чтение данных (Column Reading):** Точечное чтение байтов из `values.binN` только для блоков, прошедших все уровни фильтрации.

## Требования к окружению

### Операционная система
VictoriaLogs поддерживает Linux (Debian, Ubuntu, RHEL, CentOS, Rocky Linux, Alpine) на архитектурах amd64 и arm64, а также macOS (amd64). Для production эксплуатации на bare-metal рекомендуется:
- **Ядро Linux:** версия 4.14+ (для эффективной работы с диском и `io_uring`)
- **Файловая система:** XFS или ext4 (с отключением `atime` для снижения нагрузки на диск)
- **SELinux/AppArmor:** режим permissive или disabled, если не требуется корпоративная политика безопасности

### Аппаратные требования
Характер потребления ресурсов напрямую зависит от внутренней архитектуры VictoriaLogs (in-memory parts, WAL, columnar storage):

| Сценарий | CPU | RAM | Диск | Пропускная способность |
| :--- | :--- | :--- | :--- | :--- |
| **Малая нагрузка** (< 10K строк/сек) | 2 ядра | 4 GB | 50 GB SSD | 10 MB/s |
| **Средняя нагрузка** (10K–100K строк/сек) | 4–8 ядер | 8–16 GB | 200 GB SSD | 50 MB/s |
| **Высокая нагрузка** (> 100K строк/сек) | 8+ ядер | 16+ GB | 500 GB+ NVMe | 100+ MB/s |

**Важно для эксплуатации:**
- **RAM:** Определяет размер in-memory parts. При переполнении in-memory буфера данные душятся на диск чаще, что снижает производительность ingest. Настраивается через `-memory.allowedPercent` (по умолчанию 30% от общего объема RAM).
- **Диск:** Требует высокой скорости случайных чтений (запросы по columnar storage) и последовательных записей (WAL, flush). Для production — NVMe или SSD. HDD допустим только для архивных/редко запрашиваемых данных.
- **CPU:** Фоновые операции merge (слияние малых parts в большие) и сжатие колонок потребляют CPU. При высокой нагрузке merge может конкурировать за ресурсы с ingest и запросами.

### Программные зависимости
- **Бинарный файл:** не требует внешних зависимостей. Достаточно glibc.
- **Сбор логов:** vlagent (рекомендуется), Fluent Bit, Fluentd, Promtail или любой агент, поддерживающий Elasticsearch Bulk API, Loki API, OpenTelemetry или JSON lines.
- **Мониторинг:** curl, Prometheus (для сбора метрик с порта 9429).

### Сетевые порты
| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| `9428` | HTTP | Основной API: приём логов (`/insert/*`) и выполнение LogsQL-запросов (`/select/logsql/*`) |
| `9429` | HTTP | Метрики Prometheus (`/metrics`) |
| `9480` | HTTP | Cluster mode: `vlinsert` — приём данных |
| `9481` | HTTP | Cluster mode: `vlselect` — выполнение запросов |
| `9482` | HTTP | Cluster mode: `vlstorage` — хранение данных |

### Хранение
- **Тип диска:** SSD или NVMe для production. HDD — только для tiered storage (архив).
- **Размер:** Зависит от retention-периода и объёма ingest. Коэффициент сжатия columnar storage: ~10:1 для типичных JSON-логов, 5-10:1 для plain text.
- **Структура:** Данные organizуются в суточные разделы (`partitions/YYYYMMDD`), WAL хранится в `wal/`. Для высоконагруженных сред рекомендуется размещать WAL и данные на отдельных физических дисках.
- **Резерв:** Планируйте +20% запаса на метаданные, WAL и временные файлы компакции.

---

## Практические сценарии эксплуатации

### Деплой на bare-metal (systemd)
**Задача:** Установить VictoriaLogs на сервер без контейнеризации, с автозапуском, учетом особенностей внутреннего хранилища.

```bash
# Создание пользователя и директорий
sudo useradd --system --no-create-home --shell /usr/sbin/nologin victorialogs
sudo mkdir -p /etc/victorialogs /var/lib/victorialogs
sudo chown victorialogs:victorialogs /var/lib/victorialogs
sudo chmod 750 /var/lib/victorialogs
```

```ini
# /etc/systemd/system/victorialogs.service
[Unit]
Description=VictoriaLogs
After=network.target

[Service]
Type=simple
User=victorialogs
Group=victorialogs
ExecStart=/usr/local/bin/victoria-logs \
  -storageDataPath=/var/lib/victorialogs \
  -httpListenAddr=:9428 \
  -retentionPeriod=30d \
  -retention.maxDiskSpaceUsageBytes=100GiB \
  -memory.allowedPercent=40 \
  -wal.flushInterval=5s
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
# Установка и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now victorialogs

# Проверка
systemctl status victorialogs
# → active (running)

curl -s http://localhost:9428/health
# → OK
```

**Пояснение ключевых флагов (в контексте внутреннего устройства):**
- `-storageDataPath`: Корневая директория, содержащая `partitions/` (сегменты), `wal/` (журнал предзаписи) и временные файлы.
- `-retentionPeriod`: Автоматическое удаление суточных разделов (`partitions/YYYYMMDD`), старше указанного периода.
- `-retention.maxDiskSpaceUsageBytes`: Жёсткий лимит дискового пространства. При достижении — удаляются самые старые разделы независимо от `retentionPeriod`. Приоритет выше, чем у `retentionPeriod`.
- `-memory.allowedPercent`: Процент от общего объема RAM, разрешенный для in-memory parts (буфер перед flush'ем на диск). По умолчанию 30%. При высокой нагрузке увеличьте до 40-50%.
- `-wal.flushInterval`: Интервал сброса WAL на диск. Меньшее значение = меньшая потеря данных при сбое, но большее число операций записи.

**Особенности первого запуска:**
- При первом запуске VictoriaLogs создаёт структуру каталогов и пустой WAL.
- При последующих запусках выполняется WAL replay: не записанные на диск данные из WAL применяются к существующим partition'ам. Чем больше WAL, тем дольше старт.
- При аварийном завершении WAL replay выполняется автоматически. Не удаляйте WAL вручную при работающем сервисе.

### Resource Limits и тюнинг производительности
**Задача:** Ограничить потребление ресурсов и оптимизировать параметры под внутреннюю архитектуру VictoriaLogs.

```bash
# Ограничение через systemd
# /etc/systemd/system/victorialogs.service
[Service]
CPUQuota=50%
MemoryMax=4G
TasksMax=128
LimitNOFILE=200000
```

```bash
# Ограничение через Docker
docker run -d \
  --name victorialogs \
  --cpus=2 \
  --memory=4g \
  --ulimit nofile=65536:65536 \
  -p 9428:9428 \
  -v /etc/victorialogs:/storage \
  docker.io/victoriametrics/victoria-logs:latest \
  -storageDataPath=/storage
```

**Тюнинг параметров (влияние на внутренние механизмы):**

| Параметр | Влияние | Рекомендация |
| :--- | :--- | :--- |
| `-memory.allowedPercent` | Размер in-memory parts | 30-50% от RAM. Выше → быстрее ingest, но риск OOM |
| `-storage.maxPartDuration` | Макс. время жизни малого part перед merge | По умолчанию 1h. Увеличьте до 2-4h при низкой нагрузке для снижения числа merge |
| `-storage.maxBigPartSize` | Макс. размер big part после merge | По умолчанию 4GiB. Увеличьте до 8-16GiB для снижения частоты merge, но увеличьте время compaction |
| `-wal.flushInterval` | Частота сброса WAL | 1-10s. Меньше → безопаснее, но больше I/O |
| `-search.maxQueryDuration` | Таймаут запросов | 30s для single-node, 60s для cluster. Предотвращает долгие запросы, блокирующие компакцию |
| `-search.maxConcurrentRequests` | Очередь запросов | 8-16 для vlselect в cluster. Ограничивает потребление памяти при пике запросов |

**Рекомендации по нагрузке:**
- **<10K строк/сек:** параметры по умолчанию, `LimitNOFILE=65536`, `memory.allowedPercent=30`
- **10K–100K строк/сек:** `memory.allowedPercent=40-50%`, `LimitNOFILE=100000`, NVMe для WAL
- **>100K строк/сек:** выделенный диск для WAL, `storage.maxBigPartSize=8GiB`, `search.maxConcurrentRequests=16`, 8+ ядер CPU

### Валидация установки
**Health checks:**
```bash
# Проверка доступности HTTP-эндпоинта
curl -s http://localhost:9428/health
# → OK

# Проверка readiness
curl -s http://localhost:9428/ready
# → OK

# Проверка метрик самомониторинга
curl -s http://localhost:9428/metrics | grep vl_victorialogs_up
# → vl_victorialogs_up 1
```

**Верификация внутреннего состояния:**
```bash
# Проверить, что WAL replay завершился (в логах)
journalctl -u victorialogs --since "5 min ago" --no-pager | grep -i "wal\|replay\|started"
# → ... VictoriaLogs started successfully

# Проверить загрузку разделов
ls -la /var/lib/victorialogs/partitions/
# → 20240101  20240102  ...

# Проверить структуру данных
sudo victoria-logs -storageDataPath=/var/lib/victorialogs -check
# → SUCCESS
```

**Верификация данных:**
```bash
# Отправить тестовый лог
echo '{"level":"info","msg":"health check"}' | \
  curl -X POST http://localhost:9428/insert/jsonline -d @-

# Проверить, что лог появился
curl -s 'http://localhost:9428/select/logsql/query' \
  --data-urlencode 'query=_time:5m | stats count()'
# → count(): 1
```

**Диагностика типичных проблем на этапе валидации:**
| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `/health` не отвечает | Сервис не запущен | `systemctl status victorialogs` |
| `vl_victorialogs_up = 0` | Ошибка конфигурации или флага | Проверить логи `journalctl -u victorialogs` |
| Нет данных после ingest | WAL не сброшен, сервис перезапускается | Проверить `-wal.flushInterval`, подождать flush |
| Медленный старт | Большой WAL replay | Ожидать, в будущем уменьшить `-wal.flushInterval` |
| Ошибка открытия файлов | `LimitNOFILE` слишком мал | Увеличить `LimitNOFILE` до 100000+ |

### Управление хранением, WAL и retention
**Ручное управление разделами (Partitions):**
```bash
# Просмотр разделов
ls -la /var/lib/victorialogs/partitions/

# Проверка размера разделов
du -sh /var/lib/victorialogs/partitions/* | sort -rh | head

# Просмотр метаданных раздела
cat /var/lib/victorialogs/partitions/20240101/metadata.json
```

```bash
# Принудительное удаление старого раздела (например, при изменении retention)
# ВАЖНО: сервис должен быть остановлен
sudo systemctl stop victorialogs
sudo rm -rf /var/lib/victorialogs/partitions/20240101
sudo systemctl start victorialogs
```

**Управление WAL:**
```bash
# Размер WAL
du -sh /var/lib/victorialogs/wal/

# WAL автоматически управляется:
# - При чистом остановлении сервиса WAL усекается (старые сегменты удаляются)
# - При аварийном завершении WAL replay выполняется при старте
# - НЕ удаляйте WAL вручную при работающем сервисе

# Если WAL занимает слишком много места:
# 1. Проверьте, что сервис работает штатно (возможно, просто мало flush'ов)
# 2. Уменьшите `-wal.flushInterval`
# 3. При необходимости — плановый restart (WAL будет усечен)
```

**Поведение retention:**
- `-retentionPeriod`: "Мягкий" лимит. Фоновая очистка удаляет разделы старше указанного периода.
- `-retention.maxDiskSpaceUsageBytes`: "Жёсткий" лимит. При достижении — удаляются самые старые разделы независимо от `retentionPeriod`.
- Приоритет: `maxDiskSpaceUsageBytes` > `retentionPeriod`. Если заданы оба, сначала проверяется дисковое пространство.

**Восстановление после заполнения диска:**
```bash
# 1. Временно увеличить лимит или отключить strict limit
# 2. Удалить самый старый раздел
sudo rm -rf /var/lib/victorialogs/partitions/20230101
# 3. Перезапустить сервис
sudo systemctl restart victorialogs
```

### Безопасность хранения данных
**Права доступа к файлам:**
```bash
# Корректные права на storage
sudo chown -R victorialogs:victorialogs /var/lib/victorialogs
sudo chmod 750 /var/lib/victorialogs
sudo chmod 700 /var/lib/victorialogs/wal

# Конфигурация
sudo chown -R victorialogs:victorialogs /etc/victorialogs
sudo chmod 750 /etc/victorialogs
```

**Защита данных на уровне файловой системы:**
- VictoriaLogs не предоставляет встроенного шифрования данных на диске (data-at-rest).
- Для чувствительных данных используйте:
  - **LUKS/dm-crypt:** шифрование всего раздела, где находится `-storageDataPath`
  - **ecryptfs:** шифрование на уровне каталога
  - **Сторонние решения:** файловая система с шифрованием (ZFS encryption)

**Сетевая безопасность (single-node):**
```bash
# Ограничение доступа к порту 9428 (только из trusted subnet)
sudo ufw deny 9428
sudo ufw allow from 10.0.0.0/8 to any port 9428

# Или через iptables
sudo iptables -A INPUT -p tcp --dport 9428 -s 10.0.0.0/8 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 9428 -j DROP
```

**Безопасность кластерного режима:**
- Используйте `vmauth` как точку входа для реализации мультитенантности и разграничения прав.
- Включите mTLS между компонентами кластера (`-tls.keyFile`, `-tls.certFile`, `-tls.clientAuthFile`).
- Используйте сетевую изоляцию между компонентами кластера (firewall-правила на хостах или NetworkPolicy в Kubernetes).

### Резервное копирование и восстановление
**Стратегия бэкапа:**
```bash
# Метод 1: vmbackup (рекомендуется для production, не требует остановки)
# Создаёт снапшот данных через HTTP API и отправляет в S3-совместимое хранилище (MinIO, Ceph или AWS S3)
vmbackup \
  -storageDataPath=/var/lib/victorialogs \
  -snapshot.createURL=http://localhost:9428/snapshot/create \
  -backupsPath=s3://my-backups/victorialogs \
  -s3.endpoint=http://minio.example.com:9000 \
  -s3.region=us-east-1

# Метод 2: tar (требует остановки сервиса для консистентности)
sudo systemctl stop victorialogs
sudo tar -czf /root/vl-backup-$(date +%F).tar.gz \
  /var/lib/victorialogs \
  /etc/victorialogs
sudo systemctl start victorialogs
```

**Что включать в backup:**
- `/var/lib/victorialogs/partitions/` — все сегменты с логами
- `/var/lib/victorialogs/wal/` — WAL для восстановления после сбоя
- `/etc/victorialogs/` — конфигурационные файлы

**Восстановление:**
```bash
# 1. Остановить сервис
sudo systemctl stop victorialogs

# 2. Восстановить данные
sudo tar -xzf /root/vl-backup-2024-01-01.tar.gz -C /

# 3. Проверить права
sudo chown -R victorialogs:victorialogs /var/lib/victorialogs

# 4. Запустить сервис (WAL replay выполнится автоматически при наличии WAL)
sudo systemctl start victorialogs

# 5. Валидация
sleep 5
curl -s http://localhost:9428/health
# → OK
```

**Инкрементальные бэкапы (vmbackup):**
- Ежедневные инкрементальные (хранить 7 дней)
- Еженедельные полные (хранить 4 недели)
- Ежемесячные полные (хранить 12 месяцев)

### Процедура обновления и отката
**Обновление single-node (bare-metal):**
```bash
# 1. Проверить текущую версию
victoria-logs -version

# 2. Скачать новую версию
VERSION=v1.XX.0
wget https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/${VERSION}/victoria-logs-${VERSION}-amd64.tar.gz
tar -xzf victoria-logs-${VERSION}-amd64.tar.gz

# 3. Остановить сервис
sudo systemctl stop victorialogs

# 4. Создать бэкап перед обновлением
sudo tar -czf /root/vl-pre-upgrade-$(date +%F).tar.gz \
  /var/lib/victorialogs /etc/victorialogs

# 5. Заменить бинарный файл
sudo cp victoria-logs-${VERSION}-amd64 /usr/local/bin/victoria-logs
sudo chmod +x /usr/local/bin/victoria-logs

# 6. Запустить сервис
sudo systemctl start victorialogs

# 7. Проверить статус
systemctl status victorialogs
# → active (running)

curl -s http://localhost:9428/health
# → OK

# 8. Проверить загрузку правил и partitions
journalctl -u victorialogs --since "2 min ago" --no-pager | grep -i "partition\|wal\|started"
```

**Откат (rollback):**
```bash
# Если новая версия работает некорректно
sudo systemctl stop victorialogs

# Вариант А: вернуть предыдущий бинарник (если сохранили)
sudo cp /root/victoria-logs-old /usr/local/bin/victoria-logs
sudo chmod +x /usr/local/bin/victoria-logs

# Вариант Б: восстановить данные из backup
# sudo tar -xzf /root/vl-pre-upgrade-YYYY-MM-DD.tar.gz -C /

sudo systemctl start victorialogs

# Валидация
curl -s http://localhost:9428/health
```

**Важно:**
- WAL формат обычно обратно-совместим в рамках мажорных версий. При откате на major version разницу — требуется восстановление из backup.
- При обновлении cluster-режима: обновляйте `vlstorage` первыми, затем `vlinsert`, затем `vlselect`.
- Проверяйте release notes на предмет изменений в формате WAL или сегментов.

**Обновление в Docker:**
```bash
# 1. Остановить старый контейнер
docker stop victorialogs
docker rm victorialogs

# 2. Загрузить новый образ
docker pull victoriametrics/victoria-logs:latest

# 3. Запустить с той же конфигурацией (тома сохранены)
docker run -d \
  --name victorialogs \
  --cpus=2 \
  --memory=4g \
  -p 9428:9428 \
  -v /etc/victorialogs:/storage \
  victoriametrics/victoria-logs:latest \
  -storageDataPath=/storage
```

**Проверка после обновления:**
```bash
# Проверка версии
curl -s http://localhost:9428/metrics | grep victorialogs_build_info
# → victorialogs_build_info{version="v1.XX.0",...} 1

# Проверка partitions
curl -s http://localhost:9428/select/logsql/query \
  --data-urlencode 'query=_time:1h | stats count()'
# → данные возвращаются

# Проверка активных streams
curl -s http://localhost:9428/metrics | grep vl_victorialogs_stream_rows_total
```

### Отладка и устранение неполадок (Troubleshooting)
**Типичные ошибки и диагностика:**

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Медленный старт | Большой WAL replay | `journalctl -u victorialogs --since "10 min ago"` | Ожидать завершения replay. В будущем уменьшить `wal.flushInterval` |
| Диск заполнен | `retention.maxDiskSpaceUsageBytes` достигнут | `df -h /var/lib/victorialogs` | Увеличить лимит или удалить старые partition вручную |
| Потеря логов после сбоя | WAL поврежден или не записал данные | `journalctl -u victorialogs` | Проверить `insert.maxLineSizeBytes`, восстановить из backup |
| Высокий disk I/O | Фоновая компакция (merge) | `iotop -o` | Нормальное поведение. Можно уменьшить `storage.maxBigPartSize` для более частых мелких merge |
| OOM при ingest | Слишком большой `memory.allowedPercent` | `dmesg | grep -i oom` | Уменьшить `memory.allowedPercent`, увеличить RAM |
| Медленные запросы | Слишком много small parts | `ls /var/lib/victorialogs/partitions/*/parts/` | Проверить, что merge работает. Увеличить `storage.maxPartDuration` |
| Коррупция данных | Аварийное выключение, битый диск | `victoria-logs -storageDataPath=/var/lib/victorialogs -check` | Восстановить из backup |

**Диагностические команды:**
```bash
# Проверка статуса сервиса (systemd)
systemctl status victorialogs
journalctl -u victorialogs --since "1 hour ago" --no-pager

# Проверка ресурсов
ps -p $(pgrep victoria-logs) -o pid,%cpu,%mem,cmd
cat /proc/$(pgrep victoria-logs)/limits | grep "open files"

# Проверка диска
df -h /var/lib/victorialogs
du -sh /var/lib/victorialogs/partitions/* | sort -rh | head

# Проверка WAL
du -sh /var/lib/victorialogs/wal/
ls -la /var/lib/victorialogs/wal/

# Проверка метрик
curl -s http://localhost:9428/metrics | grep vl_victorialogs_

# Валидация всех данных
victoria-logs -storageDataPath=/var/lib/victorialogs -check

# Проверка remote write connectivity (cluster mode)
curl -s http://localhost:9480/insert/health
```

**Восстановление после сбоя:**
```bash
# Сценарий 1: WAL replay автоматически восстановит данные при старте
sudo systemctl restart victorialogs
sleep 5
curl -s http://localhost:9428/health
# → OK

# Сценарий 2: WAL поврежден, replay падает
sudo systemctl stop victorialogs
sudo mv /var/lib/victorialogs/wal /var/lib/victorialogs/wal.corrupt
sudo systemctl start victorialogs
# → Сервис запустится без WAL replay, используя последнее хорошее состояние partitions

# Сценарий 3: Полное восстановление из backup
sudo systemctl stop victorialogs
sudo tar -xzf /root/vl-backup-2024-01-01.tar.gz -C /
sudo systemctl start victorialogs
```

### Ограничения и особые случаи
**Производительность и точность:**
- **Sequential evaluation:** LogsQL запросы выполняются последовательно по пайпам. Сложные запросы с большим количеством строк могут занимать значительное время и память.
- **WAL replay time:** При аварийном завершении время старта пропорционально объему WAL. При пиковых нагрузках WAL может достигать нескольких гигабайт, что увеличивает время восстановления до нескольких минут.
- **Merge stalls:** При очень высокой ingest-нагрузке merge малых parts в большие может отставать. Это нормальное поведение, но приводит к росту числа small parts и временному снижению производительности запросов.

**Сеть и отказоустойчивость (cluster mode):**
- Сетевые разрывы между `vlinsert` и `vlstorage`/`vlselect` могут привести к:
  - Потере данных при ingest, если retry-буфер `vlinsert` переполнен
  - Тайм-аутам при выполнении запросов через `vlselect`
- Для минимизации потерь: увеличьте размеры буферов и настройте retry-логику на стороне агента сбора.

**State Recovery и особые случаи:**
- **In-memory parts:** Данные в in-memory parts теряются при аварийном завершении. WAL гарантирует отсутствие потерь только после flush'а в WAL. Данные между ingest и WAL flush могут быть потеряны.
- **Version specifics:** Формат WAL и сегментов может меняться между мажорными версиями. При downgrade требуется полное восстановление из backup.
- **Column sharding:** Если в сегменте более 128 уникальных полей, они циклически распределяются по шардам `values.binN`. Это не влияет на запросы, но увеличивает число открываемых файлов.
- **Big parts и page cache:** Big parts (>4GB) при чтении обходят кэш страниц ОС, чтобы не вытеснять "горячие" данные. Это уменьшает Cache hit ratio для больших исторических запросов, но повышает общую производительность системы.
- **Partition boundaries:** Фильтрация по времени (`_time`) работает на уровне разделов. Запрос, пересекающий границу дня, автоматически открывает несколько разделов. Узкие временные окна работают значительно быстрее.

**Известные проблемы:**
1. **High Cardinality Streams:** Создание потоков с миллионами уникальных комбинаций `_stream_fields` кардинально снижает производительность сжатия и скорость запросов.
2. **Большие строки:** Строки > 1 MB требуют увеличения `insert.maxLineSizeBytes` и могут вызвать OOM при ingest. Рекомендуется разбивать большие payload на части.
3. **Windows не поддерживается:** VictoriaLogs доступен только для Linux и macOS (amd64/arm64).

### FAQ
**В: Какой retention period выбрать для production?**
О: Зависит от compliance-требований и объема логов. Для большинства сред достаточно 30–90 дней. Для debugging критических инцидентов рекомендуется минимум 7 дней с возможностью экспорта в S3-совместимое хранилище для долгосрочного архива.

**В: Как уменьшить время старта после сбоя?**
О: Время старта определяется объёмом WAL replay. Для сокращения:
1. Уменьшите `-wal.flushInterval` (например, до 1s) во время нормальной работы.
2. Используйте быстрые диски (NVMe) для директории WAL.
3. Обеспечьте достаточный объем RAM, чтобы in-memory parts не переполнялись и данные часто flush'ились на диск.

**В: Безопасно ли удалять WAL вручную?**
О: Нет, при работающем сервисе — никогда. При остановленном сервисе — только если вы уверены, что все данные из WAL уже записаны в partitions (например, после чистого shutdown). При аварийном завершении WAL replay выполняется автоматически при следующем старте.

**В: Почему merge (компакция) не происходит?**
О: Merge запускается в фоне по триггерам:
1. Количество small parts превышает лимит.
2. Прошло время `storage.maxPartDuration`.
3. Размер small parts превышает порог.
Проверьте логи на наличие ошибок merge. При очень высокой ingest-нагрузке merge может отставать — это нормально. Увеличьте `storage.maxBigPartSize` для снижения частоты merge.

**В: Как перенести данные на другой диск?**
О: Остановите сервис, скопируйте содержимое `/var/lib/victorialogs` на новый диск, обновите `-storageDataPath` в systemd unit, перезапустите сервис. WAL replay выполнится автоматически.

**В: Что такое `memory.allowedPercent` и как его настроить?**
О: Процент от общего объема RAM, разрешенный для in-memory parts (буфер ingest). По умолчанию 30%. Для высоконагруженных сред увеличьте до 40-50%. Установка в 80%+ может привести к OOM, так как на операционную систему и процессы merge останется недостаточно памяти.

**В: Почему после сбоя пропали последние логи?**
О: Возможные причины:
1. Данные были в in-memory parts, но ещё не попали в WAL (редко, возможно при внезапном отключении питания).
2. `insert.maxLineSizeBytes` был недостаточным, и логи отбрасывались.
3. Диск был полен, ingest завершался с ошибкой.
Проверьте логи `journalctl -u victorialogs` и метрики `vl_victorialogs_insert_errors_total`.

**В: Можно ли использовать HDD вместо SSD?**
О: Для архивных данных с редко выполняемыми запросами — да. Для hot-данных с частыми запросами — нет. Производительность случайных чтений columnar storage на HDD упадет на порядки, что сделает запросы неприемлемо медленными.

**В: Как работает мультитенантность на уровне хранилища?**
О: Через HTTP-заголовок `X-Scope-OrgID`. Данные разных тенантов физически разделяются в разных потоках (streams). Используйте `vmauth` как reverse proxy для маршрутизации запросов по tenant и контроля доступа.

**В: Что делать при ошибке "too many open files"?**
О: Увеличьте `LimitNOFILE` в systemd unit до 100000 или 200000 (для cluster-компонентов). VictoriaLogs открывает множество файлов сегментов при запросах.

---

## Дополнительная информация

### См. также
- **[LogsQL: обзор](./logsql_overview.md)** — руководство по языку запросов.
- **[Инжест логов](./victorialogs_ingestion.md)** — протоколы приёма и коллекторы.
- **[Обзор vmalert](./vmalert_overview.md)** — использование VictoriaLogs для алертинга.
- **[VictoriaMetrics: обзор](./overview.md)** — общая информация об экосистеме.