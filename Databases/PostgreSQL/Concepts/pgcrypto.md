# pgcrypto: Криптография в PostgreSQL

**Актуально для:** PostgreSQL 15–18

## Определения

**pgcrypto** — стандартное расширение PostgreSQL для выполнения криптографических операций (хеширование, шифрование, генерация случайных данных) непосредственно на уровне SQL. Модуль считается доверенным (`trusted`): его может установить любой пользователь с правом `CREATE` в текущей БД.

*   **Encryption at Rest (Шифрование данных в покое):** Защита данных на дисках и в бэкапах. `pgcrypto` реализует это на уровне отдельных столбцов (Column-level encryption), дополняя общесистемное шифрование ФС.
*   **KDF (Key Derivation Function):** Функция формирования ключа, преобразующая пароль или мастер-ключ в криптографически стойкий ключ заданной длины (например, через `digest`).
*   **HMAC (Keyed-Hash Message Authentication Code):** Код аутентификации сообщений с использованием секретного ключа. Гарантирует не только целостность, но и подлинность данных.
*   **IV (Initialization Vector):** Случайное значение, используемое вместе с ключом для обеспечения уникальности шифротекста при одинаковых исходных данных.
*   **Соль (Salt):** Случайные данные, добавляемые к паролю перед хешированием для защиты от перебора по словарям и радужным таблицам.
*   **Blind Index (Слепой индекс):** Техника создания хешированного индекса для поиска по зашифрованным данным без их расшифровки.
*   **Side-channel attack (Атака по сторонним каналам):** Атака, использующая косвенную информацию о работе системы (время выполнения, энергопотребление). `pgcrypto` не защищен от таких атак.
*   **FIPS mode:** Режим соответствия стандарту FIPS 140, ограничивающий использование криптографических алгоритмов. В PostgreSQL 19 появился параметр `pgcrypto.builtin_crypto_enabled = fips`.

## Предварительные требования

*   **OpenSSL:** `pgcrypto` требует OpenSSL и не собирается без него. При использовании OpenSSL 3.0+ для старых алгоритмов (DES, Blowfish) необходимо активировать legacy provider в `openssl.cnf`.
*   **zlib:** Опционально. При наличии включается сжатие данных перед шифрованием в PGP-функциях (`--with-zlib` при сборке PostgreSQL).
*   **Права:** Модуль является `trusted` — установка не требует суперпользователя, достаточно права `CREATE` в целевой БД.
*   **Аппаратура:** Для production-нагрузки выделите отдельный CPU core для интенсивной криптографии, так как операции шифрования/хеширования потребляют вычислительные ресурсы.

## Базовые концепции

### Архитектура pgcrypto

Все функции `pgcrypto` выполняются внутри процесса PostgreSQL (`postgres`). Это означает:

1.  **Данные передаются в открытом виде между клиентом и сервером.** Шифрование защищает данные на диске и в дампах, но не защищает трафик. Для защиты канала используйте SSL/TLS.
2.  **Доверие к администратору БД.** Суперпользователь `postgres` может перехватывать ключи и открытые данные из памяти. `pgcrypto` защищает от компрометации диска/бэкапа, но не от компрометации ОС или инстанса.
3.  **Использование OpenSSL.** Все криптографические примитивы делегируются библиотеке OpenSSL, установленной на хосте. Алгоритмы, доступные в `pgcrypto`, зависят от того, что поддерживает установленная версия OpenSSL и включенные провайдеры.
4.  **Отсутствие поддержки подписи.** PGP-функции `pgcrypto` реализуют только шифрование, но не цифровую подпись. Для подписи используйте внешние инструменты (GnuPG) или приложение.

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

### Параметр конфигурации (PostgreSQL 19+)

В PostgreSQL 19 появился параметр `pgcrypto.builtin_crypto_enabled`:
*   `on` (по умолчанию) — встроенные функции `gen_salt()` и `crypt()` доступны.
*   `off` — отключает встроенные функции.
*   `fips` — отключает встроенные функции, если OpenSSL работает в режиме FIPS.

Устанавливается в `postgresql.conf` или изменяется на уровне сессии суперпользователем:
```ini
pgcrypto.builtin_crypto_enabled = on
```

## Хеширование данных

### Общие хеш-функции

Предназначены для проверки целостности. Рекомендуется использовать SHA-256 или SHA-512.

