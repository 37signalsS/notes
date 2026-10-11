# Grafana для Docker-метрик: дашборды, провиженинг, алерты

**Актуально для:** Grafana 13.x (стабильный релиз 13.2.3), Prometheus 3.x, Loki 3.x, Docker Engine 20.10–29.x

## Определения

**Дашборд (Dashboard)** — JSON-модель панелей для визуализации метрик. Полная модель полей, UID, переменных и аннотаций: [Grafana: Дашборды](../../Grafana/grafana-dashboards.md) (SSoT).

**Провиженинг (Provisioning)** — декларативное управление ресурсами Grafana (datasources, dashboards, alerting) через YAML-файлы в `/etc/grafana/provisioning` с hot reload. Полный справочник: [Grafana: Провиженинг](../../Grafana/grafana_provisioning.md) (SSoT).

**Переменная (templating)** — интерактивный фильтр дашборда (например, выбор контейнера или окружения), подставляемый в запросы панелей.

**Data Link** — гиперссылка на панели или в таблице, ведущая на другой дашборд, Loki-запрос или внешнюю систему с подстановкой меток и временного диапазона. Основной механизм корреляции «метрика → лог».

**Unified Alerting** — движок алертов Grafana (с 9.x): правила оцениваются сервером Grafana, уведомления маршрутизируются через contact points и policies. Ограничение: правила не поддерживают dashboard-переменные (вычисляются вне контекста дашборда).

**Correlations (Grafana 11+)** — декларативные связи между дашбордами и источниками данных, настраиваемые в UI; data links — ручной аналог для произвольных ссылок.

## Основные концепции

### Уровни дашбордов для Docker-мониторинга

| Уровень | Назначение | Ключевые панели |
| :--- | :--- | :--- |
| **L1 — Onepager** | Здоровье платформы на одном экране для дежурного | `up` по job'ам, число контейнеров (`engine_daemon_container_states_containers`), OOM за 1ч, заполнение `/var/lib/docker`, алерты |
| **L2 — Drill-down** | Per-container ресурсы | CPU%, working set vs лимит, NetIO, BlkIO, PIDs |
| **L3 — Диагностика** | Разбор инцидентов | CPU throttling, PSI, conntrack, ошибки/dропы пакетов, health-check'и демона |

Клик на индикатор L1 должен вести на L2 (drill-down через data link с переменной `container_name`).

### Источники данных

| Источник | Что даёт | Типичный порт |
| :--- | :--- | :--- |
| **Prometheus** | cAdvisor (per-container) + Engine Metrics (`engine_daemon_`) | 9090 |
| **Loki** | Логи контейнеров для корреляции с метриками | 3100 |

### Grafana alerts vs Prometheus alerts

| Критерий | Prometheus alerts | Grafana alerts |
| :--- | :--- | :--- |
| Где вычисляется | Prometheus (rule groups, `evaluation_interval`) | Grafana (свой scheduler) |
| Сложность PromQL | Полная, включая recording rules | Полная, но без dashboard-переменных |
| Маршрутизация | Alertmanager (grouping, inhibition, silencing) | Unified Alerting (policies, contact points) |
| Когда выбирать | Production-стек с Alertmanager, сложные зависимости между алертами | Быстрый старт, малые стеки, алерты «у дашборда» |

В Docker-стеке на Prometheus алерты обычно заводят в Prometheus (см. [Справочник метрик Docker Engine](./docker_engine_metrics_reference.md) и [cAdvisor](../../Prometheus/Exporters/cadvisor.md)), а Grafana используют для визуализации и data links.

## Практические сценарии

### Предварительные требования

- **Стек:** Prometheus со scrape-конфигурацией для cAdvisor и Engine Metrics (порт 9323), Loki — см. [Интеграция Docker с Prometheus](./docker_prometheus_integration.md) и [Docker Stack мониторинга](../../Prometheus/installation/docker_stack/overview.md).
- **Grafana:** 13.x; процесс должен достигать источников данных изнутри сети Compose (проверка: `docker exec grafana curl -s http://prometheus:9090/-/ready`).
- **Секреты:** пароль admin передаётся через `.env` (`GF_SECURITY_ADMIN_PASSWORD=${GF_ADMIN_PASSWORD}`), не коммитится в Git; регистрация отключена (`GF_SECURITY_ALLOW_SIGN_UP: "false"`); для production — OAuth/SAML (см. [SSO/SAML/JWT](../../Grafana/grafana_sso_saml_jwt.md)).
- **Права:** монтирование `./grafana/provisioning` в контейнер read-only; UID/GID процесса Grafana (по умолчанию 472) должен иметь доступ к тому `grafana_data`.

