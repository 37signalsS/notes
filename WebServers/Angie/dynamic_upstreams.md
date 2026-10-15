# Динамические группы проксируемых серверов в Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Динамический Upstream в Angie** — механизм автоматического управления составом и параметрами серверов бэкенда (IP-адреса, порты, веса, статусы доступности, лимиты соединений) в оперативной памяти без необходимости перезагрузки конфигурационного файла или отправки сигналов процессу (`reload`).

**Обнаружение сервисов (Service Discovery, SD)** — процесс автоматической регистрации сетевых координат (IP и порт) экземпляров приложений и их динамического обнаружения балансировщиком нагрузки. Общие принципы и модели (Client-side vs Server-side) описаны в [обзоре Service Discovery](../../Concepts/service-discovery-overview.md). В Angie поддерживаются три нативных механизма SD: периодическое разрешение через DNS (A/AAAA и SRV), мониторинг событий Docker API и программное управление через REST API конфигурации (Angie PRO).

**Зона разделяемой памяти (Shared Memory Zone, `zone`)** — именованный пул общей памяти, доступный мастер-процессу и всем рабочим процессам (worker processes). Хранит в себе структуру данных upstream: текущий список пиров, их параметры (веса, `max_fails`, `fail_timeout`), состояние доступности и счетчики метрик. Зона строго обязательна для функционирования любых динамических механизмов.

**Файл состояния (State file, `state`)** — файл на дисковой подсистеме, в который Angie атомарно сохраняет актуальный состав динамической группы серверов при любых изменениях. Используется для мгновенного восстановления топологии бэкендов после перезапуска службы, предотвращая "холодный старт" до завершения первых циклов Service Discovery.

**DNS Resolver (`resolver`)** — встроенный асинхронный клиент DNS-протокола в Angie, выполняющий запросы на разрешение имен серверов в фоне без блокировки обработки клиентского трафика. Поддерживает периодическую перепроверку записей на основе параметра `valid` или TTL записей.

**DNS SRV-запись (RFC 2782)** — тип записи DNS, определяющий имя хоста, порт, приоритет (priority) и вес (weight) для конкретной службы. Позволяет балансировщику определять не только IP-адрес, но и динамически назначенные порты бэкендов (характерно для Consul, HashiCorp Nomad).

**Docker Discovery (`docker_endpoint`)** — модуль в составе Angie, подключающийся напрямую к сокету Docker Engine и отслеживающий жизненный цикл контейнеров (start, stop, die, pause, unpause) в реальном времени на основе меток (labels).

**Конфигурационный API (Angie PRO API)** — HTTP REST API коммерческой версии Angie PRO, обеспечивающий управление составом upstream, параметрами балансировки и состоянием серверов (`up`, `down`, `drain`) через стандартные HTTP-методы `GET`, `PUT`, `PATCH`, `DELETE`.

**Состояния пиров (Peer States)**:
*   `up` — сервер активен и участвует в распределении трафика.
*   `down` — сервер административно выключен из балансировки; запросы на него не направляются.
*   `drain` / `draining` — сервер переведен в режим вывода из эксплуатации. Новые клиентские сессии на него не маршрутизируются, но существующие сессии (sticky sessions via cookie / IP hash) продолжают обслуживаться до завершения.
*   `unhealthy` — сервер признан неисправным механизмом пассивных или активных проверок работоспособности (Health Checks).

## Базовые концепции и архитектура

### Механизм разделяемой памяти (zone) и Slab Allocator

В традиционном веб-сервере Nginx OSS список серверов в блоке `upstream` компилируется во внутренние структуры данных при чтении конфигурации. Для изменения состава требуется полный цикл `reload`, создающий новые рабочие процессы.

В Angie директива `zone` размещает данные группы бэкендов в разделяемой памяти ядра Linux (POSIX shared memory via `mmap`):

```nginx
upstream backend_nodes {
    zone backend_nodes 64k;
    # динамические директивы или статический состав
}
```

*   **Архитектура памяти:** Внутри зоны память управляется slab-аллокатором Angie. Для каждого сервера создается структура пира (`peer structure`), содержащая sockaddr, вес, текущее число активных коннектов, счетчики ошибок, временные метки отказов и указатели на очереди.
*   **Чтение без блокировок:** Процессы-воркеры читают состояние пиров при выборе бэкенда с использованием атомарных операций и спинлоков минимальной длительности, что исключает падение производительности при тысячах запросов в секунду.
*   **Расчет размера зоны:** Минимальный поддерживаемый размер зоны составляет `64k`. Расчет требуемой памяти:
    $$\text{Memory} \approx 32\text{ КБ (базовые накладные расходы структуры)} + (\text{Количество серверов} \times 1\text{ КБ})$$
    *   `64k` достаточно для хранения до 30–50 серверов с подробными счетчиками.
    *   `128k` покрывает до 100–150 серверов.
    *   `1m`–`2m` выделяется для крупных инсталляций на сотни и тысячи динамических контейнеров.

### Жизненный цикл динамического обновления

