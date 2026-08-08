# Grafana: Источники данных

## Определения

**Источник данных (Data Source)** — это мост между Grafana и внешней системой хранения телеметрии (метрик, логов, трассировок, профилей) или бизнес-данных. Grafana работает по принципу **Stateless Visualization**: она не хранит данные внутри себя (кроме метаданных и настроек), а выполняет запросы к источникам в реальном времени.

**Текущая версия (июль 2026):** Grafana 13.1. Платформа поддерживает более 170 официальных коннекторов и нативную интеграцию со стеком LGTM (Loki, Grafana, Tempo, Mimir).

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — архитектура и основные компоненты
- [Провиженинг](./grafana_provisioning.md) — автоматизация настройки через YAML/JSON
- [Дашборды](./grafana-dashboards.md) — визуализация данных из источников

### Параметры источника

| Атрибут | Описание |
| :--- | :--- |
| **Name** | Уникальное имя источника в интерфейсе Grafana |
| **Default** | Флаг, указывающий на использование источника по умолчанию в новых панелях |
| **Type** | Тип коннектора (Prometheus, MySQL, Loki, InfluxDB и др.) |
| **URL** | Адрес подключения к системе (например, `http://prometheus:9090`) |
| **Access** | Режим доступа: `Server (proxy)` (рекомендуется) или `Browser (direct)` |
| **JSON Data** | Расширенные настройки (`timeInterval`, `httpMethod`, `maxLines`, `timeout`) |
| **Secure JSON Data** | Конфиденциальные данные (API-ключи, пароли, TLS-ключи), не передаваемые на фронтенд |

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

---

## Безопасность и аутентификация

### Методы аутентификации

В 2026 году Grafana 13.x поддерживает расширенные механизмы безопасности:
1.  **Basic Auth:** Логин и пароль для простых интеграций.
2.  **API Keys / Tokens:** Использование Bearer-токенов (для Grafana Cloud или SaaS-решений).
3.  **TLS Client Auth:** Аутентификация по сертификатам (Certificate, Key, CA Cert).
4.  **Forward OAuth Identity:** Передача токена пользователя, вошедшего в Grafana, в целевой источник.
5.  **Service Accounts:** Использование токенов сервисных аккаунтов (замена устаревшим API-ключи) для автоматизации и Terraform.

### Безопасное хранение (Secure JSON Data)

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

---

## Возможности Grafana 13.x

### AI-ассистент (Grafana Assistant)
Интегрирован в Query Editor: генерация запросов по описанию на естественном языке, объяснение сложных выражений и предложение оптимизаций PromQL/SQL.

### Private Data Source Connect (PDC)
Позволяет безопасно подключать источники данных в приватных сетях к Grafana Cloud через исходящее соединение агента (PDC Agent), исключая необходимость открытия входящих портов.

### SQL-выражения и трансформации
Grafana 13 расширяет обработку данных на стороне клиента:
- **SQL Expressions:** Возможность объединять (Join) и преобразовывать данные из разных источников (например, Prometheus и MySQL) с использованием SQL-синтаксиса в браузере.
- **Query Caching:** Встроенное кеширование результатов для снижения нагрузки на тяжелые источники (Enterprise/Cloud).

### Data Correlations (v10+)
Механизм, пришедший на смену Derived Fields. Позволяет определять глобальные правила связи (например, автоматическое создание ссылок на логи из графиков метрик по общим лейблам).

---

## Практические сценарии

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
    jsonData:
      timeInterval: "15s"
      httpMethod: "POST" # Рекомендуется для длинных PromQL запросов
      exemplars:
        datasourceUid: 'tempo-uid' # Связь с трассировками
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
```

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

### Сценарий 3: Настройка InfluxDB v2 (Flux)

В современных инсталляциях InfluxDB используется язык Flux и аутентификация по токенам.

```yaml
# provisioning/datasources/influxdb-v2.yaml
apiVersion: 1
datasources:
  - name: InfluxDB-v2
    type: influxdb
    url: http://influxdb:8086
    jsonData:
      version: Flux
      organization: my-org
      defaultBucket: telegraf
    secureJsonData:
      token: "${INFLUXDB_TOKEN}"
```

---

## Устранение неисправностей

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| **"Context deadline exceeded"**| Медленный запрос или малый таймаут | Увеличьте `queryTimeout` в настройках источника или `dataproxy.timeout` в `grafana.ini`. |
| **"404 Not Found"** | Неверный URL или путь в API | Проверьте доступность источника изнутри пода/контейнера Grafana (`curl -v`). |
| **"Unauthorized"** | Неверные токены или истек срок действия | Проверьте `secureJsonData` и настройки RBAC для Service Account. |
| **"No data" на малых зумах** | Интервал запроса меньше скрейп-интервала | Установите корректный `Min Step` или используйте переменную `$__rate_interval`. |

---

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

**См. также:**
- [Официальная документация Grafana Labs](https://grafana.com/docs/grafana/latest/datasources/)
- [Маркетплейс плагинов источников данных](https://grafana.com/grafana/plugins/?type=datasource)
- [Grafana: Провиженинг](./grafana_provisioning.md)
