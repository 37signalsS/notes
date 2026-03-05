# Grafana: Источники данных

> **Навигация:**
>
> - [Обзор Grafana](./grafana_overview.md)
> - [Провиженинг](./grafana_provisioning.md)
> - [Установка через Docker](./Installation/docker_compose_setup.md)
> - [Установка через Helm](./Installation/grafana_helm_installation.md)

## Определения

**Источник данных (Datasource)** — подключение к системе хранения данных (Prometheus, MySQL, Loki и др.). Grafana **не хранит данные**, а выполняет запросы к источникам и визуализирует результаты.

**Текущая версия (февраль 2026):** Grafana 12.x поддерживает 50+ источников данных

### Атрибуты источника

| Атрибут | Описание |
| :--- | :--- |
| **Name** | Уникальное имя в интерфейсе Grafana |
| **Default** | Флаг источника по умолчанию |
| **Type** | Тип коннектора (Prometheus, MySQL, Loki...) |
| **URL** | Адрес системы (<http://prometheus:9090>) |
| **Auth** | Параметры аутентификации |

## Основные концепции

### Языки запросов

Grafana **не имеет собственного языка запросов** — используется нативный язык каждого источника:

| Источник | Язык запросов |
| :--- | :--- |
| **Prometheus** | PromQL |
| **Loki** | LogQL |
| **Tempo** | TraceQL |
| **MySQL/PostgreSQL** | SQL |
| **Elasticsearch** | Lucene Query DSL |

### Встроенные источники данных

| Источник | Назначение |
| :--- | :--- |
| **TestData** | Генерация случайных данных для тестирования визуализаций |
| **Mixed** | Объединение данных из нескольких источников на одной панели |
| **Dashboard** | Использование результатов запросов с других дашбордов |

## Практические сценарии

### Сценарий 1: Настройка Prometheus

**Docker Compose:**

```yaml
# grafana/provisioning/datasources/datasources.yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    access: proxy
    isDefault: true
    editable: true
```

**Kubernetes (Helm):**

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

**Ручная настройка (UI):**

1. **Connections → Data Sources → Add new data source → Prometheus**
2. **URL:** `http://prometheus:9090` (Docker) или `http://prometheus-server.monitoring.svc.cluster.local` (K8s)
3. **Access:** `Server (proxy)`
4. **Save & Test**

> **Примечание:** См. также [Провиженинг](./grafana_provisioning.md) для автоматизации.

### Сценарий 2: Интеграция Loki и Tempo (Derived Fields)

**Настройка связи логов с трассировками:**

1. **Добавьте Loki:**
   - **Connections → Data Sources → Loki**
   - **URL:** `http://loki:3100`
   - **Save & test**

2. **Добавьте Tempo:**
   - **Connections → Data Sources → Tempo**
   - **URL:** `http://tempo:3200`
   - **Trace to logs:** Выберите источник Loki
   - **Save & test**

3. **Настройте Derived Fields в Loki:**
   - Откройте настройки источника **Loki**
   - **Derived Fields → Add:**
     - **Name:** `TraceID`
     - **Regex:** `traceID=([a-zA-Z0-9]+)`
     - **URL:** `${__value.raw}`
     - **Internal Link:** ✓
     - **Data source:** Tempo
   - **Save & test**

**Результат:** Кликабельные `TraceID` в логах Loki открывают трассировки в Tempo.

### Сценарий 3: Настройка Loki

**URL для различных окружений:**

| Окружение | URL |
| :--- | :--- |
| **Docker Compose** | `http://loki:3100` |
| **Kubernetes** | `http://loki-distributed-gateway.loki.svc.cluster.local` |
| **Standalone** | `http://localhost:3100` |

## Дополнительная информация

### Популярные источники данных

| Источник | Тип | Назначение |
| :--- | :--- | :--- |
| **Prometheus** | Метрики | Мониторинг инфраструктуры и приложений |
| **Loki** | Логи | Агрегация и анализ логов |
| **Tempo** | Трассировки | Распределённые трассировки |
| **Mimir** | Метрики | Долгосрочное хранение метрик Prometheus |
| **MySQL/PostgreSQL** | SQL | Бизнес-метрики из БД |
| **Elasticsearch** | Логи/Поиск | Поиск и анализ логов |
| **CloudWatch** | Метрики AWS | Мониторинг AWS-ресурсов |
| **Azure Monitor** | Метрики Azure | Мониторинг Azure-ресурсов |

### Ссылки

- [Документация по источникам](https://grafana.com/docs/grafana/latest/datasources/)
- [Провиженинг источников](./grafana_provisioning.md)
