# Инжест логов в VictoriaLogs: протоколы и практика

## Определения

**Ingestion (приём, инжест)** — процесс доставки логов (строк/JSON/текста) в VictoriaLogs через один из HTTP-эндпоинтов на порту `9428`. VictoriaLogs не хранит предопределённую схему: лог — это исходная строка + произвольный набор полей (JSON), поля индексируются автоматически.

**Stream / поток** — логически сгруппированный набор записей с одинаковым набором `_stream_fields` (по умолчанию — все поля строкового типа). Ключевое понятие для дедупликации, retention и ограничения кардинальности потоков.

**lucene-совместимый путь запроса** — возможность принудительной маршрутизации инжеста в конкретный поток (`/insert/jsonline?stream_fields=...&_stream_id=...`).

## Базовые концепции

### Принципы приёма

- **Схема не требуется:** любое JSON-поле автоматически становится «полем лога» и индексируется как текст (по умолчанию) или как числовое поле (`_fields.numeric` — Enterprise).
- **Streams** создаются автоматически по комбинации выбранных полей; слишком большое число потоков раздувает метаданные и замедляет запросы «среди всех».
- Движок полагается на заголовки/параметры для управления путями приёма и игнорирования полей.
- Инжест и чтение разделены по префиксам: `/insert/*` (запись), `/select/*` (чтение).

### Ключевые понятия

| Понятие | Значение |
| :--- | :--- |
| `-httpListenAddr` | Порт, по умолчанию `:9428` |
| `/insert/jsonline` | Универсальный JSON Lines приём |
| `/insert/loki/api/v1/push` | Loki-совместимый приём |
| `/insert/elasticsearch/_bulk` | Elasticsearch Bulk API |
| `/insert/opentelemetry/v1/logs` | OTLP |
| `/insert/syslog` | RFC3164/RFC5424 UDP/TCP |
| `/insert/datadog/api/v2/logs` | Datadog Agent |
| `VL-Msg-Field` | Имя поля, из которого брать «сообщение» |
| `VL-Ignore-Fields` | Перечень полей, не сохраняемых |
| `_stream_fields` | Поля, по которым строится стрим |
| `_time` | Поле времени (автоопределение) |
| `_msg` | Поле сообщения (автоопределение) |
| `_stream_id` | Явно заданный идентификатор стрима |

## Практические сценарии

### 1. Выбор формы записи и первичная настройка

```bash
# VictoriaLogs запускается с указанием пути данных и порта
victoria-logs -storageDataPath=/var/lib/victorialogs

# Проверка health
curl -s http://localhost:9428/health
# → 200 OK
```

### 2. Прямая отправка JSON Lines (curl-пример)

```bash
curl -X POST http://localhost:9428/insert/jsonline \
  -H 'Content-Type: application/json' \
  -d '{"_msg":"hello from JSON","level":"info","host":"web-1"}'
```

Каждая строка — отдельный лог. Поле `_time` можно не указывать: VictoriaLogs возьмёт локальное время получения.

### 3. Настройка через vmauth / nginx и безопасность

Доступ к `/insert/*` должен быть закрыт для внешних пользователей. Рекомендуется:

```yaml
# пример конфигурации vmauth
users:
  - username: logger
    password: secret
    url_prefix: http://victorialogs:9428/
```

Или на уровне nginx:

```nginx
location /insert/ {
    allow 10.0.0.0/8;
    deny all;
    proxy_pass http://victorialogs:9428;
}
```

### 4. Сбор системных логов из журналов уровня ОС (journald / syslog)

Для сбора `/var/log`, systemd-journald и rsyslog удобен паттерн «агент → JSON Lines → `/insert/jsonline`».

**Вариант А: Vector → VictoriaLogs (рекомендуется, богатые метаданные)**

```toml
# vector.toml
[sources.journald]
type = "journald"

[transforms.norm]
type = "remap"
inputs = ["journald"]
source = '''
.meta = { "service" = "journald", "host" = ._HOSTNAME ?? .host }
'''

[sinks.vl]
type = "http"
inputs = ["norm"]
uri = "http://victorialogs:9428/insert/jsonline?stream_fields=service,host"
encoding.codec = "json"
```

**Вариант Б: прямая пересылка syslog (RFC3164/RFC5424)**

