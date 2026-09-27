# Настройка Angie в роли обратного HTTP-прокси

## Определения

**Обратный прокси-сервер (Reverse Proxy)** — промежуточный узел в архитектуре сети, который принимает запросы от внешних клиентов и распределяет их между одним или несколькими внутренними бэкенд-серверами. Он выступает в роли единственной точки входа (Gateway), обеспечивая централизованное управление трафиком, безопасностью и производительностью.

**Бэкенд (Upstream)** — целевой сервер или группа серверов (приложение, микросервис, база данных), которые непосредственно обрабатывают запросы.

## Базовые концепции

В Angie (и Nginx) функциональность обратного прокси реализуется модулем `ngx_http_proxy_module`. Он позволяет не только пересылать трафик, но и модифицировать его «на лету», обеспечивая абстракцию между клиентом и инфраструктурой.

### Ключевые функции
1.  **Терминация протоколов:** Прием трафика по современным протоколам (HTTP/3, TLS 1.3) и трансляция его на бэкенд по более простым (HTTP/1.1) для снижения нагрузки на приложение.
2.  **Балансировка и отказоустойчивость:** Автоматическое распределение запросов и переключение на резервные узлы при сбоях.
3.  **Изоляция и безопасность:** Сокрытие топологии сети и реальных IP-адресов бэкендов, фильтрация нежелательных запросов.
4.  **Буферизация и кэширование:** Оптимизация передачи данных для медленных клиентов и снижение нагрузки на бэкенд за счет повторного использования ответов.

### Минимальная конфигурация
```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        # Пересылка всех запросов на локальное приложение
        proxy_pass http://127.0.0.1:8080;
    }
}
```

### Жизненный цикл запроса
При работе в роли обратного прокси Angie обрабатывает каждый запрос через последовательность этапов:

1.  **Прием соединения:** Воркер Angie принимает TCP-соединение от клиента. Для HTTPS выполняется терминация TLS (`ssl_certificate`, `ssl_certificate_key`).
2.  **Выбор локации (`location`):** Angie сопоставляет URI запроса с наиболее специфичным блоком `location`. Если блок содержит `proxy_pass`, запрос направляется на проксирование.
3.  **Проверка кэша:** Если включено кэширование (`proxy_cache`), Angie ищет готовый ответ в кэше перед обращением к бэкенду.
4.  **Подготовка запроса к бэкенду:**
    *   Выполняется перезапись URI (при наличии замены в `proxy_pass`).
    *   Устанавливаются заголовки (`proxy_set_header`), заменяющие или добавляющие метаданные (Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto).
    *   При необходимости открывается keepalive-соединение с бэкендом из пула.
5.  **Отправка запроса бэкенду:** Запрос передается на выбранный сервер из группы `upstream`. Для долгоживущих протоколов (WebSocket) может повышаться версия HTTP (`proxy_http_version 1.1`).
6.  **Буферизация ответа:** Ответ бэкенда считывается в буферы (`proxy_buffers`, `proxy_buffer_size`). Размер буферов определяет, сколько данных можно получить от бэкенда до того, как воркер начнет отправлять ответ клиенту.
7.  **Отправка ответа клиенту:** После завершения чтения или при заполнении буферов Angie начинает передачу ответа клиенту. Если клиент разрывает соединение, по умолчанию Angie прерывает и чтение от бэкенда (регистрирует ошибку 499 в логах).
8.  **Завершение транзакции:** Соединение с бэкендом либо возвращается в пул keepalive, либо закрывается (в зависимости от заголовков и директив). Воркер освобождается для обработки следующего запроса.

## Практические сценарии

### Сценарий 1: Управление заголовками и реальный IP
Бэкенд должен знать параметры оригинального запроса. Для этого прокси передает метаданные в HTTP-заголовках.

