# ClickHouse — Безопасность и управление доступом

**Актуально для:** ClickHouse 26.9.x (Stable) / 26.8.x (LTS)

## Определения

**RBAC (SQL-driven Access Control)** — модель управления доступом, где права назначаются ролям, а роли — пользователям. Управляется через SQL (`CREATE USER/ROLE/GRANT`) и хранится в `local_directory` (`/var/lib/clickhouse/access/`).

**user_directories** — секция `config.xml`, определяющая источники учётных записей: `users_xml` (файл `users.xml`), `local_directory` (SQL-созданные пользователи), `replicated` (репликация пользователей через Keeper/ZooKeeper), `ldap` (внешний LDAP-каталог), `memory` (только в памяти). Порядок секций задаёт приоритет.

**Quota** — лимит ресурсов пользователя/роли за временной интервал (число запросов, прочитанные строки/байты, время выполнения). Отличается от ограничений на сложность одного запроса: квота ограничивает набор запросов за период.

**allow_networks** — список IP/хостов, с которых пользователю разрешено подключение (фильтрация на уровне сервера).

**Row policy (RLS)** — политика уровня строк, ограничивающая выборку/изменение строк по условию (`USING expr`).

**sha256_password** — хеширование пароля через SHA-256 (предпочтительный способ хранения паролей в конфигурации).

**auth_methods** — элемент, позволяющий пользователю аутентифицироваться любым из нескольких способов (например, пароль **или** LDAP).

## Основные концепции

### Модель безопасности

```
Пользователь (User)
   ├── Роли (Roles) ──→ Привилегии (GRANT)
   ├── Профиль настроек (Settings Profile) ──→ max_memory_usage, readonly, ...
   ├── Row Policies ──→ фильтр строк
   ├── Quota ──→ лимиты за интервал
   └── allow_networks ──→ фильтр IP
```

### user_directories и приоритет

```xml
<user_directories>
    <users_xml>
        <path>/etc/clickhouse-server/users.xml</path>
    </users_xml>
    <local_directory>
        <path>/var/lib/clickhouse/access/</path>
    </local_directory>
    <replicated>
        <zookeeper_path>/clickhouse/access/</zookeeper_path>
    </replicated>
    <ldap>
        <server>my_ldap_server</server>
        <roles>
            <analyst_role />
        </roles>
    </ldap>
</user_directories>
```

Порядок секций определяет приоритет: чем выше, тем приоритетнее. `replicated` позволяет реплицировать SQL-созданных пользователей через Keeper/ZooKeeper на все узлы кластера.

### Хеширование паролей

```xml
<!-- users.d/secure_passwords.xml -->
<clickhouse>
    <users>
        <etl_user>
            <password_sha256_hex>e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855</password_sha256_hex>
        </etl_user>
    </users>
</clickhouse>
```

Генерация хеша:
```bash
echo -n 'my_password' | sha256sum | awk '{print $1}'
```

**Важно:** не используйте `<password>` (plaintext) в продакшене. Для SQL-пользователей: `CREATE USER ... IDENTIFIED WITH sha256_password BY '...'`.

## Практические сценарии

### Включение RBAC (предварительная настройка)

Для управления пользователями через SQL необходимо включить `access_management` в профиле пользователя по умолчанию и настроить `user_directories`:

```xml
<!-- config.d/access_management.xml -->
<clickhouse>
    <profiles>
        <default>
            <access_management>1</access_management>
        </default>
    </profiles>

    <user_directories>
        <users_xml>
            <path>/etc/clickhouse-server/users.xml</path>
        </users_xml>
        <local_directory>
            <path>/var/lib/clickhouse/access/</path>
        </local_directory>
    </user_directories>
</clickhouse>
```

`access_management = 1` разрешает пользователю выполнять SQL-команды управления доступом (`CREATE USER`, `GRANT`, `CREATE ROLE` и т.д.). Без этого флага RBAC недоступен даже для администраторов.

### SQL-driven RBAC

```sql
-- Роли и привилегии
CREATE ROLE analyst;
GRANT SELECT ON reporting.* TO analyst;
GRANT ALTER DELETE ON reporting.logs TO analyst;

-- Пользователь с хешированным паролем
CREATE USER readonly_user IDENTIFIED WITH sha256_password BY 'secure_pass';
GRANT analyst TO readonly_user;

-- Проверка прав
SHOW GRANTS FOR readonly_user;
SHOW GRANTS FOR CURRENT_USER;

-- Отзыв
REVOKE SELECT ON reporting.* FROM analyst;
```

