# vmui: веб-интерфейс VictoriaMetrics

## Определения

**vmui** — встроенный веб-интерфейс VictoriaMetrics, доступный на HTTP-порту каждого компонента (`/vmui`): у single-node — `http://localhost:8428/vmui`, у `vmselect`/`vminsert` кластера — тот же путь. Его же использует VictoriaLogs на порту `9428` для LogsQL. Это «экспресс-графана» для быстрой проверки данных и запросов без настройки Grafana.

## Базовые концепции

### Основные экраны и возможности

| Возможность | Назначение |
| :--- | :--- |
| Query editor | Запрос MetricsQL/PromQL с автодополнением, подсветкой синтаксиса и подсказками функций |
| **Graph / Table / JSON** | Визуализация результата запроса в виде графика, таблицы или сырого JSON |
| **Explain** | Разбор запроса (что именно ищет VM, какие серии/шаги затронуты) — отладка медленных запросов |
| **Cardinality Explorer** | Анализ кардинальности: топ метрик/меток/значений по `vmselect` без отдельного инструмента |
| **Dashboards** | Создание/хранение дашбордов из выражений; экспорт/импорт JSON; поддержка своих шаблонов (`-vmui.customDashboardsPath`) |
| Alerting tab | Просмотр алертов `vmalert` (см. [vmalert_overview.md](./vmalert_overview.md)) |
| Trace/Query History | История выполненных запросов, повтор, «избранное» |
| Export / Share | Выгрузка результатов, прямые ссылки на запрос для шаринга |

### Отличие от Grafana

- **Быстрее**: ничего не настраивать, zero-dependency, работает даже когда Grafana лежит;
- **Точечнее**: сразу весь выборка MetricsQL + экспорт в JSON; подходит для админ-диагностики;
- **Уже** — не предназначен для командного развёртывания дашбордов: это рабочий инструмент инженера, а не платформа (для платформы — [grafana_integration.md](./grafana_integration.md)).

### Зачем это в заметках

vmui — первая линия диагностики «есть ли данные», «какой запрос медленный», «что за кардинальность». Умение работать в vmui — быстрый способ ответить на вопросы интервью о диагностике TSDB.

## Практические сценарии

### 1. Быстрая проверка данных

Откройте `http://localhost:8428/vmui` и:

```text
rate(node_cpu_seconds_total[5m])
```

Сразу видно: есть ли данные (график) и текущую нагрузку. Для проверки «запись прошла?» — `up`.

### 2. Отладка запроса перед дашбордом

- Вставляете выражение → **Graph/Table**; 
- Сравниваете результат с ожиданием: если пусто — расширяете `match[]`/меняете `time range`, проверяете синтаксис через подсказки;
- Медленный запрос → **Explain**, смотрите сколько серий реально задействовано, сужаете фильтр;
- Из-под vmui видно ошибки синтаксиса в MetricsQL до попадания в Grafana.

### 3. Диагностика кардинальности

1. Open `vmui` → **Cardinality Explorer**;
2. Выбрать тип (metrics/labels/label values) — увидеть топ серий и меток;
3. Сравнить «до/после» релиза, чтобы поймать взрыв кардинальности;

Другой способ — `/api/v1/status/tsdb` (см. [http_api_reference.md](./http_api_reference.md)) и [vmestimator](./vmestimator.md).

### 4. Работа с дашбордами

- Соберите выражение → **Add to dashboard**;
- Дашборды сохраняются в JSON: экспортируйте и храните в Git (SSoT), а не «в голове»;
- Для своих шаблонов дашбордов положите JSON в каталог, заданный флагом `-vmui.customDashboardsPath`.

### 5. Сессии и help поверх Kubernetes/внутри кластера

```bash
# Пробросить порт до vmselect (кластер) и открыть vmui
kubectl -n monitoring port-forward svc/victoria-metrics-k8s-stack-vmsingle 8429:8429
# → http://localhost:8429/vmui
```

## Валидация установки

```bash
# vmui отвечает
curl -s http://localhost:8428/vmui | grep -q "<!DOCTYPE" && echo "vmui OK"

# Query через vmui-подобный API (тот же язык)
curl -s 'http://localhost:8428/api/v1/query?query=up' | jq '.data.result | length'
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| vmui пустой / 404 | Порт не тот / backend не запущен | Проверить `-httpListenAddr`; для кластера — vmselect |
| Запрос в vmui работает, в Grafana нет | Разные datasource/time range | Сравнить time range и datasource URL |
| «Too many time series» | Слишком широкий фильтр | Сузить `match[]`/добавить `topk` |
| График обрывается | Нет денсифицированных данных/ пустые промежутки | Проверить interval/`step`; добавить `keep_last_value` |

## Рекомендации по эксплуатации

- Используйте vmui как **первичную** проверку до создадания панели в Grafana — экономит CPU Grafana и время;
- Храните дашборды vmui в JSON в репозитории, если команда их использует (прослеживаемость изменения);
- Работа с кардинальностью — только через Cardinality Explorer / `/status/tsdb` (согласованно, не в резкие окна);
- Для больших кластеров не выгружайте со страниц vmui в prod через тяжёлые запросы — они нагружают vmselect (см. [http_api_reference.md](./http_api_reference.md)).

## Ограничения и особые случаи

- vmui — клиент одного инстанса/тенанта; мульти-тенантные выборки — через vmauth/несколько datasources (см. [grafana_integration.md](./grafana_integration.md));
- Продвинутые функции (Stats, alerting-табы) могут различаться между версиями — совместимость смотрите в release notes;
- `vmui.customDashboardsPath` работает начиная с определённой версии — сверяйтесь с официальной документацией.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — порты и запуск single-node;
- [HTTP API: диагностика](./http_api_reference.md) — `/vmui`, `/api/v1/status/tsdb`, `active_queries`;
- [MetricsQL: справочник](./metricsql_reference.md) — синтаксис запросов в vmui;
- [vmalert: алертинг](./vmalert_overview.md) — Alerting tab в vmui;
- [Grafana: интеграция](./grafana_integration.md) — когда использовать Grafana вместо/вместе с vmui.
# force reindex test