*   **`digest(data, algorithm)`:** Вычисляет прямой хеш.
    *   *Пример:* `SELECT crypto.digest('data', 'sha256');`
    *   Поддерживаемые алгоритмы: `md5`, `sha1`, `sha224`, `sha256`, `sha384`, `sha512`, а также любые алгоритмы, доступные в OpenSSL.
*   **`hmac(data, key, algorithm)`:** Хеш с использованием секретного ключа. Подтверждает целостность и авторство данных.
    *   *Пример:* `SELECT crypto.hmac('data', 'secret_key', 'sha256');`

### Хранение паролей (bcrypt, sha256crypt, sha512crypt)

1.  **bcrypt (алгоритм `bf`):**
    Реализует адаптивное хеширование с солью и настраиваемой сложностью. Максимальная длина пароля — 72 байта.
    ```sql
    -- Создание хеша (алгоритм blowfish 'bf', сложность/cost 10)
    INSERT INTO users (username, pass_hash) 
    VALUES ('admin', crypto.crypt('password', crypto.gen_salt('bf', 10)));

    -- Проверка при входе
    SELECT (pass_hash = crypto.crypt('entered_password', pass_hash)) AS is_valid
    FROM users WHERE username = 'admin';
    ```
    *Примечание:* Для алгоритма `bf` допустимый диапазон `iter_count` — 4–31. Значение по умолчанию — 6. При производительности ~7000 хешей/сек на современном CPU bcrypt с cost 10 дает приемлемую задержку (~100 мс на хеш).

2.  **sha256crypt / sha512crypt (современные стандарты):**
    Встроены в pgcrypto начиная с PostgreSQL 15+. Рекомендуемый диапазон итераций — 10000–50000 (по умолчанию 5000, что documentation называет слишком низким для современного железа).
    ```sql
    -- Рекомендуется увеличить итерации
    INSERT INTO users (username, pass_hash)
    VALUES ('admin', crypto.crypt('password', crypto.gen_salt('sha256crypt', 20000)));
    ```

3.  **Argon2 (внешнее расширение):**
    В PostgreSQL 18 нативно отсутствует. Для Argon2 используйте расширение `pg_pwhash` (от Cybertec) или хеширование на стороне приложения.
    ```sql
    -- Пример со сторонним расширением pg_pwhash (если установлено)
    SELECT argon2id_hash('password');
    ```

## Шифрование данных

### Симметричное шифрование (AES)

Использует один ключ. Рекомендуемый стандарт — **AES-256-CBC** или **AES-256-GCM** (если реализован на стороне приложения, так как pgcrypto PGP по умолчанию использует `aes128`). Никогда не используйте режим ECB, так как он небезопасен для структурированных данных.

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
*   **Важность IV:** Никогда не повторно используйте IV с одним и тем же ключом. Используйте `crypto.gen_random_bytes()` для генерации криптографически стойкого IV.

### Асимметричное шифрование (PGP)

Использует пару ключей (публичный/приватный). Совместимо с OpenPGP (RFC 4880).

*   **`pgp_sym_encrypt()` / `pgp_sym_decrypt()`** — симметричное шифрование с паролем:
    ```sql
    -- Шифрование
    INSERT INTO secure_messages (content)
    VALUES (crypto.pgp_sym_encrypt('secret message', 'my_password', 'cipher-algo=aes256'));

    -- Расшифровка
    SELECT crypto.pgp_sym_decrypt(content, 'my_password') FROM secure_messages;
    ```
*   **`pgp_pub_encrypt()` / `pgp_pub_decrypt()`** — асимметричное шифрование:
    ```sql
    -- Шифрование на публичном ключе контрагента
    INSERT INTO secure_messages (content)
    VALUES (crypto.pgp_pub_encrypt('secret message', crypto.dearmor(:'public_key')));

    -- Расшифровка приватным ключом
    SELECT crypto.pgp_pub_decrypt(content, crypto.dearmor(:'private_key_bin'), 'key_password')
    FROM secure_messages;
    ```
*   **Важные опции PGP:**
    *   `cipher-algo=aes256` — выбрать алгоритм шифрования (по умолчанию `aes128`).
    *   `s2k-mode=3` — использовать адаптивный S2K с солью (рекомендуется).
    *   `compress-algo=1` — включить сжатие ZIP перед шифрованием (требует сборку с zlib).
    *   `disable-mdc` — отключить SHA-1 защиту. **Не используйте**, кроме случаев восстановления данных, зашифрованных до исправления CVE-2026-14663.

### Предупреждение о raw encryption

