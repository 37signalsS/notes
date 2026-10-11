# ProxySQL: Безопасность

**Актуально для:** ProxySQL 3.0.x

## Определения

| Термин | Значение |
| :--- | :--- |
| **Audit Log** | Журнал событий подключения к ProxySQL в формате JSON; появился в версии 2.0.5 |
| **`mysql-auditlog_filename`** | Переменная, задающая базовое имя файла аудит-лога; её установка включает механизм |
| **Admin Interface** | Интерфейс управления ProxySQL на порту `6032` |
| **`admin-admin_credentials`** | Учётные данные администратора admin-интерфейса |
| **`admin-stats_credentials`** | Учётные данные пользователя только для чтения |
| **Hostgroup** | Логическая группа бэкендов |
| **`use_ssl`** | Параметр пользователя в `mysql_users`: требовать TLS к бэкенду |
| **`mysql-interfaces`** | Адреса и порты, на которых ProxySQL принимает клиентские подключения |
| **`mysql-have_ssl`** | Включает TLS на фронтенде (Client → ProxySQL); `true` по умолчанию с 2.6.0 |
| **`use_ssl` (в `mysql_users`)** | Фронтенд: принудительно требовать TLS у клиентов |
| **`use_ssl` (в `mysql_servers`)** | Бэкенд: требовать TLS при подключении к конкретному серверу |
| **Firewall Whitelist** | Механизм явного белого списка запросов по пользователю и схеме; режимы `OFF`, `DETECTING`, `PROTECTING` |
| **SPIFFE** | Аутентификация по X.509-сертификату с SAN URI вида `spiffe://...` |
| **`mysql-have_ssl`** | Включает TLS на фронтенде (Client → ProxySQL); `true` по умолчанию с 2.6.0 |
| **`use_ssl` (в `mysql_users`)** | Фронтенд: принудительно требовать TLS у клиентов |
| **`use_ssl` (в `mysql_servers`)** | Бэкенд: требовать TLS при подключении к конкретному серверу |
| **Firewall Whitelist** | Механизм явного белого списка запросов по пользователю и схеме; режимы `OFF`, `DETECTING`, `PROTECTING` |
| **SPIFFE** | Аутентификация по X.509-сертификату с SAN URI вида `spiffe://...` |

## Теоретический блок

### Модель угроз

ProxySQL находится в доверенной зоне между клиентами и бэкендами, поэтому к нему предъявляются два разных класса требований:

| Класс угроз | Что защищаем | Механизмы |
| :--- | :--- | :--- |
| Несанкционированное изменение конфигурации | Целостность роутинга | Учётные данные admin, ограничение интерфейсов, аудит-лог |
| Полный обход контроля доступа | Данные | `mysql_users` с `backend`, `use_ssl`, правила по `username` |
| Атака через прокси | Доступность и данные | Query Firewall, лимиты соединений, TLS |
| Компрометация admin-интерфейса | Вся конфигурация | Смена учётных данных, сетевая изоляция, аудит-лог |

**Ключевой риск, специфичный для прокси:** ошибка в `mysql_users` или query rules превращается в обход ограничений доступа. Если пользователь в `mysql_users` указывает `backend` с другими учётными данными, он получает права, отличные от прав клиента.

### Учётные данные admin-интерфейса

Существуют **три** независимых набора учётных данных:

| Переменная | Права | Назначение |
| :--- | :--- | :--- |
| `admin-admin_credentials` | Полный доступ | Администрирование конфигурации |
| `admin-stats_credentials` | Только чтение | Сбор статистики внешними системами |
| `mysql-monitor_username` | Только подключение | Проверки монитора |

**Значения по умолчанию — `admin:admin`.** Это значение по умолчанию, известное и используемое в эксплуатации, что делает смену обязательной.

**Практическая проблема:** эти учётные данные передаются **открытым текстом** по протоколу MySQL. Защита обеспечивается TLS либо сетевой изоляцией admin-интерфейса.

### Ограничение одной учётной записи

В актуальных версиях admin-интерфейс поддерживает **несколько** учётных записей, разделённых символом `;`. Формат:

```
admin-admin_credentials="admin:пароль_админа;cluster_sync:пароль_синхронизации"
```

Это решает практическую задачу: для синхронизации ProxySQL Cluster нужна отдельная учётная запись, а выдавать ей права администратора не следует. Разделение позволяет ограничить область действия.

### Ограничение сетевого доступа

Admin-интерфейс по умолчанию слушает на всех интерфейсах — это означает доступность из любой точки, где есть сетевая доступность.

```sql
-- Привязка к конкретному адресу вместо 0.0.0.0
UPDATE global_variables SET variable_value = '127.0.0.1'
WHERE variable_name = 'admin-mysql_ifaces';
LOAD ADMIN VARIABLES TO RUNTIME;
SAVE ADMIN VARIABLES TO DISK;
```

> **Важно:** параметр называется `admin-mysql_ifaces` — историческое имя сохранилось, хотя речь идёт об admin-интерфейсе, а не о MySQL-модуле. Название вводит в заблуждение.

**Дополнительное ограничение по умолчанию:** пользователь `admin` может подключаться **только локально**, даже если пароль задан. Для удалённого доступа нужно добавить вторую учётную запись в `admin-admin_credentials`, например `admin:пароль;radminuser:пароль_удалённого`. Это встроенная защита: умолчанию `admin` нельзя использовать как удалённого пользователя.

Практический подход — оставить admin-интерфейс на localhost и предоставлять доступ через SSH-туннель:

```bash
# Подключение к admin-интерфейсу через туннель
ssh -L 6032:127.0.0.1:6032 user@proxysql-host
mysql -h 127.0.0.1 -P 6032 -u admin -p
```

### Ограничение клиентских подключений

Переменная `mysql-interfaces` задаёт адреса и порты приёма клиентских подключений:

```sql
-- Клиентский трафик только на внутреннем интерфейсе
UPDATE global_variables SET variable_value = '10.0.1.10:6033'
WHERE variable_name = 'mysql-interfaces';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

**Правило разделения:** admin-интерфейс (`admin-mysql_ifaces`) и клиентский интерфейс (`mysql-interfaces`) должны слушать разные адреса. Совмещение на одном адресе делает admin-интерфейс доступным из сегмента приложений.

### Права через `mysql_users`

Параметры `mysql_users` определяют, как ProxySQL подключается к бэкенду от имени клиента.

| Параметр | Смысл |
| :--- | :--- |
| `username` / `password` | Учётные данные для подключения к бэкенду |
| `backend` | Учётные данные, если они отличаются от клиентских |
| `default_hostgroup` | Hostgroup по умолчанию для запросов пользователя |
| `max_connections` | Максимум одновременных сессий пользователя |
| `use_ssl` | Требовать TLS при подключении к бэкенду |
| `transaction_persistent` | Закреплять сессию за одним сервером |

**Параметр `backend`** — механизм разделения прав: клиент подключается под своими учётными данными, а ProxySQL обращается к бэкенду под другими, с меньшими правами.

```sql
-- Клиент app_oltp с правами на свою схему,
-- но обращение к бэкенду идёт от имени ограниченного пользователя
INSERT INTO mysql_users (username, password, backend, default_hostgroup, use_ssl)
VALUES ('app_oltp', 'пароль_клиента', 'svc_oltp;пароль_служебного', 10, 1);
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

### TLS на двух участках

TLS необходимо настроить **в двух местах**, и это отдельные настройки:

| Участок | Что защищает | Настройка |
| :--- | :--- | :--- |
| Client → ProxySQL | Данные и учётные данные клиента в сети | `mysql-have_ssl` (включено по умолчанию с 2.6.0), сертификаты в `datadir`; принудительно — `mysql_users.use_ssl` |
| ProxySQL → Backend | Данные между прокси и бэкендом | `mysql_servers.use_ssl = 1` + `mysql-ssl_p2s_*`; с 2.6.0 — пер-server в `mysql_servers_ssl_params` |

