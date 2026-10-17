# Настройка мониторинга Nginx с VTS-модулем, Prometheus и Grafana

**Актуально для:** Nginx 1.26.x (Stable) / 1.27.x (Mainline), nginx-module-vts 0.2.x, Prometheus 3.x, Grafana 11.x

---

## Определения

**nginx-module-vts (Virtual Host Traffic Status)** — сторонний модуль для веб-сервера **Nginx**, предоставляющий расширенную статистику о сетевом трафике в реальном времени. В отличие от стандартного модуля `stub_status`, VTS агрегирует метрики в разрезе виртуальных хостов (**server zones**), групп апстримов (**upstream groups**), фильтров по произвольным переменным и кэш-зон.

**Shared Memory (Разделяемая память / shm)** — сегмент оперативной памяти межпроцессного взаимодействия (IPC), разделяемый между всеми worker-процессами Nginx через механизм `mmap` и управляемый slab-аллокатором. В VTS разделяемая память используется для потокобезопасного хранения красно-черного дерева (rbtree) со счетчиками и гистограммами.

**Prometheus** — система мониторинга и база данных временных рядов (**TSDB — Time Series Database**), работающая по модели сбора метрик (**pull model**). Регулярно опрашивает настроенные HTTP-эндпоинты и сохраняет временные ряды с метками.

**Grafana** — платформа визуализации и анализа метрик. Позволяет строить интерактивные дашборды, настраивать панели мониторинга и отслеживать тренды производительности на основе данных из Prometheus.

**RPS (Requests Per Second)** — количество HTTP-запросов, обрабатываемых веб-сервером в секунду. Базовый показатель пропускной способности и интенсивности нагрузки.

**95-й перцентиль (P95)** — статистический показатель задержки обработки: 95% запросов выполняются быстрее указанного времени, а оставшиеся 5% составляют «длинный хвост» задержек (**latency**), выявление которого критично для оценки пользовательского опыта.

**SLI / SLO (Service Level Indicator / Objective)** — ключевые показатели качества обслуживания (индикатор) и целевой уровень надежности (цель). В контексте Nginx метрики VTS формируют основу для вычисления SLI доступности (процент ответов не-5xx) и задержки (процент запросов быстрее порогового значения).

**MTTR (Mean Time To Repair)** — среднее время восстановления работоспособности сервиса после возникновения инцидента. Наличие детальных метрик по статусам и бэкендам сокращает фазу локализации проблемы.

**Runbook** — пошаговое эксплуатационное руководство для дежурного инженера SRE/системного администратора по диагностике, локализации и устранению типовых инцидентов инфраструктуры.

---

## Основные концепции

### Архитектура решения и поток данных

Мониторинг веб-сервера строится по трехуровневой схеме с разделением плоскости обработки пользовательского трафика (**Data Plane**) и плоскости мониторинга/управления (**Management Plane**):

```
+-----------------------------------------------------------------------------------+
| Host / Server (Nginx)                                                            |
|                                                                                   |
|  [ Client HTTP/HTTPS Traffic ]                                                    |
|                 │                                                                 |
|                 ▼                                                                 |
|        [ Worker Processes ] ◄───(mutex)───► [ Shared Memory Zone (Slab / rbtree) ] |
|                 │                                      │                          |
|                 ▼                                      ▼                          |
|         [ Upstream Backends ]               [ VTS Scrape Handler ]                |
|                                                        │                          |
|                                           (GET /metrics on :8080)                 |
+────────────────────────────────────────────────────────┼──────────────────────────+
                                                         │
                                                  (Scrape 15s)
                                                         │
                                                         ▼
                                              +─────────────────────+
                                              |  Prometheus Server  |
                                              +──────────┬──────────+
                                                         │
                                            ┌────────────┴────────────┐
                                            ▼                         ▼
                                   +─────────────────+       +─────────────────+
                                   |  Alertmanager   |       | Grafana UI / DB |
                                   +─────────────────+       +─────────────────+
```

1. **Обработка запроса**: Worker-процесс Nginx обрабатывает клиентский запрос, проксирует его на бэкенд и переходит в фазу `NGX_HTTP_LOG_PHASE`.
2. **Агрегация в shm**: Модуль VTS захватывает спинлок/мьютекс разделяемой памяти (`shpool->mutex`), находит соответствующий узел в красно-черном дереве (`rbtree`) по имени виртуального хоста или апстрима и атомарно инкрементирует счетчики трафика, статусов и бакетов гистограмм.
3. **Сбор метрик (Scrape)**: Prometheus опрашивает эндпоинт `/metrics` через настроенный интервал (`scrape_interval: 15s`). Внутренний обработчик VTS форматирует накопленные в разделяемой памяти данные в текстовый формат Prometheus Exposition Format.
4. **Оповещение и визуализация**: Prometheus сохраняет временные ряды, валидирует правила алертинга (Alerting Rules) и отдает данные дашбордам Grafana.

