# Динамические группы проксируемых серверов в Angie

## Определения

**Динамический Upstream в Angie** — это механизм автоматического управления составом групп бэкенд-серверов (IP-адреса, порты, веса, параметры доступности) без необходимости перезагрузки конфигурации (`reload`).

**Обнаружение сервисов (Service Discovery)** — процесс автоматического поиска и регистрации адресов экземпляров приложений в распределенной среде. Общие принципы и модели (Client-side vs Server-side) описаны в [обзоре Service Discovery](../../Concepts/service-discovery-overview.md). Angie реализует этот процесс через интеграцию с внешними источниками данных: DNS, Docker API и специализированный конфигурационный API.

**Zone (зона разделяемой памяти)** — именованный сегмент shared memory, в котором хранится состояние группы серверов, включая текущие IP-адреса, веса, флаги доступности и метрики производительности. Обязательна для работы любых продвинутых функций upstream.

**State file (файл состояния)** — персистентное хранилище текущего состава upstream на диске. Используется для восстановления динамически добавленных серверов после перезагрузки Angie.

## Базовые концепции

### Механизм разделяемой памяти (zone)

Для работы любого динамического апстрима обязательна директива `zone`. Она выделяет область памяти, доступную всем рабочим процессам (workers), где хранится текущее состояние группы серверов.

*   **Синтаксис:** `zone <name> <size>;`
*   **Размер:** 64–128 КБ обычно достаточно для хранения данных о 50–200 серверах. Для крупных установок (тысячи контейнеров) используйте `1m`–`2m`.
*   **Важно:** Без `zone` динамические обновления (DNS `resolve`, Docker discovery, API) не работают. В блоке с `state` нельзя использовать статические директивы `server`.

### Жизненный цикл динамического обновления

При использовании динамических методов обновления состава upstream Angie выполняет следующие действия:

1.  **Инициализация:** При старте или `reload` Angie загружает существующие данные из зоны. Если указан `state`, дополнительно читает файл состояния.
2.  **Обнаружение изменений:**
    *   **DNS:** Периодически опрашивает DNS-сервер с интервалом, определяемым параметром `valid` в `resolver`. При изменении IP-адреса старые соединения через `keepalive` не разрываются — они используют кэш до истечения `keepalive_timeout`.
    *   **Docker:** Подписывается на события контейнеров (start, stop, pause, unpause, destroy) через Docker API. Изменения применяются мгновенно без задержки на TTL.
    *   **API (PRO):** Изменения применяются атомарно сразу после успешного `PUT`/`PATCH`/`DELETE` запроса.
3.  **Применение:** Новые адреса добавляются в группу, удаленные — помечаются как `down` или удаляются полностью. Существующие сессии через `keepalive` продолжают обслуживаться.
4.  **Восстановление:** При перезагрузке (`reload`) данные из зоны сохраняются. Файл `state` (если указан) записывается на диск.

### Преимущества перед Nginx OSS

В отличие от стандартного Nginx, где имена серверов разрешаются только один раз при старте, Angie:
1.  **Периодически обновляет DNS-записи** согласно TTL или заданному интервалу `valid`.
2.  **Нативно работает с Docker API**, отслеживая запуск и остановку контейнеров через события.
3.  **Предоставляет API управления** (Angie PRO) для изменения параметров upstream без перезагрузки.

### Сохранение состояния (state)

Директива `state` позволяет сохранять текущую конфигурацию в файл для восстановления после перезагрузки процесса.

*   **Синтаксис:** `state /var/lib/angie/state/<filename>;`
*   **Важно:** В апстриме с `state` нельзя использовать статические директивы `server`. Зона `zone` при этом обязательна.
*   **Путь:** В официальных пакетах директория `/var/lib/angie/state/` создается автоматически с правильными правами доступа.

## Практические сценарии

### Сценарий 1: Динамическое разрешение DNS (A/AAAA)

Используется в средах с эфемерными IP-адресами (Kubernetes, Docker swarm, облачные балансировщики). Angie периодически повторяет DNS-запросы и обновляет список серверов без reload.

```nginx
http {
    # Резолвер обязателен. valid переопределяет TTL из DNS.
    resolver 127.0.0.1 valid=30s;
    resolver_timeout 5s;

    upstream app_servers {
        zone app_servers 64k;
        # Параметр resolve активирует динамическое обновление
        server backend.internal.cloud resolve;
    }
}
```