```
   [ Внешние источники координат ]
   ├── DNS-сервер (A/AAAA/SRV) ──> Периодический опрос (timer, valid) ┐
   ├── Docker Engine API ────────> Поток событий (event stream) ──────┼──> [ Angie Core ]
   └── REST API (Angie PRO) ─────> HTTP PUT/PATCH/DELETE ─────────────┘         │
                                                                                ▼
[ Клиенты ] <──> [ Angie Workers ] <──> [ Shared Memory Zone ] <── Обновление списка пиров
                        │                      │
                  Keepalive Pool          State File
              (дренирование сокетов)   (/var/lib/angie/state)
```

1.  **Инициализация:** При старте службы создается сегмент shared memory. Если задана директива `state`, Angie считывает файл состояния с диска и мгновенно регистрирует сохраненные бэкенды.
2.  **Обнаружение изменений:**
    *   **DNS:** Процесс Angie инициирует неблокирующие UDP/TCP-запросы к серверам, указанным в директиве `resolver`. Если параметр `valid` задан, он переопределяет значение TTL из ответа DNS-сервера. Если DNS вернул новые адреса, они добавляются в пул. Если адрес исчез из ответа — он помечается на удаление.
    *   **Docker:** Фоновый поток в Angie устанавливает постоянное HTTP-соединение с UNIX-сокетом `/var/run/docker.sock` (эндпоинт `/events`). При событиях запуска (`start`) или остановки (`die`, `stop`) контейнера модуль парсит метки и мгновенно добавляет или исключает IP-адрес контейнера.
    *   **API (Angie PRO):** Обработчик директивы `api` принимает REST-запрос, валидирует JSON-пейлоад, захватывает блокировку зоны и атомарно вносит изменения.
3.  **Обработка соединений Keepalive:** При удалении бэкенда из зоны (по DNS или Docker) открытые соединения в пуле `keepalive` не сбрасываются принудительно через TCP RST. Они переводятся в режим дренирования: новые HTTP-запросы в них не отправляются, а существующие закрываются штатно по истечении `keepalive_timeout` или после обработки текущего запроса (`Connection: close`).
4.  **Персистентность:** При любом изменении состава серверов в памяти Angie производит синхронную или фоновую запись текущего снэпшота в файл `state`.

### Сравнение функциональности Angie OSS и Angie PRO

| Возможность | Angie Open Source | Angie PRO |
| :--- | :--- | :--- |
| Динамическое разрешение DNS A/AAAA (`resolve`) | Да | Да |
| Поддержка DNS SRV-записей (`service=...`) | Да | Да |
| Нативное обнаружение через Docker API (`docker_endpoint`) | Да | Да |
| Статистика upstream в реальном времени (`/status/`) | Да (Read-Only) | Да (Read-Only) |
| Метрики в формате Prometheus (`prometheus_template`) | Да | Да |
| REST API для изменения серверов в runtime (`/config/`) | Нет | **Да** (`PUT`, `PATCH`, `DELETE`) |
| Плавный вывод пиров из обслуживания (`drain`) через API | Нет | **Да** |
| Синхронизация состояния зон в кластере (`sync`) | Нет | **Да** |
| Персистентный файл состояния (`state`) | Да (в сочетании с SD) | Да (полное управление через API) |

## Практические сценарии и конфигурация

### Сценарий 1: Динамическое разрешение DNS (A/AAAA) для On-Premises микросервисов

Используется для взаимодействия с сервисами, развернутыми на виртуальных машинах или серверах внутренней сети, чьи IP-адреса могут динамически переназначаться или масштабироваться с обновлением корпоративного DNS (BIND, Unbound, dnsmasq).

**Предварительные требования:**
*   Установленный веб-сервер Angie.
*   Доступность корпоративного DNS-сервера по UDP/TCP порт 53.
*   Наличие A-записей для целевого имени в зоне `corp.internal`.

**Конфигурация `/etc/angie/http.d/dynamic_dns.conf`:**

```nginx
http {
    # Задаем надежные внутренние DNS-серверы
    # valid=10s переопределяет TTL зоны, заставляя Angie опрашивать DNS каждые 10 секунд
    # ipv6=off отключает отправку запросов типа AAAA (устраняет задержки при отсутствии IPv6)
    # status_zone включает учет статистики DNS-клиента для мониторинга
    resolver 192.168.10.2 192.168.10.3 valid=10s ipv6=off status_zone=dns_resolver_zone;
    resolver_timeout 3s;

    upstream internal_api {
        # Зона разделяемой памяти обязательна для параметра resolve
        zone internal_api 128k;

        # Параметр resolve активирует динамическое отслеживание изменений DNS
        server api.corp.internal:8080 resolve max_fails=3 fail_timeout=10s;

        # Пул постоянных соединений к бэкендам
        keepalive 32;
        keepalive_requests 1000;
        keepalive_timeout 60s;
    }

    server {
        listen 80;
        server_name gateway.corp.internal;

        location /api/ {
            proxy_pass http://internal_api;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_connect_timeout 3s;
            proxy_read_timeout 30s;
        }
    }
}
```

**Проверка конфигурации и применение:**

