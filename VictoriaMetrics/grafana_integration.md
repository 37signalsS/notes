# VictoriaMetrics + Grafana: интеграция

## Определения

**Datasource** — в Grafana — источник данных для панелей и Explore. VictoriaMetrics отдаёт совместимый с Prometheus API `/api/v1/...`, поэтому подключается как Datasource типа **Prometheus**, а VictoriaLogs — через плагин **VictoriaLogs** (`victoriametrics-logs-datasource`), позволяющий выполнять LogsQL из Explore.

**Прокси-режим (Server access = proxy)** — Grafana делает запрос к бэкенду от своего имени; используется по умолчанию, так как прямым Browser-доступом (`direct`) эндпоинты VictoriaMetrics не должны быть открыты наружу.

## Базовые концепции

### Какие URL-адреса указывать

| Что подключаем | Тип в Grafana | URL |
| :--- | :--- | :--- |
| VictoriaMetrics Single-node | Prometheus | `http://victoria-metrics:8428/` |
| VictoriaMetrics Cluster | Prometheus | `http://vmselect:8481/select/0/prometheus/` (тенант 0; для тенантов — свои URL или vmauth) |
| VictoriaLogs | VictoriaLogs (плагин) | `http://victorialogs:9428/` |
| Через [vmauth](./vmauth_overview.md) | Prometheus | `http://vmauth:8427/select/0/prometheus/` (единая точка входа, аутентификация) |

- **Metrics** — стандартный PromQL/MetricsQL-datasource: панели, alerting, template-переменные работают как с Prometheus.
- **Logs** — отдельный плагин VictoriaLogs для Explore и лог-панелей. Учётные данные (`username/password`, токены) — в provisioning через `secureJsonData`.

### Совместимость запросов

- MetricsQL — надмножество PromQL: вся PromQL-графика дашбордов работает, многие дашборды поддерживают более точные rollup-функции.
- Template-переменные (`$label_values(node_boot_time_seconds, instance)`) опираются на `/api/v1/label/<name>/values`, который VictoriaMetrics реализует — переменные работают без правок.
- VL-plugin разделяет запросы LogsQL; базовые LogQL-выражения совместимы в большинстве случаев (детали синтаксиса — в [logsql_overview.md](./logsql_overview.md)).

### Почему это важно

Дашборды пишутся под VM/Prometheus один раз и переиспользуются с обоими бэкендами; VM поддерживает агрегирование/rollup ближе к Grafana-строке, что экономит CPU дашбордов. Отсутствие отдельной настройки Grafana — самая частая причина «всё заскрейпилось, но не отображается».

## Практические сценарии

### 1. Подключение метрик: тип Prometheus (UI)

1. Grafana → **Connections → Add a datasource → Prometheus**;
2. `URL`: `http://victoria-metrics:8428/` (или `http://vmselect:8481/select/0/prometheus/`);
3. `Access`: **Server** (proxy);
4. Метод — без аутентификации (VM) либо Basic Auth при доступе через vmauth.

### 2. Подключение через provisioning (IaC)

```yaml
# grafana/provisioning/datasources/victoriametrics.yaml
apiVersion: 1

datasources:
  - name: VictoriaMetrics
    type: prometheus
    access: proxy
    url: http://victoria-metrics:8428
    isDefault: true
    jsonData:
      httpMethod: POST
      timeInterval: 15s
  - name: VictoriaLogs
    type: victoriametrics-logs-datasource
    access: proxy
    url: http://victorialogs:9428
    jsonData:
      dataSourceType: victoria-logs
    secureJsonData:
      basicAuthPassword: ${VICLORIA_LOGS_PASSWORD}
```

Рекомендуемый способ для GitOps-сред: датасорсы декларативны, отслеживаемы и не «разъезжаются» с окружениями (см. [Grafana: provisioning](./../Grafana/grafana_provisioning.md)).

### 3. Мульти-тенантность через один datasource

Чтобы несколько команд работали с разными тенантами одного кластера через один вход:

