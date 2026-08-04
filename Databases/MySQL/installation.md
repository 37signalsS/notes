# Установка и начало работы с MySQL

## Определения

**MySQL Server (`mysqld`)** — основной процесс СУБД, отвечающий за управление данными, обработку SQL-запросов и обеспечение транзакционности.

**MySQL Client (`mysql`)** — консольный инструмент для взаимодействия с сервером. В современных версиях (8.4+) рекомендуется также использовать **MySQL Shell (`mysqlsh`)** для продвинутых задач администрирования.

**Модели релизов (с 2024 года):**
- **LTS (Long Term Support):** Стабильные версии (например, **8.4 LTS**). Предназначены для критических Production-систем. Поддержка — до 8 лет.
- **Innovation:** Версии для быстрого внедрения новых функций (например, **9.0**, **26.7**). Каждая версия поддерживается только до выхода следующей (каждые 3 месяца).

## Базовые концепции

### Репозитории Oracle vs Стандартные репозитории ОС
Стандартные репозитории дистрибутивов (Ubuntu 24.04, RHEL 9) часто содержат устаревшие версии (например, 8.0). Для получения **8.4 LTS** или **Innovation** необходимо подключать официальные репозитории Oracle через пакеты конфигурации.

### Безопасность и аутентификация
- **Аутентификация:** По умолчанию используется `caching_sha2_password`. Плагин `mysql_native_password` в версии 8.4 требует явной активации, а в версии 9.0+ **полностью удален**.
- **Безопасная установка:** Скрипт `mysql_secure_installation` является обязательным шагом для удаления тестовых данных и настройки политики паролей. Подробнее см. в **[Безопасная установка СУБД](../installation_security.md)**.

## Практические сценарии

### 1. Установка на Debian / Ubuntu (24.04+)

На Ubuntu выбор версии осуществляется через интерактивный конфигуратор.

```bash
# 1. Загрузка конфигуратора репозитория (версия может обновляться)
wget https://dev.mysql.com/get/mysql-apt-config_0.8.39-1_all.deb

# 2. Установка конфигуратора
sudo dpkg -i mysql-apt-config_0.8.39-1_all.deb
# -> В меню выберите "MySQL Server & Cluster" -> "mysql-8.4-lts" или "mysql-innovation"

# 3. Установка сервера
sudo apt update
sudo apt install -y mysql-server

# 4. Запуск службы
sudo systemctl enable --now mysql
```

### 2. Установка на Rocky Linux / RHEL / AlmaLinux (9.x)

Управление версиями в RHEL-системах выполняется через переключение под-репозиториев.

```bash
# 1. Установка пакета репозитория
sudo dnf install -y https://dev.mysql.com/get/mysql84-community-release-el9-1.noarch.rpm

# 2. Переключение на ветку Innovation (опционально, по умолчанию включена 8.4 LTS)
# sudo dnf config-manager --disable mysql-8.4-lts-community
# sudo dnf config-manager --enable mysql-innovation-community

# 3. Установка сервера
sudo dnf install -y mysql-community-server

# 4. Запуск службы
sudo systemctl enable --now mysqld
```

### 3. Начальная настройка и безопасность

**Для RHEL/Rocky Linux:** Найдите временный пароль root в логах:
```bash
sudo grep 'temporary password' /var/log/mysqld.log
```

**Для всех систем:** Запустите процедуру укрепления защиты:
```bash
sudo mysql_secure_installation
```
Рекомендуемые ответы: `Y` (включить VALIDATE PASSWORD), выбор уровня сложности `2` (Strong), `Y` для удаления анонимных пользователей и запрета удаленного входа root.

### 4. Базовая работа с пользователями

Подключитесь к серверу под root:
```bash
sudo mysql -u root -p
```

Создание базы данных и пользователя с современными требованиями безопасности:
```sql
-- Создание базы
CREATE DATABASE production_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Создание пользователя (plugin caching_sha2_password по умолчанию)
CREATE USER 'app_user'@'localhost' IDENTIFIED BY 'VeryStrong_Password_2026!';

-- Назначение прав
GRANT ALL PRIVILEGES ON production_db.* TO 'app_user'@'localhost';

-- Применение изменений
FLUSH PRIVILEGES;
```

## Дополнительная информация

### Управление службой
| Команда | Описание |
| :--- | :--- |
| `systemctl status mysql` | Проверка состояния (Ubuntu) |
| `systemctl status mysqld` | Проверка состояния (RHEL/Rocky) |
| `journalctl -u mysql` | Просмотр системных логов |

### См. также
- **[MySQL в Docker](./docker.md)** — развертывание в изолированных контейнерах.
- **[Обзор MySQL и форков](./overview.md)** — архитектура и внутренние механизмы.
- **[Конфигурация my.cnf](./configuration.md)** — тюнинг параметров производительности.
- **[Мониторинг MySQL](./monitoring.md)** — настройка Zabbix и Prometheus.
