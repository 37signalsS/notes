# Grafana: Источники данных

## Определения

**Источник данных (Data Source)** — это подключение к внешней системе хранения данных, такой как Prometheus, MySQL, Loki или Elasticsearch. Grafana **не хранит данные** самостоятельно; она выполняет запросы к настроенным источникам, получает результаты и визуализирует их на панелях дашбордов.

**Текущая версия (июль 2026):** Grafana 13.1. Поддерживается более 170 официальных источников данных и расширенный функционал на базе ИИ.

**Связанные темы:**

- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Провиженинг](./grafana_provisioning.md) — автоматизация настройки через конфигурационные файлы
- [Дашборды](./grafana-dashboards.md) — создание визуализаций на основе данных

### Параметры источника

| Атрибут | Описание |
| :--- | :--- |
| **Name** | Уникальное имя источника в интерфейсе Grafana |
| **Default** | Флаг, указывающий на использование источника по умолчанию в новых панелях |
| **Type** | Тип коннектора (Prometheus, MySQL, Loki, InfluxDB и др.) |
| **URL** | Адрес подключения к системе (например, `http://prometheus:9090`) |
| **Access** | Режим доступа: `Server (proxy)` (рекомендуется) или `Browser (direct)` |
| **JSON Data** | Расширенные настройки (`timeInterval`, `httpMethod`, `maxLines`) |
| **Secure JSON Data** | Конфиденциальные данные (API-ключи, пароли, TLS-ключи), не передаваемые на фронтенд |

## Базовые концепции

### Языки запросов

Grafana использует нативные языки запросов каждой системы. Это позволяет использовать всю мощь конкретной БД:

| Источник данных | Язык запросов |
| :--- | :--- |
| **Prometheus** | PromQL (Prometheus Query Language) |
| **Loki** | LogQL (Log Query Language) |
| **Tempo** | TraceQL (Trace Query Language) |
| **MySQL / PostgreSQL** | SQL (Structured Query Language) |
| **Elasticsearch** | Lucene Query DSL |

### Встроенные системные источники

| Источник | Назначение |
| :--- | :--- |
| **TestData** | Генерация случайных или фиксированных данных для тестирования визуализаций без реальной БД |
| **Mixed** | Специальный режим, позволяющий объединять данные из разных источников на одной панели |
| **Dashboard** | Позволяет использовать результаты запросов из других панелей того же дашборда для оптимизации нагрузки |
| **Grafana** | Доступ к внутренним метрикам Grafana и результатам выполнения алертов |

## Безопасность и аутентификация

### Методы аутентификации

1.  **Basic Auth:** Логин и пароль для простых интеграций.
2.  **API Keys / Tokens:** Использование Bearer-токенов (например, для Grafana Cloud или Vercel).
3.  **TLS Client Auth:** Аутентификация по сертификатам (Certificate, Key, CA Cert).
4.  **Forward OAuth Identity:** Передача токена пользователя, вошедшего в Grafana, в целевой источник (требуется настроенный OAuth).
5.  **Workload Identity Federation (WIF):** (Grafana 13+) Для Google Cloud (BigQuery, GCM) — использование краткосрочных OIDC-токенов вместо статических JSON-ключей сервисных аккаунтов.

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

## Возможности Grafana 13.x

### AI-ассистент (Grafana Assistant)

Начиная с версии 13.0, ИИ-помощник интегрирован непосредственно в Query Editor:
- **Генерация запросов:** Построение PromQL, LogQL или SQL-запросов на основе описания на естественном языке.
- **Объяснение запросов:** Анализ сложных выражений и вывод пояснений по их работе.
- **Оптимизация:** Предложение более эффективных способов фильтрации или агрегации данных.

### Private Data Source Connect (PDC)

PDC позволяет безопасно подключать источники данных, находящиеся за файрволом или в приватных сетях (on-premises), к экземпляру Grafana Cloud без необходимости открытия входящих портов. Для этого в приватной сети устанавливается агент (PDC Agent), который устанавливает исходящее соединение с Grafana Cloud.

### SQL-выражения и трансформации

Grafana 13 расширяет возможности обработки данных на стороне клиента:
- **SQL Expressions:** Возможность объединять (Join) и преобразовывать данные из разных источников (например, Prometheus и MySQL) с использованием SQL-подобного синтаксиса прямо в интерфейсе Grafana.
- **Query Caching:** Встроенное кеширование результатов запросов для снижения нагрузки на тяжелые источники данных (доступно в Enterprise и Cloud).

## Практические сценарии

### Сценарий 1: Настройка источника Prometheus

Для настройки Prometheus можно использовать автоматизированный подход (провиженинг) или ручную настройку через интерфейс.

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

### Сценарий 2: Интеграция Loki и Tempo (Derived Fields)

Этот сценарий позволяет реализовать сквозную навигацию от логов к распределённым трассировкам.

1. **Настройка Tempo:**
   - В настройках источника Tempo укажите связь с Loki в разделе **Trace to logs**.

2. **Настройка Loki (Derived Fields):**
   - Откройте настройки источника **Loki**.
   - В разделе **Derived Fields** нажмите **Add**:
     - **Name:** `TraceID`
     - **Regex:** `traceID=([a-zA-Z0-9]+)` (регулярное выражение для извлечения ID из строки лога)
     - **Internal Link:** Включите этот флаг.
     - **Data source:** Выберите ваш источник Tempo.
   - Нажмите **Save & test**.

**Результат:** В интерфейсе просмотра логов (`Explore`) значения TraceID станут кликабельными ссылками, открывающими соответствующую трассировку в Tempo.

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

## Дополнительная информация

### Популярные источники данных

| Источник | Тип данных | Область применения |
| :--- | :--- | :--- |
| **Prometheus** | Метрики | Оперативный мониторинг инфраструктуры и приложений |
| **Loki** | Логи | Сбор, хранение и анализ логов с использованием лейблов |
| **Tempo** | Трассировки | Анализ производительности распределённых систем |
| **Mimir** | Метрики | Долгосрочное и масштабируемое хранение метрик Prometheus |
| **PostgreSQL** | SQL | Визуализация бизнес-данных и аналитики из реляционных БД |
| **CloudWatch** | Облачные данные | Мониторинг ресурсов в инфраструктуре AWS |
| **Elasticsearch** | Логи/Поиск | Глубокий анализ логов и текстовый поиск |

**См. также:**

- [Официальная документация Grafana Labs](https://grafana.com/docs/grafana/latest/datasources/)
- [Маркетплейс плагинов источников данных](https://grafana.com/grafana/plugins/?type=datasource)
- [Grafana: Провиженинг](./grafana_provisioning.md)