**Валидация:**
```bash
# Проверка что DNS разрешается
dig backend.internal.cloud +short
# → 10.0.0.5
# → 10.0.0.6

# Проверка статуса через API
curl -s http://127.0.0.1/status/http/upstreams/app_servers/ | jq '.peers'
# → {"10.0.0.5:80": {"state": "up", ...}, "10.0.0.6:80": {"state": "up", ...}}
```

### Сценарий 2: Использование DNS SRV-записей

Идеально для интеграции с **Consul** или **HashiCorp Nomad**, так как SRV-записи передают не только IP, но и порты, веса и приоритеты.

```nginx
http {
    resolver 10.0.0.1;

    upstream consul_services {
        zone consul_services 128k;
        # service=http указывает Angie искать SRV-записи для _http._tcp.web.service.consul
        server web.service.consul service=http resolve;
    }
}
```

**Валидация:**
```bash
# Проверка SRV-записей
dig web.service.consul SRV +short
# → 10 1 8080 host1.service.consul.
# → 20 1 8080 host2.service.consul.

# Проверка что Angie подхватил записи
curl -s http://127.0.0.1/status/http/upstreams/consul_services/ | jq '.peers | keys'
# → ["host1.service.consul:8080", "host2.service.consul:8080"]
```

### Сценарий 3: Нативная интеграция с Docker

Angie подключается к Docker API и автоматически наполняет upstream контейнерами, имеющими соответствующие метки (labels). Модуль поддерживает Docker и совместимые с ним инструменты (Podman 4.9.3+).

**1. Настройка в Docker Compose:**

```yaml
services:
  webapp:
    image: my-app:latest
    labels:
      - "angie.http.upstreams.pool1.port=8080"
      - "angie.network=my_bridge"
      - "angie.http.upstreams.pool1.weight=2"
      - "angie.http.upstreams.pool1.max_conns=50"
      - "angie.http.upstreams.pool1.max_fails=3"
      - "angie.http.upstreams.pool1.fail_timeout=10s"
      - "angie.http.upstreams.pool1.backup=true"
      - "angie.http.upstreams.pool1.slow_start=30s"
```

**2. Конфигурация в Angie:**

```nginx
http {
    # Подключение к Docker API (unix socket или TCP)
    docker_endpoint unix:/var/run/docker.sock;
    # docker_max_object_size 128k; # опционально, для >25 контейнеров

    upstream pool1 {
        zone pool1 64k;
        # Серверы добавятся автоматически при появлении контейнеров с метками
    }
}
```

**Валидация:**
```bash
# Проверка что контейнер получил метки
docker ps --filter label=angie.http.upstreams.pool1.port
# → CONTAINER ID   IMAGE       LABELS
# → abc12345       my-app:latest {"angie.http.upstreams.pool1.port":"8080", ...}

# Проверка событий Docker в логах Angie
sudo tail -f /var/log/angie/error.log | grep -i docker
# → [docker] connected to Docker API
# → [docker] container abc12345 added to upstream pool1
# → [docker] container abc12345 removed from upstream pool1
```

### Сценарий 4: Управление через API (Angie PRO)

Angie PRO предоставляет REST API для динамического управления upstream без перезагрузки. API поддерживает атомарные операции: добавление, изменение и удаление серверов.

```nginx
http {
    upstream dynamic_api {
        zone dynamic_api 128k;
        state /var/lib/angie/state/dynamic_api.conf;
    }

    server {
        listen 8080;
        
        location /config {
            api /config/;
            allow 127.0.0.1;
            allow 10.0.0.0/8;
            deny all;
        }
    }
}
```

**Примеры операций:**

