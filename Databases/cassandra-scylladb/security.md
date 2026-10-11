# Безопасность

**Актуально для:** Apache Cassandra 5.0.x / ScyllaDB 2026.x

## Определения

**Аутентификация (Authentication)** — проверка личности клиента (кто подключается). Реализуется pluggable-провайдерами, настраивается в `cassandra.yaml` / `scylla.yaml`.

**Авторизация (Authorization)** — проверка прав (что разрешено делать). RBAC: привилегии выдаются ролям, роли назначаются пользователям.

**TLS / mTLS** — шифрование трафика TLS; mutual TLS (mTLS) — взаимная проверка сертификатов клиента и сервера (`require_client_auth: true`).

**Keystore / Truststore** — JKS-хранилища Java: keystore содержит собственный сертификат и ключ, truststore — доверенные CA. ScyllaDB вместо них использует PEM-файлы.

**JMX (Java Management Extensions)** — интерфейс управления узлом Cassandra (nodetool, JConsole), порт 7199.

**bcrypt** — адаптивная хеш-функция для хранения паролей в PasswordAuthenticator.

## Как устроена защита

Три уровня защиты, каждый следующий бесполезен без предыдущего:

1. **Сеть:** firewall (порты 9042/7000/7199) и TLS.
2. **Аутентификация:** кто подключается (`authenticator`).
3. **Авторизация:** что разрешено (`authorizer`).

> Аутентификация — необходимое условие подсистемы прав: с `AllowAllAuthenticator` (значение по умолчанию) авторизация фактически не работает, даже если задан `authorizer: CassandraAuthorizer`.

**Позиция по умолчанию (out-of-the-box):** Cassandra и ScyllaDB из коробки открыты — `AllowAllAuthenticator` + `AllowAllAuthorizer`, JMX на localhost без пароля. Это удобно для первого запуска и неприемлемо для production.

**Ключевые различия Cassandra ↔ ScyllaDB:**

| Аспект | Cassandra | ScyllaDB |
|---|---|---|
| Конфиг | `cassandra.yaml` | `scylla.yaml` |
| Хранилище ключей TLS | JKS/JCEKS (keytool) | PEM (openssl) |
| Провайдеры аутентификации | AllowAll, Password (+ плагины) | AllowAll, Password, Certificate, Transitional, Saslauthd |
| Ротация TLS-сертификатов | `nodetool reloadssl` (4.0+) | автоматически с диска |
| Аудит, шифрование данных | DSE (Enterprise) | ScyllaDB Enterprise |

## Аутентификация

### Включение

```yaml
# cassandra.yaml (Cassandra)
authenticator: PasswordAuthenticator      # по умолчанию: AllowAllAuthenticator
authorizer: CassandraAuthorizer           # по умолчанию: AllowAllAuthorizer
role_manager: CassandraRoleManager        # только Cassandra; ScyllaDB управляет ролями сама
```

```yaml
# scylla.yaml (ScyllaDB)
authenticator: PasswordAuthenticator
authorizer: CassandraAuthorizer
```

Смена `authenticator`/`authorizer` требует перезапуска узла (rolling restart — по очереди).

**Провайдеры ScyllaDB** (Cassandra использует первые два + собственные плагины):

| Провайдер | Назначение |
|---|---|
| `AllowAllAuthenticator` | без проверки (по умолчанию) |
| `PasswordAuthenticator` | логин/пароль, bcrypt-хеш в `system_auth` |
| `com.scylladb.auth.CertificateAuthenticator` | mTLS: роль из subject сертификата (`auth_certificate_role_queries`, например `CN=([^,\s]+)`); superuser — `auth_superuser_name` |
| `com.scylladb.auth.TransitionalAuthenticator` | PasswordAuthenticator + анонимный доступ для остальных |
| `com.scylladb.auth.SaslauthdAuthenticator` | PAM через saslauthd |

**Авторизаторы ScyllaDB:** `AllowAllAuthorizer` (по умолчанию), `CassandraAuthorizer` (права в `system_auth.permissions`), `com.scylladb.auth.TransitionalAuthorizer` (управление правами через CassandraAuthorizer, остальные действия разрешены всем).