### Row-Level Security (RLS)

```sql
-- Пользователь видит только строки своего клиента
CREATE ROW POLICY filter_by_client ON reporting.events
    FOR SELECT USING client_id = 101
    TO readonly_user;

-- Разные политики для SELECT и INSERT
CREATE ROW POLICY insert_policy ON reporting.events
    FOR INSERT WITH client_id = 101
    TO etl_user;

-- Мониторинг
SELECT * FROM system.row_policies;
```

### Quotas (SQL)

```sql
-- Лимит: 1000 запросов и 10 млн прочитанных строк в час
CREATE QUOTA analyst_quota
    FOR INTERVAL 1 HOUR
        MAX queries = 1000,
        MAX read_rows = 10000000
    TO analyst;

-- Несколько интервалов сразу
CREATE QUOTA etl_quota
    FOR INTERVAL 30 MINUTE MAX execution_time = 1800
    FOR INTERVAL 1 DAY MAX queries = 5000
    TO etl_user;

-- Квота по IP (каждый IP — отдельный лимит)
CREATE QUOTA per_ip_quota
    KEYED BY ip_address
    FOR INTERVAL 1 HOUR MAX queries = 200
    TO ALL;

-- Квота по паттерну запроса (защита от runaway-запросов)
CREATE QUOTA per_pattern_quota
    KEYED BY normalized_query_hash
    FOR INTERVAL 1 HOUR MAX queries = 100
    TO default;

-- Только отслеживание без ограничения
CREATE QUOTA tracking_quota
    FOR INTERVAL 1 DAY TRACKING ONLY
    TO analyst;

-- Мониторинг (текущий пользователь)
SELECT quota_name, duration, queries, max_queries, read_rows, max_read_rows,
       execution_time, max_execution_time
FROM system.quota_usage;

-- Мониторинг всех пользователей (админ)
SELECT quota_name, quota_key, queries, max_queries,
       round(queries / max_queries * 100, 1) AS pct_used
FROM system.quotas_usage
WHERE max_queries > 0
ORDER BY pct_used DESC;
```

**Лимиты квоты:** `queries`, `query_selects`, `query_inserts`, `errors`, `result_rows`, `result_bytes`, `read_rows`, `read_bytes`, `written_bytes`, `execution_time`, `failed_sequential_authentications`, `queries_per_normalized_hash`.

**Важно:** `SELECT` из таблиц `system.quotas`, `system.quota_limits`, `system.quota_usage`, `system.quotas_usage` не засчитывается в квоту — мониторинг работает даже при исчерпанной квоте.

### allow_networks (фильтрация по IP)

```xml
<!-- users.d/network_restrictions.xml -->
<clickhouse>
    <users>
        <etl_user>
            <allow_networks>
                <ip>10.0.0.0/8</ip>
                <ip>213.180.204.3</ip>
                <host>etl-host.internal</host>
                <host_regexp>^etl\d\d\.internal\.example\.com$</host_regexp>
            </allow_networks>
        </etl_user>
    </users>
</clickhouse>
```

### LDAP-аутентификация

**Шаг 1 — определение LDAP-сервера в `config.xml`:**
```xml
<!-- config.d/ldap_servers.xml -->
<clickhouse>
    <ldap_servers>
        <my_ldap_server>
            <host>ldap.internal</host>
            <port>636</port>
            <bind_dn>uid={user_name},ou=users,dc=example,dc=com</bind_dn>
            <enable_tls>yes</enable_tls>
            <tls_minimum_protocol_version>tls1.2</tls_minimum_protocol_version>
            <tls_require_cert>demand</tls_require_cert>
            <verification_cooldown>300</verification_cooldown>
        </my_ldap_server>
    </ldap_servers>
</clickhouse>
```

