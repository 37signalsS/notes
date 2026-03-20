# Summary (Сводка)

**Summary**, как и гистограмма, измеряет распределение. Однако она вычисляет квантили на стороне клиента (в экспортёре) и предоставляет их в готовом виде.

## Особенности

* Экспортирует временные ряды:
  * `{quantile="<φ>"}`: значение φ-квантиля.
  * `_sum`: общая сумма всех наблюдаемых значений.
  * `_count`: общее количество наблюдаемых событий.
* **Ключевой недостаток:** квантили, рассчитанные Summary, нельзя корректно агрегировать (например, усреднять) по нескольким инстансам.

## Примеры метрик

* `grpc_server_handling_seconds{quantile="0.5",grpc_method="GetUser"}`
* `grpc_server_handling_seconds{quantile="0.99",grpc_method="GetUser"}`

## Пример PromQL для Summary

```promql
# 99-й перцентиль (уже вычислен на клиенте, нельзя агрегировать)
grpc_server_handling_seconds{quantile="0.99"}

# Среднее время ответа
sum(rate(grpc_server_handling_seconds_sum[5m]))
/
sum(rate(grpc_server_handling_seconds_count[5m]))
```

---

**Связанные темы:**

* [Histogram](./histogram.md) — гистограммы с корзинами
* [Histogram vs Summary](./histogram_vs_summary.md) — сравнение и выбор
* [Агрегация Summary](./percentiles.md#агрегация-summary-проблема-и-решение) — проблема и решение
* [Перцентили](./percentiles.md) — теория и вычисление
