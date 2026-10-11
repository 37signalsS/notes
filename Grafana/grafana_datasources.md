# Grafana: Источники данных

**Актуально для:** Grafana 13.2.x / 12.x (LTS)

## Определения

**Источник данных (Data Source)** — это мост между Grafana и внешней системой хранения телеметрии (метрик, логов, трассировок, профилей) или бизнес-данных. Grafana работает по принципу **Stateless Visualization**: она не хранит данные внутри себя (кроме метаданных и настроек), а выполняет запросы к источникам в реальном времени.

**UID источника** — стабильный строковый идентификатор (`uid`), задаваемый явно при провиженинге. В отличие от автогенерируемого числового `id`, фиксированный `uid` гарантирует, что перекрёстные ссылки из дашбордов, алертов и корреляций не сломаются при повторном применении кода (idempotency). При импорте дашборда «по умолчанию» Grafana подставляет `uid` выбранного источника; при IaC принято использовать templated datasource `${datasource}` или явный `uid`.

**Версия и поддержка:** актуальная линия — Grafana 13.2.x (последний патч 13.2.3, сентябрь 2026); 12.x — LTS (обновления безопасности), 11.x — EOL с июня 2026. В каталоге более 150 источников данных, свыше 60 из них поддерживаются Grafana Labs. Платформа обеспечивает нативную интеграцию со стеком LGTM (Loki, Grafana, Tempo, Mimir). Облачные и ИИ-возможности (Grafana Cloud, Private Data Source Connect, Grafana Assistant) в этом документе не рассматриваются.

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — архитектура и основные компоненты
- [Провиженинг](./grafana_provisioning.md) — автоматизация настройки через YAML/JSON
- [Дашборды](./grafana-dashboards.md) — визуализация данных из источников
- [Корреляция телеметрии (Exemplars, Trace-to-*, Correlations)](./grafana_correlation_exemplars.md) — связывание источников между собой

### Параметры источника

| Атрибут | Описание |
| :--- | :--- |
| **Name** | Уникальное имя источника в интерфейсе Grafana |
| **Default** | Флаг, указывающий на использование источника по умолчанию в новых панелях |
| **Type** | Тип коннектора (Prometheus, MySQL, Loki, InfluxDB и др.) |
| **URL** | Адрес подключения к системе (например, `http://prometheus:9090`) |
| **Access** | Режим доступа: `Server (proxy)` (рекомендуется) или `Browser (direct)` |
| **JSON Data** | Расширенные настройки (`timeInterval`, `httpMethod`, `maxLines`, `timeout`, `httpHeaderName1`) |
| **Secure JSON Data** | Конфиденциальные данные (API-ключи, пароли, TLS-ключи, `httpHeaderValue1`), не передаваемые на фронтенд |
| **uid** | Явный стабильный идентификатор для idempotent-провиженинга и ссылок |

---

## Базовые концепции

### Языки запросов

Grafana использует нативные языки запросов каждой системы, обеспечивая максимальную гибкость и производительность:

| Источник данных | Язык запросов | Назначение |
| :--- | :--- | :--- |
| **Prometheus / Mimir** | **PromQL** | Временные ряды, агрегация метрик |
| **Loki** | **LogQL** | Фильтрация и парсинг логов, генерация метрик из логов |
| **Tempo** | **TraceQL** | Поиск и анализ распределенных трассировок |
| **Pyroscope** | **FlameQL** | Анализ профилей производительности (CPU, Memory) |
| **SQL (PG/MySQL/ClickHouse)**| **SQL** | Работа с реляционными и аналитическими БД |
| **Elasticsearch / OpenSearch**| **Lucene / PPL**| Полнотекстовый поиск и агрегации |

### Встроенные системные источники

| Источник | Назначение |
| :--- | :--- |
| **TestData** | Генерация случайных или фиксированных данных для тестирования визуализаций без реальной БД |
| **Mixed** | Специальный режим, позволяющий объединять данные из разных источников на одной панели |
| **Dashboard** | Позволяет использовать результаты запросов из других панелей того же дашборда для оптимизации нагрузки |
| **Grafana** | Доступ к внутренним метрикам Grafana, результатам алертов и объектам организации |

