# MariaDB MaxScale: REST API и автоматизация maxctrl

**Актуально для:** MaxScale 25.10.x

## Определения

*   **REST API** — HTTP-интерфейс управления MaxScale (JSON). Живёт на admin-порте (default `127.0.0.1:8989`). Все ресурсы соответствуют спецификации [JSON API](http://jsonapi.org/format/).
*   **maxctrl** — CLI-клиент, являющийся обёрткой над REST API (заменил устаревший `maxadmin`, который больше не поддерживается и не включается в поставку).
*   **JSON API** — формат ответов: объект с `links` и `data`; создание/изменение объектов — через `data.attributes` и `data.relationships`.
*   **JWT** — токен аутентификации (`GET /v1/auth`), по умолчанию живёт 8 часов; инвалидируется при рестарте MaxScale.
*   **ETag** — идентификатор версии ресурса; меняется только при изменении через API (не при внутренних событиях вроде смены состояния сервера). Используется с `If-Match` для оптимистичной блокировки.
*   **Module command** — команда модуля (монитора/роутера), вызываемая через `maxctrl call command` или REST API.
*   **Runtime objects** — объекты (серверы, сервисы, фильтры, listener'ы), созданные в рантайме через API; персистятся в `persistdir` (`/var/lib/maxscale/maxscale.cnf.d/`).
*   **Mxs-Warning** — ответный заголовок с предупреждением: изменён статический объект или создана переопределяющая его runtime-конфигурация.

## Базовые концепции

### Архитектура и модель API

*   API версии 1 в namespace `/v1/`; с MaxScale 2.4.0 префикс `/v1/` необязателен — без него используется последняя версия.
*   `GET /` и `GET /v1/` отвечают `200 OK` — пригодны для HTTP health check («MaxScale жив»).
*   Ресурсы: `maxscale`, `objects`, `services`, `servers`, `listeners`, `filters`, `monitors`, `sessions`, `users`, `roles`, `sql`.
*   **Связи (relationships):** `services` — servers, services, filters (порядок в массиве определяет порядок обработки запросов!), listeners; `monitors` — servers; `filters` — services (односторонняя, меняется только со стороны сервиса); `servers` — services, monitors; `listeners` — service.
*   Создание связи — в теле `POST`/`PATCH`; модификация — `PATCH .../relationships/:type`; удаление всех связей — `"data": []`.
*   `admin_root_url` (25.10) — префикс ко всем ссылкам в ответах; нужен, когда MaxScale стоит за reverse proxy на под-пути.

### Аутентификация

*   **HTTP Basic** (default, `admin_auth=true`) с пользователями admin-интерфейса; default креды `admin` / `mariadb` — **сменить перед expos'ом** (см. [Безопасность](./maxscale_security.md)).
*   **Типы пользователей:** `basic` (только `list`/`show`, read-only) и `admin` (полный доступ).
*   **JWT:** `GET /v1/auth` → `{"meta": {"token": "..."}}`; default lifetime 8 часов (`max-age=28800`, допустимы 1..2147483646); потолок — `admin_jwt_max_age` (default `24h`); `persist=yes` — токен в cookie `maxscale_token` (`HttpOnly`, `SameSite=Strict` — защита от CSRF), ответ `204`; `logout=yes` — очистка cookie; **рестарт MaxScale инвалидирует все токены**; `/auth` по умолчанию требует HTTPS (разрешить HTTP можно только `admin_secure_gui=false` — стенд); `/whoami` — JSON payload токена (`account`, `permissions`: `admin`/`edit`/`sql`/`view`).
*   **Подпись JWT:** `admin_jwt_algorithm` (симметричные HS256/HS384/HS512 — ключ генерируется или берётся из `admin_jwt_key`/Encryption Key Manager; асимметричные — требуют `admin_ssl_cert` + `admin_ssl_key`); `admin_jwt_issuer` (default `maxscale`).
*   **OpenID Connect** (Code Flow и Implicit Flow): `admin_oidc_url`, `admin_oidc_client_id` (default = `admin_jwt_issuer`), `admin_oidc_client_secret`; endpoints `/login`, `/logout`, `/.well-defined/openid-configuration`, `/authorize`, `/jwks`; права берутся из claims ID-токена (`permissions`) или из роли по полю `account`.
*   **`admin_verify_url`** — внешняя валидация токенов (GET с bearer-токеном). Если сервер недоступен — доступ по токенам отключается полностью (Basic при этом работает); удаление параметра требует рестарта.
*   **PAM:** `admin_pam_readonly_service`, `admin_pam_readwrite_service`.
*   **Ограничение по источнику** (24.02+): `admin_readwrite_hosts` (default `%` — все) и `admin_readonly_hosts` — хосты, с которых разрешены соответственно любые и только read-операции; wildcards `%`/`_`; `localhost` — зарезервированное имя и не матчит loopback (используйте `127.0.0.1`); `skip_name_resolve` несовместим с hostname-паттернами.

### Параметры запросов и заголовки

*   `pretty` (default `true`) — человекочитаемый вывод.
*   `fields[TYPE]=json,ptr` — sparse fieldset (только `attributes`/`relationships`; массивы не обходятся): `?fields[servers]=state`.
*   `filter=json_ptr=expr` — фильтр коллекции (24.02+): выражения `eq`/`ne`/`lt`/`le`/`ge`/`gt`/`and`/`or`/`not`; пример: `?filter=/relationships/services/data/0/id="RW-Split-Router"`.
*   `filter[json_path]=expr` — фильтр по JSONPath (dot/bracket-нотация, wildcards); несколько фильтров комбинируются через AND.
*   `page[size]`, `page[number]` — псевдо-пагинация (консистентность между запросами не гарантируется).
*   `sync=false` — отключить синхронизацию конфигурации на время запроса; только временные правки (локальные изменения будут перезаписаны при следующей синхронизации).
*   Заголовки запроса: `Authorization` (Basic), `Content-Type: application/json` (PUT/POST — полный ресурс; PATCH — частичное описание), `If-Match` (ETag, для PATCH), `If-Modified-Since`, `If-None-Match`, `If-Unmodified-Since`, `X-HTTP-Method-Override` (POST/PATCH/DELETE через PUT для клиентов без методов).
*   Заголовки ответа: `Allow` (допустимые методы, напр. `GET, PATCH, PUT`), `Accept-Patch: application/json-patch`, `ETag`, `Last-Modified`, `Location`, `WWW-Authenticate`, `Mxs-Warning`.

### Коды ответов

*   2xx: `200 OK` (тело есть), `201 Created`, `202 Accepted`, `204 No Content` (успех без тела — типичный ответ на POST/PATCH/PUT/DELETE).
*   4xx: `400` (неверный запрос/тело), `401` (нужна аутентификация), `403` (нет прав), `404`, `405` (метод не поддерживается — см. `Allow`), `409` (конфликт правок), `412` (не выполнено условие If-Match/If-None-Match), `415`, `422` (тело семантически неверно), `423` (ресурс заблокирован), `428` (требуется условный запрос).
*   Тело ошибки: `{"error": {"detail": "краткое описание"}}` (поле `description` — развёрнутая версия).

## Практические сценарии

### Prerequisites

*   Admin-порт доступен (default `127.0.0.1:8989`; см. `admin_host`/`admin_port`).
*   Пользователь с правами `admin` для изменяющих операций; `basic` — только чтение.
*   Для runtime-изменений параметр должен быть Dynamic; иначе — destroy/recreate объекта или перезапуск MaxScale.

### Шаг 1: curl — чтение состояния

```bash
# Health check (200 OK = MaxScale жив)
curl -i http://127.0.0.1:8989/v1/

# Все серверы (компактный вывод)
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ "http://127.0.0.1:8989/v1/servers?pretty=false"

# Только состояния серверов (sparse fieldset)
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ "http://127.0.0.1:8989/v1/servers?fields[servers]=state"

# Только сессии конкретного сервиса (filter по JSON Pointer)
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ 'http://127.0.0.1:8989/v1/sessions?filter=/relationships/services/data/0/id="RW-Split-Service"'

# Детали сервиса: attributes.router_diagnostics содержит
# route_master, route_slave, rw_transactions, ro_transactions, replayed_transactions
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ http://127.0.0.1:8989/v1/services/RW-Split-Service
```

### Шаг 2: curl — создание объектов в рантайме

Формат тела — JSON API (`data.attributes`, `data.relationships`); успешный ответ — `204 No Content`.

```bash
# Создать сервер без перезапуска MaxScale
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X POST http://127.0.0.1:8989/v1/servers \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "id": "server4",
      "type": "servers",
      "attributes": {
        "parameters": { "address": "192.168.1.14", "port": 3306 }
      }
    }
  }'

# Создать сервер и сразу подключить к сервису и монитору
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X POST http://127.0.0.1:8989/v1/servers \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "id": "server5",
      "type": "servers",
      "attributes": { "parameters": { "address": "192.168.1.15", "port": 3306 } },
      "relationships": {
        "services": { "data": [ { "id": "RW-Split-Service", "type": "services" } ] },
        "monitors": { "data": [ { "id": "MariaDB-Monitor", "type": "monitors" } ] }
      }
    }
  }'

# Создать сервис (обязательны: router, user, password)
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X POST http://127.0.0.1:8989/v1/services \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "id": "RO-Service",
      "type": "services",
      "attributes": {
        "router": "readconnroute",
        "parameters": { "user": "maxuser", "password": "maxpwd", "router_options": "slave" }
      },
      "relationships": {
        "servers": { "data": [ { "id": "server2", "type": "servers" } ] }
      }
    }
  }'
```

### Шаг 3: curl — изменение, состояния серверов, остановка сервисов

```bash
# Изменить параметр сервера (PATCH — частичное изменение; 204)
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PATCH http://127.0.0.1:8989/v1/servers/server4 \
  -H "Content-Type: application/json" \
  -d '{"data": {"attributes": {"parameters": {"address": "192.168.1.24"}}}}'

# Переопределить список серверов сервиса (filters — порядок = порядок обработки!)
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PATCH \
  http://127.0.0.1:8989/v1/services/RW-Split-Service/relationships/servers \
  -H "Content-Type: application/json" \
  -d '{"data": [ {"id": "server1", "type": "servers"}, {"id": "server4", "type": "servers"} ]}'

# Состояние сервера: maintenance с принудительным закрытием соединений
# Допустимые state: master, slave, maintenance, running, synced, drain
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PUT \
  "http://127.0.0.1:8989/v1/servers/db-node-1/set?state=maintenance&force=yes"

# Снять состояние
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PUT \
  "http://127.0.0.1:8989/v1/servers/db-node-1/clear?state=maintenance"

# Остановить сервис (force=yes — закрыть все соединения) и запустить снова
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PUT \
  "http://127.0.0.1:8989/v1/services/RW-Split-Service/stop?force=yes"
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PUT \
  http://127.0.0.1:8989/v1/services/RW-Split-Service/start

# Перечитать список БД-пользователей сервиса
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X POST \
  http://127.0.0.1:8989/v1/services/RW-Split-Service/reload

# Удалить сервер (force=yes — сначала отвязать от сервисов и мониторов)
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X DELETE \
  "http://127.0.0.1:8989/v1/servers/server4?force=yes"
```

### Шаг 4: Module commands через REST API

Формат пути: `/v1/maxscale/modules/<module>/<operation>?<args>` (аргументы через `&`). Полный список команд — `maxctrl list commands` или `maxctrl show commands <module>`; детали и параметры команд mariadbmon (switchover/failover/rejoin, async-режим, `fetch-cmd-result`) — в **[Failover и Switchover](./maxscale_failover.md)**.

```bash
# Switchover: server2 — новый Primary, server1 — старый (параметры: monitor,
# new_primary, old_primary, async, force, old_primary_maint)
curl -sS -u admin:СЛОЖНЫЙ_ПАРОЛЬ -X PUT \
  "http://127.0.0.1:8989/v1/maxscale/modules/mariadbmon/switchover?MariaDB-Monitor&server2&server1"
```

### Шаг 5: maxctrl — глобальные опции и типовые операции

Глобальные опции:

| Опция | Смысл |
| :--- | :--- |
| `-c, --config` | Файл конфигурации maxctrl (default `~/.maxctrl.cnf`) |
| `-u, --user` | Пользователь (default `admin`) |
| `-p, --password` | Пароль (default `mariadb`; `-p ''` — ввести интерактивно) |
| `-h, --hosts` | Список хостов `HOST:PORT` через запятую (default `127.0.0.1:8989`) |
| `-t, --timeout` | Таймаут запроса (default `10000` ms; `-t 10s`) |
| `-q, --quiet` | Без вывода |
| `--tsv` | TSV-вывод (удобно для парсинга в скриптах) |
| `--skip-sync` | Отключить синхронизацию конфигурации для этой команды |
| `-s, --secure` | HTTPS к admin-интерфейсу |
| `--tls-key/--tls-cert/--tls-ca-cert/--tls-passphrase` | TLS-клиентские материалы |
| `-n, --tls-verify-server-cert` | Проверять сертификат сервера (default `true`) |

Конфигурация по умолчанию (`~/.maxctrl.cnf`): MaxCtrl берёт значения из секции `[maxctrl]` как defaults, но **откажется использовать файл, если права не убраны у всех кроме владельца** (т.е. `chmod 600`):

```ini
[maxctrl]
u = my_admin
p = СЛОЖНЫЙ_ПАРОЛЬ
```

Типовые операции:

```bash
# Состояния серверов (НЕ alter server — он меняет параметры)
maxctrl set server db-node-1 drain              # исключить из балансировки
maxctrl set server db-node-1 maintenance --force # принудительный maintenance (закрывает соединения)
maxctrl clear server db-node-1 maintenance      # снять состояние

# Изменение параметров (применяется к новым сессиям)
maxctrl alter service RW-Split-Service causal_reads=local
maxctrl alter filter MyFirewall mode=supervise
maxctrl alter monitor MariaDB-Monitor monitor_interval=3000

# Фильтры сервиса (команда во множественном числе)
maxctrl create filter OptimisticTrx optimistictrx
maxctrl alter service-filters RW-Split-Service OptimisticTrx

# Пользователи REST API (default --type=basic: только list/show)
maxctrl create user my_admin СЛОЖНЫЙ_ПАРОЛЬ --type=admin
maxctrl alter user my_admin НОВЫЙ_ПАРОЛЬ        # смена типа — destroy + create
maxctrl destroy user old_user                   # последнего admin удалить нельзя

# Связи и жизненный цикл объектов
maxctrl link service RO-Service server2
maxctrl unlink service RO-Service server2
maxctrl link monitor MariaDB-Monitor server4
maxctrl stop monitor MariaDB-Monitor            # пауза мониторинга (ручной контроль состояний)
maxctrl start monitor MariaDB-Monitor
maxctrl destroy session <id> --ttl=30           # закрыть сессию с graceful-TTL
maxctrl destroy server server4 --force          # отвязать от сервисов/мониторов и удалить

# Логи и TLS
maxctrl enable log-priority notice              # disable log-priority <log> — выключить
maxctrl rotate logs                             # для logrotate (см. maxscale_overview.md)
maxctrl reload tls                              # TLS-сертификаты + ротация JWT-ключей подписи
maxctrl reload session <id>                     # внутренний рестарт сессии (внешний ID сохраняется)
maxctrl reload sessions

# Отчёт для диагностики: состояние всех объектов
maxctrl create report /tmp/maxscale-report.txt

# Сырые REST-вызовы из maxctrl (JS-синтаксис извлечения значений)
maxctrl api get servers data[].attributes.state
maxctrl api patch servers/server1 \
  '{"data":{"attributes":{"parameters":{"address":"192.168.0.123"}}}}'

# Несколько инстансов MaxScale
maxctrl --hosts=mx1:8989,mx2:8989 list servers

# DEPRECATED с 25.01: active/passive HA-режим
# maxctrl alter maxscale passive=true
```

### Шаг 6: Автоматизация (Ansible-паттерн)

```yaml
# Пример: плановый switchover через Ansible
- name: Planned switchover via MaxScale
  ansible.builtin.command: >
    maxctrl --hosts=mx1:8989 -u {{ maxscale_user }} -p {{ maxscale_password }}
    call command MariaDB-Monitor switchover
    monitor={{ monitor }} new_primary={{ new_primary }} old_primary_maint=1
  register: switchover_result
  failed_when: switchover_result.rc != 0

- name: Verify new primary
  ansible.builtin.command: maxctrl list servers
  register: servers
  changed_when: false

- name: Fail if new primary is not Master
  ansible.builtin.assert:
    that:
      - servers.stdout is regex('{{ new_primary }}.*Master')
```

Асинхронный вариант (`async-switchover` + `fetch-cmd-result`) — в **[Failover и Switchover](./maxscale_failover.md)**.

### Шаг 7: Health-check для Keepalived

```bash
#!/bin/bash
# /etc/keepalived/check_maxscale.sh
# VRRP-скрипт: MaxScale жив и видит Primary
maxctrl list servers 2>/dev/null | grep -q Master
exit $?
```

```bash
# Более лёгкая альтернатива — корень API отвечает 200 OK
curl -fsS -o /dev/null --max-time 2 \
  -u admin:СЛОЖНЫЙ_ПАРОЛЬ http://127.0.0.1:8989/v1/
```

```keepalived
vrrp_script check_maxscale {
  script "/etc/keepalived/check_maxscale.sh"
  interval 2
  weight 2
}
```

Теория VRRP и Keepalived — в **[Механизмах Failover и Heartbeat](../../../Concepts/High_Availability/ha_failover_mechanisms.md)**.

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Connection refused` на 8989 | Admin-интерфейс отключён или слушает localhost | `admin_enabled=true`, `admin_host`, `admin_port` |
| `401 Unauthorized` | Дефолтные креды удалены, maxctrl использует default | Передайте `-u`/`-p` или настройте `~/.maxctrl.cnf` |
| `403 Forbidden` | Пользователь типа `basic` | Создайте пользователя с `--type=admin` |
| `405 Method Not Allowed` | Метод не поддерживается ресурсом | Посмотрите заголовок `Allow` в ответе |
| `409 Conflict` / `412 Precondition Failed` | Конфликт параллельных правок / ETag не совпал | Повторите `GET`, используйте `If-Match` с актуальным ETag |
| `422 Unprocessable Entity` | Тело семантически неверно (неизвестный параметр, неверный тип) | Проверьте имена и типы параметров в теле запроса |
| Изменение не применяется | Параметр не Dynamic | destroy/recreate объекта или перезапуск MaxScale |
| Runtime-объект потерян после перезапуска | Объект не персистился | Проверьте `persistdir` (`/var/lib/maxscale/maxscale.cnf.d/`); бэкапьте его |
| `maxctrl` молча использует localhost | Не задан `--hosts` | Укажите `-h mx1:8989` или `--hosts` |
| `maxctrl` не работает из systemd-юнита | `MemoryDenyWriteExecute=true` | Снимите ограничение или используйте curl |
| `/auth` возвращает ошибку | Endpoint требует HTTPS | Настройте `admin_ssl_key`/`admin_ssl_cert` (PKCS#8 PEM) или `admin_secure_gui=false` (только стенд) |
| Доступ по токенам внезапно отключился | `admin_verify_url` недоступен | Уберите `admin_verify_url` (требует рестарта); Basic при этом работает |
| Изменения не синхронизируются между инстансами | `config_sync_cluster` недоступен | `--skip-sync` / `sync=false` — только временная правка |
| В ответах предупреждения об изменении конфигурации | Изменён статический объект | Проверьте заголовок `Mxs-Warning` |

## Best Practices

1.  **maxctrl — обёртка над REST API**: всё, что делает maxctrl, можно сделать curl'ём — удобно для скриптов на Python/Go; сырые вызовы — `maxctrl api get/post/patch`.
2.  **`~/.maxctrl.cnf`** — права `600` (иначе MaxCtrl откажется читать файл); не храните пароль в shell-history.
3.  **`--hosts`** для HA-пары: один вызов — несколько инстансов; `--tsv` для парсинга; `-t` для таймаутов в CI-пайплайнах.
4.  **Runtime-объекты персистятся** в `persistdir` — бэкапьте `/var/lib/maxscale/maxscale.cnf.d/` вместе со статической конфигурацией; runtime-изменения отражайте и в конфиге/СУК, иначе после перезапуска конфигурации расходятся.
5.  **PATCH + `If-Match`/ETag** для конкурентных правок из автоматизации.
6.  **Порядок `filters` в relationships — порядок обработки запросов**; меняйте его через `PATCH .../relationships/filters`.
7.  **Health-check через `maxctrl list servers | grep Master`** или `GET /v1/` — для VRRP-скриптов.
8.  **JWT**: не используйте `admin_secure_gui=false` в продакшене; помните, что рестарт MaxScale инвалидирует все выданные токены.
9.  **Ограничивайте источники**: `admin_readonly_hosts` для read-only мониторинга, `admin_readwrite_hosts` — для автоматизации.
10. **`admin_audit` обязателен при expos'е REST API в сеть** — см. [Безопасность](./maxscale_security.md).

## Дополнительная информация

### См. также

*   **[Обзор MaxScale](./maxscale_overview.md)** — архитектура, конфигурация, maxctrl basics.
*   **[Безопасность](./maxscale_security.md)** — креды, TLS, аудит REST API.
*   **[Failover и Switchover](./maxscale_failover.md)** — module commands mariadbmon (SSoT).
*   **[Мониторинг](./maxscale_monitoring.md)** — pull-метрики через API, MaxGUI, `admin_audit`.

### Официальная документация

*   [MaxScale REST API](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-rest-api.md) — аутентификация, параметры запросов, заголовки, коды ответов.
*   Ресурсы: [servers](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-server-resource.md), [services](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-service-resource.md), [listeners](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-listener-resource.md), [filters](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-filter-resource.md), [monitors](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-monitor-resource.md), [sessions](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-session-resource.md), [users](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-admin-user-resource.md), [roles](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-role-resource.md), [sql](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-sql-resource.md).
*   [MaxCtrl reference](https://mariadb.com/docs/maxscale/reference/maxscale-maxctrl.md) — полный синтаксис всех команд.
