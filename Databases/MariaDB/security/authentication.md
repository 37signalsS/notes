# Аутентификация и политика паролей в MariaDB

MariaDB предоставляет несколько плагинов аутентификации с разными уровнями безопасности. Правильный выбор плагина и настройка политики паролей — критический шаг в закалке.

## Плагины аутентификации

| Плагин | Уровень безопасности | Использование |
| :--- | :--- | :--- |
| `unix_socket` | Высокий (без пароля в сети) | Локальный root и admin-доступ |
| `caching_sha2_password` | Высокий | Сетевые подключения (рекомендуется) |
| `ed25519` | Очень высокий | MariaDB-специфичный, максимальная защита |
| `mysql_native_password` | Низкий (SHA-1) | Только для совместимости со старыми клиентами |

```sql
-- Проверка текущего плагина аутентификации для всех пользователей
SELECT User, Host, Plugin FROM mysql.user;
-- → root | localhost | unix_socket
-- → app_svc | 10.0.5.% | caching_sha2_password

-- Смена плагина для существующего пользователя
ALTER USER 'legacy_app'@'%' IDENTIFIED VIA mysql_native_password USING PASSWORD('old_password');

-- Создание пользователя с современным плагином
CREATE USER 'new_svc'@'10.0.5.%' IDENTIFIED VIA ed25519 USING PASSWORD('strong_password_here');
```

## Включение валидации паролей (VALIDATE_PASSWORD)

Плагин `validate_password` проверяет сложность паролей при создании и смене.

```ini
[mariadb]
plugin_load_add = validate_password

# Минимальная длина пароля
validate_password_length = 14

# Уровень проверки: 0=NONE, 1=LOW (длина), 2=MEDIUM (+цифры,+спецсимволы), 3=STRONG (+словарь)
validate_password_policy = MEDIUM

# Количество цифр
validate_password_number_count = 2

# Количество спецсимволов
validate_password_mixed_case_count = 1
validate_password_special_char_count = 1
```

```sql
-- Проверка настроек валидации
SHOW VARIABLES LIKE 'validate_password%';
-- → validate_password_length = 14
-- → validate_password_policy = MEDIUM

-- Попытка создания пользователя со слабым паролем (вызовет ошибку)
CREATE USER 'weak'@'%' IDENTIFIED BY '123';
-- → ERROR 1819 (HY000): Password policy violated: ...
```

## Политика старения паролей и блокировка учётных записей

```sql
-- Установка срока жизни пароля (90 дней)
ALTER USER 'app_svc'@'10.0.5.%' PASSWORD EXPIRE INTERVAL 90 DAY;

-- Принудительная смена пароля при следующем входе
ALTER USER 'temp_user'@'%' PASSWORD EXPIRE;

-- Глобальная политика: все новые пользователи — пароль истекает через 60 дней
SET GLOBAL default_password_lifetime = 60;

-- Блокировка учётной записи после 5 неудачных попыток
ALTER USER 'app_svc'@'10.0.5.%' FAILED_LOGIN_ATTEMPTS 5 PASSWORD_LOCK_TIME 1;
-- → 1 = 1 день блокировки. Используйте PASSWORD_LOCK_TIME UNLIMITED для постоянной блокировки

-- Просмотр политики для пользователя
SELECT User, Host, password_lifetime, password_expired, failed_login_attempts, password_lock_time
FROM mysql.user WHERE User = 'app_svc';
```

## PAM-аутентификация (централизованное управление)

Для интеграции с LDAP/Active Directory или другими PAM-сервисами:

```ini
[mariadb]
plugin_load_add = auth_pam
```

```sql
-- Создание PAM-пользователя (имя PAM-сервиса берётся из /etc/pam.d/)
CREATE USER 'ldap_user'@'%' IDENTIFIED VIA auth_pam USING 'mariadb';
-- Группы LDAP маппятся на роли MariaDB через файл /etc/security/mariadb.conf
```

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation` и первичная настройка.
- **[Ролевая модель (RBAC)](rbac.md)** — управление ролями и привилегиями.
- **[SSL/TLS](ssl-tls.md)** — `REQUIRE SSL` / `REQUIRE X509` для принудительного шифрования.