### Режимы доступа: Server (proxy) против Browser (direct)

Параметр `Access` определяет, **откуда** исходит запрос к бэкенду данных. Это критично для безопасности и для работы CORS.

- **Server (proxy)** (рекомендуется): Grafana-сервер сам обращается к источнику от своего имени, а браузер клиента общается только с Grafana. Преимущества:
  - Секреты (`secureJsonData`) никогда не покидают сервер Grafana и не видны в браузере клиента.
  - Не требуется настраивать CORS на стороне бэкенда (Prometheus, Loki и др.), так как запрос идёт «сервера-к-серверу».
  - Централизованный аудит и лимиты через `dataproxy.timeout`, `dataproxy.logging` в `grafana.ini`.
  - Возможность добавлять заголовки (например, `X-Scope-OrgID` для Mimir) на стороне сервера.
- **Browser (direct)**: браузер клиента стучится напрямую в бэкенд источника. Преимущества — меньше нагрузка на Grafana-сервер и обход прокси. Недостатки:
  - Требуется корректный CORS на бэкенде (разрешённые Origin/M Methods/Headers), иначе запросы падают с `CORS policy` ошибкой.
  - Секреты источника (при `Browser` доступе) фактически доступны на клиенте — режим не подходит для приватных credentials.
  - Не поддерживается для ряда enterprise-коннекторов.

| Критерий | Server (proxy) | Browser (direct) |
| :--- | :--- | :--- |
| Кто делает запрос | Grafana-сервер | Браузер пользователя |
| Секреты на клиенте | Нет | Да (риск утечки) |
| CORS на бэкенде | Не нужен | Обязателен |
| Аудит / таймауты | Централизованно | Нет |
| Нагрузка на Grafana | Выше | Ниже |

### Безопасность и аутентификация

#### Методы аутентификации

Grafana 13.x поддерживает следующие механизмы аутентификации при подключении к источнику:
1.  **Basic Auth:** Логин и пароль для простых интеграций.
2.  **TLS Client Auth:** Аутентификация по сертификатам (Certificate, Key, CA Cert).
3.  **Forward OAuth Identity:** Передача токена пользователя, вошедшего в Grafana, в целевой источник.
4.  **Service Account Tokens / Bearer:** Токен сервисного аккаунта в заголовке `Authorization: Bearer <TOKEN>` для API и провиженинга. API-ключи (API keys) полностью устарели (deprecated с февраля 2025) и автоматически мигрированы в сервисные аккаунты — используйте сервисные аккаунты.

#### Безопасное хранение (Secure JSON Data)

Все чувствительные данные в конфигурации провиженинга должны передаваться через секцию `secureJsonData`. В базе данных Grafana эти значения хранятся в зашифрованном виде.

**Пример безопасной конфигурации:**

```yaml
# provisioning/datasources/secure-ds.yaml
apiVersion: 1
datasources:
  - name: App-Database
    type: postgres
    url: postgres-db:5432
    user: grafana_reader
    secureJsonData:
      password: "${DB_PASSWORD}" # Значение подставляется из переменной окружения
```

### Возможности, влияющие на работу с источниками

#### SQL-выражения (SQL Expressions)
**Серверные выражения (server-side expressions):** Grafana получает данные от backend-источника, затем вычисляет и объединяет их на стороне сервера, перед тем как отдать на фронтенд. Позволяет выполнять join и преобразования данных из разных backend-источников (например, Prometheus и MySQL) SQL-подобным синтаксисом, без data warehouse. Включены по умолчанию, доступны в OSS и Enterprise; требуют backend-источник (frontend-only источники, например Dashboard, не поддерживаются). Ограничения: одно SQL-выражение на панель или правило алертинга, обязательна ссылка на диапазон времени, не поддерживается на 32-битных ARM-сборках Grafana.

#### Data Correlations
Глобальные правила связи между источниками (например, автоматическое создание ссылок на логи из графика метрик по общим лейблам). Настраиваются через `Administration → Correlations` и работают на уровне организации независимо от конкретного дашборда. Появились в Grafana 10, GA начиная с 10.3. Correlations **дополняют**, а не заменяют Derived Fields: связка «log → trace» в источнике Loki по-прежнему настраивается через **Derived Fields** (Regex по строке лога + Internal link на Tempo), а Correlations удобны для произвольных cross-source связей на уровне организации.

