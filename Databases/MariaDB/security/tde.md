# Шифрование данных на диске (TDE) в MariaDB

**Актуально для:** MariaDB 10.5+ / 11.x / 12.x

## Определения

**TDE (Transparent Data Encryption)** — прозрачное шифрование данных на уровне СУБД. В MariaDB реализуется через шифрование табличных пространств InnoDB. Приложение работает с данными обычным образом через SQL, а шифрование и расшифровка происходят автоматически при чтении/записи на диск.

**DEK (Data Encryption Key)** — ключ шифрования данных, используемый непосредственно для шифрования страниц InnoDB. Каждое табличное пространство имеет собственный DEK, хранящийся в заголовке табличного пространства в зашифрованном виде.

**KEK (Key Encryption Key) / Master Key** — ключ более высокого уровня, используемый для шифрования DEK. В MariaDB KEK хранится во внешнем хранилище (файловый keyring или HashiCorp Vault) и никогда не попадает на диск в открытом виде.

**Envelope Encryption (Конвертное шифрование)** — иерархическая модель, где данные шифруются DEK, а сам DEK шифруется KEK. Для расшифровки данных необходимы оба ключа: DEK (рядом с данными) и KEK (во внешнем хранилище).

**file_key_management** — плагин MariaDB для файлового хранилища ключей. Ключи хранятся в зашифрованном файле на том же сервере. Подходит для тестовых сред; в production требует отдельного хранения файла ключей.

**hashicorp_key_management** — плагин MariaDB для интеграции с HashiCorp Vault. KEK никогда не покидает Vault в открытом виде; MariaDB получает DEK только по авторизованному запросу.

**innodb_encrypt_log** — переменная MariaDB, включающая шифрование redo-логов InnoDB. В MySQL аналогичная функциональность реализована через `innodb_redo_log_encrypt` и `innodb_undo_log_encrypt`.

## Основные концепции

### Архитектура TDE в MariaDB

MariaDB использует двухуровневую иерархию ключей:

1. Каждое зашифрованное табличное пространство InnoDB имеет уникальный **DEK** — им шифруются страницы данных (алгоритм AES, по умолчанию `AES_CTR` через `file_key_management_encryption_algorithm`).
2. DEK хранится в заголовке табличного пространства только в зашифрованном виде — «обернутым» **KEK**.
3. KEK запрашивается у хранилища ключей при старте сервера и никогда не попадает на диск в открытом виде.
4. Ротация KEK перешифровывает только обертку DEK (быстрая операция), сами данные не перезаписываются.

### Что защищает и не защищает TDE в MariaDB

**TDE защищает:**
- Табличные пространства InnoDB (файлы `.ibd`)
- Redo-логи InnoDB (при включении `innodb_encrypt_log = ON`)
- Бинарные логи (при включении `binlog_encryption = ON` — требует предварительной настройки key management)
- Бэкапы, сделанные после включения TDE

**TDE НЕ защищает:**
- Трафик между клиентом и сервером (требуется TLS/SSL)
- Данные в памяти (RAM) — суперпользователь БД может прочитать расшифрованные данные
- SQL-инъекции и атаки на приложение
- Файлы, созданные до включения TDE
- Error log, slow/general query log (могут содержать данные из запросов)
- Core dumps (отключайте `core_file`)
- Swap (отключайте или шифруйте на уровне ОС)
- Метаданные (имена таблиц, структура схемы остаются видимыми)

### Переменные MariaDB для управления TDE

| Переменная | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `innodb_encrypt_tables` | Включение шифрования для новых таблиц | `OFF` |
| `innodb_encryption_threads` | Количество потоков для фонового шифрования | `0` (авто) |
| `innodb_encryption_rotate_key_age` | Ротация DEK через N дней (0 = отключено) | `0` |
| `innodb_encrypt_log` | Шифрование redo-логов InnoDB | `OFF` |
| `innodb_encrypt_tables` | Включение шифрования по умолчанию | `OFF` |
| `binlog_encryption` | Шифрование бинарных логов | `OFF` |
| `default_table_encryption` | Шифрование новых таблиц по умолчанию | `OFF` |

