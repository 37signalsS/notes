# Nginx как обратный прокси для Consul

**Актуально для:** Nginx 1.26.x (Stable) / 1.28.x (Mainline), Consul 1.19.x – 2.0.x, consul-template 0.39.x

## Определения

**Nginx как обратный прокси для Consul** — архитектурный сценарий развёртывания, при котором Nginx выступает централизованной точкой входа (reverse proxy) для веб-интерфейса (UI) и HTTP API кластера Consul. Это обеспечивает SSL/TLS-терминацию, сегментацию сетевого доступа, балансировку нагрузки между серверами Consul с автоматическим обходом сбойных узлов, защиту от флуда и сокрытие внутренней топологии кластера.

*   **[Обратный прокси (Reverse Proxy)](../../../Networking/Concepts/proxy.md)** — сервер-посредник, принимающий клиентские запросы и распределяющий их между серверами бэкенда с обработкой протоколов L7.
*   **[Consul UI](../../../Consul/consul_ui_administration.md)** — встроенное в бинарный файл Consul одностраничное веб-приложение (SPA на Ember.js) для визуального мониторинга сервисов, узлов, KV-хранилища, ACL и топологии Service Mesh.
*   **Consul HTTP API** — интерфейс для Service Discovery, регистрации сервисов, чтения KV и управления состоянием кластера. По умолчанию слушает порт `8500` (HTTP) или `8501` (HTTPS/mTLS).
*   **Upstream Connection Pooling (`keepalive`)** — механизм Nginx для переиспользования открытых TCP-соединений с бэкендами, снижающий задержки рукопожатий и нагрузку на TCP-стек серверов Consul.
*   **Long Polling / Blocking Queries** — базовый механизм Consul API, при котором HTTP-запрос клиента «удерживается» сервером в ожидании изменения данных (параметр `index`) вплоть до истечения таймаута (параметр `wait`, по умолчанию до 5–10 минут). Требует согласованной настройки таймаутов чтения в Nginx.
*   **Consul-template** — системный демон HashiCorp, подписывающийся на обновления каталога или KV Consul и автоматически рендерящий конфигурационные файлы на диске с последующей отправкой сигнала процессу (например, `nginx -s reload`).
*   **[Динамическое разрешение DNS (Dynamic DNS)](../Proxy/Load_Balancing/dynamic_dns_resolution.md)** — механизм Nginx (директивы `resolver` и `resolve` внутри `upstream`), позволяющий периодически разрешать доменные имена бэкендов в рантайме без перезагрузки процессов.
*   **Пассивные проверки доступности (Passive Health Checks)** — механизм Nginx OSS (`max_fails`, `fail_timeout`, `proxy_next_upstream`), отслеживающий сбои реальных клиентских запросов и временно исключающий сбойный сервер из пула балансировки.

> Подробная архитектура самого кластера Consul (Raft, Gossip, агенты, серверы, кворум) описана в **[Обзор Consul](../../../Consul/consul_overview.md)** и **[Архитектура Consul](../../../Consul/consul_architecture.md)**.

## Базовые концепции и архитектура

### Архитектура решения

```
Клиент (Браузер / API / CI/CD)
             │
             ▼ HTTPS (443) [TLS 1.3, Rate Limit, Auth, Security Headers]
┌────────────────────────────────────────────────────────┐
│                      Nginx Proxy                       │
│  (Терминация TLS, маршрутизация /ui и /v1, failover)   │
└────────────┬───────────────────┬───────────────────┬───┘
             │                   │                   │
  HTTP:8500 /│        HTTP:8500 /│        HTTP:8500 /│
  HTTPS:8501 │        HTTPS:8501 │        HTTPS:8501 │
             ▼                   ▼                   ▼
┌──────────────────┐┌──────────────────┐┌──────────────────┐
│  Consul Server 1 ││  Consul Server 2 ││  Consul Server 3 │
│     (Leader)     ││    (Follower)    ││    (Follower)    │
│  LAN Gossip 8301 ││  LAN Gossip 8301 ││  LAN Gossip 8301 │
│  Raft RPC  8300  ││  Raft RPC  8300  ││  Raft RPC  8300  │
└──────────────────┘└──────────────────┘└──────────────────┘
```

Nginx размещается перед узлами управления Consul и решает следующие инфраструктурные задачи:

