# LogsQL: Справочник и руководство по языку запросов

## Определения

**LogsQL** — это высокопроизводительный потоковый (pipeline) язык запросов VictoriaLogs, оптимизированный для поиска, фильтрации и аналитической обработки больших объемов журналов. Запрос строится как последовательность операций, разделенных символом `|`, где результат каждой предыдущей операции передается на вход следующей.

**Базовая структура запроса:**
```logsql
<фильтрация> | <парсинг/извлечение> | <трансформация> | <агрегация> | <пост-фильтрация>
```

---

## Базовые концепции

### 1. Структура запроса и синтаксис
Запрос всегда начинается с фильтра (выбора данных). С 2026 года в LogsQL поддерживается использование точки с запятой `;` в конце запроса для разделения многострочных конструкций.

**Основные правила:**
- Регистр имен полей и значений в фильтрах учитывается.
- Технологические термины (deploy, pipeline, stream) не переводятся.
- Пайпы (pipes) позволяют модифицировать поток данных.

### 2. Фильтрация и временные фильтры
Временной фильтр является первичным инструментом ограничения объема сканируемых данных.

- `_time:5m` — последние 5 минут.
- `_time:24h` — последние сутки.
- `_time:[2026-01-01, 2026-01-02]` — фиксированный диапазон.
- `_time:1h level:error` — комбинация фильтров (AND по умолчанию).

### 3. Полнотекстовый поиск
- `"error"` — поиск слова в любом месте сообщения.
- `"timeout exceeded"` — поиск точной фразы.
- `~"(?i)(err|warn)"` — регулярное выражение (регистронезависимый поиск).

### 4. Потоки (Streams) и поля потока (_stream_fields)
Поля потока (`_stream_fields`) определяют группировку логов при хранении. VictoriaLogs хранит логи одного потока рядом, что обеспечивает высокую степень сжатия и скорость запросов.

**Требования к полям потока:**
- Должны быть **низкокардинальными** (стабильными): `host`, `app`, `pod`, `env`.
- Высококардинальные данные (`trace_id`, `user_id`, `request_id`) следует оставлять обычными полями.
- Неправильный выбор полей потока приводит к созданию слишком большого числа мелких потоков, что снижает эффективность сжатия и замедляет поиск.

Фильтрация по `_stream_fields` работает значительно быстрее, так как VictoriaLogs хранит данные потоков локализовано.

---

## Требования к окружению

### Операционная система
VictoriaLogs доступен для Linux (amd64, arm64) и macOS (amd64). Для production эксплуатации рекомендуется Linux-based ОС с актуальным LTS-ядром.

### Аппаратные требования
| Сценарий | CPU | RAM | Диск | Пропускная способность |
| :--- | :--- | :--- | :--- | :--- |
| **Малая нагрузка** (< 10K строк/сек) | 2 ядра | 4 GB | 50 GB SSD | 10 MB/s |
| **Средняя нагрузка** (10K–100K строк/сек) | 4–8 ядер | 8–16 GB | 200 GB SSD | 50 MB/s |
| **Высокая нагрузка** (> 100K строк/сек) | 8+ ядер | 16+ GB | 500 GB+ SSD/NVMe | 100+ MB/s |

### Программные зависимости
- Для запуска бинарного файла: никаких внешних зависимостей не требуется.
- Для контейнеризации: Docker, Podman или containerd.
- Для сбора логов: vlagent (рекомендуется), Fluent Bit, Fluentd, Promtail или любой агент, поддерживающий Elasticsearch Bulk API, Loki API, OpenTelemetry или JSON lines.

### Сетевые порты
| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| `9428` | HTTP | Основной API для приёма логов и выполнения LogsQL-запросов (vlselect/vlinsert) |
| `9429` | HTTP | Метрики Prometheus (/metrics) |

### Хранение
- **Тип диска:** SSD или NVMe рекомендуется для production из-за высокой частоты случайных чтений при запросах.
- **Размер:** Зависит от retention-периода и объёма ingest. VictoriaLogs использует columnar storage с высокой компрессией (~10:1 для типичных логов).
- **Разделы:** Данные organizуются в суточные разделы (`partitions/YYYYMMDD`), что упрощает управление retention.