### Влияние на производительность

- **CPU:** Оверхед 3-7% при активном AES-NI. На процессорах без AES-NI нагрузка может достигать 10-20%. Проверка поддержки: `grep -o aes /proc/cpuinfo | head -1`.
- **I/O:** Зашифрованные данные имеют максимальную энтропию и не сжимаются. Если требуется сжатие — используйте InnoDB page compression до шифрования.
- **Потоки шифрования:** `innodb_encryption_threads` контролирует параллелизм фонового шифрования. Значение `0` означает автоматический выбор (обычно равно количеству CPU).

## Практические сценарии

### Предварительные требования

- MariaDB **10.5+** (основной ориентир; 10.4 и старше имеют ограниченную поддержку).
- Доступ root/sudo, права администратора MariaDB.
- Утилиты: `openssl`, `systemctl`.
- Для production: HashiCorp Vault (см. [Обзор Vault](../../../Vault/overview.md)).
- Ядро Linux с поддержкой AES-NI (рекомендуется).

---

### 1. Вариант А: File Key Management (Простой)

Подходит для тестовых сред и небольших инсталляций. Ключи хранятся в зашифрованном файле на том же сервере.

#### Шаг 1: Создание структуры директорий

```bash
# Создание защищённой директории для ключей
sudo mkdir -p /etc/mysql/encryption
sudo chown root:root /etc/mysql/encryption
sudo chmod 700 /etc/mysql/encryption

# Создание мастер-ключа (KEK) для шифрования файла ключей
openssl rand -hex 32 > /etc/mysql/encryption/master.key
sudo chmod 600 /etc/mysql/encryption/master.key
sudo chown root:root /etc/mysql/encryption/master.key
```

#### Шаг 2: Создание файла ключей

```bash
# Создание файла ключей в формате: ID;HEX_KEY
# Ключ с ID=1 используется по умолчанию для новых таблиц
echo "1;$(openssl rand -hex 32)" > /etc/mysql/encryption/keyfile.enc
echo "2;$(openssl rand -hex 32)" >> /etc/mysql/encryption/keyfile.enc

# Шифрование файла ключей мастер-ключом
openssl enc -aes-256-cbc -salt -in /etc/mysql/encryption/keyfile.enc \
  -out /etc/mysql/encryption/keyfile.enc.enc \
  -pass file:/etc/mysql/encryption/master.key

# Установка прав доступа
sudo chmod 600 /etc/mysql/encryption/keyfile.enc.enc
sudo chown root:root /etc/mysql/encryption/keyfile.enc.enc

# Удаление незашифрованной версии
shred -u /etc/mysql/encryption/keyfile.enc
```

**Пояснения:**
- `ID` — уникальный идентификатор ключа. Ключ с ID=1 используется по умолчанию.
- `HEX_KEY` — 64-символьная шестнадцатеричная строка (32 байта).
- Файл `master.key` хранится отдельно от `keyfile.enc.enc` — компрометация сервера не даёт доступ к ключам, если злоумышленник не получил и `master.key`.

#### Шаг 3: Настройка `my.cnf`

```ini
[mariadb]
# Загрузка плагина file_key_management
plugin_load_add = file_key_management

# Путь к зашифрованному файлу ключей
file_key_management_filename = /etc/mysql/encryption/keyfile.enc.enc

# Путь к мастер-ключу (KEK)
file_key_management_filekey  = FILE:/etc/mysql/encryption/master.key

# Алгоритм шифрования DEK (AES_CTR рекомендуется для производительности)
file_key_management_encryption_algorithm = AES_CTR

# Активация шифрования таблиц InnoDB
innodb_encrypt_tables    = ON
innodb_encryption_threads = 4
innodb_encryption_rotate_key_age = 1

# Шифрование redo-логов (рекомендуется для production)
innodb_encrypt_log = ON

# Шифрование бинарных логов (требует предварительной настройки key management)
binlog_encryption = ON
```