**Важно:** `use_ssl` в `mysql_users` относится к **фронтенду** (Client → ProxySQL), а `use_ssl` в `mysql_servers` — к **бэкенду** (ProxySQL → Backend). Путаница этих двух настроек — частая ошибка, приводящая к тому, что TLS не работает, несмотря на настройку.

Значение `mysql-have_ssl` по умолчанию `true` — поддержка TLS включена, но сертификаты задаются отдельно.

### Audit Log

Механизм появился в версии 2.0.5 и записывает события подключения в JSON.

| Событие | Смысл |
| :--- | :--- |
| `MySQL_Client_Connect_OK` | Успешное подключение клиента |
| `MySQL_Client_Connect_ERR` | Неудачное подключение клиента |
| `MySQL_Client_Close` | Соединение закрыто сервером |
| `MySQL_Client_Quit` | Соединение закрыто клиентом |
| `MySQL_Client_Init_DB` | Смена схемы |
| `Admin_Connect_OK` / `Admin_Connect_ERR` | Подключение к admin-интерфейсу |
| `Admin_Close` / `Admin_Quit` | Закрытие соединения с admin-интерфейсом |

**Наиболее ценное свойство:** журнал фиксирует **доступ к admin-интерфейсу**. Это точка, через которую можно изменить всю маршрутизацию, поэтому её аудит важнее аудита клиентских подключений.

Состав полей JSON-записи:

| Поле | Смысл |
| :--- | :--- |
| `client_addr` | IP клиента |
| `proxy_addr` | Адрес ProxySQL, принявшего соединение |
| `event` | Тип события |
| `username` | Пользователь |
| `schemaname` | Схема |
| `ssl` | Использовался ли TLS |
| `thread_id` | Идентификатор сессии |
| `timestamp`, `time` | Время с миллисекундной точностью |
| `creation_time`, `duration` | Для событий закрытия: начало и длительность сессии |
| `extra_info` | Дополнительный контекст |

### Защита от перегрузки и атак

Прокси находится перед бэкендом, поэтому защита от DoS возлагается в первую очередь на него.

| Механизм | Переменная или настройка | Назначение |
| :--- | :--- | :--- |
| Лимит клиентских соединений | `mysql-max_connections` | Ограничить вход |
| Лимит на пользователя | `mysql_users.max_connections` | Изолировать приложения |
| Лимит на бэкенд | `mysql_servers.max_connections` | Ограничить исходящие |
| Блокировка клиентов с ошибками | `mysql-client_host_error_counts` + `mysql-client_host_cache_size` | Ограничение по IP-адресам при превышении порога ошибок |
| Защита от SQL injection | `mysql-automatic_detect_sqli` | Обнаружение попыток инъекции через libsqlinjection |

**`mysql-automatic_detect_sqli`** включается при необходимости и по умолчанию `false`. Механизм — SQL Injection Engine: анализирует отпечатки запросов (fingerprints) и блокирует распознанные как атаки. При включённой Firewall Whitelist проверка выполняется только по неразрешённым запросам пользователей в режиме `DETECTING`; разрешённые запросы обходят engine.

**`mysql-client_host_error_counts`** — порог ошибок (по умолчанию `0`, механизм отключён). Вместе с `mysql-client_host_cache_size` (размер кэша IP-адресов, по умолчанию `0`) ограничивает новые подключения с IP, превысивших лимит. Очистка: `PROXYSQL FLUSH MYSQL CLIENT HOSTS`. Статистика в `stats_mysql_client_host_cache`.

**Firewall Whitelist** — отдельный механизм от SQL Injection Engine. Позволяет явно разрешить конкретные запросы по пользователю и схеме, блокируя всё остальное. Режимы: `OFF`, `DETECTING` (логирует не разрешённые), `PROTECTING` (выполняет только разрешённые). Таблицы: `mysql_firewall_whitelist_users`, `mysql_firewall_whitelist_rules`, `mysql_firewall_whitelist_sqli_fingerprints`. Управление: `LOAD MYSQL FIREWALL TO RUNTIME`, `SAVE MYSQL FIREWALL TO DISK`. Глобальный переключатель — `mysql-firewall_whitelist_enabled`.