### Суперпользователь по умолчанию

При первом включении `PasswordAuthenticator` существует роль `cassandra` с паролем `cassandra`. **Сменить пароль до production:**

```sql
ALTER ROLE cassandra WITH PASSWORD = '<новый_пароль>';
```

### Управление ролями (CQL)

```sql
-- Создание роли с паролем
CREATE ROLE app_user WITH PASSWORD = 'secure_password_2026' AND LOGIN = true;

-- Суперпользователь
CREATE ROLE admin_user WITH SUPERUSER = true AND LOGIN = true AND PASSWORD = '<пароль>';

-- Смена пароля
ALTER ROLE app_user WITH PASSWORD = 'new_password_2026';

-- Удаление
DROP ROLE app_user;

-- Просмотр ролей
LIST ROLES;
# → role      | super | login
# → -----------+-------+-------
# → cassandra |  True |  True
# → app_user  | False |  True
```

`HASHED_PASSWORD` — вставка готового bcrypt-хеша без повторного хеширования (только superuser, для миграции из другой системы).

**Хранение паролей (Cassandra):** bcrypt-хеш в `system_auth.roles` (столбец `salted_hash`). Число раундов — 2^10 по умолчанию, настраивается `-Dcassandra.auth_bcrypt_gensalt_log2_rounds` (диапазон 4–30). Не снижайте раунды ради производительности: при большом числе коротких подключений bcrypt может загрузить CPU (CASSANDRA-14678) — эта проблема решается кэшем учётных данных, а не ослаблением хеша.

### Кэши аутентификации и прав

```yaml
roles_validity_in_ms: 2000        # кэш ролей сессии
permissions_validity_in_ms: 2000  # кэш прав (CassandraAuthorizer)
credentials_validity_in_ms: 2000  # кэш учётных данных (PasswordAuthenticator)
```

Значение `0` отключает кэш. Параметры `*_update_interval_in_ms` задают фоновое обновление записи (async reload): до завершения обновления отдаётся старое значение. Кэши автоматически отключаются для AllowAll-провайдеров.

### system_auth — критично для multi-DC

Роли и права хранятся в системной keyspace `system_auth` (по умолчанию `SimpleStrategy RF=1`). Если единственная реплика упадёт — войти в кластер будет невозможно. **До включения аутентификации** в multi-DC кластере:

```sql
ALTER KEYSPACE system_auth WITH REPLICATION = {'class': 'NetworkTopologyStrategy', 'dc1': 3, 'dc2': 3};
```

## Авторизация (GRANT / REVOKE)

```sql
-- Права на keyspace
GRANT SELECT, INSERT, UPDATE, DELETE ON KEYSPACE my_app TO app_user;
-- Эквивалент: GRANT MODIFY ON KEYSPACE my_app TO app_user;  (MODIFY = INSERT+UPDATE+DELETE)

-- Права на таблицу
GRANT SELECT ON TABLE my_app.user_events TO app_user;

-- Все keyspaces
GRANT SELECT ON ALL KEYSPACES TO readonly_user;

-- Отзыв
REVOKE SELECT ON KEYSPACE my_app FROM app_user;

-- Просмотр прав
LIST ALL PERMISSIONS OF app_user;
LIST PERMISSIONS OF app_user ON KEYSPACE my_app;
```

Типы разрешений: `SELECT`, `MODIFY` (INSERT/UPDATE/DELETE), `CREATE`, `ALTER`, `DROP`, `AUTHORIZE` (выдача прав), `DESCRIBE`, `EXECUTE` (UDF), `ALL PERMISSIONS`.

Права вступают в силу сразу, но клиент может не увидеть их до истечения кэша (`permissions_validity_in_ms`, по умолчанию 2000 мс). Принудительная очистка:

```bash
nodetool invalidatepermissionscache
```

**Валидация:**
```bash
cqlsh -u app_user -p 'secure_password_2026' 10.0.1.1
# → Connected to ProductionCluster at 10.0.1.1:9042.
# → [cqlsh 6.0.0 | Cassandra 5.0.9 | CQL spec 3.4.6 | Native protocol v5]
```