#### Шаг 4: Перезапуск и валидация

```bash
# Перезапуск MariaDB
sudo systemctl restart mariadb

# Проверка статуса службы
sudo systemctl status mariadb
# → active (running)

# Проверка загрузки плагина
mysql -e "SHOW PLUGINS LIKE 'file_key_management';"
# → file_key_management | ACTIVE | ENCRYPTION | ...

# Проверка настроек шифрования
mysql -e "SHOW VARIABLES LIKE 'innodb_encrypt%';"
# → innodb_encrypt_tables = ON
# → innodb_encryption_threads = 4
# → innodb_encryption_rotate_key_age = 1
# → innodb_encrypt_log = ON
```

---

### 2. Вариант Б: Интеграция с HashiCorp Vault (Advanced)

Для production-сред с несколькими серверами MariaDB и требованием централизованного управления ключами.

#### Шаг 1: Подготовка Vault

См. [Установка Vault](../../../Vault/guides/vault_installation.md) для первичной настройки кластера.

```bash
# Включение движка секретов transit (если ещё не включён)
vault secrets enable transit

# Создание ключа для MariaDB
vault write -f transit/keys/mariadb-tde \
  type=aes256-gcm96 \
  exportable=false

# Проверка создания ключа
vault read transit/keys/mariadb-tde
# → Key Type: aes256-gcm96
# → Versions: 1 (рабочая)
```

#### Шаг 2: Создание политики Vault для MariaDB

```hcl
# /etc/vault.d/policies/mariadb-tde.hcl
# Политика: MariaDB может запрашивать KEK, но не управлять ключом

path "transit/keys/mariadb-tde" {
  capabilities = ["read"]
}

path "transit/encrypt/mariadb-tde" {
  capabilities = ["update"]
}

path "transit/decrypt/mariadb-tde" {
  capabilities = ["update"]
}

path "transit/rewrap/mariadb-tde" {
  capabilities = ["update"]
}
```

```bash
# Назначение политики AppRole для MariaDB
vault policy write mariadb-tde /etc/vault.d/policies/mariadb-tde.hcl

# Создание AppRole для MariaDB
vault write auth/approle/role/mariadb-tde \
  token_policies="mariadb-tde" \
  token_ttl=720h \
  token_max_ttl=720h \
  bind_secret_id=true \
  secret_id_num_uses=0 \
  secret_id_ttl=0

# Получение Role ID и Secret ID
vault read auth/approle/role/mariadb-tde/role-id
vault write -f auth/approle/role/mariadb-tde/secret-id
```

**Пояснения:**
- `token_ttl=720h` (30 дней) — токен MariaDB перевыпускается автоматически через Vault Agent.
- `secret_id_num_uses=0` — бесконечное использование Secret ID (MariaDB использует его при старте).
- Политика разрешает только операции шифрования/расшифровки, но не ротацию или удаление ключа.

#### Шаг 3: Настройка `my.cnf` для Vault

```ini
[mariadb]
# Загрузка плагина hashicorp_key_management
plugin_load_add = hashicorp_key_management

# URL Vault
hashicorp_key_management_vault_url = https://vault.internal:8200

# AppRole credentials
hashicorp_key_management_auth_path = auth/approle/login
hashicorp_key_management_role_id    = <ROLE_ID>
hashicorp_key_management_secret_id  = <SECRET_ID>

# Путь к ключу в Vault Transit Engine
hashicorp_key_management_path = transit/mariadb-tde

# Включение шифрования
innodb_encrypt_tables = ON
innodb_encryption_threads = 4
innodb_encryption_rotate_key_age = 1
innodb_encrypt_log = ON
binlog_encryption = ON
```

