**Актуально для:** MariaDB 10.6 / 10.11 / 11.2 / 11.4

# Аутентификация и политика паролей в MariaDB

## Определения

**Аутентификация** — процесс проверки подлинности пользователя или сервиса при подключении к MariaDB. Реализуется через плагины аутентификации, которые определяют, как секрет проверяется сервером.

**Плагин аутентификации** — модуль, реализующий конкретный механизм проверки подлинности. MariaDB поддерживает нативные плагины (`unix_socket`, `ed25519`, `mysql_native_password`) и внешние (`auth_pam` для PAM/LDAP).

**unix_socket** — плагин аутентификации, который доверяет учётной записи операционной системы. Пользователь может подключиться к MariaDB без пароля, если его системный UID совпадает с именем пользователя MariaDB (например, `root` через `sudo`).

**ed25519** — криптографический плагин аутентификации на основе эллиптических кривых (EdDSA, RFC 7748). Предоставляет высокий уровень безопасности без передачи пароля по сети. Поставляется с MariaDB, но не установлен по умолчанию. Доступен с версии 10.4.

**mysql_native_password** — устаревший плагин на основе SHA-1. Используется по умолчанию в MariaDB для совместимости со старыми клиентами. Не рекомендуется для production-сред.

**caching_sha2_password** — плагин совместимости с MySQL 8.0+. В MariaDB доступен как миграционный плагин с версии 11.4.9 и как полноценный плагин с версии 12.1 (MDEV-9804). Не устанавливается по умолчанию, не является стандартом MariaDB и менее безопасен, чем `ed25519`.

**validate_password** — плагин проверки сложности паролей. Включает политику длины, символов, цифр и может интегрироваться со словарями. Не установлен по умолчанию.

**password_reuse_check** — плагин, предотвращающий повторное использование старых паролей. Доступен с MariaDB 10.7.0+ (стабильный с 10.7.7+).

**PAM (Pluggable Authentication Modules)** — фреймворк операционной системы для централизованной аутентификации. Позволяет делегировать проверку пароля внешним сервисам: LDAP, Active Directory, Kerberos, OTP.

**max_password_errors** — глобальная системная переменная MariaDB (10.4+), ограничивающая количество неудачных попыток входа. В отличие от MySQL, MariaDB не поддерживает per-user `FAILED_LOGIN_ATTEMPTS` / `PASSWORD_LOCK_TIME`.

**RBAC (Role-Based Access Control)** — модель разграничения прав на основе ролей. В MariaDB роли активируются при входе через `SET ROLE` или глобальную переменную `activate_all_roles_on_login`.

**Принцип наименьших привилегий (PoLP)** — предоставление пользователям и сервисам только тех прав, которые минимально необходимы для выполнения их функций.

## Основные концепции

### Архитектура аутентификации MariaDB

MariaDB использует модель плагинов: при подключении клиент отправляет имя пользователя и секрет, сервер передаёт их активному плагину аутентификации. Плагин возвращает успех или отказ. После успешной аутентификации применяется модель авторизации (RBAC).

Ключевые таблицы:
- `mysql.user` — представление (view) над `mysql.global_priv`, отображает пользователей и активные плагины.
- `mysql.global_priv` — начиная с MariaDB 10.4, основное хранилище привилегий и политик (включая срок действия пароля) в формате JSON.
- `mysql.password_reuse_check_history` — история хешей паролей для плагина `password_reuse_check`.

### Локальный vs сетевой доступ

| Тип доступа | Рекомендуемый плагин | Обоснование |
| :--- | :--- | :--- |
| Локальный root (sudo) | `unix_socket` | Отсутствие пароля в сети, опора на права ОС |
| Локальные админы | `unix_socket` или `ed25519` | Socket для SRE-доступа по SSH; ed25519 для automation без sudo |
| Сетевые приложения | `ed25519` | MariaDB-нативный, современный, не использует SHA-1 |
| Legacy-клиенты | `mysql_native_password` | Только при невозможности обновить драйвер; требует TLS |
| Миграция с MySQL 8.0+ | `caching_sha2_password` | Только для сохранения хешей при миграции; после миграции перейдите на `ed25519` |