1. **Терминация SSL/TLS и изоляция шифрования:** Клиенты взаимодействуют с единым доверенным SSL-сертификатом. Nginx завершает публичный TLS и может обращаться к серверам Consul либо по открытому HTTP внутри изолированного защищённого периметра (порт 8500), либо через внутренний mTLS с проверкой корпоративного CA (порт 8501).
2. **Балансировка нагрузки и отказоустойчивость:** Распределение трафика по пулу серверов кластера (обычно 3 или 5 узлов). При отказе лидера или плановом перезапуске сервера Nginx автоматически переключает запросы на соседние узлы через `proxy_next_upstream`, исключая отдачу клиентам кодов `502 Bad Gateway`.
3. **Сегментация и защита API:**
   - Ограничение доступа к административным и потенциально деструктивным эндпоинтам (`/v1/agent/`, `/v1/operator/`, `/v1/acl/`) по доверенным IP-подсетям (management network) и через Basic Auth.
   - Защита от флуда и зациклившихся polling-скриптов с помощью зон `limit_req_zone`.
   - Внедрение заголовков безопасности браузера (`Strict-Transport-Security`, `X-Frame-Options`, `X-Content-Type-Options`).
4. **Поддержка долгоживущих Blocking Queries:** Настройка увеличенных таймаутов чтения (`proxy_read_timeout`), чтобы предотвратить обрыв долгих HTTP-соединений со стороны прокси.
5. **Централизованный аудит и мониторинг:** Сбор логов доступа с фиксацией IP-клиента, времени отклика бэкенда (`$upstream_response_time`), статуса апстрима (`$upstream_status`) и экспорт метрик для Prometheus.

### Жизненный цикл запроса и распределение ролей Consul

1. **Получение запроса:** Клиент отправляет запрос к `consul.example.com` (порт 443).
2. **TLS и первичная фильтрация:** Nginx производит TLS-рукопожатие, проверяет IP-адрес клиента по спискам доступа (`allow`/`deny`), валидирует лимиты частоты запросов (`limit_req`).
3. **Маршрутизация:**
   - Точный запрос к корню `/` перенаправляется на `/ui/` кодом `301 Moved Permanently`.
   - Запросы к `/ui/` направляются к статическим ассетам веб-интерфейса.
   - Запросы к `/v1/` маршрутизируются к HTTP API Consul.
4. **Выбор апстрима и передача запроса:**
   - Nginx выбирает сервер из пула (по умолчанию round-robin или least_conn).
   - В соединении переиспользуется открытый TCP-сокет из пула `keepalive`.
   - Передаются служебные заголовки `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`. При наличии токена клиента сохраняется оригинальный заголовок `X-Consul-Token`.
5. **Обработка в кластере Consul:**
   - **Чтение (GET):** Любой сервер кластера (лидер или фолловер) способен вернуть данные из локального состояния Raft (в зависимости от уровня согласованности `stale`, `default` или `consistent`).
   - **Запись (PUT, POST, DELETE):** Если запрос на изменение KV или регистрацию сервиса поступил на фолловер, узел Consul автоматически форвардит операцию на текущего Raft-лидера через внутренний порт RPC `8300`.
6. **Возврат ответа и обработка сбоев:**
   - Если выбранный сервер возвращает ошибку соединения или таймаут, Nginx мгновенно перенаправляет запрос на следующий сервер из группы (при активном `proxy_next_upstream`).
   - Ответ возвращается клиенту с добавлением заголовков безопасности.

### Специфика Blocking Queries и долгоживущих соединений

Consul активно использует механизм **Blocking Queries** для мгновенной доставки обновлений агентам, consul-template и интерфейсу UI:

- Клиент передаёт GET-запрос с GET-параметрами `?index=<Last-Raft-Index>&wait=<Duration>`.
- Если с момента переданного индекса данные не изменились, сервер Consul не отвечает сразу, а удерживает HTTP-соединение открытым до тех пор, пока данные не изменятся, либо пока не истечёт время `wait` (Consul ограничивает максимальный интервал `wait` значением 10 минут, дефолтное клиентское значение обычно составляет 5 минут).
- По умолчанию в Nginx директива `proxy_read_timeout` равна `60s`. Если не увеличить этот таймаут в конфигурации Nginx, прокси будет принудительно обрывать блокирующий запрос через 60 секунд ошибкой `504 Gateway Time-out`.
- **Правило расчёта таймаута:** `proxy_read_timeout` в Nginx должен быть строго больше максимального времени `wait`, используемого клиентами, с запасом на сетевую задержку:
  $$\text{proxy\_read\_timeout} \ge \text{wait\_max} + 10\text{s}$$
  Для стандартного ожидания в 5 минут (300 секунд) задаётся минимум `310s`. Для максимального ожидания в 10 минут (600 секунд) задаётся `630s`.

### Специфика веб-интерфейса (Ember.js SPA)

Веб-интерфейс Consul представляет собой Single Page Application, вкомпилированное в бинарник Consul. Статические файлы (`vendor.js`, `consul-ui.css`) загружаются браузером по относительным путям относительно базового префикса `/ui/`:

- Если запрос обращается к `/ui` (без завершающего слэша), относительные ссылки на CSS и JS в коде страницы могут интерпретироваться браузером относительно корня `/`, что приводит к ошибкам 404 на статику и «белому экрану».
- Nginx должен строго гарантировать наличие слэша при обращении к интерфейсу через безусловный редирект корня `=` `/` на `/ui/`.
- Размещение Consul UI в подпутях (sub-path, например `example.com/services/consul/ui/`) без изменения конфигурации самого Consul (`ui_config.content_path`) приводит к поломке вызовов API Ember-приложением. Рекомендуется использовать для Consul выделенный виртуальный хост (например, `consul.infra.internal`).

---

## Практические сценарии

### Предварительные требования

| Компонент | Требование | Назначение / Обоснование |
| :--- | :--- | :--- |
| **ОС** | Debian 12 / Ubuntu 22.04, 24.04 / RHEL 9, Rocky Linux 9 | Базовые платформы без привязки к облачным сервисам |
| **Nginx** | Версия 1.26+ (Stable) или 1.28+ (Mainline) | Поддержка директивы `http2 on;`, `proxy_ssl_*` и пулов `keepalive` |
| **Consul** | Кластер 1.19+ – 2.0+ (3 или 5 серверов) | Порт `8500` (HTTP) или `8501` (HTTPS) доступен с хоста Nginx |
| **consul-template** | Версия 0.39+ | Для сценария динамической генерации апстрима |
| **Сеть** | Внутренняя сеть (LAN / VLAN) между Nginx и Consul | Доступ к TCP-портам `8500`/`8501`, а также `8600` (Consul DNS при необходимости) |
| **DNS** | Запись `consul.infra.internal` направлена на IP Nginx | Разрешение в локальном DNS (Bind9, Unbound или `/etc/hosts`) |

**Проверка исходного состояния системы:**

```bash
# Проверка версии Nginx
nginx -v
# → nginx version: nginx/1.26.2

# Проверка сетевой доступности серверов Consul с хоста Nginx
curl -s http://10.0.1.10:8500/v1/status/leader
# → "10.0.1.10:8300"

curl -s http://10.0.1.11:8500/v1/status/leader
# → "10.0.1.10:8300"

curl -s http://10.0.1.12:8500/v1/status/leader
# → "10.0.1.10:8300"
```

---

### Сценарий 1: Отказоустойчивый прокси со статическим upstream (HTTP бэкенд)

Сценарий подходит для инфраструктур с фиксированным набором серверов Consul в изолированном сегменте безопасности.

#### Шаг 1: Конфигурация пула upstream

Создайте файл `/etc/nginx/conf.d/consul_upstream.conf`:

```nginx
upstream consul_servers {
    # Алгоритм балансировки: least_conn предотвращает перегрузку узла долгими polling-запросами
    least_conn;

    # Серверы кластера Consul с параметрами пассивного контроля сбоев
    server 10.0.1.10:8500 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8500 max_fails=3 fail_timeout=10s;
    server 10.0.1.12:8500 max_fails=3 fail_timeout=10s;

    # Пул постоянных TCP-соединений к апстримам
    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}
```

#### Шаг 2: Конфигурация виртуального хоста

Создайте файл `/etc/nginx/conf.d/consul.infra.internal.conf`:

```nginx
# Перенаправление с HTTP на HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name consul.infra.internal;

    location / {
        return 301 https://$host$request_uri;
    }
}

# Основной защищённый виртуальный хост
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name consul.infra.internal;

    # Синтаксис Nginx 1.25.1+ для включения HTTP/2
    http2 on;

    # Сертификаты для клиентов (Let's Encrypt или внутренний CA)
    ssl_certificate     /etc/ssl/certs/consul.infra.internal.crt;
    ssl_certificate_key /etc/ssl/private/consul.infra.internal.key;

    # Настройки SSL/TLS
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL_CONSUL:10m;
    ssl_session_tickets off;

    # Заголовки безопасности
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    # Общие параметры проксирования
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Защита от сбоев апстрима: мгновенное переключение при падении узла
    proxy_next_upstream error timeout http_500 http_502 http_503 http_504;
    proxy_next_upstream_timeout 10s;
    proxy_next_upstream_tries 3;

    # Таймауты: учет Long Polling / Blocking Queries (5m default wait + 10s buffer)
    proxy_connect_timeout 5s;
    proxy_send_timeout 60s;
    proxy_read_timeout 310s;

    # Буферизация: оставляем включенной для статики UI, отключаем для long-polling API при необходимости
    proxy_buffers 8 16k;
    proxy_buffer_size 16k;

    # Точный редирект корня на UI
    location = / {
        return 301 /ui/;
    }

    # Обслуживание Consul UI
    location /ui/ {
        proxy_pass http://consul_servers;
    }

    # Общий доступ к Consul HTTP API
    location /v1/ {
        proxy_pass http://consul_servers;
    }

    # Ограничение доступа к критическим административным операторам
    location /v1/operator/ {
        allow 10.0.0.0/8;       # Корпоративная сеть управления
        allow 127.0.0.1;
        deny all;

        proxy_pass http://consul_servers;
    }

    # Ограничение доступа к управлению локальными агентами
    location /v1/agent/ {
        allow 10.0.0.0/8;
        allow 127.0.0.1;
        deny all;

        proxy_pass http://consul_servers;
    }
}
```