---

## Операторы пайпов (Pipes)

С 2026 года введено строгое правило: пайпы фильтрации, не начинающиеся с `field_name:`, требуют обязательного префикса `filter`.

| Пайп | Описание | Пример |
| :--- | :--- | :--- |
| `fields` | Выбор конкретных колонок для чтения с диска. | `| fields _time, host, msg` |
| `filter` | Явная фильтрация после трансформаций. | `| filter status >= 400` |
| `sort by` | Сортировка результатов (`asc` / `desc`). | `| sort by (_time desc)` |
| `limit` | Ограничение количества возвращаемых строк. | `| limit 100` |
| `coalesce` | Возвращает первое непустое значение (New 2026). | `| coalesce(user_id, uid, "anon") as user` |
| `json_array_concat` | Объединение JSON-массива в строку (New 2026). | `| json_array_concat tags, "," as s_tags` |
| `uniq` | Возвращает уникальные наборы значений. | `| uniq with hits` |
| `stream_context` | Выбор окружающих строк (должен быть первым). | `| stream_context(before 5, after 5)` |
| `collapse_nums` | Группировка похожих строк путем замены чисел. | `| collapse_nums` |

---

## Парсинг и трансформация

LogsQL позволяет извлекать структурированные данные из неструктурированных сообщений на лету.

- **`unpack_json`**: Распаковка JSON-объекта в отдельные поля.
- **`extract`**: Извлечение по шаблону с использованием `<name>`.
  ```logsql
  * | extract "user=<user_id> status=<status>"
  # → создает поля user_id и status
  ```
- **`extract_regexp`**: Извлечение с помощью именованных групп регулярных выражений.
- **`replace`**: Замена подстроки в поле.
  ```logsql
  * | replace("old_val", "new_val") at my_field
  ```
- **`format`**: Создание нового поля на основе шаблона.
  ```logsql
  * | format "User <user> logged from <ip>" as summary
  ```

---

## Агрегации и аналитика (stats)

Оператор `stats` используется для вычисления метрик над группами логов.

**Функции агрегации:**
- `count()`, `count_uniq(field)` — подсчет количества.
- `sum(field)`, `avg(field)` — математические операции.
- `min(field)`, `max(field)` — экстремумы.
- `quantile(0.95, field)` — перцентили.
- `stddev(field)` — стандартное отклонение (New 2026).

**Пример агрегации по времени (Bucketing):**
```logsql
_time:1h | stats by(_time:1m, host) count() as req_per_min
# → результат: таблица с количеством запросов в минуту для каждого хоста
```

---

## Практические сценарии

### 1. Анализ процента ошибок
Определение доли неуспешных запросов с использованием математических операций.
```logsql
_time:1h app:web 
| stats count() as total, count() if (status:>=400) as errors 
| math errors / total * 100 as error_rate
| filter error_rate > 5
```
**Результат:** Список временных интервалов или хостов, где процент ошибок превысил 5%.

### 2. Схлопывание похожих сообщений об ошибках
Использование `collapse_nums` для группировки логов, различающихся только идентификаторами или числами.
```logsql
_time:24h level:error 
| collapse_nums 
| stats by(_msg) count() as hits 
| sort by (hits desc)
```
**Результат:** Топ уникальных шаблонов ошибок с количеством их вхождений.

### 3. Работа с несколькими ID пользователя
Использование `coalesce` для нормализации данных из разных версий API.
```logsql
_time:15m | coalesce(user_id, legacy_uid, "guest") as user | stats by(user) count()
```

### 4. Деплой на bare-metal (systemd)
**Задача:** Запустить VictoriaLogs на сервере без контейнеризации, с автозапуском и ротацией логов.

```bash
# Создание пользователя и директорий
sudo useradd --system --no-create-home --shell /usr/sbin/nologin victorialogs
sudo mkdir -p /etc/victorialogs /var/lib/victorialogs
sudo chown victorialogs:victorialogs /var/lib/victorialogs
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
  -httpListenAddr=:9428
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
curl -s http://localhost:9428/health | head
```

### 5. Resource Limits и тюнинг производительности
**Задача:** Ограничить потребление ресурсов VictoriaLogs в production и подобрать оптимальные параметры.