```nginx
location / {
    proxy_pass http://backend_pool;
    
    # Передача оригинального хоста
    proxy_set_header Host $host;
    # Передача реального IP клиента
    proxy_set_header X-Real-IP $remote_addr;
    # Формирование цепочки прокси-серверов
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    # Передача схемы (http или https)
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### Сценарий 2: Оптимизация буферизации для высоких нагрузок
Буферизация (`proxy_buffering on`) позволяет Angie максимально быстро вычитать ответ из бэкенда в свою память, освобождая воркер приложения для следующего запроса.

```nginx
location /api/ {
    proxy_pass http://backend;
    
    proxy_buffering on;
    # Размер буфера для чтения заголовков ответа
    proxy_buffer_size 4k;
    # 8 буферов по 8кб для тела ответа
    proxy_buffers 8 8k;
    # Максимальный размер данных, отправляемых клиенту одновременно
    proxy_busy_buffers_size 16k;
}
```

### Сценарий 3: Отказоустойчивость и повторные попытки (Failover)
Настройка логики переключения на другой бэкенд при возникновении ошибок.

```nginx
location / {
    proxy_pass http://app_cluster;
    
    # Переключаться при ошибках сети или 502/503/504 кодах
    proxy_next_upstream error timeout http_502 http_503 http_504;
    # Ограничение количества попыток
    proxy_next_upstream_tries 3;
    # Общий таймаут на все попытки
    proxy_next_upstream_timeout 10s;
}
```

### Сценарий 4: Перехват ошибок бэкенда
Позволяет скрыть технические ошибки приложения и показать пользователю брендированную страницу.

```nginx
location / {
    proxy_pass http://app;
    # Перехватывать ответы со статусом >= 300
    proxy_intercept_errors on;
}

