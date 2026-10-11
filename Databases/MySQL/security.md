# Безопасность MySQL: TDE, TLS, аутентификация и аудит

**Актуально для:** MySQL 8.0.x / 8.4 LTS

## Определения

**Transparent Data Encryption (TDE)** — технология прозрачного шифрования данных на диске. В MySQL шифруются табличные пространства InnoDB, бинарные логи и логи транзакций. Процесс полностью прозрачен для SQL-запросов и не требует изменения кода приложения.

**Keyring Plugin / Keyring Component** — компонент MySQL, отвечающий за управление мастер-ключами (KEK). Обеспечивает взаимодействие между сервером БД и хранилищем ключей. Начиная с MySQL 8.0.24 происходит миграция с плагинов на компоненты: плагины `keyring_file`, `keyring_encrypted_file` и `keyring_oci` удалены в 8.4, их заменили `component_keyring_file`, `component_keyring_encrypted_file` и `component_keyring_oci`.

**DEK (Data Encryption Key)** — ключ шифрования данных: уникальный ключ каждого табличного пространства, которым непосредственно шифруются страницы InnoDB. Хранится в заголовке табличного пространства только в зашифрованном виде («обернутым» мастер-ключом).

**KEK (Key Encryption Key, Master Key)** — мастер-ключ, которым «оборачиваются» DEK. Никогда не хранится на диске сервера БД — находится во внешнем keyring-хранилище.

**MySQL Audit Log Plugin** — инструмент для мониторинга и протоколирования всех действий пользователей (входы, запросы, доступ к объектам). Критичен для комплаенса (PCI DSS, SOC2). В Oracle MySQL доступен в Enterprise Edition; в Percona Server — бесплатно.

**caching_sha2_password** — плагин аутентификации по умолчанию в MySQL 8.x/9.x, использующий SHA-256 для хеширования паролей и RSA-шифрование для их безопасной передачи по сети.

**mTLS (mutual TLS)** — режим TLS со взаимной аутентификацией: клиент предъявляет собственный сертификат, проверяемый сервером (`REQUIRE X509`). Защищает от кражи учетных данных и позволяет привязать доступ к конкретному хосту.

**validate_password Component** — компонент проверки сложности паролей (уровни LOW/MEDIUM/STRONG). Заменил одноименный плагин, который объявлен устаревшим; при установке из пакетов Oracle в 8.4 компонент включается по умолчанию.

**Connection Control** — плагин (доступен в Community), добавляющий нарастающую задержку ответа после серии неудачных попыток входа. Замедляет brute-force-атаки без блокировки легитимных пользователей.

## Основные концепции

### Двухуровневая иерархия ключей TDE

InnoDB использует схему DEK/KEK:

1. Каждое зашифрованное табличное пространство имеет собственный **ключ таблицы (DEK)** — им шифруются страницы данных (алгоритм AES, по умолчанию `block_encryption_mode = aes-256-cbc`).
2. DEK хранится в заголовке табличного пространства в зашифрованном виде — «обернутым» **мастер-ключом (KEK)**.
3. Мастер-ключ запрашивается у keyring-хранилища при старте сервера и никогда не попадает на диск в открытом виде.
4. Ротация мастер-ключа перешифровывает только обертку DEK (быстрая операция), сами данные не перезаписываются.

Под действие TDE попадают: файлы `.ibd` (включая general tablespaces), redo-логи (`innodb_redo_log_encrypt`), undo-табличные пространства (`innodb_undo_log_encrypt`), бинарные логи и relay-логи реплик (`binlog_encryption`), временные табличные пространства (шифруются автоматически при активном keyring, начиная с 8.0.13).

TDE **не защищает**: error log, slow/general query log (могут содержать данные из запросов), audit.log, конфигурационные файлы, core dumps (отключайте `core_file`) и swap (отключайте или шифруйте на уровне ОС). Пароли в записях аудита маскируются автоматически.

Критическое следствие схемы DEK/KEK: **потеря доступа к keyring-хранилищу = потеря всех данных**. Резервная копия ключей должна храниться отдельно от бэкапов данных: если атакующий получит и то, и другое, шифрование теряет смысл; если ключи потеряны безвозвратно — данные невосстановимы.

### Эволюция Keyring: плагины против компонентов

| Аспект | Плагины (до 8.4) | Компоненты (8.0.24+, стандарт с 8.4) |
|:-------|:-----------------|:-------------------------------------|
| Загрузка | `early-plugin-load` в `my.cnf` | manifest-файл `mysqld.my` рядом с бинарником mysqld |
| Конфигурация | системные переменные (`keyring_file_data` и т.п.) | отдельный JSON-файл (`component_keyring_file.cnf`) в `plugin_dir` |
| Установка | `INSTALL PLUGIN` / `early-plugin-load` | только через manifest; `INSTALL COMPONENT` для keyring использовать нельзя |
| Статус в 8.4+ | file-based плагины удалены; Enterprise-плагины (`keyring_okv`, `keyring_aws`, `keyring_hashicorp`) сохраняются как legacy | рекомендуемый путь |

Причина ранней загрузки (`early-plugin-load` / manifest): keyring должен быть инициализирован **до** инициализации InnoDB, иначе зашифрованные табличные пространства не будут открыты. Компоненты, зарегистрированные через `INSTALL COMPONENT`, загружаются из таблицы `mysql.component` (InnoDB) уже после инициализации InnoDB — поэтому они непригодны для TDE.

