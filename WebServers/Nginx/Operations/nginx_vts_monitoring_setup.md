# Настройка мониторинга Nginx с VTS-модулем, Prometheus и Grafana

## Определения

**nginx-module-vts** — это модуль для [Nginx](../Core/nginx_overview.md), который предоставляет подробную статистику в реальном времени. В отличие от стандартного `stub_status_module`, он предлагает детализированные метрики, совместимые с системами [мониторинга](../../../Concepts/Observability_and_Monitoring/observability_definitions.md) вроде [Prometheus](../../../Prometheus/overview.md).

## Основные концепции

### Архитектура решения

- **Load Balancer (Nginx)**: Принимает трафик и распределяет его на бэкенды. На нем установлен VTS-модуль для сбора метрик.
- **Backend 1 & Backend 2 (Go)**: Два идентичных Go-приложения, которые эмулируют работу бэкендов с искусственной задержкой ответа.
- **Prometheus**: Сервер для сбора, хранения и обработки метрик, получаемых от Nginx VTS-модуля.
- **Grafana**: Платформа для визуализации метрик, собранных в Prometheus.

### Как работает VTS-модуль

**nginx-module-vts** собирает метрики на уровне запросов и ответов, включая:

- Количество запросов по серверам (server zones) и апстримам (upstream groups)
- Время ответа (response time) с поддержкой гистограмм для расчета перцентилей
- Коды ответов (1xx–5xx) в разрезе каждого бэкенда
- Активные соединения и пропускную способность (bandwidth)

В отличие от встроенного `stub_status_module`, VTS предоставляет детализацию по каждому виртуальному хосту и группе апстримов, что критично для анализа производительности load balancer.

---

## Практические сценарии

### Подготовка бэкендов (Go)

Для эмуляции работы бэкендов используется простое Go-приложение, которое слушает на порту `8090` и отвечает с рандомной задержкой. Использование разных задержек на разных бэкендах (например, до 3 и до 5 секунд) позволяет наглядно увидеть разницу во времени ответа в системе мониторинга.

**Код приложения (`main.go`):**

> **Примечание:** `rand.Seed()` deprecated в Go 1.20+. В Go 1.20+ инициализация генератора происходит автоматически, вызов `rand.Seed()` можно убрать. Пример ниже совместим с Go 1.18–1.19.

```go
package main

import (
 "io"
 "log"
 "math/rand"
 "net/http"
 "time"
)

// init вызывается один раз при инициализации пакета.
func init() {
    // Инициализируем генератор случайных чисел один раз для лучшей производительности.
    // В Go 1.20+ эта строка не нужна — генератор инициализируется автоматически.
 rand.Seed(time.Now().UnixNano())
}

func root(w http.ResponseWriter, r *http.Request) {
 // Для первого бэкенда максимальная задержка 3 сек, для второго — 5.
 // Замените `3` на `5` для второго сервера.
 n := rand.Intn(3)
 time.Sleep(time.Duration(n) * time.Second)
 io.WriteString(w, "root answer")
}

func main() {
 http.HandleFunc("/", root)
 log.Fatal(http.ListenAndServe(":8090", nil))
}
```

**Процесс установки и запуска на каждом бэкенд-сервере:**

1. **Установить Go:**

    ```bash
    # Версия Go может отличаться — проверите актуальную на https://go.dev/dl/
    wget https://go.dev/dl/go1.22.linux-amd64.tar.gz
    tar -C /usr/local -xzf go1.22.linux-amd64.tar.gz
    export PATH=$PATH:/usr/local/go/bin
    ```

2. **Скомпилировать и запустить приложение:**

    ```bash
    go build main.go
    ./main
    ```

### Настройка Nginx Load Balancer

На сервере балансировщика устанавливается Nginx. Для получения SSL-сертификатов используется `acme.sh`.

#### Получение SSL-сертификата с acme.sh

