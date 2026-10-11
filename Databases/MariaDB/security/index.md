# Безопасность MariaDB: обзор

**Актуально для:** MariaDB 10.6 / 10.11 / 11.2 / 11.4

## Определения

**SSL/TLS (Secure Sockets Layer / Transport Layer Security)** — криптографические протоколы для защиты трафика между клиентом и сервером. Обеспечивают шифрование данных, проверку подлинности сервера (и клиента при mTLS) и целостность сообщений. Подробнее: **[SSL/TLS](ssl-tls.md)**.

**MariaDB Audit Plugin (`server_audit`)** — инструмент для глубокого мониторинга действий пользователей. Позволяет фиксировать подключения, выполненные запросы и доступ к таблицам, что является обязательным требованием комплаенса (PCI DSS, GDPR, ФСТЭК). Подробнее: **[Аудит](audit.md)**.

**Data-at-rest Encryption (TDE — Transparent Data Encryption)** — прозрачное шифрование данных, хранящихся на диске. В MariaDB реализуется через шифрование табличных пространств InnoDB, защищая от кражи физических носителей или бэкапов. Подробнее: **[Шифрование данных (TDE)](tde.md)**.

**RBAC (Role-Based Access Control)** — модель разграничения прав доступа, основанная на ролях. MariaDB внедрила полноценную поддержку ролей значительно раньше MySQL, обеспечивая гибкое управление привилегиями через группировку в логические роли (например, `developer`, `analyst`) с поддержкой иерархии и наследования. Подробнее: **[Ролевая модель (RBAC)](rbac.md)**.

**Эшелонированная защита (Defense-in-Depth)** — стратегия многоуровневого обеспечения безопасности, при которой провал одного механизма защиты компенсируется наличием других уровней. В контексте MariaDB это означает защиту на уровне сети (firewall, TLS), хоста (ограничение прав процесса), инстанса (аутентификация, аудит) и данных (шифрование, RBAC).

**Поверхность атаки (Attack Surface)** — совокупность всех точек (точек атаки), через которые злоумышленник может получить несанкционированный доступ к системе. В MariaDB сюда входят: открытые порты, удаленные учетные записи, плагины, тестовые БД, разрешенные SQL-функции (например, `LOAD DATA INFILE`), а также несферицированные логи.

**Принцип наименьших привилегий (Principle of Least Privilege, PoLP)** — предоставление пользователям и сервисам только тех прав, которые минимально необходимы для выполнения их функций. В MariaDB реализуется через гранулярные `GRANT`/`REVOKE`, роли (RBAC) и ограничение глобальных привилегий (например, запрет `SUPER` для приложений).

## Основные концепции

### Модель безопасности MariaDB

Безопасность MariaDB строится по модели слоев, каждый из которых обеспечивает собственный уровень защиты:

1. **Сетевой уровень:** `bind-address`, `skip-networking`, `require_secure_transport`, файрвол (UFW/iptables/firewalld), mTLS. Подробнее: **[Сетевая безопасность](network-security.md)**.
2. **Уровень аутентификации:** плагины (`unix_socket`, `caching_sha2_password`, `ed25519`), политика паролей, MFA через PAM. Подробнее: **[Аутентификация и политика паролей](authentication.md)**.
3. **Уровень авторизации:** RBAC (роли), гранулярные привилегии (`SELECT`, `INSERT` на уровне таблиц/столбцов), отсутствие прямых `GRANT` у приложений. Подробнее: **[Ролевая модель (RBAC)](rbac.md)**.
4. **Уровень аудита:** `server_audit` плагин, бинарные логи, syslog-интеграция для SIEM. Подробнее: **[Аудит](audit.md)**, **[Бинарное логирование](binary-logging.md)**.
5. **Уровень данных:** TDE (шифрование на диске), шифрование бэкапов, отдельное хранение ключей (Vault, file key management). Подробнее: **[Шифрование данных (TDE)](tde.md)**.

### Ключевые различия между MariaDB и MySQL в области безопасности

MariaDB исторически предлагала расширенные возможности по сравнению с MySQL:

| Возможность | MariaDB | MySQL |
| :--- | :--- | :--- |
| **Роли (RBAC)** | Полноценная поддержка с версии 10.0 | Полноценная поддержка с версии 8.0 |
| **Аудит** | Встроенный `server_audit` (бесплатный) | `audit_log` (Community) / Enterprise |
| **PAM-аутентификация** | Нативная поддержка | Ограниченная |
| **Ed25519** | Поддержка с 10.4 | Не поддерживается |
| **Шифрование таблиц** | Через file_key_management / Vault | Через Keyring File / Vault |

### Типичные ошибки конфигурации, снижающие безопасность

1. **Анонимные пользователи:** `mysql.user` содержит записи с пустым `User` — любой может подключиться без пароля.
2. **Тестовая БД `test`:** Доступна всем пользователям по умолчанию.
3. **Root через сеть:** Учетная запись `root@%` с паролем — прямой путь к компрометации.
4. **`local-infile = 1`:** Разрешает `LOAD DATA LOCAL INFILE`, что может привести к чтению файлов клиента (см. [SQL Injection](../../../Security/ApplicationSecurity/sql_injection.md)).
5. **Отсутствие аудита:** Невозможность восстановить последовательность действий при инциденте.

## Предварительные требования

### Окружение

- MariaDB 10.6, 10.11, 11.2 или 11.4 (LTS-версии предпочтительны)
- ОС: RHEL/CentOS 8+, Debian 11+, Ubuntu 20.04+ или эквивалент
- Права суперпользователя (`root` или `sudo`) для модификации конфигурации и управления сервисом
- Доступ к файрволу хоста для ограничения порта 3306/TCP

### Знания и инструменты

- Понимание модели RBAC и гранулярных привилегий MariaDB
- Навыки работы с `my.cnf` и динамическими переменными MariaDB
- Знакомство с PKI для выдачи/обновления TLS-сертификатов
- Доступ к SIEM-системе или syslog-серверу для сбора аудит-логов
- Процедуры резервного копирования и восстановления инстанса

## Пошаговые инструкции

### Шаг 1: Начальная закалка инстанса

Выполните `mariadb-secure-installation` и подтвердите удаление анонимных пользователей, тестовой БД и удалённого root-доступа.

```bash
sudo mariadb-secure-installation
```

Подробные ответы на вопросы скрипта см. в **[Начальная закалка](hardening.md)**.

### Шаг 2: Настройка аутентификации

Для локального доступа используйте `unix_socket`. Для сетевых клиентов — `caching_sha2_password` или `ed25519`. Включите плагин `validate_password` с политикой не ниже MEDIUM.

```sql
ALTER USER 'app_svc'@'10.0.5.%' IDENTIFIED VIA caching_sha2_password USING PASSWORD('...');
```

Подробнее: **[Аутентификация и политика паролей](authentication.md)**.

### Шаг 3: Принудительное TLS-шифрование

Включите `require_secure_transport` и разместите сертификаты с правами `600` для пользователя `mysql`.

```ini
[mariadb]
require_secure_transport = ON
ssl_cert = /etc/mysql/ssl/server-cert.pem
ssl_key  = /etc/mysql/ssl/server-key.pem
```

Подробнее: **[SSL/TLS](ssl-tls.md)**.

### Шаг 4: Ограничение сетевого доступа

Привяжите `bind-address` к конкретному интерфейсу и ограничьте порт 3306 файрволом. Настройте `max_user_connections` и таймауты неактивных соединений.

```ini
[mariadb]
bind-address        = 10.0.5.20
max_user_connections = 50
wait_timeout         = 600
skip-name-resolve    = 1
```

```bash
# UFW
sudo ufw allow from 10.0.5.0/24 to any port 3306 proto tcp

# firewalld
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.5.0/24" port port="3306" protocol="tcp" accept'
sudo firewall-cmd --reload
```

Подробнее: **[Сетевая безопасность](network-security.md)**.

### Шаг 5: Включение аудита

Настройте плагин `server_audit` для логирования DDL/DML операций, подключений и доступа к таблицам. Направьте вывод в syslog для интеграции с SIEM.

