# Устранение неполадок безопасности MariaDB

## Типичные ошибки безопасности

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `Access denied for user 'root'@'localhost'` | Не могу войти под root | Активен `unix_socket` плагин | Используйте `sudo mariadb` |
| `ERROR 1045 (28000): Access denied` | Клиент не может подключиться | Неверный пароль или хост не в `GRANT` | Проверьте `mysql.user`, используйте `SHOW GRANTS` |
| `ERROR 1819: Password policy violated` | Не могу создать пользователя | Пароль не соответствует `validate_password` | Увеличьте сложность пароля |
| `SSL connection error: ...` | TLS не работает | Невалидный сертификат или ключ | Проверьте пути, права доступа (600), срок действия |
| Аудит-лог пустой | Нет записей в логе | Плагин не загружен или `server_audit_logging = OFF` | Проверьте `SHOW PLUGINS` и `SHOW VARIABLES LIKE 'server_audit%'` |
| `Table 'mysql.user' doesn't exist` | Сервер не запускается | Повреждённый `datadir` | Выполните `mariadb-upgrade` |

## Диагностические команды

### Обзор безопасности текущего инстанса

```sql
-- Пользователи и плагины аутентификации
SELECT User, Host, plugin, authentication_string FROM mysql.user;

-- Настройки SSL/TLS
SHOW VARIABLES LIKE '%ssl%';
SHOW VARIABLES LIKE 'require_secure_transport';

-- Аудит
SHOW VARIABLES LIKE 'server_audit%';

-- Шифрование данных
SHOW VARIABLES LIKE 'innodb_encrypt%';

-- Валидация паролей
SHOW VARIABLES LIKE 'validate_password%';

-- Дополнительные параметры
SHOW VARIABLES LIKE 'local_infile';

-- Просмотр всех активных привилегий (для аудита)
SELECT Grantee, Table_type, Privilege_type
FROM information_schema.USER_PRIVILEGES
WHERE Grantee LIKE '%app_svc%';
```

### Проверка файлов и логов

```bash
# Проверка error log (путь зависит от дистрибутива)
sudo tail -100 /var/log/mysql/error.log | grep -i "access denied\|error\|warning"

# Проверка прав на файлы сертификатов
ls -la /etc/mysql/ssl/
# → Все файлы должны быть 600, владелец mysql:mysql

# Проверка прав на аудит-логи
ls -la /var/log/mysql/
# → audit.log должен быть 600, владелец mysql:mysql
```

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation`.
- **[Аутентификация](authentication.md)** — плагины аутентификации и политика паролей.
- **[SSL/TLS](ssl-tls.md)** — настройка и диагностика TLS.
- **[Аудит](audit.md)** — настройка и проверка плагина `server_audit`.
