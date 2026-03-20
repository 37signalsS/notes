# Операции с векторами в PromQL

## Сопоставление векторов

PromQL позволяет производить операции между векторами.

* **Один к одному (One-to-one)**: Операция выполняется между элементами с идентичными наборами лейблов.
* **Многие к одному (Many-to-one)**: Используются ключевые слова `group_left` или `group_right` для указания "главного" вектора, чьи лейблы сохранятся в результате.
* **Фильтрация сопоставления**:
  * `on(<label_list>)`: Указывает, по каким лейблам сопоставлять векторы.
  * `ignoring(<label_list>)`: Указывает, какие лейблы игнорировать при сопоставлении.

**Пример many-to-one с group_left:**

```promql
# Добавляем лейбл job из метрики up к метрике node_cpu_seconds_total
node_cpu_seconds_total * group_left(job) up
```

## Функции для работы с метками (Labels)

* `label_replace(v, dst_label, replacement, src_label, regex)`: Создает новую метку `dst_label` на основе `regex`, примененного к `src_label`.
* `label_join(v, dst_label, separator, src_label_1, ...)`: Объединяет значения нескольких меток в одну.

**Пример label_replace (шаблонизация URL):**

```promql
# Преобразуем /api/users/123 в /api/users/:id
label_replace(
  http_requests_total,
  "templated_path",
  "/api/users/:id",
  "path",
  "/api/users/[^/]+"
)
```

## Subqueries (подзапросы)

Subqueries позволяют применять функции диапазона к функциям instant vector:

```promql
# Среднее значение rate за последний час с шагом 5 минут
avg_over_time(rate(http_requests_total[5m])[1h:5m])

# Максимум 95-го перцентиля за день
max_over_time(
  histogram_quantile(0.95, sum(rate(http_duration_bucket[5m])) by (le))[1d:1h]
)
```

---

**Связанные темы:**

* [Типы данных](./data_types.md) — instant vector, range vector
* [Лейблы и кардинальность](./labels_and_cardinality.md) — правильное использование лейблов
* [Функции PromQL](./functions.md) — rate, histogram_quantile, avg_over_time