```bash
# 1. Валидация синтаксиса
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# 2. Применение конфигурации
sudo systemctl reload angie

# 3. Проверка текущих DNS-записей
dig @192.168.10.2 api.corp.internal +short
# → 192.168.20.11
# → 192.168.20.12

# 4. Проверка состояния upstream в Angie через Status API
curl -s http://127.0.0.1/status/http/upstreams/internal_api/ | jq '.peers'
# → {
# →   "192.168.20.11:8080": {
# →     "state": "up",
# →     "weight": 1,
# →     "selected": 45,
# →     "responses": {"2xx": 45, "5xx": 0}
# →   },
# →   "192.168.20.12:8080": {
# →     "state": "up",
# →     "weight": 1,
# →     "selected": 42,
# →     "responses": {"2xx": 42, "5xx": 0}
# →   }
# → }
```

### Сценарий 2: Обнаружение сервисов через DNS SRV (Consul / Nomad)

В микросервисных средах на базе HashiCorp Consul или Nomad приложения запускаются с динамическим выделением портов. Механизм DNS SRV передает балансировщику не только список IP, но и порты, веса и приоритеты без агентов на хосте балансировщика.

**Формат SRV-записи RFC 2782:** `_Service._Proto.Name TTL Class SRV Priority Weight Port Target`

**Конфигурация `/etc/angie/http.d/consul_srv.conf`:**

```nginx
http {
    # Адрес локального агента Consul DNS
    resolver 127.0.0.1:8600 valid=5s status_zone=consul_resolver;
    resolver_timeout 2s;

    upstream auth_cluster {
        zone auth_cluster 256k;

        # service=http указывает искать запись _http._tcp.auth-service.service.consul
        # Angie автоматически извлекает порт и вес из каждого ответа
        server auth-service.service.consul service=http resolve;

        # Сессионная привязка по cookie с резервным распределением
        sticky cookie srv_id expires=1h domain=.corp.internal path=/;
    }

    server {
        listen 80;
        server_name sso.corp.internal;

        location / {
            proxy_pass http://auth_cluster;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_next_upstream error timeout http_502 http_503;
        }
    }
}
```

**Проверка и валидация:**

```bash
# 1. Проверка разрешения SRV в Consul
dig @127.0.0.1 -p 8600 auth-service.service.consul SRV +short
# → 1 10 24101 node01.node.dc1.consul.
# → 1 10 24102 node02.node.dc1.consul.

# 2. Проверка распознавания портов в Angie
curl -s http://127.0.0.1/status/http/upstreams/auth_cluster/ | jq '.peers | keys'
# → [
# →   "192.168.30.15:24101",
# →   "192.168.30.16:24102"
# → ]
```

### Сценарий 3: Нативная интеграция с Docker Engine через сокет

Angie опрашивает Docker API напрямую через локальный сокет, подписывается на события контейнеров и формирует upstream на основе меток (labels). Это устраняет необходимость в сторонних утилитах вроде `registrator` или `docker-gen`.

**Предварительные требования к системе:**
*   Пользователь, под которым запущен рабочий процесс Angie (`angie`), должен состоять в системной группе `docker`.
*   Сокет `/var/run/docker.sock` должен быть доступен для чтения и записи процессу Angie.

**Настройка прав доступа в Linux:**
```bash
# Проверка пользователя службы
id angie
# → uid=998(angie) gid=998(angie) groups=998(angie)

# Добавление пользователя в группу docker
sudo usermod -aG docker angie

# Перезапуск службы для обновления групп процессов
sudo systemctl restart angie

# Проверка доступа к сокету из-под пользователя angie
sudo -u angie curl -s --unix-socket /var/run/docker.sock http://localhost/_ping
# → OK
```

**1. Конфигурация Docker Compose (`docker-compose.yml` целевого сервиса):**

```yaml
services:
  billing-service:
    image: internal-registry.corp.internal/billing:v2.4.1
    deploy:
      replicas: 3
    networks:
      - internal_mesh
    labels:
      # Регистрация в HTTP upstream 'billing_pool'
      - "angie.http.upstreams.billing_pool.port=8080"
      - "angie.http.upstreams.billing_pool.weight=3"
      - "angie.http.upstreams.billing_pool.max_conns=200"
      - "angie.http.upstreams.billing_pool.max_fails=2"
      - "angie.http.upstreams.billing_pool.fail_timeout=5s"
      - "angie.http.upstreams.billing_pool.slow_start=15s"
      # Указание целевой сети, если контейнер подключен к нескольким
      - "angie.network=internal_mesh"

networks:
  internal_mesh:
    external: true
```

**2. Конфигурация в Angie (`/etc/angie/http.d/docker_upstream.conf`):**

```nginx
http {
    # Подключение к локальному демону Docker
    docker_endpoint unix:/var/run/docker.sock;

    # Увеличение размера буфера для обработки больших ответов с метаданными (>25 контейнеров)
    docker_max_object_size 256k;

    upstream billing_pool {
        zone billing_pool 128k;
        # Пустой upstream: наполняется автоматически при обнаружении меток
    }

    server {
        listen 8080;
        server_name billing.corp.internal;

        location / {
            proxy_pass http://billing_pool;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_connect_timeout 2s;
        }
    }
}
```

**Проверка работы:**

