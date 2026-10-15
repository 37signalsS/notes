# jq — обработка JSON в командной строке

**Актуально для:** jq 1.7+

`jq` — легковесный CLI-парсер и трансформатор JSON. Работает с потоками и файлах, поддерживает вычисления, фильтры и переменные. Является стандартом де-факто для обработки JSON в shell-скриптах, CI/CD и трубопах.

## Базовые концепции

### Архитектура

`jq` принимает **фильтр** (выражение) и применяет его к JSON-вводу. Ввод может быть:
- Файлом (через аргумент или `file.json`)
- Потоком через `stdin` (чаще всего в трубопах `curl ... | jq ...`)

**Потоковая обработка:** jq обрабатывает каждый JSON-объект по отдельности, что позволяет работать с JSON Lines (`.jsonl`) и потоками событий.

### Основные типы данных

| Тип | Пример |
| :--- | :--- |
| Объект | `{"name": "server1", "cpu": 8}` |
| Массив | `[1, 2, 3]` |
| Строка | `"hello"` |
| Число | `42`, `3.14` |
| Булево | `true`, `false` |
| Null | `null` |

## Практические сценарии

### Чтение и извлечение значений

```bash
# Pretty-print (переформатировать JSON с отступами)
jq '.' data.json

# Извлечь значение по ключу
jq '.name' data.json
# → "nginx-01"

# Извлечь вложенное значение
jq '.server.hostname' data.json
# → "prod-web-01"

# Извлечь все значения поля из массива объектов
jq '.[].name' services.json
# → "web", "db", "cache"

# Сырой вывод (без кавычек для строк)
jq -r '.name' data.json
# → nginx-01

# Получить только HTTP-коды из журнала запросов
curl -s https://api.example.com/logs | jq -r '.response_code'
```

### Фильтрация и поиск

```bash
# Отбор объектов по условию
jq '.[] | select(.status == "failed") | .id' jobs.json

# Фильтрация по вложенному полю
jq '.items[] | select(.metadata.namespace == "production")' k8s.json

# Комбинация: фильтр + извлечение полей
jq '.[] | select(.cpu > 4) | {name, cpu, memory}' nodes.json

# Поиск по подстроке (регистрозависимо)
jq '.[] | select(.name | contains("prod"))' servers.json
```

### Трансформация данных

```bash
# Извлечь и переименовать поле
jq '{hostname: .name, cores: .cpu}' server.json

# Создать массив из значений поля
jq '[.[] | .name]' servers.json
# → ["web-01", "db-01", "cache-01"]

# Подсчет элементов массива
jq '.items | length' data.json

# Срез массива (skip/limit)
jq '.items[10:20]' data.json
```

### Обновление значений (in-place)

```bash
# Изменить поле в файле (требуется sponge из moreutils)
jq '.status = "completed"' state.json | sponge state.json

# Добавить новое поле
jq '.timestamp = now' data.json | sponge data.json

# Вложенное обновление
jq '.server.cpu = 16 | .server.memory = "64GB"' config.json | sponge config.json

# Использование переменных через --arg
jq --arg new_name "web-prod-01" '.name = $new_name' server.json | sponge server.json

# Использование переменной из окружения через --argjson
jq --argjson cpu $(nproc) '.cpu = $cpu' server.json | sponge server.json
```

### Работа с несколькими объектами

```bash
# Слепить несколько JSON-объектов в массив (slurp mode)
jq -s '.' *.json
# → [ {"name":"a"}, {"name":"b"} ]

# Слепить и агрегировать
jq -s 'map(.value) | add' values.jsonl

# compact output (все в одну строку, без отступов)
jq -c '.' large.json > compact.json

### Ключи и структура

```bash
# Получить все ключи объекта
jq 'keys' data.json

# Получить ключи вложенного объекта
jq '.metadata | keys' k8s-pod.json

# Проверить наличие ключа
jq 'has("critical_field")' config.json
# → true

### Оператор альтернативы (//)

```bash
# Использовать второе значение, если первое null или не существует
jq '.staging_url // .prod_url' config.json
# Если .staging_url равно null или отсутствует, вернёт .prod_url

# Значение по умолчанию
jq '.replicas // 1' deployment.json
# → 1, если .replicas не задан
```

