# VRL (Vector Remap Language)

## Определения

**VRL (Vector Remap Language)** — предметно-ориентированный язык (DSL) для трансформации данных в Vector. Компилируется в нативный код Rust — высокая производительность, безопасность, отсутствие GC.

---

## Основные концепции

### Возможности

**Трансформация событий:**

- Парсинг структурированных данных (JSON, syslog, logfmt, regex)
- Преобразование типов данных
- Создание, удаление, переименование полей

**Фильтрация и маршрутизация:**

- Булевы выражения для условий
- Проверка существования полей (`exists(.field)`)

### Библиотека функций

| Категория | Функции |
| :--- | :--- |
| **Парсинг** | `parse_json!()`, `parse_syslog!()`, `parse_key_value!()`, `parse_regex!()` |
| **Время** | `now()`, `parse_timestamp()`, `to_unix_timestamp()`, `strftime()` |
| **Строки** | `downcase()`, `upcase()`, `split()`, `replace()`, `trim()` |
| **Когерция типов** | `string!()`, `to_int()`, `to_bool()` |
| **Коллекции** | `map_keys()`, `map_values()`, `recursive: true` |

### Характеристики

| Характеристика | Описание |
| :--- | :--- |
| **Безопасность** | Проверка типов на этапе компиляции, явная обработка ошибок |
| **Производительность** | Компиляция в Rust, нет GC, нет FFI-накладных расходов |
| **Stateless** | Каждое событие обрабатывается независимо |
| **Ограничения** | Нет пользовательских функций, нет рекурсии, нет состояния между событиями |

Ограничения намеренные — обеспечивают безопасность, предсказуемость и высокую производительность.

### Пример VRL-скрипта

```vrl
# Парсинг JSON из поля message
. = parse_json!(string!(.message))

# Обработка timestamp с fallback
parsed_timestamp, err = parse_timestamp(.timestamp, format: "%Y-%m-%dT%H:%M:%S.%fZ")
if err == null {
  .timestamp = to_unix_timestamp(parsed_timestamp)
} else {
  .timestamp = to_unix_timestamp(now())
}

# Рекурсивная замена точек в ключах (для Elasticsearch/OpenSearch)
if exists(.kubernetes.annotations) {
  .kubernetes.annotations = map_keys(.kubernetes.annotations, recursive: true) -> |key| {
    replace(key, ".", "_")
  }
}

# Удаление ненужных полей
del(.p)
del(@timestamp)

# Преобразование строки
.message = downcase(string!(.message))
```

---

## Практические сценарии

Практические примеры использования VRL в конфигурациях Vector описаны в **[Practical Scenarios](./practical_scenarios.md)**:

- Парсинг JSON из Kafka и замена точек в K8s-метаданных ([подробнее](./practical_scenarios.md#практический-сценарий-роутер-логов-из-kafka-в-opensearch))
- Обогащение логов GeoIP через enrichment tables ([подробнее](./practical_scenarios.md#практический-сценарий-обогащение-логов-geoip))

---

## Дополнительная информация

**Инструменты:**

- [VRL Playground](https://vrl.dev) — онлайн-песочница для тестирования скриптов
- [VSCode Extension](https://marketplace.visualstudio.com/items?itemName=oryanp.vscode-vrl) — подсветка синтаксиса и автодополнение

**Связанные заметки:**

- [Vector Overview](./vector_overview.md) — общий обзор Vector
- [Practical Scenarios](./practical_scenarios.md) — практические сценарии с конфигурациями