### Защита данных при передаче (TLS/mTLS)

MySQL поддерживает TLSv1.2 и TLSv1.3 (TLSv1.3 — начиная с 8.0.28 при сборке с OpenSSL 1.1.1+). Режимы клиента `--ssl-mode`: `DISABLED`, `PREFERRED` (по умолчанию), `REQUIRED` (шифрование без проверки сертификата), `VERIFY_CA` (+ проверка CA), `VERIFY_IDENTITY` (+ проверка имени хоста). Для production-доступа извне целевой режим — `VERIFY_IDENTITY`.

При первом старте сервер генерирует самоподписанные сертификаты и RSA-ключи (`auto_generate_certs`, `caching_sha2_password_auto_generate_rsa_keys` — включены по умолчанию). Это удобно для разработки, но самоподписанный CA непригоден для строгой проверки подлинности: в production используйте собственный PKI.

### Аутентификация: эволюция плагинов

- `mysql_native_password` (SHA-1): объявлен устаревшим в 8.0.34, **отключен по умолчанию в 8.4**, **удален в 9.0**. Включение в 8.4 — только как временная мера совместимости (`mysql_native_password=ON`).
- `caching_sha2_password`: быстрый путь — сравнение scramble по кэшу; полный путь (первый вход, смена пароля, сброс кэша) требует защищенного канала — TLS либо RSA-обмен с серверными ключами.
- `default_authentication_plugin` удален в 8.4; управление политикой — через `authentication_policy`.
- Внешние плагины (LDAP, PAM) доступны в Enterprise Edition; с 8.0.27 поддерживается многофакторная аутентификация (до трех факторов в одном аккаунте).

### Аудит

Плагин аудита встраивается в поток обработки соединений и пишет события (подключения, запросы, результаты) синхронно или асинхронно (`audit_log_strategy`). Форматы: OLD/NEW (XML), JSON, CSV. Фильтрация (какие пользователи и какие классы событий логируются) настраивается через SQL-API фильтров. Логи аудита — чувствительный источник: направляйте их в централизованное хранилище (например, Vector → Loki/SIEM) и ограничивайте права на чтение.

## Практические сценарии

### Предварительные требования

- ОС Linux, MySQL **8.4 LTS** (основной ориентир; отличия для 8.0.x и 9.x помечены явно).
- Доступ root/sudo, права администратора MySQL (`CONNECTION_ADMIN`, `SYSTEM_VARIABLES_ADMIN` или root).
- Для Enterprise-фич (audit_log Oracle, keyring_hashicorp/keyring_okv) — соответствующая лицензия; бесплатные альтернативы — Percona Server (аудит, keyring_vault) и Community-компоненты.
- Утилиты: `openssl`, `jq`. Доступ к error log (`/var/log/mysql/error.log` или `<datadir>/*.err`).

---

### 1. Настройка шифрования данных (TDE)

#### Вариант А: component_keyring_file (Community, актуально для 8.4 LTS)

Компонент загружается через manifest, а не через `my.cnf`.

Шаг 1. Создайте каталог для файла состояния ключей:

```bash
sudo mkdir -p /var/lib/mysql-keyring
sudo chown mysql:mysql /var/lib/mysql-keyring
sudo chmod 750 /var/lib/mysql-keyring
```

Шаг 2. Создайте глобальный manifest `mysqld.my` в каталоге бинарника mysqld (узнать его: `which mysqld`; для пакетных установок это обычно `/usr/sbin/mysqld.my`):

```json
{
  "components": "file://component_keyring_file"
}
```

Шаг 3. Создайте конфигурацию компонента `component_keyring_file.cnf` в каталоге плагинов (узнать: `SHOW VARIABLES LIKE 'plugin_dir';`):

```json
{
  "path": "/var/lib/mysql-keyring/component_keyring_file",
  "read_only": false
}
```

Пояснения: `path` — файл состояния keyring (создается автоматически); `read_only: true` запрещает создание новых ключей (используется для DR-копий сервера). Права на файл состояния после первого старта стоит ограничить: `chmod 640`, владелец `mysql:mysql`.

Шаг 4. Перезапустите сервер и проверьте загрузку:

```sql
SELECT * FROM performance_schema.keyring_component_status;
-- → COMPONENT_NAME: component_keyring_file, COMPONENT_STATUS: Active
```

Если статус `Disabled` или сервер не стартовал — см. раздел «Типичные ошибки и диагностика».

#### Вариант А (legacy): Keyring File Plugin — только для MySQL 8.0.x–8.3.x

В версиях до 8.4 использовался плагин; в 8.4 он удален, приведено для сопровождения старых инсталляций:

```ini
# В my.cnf
[mysqld]
early-plugin-load = keyring_file.so
keyring_file_data = /var/lib/mysql-keyring/keyring
```

Миграция с плагина на компонент выполняется утилитой `mysql_migrate_keyring` (переносит ключи между хранилищами без простоя шифрования):

```bash
mysql_migrate_keyring --component-dir=/usr/lib/mysql/plugin \
  --source-keyring=component_keyring_file \
  --destination-keyring=component_keyring_encrypted_file
# → ключи скопированы в новое хранилище
```

#### Вариант Б: внешнее keyring-хранилище (Enterprise/Production)

Для централизованного управления ключами используется HashiCorp Vault. Реализация зависит от дистрибутива:

**Oracle MySQL Enterprise Edition** — плагин/компонент `keyring_hashicorp`:

```ini
[mysqld]
early-plugin-load = keyring_hashicorp.so
keyring_hashicorp_server_url = https://vault.internal:8200
keyring_hashicorp_mount_path = mysql-kms/
keyring_hashicorp_ca_file    = /etc/mysql/tls/vault-ca.pem
keyring_hashicorp_auth_path  = /auth/approle/login
keyring_hashicorp_role_id    = <ROLE_ID>
keyring_hashicorp_secret_id  = <SECRET_ID>
```

**Percona Server for MySQL** — бесплатный плагин `keyring_vault`:

```ini
[mysqld]
early-plugin-load = keyring_vault.so
keyring_vault_config = /etc/mysql/keyring_vault.conf
```

В обоих случаях сервер выступает AppRole-клиентом Vault: секреты подключения храните с правами `600` и обновляйте по расписанию TTL.

#### Активация шифрования таблиц

После настройки keyring шифрование можно включить для всей базы или конкретных таблиц.

```sql
-- Глобальное шифрование для новых таблиц
SET GLOBAL default_table_encryption = ON;

-- Шифрование существующей таблицы
ALTER TABLE sensitive_data ENCRYPTION = 'Y';

-- Шифрование системных таблиц и логов (SRE-рекомендация)
SET GLOBAL innodb_redo_log_encrypt = ON;
SET GLOBAL innodb_undo_log_encrypt = ON;
SET GLOBAL binlog_encryption = ON;
```

Дополнительно можно задавать шифрование по умолчанию на уровне схемы: `CREATE DATABASE app_db DEFAULT ENCRYPTION = 'Y';` — тогда все новые таблицы схемы наследуют флаг даже при выключенной глобальной переменной.

Валидация:

```sql
SELECT TABLE_SCHEMA, TABLE_NAME, CREATE_OPTIONS
FROM information_schema.TABLES
WHERE CREATE_OPTIONS LIKE '%ENCRYPTION%';
-- → список зашифрованных таблиц (CREATE_OPTIONS содержит ENCRYPTION='Y')

SELECT SPACE, NAME, ENCRYPTION_SCHEME
FROM information_schema.INNODB_TABLESPACES_ENCRYPTION
WHERE ENCRYPTION_SCHEME > 0;
-- → ENCRYPTION_SCHEME = 1 подтверждает шифрование табличного пространства

SHOW VARIABLES LIKE 'binlog_encryption';
-- → ON
```

#### Ротация мастер-ключей (Key Rotation)

Регулярная смена KEK (Master Key) без перешифрования данных таблиц (меняется только обертка DEK). Операция онлайн и не блокирует нагрузку надолго.

```sql
ALTER INSTANCE ROTATE INNODB MASTER KEY;
-- → Query OK; в error log появятся записи о перепривязке ключей табличных пространств
```

Рекомендации: ротация раз в квартал и внепланово при подозрении на компрометацию; после увольнения персонала с доступом к keyring-хранилищу. Если keyring был временно недоступен, принудительно перечитайте хранилище:

```sql
ALTER INSTANCE RELOAD KEYRING;
```

---

### 2. Управление SSL/TLS соединениями

Защита данных при передаче (In-Transit).

#### Принудительный TLS для всех соединений

```ini
[mysqld]
require_secure_transport = ON
tls_version = TLSv1.2,TLSv1.3
```

Пояснения: `require_secure_transport` отклоняет любые незащищенные подключения (включая X Protocol, порт 33060); `tls_version` исключает устаревшие протоколы. Переменные динамические — применяются без рестарта.

#### Собственные сертификаты вместо автогенерированных

```bash
sudo mkdir -p /etc/mysql/tls && cd /etc/mysql/tls
# CA
openssl genrsa -out ca-key.pem 4096
openssl req -new -x509 -nodes -days 3650 -key ca-key.pem -out ca.pem -subj "/CN=mysql-ca"
# Сертификат сервера (SAN обязателен для VERIFY_IDENTITY)
openssl req -newkey rsa:4096 -nodes -keyout server-key.pem -out server-req.pem -subj "/CN=mysql-node1"
openssl x509 -req -in server-req.pem -CA ca.pem -CAkey ca-key.pem -days 825 \
  -extfile <(printf "subjectAltName=DNS:mysql-node1,IP:10.0.0.5") -CAcreateserial -out server-cert.pem
sudo chown mysql:mysql *.pem && sudo chmod 600 *-key.pem && sudo chmod 644 *.pem
```

```ini
[mysqld]
ssl_ca   = /etc/mysql/tls/ca.pem
ssl_cert = /etc/mysql/tls/server-cert.pem
ssl_key  = /etc/mysql/tls/server-key.pem
```

#### Создание пользователя с обязательным шифрованием

```sql
CREATE USER 'app_user'@'%' IDENTIFIED BY 'password' REQUIRE SSL;
-- Требование mTLS (клиентский сертификат)
ALTER USER 'admin'@'%' REQUIRE X509;
```

Уточнение требований mTLS: `REQUIRE SUBJECT '/CN=app-node1/O=Corp'` фиксирует DN сертификата, `REQUIRE ISSUER '/CN=mysql-ca'` — выпускающий CA, `REQUIRE CIPHER 'TLS_AES_256_GCM_SHA384'` — конкретный шифр. Требования комбинируются: `REQUIRE X509 AND ISSUER '/CN=mysql-ca' AND SUBJECT '/CN=admin-laptop'`.

