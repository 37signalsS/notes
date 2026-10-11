# Безопасность и шифрование в PostgreSQL

**Актуально для:** PostgreSQL 13–18

## Определения

**HBA (Host-Based Authentication)** — механизм аутентификации по хосту: файл `pg_hba.conf` определяет, кто, откуда и каким способом может подключиться к серверу. Первая подходящая запись побеждает, «проваливания» к следующим записям нет.

**pg_hba.conf** — файл правил аутентификации в каталоге данных кластера (путь можно переназначить параметром `hba_file`). Перечитывается при старте сервера и по сигналу `SIGHUP` (reload); на Windows изменения применяются сразу для новых подключений.

**SCRAM-SHA-256** — современная аутентификация по схеме challenge-response (RFC 7677): пароль не передаётся по сети даже в открытом виде, а на сервере хранится только хэш. Метод аутентификации по умолчанию с PostgreSQL 14; сам протокол поддерживается с PostgreSQL 10.

**SSL/TLS (`sslmode`)** — шифрование клиент-серверного трафика. PostgreSQL использует термины SSL и TLS как синонимы (протоколы SSL 2/3 всегда отключены, поддерживаются TLS 1.0–1.3).

**pgcrypto** — стандартное расширение для криптографических операций на уровне SQL (хеширование, шифрование столбцов, генерация случайных данных). Trusted-расширение: устанавливается любым пользователем с правом `CREATE` в базе. Детальное руководство: **[pgcrypto: Криптография в PostgreSQL](./pgcrypto.md)**.

**RLS (Row-Level Security)** — политики на уровне строк таблицы: ограничивают, какие строки видны или доступны на изменение каждой роли, поверх обычной системы привилегий.

**TDE (Transparent Data Encryption)** — прозрачное шифрование данных на уровне СУБД. В ванильном PostgreSQL (Community Edition) нативной поддержки TDE нет: реализуется расширением `pg_tde` (Percona) или шифрованием на уровне ОС.

**pgAudit** — расширение детального аудит-логирования сессий и объектов через стандартный механизм логирования PostgreSQL (`AUDIT: SESSION,...` / `AUDIT: OBJECT,...` записи в логе). Поддерживает PostgreSQL 14+.

**BYPASSRLS** — атрибут роли, позволяющий обходить все политики RLS (суперпользователи обходят RLS всегда).

## Базовые концепции

### Модель безопасности PostgreSQL

Безопасность строится эшелонами — каждый следующий слой не отменяет предыдущий:

1. **Сетевой доступ** — `listen_addresses` (дефолт `localhost`: TCP-доступ с удалённых хостов выключен по умолчанию), `unix_socket_permissions` (дефолт `0777`: записывать может владелец, но подключаться через сокет может любой локальный пользователь — ограничение делается в `pg_hba.conf`).
2. **Аутентификация** — `pg_hba.conf`: тип соединения, адрес клиента, база, роль, метод. Записи проверяются последовательно, применяется **первая подходящая**; если она выбрана и аутентификация провалилась — последующие записи не рассматриваются. Если ни одна не подошла — доступ запрещён.
3. **Авторизация** — система привилегий SQL (`GRANT`/`REVOKE`), роли и их атрибуты. Для подключения к базе роли нужен ещё и `CONNECT`-привилегия — зачастую проще управлять ею, чем правилами `pg_hba.conf`.
4. **RLS** — политики внутри таблицы (при включённом RLS и отсутствии политик работает default-deny: ни одна строка не видна и не может быть изменена).
5. **Шифрование** — TLS для трафика и шифрование данных «в покое».

### Методы аутентификации

| Метод | Тип соединения | Суть | Применение |
| :--- | :--- | :--- | :--- |
| `trust` | любой | Подключение без проверки | Только `local`/loopback для отладки; в production недопустим |
| `reject` | любой | Безусловный запрет | Отфильтровать конкретные хосты перед разрешающей записью |
| `scram-sha-256` | любой | Challenge-response, хэш на сервере | Обязательный метод для production |
| `md5` | любой | Устаревший challenge-response; если пароль хранится в SCRAM — автоматически используется SCRAM | Только для старых клиентов; deprecated |
| `password` | любой | Пароль открытым текстом | Только внутри SSL-соединения |
| `peer` | `local` | ОС-пользователь должен совпадать с ролью БД | Локальные административные подключения |
| `ident` | TCP | Имя ОС-пользователя запрашивается у ident-сервера клиента | Наследует доверие к ident-серверу — небезопасен |
| `cert` | `hostssl` | Аутентификация клиентским сертификатом; CN сертификата сопоставляется с именем роли (или маппингом из `pg_ident.conf`) | mTLS, машинные аккаунты |
| `gss` / `sspi` | TCP / Windows | Kerberos (GSSAPI) / Windows SSPI | Корпоративный SSO; `gss` может работать с GSSAPI-шифрованием (`hostgssenc`) |
| `ldap` / `radius` / `pam` / `bsd` | зависит | Внешние системы аутентификации | Интеграция с каталогами и PAM/BSD auth |

