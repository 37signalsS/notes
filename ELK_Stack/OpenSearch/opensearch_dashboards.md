# OpenSearch Dashboards: Визуализация и управление

**Актуально для:** OpenSearch Dashboards 3.9.x (релиз 29 сентября 2026). Отличия ветки 2.x отмечены там, где они существенны.

> Эта заметка является частью обзора [OpenSearch](./opensearch_overview.md) и детально описывает возможности веб-интерфейса для анализа данных и администрирования кластера.

OpenSearch Dashboards (OSD) — это открытый веб-интерфейс для интерактивного исследования данных, построения аналитических панелей и управления компонентами OpenSearch. К 2026 году Dashboards трансформировался из простого инструмента визуализации в полноценную аналитическую платформу с рабочими пространствами (Workspaces), мультиисточниковостью, нативной поддержкой Prometheus и ИИ-агентами для расследования инцидентов.

## Определения

* **OpenSearch Dashboards** — веб-платформа для анализа данных и администрирования (изначально форк Kibana 7.10.2, значительно дивергировавший к 2026 году). Серверная часть — Node.js-приложение, клиентская — React; функциональность расширяется системой плагинов. Версии синхронизированы с ядром OpenSearch (актуальная линия 3.x, релиз 3.9.0 — сентябрь 2026).
* **Index Pattern (Шаблон индекса)** — конфигурация, связывающая Dashboards с одним или несколькими индексами OpenSearch для выполнения запросов; определяет схему полей (маппинги, форматы, скриптовые поля). С версии 3.7 поддерживает опциональный `displayName` — понятное имя поверх технического паттерна.
* **Workspace (Рабочее пространство)** — введено в версии 2.18: изолированная среда с конфигурацией под конкретный use-case (наблюдаемость, security analytics, поиск), внутри которой живут сохраненные объекты (дашборды, визуализации, шаблоны индексов).
* **Tenant (Тенант)** — механизм изоляции сохраненных объектов на уровне плагина Security: Global/Private/Custom тенанты. Исторически первый механизм организации контента; сосуществует с Workspaces.
* **Data Source (Источник данных)** — saved object типа `data-source`, описывающий подключение к внешнему кластеру OpenSearch, S3 или Prometheus (endpoint, метод аутентификации, учетные данные). Функция Multiple Data Sources включается флагом `data_source.enabled`.
* **OpenSearch Assistant** — встроенный ИИ-помощник (плагин dashboards-assistant, введен в 2.13): чат с LLM, генерация PPL/SQL-запросов и визуализаций на естественном языке.
* **Dashboard Variables (Переменные дашборда)** — введено в 3.7: параметризация визуализаций через синтаксис `$variableName` / `${variableName}` в PPL- и PromQL-запросах без редактирования самих запросов.
* **PPL (Piped Processing Language)** — конвейерный язык запросов OpenSearch (аналог Unix-пайпов: `source | where | stats | eval`). С ветки 3.3 — язык по умолчанию для нового Discover в Observability-воркспейсах.

## Основные концепции

### Архитектура и модель развертывания

OSD состоит из трех слоев:

1. **Сервер Node.js**: проксирует запросы браузера к кластеру OpenSearch, хранит собственное состояние (сохраненные объекты) в системных индексах `.kibana*` того же кластера. С версии 3.7 доступен экспериментальный подключаемый backend хранения saved objects на SQLite (proof-of-concept): `savedObjects.storage.backend: "sqlite"` и `savedObjects.storage.sqlite.path: "data/osd-metadata.db"` — позволяет запускать OSD без кластера (локальная разработка, CI-тесты); в production по умолчанию остается хранение в кластере.
2. **Клиентское React-приложение**: рендерится в браузере; вся визуализация выполняется на стороне клиента, что снимает нагрузку с сервера.
3. **Плагины**: базовые (Discover, Visualize, Dev Tools) и дополнительные (Observability, Alerting, Security, Assistant, Reporting, Integration). Минимальный дистрибутив позволяет устанавливать только нужное.

Связь с кластером настраивается в `opensearch_dashboards.yml`; один экземпляр OSD обслуживает кластер целиком, а благодаря Multiple Data Sources — и произвольное число внешних кластеров.

