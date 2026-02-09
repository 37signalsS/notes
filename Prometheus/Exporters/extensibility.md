# Расширяемость экспортеров Prometheus

### Расширяемость `node_exporter`: Textfile Collector

`node_exporter` может собирать произвольные метрики, предоставляемые внешними скриптами или приложениями. Это реализуется через **`textfile` коллектор**.

*   **Принцип работы:**
    1.  Внешний скрипт (например, на Python или Bash) выполняется по расписанию (cron).
    2.  Скрипт выполняет свою логику: парсит логи, опрашивает оборудование и т.д.
    3.  Результат своей работы скрипт записывает в виде метрик в текстовый файл с расширением `.prom` в специальную директорию.
    4.  `node_exporter` автоматически читает все `.prom` файлы из этой директории и добавляет найденные в них метрики к общему выводу на `/metrics`.

#### Пример использования `textfile` коллектора

1.  **Создаем файл с метрикой:**
    ```bash
    mkdir -p /var/lib/prometheus/node-exporter/
    cat <<EOF > /var/lib/prometheus/node-exporter/custom_metric.prom
    # TYPE my_custom_metric counter
    # HELP my_custom_metric This is a custom metric.
    my_custom_metric 100
    EOF
    ```

2.  **Настраиваем `node_exporter` для чтения метрик из директории:**
    Добавляем флаг `--collector.textfile.directory` в файл с опциями.
    ```bash
    # /etc/sysconfig/node_exporter
    OPTIONS="--collector.textfile.directory=/var/lib/prometheus/node-exporter"
    ```

3.  **Перезапускаем `node_exporter`:**
    ```bash
    systemctl restart node_exporter
    ```

4.  **Проверяем:**
    ```bash
    curl -s http://localhost:9100/metrics | grep my_custom_metric
    ```
    В выводе должна появиться ваша метрика.

### Написание собственных экспортеров

Если подходящий экспортер не найден, его можно написать самостоятельно, используя клиентские библиотеки Prometheus, доступные для большинства популярных языков программирования.

#### Общие рекомендации

1.  **Именование метрик:**
    *   Нижний регистр: `[a-zA-Z0-9:_]`.
    *   Суффиксы `_sum`, `_count`, `_bucket`, `_total` зарезервированы.
    *   Префиксы `process_`, `scrape_` зарезервированы.
    *   Название должно быть понятным и содержать единицы измерения (например, `nginx_http_request_duration_seconds`).
2.  **Выбор labels:**
    *   Не используйте в лейблах слова: `region`, `zone`, `cluster`, `az`, `datacenter`, `customer` и т.д. — это задача [Service Discovery](./service_discovery_and_relabeling.md).
    *   `le` — только для гистограмм, `quantile` — только для `Summary`.
    *   Метрика должна иметь смысл при агрегации (суммировании/усреднении). Не стоит разделять `read/write` с помощью лейбла, лучше сделать две разные метрики.
3.  **Рекомендации по коду:**
    *   Получение данных должно происходить только в момент скрапинга Prometheus'ом.
    *   Не выставляйте временные метки (timestamp), это задача Prometheus.
    *   Выбирайте порт для экспортера с учетом [официального списка](https://github.com/prometheus/prometheus/wiki/Default-port-allocations).

#### Пример экспортера на языке Go

Простейший экспортер, который инкрементирует счетчик каждые 2 секунды.

1.  **Код (`example_exporter.go`):**
    ```go
    package main

    import (
            "net/http"
            "time"
            log "github.com/Sirupsen/logrus"

            "github.com/prometheus/client_golang/prometheus"
            "github.com/prometheus/client_golang/prometheus/promhttp"
            "github.com/prometheus/client_golang/prometheus/promauto"
    )

    func recordMetrics() {
            go func() {
                    for {
                            opsProcessed.Inc()
                            time.Sleep(2 * time.Second)
                    }
            }()
    }

    var (
            opsProcessed = promauto.NewCounter(prometheus.CounterOpts{
                    Name: "example_exporter_processed_ops_total",
                    Help: "The total number of processed events",
            })
    )

    func main() {
            recordMetrics()

            http.Handle("/metrics", promhttp.Handler())
            log.Info("Beginning to serve on port :2112")
            log.Fatal(http.ListenAndServe(":2112", nil))
    }
    ```

2.  **Установка зависимостей и запуск:**
    ```bash
    # Установить Go
    export GO111MODULE=auto
    go get -d -u -v github.com/prometheus/client_golang/prometheus
    go get -d -u -v github.com/Sirupsen/logrus
    go run example_exporter.go
    ```

3.  **Проверка:**
    ```bash
    curl http://localhost:2112/metrics
    ```