1. **Установите `acme.sh`:**

    ```bash
    # Установка acme.sh (пример, актуальные команды см. в официальной документации)
    curl https://get.acme.sh | sh
    ```

2. **Выпустите сертификат:**
    Nginx должен быть настроен для прохождения проверки `http-01`. Создайте директорию для файлов проверки и выпустите сертификат.

    ```bash
    mkdir -p /opt/www/acme
    acme.sh --issue -d lbmon.kissim -w /opt/www/acme
    ```

3. **Установите сертификат в директорию Nginx:**
    Эта команда скопирует сертификаты и будет автоматически их обновлять, перезагружая Nginx.

    ```bash
    acme.sh --install-cert -d lbmon.kissim \
    --key-file       /etc/nginx/ssl/lbmon.kissim.key  \
    --fullchain-file /etc/nginx/ssl/lbmon.kissim.pem \
    --reloadcmd     "systemctl reload nginx"
    ```

#### Конфигурация Nginx

Файл конфигурации `/etc/nginx/sites-available/lbmon.conf`:

```nginx
# Определение апстрима (наших бэкендов)
upstream backend {
    # Замените на реальные IP-адреса ваших бэкендов (примеры из RFC 5737)
    server 192.0.2.1:8090;
    server 192.0.2.2:8090;
}

# Секция для HTTP и прохождения верификации Let's Encrypt
server {
    listen 80;
    server_name lbmon.kissim;

    access_log /var/log/nginx/lbmon.kissim.access.log;
    error_log /var/log/nginx/lbmon.kissim.error.log;

    # Путь для верификации acme.sh
    location /.well-known/acme-challenge/ {
        root /opt/www/acme;
    }

    # Редирект остального трафика на HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

# Основная секция для HTTPS
server {
    listen 443 ssl http2;
    server_name lbmon.kissim;

    # SSL сертификаты, установленные acme.sh
    ssl_certificate /etc/nginx/ssl/lbmon.kissim.pem;
    ssl_certificate_key /etc/nginx/ssl/lbmon.kissim.key;

    # Полезный заголовок для отладки, чтобы видеть, какой из апстримов ответил
    add_header X-Upstream $upstream_addr always;

    location / {
        proxy_pass http://backend;
    }
}
```

### Установка и настройка Nginx VTS модуля

#### Сборка Nginx с VTS-модулем из исходников

Поскольку VTS-модуль не входит в стандартную поставку Nginx, его необходимо скомпилировать вместе с Nginx. Процесс ниже описан для Ubuntu.

1. **Подготовка системы:**
    Включите репозиторий с исходным кодом в `/etc/apt/sources.list` и обновите пакеты.

    ```bash
    # Раскомментируем репозиторий с исходным кодом
    sudo sed -i -e 's/# deb-src/deb-src/' /etc/apt/sources.list
    sudo apt-get update
    ```

2. **Установка зависимостей и загрузка исходников:**
    Установите зависимости, необходимые для сборки Nginx, и скачайте его исходный код.

    ```bash
    # Устанавливаем сборочные зависимости
    sudo apt-get build-dep nginx -y

    # Создаем рабочую директорию и скачиваем исходники
    mkdir ~/nginx-build && cd ~/nginx-build
    apt-get source nginx
    ```

3. **Клонирование VTS-модуля:**

    ```bash
    git clone https://github.com/vozlt/nginx-module-vts.git
    ```

