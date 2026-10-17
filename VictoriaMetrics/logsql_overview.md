# LogsQL: язык запросов VictoriaLogs

**Актуально для:** VictoriaLogs v1.53.x (LTS-линия v1.52.x)

## Определения

**LogsQL** — pipeline-язык запросов [VictoriaLogs](https://docs.victoriametrics.com/victorialogs/): фильтрация, извлечение структуры на лету и аналитика над логами. Запрос — фильтр (или их последовательность, объединённая `AND`/`OR`/`NOT`), затем опциональная цепочка пайпов через `|`, где результат одной операции подаётся на вход следующей:

```logsql
<фильтры> | <трансформации> | <агрегация> | <пост-фильтрация>
```

**Слово (word)** — токен из букв, цифр и подчёркиваний; именно по словам ищут full-text-фильтры (word/phrase/prefix). Всё остальное (пробелы, пунктуация) — разделители.

**Поле (log field)** — именованный атрибут записи. Служебные: `_time` (timestamp), `_msg` (сообщение, цель full-text поиска), `_stream` / `_stream_id` (принадлежность к потоку). Имена полей регистрозависимы; точка в имени допустима (`log.level`).

**Поток (stream)** — группа лог-записей с одинаковым набором значений stream-полей (`_stream_fields` при приёме). Потоки — единица хранения и сжатия: данные одного потока лежат рядом, что ускоряет выборку `{app="nginx"}` и повышает компрессию.

## Базовые концепции

### Структура запроса и синтаксис

- Запрос обязан содержать минимум один фильтр. Веб-UI (`/select/vmui`) и Grafana-плагин сами передают выбранный временной диапазон, поэтому `_time:` в них обычно не нужен; в API/CLI временной фильтр добавляйте всегда.
- `AND` между фильтрами можно опускать: `_time:5m error` ≡ `_time:5m AND error`.
- `NOT` пишется словом или через `-`/`!`; короткие отрицания фильтров — `!=`, `!~`.
- Приоритет: `NOT` > `AND` > `OR`. Сомневаетесь — скобки: `error -(buggy_app OR foobar)`.
- Многострочные запросы и комментарии `#` допустимы; в конце запроса можно поставить `;` (удобно определять границу при программной сборке).
- Слово, совпадающее с ключевым, заключается в кавычки: `"and"`. Кавычки (`"`, `'`, бэктики) безопасно использовать всегда; если запрос собирается из внешнего ввода — экранируйте всё.

### Временные фильтры

Временной фильтр — главный способ сократить объём сканируемых данных (партиционирование по дням):

```logsql
_time:5m                          # последние 5 минут
_time:24h                         # последние сутки
_time:[2026-01-01T00:00:00Z, 2026-01-02T00:00:00Z]
_time:1h level:error              # комбинация (AND)
```

Дополнительно: day range (`day_range[9:00:00, 18:00:00]`) и week range (`week_range[Mon,Fri]`) для поиска по времени суток/дня недели независимо от даты.

### Полнотекстовый поиск

```logsql
error                     # слово в _msg
"error: cannot find file" # точная фраза
erro*                     # префикс слова
*"connection reset"*      # подстрока (медленно на больших объёмах)
~"(?i)(err|warn)"         # regexp (медленно; регистрозависимый по умолчанию)
*                         # «всё» — валидный фильтр, не ломает сервер
```

Поиск по нескольким полям сразу: `*:error` (любое поле) или `log_*:error` (префикс имени поля; может быть медленным).

### Фильтры по полям (основные)

| Тип | Синтаксис | Комментарий |
| :--- | :--- | :--- |
| Word / phrase | `level:error`, `msg:"timeout exceeded"` | По умолчанию применяется к `_msg` |
| Exact | `field:=value` | Точное равенство (после токенизации) |
| Multi-exact | `field:in(v1, v2)` / `not_in(...)` | Несколько значений |
| Prefix | `field:erro*` | Префикс значения |
| Range | `status:>=400`, `latency:[1s, 5s]` | Числа, даты, длительности |
| Regexp | `path:~"/api/v[0-9]+/"` | Медленный фильтр |
| Пустое значение | `field:""` | Поле отсутствует или пусто |
| Subquery | `_stream_id:in(_time:1h \| top 3 (_stream_id) \| keep _stream_id)` | Фильтр по результату вложенного запроса |

### Потоки: как выбирать `_stream_fields`

Фильтрация по потоку — самая дешёвая: `{app="nginx"}`, `{app in (api, web)} -{env="dev"}`. Рекомендации:

- В потоки — низкокардинальные стабильные идентификаторы: `host`, `app`, `pod`, `env`, `_SYSTEMD_UNIT`.
- Высококардинальные значения (`trace_id`, `user_id`, `request_id`, timestamp-суффиксы) — обычные поля; они индексируются, но не должны попадать в stream-поля.
- Каждая новая комбинация stream-полей создаёт новый поток: millions потоков = взрыв памяти и деградация. Диагностика: `| stats by(_stream) count() | sort by (count) desc | limit 20`, метрика `vl_streams_created_total`, временный логинг новых потоков (`POST /internal/log_new_streams?seconds=10`).

## Пайпы (Pipes)

**Правило фильтрации после пайпов (v1.51.0+):** пост-фильтр, не начинающийся с `field_name:`, обязан иметь префикс `filter` — иначе `unexpected pipe`: `... | filter status>=400`, `... | filter !error`, `... | filter {host="x"}`. Исключение (с фикса v1.52.x): если фильтр начинается с нетокенного символа или `not`/`!`/`-`/`=`/`>`/`{`, префикс можно не писать. Безопаснее писать `filter` всегда.

Ключевые пайпы:

| Пайп | Назначение | Пример |
| :--- | :--- | :--- |
| `fields` | Только перечисленные колонки (меньше I/O) | `\| fields _time, host, _msg` |
| `filter` | Явный пост-фильтр | `\| filter status>=400` |
| `sort by` | Сортировка | `\| sort by (_time desc)` |
| `limit` | Число возвращаемых строк | `\| limit 100` |
| `top` | Топ-N по полям (+`hits`, `rank`) | `\| top 10 by (host)` |
| `stats` | Агрегаты, в т.ч. `by()` и бакеты времени | `\| stats by(host) count() as n` |
| `extract` / `extract_regexp` | Извлечение полей по шаблону/regexp | `\| extract "user=<user_id> status=<status>"` |
| `unpack_json` / `unpack_logfmt` / `unpack_syslog` | Парсинг форматов в поля | `\| unpack_json` |
| `replace` / `replace_regexp` | Замена внутри поля | `\| replace("old", "new") at msg` |
| `format` | Новое поле из шаблона | `\| format "User <user> from <ip>" as summary` |
| `coalesce` | Первое непустое значение (v1.52.0) | `\| coalesce(user_id, uid, "anon") as user` |
| `collapse_nums` | Шаблонизация: числа → плейсхолдеры | `\| collapse_nums` |
| `json_array_concat` | JSON-массив → строка (v1.52.0) | `\| json_array_concat tags, "," as s_tags` |
| `uniq` | Уникальные комбинации полей | `\| uniq with hits` |
| `stream_context` | Соседние строки потока (первым пайпом) | `\| stream_context(before 5, after 5)` |
| `field_names` / `field_values` | Исследование схемы | `\| field_values level` |
| `math` | Математика над stats-полями | `\| math (errors / total * 100) as rate` |
| `join` / `union` / `enrich` | Обогащение и объединение | см. официальную документацию |
| `block_stats` / `query_stats` / `total_stats` | Отладка стоимости запроса | см. сценарий «Медленные запросы» |

## Агрегации (stats)

```logsql
_time:1h | stats by(_time:1m, host) count() as req_per_min
# → строки по минутам и хостам
```

Функции: `count()`, `count() if (filter)` (условный счётчик), `sum/avg/min/max/median/stddev(field)`, `quantile(0.95, field)`, `histogram(field)`, `rate(field)` и др. Бакеты времени: `by(_time:1m)`, `by(_time:5m:offset 30m)` со смещением таймзоны. Строки бакетов, не имеющие входов, пропускаются.

**Кардинальность в stats:**

- `count_uniq(field)` — **точный**, хранит все уникальные значения в памяти; на больших cardinality ограничивайте: `count_uniq(ip) limit 1_000_000`.
- `count_uniq_hash(field)` — **приблизительный** (хеши, возможны коллизии → занижение), быстрее и легче по памяти на огромных множествах.
- `top N by (field)` — топ по частоте, без удержания всех значений в памяти.

## Query options (опции запроса)

Передаются как аргументы запроса (POST `query` + опции):

- `concurrency=N` — параллелизм чтения;
- `parallel_readers=NP/2` — число параллельных readers (по умолчанию пропорционально CPU);
- `time_offset=24h` — сдвинуть `_time` (backfill-сценарии, сравнение «сейчас vs вчера»);
- `global_filter=<filter>` — применить фильтр ко всем временным диапазонам (в т.ч. внутри subqueries);
- `ignore_global_time_filter=1` — игнорировать внешний time filter (использовать осторожно);
- `allow_partial_response=1` — кластер: разрешить частичный ответ при недоступности части vlstorage.

## Практические сценарии (SRE)

### 1. Процент ошибок по хостам

```logsql
_time:1h app:web
| stats by(host)
    count() as total,
    count() if (status>=400) as errors
| math (errors / total * 100) as error_rate
| filter error_rate:>5
| sort by (error_rate desc)
```

### 2. Топ шаблонов ошибок

Числа, ID и таймстемпы в сообщениях мешают группировать — `collapse_nums` приводит сообщения к шаблону:

```logsql
_time:24h level:error
| collapse_nums
| stats by(_msg) count() as hits
| sort by (hits desc)
| limit 20
```

### 3. Топ потоков по объёму (поиск «шумных» сервисов)

```logsql
_time:1h | top 10 by (_stream)
```

### 4. Нормализация полей из разных версий API

```logsql
_time:15m | coalesce(user_id, legacy_uid, "guest") as user | stats by(user) count()
```

### 5. Разбор медленного запроса

**Серверный уровень.** Медленные запросы (по умолчанию дольше 5s — флаг `-search.logSlowQueryDuration`) попадают в логи; копятся в `vl_slow_queries_total`. Счётчики per-query I/O: `vl_storage_per_query_processed_rows`, `vl_storage_per_query_read_bytes` и др.

**Уровень запроса.** Статистика исполнения — пайпы, а не отдельный HTTP-эндпоинт:

```logsql
# Итоговая статистика: BlocksProcessed, RowsProcessed, BlocksSearchDuration и т.д.
_time:24h level:error | query_stats

# Стоимость по блокам (где именно «дорого») — отладочный пайп
_time:24h | filter level:error | block_stats
```

**Корректирующие действия:** сузить `_time`; добавить stream-фильтр `{...}`; вынести дорогие regexp/substring после селективных фильтров; ограничить колонки `| fields`; увеличить бакеты `by(_time:5m)`; снизить cardinality stream-полей; для кластера — проверить доступность vlstorage (`allow_partial_response`).

### 6. Логирование новых потоков (диагностика cardinality)

```bash
curl -X POST 'http://localhost:9428/internal/log_new_streams?seconds=10'
# → 10 секунд в лог пишется каждая новая комбинация stream-полей
```

### 7. Выборка и экспорт

```bash
# Топ-100 ошибок за час (JSON lines)
curl -sG 'http://localhost:9428/select/logsql/query' \
  --data-urlencode 'query=_time:1h level:error | sort by (_time desc) | limit 100'

# Hits-статистика для Grafana (гистограмма «сколько логов в бакете»)
curl -sG 'http://localhost:9428/select/logsql/hits' \
  --data-urlencode 'query=level:error'
```

Удаление данных ( Enterprise-фича `-retentionPeriod` не заменяет; задаётся флагом `-deleteAuthKey` / authKey запроса):

```bash
curl -X POST 'http://localhost:9428/delete/run_task?filter={app=nginx}&authKey=<deleteAuthKey>'
# задача удаления запускается асинхронно; статус — /delete/list_tasks
```

## Эксплуатация VictoriaLogs (devops/sre)

### Установка

```bash
# Бинарник (пример v1.53.0; Linux amd64/arm64, macOS, Windows, FreeBSD/OpenBSD — артефакты релизов)
curl -L -O https://github.com/VictoriaMetrics/VictoriaLogs/releases/download/v1.53.0/victoria-logs-linux-amd64-v1.53.0.tar.gz
tar xzf victoria-logs-linux-amd64-v1.53.0.tar.gz
./victoria-logs-prod -storageDataPath=/var/lib/victoria-logs -httpListenAddr=:9428
```

```bash
# Docker (пиньте версию)
docker run -d --name victoria-logs -p 9428:9428 \
  -v /var/lib/victoria-logs:/victoria-logs \
  docker.io/victoriametrics/victoria-logs:v1.53.0 \
  -storageDataPath=/victoria-logs
```

Для Kubernetes — чарты `victoria-logs-single` / `victoria-logs-cluster` / `victoria-logs-collector` и CRD `VLSingle`/`VLCluster`; systemd-сценарий — в [victorialogs_k8s_setup.md](../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) нет, для bare-metal используйте unit:

```ini
# /etc/systemd/system/victorialogs.service (фрагмент)
[Service]
User=victorialogs
ExecStart=/usr/local/bin/victoria-logs-prod \
  -storageDataPath=/var/lib/victoria-logs \
  -httpListenAddr=:9428 \
  -retentionPeriod=30d
Restart=on-failure
LimitNOFILE=65536
```

### Порты и эндпоинты

| Эндпоинт | Назначение |
| :--- | :--- |
| `:9428/insert/*` | Приём логов (jsonline, Elasticsearch, Loki, OTLP, syslog и др.) — см. [victorialogs_ingestion.md](./victorialogs_ingestion.md) |
| `:9428/select/logsql/query` | Выполнение LogsQL-запросов |
| `:9428/select/logsql/hits` | Hits-гистограмма для Grafana |
| `:9428/select/vmui` | Встроенный Web UI |
| `:9428/select/vmalert/*` | Прокси на vmalert (интеграция UI) |
| `:9428/metrics` | Метрики Prometheus (**тот же порт**, отдельного 9429 нет) |
| `:9428/internal/*` | Управление: partition attach/detach/snapshot, force_merge, log_new_streams, delete |
| `:9428/debug/pprof/*` | pprof (heap, profile) для профилирования |

### Retention и партиции

- По умолчанию хранится `[now-7d, now]`; записи вне диапазона **отклоняются на приёме** (`-retentionPeriod`, минимум `1d`). Будущие метки времени: до `now+2d` (`-futureRetention`).
- Старые суточные партиции `<-storageDataPath>/partitions/YYYYMMDD` удаляются фоновой очисткой; каждое отклонение пишется в счётчик `vl_rows_dropped_total`.
- Дисковые лимиты (взаимоисключающие с точностью до комбинации с временем): `-retention.maxDiskSpaceUsageBytes=100GiB` или `-retention.maxDiskUsagePercent=80`. Чтобы чистить только по диску: `-retentionPeriod=100y -retention.maxDiskUsagePercent=85`.
- Остановка приёма при нехватке места: `-storage.minFreeDiskSpaceBytes` (по умолчанию ~10 GB) → режим read-only, метрика `vl_storage_is_read_only=1`.
- Бэкап партиций: `POST /internal/partition/snapshot/create?partition_prefix=YYYYMMDD` → rsync снапшота → `POST /internal/partition/detach?name=YYYYMMDD` (ждёт завершения читающих запросов) → удаление каталога. Multi-tier (NVMe→HDD) строится на той же последовательности — детально в [victorialogs_internals.md](./victorialogs_internals.md).
- Принудительная компакция старых партиций: `POST /internal/force_merge?partition_prefix=YYYYMMDD`.

### Мониторинг

Метрики — на `http://localhost:9428/metrics`. Ключевые (полный справочник — [Metrics of VictoriaLogs](https://docs.victoriametrics.com/victorialogs/metrics/)):

| Метрика | Смысл |
| :--- | :--- |
| `vl_rows_ingested_total` | Принято строк (норма ingest) |
| `vl_bytes_ingested_total` | Принято байт |
| `vl_rows_dropped_total` | Отбрасано (вне retention и т.п.) — алерт `rate(...) > 0` |
| `vl_too_long_lines_skipped_total` | Строки длиннее лимита |
| `vl_http_requests_total` / `vl_http_request_duration_seconds` | HTTP-трафик API |
| `vl_slow_queries_total` | Медленные запросы (> `-search.logSlowQueryDuration`) |
| `vl_storage_rows` / `vl_data_size_bytes` / `vl_compressed_data_size_bytes` | Объём и сжатие |
| `vl_streams_created_total` | Создание потоков (cardinality-взрыв) |
| `vl_free_disk_space_bytes` / `vl_total_disk_space_bytes` | Диск |
| `vl_storage_is_read_only` | Read-only из-за места |
| `vl_active_merges` / `vl_merges_total` | Фоновые компакции |

Для автоскрейпа vmagent'ом / кластера смотрите [vmagent_overview.md](./vmagent_overview.md) и [victorialogs_internals.md](./victorialogs_internals.md); compose-демо с мониторингом и алертингом — в репозитории VictoriaLogs (`deployment/docker`).

### Мультитенантность и безопасность

- Тенант — заголовки `AccountID` / `ProjectID` (uint32, по умолчанию 0) при записи и запросе. Сам VT **не делает per-tenant авторизацию** — ставьте [vmauth](./vmauth_overview.md) с маршрутизацией правил на tenant.
- Базовая защита: `-httpAuth.username/-password` (Basic Auth на весь HTTP) и authKey'ы служебных эндпоинтов: `-metricsAuthKey`, `-flagsAuthKey`, `-deleteAuthKey`, `-pprofAuthKey` (переопределяют `-httpAuth.*`).
- TLS — флаги `-tls` + сертификаты; на практике чаще — прокси перед VT.
- Удаление логов только через `/delete/run_task` (Enterprise) с authKey — полезно ограничивать сетью.

### Валидация

```bash
curl -s http://localhost:9428/health
# → OK

# Тестовая запись и чтение
echo '{"level":"info","msg":"validation ping"}' | \
  curl -s -X POST -H 'Content-Type: application/stream+json' --data-binary @- \
  'http://localhost:9428/insert/jsonline'
curl -sG http://localhost:9428/select/logsql/query --data-urlencode 'query=_time:5m "validation ping"'
# → запись в ответе

# Метрики и Web UI
curl -s http://localhost:9428/metrics | head
# → открыть http://<host>:9428/select/vmui и выполнить запрос *| limit 10
```

## Troubleshooting

| Симптом | Причина | Действие |
| :--- | :--- | :--- |
| `/health` не отвечает | Процесс не запущен / слушает другой адрес | `systemctl status`, `-httpListenAddr` |
| Запросы возвращают 0 строк | Узкий `_time`; данные вне retention; тенант не тот | Расширить окно; проверить `vl_storage_log_max_timestamp_seconds`; заголовки AccountID/ProjectID |
| Медленные запросы | Широкий `_time`, нет stream-фильтра, regexp, высокая cardinality | `query_stats` / `block_stats`; сузить окно; `{...}`-фильтр; `vl_slow_queries_total` |
| Растёт `vl_rows_dropped_total` | Записи вне retention или `now+futureRetention` | Часы источника; `-futureRetention`; алерт на метрику |
| Растёт `vl_streams_created_total` | Взрыв cardinality stream-полей | `/internal/log_new_streams`; убрать высококардинальные поля из `_stream_fields` |
| Ингест остановлен, `vl_storage_is_read_only=1` | Место на диске ниже `-storage.minFreeDiskSpaceBytes` | Освободить диск; расширить retention-лимиты |
| `unexpected pipe` на пост-фильтре | v1.51.0+: нет префикса `filter` | `... \| filter <условие>` |
| Логи >256 KiB обрезаются/отбрасиваются | Лимит строки | `-insert.maxLineSizeBytes` (можно снизить; потолок 2 MB зашит в код) |
| Слишком много полей в JSON-строке | Лимит полей на строку | `-insert.maxFieldsPerLine` (по умолчанию 1000) |
| OOM при `count_uniq` | Точный подсчёт удерживает значения в памяти | `count_uniq(...) limit N`; `count_uniq_hash`; `top` |

## Рекомендации по производительности

1. Всегда ограничивайте `_time`; в Web UI полагайтесь на выбранный диапазон.
2. Ставьте селективные фильтры (stream, exact, range) до regexp/substring/`*:`-поиска.
3. Используйте `{stream}`-фильтры — они сокращают чтение блоков на диске сильнее любых полевых фильтров.
4. `| fields` в конце — уменьшает объём ответа и чтение колонок.
5. Исследуйте схему пайпами `field_names` / `field_values` вместо сканирования `*`.
6. Сортировка и `count_uniq` без лимита дороги по памяти — лимитируйте.
7. Память: `-memory.allowedPercent` (по умолчанию 60) кэши VictoriaLogs; docs рекомендуют держать ~50% RAM свободными, а на `-storageDataPath` — минимум 20% свободного места.
8. `LimitNOFILE` — повышайте при большом числе сегментов/потоков (единственная «настройка, которую почти всегда нужно сделать» по FAQ вендора).

## Ограничения и особые случаи

- Лимит размера лог-строки — 2 MB (зашит); `-insert.maxLineSizeBytes` лишь снижает порог (по умолчанию 256 KiB).
- Имя поля — максимум 128 байт; число полей на строку — `-insert.maxFieldsPerLine` (1000).
- `count_uniq` точный, но память-ограниченный; `count_uniq_hash` приблизительный (возможны коллизии хешей → занижение).
- Кластер: при недоступности части vlstorage запросы падают, если не задан `allow_partial_response` (см. [victorialogs_internals.md](./victorialogs_internals.md)).
- `stddev`, `coalesce`, `json_array_concat` требуют актуальных версий (соответственно с v1.49.0 и v1.52.0).
- Backfill-правил vmalert с кастомным time filter имеет ограничения vmalert — см. [vmalert_overview.md](./vmalert_overview.md).

## Дополнительная информация

### Ссылки

- [LogsQL (официально)](https://docs.victoriametrics.com/victorialogs/logsql/) — полный справочник фильтров и пайпов;
- [LogsQL Examples](https://docs.victoriametrics.com/victorialogs/logsql-examples/) / [SQL→LogsQL](https://docs.victoriametrics.com/victorialogs/sql-to-logsql/) / [LogQL→LogsQL](https://docs.victoriametrics.com/victorialogs/logql-to-logsql/) — рецепты и миграции;
- [Metrics of VictoriaLogs](https://docs.victoriametrics.com/victorialogs/metrics/) — справочник метрик;
- [vlogscli](https://docs.victoriametrics.com/victorialogs/querying/vlogscli/) — рекомендуемый CLI для запросов;
- [Песочница](https://play-vmlogs.victoriametrics.com/) — Web UI с демо-данными.

### См. также

- [VictoriaLogs: внутреннее устройство](./victorialogs_internals.md) — хранение, партиции, кластер;
- [Инжест логов](./victorialogs_ingestion.md) — протоколы и коллекторы;
- [Развёртывание в Kubernetes](../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) — Helm/operator и мониторинг;
- [vmalert](./vmalert_overview.md) — алерты на LogsQL (`type: vlogs`);
- [vmauth](./vmauth_overview.md) — авторизация, тенанты, балансировка;
- [Логирование: глубокое погружение](../Concepts/Observability_and_Monitoring/logs_deep_dive.md) — сравнение систем логирования.