### Условные выражения

```bash
# if/then/else/ end (выражение)
jq 'if .status == "ok" then .data else "error" end' api-response.json

# Множественная условная обработка
jq '.[] | if .type == "critical" then .name else empty end' alerts.json

# any() и all() для проверок
jq 'map(.status == "ok") | all' services.json
# → true, если все сервисы в статусе ok

jq '.[] | select(.errors > 0) | .name' services.json
```

### Reduce и группировка

```bash
# Сумма значений
jq 'reduce .[] as $item (0; . + $item.count)' data.json

# Группировка по полю
jq 'group_by(.category) | map({category: .[0].category, count: length})' items.json

# Агрегация в объект
jq '.[] | {level: .severity} | group_by(.level) | {critical: 0, warning: 0} + (map(.) | .[])' alerts.json
```

### Работа с JSON Lines (NDJSON)

```bash
# Чтение JSONL (по одному объекту на строку)
jq -c '.' events.jsonl

# Фильтр для потока событий
curl -Ns https://api.example.com/stream | \
  jq -c 'select(.event_type == "error") | {timestamp, message}'
```

### Сериализация в строку

```bash
# Преобразовать объект в JSON-строку
jq -r 'tojson' data.json
# → {"name":"server","cpu":8}

# Обратное преобразование
echo '{"name":"test"}' | jq 'fromjson? // .'
```

## Операции и команды

| Команда | Описание | Пример |
| :--- | :--- | :--- |
| `jq '.'` | Pretty-print / форматирование | `jq '.' data.json` |
| `jq '.key'` | Извлечение значения | `jq '.name' config.json` |
| `jq '.[]'` | Итерация по массиву/объекту | `jq '.[] \| .id' items.json` |
| `jq 'select(...)'` | Фильтр по условию | `jq '.[] \| select(.>5)' arr.json` |
| `jq -r` | Сырой вывод (без кавычек) | `jq -r '.url' config.json` |
| `jq -c` | Компактный вывод | `jq -c '.' large.json` |
| `jq -s` | Slurp (слияние в массив) | `jq -s '.' *.json` |
| `jq -S` | Сортировка ключей | `jq -S '.' unsorted.json` |
| `jq 'keys'` | Список ключей | `jq 'keys' obj.json` |
| `jq 'length'` | Количество элементов | `jq '.items \| length' data.json` |
| `jq --arg name "val"` | Передача строковой переменной | `jq --arg v "true" '.flag = ($v == "true")'` |
| `jq --argjson name val` | Передача JSON-переменной | `jq --argjson n 42 '.count = $n'` |
| `jq 'group_by(.field)'` | Группировка | `jq 'group_by(.type)' items.json` |
| `jq 'map(.field)'` | Трансформация массива | `jq '.items \| map(.id)' data.json` |
| `jq 'reduce'` | Агрегация | `jq 'reduce .[] as $x (0; .+1)'` |
| `jq 'tojson'` | Сериализация в строку | `jq -r '. \| tojson'` |
| `jq 'fromjson'` | Десериализация из строки | `echo '{"a":1}' \| jq fromjson` |
| `jq -e` | Тихий режим с проверкой | `jq -e '.status == "ok"' resp.json` |

## Дополнительная информация

### Производительность

Для больших файлов (`>100 MB`) используйте:
- `-S` (sort keys) — предсказуемый вывод, полезно для диффов
- `jq -c` — компактный вывод уменьшает размер
- `jq 'reduce'` — эффективнее `map`, когда не нужен массив

### Интеграция с pipe и process substitution

```bash
# Чтение из процесса вместо файла
jq '.name' <(curl -s https://api.example.com/data)

# Объединение с xargs для пакетной обработки
cat services.json | jq -r '.[].host' | xargs -I{} ssh {} 'uptime'
```

### См. также

- [cURL — универсальный инструмент для передачи данных](./curl.md) — использование `curl | jq` для обработки API-ответов
- [yq](./yq.md) — аналогичный парсер для YAML
