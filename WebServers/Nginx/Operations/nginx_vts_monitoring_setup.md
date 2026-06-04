# Настройка мониторинга Nginx с VTS-модулем, Prometheus и Grafana

## Определения

**nginx-module-vts (Virtual Host Traffic Status)** — сторонний модуль для **Nginx**, предоставляющий расширенную статистику о трафике в реальном времени. В отличие от стандартного модуля `stub_status`, VTS позволяет собирать метрики в разрезе виртуальных хостов (**server zones**), групп апстримов (**upstream groups**) и конкретных кэш-зон.

**Prometheus** — система мониторинга и база данных временных рядов (**TSDB — Time Series Database**), работающая по модели сбора метрик (**pull model**). Используется для хранения и обработки данных, получаемых от экспортеров или модулей Nginx.

**Grafana** — платформа для визуализации и анализа метрик. Позволяет строить интерактивные дашборды на основе данных из Prometheus и других источников.

**RPS (Requests Per Second)** — количество запросов в секунду, один из ключевых показателей производительности веб-сервера.

**95-й перцентиль (P95)** — статистический показатель, означающий, что 95% запросов были обработаны быстрее или за указанное время. Помогает выявить "хвосты" задержек (**latency**), которые не видны на средних значениях.

## Основные концепции

### Архитектура решения

Типовая схема мониторинга высоконагруженного балансировщика включает следующие компоненты:

1. **Load Balancer (Nginx)**: Центральный узел, принимающий трафик. На нем установлен VTS-модуль для агрегации данных о каждом запросе.
2. **Backends**: Целевые серверы приложений. Для тестирования часто используются эмуляторы на языке **Go**, имитирующие задержки ответа.
3. **Prometheus**: Регулярно опрашивает (**scrape**) эндпоинт Nginx (например, `/metrics`) и сохраняет полученные значения.
4. **Grafana**: Запрашивает данные из Prometheus и отображает их на графиках.

### Преимущества VTS перед stub_status

Стандартный модуль `ngx_http_stub_status_module` предоставляет лишь 7 базовых метрик (активные соединения, принятые/обработанные запросы и т.д.) для всего сервера.

**nginx-module-vts** значительно расширяет возможности, фиксируя:

- Статус-коды ответов (1xx, 2xx, 3xx, 4xx, 5xx) для каждого домена.
- Время ответа апстримов (среднее, гистограммы).
- Объем переданного и полученного трафика (**bandwidth**).
- Статистику использования кэша (**cache hit ratio**).

Все метрики доступны в формате Prometheus из коробки, что исключает необходимость использования дополнительных экспортеров.

## Практические сценарии

### Подготовка тестовых бэкендов (Go)

Для демонстрации работы мониторинга создадим простое приложение, которое отвечает с искусственной задержкой.

**Пример кода (`main.go`):**

```go
package main

import (
 "io"
 "log"
 "math/rand"
 "net/http"
 "time"
)

func root(w http.ResponseWriter, r *http.Request) {
 // Имитация разной задержки для разных серверов (например, 3 или 5 секунд)
 n := rand.Intn(3) 
 time.Sleep(time.Duration(n) * time.Second)
 io.WriteString(w, "Backend response")
}

func main() {
 http.HandleFunc("/", root)
 log.Printf("Starting backend on :8090...")
 log.Fatal(http.ListenAndServe(":8090", nil))
}
```

Запуск приложения:

```bash
go build -o backend main.go
./backend
```

### Сборка Nginx с поддержкой VTS

Модуль VTS не входит в официальные репозитории и требует компиляции Nginx из исходного кода.

1. **Загрузка исходников и модуля**:

    ```bash
    mkdir ~/nginx-build && cd ~/nginx-build
    apt-get source nginx
    git clone https://github.com/vozlt/nginx-module-vts.git
    ```

2. **Добавление модуля в сборку**:
    В файле `debian/rules` добавьте параметр в секцию `common_configure_flags`:
    `--add-module=../nginx-module-vts`

3. **Компиляция и установка**:

    ```bash
    # Сборка пакета без подписи
    dpkg-buildpackage -b -uc -us
    # Установка полученных пакетов
    sudo dpkg -i ../nginx-common_*.deb ../nginx_*.deb
    ```

### Конфигурация Nginx

Включите сбор статистики в основном файле конфигурации и настройте эндпоинт для Prometheus.

**В блоке `http` (`/etc/nginx/nginx.conf`):**

```nginx
http {
    vhost_traffic_status_zone;
    # ...
}
```

**В блоке `server` вашего сайта:**

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://backend_upstream;
    }

    # Эндпоинт для сбора метрик Prometheus
    location /metrics {
        vhost_traffic_status_display;
        vhost_traffic_status_display_format prometheus;
        
        # Ограничение доступа по IP для безопасности
        allow 127.0.0.1;
        allow 192.168.1.0/24; # Сеть Prometheus
        deny all;
    }

    # Визуальный интерфейс VTS (опционально)
    location /status {
        vhost_traffic_status_display;
        vhost_traffic_status_display_format html;
    }
}
```

### Настройка Prometheus

Добавьте задачу по сбору метрик в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'nginx-vts'
    scrape_interval: 10s
    static_configs:
      - targets: ['your-nginx-host:80']
    metrics_path: '/metrics'
```

### Визуализация в Grafana

1. Подключите Prometheus как источник данных (**Data Source**).
2. Импортируйте готовый дашборд. Рекомендуемые ID сообщества:
    - **2949** (Nginx VTS Stats)
    - **9614** (NGINX VTS Dashboard)

## Дополнительная информация

### Примеры PromQL запросов

- **Общий RPS сервера**:

    ```promql
    sum(rate(nginx_vts_server_requests_total[1m]))
    ```

- **Количество 5xx ошибок в разрезе апстримов**:

    ```promql
    sum(rate(nginx_vts_upstream_requests_total{code="5xx"}[5m])) by (upstream)
    ```

- **95-й перцентиль задержки ответов**:

    ```promql
    histogram_quantile(0.95, sum(rate(nginx_vts_upstream_response_time_seconds_bucket[5m])) by (le))
    ```

### Альтернативные подходы

- **nginx-log-exporter**: Парсит `access.log` и преобразует записи в метрики. Не требует пересборки Nginx, но создает нагрузку на диск и может иметь задержки при больших объемах логов.
- **stub_status + nginx-exporter**: Официальное решение, но с очень ограниченным набором данных (нет статус-кодов и апстримов).
- **Angie**: Современный форк Nginx, включающий расширенный API мониторинга (аналог Nginx Plus) в Open Source версии. Подробнее: **[Мониторинг Angie](../../Angie/angie_monitoring/angie_monitoring_pro.md)**.

## См. также

- **[Обзор Nginx](../Core/nginx_overview.md)** — архитектура и базовые принципы.
- **[Мониторинг кэша Nginx](../Performance/Caching/monitoring.md)** — использование VTS для анализа эффективности кэширования.
- **[Обзор Prometheus](../../../Prometheus/overview.md)** — основы работы с системой мониторинга.
- **[Обзор Grafana](../../../Grafana/grafana_overview.md)** — принципы визуализации данных.