Дополнительные поля записи: `sameuser` (база = имя роли), `samerole` (роль — член роли с именем базы), `replication` (физические репликационные подключения; логические репликацию не ловят), `+role` в поле USER (любой член роли), `/regex` и `@file` в полях DATABASE/USER, адреса в CIDR-нотации или спецключевые слова `all`/`samehost`/`samenet`, hostname (обратный + прямой DNS), `.example.com` (суффикс). Записи могут быть объединены директивами `include`, `include_if_exists`, `include_dir`.

**Важно:** пароль значим только для методов, требующих его (`password`, `md5`, `scram-sha-256`); если пароль не задан (`NULL` в `pg_authid`), password-аутентификация всегда неудачна. Таймаут аутентификации — `authentication_timeout` (дефолт `1m`).

### Роли и привилегии

| Атрибут | Суть |
| :--- | :--- |
| `LOGIN` | Роль пригодна как имя для подключения; `CREATE USER` = `CREATE ROLE` с `LOGIN` по умолчанию |
| `SUPERUSER` | Обходит все проверки прав (кроме права на вход) — опасен, использовать только для администрирования |
| `CREATEDB` / `CREATEROLE` | Создание баз / ролей. `CREATEROLE` не даёт создавать SUPERUSER-роли, управлять привилегиями REPLICATION-ролей и выдавать/отзывать `BYPASSRLS` |
| `REPLICATION` | Инициация streaming-репликации (требуется также `LOGIN`) |
| `BYPASSRLS` | Обход всех политик RLS |
| `NOINHERIT` | Не наследовать привилегии ролей-членов по умолчанию |
| `CONNECTION LIMIT n` | Лимит одновременных подключений роли (`-1` = без лимита) |

Пароли задаются через `CREATE ROLE ... PASSWORD '...'`, `ALTER ROLE` или команду psql `\password` (не через SQL-строку в скриптах — она попадёт в логи и историю). Хэши хранятся в системном каталоге `pg_authid` (виден только суперпользователю):

```sql
SELECT rolname, rolpassword FROM pg_authid WHERE rolname = 'app_user';
-- → SCRAM-SHA-256$4096:c2FsdA==$c3RvcmVkLXNjcmFtLXN0b3JlZA==
```

Роль может иметь персональные дефолты параметров (`ALTER ROLE app SET ...`), что позволяет, например, принудительно включать `statement_timeout` для сервисных ролей.

### Пароли: хранение и миграция md5 → SCRAM

Параметр `password_encryption` определяет алгоритм хэширования при задании пароля. Дефолт — `scram-sha-256` (в PostgreSQL 13 дефолт был `md5`, начиная с 14 — `scram-sha-256`). Число итераций SCRAM задаёт `scram_iterations` (дефолт `4096`); оно фиксируется на момент задания пароля — изменение параметра не влияет на уже зашифрованные пароли, для них нужен сброс пароля.

Поддержка MD5-хэшей deprecated и будет удалена в будущих релизах. Миграция существующего кластера:

```bash
# 1. Убедиться, что все клиентские библиотеки поддерживают SCRAM
# 2. Включить новый алгоритм хэширования
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
SELECT pg_reload_conf();
# 3. Сбросить пароли всех ролей (хэш перевычислится по новому алгоритму)
\password app_user          # в psql, или ALTER ROLE ... PASSWORD '...'
# 4. Заменить метод в pg_hba.conf и перечитать конфиг
#    host all all 10.0.0.0/8 scram-sha-256
```

Переходный трюк: запись `md5` в `pg_hba.conf` автоматически использует SCRAM, если хэш роли уже SCRAM-формат — это позволяет менять `pg_hba.conf` и пароли независимо, не ломая старых клиентов.

## Практические сценарии

### Требования

- PostgreSQL 13–18; суперпользователь для правки `postgresql.conf`/`pg_hba.conf` и установки расширений (`pgcrypto` — исключение: trusted).
- Сборка с OpenSSL (`pg_config --configure | grep -o 'with-openssl'`) для TLS и `pgcrypto`.
- `psql` для применения политик; роль с `pg_read_all_stats` (или суперпользователь) для `pg_stat_ssl`/`pg_stat_activity`.
- Для pgAudit — установка пакета расширения и правка `shared_preload_libraries` (перезапуск сервера).

