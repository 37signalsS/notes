# Grafana: Источники данных

## Определения

**Источник данных (Data Source)** — это подключение к внешней системе хранения данных, такой как Prometheus, MySQL, Loki или Elasticsearch. Grafana **не хранит данные** самостоятельно; она выполняет запросы к настроенным источникам, получает результаты и визуализирует их на панелях дашбордов.

**Текущая версия (март 2026):** Grafana 12.x поддерживает более 50 официальных источников данных и сотни плагинов от сообщества.

**Связанные темы:**

- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Провиженинг](./grafana_provisioning.md) — автоматизация настройки через конфигурационные файлы
- [Дашборды](./grafana-dashboards.md) — создание визуализаций на основе данных

### Атрибуты источника

| Атрибут | Описание |
| :--- | :--- |
| **Name** | Уникальное имя источника в интерфейсе Grafana |
| **Default** | Флаг, указывающий на использование источника по умолчанию в новых панелях |
| **Type** | Тип коннектора (Prometheus, MySQL, Loki, InfluxDB и др.) |
| **URL** | Адрес подключения к системе (например, `http://prometheus:9090`) |
| **Auth** | Параметры аутентификации (Basic Auth, API-ключи, TLS-сертификаты) |

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

**Ручная настройка через веб-интерфейс:**

1. Перейдите в **Connections → Data Sources → Add new data source**.
2. Выберите **Prometheus**.
3. В поле **URL** укажите адрес сервера (например, `http://localhost:9090`).
4. В разделе **Access** выберите `Server (proxy)` (рекомендуется для большинства случаев).
5. Нажмите **Save & Test**.

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

### Сценарий 3: Настройка InfluxDB (Provisioning)

Пример конфигурации для InfluxDB v1.x:

```yaml
# provisioning/datasources/influxdb.yaml
apiVersion: 1
datasources:
  - name: InfluxDB
    type: influxdb
    url: http://influxdb:8086
    database: telegraf
    user: telegraf
    password: "${INFLUXDB_PASSWORD}" # Рекомендуется использовать переменные окружения
    access: proxy
    isDefault: false
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

**См. также:**

- [Официальная документация Grafana Labs](https://grafana.com/docs/grafana/latest/datasources/)
- [Маркетплейс плагинов источников данных](https://grafana.com/grafana/plugins/?type=datasource)
