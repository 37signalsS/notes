# Примеры LogQL запросов для Kubernetes

## Определения

**LogQL** (Log Query Language) — язык запросов Loki, синтаксически похожий на PromQL. Состоит из селектора потока `{метки}` и конвейера фильтров (`|=`, `|~`, `| json`, агрегации).

**Структура запроса:** `{селектор} | фильтр | парсер | агрегация`

**Подробнее:** [Язык LogQL](../loki_overview.md#язык-запросов-logql)

## Основные концепции

### Типы операций в конвейере

| Операция | Синтаксис | Назначение |
| :--- | :--- | :--- |
| **Фильтр строк** | `\|= "error"`, `!= "debug"` | Поиск/исключение подстроки |
| **Regex-фильтр** | `\|~ "pattern"`, `!~ "pattern"` | Фильтрация по регулярному выражению |
| **JSON-парсер** | `\| json` | Извлечение полей из JSON-логов |
| **Logfmt-парсер** | `\| logfmt` | Извлечение полей из logfmt-логов |
| **Фильтр по полям** | `\| json \| status_code >= 500` | Фильтрация после парсинга |
| **Line Format** | `\| line_format "{{.method}} {{.status}}"` | Форматирование вывода |
| **Label Format** | `\| label_format env=environment` | Переименование лейблов |

### Агрегирующие функции

| Функция | Тип | Пример |
| :--- | :--- | :--- |
| **`rate()`** | Метрика | `rate({app="api"}[5m])` — строк/сек |
| **`count_over_time()`** | Счётчик | `count_over_time({app="api"}[1h])` — всего строк |
| **`sum by()`** | Группировка | `sum by (level) (rate(...))` — по уровням |
| **`topk()`** | Топ-N | `topk(5, count_over_time(...))` — топ-5 |
| **`avg_over_time()`** | Среднее | `avg_over_time({app="api"} \| json \| duration_ms[5m])` |

## Практические сценарии

### Базовые запросы

```logql
// Все логи из namespace
{namespace="ingress-nginx"}

// Логи конкретного пода
{pod="my-app-pod-12345"}

// Логи контейнера в поде
{pod="my-app-pod", container="app"}

// Логи по лейблу приложения
{app="my-app"}
```

### Фильтрация по содержимому

```logql
// Поиск ошибок в Java-приложении
{app="my-java-app"} |= "Exception"

// Логи с уровнем ERROR (case-insensitive)
{app="my-app"} |~ "(?i)error"

// Исключение строк с debug
{app="my-app"} |= "error" !=~ "debug"

// Несколько паттернов (error/exception/fatal)
{app="my-app"} |~ "(error|exception|fatal)"
```

### Парсинг JSON-логов

```logql
// Базовый парсинг
{app="my-app"} | json

// Фильтр по полю JSON (HTTP 5xx)
{app="my-app"} | json | status_code >= 500

// Фильтр по текстовому полю
{app="my-app"} | json | msg="request completed"

// Несколько условий (POST-запросы с ошибками)
{app="my-app"} | json | method="POST", status_code >= 400
```

### Парсинг logfmt

```logql
// Фильтр по уровню лога
{app="my-app"} | logfmt | level="error"

// Фильтр по нескольким полям
{app="my-app"} | logfmt | level="warn", service="auth"
```

### Агрегация и метрики

```logql
// Количество строк за час
count_over_time({app="my-app"}[1h])

// Rate ошибок за 5 минут
sum(rate({app="my-app"} |~ "error"[5m]))

// Топ-5 контейнеров по объему логов
topk(5, count_over_time({namespace="default"}[1h]))

// Ошибки по уровням (logfmt)
sum by (level) (rate({app="my-app"} | logfmt | level=~"error|warn"[5m]))

// Количество уникальных пользователей
count by (user_id) ({app="my-app"} | json)

// Процент ошибок от общего трафика
sum(rate({app="my-app"} |= "error"[5m])) / sum(rate({app="my-app"}[5m]))
```

### Production-сценарии

```logql
// Медленные запросы (>1 сек)
{app="api"} | json | duration_ms > 1000

// HTTP 5xx ошибки
{app="api"} | json | status_code >= 500

// Ошибки аутентификации
{app="auth"} |= "authentication failed"

// Restarts контейнеров в kube-system
{kubernetes_namespace="kube-system"} |= "container restarted"

// OutOfMemoryError в Java
{app="java-app"} |= "OutOfMemoryError"

// Долгие запросы с группировкой по статусу
sum by (status_code) (rate({app="api"} | json | duration_ms > 500[5m]))

// Ошибки с извлечением trace_id для корреляции
{app="api"} | json | level="error" | line_format "trace_id={{.trace_id}} msg={{.message}}"
```

### Визуализация в Grafana

**Панель «Rate ошибок» (Time series):**

```logql
sum(rate({app="my-app"} |= "error"[5m]))
```

**Панель «Топ ошибок по типам» (Bar chart):**

```logql
topk(10, sum by (error_type) (rate({app="my-app"} | json | error_type != ""[1h])))
```

**Панель «Распределение по уровням» (Pie chart):**

```logql
sum by (level) (rate({app="my-app"} | logfmt | level=~"info|warn|error"[5m]))
```

**Панель «Латентность по перцентилям» (Time series):**

```logql
histogram_quantile(0.95, sum by (le) (rate({app="api"} | json | duration_ms[5m])))
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Обзор LogQL](../loki_overview.md#язык-запросов-logql) | Синтаксис, селекторы, базовые концепции |
| [Установка Loki](loki_installation.md) | Развертывание бэкенда Loki |
| [Установка Grafana](grafana_installation.md) | Визуализация и настройка datasource |
| [Документация LogQL](https://grafana.com/docs/loki/latest/logql/) | Официальная документация Grafana Labs |
