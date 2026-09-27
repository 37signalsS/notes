# Nginx как обратный прокси для Grafana

## 1. Определения

**Nginx как обратный прокси для Grafana** — сценарий развёртывания, при котором Nginx выступает единой точкой входа, принимая запросы на стандартных портах (80/443) и перенаправляя их на внутренний порт Grafana (по умолчанию 3000). Это обеспечивает SSL/TLS-терминацию, скрытие внутренней инфраструктуры и централизованную аутентификацию.

*   **[Nginx](../Core/nginx_overview.md)** — высокопроизводительный веб-сервер и обратный прокси.
*   **[Grafana](../../../Grafana/grafana_overview.md)** — open-source платформа для визуализации и мониторинга данных. По умолчанию работает на порту `3000` (HTTP/HTTPS).
*   **[Обратный прокси (Reverse Proxy)](../../../Networking/Concepts/proxy.md)** — сервер-посредник, принимающий запросы от клиентов и распределяющий их между внутренними серверами (бэкендами).
*   **WebSocket / Upgrade** — механизм долгоживущих соединений, используемый Grafana Live и функциями реального времени. Требует явной передачи заголовков `Upgrade` и `Connection` через прокси.
*   **Auth proxy** — режим аутентификации, при котором Nginx (или иной прокси) проверяет пользователя и передаёт его имя/группы в заголовках (например, `X-WEBAUTH-USER`). Grafana доверяет этим заголовкам и не запрашивает логин отдельно. См. детали в **[Управление пользователями и аутентификация](../../../Grafana/grafana_user_management_and_authentication.md)**.
*   **Sub-path (подпуть)** — режим, при котором Grafana доступна не на корне домена, а по префиксу (например, `https://example.com/grafana/`). Требует синхронной настройки Nginx и Grafana (`root_url`, `serve_from_sub_path`).

> Основные понятия Grafana (дашборды, панели, источники данных, провиженинг) описаны в **[Обзор Grafana](../../../Grafana/grafana_overview.md)**.

## 2. Базовые концепции

### Архитектура решения

```
Клиент → [ Nginx (SSL termination, auth, logging) ] → [ Grafana:3000 ]
                                                       (single node или HA cluster)
```

Nginx размещается перед инсталляцией Grafana и выполняет следующие функции:

1. **Терминация SSL/TLS**: Вынос шифрования на Nginx. Один сертификат (Wildcard или Let's Encrypt) покрывает доступ к UI без необходимости настройки HTTPS в самой Grafana.
2. **Балансировка и отказоустойчивость**: При HA-развёртывании Grafana (несколько инстансов с общей БД) Nginx распределяет запросы между узлами. При сбое одного инстанса трафик автоматически переключается.
3. **Управление доступом**:
    - Ограничение доступа по IP-адресам или через Basic Auth / Auth proxy (SSO через корпоративный IdP).
    - Внедрение заголовков безопасности (HSTS, CSP, X-Frame-Options).
    - Передача токенов аутентификации через кастомные заголовки (Auth proxy).
4. **Поддержка WebSocket**: Grafana Live, real-time обновления дашбордов и уведомления используют WebSocket. Nginx должен корректно передавать заголовки `Upgrade` и `Connection`.
5. **Оптимизация**: Кэширование статических ассетов, сжатие (Gzip/Brotli), буферизация для больших дашбордов и запросов Explore.
6. **Логирование и аудит**: Централизованный доступный лог всех обращений с указанием реального IP-адреса клиента (`X-Forwarded-For`), времени и результата.

### Жизненный цикл запроса

1. Клиент отправляет HTTPS-запрос на `grafana.example.com`.
2. Nginx завершает TLS, проверяет заголовки, IP-клиент и (при необходимости) аутентификацию.
3. Nginx выбирает upstream-сервер по round-robin или least_conn.
4. При наличии `keepalive` в upstream соединение с бэкендом переиспользуется.
5. Grafana обрабатывает запрос: авторизует пользователя, выполняет запрос к источнику данных, возвращает HTML/JSON/WebSocket-фрейм.
6. Nginx передаёт ответ клиенту, добавляя заголовки безопасности.

### Специфика долгоживущих соединений

Grafana использует **WebSocket** для функций реального времени (Grafana Live). Дополнительно, тяжелые запросы в **Explore** или при больших временных интервалах могут удерживать соединение несколько минут. Nginx по умолчанию имеет `proxy_read_timeout 60s`, поэтому требуется явное увеличение этого параметра.

В HA-режиме сессии пользователей хранятся в PostgreSQL/MySQL, а не в файловой системе, что позволяет Nginx балансировать запросы между несколькими инстансами Grafana без привязки сессий (sticky sessions).

### Конфигурация Grafana для работы за прокси

Grafana должна «знать» внешний URL для корректной генерации ссылок, cookie и callback-адресов. Это настраивается в `grafana.ini` (секция `[server]`) или через переменные окружения `GF_SERVER_*`:

- `domain` — основной домен доступа (без протокола и пути).
- `root_url` — полный внешний URL (обязательно с протоколом и завершающим слэшем).
- `serve_from_sub_path` — флаг, включающий режим подпути (sub-path).
- `enforce_domain` — принудительное перенаправление на указанный домен (полезно при множестве alias).

## 3. Практические сценарии

### 3.1. Предварительные требования

| Компонент | Требование | Примечание |
| :--- | :--- | :--- |
| **ОС** | Debian 12 (Bookworm), Ubuntu 22.04/24.04 (Jammy/Noble), RHEL/Rocky 9 | Другие дистрибутивы на основе Debian/RHEL также поддерживаются |
| **Nginx** | Версия 1.27+ | Рекомендуется `nginx-full` (Debian/Ubuntu) |
| **Grafana** | Версия 13.1.x (OSS или Enterprise) | 12.x — LTS; 11.x — EOL (июнь 2026) |
| **Сеть** | Доступ от Nginx до порта `3000` на Grafana-узлах | При HA — несколько адресов upstream |
| **Права** | root или пользователь с правами sudo | Для управления Nginx и firewall |
| **DNS** | A-запись `grafana.example.com` → IP-frontend Nginx | Или `/etc/hosts` для тестовых сред |

**Начальное состояние системы:**

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y nginx curl gnupg apache2-utils

# RHEL/Rocky
sudo dnf install -y nginx curl

# Проверка версии Nginx
nginx -v
# → nginx version: nginx/1.27.x

# Проверка доступности Grafana из хоста Nginx
curl -s http://10.0.2.10:3000/api/health
# → {"database":"ok","memory":"ok"}
```

### 3.2. Сценарий 1: Базовый обратный прокси (одиночный узел)

Подходит для небольших инсталляций с одним экземпляром Grafana.

**Шаг 1: Создание виртуального хоста**

`/etc/nginx/conf.d/grafana.conf`:
```nginx
# Маппинг для поддержки WebSockets (Grafana Live)
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

# Редирект с HTTP на HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name grafana.example.com;

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name grafana.example.com;

    ssl_certificate     /etc/letsencrypt/live/grafana.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/grafana.example.com/privkey.pem;

    ssl_protocols TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";

    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    proxy_read_timeout 310s;
    proxy_connect_timeout 5s;

    location / {
        proxy_pass http://localhost:3000;

        # Оптимизация буферов для больших дашбордов и Explore
        proxy_buffers 8 32k;
        proxy_buffer_size 64k;
    }
}
```

> **Важно:** синтаксис `listen 443 ssl http2;` является актуальным для Nginx 1.25+. Устаревший вариант `http2 on;` внутри блока `server` не рекомендуется.

**Шаг 2: Настройка Grafana**

`/etc/grafana/grafana.ini`:
```ini
[server]
domain = grafana.example.com
root_url = https://grafana.example.com/
enable_gzip = true
```

Или через переменные окружения (предпочтительно для контейнеров):

```bash
GF_SERVER_DOMAIN=grafana.example.com
GF_SERVER_ROOT_URL=https://grafana.example.com/
GF_SERVER_ENABLE_GZIP=true
```

**Шаг 3: Валидация и применение**

```bash
# Проверка синтаксиса Nginx
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Перезагрузка конфигурации
sudo systemctl reload nginx

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" https://grafana.example.com/api/health
# → 200