### Защита в глубину для аутентификации

1. **Плагин:** `unix_socket` для локального root, `ed25519` для сетевых аккаунтов.
2. **Сетевой контроль:** `require_secure_transport = ON` (TLS). Подробнее: **[SSL/TLS](ssl-tls.md)**.
3. **Политика паролей:** `validate_password` с политикой не ниже MEDIUM, `password_reuse_check` (10.7+), `default_password_lifetime`.
4. **Ограничение попыток:** `max_password_errors` (10.4+) для защиты от brute-force.
5. **Аудит:** `server_audit` для фиксации неудачных входов. Подробнее: **[Аудит](audit.md)**.
6. **RBAC:** минимизация привилегий через роли. Подробнее: **[Ролевая модель (RBAC)](rbac.md)**.

## Предварительные требования

- MariaDB 10.6 / 10.11 / 11.2 / 11.4 запущена и доступна через `sudo mariadb`
- Права `sudo` для редактирования `my.cnf` и перезапуска сервиса
- Бэкап системной базы `mysql` перед изменением плагинов аутентификации
- Понимание модели аутентификации MariaDB (см. **[Начальная закалка](hardening.md)**)
- Для `ed25519`: клиентские библиотеки MariaDB Connector/C 3.0+, Connector/J 3.0+, Connector/Node.js 2.0+, Connector/ODBC 3.0+, или MySqlConnector с пакетом `MySqlConnector.Authentication.Ed25519`
- Для PAM: настроенный `/etc/pam.d/mariadb`, установленный пакет `libpam0g` / `pam-devel`, и для RHEL 8+ — `sssd` вместо `pam_ldap`

## Практические сценарии

### Сценарий 1: Проверка текущих плагинов аутентификации

```sql
-- Все пользователи и их плагины
SELECT User, Host, Plugin FROM mysql.user;
-- → root | localhost | unix_socket
-- → app_svc | 10.0.5.% | mysql_native_password

-- Проверка политики пароля и срока действия
SELECT User, Host,
  JSON_UNQUOTE(JSON_EXTRACT(Priv, '$.password_lifetime')) AS password_lifetime,
  JSON_UNQUOTE(JSON_EXTRACT(Priv, '$.password_expired')) AS password_expired
FROM mysql.global_priv WHERE User != '';

-- Поиск устаревших хешей SHA-1
SELECT User, Host, LENGTH(authentication_string) AS hash_len
FROM mysql.user WHERE plugin = 'mysql_native_password' AND LENGTH(authentication_string) < 40;
-- Если возвращает строки — пользователи используют устаревшие хеши
```

### Сценарий 2: Переключение root на unix_socket

```sql
-- Смена плагина на unix_socket
ALTER USER 'root'@'localhost' IDENTIFIED VIA unix_socket;
FLUSH PRIVILEGES;
```

```bash
# Проверка
sudo mariadb -e "SELECT User, Host, Plugin FROM mysql.user WHERE User='root';"
# → root | localhost | unix_socket
```

**Важно:** При активном `unix_socket` всегда используйте `sudo mariadb` для локального root-доступа. Если требуется доступ без sudo — смените плагин на `ed25519` (не рекомендуется для production).

### Сценарий 3: Установка ed25519 для сетевого аккаунта

`ed25519` поставляется с MariaDB с версии 10.4, но не установлен по умолчанию.

```sql
-- Установка плагина (если не установлен)
INSTALL SONAME 'auth_ed25519';

-- Создание пользователя с ed25519
CREATE USER 'app_svc'@'10.0.5.%' IDENTIFIED VIA ed25519 USING PASSWORD('СЛОЖНЫЙ_ПАРОЛЬ_ЗДЕСЬ');

-- Для существующего пользователя
ALTER USER 'legacy_app'@'%' IDENTIFIED VIA ed25519 USING PASSWORD('новый_пароль');
```