### Внутреннее устройство и модель разделяемой памяти

- **Аллокация slab**: При старте Nginx мастер-процесс выделяет единый блок памяти заданного размера (`vhost_traffic_status_zone`). Память распределяется slab-аллокатором на слоты и страницы.
- **Структура rbtree**: Все счетчики организованы в виде красно-черных деревьев по пространствам имен:
  - `server_zones` — агрегация по директиве `server_name` или значению заголовка `Host`.
  - `filter_zones` — кастомные зоны, сгенерированные директивой `vhost_traffic_status_filter_by_set_key`.
  - `upstream_zones` — статистика по каждому физическому серверу в блоках `upstream`.
  - `cache_zones` — статистика дисковых зон кэширования `proxy_cache`.
- **Проблема High Cardinality**: При использовании пользовательских переменных в фильтрах (например, IP-адресов или полных URI) дерево быстро разрастается, исчерпывает объем slab-памяти и вызывает contention мьютекса разделяемой памяти, что приводит к деградации RPS Nginx. Для контроля кардинальности применяются директивы `vhost_traffic_status_filter_max_node` и `vhost_traffic_status_filter_check_duplicate`.

### Сравнение инструментов мониторинга Nginx

| Критерий | `ngx_http_stub_status_module` | `nginx-module-vts` | `nginx-prometheus-exporter` | `Angie` (нативный) |
| :--- | :--- | :--- | :--- | :--- |
| **Детализация по виртуальным хостам** | Нет (только глобально) | Да | Нет (при работе со stub_status) | Да |
| **Гистограммы Latency (P90/P95/P99)** | Нет | Да (`request_duration_seconds`) | Нет | Да |
| **Статистика апстримов** | Нет | Да (по серверам) | Только в Nginx Plus | Да |
| **Статистика дискового кэша** | Нет | Да (Hit / Miss / Expired) | Нет | Да |
| **Встроенный формат Prometheus** | Нет (только сырой текст) | Да (нативный эндпоинт) | Да (отдельный сервис) | Да (`/status/format/prometheus`) |
| **Накладные расходы на процессы** | Нулевые | Захват мьютекса shm в log phase | Внешний опрос stub_status | Нативная разделяемая память |
| **Установка** | Встроена в Nginx | Требует компиляции модуля | Отдельный бинарник/демон | Встроена из коробки |

### Текущий статус проекта nginx-module-vts

Модуль `nginx-module-vts` поддерживается сообществом (ветка релизов `v0.2.x`, maintainer `u5surf`), где обеспечена совместимость с версиями Nginx 1.26.x и 1.27.x, оптимизировано время удержания блокировки разделяемой памяти и исправлена обработка динамических апстримов.

Для новых проектов или миграций без необходимости компиляции сторонних C-модулей рекомендуется рассматривать **[Angie](../../Angie/angie_overview.md)**, где расширенный мониторинг является частью ядра и не требует внешних динамических библиотек.

---

## Практические сценарии

### Предварительные требования (Prerequisites)

- **ОС:** Linux (Debian 12 Bookworm, Ubuntu 22.04/24.04 LTS, Rocky Linux / RHEL 9).
- **Пакеты:** Nginx 1.26.x, скомпилированный с флагом `--with-compat` (стандарт для официальных репозиториев nginx.org), компилятор `gcc`, `make`, библиотеки `libpcre2-dev` (или `libpcre3-dev`), `zlib1g-dev`, `libssl-dev`.
- **Сеть:** Доступ от сервера Prometheus к management-порту Nginx (по умолчанию TCP 8080).
- **Права доступа:** `sudo` или root для сборки модуля и применения конфигураций systemd.

### Подготовка тестового окружения (Go-бэкенд)

Для валидации гистограмм задержек и генерации кодов ответов создадим тестовое приложение на Go.

**Код приложения (`/opt/backend/main.go`):**

```go
package main

import (
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"time"
)

func handler(w http.ResponseWriter, r *http.Request) {
	// Имитация задержки от 10мс до 800мс
	delay := rand.Intn(790) + 10
	time.Sleep(time.Duration(delay) * time.Millisecond)

	// Имитация 5% ошибок для проверки алертинга
	if rand.Float32() < 0.05 {
		w.WriteHeader(http.StatusInternalServerError)
		fmt.Fprintf(w, "Error 500 (delay: %dms)\n", delay)
		return
	}

	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, "Response OK (delay: %dms)\n", delay)
}

func main() {
	http.HandleFunc("/", handler)
	log.Println("Starting mock backend on 127.0.0.1:8090...")
	if err := http.ListenAndServe("127.0.0.1:8090", nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
```