```bash
# 1. Запуск контейнеров
docker compose up -d --scale billing-service=3

# 2. Проверка распознавания в логах Angie
sudo tail -n 20 /var/log/angie/error.log | grep docker
# → [info] 12412#12412: [docker] connected to Docker daemon via unix:/var/run/docker.sock
# → [info] 12412#12412: [docker] peer 172.28.0.4:8080 added to upstream "billing_pool"
# → [info] 12412#12412: [docker] peer 172.28.0.5:8080 added to upstream "billing_pool"
# → [info] 12412#12412: [docker] peer 172.28.0.6:8080 added to upstream "billing_pool"

# 3. Проверка статуса пиров
curl -s http://127.0.0.1/status/http/upstreams/billing_pool/ | jq '.peers | keys'
# → [
# →   "172.28.0.4:8080",
# →   "172.28.0.5:8080",
# →   "172.28.0.6:8080"
# → ]
```

### Сценарий 4: Управление пулом серверов в runtime через REST API в Angie PRO

Используется платформами CI/CD, пайплайнами автоматического тестирования или оркестраторами для бесшовного ввода/вывода узлов из балансировки, реализации сине-зеленых (Blue-Green) и канареечных (Canary) развертываний без `reload`.

**Предварительные требования:**
*   Установленный пакет `angie-pro`.
*   Созданный каталог для сохранения состояния `/var/lib/angie/state/` с правами пользователя `angie:angie` (права `0750`).

**Конфигурация `/etc/angie/http.d/pro_api.conf`:**

```nginx
http {
    upstream payment_backends {
        zone payment_backends 256k;
        # Файл персистентного хранения конфигурации upstream
        state /var/lib/angie/state/payment_backends.conf;
        # В блоке со state статические директивы server указывать запрещено
    }

    server {
        # Защищенный административный порт, доступный только внутри инфраструктуры
        listen 127.0.0.1:8888;
        listen 192.168.10.1:8888;

        location /config/ {
            api /config/;

            # Ограничение доступа по подсетям доверенных систем управления
            allow 127.0.0.1;
            allow 192.168.10.0/24;
            deny all;
        }

        location /status/ {
            api /status/;
            allow 127.0.0.1;
            allow 192.168.10.0/24;
            deny all;
        }
    }
}
```

**Операции управления через API:**

```bash
# 1. Добавление нового сервера в пул
curl -s -X PUT -H "Content-Type: application/json" \
  -d '{"server": "192.168.10.15:8080", "weight": 2, "max_conns": 150}' \
  http://127.0.0.1:8888/config/http/upstreams/payment_backends/servers/192.168.10.15:8080 | jq .
# → {
# →   "success": "Created",
# →   "description": "New configuration API entity \"/config/http/upstreams/payment_backends/servers/192.168.10.15:8080\" was created."
# → }

# 2. Добавление второго сервера
curl -s -X PUT -H "Content-Type: application/json" \
  -d '{"server": "192.168.10.16:8080", "weight": 1}' \
  http://127.0.0.1:8888/config/http/upstreams/payment_backends/servers/192.168.10.16:8080 | jq .
# → {
# →   "success": "Created",
# →   "description": "New configuration API entity \"/config/http/upstreams/payment_backends/servers/192.168.10.16:8080\" was created."
# → }

# 3. Изменение веса сервера на лету (Canary 10%)
curl -s -X PATCH -H "Content-Type: application/json" \
  -d '{"weight": 10}' \
  http://127.0.0.1:8888/config/http/upstreams/payment_backends/servers/192.168.10.15:8080 | jq .
# → {
# →   "success": "Updated",
# →   "description": "Existing configuration API entity \"/config/http/upstreams/payment_backends/servers/192.168.10.15:8080\" was updated with merging."
# → }

# 4. Перевод сервера в режим плавного вывода из обслуживания (Graceful Drain)
# Существующие соединения завершаются, новые запросы без сессионных cookie не поступают
curl -s -X PUT -H "Content-Type: text/plain" \
  -d "drain" \
  http://127.0.0.1:8888/config/http/upstreams/payment_backends/servers/192.168.10.15:8080/down | jq .
# → {
# →   "success": "Updated",
# →   "description": "Existing configuration API entity \"/config/http/upstreams/payment_backends/servers/192.168.10.15:8080/down\" was updated with replacing."
# → }

# 5. Проверка состояния пира после перевода в drain
curl -s http://127.0.0.1:8888/status/http/upstreams/payment_backends/ | jq '.peers["192.168.10.15:8080"].state'
# → "draining"

# 6. Полное удаление сервера с принудительным сбросом зависших коннектов через 2000 мс
curl -s -X DELETE \
  "http://127.0.0.1:8888/config/http/upstreams/payment_backends/servers/192.168.10.15:8080?connection_drop=2000" | jq .
# → {
# →   "success": "Deleted",
# →   "description": "Configuration API entity \"/config/http/upstreams/payment_backends/servers/192.168.10.15:8080\" was deleted."
# → }

# 7. Проверка сохранения в state-файле
cat /var/lib/angie/state/payment_backends.conf
# → server 192.168.10.16:8080 weight=1 max_conns=0 max_fails=1 fail_timeout=10s;
```

### Сценарий 5: Динамический upstream для Kubernetes On-Premises (CoreDNS Headless Service)

При эксплуатации Kubernetes на собственной инфраструктуре (Bare-Metal / Talos / kubeadm) внешнему Angie часто требуется проксировать трафик напрямую на поды через Headless Service (`clusterIP: None`), минуя kube-proxy.