```ini
[mariadb]
plugin_load_add = server_audit
server_audit_events = CONNECT, QUERY, TABLE
server_audit_logging = ON
server_audit_syslog = ON
```

Подробнее: **[Аудит](audit.md)**.

### Шаг 6: Шифрование данных на диске (TDE)

Активируйте шифрование табличных пространств InnoDB для баз с персональными данными. Храните ключи отдельно от данных с помощью `file_key_management` или Vault.

```ini
[mariadb]
innodb_encrypt_tables    = ON
innodb_encrypt_log       = ON
innodb_encrypt_temporary_tables = ON
encrypt_binlog           = ON
```

Подробнее: **[Шифрование данных (TDE)](tde.md)**.

### Шаг 7: Настройка ролевой модели (RBAC)

Создайте роли вместо прямых `GRANT` пользователям. Никогда не выдавайте приложениям привилегию `SUPER`.

```sql
CREATE ROLE 'app_read'@'10.0.5.%';
GRANT SELECT ON app_db.* TO 'app_read'@'10.0.5.%';
GRANT 'app_read'@'10.0.5.%' TO 'app_svc'@'10.0.5.%';
SET DEFAULT ROLE 'app_read'@'10.0.5.%' TO 'app_svc'@'10.0.5.%';
```

Подробнее: **[Ролевая модель (RBAC)](rbac.md)**.

### Шаг 8: Включение бинарного логирования

Включите бинарный лог для forensic и репликации. Настройте ротацию и шифрование бинарных логов.

```ini
[mariadb]
log_bin                = /var/log/mysql/mariadb-bin.log
binlog_expire_logs_seconds = 2592000
binlog_encryption       = ON
```

Подробнее: **[Бинарное логирование](binary-logging.md)**.

### Шаг 9: Дополнительные параметры hardening

```ini
[mariadb]
local-infile            = 0
skip-show-database      = 1
symbolic-links          = 0
```

Подробнее: **[Дополнительные параметры](additional-parameters.md)**.

## Конфигурации и команды

### Полный пример `my.cnf` для production-инстанса

```ini
[mariadb]
# Сеть
bind-address            = 10.0.5.20
skip-name-resolve       = 1
require_secure_transport = ON

# Ограничения соединений
max_connections          = 500
max_user_connections     = 50
wait_timeout             = 600
interactive_timeout      = 600
max_allowed_packet       = 64M

# Аутентификация
plugin_load_add         = validate_password

# TLS
ssl_cert                = /etc/mysql/ssl/server-cert.pem
ssl_key                 = /etc/mysql/ssl/server-key.pem

# Аудит
plugin_load_add         = server_audit
server_audit_events      = CONNECT, QUERY, TABLE
server_audit_logging     = ON
server_audit_syslog      = ON

# Шифрование на диске
innodb_encrypt_tables            = ON
innodb_encrypt_log               = ON
innodb_encrypt_temporary_tables  = ON
encrypt_binlog                   = ON

# Бинарный лог
log_bin                         = /var/log/mysql/mariadb-bin.log
binlog_expire_logs_seconds       = 2592000
binlog_encryption                = ON

# Hardening
local-infile                     = 0
skip-show-database               = 1
symbolic-links                   = 0
```

### Диагностические команды

```sql
-- Проверка активных пользователей и плагинов аутентификации
SELECT User, Host, Plugin FROM mysql.user;

-- Проверка отсутствия анонимных пользователей
SELECT User, Host FROM mysql.user WHERE User = '';
-- → (пустой результат — хорошо)

-- Проверка TLS-статуса активных соединений
SELECT ssl_cipher, ssl_version FROM information_schema.PROCESSLIST WHERE db IS NOT NULL;

-- Проверка статуса шифрования таблиц
SELECT TABLE_SCHEMA, TABLE_NAME, CREATE_OPTIONS FROM information_schema.TABLES WHERE ENGINE = 'InnoDB';

-- Проверка настроек валидации паролей
SHOW VARIABLES LIKE 'validate_password%';

-- Проверка лимитов соединений
SHOW VARIABLES LIKE 'max_connections';
SHOW VARIABLES LIKE 'max_user_connections';
SHOW STATUS LIKE 'Max_used_connections';
```