### 1. Провиженинг стека (Docker Compose)

Структура файлов:

```
monitoring-stack/
├── docker-compose.yml
└── grafana/
    └── provisioning/
        ├── datasources/
        │   └── datasources.yaml
        └── dashboards/
            └── providers.yaml
```

**`provisioning/datasources/datasources.yaml`:**

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    uid: prometheus
    url: http://prometheus:9090
    access: proxy
    isDefault: true
    editable: false
    jsonData:
      timeInterval: "15s"
      httpMethod: "POST"
  - name: Loki
    type: loki
    uid: loki
    url: http://loki:3100
    access: proxy
    editable: false
```

**`provisioning/dashboards/providers.yaml`:**

```yaml
apiVersion: 1
providers:
  - name: 'Docker-Monitoring'
    orgId: 1
    folder: 'Docker'
    type: file
    disableDeletion: true
    updateIntervalSeconds: 30
    allowUiUpdates: false
    options:
      path: /etc/grafana/provisioning/dashboards/json
      foldersFromFilesStructure: true
```

**Фрагмент `docker-compose.yml`:**

```yaml
services:
  grafana:
    image: grafana/grafana:13.2.3
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    environment:
      GF_PATHS_PROVISIONING: /etc/grafana/provisioning
      GF_SECURITY_ADMIN_PASSWORD: ${GF_ADMIN_PASSWORD}
      GF_SECURITY_ALLOW_SIGN_UP: "false"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - grafana_data:/var/lib/grafana
    networks:
      - monitoring
```

**Валидация:**

```bash
docker logs grafana 2>&1 | grep -i provisioning
# → level=info msg="Provisioning results" logger=provisioning ... datasources=2 dashboards=0
```

### 2. Готовые дашборды (импорт по ID)

Готовые модели с grafana.com для Docker-метрик (полное описание метрик каждого: [cAdvisor](../../Prometheus/Exporters/cadvisor.md)):

| ID | Назначение | Метрики | Панели |
| :--- | :--- | :--- | :--- |
| **21743** | cAdvisor exporter — Docker containers Overview | CPU, RAM, Network, Disk I/O, restarts по контейнерам; выбор job/node/service | Современные (Grafana 11.1+) |
| **14282** | cAdvisor Full | CPU, RAM, Network, Disk I/O, Processes по контейнерам | Старые (Grafana 7.x) |
| **1229** | Docker и cAdvisor | CPU, RAM, Network контейнеров и хоста | Старые (Grafana 6.x) |
| **10619** | Docker Container & Host Metrics | Обзор контейнера и хоста (cAdvisor + Node Exporter) | Старые (Grafana 5.x) |
| **21040** | Docker daemon metrics | Метрики демона с порта 9323 (`engine_daemon_*`) | Grafana 10.3+ |
| **11600** | Node Exporter Full | Метрики хоста (используется совместно с cAdvisor) | — |

Импорт: Dashboards → Import → ввести ID → Load → выбрать datasource `Prometheus` → Import. Для Compose-стека дашборды можно скачать JSON (`curl https://grafana.com/api/dashboards/14282/revisions/1/download`) и положить в `provisioning/dashboards/json/` — тогда они подхватываются провайдером без ручного импорта.

> Ограничение: дашборды 1229/10619/14282 созданы в эпоху Grafana 5–7 и содержат устаревшие типы панелей («Graph (old)») — в Grafana 13 они отрисовываются с предупреждениями о миграции. Для новых развёртываний предпочтителен 21743; 21040 дополняет картину метриками демона (9323).

### 3. Переменные для Docker-дашбордов

Типичные переменные (templating) для L2/L3 дашбордов:

```json
{
  "templating": {
    "list": [
      {
        "name": "env",
        "type": "query",
        "datasource": { "type": "prometheus", "uid": "prometheus" },
        "query": "label_values(container_cpu_usage_seconds_total{container_name!=""}, env)",
        "includeAll": true
      },
      {
        "name": "container_name",
        "type": "query",
        "datasource": { "type": "prometheus", "uid": "prometheus" },
        "query": "label_values(container_cpu_usage_seconds_total{env=\"$env\", container_name!=""}, container_name)",
        "includeAll": false
      }
    ]
  }
}
```

Панели используют фильтр `{container_name=~"$container_name"}`. Переменная `env` берётся из лейбла, который добавляется в `relabel_configs` из Docker-лейбла контейнера (см. [Интеграция Docker с Prometheus](./docker_prometheus_integration.md), сценарий 4).