### 1. Шифрование данных «в покое» (TDE)

Поскольку в ядре PostgreSQL 13–18 нативного TDE нет, SRE используют три подхода:

#### Вариант А: Расширение `pg_tde` (Percona)

Расширение предоставляет access method `tde_heap` и шифрует кортежи, WAL и индексы прозрачно для приложения. Ограничения и требования:

- Бинарные пакеты предоставляются только для **Percona Server for PostgreSQL 17/18**; для community-сборок — сборка из исходников.
- **Не шифрует** временные файлы и статистику.
- Управление ключами: файловый провайдер (keyringfile) или внешние KMS через Global Key Provider interface (PKCS#11, например HashiCorp Vault/OpenBao).
- Установка от суперпользователя (расширение не trusted).

```sql
CREATE EXTENSION pg_tde;

-- Таблица на зашифрованном access method
CREATE TABLE sensitive_data (
    id INT PRIMARY KEY,
    secret_val TEXT
) USING tde_heap;
```

Детали и статус таблиц: документация [docs.percona.com/pg-tde](https://docs.percona.com/pg-tde/).

#### Вариант Б: Шифрование на уровне файловой системы (LUKS / ZFS / dm-crypt)

Рекомендуемый подход Community. Данные шифруются при записи на диск средствами ОС.
- **Плюсы:** нулевой оверхед на уровне SQL, простота настройки, соответствие PCI DSS.
- **Минусы:** не защищает от пользователя `postgres` (суперпользователя БД) при компрометации ОС, пока файловая система смонтирована — ОС предоставляет незашифрованное представление данных. Защита работает только при физической краже носителя.

#### Вариант В: Шифрование на стороне клиента

Если администратор сервера не является доверенным — клиент шифрует данные до отправки; незашифрованные данные никогда не появляются на сервере БД. Реализуется через `pgcrypto` в коде приложения или внешние инструменты; ценой является потеря поиска/индексации по зашифрованным полям.

Теория управления ключами (DEK/KEK, envelope encryption, ротация, KMS/HSM, влияние на производительность и бэкапы) — в SSoT **[Шифрование данных «в покое»](../../Concepts/encryption_at_rest.md)**.

### 2. Шифрование на уровне столбцов (`pgcrypto`)

Используется, когда нужно защитить отдельные поля даже от администратора БД. Детальное руководство: **[pgcrypto: Криптография в PostgreSQL](./pgcrypto.md)**.

Ключевой нюанс (из официальной документации): клиент поставляет ключ, данные расшифровываются на сервере и передаются клиенту — расшифрованные данные и ключ **кратковременно присутствуют на сервере**, и тот, кто имеет полный доступ к серверу БД (системный администратор), может их перехватить. Поэтому `pgcrypto` защищает от кражи диска/бэкапа, но не от компрометации ОС или суперпользователя, контролирующего процесс.

### 3. Защита трафика (SSL/TLS)

#### Настройка сервера (`postgresql.conf`)

```ini
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'
ssl_min_protocol_version = 'TLSv1.2'   # дефолт; SSLv2/3 всегда отключены
ssl_max_protocol_version = ''           # дефолт: любая доступная версия
ssl_ciphers = 'HIGH:MEDIUM:+3DES:!aNULL'  # дефолт, для TLS ≤ 1.2
ssl_prefer_server_ciphers = on          # дефолт
ssl_groups = 'X25519:prime256v1'       # дефолт (в ≤17 назывался ssl_ecdh_curve)
```

Правила эксплуатации (из официальной документации):

- Файлы по умолчанию ищутся в `$PGDATA`; относительные пути считаются от каталога данных. На `server.key` права должны запрещать доступ группе и прочим: `chmod 0600 server.key` (допустима альтернатива — владелец root и `0640` с членством пользователя postgres в группе).
- Первый сертификат в `server.crt` должен быть серверным (соответствовать `server.key`); промежуточные CA можно дописать в конец; корневой CA в `server.crt` не нужен — его должен иметь клиент.
- Ключ с passphrase: сервер запросит его при старте и не запустится без ввода; passphrase отключает перезагрузку SSL-конфигурации через reload, если не настроен `ssl_passphrase_command` + `ssl_passphrase_command_supports_reload = on`; на Windows зашифрованные ключи не поддерживаются.
- Сертификаты и ключи перечитываются при старте и при reload. Ошибка при старте — сервер откажется запускаться; ошибка при reload — старая SSL-конфигурация продолжит работать, ошибка попадёт в лог.
- Самоподписанные сертификаты — только для тестов; в production — сертификат от CA (корпоративного или публичного).

Самоподписанный сертификат на 365 дней:

```bash
openssl req -new -x509 -days 365 -nodes -text -out server.crt \
  -keyout server.key -subj "/CN=dbhost.example.com"
chmod og-rwx server.key
```

Дополнительные параметры: `ssl_ca_file` (доверенные CA для проверки клиентских сертификатов), `ssl_crl_file` / `ssl_crl_dir` (списки отзыва; каталог готовится `openssl rehash`, CRL подгружаются по требованию), `ssl_dh_params_file` (`openssl dhparam -out dhparams.pem 2048`), `ssl_tls13_ciphers` (для TLS 1.3), `ssl_passphrase_command`.

#### Принудительный SSL для пользователей (`pg_hba.conf`)

Записи `hostssl` матчатся только для TLS-подключений, `hostnossl` — только для нешифрованных (для GSSAPI-шифрования есть `hostgssenc`/`hostnogssenc`). Запись `hostssl` без включённого `ssl` игнорируется с предупреждением в логе.

```ini
# TYPE  DATABASE  USER  ADDRESS      METHOD        OPTIONS
hostssl all       all   10.0.0.0/8   scram-sha-256  clientcert=verify-full
host    all       all   0.0.0.0/0    reject
```

Опция `clientcert=verify-ca|verify-full` доступна для любой записи `hostssl` и требует от клиента доверенный сертификат (`verify-full` дополнительно проверяет совпадение CN с именем роли или маппингом; выбор поля — `clientname=CN|DN`, дефолт `CN`). Метод `cert` использует сертификат как сам способ аутентификации (цепочка проверяется всегда).

#### Проверка на стороне клиента (`sslmode`)

| `sslmode` | Защита от прослушки | Защита от MITM | Суть |
| :--- | :--- | :--- | :--- |
| `disable` | Нет | Нет | Без шифрования |
| `allow` | Возможно | Нет | Шифрование, только если сервер настаивает |
| `prefer` (дефолт) | Возможно | Нет | Шифрование, если сервер поддерживает; дефолт оставлен для совместимости и **не рекомендуется** |
| `require` | Да | Нет | Шифрование обязательно; доверие сети (CA не проверяется) |
| `verify-ca` | Да | Зависит от политики CA | Проверяется цепочка до корневого CA клиента |
| `verify-full` | Да | Да | Плюс проверка имени хоста по SAN (`dNSName`) или CN — рекомендуется для чувствительных сред |

Важные нюансы клиента:

- Корневые CA клиента лежат в `~/.postgresql/root.crt` (Windows: `%APPDATA%\postgresql\root.crt`), CRL — в `~/.postgresql/root.crl`; клиентские сертификаты — `~/.postgresql/postgresql.crt` и `postgresql.key` (ключ с правами `0600`).
- `verify-full` матчит IP-адрес по SAN типа `iPAddress`/`dNSName` без DNS-запросов; wildcard `*` в SAN матчит всё, кроме точки (поддомены не покрываются).
- Для обратной совместимости: если `root.crt` существует, `sslmode=require` ведёт себя как `verify-ca` — полагаться на это не следует, приложения должны указывать `verify-ca`/`verify-full` явно.

#### Валидация

```sql
SHOW ssl;                                 -- → on
SELECT pid, ssl, version, cipher, bits, compression, client_dn
FROM pg_stat_ssl WHERE pid = pg_backend_pid();
-- → pid | ssl | version | cipher | bits | compression | client_dn
-- → 12345 | t   | TLSv1.3 | TLS_AES_256_GCM_SHA384 | 256 | f | (NULL)
```

`pg_stat_ssl` содержит по строке на подключение (включая репликационные): `pid`, `ssl`, `version`, `cipher`, `bits`, `compression`, `client_dn`, `client_serial`, `issuer_dn`. Сведения о сертификате текущего клиента даёт также расширение `sslinfo` (`ssl_is_used()`, `ssl_version()`, `ssl_cipher()`, `ssl_client_dn()`).

### Ротация сертификатов (bare-metal / VM)

Сертификаты и ключи перечитываются при старте и при reload (`SIGHUP` / `pg_reload_conf()`), поэтому ротация в production выполняется без перезапуска кластера — при условии, что ключ не защищён passphrase (passphrase отключает reload; см. `ssl_passphrase_command`).

**Процедура (zero-downtime):**

1.  **Подготовить новый сертификат** (от CA, с SAN хоста) и положить рядом со старым, например `/etc/ssl/certs/postgres.crt.new`.
2.  **Атомарная подмена** файлов (переименование в пределах одной файловой системы — атомарно):

    ```bash
    sudo install -m 600 -o postgres -g postgres server.key.new /etc/ssl/private/postgres.key
    sudo install -m 644 server.crt.new /etc/ssl/certs/postgres.crt
    # Права на ключ: группа и прочие не должны читать
    ls -l /etc/ssl/private/postgres.key
    # → -rw------- 1 postgres postgres 1704 ... postgres.key
    ```
3.  **Reload** — сервер перечитывает сертификаты; ошибка при reload не роняет сервер (старая конфигурация продолжает работать, ошибка попадает в лог):

    ```bash
    sudo systemctl reload postgresql
    sudo -u postgres psql -c "SELECT pg_reload_conf();"
    # → t
    ```
4.  **Валидация** — новое подключение должно использовать новый сертификат:

    ```sql
    SELECT pid, ssl, version, cipher FROM pg_stat_ssl
    WHERE pid = pg_backend_pid();
    -- → pid | ssl | version | cipher
    -- → 12345 | t | TLSv1.3 | TLS_AES_256_GCM_SHA384
    ```
    Проверка отпечатка: `openssl x509 -in /etc/ssl/certs/postgres.crt -noout -fingerprint -sha256` сравнить с тем, что видит клиент (`sslinfo`).

**Особенности:**

*   **Существующие соединения** продолжают работать на старом сертификате до переподключения — ротация не обрывает сессии.
*   **Промежуточные CA** можно дописывать в конец `server.crt`; корневой CA в `server.crt` не нужен.
*   **CRL/отзыв**: `ssl_crl_file` / `ssl_crl_dir` подгружаются по требованию; каталог готовится `openssl rehash`.
*   **PgBouncer**: если TLS терминируется на пулере, ротировать сертификаты нужно и на пулере, и на PostgreSQL (клиент→пулер и пулер→сервер — разные сертификаты).
*   **Patroni/Spilo**: сертификаты обычно монтируются из секретов; ротация — обновление секрета + reload на всех узлах (Patroni не перезапускает PostgreSQL сам).
*   **Клиентские сертификаты** (`clientcert=verify-full`): ротация клиентских сертификатов — обновление `~/.postgresql/postgresql.crt` на клиентах; серверный CRL позволяет отозвать старые до истечения.

### 4. Аутентификация: настройка `pg_hba.conf`

Типовой минимальный конфиг для production-кластера:

```ini
# TYPE  DATABASE        USER            ADDRESS          METHOD      OPTIONS
local   all             all                                       peer
host    all             all             127.0.0.1/32     scram-sha-256
hostssl all             all             10.0.0.0/8       scram-sha-256
host    replication     replicator      10.0.0.0/24      scram-sha-256
host    all             all             0.0.0.0/0        reject
```

Применение изменений:

```bash
sudo systemctl reload postgresql     # или: pg_ctl reload / SELECT pg_reload_conf();
sudo -u postgres psql -c "SELECT line_number, type, database, user_name, error FROM pg_hba_file_rules WHERE error IS NOT NULL;"
-- → (0 rows)   — представление pg_hba_file_rules позволяет предпроверить правила до подключения
```

Операционные детали: `pg_hba.conf` читается при старте и по `SIGHUP`; на Windows изменения применяются сразу для новых подключений. Подробнее про расположение файла и reload — в **[Управлении соединениями](../Operations/connection_management.md)**.

### 5. Row-Level Security (RLS)

Сценарий: пользователь видит только свои записи в таблице `orders`.

```sql
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_orders_policy ON orders
    USING (user_id = current_user_id());
```

Ключевая механика (из официальной документации):

- **Владелец таблицы обычно не подпадает под политики** — он видит все строки. Подчинить его политикам: `ALTER TABLE orders FORCE ROW LEVEL SECURITY`.
- Суперпользователи и роли с `BYPASSRLS` обходят RLS всегда.
- При включённом RLS без политик — default-deny (ни одна строка не видна и не может быть изменена).
- `USING (expr)` — какие строки видны; `WITH CHECK (expr)` — какие строки можно вставить/обновить. Если `WITH CHECK` не задан, он неявно равен `USING`.
- Политика может быть на `ALL`/`SELECT`/`INSERT`/`UPDATE`/`DELETE` и для конкретных ролей (`TO role`) или `PUBLIC`. Несколько политик комбинируются через `OR` (permissive, дефолт) или `AND` (restrictive, `AS RESTRICTIVE`).
- Выражения политик вычисляются для каждой строки до условий пользователя (исключение — `leakproof`-функции) с правами запросившего; доступ к данным, недоступным вызывающему, можно дать через security-definer функции.
- `TRUNCATE` и `REFERENCES` не подпадают под RLS; проверки ссылочной целостности (PK/UNIQUE/FK) тоже обходят RLS — возможны скрытые каналы утечки информации через ошибки ограничений.
- Отключение (`DISABLE ROW LEVEL SECURITY`) не удаляет политики — они просто игнорируются.
- Параметр `row_security = off` не отключает RLS, а вызывает ошибку, если результат запроса был бы отфильтрован — полезно для `pg_dump`, чтобы бэкап молча не потерял строки.
- Политики с подзапросами к другим таблицам могут давать состояния гонки в Read Committed (политика читает старую версию связанной строки, пока `FOR UPDATE` ждёт коммита другой транзакции). Митигации: `SELECT ... FOR SHARE` в подзапросах, `ACCESS EXCLUSIVE` на обновляемой связанной таблице, security-definer функция.

Тестирование политик — через `SET ROLE`:

```sql
SET ROLE alice;
SELECT * FROM orders;              -- только строки alice
UPDATE orders SET note = 'x' WHERE user_id = 42;   -- UPDATE 0 (молча, строка чужая)
RESET ROLE;
```

Представления по умолчанию выполняются с правами владельца (security-definer семантика), что обходит RLS вызывающего. С PostgreSQL 15 доступен выбор invoker-семантики:

```sql
CREATE VIEW my_orders WITH (security_invoker = true) AS
    SELECT * FROM orders;
```

### 6. Аудит и логирование

#### Встроенные средства (`postgresql.conf`)

```ini
log_destination = 'stderr'        # или csvlog, jsonlog, syslog (eventlog на Windows)
log_connections = 'all'           # в 18 — строка: receipt, authentication, authorization,
                                  # setup_durations, all; в ≤17 — boolean on/off
log_disconnections = on           # дефолт off; логирует завершение сессий с длительностью
log_statement = 'ddl'             # none | ddl | mod | all; дефолт none
log_line_prefix = '%m [%p] %u@%d/%a '
log_hostname = off                # on — имена хостов вместо IP (штраф на резолвинг)
```

- Неудачная аутентификация логируется всегда, независимо от `log_connections`.
- `log_statement = mod` (DDL + `INSERT`/`UPDATE`/`DELETE`/`TRUNCATE`/`COPY FROM`) или `all` — операторы могут раскрывать чувствительные данные и даже пароли открытым текстом; в production используют точечно, комбинируя с `log_min_error_statement` и `log_min_duration_statement`.
- Файлы логов по умолчанию `0600` (только владелец сервера); `log_file_mode = 0640` — для группы; world-readable логи недопустимы (содержат чувствительные данные).
- `csvlog`/`jsonlog` требуют `logging_collector = on`; CSV-логи можно загружать в таблицу через `COPY ... WITH csv`.
- psql при определении необходимости пароля подключается дважды — дублирующиеся «connection received» не всегда означают проблему.

#### pgAudit (расширение)

Детальное сессионное и объектное аудит-логирование для compliance (PCI DSS, ISO, госструктуры):

```ini
# postgresql.conf
shared_preload_libraries = 'pgaudit'   # обязательно, требует перезапуска
pgaudit.log = 'write, ddl'             # классы: READ, WRITE, FUNCTION, ROLE, DDL,
                                       # MISC, MISC_SET, ALL (можно вычитать: 'all, -misc')
pgaudit.log_relation = on              # отдельная запись на каждую таблицу в SELECT/DML
```

```sql
CREATE EXTENSION pgaudit;              # до установки pgaudit.log; ставит event triggers для DDL
```

Пример вывода:

```
AUDIT: SESSION,33,2,DDL,CREATE TABLE,TABLE,public.important_table,CREATE TABLE important_table (id INT);,<not logged>
```

Объектный аудит: `pgaudit.role = 'auditor'` + `GRANT` привилегий на таблицы роли `auditor` — логируются только затрагивающие эти таблицы операторы. Ограничения: аудит best-effort и не транзакционен (запись может потеряться при сбое до flush или попасть в лог при откате транзакции); autovacuum не логируется; надёжно аудировать суперпользователя нельзя (решение — доступ к суперпользователю строго ограничен, эскалация через расширение `set_user`); настройки может менять только суперпользователь и они не наследуются через `SET ROLE`. Перед удалением расширения параметр `pgaudit.log` нужно сбросить.

### 7. Защита от спуфинга сервера

По умолчанию клиент **не проверяет** сертификат сервера — подмена DNS-записи или перехват IP позволяют MITM без ведома клиента. Защита:

- `sslmode=verify-full` (или `verify-ca`) + корневой CA на клиенте (`~/.postgresql/root.crt`) — единственный способ убедиться в подлинности сервера; `require` без CA от MITM не защищает.
- Только записи `hostssl` в `pg_hba.conf` — нешифрованные подключения не проходят аутентификацию.
- Взаимная аутентификация сертификатами (`cert` / `clientcert=verify-full`) предотвращает выдачу себя за авторизованного клиента.
- Альтернативы: GSSAPI-шифрование (`hostgssenc`) или туннель через stunnel/SSH.

## Сравнение методов защиты данных

| Метод | Уровень | Прозрачность | Защита от админа БД |
| :--- | :--- | :--- | :--- |
| **LUKS / ZFS / dm-crypt** | Диск (раздел) | Высокая | Нет (при смонтированной ФС) |
| **pg_tde (Percona)** | Таблица (`tde_heap`) | Высокая | Частично (защищает файлы, но не от SQL-запросов привилегированных ролей) |
| **pgcrypto** | Столбец | Низкая (SQL) | Частично (кроме скомпрометированного суперпользователя/ОС — ключи и данные кратковременно в памяти сервера) |
| **RLS** | Строка | Средняя | Нет (суперпользователь и `BYPASSRLS` обходят) |

## Поиск и устранение неисправностей

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `FATAL: no pg_hba.conf entry for host "...", user "...", database "...", SSL on` | Ни одна запись не подходит (тип, адрес, база, роль) | Добавить нужную строку (`host`/`hostssl`); для репликации — `host replication ...`; reload |
| `password authentication failed for user "..."` | Формат хэша в `pg_authid` не совместим с методом (md5-хэш при методе `scram-sha-256`) | Сбросить пароль (`\password`), проверить `password_encryption` |
| `connection requires a valid client certificate` | В `hostssl`-записи `clientcert=verify-ca/verify-full`, клиент без сертификата | Настроить `~/.postgresql/postgresql.crt` + `postgresql.key` (`0600`) |
| `hostssl`-запись игнорируется, в логе warning | `ssl = off` или сборка без OpenSSL | Включить `ssl`, задать `ssl_cert_file`/`ssl_key_file`, reload |
| `SSL error: certificate verify failed` / `hostname mismatch` | Нет или просрочен `root.crt` на клиенте; CN/SAN ≠ имя хоста | Установить CA; `verify-full` требует точного совпадения имени хоста |
| Изменения `pg_hba.conf` не применяются | Конфиг перечитывается только по `SIGHUP` | `systemctl reload postgresql` / `pg_reload_conf()`; проверить `pg_hba_file_rules` (поле `error`) |
| Сервер не стартует после замены сертификатов | Права на `server.key` свободнее `0600`/`0640`, или passphrase без `ssl_passphrase_command` | Исправить права (`chmod 0600`), настроить команду получения passphrase |
| RLS «молча» скрывает строки у владельца таблицы | Владелец не подпадает под политики | `ALTER TABLE ... FORCE ROW LEVEL SECURITY`; тестировать через `SET ROLE` |
| `ERROR: permission denied for table` при включённом RLS | RLS включён, но нет ни одной политики (default-deny) | Создать политику (`CREATE POLICY ... USING (true)` для отладки) |
| В логах нет записей о подключениях | `log_connections` выключен (дефолт) | `log_connections = 'all'` (18) / `on` (≤17) |
| `CREATE TABLE ... USING pg_tde` не работает | Расширение не установлено или не Percona Server 17/18 | `CREATE EXTENSION pg_tde` от суперпользователя; проверить сборку сервера |

## Лучшие практики

- **Принцип наименьших привилегий:** отдельные роли для приложения, миграций и бэкапов; приложение — без `SUPERUSER`/`CREATEDB`/`CREATEROLE`; `CONNECTION LIMIT` для сервисных ролей.
- `scram-sha-256` обязателен для production; `trust`/`peer` — только локально; `password` — только внутри SSL; `md5` — только для старых клиентов на время миграции.
- `hostssl` + `sslmode=verify-full` для удалённых подключений; `clientcert=verify-full` (mTLS) для машинных аккаунтов.
- `listen_addresses` — только нужные интерфейсы; `unix_socket_permissions` `0770`/`0700` при групповом доступе к сокету.
- `log_connections`, `log_disconnections`, `log_line_prefix` с `%u %d [%p]`; аудит DDL/ROLE через pgAudit (`pgaudit.log = 'ddl, role'`).
- Ротация ключей (DEK/KEK) и хранение KEK вне сервера БД — по SSoT **[Шифрование данных «в покое»](../../Concepts/encryption_at_rest.md)**; резервные копии зашифрованных таблиц требуют того же KEK на DR-площадке.
- Регулярный аудит: `pg_authid` (формат хэшей), `pg_hba.conf` через `pg_hba_file_rules`, права ролей (`pg_roles`, `information_schema.role_table_grants`).
- Не включать `log_statement = all` в production без необходимости — пароли и данные в логах; RLS: `FORCE ROW LEVEL SECURITY` для владельца, `security_invoker`-представления (PG 15+) вместо security-definer.
- Бэкапы: `pg_dump` с `row_security = off` (ошибка вместо молчаливого пропуска строк).

## Очистка и откат изменений

```bash
# Применение/откат конфигурации
sudo systemctl reload postgresql        # pg_hba.conf, postgresql.conf (reloadable-параметры)
sudo systemctl restart postgresql       # shared_preload_libraries (pgAudit), listen_addresses
```

```sql
-- Отключить RLS (политики сохраняются, но игнорируются)
ALTER TABLE orders DISABLE ROW LEVEL SECURITY;
DROP POLICY user_orders_policy ON orders;

-- Удалить расширения (перед DROP pgaudit — сбросить pgaudit.log)
ALTER SYSTEM RESET pgaudit.log; SELECT pg_reload_conf();
DROP EXTENSION pgaudit;
DROP EXTENSION pgcrypto;

-- Отключить TLS для новых подключений
ALTER SYSTEM SET ssl = off; SELECT pg_reload_conf();

-- Убрать пароль роли (password-аутентификация станет невозможной)
ALTER ROLE app_user PASSWORD NULL;
```

## Вопросы на собеседованиях

1. Чем `hostssl` отличается от `host` и что произойдёт с существующими подключениями после reload `pg_hba.conf`?
2. Почему первая подходящая запись `pg_hba.conf` важнее всех остальных, и что значит «no fall-through»?
3. Чем `verify-ca` отличается от `verify-full` и когда `verify-full` обязателен?
4. Почему `md5` deprecated, и какие шаги безопасной миграции на SCRAM без даунтайма клиентов?
5. Почему RLS не применяется к владельцу таблицы, и как это изменить? Что не подпадает под RLS вообще?
6. Почему `pgcrypto` не защищает от суперпользователя, и что защищает?
7. Что не шифрует `pg_tde`, и чем он отличается от LUKS по границам защиты?
8. Как аудировать DDL без `log_statement = all`, и какие риски несёт полное логирование операторов?

## Дополнительная информация

### Смежные темы
- **[pgcrypto: Криптография в PostgreSQL](./pgcrypto.md)** — детальное руководство по столбцовому шифрованию.
- **[Шифрование данных «в покое» (SSoT)](../../Concepts/encryption_at_rest.md)** — DEK/KEK, envelope encryption, ротация ключей, KMS/HSM.
- **[Управление соединениями](../Operations/connection_management.md)** — `pg_hba.conf`, таймауты, пулинг.
- **[Trusted-расширения](./extensions_utility.md)** — почему `pgcrypto` ставится без суперпользователя.
- **[Безопасность MariaDB](../../MariaDB/security/index.md)** и **[Безопасность MySQL](../../MySQL/security.md)** — реализация TDE и keyring в других СУБД.
- **[Официальная документация: pgcrypto](https://www.postgresql.org/docs/current/pgcrypto.html)**, **[pgAudit](https://github.com/pgaudit/pgaudit)**, **[pg_tde (Percona)](https://docs.percona.com/pg-tde/)**.

### Официальная документация PostgreSQL 18
- [Client Authentication (глава)](https://www.postgresql.org/docs/current/client-authentication.html)
- [The `pg_hba.conf` File](https://www.postgresql.org/docs/current/auth-pg-hba-conf.html)
- [Password Authentication](https://www.postgresql.org/docs/current/auth-password.html)
- [Encryption Options](https://www.postgresql.org/docs/current/encryption-options.html)
- [Secure TCP/IP Connections with SSL](https://www.postgresql.org/docs/current/ssl-tcp.html)
- [libpq — SSL Support (`sslmode`)](https://www.postgresql.org/docs/current/libpq-ssl.html)
- [Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [Role Attributes](https://www.postgresql.org/docs/current/role-attributes.html)
- [Runtime Config: Connections and Authentication](https://www.postgresql.org/docs/current/runtime-config-connection.html)
- [Runtime Config: Error Reporting and Logging](https://www.postgresql.org/docs/current/runtime-config-logging.html)