#### Query Caching
Кеширование результатов запросов на стороне Grafana для снижения нагрузки на медленные источники. Функция Grafana Enterprise; кеш-бэкенд (обычно Redis) настраивается в `grafana.ini`.

---

## Практические сценарии

### Предварительные требования

- **Grafana**: 11.x (минимум), 12.x (LTS) или 13.2.x (актуальная). См. [Обзор Grafana](./grafana_overview.md).
- **Сетевая доступность**: Grafana-сервер (при `Server` доступе) или браузер клиента (при `Browser` доступе) должны достигать `URL` источника (проверка `curl -v <URL>` из пода/хоста Grafana).
- **Учётные данные**: токен/пароль/сертификат заранее подготовлены и вынесены в секреты (env-переменная, Vault, Kubernetes Secret) — не в коммите.
- **Права RBAC**: для создания через UI — роль Editor/Admin; через API/провиженинг — `datasources:create`/Service Account с соответствующей ролью. См. [Управление пользователями и аутентификация](./grafana_user_management_and_authentication.md).
- **Провиженинг**: директория `/etc/grafana/provisioning/datasources` смонтирована (для файлового подхода) либо доступ к UI `Connections → Data sources`.
- **Ограничение**: Unified Alerting не поддерживает dashboard-переменные в запросах источника (вычисляются сервером вне контекста дашборда).

### Сценарий 1: Настройка источника Prometheus

Для настройки Prometheus можно использовать автоматизированный подход (провиженинг) или ручную настройку.

**Конфигурация для Docker Compose:**

```yaml
# provisioning/datasources/prometheus.yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    access: proxy
    isDefault: true
    editable: true
    uid: prometheus-prod # Стабильный uid для ссылок из дашбордов/алертов
    jsonData:
      timeInterval: "15s"
      httpMethod: "POST" # Рекомендуется для длинных PromQL запросов
      exemplarTraceIdDestinations: # Связь с трассировками (exemplars → Tempo)
        - name: traceID
          datasourceUid: tempo-uid
```

**Конфигурация для Kubernetes (Helm `values.yaml`):**

```yaml
# values.yaml
grafana:
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
        - name: Prometheus
          type: prometheus
          url: http://prometheus-server.monitoring.svc.cluster.local
          access: proxy
          isDefault: true
          uid: prometheus-prod
```

**Ожидаемый результат:** при запуске/перезагрузке Grafana источник `Prometheus` появляется в списке `Connections → Data sources` и становится источником по умолчанию.

**Валидация:**
```bash
# Проверка, что источник зарегистрирован (Server-side)
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://grafana:3000/api/datasources/uid/prometheus-prod | jq '.id, .uid'
# → 1 / "prometheus-prod"

# Быстрый запрос к Prometheus через прокси Grafana
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  "http://grafana:3000/api/datasources/proxy/uid/prometheus-prod/api/v1/query?query=up" \
  | jq '.status'
# → "success"
```

**Типичные проблемы:**
- Источник не появляется — неверный путь монтирования `/etc/grafana/provisioning/datasources` или синтаксическая ошибка YAML (см. логи Grafana `logger=provisioning`).
- `404` через proxy — источник недоступен из пода Grafana; проверьте `curl -v http://prometheus:9090` изнутри пода.

### Сценарий 1.1: Ручная настройка через UI

1.  Откройте **Connections → Data sources → Add new data source**.
2.  Выберите тип **Prometheus**, укажите **Name** (`Prometheus`) и **URL** (`http://prometheus:9090`).
3.  В разделе **HTTP** оставьте **Access = Server (proxy)**, при необходимости задайте `httpMethod = POST` в **JSON Data**.
4.  Нажмите **Save & test**.

**Ожидаемый результат:** кнопка возвращает «Data source is working» (зелёная галочка) — значит Grafana успешно достигла бэкенда.

**Валидация:**
```
Connections → Data sources → Prometheus → Save & test
# → "Data source is working. <N> metrics found"
```