#### Шаг 3: Валидация и применение

```bash
# Проверка корректности конфигурации Nginx
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Безопасная перезагрузка воркеров Nginx
sudo systemctl reload nginx

# Проверка редиректа с корня
curl -k -I https://consul.infra.internal/
# → HTTP/2 301 
# → location: /ui/

# Проверка ответа Consul UI
curl -k -s -o /dev/null -w "%{http_code}\n" https://consul.infra.internal/ui/
# → 200

# Проверка чтения лидера кластера через прокси
curl -k -s https://consul.infra.internal/v1/status/leader
# → "10.0.1.10:8300"
```

---

### Сценарий 2: Защищённый бэкенд с mTLS к серверам Consul (порт 8501)

В защищённых zero-trust средах серверы Consul настраиваются на обязательный взаимный TLS (порт `8501`). Nginx должен верифицировать сертификаты серверов Consul и предоставлять собственный клиентский сертификат.

```
Nginx [Client Cert / Key] ──── mTLS:8501 (CA check) ────► Consul Server:8501
```

#### Шаг 1: Конфигурация HTTPS-апстрима

Создайте файл `/etc/nginx/conf.d/consul_mtls_upstream.conf`:

```nginx
upstream consul_secure_servers {
    least_conn;

    server 10.0.1.10:8501 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8501 max_fails=3 fail_timeout=10s;
    server 10.0.1.12:8501 max_fails=3 fail_timeout=10s;

    keepalive 32;
}
```

#### Шаг 2: Настройка TLS-параметров бэкенда в блоке server/location

В файле `/etc/nginx/conf.d/consul.infra.internal.conf` замените параметры передачи на защищённый бэкенд:

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name consul.infra.internal;
    http2 on;

    ssl_certificate     /etc/ssl/certs/consul.infra.internal.crt;
    ssl_certificate_key /etc/ssl/private/consul.infra.internal.key;

    # mTLS параметры для подключения Nginx к бэкенду Consul
    proxy_ssl_certificate         /etc/nginx/ssl/consul-proxy-client.crt;
    proxy_ssl_certificate_key     /etc/nginx/ssl/consul-proxy-client.key;
    proxy_ssl_trusted_certificate /etc/nginx/ssl/consul-agent-ca.pem;
    proxy_ssl_verify              on;
    proxy_ssl_verify_depth        2;
    proxy_ssl_protocols           TLSv1.2 TLSv1.3;
    proxy_ssl_server_name         on;
    proxy_ssl_name                server.dc1.consul;

    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_read_timeout 310s;

    location = / {
        return 301 /ui/;
    }

    location / {
        proxy_pass https://consul_secure_servers;
    }
}
```

#### Шаг 3: Проверка защищённого рукопожатия

```bash
# Валидация прав доступа на клиентский ключ Nginx
sudo ls -l /etc/nginx/ssl/consul-proxy-client.key
# → -rw-r----- 1 root www-data 1679 Oct 17 12:00 /etc/nginx/ssl/consul-proxy-client.key

sudo nginx -t && sudo systemctl reload nginx
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Проверка API через mTLS-прокси
curl -k -s https://consul.infra.internal/v1/status/peers
# → ["10.0.1.10:8300","10.0.1.11:8300","10.0.1.12:8300"]
```

---

### Сценарий 3: Динамический upstream через consul-template

При динамическом масштабировании или ротации серверов Consul ручное редактирование `nginx.conf` заменяется демоном `consul-template`. Он опрашивает каталог Consul и рендерит список серверов.

#### Шаг 1: Установка consul-template

```bash
# Установка на Debian/Ubuntu (из официального репозитория HashiCorp)
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update && sudo apt-get install -y consul-template

