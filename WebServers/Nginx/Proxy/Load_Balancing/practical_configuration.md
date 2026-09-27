# Практическая конфигурация балансировки нагрузки Nginx

## Определения

**Upstream-группа** — именованный пул бэкенд-серверов, между которыми распределяются запросы. Определяется директивой `upstream` в контексте `http`.

**Проксирование (Proxying)** — процесс приема запроса от клиента и его передачи бэкенду. В Nginx реализуется через семейство директив `proxy_*`.

**Keep-alive (Upstream)** — механизм повторного использования TCP-соединений с бэкендами, позволяющий избежать затрат на установку нового соединения для каждого запроса.

**Буферизация (Buffering)** — механизм, при котором Nginx считывает ответ бэкенда в свои буферы и только потом отдает данные клиенту, освобождая бэкенд максимально быстро.

**mTLS (Mutual TLS)** — двусторонняя аутентификация по TLS, при которой и клиент, и сервер предъявляют друг другу сертификаты. В контексте Nginx используется для безопасного соединения с бэкендами.

## Основные концепции и архитектура

### Роль и структура Upstream

Блок `upstream` отделяет логику распределения нагрузки от логики обработки запросов в блоках `server`. Это дает следующие преимущества:
1. **Абстракция:** Изменение состава серверов не требует правки каждого `location`.
2. **Отказоустойчивость:** Автоматическое исключение неисправных узлов на основе пассивных проверок.
3. **Оптимизация:** Возможность тонкой настройки параметров соединений (`keepalive`, `max_conns`, `slow_start`).

### Механизм передачи запроса

Директива `proxy_pass` создает новый HTTP-запрос к бэкенду. Nginx выступает в роли клиента, поэтому крайне важно понимать жизненный цикл запроса:
1. **Установка соединения:** Nginx открывает TCP-соединение с бэкендом (или берет из keepalive-пула).
2. **Формирование запроса:** Применяются `proxy_set_header` для передачи метаданных клиента.
3. **Буферизация:** Ответ бэкенда считывается в буферы (`proxy_buffers`) или передается клиенту сразу (`proxy_buffering off`).
4. **Обработка ошибок:** При сбое Nginx может переключиться на следующий сервер через `proxy_next_upstream`.

*Важное примечание:* В многослойных архитектурах Nginx часто работает за внешним балансировщиком (L4 LB). В такой конфигурации крайне важно правильно обрабатывать заголовок `X-Forwarded-For` или использовать [Proxy Protocol](../../../../Networking/Protocols/proxy_protocol.md), чтобы не потерять реальный IP клиента. Подробнее см. в [Обзоре концепций балансировки](./overview_concepts.md).

### Таймауты и их значение для SRE

Каждый таймаут в конфигурации проксирования защищает либо бэкенд, либо клиента от зависаний. Понимание семантики каждого параметра критично для настройки SLA:

| Директива | Описание | Рекомендация |
| :--- | :--- | :--- |
| `proxy_connect_timeout` | Время на установку TCP-соединения. | 1s - 5s |
| `proxy_send_timeout` | Время на передачу данных бэкенду. | 30s - 60s |
| `proxy_read_timeout` | Время ожидания ответа после передачи запроса. | 30s - 60s (увеличивать для отчетов) |
| `proxy_next_upstream_timeout` | Общее время на все попытки переключения. | 10s - 30s |
| `proxy_next_upstream_tries` | Максимальное число попыток (включая первую). | 3-5 |

### Специфика Angie

В **Angie** доступны расширенные возможности для управления апстримами:
- `resolver conf` — автоматическое использование системных DNS.
- `sticky` — липкие сессии (в Nginx OSS только через Hash).
- Продвинутые метрики в формате JSON через API.

## Практические сценарии

### 1. Объявление группы серверов

Блок `upstream` располагается в контексте `http`.

```nginx
upstream app_cluster {
    zone cluster_zone 128k;

    server 10.0.0.1:8080 weight=3 max_fails=3 fail_timeout=30s;
    server 10.0.0.2:8080 weight=1 max_fails=3 fail_timeout=30s;
    server 10.0.0.3:8080 backup;
    server 10.0.0.4:8080 down;
}
```

### 2. Настройка проксирования и передача заголовков

Для корректной работы приложения (формирования ссылок, логирования IP) бэкенд должен знать параметры исходного запроса.