### Ключевые инструменты и интерфейс

1. **Discover**: основной инструмент поиска по логам. Классический интерфейс использует DQL/Lucene и поддерживает поля типа `wildcard` (быстрый поиск по регулярным выражениям в больших логах). Для Observability-воркспейсов начиная с ветки 3.3 доступен **новый интерфейс Discover**, где язык по умолчанию — PPL (расширен командами `JOIN`, `LOOKUP`, `SUBQUERY`); агрегирующие запросы (`stats`) автоматически превращаются в визуализации. Переключение между новым и «классическим» режимами доступно пользователю.
2. **Dashboard и Visualize**: конструктор панелей (линии, столбцы, pie, gauge, heatmaps, TSVB, Vega, карты). Поддерживает интерактивную кросс-фильтрацию (Cross-filtering) — клик по значению на одном графике применяет фильтр ко всему дашборду. С версии 3.7 добавлены **переменные дашборда** для динамической параметризации.
3. **Explore Metrics** (3.7+): вкладка обзора метрик в Discover — browsing доступных метрик без написания запросов, с переходом к PromQL.
4. **Dev Tools**: консоль для прямой работы с REST API кластера (автодополнение DSL); незаменима для отладки запросов, управления ролями и политиками ISM.
5. **Observability**: специализированные приложения — Trace Analytics (анализ распределенных трейсов из [Jaeger](../../Jaeger/jaeger_overview.md)), Log Explorer (PPL-аналитика логов), Metrics (PromQL/PPL-панели), Application Analytics (преднастроенные KPI приложений), Panels (общая доска визуализаций).
6. **OpenSearch Assistant**: чат-панель и контекстные помощники (генерация запросов, объяснение ошибок, text-to-visualization).
7. **Dashboards Management**: центр администрирования OSD — шаблоны индексов, источники данных, расширенные настройки (Advanced Settings), импорт/экспорт объектов.
8. **Reporting**: генерация отчетов PDF/PNG (дашборды, визуализации, ноутбуки) и CSV/XLSX (сохраненные поиски Discover) — разово или по расписанию (cron/interval); см. сценарий «Плановые отчеты» ниже.

### Новое в Dashboards 3.9 (сентябрь 2026)

* **Переменные дашборда для Prometheus**: query-переменная на источнике Prometheus подставляет имена метрик, label-имена и label-значения — одна `$service`-переменная управляет всеми панелями, включая заголовки; добавлены тип Text, опция «Allow custom values» и regex-группы для извлечения значений.
* **Sync crosshair**: синхронизация перекрестия по всем time-series панелям дашборда (включается в настройках дашборда) — корреляция всплесков метрик и логов по одной временной точке.
* **Секции дашборда**: группировка панелей в именованные сворачиваемые секции с перетаскиванием (`dashboard.allowDashboardSections: true` в Advanced Settings).
* **Визуализации**: stacked bar и area, форматирование единиц с min/max границами осей и десятичной точностью, кастомные имена серий, highlight при наведении, legend click-to-focus.
* **Discover Metrics**: шаблоны имен серий, настройка Min step и макросы `$__interval`, `$__rate_interval`, `$__range` для PromQL-запросов.
* **APM setup wizard**: пошаговый мастер настройки Application Monitoring (dataset, service map, Prometheus-источник RED-метрик).
* **Unified alerts view (GA)**: алерты, аномалии и прогнозы в одном интерфейсе; PPL query profiling в Dev Tools; Grok debugger (с 3.8).

### Организация контента: Workspaces против мультиарендности

Два дополняющих друг друга механизма:

| Характеристика | Tenants (Security plugin) | Workspaces (2.18+) |
| :--- | :--- | :--- |
| Уровень изоляции | Сохраненные объекты пользователя | Все объекты + конфигурация UI + набор плагинов |
| Управление | Роли Security (`tenant_permissions`) | ACL воркспейса + API `/api/workspaces` |
| Типизация | Global / Private / Custom | Use-cases: `use-case-observability`, `use-case-security-analytics`, `use-case-search`, `use-case-essentials`, `use-case-all` |
| Совместное использование | Один тенант = одна команда | Объект может принадлежать нескольким воркспейсам |
| Статус | Зрелый механизм | Активно развиваемое направление проекта |

