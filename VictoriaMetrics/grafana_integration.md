# VictoriaMetrics + Grafana: интеграция

**Актуально для:** VictoriaMetrics v1.154.x (Community) / v1.148.x (LTS), VictoriaLogs v1.53.x (LTS v1.52.x), Grafana 13.2.x / 12.x (LTS)

## Определения

**Datasource** — в Grafana — источник данных для панелей и Explore. VictoriaMetrics отдаёт совместимый с Prometheus API `/api/v1/...`, поэтому подключается как Datasource типа **Prometheus** (встроенный) или через официальный плагин **VictoriaMetrics** (`victoriametrics-metrics-datasource`); VictoriaLogs — через плагин **VictoriaLogs** (`victoriametrics-logs-datasource`), позволяющий выполнять LogsQL из Explore.

**Прокси-режим (Server access = proxy)** — Grafana делает запрос к бэкенду от своего имени; используется по умолчанию, так как прямым Browser-доступом (`direct`) эндпоинты VictoriaMetrics не должны быть открыты наружу.

**Forward OAuth Identity** — режим, при котором Grafana передаёт токен пользователя (заголовок `Authorization: Bearer <access_token>`) в бэкенду через `jsonData.oauthPassThru: true`; vmauth валидирует JWT и маршрутизирует запрос по заявке `vm_access`.

## Базовые концепции

### Два плагина для метрик: Prometheus против VictoriaMetrics Datasource

VictoriaMetrics интегрируется с Grafana двумя способами — выбирают один:

| Подход | Type datasource | Когда |
| :--- | :--- | :--- |
| **Prometheus datasource** (встроенный) | `prometheus` | Большинство дашбордов и алертинга; 100% совместим с PromQL; подходит, если не нужен специфичный MetricsQL |
| **VictoriaMetrics datasource** (официальный плагин) | `victoriametrics-metrics-datasource` | Нужны родные функции MetricsQL, Ad Hoc filters, трейсинг исполнения запросов, Prettify; рекомендуется для новых проектов на VM |

Официальный плагин `victoriametrics-metrics-datasource` публиковался в GitHub; установка — через `GF_INSTALL_PLUGINS` или Marketplace. Оба datasource дают одинаковый результат на PromQL-запросах; плагин добавляет удобства поверх MetricsQL.

### Какие URL-адреса указывать

| Что подключаем | Type в Grafana | URL |
| :--- | :--- | :--- |
| VictoriaMetrics Single-node | `prometheus` или `victoriametrics-metrics-datasource` | `http://victoria-metrics:8428/` |
| VictoriaMetrics Cluster | `prometheus` или `victoriametrics-metrics-datasource` | `http://vmselect:8481/select/0/prometheus/` (тенант 0; для тенантов — свои URL или vmauth) |
| VictoriaLogs | `victoriametrics-logs-datasource` | `http://victorialogs:9428/` |
| Через [vmauth](./vmauth_overview.md) | любой из выше | `http://vmauth:8427/select/0/prometheus/` (единая точка входа, аутентификация) |

> С v1.150.0 мультитенантность через заголовки включена по умолчанию (`-enableMultitenancyViaHeaders`), поэтому в кластере допустимы упрощённые URL без tenant ID в пути: `http://vmselect:8481/select/prometheus/...`. Пути с `/select/<accountID>/...` также работают.

- **Metrics** — стандартный PromQL/MetricsQL-datasource: панели, alerting, template-переменные работают как с Prometheus.
- **Logs** — отдельный плагин VictoriaLogs для Explore и лог-панелей. Учётные данные (`username/password`, токены) — в provisioning через `secureJsonData`.

### Совместимость запросов

- MetricsQL — надмножество PromQL: вся PromQL-графика дашбордов работает, многие дашборды поддерживают более точные rollup-функции.
- Template-переменные (`$label_values(node_boot_time_seconds, instance)`) опираются на `/api/v1/label/<name>/values`, который VictoriaMetrics реализует — переменные работают без правок.
- VL-plugin разделяет запросы LogsQL; базовые LogQL-выражения совместимы в большинстве случаев (детали синтаксиса — в [logsql_overview.md](./logsql_overview.md)).

