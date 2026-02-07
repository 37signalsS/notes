# Экспортеры Prometheus

## Определения

*   **Экспортер (Exporter)** — это программа, которая собирает метрики из сторонней системы и преобразует их в формат, понятный [[./overview.md|Prometheus]]. Экспортеры действуют как "переводчики" или "адаптеры" между Prometheus и системой, которую необходимо мониторить.

*   **Процесс экспозиции (Exposition)** — это процесс предоставления данных для Prometheus. Prometheus собирает данные по HTTP протоколу, в формате plain text c кодировкой UTF-8. Начиная с версии 0.4.0 это единственный способ (ранее был доступен Protobuf).

## Базовые концепции

### Принцип работы экспортера

1.  Экспортер запрашивает данные у целевой системы (например, у базы данных или у операционной системы).
2.  Он преобразует полученные данные в текстовый формат метрик Prometheus.
3.  Экспортер открывает HTTP-эндпоинт (обычно `/metrics`), по которому Prometheus может забрать (scrape) эти метрики.

Экспортер не хранит метрики и не знает о существовании Prometheus. Он просто постоянно парсит данные и отдает их по запросу. Как часто Prometheus будет приходить за этими данными, настраивается в его [[./configuration.md|конфигурации]] (`scrape_interval`).

### Формат данных Prometheus

Prometheus собирает данные по HTTP протоколу, в формате plain text c кодировкой UTF-8.

*   **Комментарии:** Для комментариев используется `#`.
*   **HELP и TYPE:** Строки, начинающиеся с `# HELP` и `# TYPE`, являются зарезервированными.
    *   `# HELP <metric_name> <description>`: Описание метрики.
    *   `# TYPE <metric_name> <type>`: Указывает [[./concepts/metric_types.md|тип метрики]] (`counter`, `gauge`, `histogram`, `summary`). Эта строка должна быть объявлена до первого использования метрики.
*   **Формат метрики:**
    ```
    metric_name{label_name="label_value"} value timestamp
    ```
    `timestamp` является опциональным.

### Источники метрик для Prometheus

1.  **Exporters:** Сторонние приложения, которые собирают метрики из существующих источников (например, Nginx, PostgreSQL, ОС Linux) и отдают их в понятном для Prometheus виде. Существует большое количество официальных и поддерживаемых сообществом экспортеров.
2.  **Клиентские библиотеки для кастомных экспортеров:** Если подходящий экспортер не найден, его можно написать самостоятельно, используя готовые библиотеки для большинства современных языков программирования.
3.  **Прямая инструментация:** Встроить процесс экспозиции метрик прямо в код своего приложения, также с помощью клиентских библиотек.

### Нативная инструментация: лучший экспортер — его отсутствие

Идеальная ситуация — когда приложению или системе не нужен отдельный экспортер. Это возможно, если приложение **само умеет отдавать метрики** в формате Prometheus. Такой подход называется **нативной инструментацией (native instrumentation)**.

*   **Преимущества:**
    *   **Надежность и точность:** Метрики генерируются непосредственно из кода.
    *   **Детализация бизнес-логики:** Можно собирать уникальные метрики, недоступные извне.
    *   **Упрощение архитектуры:** Не нужно развертывать и обслуживать дополнительный компонент.
*   **Опасность чрезмерной инструментации:** Не стоит увлекаться и превращать мониторинг в трассировку, создавая метрики с высокой [[./concepts/labels_and_cardinality.md|кардинальностью]] (например, с `request_id` в лейблах). Это ведет к разрастанию TSDB и деградации производительности. Для отслеживания отдельных запросов существуют системы трассировки (например, [[../Jaeger/jaeger_overview.md|Jaeger]] или [[../OpenTelemetry/opentelemetry_overview.md|OpenTelemetry]]). Подробнее см. в [[./concepts/labels_and_cardinality.md]].

### Высокая доступность и отказоустойчивость экспортеров

Экспортеры, как правило, являются легковесными, **stateless** приложениями. Обеспечение их высокой доступности (например, запуск нескольких реплик) считается избыточным.

Вместо этого применяются следующие стратегии:

*   **Алертинг на недоступность таргета:** Самое важное — знать, что экспортер не работает. В Prometheus есть встроенная метрика `up`, которая автоматически становится `0` для недоступного таргета. Настройка алерта `up == 0` является обязательной практикой. Подробнее см. в [[./alertmanager.md|Alertmanager]] и [[./rules.md|Правила оповещений]].
*   **Использование параллельных систем:** Для расследования инцидентов, произошедших во время недоступности экспортера, используются другие системы: логирование (ELK, Loki) или другие утилиты мониторинга (например, [atop](../Linux/Diagnostics/Performance/atop.md)).

## Практические сценарии

### Популярные экспортеры

#### `node_exporter`

Один из самых распространенных экспортеров, и часто один из первых, с которым знакомятся пользователи Prometheus. Он собирает метрики с хост-машины (сервера), предоставляя детальный ресурсный мониторинг.

*   **Собираемые метрики:** загрузка CPU, использование оперативной памяти, информация о жёстких дисках (включая I/O), сетевая активность и многое другое.
*   **Источник данных:** `node_exporter` не обращается напрямую к ядру. Он читает и парсит файлы из виртуальных файловых систем Linux, таких как [[../Linux/FileSystems/virtual_fs_proc.md|/proc]] и [[../Linux/FileSystems/virtual_fs_sys.md|/sys]]. Например, для получения информации о памяти он читает `/proc/meminfo`.
*   **Совместимость с ОС:** `node_exporter` предназначен исключительно для операционных систем на базе Linux. Для мониторинга Windows систем используется `wmi_exporter`.
*   **Веб-интерфейс:** `node_exporter` по умолчанию доступен на порту `9100`. При обращении к `http://<node_exporter_ip>:9100/metrics` отображается страница со всеми экспортируемыми метриками.

#### `cAdvisor` (Container Advisor)

Предоставляет метрики о запущенных контейнерах. Он позволяет отслеживать потребление ресурсов (CPU, память, сеть, I/O) для каждого контейнера. `cAdvisor` является неотъемлемой частью мониторинга в средах [[../Docker/docker_overview.md|Docker]] и [[../Kubernetes/kubernetes_overview.md|Kubernetes]]. Подробнее об интеграции можно почитать в заметке [[../Docker/Docker_metrics/docker_prometheus_integration.md|Интеграция Docker и Prometheus]].

#### `blackbox_exporter`

В отличие от экспортеров, которые собирают *внутренние* метрики системы (whitebox), `blackbox_exporter` предназначен для мониторинга систем *снаружи*, с точки зрения пользователя (blackbox). Он позволяет проверять доступность и работоспособность эндпоинтов по сети и должен запускаться отдельно от наблюдаемого сервиса.

*   **Назначение:** Проверка эндпоинтов с использованием различных протоколов: HTTP(S), TCP, ICMP, DNS. Например, можно проверить, что веб-сайт возвращает код `200 OK`, что SSL-сертификат действителен или что TCP-порт открыт.

*   **Принцип работы:** `blackbox_exporter` работает по особому принципу. Prometheus опрашивает не целевую систему (например, `google.com`), а сам `blackbox_exporter` (на его эндпоинте `/probe`), передавая ему целевой адрес в качестве параметра (`?target=...`). Остальная логика проверок настраивается в конфигурации самого экспортера.
    1.  Prometheus делает запрос к `http://blackbox-exporter:9115/probe?target=google.com&module=http_2xx`.
    2.  `blackbox_exporter` получает этот запрос, выполняет проверку цели `google.com` согласно правилам модуля `http_2xx`.
    3.  Он возвращает Prometheus'у метрики о результатах проверки: `probe_success` (1 или 0), `probe_duration_seconds` (длительность проверки) и другие.

> **Замечания из лекции:**
> *   При проверке URL в браузере стоит помнить, что по пути `/metrics` `blackbox_exporter` отдает метрики о своей работе, а не результаты проверок. Результаты проверок доступны по пути `/probe`.
> *   Ошибка `network is unreachable` при проверке IPv6-адреса (`[2606:4700:...]`) указывает на то, что на хосте не настроена маршрутизация для IPv6.

