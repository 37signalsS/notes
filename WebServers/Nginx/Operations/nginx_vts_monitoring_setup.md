# Настройка мониторинга Nginx с VTS-модулем, Prometheus и Grafana

## Определения

**nginx-module-vts (Virtual Host Traffic Status)** — сторонний модуль для **Nginx**, предоставляющий расширенную статистику о трафике в реальном времени. В отличие от стандартного модуля `stub_status`, VTS позволяет собирать метрики в разрезе виртуальных хостов (**server zones**), групп апстримов (**upstream groups**), фильтров и конкретных кэш-зон.

**Prometheus** — система мониторинга и база данных временных рядов (**TSDB — Time Series Database**), работающая по модели сбора метрик (**pull model**). Используется для хранения и обработки данных, получаемых от экспортеров или модулей Nginx.

**Grafana** — платформа для визуализации и анализа метрик. Позволяет строить интерактивные дашборды на основе данных из Prometheus и других источников.

**RPS (Requests Per Second)** — количество запросов в секунду, один из ключевых показателей производительности веб-сервера.

**95-й перцентиль (P95)** — статистический показатель, означающий, что 95% запросов были обработаны быстрее или за указанное время. Помогает выявить «хвосты» задержек (**latency**), которые не видны на средних значениях.

## Основные концепции

### Архитектура решения

Типовая схема мониторинга высоконагруженного балансировщика включает следующие компоненты:

1.  **Load Balancer (Nginx)**: Центральный узел, принимающий трафик. На нем установлен VTS-модуль для агрегации данных о каждом запросе в разделяемую память (**Shared Memory**).
2.  **Backends**: Целевые серверы приложений. Для тестирования используются эмуляторы, имитирующие задержки ответа.
3.  **Prometheus**: Регулярно опрашивает (**scrape**) эндпоинт Nginx (например, `/metrics`) и сохраняет полученные значения.
4.  **Grafana**: Запрашивает данные из Prometheus и отображает их на графиках.

### Преимущества VTS перед stub_status

Стандартный модуль `ngx_http_stub_status_module` предоставляет лишь 7 базовых метрик (активные соединения, принятые/обработанные запросы) для всего сервера без детализации по сайтам.

**nginx-module-vts** значительно расширяет возможности, фиксируя:
-   Статус-коды ответов (1xx, 2xx, 3xx, 4xx, 5xx) для каждого домена (**Server Zone**).
-   Время ответа апстримов (среднее и гистограммы задержек).
-   Объем переданного и полученного трафика (**Bandwidth**).
-   Статистику использования кэша (**Cache Hit Ratio**).
-   Фильтрацию по произвольным переменным (например, по странам через GeoIP).

> **Важно:** Модуль VTS не обновлялся активно с 2021 года. Для новых проектов рекомендуется рассматривать **[Angie](../../Angie/angie_overview.md)**, где расширенный мониторинг является нативной частью ядра и поддерживает экспорт в формате Prometheus без сторонних модулей.

## Практические сценарии

### Подготовка тестовых бэкендов (Go)

Для демонстрации работы мониторинга создадим приложение, которое отвечает с искусственной задержкой.

**Пример кода (`main.go`):**

```go
package main

import (
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"time"
)

func root(w http.ResponseWriter, r *http.Request) {
	// Имитация случайной задержки от 0 до 2 секунд
	n := rand.Intn(2000)
	time.Sleep(time.Duration(n) * time.Millisecond)
	fmt.Fprintf(w, "Backend response (latency: %dms)", n)
}

func main() {
	http.HandleFunc("/", root)
	log.Println("Starting backend on :8090...")
	if err := http.ListenAndServe(":8090", nil); err != nil {
		log.Fatal(err)
	}
}
```

### Способы установки Nginx с поддержкой VTS

#### Вариант 1: Сборка из исходного кода (Debian/Ubuntu)

1.  **Загрузка исходников и модуля**:
    ```bash
    mkdir ~/nginx-build && cd ~/nginx-build
    sudo apt-get update && sudo apt-get source nginx
    git clone https://github.com/vozlt/nginx-module-vts.git
    ```

2.  **Добавление модуля в сборку**:
    В файле `debian/rules` добавьте параметр в секцию `common_configure_flags`:
    `--add-module=../nginx-module-vts`

3.  **Компиляция и установка**:
    ```bash
    sudo apt-get build-dep nginx
    dpkg-buildpackage -b -uc -us
    sudo dpkg -i ../nginx-common_*.deb ../nginx_*.deb
    ```

#### Вариант 2: Использование Docker (быстрый старт)

Для быстрого развертывания можно использовать готовые образы или собрать свой на базе официального.

**Dockerfile:**
```dockerfile
FROM nginx:1.26 AS builder
# Установка инструментов сборки и зависимостей модуля
RUN apt-get update && apt-get install -y git build-essential libpcre3-dev zlib1g-dev
RUN git clone https://github.com/vozlt/nginx-module-vts.git /usr/src/nginx-module-vts
# ... (логика сборки динамического модуля)
```
*Примечание: в production рекомендуется использовать проверенные образы, например `bitnami/nginx`, или поддерживать собственную инфраструктуру сборки.*