### Почему это важно

Дашборды пишутся под VM/Prometheus один раз и переиспользуюются с обоими бэкендами; VM поддерживает агрегирование/rollup ближе к Grafana-строке, что экономит CPU дашбордов. Отсутствие отдельной настройки Grafana — самая частая причина «всё заскрейпилось, но не отображается».

## Практические сценарии

### Предварительные требования

- **Grafana**: 12.x (LTS) или 13.2.x (актуальная). См. [Обзор Grafana](../Grafana/grafana_overview.md).
- **Plugins**: `victoriametrics-metrics-datasource` (опц.) и `victoriametrics-logs-datasource` установлены (через Marketplace, `GF_INSTALL_PLUGINS` или Helm `grafana.plugins`).
- **Сетевая доступность**: Grafana (при `Server`/proxy) должна достигать URL бэкенда — проверка `curl -v <URL>` из пода Grafana.
- **Учётные данные**: при доступе через vmauth — Basic Auth или Service Account токен, уже вынесенные в секреты.
- **Provisioning**: директория `/etc/grafana/provisioning/datasources` смонтирована (для файлового подхода) либо доступ к UI `Connections → Data sources`.

### 1. Установка плагинов

```bash
# Через переменную окружения в Docker Compose / образе Grafana
GF_INSTALL_PLUGINS="victoriametrics-metrics-datasource,victoriametrics-logs-datasource"

# Сторонний способ — grafana-cli
grafana-cli plugins install victoriametrics-metrics-datasource
grafana-cli plugins install victoriametrics-logs-datasource
# → перезапустить Grafana
```

> Плагин `victoriametrics-logs-datasource` имеет статус Commercial; для unsigned-сборок до переименования ID может потребоваться `allow_loading_unsigned_plugins = victoriametrics-logs-datasource` в `grafana.ini`.

### 2. Подключение метрик: тип Prometheus (UI)

1. Grafana → **Connections → Add a datasource → Prometheus**;
2. `URL`: `http://victoria-metrics:8428/` (или `http://vmselect:8481/select/0/prometheus/`);
3. `Access`: **Server** (proxy);
4. Метод — без аутентификации (VM) либо Basic Auth при доступе через vmauth.

### 3. Подключение метрик: плагин VictoriaMetrics (UI)

1. Grafana → **Connections → Add a datasource → VictoriaMetrics**;
2. `URL`: `http://victoria-metrics:8428/` (single) или `http://vmselect:8481/select/0/prometheus/` (cluster);
3. `Access`: **Server** (proxy);
4. При желании — включить **Forward OAuth Identity** для проброса токена пользователя в vmauth.

При использовании плагина Grafana автоматически использует MetricsQL; остальные настройки (алертинг, переменные) совпадают с Prometheus-datasource.

### 4. Подключение через provisioning (IaC)

Полный пример с учётом текущих возможностей (maxLines, мультитенантность, Forward OAuth Identity):

```yaml
# grafana/provisioning/datasources/victoriametrics.yaml
apiVersion: 1

datasources:
  - name: VictoriaMetrics
    type: victoriametrics-metrics-datasource
    access: proxy
    url: http://victoria-metrics:8428
    isDefault: true
    jsonData:
      httpMethod: POST
      timeInterval: 15s
      # Проброс токена пользователя в vmauth (JWT-claims vm_access)
      oauthPassThru: true
  - name: VictoriaMetrics-Cluster
    type: victoriametrics-metrics-datasource
    access: proxy
    url: http://vmauth:8427/select/0/prometheus/
    jsonData:
      httpMethod: POST
      timeInterval: 15s
  - name: VictoriaLogs
    type: victoriametrics-logs-datasource
    access: proxy
    url: http://victorialogs:9428
    jsonData:
      # Максимум строк на запрос (по умолчанию 1000, max 10000)
      maxLines: 2000
      # Мультитенантность через заголовки AccountID/ProjectID
      multitenancyHeaders:
        AccountID: "0"
        ProjectID: "0"
      # Trace ID из поля → ссылка на трейс-источник (log to trace)
      derivedFields:
        - name: trace_id
          matcherType: label
          datasourceUid: tempo
      # Log level rules: классификация уровня по полю (см. документацию плагина)
      logLevelRules:
        - field: severity
          match:
            - "error"
            - "fatal"
            level: error
    secureJsonData:
      basicAuthPassword: ${VICTORIA_LOGS_PASSWORD}
```