## TLS/SSL (шифрование трафика)

### Cassandra (JKS)

```yaml
# cassandra.yaml
client_encryption_options:
    enabled: true
    keystore: /etc/cassandra/ssl/keystore.jks
    keystore_password: changeit
    require_client_auth: false      # true = mTLS для клиентов
    truststore: /etc/cassandra/ssl/truststore.jks
    truststore_password: changeit
    # protocol: TLS                 # по умолчанию TLS (автонастройка версии)
    # algorithm: SunX509
    # store_type: JKS

server_encryption_options:
    internode_encryption: all       # none | all | dc | rack
    keystore: /etc/cassandra/ssl/keystore.jks
    keystore_password: changeit
    truststore: /etc/cassandra/ssl/truststore.jks
    truststore_password: changeit
    require_client_auth: true       # mTLS между узлами
```

`internode_encryption`: `all` — всё межузловое шифрование, `dc` — только между DC, `rack` — только между стойками. В Cassandra 4.0+ один порт 7000 может обслуживать и шифрованный, и открытый трафик (StartTLS, CASSANDRA-10404) — отдельный порт 7001 опционален.

Генерация самоподписанных сертификатов (тесты):

```bash
# Сертификат узла
keytool -genkeypair -keyalg RSA -keysize 2048 \
    -alias cassandra -validity 365 \
    -keystore keystore.jks -storepass changeit

# Экспорт и импорт в truststore (доверие между узлами)
keytool -exportcert -alias cassandra -file cassandra.crt -keystore keystore.jks -storepass changeit
keytool -importcert -alias cassandra -file cassandra.crt -keystore truststore.jks -storepass changeit
```

### ScyllaDB (PEM)

Конфигурация принципиально отличается — PEM-файлы вместо JKS:

```yaml
# scylla.yaml
client_encryption_options:
    enabled: true
    certificate: /etc/scylla/db.crt        # PEM-сертификат
    keyfile: /etc/scylla/db.key            # PEM-ключ
    truststore: /etc/scylla/ca.crt         # PEM с доверенными CA (опционально; по умолчанию — системное хранилище)
    require_client_auth: false
    priority_string: SECURE128:-VERS-TLS1.0:-VERS-TLS1.1   # GnuTLS: минимум TLS 1.2
    # certficate_revocation_list: /etc/scylla/crl.pem        # CRL (ключ с опечаткой — таково фактическое имя)
    # enable_session_tickets: false                          # TLS 1.3 session tickets

server_encryption_options:
    internode_encryption: all
    certificate: /etc/scylla/db.crt
    keyfile: /etc/scylla/db.key
    truststore: /etc/scylla/ca.crt
    require_client_auth: true
```

`priority_string` — синтаксис GnuTLS priority strings (gnutls.org). Пример выше отключает TLS 1.0/1.1 при минимальной стойкости 128 бит.

```bash
# Самоподписанный сертификат (тесты)
openssl req -x509 -newkey rsa:2048 -keyout db.key -out db.crt -days 365 -nodes -subj "/CN=$(hostname)"
```

**Горячая замена сертификатов:** ScyllaDB отслеживает файлы сертификатов на диске и перечитывает их автоматически — перезапуск не нужен. Cassandra 4.0+: `nodetool reloadssl`.

### Подключение клиентов с TLS

Cassandra — `cqlsh` через `~/.cassandra/cqlshrc`:

```ini
[connection]
hostname = 10.0.1.1
port = 9042
factory = cqlshlib.ssl.ssl_transport_factory

[ssl]
certfile = ~/.cassandra/rootCa.crt    # CA для проверки сервера
validate = true                       # проверка CN/SAN сертификата (по умолчанию true)
userkey = ~/.cassandra/client.key     # только при require_client_auth=true
usercert = ~/.cassandra/client.crt
```

```bash
cqlsh --ssl 10.0.1.1 9042
```

Переменные `SSL_CERTFILE` и `SSL_VALIDATE` переопределяют настройки cqlshrc. ScyllaDB использует тот же механизм cqlsh.

**nodetool с TLS:** файл `~/.cassandra/nodetool-ssl.properties`:

```properties
-Dcom.sun.management.jmxremote.ssl=true
-Dcom.sun.management.jmxremote.ssl.need.client.auth=true
-Dcom.sun.management.jmxremote.registry.ssl=true
-Djavax.net.ssl.keyStore=/etc/cassandra/ssl/keystore.jks
-Djavax.net.ssl.keyStorePassword=changeit
-Djavax.net.ssl.trustStore=/etc/cassandra/ssl/truststore.jks
-Djavax.net.ssl.trustStorePassword=changeit
```

```bash
nodetool --ssl -u cassandra -pw <пароль> status
```

## JMX (порт 7199)

JMX — интерфейс для nodetool/JConsole. По умолчанию (`LOCAL_JMX=yes` в `cassandra-env.sh`) доступен только с localhost без аутентификации — это безопасная конфигурация, её и стоит сохранять. ScyllaDB использует стандартный JMX на том же порту 7199.

**Если нужен удалённый JMX** (лучше — SSH-туннель):

```bash
# cassandra-env.sh: LOCAL_JMX=no
JVM_OPTS="$JVM_OPTS -Dcom.sun.management.jmxremote.authenticate=true"
JVM_OPTS="$JVM_OPTS -Dcom.sun.management.jmxremote.password.file=/etc/cassandra/jmxremote.password"
```

```bash
# /etc/cassandra/jmxremote.password (chmod 400, владелец — пользователь Cassandra)
cassandra <пароль>
```

Альтернатива — интегрированная аутентификация Cassandra (роли CQL для JMX): раскомментировать в `cassandra-env.sh` строки `-Dcassandra.jmx.remote.login.config=CassandraLogin`, `-Djava.security.auth.login.config=$CASSANDRA_HOME/conf/cassandra-jaas.config` и `-Dcassandra.jmx.authorizer=org.apache.cassandra.auth.jmx.AuthorizationProxy`, отключив стандартный `jmxremote.password.file`. Доступно только после того, как узел вошёл в кольцо (auth-подсистема ещё не настроена на bootstrap) — на bootstrap держите локальный JMX.

```bash
nodetool -u cassandra -pw <пароль> status                          # с аутентификацией
nodetool -u cassandra -pwf /path/to/jmx_password_file status       # пароль из файла (скрипты)
```

## Сетевая защита (firewall)

| Порт | Назначение | Доступ |
|---|---|---|
| 9042 | CQL (native transport) | приложения-клиенты |
| 7000 | межузловой трафик (gossip, streaming) | узлы кластера |
| 7001 | межузловой SSL (отдельный порт; в 4.0+ опционален — StartTLS на 7000) | узлы кластера |
| 7199 | JMX (nodetool) | только localhost / ops-сеть |
| 9180 | нативный Prometheus endpoint (ScyllaDB) | monitoring-сеть |
| 9043 | отдельный TLS-порт для CQL (ScyllaDB, `native_transport_port_ssl`) | при использовании |

Thrift (порт 9160) **удалён в Cassandra 4.0** (CASSANDRA-11115) вместе с опциями `start_rpc`, `rpc_port` — их нельзя добавлять обратно в `cassandra.yaml`, иначе узел не запустится.

**UDF (user-defined functions):** отключены по умолчанию (`enable_user_defined_functions: false`, `enable_scripted_user_defined_functions: false`) — не включайте без необходимости. Скриптовые UDF без UDF-потоков — RCE (CVE-2021-44521, CASSANDRA-17352, исправлено в 3.0.26/3.11.12/4.0.2).

## Управление секретами (secrets)

**Проблема:** пароли и ключи в конфигурации (`keystore_password`, `truststore_password`, пароли ролей в скриптах) — риск утечки при коммите в Git или доступе к хосту.

**Практики:**

- **Не хранить секреты в Git:** конфигурации с паролями — вне VCS или через шаблоны с переменными окружения
- **Vault / KMS:** хранить пароли, TLS-ключи и JMX-учётные данные в системе управления секретами (HashiCorp Vault и аналоги); подставлять при деплое — обзор подходов — **[Управление секретами: обзор](../../Security/Concepts/secrets_management_overview.md)**
- **Права на файлы:** `jmxremote.password` — `chmod 400`, владелец — пользователь Cassandra (см. раздел JMX); PEM-ключи ScyllaDB — аналогично
- **Ротация:** пароли ролей — `ALTER ROLE ... WITH PASSWORD`; TLS-сертификаты — горячая замена (см. раздел TLS)