### Конфигурация Nginx

Включите сбор статистики и настройте зоны памяти. Без настройки гистограмм P95/P99 не будут точными.

**В блоке `http` (`/etc/nginx/nginx.conf`):**

```nginx
http {
    # Размер зоны памяти (32Мб достаточно для ~1000 хостов)
    vhost_traffic_status_zone shared:vhost_traffic_status:32m;

    # Настройка корзин гистограмм для точного измерения Latency (в секундах)
    vhost_traffic_status_histogram_buckets 0.005 0.01 0.05 0.1 0.5 1 5 10;

    # Группировка по доменам (отключает детализацию по портам для чистоты метрик)
    vhost_traffic_status_filter_by_host on;
}
```

**Расширенная фильтрация (`set_key`):**
Позволяет собирать статистику по произвольным критериям, например по User-Agent или типу контента.
```nginx
vhost_traffic_status_filter_by_set_key $status $server_name;
```

**В блоке `server` вашего сайта:**

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://backend_upstream;
        # Исключение определенных запросов из статистики (например, от систем мониторинга)
        vhost_traffic_status_bypass $is_bot;
    }

    # Эндпоинт для сбора метрик Prometheus
    location /metrics {
        vhost_traffic_status_display;
        vhost_traffic_status_display_format prometheus;
        
        # Безопасность: доступ только для доверенных IP
        allow 127.0.0.1;
        allow 192.168.1.0/24; # Сеть мониторинга
        deny all;
    }

    # Визуальный дашборд самого модуля (HTML)
    location /status {
        vhost_traffic_status_display;
        vhost_traffic_status_display_format html;
    }
}
```

### Настройка Prometheus

Добавьте задачу в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'nginx-vts'
    scrape_interval: 15s
    static_configs:
      - targets: ['your-nginx-host:80']
    metrics_path: '/metrics'
```

### Настройка правил оповещения (Alerting)

Пример базовых алертов для `alert_rules.yml`:

```yaml
groups:
- name: nginx_alerts
  rules:
  - alert: NginxHighErrorRate
    expr: sum(rate(nginx_vts_server_requests_total{code="5xx"}[5m])) / sum(rate(nginx_vts_server_requests_total[5m])) > 0.05
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "High error rate on Nginx"
      description: "More than 5% of requests result in 5xx errors on {{ $labels.instance }}"

  - alert: NginxHighLatency
    expr: histogram_quantile(0.95, sum(rate(nginx_vts_server_response_duration_seconds_bucket[5m])) by (le)) > 2
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High Nginx latency"
      description: "P95 latency is over 2s for more than 5 minutes"
```

### Визуализация в Grafana

1.  Подключите Prometheus как **Data Source**.
2.  Импортируйте дашборд. Рекомендуемые ID:
    -   **2949** — классический дашборд для VTS.
    -   **9614** — современная версия с поддержкой гистограмм.

## Дополнительная информация

### Примеры PromQL запросов

-   **Средний RPS по всем хостам**:
    ```promql
    sum(rate(nginx_vts_server_requests_total[1m]))
    ```

-   **Доля ошибок 5xx (Error Rate)**:
    ```promql
    sum(rate(nginx_vts_server_requests_total{code="5xx"}[5m])) / sum(rate(nginx_vts_server_requests_total[5m]))
    ```

-   **95-й перцентиль задержки ответов (Latency)**:
    ```promql
    histogram_quantile(0.95, sum(rate(nginx_vts_server_response_duration_seconds_bucket[5m])) by (le))
    ```

### Решение проблем (Troubleshooting)

1.  **Ошибка `shared memory zone "vhost_traffic_status" is too small`**: Увеличьте размер зоны в `vhost_traffic_status_zone` до 64m или 128m. Это критично при большом количестве виртуальных хостов или использовании фильтров.
2.  **Метрики не появляются в Prometheus**: Проверьте `allow/deny` в блоке `location /metrics`. Убедитесь, что Prometheus может достучаться до порта Nginx. Проверьте логи Nginx на наличие ошибок доступа (403).
3.  **Отсутствие гистограмм**: Проверьте наличие директивы `vhost_traffic_status_histogram_buckets` в контексте `http`. Изменения требуют полного перезапуска или `reload` Nginx.

### Альтернативы

-   **[Angie](../../Angie/angie_overview.md)**: Нативный экспорт метрик, поддержка `prometheus` модуля «из коробки», активная разработка, поддержка HTTP/3 и расширенной статистики без сторонних зависимостей.
-   **nginx-prometheus-exporter**: Официальное решение от Nginx Inc. Не требует пересборки, но работает через `stub_status` (ограниченный набор метрик) или Nginx Plus (платная версия).

## См. также

-   **[Обзор Nginx](../Core/nginx_overview.md)** — архитектура и базовые принципы.
-   **[Мониторинг кэша Nginx](../Performance/Caching/monitoring.md)** — использование VTS для анализа эффективности кэширования.
-   **[Обзор Prometheus](../../../Prometheus/overview.md)** — основы работы с системой мониторинга.
-   **[Обзор Grafana](../../../Grafana/grafana_overview.md)** — принципы визуализации данных.