```bash
# Ограничение ресурсов через systemd
# /etc/systemd/system/victorialogs.service
[Service]
CPUQuota=50%
MemoryMax=2G
TasksMax=64
```

```bash
# Ограничение через Docker
docker run -d \
  --name victorialogs \
  --cpus=1 \
  --memory=2g \
  -p 9428:9428 \
  -v /etc/victorialogs:/storage \
  docker.io/victoriametrics/victoria-logs:latest \
  -storageDataPath=/storage
```

> **Важно:** При высокой нагрузке (>100K строк/сек) увеличивайте `memory.allowedPercent` до 50% и используйте NVMe-накопители. Для больших сред — уменьшайте количество `_stream_fields` dimensions.

### 6. Production runbook — реакция на медленные запросы
**Задача:** Структурировать действия инженера при degration производительности запросов.

**Шаг 1: Идентификация проблемного запроса**
```bash
# Проверить метрики VictoriaLogs
curl -s http://localhost:9428/metrics | grep vl_victorialogs_query

# Просмотреть медленные запросы
curl -s 'http://localhost:9428/select/logsql/query_stats' | head
```

**Шаг 2: Анализ LogsQL**
```logsql
# Проверить стоимость выполнения по блокам
_time:24h | filter level:error | block_stats | limit 10
```

**Шаг 3: Корректирующие действия**
| Действие | Описание |
| :--- | :--- |
| **Уменьшение временного окна** | Уменьшить `_time` до минимально необходимого |
| **Удаление лишних полей** | Добавить `| fields _time, _msg` в конец запроса |
| **Упрощение фильтров** | Переместить фильтры в начало запроса |
| **Увеличение interval** | Для агрегаций использовать больший интервал bucketing |
| **Проверка streams** | Снизить количество `_stream_fields` если их слишком много |

**Шаг 4: Верификация**
```bash
# Проверить, что latency снизилась
curl -s 'http://localhost:9428/select/logsql/query_stats' | grep latency
```

### 7. Управление retention и ротацией данных
**Задача:** Настроить автоматическое удаление старых логов.

```bash
# Запуск с retention 30 дней
victoria-logs \
  -storageDataPath=/var/lib/victorialogs \
  -retentionPeriod=30d \
  -httpListenAddr=:9428
```

```bash
# Проверка текущего retention
curl -s http://localhost:9428/metrics | grep retention
```

> **Важно:** Изменение `-retentionPeriod` влияет только на НОВЫЕ данные. Старые разделы удаляются при следующем запуске фоновой очистки. Для немедленного применения удалите соответствующие каталоги в `partitions/`.

---

## Валидация установки

### Health checks
```bash
# Проверка доступности API
curl -s http://localhost:9428/health
# → OK

# Проверка метрик
curl -s http://localhost:9428/metrics | grep vl_victorialogs_up
# → vl_victorialogs_up 1
```

### Верификация данных
```bash
# Отправить тестовый лог
echo '{"level":"info","msg":"test log"}' | curl -X POST http://localhost:9428/insert/jsonline -d @-

# Проверить, что лог появился
curl -s 'http://localhost:9428/select/logsql/query' \
  --data-urlencode 'query=_time:5m | stats count()'
```

### Диагностика типичных проблем
| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `curl /health` не отвечает | Сервис не запущен | `systemctl status victorialogs` |
| `vl_victorialogs_up = 0` | Ошибка конфигурации | Проверить логи `journalctl -u victorialogs` |
| Данные не поступают | Ошибка в агенте сбора | Проверить endpoint у vlagent/Fluent Bit |
| Запросы возвращают 0 строк | Неверный `_time` фильтр | Увеличить временное окно запроса |
| Высокое CPU (>100%) | Слишком много streams | Уменьшить `_stream_fields` cardinality |
| Высокий disk I/O | Недостаток памяти для in-memory parts | Увеличить `memory.allowedPercent` |

---

## Рекомендации по производительности

