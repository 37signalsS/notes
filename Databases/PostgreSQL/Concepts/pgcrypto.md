# pgcrypto: Криптография в PostgreSQL

## Определения

**pgcrypto** — основное расширение PostgreSQL для выполнения криптографических операций (хеширование, шифрование, генерация случайных данных) непосредственно на уровне SQL.

*   **Encryption at Rest (Шифрование данных в покое):** Защита данных на дисках и в бэкапах. pgcrypto реализует это на уровне отдельных столбцов (Column-level encryption).
*   **HMAC (Keyed-Hash Message Authentication Code):** Код аутентификации сообщений с использованием секретного ключа, гарантирующий целостность и подлинность.
*   **Соль (Salt):** Случайные данные, добавляемые к паролю перед хешированием для защиты от перебора.
*   **Blind Index (Слепой индекс):** Техника создания хешированного индекса для поиска по зашифрованным данным без их расшифровки.

## Установка и безопасность

Для обеспечения принципа наименьших привилегий рекомендуется устанавливать расширение в отдельную схему.

### Алгоритм установки

1.  Создание схемы и установка:
    ```sql
    CREATE SCHEMA crypto;
    CREATE EXTENSION pgcrypto SCHEMA crypto;
    ```
2.  Ограничение доступа:
    ```sql
    -- Отозвать права у всех
    REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA crypto FROM PUBLIC;
    
    -- Выдать права конкретной роли приложения
    GRANT USAGE ON SCHEMA crypto TO app_user;
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA crypto TO app_user;
    ```

## Хеширование данных

### Общие хеш-функции
Предназначены для проверки целостности.

*   **`digest(data, algorithm)`:** Вычисляет хеш. Рекомендуются `sha256`, `sha512`.
    *   *Пример:* `SELECT crypto.digest('data', 'sha256');`
*   **`hmac(data, key, algorithm)`:** Хеш с использованием секретного ключа. Подтверждает целостность и авторство.

### Хранение паролей (bcrypt и Argon2)

1.  **bcrypt (Стандарт pgcrypto):**
    ```sql
    -- Создание хеша (алгоритм blowfish 'bf', сложность 10)
    INSERT INTO users (username, pass_hash) 
    VALUES ('admin', crypto.crypt('password', crypto.gen_salt('bf', 10)));

    -- Проверка при входе
    SELECT (pass_hash = crypto.crypt('entered_password', pass_hash)) AS is_valid
    FROM users WHERE username = 'admin';
    ```
2.  **Argon2 (Современный стандарт):**
    В PG 17 нативно отсутствует. Рекомендуется использовать расширение `pg_pwhash` или хешировать в приложении.
    ```sql
    -- Пример со сторонним расширением pg_pwhash (если установлено)
    SELECT argon2id_hash('password');
    ```

## Шифрование данных

### Симметричное шифрование (AES)
Использует один ключ. Рекомендуемый стандарт — **AES-256-CBC**.

*   **Пример вставки (AES-256-CBC):**
    ```sql
    INSERT INTO users (username, api_key)
    VALUES ('dev_user', crypto.encrypt_iv(
        convert_to('my_secret_key', 'utf8'),
        crypto.digest('my_master_key', 'sha256'), -- Ключ 32 байта
        crypto.gen_random_bytes(16),              -- IV
        'aes-cbc'
    ));
    ```

### Асимметричное шифрование (PGP)
Использует пару ключей. Совместимо с OpenPGP.

*   `pgp_pub_encrypt()` / `pgp_pub_decrypt()`:
    ```sql
    -- Шифрование на публичном ключе
    INSERT INTO secure_messages (content)
    VALUES (crypto.pgp_pub_encrypt('secret message', crypto.dearmor(:'public_key')));
    ```

## Генерация идентификаторов и UUID

1.  **UUIDv4 (Случайный):**
    Встроено в ядро (PG 13+). Расширение не требуется.
    ```sql
    SELECT gen_random_uuid();
    ```
2.  **UUIDv7 (Сортируемый, стандарт 2026):**
    Рекомендуется для первичных ключей. Требует расширения `pg_uuidv7` или генерации в приложении.
    ```sql
    -- С расширением pg_uuidv7
    SELECT uuidv7();
    ```

## Интеграция с Vault через сессионные переменные

Безопасный способ передачи ключей из приложения в БД без их логирования.

```sql
-- В приложении при открытии транзакции:
-- SET LOCAL app.encryption_key = 'key_from_vault_transit';

-- В SQL:
SELECT crypto.decrypt_iv(
    api_key, 
    crypto.digest(current_setting('app.encryption_key'), 'sha256'),
    iv,
    'aes-cbc'
) FROM users;
```

## Практические сценарии

### 1. Поиск по зашифрованным данным (Blind Index)
Поскольку шифрование с IV недетерминировано, для поиска используется HMAC-индекс.

```sql
-- 1. Создание таблицы со "слепым" индексом
CREATE TABLE sensitive_data (
    id serial PRIMARY KEY,
    val_enc bytea,              -- Зашифрованное значение
    val_blind_idx bytea         -- HMAC-хеш для поиска
);

-- 2. Вставка данных
INSERT INTO sensitive_data (val_enc, val_blind_idx)
VALUES (
    crypto.encrypt_iv('secret_val', 'key', 'iv', 'aes-cbc'),
    crypto.hmac('secret_val', 'indexing_key', 'sha256') -- 'indexing_key' хранится отдельно
);

-- 3. Создание индекса
CREATE INDEX idx_sensitive_blind ON sensitive_data (val_blind_idx);

-- 4. Быстрый поиск
SELECT * FROM sensitive_data 
WHERE val_blind_idx = crypto.hmac('secret_val', 'indexing_key', 'sha256');
```

### 2. Контроль подлинности (HMAC-аудит)
```sql
INSERT INTO audit_logs (log_data, signature)
VALUES ('data', encode(crypto.hmac('data', 'audit_secret', 'sha256'), 'hex'));
```

### 3. Использование PGP для внешнего обмена
```sql
SELECT crypto.pgp_pub_decrypt(raw_data, crypto.dearmor(:'private_key_bin')) FROM partner_imports;
```

## Сравнение методов защиты

| Метод | Уровень | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **pgcrypto** | Столбец | Гранулярность, PCI DSS. | Нагрузка на CPU. |
| **TDE** | ФС | Прозрачность. | Не защищает от SQL-инъекций. |
| **Vault Transit** | CaaS | Центр управления ключами. | Сетевые задержки. |

### См. также
*   [Безопасность PostgreSQL](../Operations/security_hardening.md)
*   [Вспомогательные расширения](./extensions_utility.md)
*   [Масштабирование PostgreSQL](./scaling.md)
*   [Официальная документация pgcrypto](https://www.postgresql.org/docs/current/pgcrypto.html)