```nginx
http {
    # Внутренний IP службы CoreDNS в кластере kube-system
    resolver 10.96.0.10 valid=5s ipv6=off;
    resolver_timeout 2s;

    upstream k8s_backend {
        zone k8s_backend 256k;

        # Разрешение Headless Service: CoreDNS возвращает IP-адреса всех готовых (Ready) подов
        server app-headless.production.svc.cluster.local:8080 resolve;

        # Проверка состояния подов
        keepalive 64;
    }

    server {
        listen 80;
        server_name app.infra.internal;

        location / {
            proxy_pass http://k8s_backend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_next_upstream error timeout http_502 http_503;
        }
    }
}
```

**Валидация:**
```bash
# Проверка разрешения через CoreDNS
dig @10.96.0.10 app-headless.production.svc.cluster.local +short
# → 10.244.1.45
# → 10.244.2.112
# → 10.244.3.78

# Проверка распределения в Angie
curl -s http://127.0.0.1/status/http/upstreams/k8s_backend/ | jq '.peers | keys'
# → [
# →   "10.244.1.45:8080",
# →   "10.244.2.112:8080",
# →   "10.244.3.78:8080"
# → ]
```

### Сценарий 6: Отказоустойчивая гибридная схема: динамический пул + статический backup

Защита от сценариев сбоя корпоративного DNS или аварии реестра Service Discovery. В нормальном режиме запросы обрабатываются динамическими бэкендами, но при их отказе трафик автоматически и бесшовно переключается на статический резервный кластер или локальную страницу-заглушку.

```nginx
http {
    resolver 192.168.10.2 valid=10s ipv6=off;
    resolver_timeout 2s;

    upstream critical_service {
        zone critical_service 128k;

        # Основной динамический пул серверов
        server backend.corp.internal:8080 resolve max_fails=2 fail_timeout=5s;

        # Статический резервный сервер (backup активируется только если все динамические пиры недоступны)
        server 192.168.99.10:8080 backup;
    }

    server {
        listen 80;
        server_name portal.corp.internal;

        location / {
            proxy_pass http://critical_service;
            proxy_http_version 1.1;
            proxy_set_header Host $host;

            # Переключение на следующий сервер при ошибках шлюза или таймаутах
            proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;
            proxy_next_upstream_tries 3;
            proxy_next_upstream_timeout 5s;

            # Локальный fallback если даже backup-сервер вернул ошибку
            error_page 502 503 504 = @service_unavailable;
        }

        location @service_unavailable {
            return 503 '{"error": "Service Temporarily Unavailable", "code": 503}\n';
            default_type application/json;
        }
    }
}
```

### Сценарий 7: Динамические апстримы L4 (TCP/UDP) в блоке `stream`

Динамическое масштабирование и Service Discovery применимы не только для HTTP, но и для уровня L4 (проксирование СУБД PostgreSQL, Redis, MySQL, LDAP).

**Конфигурация `/etc/angie/stream.d/postgres_balancing.conf`:**

```nginx
stream {
    resolver 192.168.10.2 valid=10s ipv6=off status_zone=stream_dns;
    resolver_timeout 2s;

    upstream pg_read_pool {
        zone pg_read_pool 128k;

        # Разрешение реплик PostgreSQL через DNS
        server pg-replicas.corp.internal:5432 resolve max_fails=3 fail_timeout=10s;
    }

    server {
        listen 5433;
        proxy_pass pg_read_pool;
        proxy_connect_timeout 3s;
        proxy_timeout 1h;
    }
}
```

**Валидация:**
```bash
# Проверка L4 upstream через Status API
curl -s http://127.0.0.1/status/stream/upstreams/pg_read_pool/ | jq '.peers'
# → {
# →   "192.168.50.21:5432": {"state": "up", "connections": 12},
# →   "192.168.50.22:5432": {"state": "up", "connections": 10}
# → }
```

## Операции и команды

### Управление конфигурацией и процессами

```bash
# Проверка корректности синтаксиса перед перезагрузкой
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Безопасное применение изменений (Graceful Reload)
sudo systemctl reload angie

# Просмотр статуса службы
sudo systemctl status angie --no-pager

# Просмотр активных рабочих процессов (workers)
ps aux | grep "[a]ngie: worker"
# → angie     14201  0.0  0.4  54210 18400 ?  S  10:00  0:02 angie: worker process
# → angie     14202  0.0  0.4  54210 18380 ?  S  10:00  0:02 angie: worker process
```

### Диагностика разрешения DNS и SRV

```bash
# Тестирование прямого разрешения имени через целевой резолвер
dig @192.168.10.2 api.corp.internal A +short
# → 192.168.20.11
# → 192.168.20.12

# Проверка TTL записи (сравнение с параметром valid в Angie)
dig @192.168.10.2 api.corp.internal +nocmd +noall +answer
# → api.corp.internal.  30  IN  A  192.168.20.11

# Тестирование получения SRV-записи службы Consul/Nomad
dig @127.0.0.1 -p 8600 _http._tcp.web.service.consul SRV +noall +answer
# → _http._tcp.web.service.consul. 0 IN SRV 1 10 8080 node1.consul.
# → _http._tcp.web.service.consul. 0 IN SRV 1 10 8081 node2.consul.
```

### Диагностика интеграции с Docker API

