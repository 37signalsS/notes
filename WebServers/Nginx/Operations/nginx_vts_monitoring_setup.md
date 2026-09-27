# Настройка мониторинга Nginx с VTS-модулем, Prometheus и Grafana

## Определения

**nginx-module-vts (Virtual Host Traffic Status)** — сторонний модуль для **Nginx**, предоставляющий расширенную статистику о трафике в реальном времени. В отличие от стандартного модуля `stub_status`, VTS позволяет собирать метрики в разрезе виртуальных хостов (**server zones**), групп апстримов (**upstream groups**), фильтров и конкретных кэш-зон.

**Prometheus** — система мониторинга и база данных временных рядов (**TSDB — Time Series Database**), работающая по модели сбора метрик (**pull model**). Используется для хранения и обработки данных, получаемых от экспортеров или модулей Nginx.

**Grafana** — платформа для визуализации и анализа метрик. Позволяет строить интерактивные дашборды на основе данных из Prometheus и других источников.

**RPS (Requests Per Second)** — количество запросов в секунду, один из ключевых показателей производительности веб-сервера.

**95-й перцентиль (P95)** — статистический показатель, означающий, что 95% запросов были обработаны быстрее или за указанное время. Помогает выявить «хвосты» задержек (**latency**), которые не видны на средних значениях.

**MTTR (Mean Time To Repair)** — среднее время восстановления сервиса после инцидента. В контексте мониторинга Nginx инциденты (падение worker-процессов, неверная конфигурация, нехватка ресурсов) напрямую влияют на MTTR, поэтому наличие runbook'ов и автоматизированных проверок является обязательным для SRE-практик.

**Runbook** — пошаговая инструкция для оператора/SRE по реагированию на типичный инцидент. Runbook включает команды диагностики, критерии escalation и шаги отката конфигурации.

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

**Запуск и проверка:**
```bash
go run main.go &
# → Starting backend on :8090...

curl -s http://localhost:8090/
# → Backend response (latency: 1234ms)
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

#### Вариант 2: Сборка динамического модуля через Docker

Для изолированной сборки динамического модуля под существующий **Nginx** используется multi-stage сборка. Этот подход гарантирует совпадение версий и флагов компиляции.

**Dockerfile:**
```dockerfile
FROM nginx:1.26 AS builder

# Установка инструментов сборки, точно соответствующих версии Nginx
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpcre3-dev \
    zlib1g-dev \
    libssl-dev \
    wget \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Получение исходников той же версии, что и в базовом образе
ARG NGINX_VERSION=1.26.1
RUN wget -qO- https://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz | tar xz

# Клонирование и сборка VTS как динамического модуля
RUN git clone https://github.com/vozlt/nginx-module-vts.git \
 && cd nginx-${NGINX_VERSION} \
 && ./configure \
      --with-compat \
      --add-dynamic-module=../nginx-module-vts \
 && make modules

# Финальный образ: только готовый модуль и Nginx
FROM nginx:1.26
COPY --from=builder /nginx-1.26.1/objs/ngx_http_vhost_traffic_status_module.so /etc/nginx/modules/
RUN echo 'load_module modules/ngx_http_vhost_traffic_status_module.so;' > /etc/nginx/modules.conf
```

**Сборка и запуск:**
```bash
docker build -t nginx-vts .
docker run -d -p 80:80 -p 9113:9113 nginx-vts
```

> **Примечание:** В production рекомендуется использовать проверенные внутренние образы или поддерживать собственную инфраструктуру сборки с контролем целостности артефактов.

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

**Валидация конфигурации и применение:**
```bash
# Проверка синтаксиса перед применением
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Атомарный reload без потери соединений
sudo systemctl reload nginx
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

## Операции и команды

### Управление конфигурацией Nginx

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `nginx -t` | Проверка синтаксиса конфигурации | `nginx: the configuration file ... syntax is ok` |
| `nginx -T` | Вывод полной объединенной конфигурации | Длинный вывод с объединенными `include` |
| `systemctl reload nginx` | Атомарный reload (SIGHUP) | Нет вывода, master перечитывает конфиг |
| `systemctl restart nginx` | Полный перезапуск | Разрыв соединений, создание новых процессов |
| `nginx -s reopen` | Переоткрытие логов | Нет вывода |

### Диагностика модуля VTS

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `curl -s http://localhost/metrics` | Проверка эндпоинта метрик | Текст в формате Prometheus с префиксом `nginx_vts_` |
| `curl -s http://localhost/status` | Визуальный HTML-дашборд VTS | HTML-страница с таблицами по серверам |
| `pmap -x $(cat /run/nginx.pid) \| grep vhost_traffic` | Проверка размера разделяемой памяти | Число, соответствующее размеру зоны (например, `33554432` для 32m) |
| `nginx -V 2\>&1 \| grep vts` | Проверка, что модуль скомпилирован | `--add-module=../nginx-module-vts` или загрузка `.so` |

### Мониторинг через Prometheus

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `promtool check rules alert_rules.yml` | Валидация правил алертов | `Checking alert_rules.yml` + `SUCCESS` или ошибки |
| `curl -s http://prometheus:9090/api/v1/targets` | Проверка активных таргетов | JSON со статусом `up` для `nginx-vts` |
| `promtool query instant http://prometheus:9094 'up{job="nginx-vts"}'` | Проверка доступности таргета | Вектор с меткой `value="1"` |

### Резервное копирование и откат

