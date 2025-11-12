# PostgreSQL: Обзор и установка

**PostgreSQL** — это мощная, объектно-реляционная система управления базами данных с открытым исходным кодом. Она является одной из популярных СУБД для проектов различных уровней: от стартапа до высоконагруженной системы. PostgreSQL заслужила репутацию надежной, функциональной и производительной СУБД, подходящей для широкому кругу задач.

---

## Ключевые особенности

-   **Надежность и соответствие стандартам:** Строгое следование стандарту SQL и поддержка транзакций ([ACID](../Concepts/acid.md)).
-   **Расширяемость:** Позволяет определять собственные типы данных, операторы и функции, а также имеет масштабируемую систему встроенных языков программирования.
-   **Объектно-реляционная модель:** Поддержка наследования, сложных объектов и других концепций ООП.
-   **Кроссплатформенность:** Работает на большинстве операционных систем, включая Linux, Windows, macOS.
-   **Геопространственные данные:** Возможность индексирования геообъектов.
-   **Репликация и транзакции:** Устойчивые и надежные функции репликаций и транзакций.

---

### Установка и использование в Ubuntu 20.04

#### 1. Настройка сервера

Перед установкой рекомендуется настроить брандмауэр.

```bash
# Обновление пакетов
sudo apt update

# Установка UFW (Uncomplicated Firewall)
sudo apt install ufw

# Разрешить подключения по SSH
sudo ufw allow OpenSSH

# Включить брандмауэр
sudo ufw enable

# Проверить статус
sudo ufw status
```

#### 2. Установка PostgreSQL

```bash
# Обновляем списки пакетов
sudo apt update

# Устанавливаем PostgreSQL и пакет с дополнительными утилитами
sudo apt install postgresql postgresql-contrib

# Запускаем сервис
sudo systemctl start postgresql.service

# Проверяем статус сервиса
sudo systemctl status postgresql.service
```

#### 3. Работа с ролями и базами данных

При установке PostgreSQL создает пользователя `postgres`, который является суперпользователем в СУБД.

**Подключение к консоли `psql`:**

```bash
# Переключиться на системного пользователя postgres
sudo -i -u postgres

# Запустить консоль psql
psql

# Проверить информацию о текущем соединении
\conninfo

# Выйти из psql
\q

# Выйти из сессии пользователя postgres
exit
```

**Создание новой роли (пользователя):**

```bash
# Запуск интерактивного создания пользователя от имени postgres
sudo -u postgres createuser --interactive

# Введите имя роли, например, 'tester'
# На вопрос "Shall the new role be a superuser?" ответьте 'y' или 'n'
```

**Создание новой базы данных:**

```bash
# Создать базу данных с именем 'tester'
sudo -u postgres createdb tester
```

#### 4. Работа с таблицами

**Подключение к БД от имени нового пользователя:**

```bash
# Создаем системного пользователя с таким же именем, как и роль
sudo adduser tester

# Переключаемся на нового пользователя и подключаемся к psql
# (по умолчанию psql пытается подключиться к БД с именем текущего пользователя)
sudo -u tester psql
```

**Создание таблицы:**

```sql
CREATE TABLE snowboarder (
    equip_id serial PRIMARY KEY,
    title varchar (50) NOT NULL,
    company varchar (25) NOT NULL,
    size varchar (25) check (size in ('XS', 'S', 'M', 'L', 'XL', 'XXL'))
);
```

**Просмотр таблиц:**
```sql
-- Показать все отношения (таблицы, последовательности)
\d

-- Показать только таблицы
\dt
```

**Манипулирование данными:**

```sql
-- Вставка данных
INSERT INTO snowboarder (title, company, size) VALUES ('snowboard', 'burton', 'XL');

-- Выборка данных
SELECT * FROM snowboarder;

-- Обновление данных
UPDATE snowboarder SET company = 'blackfire' WHERE title = 'boots';

-- Удаление данных
DELETE FROM snowboarder WHERE title = 'binding';
```

**Изменение структуры таблицы:**

```sql
-- Добавление столбца
ALTER TABLE snowboarder ADD price varchar (25);

-- Удаление столбца
ALTER TABLE snowboarder DROP price;
```

**Удаление таблицы:**
```sql
DROP TABLE snowboarder;
```

#### 5. Установка phpPgAdmin (опционально)

`phpPgAdmin` — это веб-интерфейс для администрирования PostgreSQL.

```bash
sudo apt-get install phppgadmin
```
После установки необходимо отредактировать файл конфигурации Apache (`/etc/apache2/conf-available/phppgadmin.conf`), чтобы разрешить доступ не только с локальной машины.

```apache
# Закомментировать 'Require local'
# Require local
# Добавить 'Allow From all'
Allow From all
```
Перезапустите Apache:
```bash
sudo systemctl restart apache2
```

#### 6. Удаление PostgreSQL

```bash
# Остановить сервис
sudo systemctl stop postgresql

# Удалить пакеты и конфигурационные файлы
sudo apt-get --purge remove postgresql\*

# Удалить оставшиеся директории и системного пользователя
sudo rm -r /etc/postgresql/
sudo rm -r /var/lib/postgresql/
sudo userdel -r postgres
sudo groupdel postgres
```