**Проверка:**
```sql
SELECT User, Host, Plugin FROM mysql.user WHERE User = 'app_svc';
-- → app_svc | 10.0.5.% | ed25519
```

**Требования к клиентам:**
- MariaDB Connector/C 3.0+
- MariaDB Connector/J 3.0+
- MariaDB Connector/Node.js 2.0+
- MariaDB Connector/ODBC 3.0+
- MySqlConnector (ADO.NET) — требуется пакет `MySqlConnector.Authentication.Ed25519`

### Сценарий 4: Настройка validate_password

Плагин `validate_password` проверяет сложность паролей при создании и смене пользователей. Не установлен по умолчанию.

```ini
[mariadb]
plugin_load_add = validate_password

# Минимальная длина пароля
validate_password_length = 14

# Уровень проверки: 0=LOW (длина), 1=MEDIUM (+цифры,+спецсимволы,+регистр), 2=STRONG (+словарь)
validate_password_policy = MEDIUM

# Количество цифр (MEDIUM и STRONG)
validate_password_number_count = 2

# Количество символов верхнего и нижнего регистра (MEDIUM и STRONG)
validate_password_mixed_case_count = 1

# Количество спецсимволов (MEDIUM и STRONG)
validate_password_special_char_count = 1
```

**Примечание:** Переменные с underscore (`validate_password_length`) являются plugin-style именами. В зависимости от версии MariaDB могут также быть доступны dot-notation переменные (`validate_password.length`). Проверьте доступные переменные:

```sql
SHOW VARIABLES LIKE 'validate_password%';
```

**Проверка блокировки слабого пароля:**
```sql
-- Попытка создания пользователя со слабым паролем (вызовет ошибку)
CREATE USER 'weak'@'%' IDENTIFIED BY '123';
-- → ERROR 1819 (HY000): Password policy violated: ...
```

### Сценарий 5: Политика старения и повторного использования паролей

#### Старение паролей

```sql
-- Установка срока жизни пароля для пользователя (90 дней)
ALTER USER 'app_svc'@'10.0.5.%' PASSWORD EXPIRE INTERVAL 90 DAY;

-- Принудительная смена пароля при следующем входе
ALTER USER 'temp_user'@'%' PASSWORD EXPIRE;

-- Глобальная политика: все новые пользователи — пароль истекает через 60 дней
SET GLOBAL default_password_lifetime = 60;
```

Для персистентности добавьте в `my.cnf`:
```ini
[mariadb]
default_password_lifetime = 60
```

**Проверка (MariaDB 11.5+):**
```sql
SELECT USER, PASSWORD_EXPIRATION_TIME, PASSWORD_ERRORS
FROM information_schema.USERS WHERE USER LIKE '%app_svc%';
```

**Проверка (универсальная):**
```sql
SHOW VARIABLES LIKE 'default_password_lifetime';
SHOW VARIABLES LIKE 'disconnect_on_expired_password';
```

#### Защита от повторного использования

Доступно с MariaDB 10.7.0+ (стабильный с 10.7.7+). Требует установки плагина `password_reuse_check`.

```sql
-- Установка плагина
INSTALL SONAME 'password_reuse_check';

-- Запрет повторного использования пароля в течение 180 дней
SET GLOBAL password_reuse_check_interval = 180;
```

Для персистентности добавьте в `my.cnf`:
```ini
[mariadb]
plugin_load_add = password_reuse_check
password_reuse_check_interval = 180
```

**Важно:** История хешей хранится в таблице `mysql.password_reuse_check_history`. При `strict_password_validation = OFF` администратор может обойти проверку, установив хеш напрямую.

#### Ограничение количества ошибок входа