1. **Селективность**: Помещайте наиболее точные фильтры (например, `_time` или `_stream_fields`) в самое начало запроса.
2. **Использование потоков**: Фильтрация по `_stream_fields` (например, `app="nginx"`, `env="prod"`) работает значительно быстрее, так как VictoriaLogs хранит данные потоков локализовано.
3. **Минимизация I/O**: Всегда используйте пайп `| fields` для ограничения количества считываемых колонок, если вам нужны не все данные.
4. **Предварительный осмотр**: Используйте `| field_names` или `| field_values name` для быстрого анализа схемы данных без сканирования всех записей.

---

## Отладка и устранение неполадок

### Типичные ошибки и диагностика

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Медленные запросы | Слишком широкий `_time` или нет `| fields` | `| block_stats` | Уменьшить окно, добавить fields |
| Потеря логов | Недостаточная память или диск полон | `df -h`, `journalctl` | Очистить место, увеличить memory.allowedPercent |
| Высокое CPU | Много streams или сложные regex | `top -p <pid>` | Уменьшить `_stream_fields`, упростить фильтры |
| Ошибки при ingest | Пустой или невалидный JSON | Логи vlinsert | Проверить формат отправляемых логов |
| Данные не найдены | Неверный фильтр или retention | Проверить `_time` | Увеличить окно, проверить retentionPeriod |
| Отсутствует `churn` метрика | Используется Prometheus без MetricsQL | Проверить версию VictoriaMetrics | Использовать MetricsQL или пересчитать вручную |

### Диагностические команды
```bash
# Проверка статуса сервиса
systemctl status victorialogs
journalctl -u victorialogs --since "1 hour ago" --no-pager

# Проверка ресурсов
ps -p $(pgrep victoria-logs) -o pid,%cpu,%mem,cmd
cat /proc/$(pgrep victoria-logs)/limits | grep "open files"

# Проверка диска
df -h /var/lib/victorialogs
du -sh /var/lib/victorialogs/partitions/* | sort -rh | head
```

### Восстановление после сбоя
```bash
# Перезапуск с очисткой in-memory состояния
sudo systemctl restart victorialogs

# Проверка после перезапуска
sleep 5
curl -s http://localhost:9428/health
# → OK
```

---

## Рекомендации по эксплуатации

### Resource Limits и планирование
VictoriaLogs — легковесный компонент, но при высокой нагрузке его требования растут:

| Компонент | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| **CPU** | 1 ядро на 20K строк/сек | vlinsert CPU-bound при высоком ingest |
| **RAM** | `memory.allowedPercent` = 30-50% от total | Для in-memory parts и компрессии |
| **Диск** | SSD/NVMe, отдельный раздел | Случайные чтения при запросах |
| **open files** | `LimitNOFILE=65536` минимум | Множество открытых сегментов |

### Безопасность
- **Аутентификация:** Используйте `vmauth` как reverse proxy для реализации мультитенантности и разграничения прав доступа.
- **Сеть:** Ограничьте доступ к порту `9428` firewall-ом. В production используйте только HTTPS с валидными сертификатами.
- **Данные:** VictoriaLogs не имеет встроенной аутентификации; все вопросы безопасности решаются на уровне сетевого доступа и прокси.

### Процедура обновления
```bash
# 1. Остановка сервиса
sudo systemctl stop victorialogs

# 2. Бэкап конфигурации и данных
sudo tar -czf /root/vl-backup-$(date +%F).tar.gz /etc/victorialogs /var/lib/victorialogs

# 3. Обновление бинарника
sudo cp victoria-logs-new /usr/local/bin/victoria-logs
sudo chmod +x /usr/local/bin/victoria-logs

# 4. Запуск и проверка
sudo systemctl start victorialogs
sleep 3
curl -s http://localhost:9428/health
```

### Очистка и обслуживание
```bash
# Проверка целостности данных
victoria-logs -storageDataPath=/var/lib/victorialogs -check

# Ручное удаление старого раздела (при изменении retention)
sudo rm -rf /var/lib/victorialogs/partitions/20250101

# Перезапуск фоновой очистки
sudo systemctl restart victorialogs
```

---

## Ограничения и особые случаи

### Точность HyperLogLog и кардинальности
LogsQL использует приблизительные алгоритмы для `count_uniq`. Отклонение от точного значения составляет ~2-3%, что приемлемо для большинства практических задач, но может быть критично при малых объемах данных.