# Проверка редиректа с HTTP на HTTPS
curl -s -o /dev/null -w "%{redirect_url}" http://grafana.example.com/
# → https://grafana.example.com/
```

### 3.3. Сценарий 2: Работа в подпути (sub-path)

Если Grafana должна быть доступна по адресу `https://example.com/grafana/`, необходимо внести синхронные изменения в Nginx и Grafana.

**Nginx:**

```nginx
location /grafana/ {
    proxy_pass http://localhost:3000/;  # Обратите внимание на слэш в конце
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    proxy_read_timeout 310s;
}
```

> Обратите внимание: слэш в конце `proxy_pass` обязателен. Без него Nginx передаст запрос с исходным путём (`/grafana/login`), что приведёт к 404 в Grafana.

**Grafana:**

```ini
[server]
root_url = https://example.com/grafana/
serve_from_sub_path = true
```

**Валидация:**

```bash
curl -s -o /dev/null -w "%{http_code}" https://example.com/grafana/api/health
# → 200
```

### 3.4. Сценарий 3: Auth proxy (SSO через Nginx)

Используется, когда перед Grafana уже стоит корпоративный прокси (Nginx/Apache/Traefik), который сам аутентифицирует пользователя (например, через `auth_request` к Keycloak, mTLS или Apache mod_auth). Grafana доверяет заголовкам, переданным прокси.

> Детали настройки Grafana для auth proxy см. в **[Управление пользователями и аутентификация](../../../Grafana/grafana_user_management_and_authentication.md)**.

**Grafana (`grafana.ini`):**

```ini
[server]
root_url = https://grafana.example.internal/

[auth.proxy]
enabled = true
header_name = X-WEBAUTH-USER
header_property = username
auto_sign_up = true
headers = X-WEBAUTH-GROUPS:X-Webauth-Groups
ldap_sync_ttl = 60
```

**Nginx:**

```nginx
location / {
    auth_request /auth;                       # внешняя проверка у прокси/IdP
    proxy_set_header X-WEBAUTH-USER $authenticated_user;
    proxy_set_header X-WEBAUTH-GROUPS $authenticated_groups;

    # Защита: запретить клиенту протащить поддельный заголовок
    proxy_hide_header X-WEBAUTH-USER;

    proxy_pass http://127.0.0.1:3000;
}
```

**Валидация:**

```bash
# Вход через прокси → Grafana создаёт/обновляет пользователя по X-WEBAUTH-USER
curl -s -H "Authorization: Bearer <ADMIN_TOKEN>" http://grafana.example.com/api/user | jq .
# → {"login":"ivanov","role":"Admin",...}
```

### 3.5. Сценарий 4: Защищённый доступ (Basic Auth + IP-allowlist)

Для ограничения доступа к чувствительным endpoint'ам рекомендуется комбинация IP-allowlist и Basic Auth.

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

**Обновление location-блоков (для API-метрик Grafana):**

```nginx
location /api/ {
    satisfy any;
    allow 10.0.0.0/24;
    deny all;

    auth_basic "Grafana Management";
    auth_basic_user_file /etc/nginx/.htpasswd;

    proxy_pass http://localhost:3000;
}
```

> `satisfy any` разрешает доступ, если выполняется хотя бы одно условие (IP ИЛИ Basic Auth). Если требуется одновременная проверка обоих условий — используйте `satisfy all`.

**Валидация:**

```bash
# Проверка из разрешённой подсети (должен пройти без запроса пароля)
curl -s -o /dev/null -w "%{http_code}" https://grafana.example.com/api/health
# → 200

# Проверка извне (должен запросить пароль)
curl -s -o /dev/null -w "%{http_code}" https://admin:password@grafana.example.com/api/health
# → 200
```

### 3.6. Сценарий 5: Развёртывание на bare metal и systemd

На production-серверах Nginx и Grafana разворачиваются как системные службы с настройкой автоматического старта и перезапуска при сбоях.

**Проверка статуса Nginx:**

