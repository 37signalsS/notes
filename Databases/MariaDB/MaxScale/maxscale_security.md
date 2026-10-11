# MariaDB MaxScale: Безопасность — Firewall, Masking, REST API

**Актуально для:** MaxScale 25.10.x

## Определения

*   **Firewall filter** (`module=firewall`) — фильт-allowlist: в режиме обучения собирает канонические формы запросов (литералы заменены на `?`), затем в режиме принуждения блокирует всё, что не входит в allowlist. Доступен с MaxScale 25.10; legacy-модуль `dbfwfilter` в актуальной документации не описан.
*   **Каноническая форма** — запрос с заменёнными литералами: `SELECT * FROM t WHERE f = 10` и `... f = 20` → `SELECT * FROM t WHERE f = ?`.
*   **Allowlist** — JSON-файл `<datadir>/firewall/<Filter>-allowed_statements.json` (обычно `/var/lib/maxscale/firewall/`); переносим между инстансами; синтаксическая ошибка в файле не даст MaxScale стартовать.
*   **Masking filter** (`module=masking`) — динамическое маскирование колонок в результатах SELECT без изменения данных на диске. Best-effort защита от случайного misuse, а не от злонамеренных атак.
*   **obfuscate** — правило необратимого одностороннего преобразования значения; при малом диапазоне исходных значений исходник восстановим перебором.
*   **applies_to / exempted** — таргетинг правил маскирования на пользователей (маскировать только для части пользователей или исключить админов).
*   **regexfilter** — перезапись запросов по PCRE2-выражению на лету; в замене `$1` вместо `\1`.
*   **readonly filter** (`module=readonly`) — implicit-фильтр без параметров и собственной секции; блокирует запись; ошибка 1792 (`ER_CANT_EXECUTE_IN_READ_ONLY_TRANSACTION`, SQLSTATE `25006`).
*   **Admin user / role** — учётные записи REST API/maxctrl; роль определяет набор permissions: `admin`, `edit`, `sql`, `view`.
*   **admin_audit** — аудит вызовов REST API в CSV.

## Теоретический блок

### Как работает firewall-фильтр

Четыре режима:

| Режим | Поведение |
| :--- | :--- |
| `idle` (default) | Ни обучение, ни принуждение |
| `learn-clear` | Очистить allowlist и учить заново |
| `learn-append` | Добавлять к существующему allowlist |
| `supervise` | Проверять, но только логировать нарушения |
| `enforce` | Блокировать не-allowlisted запросы |

Сохранение allowlist: при переходе из режима обучения в любой другой режим, **кроме `idle`**, allowlist сохраняется в файл. Переход `learn-*` → `idle` отбрасывает выученные операторы (существующий allowlist при этом не меняется). Копируйте allowlist **до** выхода из режима обучения, если нужно сохранить старый.

Действие при нарушении в `enforce`: `return-error` (default, ошибка клиенту) или `disconnect` (разрыв соединения).

`user_scope`: `collective` (default) — allowlist общий для всех пользователей; `individual` — каждый пользователь ограничен своими запросами (пользователь, не участвовавший в обучении, не может ничего).

`exclude_users` — пользователи, чьи запросы не подпадают под firewall (с хостом и без, с кавычками): `exclude_users=admin, 'super'@'192.168.0.1'`.

Пустой allowlist: `supervise`/`enforce` без файла allowlist эквивалентны пустому allowlist — ни один запрос не разрешён.

Пример защиты от SQL-инъекции: при выученном `SELECT * FROM users WHERE username = ? AND password = ?` запрос `SELECT * FROM users WHERE username = '' OR '1'='1' AND password = ''` не совпадёт ни с одной канонической формой и будет заблокирован.

Логирование: в `supervise` нарушение — warning в лог MaxScale (`2024-11-18 08:01:47   warning: (1) [firewall] (Service); Firewall incident (user@127.0.0.1): DELETE FROM t`). В `enforce` — событие `firewall_incident`: по умолчанию warning в лог (при `maxlog`) и событие syslog (при `syslog`), настраивается через `event_firewall_incident_facility=LOG_AUTH` и `event_firewall_incident_level=LOG_CRIT`.

### Как работает masking