Практическая схема для enterprise: **Workspaces** разграничивают домены (например, «Логи продакшена», «Security Analytics», «Поиск по каталогу»), а **тенанты** продолжают работать как персональное/командное хранилище объектов внутри каждого домена. Связка управляется атрибутом `workspaces` в saved object (массив ID — объект виден во всех перечисленных пространствах).

### Мультиисточниковость (Multiple Data Sources)

Эволюция функции:

| Версия | Этап |
| :--- | :--- |
| 2.4 | Экспериментальный запуск: подключение внешних кластеров OpenSearch |
| 2.14 | Интеграция с основными плагинами (визуализации, Discover) |
| 2.16+ | Полноценное приложение **Management > Data sources**; поддержка S3 и Prometheus |
| 3.7 | Нативный PromQL, детект движков аналитики, усиление безопасности учетных данных |

Ключевые свойства:

* Типы подключений: self-managed OpenSearch, Amazon OpenSearch Service, Amazon S3, Prometheus (включая Amazon Managed Service for Prometheus).
* Аутентификация: No auth, Basic (username/password), AWS SigV4.
* Данные учетных записей шифруются и хранятся как часть saved object `data-source`; в цикле 3.7 закрыты критические уязвимости зависимостей Node.js (CVE-2026-28292 — RCE в simple-git, CVE-2026-33937 — RCE в handlebars, CVE-2026-25639 — DoS в axios); ранее исправлена CVE-2026-77811 — stored XSS через шаблон интеграции в плагине observability (исправлено в 3.4 и 2.19.6). Своевременное обновление критично.
* Индекс-паттерн привязывается к источнику через reference-поле; визуализации наследуют источник от шаблона индекса.
* Экономический смысл: сотни кластеров обслуживаются одним экземпляром OSD вместо отдельного стека на каждый кластер (health-check идет только к метадата-хранилищу).

### Языки запросов в интерфейсе

| Язык | Где используется | Назначение |
| :--- | :--- | :--- |
| DQL | Discover (по умолчанию в классике) | Простой фильтрующий синтаксис `field:value AND ...` |
| Lucene | Discover, строки поиска | Продвинутый полнотекстовый синтаксис |
| PPL | Новый Discover, Log Explorer, визуализации | Конвейерная аналитика: `source=index \| where \| stats count by host` |
| SQL | Dev Tools, JDBC/ODBC-клиенты | Табличные запросы `SELECT ... GROUP BY` |
| PromQL | Explore Metrics, панели метрик | Запросы к Prometheus-совместимым источникам |

## Практические сценарии

### Быстрый старт: стек за 5 минут (Docker Compose)

Требования: Docker Compose v2, 4 ГБ RAM. Версии образа и ядра должны совпадать (3.9.0):

```yaml
services:
  opensearch:
    image: opensearchproject/opensearch:3.9.0
    environment:
      - discovery.type=single-node
      - OPENSEARCH_INITIAL_ADMIN_PASSWORD=Dev#2026Start!
      - DISABLE_INSTALL_DEMO_CONFIG=false
    ports:
      - "9200:9200"

  dashboards:
    image: opensearchproject/opensearch-dashboards:3.9.0
    ports:
      - "5601:5601"
    environment:
      OPENSEARCH_HOSTS: '["https://opensearch:9200"]'
      OPENSEARCH_USERNAME: admin
      OPENSEARCH_PASSWORD: Dev#2026Start!
    depends_on:
      - opensearch
```

```bash
docker compose up -d && sleep 60
curl -s http://localhost:5601/api/status
# → {"name":"...","uuid":"...",
# →  "version":{"number":"3.9.0","build_flavor":"oss","build_type":"tar",...},
# →  "status":{"overall":{"state":"available",...}}}
```

Интерфейс доступен на `http://localhost:5601`, логин `admin` / пароль из `OPENSEARCH_INITIAL_ADMIN_PASSWORD`. Состояние `available` означает успешное подключение к кластеру; состояние `degraded` обычно сигнализирует, что ядро еще инициализируется.

### Ключевые параметры opensearch_dashboards.yml