```bash
# Просмотр текущего состава (defaults=on показывает все параметры)
curl -s http://127.0.0.1/config/http/upstreams/dynamic_api/servers?defaults=on | jq .

# Добавление сервера
curl -X PUT -d '{"server": "10.0.0.5:80", "weight": 2, "max_conns": 100}' \
  http://127.0.0.1/config/http/upstreams/dynamic_api/servers/10.0.0.5:80

# Изменение веса существующего сервера
curl -X PATCH -d '5' \
  http://127.0.0.1/config/http/upstreams/dynamic_api/servers/10.0.0.5:80/weight

# Вывод сервера на обслуживание (drain)
# В drain-режиме сервер продолжает обрабатывать sticky-сессии,
# но не принимает новые запросы
curl -X PUT -d "drain" \
  http://127.0.0.1/config/http/upstreams/dynamic_api/servers/10.0.0.5:80/down

# Удаление сервера (с принудительным закрытием соединений)
curl -X DELETE \
  "http://127.0.0.1/config/http/upstreams/dynamic_api/servers/10.0.0.5:80?connection_drop=1000"

# Сброс параметра к значению по умолчанию
curl -X DELETE \
  http://127.0.0.1/config/http/upstreams/dynamic_api/servers/10.0.0.5:80/weight
```

### Сценарий 5: Kubernetes CoreDNS интеграция

В Kubernetes окружении DNS-имена сервисов (_http._tcp.<service>.<namespace>.svc.cluster.local) можно использовать для автоматического discovery.

```nginx
http {
    resolver kube-dns.kube-system.svc.cluster.local valid=10s;
    resolver_timeout 2s;

    upstream k8s_api {
        zone k8s_api 64k;
        # SRV-записи в Kubernetes передают порт сервиса
        server api-service.default.svc.cluster.local service=_http._tcp resolve;
    }
}
```

**Валидация:**
```bash
# Проверка SRV в Kubernetes
dig api-service.default.svc.cluster.local SRV +short
# → 10 100 8080 api-service-0.default.svc.cluster.local.

# Проверка upstream
curl -s http://127.0.0.1/status/http/upstreams/k8s_api/ | jq '.peers | keys'
```

### Сценарий 6: Смешанная конфигурация (статический + динамический fallback)

Комбинирование статического сервера с динамическими, обеспечивающее отказоустойчивость при недоступности DNS или Docker.

```nginx
http {
    upstream mixed_app {
        zone mixed_app 64k;
        
        # Статический fallback-сервер (всегда доступен)
        server 192.168.1.100:8080 backup;
        
        # Динамические серверы из DNS
        server app.internal.cloud resolve;
    }

    server {
        location / {
            proxy_pass http://mixed_app;
            # Резервный маршрут если все upstream недоступны
            error_page 502 503 504 = @fallback;
        }

        location @fallback {
            return 503 "Service temporarily unavailable\n";
        }
    }
}
```

## Операции и команды

### Управление процессами Angie

```bash
# Проверка конфигурации перед применением
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Применение конфигурации (zero downtime)
sudo angie -s reload

# Перезапуск worker процессов
sudo angie -s reopen

# Остановка сервера (graceful)
sudo angie -s quit

# Принудительная остановка
sudo angie -s stop
```

### Тестирование разрешения имен

```bash
# Проверка A/AAAA записи
dig backend.internal.cloud A +short
# → 10.0.0.5
# → 10.0.0.6

# Проверка SRV-записи
dig web.service.consul SRV +short
# → 10 1 8080 host1.service.consul.

# Проверка с кастомным резолвером
dig @10.0.0.1 backend.internal.cloud A +short

# Проверка TTL записи
dig backend.internal.cloud +nocmd +noall +answer
# → backend.internal.cloud.  30  IN  A  10.0.0.5
#   (TTL=30 секунд, должен совпадать с valid=30s в конфигурации)
```

### Управление Docker discovery

```bash
# Проверка доступности Docker API
curl -s --unix-socket /var/run/docker.sock http://localhost/_ping
# → OK

# Поиск контейнеров с нужными метками
docker ps --filter "label=angie.http.upstreams.pool1.port"
# → CONTAINER ID   IMAGE       LABELS
# → abc12345       my-app:latest {"angie.http.upstreams.pool1.port":"8080", ...}

# Просмотр всех меток контейнера
docker inspect abc12345 --format '{{ json .Config.Labels }}' | jq .

# Проверка прав на сокет Docker
ls -la /var/run/docker.sock
# → srw-rw---- 1 root docker ... /var/run/docker.sock
# Пользователь angie должен быть в группе docker

# Проверка сетей Docker
docker network ls
# → NETWORK ID     NAME        DRIVER    SCOPE
# → abc12345       my_bridge   bridge     local

# Просмотр событий Docker в реальном времени
docker events --filter 'type=container' --filter 'event=start|stop|destroy'
```