| Команда | Описание |
| :--- | :--- |
| `cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak.$(date +%Y%m%d%H%M%S)` | Бэкап конфигурации перед изменением |
| `cp -a /etc/nginx/conf.d/ /etc/nginx/conf.d.bak.$(date +%Y%m%d%H%M%S)` | Бэкап виртуальных хостов |
| `nginx -t && cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.new && mv /etc/nginx/nginx.conf.new /etc/nginx/nginx.conf` | Атомарное обновление: проверка → запись во временный файл → переименование |

> **Важно:** Прямое редактирование `nginx.conf` без предварительного `nginx -t` и атомарного `mv` является антипаттерном. При ошибке конфигурации `reload` не применится, но старый файл останется на месте.

## Устранение неисправностей

### Ошибка `shared memory zone "vhost_traffic_status" is too small`

**Причина:** Недостаточный размер зоны `vhost_traffic_status_zone` для количества виртуальных хостов или сложности фильтров.

**Решение:** Увеличьте размер зоны до 64m или 128m.
```bash
# В nginx.conf:
vhost_traffic_status_zone shared:vhost_traffic_status:64m;

# Проверка и применение:
nginx -t && systemctl reload nginx
```

### Метрики не появляются в Prometheus

**Причина:** Ошибки доступа к эндпоинту или отсутствие модуля VTS в конфигурации.

**Диагностика:**
```bash
# Проверка доступности извне (с хоста Prometheus)
curl -s -o /dev/null -w "%{http_code}" http://nginx-host/metrics
# → 200 (успех) или 403 (блокировка IP)

# Проверка логов Nginx на предмет 403
sudo journalctl -u nginx --since "5 minutes ago" | grep "access forbidden"
```

**Решение:**
- Убедитесь, что IP Prometheus указан в `allow` для `location /metrics`.
- Проверьте, что модуль VTS загружен: `nginx -V 2>&1 | grep vts`.

### Отсутствие гистограмм

**Причина:** Директива `vhost_traffic_status_histogram_buckets` отсутствует в контексте `http`.

**Решение:**
```bash
# В nginx.conf в блоке http:
vhost_traffic_status_histogram_buckets 0.005 0.01 0.05 0.1 0.5 1 5 10;

# Применение (полный reload требуется при изменении buckets)
nginx -t && systemctl reload nginx
```

### High Memory Usage (Shared Memory)

**Причина:** Слишком большой размер зоны `vhost_traffic_status_zone` или утечка в модуле.

**Диагностика:**
```bash
# Проверка RSS процесса Nginx
ps -o pid,rss,cmd -C nginx | grep master
# →  1234  125680 nginx: master process /usr/sbin/nginx

# Сравнение с размером зоны (32m = 33554432 байт ≈ 32 MiB)
```

**Решение:**
- Снизьте размер зоны, если количество хостов небольшое.
- Проверьте наличие утечек в ошибках `error.log`.

## Рекомендации и лучшие практики

### Безопасность эндпоинта /metrics

-   Никогда не делайте `/metrics` публично доступным без аутентификации.
-   Используйте `allow/deny` для ограничения доступа только IP систем мониторинга.
-   В high-security средах используйте взаимный TLS (mTLS) между Prometheus и Nginx.

### Размер разделяемой памяти

-   Начните с `32m` при количестве виртуальных хостов до 1000.
-   Увеличивайте до `64m` или `128m` при использовании фильтров (`set_key`) или большом количестве хостов.
-   Мониторьте RSS процесса Nginx: зона VTS выделяется из Shared Memory и учитывается в памяти.

### Частота сбора (Scrape Interval)

-   Рекомендуемый `scrape_interval` для VTS: `15s` — баланс между детализацией и нагрузкой.
-   Для высоконагруженных систем с жесткими требованиями к latency используйте `5s` или `10s`, но учитывайте рост объема данных в Prometheus.
-   Избегайте интервалов меньше `5s` без необходимости: это создает избыточную нагрузку на Nginx и Prometheus.

### Атомарность обновлений

-   Всегда используйте `nginx -t` перед `reload`.
-   Для изменения конфигурации применяйте паттерн: `cp → nginx -t → mv`.
-   Храните конфигурацию в VCS (Git), деплойте через CI/CD с автоматической валидацией.

### Резервное копирование

-   Бэкапьте `/etc/nginx/` перед каждым изменением.
-   Храните бэкапы минимум 7 дней или интегрируйте с системой управления конфигурациями.
-   Тестируйте процедуру отката: `cp backup.conf nginx.conf && systemctl reload nginx`.

### Алертинг и MTTR

-   Настройте алерты на P95 latency, error rate (5xx) и RPS.
-   Используйте успокоение (`for: 2m`) для подавления flapping.
-   Ведите runbook для типичных инцидентов VTS: проверка shared memory, валидация конфигурации, restart vs reload.

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

### Альтернативы

-   **[Angie](../../Angie/angie_overview.md)**: Нативный экспорт метрик, поддержка `prometheus` модуля «из коробки», активная разработка, поддержка HTTP/3 и расширенной статистики без сторонних зависимостей.
-   **nginx-prometheus-exporter**: Официальное решение от Nginx Inc. Не требует пересборки, но работает через `stub_status` (ограниченный набор метрик) или Nginx Plus (платная версия).

## См. также

-   **[Обзор Nginx](../Core/nginx_overview.md)** — архитектура и базовые принципы работы.
-   **[Диагностика веб-серверов](../../Concepts/webserver_troubleshooting.md)** — общая методология поиска неисправностей.