Минимальный production-набор (файл `/etc/opensearch-dashboards/opensearch_dashboards.yml` или `config/opensearch_dashboards.yml` в дистрибутиве):

```yaml
server.port: 5601
server.host: "0.0.0.0"
server.name: "osd-prod-01"

opensearch.hosts: ["https://os-node-01:9200", "https://os-node-02:9200"]
opensearch.username: "kibanaserver"        # сервисная учетная запись, не admin
opensearch.password: "${OSD_SERVICE_PASS}"
opensearch.requestHeadersAllowlist: ["Authorization", "securitytenant"]

opensearch.ssl.verificationMode: full      # проверка сертификатов кластера
opensearch.ssl.certificateAuthorities: ["/etc/osd/certs/ca.crt"]

# Опциональные блоки (включайте по необходимости):
data_source.enabled: true                  # Multiple Data Sources
assistant.chat.enabled: true               # ИИ-ассистент (см. сценарий ниже)
```

Пояснения: сервисная роль `kibanaserver` создается плагином Security и используется OSD для доступа к системным индексам — работа под `admin` допустима только в тестовых средах. После изменения конфигурации перезапустите сервис (`systemctl restart opensearch-dashboards`) и проверьте журнал:

```bash
journalctl -u opensearch-dashboards -n 20 --no-pager
# → ... [info][plugins][security] Config ... is valid
# → ... [info][server] http server running at http://0.0.0.0:5601
```

### Подключение внешнего источника данных

Задача: визуализировать данные второго кластера (например, DR-площадки) без развертывания отдельного OSD.

1. Включите функцию в конфигурации: `data_source.enabled: true`, перезапустите OSD.
2. Перейдите в **Dashboards Management > Data sources > Create data source**.
3. Заполните: `Title` (`dr-cluster`), `Endpoint` (`https://dr-os.example.com:9200`), метод аутентификации (Basic или AWS SigV4), учетные данные.
4. Нажмите **Test connection** — при успехе появится подтверждение и версия удаленного кластера.
5. Создайте Index Pattern с привязкой к источнику: при выборе паттерна укажите подключение `dr-cluster`.
6. Проверка через Dev Tools — выберите источник в селекторе консоли и выполните запрос к его индексам.

Управление учетными данными: пароль можно обновить позже кнопкой **Update stored credential** (для SigV4 — **Update stored AWS credential**) без пересоздания подключения.

### Работа с Workspaces

Создание пространства для команды SRE с набором Observability-плагинов:

* **Через UI**: главная страница > **Create workspace** > имя и описание > выбор use-case (`Observability`) > настройка ACL (какие команды/пользователи имеют доступ).
* **Через API** (OpenSearch Dashboards 3.x, требуется роль с правами администратора OSD):

```bash
curl -X POST http://localhost:5601/api/workspaces \
  -H 'osd-xsrf: true' \
  -H 'Content-Type: application/json' \
  -u admin:'Dev#2026Start!' \
  -d '{
    "name": "SRE Logs",
    "description": "Продакшен-логи и трейсы",
    "features": ["use-case-observability"],
    "colorAndTheme": { "customThemes": { "color": {"brand": "#2563eb"} } }
  }'
# → {"success":true,"result":{"id":"M5NqCu","name":"SRE Logs",...}}
```

Внутри воркспейса создавайте дашборды и шаблоны индексов как обычно — объекты автоматически получат атрибут `workspaces: ["M5NqCu"]` и будут видны только здесь. Чтобы поделиться объектом между командами, ассоциируйте его с несколькими воркспейсами (**Copy to workspace** / поле `workspaces` через Saved Objects API). Полное управление кластером (роли, ISM, узлы) остается вне воркспейсов — это по-прежнему функции уровня Security/Administration.

### Включение и использование ИИ-ассистента

Ассистент требует ML-стека на стороне кластера.

**Шаг 1. Необходимые плагины**: на кластере — ML-Commons, Flow Framework, Skills, SQL, Observability; в OSD — Assistant и Observability (входят в стандартный дистрибутив).

**Шаг 2. Конфигурация OSD** (`opensearch_dashboards.yml`):

```yaml
assistant.chat.enabled: true              # чат-ассистент
observability.query_assist.enabled: true  # генерация PPL в Log Explorer
observability.summarize.enabled: true     # саммари ответов (опционально)
```