Рекомендуемый способ для GitOps-сред: датасорсы декларативны, отслеживаемы и не «разъезжаются» с окружениями (см. [Grafana: provisioning](../Grafana/grafana_provisioning.md)).

### 5. Подключение через Helm (Kubernetes / k8s-stack)

В чарте `victoria-metrics-k8s-stack` datasource'ы задаются через `additionalDataSources`, а плагины — через `grafana.plugins`:

```yaml
# values.yaml (фрагмент k8s-stack)
grafana:
  plugins:
    - victoriametrics-metrics-datasource
    - victoriametrics-logs-datasource
  additionalDataSources:
    - name: VictoriaMetrics
      type: victoriametrics-metrics-datasource
      url: http://vmselect:8481/select/0/prometheus
      access: proxy
      isDefault: true
      jsonData:
        httpMethod: POST
    - name: VictoriaLogs
      type: victoriametrics-logs-datasource
      url: http://vlselect:9481
      jsonData:
        maxLines: 2000
```

> Через `k8s-sidecar` datasource'ы также можно провайдить через ConfigMap — см. [Grafana: provisioning](../Grafana/grafana_provisioning.md), сценарий 3.

### 6. Мульти-тенантность через один datasource

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

С v1.150.0 tenant ID в пути можно опускать, а тенант передавать через заголовки `AccountID`/`ProjectID` (или JWT-claims `vm_access` через vmauth).

### 7. Шаблоны запросов и переменные

```text
# Переменная "инстанс" из данных самого VM
$label_values(node_boot_time_seconds, instance)

# Панель с «прощающим» rollup — VM сама подставит подходящий time-range
rate(node_cpu_seconds_total[$__rate_interval])
```

### 8. vmalert и Grafana Alerting UI

Для отображения правил vmalert в UI Grafana (вкладка Alerting в VM) и их обратной связи в дашбордах — укажите `-vmalert.proxyURL` на vmsingle/vmselect (с v1.125.0):

```
vmsingle -vmalert.proxyURL=http://vmalert:8880
# или в кластере на vmselect:
vmselect -vmalert.proxyURL=http://vmalert:8880
```

vmalert при этом настраивается `-datasource.url=http://<vmsingle или vmselect>` и `-notifier.url=http://grafana:3000/api/...`. Подробнее — в [vmalert_overview.md](./vmalert_overview.md).

### 9. Дашборды VictoriaMetrics

