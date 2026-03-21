# Шаблоны запросов PromQL

## Мониторинг инфраструктуры

* **Утилизация CPU по instance (в %):**

    ```promql
    avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100
    ```

* **Использование памяти (в %):**

    ```promql
    (1 - node_memory_mem_available_bytes / node_memory_mem_total_bytes) * 100
    ```

* **Использование диска (в %):**

    ```promql
    (1 - node_filesystem_avail_bytes / node_filesystem_size_bytes) * 100
    ```

* **Входящий сетевой трафик (байт/сек):**

    ```promql
    rate(node_network_receive_bytes_total[5m])
    ```

## Мониторинг приложений

* **Доля ошибок HTTP 5xx:**

    ```promql
    sum(rate(http_requests_total{code=~"5.."}[5m]))
    /
    sum(rate(http_requests_total[5m]))
    ```

* **95-й перцентиль времени ответа:**

    ```promql
    histogram_quantile(0.95,
      sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
    )
    ```

* **RPS (запросов в секунду):**

    ```promql
    sum(rate(http_requests_total[5m]))
    ```

## Мониторинг Kubernetes

* **Количество подов в состоянии Running:**

    ```promql
    sum(kube_pod_status_phase{phase="Running"})
    ```

* **Использование CPU контейнером (в ядрах):**

    ```promql
    rate(container_cpu_usage_seconds_total[5m])
    ```

* **Использование памяти контейнером:**

    ```promql
    container_memory_usage_bytes
    ```

## Алертинг

* **Проверка отсутствия метрики (для алертинга):**

    ```promql
    absent(up{job="my-critical-service"})
    ```

* **Сервис недоступен:**

    ```promql
    up{job="api-server"} == 0
    ```

* **Прогноз нехватки диска через 4 часа:**

    ```promql
    predict_linear(node_filesystem_free_bytes[1h], 3600 * 4) < 0
    ```

* **Высокая загрузка CPU (>80% в течение 10 минут):**

    ```promql
    avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[5m])) * 100 < 20
    ```

> **См. также:** [Rules и алертинг](../../../Kubernetes/Security/kyverno/rules.md) — создание правил для Alertmanager.

---

**Связанные темы:**

* [Функции PromQL](./functions.md) — rate, histogram_quantile, predict_linear, absent
* [Агрегация](./aggregation.md) — операторы sum, avg, irate
* [Алертинг](../../../Kubernetes/Security/kyverno/rules.md) — создание правил для Alertmanager
* [Kubernetes](../kubernetes/) — мониторинг Kubernetes