**Шаг 3. Регистрация агента LLM в ML Commons**: подключите модель через коннектор (Bedrock, OpenAI или локальная модель) и зарегистрируйте корневого агента. Выполняется суперпользователем (доступ к системным индексам):

```json
PUT /.plugins-ml-config/_doc/os_chat
{
  "type": "os_chat_root_agent",
  "configuration": {
    "agent_id": "<root_agent_id>"
  }
}
# → {"_index":".plugins-ml-config","result":"created"}
```

Для query-assist аналогично регистрируется PPL-агент в документе `os_query_assist_ppl`.

**Шаг 4. Использование**: откройте чат-панель Assistant и задайте вопрос естественным языком:

> «Покажи топ-5 IP-адресов с кодами ответа 5xx за последние 24 часа»

Ассистент сгенерирует PPL-запрос вида `source=logs-* | where status >= 500 | stats count() by clientip | sort -count()` и предложит визуализацию (Bar chart). Возможности ветки 3.x: многошаговые агентские расследования (agentic AI), экспорт результатов расследования в PDF/Markdown (кнопка **Export investigation**, 3.7+), text-to-visualization. В управляемом Amazon OpenSearch Service те же возможности доступны как Agentic Chat (кнопка **Ask AI**) и Investigation Agent (команда `/investigate`).

> Осторожно: ответы генеративной модели вероятностны — проверяйте сгенерированные запросы перед выполнением на production-данных.

### Настройка мониторинга и алертинга

Встроенный плагин Alerting (без внешних систем):

1. **Define Monitor**: раздел **Alerting > Create monitor**; тип Query-level monitor; задайте извлекающий запрос (например, количество записей уровня `ERROR` в `logs-*` за последние 5 минут).
2. **Define Trigger**: условие срабатывания, например `ctx.results[0].hits.total.value > 100`; настройте severity и recovery-условие.
3. **Action + Channel**: получатель уведомления. Современная терминология — каналы Notification plugin: Slack, Microsoft Teams, Amazon Chime, email, SNS, custom webhook (ранее называлось Destinations).

Проверочный запрос существующих мониторов:

```bash
curl -ku admin:'Dev#2026Start!' https://localhost:9200/_plugins/_alerting/monitors
# → {"monitors":[{"name":"high-5xx","monitor_type":"query_level_monitor",
# →   "enabled":true,"schedule":{"period":{"interval":5,"unit":"MINUTES"}},...}]}
```

Автоматизацию самих индексов (rollover, delete) выполняет ISM — см. [Управление жизненным циклом (ISM)](./opensearch_ism_lifecycle.md); алертинг и ISM дополняют друг друга: первый следит за содержимым, второй — за размером и возрастом.

### Визуализация метрик Prometheus рядом с логами

Единая точка анализа логов и метрик без Grafana:

1. Убедитесь, что `data_source.enabled: true` (версия 2.16+; полноценный опыт — 3.7+).
2. **Dashboards Management > Data sources > Create**: тип **Prometheus**, endpoint `http://prometheus:9090` (или AMP workspace endpoint), при необходимости SigV4.
3. Откройте вкладку **Explore Metrics** в Discover (3.7+) — обзор доступных метрик браузером, либо создайте панель визуализации с PromQL-запросом:

```promql
sum(rate(http_requests_total{job="nginx",status=~"5.."}[5m])) by (service)
```

Редактор автоматически сопоставит поля результата с осями графика. Добавьте переменную дашборда `$service` и используйте ее в запросе: `... by ($service)` — переключение сервиса станет выпадающим списком над дашбордом. Так логи (PPL) и метрики (PromQL) живут в одном дашборде с общим таймлайном.

Возможности 3.9 для таких дашбордов: query-переменная на источнике Prometheus сама строит список значений (имена метрик, label-имена, label-значения, серии) — не нужно хардкодить значения в переменной; доступны тип Text, опция «Allow custom values» и regex-группы для извлечения частей значения. Включите **Sync crosshair** в настройках дашборда — перекрестие синхронизируется по всем time-series панелям, что упрощает корреляцию всплесков метрик с логами. Панели можно группировать в именованные сворачиваемые секции (`dashboard.allowDashboardSections: true`).