# Проверка версии
consul-template --version
# → consul-template v0.39.0 (built ...)
```

#### Шаг 2: Создание шаблона с защитой от пустого апстрима

В Consul все серверные ноды автоматически регистрируются в системном сервисе с именем `consul`.

Создайте файл `/etc/consul-template/templates/consul_upstream.ctmpl`:

```go-template
# Автоматически сгенерировано consul-template. Не редактировать вручную.
upstream consul_dynamic_servers {
    least_conn;

{{- range service "consul" }}
    server {{ .Address }}:{{ .Port }} max_fails=3 fail_timeout=10s;
{{- else }}
    # Защитный fallback: если каталог временно недоступен или пуст,
    # перенаправляем на локальный сокет, чтобы Nginx не падал при синтаксической проверке
    server 127.0.0.1:8500 backup;
{{- end }}

    keepalive 32;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}
```

#### Шаг 3: Настройка конфигурации consul-template

Создайте `/etc/consul-template/config.hcl`:

```hcl
consul {
  # Локальный агент Consul или конкретный сервер
  address = "127.0.0.1:8500"
  retry {
    enabled = true
    attempts = 5
    backoff = "250ms"
  }
}

template {
  source      = "/etc/consul-template/templates/consul_upstream.ctmpl"
  destination = "/etc/nginx/conf.d/consul_dynamic_upstream.conf"
  # Валидация перед перезагрузкой: reload вызывается только если nginx -t завершился успешно
  command     = "nginx -t && systemctl reload nginx"
  perms       = 0644
}
```

#### Шаг 4: Настройка systemd-сервиса

Создайте `/etc/systemd/system/consul-template.service`:

```ini
[Unit]
Description=Consul Template for Nginx
After=network.target consul.service
Wants=consul.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/consul-template -config=/etc/consul-template/config.hcl
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
KillMode=process
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
# Активация и старт сервиса
sudo systemctl daemon-reload
sudo systemctl enable --now consul-template

# Проверка статуса
sudo systemctl status consul-template
# → Active: active (running) since ...

# Проверка сгенерированного файла конфигурации
cat /etc/nginx/conf.d/consul_dynamic_upstream.conf
# → # Автоматически сгенерировано consul-template. Не редактировать вручную.
# → upstream consul_dynamic_servers {
# →     least_conn;
# →     server 10.0.1.10:8500 max_fails=3 fail_timeout=10s;
# →     server 10.0.1.11:8500 max_fails=3 fail_timeout=10s;
# →     server 10.0.1.12:8500 max_fails=3 fail_timeout=10s;
# →     keepalive 32;
# →     keepalive_requests 1000;
# →     keepalive_timeout 60s;
# → }
```

---

### Сценарий 4: Бездемонный динамический upstream через Consul DNS (Nginx 1.27.3+)

Начиная с Nginx 1.27.3 (Mainline) и в Nginx 1.30+ (Stable), директива `resolver` поддерживается непосредственно внутри блока `upstream`. Это позволяет обращаться к встроенному DNS-серверу Consul (порт `8600`) без использования сторонних демонов вроде `consul-template`.

```nginx
# /etc/nginx/conf.d/consul_dns_upstream.conf
upstream consul_dns_backend {
    # Зона разделяемой памяти обязательна при использовании параметра resolve
    zone consul_dns_backend 64k;

    # Опрос встроенного DNS Consul (127.0.0.1:8600) каждые 5 секунд
    resolver 127.0.0.1:8600 valid=5s;
    resolver_timeout 2s;

    # Стандартное доменное имя серверов Consul в DNS каталоге
    server consul.service.consul:8500 resolve;

    keepalive 32;
}

server {
    listen 443 ssl;
    server_name consul.infra.internal;
    http2 on;

    ssl_certificate     /etc/ssl/certs/consul.infra.internal.crt;
    ssl_certificate_key /etc/ssl/private/consul.infra.internal.key;

    location = / {
        return 301 /ui/;
    }

    location / {
        proxy_pass http://consul_dns_backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_read_timeout 310s;
    }
}
```

```bash
# Проверка разрешения домена серверов Consul через порт 8600
dig @127.0.0.1 -p 8600 consul.service.consul +short
# → 10.0.1.10
# → 10.0.1.11
# → 10.0.1.12
```

---

### Сценарий 5: Аутентификация, разграничение методов и защита API

Для сред, где доступ к UI должен быть защищён корпоративными учётными записями, а API разделено на безопасное чтение и защищённое администрирование.

#### Шаг 1: Создание учетных данных Basic Auth

```bash
# Установка утилиты htpasswd
sudo apt-get install -y apache2-utils

# Создание файла паролей
sudo htpasswd -c /etc/nginx/.htpasswd_consul_admin admin
# → New password: <ввод пароля>
# → Re-type new password: <повтор пароля>