# Определение кастомной страницы для 50x ошибок
error_page 500 502 503 504 /static/custom_50x.html;
```

### Сценарий 5: Поддержка современных протоколов (WebSocket, gRPC, HTTP/3)
Angie поддерживает прозрачное проксирование бинарных и долгоживущих протоколов.

**WebSocket:**
```nginx
location /ws/ {
    proxy_pass http://ws_backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s; # Важно для WebSocket
}
```

**gRPC:**
```nginx
location /api.v1.Service/ {
    grpc_pass grpc://backend_grpc;
}
```

**HTTP/3 на бэкенд (Эксклюзивно для Angie):**
Angie умеет взаимодействовать с бэкендом по протоколу HTTP/3, что уникально для данной ветки серверов.
```nginx
location /h3-internal/ {
    proxy_pass https://modern_backend;
    proxy_http_version 3.0;
}
```

Подробный разбор долгоживущих протоколов (Upgrade-handshake, балансировка WebSocket, SSE и избежание буферизации, TLS к gRPC-бэкенду) — [WebSocket, SSE и gRPC в Angie](./angie-websocket-sse-grpc.md). Дублирование трафика на тестовые стенды — [Mirror в Angie](./angie-traffic-mirroring.md).

### Сценарий 6: Управление при обрыве соединения клиентом
По умолчанию Nginx/Angie закрывает соединение с бэкендом, если клиент разорвал связь (например, закрыл вкладку). Это вызывает ошибку **499 (Client Closed Request)** в логах. Директива `proxy_ignore_client_abort` позволяет дождаться ответа бэкенда.

```nginx
location /long-transaction/ {
    proxy_pass http://backend;
    
    # Не обрывать запрос к бэкенду при уходе клиента
    # Полезно для записи в БД или наполнения кэша
    proxy_ignore_client_abort on;
}
```

### Сценарий 7: Терминация TLS на прокси
Angie принимает HTTPS-соединение от клиента, расшифровывает его и пересылает трафик бэкенду по HTTP или HTTPS. Это снижает нагрузку на бэкенд и централизует управление сертификатами.

```nginx
server {
    listen 443 ssl;
    server_name secure.example.com;

    ssl_certificate     /etc/angie/ssl/example.com.crt;
    ssl_certificate_key /etc/angie/ssl/example.com.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://backend_cluster;
        # Передаем информацию о исходной схеме
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Для проксирования на бэкенд по HTTPS используйте `https://` в `proxy_pass` и при необходимости настройте проверку сертификата:
```nginx
location / {
    proxy_pass https://backend;
    proxy_ssl_verify       on;
    proxy_ssl_verify_name  on;
    proxy_ssl_trusted_certificate /etc/angie/ssl/ca-bundle.crt;
}
```

### Сценарий 8: Ограничение скорости и доступ
Для защиты бэкенда отburst-нагрузки или неавторизованного доступа используйте `limit_req` и `allow`/`deny` в контексте прокси.

```nginx
# Ограничение: 10 запросов в секунду на IP
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

server {
    listen 80;
    server_name api.example.com;

    # Разрешаем только внутреннюю сеть
    allow 10.0.0.0/8;
    allow 192.168.0.0/16;
    deny all;

    location / {
        limit_req zone=api_limit burst=20 nodelay;
        proxy_pass http://api_backend;
        proxy_set_header Host $host;
    }
}
```

> **Ограничение исходящей скорости (`limit_rate`):** для ограничения полосы загрузки (например, крупных файлов) используйте `limit_rate`/`limit_rate_after` — см. **[Защита от DoS-атак в Angie](./High_Load/dos_protection.md)** (раздел «Ограничение пропускной способности»).

## Операции и команды

### Верификация конфигурации прокси

Перед применением изменений всегда проверяйте синтаксис:

```bash
# Проверка синтаксиса всего конфига
angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка только конфигурации upstream (если используется include)
angie -c /etc/angie/angie.conf -t
```

### Тестирование upstream и эндпоинтов

Проверка доступности бэкендов до и после внесения изменений:

```bash
# Проверка доступности конкретного бэкенда через curl (с подменой Host)
curl -I -H "Host: example.com" http://127.0.0.1:8080/health

# Проверка что прокси пересылает запрос на правильный бэкенд
curl -I -H "Host: example.com" http://127.0.0.1/

# Проверка ответа бэкенда через прокси с учетом заголовков
curl -v -H "X-Real-IP: 1.2.3.4" http://127.0.0.1/api/status
```

### Управление службой

```bash
# Применение конфигурации без потерь соединений
systemctl reload angie

# Проверка статуса
systemctl status angie
# → Active: active (running) since Mon 2026-09-21 10:00:00 UTC; 2 days ago

# Просмотр логов при проблемах проксирования
journalctl -u angie -f --since "10 minutes ago"

# Поиск ошибок upstream в логах
grep -E "upstream|502|503|504" /var/log/angie/error.log
```

### Инспекция логов и переменных

```bash
# Использование расширенного формата логов с upstream-переменными
# (предварительно настроить log_format в http{} блоке)
tail -F /var/log/angie/access.log | awk '{print $1, $7, $9, $10, $11}'
# → IP URI upstream_status upstream_response_time upstream_connect_time

# Поиск запросов с большим временем ответа (>1s)
awk -v limit=1 '$10 > limit {print $0}' /var/log/angie/access.log
```

### Проверка состояния upstream через API

```bash
# Получение списка серверов в upstream
curl -s http://127.0.0.1:8888/api/status/http/upstreams/backend_cluster/ | jq '.peers[] | {server, state, active}'

# Проверка keepalive соединений для конкретного upstream
curl -s http://127.0.0.1:8888/api/status/http/upstreams/backend_cluster/ | jq '{
    upstream_peers: [.peers[] | {server, keepalive, selected: .selected.current}],
    total_active: (.peers | map(.active) | add)
}'
```

### Диагностика DNS и сети

```bash
# Проверка резолвинга домена бэкенда
dig backend.internal +short

# Проверка TCP-доступности порта бэкенда
nc -zv backend.internal 8080
# → Connection succeeded!

# Трассировка до бэкенда для выявления сетевых проблем
traceroute -T -p 8080 backend.internal
```

## Устранение неисправностей

### 502 Bad Gateway
**Причина:** Бэкенд недоступен, не отвечает или возвращает невалидный ответ.

**Диагностика:**
```bash
# Проверка доступности бэкенда напрямую
curl -v http://backend.internal:8080/health

# Проверка логов Angie
grep -E "connect() failed|Connection refused" /var/log/angie/error.log

# Проверка что upstream объявлен корректно
angie -T | grep -A5 "upstream backend"
```

**Решения:**
- Убедитесь что бэкенд запущен и слушает указанный порт (`ss -tlnp | grep 8080`).
- Проверьте firewall между Angie и бэкендом.
- Если используется `upstream` с балансировкой — проверьте что хотя бы один сервер доступен (не все помечены как `down`).
- Для HTTPS-бэкендов проверьте срок действия сертификата и цепочку доверия (`openssl s_client -connect backend:443`).

### 504 Gateway Timeout
**Причина:** Бэкенд не ответил за отведенное время.

**Диагностика:**
```bash
# Проверка текущего значения таймаута
angie -T | grep proxy_read_timeout

# Измерение времени ответа бэкенда напрямую
time curl -o /dev/null -s http://backend.internal:8080/api/slow-endpoint
```

**Решения:**
- Увеличьте `proxy_read_timeout` для медленных эндпоинтов (например, генерации отчетов).
- Проверьте нагрузку на бэкенд (`top`, `htop`, `iostat`).
- Если бэкенд делает внешние вызовы — проверьте его сетевую доступность.
- Убедитесь что `proxy_connect_timeout` не слишком мал для установки TLS-соединения.

### 503 Service Unavailable
**Причина:** Нет доступных бэкендов в группе `upstream` (все помечены как DOWN или превышено `max_conns`).

**Диагностика:**
```bash
# Проверка статуса серверов в upstream через API
curl -s http://127.0.0.1:8888/api/status/http/upstreams/app_cluster/ | jq '.peers[] | {server, state, fails}'
```

**Решения:**
- Проверьте логи бэкенда на предмет падения процесса.
- Если используются активные проверки (`check` или `upstream_probe`) — проверьте их конфигурацию и доступность health-check эндпоинта.
- Для PRO версии проверьте настройки очереди (`queue`) и лимитов соединений (`max_conns`).
- Временно выведите сервер из балансировки через API, исправьте проблему и верните обратно.

### Ошибка DNS (upstream не резолвится)
**Причина:** Неправильное доменное имя в `proxy_pass` или недоступность DNS-сервера.

**Диагностика:**
```bash
# Проверка резолвинга с хоста, где работает Angie
dig backend.internal +short
nslookup backend.internal

# Проверка /etc/resolv.conf
cat /etc/resolv.conf
```

**Решения:**
- Используйте IP-адреса вместо домен для критических upstream, либо настройте `resolver` в блоке `http` с валидными DNS-серверами.
- Проверьте что DNS-сервер доступен из сети Angie (`dig @<dns-ip> backend.internal`).
- Для динамических upstream (Docker Discovery) убедитесь что Docker-socket доступен и метки контейнеров корректны.

### Сбои TLS при проксировании на бэкенд
**Причина:** Несовпадение версий TLS, невалидный сертификат, неправильная конфигурация SNI.

**Диагностика:**
```bash
# Проверка TLS-рукопожатия с бэкендом
openssl s_client -connect backend.internal:443 -servername backend.internal

# Проверка что Angie отправляет правильный SNI
curl -vvv https://backend.internal/ --proxy-insecure
```

**Решения:**
- Укажите `proxy_ssl_server_name on;` для передачи SNI на бэкенд.
- Используйте `proxy_ssl_trusted_certificate` с корневым CA бэкенда.
- Если бэкенд использует самоподписанный сертификат — добавьте его в доверенные.
- Убедитесь что версия TLS в `proxy_ssl_protocols` поддерживается бэкендом.

### Исчерпание пула keepalive-соединений
**Причина:** Слишком маленькое значение `keepalive` в upstream при высокой нагрузке, или отсутствие `proxy_http_version 1.1`.

**Диагностика:**
```bash
# Проверка метрик keepalive через API
curl -s http://127.0.0.1:8888/api/status/http/upstreams/backend_cluster/ | jq '.peers[] | {server, keepalive}'
```

**Решения:**
- Увеличьте значение `keepalive` в блоке `upstream` (по умолчанию неактивировано).
- Обязательно добавьте в `location`:
  ```nginx
  proxy_http_version 1.1;
  proxy_set_header Connection "";
  ```
- Проверьте что `keepalive` объявлен после директив балансировки (least_time, sticky и т.д.).
- Мониторьте метрику `keepalive.idle` через API — она показывает количество простаивающих соединений в пуле.

### Потеря реального IP клиента (все запросы от 127.0.0.1)
**Причина:** Не настроена передача заголовков `X-Real-IP` и `X-Forwarded-For`.

**Диагностика:**
```bash
# Проверка что Angie передает заголовки
curl -H "X-Real-IP: 5.6.7.8" http://127.0.0.1/ | grep -i "remote addr"
```

**Решения:**
- Добавьте в конфигурацию `location`:
  ```nginx
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  ```
- Если перед Angie стоит CDN или WAF — настройте `set_real_ip_from` и `real_ip_header` для корректного извлечения реального IP из заголовка CDN.

## Лучшие практики

### Версия HTTP и пул keepalive
Всегда используйте HTTP/1.1 для проксирования, чтобы эффективно повторно использовать соединения с бэкендом:

```nginx
upstream backend_cluster {
    zone backend_cluster 64k;
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
    keepalive 32;
}

server {
    location / {
        proxy_pass http://backend_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
```

### Изоляция внутренних и внешних upstream
Разделяйте конфигурацию upstream по доменам ответственности:
- Внутренние сервисы (базы данных, кэш) — отдельные `upstream` группы с ограниченным доступом по сети.
- Внешние API — выделенные группы с индивидуальными таймаутами и retry-логикой.
- Используйте именование `upstream` по назначению (`api_pool`, `static_pool`, `db_primary`), а не по адресам.

### Таймауты на основе характеристик бэкенда
Настраивайте таймауты дифференцированно:
- **API/JSON:** короткие таймауты (`proxy_connect_timeout 5s`, `proxy_read_timeout 30s`).
- **Загрузка файлов/медиа:** увеличенный `proxy_read_timeout` (300s+) и `client_body_timeout`.
- **WebSocket:** `proxy_read_timeout` от 1 часа, так как соединение долгоживущее.

### Верификация TLS между Angie и бэкендом
Для внутреннего трафика используйте взаимную аутентификацию (mTLS), особенно если бэкенды работают в разных сегментах сети:
- Включите `proxy_ssl_verify on;` и `proxy_ssl_verify_name on;`.
- Укажите корневой CA внутренней PKI через `proxy_ssl_trusted_certificate`.
- Это защищает от атак типа man-in-the-middle внутри сети.

### Ограничение размера буферов и тела запроса
- Устанавливайте `proxy_buffer_size` исходя из размера заголовков бэкенда (обычно 4k–8k).
- Используйте `proxy_max_temp_file_size` для ограничения размера ответов, которые не помещаются в память.
- Ограничивайте `client_max_body_size` на уровне `location` для предотвращения переполнения диска временными файлами.

### Единый формат логов
Определите расширенный `log_format` в блоке `http` и используйте его во всех `access_log`. Включите upstream-переменные для корреляции запросов:

```nginx
log_format upstream_combined '$remote_addr - $remote_user [$time_local] '
    '"$request" $status $body_bytes_sent '
    '"$http_referer" "$http_user_agent" '
    'rt=$request_time ua="$upstream_addr" '
    'us="$upstream_status" ut="$upstream_response_time" '
    'uc="$upstream_connect_time"';
```

### Мониторинг upstream-метрик
Интегрируйте API Angie в систему мониторинга (Prometheus, Zabbix). Собирайте как минимум:
- `upstream_status` — распределение HTTP-кодов от бэкендов.
- `upstream_response_time` — латентность приложения.
- `upstream_connect_time` — сетевые задержки до бэкендов.
- `peers[].state` — доступность серверов в группе.
- `keepalive.idle` — эффективность пула соединений.

## Дополнительная информация

### Управление пулом соединений (Keep-alive)
Для снижения задержек на установку TCP-соединений (Handshake) рекомендуется использовать пул постоянных соединений в блоке `upstream`.
```nginx
upstream backend_cluster {
    server 10.0.0.1:8080;
    # Держать открытыми до 32 соединений
    keepalive 32;
}
```

### Сравнение таймаутов
| Директива | Описание | Рекомендуемое значение | Связь с ошибкой 499 |
| :--- | :--- | :--- | :--- |
| `proxy_connect_timeout` | Время на установку TCP-соединения с бэкендом. | 5s–10s | Приводит к 502/504, если бэкенд недоступен. |
| `proxy_send_timeout` | Таймаут передачи запроса бэкенду. | 30s–60s | Редко является причиной 499. |
| `proxy_read_timeout` | Ожидание ответа бэкенда (между двумя операциями чтения). | 60s+ | Если меньше таймаута клиента — 504. Если больше — клиент может уйти сам (499). |

### Переменные мониторинга
Для анализа работы прокси в `log_format` используйте:
*   `$upstream_addr` — IP и порт бэкенда, обработавшего запрос.
*   `$upstream_status` — HTTP-статус ответа от бэкенда.
*   `$upstream_response_time` — время обработки запроса бэкендом.
*   `$upstream_connect_time` — время на установку соединения.

## См. также

*   **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — алгоритмы, веса и sticky-сессии.
*   **[Динамические апстримы в Angie](./dynamic_upstreams.md)** — Service Discovery (DNS, Docker).
*   **[Настройка TLS в Angie](./angie_tls_setup.md)** — терминация HTTPS.
*   **[Серверное кэширование (Proxy Cache) в Nginx и Angie](../Nginx/Performance/Caching/proxy_caching.md)** — кэширование ответов бэкенда.
*   **[Реальный IP клиента (Real-IP) и X-Forwarded-For](../../Networking/Protocols/HTTP/http_servers_proxies.md)** — `real_ip_header`, `set_real_ip_from`, PROXY protocol.
*   **[Безопасность HTTP в продакшене](../../Networking/Protocols/HTTP/http_security_hardening.md)** — security-заголовки, CORS, request smuggling.
*   **[Оптимизация сжатия в Nginx](../Nginx/Performance/nginx_compression.md)** — gzip / brotli / zstd для ответов.
