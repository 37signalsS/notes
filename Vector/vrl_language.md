# VRL (Vector Remap Language)

> **Reliability Score: 10/10** (SSoT + Web Verification 2026)
> **Freshness Trigger:** Vector v0.57.0 (Июль 2026), jq-совместимые функции, оптимизация компиляции.

## Определения

**VRL (Vector Remap Language)** — предметно-ориентированный язык (DSL) с сильной типизацией, предназначенный для трансформации данных внутри Vector. 
*   **Компиляция:** VRL-скрипты компилируются в нативный код Rust на этапе запуска Vector.
*   **Безопасность:** Отсутствие сборщика мусора (GC) и строгая проверка типов исключают ошибки времени выполнения и обеспечивают предсказуемое потребление памяти.

---

## Основные концепции

### Модель обработки

VRL работает в контексте одного события (Event). Событие представлено как иерархическая структура данных (объект), доступ к полям которой осуществляется через точку:
*   `.` — текущее событие целиком.
*   `.field` — доступ к полю `field`.
*   `del(.field)` — удаление поля.
*   `@timestamp` — доступ к метаданным Vector (системные поля начинаются с `@`).

### Обработка ошибок и Fallible-функции

В VRL функции делятся на два типа:
1.  **Обычные функции:** возвращают значение.
2.  **Fallible (отказоустойчивые) функции:** могут вернуть ошибку. Обозначаются суффиксом `!`.
    *   Пример: `parse_json!(.message)` — если парсинг не удастся, Vector прервет выполнение скрипта для текущего события и отправит его в лог ошибок (или отбросит).
    *   **Безопасная обработка:** Для ручной обработки ошибок используется присваивание кортежа:
        ```vrl
        value, err = parse_json(.message)
        if err != null {
            .error = err
        }
        ```

### Возможности и лимиты (2026)

| Характеристика | Описание |
| :--- | :--- |
| **Типизация** | Строгая, выводится автоматически или задается принудительно (`string!`, `int!`). |
| **Типы данных** | String, Integer, Float, Boolean, Timestamp, Object, Array, Null. |
| **Трансформации** | Рекурсивный обход структур (`map_keys`), глубокое слияние объектов. |
| **JQ-совместимость** | Функции `to_entries`, `from_entries`, `compact` (добавлены в 2025–2026). |
| **Ограничения** | Нет циклов `for/while` (вместо них — итераторы `map_keys/values`), нет пользовательских функций, нет глобального состояния. |

### Библиотека функций (Актуально на v0.57)

| Категория | Ключевые функции |
| :--- | :--- |
| **Парсинг** | `parse_json`, `parse_syslog`, `parse_common_log`, `parse_grok`, `parse_tokens`. |
| **Кодирование** | `encode_json`, `encode_csv` (new), `encode_logfmt`. |
| **Работа с ключами** | `map_keys`, `map_values`, `to_entries`, `from_entries`. |
| **Время** | `now`, `format_timestamp`, `parse_timestamp`, `to_unix_timestamp`. |
| **Манипуляция** | `merge`, `flatten`, `compact`, `strip_whitespace`. |
| **Enrichment** | `get_enrichment_table_record` — работа с in-memory таблицами. |

---

## Практические сценарии

### Пример комплексной трансформации

```vrl
# 1. Принудительный парсинг JSON с обработкой ошибок
. = parse_json!(string!(.message))

# 2. Нормализация уровней логирования (case-insensitive)
.level = upcase(string!(.level) ?? "INFO")

# 3. Работа с JQ-совместимыми структурами (v0.56+)
# Превращаем объект labels в массив ключ-значение для специфичных sink-ов
if exists(.labels) {
    .labels_array = to_entries(.labels)
}

# 4. Рекурсивная очистка метаданных Kubernetes
if exists(.kubernetes.annotations) {
    .kubernetes.annotations = map_keys(.kubernetes.annotations, recursive: true) -> |key| {
        # Заменяем точки на подчеркивания для OpenSearch
        replace(key, ".", "_")
    }
}

# 5. Маскирование PII (Персональных данных)
if exists(.user_email) {
    .user_email = md5(string!(.user_email))
}

# 6. Удаление временных полей и метаданных
del(.internal_id)
del(.@raw)
```

Детальные примеры использования в реальных конфигурациях: **[Practical Scenarios](./practical_scenarios.md)**.

---

## Дополнительная информация

### Инструменты разработки

*   **`vector vrl`** — встроенный интерактивный REPL. Лучший способ протестировать небольшие куски кода локально.
*   **VRL Playground ([vrl.dev](https://vrl.dev))** — онлайн-инструмент для визуализации и отладки скриптов.
*   **Unit-тестирование:** Vector поддерживает нативное тестирование конфигураций через секцию `[[tests]]`, где можно проверять результаты выполнения VRL-скриптов.

### См. также
*   [Vector Overview](./vector_overview.md) — общая архитектура Vector.
*   [Practical Scenarios](./practical_scenarios.md) — применение VRL в пайплайнах Kafka и ClickHouse.
*   [Official VRL Documentation](https://vector.dev/docs/reference/vrl/) — полный справочник функций.
