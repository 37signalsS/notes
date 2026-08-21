# Дополнительные параметры безопасности MariaDB

Эти параметры снижают поверхность атаки и должны быть настроены в каждом production-инстансе.

## Параметры `my.cnf`

```ini
[mariadb]
# === Защита от атак через файловую систему ===
# Запрет загрузки файлов через SQL (LOAD DATA INFILE)
local-infile = 0

# Запрет использования символических ссылок (защита от Path Traversal)
symbolic-links = 0

# Отключение управляющего соединения (-special) для клиентов
skip-symbolic-links = yes

# === Скрытие информации ===
# Запрет просмотра всех БД пользователями без прав
skip-show-database = 1

# Ограничение информации в ошибках (не раскрывать версию/путь)
log_error_verbosity = 2

# === Ограничение возможностей ===
# Запрет функций, опасных для безопасности (зависит от версии)
# mariadb-secure-installation уже отключает часть из них

# Таймаут аутентификации (защита от brute-force)
# Значение по умолчанию 0 (без таймаута), рекомендуется 10-15 секунд
connect_timeout = 10

# Ограничение времени на обработку запроса (защита от DoS)
max_statement_time = 30
```

```sql
-- Проверка текущих настроек безопасности
SHOW VARIABLES LIKE 'local_infile';
-- → local_infile = OFF

SHOW VARIABLES LIKE 'skip_show_database';
-- → skip_show_database = ON

SHOW VARIABLES LIKE 'log_error_verbosity';
-- → log_error_verbosity = 2
```

## Ограничение привилегий (sql_mode)

```sql
-- Просмотр текущего sql_mode
SELECT @@sql_mode;
-- → STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION

-- Рекомендуемый безопасный sql_mode для production
SET GLOBAL sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION,PIPES_AS_CONCAT,ANSI_QUOTES,NO_AUTO_CREATE_USER';
```

## Чистка от ненужных привилегий

```sql
-- Поиск пользователей с опасными глобальными привилегиями
SELECT User, Host, Super_priv, File_priv, Process_priv
FROM mysql.user
WHERE Super_priv = 'Y' OR File_priv = 'Y';
-- → Если приложения имеют Super_priv — это серьёзная проблема

-- Отзыв опасных привилегий у прикладного пользователя
REVOKE Super_priv, File_priv, Process_priv ON *.* FROM 'app_svc'@'10.0.5.%';

-- Просмотр ВСЕХ привилегий пользователя (с учётом ролей)
SHOW GRANTS FOR 'app_svc'@'10.0.5.%' USING app_readwrite_role;
```

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation` и первичная настройка.
- **[Сетевая безопасность](network-security.md)** — `bind-address`, `max_connections` и файрвол.
- **[Ролевая модель (RBAC)](rbac.md)** — управление ролями и привилегиями.
- **[Конфигурация MariaDB](../configuration.md)** — полный список параметров `my.cnf`.