**Пояснения:**
- `hashicorp_key_management_vault_url` — адрес Vault. Используйте HTTPS с валидным сертификатом.
- `hashicorp_key_management_auth_path` — путь AppRole аутентификации.
- `hashicorp_key_management_path` — путь к ключу в Transit Engine (без префикса `transit/keys/` в некоторых версиях; проверяйте документацию плагина).

#### Шаг 4: Перезапуск и валидация

```bash
# Перезапуск MariaDB
sudo systemctl restart mariadb

# Проверка загрузки плагина
mysql -e "SHOW PLUGINS LIKE 'hashicorp_key_management';"
# → hashicorp_key_management | ACTIVE | ENCRYPTION | ...

# Проверка подключения к Vault
sudo tail -100 /var/log/mysql/error.log | grep -i vault
# → Должны быть записи об успешном подключении к Vault

# Проверка настроек шифрования
mysql -e "SHOW VARIABLES LIKE 'innodb_encrypt%';"
```

---

### 3. Настройка шифрования существующих таблиц

```sql
-- Включение шифрования для конкретной таблицы
ALTER TABLE orders ENCRYPTION='Y';

-- Включение шифрования по умолчанию для новых таблиц
SET GLOBAL default_table_encryption = ON;

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
-- → innodb_encrypt_log = ON
```

**Пояснения:**
- `ALTER TABLE ... ENCRYPTION='Y'` выполняет перешифрование данных InnoDB. Это фоновая операция; для больших таблиц мониторьте прогресс через `information_schema.INNODB_TABLESPACES_ENCRYPTION`.
- `default_table_encryption = ON` включает шифрование для всех новых таблиц InnoDB.

### 4. Ротация ключей

#### Ротация DEK (автоматическая)

```sql
-- Ротация DEK через N дней (настройка в my.cnf)
innodb_encryption_rotate_key_age = 90

-- Принудительная ротация всех DEK
ALTER TABLE orders ENCRYPTION='Y';
-- → DEK перегенерируется, данные перешифровываются
```

#### Ротация KEK (ручная)

```sql
-- Перезагрузка KEK из хранилища (для file_key_management перешифровывает файл ключей)
-- Для HashiCorp Vault ротация KEK выполняется на стороне Vault:
vault write transit/keys/mariadb-tde/config \
  min_decryption_version=1 \
  min_encryption_version=3

-- MariaDB автоматически использует новую версию KEK для новых операций
-- Старые DEK перешифровываются (rewrap) при следующей ротации DEK
```

### 5. Верификация TDE

```bash
# Проверка, что данные на диске действительно зашифрованы
hexdump -C /var/lib/mysql/testdb/orders.ibd | head -5
# → Если зашифровано, данные будут выглядеть как случайный набор байт
# → Если не зашифровано, видны текстовые данные

# Проверка поддержки AES-NI (рекомендуется для производительности)
grep -o aes /proc/cpuinfo | head -1
# → aes (если поддерживается)
```

```sql
-- Проверка статуса шифрования всех табличных пространств
SELECT NAME, ENCRYPTION_SCHEME, KEY_ROTATION_PAGE_NUMBER
FROM information_schema.INNODB_TABLESPACES_ENCRYPTION;
-- → ENCRYPTION_SCHEME = 1 подтверждает шифрование

-- Проверка encryption-параметров
SHOW VARIABLES LIKE 'innodb_encrypt%';
SHOW VARIABLES LIKE 'binlog_encryption';
```

## HSM, FIPS и GOST

### HSM (Hardware Security Module)

HSM — аппаратный модуль защиты ключей. MariaDB Community не имеет нативного HSM-плагина; интеграция реализуется через:

1. **HashiCorp Vault с HSM-бэкендом** — Vault хранит KEK в HSM (PKCS#11), MariaDB работает с Vault через `hashicorp_key_management`. Подробнее: [Вариант Б](#2-вариант-б-интеграция-с-hashicorp-vault-advanced).
2. **PKCS#11 через OpenSSL** — при сборке MariaDB с OpenSSL, поддерживающим PKCS#11-провайдеры (например, OpenSC), ключи могут резидировать в HSM.
3. **Сертифицированные шлюзы** — для требований ФСТЭК/ГОСТ используются сертифицированные HSM (например, российские криптопровайдеры) на уровне ОС или как отдельный шлюз.

**Теория HSM/KMS (DEK/KEK, Envelope Encryption):** см. [Шифрование данных в покое](../../Concepts/encryption_at_rest.md).

### FIPS 140-2/140-3

**Ключевой факт:** MariaDB **не поддерживает** включение FIPS-режима внутри сервера (MDEV-20260 — закрыта как «не будет реализовано»). FIPS-режим включается на уровне:

1. **Ядро ОС** — FIPS-режим в RHEL/CentOS (`fips=1` в kernel cmdline, `crypto-policies`).
2. **OpenSSL-конфигурация** — FIPS provider в OpenSSL 3:

```bash
# Конфигурация OpenSSL 3 с FIPS provider
# /etc/ssl/openssl.cnf
openssl_conf = openssl_init

[openssl_init]
providers = provider_sect

[provider_sect]
fips = fips_sect
base = base_sect

[fips_sect]
activate = 1
```

```bash
# Запуск MariaDB с FIPS-конфигурацией OpenSSL
OPENSSL_CONF=/etc/ssl/openssl-fips.cnf systemctl start mariadb
```

**Проверка:**

```bash
# Проверка FIPS-режима ядра
sysctl crypto.fips_enabled
# → crypto.fips_enabled = 1

# Проверка, что MariaDB использует FIPS-провайдер
journalctl -u mariadb | grep -i fips
```

**Пояснения:**
- FIPS-режим ограничивает разрешённые алгоритмы (AES, SHA-256, RSA — без MD5/SHA-1).
- При FIPS-режиме проверьте совместимость клиентов и репликации.
- MariaDB TDE использует AES — совместим с FIPS; но сам FIPS-режим — свойство ОС/OpenSSL, не СУБД.

### GOST (ГОСТ-шифрование)

**MariaDB не поддерживает ГОСТ-алгоритмы шифрования нативно.** TDE использует AES; `file_key_management` не поддерживает ГОСТ-шифры.

Для требований ФСТЭК/ГОСТ (Приказ № 117, Гост Р 57580.1):

1. **Шифрование на уровне ОС** — LUKS с сертифицированными ГОСТ-модулями (криптопровайдеры, аккредитованные ФСБ/ФСТЭК).
2. **Сертифицированные HSM/шлюзы** — ГОСТ-шифрование на аппаратном уровне.
3. **TDE MariaDB (AES)** — может быть дополнительным слоем, но **не заменяет** ГОСТ-шифрование в отчётах по ФСТЭК.

**Важно:** не заявляйте TDE MariaDB как «ГОСТ-шифрование» в комплаенс-отчётах. Подробнее: [Комплаенс](compliance.md).

## Устранение неполадок

### Плагин не загружается при старте

**Симптомы:** MariaDB не стартует, в логах `file_key_management` или `hashicorp_key_management` not found.

**Диагностика:**
```bash
# Проверка наличия файла ключей
ls -la /etc/mysql/encryption/keyfile.enc.enc
# → Файл должен существовать и иметь права 600

# Проверка логов MariaDB
sudo tail -100 /var/log/mysql/error.log | grep -i "key_management\|encryption"
```

**Решение:**
1. Убедитесь, что `plugin_load_add` указан в `my.cnf` в секции `[mariadb]`.
2. Убедитесь, что файл ключей существует и доступен пользователю `mysql`.
3. Проверьте целостность `master.key` и `keyfile.enc.enc`.

### Ошибка «Unable to decrypt tablespace» при старте

**Причина:** KEK недоступен или изменён.

**Диагностика:**
```bash
# Проверка доступности файла ключей
ls -la /etc/mysql/encryption/keyfile.enc.enc

# Проверка доступности Vault
curl -k https://vault.internal:8200/v1/sys/health
# → {"initialized":true,"sealed":false,...}
```

**Решение:**
1. Для `file_key_management`: восстановите `keyfile.enc.enc` из резервной копии.
2. Для `hashicorp_key_management`: проверьте доступность Vault и валидность AppRole credentials.
3. При изменении KEK на стороне Vault выполните ротацию DEK: `ALTER TABLE ... ENCRYPTION='Y'`.

### Высокое использование CPU после включения TDE

**Причина:** Процессор не поддерживает AES-NI, или включено шифрование большого объема исторических данных.

**Диагностика:**
```bash
# Проверка поддержки AES-NI
grep -o aes /proc/cpuinfo | head -1
# → Должен вывести "aes"

# Проверка нагрузки CPU
top -bn1 | grep mysqld
```

**Решение:**
1. Если AES-NI не поддерживается — рассмотрите обновление процессора.
2. Шифрование существующих данных — фоновая операция; дождитесь завершения.
3. Увеличьте `innodb_encryption_threads` для ускорения фонового шифрования.

### Бэкап не восстанавливается после потери ключа

**Причина:** KEK/Master Key был утерян.

**Решение:**
- Для `file_key_management`: восстановите `keyfile.enc.enc` и `master.key` из резервной копии.
- Для Vault: восстановите доступ к Transit Engine ключу.
- Если KEK не восстановим — данные утеряны безвозвратно.

## Лучшие практики

1. **Не храните KEK на том же сервере, что и данные.** Для `file_key_management` храните `master.key` на отдельном сервере или в HSM. Для Vault — используйте отдельный кластер.
2. **Шифруйте redo-логи.** Включите `innodb_encrypt_log = ON` — логи транзакций содержат копии изменённых данных.
3. **Тестируйте восстановление.** Минимум 1 раз в квартал выполняйте полное восстановление из зашифрованного бэкапа на изолированном сервере.
4. **Ротация ключей.** Ротация KEK — ежеквартально и внепланово при подозрении на компрометацию.
5. **Аудит доступа к ключам.** Все обращения к Vault логируются (`vault audit enable file ...`) и отправляются в SIEM.
6. **OS hardening.** Отключайте swap, core dumps (`fs.suid_dumpable=0`), используйте SELinux/AppArmor в режиме enforcing.
7. **Разделение ключей по окружениям.** Используйте разные ключи для dev/staging/prod.
8. **Документируйте DR-процедуру.** Укажите: где хранится резервная копия KEK, кто имеет доступ, как выполнить восстановление.

## Дополнительная информация

### Ограничения

- **Перенос датафайлов** на другой сервер требует идентичного хранилища ключей: без KEK табличные пространства не откроются.
- **Даунгрейд** с включенным `binlog_encryption` на версию без поддержки шифрования binlog невозможен — сначала выключите переменную и дождитесь ротации логов.
- **Репликация:** источник и реплики должны иметь доступ к одному классу хранилища ключей.

### Смежные темы

- **[Шифрование данных в покое](../../Concepts/encryption_at_rest.md)** — теория TDE, DEK/KEK, Envelope Encryption.
- **[Обзор безопасности](index.md)** — общая модель безопасности MariaDB.
- **[Бинарное логирование](binary-logging.md)** — шифрование бинарных логов (`binlog_encryption`).
- **[SSL/TLS](ssl-tls.md)** — шифрование данных в транзите.
- **[HashiCorp Vault](../../../Vault/overview.md)** — управление ключами шифрования.
- **[Установка Vault](../../../Vault/guides/vault_installation.md)** — развёртывание кластера Vault для production.