**Типичные проблемы:**
- «Cannot connect» — бэкенд недоступен из сети Grafana или закрыт фаерволом.
- «Bad gateway (502)» при proxy — Grafana не может разрезолвить/достучаться до `URL`; проверьте DNS и порт.

### Сценарий 2: Интеграция Loki и Tempo (Derived Fields & Correlations)

Реализация сквозной навигации от логов к распределённым трассировкам.

1. **Настройка Tempo:**
   - В настройках источника Tempo укажите связь с Loki в разделе **Trace to logs**.

2. **Настройка Loki (Derived Fields / Correlations):**
   - Откройте настройки источника **Loki**.
   - В разделе **Derived Fields** (или через глобальные **Data Correlations**) добавьте правило:
     - **Name:** `TraceID`
     - **Regex:** `traceID=([a-zA-Z0-9]+)` (извлечение ID из строки лога)
     - **Internal Link:** Включите флаг.
     - **Data source:** Выберите ваш источник Tempo.

**Результат:** В интерфейсе `Explore` значения TraceID в логах станут кликабельными ссылками, открывающими трейс в Tempo.

**Валидация:**
```bash
# Проверка, что Tempo-источник доступен и корреляции работают (пример через Explore API)
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  "http://grafana:3000/api/ds/query" -H "Content-Type: application/json" \
  --data '{"queries":[{"refId":"A","datasource":{"uid":"tempo-uid"},"queryType":"traceql","query":"{ }"}]}' \
  | jq '.results.A.status'
# → "OK" (или "success")
```

**Типичные проблемы:**
- Ссылка TraceID не кликабельна — неверный Regex (не совпадает с форматом лога) или не выбран Data source Tempo в Internal Link.
- Навигация не работает — проверьте поле **Query** (`${__value.raw}`) в целевом Tempo-источнике; для произвольных cross-source связей используйте глобальные Correlations.

### Сценарий 3: Настройка InfluxDB v2 (Flux)

В современных инсталляциях InfluxDB используется язык Flux и аутентификация по токенам.

```yaml
# provisioning/datasources/influxdb-v2.yaml
apiVersion: 1
datasources:
  - name: InfluxDB-v2
    type: influxdb
    url: http://influxdb:8086
    access: proxy
    jsonData:
      version: Flux
      organization: my-org
      defaultBucket: telegraf
    secureJsonData:
      token: "${INFLUXDB_TOKEN}"
```

**Ожидаемый результат:** источник `InfluxDB-v2` зарегистрирован; запросы на Flux выполняются через `Explore`.

**Типичные проблемы:**
- `401 Unauthorized` — `INFLUXDB_TOKEN` не подставился или истёк; проверьте переменную окружения Grafana.
- Пустые результаты — неверная `organization`/`defaultBucket`.

### Сценарий 4: Mimir как Prometheus-совместимый источник (мультитенантность)

Grafana Mimir предоставляет Prometheus-API, но в мультитенантном режиме требует заголовок `X-Scope-OrgID`. Его добавляют на стороне Grafana (server proxy), чтобы не светить тенант в браузере.

```yaml
# provisioning/datasources/mimir.yaml
apiVersion: 1
datasources:
  - name: Mimir-LTS
    type: prometheus
    url: http://mimir-query-frontend.mimir.svc:9009/prometheus
    access: proxy
    jsonData:
      httpMethod: POST
      httpHeaderName1: "X-Scope-OrgID"   # Имя заголовка тенанта
    secureJsonData:
      httpHeaderValue1: "my-org-id"       # Значение тенанта (секрет)
```

**Ожидаемый результат:** источник `Mimir-LTS` прозрачно передаёт `X-Scope-OrgID` в каждом запросе; PromQL работает как к обычному Prometheus.

**Валидация:**
```bash
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  "http://grafana:3000/api/datasources/proxy/uid/mimir-lts/api/v1/query?query=up" \
  | jq '.status'
# → "success"
```

**Типичные проблемы:**
- `401/403` от Mimir — не задан `httpHeaderName1`/`httpHeaderValue1` или тенант не существует.
- Перепутан `url` — Mimir query-frontend слушает `/prometheus` (или `/api/prom`), проверьте ingress.

### Сценарий 5: Управление источником данных как код (Terraform / gcx)