**Запуск службы бэкенда через systemd (`/etc/systemd/system/mock-backend.service`):**

```ini
[Unit]
Description=Mock HTTP Backend for Nginx VTS Testing
After=network.target

[Service]
Type=simple
User=nobody
WorkingDirectory=/opt/backend
ExecStart=/usr/bin/go run /opt/backend/main.go
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

**Активация и проверка бэкенда:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mock-backend
# → Created symlink /etc/systemd/system/multi-user.target.wants/mock-backend.service → /etc/systemd/system/mock-backend.service.

curl -s http://127.0.0.1:8090/
# → Response OK (delay: 142ms)
```

### Сборка и установка VTS-модуля

#### Сценарий 1: Сборка динамического модуля под установленный бинарник Nginx

Подход позволяет добавить VTS без пересборки всего веб-сервера. Необходима точная совместимость сборочных флагов.

```bash
# 1. Определение точной версии Nginx
NGINX_VER=$(nginx -v 2>&1 | awk -F'/' '{print $2}')
echo "Detected Nginx version: ${NGINX_VER}"
# → Detected Nginx version: 1.26.2

# 2. Установка сборочных зависимостей
sudo apt-get update && sudo apt-get install -y --no-install-recommends \
    build-essential \
    libpcre2-dev \
    zlib1g-dev \
    libssl-dev \
    git \
    wget \
    ca-certificates

# 3. Загрузка исходников Nginx и модуля VTS
mkdir -p /tmp/nginx-build && cd /tmp/nginx-build
wget -qO- "https://nginx.org/download/nginx-${NGINX_VER}.tar.gz" | tar -xz
git clone --depth 1 --branch v0.2.7 https://github.com/vozlt/nginx-module-vts.git

# 4. Сборка динамического модуля с флагом --with-compat
cd "nginx-${NGINX_VER}"
./configure --with-compat --add-dynamic-module=../nginx-module-vts
make modules

# 5. Копирование собранного модуля в каталог библиотек Nginx
sudo mkdir -p /etc/nginx/modules
sudo cp objs/ngx_http_vhost_traffic_status_module.so /etc/nginx/modules/
sudo chmod 644 /etc/nginx/modules/ngx_http_vhost_traffic_status_module.so

# 6. Очистка временных файлов сборки
cd / && rm -rf /tmp/nginx-build
```

#### Сценарий 2: Сборка динамического модуля через Multi-stage Docker

В изолированных окружениях сборка выносится в промежуточный образ для чистоты production-контейнера.

**Dockerfile:**

```dockerfile
FROM nginx:1.26.2 AS builder

# Установка сборочных инструментов
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpcre2-dev \
    zlib1g-dev \
    libssl-dev \
    git \
    wget \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Загрузка исходников соответствующей версии Nginx и модуля VTS
ARG NGINX_VERSION=1.26.2
ARG VTS_VERSION=v0.2.7

WORKDIR /build
RUN wget -qO- https://nginx.org/download/nginx-${NGINX_VERSION}.tar.gz | tar -xz \
 && git clone --depth 1 --branch ${VTS_VERSION} https://github.com/vozlt/nginx-module-vts.git \
 && cd nginx-${NGINX_VERSION} \
 && ./configure --with-compat --add-dynamic-module=../nginx-module-vts \
 && make modules

# Финальный production-образ
FROM nginx:1.26.2
COPY --from=builder /build/nginx-1.26.2/objs/ngx_http_vhost_traffic_status_module.so /etc/nginx/modules/

RUN mkdir -p /etc/nginx/modules.d \
 && echo "load_module /etc/nginx/modules/ngx_http_vhost_traffic_status_module.so;" > /etc/nginx/modules.d/10-vts.conf
```

**Сборка и валидация контейнера:**

```bash
docker build -t nginx-vts:1.26.2 .
# → Successfully tagged nginx-vts:1.26.2

docker run -d --name nginx-vts-test -p 80:80 -p 8080:8080 nginx-vts:1.26.2
# → c1a2b3d4e5f6...

docker exec nginx-vts-test nginx -V
# → nginx version: nginx/1.26.2
```

### Конфигурация Nginx

SRE-стандартом является изоляция эндпоинта метрик на отдельном внутреннем порту (например, `8080` или loopback `127.0.0.1`), чтобы исключить утечку бизнес-метрик во внешнюю сеть и предотвратить атаки на парсер метрик.

#### Основной файл конфигурации (`/etc/nginx/nginx.conf`)