VictoriaLogs принимает syslog на `/insert/syslog` (TCP/UDP): на стоке rsyslog/`systemd` включайте пересылку на адрес VictoriaLogs. Формат — RFC3164/5424; время из syslog-заголовка попадает в `_time`.

Правила кардинальности `_stream_fields` применяются и тут: выбирайте фиксированный набор (host/service), а не `_msg`.

### 5. Экспорт данных из VictoriaLogs

```bash
# Выборка через select API (JSON Lines)
curl -sG 'http://localhost:9428/select/logsql/query' \
  --data-urlencode 'query=level:error _time:24h | limit 100' \
  | jq . > errors_today.json

# Сохранение в файл
curl -sG 'http://localhost:9428/select/logsql/query' \
  --data-urlencode 'query=_stream_hash:abcd1234 _time:7d' > export.jsonl
```

- API `/select/logsql/query` возвращает результаты в формате JSON-lines; ограничение выборки — выражением `limit` (не нагружайте большими выгрузками прод);
- Для **полного** выноса данных (миграция/архив) такая выборка не годится: используйте бэкап каталога данных через [vmbackup](./vmbackup_restore.md) (работает по снапшоту `/snapshot/create` на 9428) или копию `-storageDataPath` на остановленном инстансе;
- Потоковый перенос больших объёмов — постранично с курсором по `_time` (по 10–100 тыс. строк на итерацию).

## Валидация установки

```bash
# 1) Проверить, что порт слушает и health OK
curl -s http://localhost:9428/health

# 2) Записать тестовую запись и прочитать её
curl -s 'http://localhost:9428/insert/jsonline' \
  -d '{"_msg":"test","level":"debug"}'
curl -s 'http://localhost:9428/select/logsql/query' \
  -d 'query=level:"debug"' | jq .
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `422 Unprocessable Entity` | Отправлено не JSON Lines (нет переводов строк) | Проверить формат, Content-Type, наличие `\n` между записями |
| `413 Request Entity Too Large` | Большой batch | Разбить на пакеты (например, по 1–10 МБ) |
| `401/403` | Ограничение доступа | Проверить IP-фильтры и аутентификацию vmauth |
| Данные не появляются в запросах | `VL-Ignore-Fields` перечислил нужное поле; источник пишет в другой стрим | Проверить заголовки/`stream_fields`; `query_stream_fields` |
| Много потоков (кардинальность) | `_stream_fields` выбран неудачно (например, `_msg`) | Выбрать фиксированный набор полей уровня сервиса/окружения |
| Устаревшие временные метки не индексируются | `_time` далеко от now() | Согласовать тайм-зону источников; проверить флаг `-db.lockAnti-lock`/`-storage.maxRetentionPeriod` |

## Рекомендации по эксплуатации

- Ограничивайте `_stream_fields` фиксированным набором (например, `["host","service","env"]`), а не всеми полями — это ключ к стабильной кардинальности стримов.
- Базируйте поиск на индексируемых полях; глубокий grep по «сырому» строковому контенту (`fulltext`) оставляйте в `_msg`.
- Настройте retention через `-retentionPeriod` / `-storage.maxRetentionPeriod` и чистите старые данные через `victoria-logs` флаг `-retention`. Бэкап — только через `vmbackup`.
- Для CPU тяжёлых/часто повторяемых запросов используйте parsing/LogsQL в vmui до передачи в дашборды.

## Ограничения и особые случаи

- Инжест не ведёт транзакций в классическом смысле: при сбое пакет может быть принят частично (это заложено в дизайн — «лучшее усилие» + WAL). Для строгой гарантии используйте ретраи на клиенте.
- Попытка задать числовое поле через Enterprise `_fields.numeric` — вне Community; в Open Source числовые поля остаются текстом.
- `/insert/opentelemetry` требует корректного Content-Type (`application/x-protobuf` для OTLP/HTTP) и не принимает gzip+protobuf внутри одного запроса без настройки.

## Дополнительная информация

### См. также

- [VictoriaLogs: внутреннее устройство](./victorialogs_internals.md) — формат хранения, индексация;
- [VictoriaLogs: настройка в Kubernetes](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) — Helm, operator и vlmg;
- [vmauth: прокси и аутентификация](./vmauth_overview.md) — защита `/insert/*`;
- [LogsQL: обзор](./logsql_overview.md) — запросы к принятым логам;
- [vmbackup/vmrestore](./vmbackup_restore.md) — бэкап и экспорт каталога данных.
# force reindex test