```nginx
location / {
    proxy_pass http://app_cluster;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_redirect off;
    client_max_body_size 100M;
}
```

#### Восстановление реального IP клиента (`real_ip`)

Бэкенд получает `X-Real-IP`/`X-Forwarded-For` из заголовков, но для корректной логики Nginx (rate limiting, geo, логи) сам Nginx должен знать фактический IP клиента. Если Nginx стоит за CDN или L4/L7 балансировщиком, доверяйте IP только от списка доверенных источников:

```nginx
# Доверенные источники: балансировщик или CDN (обязательно, иначе любой может подделать IP)
set_real_ip_from 10.0.0.0/8;
set_real_ip_from 203.0.113.0/24;   # внешний L4 LB / CDN
real_ip_header X-Forwarded-For;
# real_ip_header proxy_protocol;   # если используется PROXY Protocol вместо заголовков
real_ip_recursive on;              # брать первое недоверенное значение в цепочке XFF
```

**Предостережение:** без `set_real_ip_from` заголовок `X-Forwarded-For` может быть подделан клиентом, чтобы обойти IP-лимиты (`limit_req`/`limit_conn`) и гео-блокировки. Доверяйте XFF только от известных прокси и используйте **PROXY Protocol** на L4 (см. [Proxy Protocol](../../../../Networking/Protocols/proxy_protocol.md)). Полный разбор `real_ip_header`/`set_real_ip_from`/`real_ip_recursive` для Nginx — в [HTTP-серверах и прокси](../../../../Networking/Protocols/HTTP/http_servers_proxies.md).

### 3. Оптимизация производительности (Keep-alive)

По умолчанию Nginx использует HTTP/1.0 для соединений с бэкендом и закрывает их сразу после ответа. Для высоконагруженных систем это создает избыточную нагрузку на CPU и сеть.

```nginx
upstream backend_pool {
    server 10.0.0.1:8080;

    keepalive 64;
    keepalive_requests 1000;
    keepalive_timeout 60s;
}

server {
    location / {
        proxy_pass http://backend_pool;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

### 4. Обеспечение отказоустойчивости (Failover)

Директива `proxy_next_upstream` позволяет Nginx прозрачно для пользователя переключиться на другой сервер при ошибке.

```nginx
location / {
    proxy_pass http://app_cluster;
    proxy_next_upstream error timeout invalid_header http_502 http_503 http_504;
    proxy_next_upstream_tries 3;
    proxy_next_upstream_timeout 15s;
}
```

*Важно:* Если запрос является неидемпотентным (например, `POST`), Nginx по умолчанию не будет его повторять на другой сервер, если бэкенд уже начал отправлять ответ. Для изменения этого поведения используйте параметр `non_idempotent`.

### 5. Управление буферизацией и стримингом

- **`proxy_buffering on` (по умолчанию):** Nginx читает ответ бэкенда целиком в свои буферы и только потом отдает клиенту. Это освобождает бэкенд максимально быстро.
- **`proxy_buffering off`:** Используется для стриминга (SSE, Comet), данные передаются клиенту сразу по мере поступления.

```nginx
location /api/stream {
    proxy_pass http://app_cluster;
    proxy_buffering off;
    proxy_cache_bypass $http_upgrade;
}

location /static/ {
    proxy_pass http://app_cluster;
    proxy_buffers 16 32k;
    proxy_buffer_size 64k;
    proxy_busy_buffers_size 128k;
}
```

### 6. Работа с защищенными бэкендами (HTTPS/mTLS)

Если Nginx должен подключаться к бэкенду по HTTPS.

```nginx
location /secure/ {
    proxy_pass https://secure_upstream;

    proxy_ssl_verify on;
    proxy_ssl_trusted_certificate /etc/nginx/certs/backend_ca.crt;
    proxy_ssl_server_name on;

    proxy_ssl_certificate /etc/nginx/certs/nginx_client.crt;
    proxy_ssl_certificate_key /etc/nginx/certs/nginx_client.key;
}
```

### 7. Обработка ошибок бэкенда

Позволяет перехватывать ошибки бэкенда и показывать пользователю красивые страницы или выполнять редирект.

```nginx
location / {
    proxy_pass http://app_cluster;
    proxy_intercept_errors on;
}