```bash
sudo systemctl status nginx
# → ● nginx.service - A high performance web server and a reverse proxy server
# →    Loaded: loaded (/lib/systemd/system/nginx.service; enabled; vendor preset: enabled)
# →    Active: active (running) since Mon 2026-09-22 10:00:00 UTC; 1h 30min ago
```

**Проверка статуса Grafana:**

```bash
sudo systemctl status grafana-server
# → ● grafana-server.service - Grafana instance
# →    Loaded: loaded (/lib/systemd/system/grafana-server.service; enabled; vendor preset: enabled)
# →    Active: active (running) since Mon 2026-09-22 10:00:30 UTC; 1h 29min ago
```

**Автоматический reload Nginx при изменении конфигурации (опционально):**

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

### 3.7. Сценарий 6: Мониторинг и проверка здоровья

Для отслеживания работоспособности прокси и бэкенда используется комбинация Nginx stub_status и проверок Grafana API.

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
curl http://127.0.0.1:8080/nginx_status
# → Active connections: 2
# → server accepts handled requests
# → 12345 12345 67890
# → Reading: 0 Writing: 1 Waiting: 1
```

**Интеграция с Prometheus Node Exporter (textfile collector):**

```bash
#!/bin/bash
# /usr/local/bin/grafana-proxy-metrics.sh