Функции `encrypt()` и `decrypt()` (без `_iv`) считаются устаревшими для новых проектов. Они:
1.  Используют ключ напрямую без KDF.
2.  Не проверяют целостность данных.
3.  Требуют ручного управления IV.
4.  Не работают с текстом (требуют `bytea`).

Для новых разработок используйте PGP-функции или приложение-side шифрование.

## Генерация идентификаторов и случайных данных

1.  **`gen_random_bytes(count)`:** Криптографически стойкие случайные байты. Максимум 1024 байта за вызов.
    ```sql
    SELECT encode(crypto.gen_random_bytes(16), 'hex');
    ```
2.  **`gen_random_uuid()`:** UUIDv4. В PostgreSQL 18 помечена как устаревшая (внутренне вызывает нативную функцию ядра).
    ```sql
    SELECT gen_random_uuid();
    ```
3.  **UUIDv7 (Сортируемый, RFC 9562, 2024):**
    Идеален для первичных ключей, так как содержит временную метку, что улучшает производительность индексов B-Tree.
    ```sql
    -- PostgreSQL 18+: нативная функция ядра
    SELECT uuidv7();
    -- PostgreSQL < 18: расширение pg_uuidv7 или генерация в приложении
    ```
    Подробное сравнение стратегий генерации ID — в **[Генерация идентификаторов](../../Concepts/id_generation.md)**.
4.  **`fips_mode()`:** Возвращает `true`, если OpenSSL работает в режиме FIPS.
    ```sql
    SELECT crypto.fips_mode();
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

*Важно:* Параметр `app.encryption_key` должен быть настроен через `ALTER SYSTEM` или `SET LOCAL`, но никогда не передаваться как литерал в SQL — иначе он попадет в логи и `pg_stat_statements`.

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
    crypto.encrypt_iv('secret_val', 'encryption_key', crypto.gen_random_bytes(16), 'aes-cbc'),
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

### 4. Ротация мастер-ключей

Сценарий для SRE: требуется сменить мастер-ключ шифрования без простоя.
```sql
-- 1. Создать новую версию ключа
ALTER TABLE users ADD COLUMN api_key_v2 bytea;

-- 2. Перешифровать на новом ключе (пакетно)
UPDATE users SET api_key_v2 = crypto.encrypt_iv(
    crypto.decrypt_iv(api_key, old_key, iv, 'aes-cbc'),
    new_key,
    crypto.gen_random_bytes(16),
    'aes-cbc'
);

-- 3. После проверки удалить старый столбец
ALTER TABLE users DROP COLUMN api_key;
ALTER TABLE users RENAME COLUMN api_key_v2 TO api_key;
```

### 5. Валидация установки

```sql
-- Проверка версии расширения
SELECT extversion FROM pg_extension WHERE extname = 'pgcrypto';
-- Ожидаемо: 1.3 (для PG 15–18)

-- Проверка поддержки алгоритмов
SELECT crypto.digest('test', 'sha256') IS NOT NULL AS sha256_ok;
SELECT crypto.hmac('test', 'key', 'sha512') IS NOT NULL AS hmac_ok;
SELECT crypto.gen_random_bytes(16) IS NOT NULL AS random_ok;

