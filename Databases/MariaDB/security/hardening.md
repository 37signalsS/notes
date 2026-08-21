# Начальная закалка MariaDB (mariadb-secure-installation)

Скрипт `mariadb-secure-installation` устраняет стандартные уязвимости конфигурации "из коробки". Это **первый обязательный шаг** после установки.

```bash
sudo mariadb-secure-installation
```

## Рекомендуемые ответы для Production

| Вопрос | Ответ | Пояснение |
| :--- | :--- | :--- |
| Switch to unix_socket authentication? | `Y` | Обеспечивает безопасность root-доступа через системные права ОС |
| Change the root password? | `Y` | Установите сложный пароль, даже если используете socket |
| Remove anonymous users? | `Y` | Предотвращает несанкционированный доступ без имени пользователя |
| Disallow root login remotely? | `Y` | Root должен подключаться только локально (через SSH/Socket) |
| Remove test database? | `Y` | Тестовая БД доступна всем пользователям по умолчанию |
| Reload privilege tables now? | `Y` | Применение изменений без перезапуска сервера |

## Ручная проверка после скрипта

```sql
-- Проверка отсутствия анонимных пользователей
SELECT User, Host, Plugin FROM mysql.user WHERE User = '';
-- → (пустой результат - хорошо)

-- Проверка отсутствия тестовой БД
SHOW DATABASES;
-- → test не должно быть в списке

-- Проверка, что root доступен только через unix_socket
SELECT User, Host, Plugin FROM mysql.user WHERE User = 'root';
-- → root | localhost | unix_socket

-- Проверка отсутствия удалённого root
SELECT User, Host FROM mysql.user WHERE User = 'root' AND Host != 'localhost';
-- → (пустой результат - хорошо)
```

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Аутентификация](authentication.md)** — плагины аутентификации и политика паролей.
- **[Сетевая безопасность](network-security.md)** — ограничение сетевого доступа.
- **[Установка MariaDB](../installation_and_setup.md)** — установка и начальная настройка.
