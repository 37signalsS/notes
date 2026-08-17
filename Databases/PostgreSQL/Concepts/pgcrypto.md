# pgcrypto: Криптография в PostgreSQL

## Определения

**pgcrypto** — основное расширение PostgreSQL для выполнения криптографических операций (хеширование, шифрование, генерация случайных данных) непосредственно на уровне SQL.

*   **Encryption at Rest (Шифрование данных в покое):** Защита данных на дисках и в бэкапах. `pgcrypto` реализует это на уровне отдельных столбцов (Column-level encryption), дополняя общесистемное шифрование ФС.
*   **KDF (Key Derivation Function):** Функция формирования ключа, преобразующая пароль или мастер-ключ в криптографически стойкий ключ заданной длины (например, через `digest`).
*   **HMAC (Keyed-Hash Message Authentication Code):** Код аутентификации сообщений с использованием секретного ключа. Гарантирует не только целостность, но и подлинность данных.
*   **IV (Initialization Vector):** Случайное значение, используемое вместе с ключом для обеспечения уникальности шифротекста при одинаковых исходных данных.
*   **Соль (Salt):** Случайные данные, добавляемые к паролю перед хешированием для защиты от перебора по словарям и радужным таблицам.
*   **Blind Index (Слепой индекс):** Техника создания хешированного индекса для поиска по зашифрованным данным без их расшифровки.

## Установка и безопасность

Для обеспечения принципа наименьших привилегий и защиты от утечки ключей через логи, рекомендуется устанавливать расширение в выделенную схему.

### Алгоритм установки

1.  **Создание схемы и установка:**
    ```sql
    CREATE SCHEMA crypto;
    CREATE EXTENSION pgcrypto SCHEMA crypto;
    ```
2.  **Ограничение доступа (Best Practice):**
    ```sql
    -- Отозвать права у всех (включая PUBLIC)
    REVOKE ALL ON SCHEMA crypto FROM PUBLIC;
    REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA crypto FROM PUBLIC;
    
    -- Выдать права конкретной роли приложения
    GRANT USAGE ON SCHEMA crypto TO app_user;
    GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA crypto TO app_user;
    ```

## Хеширование данных

### Общие хеш-функции
Предназначены для проверки целостности. Рекомендуется использовать SHA-256 или SHA-512.

*   **`digest(data, algorithm)`:** Вычисляет прямой хеш.
    *   *Пример:* `SELECT crypto.digest('data', 'sha256');`
*   **`hmac(data, key, algorithm)`:** Хеш с использованием секретного ключа. Подтверждает целостность и авторство данных.

### Хранение паролей (bcrypt и Argon2)

1.  **bcrypt (Стандарт pgcrypto):**
    Реализует адаптивное хеширование с солью и настраиваемой сложностью.
    ```sql
    -- Создание хеша (алгоритм blowfish 'bf', сложность/cost 10)
    INSERT INTO users (username, pass_hash) 
    VALUES ('admin', crypto.crypt('password', crypto.gen_salt('bf', 10)));

    -- Проверка при входе
    SELECT (pass_hash = crypto.crypt('entered_password', pass_hash)) AS is_valid
    FROM users WHERE username = 'admin';
    ```
2.  **Argon2 (Современный стандарт):**
    В PostgreSQL 17 нативно отсутствует.
    - *Рекомендация:* Использовать расширение `pg_pwhash` или выполнять хеширование на стороне приложения (App-side hashing).
    ```sql
    -- Пример со сторонним расширением pg_pwhash (если установлено)
    SELECT argon2id_hash('password');
    ```

## Шифрование данных

### Симметричное шифрование (AES)
Использует один ключ. Рекомендуемый стандарт — **AES-256-CBC**. Никогда не используйте режим ECB, так как он небезопасен для структурированных данных.

*   **Пример вставки с IV (AES-256-CBC):**
    ```sql
    INSERT INTO users (username, api_key)
    VALUES ('dev_user', crypto.encrypt_iv(
        convert_to('my_secret_key', 'utf8'),
        crypto.digest('my_master_key', 'sha256'), -- Ключ 32 байта
        crypto.gen_random_bytes(16),              -- IV (16 байт для AES)
        'aes-cbc'
    ));
    ```

