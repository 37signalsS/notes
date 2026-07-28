# Примеры LogQL запросов для Kubernetes

## Определения

**LogQL** (Log Query Language) — специализированный язык запросов Loki, вдохновлённый PromQL. Он позволяет извлекать данные из логов, фильтровать их, преобразовывать в метрики и агрегировать.

**Структура запроса:** `{селектор_потока} | фильтры_строк | парсеры | фильтры_полей | агрегации`

**Важное правило оптимизации:** Сначала применяйте фильтры по строкам (`|=`, `|~`), а затем парсеры (`| json`, `| pattern`). Это значительно снижает нагрузку на Querier, так как парсинг ресурсозатратен.

**Подробнее:** [Язык LogQL](../loki_overview.md#язык-запросов-logql)

## Основные концепции

### Типы операций в конвейере

| Операция | Синтаксис | Назначение |
| :--- | :--- | :--- |
| **Фильтр строк** | `|= "error"`, `!= "debug"` | Поиск или исключение подстроки (самый быстрый фильтр) |
| **Regex-фильтр** | `\|~ "pattern"`, `!~ "pattern"` | Фильтрация по регулярному выражению |
| **JSON-парсер** | `\| json` | Автоматическое извлечение полей из JSON-структур |
| **Logfmt-парсер** | `\| logfmt` | Извлечение полей из формата ключ=значение |
| **Pattern-парсер** | `\| pattern "<pattern>"` | Извлечение данных из неструктурированных логов по шаблону |
| **Фильтр по полям** | `\| status_code >= 500` | Фильтрация по значениям, извлечённым парсером |
| **Line Format** | `\| line_format "{{.msg}}"` | Изменение текста строки лога для отображения |
| **Label Format** | `\| label_format new=old` | Переименование, создание или удаление лейблов |
| **Drop / Keep** | `\| drop a, b`, `\| keep c` | Удаление или сохранение только указанных лейблов |

### Агрегирующие функции

| Функция | Тип | Пример |
| :--- | :--- | :--- |
| **`rate()`** | Метрика | `rate({app="api"}[5m])` — количество строк в секунду |
| **`count_over_time()`** | Счётчик | `count_over_time({app="api"}[1h])` — общее число строк за период |
| **`sum by()`** | Группировка | `sum by (level) (rate(...))` — сумма по уровням |
| **`topk()`** | Топ-N | `topk(5, count_over_time(...))` — топ-5 значений |
| **`avg_over_time()`** | Среднее | `avg_over_time({app="api"} \| json \| unwrap duration[5m])` |
| **`quantile_over_time()`** | Перцентиль | `quantile_over_time(0.95, ... \| unwrap latency[5m])` |

## Практические сценарии

### Базовые запросы

```logql
// Все логи из конкретного Namespace
{namespace="ingress-nginx"}

// Логи конкретного пода
{pod="my-app-pod-12345"}

// Логи контейнера в поде
{pod="my-app-pod", container="app"}

// Использование регулярных выражений в селекторах
{pod=~"my-app-.*", container!="istio-proxy"}
```

### Фильтрация и парсинг неструктурированных логов

Парсер `pattern` позволяет работать с логами фиксированного формата без использования сложных регулярных выражений.

```logql
// Пример строки: 127.0.0.1 - - [10/Oct/2025:13:55:36 +0000] "GET /api/v1/users HTTP/1.1" 200 2326
{app="nginx"} 
| pattern "<ip> - - [<timestamp>] \"<method> <path> <_>\" <status> <size>"
| status >= 400
```

### Работа с JSON и числовыми значениями (unwrap)

Оператор `unwrap` необходим для превращения извлечённых полей в числовые значения (samples), над которыми можно проводить математические операции.

```logql
// Вычисление среднего времени ответа из JSON-лога
// Лог: {"msg": "request", "latency": 150.5}
avg_over_time(
  {app="api"} 
  | json 
  | unwrap latency [5m]
)

// Процентиль 99 для времени выполнения (duration)
quantile_over_time(0.99,
  {app="worker"}
  | json
  | unwrap duration [1h]
)
```

### Модификация лейблов и строк

```logql
// Создание нового лейбла на основе существующего
{app="api"} | label_format service_name="api-{{.namespace}}"

// Очистка строки лога для вывода в Grafana (оставляем только сообщение и статус)
{app="api"} | json | line_format "Status: {{.status}} | Message: {{.msg}}"

// Использование label_replace (аналог PromQL)
{app="api"} | label_replace(pod, "node", "$1", "instance", "(.*):.*")
```

### Агрегация и сложные метрики

```logql
// Процент ошибок 5xx от общего трафика
sum(rate({app="api"} | json | status >= 500 [5m])) 
/ 
sum(rate({app="api"}[5m])) * 100

// Топ-10 пользователей по количеству запросов (из JSON)
topk(10, sum by (user_id) (count_over_time({app="api"} | json | user_id != "" [1h])))

// Поиск уникальных IP-адресов за час
sum(count_over_time({app="nginx"} | pattern "<ip> <_>" | distinct ip [1h]))
```

### Production-сценарии

```logql
// Обнаружение всплесков 404 ошибок в Nginx
{job="nginx-ingress"} |= " 404 " | rate(5m) > 10

// Мониторинг OutOfMemory (OOM) событий через системные логи
{cluster="prod"} |= "Out of memory" |~ "Killed process"

// Медленные SQL-запросы (>500мс) из логов приложения
{app="backend"} |= "duration_ms" | json | duration_ms > 500

// Корреляция логов по trace_id
{app=~"frontend|backend"} | json | trace_id="abc-123" | line_format "{{.app}}: {{.msg}}"
```

### Визуализация в Grafana

**Панель «Error Rate» (Time series):**
```logql
sum by (app) (rate({namespace="prod"} |= "level=error" [5m]))
```

**Панель «Latency Quantiles» (Heatmap или Time series):**
```logql
histogram_quantile(0.95, sum by (le) (rate({app="api"} | json | unwrap latency [5m])))
```

**Панель «Logs Volume by Container» (Bar Gauge):**
```logql
sum by (container) (count_over_time({namespace="prod"}[1h]))
```

## Дополнительная информация

| Ресурс | Описание |
| :--- | :--- |
| [Обзор LogQL](../loki_overview.md#язык-запросов-logql) | Синтаксис, селекторы и базовые концепции |
| [Установка Loki](loki_installation.md) | Развертывание бэкенда Loki в Kubernetes |
| [Установка Grafana](grafana_installation.md) | Визуализация и настройка источника данных |
| [Официальная документация LogQL](https://grafana.com/docs/loki/latest/logql/) | Полный справочник по языку от Grafana Labs |