### Управление через API (Angie PRO)

```bash
# Получение списка всех upstream (read-only status)
curl -s http://127.0.0.1/status/http/upstreams/ | jq 'keys'
# → ["app_servers", "dynamic_api", "pool1"]

# Просмотр деталей конкретного upstream
curl -s http://127.0.0.1/status/http/upstreams/dynamic_api/ | jq '.peers'
# → {"10.0.0.5:80": {"state": "up", "weight": 2, ...}, ...}

# Просмотр с Pretty=off для компактного вывода
curl -s "http://127.0.0.1/status/http/upstreams/dynamic_api/?pretty=off" | jq .

# Получение списка серверов через config API (PRO)
curl -s http://127.0.0.1/config/http/upstreams/dynamic_api/servers | jq .

# Параллельные запросы к нескольким upstream
for upstream in app_servers pool1 dynamic_api; do
  echo "=== $upstream ==="
  curl -s "http://127.0.0.1/status/http/upstreams/$upstream/" | \
    jq '.peers | to_entries[] | {server: .key, state: .value.state, weight: .value.weight}'
done
```

### Управление файлом состояния

```bash
# Путь к файлу состояния (согласно директиве state)
STATE_FILE="/var/lib/angie/state/dynamic_api.conf"

# Просмотр содержимого
cat "$STATE_FILE"
# → server 10.0.0.5:80 weight=2 max_conns=100;
# → server 10.0.0.6:80 weight=1;

# Резервное копирование перед изменениями
cp "$STATE_FILE" "${STATE_FILE}.bak.$(date +%Y%m%d%H%M%S)"

# Проверка прав доступа
ls -la "$STATE_FILE"
# → -rw-r----- 1 angie angie ... dynamic_api.conf

# Восстановление из резервной копии
sudo systemctl stop angie
cp "${STATE_FILE}.bak.20260921120000" "$STATE_FILE"
sudo systemctl start angie
```

## Устранение неисправностей

### Динамические серверы не добавляются в upstream

**Симптомы:** В `/status/http/upstreams/<name>/` отображается только статический сервер или группа пуста. В `error.log` нет сообщений о добавлении серверов.

**Диагностика:**
```bash
# 1. Проверка что zone объявлена
grep -n "zone.*<name>" /etc/angie/angie.conf
# → upstream <name> { zone <name> 64k; ... }

# 2. Проверка логов Angie на предмет ошибок модуля
sudo tail -f /var/log/angie/error.log | grep -E "docker|upstream|zone"

# 3. Проверка что resolver работает (для DNS)
dig backend.internal.cloud @127.0.0.1
```

**Решение:**
*   Добавьте `zone <name> <size>;` в блок upstream.
*   Убедитесь что директива `resolver` указана в `http` блоке (для DNS).
*   Проверьте что директива `docker_endpoint` указана в `http` блоке (для Docker).

### DNS: серверы не обновляются после изменения IP

**Симптомы:** IP-адрес в upstream остался старым после изменения DNS-записи.

**Диагностика:**
```bash
# Проверка TTL в DNS
dig backend.internal.cloud +nocmd +noall +answer
# → backend.internal.cloud.  3600  IN  A  10.0.0.5

# Проверка параметра valid в Angie
grep -n "valid=" /etc/angie/angie.conf
# → resolver 127.0.0.1 valid=30s;
```

**Решение:**
*   Укажите `valid=30s` (или меньше) в директиве `resolver`, чтобы Angie опрашивала DNS чаще.
*   Для принудительного обновления выполните `sudo angie -s reload`.
*   Убедитесь что DNS-сервер доступен: `dig @127.0.0.1 backend.internal.cloud`.

### Docker: контейнеры не добавляются в upstream

**Симптомы:** В логах нет сообщений `[docker] container ... added to upstream ...`.

**Диагностика:**
```bash
# 1. Проверка доступности Docker API
curl -s --unix-socket /var/run/docker.sock http://localhost/_ping
# → OK

# 2. Проверка прав пользователя angie
id angie
# → uid=996(angie) gid=996(angie) groups=996(angie),999(docker)
# Группа docker ОБЯЗАТЕЛЬНА для доступа к /var/run/docker.sock

# 3. Проверка меток контейнера
docker inspect webapp --format '{{ json .Config.Labels }}' | jq .
# → {"angie.http.upstreams.pool1.port": "8080", ...}

# 4. Проверка что upstream name совпадает с меткой
# Метка: angie.http.upstreams.pool1.port
# Upstream: upstream pool1 { ... }
# Имена "pool1" должны совпадать!
```