**Шаг 2 — подключение каталога к пользователям:**
```xml
<!-- config.d/user_directories.xml -->
<clickhouse>
    <user_directories>
        <users_xml>
            <path>/etc/clickhouse-server/users.xml</path>
        </users_xml>
        <local_directory>
            <path>/var/lib/clickhouse/access/</path>
        </local_directory>
        <ldap>
            <server>my_ldap_server</server>
            <roles>
                <analyst_role />
            </roles>
            <role_mapping>
                <base_dn>ou=groups,dc=example,dc=com</base_dn>
                <scope>subtree</scope>
                <search_filter>(&(objectClass=groupOfNames)(member={bind_dn}))</search_filter>
                <attribute>cn</attribute>
                <prefix>clickhouse_</prefix>
            </role_mapping>
        </ldap>
    </user_directories>
</clickhouse>
```

`{user_name}` в `bind_dn` подставляется при каждой попытке аутентификации (simple bind). `role_mapping` сопоставляет LDAP-группы с локальными ролями (атрибут `cn` группы становится именем роли с префиксом `clickhouse_`).

**Расширенная LDAP конфигурация с поиском групп:**

```xml
<ldap_servers>
    <my_ldap_server>
        <host>ldap.internal</host>
        <port>636</port>
        <bind_dn>uid={user_name},ou=users,dc=example,dc=com</bind_dn>
        <enable_tls>yes</enable_tls>
        <tls_minimum_protocol_version>tls1.2</tls_minimum_protocol_version>
        <tls_require_cert>demand</tls_require_cert>
        <verification_cooldown>300</verification_cooldown>

        <!-- Поиск группы для пользователя -->
        <search_filter>(uid={user_name})</search_filter>
        <role_mapping>
            <base_dn>ou=groups,dc=example,dc=com</base_dn>
            <scope>subtree</scope>
            <search_filter>(&</search_filter>
            <attribute>cn</attribute>
            <prefix>clickhouse_</prefix>
        </role_mapping>
    </my_ldap_server>
</ldap_servers>
```

**Active Directory** (с определением DN пользователя):
```xml
<my_ad_server>
    <host>ad.internal</host>
    <port>389</port>
    <bind_dn>EXAMPLE\{user_name}</bind_dn>
    <user_dn_detection>
        <base_dn>CN=Users,DC=example,DC=com</base_dn>
        <search_filter>(&(objectClass=user)(sAMAccountName={user_name}))</search_filter>
    </user_dn_detection>
</my_ad_server>
```

### Ограничения настроек пользователя

```xml
<!-- users.d/user_limits.xml -->
<clickhouse>
    <users>
        <etl_user>
            <readonly>1</readonly>              <!-- 0 — обычный, 1 — read-only, 2 — read-only + временные таблицы -->
            <allow_ddl>0</allow_ddl>            <!-- запрет DDL -->
            <max_memory_usage>10000000000</max_memory_usage>
            <max_execution_time>300</max_execution_time>
        </etl_user>
    </users>
</clickhouse>
```

Или через профили настроек (рекомендуется):
```sql
CREATE SETTINGS PROFILE etl_profile
    SETTINGS max_memory_usage = 10000000000,
             max_execution_time = 300,
             readonly = 1
TO etl_user;
```

### TOTP (двухфакторная аутентификация)

```xml
<!-- users.d/totp.xml -->
<clickhouse>
    <users>
        <admin_user>
            <password_sha256_hex>...</password_sha256_hex>
            <time_based_one_time_password>
                <secret>JBSWY3DPEHPK3PXP</secret>
                <period>30</period>
                <digits>6</digits>
                <algorithm>SHA1</algorithm>
            </time_based_one_time_password>
        </admin_user>
    </users>
</clickhouse>
```

Подключение: `clickhouse-client --password 'primary_password+345123'` (пароль + TOTP-код) или `--password primary --one-time-password 345123`.

### TLS/SSL шифрование соединений

ClickHouse поддерживает два транспортных протокола с TLS:

| Протокол | Порт | Настройка | Описание |
| :--- | :--- | :--- | :--- |
| HTTPS | 8443 | `https_port` / `openSSL` | HTTP-интерфейс с TLS (clickhouse-client, BI-инструменты) |
| Native | 9440 | `tcp_port_secure` | Нативный протокол с TLS (репликация, клиентские драйверы) |

**Конфигурация сервера (`config.d/ssl.xml`):**