При подходе Monitoring as Code источники описываются декларативно и применяются через CI/CD. См. [Monitoring as Code](./monitoring_as_code.md).

**Terraform:**
```hcl
resource "grafana_data_source" "prometheus" {
  type       = "prometheus"
  name       = "Prometheus"
  url        = "http://prometheus:9090"
  is_default = true
  uid        = "prometheus-prod"

  json_data_encoded = jsonencode({
    httpMethod   = "POST"
    timeInterval = "15s"
  })
  # Секреты подставляются из Vault/CI, а не коммитятся
  secure_json_data_encoded = jsonencode({
    httpHeaderValue1 = var.mimir_tenant
  })
}
```

**gcx (Grafana CLI):**
```bash
# Выгрузка ресурсов Grafana (дашборды, папки и др.) в локальные YAML
gcx resources pull -p ./resources -o yaml
# Применение локальных изменений обратно в Grafana
gcx resources push -p ./resources
# → список синхронизированных ресурсов

# Обнаружение источников и запросы к ним (read-only, не декларативное управление)
gcx datasources list
gcx datasources query <DS_UID> 'up'
```

*`gcx` — актуальная CLI Grafana Labs (пришла на смену `grafanactl`, который, в свою очередь, заменил Grizzly). Источники данных доступны в `gcx` для чтения и запросов (`gcx datasources list/get/query`); декларативное управление источниками выполняйте через YAML-провиженинг или Terraform.*

**Ожидаемый результат:** `terraform apply` создаёт/обновляет источник; повторный запуск идемпотентен благодаря фиксированному `uid`.

**Валидация:**
```bash
terraform plan   # → grafana_data_source.prometheus будет создан/изменён
terraform apply  # → Apply complete! Resources: 1 added
```

**Типичные проблемы:**
- `409 conflict` — источник с таким `uid` уже есть, но управляется вручную; удалите ручной или задайте `uid` явно.
- Дашборды не видят источник — убедитесь, что `uid` совпадает с `datasource` в JSON дашбордов.

---

## Устранение неполадок

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| **"Context deadline exceeded"**| Медленный запрос или малый таймаут | Увеличьте HTTP-таймаут источника (`jsonData.timeout`, переопределяет `dataproxy.timeout` в `grafana.ini`); для Prometheus — `queryTimeout` (query timeout, по умолчанию `60s`). |
| **"404 Not Found"** | Неверный URL или путь в API | Проверьте доступность источника изнутри пода/контейнера Grafana (`curl -v`). |
| **"Unauthorized"** | Неверные токены или истек срок действия | Проверьте `secureJsonData` и настройки RBAC для Service Account. |
| **"No data" на малых зумах** | Интервал запроса меньше скрейп-интервала | Установите корректный `Min Step` или используйте переменную `$__rate_interval`. |
| **"CORS policy" (Browser access)** | Бэкенд не разрешает Origin клиента | Переключитесь на `Server (proxy)` или настройте CORS на бэкенде. |
| **"Bad gateway (502)"** | Grafana не достигает `URL` (DNS/порт/сеть) | Проверьте `curl -v <URL>` из пода Grafana; firewall/Service. |
| **"Data source is not working"** | Бэкенд недоступен или неверны creds | Проверьте доступность и `secureJsonData`; см. лог `logger=tsdb`. |
| **"Forbidden" при создании** | Нет прав RBAC | Назначьте роль Editor / `datasources:create` сервисному аккаунту. |
| **Пустые результаты (Mimir/Influx)** | Неверный тенант / org / bucket | Сверьте `httpHeaderValue1`, `organization`, `defaultBucket`. |

**Диагностика:** основные ошибки видны в логах Grafana (`logger=provisioning` для файлов, `logger=tsdb`/`logger=dataproxy` для запросов). Проверка связности — `curl -v <URL>` непосредственно из пода Grafana (или хоста при `Browser` доступе). Точечная проверка одного источника — `GET /api/datasources/uid/:uid/health`.

## Рекомендации по эксплуатации