### Асимметричное шифрование (PGP)
Использует пару ключей (публичный/приватный). Совместимо с OpenPGP.

*   **`pgp_pub_encrypt()` / `pgp_pub_decrypt()`**:
    ```sql
    -- Шифрование на публичном ключе контрагента
    INSERT INTO secure_messages (content)
    VALUES (crypto.pgp_pub_encrypt('secret message', crypto.dearmor(:'public_key')));
    ```

## Генерация идентификаторов и UUID

1.  **UUIDv4 (Случайный):**
    Встроено в ядро (PG 13+). Расширение для этой функции не требуется.
    ```sql
    SELECT gen_random_uuid();
    ```
2.  **UUIDv7 (Сортируемый, стандарт 2026):**
    Идеален для первичных ключей, так как содержит временную метку, что улучшает производительность индексов B-Tree.
    ```sql
    -- Требует расширения pg_uuidv7 или генерации в приложении
    SELECT uuidv7();
    ```

## Интеграция с Vault через сессионные переменные

Безопасный способ передачи ключей шифрования из HashiCorp Vault в БД без их сохранения в логах (`pg_stat_statements`).

```sql
-- В приложении при открытии транзакции:
-- SET LOCAL app.encryption_key = 'key_from_vault_transit';

-- В SQL запросе:
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
    val_enc bytea,              -- Зашифрованное значение (AES-CBC + IV)
    val_blind_idx bytea         -- HMAC-хеш для поиска (Blind Index)
);

-- 2. Вставка данных
INSERT INTO sensitive_data (val_enc, val_blind_idx)
VALUES (
    crypto.encrypt_iv('secret_val', 'encryption_key', 'iv', 'aes-cbc'),
    crypto.hmac('secret_val', 'indexing_key', 'sha256') -- 'indexing_key' хранится отдельно
);

-- 3. Создание индекса
CREATE INDEX idx_sensitive_blind ON sensitive_data (val_blind_idx);

-- 4. Быстрый поиск (O(log n))
SELECT * FROM sensitive_data 
WHERE val_blind_idx = crypto.hmac('secret_val', 'indexing_key', 'sha256');
```

### 2. Контроль подлинности (HMAC-аудит)
Гарантирует, что записи в аудит-логе не были изменены администратором БД.
```sql
INSERT INTO audit_logs (log_data, signature)
VALUES ('data_entry', encode(crypto.hmac('data_entry', 'audit_secret', 'sha512'), 'hex'));
```

### 3. Использование PGP для внешнего обмена данными
```sql
-- Расшифровка входящего сообщения от партнера
SELECT crypto.pgp_pub_decrypt(raw_data, crypto.dearmor(:'private_key_bin')) FROM partner_imports;
```

## Типичные проблемы и Troubleshooting

1.  **Ошибка `Key length not supported`:** AES-256 требует ключ ровно 32 байта. Используйте `digest(key, 'sha256')` для подготовки ключа.
2.  **Утечка ключей в логи:** Если использовать ключи как литералы в SQL, они попадут в логи. Используйте `SET LOCAL` и `current_setting`.
3.  **Производительность:** Шифрование — ресурсозатратная операция. Выносите тяжелую криптографию на уровень приложения, если БД перегружена по CPU.

## Сравнение методов защиты

| Метод | Уровень | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- |
| **pgcrypto** | Столбец | Гранулярность, защита от доступа админа БД, соответствие PCI DSS. | Нагрузка на CPU, сложность запросов. |
| **TDE (Transparent Encryption)** | ФС | Прозрачность для приложения, нулевой оверхед на SQL. | Не защищает от SQL-инъекций или доступа с правами суперпользователя. |
| **Vault Transit (CaaS)** | Внешний | Централизованное управление ключами, ротация, аудит. | Сетевые задержки при каждом запросе. |

### См. также
*   [Безопасность PostgreSQL](../Operations/security_hardening.md)
*   [Вспомогательные расширения](./extensions_utility.md)
*   [Масштабирование PostgreSQL](./scaling.md)
*   [Официальная документация pgcrypto](https://www.postgresql.org/docs/current/pgcrypto.html)