В MariaDB нет per-user аналогов MySQL `FAILED_LOGIN_ATTEMPTS` / `PASSWORD_LOCK_TIME`. Используйте глобальную переменную `max_password_errors` (введена в 10.4.2):

```ini
[mariadb]
max_password_errors = 10
```

```sql
-- Применение без перезагрузки
SET GLOBAL max_password_errors = 10;
```

**Проверка:**
```sql
SHOW VARIABLES LIKE 'max_password_errors';
-- → max_password_errors = 10
```

**Важно:** `max_password_errors` игнорируется для локальных подключений (`localhost`, `127.0.0.1`, `::1`). Для защиты от brute-force настройте файрвол и `skip-networking` или `bind-address = 127.0.0.1`. Подробнее: **[Сетевая безопасность](network-security.md)**.

### Сценарий 6: PAM-аутентификация (централизованное управление)

Плагин `auth_pam` делегирует аутентификацию операционной системе через PAM. Позволяет интегрировать LDAP, Active Directory, Kerberos, OTP.

**Установка:**
```sql
-- Версия 2.0 (современная)
INSTALL SONAME 'auth_pam';

-- Для MariaDB 10.4 при проблемах с pam v2 используйте v1
-- UNINSTALL SONAME 'auth_pam';
-- INSTALL SONAME 'auth_pam_v1';
```

**Конфигурация PAM (`/etc/pam.d/mariadb`):**
```
# Пример: только LDAP
auth required pam_ldap.so
auth required pam_user_map.so
account required pam_ldap.so

# Пример: LDAP + локальные пользователи (SSSD для RHEL 8+)
auth [success=1 new_authtok_reqd=1 default=ignore] pam_unix.so audit
auth required pam_sss.so try_first_pass
auth required pam_user_map.so
account sufficient pam_unix.so audit
account required pam_sss.so
```

**Примечание:** В современных дистрибутивах (RHEL 8+, Debian 11+) используйте `pam_sss.so` (SSSD) вместо `pam_ldap.so` для интеграции с Active Directory. Модуль `pam_user_map` включён в базовую поставку ОС.

**Создание PAM-пользователя:**
```sql
-- Анонимный прокси-пользователь для маппинга групп LDAP
CREATE USER ''@'%' IDENTIFIED VIA pam USING 'mariadb';
GRANT PROXY ON 'dba'@'%' TO ''@'%';

-- Создание LDAP-пользователя
CREATE USER 'ldap_user'@'%' IDENTIFIED VIA pam USING 'mariadb';
-- Группы LDAP маппятся на роли MariaDB через /etc/security/mariadb.conf
```

**Включение глобальной активации ролей (RBAC):**
```sql
SET GLOBAL activate_all_roles_on_login = ON;
```

Для персистентности добавьте в `my.cnf`:
```ini
[mariadb]
plugin_load_add = auth_pam
activate_all_roles_on_login = ON
```

### Сценарий 7: X509-аутентификация (сертификаты клиентов)

При включенном TLS можно требовать от клиента действительный сертификат X509:

```ini
[mariadb]
require_secure_transport = ON
ssl_cert = /etc/mysql/ssl/server-cert.pem
ssl_key = /etc/mysql/ssl/server-key.pem
ssl_ca = /etc/mysql/ssl/ca.pem
```

```sql
-- Требовать любой действительный сертификат
CREATE USER 'app_svc'@'10.0.5.%' IDENTIFIED BY 'password' REQUIRE X509;

-- Требовать сертификат от определённого издателя
CREATE USER 'app_svc'@'10.0.5.%' IDENTIFIED BY 'password' REQUIRE ISSUER 'CN=MyCA';

-- Требовать сертификат с определённым субъектом
CREATE USER 'app_svc'@'10.0.5.%' IDENTIFIED BY 'password' REQUIRE SUBJECT 'CN=app_svc';
```

Подробнее о сертификатах: **[SSL/TLS](ssl-tls.md)**.

### Сценарий 8: Автоматизация и безопасное хранение учётных данных

