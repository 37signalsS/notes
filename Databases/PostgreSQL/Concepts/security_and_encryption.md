# Безопасность и шифрование в PostgreSQL

## Определения

**Transparent Data Encryption (TDE)** — прозрачное шифрование данных на уровне СУБД. В ванильном PostgreSQL (Community Edition) 17/18 нативная поддержка TDE отсутствует. Основной способ реализации — расширение `pg_tde` (от Percona) или шифрование на уровне ОС.

**pgcrypto** — стандартное расширение PostgreSQL для выполнения криптографических операций на уровне SQL. Используется для шифрования отдельных столбцов.

**Row-Level Security (RLS)** — механизм управления доступом на уровне строк. Позволяет ограничить видимость данных внутри одной таблицы для разных пользователей на основе SQL-политик.

**SCRAM-SHA-256** — современный и безопасный протокол аутентификации (Challenge-Response), являющийся стандартом в PostgreSQL 14+.

## Практические сценарии

### 1. Шифрование данных «в покое» (TDE)

Поскольку в ядре PostgreSQL 17/18 нативного TDE нет, SRE используют следующие подходы:

#### Вариант А: Расширение `pg_tde` (Percona)
Позволяет шифровать таблицы и индексы прозрачно для приложения. Поддерживает интеграцию с HashiCorp Vault.

```sql
-- 1. Подключение расширения
CREATE EXTENSION pg_tde;

-- 2. Создание таблицы с шифрованием
CREATE TABLE sensitive_data (
    id INT PRIMARY KEY,
    secret_val TEXT
) USING pg_tde;
```

#### Вариант Б: Шифрование на уровне файловой системы (LUKS / ZFS)
Рекомендуемый подход Community. Данные шифруются при записи на диск средствами ОС.
- **Плюсы:** Нулевой оверхед на уровне SQL, простота настройки, соответствие PCI DSS.
- **Минусы:** Не защищает от пользователя `postgres` (суперпользователя БД), если он скомпрометирован.

---

### 2. Шифрование на уровне столбцов (`pgcrypto`)

Используется, когда нужно защитить данные даже от администратора БД.

```sql
CREATE EXTENSION pgcrypto;

-- Шифрование данных (AES)
INSERT INTO users (username, password_enc) 
VALUES ('admin', pgp_sym_encrypt('my_super_secret', 'my_key'));

-- Чтение данных
SELECT pgp_sym_decrypt(password_enc, 'my_key') FROM users WHERE username = 'admin';
```
*Важно: Индексы на зашифрованных столбцах неэффективны для поиска.*

---

### 3. Защита трафика (SSL/TLS)

#### Настройка сервера (`postgresql.conf`)
```ini
ssl = on
ssl_cert_file = 'server.crt'
ssl_key_file = 'server.key'
ssl_min_protocol_version = 'TLSv1.2'
```

#### Принудительный SSL для пользователей (`pg_hba.conf`)
Замените `host` на `hostssl`, чтобы запретить незашифрованные подключения.
```
# TYPE  DATABASE        USER            ADDRESS                 METHOD
hostssl all             all             0.0.0.0/0               scram-sha-256
```

---

### 4. Row-Level Security (RLS)

Сценарий: Пользователь видит только свои записи в таблице `orders`.

```sql
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_orders_policy ON orders
    USING (user_id = current_user_id());
```

## Сравнение методов защиты данных

| Метод | Уровень | Прозрачность | Защита от админа БД |
| :--- | :--- | :--- | :--- |
| **LUKS / AWS EBS Enc** | Диск | Высокая | Нет |
| **pg_tde (Percona)** | Таблица | Высокая | Частично |
| **pgcrypto** | Столбец | Низкая (SQL) | Да |
| **RLS** | Строка | Средняя | Нет |

## Дополнительная информация

### Смежные темы
- **[Теория шифрования в покое (SSoT)](../../Concepts/encryption_at_rest.md)** — общие принципы DEK/KEK.
- **[pgcrypto: Детальное руководство](./pgcrypto.md)** — криптографические функции SQL.
- **[Безопасность MariaDB](../../MariaDB/security/index.md)** — реализация TDE в MariaDB.
- **[Безопасность MySQL](../../MySQL/security.md)** — Keyring плагины в MySQL.