```bash
# Проверка доступности сокета Docker Engine
sudo -u angie curl -s --unix-socket /var/run/docker.sock http://localhost/_ping
# → OK

# Поиск запущенных контейнеров с метками для конкретного upstream
docker ps --filter "label=angie.http.upstreams.billing_pool.port" \
  --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Labels}}"

# Просмотр сетевых параметров контейнера и принадлежности к сетям
docker inspect <container_id> --format '{{json .NetworkSettings.Networks}}' | jq .

# Отслеживание потока событий контейнеров в реальном времени
docker events --filter 'type=container' --filter 'event=start' --filter 'event=die'
```

### Мониторинг и инспекция через Status API

```bash
# Список всех активных HTTP upstreams
curl -s http://127.0.0.1/status/http/upstreams/ | jq 'keys'
# → [
# →   "billing_pool",
# →   "internal_api",
# →   "payment_backends"
# → ]

# Сводный отчет по пирам конкретного пула (адрес, статус, вес, число активных запросов)
curl -s http://127.0.0.1/status/http/upstreams/internal_api/ | \
  jq '.peers | to_entries[] | {peer: .key, state: .value.state, weight: .value.weight, active: .value.active}'

# Мониторинг метрик встроенного DNS-резолвера
curl -s http://127.0.0.1/status/resolvers/dns_resolver_zone/ | jq .
# → {
# →   "queries": {"A": 12450, "AAAA": 0, "SRV": 0},
# →   "responses": {"noerror": 12448, "nxdomain": 0, "servfail": 2, "timedout": 0}
# → }
```

### Управление файлами состояния (`state`)

```bash
# Просмотр текущего сгенерированного файла состояния
cat /var/lib/angie/state/payment_backends.conf
# → server 192.168.10.15:8080 weight=2 max_conns=150 max_fails=1 fail_timeout=10s;
# → server 192.168.10.16:8080 weight=1 max_conns=0 max_fails=1 fail_timeout=10s;

# Проверка прав доступа к файлу и каталогу состояния
ls -ld /var/lib/angie/state
# → drwxr-x--- 2 angie angie 4096 Oct 14 12:00 /var/lib/angie/state

ls -la /var/lib/angie/state/payment_backends.conf
# → -rw-r----- 1 angie angie 178 Oct 14 12:05 /var/lib/angie/state/payment_backends.conf

# Создание резервной копии перед регламентными работами
sudo -u angie cp /var/lib/angie/state/payment_backends.conf \
  /var/lib/angie/state/payment_backends.conf.bak.$(date +%F_%H%M%S)
```

## Устранение неисправностей

### 1. Серверы не добавляются в upstream при запуске

**Симптомы:** Запросы к сайту возвращают `502 Bad Gateway`. Вывод `/status/http/upstreams/<name>/peers` пуст или содержит только статические серверы. В `error.log` нет записей об обнаружении.

**Диагностика:**
```bash
# 1. Проверка наличия директивы zone
grep -rn "upstream" /etc/angie/ | grep -A 2 "{"
# Если внутри блока upstream отсутствует zone <name> <size>, динамические механизмы отключены

# 2. Проверка сообщений об ошибках парсинга
sudo tail -n 50 /var/log/angie/error.log | grep -E "upstream|resolver|docker"
```

**Решение:**
1.  Обязательно добавьте директиву `zone <upstream_name> 64k;` (или большего размера) первой строкой внутри блока `upstream`.
2.  Для разрешения DNS убедитесь, что директива `resolver` объявлена на уровне `http` или текущего `server`.
3.  Для Docker убедитесь, что объявлена директива `docker_endpoint unix:/var/run/docker.sock;` в блоке `http`.

---

### 2. Задержки DNS-разрешения и зависания из-за запросов IPv6

**Симптомы:** При перезагрузке или смене IP бэкенда в логах появляются ошибки:
```text
[error] 1234#1234: send() failed (111: Connection refused) while resolving
[warn] 1234#1234: host "api.corp.internal" was not resolved: server error (timed out)
```
Время ответа клиентам периодически подскакивает на 2–5 секунд.

**Причина:** По умолчанию резолвер Angie выполняет параллельные запросы типов A (IPv4) и AAAA (IPv6). Если во внутренней сети IPv6 не настроен или DNS-сервер игнорирует AAAA-запросы без ответа, резолвер ожидает истечения `resolver_timeout`.

**Решение:**
Добавьте параметр `ipv6=off` в директиву `resolver`:
```nginx
resolver 192.168.10.2 valid=10s ipv6=off;
resolver_timeout 2s;
```

---

### 3. Ошибка доступа к сокету Docker: `permission denied`

**Симптомы:** В `error.log` фиксируется сообщение:
```text
[crit] 14201#14201: connect() to unix:/var/run/docker.sock failed (13: Permission denied) while connecting to docker daemon
```

**Диагностика:**
```bash
# Проверка прав на сокет Docker
ls -la /var/run/docker.sock
# → srw-rw---- 1 root docker 0 Oct 14 09:00 /var/run/docker.sock

# Проверка групп пользователя angie
groups angie
# → angie : angie (группа docker отсутствует!)
```

**Решение:**
1.  Включите пользователя `angie` в группу `docker`:
    ```bash
    sudo usermod -aG docker angie
    ```
2.  Перезапустите службу Angie, так как смена групп не применяется к уже работающим процессам:
    ```bash
    sudo systemctl restart angie
    ```