Правило задаёт: что заменить (`replace`: `database`, `table`, `column`, опционально `match` — PCRE2 для частичной маскировки), чем заменить (`with`: `value` — фиксированная строка, или `fill` — символ-заполнитель, растягиваемый до длины значения), для кого (`applies_to` — список пользователей, `exempted` — исключения).

*   `value` заменяет значение verbatim и должен совпадать по длине с возвращаемым значением **точно**; при несовпадении длины используется `fill`. Если заданы оба — приоритет у `value`. `fill` по умолчанию — `X`.
*   `match` — заменяется только совпавшая часть значения (заполняется `fill`).
*   `obfuscate` — необратимое одностороннее преобразование значения.

Важно: если правило задаёт только `column` (без `table`/`database`), оно матчится по имени колонки во всех таблицах. Если в резалтсете нет информации о таблице (например, `UNION`), правило считается совпавшим — маскирование нельзя обойти через `UNION`.

Без `applies_to` правило применяется **ко всем пользователям** — включая приложение, которому нужны реальные данные.

**Ограничения по типам:** маскируются только строковые типы — `BINARY`, `VARBINARY`, `CHAR`, `VARCHAR`, `BLOB`, `TINYBLOB`, `MEDIUMBLOB`, `LONGBLOB`, `TEXT`, `TINYTEXT`, `MEDIUMTEXT`, `LONGTEXT`, `ENUM`, `SET`. Для остальных типов маскирование не выполняется (диагностика — `warn_type_mismatch=always`).

**Большие payload:** резалтсеты ≥16MB доставляются несколькими пакетами; параметр `large_payload` (`abort` default — соединение закрывается, `ignore` — колонки не маскируются). Ограничение применяется только к резалтсетам с маскируемыми колонками.

**Защита от обхода** (все параметры default `true`): `prevent_function_usage` (запросы с функциями над маскированными колонками отклоняются), `check_user_variables` (запрет `set @a = (select ssn ...)`), `check_unions` (отклоняются UNION, где 2-й и последующий SELECT ссылаются на маскируемые колонки), `check_subqueries` (подзапросы к маскируемым колонкам), `require_fully_parsed` (неразбираемые запросы блокируются), `treat_string_arg_as_field` (защита от обхода через `ANSI_QUOTES`: `set @@sql_mode = 'ANSI_QUOTES'; select concat("ssn") from managers;`).

**Привилегии:** если пользователь может `CREATE TABLE` + `INSERT`, он скопирует маскируемую колонку в новую таблицу в открытом виде. Маскирование требует минимизации привилегий БД-пользователей.

**Module command:** `maxctrl call command masking reload <Filter>` — перечитать правила; новые правила вступают в силу только при успешной загрузке. Относительный путь `rules` интерпретируется относительно каталога модулей (`/etc/maxscale.modules.d/`).

### regexfilter

Перезапись запросов: `match` (PCRE2, обязателен) → `replace` (обязателен). Применяется до роутера. Дополнительно: `options` (`ignorecase` default / `case` / `extended`), `source` (применять только к клиентам с адреса), `user` (только для имени пользователя клиента), `log_file` (все запросы — только для диагностики), `log_trace` (совпавшие/несовпавшие запросы с заменами на info-уровне — предпочтительный способ диагностики, уровень меняется в рантайме).

### Модель безопасности REST API

Default: пользователь `admin` с паролем `mariadb`, `admin_host=127.0.0.1`, `admin_port=8989`, `admin_auth=true`, `admin_enabled=true`, `admin_gui=true`. Basic-аутентификация без HTTPS небезопасна — пароли перехватываются в трафике.

**Пользователи:** `maxctrl create user <name> <password> --type=admin|basic` (default `basic`); REST API: `POST /v1/users` с `data.attributes.role` (приоритет над legacy-полем `account`). Смена пароля: `maxctrl alter user <name> <password>` / `PATCH /v1/users/:name`. Удаление: `maxctrl destroy user <name>` / `DELETE /v1/users/:name` — **последнего admin-пользователя удалить нельзя** (сначала создайте замену).

**Permissions** (набор прав роли):

| Permission | Что даёт |
| :--- | :--- |
| `admin` | Доступ к `/users` и `/roles` (создание учётных записей и ролей) |
| `edit` | Запись во все endpoints, кроме `/users` и `/roles` |
| `sql` | Read-only к `/maxscale`, `/servers`, `/services`, `/listeners` + полный доступ к `/sql` (Query Editor) |
| `view` | Read-only ко всем endpoints, кроме `/users` и `/roles` |