```xml
<!-- /etc/clickhouse-server/config.d/ssl.xml -->
<clickhouse>
    <!-- HTTPS порт -->
    <https_port>8443</https_port>

    <!-- Native TLS порт -->
    <tcp_port_secure>9440</tcp_port_secure>

    <!-- Приоритет TLS-портов: если клиент подключается на 9000, а TLS доступен на 9440, -->
    <!-- сервер автоматически предлагает TLS на 9440 ( opportunistic TLS) -->

    <!-- Сертификаты -->
    <openSSL>
        <server>
            <certificate_file>/etc/clickhouse-server/ssl/server.crt</certificate_file>
            <private_key_file>/etc/clickhouse-server/ssl/server.key</private_key_file>
            <verification_mode>verify_if_available</verification_mode>
            <client_certificate_request>0</client_certificate_request>
            <!-- cipher_list для OpenSSL -->
        </server>
    </openSSL>

    <!-- Ограничение интерфейсов прослушивания -->
    <!-- По умолчанию: listen_host = :: (все интерфейсы) — ОПАСНО в production -->
    <listen_host>127.0.0.1</listen_host>
    <listen_host>10.0.0.0/8</listen_host>
</clickhouse>
```

**Сертификаты:** используйте сертификаты с SAN (Subject Alternative Name), включающие IP и hostname. Для внутренних CA используйте `verify_peer` для взаимной аутентификации клиентов.

**Важно:** отключите незашифованный порт 9000 в production — перенаправляйте все клиентские подключения на 9440. Используйте `listen_host` для ограничения доступа на уровне ОС, а не только firewall.

### X.509 сертификатная аутентификация

```xml
<clickhouse>
    <users>
        <cert_user>
            <auth_by_x509_certificate>
                <cn>clickhouse-client</cn>
                <issuer>/CN=example-CA</issuer>
                <subject_hash>0000000000000000000000000000000000000000</subject_hash>
            </auth_by_x509_certificate>
            <profile>readonly_profile</profile>
        </cert_user>
    </users>
</clickhouse>
```

`clickhouse-client --host host --port 9440 --certificate /etc/ssl/client.crt --private-key /etc/ssl/client.key` аутентифицирует клиента по сертификату без пароля.

### Аудит запросов

Аудит включается через конфигурацию `query_log` и `text_log` в `config.xml`:

```xml
<!-- config.d/logging.xml -->
<clickhouse>
    <logger>
        <level>information</level>
        <log>/var/log/clickhouse-server/clickhouse-server.log</log>
        <text_log>
            <type>passive</type>
            <compression>gzip</compression>
        </text_log>
    </logger>

    <query_log>
        <database>system</database>
        <table>query_log</table>
        <engine>Engine = MergeTree PARTITION BY toYYYYMM(event_time) ORDER BY (event_time, query_start_time) TTL event_time + INTERVAL 90 DAY</engine>
        <flush_interval_seconds>75</flush_interval_seconds>
    </query_log>
</clickhouse>
```

**Аудит запросов (SQL):**

```sql
-- Включить логирование всех запросов (SQL)
SET log_queries = 1;

-- Проверка, включен ли аудит
SELECT count() FROM system.query_log WHERE type = 'QueryFinish';

-- Логи аутентификации и прав доступа
SELECT event_time, user, query, exception 
FROM system.query_log 
WHERE query LIKE '%CREATE USER%' OR query LIKE '%GRANT%'
ORDER BY event_time DESC LIMIT 100;

-- Текстовые логи (security events, connection attempts)
SELECT event_time, message FROM system.text_log 
WHERE (message LIKE '%Authentication%' OR message LIKE '%Access denied%')
ORDER BY event_time DESC LIMIT 10;
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Authentication failed` | Неверный пароль/хеш, пользователь не найден в user_directories | Проверить приоритет `user_directories`; сверить `password_sha256_hex`; `SYSTEM DROP DNS CACHE` при LDAP |
| `User ... is not found` | Пользователь не создан или не в нужном каталоге | `SELECT * FROM system.users`; проверить `user_directories` |
| `Quota ... has been exceeded` | Исчерпан лимит квоты | `SELECT * FROM system.quota_usage`; увеличить лимит или подождать конца интервала |
| `Not enough privileges` | Нет привилегии | `SHOW GRANTS FOR user`; `GRANT ... TO user` |
| `Access denied` при подключении с хоста | `allow_networks` не включает IP клиента | Добавить IP/подсеть в `<allow_networks>` |
| Логинаут через `SYSTEM DROP DNS CACHE` при LDAP |
| TLS-соединение не устанавливается | Сертификат не действителен или CA не доверен | Проверить сертификаты через `openssl s_client -connect host:9440 -servername host`; включить `verification_cooldown` в LDAP |
| TOTP-код не принимается | Синхронизация времени, неверный secret | Проверить NTP (`chrony`/`ntpd`); сверить `period` и `digits` |
| `allow_ddl = 0` блокирует нужный запрос | Пользователь имеет `readonly`/`allow_ddl = 0` | Присвоить профиль с `allow_ddl = 1` или выполнить через сервисный аккаунт |
| X.509 аутентификация не работает | `auth_by_x509_certificate` не настроен, или CN/issuer не совпадают | Проверить CN и issuer в сертификате; включить `client_certificate_request = 1` в `openSSL` |
| `listen_host` блокирует подключение | IP клиента не в списке `listen_host` | Добавить подсеть или использовать `0.0.0.0` (но только через firewall) |
| `query_log` не пишет | `log_queries` не включён или `query_log` не настроен | `SET log_queries = 1`; проверить конфиг `query_log` в `config.xml` |
| Роли LDAP сбрасываются после перезагрузки | `replicated` user_directory не настроен, LDAP-роли не локальны | Создать роли локально (`CREATE ROLE`); использовать `replicated` для SQL-пользователей

