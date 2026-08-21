# Шифрование данных на диске (TDE) в MariaDB

MariaDB поддерживает шифрование таблиц InnoDB с использованием внешних менеджеров ключей. Подробная теория (DEK/KEK, Envelope Encryption, AES-XTS) описана в **[Шифрование данных в покое](../../Concepts/encryption_at_rest.md)**.

## Вариант А: File Key Management (Простой)

Ключи хранятся в зашифрованном файле.

### Подготовка файла ключей

```bash
# Создание ключа шифрования для файла ключей
openssl rand -hex 32 > /etc/mysql/encryption/master.key

# Создание файла ключей в формате: ID;HEX_KEY
# Ключ с ID=1 используется по умолчанию для новых таблиц
echo "1;$(openssl rand -hex 32)" > /etc/mysql/encryption/keyfile.enc
echo "2;$(openssl rand -hex 32)" >> /etc/mysql/encryption/keyfile.enc

# Шифрование файла ключей мастер-ключом
openssl enc -aes-256-cbc -salt -in /etc/mysql/encryption/keyfile.enc \
  -out /etc/mysql/encryption/keyfile.enc.enc \
  -pass file:/etc/mysql/encryption/master.key

# Установка прав доступа
chmod 600 /etc/mysql/encryption/master.key
chmod 600 /etc/mysql/encryption/keyfile.enc.enc
```

### Настройка `my.cnf`

```ini
[mariadb]
plugin_load_add = file_key_management
file_key_management_filename = /etc/mysql/encryption/keyfile.enc.enc
file_key_management_filekey  = FILE:/etc/mysql/encryption/master.key
file_key_management_encryption_algorithm = AES_CTR

# Активация шифрования
innodb_encrypt_tables    = ON
innodb_encryption_threads = 4
innodb_encryption_rotate_key_age = 1
```

## Вариант Б: Интеграция с HashiCorp Vault (Advanced)

Требует плагина `hashicorp_key_management`. Автоматическая ротация ключей без перезапуска сервера.

```ini
[mariadb]
plugin_load_add = hashicorp_key_management
hashicorp_key_management_vault_url = https://vault.internal:8200
hashicorp_key_management_token     = s.xxxxxx
hashicorp_key_management_path      = secret/mariadb-keys
```

Подробнее об интеграции с Vault: **[HashiCorp Vault](../../../Vault/overview.md)**.

## Шифрование существующих таблиц

```sql
-- Включение шифрования для таблицы
ALTER TABLE orders ENCRYPTION='Y';

-- Проверка статуса шифрования всех таблиц
SELECT NAME, ENCRYPTION_SCHEME
FROM information_schema.INNODB_TABLESPACES_ENCRYPTION;
-- → orders | 1
-- → users  | 1

-- Проверка текущих настроек шифрования
SHOW VARIABLES LIKE 'innodb_encrypt%';
-- → innodb_encrypt_tables = ON
-- → innodb_encryption_threads = 4
-- → innodb_encryption_rotate_key_age = 1
```

## Верификация TDE

```bash
# Проверка, что данные на диске действительно зашифрованы
# (после включения innodb_encrypt_tables = ON)
hexdump -C /var/lib/mysql/testdb/orders.ibd | head -5
# → Если зашифровано, данные будут выглядеть как случайный набор байт
# → Если не зашифровано, видны текстовые данные
```

## См. также

- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Шифрование данных в покое](../../Concepts/encryption_at_rest.md)** — теория TDE, DEK/KEK, Envelope Encryption.
- **[Бинарное логирование](binary-logging.md)** — шифрование бинарных логов (`binlog_encryption`).
- **[SSL/TLS](ssl-tls.md)** — шифрование данных в транзите.
- **[HashiCorp Vault](../../../Vault/overview.md)** — управление ключами шифрования.