Подключение клиента с проверкой подлинности сервера:

```bash
mysql --host=mysql-node1 --ssl-mode=VERIFY_IDENTITY \
      --ssl-ca=/etc/mysql/tls/ca.pem \
      --ssl-cert=/etc/mysql/tls/client-cert.pem \
      --ssl-key=/etc/mysql/tls/client-key.pem
```

Валидация активного шифрования внутри сессии:

```bash
mysql --ssl-mode=REQUIRED -e "status"
# → SSL: Cipher in use is TLS_AES_256_GCM_SHA384
```

```sql
SHOW GLOBAL STATUS LIKE 'Ssl_cipher';
-- → Value: TLS_AES_256_GCM_SHA384 (пусто — соединение не зашифровано)
SHOW GLOBAL VARIABLES LIKE 'tls_version';
-- → TLSv1.2,TLSv1.3
```

Замечание о производительности: TLS добавляет оверхед на установку соединения (~1 дополнительный RTT на handshake); для приложений с частыми короткими подключениями используйте пулинг соединений на стороне приложения или ProxySQL.

---

### 3. Настройка аудита (Percona / Oracle Audit Log)

Если используется **Percona Server**, плагин аудита доступен бесплатно. В Oracle MySQL тот же плагин входит в Enterprise Edition.

#### Включение аудита

```sql
INSTALL PLUGIN audit_log SONAME 'audit_log.so';

-- Настройка фильтрации (логировать только DDL и входы)
SET GLOBAL audit_log_policy = 'ALL';
SET GLOBAL audit_log_format = 'JSON';
SET GLOBAL audit_log_rotate_on_size = 104857600; -- 100MB
```

Пояснения параметров: `audit_log_policy` — `ALL` (все события), `LOGINS` (только подключения), `QUERIES` (только запросы), `NONE` (выключить); `audit_log_format` — формат записей, JSON удобен для парсинга Vector/Loki; `audit_log_rotate_on_size` — размер файла ротации в байтах. Для снижения нагрузки на запись выберите асинхронную стратегию: `SET GLOBAL audit_log_strategy = 'ASYNCHRONOUS';`.

Точечная фильтрация (кто и что логировать) настраивается через API фильтров:

```sql
SELECT audit_log_filter_set_filter('log_all', '{"filter": {"log": true}}');
SELECT audit_log_filter_set_user('%', 'log_all');
-- → фильтр log_all назначен всем пользователям
```

### 4. MySQL Enterprise Firewall

Файрвол на уровне SQL-запросов: разрешает только запросы из whitelist'а.
Входит в **MySQL Enterprise Edition** (в Percona / Community нет).

**Установка и включение:**

```sql
INSTALL PLUGIN MYSQL_FIREWALL SONAME 'mysql_firewall.so';
INSTALL PLUGIN MYSQL_FIREWALL_USERS SONAME 'mysql_firewall.so';
INSTALL PLUGIN MYSQL_FIREWALL_WHITELIST SONAME 'mysql_firewall.so';

SET GLOBAL mysql_firewall_mode = 'RECORDING';   -- или PROTECTING / DETECTING / OFF
```

**Режимы:**

| Режим | Поведение |
| :--- | :--- |
| `OFF` | Файрвол выключен |
| `RECORDING` | Записывает разрешённые запросы в whitelist (фаза обучения) |
| `PROTECTING` | Разрешает только whitelist, остальное блокирует |
| `DETECTING` | Разрешает всё, но подозрительное пишет в error log |

**Профили (MySQL 8.0.23+):** можно группировать учётные записи в
group profile — один whitelist на несколько пользователей. До 8.0.23
профиль привязывался к одной учётной записи.

**Привилегии:** `FIREWALL_ADMIN` (управление всеми профилями),
`FIREWALL_USER` (управление своим профилем), `FIREWALL_EXEMPT`
(обход файрвола — для администраторов и приложений с динамическим SQL).

**SRE-заметка:** файрвол ломает приложения, генерирующие уникальные
литералы в каждом запросе — каждый такой запрос попадает в whitelist
отдельно, и он разрастается. Перед переводом в `PROTECTING` обязательно
пройти фазу `RECORDING` на реальной нагрузке.

#### Валидация

Логи сохраняются в `datadir/audit.log`. Проверка через ОС:

```bash
tail -f /var/lib/mysql/audit.log | jq .
# → JSON-записи вида {"class":"general","event":"query",...}
```

Эксплуатационные требования: права на файл — `mysql:mysql`, чтение ограничено группой аудита (`chmod 640`); отправка в SIEM через Vector (см. стек observability); пароли в записях аудита маскируются автоматически, но литералы строк в запросах — нет, поэтому general_log при включенном аудите держите выключенным.

#### Аудит через information_schema (SRE-панель)

Помимо файлового аудита, штатные views позволяют быстро оценить安全 posture без внешних инструментов:

```sql
-- Все пользователи и их плагины аутентификации
SELECT user, host, plugin, account_locked, password_expired
FROM mysql.user
ORDER BY user;

-- Пользователи с доступом извне (не localhost)
SELECT user, host, account_locked
FROM mysql.user
WHERE host NOT IN ('localhost', '127.0.0.1', '::1')
  AND host NOT LIKE '10.%'
  AND host NOT LIKE '192.168.%';

-- Привилегии на уровне схем/таблиц (поиск избыточных GRANT)
SELECT grantee, table_schema, table_name, privilege_type
FROM information_schema.SCHEMA_PRIVILEGES
WHERE grantee NOT LIKE 'mysql.%'
ORDER BY grantee, table_schema;

-- Статус SSL для активных подключений
SELECT user, host, ssl_cipher, tls_version
FROM performance_schema.ssl_account_status
WHERE ssl_cipher IS NOT NULL;

-- Источник подключений по подсетям
SELECT SUBSTRING_INDEX(host, '.', 3) AS subnet, COUNT(*) AS connections
FROM information_schema.PROCESSLIST
GROUP BY subnet
ORDER BY connections DESC;
```

Эти запросы можно интегрировать в Grafana-дашборд или запускать как cron-джобу для периодической проверки baseline.

---

### 4. Жесткая аутентификация и парольная политика

#### Политика сложности паролей (validate_password Component)

```sql
INSTALL COMPONENT 'file://component_validate_password';

SET PERSIST validate_password.policy = STRONG;        -- LOW(0)/MEDIUM(1)/STRONG(2)
SET PERSIST validate_password.length = 14;            -- минимальная длина
SET PERSIST validate_password.mixed_case_count = 1;   -- строчные + заглавные
SET PERSIST validate_password.number_count = 1;       -- цифры
SET PERSIST validate_password.special_char_count = 1; -- спецсимволы

SELECT VALIDATE_PASSWORD_STRENGTH('weak') AS weak,
       VALIDATE_PASSWORD_STRENGTH('Tr0ub4dor&3LongEnough') AS strong;
-- → weak: 25, strong: 100
```

`SET PERSIST` сохраняет значение между рестартами без правки my.cnf (8.0+).

#### Аккаунты: срок действия, история, блокировка

```sql
CREATE USER 'svc_app'@'10.0.%' IDENTIFIED BY 'Str0ng-P@ssw0rd!'
  REQUIRE SSL
  PASSWORD EXPIRE INTERVAL 90 DAY     -- принудительная смена каждые 90 дней
  PASSWORD HISTORY 5                  -- запрет повторов последних 5 паролей
  PASSWORD REUSE INTERVAL 365 DAY     -- запрет повторного использования в течение года
  FAILED_LOGIN_ATTEMPTS 5             -- блокировка после 5 неудачных входов (8.0.19+)
  PASSWORD_LOCK_TIME 2;               -- ...на 2 дня

ALTER USER 'svc_app'@'10.0.%' ACCOUNT LOCK;   -- временная блокировка (например, при отладке)
-- → ERROR 3118 при попытке входа заблокированного пользователя
```

Ограничение `FAILED_LOGIN_ATTEMPTS` действует на уровне аккаунта; общесерверная защита от перебора — connection control:

```sql
INSTALL PLUGIN CONNECTION_CONTROL SONAME 'connection_control.so';
INSTALL PLUGIN CONNECTION_CONTROL_FAILED_LOGIN_ATTEMPTS SONAME 'connection_control_failed_login_attempts.so';

SET GLOBAL connection_control_failed_connections_threshold = 10; -- порог неудач подряд
SET GLOBAL connection_control_min_connection_delay = 2000;       -- стартовая задержка, мс
SET GLOBAL connection_control_max_connection_delay = 3600000;    -- потолок задержки, мс

SHOW GLOBAL STATUS LIKE 'Connection_control_delay_generated';
-- → счетчик срабатываний задержки
```

#### Миграция с mysql_native_password

Перед переходом на 9.x выявите устаревшие аккаунты:

```sql
SELECT user, host, plugin FROM mysql.user
WHERE plugin NOT IN ('caching_sha2_password', 'auth_socket', 'authentication_ldap_sasl');
-- → список аккаунтов на mysql_native_password/sha256_password

ALTER USER 'legacy_app'@'%' IDENTIFIED WITH caching_sha2_password BY 'NewStr0ng-Pass!';
-- → аккаунт переведен на актуальный плагин
```

В 8.4 включение старого плагина — временное решение: `mysql_native_password=ON` в `[mysqld]`; в 9.x опция удалена вместе с плагином. Контроль политики по умолчанию:

```ini
[mysqld]
authentication_policy = caching_sha2_password,,
# первый фактор обязателен и равен caching_sha2_password
```

Многофакторная аутентификация (8.0.27+) — пример с двумя факторами (второй фактор LDAP требует Enterprise Edition):

```sql
CREATE USER 'dba'@'localhost'
  IDENTIFIED WITH caching_sha2_password BY 'FirstFactor-Pass!'
  AND IDENTIFIED WITH authentication_ldap_sasl AS 'uid=dba,ou=people,dc=example,dc=com';
```

Детальное управление ролями и привилегиями вынесено в отдельный файл: [Управление ролями в MySQL](./role_management.md) — RBAC и динамические привилегии.

---

### 5. Сетевая изоляция и сокращение поверхности атаки

Общая конфигурация сервера описана в [Конфигурация my.cnf](./configuration.md); ниже — параметры, критичные для безопасности.

```ini
[mysqld]
bind-address             = 10.0.0.5              # только внутренний интерфейс (127.0.0.1 — для локальных приложений)
skip_name_resolve        = ON                    # не выполнять обратные DNS-запросы: быстрее и исключает подмену через DNS
local_infile             = OFF                   # запрет LOAD DATA LOCAL INFILE: защита от чтения файлов клиента
secure_file_priv         = /var/lib/mysql-files  # изоляция операций FILE (SELECT ... INTO OUTFILE, LOAD_FILE)
admin_address            = 127.0.0.1             # выделенный админ-интерфейс (порт 33062) недоступен извне
```