### Настройка Prometheus для Blackbox Exporter

```yaml
scrape_configs:
  - job_name: 'blackbox'
    metrics_path: /probe # Указываем путь /probe
    params:
      module: [http_2xx] # Передаем имя модуля как параметр
    static_configs:
      - targets:
        - "http://prometheus.io" # В targets указываем НЕ blackbox-exporter, а ЦЕЛЬ для проверки
        - "https://google.com"
    relabel_configs:
      # 1. Копируем адрес цели (из targets) в параметр __param_target
      - source_labels: [__address__]
        target_label: __param_target
      # 2. Копируем __param_target в лейбл instance для красивого отображения
      - source_labels: [__param_target]
        target_label: instance
      # 3. Подменяем адрес для скрайпинга на адрес самого blackbox_exporter
      - target_label: __address__
        replacement: 127.0.0.1:9115
```
Подробнее о relabeling см. в [[./service_discovery_and_relabeling.md]].

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
    *   Не используйте в лейблах слова: `region`, `zone`, `cluster`, `az`, `datacenter`, `customer` и т.д. — это задача [[./service_discovery_and_relabeling.md|Service Discovery]].
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

## Дополнительная информация

### Другие популярные экспортеры

Существуют экспортеры практически для всего:

*   Базы данных (`mysqld_exporter`, `postgres_exporter`). См. [MySQL](../Databases/MySQL/overview.md), [PostgreSQL](../Databases/PostgreSQL/overview.md).
*   Веб-серверы (`nginx-prometheus-exporter`).
*   Брокеры сообщений (`rabbitmq_exporter`, `kafka_exporter`). См. [[../Kafka/kafka_for_monitoring.md]].
*   И даже для экзотических систем, таких как 1С.

### Ключи запуска `node_exporter`

| Ключ | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| `--log.level` | `info` | Уровень логирования (`debug`, `info`, `warn`, `error`). |
| `--log.format` | `logfmt` | Формат логов (`logfmt`, `json`). |
| `--web.listen-address` | `":9100"` | Адрес и порт, который будет слушать `node_exporter`. |
| `--web.telemetry-path` | `"/metrics"` | URI, по которому будут доступны метрики. |
| `--web.disable-exporter-metrics` | `-` | Список метрик для исключения из экспозиции (например, `go_*`). |

### Настройка модулей `blackbox_exporter`

Конфигурационный файл `blackbox.yml` содержит `modules`. Каждый модуль описывает, как выполнять проверку (`prober`) и ее параметры.

**Общая структура:**
```yaml
modules:
  http_2xx: # Имя модуля
    prober: http # Тип проверки: http, tcp, icmp, dns
    timeout: 5s
    http:
      valid_status_codes: [200]
      preferred_ip_protocol: "ip4"
```

*   **ICMP (ping):**
    ```yaml
    icmp_default:
      prober: icmp
      timeout: 5s
      icmp:
        preferred_ip_protocol: "ip4"
    ```
    Проверка: `curl "localhost:9115/probe?module=icmp_default&target=google.com"`

*   **DNS:**
    ```yaml
    dns_default:
      prober: dns
      timeout: 5s
      dns:
        query_name: "prometheus.io"
        preferred_ip_protocol: "ip4"
    ```
    Проверка: `curl "localhost:9115/probe?module=dns_default&target=8.8.8.8"`

*   **TCP:**
    ```yaml
    tcp_ssh_banner:
      prober: tcp
      timeout: 5s
      tcp:
        query_response:
          - expect: "^SSH-2.0-"
        preferred_ip_protocol: "ip4"
    ```
    Проверка: `curl "localhost:9115/probe?module=tcp_ssh_banner&target=127.0.0.1:22"`

*   **HTTP:**
    ```yaml
    http_2xx:
      prober: http
      timeout: 5s
      http:
        valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
        valid_status_codes: [200] # Проверка на 200 OK
        method: GET
        fail_if_body_not_matches_regexp:
          - "Prometheus" # Проверка наличия слова в теле ответа
    ```
    Проверка: `curl "localhost:9115/probe?module=http_2xx&target=http://prometheus.io"`