```nginx
# Загрузка модуля в глобальном контексте
load_module /etc/nginx/modules/ngx_http_vhost_traffic_status_module.so;

user www-data;
worker_processes auto;
pid /run/nginx.pid;

events {
    worker_connections 4096;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # 1. Выделение зоны разделяемой памяти (32MB достаточно для ~1500 хостов/апстримов)
    vhost_traffic_status_zone shared:vhost_traffic_status:32m;

    # 2. Настройка корзин гистограмм для точного расчета P50, P90, P95, P99 Latency (в секундах)
    vhost_traffic_status_histogram_buckets 0.005 0.01 0.025 0.05 0.1 0.25 0.5 1 2.5 5 10;

    # 3. Фильтрация по имени виртуального хоста (отсекает номер порта для чистоты временных рядов)
    vhost_traffic_status_filter_by_host on;

    # 4. Защита от High Cardinality и дубликатов ключей
    vhost_traffic_status_filter_check_duplicate on;
    vhost_traffic_status_filter_max_node 1024;

    # Определение апстрима бэкендов
    upstream app_backend {
        server 127.0.0.1:8090 max_fails=3 fail_timeout=10s;
        keepalive 32;
    }

    # Подключение виртуальных хостов
    include /etc/nginx/conf.d/*.conf;
}
```

#### Виртуальный хост сервиса (`/etc/nginx/conf.d/app.conf`)

```nginx
# Определение служебных запросов (healthcheck / боты), исключаемых из сбора метрик
map $http_user_agent $is_metrics_bypass {
    default 0;
    "~*HealthCheck" 1;
    "~*UptimeRobot" 1;
}

server {
    listen 80;
    server_name app.internal.net;

    # Исключение определенных запросов из статистики VTS
    vhost_traffic_status_bypass_stats $is_metrics_bypass;

    location / {
        proxy_pass http://app_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_connect_timeout 2s;
        proxy_read_timeout 5s;
    }
}
```

#### Выделенный сервер мониторинга (`/etc/nginx/conf.d/management.conf`)

```nginx
server {
    # Прослушивание внутреннего порта управления или loopback
    listen 127.0.0.1:8080;
    listen 192.168.1.10:8080; # Внутренний сетевой интерфейс узла
    server_name _;

    # Запрет логирования обращений к эндпоинтам метрик
    access_log off;

    # Эндпоинт в формате Prometheus Exposition Format
    location /metrics {
        vhost_traffic_status_display;
        vhost_traffic_status_display_format prometheus;

        # Ограничение доступа по белому списку IP
        allow 127.0.0.1;
        allow 192.168.1.50; # Сервер Prometheus
        deny all;
    }

    # Встроенный интерактивный веб-дашборд модуля VTS
    location /status {
        vhost_traffic_status_display;
        vhost_traffic_status_display_format html;

        allow 127.0.0.1;
        allow 192.168.1.0/24; # Подсеть администраторов / VPN
        deny all;
    }

    # API контроля зон (сброс счетчиков, инспекция JSON)
    location /status/control {
        vhost_traffic_status_control;

        allow 127.0.0.1;
        deny all;
    }
}
```

#### Валидация и применение конфигурации

```bash
# 1. Валидация синтаксиса
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Применение без разрыва установленных TCP-соединений
sudo systemctl reload nginx

# 3. Проверка статуса демона
sudo systemctl is-active nginx
# → active
```

### Настройка Prometheus

В файл конфигурации `/etc/prometheus/prometheus.yml` добавляется задача сбора:

```yaml
scrape_configs:
  - job_name: 'nginx-vts'
    scrape_interval: 15s
    scrape_timeout: 10s
    metrics_path: '/metrics'
    static_configs:
      - targets: ['192.168.1.10:8080']
        labels:
          environment: 'production'
          role: 'reverse-proxy'
    # Очистка и фильтрация служебных меток при необходимости
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: 'nginx_vts_.*'
        action: keep
```

### Настройка правил алертинга (Prometheus Alerting Rules)

Правила для файла `/etc/prometheus/rules/nginx_vts_alerts.yml`. Все имена метрик соответствуют экспозиции модуля:

```yaml
groups:
  - name: nginx_vts_alerts
    rules:
      # Падение доступности самого веб-сервера
      - alert: NginxDown
        expr: up{job="nginx-vts"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Nginx instance is down"
          description: "Target {{ $labels.instance }} is unreachable for more than 1 minute."
          runbook_url: "https://wiki.internal.net/runbooks/nginx-down"

      # Доля ответов 5xx превышает 5% за 5 минут
      - alert: NginxHighErrorRate5xx
        expr: |
          (
            sum(rate(nginx_vts_server_requests_total{code="5xx"}[5m]))
            /
            sum(rate(nginx_vts_server_requests_total[5m]))
          ) * 100 > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "High 5xx error rate on Nginx ({{ $value | printf \"%.2f\" }}%)"
          description: "More than 5% of requests on {{ $labels.host }} ended with 5xx server errors."

      # Задержка обработки P95 превышает 1.5 секунды
      - alert: NginxHighLatencyP95
        expr: |
          histogram_quantile(0.95,
            sum(rate(nginx_vts_server_request_duration_seconds_bucket[5m])) by (le, host)
          ) > 1.5
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "High P95 latency on Nginx host {{ $labels.host }}"
          description: "95% of requests take more than 1.5s to complete for over 3 minutes."

      # Исчерпание разделяемой памяти VTS (более 85%)
      - alert: NginxVtsSharedMemoryCritical
        expr: |
          (
            nginx_vts_main_shm_usage_bytes{shared="used_size"}
            /
            nginx_vts_main_shm_usage_bytes{shared="max_size"}
          ) * 100 > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Nginx VTS shared memory is running out ({{ $value | printf \"%.2f\" }}%)"
          description: "VTS zone memory utilization is over 85%. Increase vhost_traffic_status_zone size."
```

Валидация правил Prometheus:

```bash
promtool check rules /etc/prometheus/rules/nginx_vts_alerts.yml
# → Checking /etc/prometheus/rules/nginx_vts_alerts.yml
# →   SUCCESS: 4 rules found
```

### Визуализация в Grafana

1. В Grafana перейдите в **Connections → Data Sources** и подключите Prometheus (`http://192.168.1.50:9090`).
2. Перейдите в **Dashboards → New → Import** и импортируйте эталонные шаблоны:
   - **ID 2949** — «NGINX VTS Statistics»: классический дашборд с детализацией по серверным зонам, апстримам и статус-кодам.
   - **ID 9614** — «NGINX VTS»: расширенная версия с поддержкой бакетов задержек и расчетом перцентилей.
3. Отредактируйте переменные дашборда (**Dashboard settings → Variables**):
   - `host` — `label_values(nginx_vts_server_requests_total, host)`
   - `upstream` — `label_values(nginx_vts_upstream_requests_total, upstream)`

---

## Операции и команды

### Управление конфигурацией и процессами Nginx

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `sudo nginx -t` | Проверка синтаксиса всех подключенных конфигураций | `nginx: configuration file /etc/nginx/nginx.conf test is successful` |
| `sudo nginx -T \| grep -i vhost_traffic` | Поиск директив VTS в объединенном дереве конфигурации | Вывод директив `vhost_traffic_status_zone` и других |
| `sudo systemctl reload nginx` | Перечитывание конфигурации мастер-процессом (SIGHUP) | Нет вывода при успехе (код возврата `0`) |
| `sudo systemctl status nginx` | Проверка статуса службы и PID процессов | `Active: active (running)` с перечнем worker processes |

### Проверка и валидация эндпоинтов VTS

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `curl -s -I http://127.0.0.1:8080/metrics` | Проверка HTTP-заголовков эндпоинта метрик | `HTTP/1.1 200 OK` и `Content-Type: text/plain; version=0.0.4` |
| `curl -s http://127.0.0.1:8080/metrics \| grep "^nginx_vts_info"` | Проверка версии модуля и веб-сервера | `nginx_vts_info{hostname="...",module_version="v0.2.7",version="1.26.2"} 1` |
| `curl -s http://127.0.0.1:8080/status/format/json \| jq .sharedZones` | Проверка состояния разделяемой памяти через JSON API | `{"name": "vhost_traffic_status", "maxSize": 33554432, "usedSize": ...}` |
| `nginx -V 2\>&1 \| grep -o "vhost_traffic_status"` | Проверка загрузки или линковки модуля | `vhost_traffic_status` |

### Управление счетчиками на лету (Control API)

Модуль VTS поддерживает динамический сброс и удаление зон без перезапуска веб-сервера через эндпоинт `/status/control`.

```bash
# 1. Сброс счетчиков конкретной серверной зоны
curl -s "http://127.0.0.1:8080/status/control?cmd=reset&group=server&zone=app.internal.net"
# → {"status": 200, "message": "OK"}

# 2. Удаление неиспользуемой серверной зоны из памяти
curl -s "http://127.0.0.1:8080/status/control?cmd=delete&group=server&zone=old.internal.net"
# → {"status": 200, "message": "OK"}
```

### Диагностика Prometheus и алертов