- Официальные дашборды VM (single-node и cluster) — в каталоге Grafana, «VictoriaMetrics»;
- Свои дашборды переносите целиком: экспорт JSON из Grafana → импорт в другую Grafana (VM-совместимый PromQL не требует правок);
- Логи — из Explore VictoriaLogs (LogsQL) в шаблоны панелей типа *Logs*/*Table*.

## Валидация установки

```bash
# В Grafana: datasource → Save & Test → "Success"

# Проверка API VM из Grafana-подобного запроса
curl -s 'http://victoria-metrics:8428/api/v1/query?query=up' | jq '.data.result | length'
# >0 — метрики видимы

# Проверка datasource через прокси Grafana
curl -s "http://grafana:3000/api/datasources/proxy/uid/victoriametrics/api/v1/query?query=up" \
  -H "Authorization: Bearer <SA_TOKEN>" | jq '.status'
# → "success"

# Проверка LogsQL напрямую к VictoriaLogs
curl -s 'http://victorialogs:9428/select/logsql/query' \
  -d 'query=_time:5m' | head -c 200

# Пинг VictoriaLogs (кластер: /select/logsql/ping)
curl -s http://victorialogs:9428/select/logsql/ping
# → pong
```

## Поиск и устранение неисправлостей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Панели «No data», `/api/v1/write` работает | Datasource смотрит не на тот URL/порт (cluster vs single) | Проверить URL: для cluster нужен `/select/<tenant>/prometheus/` |
| Ошибка "401" на метриках | Basic Auth на vmauth не прошёл | Проверить credentials в provisioning (secureJsonData) |
| Explore VictoriaLogs пуст | Плагин не установлен / URL VL неверный | Установить `victoriametrics-logs-datasource`; проверить `:9428/select/logsql/query` |
| "plugin not found" в UI | Плагин не установлен или не в `allow_loading_unsigned_plugins` | Установить плагин; для unsigned — добавить в `grafana.ini` |
| Медленные панели | Browser-режим и большой `$__interval` | Переключить на `proxy`, уменьшить разрешение запроса |
| Переменные пустые | `instance` не существует в данных | Поменять метрику/имя метки в `$label_values(...)` |
| Логи не подгружаются через proxy | URL VL недоступен из пода Grafana | `curl -v http://victorialogs:9428/select/logsql/ping` из пода Grafana |
| Метрики видны, а Alerting UI пуст | Не задан `-vmalert.proxyURL` | Добавить флаг vmsingle/vmselect → [vmalert_overview.md](./vmalert_overview.md) |

## Рекомендации по эксплуатации

- Всегда `access: proxy` (Server): Browser-доступ требует открытия VM наружу — нарушение [security.md](./security.md).
- Для алертинга предпочитайте `vmalert` (см. [vmalert_overview.md](./vmalert_overview.md)), а Grafana Alerting оставляйте для «не-метрик». При необходимости метрик-алертов включайте `-vmalert.proxyURL`.
- Мульти-тенантность в дашбордах делайте через переменные/URL, а не через отдельные Grafana-инстансы.
- Периодически сверяйте метки (`$label_values`) — VM отдаёт актуальные значения, что ловит дрейф конфигов.
- Фиксируйте `uid` datasource в provisioning — перенос дашбордов между окружениями не ломает ссылки.
- Храните секреты в `secureJsonData` через env-переменные, а не в коммите.

## Ограничения и особые случаи

- Плагин VictoriaLogs поставляется отдельно (Commercial) и требует установки в Grafana (Marketplace / `GF_INSTALL_PLUGINS` / Helm `grafana.plugins`);
- Плагин VictoriaMetrics (метрики) — отдельная установка; если не нужен, используйте встроенный Prometheus datasource (тоже совместим);
- Forward OAuth Identity требует vmauth с JWT-валидацией (`vm_access` claim с v1.147.0; `default_vm_access_claim` для токенов без claims — см. [vmauth_overview.md](./vmauth_overview.md));
- Для исторических логов в Grafana доступно только то, что принято/не удалено по retention (см. [victorialogs_internals.md](./victorialogs_internals.md));
- Добавление нескольких `/select/<tenant>/...` datasources — корректно, но при пересечении tenant-доступа потребует аккуратной настройки прав в Grafana (см. [Grafana: RBAC](../Grafana/grafana_rbac_fine_grained.md));
- Live tailing логов (`/select/logsql/tail`) работает через плагин VictoriaLogs, но не все панели поддерживают стриминг — используйте Explore.

## Дополнительная информация

### См. также

- [Grafana: источники данных](../Grafana/grafana_datasources.md) — параметры datasource, режимы доступа;
- [Grafana: provisioning](../Grafana/grafana_provisioning.md) — декларативные датасорсы и dashboards;
- [Grafana: шаблонизация](../Grafana/grafana_templating.md) — template-переменные;
- [VictoriaMetrics: настройка VictoriaLogs в Kubernetes](../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) — Helm-установка с VL-plugin;
- [vmauth: прокси и маршрутизация](./vmauth_overview.md) — единая точка входа для Grafana;
- [vmalert: обзор](./vmalert_overview.md) — алертинг, proxyURL, интеграция с VM Alerting UI;
- [LogsQL: справочник запросов](./logsql_overview.md) — синтаксис и функции аналитики логов;
- [HTTP API VictoriaMetrics](./http_api_reference.md) — эндпоинты и порты компонентов.