### 4. Grafana alert на Docker-метрику

Пример правила (UI: Alerting → Alert rules → New alert rule) для контейнера, близкого к лимиту памяти:

- **Query A:** `container_memory_working_set_bytes{container_name!=""} / container_spec_memory_limit_bytes{container_name!=""} > 0.9`
- **Condition:** `WHEN last() OF query(A) IS ABOVE 0.9`
- **For:** `2m`
- **Labels:** `severity: critical`
- **Annotations:** `summary: "Контейнер {{ $labels.container_name }} — память >90% от лимита"`

Для production-стека предпочтительны алерты в Prometheus + маршрутизация через Alertmanager (см. [Справочник метрик Docker Engine](./docker_engine_metrics_reference.md), раздел «Алерты»).

### 5. Корреляция метрик и логов (метрика → контейнер → лог)

Data link с панели L2 на логи контейнера в Loki:

- Проще всего — в редакторе панели: **Panel options → Data links → Add link**, URL: `http://grafana:3000/explore?orgId=1&left=["now-1h","now","Loki","{container_name=\\\"${__value.labels.container_name}\\\"}"]` — метка панели подставляется автоматически.
- Современная альтернатива — **Correlations** (Grafana 11+): связь «Prometheus → Loki» настраивается один раз в настройках источника данных и работает во всех панелях и Explore без ручных ссылок. Детали и примеры: [Корреляция телеметрии](../../Grafana/grafana_correlation_exemplars.md).

Workflow при OOM-инциденте:
1. Алерт `ContainerOomKilled` (Prometheus) → дежурный открывает L2-дашборд.
2. Data link на контейнер → Loki: `{container_name="web_app"} | json` за окно алерта.
3. Одновременно метрика `container_memory_working_set_bytes` показывает рост памяти перед kill.

Лейбл в Loki-запросе зависит от конфигурации агента сбора логов (Alloy/Vector/Promtail обычно выставляют `container_name` или `container`) — сверьтесь с [Агентный сбор логов](../Docker_logs/docker_agent_based_logging.md).

### 6. Плейлист для NOC-экрана

```yaml
# provisioning/playlists/playlists.yaml
apiVersion: 1
playlists:
  - name: 'Docker-NOC-Rotation'
    interval: '1m'
    orgId: 1
    items:
      - type: dashboard_by_folder
        value: 'Docker'
        title: 'All Docker Dashboards'
```

## Валидация

```bash
# 1. Провиженинг применился
docker logs grafana 2>&1 | grep -i provisioning
# → datasources=2 dashboards=1

# 2. Дашборды зарегистрированы
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://localhost:3000/api/search?folderIds=1 | jq '.[].title'
# → "Docker and cAdvisor" ...

# 3. Данные идут в панели (PromQL напрямую)
curl -s 'http://prometheus:9090/api/v1/query?query=up{job="cadvisor"}' | jq '.data.result[].metric'
# → health = up

# 4. Data link на Loki отдаёт логи
curl -s 'http://loki:3100/loki/api/v1/query_range?query={container_name="cadvisor"}&limit=5' | jq '.data.resultType'
# → streams

# 5. Правила алертов зарегистрированы (Unified Alerting API)
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://localhost:3000/api/v1/provisioning/alert-rules | jq '.[].title'
# → "ContainerMemoryNearLimit" ...

# 6. Плейлист NOC-ротации создан
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://localhost:3000/api/playlists | jq '.[].name'
# → "Docker-NOC-Rotation"
```

## Диагностика и устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Дашборд пустой, «No data» | Не совпадает `datasource.uid` в JSON с UID провиженинга | Сверьте `uid` в `datasources.yaml` и `datasource.uid` в JSON дашборда |
| Дашборд не появился из папки | Невалидный JSON или не тот путь в `options.path` | `jq . dashboards/json/*.json`; проверьте логи `logger=provisioning` |
| Переменная `container_name` пустая | Лейбл `env` не добавлен в `relabel_configs` | Добавьте relabeling из Docker-лейблов (сценарий 4 в [интеграции](./docker_prometheus_integration.md)) |
| Data link на Loki не открывает логи | Лейбл в Loki отличается (`container` vs `container_name`) | Проверьте лейблы: `curl -s http://loki:3100/loki/api/v1/label` |
| Алерт Grafana не firing | Правило использует dashboard-переменную | Unified Alerting не поддерживает dashboard-переменные — подставьте конкретные значения |
| `401` от Prometheus в логах Grafana | Не подставился секрет из `secureJsonData` | Передайте переменную окружения в процесс Grafana (`.env` + `environment:` в compose) |