```yaml
- name: VM Team A
  type: prometheus
  url: http://vmauth:8427/select/100/prometheus/   # тенант accountID=100, projectID=0
  jsonData:
    httpHeaderName1: X-Scope-OrgID   # если vmauth проверяет заголовок
  secureJsonData:
    httpHeaderValue1: "100:0"
```

### 4. Шаблоны запросов и переменные

```text
# Переменная "инстанс" из данных самого VM
$label_values(node_boot_time_seconds, instance)

# Панель с «прощающим» rollup — VM сама подставит подходящий time-range
rate(node_cpu_seconds_total[$__rate_interval])
```

### 5. Дашборды VictoriaMetrics

- Официальные дашборды VM (single-node и cluster) — в каталоге Grafana, «VictoriaMetrics»;
- Свои дашборды переносите целиком: экспорт JSON из Grafana → импорт в другую Grafana (VM-совместимый PromQL не требует правок);
- Логи — из Explore VictoriaLogs (LogsQL) в шаблоны панелей типа *Logs*/*Table*.

## Валидация установки

```bash
# В Grafana: datasource → Save & Test → "Success"

# Проверка API VM из Grafana-подобного запроса
curl -s 'http://victoria-metrics:8428/api/v1/query?query=up' | jq '.data.result | length'
# >0 — метрики видимы

# Проверка плагина логов
curl -s 'http://victorialogs:9428/select/logsql/query' \
  -d 'query=_time:5m' | head -c 200
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Панели «No data», `/api/v1/write` работает | Datasource смотрит не на тот URL/порт (cluster vs single) | Проверить URL: для cluster нужен `/select/<tenant>/prometheus/` |
| Ошибка "401" на метриках | Basic Auth на vmauth не прошёл | Проверить credentials в provisioning (secureJsonData) |
| Explore VictoriaLogs пуст | Плагин не установлен / URL VL неверный | Установить `victoriametrics-logs-datasource`; проверить `:9428/select/logsql/query` |
| Медленные панели | Browser-режим и большой `$__interval` | Переключить на `proxy`, уменьшить разрешение запроса |
| Переменные пустые | `instance` не существует в данных | Поменять метрику/имя метки в `$label_values(...)` |

## Рекомендации по эксплуатации

- Всегда `access: proxy` (Server): Browser-доступ требует открытия VM наружу — нарушение [security.md](./security.md).
- Для алертинга предпочитайте `vmalert` (см. [vmalert_overview.md](./vmalert_overview.md)), а Grafana Alerting оставляйте для «не-метрик».
- Мульти-тенантность в дашбордах делайте через переменные/URL, а не через отдельные Grafana-инстансы.
- Периодически сверяйте метки (`$label_values`) — VM отдаёт актуальные значения, что ловит дрейф конфигов.

## Ограничения и особые случаи

- Плагин VictoriaLogs поставляется отдельно и требует установки в Grafana (маркетплейс / Grafana Alloy-стек);
- Для исторических логов в Grafana доступно только то, что принято/не удалено по retention (см. [victorialogs_internals.md](./victorialogs_internals.md));
- Добавление нескольких `/select/<tenant>/...` datasources — корректно, но при пересечении унтенант-доступа потребует аккуратной настройки прав в Grafana (см. [Grafana: RBAC](./../Grafana/grafana_rbac_fine_grained.md)).

## Дополнительная информация

### См. также

- [Grafana: источники данных](./../Grafana/grafana_datasources.md) — параметры datasource, режимы доступа;
- [Grafana: provisioning](./../Grafana/grafana_provisioning.md) — декларативные датасорсы и dashboards;
- [Grafana: шаблонизация](./../Grafana/grafana_templating.md) — template-переменные;
- [VictoriaMetrics: настройка VictoriaLogs в Kubernetes](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) — Helm-установка с VL-plugin;
- [vmauth: прокси и маршрутизация](./vmauth_overview.md) — единая точка входа для Grafana.
# force reindex test