## Проверка и валидация

### После начальной закалки

```bash
# Проверка статуса сервиса
systemctl status mariadb
# → active (running)

# Проверка открытых портов
ss -tlnp | grep 3306
# → LISTEN 0 80 10.0.5.20:3306 ...

# Проверка отсутствия тестовой БД
mariadb -e "SHOW DATABASES;" | grep -w test
# → (пустой результат — хорошо)
```

### После включения TLS

```bash
# Проверка принудительного TLS
mariadb -e "SHOW VARIABLES LIKE 'require_secure_transport';"
# → require_secure_transport = ON

# Проверка шифрования извне
openssl s_client -connect 10.0.5.20:3306 -servername db01.example.com
# → Verify return code: 0 (ok)
```

### После настройки аудита

```bash
# Проверка, что сервер слушает только внутренний интерфейс
ss -tlnp | grep 3306
# → 10.0.5.20:3306, не 0.0.0.0:3306
```

### После настройки ролей

```sql
-- Проверка ролей и привилегий
SHOW GRANTS FOR 'app_svc'@'10.0.5.%';
-- → GRANT USAGE ON *.* TO `app_svc`@`10.0.5.%`
-- → GRANT `app_read`@`10.0.5.%` TO `app_svc`@`10.0.5.%`

-- Проверка отсутствия SUPER у приложений
SELECT User, Host, Super_priv FROM mysql.user WHERE Super_priv = 'Y';
-- → только root-учетные записи
```

## Типичные ошибки и устранение неполадок

### Ошибка: соединение отклоняется после включения `require_secure_transport`

**Симптом:** `ERROR 2026 (HY000): SSL connection error: Unable to get certificate`

**Причина:** Клиент не поддерживает TLS или сертификат сервера неверен/просрочен.

**Решение:**
1. Проверьте сертификат: `openssl x509 -in /etc/mysql/ssl/server-cert.pem -noout -dates`
2. На клиенте передайте параметры `--ssl-ca`, `--ssl-cert`, `--ssl-key`
3. Для диагностики: `mariadb --ssl --ssl-verify-server-cert -e "SELECT 1"`

### Ошибка: доступ заблокирован после настройки файрвола

**Симптом:** `ERROR 2003 (HY000): Can't connect to MySQL server on '10.0.5.20' (110)`

**Решение:**
```bash
# Проверка правил UFW
sudo ufw status verbose

# Проверка файрвола хоста
sudo iptables -L -n | grep 3306
sudo firewall-cmd --list-all
```

### Ошибка: `server_audit` не запускается

**Симптом:** плагин не загружается, ошибка в `journalctl -u mariadb`

**Решение:**
1. Убедитесь, что пакет `mariadb-plugin-server_audit` установлен: `rpm -qa | grep server_audit` или `dpkg -l | grep server_audit`
2. Проверьте конфигурацию: `SHOW PLUGINS;` — плагин должен быть в статусе `ACTIVE`

### Ошибка: `max_connections` переполняется

**Симптом:** `ERROR 1040 (HY000): Too many connections`

**Решение:**
1. Временно увеличить лимит: `SET GLOBAL max_connections = 1000;`
2. Найти "утяжеляющие" соединения: `SELECT USER, HOST, COUNT(*) FROM information_schema.PROCESSLIST GROUP BY USER, HOST ORDER BY COUNT(*) DESC;`
3. Настроить `wait_timeout` для автоматического закрытия неактивных соединений

## Лучшие практики

