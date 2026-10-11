# vmctl: миграция исторических данных в VictoriaMetrics

## Определения

**vmctl** — CLI-утилита VictoriaMetrics для переноса исторических метрик в VictoriaMetrics из Prometheus, InfluxDB, OpenTSDB, Graphite, Mimir/Thanos (через Prometheus Remote Read) и между инстансами VictoriaMetrics без простоя.

**Native mode (`vmctl victoriametrics`)** — самый быстрый способ переноса: работает напрямую между VictoriaMetrics-совместимыми серверами, копируя уже упакованные блоки данных без перекодировки.

## Базовые концепции

### Режимы импорта

| Режим | Откуда | Тип | Скорость |
| :--- | :--- | :--- | :--- |
| `prometheus` | Снапшот TSDB Prometheus (`--prom-snapshot`), remote read (`--prom-remote-read-url`) | PromQL-данные, перекодировка | средняя |
| `influxdb` | InfluxDB (SQL-запросы) | перекодировка | средняя |
| `opentsdb` | OpenTSDB HTTP API | перекодировка | средняя |
| `graphite` | Graphite Carbon | перекодировка | средняя |
| `victoriametrics` | source VictoriaMetrics (single/cluster) | **native, без перекодировки** | высокая |

### Как работает native-режим

```
source VM ── native export (интервалами) ──► vmctl ✔ контроль размеров блока
   └────────── dst VM (/api/v1/write/native) ◄──── vmctl
```

- Данные копируются «блоками» по выбранным тайм-диапазонам; при ошибке сегмента — ретраи.
- Он поддерживает миграцию в cluster (`--vm-native-dst-addr` + `--vm-native-src-account-id`/`--vm-account-id`) и тенанты.
- Минус: требует доступности обоих серверов в момент миграции; блоки повторно не индексируются на приемнике.

## Практические сценарии

### 1. Prometheus → VictoriaMetrics из снапшота TSDB

```bash
# 0. Создать снапшот в Prometheus (не требует остановки)
#    curl -XPOST http://prometheus:9090/api/v1/admin/tsdb/snapshot

vmctl prometheus \
  --prom-snapshot=/prometheus/snapshots/20260922T120000Z-<sha> \
  --vm-addr=http://localhost:8428/api/v1/write \
  --vm-concurrency=4 \
  --vm-batch-size=2000
```

### 2. Mimir / Thanos → VictoriaMetrics через Remote Read

Данные вычитываются по API Remote Read (скорость ниже, чем из снапшота):

```bash
vmctl prometheus \
  --prom-remote-read-url=http://mimir:9009/prometheus \
  --vm-addr=http://localhost:8428/api/v1/write
```

### 3. VictoriaMetrics → VictoriaMetrics (рекомендуется, native)

```bash
vmctl victoriametrics \
  --vm-native-src-addr=http://source-vm:8428 \
  --vm-native-dst-addr=http://dest-vm:8428 \
  --vm-native-step-interval=24h \
  --vm-native-filter-time-start=2026-09-01T00:00:00Z
```

Флаги native-режима: `--vm-native-step-interval` (разбиение на диапазоны), `--vm-native-filter-time-start`/`--vm-native-filter-time-end`, `--vm-native-src-account-id` (для cluster).

### 4. InfluxDB → VictoriaMetrics

```bash
vmctl influxdb \
  -influxdb.addr=http://influxdb:8086 \
  -influxdb.database=metrics \
  -vm-addr=http://localhost:8428/api/v1/write
```

## Валидация установки

```bash
vmctl --version
# → vmctl v1.110.0 ...

# Проверка достижимости источников и прав
vmctl prometheus --prom-snapshot=/path/not/exists   # ошибка сразу
curl -s http://localhost:8428/api/v1/query -d 'query=count({__name__=~".*"})'
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Ошибки `write timeout` на приемнике | Не хватает `-remoteWrite.queues`/`-maxInsertRequestSize` | Уменьшить `--vm-batch-size`/concurrency, увеличить таймауты VM |
| Медленный импорт из Prometheus | Перекодировка блоков, большое число серий | Использовать native-режим, увеличить concurrency |
| Пропущенные старые точки | Приемник режет данные старше retention | На приемнике временно выставить больший retention или писать в другой тенант |
| Дубликаты метрик после миграции | Одинаковые серии из нескольких диапазонов | Сделать идемпотентно (дедупликация на приемнике по таймстампам) |

## Рекомендации по эксплуатации

- Перед большой миграцией запустите пилот на «пробном» диапазоне (`--vm-native-filter-time-*`) и сверьте кардинальность.
- Проверяйте CPU/диск приемника: при конверсии non-native режима нагрузка на CPU выше.
- Для непрерывного переноса данных «на живую» совмещайте миграцию истории (vmctl) с переключением vmagent/remote-write на новый VM с overlapping retention и дедупликацией.

## Ограничения и особые случаи

- Native-режим не может переносить между разными мажорными версиями формата хранения — совместимость версий учитывайте заранее.
- `prometheus`-импорт из снапшота быстрее remote-read по размеру, но требует доступа к ФС Prometheus.
- vmctl не используется для постоянной репликации — только одноразовый перенос истории.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — базовые примеры vmctl;
- [vmbackup/vmrestore](./vmbackup_restore.md) — регулярное резервное копирование;
- [Prometheus: TSDB и снапшоты](../Prometheus/concepts/tsdb.md).
# force reindex test