STATUS=$(curl -s http://127.0.0.1:8080/nginx_status)
ACTIVE=$(echo "$STATUS" | awk '/Active connections:/ {print $3}')
WAITING=$(echo "$STATUS" | awk '/Waiting:/ {print $NF}')

cat <<EOF > /var/lib/node_exporter/textfile_collector/grafana_proxy.prom
grafana_proxy_active_connections $ACTIVE
grafana_proxy_waiting_connections $WAITING
EOF
```

```ini
# /etc/systemd/system/grafana-proxy-metrics.service
[Unit]
Description=Collect Nginx metrics for Grafana proxy

[Service]
Type=oneshot
ExecStart=/usr/local/bin/grafana-proxy-metrics.sh
```

```bash
# Запуск каждые 30 секунд через systemd timer
sudo systemctl enable --now grafana-proxy-metrics.timer
```

### 3.8. Сценарий 7: Graceful shutdown и обслуживание

При обновлении кластера Grafana требуется переконфигурация Nginx без разрыва соединений.

```bash
# 1. Graceful shutdown Grafana через systemd
sudo systemctl reload grafana-server

# 2. Или полная остановка (с разрывом соединений)
sudo systemctl stop grafana-server

# 3. Reload Nginx (без разрыва соединений)
sudo systemctl reload nginx

# 4. Quit Nginx (завершение после обработки текущих запросов)
sudo nginx -s quit
```

> **Важно:** `nginx -s quit` завершает worker-процессы после обработки текущих запросов, но не запускает новые. `systemctl reload nginx` выполняет graceful restart: старые worker'ы завершают обработку, новые поднимаются сразу.

## 4. Операции и команды

### Управление Nginx

| Действие | Команда | Примечание |
| :--- | :--- | :--- |
| **Проверка конфигурации** | `nginx -t` | Обязательно выполнять перед применением изменений. |
| **Reload (Graceful)** | `nginx -s reload` или `systemctl reload nginx` | Подхват новых конфигов без разрыва соединений. |
| **Reopen логов** | `nginx -s reopen` | Повторное открытие лог-файлов. |
| **Quit (Graceful stop)** | `nginx -s quit` | Завершение после обработки текущих запросов. |
| **Stop (Force stop)** | `nginx -s stop` | Немедленная остановка. |
| **Статус через systemd** | `systemctl status nginx` | Проверка активного статуса службы. |

### Управление Grafana

| Действие | Команда | Примечание |
| :--- | :--- | :--- |
| **Проверка статуса** | `systemctl status grafana-server` | Активный статус службы. |
| **Reload конфигурации** | `systemctl reload grafana-server` | Перечитывание `grafana.ini` (не все параметры поддерживают reload). |
| **Перезапуск** | `systemctl restart grafana-server` | Полный перезапуск процесса. |
| **Логи в реальном времени** | `journalctl -u grafana-server -f` | Мониторинг логов службы. |
| **Сброс пароля admin** | `grafana-cli admin reset-admin-password <new_password>` | Требует доступа к консоли сервера. |
| **Проверка здоровья API** | `curl -s http://localhost:3000/api/health` | Должен вернуть `{"database":"ok","memory":"ok"}`. |
| **Список плагинов** | `grafana-cli plugins ls` | Проверка установленных расширений. |

### Диагностика Nginx upstream

```bash
# Просмотр активных upstream-соединений
ss -tnp | grep :3000 | grep ESTAB | wc -l
# → 12

# Проверка переменной upstream_addr в логах
awk '{print $NF}' /var/log/nginx/grafana_access.log | sort | uniq -c | sort -rn
# →     45 10.0.2.10:3000
# →     38 10.0.2.11:3000

# Проверка ошибок upstream
grep "upstream timed out" /var/log/nginx/error.log
# → 2026/09/22 10:00:00 [error] 1234#1234: *5678 upstream timed out (110: Connection timed out) ...

# Проверка WebSocket-соединений
ss -tnp | grep nginx | grep 3000 | grep ESTAB | wc -l
# → 8
```

### Анализ логов

```bash
# Мониторинг ошибок в реальном времени
tail -f /var/log/nginx/error.log | grep -i "upstream\|grafana"

# Фильтрация по коду ответа Grafana
awk '$9 ~ /5[0-9]{2}/' /var/log/nginx/grafana_access.log | tail -n 20

# Проверка времени ответа upstream
awk '{print $NF}' /var/log/nginx/grafana_access.log | awk -F'=' '{print $2}' | sort -n | tail -n 10
```

## 5. Устранение неисправностей

| Ошибка / симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `upstream timed out (110: Connection timed out)` | Grafana не отвечает или перегружена (тяжёлые запросы Explore). | Проверьте доступность Grafana напрямую: `curl http://<backend>:3000/api/health`. Увеличьте `proxy_read_timeout` до 310s. Проверьте CPU/memory на серверах Grafana. |
| `502 Bad Gateway` | Grafana не запущена или порт закрыт. | Проверьте `ss -ltnp \| grep 3000`. Убедитесь что firewall разрешает трафик между Nginx и Grafana. |
| `504 Gateway Timeout` | Запрос превысил `proxy_read_timeout`. | Увеличьте `proxy_read_timeout` до 310s. Проверьте наличие долгих запросов к источникам данных. |
| `WebSocket connection failed` | Отсутствуют заголовки `Upgrade` / `Connection`. | Убедитесь что настроен `map $http_upgrade $connection_upgrade` и `proxy_set_header Upgrade $http_upgrade;`. |
| `Origin not allowed` | Заголовок `Host` в Nginx не совпадает с `domain` в `grafana.ini`. | Убедитесь что `server_name` в Nginx совпадает с `domain` в Grafana. |
| `Редирект на http вместо https` | Отсутствует заголовок `X-Forwarded-Proto`. | Добавьте `proxy_set_header X-Forwarded-Proto $scheme;` в location-блок. |
| `Пустой белый экран` | Неверный `root_url` или смешанный контент (Mixed Content). | Проверьте что `root_url` начинается с `https://`. Убедитесь что CSP разрешает скрипты Grafana. |
| `Permission denied` при чтении `.htpasswd` | Неправильные права на файл. | Установите права: `sudo chmod 640 /etc/nginx/.htpasswd && sudo chown root:www-data /etc/nginx/.htpasswd`. |
| `could not build optimal proxy_headers_hash` | Слишком много заголовков в `proxy_set_header`. | Увеличьте `proxy_headers_hash_max_size` (по умолчанию 512). |
| `worker_connections are not enough` | Большое количество WebSocket-соединений. | Увеличьте `worker_connections` в `events {}` (например, до 4096) и `worker_rlimit_nofile` в `main {}`. |
| `Cookie не устанавливается / вечный редирект` | `root_url` указан с `http` или отсутствует `X-Forwarded-Proto`. | Укажите `root_url=https://...` и передавайте `X-Forwarded-Proto`. |
| `Auth proxy не работает — пользователь не создаётся` | Прокси не проставляет заголовок `X-WEBAUTH-USER`. | Проверьте конфигурацию `auth_request` upstream. В логах Grafana ищите `auth.proxy: ...`. |

## 6. Рекомендации и лучшие практики

### Безопасность

1. **Ограничьте доступ к API Grafana.** Endpoints `/api/` должны быть доступны только из внутренней сети. Используйте `allow/deny` в связке с Basic Auth или Auth proxy.
2. **Используйте TLS 1.3.** Запретите старые протоколы: `ssl_protocols TLSv1.3;`. TLS 1.2 допускается только при необходимости поддержки устаревших клиентов.
3. **Включайте HSTS.** `add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;`.
4. **Скрывайте заголовок версии Nginx.** `server_tokens off;` в блоке `http {}`.
5. **Защита от поддельных заголовков (Auth proxy).** Используйте `proxy_hide_header X-WEBAUTH-USER;`, чтобы клиент не мог подставить собственный заголовок.
6. **Ротация логов.** Настройте `logrotate` для `/var/log/nginx/grafana_access.log` и `error.log`. Ротация раз в день, хранение 30 дней.
7. **Защита от DDoS.** Ограничьте количество одновременных соединений с одного IP: `limit_conn_zone $binary_remote_addr zone=addr:10m; limit_conn addr 10;`.

### Производительность

8. **Используйте `keepalive` в upstream.** При HA-развёртывании добавьте upstream-блок с `keepalive 32` для снижения задержек handshake.
9. **Настройте `proxy_http_version 1.1`.** Обязательно для WebSocket и keepalive.
10. **Отключите `proxy_set_header Connection`.** Значение `""` позволяет Nginx управлять заголовком Connection самостоятельно.
11. **Настройте буферы.** `proxy_buffers 8 32k; proxy_buffer_size 64k;` ускоряют загрузку больших дашбордов и ответов Explore.
12. **Увеличьте `worker_connections`.** При большом количестве WebSocket-соединений установите `worker_rlimit_nofile 65536` и `worker_connections 4096`.

### Эксплуатация

13. **Тестируйте обновления в staging.** Любое изменение конфигурации Nginx или Grafana должно проходить через среду, идентичную production.
14. **Ведите changelog конфигурации.** Используйте Git для хранения `nginx.conf`, `grafana.ini` и провиженинга.
15. **Настраивайте алертинг.** Добавьте алёрты на 5xx ошибки Nginx, недоступность upstream и превышение времени ответа.
16. **Тестируйте отказоустойчивость.** Периодически отключайте один узел Grafana и проверяйте, что Nginx переключает трафик без ошибок.
17. **Используйте провиженинг.** Дашборды, источники данных и алерты должны храниться в Git, а не только в БД Grafana.

## 7. Дополнительная информация

### Критические ограничения

1. **Запрет `try_files`**: В блоке `location /` при проксировании к Grafana нельзя использовать `try_files`. Nginx попытается найти файл на диске и вернёт 404, так как Grafana отдаёт контент динамически через свой бэкенд.
2. **Заголовки безопасности и CSP**: Если вы используете `Content-Security-Policy` (CSP) на уровне Nginx, убедитесь что разрешены скрипты и инлайновые стили, необходимые для работы Grafana, либо используйте встроенные механизмы CSP в `grafana.ini`.
3. **Тайм-ауты**: Для работы тяжелых запросов в Explore или при использовании больших интервалов времени `proxy_read_timeout` должен быть не менее 310s.

### См. также

*   **[Обзор Nginx](../Core/nginx_overview.md)**
*   **[Обзор Grafana](../../../Grafana/grafana_overview.md)** — архитектура, версии, конфигурация.
*   **[Прокси-серверы: концепции](../../../Networking/Concepts/proxy.md)**
*   **[Управление пользователями и аутентификация](../../../Grafana/grafana_user_management_and_authentication.md)** — auth proxy, SSO, RBAC.
*   **[Оптимизация TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)**