-- Проверка FIPS режима
SELECT crypto.fips_mode() AS is_fips;
```

## Лучшие практики и очистка

*   **Хранение ключей:** Никогда не храните мастер-ключи в базе данных или конфигурационных файлах на диске. Используйте внешние системы: HashiCorp Vault, AWS KMS, HSM. Передавайте ключи в сессию через `SET LOCAL`.
*   **Алгоритмы:** Для паролей используйте `sha256crypt`/`sha512crypt` с `iter_count >= 20000` или bcrypt с cost >= 10. Для данных — AES-256 через PGP (`cipher-algo=aes256`) или `encrypt_iv` с `aes-cbc`.
*   **IV и соль:** Всегда используйте `crypto.gen_random_bytes()` для IV и `gen_salt()` для соли. Никогда не генерируйте их через `random()`.
*   **Индексы:** Не создавайте индексы на зашифрованных столбцах напрямую. Используйте Blind Index (HMAC) или храните хеш отдельно.
*   **Мониторинг CPU:** Шифрование нагружает CPU. Мониторьте `pg_stat_activity` и системные метрики. При росте latency рассмотрите вынос криптографии на уровень приложения или выделение крипто-процессов.
*   **OpenSSL 3 legacy provider:** Если используете DES, MD5 или Blowfish, убедитесь, что legacy provider активирован. Иначе `crypt('bf', ...)` вернет ошибку.
*   **Ротация ключей:** Планируйте ротацию мастер-ключей раз в 90–180 дней. Используйте версионирование столбцов (`api_key_v2`) для плавного перехода.
*   **Резервное копирование:** Бэкапы зашифрованных данных не защищены старым ключом после ротации. Убедитесь, что ключи ротации доступны для восстановления.

### Откат и очистка

1.  **Удаление расширения:**
    ```sql
    DROP EXTENSION pgcrypto;
    ```
    *Примечание:* Удаление расширения не удаляет данные из зашифрованных столбцов. Они становятся нечитаемыми.

2.  **Миграция с raw encryption на PGP:**
    ```sql
    -- Пример миграции столбца
    ALTER TABLE users ADD COLUMN secret_pgp bytea;
    UPDATE users SET secret_pgp = pgp_sym_encrypt(
        convert_from(decrypt(secret_raw, 'old_key', 'aes-cbc'), 'utf8'),
        'new_key'
    );
    ALTER TABLE users DROP COLUMN secret_raw;
    ALTER TABLE users RENAME COLUMN secret_pgp TO secret;
    ```

## Типичные проблемы и Troubleshooting

1.  **Ошибка `Key length not supported`:** AES-256 требует ключ ровно 32 байта. Используйте `digest(key, 'sha256')` для подготовки ключа.
2.  **Утечка ключей в логи:** Если использовать ключи как литералы в SQL, они попадут в логи. Используйте `SET LOCAL` и `current_setting`.
3.  **Ошибка `provider: legacy provider not available`:** При использовании OpenSSL 3.0+ и старых алгоритмов (DES, Blowfish) активируйте legacy provider в `openssl.cnf`:
    ```ini
    [provider_sect]
    activate = 1
    ```
4.  **Ошибка `decryption failed` после обновления OpenSSL:** Возможно, затронута работа CVE-2026-14663. Для восстановления данных можно использовать опцию `ignore-cipher-failure=1`, но это небезопасно и предназначено только для аварийного восстановления.
5.  **Производительность:** Шифрование — ресурсозатратная операция. Выносите тяжелую криптографию на уровень приложения, если БД перегружена по CPU. Мониторьте нагрузку через `pg_stat_activity` и `perf`.
6.  **NULL-безопасность:** Все функции `pgcrypto` возвращают `NULL`, если любой аргумент `NULL`. Это может создать уязвимости при неосторожном использовании (например, незаметная потеря ключа).
7.  **Ограничение `gen_random_bytes`:** Функция возвращает не более 1024 байт за вызов. Для генерации больших объемов используйте цикл или `repeat()`.

## Валидация pgcrypto

```sql
-- Статус расширения
SELECT extname, extversion, extrelocatable FROM pg_extension WHERE extname = 'pgcrypto';
-- Ожидаемо: pgcrypto, версия 1.3, relocatable = true

-- Проверка работоспособности функций
SELECT 
    crypto.digest('test', 'sha256') AS sha256_works,
    crypto.hmac('test', 'key', 'sha512') AS hmac_works,
    crypto.gen_random_bytes(16) IS NOT NULL AS random_works,
    crypto.fips_mode() AS fips_enabled;

-- Проверка сжатия (если собрано с zlib)
SELECT pgp_sym_encrypt('test', 'key', 'compress-algo=1') IS NOT NULL AS compress_ok;
```

## Сравнение методов защиты

| Метод | Уровень | Прозрачность | Защита от админа БД | Производительность | Требования |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **pgcrypto** | Столбец | Низкая (SQL) | Да | Средняя (нагружает CPU) | OpenSSL |
| **pgcrypto raw (`encrypt_iv`)** | Столбец | Низкая (SQL) | Да | Высокая | Нет KDF, нет целостности |
| **TDE (pg_tde)** | Таблица | Высокая | Частично | Низкая | Расширение pg_tde |
| **LUKS / ZFS** | Диск | Высокая | Нет | Нулевая | ОС |
| **Vault Transit** | Внешний | Средняя | Да | Сетевая задержка | Vault + сеть |

### См. также
*   [Безопасность и шифрование PostgreSQL](../Concepts/security_and_encryption.md)
*   [Вспомогательные расширения](./extensions_utility.md)
*   [Масштабирование PostgreSQL](./scaling.md)
*   [Официальная документация pgcrypto](https://www.postgresql.org/docs/current/pgcrypto.html)
*   [pg_pwhash — современные алгоритмы хеширования](https://github.com/cybertec-postgresql/pg_pwhash)