sudo chmod 640 /etc/nginx/.htpasswd_consul_admin
sudo chown root:www-data /etc/nginx/.htpasswd_consul_admin
```

#### Шаг 2: Конфигурация виртуального хоста с защитой

```nginx
server {
    listen 443 ssl;
    server_name consul.infra.internal;
    http2 on;

    ssl_certificate     /etc/ssl/certs/consul.infra.internal.crt;
    ssl_certificate_key /etc/ssl/private/consul.infra.internal.key;

    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 310s;

    location = / {
        return 301 /ui/;
    }

    # Защита веб-интерфейса Basic Auth
    location /ui/ {
        auth_basic "Consul Management UI";
        auth_basic_user_file /etc/nginx/.htpasswd_consul_admin;

        proxy_pass http://consul_servers;
    }

    # Публичное или внутрисервисное чтение каталога и KV
    location /v1/ {
        # Запрещаем изменение данных (PUT, POST, DELETE) без авторизации
        limit_except GET HEAD {
            auth_basic "Consul API Write Access";
            auth_basic_user_file /etc/nginx/.htpasswd_consul_admin;
        }

        proxy_pass http://consul_servers;
    }

    # Полная блокировка чувствительных служебных эндпоинтов от внешнего периметра
    location ~* ^/v1/(agent|operator|acl|session)/ {
        satisfy all;

        # Разрешено только с доверенных Jump-хостов / подсетей управления
        allow 10.0.50.0/24;
        allow 127.0.0.1;
        deny all;

        auth_basic "Consul Cluster Operations";
        auth_basic_user_file /etc/nginx/.htpasswd_consul_admin;

        proxy_pass http://consul_servers;
    }
}
```

```bash
# Проверка попытки записи без пароля (ожидается 401 Unauthorized)
curl -k -s -o /dev/null -w "%{http_code}\n" -X PUT -d "test" https://consul.infra.internal/v1/kv/test
# → 401

# Проверка записи с авторизацией
curl -k -s -u admin:secret -X PUT -d "test" https://consul.infra.internal/v1/kv/test
# → true
```

---

### Сценарий 6: Защита от перегрузки (Rate Limiting) для Consul API

Некорректно написанные микросервисы или скрипты могут отправлять тысячи запросов в секунду к `/v1/kv/` или `/v1/catalog/`, вызывая деградацию Raft-машины состояний.

```nginx
# Зона лимитов: 10 МБ памяти (~160 000 IP-адресов), средняя скорость 50 запросов/сек на IP
limit_req_zone $binary_remote_addr zone=consul_api_limit:10m rate=50r/s;
limit_req_status 429;