| Команда | Описание | Ожидаемый вывод |
| :--- | :--- | :--- |
| `promtool check rules /etc/prometheus/rules/*.yml` | Валидация синтаксиса правил оповещения | `SUCCESS: ... rules found` |
| `curl -s http://127.0.0.1:9090/api/v1/targets \| jq '.data.activeTargets[] \| select(.labels.job=="nginx-vts") \| {health, lastScrape}'` | Проверка состояния таргета в Prometheus | `{"health": "up", "lastScrape": "..."}` |
| `promtool query instant http://127.0.0.1:9090 'up{job="nginx-vts"}'` | Мгновенный PromQL-запрос состояния хоста | `up{environment="production", job="nginx-vts", ...} => 1 @[...]` |

### Резервное копирование и регламент отката

Перед внесением изменений в конфигурацию мониторинга обязателен бэкап и проверка атомарности применения:

```bash
# 1. Создание снимка каталога конфигурации с временной меткой
TIMESTAMP=$(date +%Y%m%d%H%M%S)
sudo cp -a /etc/nginx /etc/nginx.bak.${TIMESTAMP}

# 2. Внесение изменений и атомарная валидация
sudo nginx -t && sudo systemctl reload nginx
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 3. Экстренный откат в случае инцидента
# sudo rm -rf /etc/nginx && sudo cp -a /etc/nginx.bak.${TIMESTAMP} /etc/nginx && sudo systemctl reload nginx
```

---

## Устранение неисправностей

### 1. Переполнение разделяемой памяти: `shared memory zone "vhost_traffic_status" is too small`

**Симптомы:**
В `/var/log/nginx/error.log` появляются сообщения:
```
[alert] 1234#1234: ngx_slab_alloc() failed: no memory in vhost_traffic_status_zone "vhost_traffic_status"
```
Метрики для новых хостов перестают фиксироваться, PromQL-запросы возвращают неполные данные.

**Причина:**
Размер зоны разделяемой памяти недостаточен для текущего количества виртуальных хостов, бэкендов или динамических узлов фильтрации (`filter_by_set_key`).

**Диагностика:**
```bash
# Проверка текущего использования памяти через JSON-эндпоинт
curl -s http://127.0.0.1:8080/status/format/json | jq '.sharedZones'
# → {
# →   "name": "vhost_traffic_status",
# →   "maxSize": 33554432,
# →   "usedSize": 33550120,
# →   "usedNode": 1024
# → }
```

**Решение:**
1. Увеличьте размер зоны в `nginx.conf` (например, с `32m` до `64m` или `128m`):
   ```nginx
   vhost_traffic_status_zone shared:vhost_traffic_status:64m;
   ```
2. Ограничьте максимальное число узлов фильтрации для предотвращения утечек памяти:
   ```nginx
   vhost_traffic_status_filter_max_node 2048;
   ```
3. Проверьте синтаксис и выполните перезапуск (изменение размера разделяемой памяти требует `restart` или `reload` с перевыделением slab-памяти):
   ```bash
   sudo nginx -t && sudo systemctl restart nginx
   # → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
   # → nginx: configuration file /etc/nginx/nginx.conf test is successful
   ```

### 2. Ошибка ABI-несовместимости: `is not binary compatible`

**Симптомы:**
При запуске Nginx аварийно завершается с ошибкой в `/var/log/nginx/error.log`:
```
[emerg] 1234#1234: module "/etc/nginx/modules/ngx_http_vhost_traffic_status_module.so" is not binary compatible in /etc/nginx/nginx.conf:1
```

**Причина:**
Динамический модуль был скомпилирован с другим набором сборочных флагов, другой версией компилятора или без директивы `--with-compat`.

**Диагностика:**
```bash
# Извлечение сборочной сигнатуры из бинарника модуля
strings /etc/nginx/modules/ngx_http_vhost_traffic_status_module.so | grep -E "^[0-9],[0-9],[0-9]"
# → 1,26,1,101111010110...

# Проверка сигнатуры текущего Nginx
nginx -V
```

**Решение:**
Пересоберите модуль строго под установленную версию бинарника Nginx (`nginx -v`) с добавлением флага `--with-compat` и точно совпадающими версиями зависимостей OpenSSL и PCRE (см. подраздел «Сборка динамического модуля»).

### 3. Запрос к `/metrics` возвращает код 403 Forbidden

**Симптомы:**
В логах Prometheus таргет переходит в состояние `DOWN`, а `curl` возвращает:
```
HTTP/1.1 403 Forbidden
```

**Причина:**
IP-адрес опрашивающего узла Prometheus не совпадает с директивами `allow` в блоке `location /metrics` (частая проблема при прохождении через Docker NAT, промежуточные шлюзы или смене интерфейса).

