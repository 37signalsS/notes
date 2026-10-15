# yq — обработка YAML в командной строке

**Актуально для:** yq 4.40+ (Go-реализация, миксерус/yq)

`yq` — вычислитель выражений YAML, аналогичный `jq` для JSON. Использует тот же синтаксис выборок (path expressions) и поддерживает чтение/запись YAML, JSON, XML и INI-файлов.

## Базовые концепции

`yq` применяет выражение (filter) к YAML-документу и выводит результат. По умолчанию используется `eval` (можно сократить до `e`).

## Практические сценарии

### Извлечение значений

```bash
# Получить значение по ключу
yq e '.server.port' config.yaml
# → 8080

# Извлечь из массива по индексу
yq e '.items[0].name' services.yaml

# Извлечь все значения поля из массива объектов
yq e '.items[].name' services.yaml
```

### Фильтрация

```bash
# Отбор объектов по условию
yq e '.items[] | select(.status == "failed") | .id' jobs.yaml

# Подсчет элементов массива
yq e '.items | length' services.yaml
# → 5

# Сортировка массива по полю
yq e '.items | sort_by(.version)' services.yaml
```

### Трансформация данных

```bash
# Создать массив из значений поля
yq e '.items | map(.name)' services.yaml

# Альтернативный оператор (//) — значение по умолчанию
yq e '.staging_url // .prod_url' config.yaml
# Если .staging_url равно null или отсутствует, вернёт .prod_url

# Удалить ключ
yq e 'del(.deprecated_field)' config.yaml

# Обрезка вывода по пути
yq e '.metadata.namespace' k8s.yaml
```

### Обновление значений в файле (-i, in-place)

```bash
# Изменить строковое значение
yq e -i '.version = "2.0"' deployment.yaml

# Изменить числовое значение
yq e -i '.spec.replicas = 3' deployment.yaml

# Добавить элемент в массив
yq e -i '.items += [{"name": "new-item"}]' config.yaml

# Удалить элемент из массива по условию
yq e -i '.items |= filter(.name != "old-item")' config.yaml
```

## Дополнительная информация

### Сравнение с jq

| Функция | jq | yq |
| :--- | :--- | :--- |
| Язык выборок | path expressions | path expressions (совместим) |
| Формат по умолчанию | JSON | YAML + JSON |
| Запись в файл | pipe \| sponge | `-i` (in-place) |
| Объединение документов | `-s` (slurp) | `-s` (slurp) |
| Сортировка ключей вывода | `-S` | `--sort-keys` |

### См. также

- [jq — обработка JSON в командной строке](./jq.md) — аналогичный инструмент для JSON
