# Установка и настройка MariaDB

## Определения

**MariaDB** — реляционная система управления базами данных (RDBMS) с открытым исходным кодом, развивающаяся как высокопроизводительный и функционально богатый форк MySQL.

**LTS (Long Term Support)** — версии с долгосрочной поддержкой (обычно 5 лет), обеспечивающие стабильность API и гарантированные обновления безопасности. Приоритетны для production-сред.

**GPG Key (GnuPG Key)** — криптографический ключ, используемый для проверки подлинности и целостности пакетов в репозиториях Linux.

**Unix Socket (`unix_socket`)** — механизм аутентификации, позволяющий пользователям ОС подключаться к БД без пароля, если их системный UID совпадает с именем пользователя в базе (актуально для `root` через `sudo`).

## Основные концепции

### Жизненный цикл и выбор версии

Для продуктивных систем следует выбирать актуальные LTS-ветки. Использование Rolling релизов (например, 12.1, 12.2) в production не рекомендуется из-за короткого цикла поддержки.

| Версия | Статус | Поддержка до | Ключевые фичи |
| :--- | :--- | :--- | :--- |
| **12.3 LTS** | Рекомендуемая | Май 2031 | Векторный поиск, атомарные логи |
| **11.4 LTS** | Стабильная | Июнь 2029 | Оптимизация оптимизатора |
| **10.11 LTS** | Зрелая | Февраль 2028 | Высокая стабильность, широкая поддержка ОС |

### Требования к среде (Prerequisites)

- **Память:** Минимум 1 ГБ RAM (рекомендуется 4 ГБ+ для InnoDB Buffer Pool).
- **Диск:** Минимум 500 МБ для бинарных файлов + объем под данные и логи (WAL). Рекомендуется SSD/NVMe.
- **ОС:** Linux (Debian 11+, Ubuntu 20.04+, RHEL 8+).
- **Доступ:** Права `sudo` на целевом хосте.

## Практические сценарии

### Установка через официальный репозиторий (Debian/Ubuntu)

Этот метод гарантирует получение последних исправлений безопасности напрямую от MariaDB Foundation.

**1. Настройка репозитория и GPG-ключей:**
Скрипт `mariadb_repo_setup` автоматически выполняет `apt-key add` и создает файл `.list`.

```bash
curl -LsS https://r.mariadb.com/downloads/mariadb_repo_setup | sudo bash -s -- --mariadb-server-version="mariadb-12.3"
```

**2. Установка пакетов:**
```bash
sudo apt update
sudo apt install -y mariadb-server mariadb-client
```

**3. Валидация установки:**
```bash
mariadb --version
# → result: mariadb  Ver 15.1 Distrib 10.11.x-MariaDB (или 12.3.x)
```

### Установка в RHEL / Rocky Linux / AlmaLinux

```bash
# 1. Настройка репозитория
curl -LsS https://r.mariadb.com/downloads/mariadb_repo_setup | sudo bash -s -- --mariadb-server-version="mariadb-12.3"

# 2. Установка через DNF
sudo dnf install -y MariaDB-server MariaDB-client
```

### Послеустановочная закалка безопасности (Hardening)

Скрипт `mariadb-secure-installation` устраняет стандартные уязвимости конфигурации "из коробки".

```bash
sudo mariadb-secure-installation
```

**Рекомендуемые ответы для Production:**
- **Switch to unix_socket authentication? [Y/n]**: `Y`. Обеспечивает безопасность root-доступа через системные права.
- **Change the root password? [Y/n]**: `Y` (установите сложный пароль, даже если используете socket).
- **Remove anonymous users? [Y/n]**: `Y`. Предотвращает несанкционированный доступ без имени пользователя.
- **Disallow root login remotely? [Y/n]**: `Y`. Root должен подключаться только локально (через SSH/Socket).
- **Remove test database and access to it? [Y/n]**: `Y`.
- **Reload privilege tables now? [Y/n]**: `Y`.

### Проверка корректности запуска и сетевой доступности

После установки необходимо убедиться, что сервис работает и слушает нужные интерфейсы.

```bash
# Проверка статуса сервиса
sudo systemctl status mariadb --no-pager

# Проверка прослушивания портов (по умолчанию 127.0.0.1:3306)
sudo ss -tlnp | grep 3306
# → result: LISTEN 0 80 127.0.0.1:3306 0.0.0.0:* users:(("mariadbd",pid=...,fd=...))

# Проверка аутентификации через unix_socket
sudo mariadb -u root -e "SELECT User, Host, Plugin FROM mysql.user WHERE User='root';"
```

## Устранение неполадок (Troubleshooting)

### Ошибки репозитория и GPG
- **Симптом:** `The following signatures couldn't be verified because the public key is not available`.
- **Причина:** Сбой импорта GPG-ключа или блокировка трафика к серверам ключей.
- **Решение:** Повторно запустите `mariadb_repo_setup` или импортируйте ключ вручную:
  `sudo apt-key adv --recv-keys --keyserver keyserver.ubuntu.com 0xF1656F24C74CD1D8`

### Ошибка `Access denied for user 'root'@'localhost'`
- **Причина:** Попытка входа без `sudo` при активном плагине `unix_socket`.
- **Решение:** Всегда используйте `sudo mariadb` для локального доступа под root. Если требуется доступ без sudo, смените плагин на `mysql_native_password` (не рекомендуется для SRE).

### Конфликт версий при обновлении
- **Симптом:** Сервер не запускается после `apt upgrade`, в логах ошибка `InnoDB: Unsupported redo log format`.
- **Решение:** Обязательно выполните `mariadb-upgrade` после смены бинарных файлов. Если обновление было мажорным (например, 10.6 -> 11.4), проверьте `my.cnf` на наличие удаленных параметров.

## Дополнительная информация

### Совместимость аутентификации
MariaDB 12.3 LTS поддерживает современные плагины, включая `caching_sha2_password` (по умолчанию в MySQL 8+). При миграции старых PHP/Python приложений может потребоваться обновление клиентских библиотек или явное указание плагина `mysql_native_password` для совместимости.

### См. также
- **[Безопасность MariaDB](security/index.md)** — продвинутая настройка TLS, аудита и шифрования.
- **[Обзор MariaDB](overview.md)** — архитектурные основы.
- **[Конфигурация MariaDB](configuration.md)** — глубокая настройка `my.cnf`.
- **[Клиентские утилиты](client_utilities.md)** — работа с `mariadb-shell` и `mariadb-admin`.
- **[Безопасная установка СУБД](../installation_security.md)** — общие принципы закалки баз данных.