## Возможности Enterprise-редакций

В Open Source отсутствуют (проверяйте редакцию до проектирования):

- **Аудит:** ScyllaDB Enterprise — `audit: "table"` (таблица `audit.audit_log`, с 2024.2 — NetworkTopologyStrategy RF=3) или `syslog`, фильтры `audit_categories`/`audit_keyspaces`/`audit_tables`/`audit_rules`. Cassandra — аудит только в DSE.
- **Шифрование данных (encryption at rest):** ScyllaDB Enterprise — секции `system_info_encryption`/`user_info_encryption` в `scylla.yaml`, per-таблица через `scylla_encryption_options`, провайдеры ключей: локальный файл (по умолчанию, не для production) или внешний KMS по KMIP. Cassandra — TDE только в DSE. Теория и сравнение — **[Шифрование данных «в покое»](../Concepts/encryption_at_rest.md)**.
- **LDAP / Kerberos:** DSE и ScyllaDB Enterprise.

## Поиск и устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| `Unable to authenticate` | неверные учётные данные; `PasswordAuthenticator` не включён на всех узлах | проверить `authenticator` в конфиге; первый вход — `cqlsh -u cassandra -p cassandra` |
| Потеря доступа в multi-DC | `system_auth` с RF=1, узел с репликой недоступен | `ALTER KEYSPACE system_auth WITH REPLICATION = {...}` (до включения auth); восстановить узел |
| GRANT/REVOKE не виден клиенту | кэш прав (`permissions_validity_in_ms`, 2000 мс) | подождать или `nodetool invalidatepermissionscache` |
| `cqlsh --ssl`: hostname verification failure | CN/SAN сертификата не совпадает с хостом; `validate = true` по умолчанию | сертификат с правильным SAN; `validate = false` — только для тестов |
| `nodetool`: `SecurityException: Authentication failed! Credentials required` | включена JMX-аутентификация | `nodetool -u <user> -pw <пароль> status` |
| Смена сертификатов не вступает в силу | Cassandra < 4.0 — перезапуск | Cassandra 4.0+: `nodetool reloadssl`; ScyllaDB — автоматически |
| Новые настройки auth не работают | `authenticator`/`authorizer` — статические параметры | rolling restart узлов |

## Рекомендации

- **Defense-in-depth:** firewall + TLS + аутентификация + авторизация; ни один уровень не заменяет остальные.
- **Сменить пароль `cassandra`** сразу после включения `PasswordAuthenticator`.
- **`system_auth` с RF=3** (NetworkTopologyStrategy) до включения auth в multi-DC.
- **TLS везде:** client-to-node и internode; `require_client_auth: true` (mTLS) для internode в ненадёжных сетях.
- **JMX — только localhost**; удалённый доступ — через SSH-туннель или с auth + SSL.
- **Least privilege:** права на уровне keyspace/таблицы, роли вместо прямых прав пользователям; `SUPERUSER` — только администраторам.
- **UDF держать отключёнными** (CVE-2021-44521).
- **Ротация паролей:** `ALTER ROLE ... WITH PASSWORD`; аудит прав — `LIST ROLES` / `LIST ALL PERMISSIONS OF <role>`.
- **bcrypt rounds не снижать** без крайней необходимости (CASSANDRA-14678 — trade-off CPU vs стойкость).
- **Мониторить неудачные попытки входа** (аудит — Enterprise; в OSS — логи узла).

## См. также
- **[Установка и настройка](./installation.md)** — cassandra.yaml, порты.
- **[Обслуживание и эксплуатация](./operations.md)** — nodetool, жизненный цикл узлов.
- **[Мониторинг и observability](./monitoring.md)** — JMX Exporter, Prometheus endpoint 9180.
- **[Шифрование данных «в покое»](../Concepts/encryption_at_rest.md)** — теория шифрования, TDE.