3.  При включенном SELinux (RHEL/AlmaLinux) создайте разрешающее правило:
    ```bash
    sudo setsebool -P daemons_enable_cluster_mode 1
    ```

---

### 4. Контейнеры Docker не подхватываются или выбирается неверный IP-адрес

**Симптомы:** Контейнеры запущены, но в upstream не попадают, либо запросы уходят на недоступные адреса подсети `bridge` вместо выделенной сети.

**Диагностика:**
```bash
# Проверка точного совпадения имени upstream в метке
# Метка контейнера: angie.http.upstreams.<имя>.port
# Конфиг Angie:     upstream <имя> { ... }
docker inspect <container_id> --format '{{json .Config.Labels}}' | jq .

# Проверка сетей, к которым подключен контейнер
docker inspect <container_id> --format '{{json .NetworkSettings.Networks}}' | jq 'keys'
```

**Решение:**
1.  Имя upstream в конфиге должно посимвольно совпадать с фрагментом имени метки: для `upstream app_pool` метка обязана быть `angie.http.upstreams.app_pool.port=8080`.
2.  Если контейнер подключен к нескольким сетям Docker (например, `backend_net` и `monitoring_net`), явно укажите целевую маршрутизируемую сеть через метку `angie.network`:
    ```yaml
    labels:
      - "angie.http.upstreams.app_pool.port=8080"
      - "angie.network=backend_net"
    ```

---

### 5. Переполнение буфера объектов Docker при большом числе контейнеров

**Симптомы:** В `error.log` появляется ошибка:
```text
[error] 14201#14201: docker response too large: buffer size 32768 exceeded
```
Часть контейнеров перестает отслеживаться.

**Причина:** По умолчанию внутренний буфер парсинга ответа Docker API ограничен 32 КБ. При наличии сотен запущенных контейнеров JSON-ответ с описанием состояния и меток превышает лимит.

**Решение:**
Увеличьте значение директивы `docker_max_object_size` в блоке `http`:
```nginx
http {
    docker_endpoint unix:/var/run/docker.sock;
    docker_max_object_size 512k;
    ...
}
```

---

### 6. Ошибки сохранения файла состояния (`state`): `Permission denied`

**Симптомы:** При добавлении серверов через API или при `systemctl reload angie` в логах появляется ошибка:
```text
[crit] 14201#14201: open() "/var/lib/angie/state/dynamic.conf.tmp" failed (13: Permission denied)
```
После перезапуска Angie все динамически добавленные серверы исчезают.

**Решение:**
1.  Создайте каталог состояния, если он отсутствует, и назначьте владельцем пользователя `angie`:
    ```bash
    sudo mkdir -p /var/lib/angie/state
    sudo chown -R angie:angie /var/lib/angie/state
    sudo chmod 750 /var/lib/angie/state
    ```
2.  Убедитесь, что дисковый раздел не заполнен на 100%:
    ```bash
    df -h /var/lib/angie
    ```

---

### 7. Нехватка памяти зоны: `could not allocate shared memory zone`

**Симптомы:**
```text
[emerg] 14200#14200: could not allocate shared memory zone "internal_api"
[error] 14201#14201: ngx_slab_alloc() failed: no memory in shared memory zone "internal_api"
```
Новые серверы не добавляются через DNS resolve или API.

**Решение:**
Увеличьте размер зоны в блоке upstream (например, с `64k` до `256k` или `1m`):
```nginx
upstream internal_api {
    zone internal_api 256k;
    server api.corp.internal:8080 resolve;
}
```
После изменения размера зоны требуется перезапуск или перезагрузка (`systemctl reload angie`).

## Лучшие практики

### Архитектура и надежность

*   **Таймаут и частота DNS-запросов:** Настраивайте `resolver_timeout` в диапазоне `2s`–`3s`, а интервал перепроверки `valid` — от `5s` до `15s`. Избегайте экстремально низких значений `valid` (1–2 сек), чтобы не создавать избыточную нагрузку на корпоративные DNS-серверы при десятках рабочих процессов Angie.
*   **Гибридный fallback:** В критичных контурах всегда сопровождайте динамический пул статическим сервером с флагом `backup` (Сценарий 6). Это гарантирует доступность сервиса при аварии контроллеров DNS или реестров Service Discovery.
*   **Изоляция зон памяти:** Создавайте отдельную зону `zone` для каждого логического сервиса. Не объединяйте разнородные бэкенды в одну зону: переполнение одной зоны или сбой ее блокировки не должны затрагивать соседние сервисы.
*   **Защита от каскадных сбоев:** Задавайте параметры `max_fails` и `fail_timeout` для каждого динамического пула, чтобы своевременно исключать зависшие бэкенды из балансировки.

### Эксплуатация и SRE

*   **Плавный вывод из эксплуатации (Drain):** Перед остановкой или обновлением ноды с приложением переводите ее в статус `drain` через API (Angie PRO) либо средствами платформы оркестрации. Это позволяет дождаться завершения текущих пользовательских корзин/сессий без обрыва TCP-сокетов.
*   **Резервное копирование `state`:** Включите директорию `/var/lib/angie/state/` в планы резервного копирования инфраструктуры. Перед накатом обновлений конфигурации создавайте моментальный снимок файлов состояния.
*   **Мониторинг резолвера:** Настраивайте директиву `resolver` с параметром `status_zone` и экспортируйте метрики в Prometheus. Отслеживайте всплески кодов ответов `servfail` и `timedout`, предупреждая деградацию Service Discovery до падения приложений.