Принципы разграничения по хостам: избегайте `'user'@'%'` — указывайте подсеть приложения (`'svc_app'@'10.0.%'`) или конкретные узлы; для административного доступа разрешайте только localhost/jump-host. На уровне ОС закройте порт 3306 файрволом (nftables/ufw/security groups) для всех, кроме подсети приложений. Специфику запуска в контейнерах (включая нюансы аутентификации образов MySQL) см. [Запуск MySQL в Docker](./docker.md).

Валидация поверхности атаки:

```sql
SHOW VARIABLES LIKE 'local_infile';        -- → OFF
SHOW VARIABLES LIKE 'secure_file_priv';    -- → /var/lib/mysql-files
SELECT user, host FROM mysql.user WHERE host = '%';
-- → пустой результат или осознанные исключения
```

#### X Protocol (порт 33060) — вторая дверь в тот же сервер

В MySQL 8.0 **X Plugin включён по умолчанию**, поэтому `mysqld` поднимает второй
TCP-порт `33060` рядом с классическим `3306`. Оба порта ведут к **одному и тому же
серверу, тем же учётным записям, схемам и данным** — правила файрвола, написанные
только под `3306`, этот порт обычно не закрывают.

Особенность, которую легко пропустить: **`bind-address` не управляет X Plugin**. У него
собственная привязка.

```ini
[mysqld]
# Если X Protocol не используется — выключить плагин целиком.
# Допустимые значения опции: ON, OFF, FORCE, FORCE_PLUS_PERMANENT
mysqlx                 = OFF

# Если X Protocol нужен (mysqlsh, MySQL Shell, X DevAPI, mysqlsh --mysqlx) —
# ограничить его собственным адресом, а не закрывать.
mysqlx_bind_address    = 127.0.0.1
mysqlx_port            = 33060
```

Отключение выполняется только на старте сервера, тремя эквивалентными способами:

| Способ | Где |
| :--- | :--- |
| `mysqlx = OFF` в конфигурационном файле | `[mysqld]` в `my.cnf` |
| `--mysqlx=0` | Командная строка запуска |
| `--skip-mysqlx` | Командная строка запуска |

Скомпилировать сервер вообще без X Plugin можно только на этапе сборки —
опция CMake `-DWITH_MYSQLX=OFF`.

Валидация — проверять и конфигурацию, и фактически слушающие сокеты:

```sql
SHOW VARIABLES LIKE 'mysqlx%';
-- → Variable_name           | Value
-- → mysqlx_bind_address     | 127.0.0.1
-- → mysqlx_port             | 33060
```

```bash
# Сокет мог остаться в LISTEN даже при mysqlx=OFF в некоторых сборках —
# источник истины здесь, а не переменная
ss -ltnp | grep -E '3306|33060'
# → LISTEN 0 151 127.0.0.1:3306   0.0.0.0:*    users:(("mysqld",pid=1234,fd=30))
# → LISTEN 0 151 127.0.0.1:33060  0.0.0.0:*    users:(("mysqld",pid=1234,fd=31))
```

```bash
# Правило файрвола должно закрывать оба порта
sudo nft list ruleset | grep -E '3306|33060'
# → tcp dport { 3306, 33062 } ip saddr 10.0.0.0/8 accept
```

`require_secure_transport = ON` отклоняет незащищённые подключения **на обоих**
протоколах, поэтому он закрывает X Protocol на уровне TLS, но не ограничивает круг
источников — это задача `mysqlx_bind_address` и файрвола.

> **Практическое правило:** либо выключить X Plugin, либо закрыть `33060` файрволом
> ровно так же, как `3306`, и задать `mysqlx_bind_address`. Третьего варианта нет.
> Подробности о подключении через MySQL Shell и административном интерфейсе на
> `33062` — [Управление соединениями](./connection-management.md).

### 5.2. Защита на уровне ОС и файловой системы

Параметры `my.cnf` не покрывают весь attack surface. SysAdmin-компонент:

```bash
# Файловые права на datadir и ключам
chown -R mysql:mysql /var/lib/mysql
chmod 750 /var/lib/mysql
chmod 600 /etc/mysql/tls/*-key.pem
chmod 644 /etc/mysql/tls/*.pem

# Отключение core dumps (могут содержать KEK в памяти)
echo "core_pattern=|/bin/false" >> /etc/sysctl.conf
echo "fs.suid_dumpable=0" >> /etc/sysctl.conf
sysctl -p

# Шифрование swap на уровне ОС (если TDE не покрывает swap)
cryptsetup open --type plain /dev/sdX swap_crypt
mkswap /dev/mapper/swap_crypt
swapon /dev/mapper/swap_crypt

# SELinux/AppArmor: проверить контекст datadir
ls -Z /var/lib/mysql
# → system_u:object_r:mysqld_db_t:s0 ... (для RHEL)
```

Валидация ОС-безопасности:

```bash
# Ядро: поддержка AES-NI для TDE
grep -o aes /proc/cpuinfo | head -1
# → aes (если поддерживается)

# Открытые файловые дескрипторы mysqld
ls -la /proc/$(pidof mysqld)/fd | wc -l
# → количество; резкий рост может указывать на утечку

# Core dump настроен на отключение
sysctl fs.suid_dumpable
# → 0
```