#### Файл ~/.my.cnf

```ini
[client]
user=app_svc
password=СЛОЖНЫЙ_ПАРОЛЬ
```

```bash
# Права: только владелец может читать
chmod 600 ~/.my.cnf
```

#### Credential rotation

Пароли сервисных аккаунтов должны ротироваться регулярно (раз в 90 дней). Используйте секрет-менеджер (HashiCorp Vault, Ansible Vault) вместо хранения в конфигах. Подробнее об управлении секретами: **[Шифрование данных (TDE)](tde.md)**.

#### systemd-сервис для клиентских скриптов

Если приложение использует `~/.my.cnf`, убедитесь, что сервисный аккаунт имеет доступ:

```ini
# /etc/systemd/system/myapp.service.d/hardening.conf
[Service]
ProtectSystem=full
ProtectHome=read-only
NoNewPrivileges=yes
PrivateTmp=yes
```

### Сценарий 9: MFA/OTP через PAM

MariaDB не имеет нативного MFA-плагина; многофакторная аутентификация реализуется через PAM-модули OTP (Google Authenticator, FreeOTP, privacyIDEA).

**Установка PAM-модуля OTP:**

```bash
# Google Authenticator PAM-модуль
sudo apt install libpam-google-authenticator   # Debian/Ubuntu
sudo yum install google-authenticator          # EPEL для RHEL/CentOS
```

**Конфигурация PAM (`/etc/pam.d/mariadb`) — LDAP + OTP:**

```
# Сначала OTP, затем LDAP
auth required pam_google_authenticator.so forward_pass
auth [success=1 default=ignore] pam_sss.so try_first_pass
auth required pam_user_map.so
account sufficient pam_unix.so audit
account required pam_sss.so
```

**Настройка пользователя:**

```bash
# Каждый пользователь запускает google-authenticator один раз
google-authenticator
# → QR-код для мобильного приложения + emergency scratch codes
```

**Создание PAM-пользователя MariaDB:**

```sql
CREATE USER 'admin_user'@'%' IDENTIFIED VIA pam USING 'mariadb';
GRANT PROXY ON 'dba'@'%' TO 'admin_user'@'%';
```

**Проверка:**

```bash
# Подключение запросит OTP-код
mariadb --user=admin_user --password=<LDAP_PASSWORD> -e "SELECT USER();"
# → запрос OTP-кода из мобильного приложения
```

**Пояснения:**
- MFA требует, чтобы PAM-стек запрашивал второй фактор; MariaDB просто делегирует аутентификацию PAM.
- Emergency scratch codes храните в сейфе — они обходят OTP.
- Для PCI DSS Req 8.3 MFA обязательна для административного доступа к СУБД.

### Сценарий 10: Proxy users (проксирование привилегий)

Proxy users позволяют одному пользователю подключаться от имени другого, не зная его пароля. Полезно для централизованного доступа: PAM-пользователь подключается, а привилегии берёт из проксируемой учётной записи.

**Механизм:**

```sql
-- 1. Создать целевого пользователя с привилегиями
CREATE USER 'app_role'@'10.0.5.%';
GRANT SELECT, INSERT ON app_db.* TO 'app_role'@'10.5.%';

-- 2. Создать прокси-пользователь (например, PAM)
CREATE USER 'pam_user'@'%' IDENTIFIED VIA pam USING 'mariadb';

-- 3. Разрешить проксирование
GRANT PROXY ON 'app_role'@'10.0.5.%' TO 'pam_user'@'%';
```

**Проверка:**

```sql
-- При подключении через прокси
SELECT USER(), CURRENT_USER();
-- → USER(): pam_user@client-host
-- → CURRENT_USER(): app_role@10.0.5.%
```

**Пояснения:**
- `USER()` — кто подключился; `CURRENT_USER()` — от чьего имени работает (проксированный).
- Proxy users — паттерн для централизованного управления: одна PAM-учётка, привилегии — в ролях.
- Аудит фиксирует оба имени, что важно для расследований.