**Роли:** встроенные — `admin` (`admin,edit,view,sql`), `editor` (`edit,view,sql`), `basic` (`view,sql`), `sql` (`sql`). Кастомные роли: `POST /v1/roles` с произвольным набором permissions (неизвестные сохраняются как user-defined). Управление ролями — только через REST API (maxctrl-команд нет).

**Аутентификация:** Basic (`admin_auth=true`), JWT (`GET /v1/auth`), OpenID Connect, PAM (`admin_pam_readwrite_service` / `admin_pam_readonly_service` — простые PAM-сервисы, только пароль; используются, если обычная аутентификация не удалась), внешняя валидация токенов (`admin_verify_url`). Механика — в [REST API и maxctrl](./maxscale_rest_api.md).

**Блокировка хоста:** `max_auth_errors_until_block` (default `10`) — после ошибок аутентификации хост блокируется на 60 секунд; `0` отключает. Значение не жёсткий предел: допустимое число ошибок — между `N` и `threads * N`. Неудачи логируются: `admin_log_auth_failures=true` (default); событие `event.authentication_failure.facility=LOG_AUTH`, `event.authentication_failure.level=LOG_CRIT`.

**TLS admin-интерфейса:** `admin_ssl_key` + `admin_ssl_cert` (PEM; **только PKCS#8** — PKCS#1 приведёт к ошибке запуска; ключ с паролем — `admin_ssl_passphrase`), `admin_ssl_ca` (CA для исходящих запросов, например OIDC; сам по себе mTLS **не** включает), `admin_ssl_version` (enum_mask, default `MAX`; с 24.02.2 — точное перечисление: `TLSv1.2` разрешает только TLSv1.2; старое поведение — `TLSv1.2,TLSv1.3`), `admin_ssl_cipher` (default `NORMAL`, gnutls priority string, например `SECURE256:-ECDHE-RSA:-AES-256-CCM:+AES-128-GCM`), `admin_ssl_verify_peer_certificate` / `admin_ssl_verify_peer_host` (25.10+, mTLS: клиентский сертификат проверяется по `admin_ssl_ca`).

**admin_secure_gui** (default `true`): GUI и endpoint `/auth` доступны только по HTTPS. `admin_secure_gui=false` — только для изолированного стенда (учётные данные идут открытым текстом). `admin_gui=false`: root-ресурс отдаёт `200 OK` — low-overhead health check.

**Сетевая фильтрация** (24.02+): `admin_readwrite_hosts` (default `%`) — хосты, с которых разрешены любые операции; `admin_readonly_hosts` — только чтение; клиент может читать, если его адрес матчит любой из двух списков. Формат: comma-separated список адресов/hostname, CIDR; wildcards `%` и `_`; `localhost` зарезервирован и **не** матчит (используйте `127.0.0.1`); при hostname выполняется reverse DNS (может тормозить — лучше IP); `skip_name_resolve` несовместим с hostname-паттернами.

**Аудит:** `admin_audit=false` (default), `admin_audit_file=/var/log/maxscale/admin_audit.csv` (для нестандартного пути директория должна существовать), `admin_audit_exclude_methods` (значения: `GET,PUT,POST,PATCH,DELETE,HEAD,OPTIONS,CONNECT,TRACE`; default — без исключений; сброс пустым значением; runtime-изменение через `maxctrl alter maxscale admin_audit_exclude_methods=` перезаписывает запись из `maxscale.cnf`).

**require_secure_transport** (default `false`): если `true` — listeners, servers и REST API обязаны использовать SSL; любое изменение, отключающее SSL, отклоняется; Unix-сокеты считаются безопасными.

## Практические сценарии

### Prerequisites

*   Для firewall — representative workload для обучения.
*   Для masking — понимание, какие пользователи должны видеть данные (иначе маскируете и приложение), и минимальные привилегии БД-пользователей.
*   Для REST API — TLS-ключ в формате PKCS#8 PEM (PKCS#1-ключ нужно сконвертировать, иначе MaxScale не стартует).

### Шаг 1: Firewall — обучение и включение

```ini
# /etc/maxscale.cnf

[MyFirewall]
type=filter
module=firewall

[RW-Split-Service]
type=service
router=readwritesplit
...
filters=MyFirewall
```

Обучение и включение (через maxctrl):

```bash
# 1. Режим обучения (allowlist очищается)
maxctrl alter filter MyFirewall mode=learn-clear
# → прогнать representative workload через MaxScale

# 2. Режим наблюдения: нарушения только логируются
maxctrl alter filter MyFirewall mode=supervise
# → allowlist сохранён в <datadir>/firewall/MyFirewall-allowed_statements.json
# → проверить лог на предмет легитимных запросов, не попавших в allowlist
# 2024-11-18 08:01:47   warning: (1) [firewall] (Service); Firewall incident (user@127.0.0.1): DELETE FROM t

# 3. Принуждение
maxctrl alter filter MyFirewall mode=enforce
```

Конфигурация с ограничением по пользователям:

```ini
[MyFirewall]
type=filter
module=firewall
user_scope=individual
exclude_users=admin, 'super'@'192.168.0.1'
action=return-error

# Эскалация инцидентов firewall в syslog (опционально)
event_firewall_incident_facility=LOG_AUTH
event_firewall_incident_level=LOG_CRIT
```

### Шаг 2: Masking с таргетингом на пользователей

```json
// /etc/maxscale.d/masking_rules.json
{
  "rules": [
    {
      "replace": { "column": "email" },
      "with": { "value": "****@example.com" },
      "applies_to": ["'report_user'@'%'"],
      "exempted": ["'admin'@'%'"]
    },
    {
      "replace": { "column": "phone", "match": "\\d{4}" },
      "with": { "fill": "X" },
      "applies_to": ["'report_user'@'%'"]
    },
    {
      "replace": { "database": "billing", "table": "cards", "column": "pan" },
      "with": { "fill": "X" }
    }
  ]
}
```

Правило 3 без `applies_to` маскирует колонку **для всех пользователей** — включая приложение. `value` должен совпадать по длине с возвращаемым значением, иначе применяется `fill`; `match` маскирует только совпавшую часть (первые четыре подряд идущие цифры в телефоне).

```ini
[Masking-Filter]
type=filter
module=masking
rules=/etc/maxscale.d/masking_rules.json
warn_type_mismatch=always
large_payload=abort

[RW-Split-Service]
type=service
...
filters=Masking-Filter
```

Перечитать правила после правки файла (применяются только при успешной загрузке):

```bash
maxctrl call command masking reload Masking-Filter
```

Проверка:

```sql
-- Как report_user
SELECT email, phone FROM customers LIMIT 1;
-- → ****@example.com, 555-XXXX-5678
```

### Шаг 3: regexfilter — перезапись запросов

```ini
[RewriteFilter]
type=filter
module=regexfilter
match=^(SELECT.*)\s+FROM\s+big_table(.*)$
replace=$1 FROM big_table_partitioned$2
options=ignorecase
# Только для клиента с адреса 10.0.0.5 и пользователя report_user:
# source=10.0.0.5
# user=report_user
# Диагностика: совпавшие/несовпавшие запросы с заменами (info-уровень)
# log_trace=true

[RW-Split-Service]
type=service
...
filters=RewriteFilter
```

### Шаг 4: readonly filter для readconnroute

`readconnroute` сам **не запрещает запись** даже при `router_options=slave`. Для read-only порта добавьте фильтр — он implicit, собственной секции и параметров не имеет:

```ini
[Read-Service]
type=service
router=readconnroute
servers=replica1,replica2
router_options=slave
filters=readonly
```

Попытка записи вернёт ошибку 1792 (`ER_CANT_EXECUTE_IN_READ_ONLY_TRANSACTION`, SQLSTATE `25006`). Фильтр блокирует `SET TRANSACTION READ WRITE` и `START TRANSACTION READ WRITE`, но **не** детектирует `SET tx_read_only=0` и `PREPARE`/`EXECUTE` из пользовательских переменных — защита от случайной записи, а не от злонамеренного пользователя.

### Шаг 5: Безопасность REST API

Учётные записи:

```bash
# Создать admin-пользователя (--type: admin|basic, default basic — только чтение)
maxctrl create user my_admin СЛОЖНЫЙ_ПАРОЛЬ --type=admin

# Сменить пароль
maxctrl alter user my_admin НОВЫЙ_ПАРОЛЬ

# Удалить дефолтного (последнего admin-пользователя удалить нельзя —
# сначала создайте замену)
maxctrl destroy user admin

# Проверить учётные записи
maxctrl show users
```

Кастомная роль для автоматизации (REST API; maxctrl-команд для ролей нет):

```bash
# Роль ops: чтение + изменение объектов, без доступа к /users и /roles
curl -sS -u my_admin:СЛОЖНЫЙ_ПАРОЛЬ -X POST http://127.0.0.1:8989/v1/roles \
  -H 'Content-Type: application/json' \
  -d '{"data": {"id": "ops", "attributes": {"permissions": ["view", "edit"]}}}'
# → 204 No Content
```

Конфигурация:

```ini
# /etc/maxscale.cnf
[maxscale]
# Слушать на всех интерфейсах (только если действительно нужно!)
admin_host=0.0.0.0
admin_port=8989

# TLS для admin-интерфейса: ключ ОБЯЗАТЕЛЬНО в формате PKCS#8 PEM
admin_ssl_key=/certs/maxscale-admin-key.pem
admin_ssl_cert=/certs/maxscale-admin-cert.pem
# Пароль ключа, если он защищён
# admin_ssl_passphrase=...
# CA для исходящих запросов (например, OIDC); сам по себе mTLS не включает
# admin_ssl_ca=/certs/ca-cert.pem
# Только TLSv1.2+ (с 24.02.2 значение — точное перечисление версий)
admin_ssl_version=TLSv1.2,TLSv1.3
# mTLS (25.10+): клиентский сертификат проверяется по admin_ssl_ca
# admin_ssl_verify_peer_certificate=true
# admin_ssl_verify_peer_host=true

# Ограничение сети (24.02+): с каких хостов какие операции разрешены
admin_readwrite_hosts=10.0.0.0/8,127.0.0.1
admin_readonly_hosts=10.1.0.0/16

# Аудит вызовов REST API
admin_audit=true
admin_audit_file=/var/log/maxscale/admin_audit.csv
# Не логировать шумные методы (default — логируются все)
# admin_audit_exclude_methods=GET,HEAD,OPTIONS

# Блокировка хоста после ошибок аутентификации (default 10, блок на 60s; 0 — отключено)
max_auth_errors_until_block=5

# Требовать SSL для listeners, servers и REST API
require_secure_transport=true
```

Проверка:

```bash
# Подключение с TLS
maxctrl --secure --tls-ca-cert=/certs/ca-cert.pem show maxscale

# Health check: при admin_gui=false root-ресурс отдаёт 200 OK
curl -sS --cacert /certs/ca-cert.pem -u my_admin:СЛОЖНЫЙ_ПАРОЛЬ https://127.0.0.1:8989/
# → 200

# Аудит пишется в CSV
tail -f /var/log/maxscale/admin_audit.csv
```

## Устранение неполадок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| MaxScale не стартует после правки allowlist | Синтаксическая ошибка в JSON | Проверьте файл `<datadir>/firewall/<Filter>-allowed_statements.json` |
| Выученные операторы потеряны после смены режима | Переход `learn-*` → `idle` отбрасывает выученное | Копируйте allowlist до выхода из обучения; используйте `learn-append` |
| Все запросы заблокированы в `supervise`/`enforce` | Нет файла allowlist | Это эквивалент пустого allowlist: сначала пройдите обучение |
| Легитимные запросы блокируются в `enforce` | Не прошли через обучение | Переключите в `learn-append`, прогоните недостающий workload, вернитесь в `supervise` → `enforce` |
| Маскируются данные приложения | Нет `applies_to` — правило для всех | Добавьте `applies_to` с пользователем отчётов |
| Маскирование обходится через UNION | Нет информации о таблице в резалтсете | Это защита: правило с `table`/`database` матчится всегда; не сужайте правило без необходимости |
| Функции над маскированной колонкой возвращают данные | `prevent_function_usage=false` | Оставьте `prevent_function_usage=true` (или firewall на функции) |
| Маскирование не применяется к колонке | Тип колонки не из списка строковых | Только BINARY/VARBINARY/CHAR/VARCHAR/BLOB/TEXT/ENUM/SET и др.; `warn_type_mismatch=always` для диагностики |
| Большие резалтсеты не маскируются / соединение закрывается | Payload ≥16MB | `large_payload=abort` (default) или `ignore` |
| `dbfwfilter` не найден | Legacy-модуль не описан в актуальной документации | Используйте `module=firewall` (25.10+) |
| REST API доступен с дефолтными кредами | Не сменены `admin:mariadb` | Создайте пользователя и удалите `admin` (Шаг 5) |
| REST API не стартует с TLS | Ключ в формате PKCS#1 | Сконвертируйте ключ в PKCS#8 PEM |
| Аудит не пишется в нестандартный файл | Директория не существует | Создайте директорию для `admin_audit_file` |
| `admin_readwrite_hosts` с hostname не работает | `skip_name_resolve` или `localhost` в списке | Только IP (или `127.0.0.1` вместо `localhost`); несовместим с `skip_name_resolve` |
| Настройки `admin_audit_exclude_methods` из конфига игнорируются | Было runtime-изменение | Runtime-изменение перезаписывает запись из `maxscale.cnf` |
| Доступ по токенам внезапно отключился | Рестарт MaxScale или недоступен `admin_verify_url` | Токены инвалидируются рестартом; уберите `admin_verify_url` (требует рестарта) |

## Best Practices

1.  **Firewall: всегда через `supervise` перед `enforce`** — сначала смотрите лог нарушений, потом блокируйте.
2.  **Allowlist переносите между инстансами** — копируйте `<datadir>/firewall/*.json` в HA-схеме, чтобы не учить заново; копируйте **до** выхода из режима обучения.
3.  **Masking без `applies_to` — дефект конфигурации**: маскирование должно касаться только пользователей, которым данные не нужны.
4.  **`fill` вместо `value`** в маскировании, когда важна постоянная длина маски (PCI DSS style).
5.  **Минимальные привилегии БД-пользователей** — маскирование обходится через `CREATE TABLE` + `INSERT`; readonly filter не защита от злонамеренного (`SET tx_read_only=0` не детектируется).
6.  **`readonly` filter обязателен** для read-only портов на `readconnroute`.
7.  **Firewall и masking вместе**: firewall блокирует запросы с функциями над чувствительными колонками, masking прячет значения — защита в глубину.
8.  **REST API — только localhost** по умолчанию; при expos'е — TLS (PKCS#8) + не-дефолтные креды + `admin_audit` + `admin_readwrite_hosts`/`admin_readonly_hosts`.
9.  **Кастомные роли с минимальными permissions** для автоматизации (`view`/`edit` вместо `admin`) — доступ к `/users` и `/roles` только с `admin`.
10.  **`max_auth_errors_until_block` + `admin_log_auth_failures`** — обнаружение подбора учётных данных; эскалируйте `event.authentication_failure` в syslog.
11.  **`require_secure_transport=true`** в production — SSL обязателен для listeners, servers и REST API.
12.  **`admin_gui=false`** на хостах без GUI — root-ресурс становится low-overhead health check.

## Дополнительная информация

### См. также

*   **[Обзор MaxScale](./maxscale_overview.md)** — TLS listener'ов и серверов (шифрование трафика к бэкендам).
*   **[REST API и maxctrl](./maxscale_rest_api.md)** — механика API, JWT/OIDC/PAM, эндпоинты.
*   **[Мониторинг](./maxscale_monitoring.md)** — pull-метрики, MaxGUI, `admin_audit`.
*   **[Роутеры](./maxscale_routers.md)** — где нужен readonly filter.
*   **[Failover](./maxscale_failover.md)** — module commands мониторов.
*   **[Безопасность MariaDB](../security/hardening.md)** — харденинг сервера БД.
*   Официальная документация: [Firewall Filter](https://mariadb.com/docs/maxscale/reference/maxscale-filters/maxscale-firewall-filter.md), [Masking Filter](https://mariadb.com/docs/maxscale/reference/maxscale-filters/maxscale-masking-filter.md), [Readonly Filter](https://mariadb.com/docs/maxscale/reference/maxscale-filters/maxscale-readonly.md), [Regex Filter](https://mariadb.com/docs/maxscale/reference/maxscale-filters/maxscale-regex-filter.md), [Admin User Resource](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-admin-user-resource.md), [Role Resource](https://mariadb.com/docs/maxscale/reference/maxscale-rest-api/maxscale-role-resource.md).
