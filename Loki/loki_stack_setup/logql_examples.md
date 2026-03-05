# Примеры LogQL запросов для Kubernetes

## Базовые запросы

| Задача | LogQL запрос |
| :--- | :--- |
| **Все логи из namespace** | `{namespace="ingress-nginx"}` |
| **Логи конкретного пода** | `{pod="my-app-pod-12345"}` |
| **Логи конкретного контейнера** | `{pod="my-app-pod",container="app"}` |
| **Логи по лейблу приложения** | `{app="my-app"}` |

## Фильтрация по содержимому

### Текстовый поиск

| Задача | LogQL запрос |
| :--- | :--- |
| **Поиск ошибок в Java-приложении** | `{app="my-java-app"} \|= "Exception"` |
| **Логи с уровнем ERROR** | `{app="my-app"} \|~ "(?i)error"` |
| **Исключить строки** | `{app="my-app"} \|= "error" !=~ "debug"` |
| **Поиск по нескольким паттернам** | `{app="my-app"} \|~ "(error\|exception\|fatal)"` |

### Парсинг JSON-логов

| Задача | LogQL запрос |
| :--- | :--- |
| **Парсинг JSON** | `{app="my-app"} \| json` |
| **Фильтр по полю JSON** | `{app="my-app"} \| json \| status_code >= 500` |
| **Извлечение поля** | `{app="my-app"} \| json \| msg="request completed"` |
| **Фильтр по нескольким полям** | `{app="my-app"} \| json \| method="POST", status_code >= 400` |

### Парсинг logfmt

```logql
{app="my-app"} | logfmt | level="error"
```

## Агрегация и метрики

### Подсчет событий

| Задача | LogQL запрос |
| :--- | :--- |
| **Количество строк за период** | `count_over_time({app="my-app"}[1h])` |
| **Rate ошибок за 5 минут** | `sum(rate({app="my-app"} \|~ "error" [5m]))` |
| **Топ контейнеров по логам** | `topk(5, count_over_time({namespace="default"}[1h]))` |
| **Количество ошибок по уровням** | `sum by (level) (rate({app="my-app"} \| logfmt \| level=~"error\|warn" [5m]))` |

### Статистика

```logql
# Количество уникальных значений поля
count by (user_id) ({app="my-app"} | json)

# Процент ошибок
sum(rate({app="my-app"} |= "error"[5m])) / sum(rate({app="my-app"}[5m]))
```

## Практические примеры

### 1. Поиск медленных запросов

```logql
{app="api"} | json | duration_ms > 1000
```

### 2. Анализ HTTP-статусов

```logql
{app="api"} | json | status_code >= 500
```

### 3. Отслеживание ошибок аутентификации

```logql
{app="auth"} |= "authentication failed"
```

### 4. Мониторинг restart контейнеров

```logql
{kubernetes_namespace="kube-system"} |= "container restarted"
```

### 5. Поиск утечек памяти

```logql
{app="java-app"} |= "OutOfMemoryError"
```

## Визуализация в Grafana

### Панель "Количество ошибок"

```logql
sum(rate({app="my-app"} |= "error" [5m]))
```

**Тип визуализации:** Time series

### Панель "Топ ошибок по типам"

```logql
topk(10, sum by (error_type) (rate({app="my-app"} | json | error_type != "" [1h])))
```

**Тип визуализации:** Bar chart

### Панель "Распределение логов по уровням"

```logql
sum by (level) (rate({app="my-app"} | logfmt | level=~"info\|warn\|error" [5m]))
```

**Тип визуализации:** Pie chart

## Связанные темы

* **[Обзор Grafana Loki](./loki_overview.md)** — язык запросов LogQL, базовые концепции
* **[Установка Loki](./loki_stack_setup/loki_installation.md)** — установка Loki
* **[Установка Grafana](./loki_stack_setup/grafana_installation.md)** — визуализация логов