### 5.3. Шифрование канала репликации

Репликационный канал передает все изменения: без TLS данные реплики доступны в cleartext на сетевом интерфейсе реплики.

```ini
[mysqld]
source_ssl_mode = REQUIRED          # для источника (8.0+)
replica_ssl_mode = REQUIRED         # для реплики (8.0+)
```

Применение к существующей репликации:

```sql
-- На источнике: проверить доступные сертификаты
SHOW VARIABLES LIKE 'have_ssl';
-- → YES

-- На реплике: включить SSL для канала
CHANGE REPLICATION SOURCE TO
  SOURCE_SSL = 1,
  SOURCE_SSL_CA = '/etc/mysql/tls/ca.pem',
  SOURCE_SSL_CERT = '/etc/mysql/tls/client-cert.pem',
  SOURCE_SSL_KEY = '/etc/mysql/tls/client-key.pem',
  SOURCE_SSL_VERIFY_SERVER_CERT = 1;
START REPLICA;
```

Валидация:

```sql
SHOW REPLICA STATUS\G
-- → Source_SSL: Allowed / Active
-- → Replica_SSL_Verify_Server_Cert: Yes
```

Аккаунты для репликации должны иметь минимальные привилегии и привязку к хосту:

```sql
-- На источнике
CREATE USER 'repl'@'10.0.1.%' IDENTIFIED BY 'Repl-Str0ng-Pass!' REQUIRE SSL;
GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO 'repl'@'10.0.1.%';
```

---

### 6. Управление секретами на стороне клиента

Антипаттерны: пароль в общем `my.cnf` (`[client] password=...`), переменная окружения `MYSQL_PWD` (видна в `/proc/<pid>/environ` и выводе `ps`), пароли в коде и CI-логах.

Штатное решение — login-path с обфускацией (AES) в `~/.mylogin.cnf`:

```bash
mysql_config_editor set --login-path=prod --host=10.0.0.5 --user=admin --password
# → пароль запрашивается интерактивно и сохраняется обфусцированным
chmod 600 ~/.mylogin.cnf
mysql --login-path=prod
# → вход без пароля в командной строке и истории shell
```

Для инфраструктурных секретов (KEK-ключи, учетные данные сервисов) используйте Vault: keyring_hashicorp покрывает мастер-ключи TDE (см. сценарий 1), динамические креденшелы для приложений выдаются через Vault Agent. Файлы состояния keyring и `~/.mylogin.cnf` не включайте в бэкапы домашнего каталога и конфигураций.

## Дополнительная информация

### Влияние TDE на производительность
- **CPU:** Оверхед 3-7% при активном AES-NI. Без аппаратного ускорения потери существенно выше — проверьте поддержку: `grep -o aes /proc/cpuinfo | head -1`.
- **I/O:** Увеличивается размер файлов из-за невозможности сжатия зашифрованных страниц (если сжатие не настроено на уровне InnoDB до шифрования). Файловое сжатие поверх TDE бесполезно: случайные данные несжимаемы; используйте InnoDB page compression или компрессию до записи.
- Перед включением шифрования на нагруженной системе измерьте базовую производительность (sysbench) и сравните после включения — эффект зависит от профиля нагрузки (read-heavy страдает меньше, чем write-heavy с активным redo).

### Edge cases и ограничения
- **Перенос датафайлов на другой сервер** (физическая копия `.ibd`, клонирование тома) требует идентичного keyring-хранилища: без мастер-ключа табличные пространства не откроются (`ERROR 3185`).
- **Даунгрейд** с включенным `binlog_encryption` на версию без поддержки шифрования binlog невозможен — сначала выключите переменную и дождитесь ротации логов.
- **XtraBackup:** шифруйте резервные копии (`xtrabackup --encrypt=AES256 --encrypt-key-file=...`); ключи keyring в бэкап данных не входят и не должны — храните их в отдельном контуре.
- **Экспорт/импорт табличных пространств** (`FLUSH TABLES ... FOR EXPORT`) между инстансами работает только при одинаковом keyring-бэкенде.
- **Репликация:** источник и реплики должны иметь доступ к одному классу keyring-хранилища; канал репликации также переводите на TLS (`CHANGE REPLICATION SOURCE TO SOURCE_SSL=1`).

### Типичные ошибки и диагностика

