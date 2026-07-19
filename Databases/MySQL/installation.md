# Установка и начало работы с MySQL

## Определения

**MySQL Server (`mysql-server`)** — серверная часть реляционной системы управления базами данных (СУБД), представляющая собой системную службу `mysqld` для обработки запросов и управления данными.

**MySQL Client (`mysql`)** — консольная клиентская утилита для интерактивного взаимодействия с сервером MySQL и выполнения SQL-запросов.

## Основные концепции

### Клиент-серверная модель

MySQL функционирует как фоновый процесс-сервер (`mysqld`), который принимает, обрабатывает и отвечает на запросы. Пользователи взаимодействуют с данными через клиентские приложения или утилиты, отправляя команды по протоколу TCP/IP или через локальные сокеты.

### Особенности версии 8.4 LTS

На июль 2026 года основной стабильной версией является **MySQL 8.4 LTS**. Ключевые изменения:
- **Аутентификация:** По умолчанию используется плагин `caching_sha2_password`. Старый плагин `mysql_native_password` отключен по умолчанию и требует ручной активации в `my.cnf` для легаси-приложений.
- **Безопасность:** Рекомендуется использование `mysql_secure_installation` сразу после развертывания.

Подробный процесс укрепления защиты описан в руководстве **[Безопасная установка СУБД](../installation_security.md)**.

## Практические сценарии

### 1. Установка на Debian/Ubuntu (24.04/26.04)

В современных версиях Ubuntu пакеты MySQL 8.4 LTS доступны в официальных репозиториях.

```bash
# Обновление индексов пакетов
sudo apt update

# Установка сервера
sudo apt install -y mysql-server

# Запуск и добавление в автозагрузку
sudo systemctl enable --now mysql

# Проверка статуса
sudo systemctl status mysql
# -> ● mysql.service - MySQL Community Server
# ->    Active: active (running) ...
```

### 2. Установка на Rocky Linux / RHEL / CentOS

Для получения версии 8.4 LTS на RHEL-совместимых системах рекомендуется использовать официальный репозиторий MySQL.

```bash
# Установка конфигурации репозитория MySQL 8.4 LTS
sudo dnf install -y https://dev.mysql.com/get/mysql84-community-release-el9-1.noarch.rpm

# Отключение встроенного модуля mysql (если есть)
sudo dnf -y module disable mysql

# Установка сервера
sudo dnf install -y mysql-community-server

# Запуск и добавление в автозагрузку
sudo systemctl enable --now mysqld
```

### 3. Начальная настройка безопасности

**Для Rocky Linux / RHEL:** Сначала найдите временный пароль root, сгенерированный при установке:
```bash
sudo grep 'temporary password' /var/log/mysqld.log
```

**Для всех систем:** Запустите скрипт защиты:
```bash
sudo mysql_secure_installation
```
Следуйте инструкциям: установите сложный пароль, удалите анонимных пользователей и тестовую БД.

### 4. Базовые операции в клиенте mysql

**Подключение к серверу:**

```bash
# Локальное подключение под root (через sudo или с паролем)
sudo mysql -u root -p

# Подключение под обычным пользователем
mysql -u my_user -p
```

**Работа с данными:**

```sql
-- Просмотр списка баз данных
SHOW DATABASES;

-- Создание новой базы данных
CREATE DATABASE project_db;

-- Создание пользователя (MySQL 8.0+)
CREATE USER 'dev_user'@'localhost' IDENTIFIED BY 'StrongPassword123!';
GRANT ALL PRIVILEGES ON project_db.* TO 'dev_user'@'localhost';
FLUSH PRIVILEGES;
```

## Дополнительная информация

- **[MySQL в Docker](./docker.md)** — развертывание в изолированных контейнерах.
- **[Настройка MariaDB](../MariaDB/installation_and_setup.md)** — установка альтернативного форка.
- **[Автоматизация через Ansible](../../Ansible/examples/mysql_setup.md)** — готовые роли для установки.

### См. также
- **[Обзор MySQL и форков](./overview.md)**
- **[Конфигурация my.cnf](./configuration.md)**
- **[Мониторинг MySQL](./monitoring.md)**