### Сценарий 11: Zero-downtime ротация секретов

Ротация паролей сервисных аккаунтов без простоя приложения.

**Процедура (двойной пароль):**

```sql
-- 1. Выпустить второй пароль (MariaDB поддерживает только один активный пароль,
--    поэтому ротация через окно переключения)
-- Шаг 1: обновить пароль в секрет-менеджере (Vault) — приложение читает новый пароль
-- Шаг 2: сменить пароль в MariaDB
ALTER USER 'app_svc'@'10.0.5.%' IDENTIFIED BY 'NEW_PASSWORD';

-- Шаг 3: перезапустить пул соединений приложения (rolling restart)
```

**Zero-downtime через MaxScale (рекомендуется):**

```bash
# MaxScale поддерживает смену backend-пароля без разрыва клиентских соединений
maxctrl alter server db01 password NEW_PASSWORD
# → клиенты MaxScale не переподключаются
```

**Автоматизация через Vault:**

```bash
# Ротация в Vault (пример)
vault write database/rotate-root/mariadb
# → Vault меняет пароль root и обновляет dynamic credentials
```

**Пояснения:**
- MariaDB хранит один активный хеш пароля; «двойной пароль» (как в некоторых СУБД) нативно не поддерживается.
- Без прокси (MaxScale) ротация требует rolling restart пула соединений приложения.
- Планируйте ротацию в окно низкой нагрузки; мониторьте `Aborted_connects` после смены.

## Проверка состояния аутентификации

```sql
-- Список всех пользователей и плагинов
SELECT User, Host, Plugin, account_locked, password_expired
FROM mysql.global_priv WHERE User != '';

-- Проверка политики паролей
SHOW VARIABLES LIKE 'validate_password%';
SHOW VARIABLES LIKE 'default_password_lifetime';
SHOW VARIABLES LIKE 'max_password_errors';
SHOW VARIABLES LIKE 'password_reuse_check_interval';
SHOW VARIABLES LIKE 'disconnect_on_expired_password';

-- Проверка устаревших хешей SHA-1
SELECT User, Host, LENGTH(authentication_string) AS hash_len
FROM mysql.user WHERE plugin = 'mysql_native_password' AND LENGTH(authentication_string) < 40;
-- Если возвращает строки — пользователи используют устаревшие хеши, запланируйте миграцию на ed25519
```

## Типичные ошибки и устранение неполадок

### Ошибка: `Access denied for user 'root'@'localhost'`

**Симптом:** Не могу войти под root.

**Причина:** Активен плагин `unix_socket` и вход выполняется без `sudo`.

**Решение:** Всегда используйте `sudo mariadb` для локального root-доступа. Если требуется доступ без sudo, смените плагин на `ed25519` или `mysql_native_password` (не рекомендуется для production).

### Ошибка: `Plugin 'caching_sha2_password' is not installed`

**Симптом:** Не могу создать пользователя с `caching_sha2_password`.

**Причина:** Плагин доступен только в MariaDB 11.4.9+ (миграционный режим) или 12.1+ (полный), и не установлен по умолчанию.

**Решение:** Для миграции с MySQL 8.0+ установите плагин `INSTALL SONAME 'caching_sha2_password';`. Для production в MariaDB используйте `ed25519`.

### Ошибка: `Authentication plugin 'ed25519' cannot be loaded`

**Симптом:** Клиент не поддерживает ed25519.

**Причина:** Старая версия клиентской библиотеки (Connector/C < 3.0, Connector/J < 3.0, драйвер PHP < 8.0).

**Решение:** Обновите клиентские библиотеки. Для временной совместимости используйте `mysql_native_password` с `require_secure_transport = ON`.

### Ошибка: `PAM authentication failed`

**Симптом:** LDAP-пользователь не может войти.

**Причина:** Неправильная конфигурация `/etc/pam.d/mariadb`, отсутствие `pam_user_map`, или неправильные права на каталог `auth_pam_tool_dir`.