### Производные и скриптовые поля

Три механизма создания полей «на лету» без переиндексации — от простого к сложному:

1. **Scripted fields в шаблоне индекса** (Painless): **Dashboards Management > Index Patterns > выбрать шаблон > Scripted field**. Пример — объединение полей в одно: `doc['first_name'].value + ' ' + doc['last_name'].value`. Поле вычисляется при каждом обращении и нагружает CPU кластера — используйте умеренно.
2. **PPL eval в Log Explorer**: временные вычисляемые поля внутри сессии анализа — `source=logs-* | eval latency_ms = took / 1000 | where latency_ms > 500`. Ничего не сохраняется, идеален для разовых разборов инцидентов.
3. **Derived fields на уровне маппинга** (ядро OpenSearch, экспериментально): значение вычисляется скриптом в момент запроса вместо индексации — экономия диска ценой скорости поиска; настраивается в маппинге индекса через Dev Tools, а не в UI.

Правило выбора: постоянное поле, нужное многим дашбордам, — индексируйте на этапе ingest (ingest pipeline); временное — scripted/PPL.

### Импорт и экспорт сохраненных объектов

Перенос дашбордов между средами (dev → prod) или резервное копирование:

```bash
# Экспорт из dev (UI: Dashboards Management > Saved Objects > Export)
curl -s -X POST http://dev-osd:5601/api/saved_objects/_export \
  -H 'osd-xsrf: true' -u admin:'...' \
  -H 'Content-Type: application/json' \
  -d '{"type":"dashboard","includeReferencesDeep":true}'
# → NDJSON-поток: {"type":"dashboard",...}\n{"type":"visualization",...}\n...

# Импорт в prod (с разрешением конфликтов ID)
curl -X POST http://prod-osd:5601/api/saved_objects/_import?overwrite=true \
  -H 'osd-xsrf: true' -u admin:'...' \
  --form file=@dashboards.ndjson
# → {"success":true,"createdCount":7,...}
```

Флаг `includeReferencesDeep: true` вытягивает вместе с дашбордом все зависимые визуализации и шаблоны индексов. Перед импортом убедитесь, что шаблон индекса указывает на существующие в целевом кластере индексы, иначе панели останутся пустыми. Альтернатива для регулярного переноса — Terraform/API-автоматизация тех же эндпоинтов.

### Плановые отчеты (Reporting)

Плагин Reporting (входит в дистрибутив) автоматизирует регулярные сводки для SRE: ежедневный PDF дашборда SLO, выгрузка CSV медленных запросов и т. п. Форматы зависят от источника: Dashboard/Visualization/Notebook → PDF или PNG; Saved Search (сохраненный поиск из Discover) → CSV или XLSX.

**Через UI**: Reporting > Create report definition — выберите источник (дашборд/визуализацию/saved search), тайм-рейндж, формат и триггер: On demand, Recurring (interval) или Cron (например, `0 6 * * *` — каждый день в 06:00).

**Через API** (определение создается на кластере, порт 9200; сам файл рендерится OSD, порт 5601):

```bash
curl -X POST https://localhost:9200/_plugins/_reports/definition \
  -H 'Content-Type: application/json' -u admin:'Dev#2026Start!' \
  -d '{
    "reportDefinition": {
      "name": "Daily SLO dashboard",
      "isEnabled": true,
      "source": { "type": "Dashboard", "id": "<dashboard_id>", "origin": "http://localhost:5601" },
      "format": { "duration": "P1D", "fileFormat": "Pdf" },
      "trigger": { "triggerType": "CronSchedule",
        "schedule": { "cron": { "expression": "0 6 * * *", "timezone": "UTC" } } },
      "status": "ACTIVE"
    }
  }'
# → {"reportDefinitionId":"<definition_id>"}

# Скачать сгенерированный отчет (OSD, требуется заголовок osd-xsrf)
curl -X POST "http://localhost:5601/api/reporting/generateReport/<definition_id>?timezone=UTC&dateFormat=MMM%20D,%20YYYY&csvSeparator=,&allowLeadingWildcards=false" \
  -H 'osd-xsrf: true' -u admin:'Dev#2026Start!'
# → файл отчета (PDF/PNG/CSV/XLSX)
```