**Диагностика:**
```bash
# Поиск записей о блокировке в логе ошибок
sudo grep "access forbidden by rule" /var/log/nginx/error.log | tail -n 3
# → 2026/10/16 11:20:00 [error] 1234#1234: *5 access forbidden by rule, client: 192.168.1.55, server: _, request: "GET /metrics HTTP/1.1"
```

**Решение:**
Добавьте реальный IP-адрес сервера мониторинга (`192.168.1.55`) или всю доверенную подсеть в `/etc/nginx/conf.d/management.conf`:
```nginx
location /metrics {
    vhost_traffic_status_display;
    vhost_traffic_status_display_format prometheus;

    allow 127.0.0.1;
    allow 192.168.1.50;
    allow 192.168.1.55; # Добавленный адрес
    deny all;
}
```
Примените конфигурацию: `sudo nginx -t && sudo systemctl reload nginx`.

### 4. Отсутствие гистограмм задержек (пустые квантили в Grafana)

**Симптомы:**
Запрос `histogram_quantile(0.95, ...)` возвращает `NaN` или `No data`, а в выводе `/metrics` отсутствуют строки с суффиксом `_bucket`.

**Причина:**
В контексте `http` отсутствует директива `vhost_traffic_status_histogram_buckets`, либо в PromQL-запросе допущена ошибка в имени метрики (использовано `response_duration` вместо `request_duration` на уровне серверных зон).

**Диагностика:**
```bash
# Проверка наличия бакетов в выдаче метрик
curl -s http://127.0.0.1:8080/metrics | grep "_bucket" | head -n 3
# Если вывод пустой — корзины гистограмм не активированы
```

**Решение:**
1. Убедитесь, что в блоке `http` файла `nginx.conf` задана шкала бакетов:
   ```nginx
   vhost_traffic_status_histogram_buckets 0.005 0.01 0.05 0.1 0.5 1 5 10;
   ```
2. Проверьте правильность PromQL-запроса:
   - Для виртуальных хостов: `nginx_vts_server_request_duration_seconds_bucket`.
   - Для апстримов: `nginx_vts_upstream_response_duration_seconds_bucket`.
3. Перезапустите Nginx: `sudo nginx -t && sudo systemctl restart nginx`.

### 5. Contention мьютекса разделяемой памяти и рост нагрузки на CPU

**Симптомы:**
При росте RPS до десятков тысяч процессорное время worker-процессов тратится в системных вызовах блокировок (`futex`), растет общее время ответа веб-сервера.

**Причина:**
Высокая кардинальность при использовании директивы `vhost_traffic_status_filter_by_set_key` (например, при передаче в ключ значений `$remote_addr` или `$request_uri`). Каждый уникальный ключ требует создания узла в rbtree под эксклюзивной блокировкой мьютекса памяти.

**Диагностика:**
```bash
# Оценка количества узлов в дереве фильтров
curl -s http://127.0.0.1:8080/status/format/json | jq '.filterZones | length'
# → 54200 (критически высокая кардинальность)
```

**Решение:**
1. Исключите переменные с высокой энтропией из `vhost_traffic_status_filter_by_set_key`. Используйте только агрегированные признаки (например, `$status`, `$upstream_cache_status`, `$geoip_country_code`).
2. Включите директиву ограничения максимального количества узлов:
   ```nginx
   vhost_traffic_status_filter_max_node 1024;
   ```
3. Сбросьте раздутые зоны через Control API или выполните `reload`.

---

## Рекомендации и лучшие практики

### Сегментация сети и безопасность плоскости управления

- **Выделенный порт:** Никогда не публикуйте `/metrics` на портах публичного клиентского трафика (`80`, `443`). Размещайте эндпоинты мониторинга на отдельном сетевом интерфейсе, loopback (`127.0.0.1:8080`) или выделенном VLAN.
- **Ограничение прав:** Если Prometheus находится на удаленном хосте, используйте комбинацию фильтрации по IP (`allow/deny`), брандмауэра ОС (`nftables`/`iptables`) и Basic Auth (`auth_basic`) либо взаимной аутентификации по сертификатам (mTLS).
- **Скрытие информации:** Эндпоинт `/status` в формате HTML раскрывает внутреннюю топологию сети (адреса и порты апстрим-серверов). Доступ к нему должен быть ограничен исключительно сетью администраторов.

### Сайзинг Shared Memory и контроль кардинальности

- **Базовый расчет памяти:**
  - 1 серверная зона занимает ~2 КБ в разделяемой памяти с учетом гистограмм.
  - Зона размером `32MB` надежно обслуживает до 1500–2000 сущностей (хосты + бэкенды + фильтры).
  - При активном использовании апстримов с десятками серверов выделяйте от `64MB` до `128MB`.