4. **Конфигурирование сборки и компиляция:**
    - Перейдите в директорию с исходниками Nginx (например, `nginx-1.18.0/`).
    - Откройте файл `debian/rules` для редактирования.
    - Найдите один из блоков с флагами для конфигурирования (например, `common_configure_flags` или `full_configure_flags`).
    - Добавьте в конец этого блока флаг для подключения VTS-модуля, указав относительный путь к нему:
        `--add-module=../nginx-module-vts`
    - Запустите сборку .deb пакета:

        ```bash
        # -b - собрать только бинарный пакет
        # -uc - не подписывать .changes файл
        # -us - не подписывать исходный код
        dpkg-buildpackage -b -uc -us
        ```

    - После успешной сборки установите сгенерированный .deb пакет, который находится в родительской директории (`~/nginx-build`):

        ```bash
        # Имя пакета может отличаться в зависимости от версии
        sudo dpkg -i ../nginx-common_*.deb ../nginx_*.deb
        ```

    **Важно:** Чтобы избежать замены вашего кастомного пакета при системном обновлении, рекомендуется изменить имя пакета в файле `debian/control` перед сборкой и/или закрепить версию пакета с помощью `apt-mark hold nginx`.

#### Настройка VTS в Nginx

Добавьте следующие директивы в ваш `nginx.conf` и конфигурацию сайта:

**В `nginx.conf` в секции `http`:**

```nginx
http {
    # ... другие директивы
    vhost_traffic_status_zone;
}
```

**В `server` блоке вашего сайта:**

```nginx
server {
    # ...
    location /status {
        vhost_traffic_status_display;
        vhost_traffic_status_display_format html;
    }
}
```

После перезагрузки Nginx, по адресу `/status` будет доступна HTML-страница со статистикой.

### Интеграция с Prometheus

VTS-модуль может отдавать метрики в формате, совместимом с [Prometheus](../../../Prometheus/overview.md).

1. **Настройте Nginx для отдачи метрик Prometheus:**
    Измените location `/status` (или создайте новый) следующим образом:

    ```nginx
    location /metrics {
        vhost_traffic_status_display;
        vhost_traffic_status_display_format prometheus;
    }
    ```

2. **Настройте Prometheus для сбора метрик:**
    Добавьте новую `job` в ваш `prometheus.yml`:

    ```yaml
    - job_name: 'nginx-vts'
      scrape_interval: 10s
      metrics_path: /metrics
      static_configs:
        - targets: ['lbmon.kissim'] # Используйте DNS имя вашего балансировщика
      scheme: https
      tls_config:
        insecure_skip_verify: true # Пропускать проверку сертификата, если он самоподписанный
    ```

### Визуализация в Grafana

1. **Добавьте Prometheus как Data Source** в [Grafana](../../../Grafana/grafana_overview.md).
2. **Найдите и импортируйте дашборд** для Nginx VTS. На официальном сайте Grafana есть несколько популярных вариантов, например, с ID `9614` или `2949`.

## Дополнительная информация

### Примеры запросов (PromQL) для Grafana

- **Количество запросов (RPS) по кодам ответа:**

    ```promql
    sum(rate(nginx_vts_server_requests_total[1m])) by (code)
    ```

- **95-й перцентиль времени ответа апстрима:**

    ```promql
    histogram_quantile(0.95, sum(rate(nginx_vts_upstream_response_time_seconds_bucket[5m])) by (le, upstream))
    ```

### Альтернативные методы мониторинга

- **`stub_status_module`**: Встроенный модуль, который предоставляет очень базовую статистику (активные соединения, общее число запросов). Он прост в настройке, но его информативности недостаточно для серьезного анализа производительности.
- **`nginx-log-exporter`**: Экспортер для Prometheus, который работает путем парсинга логов доступа (`access.log`) Nginx.
  - **Плюсы**: Не требует пересборки Nginx. Позволяет извлекать любые данные, которые можно добавить в формат лога.
  - **Минусы**: Создает дополнительную нагрузку на I/O подсистему из-за постоянного чтения лог-файлов. Может быть менее точным по сравнению с VTS при очень высоких RPS.

## Смотрите также

- [Nginx Overview](../Core/nginx_overview.md) — общий обзор Nginx
- [Other Prometheus Exporters](../../../Prometheus/Exporters/other_exporters.md) — список экспортеров, включая nginx-vts-exporter
- [Angie Monitoring](../../Angie/angie_monitoring/angie_monitoring_pro.md) — встроенный API мониторинга в Angie (форк Nginx)