## Граничные случаи и ограничения

- **Устаревшие панели в старых дашбордах.** 1229/10619/14282 используют «Graph (old)» и другие deprecated-типы панелей: в Grafana 13 они отрисовываются, но при редактировании предлагают миграцию. Миграция ломает совместимость с Grafana < 8 — если нужны обе версии, держите отдельные JSON.
- **`${DS_PROMETHEUS}` в скачанном JSON.** Модели с grafana.com часто содержат переменную datasource `${DS_PROMETHEUS}`; при провиженинге её нужно заменить на конкретный `uid` (`"uid": "prometheus"`), иначе панели показывают «No data».
- **ARM-хосты.** cAdvisor на ARM (Raspberry Pi) требует монтирования `/etc/machine-id` и `privileged: true`, иначе метрики памяти равны нулю — детали в [Деплой cAdvisor](./docker_cadvisor_deployment.md).
- **Кардинальность переменных.** `label_values()` по `container_name` на хосте с сотнями короткоживущих контейнеров (jobs, CI) делает переменную медленной и расширяет список мёртвыми контейнерами. Фильтруйте переменную: `label_values(container_last_seen{container_name!=""}, container_name)`.
- **Unified Alerting и переменные.** Правила алертов вычисляются сервером вне контекста дашборда — `${container_name}` в правиле не подставляется; используйте конкретные значения (см. [Провиженинг](../../Grafana/grafana_provisioning.md)).
- **Engine Metrics ≠ per-container.** Порт 9323 не содержит метрик отдельных контейнеров (только агрегаты `engine_daemon_*`); per-container картинка возможна только через cAdvisor — см. [Справочник метрик Docker Engine](./docker_engine_metrics_reference.md).

## Лучшие практики

- **Провиженинг read-only:** монтируйте `./provisioning:/etc/grafana/provisioning:ro` и ставьте `editable: false`, `allowUiUpdates: false`, `disableDeletion: true` — Git остаётся единственным источником истины.
- **Стабильные UID** у datasources и дашбордов — ссылки (data links, алерты) не ломаются при миграции между инстансами.
- **Скачивайте JSON дашбордов в Git** вместо ручного импорта по ID — воспроизводимость окружений Dev/Prod.
- **L1-дашборд должен помещаться на один экран** без прокрутки; drill-down — по клику с data link.
- **Коррелируйте метрики с логами** через data links на Loki — это сокращает MTTR при OOM и throttling-инцидентах.
- **Алерты в production — в Prometheus + Alertmanager**, Grafana alerts — для малых стеков и быстрого старта.
- **Мониторьте сам Grafana** через его метрики (`:3000/metrics`, `grafana_dashboard_versions_total`) — при деградации Grafana теряет глаза на весь стек.
- **Откат и очистка:** удалите `./grafana/provisioning` из монтирования и перезапустите Grafana (`docker compose restart grafana`) — провижинированные ресурсы исчезнут из UI (при `disableDeletion: true` дашборды останутся в БД до ручного удаления: Dashboards → Delete). Полная очистка: `docker compose down -v` (удаляет том `grafana_data` вместе с дашбордами, настройками и секретами).

## Дополнительная информация

- **[Grafana: Дашборды](../../Grafana/grafana-dashboards.md)** — SSoT: JSON-модель, переменные, аннотации, библиотечные панели.
- **[Grafana: Провиженинг](../../Grafana/grafana_provisioning.md)** — SSoT: datasources, dashboard providers, alerting, плейлисты, hot reload.
- **[cAdvisor (Container Advisor)](../../Prometheus/Exporters/cadvisor.md)** — SSoT: метрики, PromQL, ID дашбордов, правила алертинга.
- **[Интеграция Docker с Prometheus](./docker_prometheus_integration.md)** — scrape-конфигурация, relabeling, лейблы для переменных.
- **[Справочник метрик Docker Engine](./docker_engine_metrics_reference.md)** — метрики порта 9323 и алерты Prometheus.
- **[Агентный сбор логов](../Docker_logs/docker_agent_based_logging.md)** — лейблы контейнеров в Loki.
- **[Корреляция телеметрии в Grafana](../../Grafana/grafana_correlation_exemplars.md)** — correlations, exemplars, derived fields (метрика → лог → трейс).
- **[Docker Stack мониторинга](../../Prometheus/installation/docker_stack/overview.md)** — полный стек мониторинга на Docker.