**Решение:**
```bash
# Проверка конфигурации PAM
sudo pamtester mariadb ldap_user authenticate

# Проверка прав на вспомогательные файлы PAM
ls -la /var/lib/mysql/auth_pam_tool_dir/
# → drwx------ mysql mysql ...

# Проверка логов
sudo journalctl -u mariadb | grep -i pam
```

### Ошибка: `ERROR 1819: Password policy violated`

**Симптом:** Не могу создать пользователя со сложным паролем.

**Причина:** Пароль не соответствует политике `validate_password`.

**Решение:** Увеличьте сложность пароля или снизьте политику для development-сред. Проверьте действующие переменные:
```sql
SHOW VARIABLES LIKE 'validate_password%';
```

### Ошибка: `max_password_errors` не срабатывает

**Симптом:** Множество неудачных подключений не блокируются.

**Причина:** Переменная `max_password_errors` игнорируется для локальных подключений (`localhost`, `127.0.0.1`).

**Решение:** Настройте файрвол для ограничения удалённых подключений (см. **[Сетевая безопасность](network-security.md)**).

## Лучшие практики

1. **unix_socket для локального root.** Никогда не открывайте root-доступ через сетевой интерфейс.
2. **ed25519 для сетевых аккаунтов.** Нативный MariaDB-плагин, не требует RSA-обмена, не уязвим для атак на SHA-1.
3. **mysql_native_password — только для legacy.** Используйте только при невозможности обновить клиент; обязательно включите TLS.
4. **caching_sha2_password — только для миграции.** После миграции с MySQL 8.0+ переключитесь на `ed25519`. Не используйте как постоянное решение в MariaDB.
5. **validate_password с политикой MEDIUM/STRONG.** Минимум 14 символов, смешанный регистр, цифры, спецсимволы.
6. **password_reuse_check для compliance.** Обязателен для PCI DSS, GDPR, ФСТЭК при работе с паролями.
7. **max_password_errors для brute-force защиты.** Установите разумное значение (5-10) на production.
8. **PAM для корпоративных сред.** Централизует управление учётными записями, интегрируется с LDAP/AD через SSSD.
9. **Хранилище учётных данных.** Пароли в `~/.my.cnf` только для служебных аккаунтов на staging; в production используйте секрет-менеджер.
10. **Аудит входов.** Включите `server_audit` для логирования успешных и неудачных подключений.
11. **Права на файлы конфигурации.** `~/.my.cnf` должен иметь права `600` (`chmod 600 ~/.my.cnf`).
12. **Тестируйте на staging.** Любые изменения плагинов аутентификации тестируйте на инстансе с идентичной ОС и версией MariaDB.

## Дополнительная информация

### Ссылки на подразделы

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation` и первичная настройка.
- **[Ролевая модель (RBAC)](rbac.md)** — управление ролями и привилегиями, `activate_all_roles_on_login`.
- **[SSL/TLS](ssl-tls.md)** — `REQUIRE SSL` / `REQUIRE X509` для принудительного шифрования.
- **[Аудит](audit.md)** — `server_audit` плагин, логирование входов и запросов.
- **[Шифрование данных (TDE)](tde.md)** — управление ключами, секрет-менеджеры.
- **[Сетевая безопасность](network-security.md)** — файрвол, `bind-address`, защита от DoS.
- **[Установка MariaDB](../installation_and_setup.md)** — установка и послеустановочная закалка.
- **[Конфигурация MariaDB](../configuration.md)** — полный список параметров `my.cnf`.

### Смежные темы

- **[Миграция с MySQL](../Operations/migration_mysql_to_mariadb.md)** — особенности аутентификации при переходе с MySQL 8.0+.
- **[Обзор MariaDB](../overview.md)** — архитектура и стратегия развития.
- **[Бинарное логирование](binary-logging.md)** — forensic и репликация.