## Лучшие практики

1. **Принцип наименьших привилегий:** `GRANT` только нужные привилегии на нужные таблицы; используйте роли.
2. **sha256_password** для паролей в конфигурации, никогда plaintext.
3. **Quotas** для защиты от runaway-запросов: `KEYED BY normalized_query_hash` ограничивает повторяющиеся тяжёлые запросы.
4. **allow_networks** — ограничивайте подключение по IP/подсети, особенно для сервисных аккаунтов.
5. **LDAP** для централизованной аутентификации; `role_mapping` для автоматического назначения ролей по группам.
6. **`replicated` user_directory** — репликация SQL-пользователей через Keeper на все узлы кластера.
7. **Row policies** для мультитенантности — фильтрация строк по клиенту/арендатору.
8. **Аудит:** включите `query_log` и `text_log` для compliance и расследований.
   9. **Не редактируйте `config.xml`/`users.xml` напрямую** — используйте `config.d/` и `users.d/`.
   10. **TLS для всех production-соединений:** включайте HTTPS (8443) и native TLS (9440); отключайте plaintext 8123/9000 через `firewalld`/`iptables`.
   11. **`listen_host` по умолчанию:** всегда ограничивайте подсети через `listen_host`, а не только firewall — defense in depth.
   12. **`replicated` user_directory:** используйте репликацию SQL-пользователей через Keeper для согласованности в кластере; не храните пароли в `users.xml` для сервисных аккаунтов.
   13. **Аудит и retention:** настраивайте `query_log` с TTL (90 дней); логируйте `GRANT`/`REVOKE`/`CREATE USER`; экспортируйте `system.query_log` в SIEM.
   14. **Шифрование данных:** используйте `diskEncryption` для защиты данных в покое на дисках (`system.disks` + `CREATE DISK ... TYPE default ENCRYPTED`).

## Дополнительная информация

### Смежные темы

- Основной обзор — **[ClickHouse](./clickhouse.md)**.
- RBAC (базовый пример) — **[Эксплуатация](./clickhouse-operations.md#безопасность-и-управление-доступом)**.
- Мониторинг квот и пользователей — **[Мониторинг](./clickhouse-monitoring.md)**.
- LDAP-сервер (сам LDAP) — **[LDAP](../../LDAP/ldap_troubleshooting.md)**.

### Ресурсы

- [Документация: CREATE QUOTA](https://clickhouse.com/docs/reference/statements/create/quota)
- [Документация: LDAP](https://clickhouse.com/docs/concepts/features/security/external-authenticators/ldap)
- [Документация: user_directories](https://clickhouse.com/docs/reference/settings/server-settings/settings/user)
- [Документация: TLS/SSL](https://clickhouse.com/docs/operations/server-configuration-keeping#tls)
- [Документация: RBAC](https://clickhouse.com/docs/guides/basics/tutorial-rbac)