error_page 502 503 504 /custom_50x.html;
location = /custom_50x.html {
    root /usr/share/nginx/html;
    internal;
}
```

> **Примечание:** Для планового maintenance-режима (не ошибок бэкенда) используйте подход с `include` и симлинком. Подробнее — в **[Maintenance-режим в Nginx](../../Scenarios/nginx_maintenance_mode.md)**.

## Операции и команды

### Валидация прокси-конфигурации

```bash
# Проверка синтаксиса перед применением
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Грациозная перезагрузка без потери соединений
nginx -s reload
# → signal reload started
```

### Диагностика проксирования и upstream

```bash
# Поиск ошибок upstream в логе (502, 504, переполнение очереди)
grep -E "upstream|502|504" /var/log/nginx/error.log | tail -n 50

# Анализ распределения запросов по бэкендам (требуется $upstream_addr в логе)
awk '{print $NF}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -n 10

# Проверка времени ответа бэкендов (требуется $upstream_response_time)
awk '$upstream_response_time > 1.0 {print $0}' /var/log/nginx/access.log | head -n 20

# Определение фактического списка upstream-серверов
nginx -T | grep -A 20 "upstream"
```

### Проверка keepalive-соединений

```bash
# Подсчет установленных соединений к бэкенду
ss -tn state established '( daddr = 10.0.0.10 and sport = :8080 )' | wc -l

# Просмотр всех keepalive-соединений upstream
ss -tn state established '( daddr = 10.0.0.10 and sport = :8080 )'
```

### Диагностика с curl

```bash
# Проверка, что Nginx проксирует на правильный бэкенд
curl -I http://app.example.com/health
# → HTTP/1.1 200 OK

# Проверка заголовков при ошибках бэкенда
curl -v http://app.example.com/slow-endpoint 2>&1 | grep -E "< HTTP|X-Upstream|timed out"
```

## Диагностика и устранение неполадок

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `502 Bad Gateway` на всех запросах | Все бэкенды недоступны или упали | Проверить доступность бэкендов: `curl http://10.0.0.10:8080`; убедиться, что `upstream` указан правильно; проверить firewall/SELinux |
| `502 Bad Gateway` на отдельных запросах | Один бэкенд недоступен, исчерпан `max_conns` или `fail_timeout` | Проверить `error.log`; проверить, не установлен ли флаг `down` вручную |
| `504 Gateway Timeout` | Бэкенд не ответил за `proxy_read_timeout` | Увеличить `proxy_read_timeout`; проверить нагрузку на бэкенд; проверить сетевую доступность |
| `503 Service Unavailable` при нагрузке | Все серверы достигли `max_conns`, очередь пуста или переполнена | Увеличить `max_conns`; добавить серверы; настроить `queue` (Angie/Plus) |
| Дисбаланс нагрузки | Неправильный `weight`, `ip_hash` с NAT, `least_conn` с быстрыми ошибками | Проверить веса; для NAT использовать `hash` вместо `ip_hash`; исключить неработающие бэкенды через `max_fails` |
| Потеря сессий при росте кластера | Используется `ip_hash` или `hash` без `consistent` | Перейти на `hash ... consistent` для минимизации перераспределения |
| Бесконечные повторные запросы | `proxy_next_upstream` без ограничения `tries`/`timeout` | Установить `proxy_next_upstream_tries` и `proxy_next_upstream_timeout` |
| "upstream sent too big header" | Бэкенд прислал слишком много заголовков | Увеличить `proxy_buffer_size` и `proxy_buffers` |
| "an upstream response is buffered to a temporary file" | Ответ бэкенда не помещается в память | Увеличить `proxy_buffers` или `proxy_max_temp_file_size` |

### Диагностические команды

```bash
# Поиск ошибок upstream в логе
grep -E "upstream|502|504" /var/log/nginx/error.log | tail -n 50

# Анализ распределения запросов по бэкендам
awk '{print $NF}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head -n 10

# Проверка времени ответа бэкендов
awk '$upstream_response_time > 1.0 {print $0}' /var/log/nginx/access.log | head -n 20

# Поиск записей о слишком больших заголовках от бэкенда
grep "upstream sent too big header" /var/log/nginx/error.log

# Проверка переполнения временными файлами при буферизации
grep "buffered to a temporary file" /var/log/nginx/error.log
```

## Лучшие практики

### Производительность