server {
    listen 443 ssl;
    server_name consul.infra.internal;
    http2 on;

    ssl_certificate     /etc/ssl/certs/consul.infra.internal.crt;
    ssl_certificate_key /etc/ssl/private/consul.infra.internal.key;

    location /v1/ {
        # burst=100 допускает всплески, nodelay обрабатывает их сразу без задержек в очереди
        limit_req zone=consul_api_limit burst=100 nodelay;

        proxy_pass http://consul_servers;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_read_timeout 310s;
    }

    location /ui/ {
        # UI освобождается от жестких лимитов API
        proxy_pass http://consul_servers;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

---

### Сценарий 7: Мониторинг, метрики и структурированный аудит логов

Для SRE-команд критически важно отслеживать латентность ответов серверов Consul и выявлять узлы, отвечающие с задержкой.

#### Шаг 1: Настройка расширенного лог-формата Nginx

В блоке `http` файла `/etc/nginx/nginx.conf`:

```nginx
log_format consul_combined '$remote_addr - $remote_user [$time_local] '
                           '"$request" $status $body_bytes_sent '
                           '"$http_referer" "$http_user_agent" '
                           'rt=$request_time uct="$upstream_connect_time" '
                           'uht="$upstream_header_time" urt="$upstream_response_time" '
                           'upstream="$upstream_addr" ustatus="$upstream_status"';
```

В блоке `server`:

```nginx
access_log /var/log/nginx/consul_access.log consul_combined;
error_log  /var/log/nginx/consul_error.log warn;
```

#### Шаг 2: Включение stub_status для Prometheus Nginx Exporter

```nginx
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location /stub_status {
        stub_status on;
        allow 127.0.0.1;
        deny all;
    }
}
```

```bash
# Проверка отдачи метрик соединений
curl http://127.0.0.1:8080/stub_status
# → Active connections: 4 
# → server accepts handled requests
# →  142 142 284 
# → Reading: 0 Writing: 1 Waiting: 3
```

---

## Операции и команды

### Управление процессами Nginx и consul-template

| Действие | Команда | Назначение / Ожидаемый результат |
| :--- | :--- | :--- |
| **Проверка синтаксиса** | `sudo nginx -t` | Валидация всех конфигурационных файлов перед перезагрузкой |
| **Graceful Reload Nginx** | `sudo systemctl reload nginx` | Подхват новой конфигурации без обрыва текущих Long Polling сессий |
| **Однократный тест шаблона** | `consul-template -config=/etc/consul-template/config.hcl -once -dry-run` | Вывод сгенерированного upstream в stdout без записи на диск |
| **Перечитывание шаблонов** | `sudo systemctl reload consul-template` | Отправка сигнала SIGHUP демону для перечитывания шаблонов |
| **Мониторинг генератора** | `journalctl -u consul-template -f` | Просмотр событий изменения топологии серверов в реальном времени |

### Диагностика Consul API и Blocking Queries

```bash
# 1. Проверка доступности Raft-лидера через прокси
curl -k -s https://consul.infra.internal/v1/status/leader
# → "10.0.1.10:8300"

# 2. Проверка состава нод кластера
curl -k -s https://consul.infra.internal/v1/catalog/nodes | jq '.[].Node'
# → "server-01"
# → "server-02"
# → "server-03"

# 3. Тестирование механизма Blocking Query с ожиданием до 30 секунд
curl -k -v "https://consul.infra.internal/v1/kv/my-key?index=1&wait=30s"
# → < HTTP/2 200 
# → < x-consul-index: 1042
# → < x-consul-knownleader: true
# → [ответ задерживается до изменения ключа или истечения 30 секунд]
```

### Диагностика сетевых соединений и сокетов upstream

```bash
# Подсчет активных keepalive-соединений Nginx к порту Consul (8500)
ss -tnp | grep nginx | grep 8500 | grep ESTAB | wc -l
# → 6

# Анализ распределения запросов по конкретным нодам бэкенда из логов
awk -F'upstream="' '{print $2}' /var/log/nginx/consul_access.log | awk -F'"' '{print $1}' | sort | uniq -c | sort -rn
# → 1420 10.0.1.10:8500
# → 1398 10.0.1.11:8500
# → 1405 10.0.1.12:8500

# Поиск случаев срабатывания failover (несколько адресов через запятую в $upstream_addr)
grep -E 'upstream="[0-9\.\:]+, [0-9\.\:]+"' /var/log/nginx/consul_access.log | tail -n 5
# → 10.0.1.10:8500, 10.0.1.11:8500 ustatus="502, 200"
```

---

## Устранение неисправностей

| Ошибка / Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `504 Gateway Time-out` на вызовах API | `proxy_read_timeout` меньше, чем параметр `wait` клиента Consul | Проверьте параметр `wait` в запросе (например, `wait=5m` = 300s). Установите в Nginx `proxy_read_timeout 310s;` или `630s;`. |
| `502 Bad Gateway` при сбое одного узла Consul | Отсутствует директива `proxy_next_upstream` | Добавьте в блок `server`: `proxy_next_upstream error timeout http_502 http_503;` и `proxy_next_upstream_tries 3;`. |
| Предупреждение Nginx: `the "http2" parameter of the "listen" directive is deprecated` | Использование устаревшего синтаксиса `listen 443 ssl http2;` в Nginx 1.25.1+ | Замените на раздельные директивы: `listen 443 ssl;` и `http2 on;`. |
| `consul-template` падает: `empty upstream "..."` при старте Nginx | Шаблон сгенерировал блок `upstream` без единой строки `server` | Добавьте в `.ctmpl` блок `{{- else }} server 127.0.0.1:8500 backup; {{- end }}`. Задайте `command = "nginx -t && systemctl reload nginx"`. |
| Белый экран в Consul UI (ошибки 404 на `vendor.js`) | Отсутствует завершающий слэш в запросе к `/ui` | Добавьте строгий редирект корня: `location = / { return 301 /ui/; }`. Не используйте `if ($request_uri = "/")` внутри общего location. |
| Ошибка mTLS: `upstream SSL certificate verify error: (21:unable to verify the first certificate)` | Nginx не доверяет внутреннему CA Consul | Убедитесь, что в `proxy_ssl_trusted_certificate` указан корневой CA Consul кластера, а не публичный веб-сертификат. |
| `429 Too Many Requests` у легитимных клиентов | Слишком жёсткий лимит в `limit_req_zone` | Увеличьте `burst` (например, `burst=100 nodelay;`) или вынесите доверенные IP-адреса клиентов в `geo` / `map`-исключения. |
| `worker_connections are not enough` в `error.log` | Исчерпание лимита соединений из-за сотен зависших Blocking Queries | Увеличьте лимиты в `/etc/nginx/nginx.conf`: в блоке `events` `worker_connections 4096;`, в блоке `main` `worker_rlimit_nofile 65536;`. |
| `403 Forbidden` при вызове `/v1/agent/self` | Срабатывание директивы `deny all;` в блоке административного API | Проверьте реальный IP клиента в логах. При работе через промежуточные балансировщики настройте модуль `set_real_ip_from`. |

---

## Рекомендации и лучшие практики

### Безопасность (Hardening)

1. **Разграничение сетевых периметров:** Защищайте эндпоинты управления кластером (`/v1/agent/`, `/v1/operator/`, `/v1/acl/`). Доступ к ним должен быть разрешён только из внутренней подсети мониторинга и автоматизации.
2. **Изоляция шифрования:** Используйте протоколы TLS 1.2 и TLS 1.3 с безопасными наборами шифров. Отключайте устаревшие TLS 1.0 и 1.1.
3. **mTLS между Nginx и Consul:** Внутри дата-центра используйте шифрование трафика до портов `8501` серверов Consul с проверкой клиентских сертификатов Nginx (`proxy_ssl_verify on`).
4. **Скрытие серверных баннеров:** Задавайте `server_tokens off;` на уровне `http`, чтобы исключить утечку точной версии Nginx во внешнюю сеть.
5. **Безопасные заголовки браузера:** Всегда передавайте `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN` и HSTS.

### Надёжность и доступность (SRE)

6. **Отказоустойчивое переключение (`proxy_next_upstream`):** Всегда активируйте `proxy_next_upstream error timeout http_502 http_503;`. Это гарантирует прозрачное переключение клиента на рабочий узел в случае внезапного падения лидера или рестарта демона Consul.
7. **Алгоритм балансировки `least_conn`:** Для Consul `least_conn` предпочтительнее round-robin, так как блокирующие запросы (Blocking Queries) удерживают соединения по несколько минут. Алгоритм направляет новые запросы на сервер с наименьшим количеством открытых сокетов.
8. **Безопасная автоматизация consul-template:** Никогда не выполняйте безусловный перезапуск `nginx -s reload` из шаблонизатора без предварительной проверки `nginx -t`. Шаблон обязан содержать `{{- else }}` с резервным адресом `backup`.

### Производительность

9. **Пул соединений `keepalive` в upstream:** Всегда объявляйте `keepalive 32;` (или 64) в блоке `upstream` и сопровождайте его директивами `proxy_http_version 1.1;` и `proxy_set_header Connection "";`. Это предотвращает исчерпание эфемерных портов на хосте Nginx и устраняет оверхед на TCP/TLS handshake.
10. **Согласование таймаутов:** Задавайте `proxy_read_timeout` не менее `310s`. Для окружений с клиентами, запрашивающими 10-минутное удержание (`wait=10m`), увеличивайте таймаут до `630s`.
11. **Выделение файловых дескрипторов:** При обслуживании сотен клиентов Service Discovery установите `worker_rlimit_nofile 65536;` и `worker_connections 4096;` в главной конфигурации Nginx.

### Эксплуатация (SysAdmin)

12. **Валидация перед reload:** В регламентах обслуживания всегда используйте команду `nginx -t && systemctl reload nginx`. Graceful reload не прерывает активные долгие сессии клиентов.
13. **Ротация журналов:** Настройте регулярную ротацию логов через `logrotate` с директивой `postrotate` (`kill -USR1 $(cat /run/nginx.pid)`).
14. **Мониторинг задержек бэкендов:** Регулярно анализируйте значения `$upstream_response_time` в журналах доступа для заблаговременного выявления перегруженных нод Consul.

---

## Дополнительная информация

- **[Обзор Consul](../../../Consul/consul_overview.md)** — архитектура кластера, агенты, порты, протоколы Gossip и Raft.
- **[Архитектура Consul](../../../Consul/consul_architecture.md)** — консенсус Raft, роли узлов, кворум и жизненный цикл транзакций.
- **[Администрирование Consul UI](../../../Consul/consul_ui_administration.md)** — внутреннее устройство веб-интерфейса, OIDC SSO, конфигурация `ui_config`.
- **[KV-хранилище Consul](../../../Consul/consul_kv_store.md)** — работа с ключами, версионирование, транзакции и Blocking Queries.
- **[Rate Limiting в Consul](../../../Consul/consul_rate_limiting.md)** — внутренние механизмы лимитирования запросов Consul и фильтрация трафика.
- **[Динамическое разрешение DNS в Upstream](../Proxy/Load_Balancing/dynamic_dns_resolution.md)** — настройка параметров `resolve`, `zone` и `resolver` в современных версиях Nginx.
- **[Настройка Let's Encrypt с Nginx](./nginx_with_letsencrypt.md)** — автоматизация получения и обновления TLS-сертификатов.
- **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)** — системные настройки процессов, лимиты дескрипторов и структура конфигурации.