**Решение:**
*   Добавьте пользователя `angie` в группу `docker`: `sudo usermod -aG docker angie`.
*   Перезапустите Angie после изменения групп: `sudo systemctl restart angie`.
*   Убедитесь что имя upstream в конфигурации совпадает с `<name>` в метке.
*   Для удаленного Docker API используйте `docker_endpoint http://host:2375;` и откройте порт в брандмауэре.

### Docker: ошибка "container not found" после перезагрузки

**Симптомы:** После `reload` контейнеры временно исчезают из upstream, затем появляются снова.

**Причина:** При перезагрузке Angie теряет соединение с Docker API. После переустановления соединения происходит повторное сканирование контейнеров.

**Решение:**
*   Это ожидаемое поведение. Для минимизации простоев используйте `state` директиву для сохранения состояния.
*   Убедитесь что Docker API стабильно доступен (для unix socket проверьте права, для TCP — стабильность сети).

### State file: ошибки при сохранении

**Симптомы:** В логах `error.log` появляются ошибки записи в state file. После reload динамические серверы исчезают.

**Диагностика:**
```bash
# Проверка существования директории
ls -la /var/lib/angie/state/
# → drwxr-xr-x  angie angie  ... state/

# Проверка прав на файл
ls -la /var/lib/angie/state/dynamic_api.conf
# → -rw-r-----  angie angie  ... dynamic_api.conf

# Проверка места на диске
df -h /var/lib/angie
```

**Решение:**
*   Убедитесь что пользователь `angie` имеет права на запись в директорию `/var/lib/angie/state/`.
*   Проверьте что `selinux` не блокирует запись (временно: `sudo setenforce 0` для диагностики).
*   Убедитесь что на диске достаточно свободного места.

### API (PRO): изменения не применяются

**Симптомы:** `PUT`/`PATCH` запросы возвращают 200, но сервер не появляется в upstream.

**Диагностика:**
```bash
# Проверка ответа API
curl -v -X PUT -d '{"server": "10.0.0.5:80"}' \
  http://127.0.0.1/config/http/upstreams/dynamic_api/servers/10.0.0.5:80
# → HTTP/1.1 201 Created
# → {"description": "New peer added."}

# Проверка что изменения применились
curl -s http://127.0.0.1/config/http/upstreams/dynamic_api/servers | jq .
```

**Решение:**
*   Убедитесь что upstream объявлен с `zone` и `state` (PRO).
*   Проверьте что API location настроен с `api /config/;` и `write` доступен.
*   Для HTTP upstream используйте `/config/http/upstreams/...`, для Stream — `/config/stream/upstreams/...`.

### Конфликт портов или ресурсов зоны

**Симптомы:** В логах `error.log`: `could not allocate shared memory zone`, `zone "pool1" already exists`.

**Решение:**
*   Убедитесь что имена `zone` уникальны в рамках одного Angie instance.
*   Увеличьте размер зоны или уменьшите количество серверов.
*   Проверьте что не осталось устаревших конфигов в `include` директориях.

## Лучшие практики

### Безопасность

*   **Docker socket:** Никогда не монтируйте `/var/run/docker.sock` в контейнер без необходимости. Если монтируете, используйте readonly (`:ro`) и ограничьте доступ через `allow/deny`.
*   **API доступ:** Выносите конфигурационный API на отдельный порт или `listen 127.0.0.1:8080;`. Никогда не делайте `write` доступ публичным.
*   **Аутентификация:** Используйте `auth_basic` или `auth_jwt` для защиты эндпоинта `/config/`.
*   **State file:** Устанавливайте права `0600` на state файлы. Директория `/var/lib/angie/state/` должна принадлежать пользователю `angie`.

### Эксплуатация