### Безопасность

*   **Изоляция сокета Docker:** Если Angie запускается в контейнере, не монтируйте сокет хоста `/var/run/docker.sock` в режиме записи. Используйте проксирующие сокет-демоны (например, `docker-socket-proxy`), разрешающие только GET-запросы к `/events` и `/containers/json`, либо выделяйте права на сокет минимально необходимому пользователю.
*   **Защита эндпоинтов `/config/` и `/status/`:** Никогда не публикуйте интерфейсы управления во внешнюю сеть. Привязывайте административный сервер к `127.0.0.1` или внутренней приватной подсети администрирования, используйте директивы `allow/deny`, mutual TLS (mTLS) и базовую аутентификацию `auth_basic`.
*   **Права на файлы состояния:** Назначайте права `0600` на файлы конфигурации в `/var/lib/angie/state/` и права `0750` на директорию, владельцем должен являться системный пользователь `angie`.

### Производительность

*   **Использование пула Keepalive:** Обязательно настраивайте директиву `keepalive` в блоках `upstream`. При динамическом разрешении DNS кэшированные соединения продолжают эффективно переиспользоваться, снижая нагрузку на CPU бэкендов при установлении TCP/TLS хэндшейков.
*   **Отключение IPv6 в чистых IPv4 сетях:** Директива `resolver ... ipv6=off;` экономит ровно 50% системных сетевых вызовов при опросе DNS и предотвращает блокировку пула по таймаутам несуществующих AAAA-записей.

### Ограничения и архитектурные нюансы

*   **Контейнеры с `network_mode: host`:** Модуль Docker Discovery регистрирует такие контейнеры с IP-адресом самого хоста Docker. Если несколько контейнеров на одном хосте используют режим `host`, возникнет коллизия адресов, если порты не уникальны.
*   **Приоритеты DNS SRV:** Angie преобразует числовые приоритеты (Priority) из SRV-записей в логику `primary` / `backup`. Серверы с наименьшим числом priority считаются основными; серверы с более высоким числом priority переводятся в статус `backup`. Веса (Weight) из SRV-записей транслируются напрямую в веса балансировки Angie.
*   **Несовместимость директивы `state` со статическими `server`:** Внутри блока `upstream`, где объявлена директива `state`, запрещено использовать директиву `server`. Начальный состав должен наполняться исключительно через API или Service Discovery.

## Дополнительная информация

### Сравнение методов Service Discovery в Angie

| Критерий | DNS A/AAAA (`resolve`) | DNS SRV (`service=...`) | Docker API (`docker_endpoint`) | REST API (Angie PRO) |
| :--- | :--- | :--- | :--- | :--- |
| **Необходимая версия** | Angie OSS / PRO | Angie OSS / PRO | Angie OSS / PRO | **Angie PRO** |
| **Передача порта** | Фиксированный в конфиге | **Динамический из SRV** | **Динамический из метки** | **Динамический из JSON** |
| **Передача весов/лимитов** | Статические в конфиге | Вес из SRV | **Все параметры из меток** | **Полное управление в JSON** |
| **Скорость реакции** | Задержка по `valid` (5–15с)| Задержка по `valid` (5–15с)| **Мгновенно (события)** | **Мгновенно (HTTP-вызов)** |
| **Точка отказа** | DNS-сервер | DNS-сервер / Consul | Локальный Docker сокет | Оркестратор / CI/CD агент |
| **Режим `drain`** | Нет | Нет | Нет | **Да (полная поддержка)** |

### Мониторинг ключевых метрик для SRE

При использовании динамических upstream критически важно настроить алертинг на следующие метрики Status API:
1.  **Число активных пиров в upstream:**
    Алерт при значении `peers == 0` или падении числа доступных бэкендов ниже критического порога (`state == "up"`).
2.  **Частота ошибок DNS-резолвера:**
    Отношение `responses.servfail + responses.timedout` к общему числу `queries.A`. Всплеск ошибок сигнализирует о деградации DNS и риске потери бэкендов по истечении кэша.
3.  **Переход серверов в `unhealthy`:**
    Мониторинг счетчика `fails` и статуса доступности каждого пира.

## См. также

*   **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — алгоритмы балансировки (round-robin, least_conn, hash), пассивные и активные проверки доступности.
*   **[Балансировка и проксирование L4 (TCP/UDP)](./l4_balancing_and_proxying.md)** — динамические upstream в контексте модуля `stream` для кластеров баз данных и очередей сообщений.
*   **[Мониторинг Angie — API](./angie_monitoring/angie_monitoring_api.md)** — описание эндпоинтов `/status/http/upstreams/` и `/status/resolvers/`.
*   **[Мониторинг Angie PRO — расширенные возможности](./angie_monitoring/angie_monitoring_pro.md)** — подробная спецификация конфигурационного REST API (`/config/`), операции над upstream и keyval-хранилищами.
*   **[Обзор Service Discovery](../../Concepts/service-discovery-overview.md)** — теоретические основы обнаружения сервисов, сравнение серверной и клиентской моделей.