- **Защита от спуфинга заголовка Host:** Если Nginx принимает произвольные заголовки `Host`, атакующий может сгенерировать миллионы фиктивных доменов и переполнить разделяемую память. Всегда настраивайте default server, сбрасывающий неопознанный трафик:
  ```nginx
  server {
      listen 80 default_server;
      server_name _;
      return 444;
  }
  ```

### Тюнинг сбора метрик в Prometheus (Scrape Discipline)

- **Интервал сбора:** Рекомендуемый интервал опроса составляет `15s`. Уменьшение интервала до `1s–5s` на серверах с сотнями доменов создает постоянную нагрузку на сериализацию метрик в текстовый вид внутри Nginx.
- **Таймаут сбора:** Устанавливайте `scrape_timeout: 10s` при `scrape_interval: 15s`. Если генерация метрик занимает более 1–2 секунд, это признак избыточной кардинальности или нехватки CPU.

### Эксплуатационные метрики SRE и расчет бюджетов ошибок (Error Budget)

- Используйте метрики VTS для формирования Service Level Objectives (SLO).
- Базовый SLI доступности сервиса (процент успешных запросов за окно 30 дней):
  $$\text{SLI}_{\text{availability}} = \frac{\sum \text{rate}(nginx\_vts\_server\_requests\_total\{code!\sim"5xx"\})}{\sum \text{rate}(nginx\_vts\_server\_requests\_total)}$$
- Заложите в алерт-менеджмент многооконные правила сжигания бюджета ошибок (Multiwindow Multi-Burn-Rate Alerts) по методологии Google SRE.

---

## Дополнительная информация

### Каталог проверенных PromQL-запросов

**1. Текущий общий RPS по всем виртуальным хостам:**
```promql
sum(rate(nginx_vts_server_requests_total[1m]))
```

**2. RPS в разрезе статус-кодов:**
```promql
sum by (code) (rate(nginx_vts_server_requests_total[1m]))
```

**3. Процент серверных ошибок 5xx (Error Rate):**
```promql
(
  sum(rate(nginx_vts_server_requests_total{code="5xx"}[5m]))
  /
  sum(rate(nginx_vts_server_requests_total[5m]))
) * 100
```

**4. Задержка обработки запросов (P50, P95, P99 Latency):**
```promql
# 95-й перцентиль
histogram_quantile(0.95,
  sum(rate(nginx_vts_server_request_duration_seconds_bucket[5m])) by (le, host)
)

# 99-й перцентиль
histogram_quantile(0.99,
  sum(rate(nginx_vts_server_request_duration_seconds_bucket[5m])) by (le, host)
)
```

**5. Процент использования разделяемой памяти VTS:**
```promql
(
  nginx_vts_main_shm_usage_bytes{shared="used_size"}
  /
  nginx_vts_main_shm_usage_bytes{shared="max_size"}
) * 100
```

**6. Эффективность дискового кэша (Cache Hit Ratio %):**
```promql
(
  sum(rate(nginx_vts_server_cache_total{status="hit"}[5m]))
  /
  sum(rate(nginx_vts_server_cache_total[5m]))
) * 100
```

**7. Входящий и исходящий сетевой трафик (Mbit/s):**
```promql
# Исходящий трафик
sum by (host) (rate(nginx_vts_server_bytes_total{direction="out"}[1m])) * 8 / 1000000

# Входящий трафик
sum by (host) (rate(nginx_vts_server_bytes_total{direction="in"}[1m])) * 8 / 1000000
```

### Альтернативные решения

- **[Angie](../../Angie/angie_overview.md)** — российский форк Nginx с нативной поддержкой Prometheus-экспорта без сторонних динамических библиотек. Включает расширенный модуль `api` и консоль управления.
- **nginx-prometheus-exporter** — официальный экспортер от Nginx Software Inc. Работает как отдельный сервис, опрашивающий стандартный `stub_status` (минимальный набор метрик) или платный Nginx Plus API.

---

## См. также

- **[Обзор Nginx](../Core/nginx_overview.md)** — архитектура процессов, event loop и жизненный цикл соединения.
- **[Сборка Nginx из исходного кода и динамические модули](../Core/nginx_build_from_source.md)** — регламент компиляции модулей с флагом `--with-compat`.
- **[Анализ логов Nginx](./nginx_log_analysis.md)** — парсинг логов доступа, структурирование JSON и сбор метрик без сторонних модулей.
- **[Диагностика веб-серверов](../../Concepts/webserver_troubleshooting.md)** — комплексная методология поиска и локализации сетевых и системных сбоев.
- **[Обзор Angie](../../Angie/angie_overview.md)** — функционал нативного мониторинга и L4/L7 балансировки в Angie.