*   **TTL и валидация:** Настраивайте `resolver valid` с запасом 2–3 раза ниже TTL в DNS. Для внутренних сервисов используйте `valid=5s`–`30s`.
*   **Fallback:** Всегда добавляйте статический `backup` сервер в динамические upstream для случаев полной недоступности DNS/Docker.
*   **Мониторинг:** Настройте алерты на изменение количества серверов в upstream (`/status/http/upstreams/<name>/peers`).
*   **State backup:** Регулярно копируйте state файлы. При откате на старую версию конфигурации state может содержать серверы, которых уже нет в DNS/Docker.

### Производительность

*   **Размер зоны:** Для до 100 серверов достаточно `64k`. Для 500+ серверов используйте `1m`–`2m`.
*   **Keepalive:** Включайте `keepalive` в upstream для снижения накладных расходов на установку соединений. При использовании `resolve` кэшированные keepalive-соединения не разрываются при смене IP.
*   **Docker буфер:** При большом количестве контейнеров (>25) увеличьте `docker_max_object_size` до `128k` или `256k`.

### Ограничения и известные проблемы

*   **Docker:** Модуль отслеживает только контейнеры в Docker-сетях. Контейнеры с `network=host` добавляются с IP хоста, что может привести к конфликтам.
*   **DNS SRV:** Вес из SRV-записи игнорируется если задан `weight` в директиве `server`. Приоритеты SRV преобразуются в `backup`/primary разделение.
*   **State:** В одном upstream нельзя смешивать статические `server` и динамические (Docker/DNS/API) без `state`. При наличии `state` статические серверы игнорируются.
*   **Keepalive + resolve:** При удалении IP из DNS соответствующие keepalive-соединения остаются открытыми до истечения `keepalive_timeout`. Это поведение по design.

## Дополнительная информация

### Сравнение методов Service Discovery

| Метод | Привязка к | Обновление | Требует PRO | Параметры сервера |
| :--- | :--- | :--- | :--- | :--- |
| **DNS (A/AAAA)** | Доменное имя | По TTL (обычно 30–300с) | Нет | `weight`, `max_conns`, `backup` |
| **DNS SRV** | SRV-запись | По TTL | Нет | `weight` (из SRV), `backup` |
| **Docker labels** | Метки контейнера | Мгновенно (события) | Нет | `port`, `weight`, `max_conns`, `max_fails`, `fail_timeout`, `backup`, `slow_start`, `sid` |
| **HTTP API** | REST-запрос | Мгновенно | **Да** | `weight`, `max_conns`, `max_fails`, `fail_timeout`, `slow_start`, `backup`, `down`, `drain` |

### Мониторинг динамики

Для проверки текущего состава апстрима используйте встроенный статус API:

```bash
# Общий статус всех HTTP upstreams
curl -s http://127.0.0.1/status/http/upstreams/ | jq 'to_entries[] | {name: .key, servers: (.value.peers | keys)}'

# Детали по конкретному upstream
curl -s http://127.0.0.1/status/http/upstreams/pool1/ | jq '.peers[] | {server, state, weight, max_conns}'

# Stream upstreams
curl -s http://127.0.0.1/status/stream/upstreams/postgres_cluster/ | jq '.peers[] | {server, state, sessions}'
```

### Рекомендации по эксплуатации

1.  **Права доступа Docker:** Если используется `unix socket`, убедитесь что пользователь `angie` добавлен в группу `docker` (`sudo usermod -aG docker angie`). После изменения групп выполните `sudo systemctl restart angie`.
2.  **Таймауты DNS:** Всегда настраивайте `resolver_timeout` (рекомендуется `2s`–`5s`), чтобы избежать зависаний при проблемах с DNS.
3.  **Безопасность API:** Никогда не оставляйте `api write=on` или `/config/` открытым для публичного доступа. Используйте `allow/deny` и `auth_basic`.
4.  **State backup:** Регулярно копируйте state файлы из `/var/lib/angie/state/`. При каскадном откате на старую конфигурацию state может содержать серверы, которых уже нет в DNS/Docker.

## См. также

*   **[Балансировка нагрузки HTTP в Angie](./angie_http_load_balancing.md)** — алгоритмы, health checks, Docker discovery.
*   **[Балансировка и проксирование L4 (TCP/UDP)](./l4_balancing_and_proxying.md)** — динамические upstream в stream-контексте.
*   **[Мониторинг Angie — API](./angie_monitoring/angie_monitoring_api.md)** — эндпоинты `/status/http/upstreams/<upstream>/` и `/status/stream/upstreams/<upstream>/`.