**SPIFFE** — аутентификация по X.509-сертификату: клиент должен предъявить сертификат, проверенный против `proxysql-ca.pem`, с SAN URI вида `spiffe://...`. Идентификатор задаётся в атрибуте `spiffe_id` пользователя (`mysql_users.attributes`), с 2.4.0 — поддержка regex через префикс `!`. COM_CHANGE_USER не поддерживается.

### Уязвимости и hardening (ProxySQL 3.0.x)

ProxySQL — программный компонент с поверхностью атаки: он принимает трафик от ненадёжных клиентов и хранит учётные данные. Критические уязвимости исправляются в patch-версиях, поэтому **обновляйте регулярно** и отслеживайте [CVE-список](https://github.com/sysown/proxysql/security).

| Уязвимость / риск | Суть | Мера |
| :--- | :--- | :--- |
| Heap overflow при обработке первого пакета (CVE-2026-48773, 3.0.8 и ниже) | Неаутентифицированный клиент может переполнить кучу в обработке первого пакета MySQL/PostgreSQL | Обновиться до 3.0.9+ |
| Подмена source-IP через PROXY Protocol v1 (CVE-2026-48772, 3.0.8 и ниже) | Заголовок PROXY Protocol с транспортом `UNKNOWN` мог перекрыть `client_addr` и обойти ACL-правила `mysql_query_rules` | Обновиться до 3.0.9+; если PROXY Protocol нужен — проверяйте, что address-поля в `UNKNOWN`-фреймах отбрасываются |
| Компрометация учётных данных в логах | `SET admin-admin_credentials='user:pass'` логировал значение пароля | С 3.0.7 значения паролей в логах заменяются на `***` |
| Открытые пароли в конфигурации | `proxysql.cnf` и `admin-admin_credentials` хранят пароли в чистом виде | Храните конфиг за пределами репозиториев, ограничите права доступа, используйте secret-менеджеры |
| Утечка learned credentials (Pass-Through Auth) | При включённой pass-through-аутентификации пароли хранятся в памяти процесса в чистом виде | Используйте только при необходимости, задайте finite `mysql-passthrough_auth_cache_ttl_s`, ограничите `mysql-passthrough_auth_username_pattern` |

**Команды hardening:**
- Отключите неиспользуемые интерфейсы: `admin-telnet_enabled='false'`, `admin-restapi_enabled='false'`, `admin-web_enabled='false'`.
- Включите аудит-лог и проверяйте `Admin_Connect_ERR` на признаки подбора паролей.
- Для production отключите `admin-debug` (по умолчанию `false`) и не используйте `admin-read_only` без необходимости.
- При использовании ProxySQL Cluster проверяйте, что `admin-cluster_username`/`admin-cluster_password` присутствуют в `admin-admin_credentials` каждого узла, иначе синхронизация не начнётся (подробнее — в [ProxySQL: HA и Cluster](./proxysql_ha_cluster.md)).

## Практический блок

### Базовая защита admin-интерфейса

```sql
-- 1. Смена учётных данных с заменой значения по умолчанию.
--    Формат с несколькими записями: учётная_запись:пароль;учётная_запись:пароль
SET admin-admin_credentials="admin:СЛОЖНЫЙ_ПАРОЛЬ_НЕ_ПО_УМОЛЧАНИЮ";
SET admin-stats_credentials="stats:ДРУГОЙ_СЛОЖНЫЙ_ПАРОЛЬ";

-- 2. Привязка к localhost
SET admin-mysql_ifaces='127.0.0.1';

-- 3. Отключение неиспользуемых интерфейсов администрирования
SET admin-telnet_enabled='false';

LOAD ADMIN VARIABLES TO RUNTIME;
SAVE ADMIN VARIABLES TO DISK;
```

**Проверка:**

```bash
# Проверка доступа с localhost
mysql -h 127.0.0.1 -P 6032 -u admin -p -e "SHOW VARIABLES LIKE 'admin-%'"
# → admin-admin_credentials
# → admin-mysql_ifaces
# → 127.0.0.1

# Проверка, что admin-интерфейс недоступен с внешнего интерфейса
mysql -h 10.0.1.10 -P 6032 -u admin -p
# → ERROR 2003 (HY000): Can't connect to MySQL server on '10.0.1.10:6032' (111)
```

> **Проверка обязательна.** Ошибка в `admin-mysql_ifaces` может закрыть доступ к admin-интерфейсу и потребовать правки конфигурационного файла с перезапуском. Всегда держите открытой SSH-сессию перед изменением.

### Включение аудит-лога

```sql
-- Задание непустого имени файла автоматически включает Audit Log
UPDATE global_variables SET variable_value = '/var/lib/proxysql/audit.log'
WHERE variable_name = 'mysql-auditlog_filename';

-- Размер файла до ротации, байт
UPDATE global_variables SET variable_value = '104857600'
WHERE variable_name = 'mysql-auditlog_filesize';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

**Проверка:**

```bash
ls -la /var/lib/proxysql/audit*
# → -rw-r----- 1 proxysql proxysql 4821 Sep 27 17:40 audit.log00000001

tail -f /var/lib/proxysql/audit.log00000001
```

```json
{
  "client_addr": "10.0.5.21:40572",
  "creation_time": "2026-09-27 17:38:17.357",
  "duration": "299.648ms",
  "event": "MySQL_Client_Close",
  "extra_info": "MySQL_Thread.cpp:4307:process_all_sessions()",
  "proxy_addr": "10.0.1.10:6033",
  "schemaname": "appdb",
  "ssl": false,
  "thread_id": 807,
  "time": "2026-09-27 17:38:17.657",
  "timestamp": 1772841497657,
  "username": "app_oltp"
}
```

**Ротация:** файлы именуются как базовое имя плюс восьмизначный прогрессивный номер. При достижении `mysql-auditlog_filesize` текущий файл закрывается и создаётся новый.

**Что искать в аудит-логе при разборе инцидента:**

```bash
# Неудачные подключения к admin-интерфейсу — признак попытки подбора
grep 'Admin_Connect_ERR' /var/lib/proxysql/audit.log* | tail -50

# Кто подключался к admin-интерфейсу
grep 'Admin_Connect_OK' /var/lib/proxysql/audit.log* | tail -20

# Подключения без TLS
grep '"ssl":false' /var/lib/proxysql/audit.log* | tail -20
```

### Разделение клиентского и admin-интерфейса

```sql
-- Клиентский трафик на выделенном адресе
UPDATE global_variables SET variable_value = '10.0.1.10:6033'
WHERE variable_name = 'mysql-interfaces';

-- Admin-только на localhost
UPDATE global_variables SET variable_value = '127.0.0.1'
WHERE variable_name = 'admin-mysql_ifaces';

LOAD MYSQL VARIABLES TO RUNTIME;
LOAD ADMIN VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
SAVE ADMIN VARIABLES TO DISK;
```

**Проверка разделения:**

```bash
# Из сегмента приложений admin-интерфейс недоступен
nc -zv 10.0.1.10 6032
# → nc: connectx to 10.0.1.10 port 6032 (tcp) failed: Connection refused

# Клиентский порт доступен
nc -zv 10.0.1.10 6033
# → Connection to 10.0.1.10 port 6033 [tcp/mysql] succeeded!
```

### Настройка TLS к бэкендам

```sql
-- 1. Включение проверки сертификата бэкенда (ProxySQL → Backend)
UPDATE mysql_servers SET use_ssl = 1
WHERE hostgroup_id IN (10, 20);
LOAD MYSQL SERVERS TO RUNTIME;

-- 2. Пути к CA и сертификатам для соединений с бэкендом
UPDATE global_variables SET variable_value = '/etc/proxysql/ssl/ca.pem'
WHERE variable_name = 'mysql-ssl_p2s_ca';

UPDATE global_variables SET variable_value = '/etc/proxysql/ssl/server-cert.pem'
WHERE variable_name = 'mysql-ssl_p2s_cert';

UPDATE global_variables SET variable_value = '/etc/proxysql/ssl/server-key.pem'
WHERE variable_name = 'mysql-ssl_p2s_key';

LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;

-- 3. Требовать TLS у клиентов (Client → ProxySQL) на уровне пользователя
UPDATE mysql_users SET use_ssl = 1
WHERE username IN ('app_oltp', 'app_writer');
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

```bash
chmod 600 /etc/proxysql/ssl/server-key.pem
chown proxysql:proxysql /etc/proxysql/ssl/server-key.pem
# → права закрыты от чтения другими пользователями
```

**Проверка фактического использования TLS:**

```sql
-- Требование TLS задано в конфигурации серверов
SELECT hostgroup_id, hostname, port, use_ssl
FROM runtime_mysql_servers;
# → hostgroup_id | hostname     | port | use_ssl
# → 10           | db-primary-1 | 3306 | 1
```

Колонка `use_ssl` в `runtime_mysql_servers` показывает, задано ли требование TLS для соединений пула. Фактическое использования TLS проверяется на стороне бэкенда: у активного соединения непустой `Ssl_cipher` в `performance_schema.session_status` (или в выводе `SHOW STATUS LIKE 'Ssl_cipher'`). Расхождение (требование задано, шифр пуст) означает, что TLS не работает, несмотря на настройку.

### Разделение прав через `backend`

```sql
-- svc_oltp на бэкенде имеет доступ только к своей схеме
CREATE USER 'svc_oltp'@'%' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';
GRANT SELECT, INSERT, UPDATE, DELETE ON appdb.* TO 'svc_oltp'@'%';
FLUSH PRIVILEGES;
```

```sql
-- Клиент подключается под своими данными, к бэкенду обращается под svc_oltp
INSERT INTO mysql_users (username, password, backend, default_hostgroup, use_ssl)
VALUES ('app_oltp', 'пароль_клиента', 'svc_oltp;СЛОЖНЫЙ_ПАРОЛЬ', 10, 1);
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;
```

**Проверка фактически используемых учётных данных:**

```sql
SELECT hostgroup, srv_host, username
FROM stats_mysql_connection_pool;
# → username
# → svc_oltp
```

### Изоляция приложений

```sql
-- Раздельные лимиты соединений и TLS для каждого приложения
INSERT INTO mysql_users (username, default_hostgroup, max_connections,
                         use_ssl, transaction_persistent)
VALUES ('app_oltp',    10, 300, 1, 0),
       ('app_reporting', 20, 20,  1, 0),
       ('app_migrate',    10, 5,   1, 1);
LOAD MYSQL USERS TO RUNTIME;
SAVE MYSQL USERS TO DISK;

-- Запрет для отчётного пользователя на операции записи
INSERT INTO mysql_query_rules (rule_id, active, username, match_digest,
                               error_msg, apply)
VALUES (13000, 1, 'app_reporting', '^(INSERT|UPDATE|DELETE|REPLACE|ALTER|DROP)',
        'User app_reporting is not allowed to modify data', 1);
LOAD MYSQL QUERY RULES TO RUNTIME;
SAVE MYSQL QUERY RULES TO DISK;
```

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | --- | --- |
| Потерян доступ к admin-интерфейсу | Неверное значение `admin-mysql_ifaces` | Подключитесь по SSH, исправьте `proxysql.cnf`, перезапустите службу |
| Аудит-лог не создаётся | `mysql-auditlog_filename` пуст | Задайте непустое имя файла |
| Аудит-лог не содержит событий admin | Установлено имя файла, но событий не было | Проверьте подключение к admin-интерфейсу; события возникают только при подключении |
| TLS не используется, хотя настроен | Не задан `use_ssl` у пользователя или неверные пути к сертификатам | Проверьте колонку `ssl` в `stats_mysql_connection_pool` |
| `Access denied` при подключении клиента | Неверные данные в `mysql_users` или пользователь отсутствует на бэкенде | Проверьте `mysql_users`; убедитесь, что пользователь создан на всех бэкендах |
| Клиент видит права шире, чем ожидалось | Параметр `backend` не задан, ProxySQL использует клиентские данные | Задайте `backend` с ограниченной учётной записью |
| Admin-интерфейс доступен из сегмента приложений | Слушает на `0.0.0.0` | Привяжите к `127.0.0.1`, предоставляйте доступ через SSH-туннель |
| Множественные учётные данные admin не работают | Неверный разделитель | Используйте `;` между записями формата `пользователь:пароль` |
| Audit Log вырос до огромного размера | Не настроена ротация на уровне системы | Настройте `mysql-auditlog_filesize` и `logrotate` |
| `mysql-monitor_username` совпадает с пользователем в `mysql_users` | Нарушено ограничение ProxySQL | Разделите учётные данные монитора и клиентов |
| Запросы, не вошедшие в белый список, блокируются неожиданно | Firewall Whitelist в режиме `PROTECTING` | Проверьте `mysql_firewall_whitelist_rules`; временно переключите режим в `DETECTING` для сбора digest |
| SQL-инъекции блокируются с ложными сработками | `mysql-automatic_detect_sqli=1` без Firewall Whitelist | Добавьте отпечатки легитимных запросов в `mysql_firewall_whitelist_sqli_fingerprints` |
| IP-клиент заблокирован после ряда ошибок | Превышен `mysql-client_host_error_counts` | Очистите кэш: `PROXYSQL FLUSH MYSQL CLIENT HOSTS`; проверьте `stats_mysql_client_host_cache` |
| Удалённый admin-подлогин не работает | Пользователь `admin` локальный по умолчанию | Добавьте вторую запись в `admin-admin_credentials` для удалённого доступа |

### Обслуживание и очистка

```sql
-- Ротация логов аудита
UPDATE global_variables SET variable_value = '52428800'
WHERE variable_name = 'mysql-auditlog_filesize';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

```bash
# Ротация на уровне системы: файлы audit.log уже пронумерованы ProxySQL,
# поэтому logrotate должен сжимать старые, а не удалять текущий
cat > /etc/logrotate.d/proxysql << 'EOF'
/var/lib/proxysql/audit.log* {
    daily
    rotate 30
    compress
    missingok
    notifempty
    copytruncate
}
EOF

# Проверка конфигурации ротации
logrotate -d /etc/logrotate.d/proxysql
```

```sql
-- Отключение аудит-лога, если он не требуется
UPDATE global_variables SET variable_value = NULL
WHERE variable_name = 'mysql-auditlog_filename';
LOAD MYSQL VARIABLES TO RUNTIME;
SAVE MYSQL VARIABLES TO DISK;
```

**Порядок смены учётных данных admin:**

```sql
-- 1. Установить новые значения
SET admin-admin_credentials="admin:НОВЫЙ_ПАРОЛЬ";
LOAD ADMIN VARIABLES TO RUNTIME;

-- 2. Проверить вход с новым паролем ДО сохранения на диск.
--    При ошибке пароль будет потерян после перезапуска
mysql -h 127.0.0.1 -P 6032 -u admin -p

-- 3. Только после успешной проверки
SAVE ADMIN VARIABLES TO DISK;
```

## Дополнительная информация

### См. также
- **[ProxySQL: Обзор](./proxysql_overview.md)** — архитектура и базовая настройка.
- **[ProxySQL: Конфигурация и переменные](./proxysql_configuration.md)** — синтаксис `proxysql.cnf`, группы переменных.
- **[ProxySQL: Query Rules и Query Cache](./proxysql_query_rules.md)** — firewall и ограничения.
- **[ProxySQL: Мониторинг](./proxysql_monitoring.md)** — метрики и события.
- **[ProxySQL: HA и ProxySQL Cluster](./proxysql_ha_cluster.md)** — Cluster и учётные данные синхронизации.
- **[Безопасность MySQL](../security.md)** — безопасность на стороне бэкенда.

### Официальная документация
- [Audit Log](https://proxysql.com/documentation/audit-log/)
- [Admin Variables](https://proxysql.com/documentation/global-variables/admin-variables/)
- [MySQL Variables](https://proxysql.com/documentation/global-variables/mysql-variables/)
- [Configuring ProxySQL](https://proxysql.com/documentation/configuring/)