- **Используйте `Server (proxy)` доступ** по умолчанию — скрывает секреты от клиента и снимает требование CORS на бэкенде.
- **Фиксируйте `uid`** для всех провиженинг-источников, чтобы ссылки из дашбордов и алертов оставались стабильными.
- **Устанавливайте `editable: false`** в провиженинг-конфигурациях, чтобы ручные правки в UI не создавали конфигурационный дрейф (Git остаётся источником правды).
- **Храните секреты вне Git**: через env-переменные (`${VAR}`), Vault, SOPS или Kubernetes Secret; никогда не коммитьте пароли в `secureJsonData` как есть.
- **Минимальные привилегии**: для CI/CD и API используйте выделенный Service Account с ролью Editor (или кастомной ролью `datasources:create/query`), токен ротируйте.
- **Соглашение об именовании**: понятные стабильные имена (`Prometheus`, `Loki`) упрощают выбор источника в дашбордах и шаблонах `${datasource}`.

## Ограничения и особые случаи

- **Browser (direct) доступ** требует корректного CORS на бэкенде и непригоден для приватных секретов (они попадают в браузер клиента).
- **Proxy не для всех типов**: ряд enterprise-коннекторов поддерживает только `Server (proxy)` или только определённый режим — сверяйте документацию конкретного плагина (см. [Плагины Grafana](./grafana_plugins.md)).
- **Derived Fields и Correlations дополняют друг друга**: Derived Fields (Regex по строке лога + Internal link) — для ссылок «log → trace» в источнике Loki; глобальные Correlations (с 10.3) — для произвольных cross-source связей на уровне организации.
- **Mixed-источник** объединяет данные на одной панели, но не поддерживает cross-source joins внутри одного запроса (для join используйте SQL Expressions).
- **Секреты в `Browser` режиме**: не используйте `secureJsonData` с приватными credentials при `access: browser` — они становятся доступны на клиенте.
- **Версионность**: синтаксис `jsonData`/`secureJsonData` и доступность фич (SQL Expressions, Correlations) различаются между 11/12/13 — фиксируйте версию Grafana в CI-образе.

## Дополнительная информация

### Популярные источники данных и области применения

| Источник | Тип данных | Область применения |
| :--- | :--- | :--- |
| **Prometheus / Mimir** | Метрики | Оперативный мониторинг инфраструктуры и Kubernetes |
| **Loki** | Логи | Сбор и анализ логов (интеграция по лейблам) |
| **Tempo** | Трассировки | Анализ производительности распределённых систем |
| **ClickHouse** | OLAP | Аналитическая визуализация огромных объемов данных |
| **PostgreSQL** | SQL | Визуализация бизнес-метрик из реляционных БД |
| **Elasticsearch / OpenSearch**| Логи/Поиск | Глубокий полнотекстовый анализ и поиск |

### Data Source HTTP API

| Метод | Эндпоинт | Назначение |
| :--- | :--- | :--- |
| GET | `/api/datasources` | Список всех источников (без пагинации; по умолчанию не более 5000) |
| GET | `/api/datasources/uid/:uid` | Источник по `uid` |
| POST | `/api/datasources` | Создать источник (право `datasources:create`) |
| PUT | `/api/datasources/uid/:uid` | Обновить существующий (право `datasources:write`) |
| DELETE | `/api/datasources/uid/:uid` | Удалить (право `datasources:delete`) |
| GET | `/api/datasources/proxy/uid/:uid/*` | Проксирование запросов к источнику |
| GET | `/api/datasources/uid/:uid/health` | Проверка работоспособности источника |
| GET | `/api/datasources/uid/:uid/resources/*` | Ресурсы плагина источника |
| POST | `/api/ds/query` | Универсальный запрос к backend-источнику |

Чтение требует права `datasources:read` (scope `datasources:*`). Эндпоинты `/api/datasources/name/:name` и `/api/datasources/id/:name` помечены как deprecated. Начиная с Grafana 13 эндпоинты `/api` постепенно вытесняются маршрутом `/apis`; legacy-маршруты продолжают работать, но больше не развиваются.

### См. также

- [Провиженинг Grafana](./grafana_provisioning.md) — файловое управление источниками
- [Monitoring as Code](./monitoring_as_code.md) — Terraform/gcx для источников
- [Плагины Grafana](./grafana_plugins.md) — типы Data Source коннекторов
- Официальная документация: https://grafana.com/docs/grafana/latest/datasources/