### WAL и диск
Write-Ahead Log (WAL) обеспечивает гарантию сохранности данных при сбоях. Однако:
- WAL может занимать значительное место на диске при пиковых нагрузках.
- При аварийной остановке системы требуется выполнить WAL replay при старте, что увеличивает время восстановления.

### Зависимость от сетевого доступа
В кластерном режиме `vlinsert`, `vlstorage` и `vlselect` взаимодействуют по сети. Сетевые разрывы могут привести к:
- Потере данных при ingest (если retry-буфер переполнен)
- Тайм-аутам при выполнении запросов

### Ограничения версии
- Backfill для правил LogsQL с кастомным time filter не поддерживается (ограничение vmalert).
- `stddev()` в `stats` добавлен в 2026 году и требует актуальной версии VictoriaLogs.

### Известные проблемы
1. **High Cardinality Streams:** Создание streams с миллионами уникальных значений кардинально снижает производительность.
2. **Большие строки:** Строки > 1 MB требуют увеличения `insert.maxLineSizeBytes` и могут вызвать OOM.
3. **Windows не поддерживается:** VictoriaLogs доступен только для Linux и macOS (amd64/arm64).

---

## FAQ

**В: Какой retention period выбрать для production?**
О: Зависит от compliance-требований. Для большинства сред достаточно 30–90 дней. Для debugging критических инцидентов рекомендуется минимум 7 дней с возможностью экспорта в S3-совместимое хранилище для долгосрочного архива.

**В: Нужно ли создавать mapping/индексы перед ingest?**
О: Нет, VictoriaLogs использует schema-less подход. Поля автоматически обнаруживаются из JSON-записей. Предварительное описание схемы не требуется.

**В: Как откатить изменения конфигурации?**
О: Используйте systemd для управления сервисом:
```bash
sudo systemctl restart victorialogs
# При проблемах:
sudo systemctl revert victorialogs
```

**В: Чем LogsQL отличается от PromQL?**
О: LogsQL — это pipeline-язык для логов (строки), PromQL — для метрик (числовые временные ряды). LogsQL оптимизирован для фильтрации и полнотекстового поиска, PromQL — для математических операций над агрегированными метриками.

**В: Как мониторить сам VictoriaLogs?**
О: Используйте встроенный эндпоинт `/metrics` (порт 9429) для сбора метрик в VictoriaMetrics. Ключевые метрики: `vl_victorialogs_inserted_rows_total`, `vl_victorialogs_query_duration_seconds`, `vl_victorialogs_memory_available_bytes`.

**В: Поддерживается ли multi-tenancy?**
О: Да, через `vmauth` как reverse proxy с маршрутизацией по пользователям/tenant_id. Подробнее см. [Внутреннее устройство VictoriaLogs](./victorialogs_internals.md).

**В: Что делать при потере логов?**
О: Проверить `insert.maxLineSizeBytes` (не пропускает большие строки), `_stream_fields` на высокую кардинальность, доступное место на диске и статус vlinsert через `/metrics`.

---

## Дополнительная информация

### См. также
- **[Внутреннее устройство VictoriaLogs](./victorialogs_internals.md)** — архитектурные оптимизации и структура хранения.
- **[Инжест логов](./victorialogs_ingestion.md)** — протоколы приёма и коллекторы.
- **[Развёртывание в Kubernetes](../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md)** — руководство по установке стека логирования.
- **[Обзор vmalert](./vmalert_overview.md)** — создание алертов на основе LogsQL запросов.
- **[Управление правилами vmalert в Kubernetes](./vmalert_rules_management_with_manifests.md)** — VMRule CRD и оператор.
- **[Логирование: глубокое погружение](../Concepts/Observability_and_Monitoring/logs_deep_dive.md)** — сравнение систем логирования.

Связанные компоненты:
- [VictoriaMetrics — обзор](./overview.md) — платформа хранения метрик;
- [vmalert — обзор](./vmalert_overview.md) — алертинг на основе метрик и логов;
- [VictoriaLogs: внутреннее устройство](./victorialogs_internals.md) — архитектура хранения;
- [Cardinality в Prometheus](../Prometheus/concepts/labels_and_cardinality.md) — фундаментальные концепции кардинальности.