Проверка существующих определений: `GET /_plugins/_reports/definition` на кластере. Важно: определение с несовместимой парой «тип источника — формат» (например, `Visualization` + `Csv`) принимается API, но не рендерится и ломает загрузку страницы Reporting в OSD — такое определение нужно удалить (`DELETE /_plugins/_reports/definition/<id>`). Права на создание отчетов регулируются ролями Security (предопределенные роли `reporting_full_access` / `reporting_reader`).

## Дополнительная информация

### Производительность и тюнинг

Настройки интерфейса (раздел **Dashboards Management > Advanced Settings** или `opensearch_dashboards.yml`):

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| `discover:sampleSize` | Количество строк, загружаемых в Discover за один запрос. | Уменьшите до 100–200 на огромных индексах — главный фактор скорости отрисовки. |
| `courier:ignoreFilterIfFieldNotInIndex` | Игнорировать фильтры по полям, отсутствующим в маппинге шаблона (наследие Kibana-эпохи). | Включите (`true`) при разнородных логах в одном шаблоне; в новых ветках проверяйте наличие настройки — механизм выборки заменен современным fetch-слоем. |
| `assistant.chat.enabled` | Чат-ассистент (2.13+). | Требует ML Commons и зарегистрированного агента LLM; отключайте, если ML-стек не развернут. |
| `observability.query_assist.enabled` | Генерация PPL-запросов из естественного языка в Log Explorer. | Экспериментальная функция; включайте вместе с query-assist агентом. |
| `assistant.next.enabled` | Экспериментальные функции ассистента нового поколения, включая text-to-visualization (2.16+). | Для пилотов ИИ-функций. |
| `timepicker:refreshIntervalDefaults` / `timepicker:enabled` | Автообновление дашбордов. | Отключайте частое автообновление (менее 10 с) — каждый тик генерирует запросы к кластеру. |

Серверные параметры OSD:

* `server.maxPayloadBytes` — увеличьте (например, до 104857600) при импорте больших NDJSON-дампов.
* Переменная `NODE_OPTIONS=--max-old-space-size=2048` — лимит памяти Node.js-процесса; при активной работе десятков пользователей закладывайте не менее 1 ГБ на экземпляр.
* Запускайте минимум два реплики OSD за балансировщиком для отказоустойчивости UI (само состояние хранится в кластере, экземпляры stateless).

### Устранение типовых неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| OSD не стартует, в логах «Unable to retrieve version information from OpenSearch nodes» | Недоступен `opensearch.hosts`, ошибка TLS (неверный CA при `verificationMode: full`) или сервисная учетная запись без прав на системные индексы | Проверьте кластер напрямую: `curl -ku admin:'...' https://os-node-01:9200`; проверьте CA в `opensearch.ssl.certificateAuthorities`; проверьте роль `kibanaserver` в Security |
| Страница «Dashboards server is not ready yet», `/api/status` = `degraded` | Ядро еще инициализируется (30–60 с) или миграции saved objects не завершены | Подождите и обновите страницу; если не проходит — `GET _cluster/health` (должен быть yellow/green) и `journalctl -u opensearch-dashboards` |
| Ошибка совместимости версий при старте OSD | Несовпадение минорных версий OSD и ядра (OSD 3.x требует ядро 3.x той же минорной линии) | Выровняйте версии образов/пакетов; матрица совместимости в документации проекта |
| Пустые панели после импорта NDJSON | Index pattern указывает на индексы, отсутствующие в целевом кластере, или смещен временной фильтр | Проверьте шаблон индекса (Management > Index Patterns) и тайм-рейндж дашборда |
| Поле не найдено в Discover при фильтрации | Поле отсутствует в маппинге шаблона индекса | Включите `courier:ignoreFilterIfFieldNotInIndex` для разнородных логов или добавьте поле в маппинг |
| Импорт большого NDJSON обрезается / 413 | Лимит полезной нагрузки сервера | Увеличьте `server.maxPayloadBytes` (например, до 104857600) и перезапустите OSD |
| Страница Reporting не загружает список определений | Существует определение с несовместимой парой «тип источника — формат» (например, `Visualization` + `Csv`) | Удалите дефектное определение: `DELETE /_plugins/_reports/definition/<id>` на кластере |
| Высокое потребление памяти процессом OSD | Десятки пользователей/дашбордов, крупные NDJSON | Поднимите `NODE_OPTIONS=--max-old-space-size=2048`; закладывайте ≥1 ГБ на экземпляр |
| После обновления объекты не мигрировались | Миграции saved objects прерваны или `.kibana*` поврежден | Снапшот системных индексов `.kibana*` делается ДО обновления; при сбое — восстановите снапшот и повторите обновление |