| Симптом | Причина | Диагностика и решение |
|:--------|:--------|:----------------------|
| `ERROR 3159 (HY000): Connections using insecure transport are prohibited` | Клиент подключился без TLS при `require_secure_transport=ON` | Подключаться с `--ssl-mode=REQUIRED` (или выше); проверить `SHOW STATUS LIKE 'Ssl_cipher'` |
| `ERROR 2061 (HY000): Authentication requires secure connection` | Полный цикл `caching_sha2_password` без TLS и без RSA-канала | Использовать TLS либо `--get-server-public-key`; убедиться, что RSA-ключи сервера сгенерированы |
| `ERROR 1524 (HY000): Plugin 'mysql_native_password' is not loaded` | Аккаунт на удаленном/отключенном плагине (8.4/9.x) | Найти аккаунты запросом из сценария 4, выполнить `ALTER USER ... IDENTIFIED WITH caching_sha2_password` |
| `ERROR 3185 (HY000): Can't find master key from keyring` | Keyring недоступен или отсутствует нужный мастер-ключ (перенос данных, смена хранилища) | Проверить error log; восстановить доступ к хранилищу; `ALTER INSTANCE RELOAD KEYRING` |
| Сервер не стартует после настройки keyring-компонента; в логе `Failed to initialize keyring` | Невалидный JSON манифеста/конфига, неверный путь, права на файл состояния | Валидировать JSON (`jq . mysqld.my`); проверить пути относительно `plugin_dir`; `chown mysql:mysql` на файл состояния |
| `Component_status = Disabled` в `performance_schema.keyring_component_status` | Компонент загрузился, но не инициализировался (конфигурация) | Исправить конфиг согласно error log; перезапуск сервера обязателен |
| `ERROR 1045` при mTLS-подключении с валидным сертификатом | Не совпадает DN с `REQUIRE SUBJECT`/`REQUIRE ISSUER` | Сравнить точные строки: `openssl x509 -in client-cert.pem -noout -subject -issuer`; порядок полей DN значим |
| `SSL connection error: protocol version mismatch` | Старый клиент/коннектор без TLSv1.2+ | Обновить коннектор; временно расширить `tls_version` осознанно, зафиксировав риск |
| `audit.log` не создается или пуст | `audit_log_policy=NONE`, нет прав на запись, SELinux/AppArmor блокирует | `SELECT @@audit_log_policy;`; проверить права datadir и контекст SELinux (`ls -Z`) |

### Best Practices

1.  **Baseline before hardening:** Сначала снимите baseline: текущие аккаунты, статус SSL, покрытие шифрования. Используйте запросы `information_schema` из раздела 4.
2.  **Least privilege:** Минимально возможные привилегии. Используйте роли вместо прямых `GRANT`. Никаких `ALL PRIVILEGES` для сервисных аккаунтов. Детали: **[Управление ролями в MySQL](./role_management.md)**.
3.  **Defense in depth:** Комбинируйте TDE (на диске), TLS (при передаче), политику аутентификации (доступ) и аудит (видимость). Ни один отдельный контроль не достаточен.
4.  **Key separation:** Храните файл состояния keyring вне `datadir` и вне бэкапов данных. DR-копию ключей — в отдельном контуре безопасности. Ротация KEK — ежеквартально и после изменений в команде.
5.  **Certificate hygiene:** Собственный CA с SAN. `tls_version = TLSv1.2,TLSv1.3`. Мониторинг срока действия сертификатов и автоматическое продление до истечения.
6.  **Audit with purpose:** Начните с политики `LOGINS`, расширяйте до `ALL` на период комплаенса. Ротация логов по размеру и времени. Доставка в SIEM — в течение минут, а не часов.
7.  **OS hardening:** Отключите core dumps (`fs.suid_dumpable=0`), шифруйте swap, SELinux/AppArmor — в режиме enforcing. Права на `datadir`: `mysql:mysql 750`.
8.  **Network segmentation:** `bind-address` только на внутренний интерфейс. `skip_name_resolve=ON`. Файрвол по allow-list для подсетей приложений. Админ-доступ — только localhost/jump host.
9.  **Secret management:** Никаких паролей в `my.cnf`, переменных окружения или коде. `mysql_config_editor` для интерактивных клиентов, Vault для инфраструктурных секретов.
10. **Validate everything:** После каждого изменения запускайте валидационные запросы и `SHOW VARIABLES`. Документируйте исключения и получайте их одобрение.

---

### Чек-лист безопасности MySQL

1. **Транспорт:** `require_secure_transport=ON`, TLSv1.2+, для внешних клиентов `VERIFY_IDENTITY` с собственным CA.
2. **Хранение:** TDE для таблиц с PII, шифрование redo/undo/binlog, ротация мастер-ключа ежеквартально.
3. **Ключи:** keyring-компонент (актуальная архитектура), файл состояния вне бэкапов данных, DR-копия ключей в отдельном контуре.
4. **Аутентификация:** `caching_sha2_password` везде, `validate_password` STRONG, `FAILED_LOGIN_ATTEMPTS` на сервисных аккаунтах, `mysql_native_password` отключен.
5. **Привилегии:** минимальные GRANT, роли вместо прямых привилегий, никаких `ALL PRIVILEGES` у сервисных учетных записей.
6. **Сеть:** `bind-address` на внутренний интерфейс, `skip_name_resolve`, `local_infile=OFF`, `secure_file_priv`, файрвол вокруг 3306.
7. **Аудит:** `audit_log` в JSON, ротация, доставка в SIEM (Vector), права на лог ограничены.
8. **Секреты:** `mysql_config_editor`/Vault, ноль паролей в общих конфигах и окружении.

### См. также
- **[Теория шифрования в покое](../Concepts/encryption_at_rest.md)** — общие принципы DEK/KEK.
- **[Безопасность MariaDB](../MariaDB/security/index.md)** — реализация TDE и аудита в MariaDB.
- **[Управление ролями в MySQL](./role_management.md)** — RBAC и динамические привилегии.
- **[Конфигурация MySQL](./configuration.md)** — общие параметры `my.cnf`, включая `require_secure_transport`.
- **[Безопасность репликационного пользователя и SSL](./replication/setup.md)** — привилегии репликационной учётной записи и TLS-канал репликации.
- **[Резервное копирование и восстановление](./backup_and_recovery/overview.md)** — шифрование бэкапов и управление ключами при восстановлении.
- **[Запуск MySQL в Docker](./docker.md)** — особенности безопасности контейнерных развертываний.
