# VictoriaMetrics Enterprise: расширенные функции

## Определения

**VictoriaMetrics Enterprise** — платная редакция с расширенными производственными функциями поверх той же data-модели/формата хранения, что и Community. Модель данных и формат хранения **идентичны** — переход Community→Enterprise не требует переиндексации или миграции данных (нужен файл лицензии и включение флагов).

**Лицензирование** — подписка на инстансы; запуск с расширенными флагами требует наличие лицензионного ключа (флаги серии `-license...`). Без ключа Enterprise-сборка предоставляет набор только базовых функций.

## Базовые концепции

### Ключевые Enterprise-функции VictoriaMetrics

| Функция | Где | Что даёт |
| :--- | :--- | :--- |
| **Downsampling** | vmstorage / single-node | Автоматическая агрегация старых данных (уменьшение занимаемого места, типично для периода >30д) |
| **Per-series retention filters** | vmstorage / single-node | Разное хранение для разных серий (например, лоу-частотные метрики держать меньше) |
| **vmbackupmanager** | vmbackup | Планировщик бэкапов + retention (хранить N копий/периоды) |
| **vmgateway** | отдельный компонент | Токен/JWT-аутентификация шлюз к VM; proxy для записи/чтения |
| **Storage node groups** | cluster | Изоляция данных тенантов на выделенных группах `vmstorage` |
| **Streaming aggregation (vmagent)** | vmagent | Агрегация на стороне агента (см. также [vmagent_overview.md](./vmagent_overview.md)) |
| **Доп. функции MetricsQL** | vmselect | `histogram_quantiles` и др. (см. [metricsql_reference.md](./metricsql_reference.md)) |
| **vmanomaly** | отдельный компонент | Anomaly detection для метрик (модельный ML-сервис) |

### Зачем это в заметках

На прод-e решения «долго хранить дешевле» и «изолировать тенантов» упираются в эти функции: интервью «чем Enterprise отличается, когда оправдан», и задачи оптимизации затрат хранения без потери гранулярности.

## Практические сценарии

### 1. Downsampling (агрегация старых серий)

Снижает объём для периодов, где нужен тренд, но не point-точность:

```yaml
# retentionFilter.yml (указывается флагом -retentionFilter=...)
- match: '{__name__=~"node_(cpu|mem).*"}'
  interval: 5m          # агрегация в 5-минутные значения
  offset: 168h          # начинается после недели
```

- Задаётся на `vmstorage`/single-node; флаг `-retentionFilter=/path/to/file.yml` (в cluster также может указываться per-node);
- Запускайте в «окно»: применение проходит в фоне и создаёт доп. merge-нагрузку;
- Не затрагивает горячие данные (offset начинает применяться с указанного сдвига от now()).

### 2. Per-series retention filters

Для длительного хранения только важных серий:

```yaml
# retentionFilter.yml
- match: '{env="prod"}'                       # серии прода
  retentionPeriod: 90d
- match: '{__name__=~"node_cpu_seconds_total"}'  # CPU — 30 дней
  retentionPeriod: 30d
- match: '{__name__=~".*"}'  # всё прочее — базовый
  retentionPeriod: 7d
```

Преимущество: гранулярность/место управляются per-series, а не одним `-retentionPeriod` для всех.

### 3. vmgateway (аутентификация и маршрутизация)

```bash
# Шлюз с JWT: клиенты аутентифицируются, а доступ к записи/чтению ограничивается правами
vmgateway \
  -httpListenAddr=:8431 \
  -auth.token=$GATEWAY_TOKEN \
  -write.url=http://vminsert:8480/insert/0/prometheus/ \
  -read.url=http://vmselect:8481/select/0/prometheus/
```

- Клиент шлёт `Authorization: Bearer <jwt>`; gateway проверяет и проксирует;
- Удобно как внешняя точка доступа для команд без предоставления прямого доступа к vmauth/vminsert.

### 4. vmbackupmanager: планирование и retention бэкапов

```bash
vmbackupmanager \
  -storageDataPath=/var/lib/vmstorage \
  -snapshot.createURL=http://vmstorage-0:8482/snapshot/create \
  -dst=s3://backups/victoria-cluster/0 \
  -run=0 2 * * *        # cron-выражение запуска
```

- Автоматически делает снапшот и инкремент по расписанию (`-run`);
- Retention (хранить последние N копий / по времени) задаётся отдельной конфигурацией — сверяйтесь с официальной документацией (раздел `vmbackupmanager`);
- Плановая ротация избавляет от ручных CRON-скриптов чистки.

### 5. Streaming aggregation в vmagent (кратко)

Флаг `-streamAggr.config=/path/streamAggr.yml` (подробно — в [vmagent_overview.md](./vmagent_overview.md), секция Streaming Aggregation).

## Валидация установки

```bash
# Лицензия загружена корректно
curl -s http://localhost:8428/api/v1/status/buildinfo | jq -r '.data.productName'
# → VictoriaMetrics (cluster/node) [enterprise]

# Downsampling/retention фильтр активен
curl -s http://vmstorage-0:8482/flags | grep -E "retentionFilter|streamAggr"
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Функция недоступна / «trial expired» | Лицензия истекла/не загружена | Обновить ключ; проверить `-license` флаги |
| Downsampling не применяется | Ошибка в YAML / не тот формат `match` | Проверить синтаксис YAML, `victoria-metrics log` |
| vmbackupmanager не бэкапит | `-snapshot.createURL` неверный / нет прав | Убедиться что snapshot-эндпоинт отвечает |
| Per-series retention не учитывается | Формат совпал раньше (первый matching) | Упорядочить правила от частного к общему |

## Рекомендации по эксплуатации

- Переходите на Enterprise только при явной потребности (долгое хранение/изоляция/аномалии) — Community покрывает базовые кейсы;
- Лицензионные ключи храните в секретах (K8s secret / vault), не коммитьте в Git;
- Downsampling и per-series retention **проверяйте на тестовом инстансе** до прод-окна (merge-нагрузка перераспределяет диски);
- Для изоляции тенантов используйте `storage node groups` кластера в сочетании с [vmauth](./vmauth_overview.md).

## Ограничения и особые случаи

- Нет публичного формата Enterprise-данных: бэкапы/restore совместимы между Community/Enterprise, но downsampled-данные не «раскручиваются» обратно в полную гранулярность;
- Streaming aggregation в vmagent Enterprise — агрегирует в горячем виде; полные исторические исходники следует держать в исходном виде отдельно, если нужны;
- Retention/downsampling применяются фоном: сразу после включения места мало освобождается — следите за `vm_data_size_*`.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — сравнение Community/Enterprise, флаги;
- [vmagent: Streaming Aggregation](./vmagent_overview.md) — раздел про `-streamAggr.*`;
- [metricsql_reference.md](./metricsql_reference.md) — Enterprise-функции MetricsQL;
- [vmbackup/vmrestore](./vmbackup_restore.md) — бэкап и ротация (vmbackupmanager);
- [Операции с кластером](./cluster_operations.md) — storage node groups, RF.