1. **Один рубеж — не защита.** Комбинируйте сетевой контроль, TLS, RBAC и аудит. Провал одного слоя компенсируется наличием других.
2. **Root только через socket.** Никогда не открывайте root-доступ через сеть. Локальный root должен использовать `unix_socket`.
3. **Роли вместо прямых GRANT.** Приложения получают доступ через роли. Это упрощает аудит и переключение привилегий.
4. **Принудительный TLS.** `require_secure_transport = ON` — не опционально для production. Запретите `caching_sha2_password` для старых клиентов, если они не могут обновить драйвер.
5. **Аудит в SIEM.** Вывод `server_audit` в syslog или внешний SIEM. Без централизованного сбора логов комплаенс-требования не выполняются.
6. **Шифрование ключей отдельно от данных.** Файл ключей TDE должен храниться на отдельном носителе или в HashiCorp Vault, доступ к которому ограничен.
7. **Ротация бинарных логов.** Настройте `binlog_expire_logs_seconds` и мониторьте использование диска. Без ротации логи займут всё доступное пространство.
8. **Регулярный аудит привилегий.** Периодически проверяйте `mysql.user` и `information_schema.USER_PRIVILEGES` на предмет лишних глобальных привилегий.
9. **Бэкапы отдельно от БД.** Храните зашифрованные бэкапы на отдельном носителе. Тестируйте восстановление не реже одного раза в квартал.
10. **`skip-name-resolve = 1`.** Отключает DNS-резолв при аутентификации, ускоряет подключения и исключает DNS-spoofing-атаки.

## Дополнительная информация

### Ссылки на подразделы

- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation` и первичная накалка.
- **[Аутентификация и политика паролей](authentication.md)** — плагины аутентификации, `validate_password`, PAM, MFA/OTP.
- **[SSL/TLS](ssl-tls.md)** — управление сертификатами, mTLS, автоматизация ротации, диагностика TLS.
- **[Сетевая безопасность](network-security.md)** — `bind-address`, файрвол, защита от DoS.
- **[Аудит](audit.md)** — `server_audit`, целостность логов, комплаенс, интеграция с SIEM, NTP.
- **[Шифрование данных (TDE)](tde.md)** — TDE, `file_key_management`, Vault, HSM/FIPS/GOST.
- **[Ролевая модель (RBAC)](rbac.md)** — создание ролей, гранулярные привилегии, наследование, хранимые объекты, маскирование.
- **[Бинарное логирование](binary-logging.md)** — forensic, ротация, шифрование бинарных логов.
- **[Дополнительные параметры](additional-parameters.md)** — `local-infile`, `skip-show-database`, `symbolic-links`.
- **[Устранение неполадок](troubleshooting.md)** — ошибки безопасности, инциденты, postmortem, диагностика.
- **[CIS Benchmark](cis-benchmark.md)** — контрольные семейства для безопасной конфигурации.
- **[Комплаенс](compliance.md)** — маппинг PCI DSS / GDPR / ФСТЭК на контролы MariaDB.
- **[Мониторинг безопасности](security-monitoring.md)** — security-алерты и IOC.
- **[Производительность security-фич](security-performance.md)** — оверхед TLS, аудита, TDE.
- **[Безопасность в контейнерах](container-security.md)** — non-root, read-only rootfs, secrets.
- **[Тестирование безопасности](security-testing.md)** — пентест, аудит TLS и привилегий.
- **[Безопасность Galera](galera-security.md)** — шифрование SST, репликационный трафик, `wsrep_allowlist`.
- **[Автоматизация hardening](automation-hardening.md)** — Ansible-плейбуки, compliance-as-code.

### Смежные темы

- **[Обзор MariaDB](../overview.md)** — архитектура и стратегия развития.
- **[Конфигурация MariaDB](../configuration.md)** — `my.cnf`, иерархия загрузки, тюнинг.
- **[Установка MariaDB](../installation_and_setup.md)** — установка и начальная закалка.
- **[SQL Injection](../../../Security/ApplicationSecurity/sql_injection.md)** — защита от внедрения SQL.
- **[Аудит и комплаенс](../../../Security/audit_and_compliance_overview.md)** — общие принципы отчетности.
- **[HashiCorp Vault](../../../Vault/overview.md)** — управление ключами шифрования.
- **[Шифрование данных в покое](../../Concepts/encryption_at_rest.md)** — теория TDE, DEK/KEK, Envelope Encryption.
- **[Безопасная установка СУБД](../../installation_security.md)** — общие принципы закалки.