Диагностический эндпоинт состояния: `GET /api/status` (порт 5601) — поля `status.overall.state` и версия; логи: `journalctl -u opensearch-dashboards -f`.

### Безопасность

* **Аутентификация**: при включенном Security плагине OSD требует логин; бэкенды — внутренняя база, LDAP/AD, SAML/OIDC-провайдеры. Сервисная учетная запись OSD должна иметь минимальные права (роль `kibanaserver`, а не `all_access`).
* **Разграничение доступа**: роли Security определяют видимые индексы и операции; тенант (`tenant_permissions`) — куда пользователь сохраняет объекты. Пользователь без прав на индекс не увидит данные ни в Discover, ни через ассистента.
* **Workspace ACL** (2.18+): дополнительный слой — кто может просматривать и администрировать конкретное рабочее пространство.
* **TLS**: настройте `opensearch.ssl.verificationMode: full` и собственный CA для связи OSD-кластер; для публикации за reverse-proxy используйте `server.basePath` и `server.rewriteBasePath`.
* **Актуальность версии**: в 2026 году в OSD исправлены критические уязвимости зависимостей Node.js (CVE-2026-28292 — command injection/RCE через simple-git, CVE-2026-33937 — RCE через handlebars, CVE-2026-25639 — DoS через axios; исправлены в цикле 3.7) и stored XSS в плагине observability (CVE-2026-77811, исправлен в 3.4 и 2.19.6) — держите OSD обновленным и подписывайтесь на advisories проекта.

Детали управления ролями и пользователями: [Администрирование OpenSearch](./opensearch_administration.md).

### Обновление и совместимость версий

* Номера версий OSD синхронизированы с ядром: OpenSearch 3.x работает только с Dashboards 3.x той же минорной версии (матрица совместимости в документации проекта).
* Порядок обновления стека: снапшот системных индексов `.kibana*` → обновление ядра → обновление OSD → проверка `/api/status`.
* Ветка 2.19 продолжает получать патчи безопасности параллельно с 3.x (2.19.6 — июль 2026, 2.19.7 запланирован на октябрь 2026) — организации на 2.x имеют время на планирование миграции, но новые функции (Workspaces-улучшения, Explore Metrics, dashboard variables, Prometheus-переменные и crosshair из 3.9) появляются только в 3.x.
* При апгрейде с 1.x требуется промежуточное обновление (1.3 → 2.x → 3.x) как для ядра, так и для Dashboards.

Руководства по развертыванию самого стека: [Helm в Kubernetes](./opensearch_helm_deployment.md), [Ansible на выделенных серверах](./opensearch_ansible_deployment.md).

### Смежные продукты на базе OSD

Кодовая база OSD служит фундаментом для специализированных интерфейсов экосистемы: **[Wazuh Dashboard](../../Security/Tools/Wazuh/deployment.md)** (SIEM-консоль Wazuh построена на форке OpenSearch Dashboards с собственными приложениями анализа событий) и консоли Amazon OpenSearch Service. Навыки работы с OSD переносятся на эти продукты напрямую.

---
## См. также

* **[OpenSearch: Обзор](./opensearch_overview.md)** — архитектура и ядро системы.
* **[Администрирование OpenSearch](./opensearch_administration.md)** — роли, безопасность, устранение неполадок.
* **[Alerting](./opensearch-alerting.md)** — мониторы и алерты через UI OpenSearch Dashboards.
* **[Kibana: Поиск, визуализация и управление](../Kibana/kibana_search_and_visualization.md)** — аналог в Elastic Stack для сравнения подходов.