1. **Используйте `zone` для всех upstream-групп с `least_conn` или sticky-сессиями.** Без `zone` Nginx не может сохранять состояние соединений между рабочими процессами, что приводит к некорректной балансировке.
2. **Включайте `keepalive` в `upstream` для высоконагруженных HTTP-сервисов.** Без keepalive Nginx использует HTTP/1.0 и закрывает соединение после каждого запроса, что создает избыточную нагрузку на CPU и порты.
3. **Используйте `hash ... consistent` для кэширующих прокси вместо `ip_hash`.** Консистентное хеширование минимизирует перераспределение ключей при изменении состава бэкендов.
4. **Избегайте `random` в production без явной необходимости.** Случайное распределение может привести к дисбалансу при малом числе серверов и затрудняет прогнозирование нагрузки.
5. **Настраивайте `proxy_buffering` по типу трафика.** Для API с быстрыми ответами включите буферизацию; для стриминга (SSE, WebSocket) отключите её.

### Безопасность

1. **Никогда не полагайтесь на балансировку как на механизм безопасности.** Для контроля доступа используйте `internal`, `auth_request` или WAF.
2. **Явно указывайте `max_fails` и `fail_timeout`** для каждого сервера. Без этих параметров Nginx по умолчанию использует `max_fails=1` и `fail_timeout=10s`, что может привести к частым переключениям при временных сбоях.
3. **Не используйте `backup`-серверы для активной нагрузки.** Они предназначены только для аварийного переключения и имеют более низкий приоритет.
4. **Изолируйте management-интерфейсы.** Если используете `status_zone` (Angie/Nginx Plus), ограничьте доступ к API метрик firewall-правилами или `allow/deny`.
5. **Скрывайте служебные заголовки:** используйте `proxy_hide_header` для `Server` и `X-Powered-By`, чтобы снизить поверхность атаки.

### Эксплуатация (SRE)

1. **Логирование upstream-переменных:** Добавьте в `log_format` переменные `$upstream_addr`, `$upstream_status`, `$upstream_response_time` для трассировки запросов:

    ```nginx
    log_format upstream_debug '$remote_addr - [$time_local] '
                              '$upstream_addr $upstream_status $upstream_response_time';
    ```

2. **Мониторинг дисбаланса:** Регулярно проверяйте распределение запросов по бэкендам. Дисбаланс более чем на 20% при использовании Round Robin или `least_conn` указывает на проблему с весами или медленный бэкенд.
3. **Алертинг на 502/504:** Настройте оповещение на ошибки `502 Bad Gateway` и `504 Gateway Timeout` в `error.log`. Частые 502 указывают на падение бэкендов; частые 504 — на таймауты или перегрузку.
4. **Тестирование failover:** Периодически проверяйте, что `proxy_next_upstream` корректно переключает трафик при отключении одного из бэкендов:

    ```bash
    systemctl stop app@node1
    curl -I http://app.example.com/health
    # Проверить, что запросы ушли на оставшиеся узлы
    ```

5. **Резервное копирование конфигурации:** Перед изменением алгоритмов или параметров upstream создайте бэкап и проверяйте конфигурацию через `nginx -t`.

## Дополнительная информация

### См. также

- [Алгоритмы балансировки нагрузки](./algorithms.md) — выбор метода распределения запросов.
- [Health Checks и мониторинг](./health_checks_and_monitoring.md) — пассивные и активные проверки состояния.
- [Динамическое разрешение DNS](./dynamic_dns_resolution.md) — работа с динамическими IP бэкендов.

### Примечания

- В Nginx Open Source базовый набор алгоритмов (Round Robin, Least Connections, Hash, IP Hash, Random) доступен без дополнительных модулей. Для sticky-сессий используйте `ip_hash` или `hash`, либо сторонние модули.
- Angie и Nginx Plus расширяют базовый функционал алгоритмами `least_time` и `feedback`, а также параметрами `slow_start`, `drain` и `queue`.
- Динамическое разрешение DNS в `upstream` доступно в Nginx OSS начиная с версии 1.27.3. В более ранних версиях используется трюк с переменной в `proxy_pass`. Подробности: [Динамическое разрешение DNS](./dynamic_dns_resolution.md).
- Для stateful-приложений, требующих привязки сессий, в Nginx OSS используйте `ip_hash` или `hash`, а в Angie/Nginx Plus — встроенный метод `sticky`.
