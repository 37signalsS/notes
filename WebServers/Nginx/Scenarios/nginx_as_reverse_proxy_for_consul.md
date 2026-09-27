# Nginx как обратный прокси для Consul

## 1. Определения

**Nginx как обратный прокси для Consul** — сценарий развёртывания, при котором Nginx выступает единой точкой входа (reverse proxy) для доступа к веб-интерфейсу (UI) и HTTP API Consul. Это обеспечивает SSL/TLS-терминацию, централизованную аутентификацию и сокрытие внутренней инфраструктуры кластера.

*   **[Обратный прокси (Reverse Proxy)](../../../Networking/Concepts/proxy.md)** — сервер-посредник, принимающий запросы от клиентов и распределяющий их между серверами бэкенда.
*   **Consul UI** — графический интерфейс для управления сервисами, узлами, KV-хранилищем и политиками безопасности.
*   **Consul API** — основной интерфейс взаимодействия для Service Discovery и автоматизации (порт `8500` по умолчанию).
*   **Upstream** — группа бэкенд-серверов, за которыми Nginx выполняет балансировку.
*   **Long Polling / Blocking Queries** — механизм Consul, при котором запрос «зависает» до изменения данных или таймаута (до 5 минут). Требует специальной настройки тайм-аутов в Nginx.
*   **Consul-template** — утилита HashiCorp для подписки на изменения в Consul KV и автоматической регенерации конфигурационных файлов с последующим сигналом процессу (например, `nginx -s reload`).

> Основные понятия Consul (агенты, серверы, datacenter, Gossip, Raft) описаны в **[Обзор Consul](../../../Consul/consul_overview.md)** и **[Архитектура Consul](../../../Consul/consul_architecture.md)**.

## 2. Базовые концепции

### Архитектура решения

```
Клиент → [ Nginx (SSL termination, auth, logging) ] → [ Consul Server 1:8500 ]
                                                       [ Consul Server 2:8500 ]
                                                       [ Consul Server 3:8500 ]
```

Nginx размещается перед кластером Consul и выполняет следующие функции:

1. **Терминация SSL/TLS**: Вынос вычислительной нагрузки по шифрованию на Nginx. Один сертификат (Wildcard или Let's Encrypt) покрывает доступ к UI и API без необходимости настройки HTTPS на каждом узле Consul.
2. **Балансировка и отказоустойчивость**: Распределение запросов между всеми серверами кластера (обычно 3 или 5 узлов). При сбое узла Nginx автоматически переключает трафик на доступные инстансы.
3. **Управление доступом**:
    - Ограничение доступа к административному API (`/v1/agent/`, `/v1/operator/`) по IP-адресам или через Basic Auth.
    - Внедрение заголовков безопасности (HSTS, CSP, X-Frame-Options).
    - Передача токенов доступа через кастомные заголовки.
4. **Поддержка Long Polling**: Consul использует блокирующие запросы (Blocking Queries) с таймаутом до 5 минут. Nginx должен иметь соответствующие `proxy_read_timeout`, иначе соединения будут разрываться.
5. **Логирование и аудит**: Централизованный доступный лог всех обращений к UI/API с указанием upstream-узла, времени и результата.

### Жизненный цикл запроса

1. Клиент отправляет HTTPS-запрос на `consul.example.com`.
2. Nginx завершает TLS, проверяет заголовки и IP-клиента.
3. Nginx выбирает upstream-сервер по алгоритму round-robin (по умолчанию) или least_conn.
4. При наличии `keepalive` в upstream соединение с бэкендом переиспользуется.
5. Consul обрабатывает запрос и возвращает ответ.
6. Nginx передаёт ответ клиенту, добавляя заголовки безопасности.

### Специфика долгоживущих соединений

Consul активно использует **Blocking Queries** для моментального получения обновлений (например, при отслеживании изменений в KV). Запрос может «зависать» до 5 минут. Nginx по умолчанию имеет `proxy_read_timeout 60s`, поэтому требуется явное увеличение этого параметра.

Начиная с Consul 1.10+, для серверных компонентов доступен механизм **Streaming** (gRPC), снижающий количество долгих HTTP-соединений. Однако при проксировании HTTP API через Nginx Long Polling остаётся актуальным.

## 3. Практические сценарии

### 3.1. Предварительные требования

| Компонент | Требование | Примечание |
| :--- | :--- | :--- |
| **ОС** | Debian 12 (Bookworm), Ubuntu 22.04/24.04 (Jammy/Noble), RHEL/Rocky 9 | Другие дистрибутивы на основе Debian/RHEL также поддерживаются |
| **Nginx** | Версия 1.27+ | Рекомендуется `nginx-full` (Debian/Ubuntu) или `nginx-mod-http-perl` при необходимости |
| **Consul** | Версия 1.15+ (серверы) | Работает с любой версией, но 1.10+ рекомендуется для Streaming API |
| **Сеть** | Доступ от Nginx до порта `8500` на всех серверах Consul | При использовании TLS-интерфейса Consul — порт `8501` |
| **Права** | root или пользователь с правами sudo | Для управления Nginx и firewall |
| **DNS** | A-запись `consul.example.com` → IP-frontend Nginx | Или `/etc/hosts` для тестовых сред |

**Начальное состояние системы:**

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y nginx curl gnupg

# RHEL/Rocky
sudo dnf install -y nginx curl

# Проверка версии
nginx -v
# → nginx version: nginx/1.27.x

# Проверка доступности Consul извне (должен вернуть JSON)
curl -s http://10.0.1.10:8500/v1/status/leader
# → "10.0.1.10:8300"
```

### 3.2. Сценарий 1: Статический upstream (базовый)

Подходит для небольших кластеров с фиксированным набором серверов.

**Шаг 1: Создание upstream-файла**

`/etc/nginx/conf.d/consul_upstream.conf`:
```nginx
upstream consul_servers {
    keepalive 32;

    server 10.0.1.10:8500 max_fails=3 fail_timeout=10s;
    server 10.0.1.11:8500 max_fails=3 fail_timeout=10s;
    server 10.0.1.12:8500 max_fails=3 fail_timeout=10s;
}
```

`keepalive 32` поддерживает до 32 постоянных соединений к каждому бэкенду, снижая задержки и нагрузку на TCP-стек Consul.

**Шаг 2: Создание виртуального хоста**

`/etc/nginx/conf.d/consul.example.com.conf`:
```nginx
server {
    listen 80;
    listen [::]:80;
    server_name consul.example.com;

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name consul.example.com;

    ssl_certificate     /etc/letsencrypt/live/consul.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/consul.example.com/privkey.pem;

    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=63072000" always;

    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_read_timeout 310s;
    proxy_connect_timeout 5s;

    location / {
        proxy_pass http://consul_servers;

        if ($request_uri = "/") {
            return 301 /ui/;
        }
    }

    location /v1/agent {
        allow 10.0.0.0/24;
        deny all;
        proxy_pass http://consul_servers;
    }

    location /v1/operator {
        allow 10.0.0.0/24;
        deny all;
        proxy_pass http://consul_servers;
    }
}
```

> Обратите внимание: синтаксис `listen 443 ssl http2;` является актуальным для Nginx 1.25+. Устаревший вариант `http2 on;` внутри блока `server` не рекомендуется.

**Шаг 3: Валидация и применение**

```bash
# Проверка синтаксиса
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Перезагрузка конфигурации
sudo systemctl reload nginx

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" https://consul.example.com/ui/
# → 200
```

### 3.3. Сценарий 2: Динамический upstream через consul-template

При масштабировании кластера фиксированный список серверов в конфиге становится недостаточным. `consul-template` позволяет генерировать upstream-блок из актуального каталога Consul.

**Предварительные требования:**

```bash
# Установка consul-template (Debian/Ubuntu — через официальный репозиторий HashiCorp)
curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt-get update && sudo apt-get install -y consul-template

# Проверка
consul-template --version
# → consul-template v0.x.x
```

**Шаг 1: Создание шаблона upstream**

`/etc/consul-template/consul_servers.ctmpl`:
```go-template
upstream consul_servers {
    {{ range service "consul-server" "any" }}
    server {{ .Address }}:8500 max_fails=3 fail_timeout=10s;
    {{ end }}
    keepalive 32;
}
```

> **Примечание:** Серверы Consul должны быть зарегистрированы в каталоге с тегом `consul-server` или аналогичным. Если используется агентская регистрация, убедитесь что сервис `consul` имеет тип `server`.

**Шаг 2: Конфигурация consul-template**

`/etc/consul-template/config.hcl`:
```hcl
consul {
  address = "127.0.0.1:8500"
}

template {
  source      = "/etc/consul-template/consul_servers.ctmpl"
  destination = "/etc/nginx/conf.d/consul_servers.conf"
  command     = "nginx -s reload"
  perms       = 0644
}
```

**Шаг 3: Запуск consul-template как systemd-сервиса**

`/etc/systemd/system/consul-template.service`:
```ini
[Unit]
Description=Consul Template
After=network.target consul.service
Requires=consul.service

[Service]
Type=simple
ExecStart=/usr/bin/consul-template -config=/etc/consul-template/config.hcl
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Включение и запуск
sudo systemctl daemon-reload
sudo systemctl enable --now consul-template

# Проверка статуса
sudo systemctl status consul-template
# → Active: active (running) since ...

# Проверка сгенерированного файла
cat /etc/nginx/conf.d/consul_servers.conf
# → upstream consul_servers {
# →     server 10.0.1.10:8500 max_fails=3 fail_timeout=10s;
# →     server 10.0.1.11:8500 max_fails=3 fail_timeout=10s;
# →     server 10.0.1.12:8500 max_fails=3 fail_timeout=10s;
# → }
# →     keepalive 32;
# → }
```

**Шаг 4: Обновление Nginx конфигурации**

После замены статического upstream на динамический, остальная часть конфигурации из Сценария 1 остаётся без изменений.

### 3.4. Сценарий 3: Защищённый доступ к API (Basic Auth + IP-allowlist)

Для ограничения доступа к чувствительным endpoint'ам (`/v1/agent/`, `/v1/operator/`, `/v1/acl/`) рекомендуется комбинация IP-allowlist и Basic Auth.

**Создание файла паролей:**

```bash
# Установка утилиты
sudo apt-get install -y apache2-utils

# Создание файла .htpasswd
sudo htpasswd -c /etc/nginx/.htpasswd admin
# → New password:
# → Re-type new password:
# → Adding password for user admin

# Проверка
cat /etc/nginx/.htpasswd
# → admin:$apr1$H6JkCXlJ$lZp...
```

**Обновление location-блоков:**

```nginx
location /v1/agent {
    satisfy any;
    allow 10.0.0.0/24;
    deny all;

    auth_basic "Consul Management";
    auth_basic_user_file /etc/nginx/.htpasswd;

    proxy_pass http://consul_servers;
}

location /v1/operator {
    satisfy any;
    allow 10.0.0.0/24;
    deny all;

    auth_basic "Consul Management";
    auth_basic_user_file /etc/nginx/.htpasswd;

    proxy_pass http://consul_servers;
}
```

> `satisfy any` разрешает доступ, если выполняется хотя бы одно условие (IP ИЛИ Basic Auth). Если требуется одновременная проверка обоих условий — используйте `satisfy all`.

**Валидация:**

```bash
# Проверка из разрешённой подсети (должен пройти без запроса пароля)
curl -s -o /dev/null -w "%{http_code}" https://consul.example.com/v1/agent/self
# → 200

# Проверка извне (должен запросить пароль)
curl -s -o /dev/null -w "%{http_code}" https://admin:password@consul.example.com/v1/agent/self
# → 200
```

### 3.5. Сценарий 4: Мониторинг и проверка здоровья

Для отслеживания работоспособности прокси и бэкендов используется комбинация Nginx stub_status, метрик upstream и внешних проверок Consul.

**Активация stub_status:**

```nginx
server {
    listen 127.0.0.1:8080;
    server_name _;

    location /nginx_status {
        stub_status on;
        allow 127.0.0.1;
        deny all;
    }
}
```

```bash
# Проверка
curl http://127.0.0.1:8080/nginx_status
# → Active connections: 2
# → server accepts handled requests
# → 12345 12345 67890
# → Reading: 0 Writing: 1 Waiting: 1
```

**Интеграция с Prometheus Node Exporter (textfile collector):**

```bash
#!/bin/bash
# /usr/local/bin/consul-proxy-metrics.sh

STATUS=$(curl -s http://127.0.0.1:8080/nginx_status)
ACTIVE=$(echo "$STATUS" | awk '/Active connections:/ {print $3}')
WAITING=$(echo "$STATUS" | awk '/Waiting:/ {print $NF}')

cat <<EOF > /var/lib/node_exporter/textfile_collector/consul_proxy.prom
consul_proxy_active_connections $ACTIVE
consul_proxy_waiting_connections $WAITING
EOF
```

```ini
# /etc/systemd/system/consul-proxy-metrics.service
[Unit]
Description=Collect Nginx metrics for Consul proxy

[Service]
Type=oneshot
ExecStart=/usr/local/bin/consul-proxy-metrics.sh
```

```bash
# Запуск каждые 30 секунд через systemd timer
sudo systemctl enable --now consul-proxy-metrics.timer
```

### 3.6. Сценарий 5: Развёртывание на bare metal и systemd

На production-серверах Nginx и consul-template разворачиваются как системные службы с настройкой автоматического старта и перезапуска при сбоях.

**Проверка статуса Nginx:**

```bash
sudo systemctl status nginx
# → ● nginx.service - A high performance web server and a reverse proxy server
# →    Loaded: loaded (/lib/systemd/system/nginx.service; enabled; vendor preset: enabled)
# →    Active: active (running) since Mon 2026-09-22 10:00:00 UTC; 1h 30min ago
```

**Автоматический reload при изменении конфигурации (опционально):**

Для интерактивной разработки можно использовать `systemd` path unit, который вызывает reload при изменении файлов конфигурации:

```ini
# /etc/systemd/system/nginx-reload.path
[Unit]
Description=Watch Nginx config changes

[Path]
PathModified=/etc/nginx/conf.d/
PathModified=/etc/nginx/sites-enabled/

[Install]
WantedBy=multi-user.target

# /etc/systemd/system/nginx-reload.service
[Unit]
Description=Reload Nginx on config change

[Service]
Type=oneshot
ExecStart=/usr/sbin/nginx -t && /bin/systemctl reload nginx
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nginx-reload.path
```

### 3.7. Сценарий 6: Graceful shutdown и обслуживание

При обновлении кластера Consul требуется переконфигурация Nginx без разрыва соединений.

```bash
# 1. Уведомление о готовности к отключению (работает с Nginx 1.19+)
sudo nginx -s QUIT

# 2. Или graceful shutdown через systemd (сохраняет соединения)
sudo systemctl reload nginx

# 3. Полная остановка (с разрывом соединений)
sudo systemctl stop nginx
```

> **Важно:** `nginx -s QUIT` завершает worker-процессы после обработки текущих запросов, но не запускает новые. `nginx -s reload` (или `systemctl reload nginx`) выполняет graceful restart: старые worker'ы завершают обработку, новые поднимаются сразу.

## 4. Операции и команды

### Управление Nginx

| Действие | Команда | Примечание |
| :--- | :--- | :--- |
| **Проверка конфигурации** | `nginx -t` | Обязательно выполнять перед применением изменений. |
| **Reload (Graceful)** | `nginx -s reload` или `systemctl reload nginx` | Подхват новых конфигов без разрыва соединений. |
| **Reopen логов** | `nginx -s reopen` | Повторное открытие лог-файлов (логирование в новый файл). |
| **Quit (Graceful stop)** | `nginx -s quit` | Завершение после обработки текущих запросов. |
| **Stop (Force stop)** | `nginx -s stop` | Немедленная остановка. |
| **Статус через systemd** | `systemctl status nginx` | Проверка активного статуса службы. |

### Управление consul-template

| Действие | Команда | Примечание |
| :--- | :--- | :--- |
| **Однократный рендеринг** | `consul-template -config=/etc/consul-template/config.hcl -once` | Генерация файлов без запуска демона. |
| **Проверка шаблона** | `consul-template -dry-run -config=...` | Валидация без записи файлов. |
| **Reload через сигнал** | `kill -HUP $(pgrep consul-template)` | Принудительная перечитывание конфигурации демоном. |
| **Логи демона** | `journalctl -u consul-template -f` | Мониторинг событий рендеринга. |

### Диагностика соединений с Consul

```bash
# Проверка доступности Consul API
curl -s http://10.0.1.10:8500/v1/status/leader
# → "10.0.1.10:8300"

# Проверка регистрации сервисов
curl -s http://10.0.1.10:8500/v1/catalog/services | jq .
# → {
# →   "consul": [],
# →   "consul-server": [],
# →   "my-app": []
# → }

# Проверка здоровья сервиса
curl -s "http://10.0.1.10:8500/v1/health/service/consul-server?passing"
# → [
# →   {
# →     "Node": "server-1",
# →     "Address": "10.0.1.10",
# →     "Service": {
# →       "ID": "consul-server-1",
# →       "Service": "consul-server",
# →       "Port": 8500,
# →       "Tags": []
# →     }
# →   }
# → ]

# Проверка Blocking Query
curl -s "http://10.0.1.10:8500/v1/kv/config/app/max_connections?index=148&wait=5m"
# → запрос висит до изменения ключа или таймаута
```

### Диагностика Nginx upstream

```bash
# Просмотр активных upstream-соединений
ss -tnp | grep :8500 | grep ESTAB | wc -l
# → 12

# Проверка переменной upstream_addr в логах
awk '{print $NF}' /var/log/nginx/consul_access.log | sort | uniq -c | sort -rn
# →     45 10.0.1.10:8500
# →     38 10.0.1.11:8500
# →     41 10.0.1.12:8500

# Проверка ошибок upstream
grep "upstream timed out" /var/log/nginx/error.log
# → 2026/09/22 10:00:00 [error] 1234#1234: *5678 upstream timed out (110: Connection timed out) ...

# Проверка keepalive-соединений
ss -tnp | grep nginx | grep 8500 | grep ESTAB | wc -l
# → 8
```

### Анализ логов

```bash
# Мониторинг ошибок в реальном времени
tail -f /var/log/nginx/error.log | grep -i "upstream\|consul"

# Фильтрация по коду ответа Consul
awk '$9 ~ /5[0-9]{2}/' /var/log/nginx/consul_access.log | tail -n 20

# Проверка времени ответа upstream
awk '{print $NF}' /var/log/nginx/consul_access.log | awk -F'=' '{print $2}' | sort -n | tail -n 10
```

## 5. Устранение неисправностей

| Ошибка / симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `upstream timed out (110: Connection timed out)` | Consul не отвечает или перегружен. | Проверьте доступность Consul напрямую: `curl http://<backend>:8500/v1/status/leader`. Увеличьте `proxy_connect_timeout` и `proxy_read_timeout`. Проверьте CPU/memory на серверах Consul. |
| `502 Bad Gateway` | Все бэкенды недоступны или порт закрыт. | Проверьте `ss -tnlp \| grep 8500` на серверах Consul. Убедитесь что firewall разрешает трафик между Nginx и Consul. |
| `504 Gateway Timeout` | Запрос превысил `proxy_read_timeout`. | Убедитесь что `proxy_read_timeout` ≥ 310s. Проверьте наличие долгих Blocking Queries в логах Consul. |
| `Connection refused` при проверке `consul-template` | Consul не запущен или слушает на другом интерфейсе. | Проверьте `consul members`. Убедитесь что `consul.hcl` содержит `client_addr = 0.0.0.0` или адрес, доступный с хоста Nginx. |
| Consul UI отдаёт битые ассеты (пустой экран) | Отсутствует завершающий слэш в `/ui/`. | Убедитесь что location-блок содержит `if ($request_uri = "/") { return 301 /ui/; }`. |
| `404 при запросе /v1/status/leader` | Неправильный порт или Consul работает в HTTPS-режиме (порт 8501). | Если Consul настроен на HTTPS, измените upstream на `https://` и добавьте `proxy_ssl_verify off;` (или укажите CA). |
| `could not build optimal proxy_headers_hash` | Слишком много заголовков в `proxy_set_header`. | Увеличьте `proxy_headers_hash_max_size` (по умолчанию 512). |
| `worker_connections are not enough` | Большое количество одновременных Long Polling-соединений. | Увеличьте `worker_connections` в `events {}` (например, до 4096) и `worker_rlimit_nofile` в `main {}`. |
| `Permission denied` при чтении `.htpasswd` | Неправильные права на файл. | Установите права: `sudo chmod 640 /etc/nginx/.htpasswd && sudo chown root:www-data /etc/nginx/.htpasswd`. |
| Динамический upstream не обновляется | `consul-template` не перерендерил шаблон. | Проверьте статус: `systemctl status consul-template`. Проверьте логи: `journalctl -u consul-template -f`. Убедитесь что сервис `consul-server` зарегистрирован в каталоге. |
| Новая версия Nginx не подхватывается | Отсутствует reload после обновления пакета. | Выполните `sudo systemctl restart nginx`. Настройте postinst hook или Ansible-плейбук для автоматического reload. |

## 6. Рекомендации и лучшие практики

### Безопасность

1. **Ограничьте доступ к admin API.** Endpoints `/v1/agent/`, `/v1/operator/`, `/v1/acl/` должны быть доступны только из внутренней сети управления. Используйте `allow/deny` в связке с Basic Auth.
2. **Используйте TLS 1.3.** Запретите старые протоколы: `ssl_protocols TLSv1.3;`. TLS 1.2 допускается только при необходимости поддержки устаревших клиентов.
3. **Включайте HSTS.** `add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;`.
4. **Скрывайте заголовок версии Nginx.** `server_tokens off;` в блоке `http {}`.
5. **Ограничьте размер заголовков.** При больших ответах Consul (например, `/v1/catalog/services` в крупных кластерах) увеличьте `large_client_header_buffers`.
6. **Ротация логов.** Настройте `logrotate` для `/var/log/nginx/consul_access.log` и `error.log`. Ротация раз в день, хранение 30 дней.
7. **Защита от DDoS.** Ограничьте количество одновременных соединений с одного IP: `limit_conn_zone $binary_remote_addr zone=addr:10m; limit_conn addr 10;`.
8. **Не отдавайте служебные директории.** Запретите доступ к `.well-known`, `.git`, `.env` если они не используются.

### Производительность

9. **Используйте `keepalive` в upstream.** `keepalive 32` поддерживает пул постоянных соединений, снижая задержки handshake с Consul.
10. **Настройте `proxy_http_version 1.1`.** Обязательно для keepalive. HTTP/1.0 закрывает соединение после каждого запроса.
11. **Отключите `proxy_set_header Connection`.** Значение `""` позволяет Nginx управлять заголовком Connection самостоятельно.
12. **Мониторьте `upstream_response_time`.** Добавьте в `log_format` для отслеживания задержек Consul.
13. **Используйте `least_conn` для неравномерной нагрузки.** Если часть серверов Consul обрабатывает больше запросов (например, из-за размера индекса Raft), переключитесь на `least_conn`.
14. **Увеличьте `worker_connections`.** При большом количестве Long Polling-соединений установите `worker_rlimit_nofile 65536` и `worker_connections 4096`.

### Эксплуатация

15. **Тестируйте обновления в staging.** Любое изменение конфигурации Nginx или Consul должно проходить через среду, идентичную production.
16. **Ведите changelog конфигурации.** Используйте Git для хранения `nginx.conf` и `consul-template` шаблонов.
17. **Настраивайте алертинг.** Добавьте алёрты на 5xx ошибки Nginx, недоступность upstream и превышение времени ответа.
18. **Документируйте процедуры.** Для каждой среды должен быть регламент: кто имеет доступ к `/v1/agent/`, как обновлять сертификаты, как действовать при падении кластера Consul.
19. **Тестируйте отказоустойчивость.** Периодически отключайте один узел Consul и проверяйте, что Nginx переключает трафик без ошибок.
20. **Используйте `consul-template` в production.** Статический upstream уязвим при расширении кластера. Автоматическое обновление снижает риск человеческой ошибки.

## 7. Дополнительная информация

### См. также

- **[Обзор Consul](../../../Consul/consul_overview.md)** — архитектура, режимы работы, ключевые концепции.
- **[Архитектура Consul](../../../Consul/consul_architecture.md)** — серверы, агенты, Gossip, Raft, порты.
- **[KV-хранилище Consul](../../../Consul/consul_kv_store.md)** — автоматизация через consul-template, блокирующие запросы.
- **[Настройка Let's Encrypt с Nginx](./nginx_with_letsencrypt.md)** — автоматизация SSL.
