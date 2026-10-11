# Шифрование данных «в покое» (Encryption at Rest / TDE)

**Актуально для:** PostgreSQL 18, MySQL 8.4 LTS, MariaDB 12.x, SQL Server 2022, MongoDB 8.0

## Определения

**Encryption at Rest (Шифрование в покое)** — метод защиты информации, хранящейся на физических носителях (диски, ленты, съемные носители). Цель — предотвратить чтение данных в случае физической кражи носителя или несанкционированного доступа к файловой системе. Шифрование в покое является одним из столпов модели «эшелонированной защиты» (Defense in Depth), дополняя защиту трафика (In-Transit) и защиту данных в использовании (In-Use).

**TDE (Transparent Data Encryption)** — технология прозрачного шифрования данных на уровне СУБД. Прозрачность означает, что приложение работает с данными обычным образом через SQL, а шифрование и расшифровка происходят автоматически при чтении/записи на диск. Приложение не требует модификации кода для работы с зашифрованными данными.

**DEK (Data Encryption Key)** — ключ, используемый непосредственно для шифрования данных (таблиц, логов). Обычно хранится в зашифрованном виде и генерируется для каждого защищаемого объекта (таблицы, табличного пространства или базы данных, в зависимости от СУБД).

**KEK (Key Encryption Key) / Master Key** — ключ более высокого уровня, используемый для шифрования DEK. KEK хранится во внешнем защищенном хранилище (Keyring, KMS, HSM) и никогда не покидает его в открытом виде. KEK используется только для шифрования/расшифровки DEK, но не для обработки данных напрямую.

**Envelope Encryption (Конвертное шифрование)** — иерархическая модель управления ключами, где данные шифруются ключом DEK, а сам DEK шифруется ключом KEK. Это позволяет безопасно хранить зашифрованный DEK рядом с данными, не раскрывая его без доступа к внешнему хранилищу KEK. Модель «конверта» означает, что для расшифрования данных необходимы оба ключа: DEK (расположенный рядом с данными) и KEK (находящийся в HSM/KMS).

**AES (Advanced Encryption Standard)** — симметричный блочный шифр, стандарт де-факто для шифрования данных. Для TDE используются ключи длиной 256 бит (AES-256). Современные процессоры (Intel с AES-NI, ARM с ARMv8 Crypto Extensions) аппаратно ускоряют операции AES, минимизируя влияние на производительность.

**AES-XTS (XEX-based Tweaked-codebook mode with Ciphertext Stealing)** — режим шифрования AES, специально разработанный для шифрования данных на диске (block device level). В отличие от AES-CBC, XTS обеспечивает независимость шифрования каждого сектора диска и устойчивость к атакам на основе анализа структуры данных. Используется в LUKS2, BitLocker, FileVault 2.

**AES-GCM (Galois/Counter Mode)** — режим шифрования AES с аутентификацией (AEAD — Authenticated Encryption with Associated Data). Обеспечивает одновременно конфиденциальность и проверку целостности данных без дополнительного прохода. Используется в расширениях pg_tde/pgcrypto, TLS 1.3, IPsec.

**HSM (Hardware Security Module)** — физическое устройство для генерации и хранения ключей с аппаратной защитой от вскрытия. Используется в наиболее требовательных средах (PCI DSS Level 1, FinTech, государственные структуры).

## Основные концепции

### Уровни реализации шифрования

1.  **Уровень приложения:** Данные шифруются в коде перед отправкой в БД. Максимальная защита (включая защиту от администратора БД), но невозможен поиск и индексация по зашифрованным полям без дополнительных техник (Blind Index). Пример: `pgcrypto` в PostgreSQL, `AES_ENCRYPT`/`AES_DECRYPT` в MySQL.
2.  **Уровень СУБД (TDE):** Шифруются табличные пространства (Tablespaces), логи транзакций (WAL/Redo), временные файлы и, в некоторых реализациях, бинарные логи. Баланс между безопасностью и функциональностью SQL. TDE прозрачна для приложения и не требует изменения запросов.
3.  **Уровень файловой системы / Блочный уровень:** Шифруется весь раздел диска (LUKS/dm-crypt в Linux, BitLocker в Windows). Защищает от кражи диска, но не защищает от компрометации ОС или от пользователя БД с правами суперпользователя, имеющего доступ к расшифрованной ФС.

### Сравнение уровней шифрования

| Уровень | Гранулярность | Защита от кражи диска | Защита от админа БД | Влияние на SQL | Прозрачность для приложения |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Приложение (Column-level)** | Столбец | Да | Да | Запреты на операции, индексация | Низкая |
| **СУБД (TDE)** | Tablespace / БД | Да | Частично (не от суперпользователя) | Минимальное | Высокая |
| **Файловая система (LUKS)** | Раздел | Да | Нет | Нет | Полная |

### Механизм управления ключами (KMS)

Для работы TDE требуется внешнее хранилище ключей:

- **File-based Keyring:** Ключи хранятся в зашифрованном файле на том же сервере. Минимальная защита (подходит для тестов). В MySQL 8.4 используется `component_keyring_file`, в PostgreSQL — файловый провайдер `pg_tde`. **Важно:** компрометация сервера означает компрометацию ключей.
- **KMS (Key Management Service):** Self-hosted решения (HashiCorp Vault, OpenBao). Ключ никогда не покидает KMS в открытом виде. KMS возвращает DEK только по авторизованному запросу сервера БД.
- **HSM (Hardware Security Module):** Физическое устройство для генерации и хранения ключей с аппаратной защитой от вскрытия. Используется в наиболее требовательных средах (PCI DSS Level 1, FinTech, государственные структуры).
- **EKM (Extensible Key Management):** Механизм SQL Server для интеграции с внешними HSM/KMS через провайдеры. Позволяет использовать любое хранилище ключей, поддерживающее протокол PKCS#11 или KMIP.

### Ротация ключей

Ротация ключей — обязательная операция для соответствия стандартам безопасности и минимизации рисков:

- **Ротация DEK:** Происходит автоматически в большинстве СУБД. DEK зашифровывается текущим KEK. При смене KEK все DEK перешифровываются (rewrap), но сами данные не перезаписываются — меняется только «конверт».
- **Ротация KEK (Master Key):** Происходит реже (рекомендация NIST: не реже 1 раза в год для симметричных мастер-ключей). При ротации KEK СУБД перешифровывает DEK новым ключом. Важно сохранять историю ключей для расшифрования старых бэкапов.
- **Автоматическая ротация:** HashiCorp Vault и OpenBao позволяют настроить автоматическую ротацию через policies.

**Важно:** При потере KEK/Master Key данные становятся навсегда недоступными. Рекомендуется:
- Хранить резервные копии ключей в отдельном хранилище (или second KMS).
- Тестировать восстановление из зашифрованных бэкапов не реже 1 раза в квартал.
- Использовать split-knowledge/dual-control для ручных операций с ключами.

### Влияние на производительность и эксплуатацию

*   **CPU:** Современные процессоры с поддержкой инструкций AES-NI минимизируют накладные расходы (обычно < 3-5% на чтение/запись). На процессорах без AES-NI (некоторые ARM, старые x86) нагрузка может достигать 10-20%. Рекомендация: при проектировании инфраструктуры учитывать необходимость AES-NI в характеристиках процессора.
*   **Сжатие:** Зашифрованные данные имеют максимальную энтропию и практически не сжимаются. Если требуется и сжатие, и шифрование, порядок операций строго определён: **сначала сжатие, затем шифрование**.
*   **Бэкапы:** Бэкапы, сделанные с TDE-таблиц, также зашифрованы. Для их восстановления требуется доступ к тому же KEK/Master Key. Это критически важно учитывать при катастрофическом восстановлении (DR) — KEK должен быть доступен на DR-площадке.
*   **Репликация:** TDE-данные передаются в зашифрованном виде между нодами кластера (обычно через TLS). Расшифрование происходит только на целевом узле. Это не влияет на производительность репликации, но требует наличия KEK на каждом узле.
*   **I/O:** Современные реализации TDE шифруют данные страницами (обычно 16 КБ, как в PostgreSQL/MySQL). Шифрование происходит на уровне блочного ввода-вывода, что позволяет использовать аппаратное ускорение (AES-NI) без оверхеда на уровне SQL-запросов.
*   **TempDB / Временные файлы:** В некоторых реализациях (SQL Server) шифрование TempDB включается автоматически при включении TDE в любой пользовательской БД. Это предотвращает утечку данных через временные таблицы.

### Что защищает и не защищает TDE

**TDE защищает:**
- Табличные пространства и файлы данных
- Логи транзакций (WAL/Redo)
- Бинарные логи (MySQL) — при включении `binlog_encryption`
- Временные файлы (TempDB в SQL Server)
- Бэкапы (если сделаны после включения TDE)
- Экспортные файлы

**TDE НЕ защищает:**
- Трафик между клиентом и сервером (требуется TLS/SSL)
- Данные в памяти (RAM) — суперпользователь БД может прочитать расшифрованные данные
- SQL-инъекции и атаки на приложение
- Файлы, созданные до включения TDE
- Метаданные (имена таблиц, структура схемы остаются видимыми)
- Файлы не-SQL (например, внешние данные, загруженные через `COPY` без шифрования)

## Практические сценарии

### Сценарий 1: Выбор стратегии шифрования

1. **PCI DSS / GDPR:** Требуют защиты PII (персональных данных). TDE является стандартом для выполнения этих требований. Для высокочувствительных данных (payment card data) рекомендуется комбинация TDE + Column-level encryption.
2. **HIPAA (Healthcare):** Требует шифрования ePHI (electronic Protected Health Information). TDE + Encryption in Transit + Access Controls.
3. **SOX / SOC2:** Требуют аудита доступа к финансовым данным. TDE + Audit Logging.
4. **On-Premise:** HashiCorp Vault или OpenBao как централизованное хранилище ключей с аудитом доступа и автоматической ротацией.
5. **Миграция с legacy-систем:** При наличии унаследованных БД без TDE используйте LUKS/dm-crypt на уровне ОС как промежуточное решение при переходе на СУБД с нативным TDE.

### Предварительные требования для всех сценариев

- **Аппаратное ускорение AES:** Процессор с поддержкой AES-NI (Intel Westmere 2010+, AMD Bulldozer 2011+). Проверка: `grep -o aes /proc/cpuinfo | head -1`.
- **Версия СУБД:** MySQL 8.4 LTS, MariaDB 12.x, PostgreSQL 18, SQL Server 2022 или выше.
- **Доступ root/sudo:** Для работы с LUKS, systemd, конфигурационными файлами.
- **Резервное копирование:** Перед включением TDE выполните полный бэкап. Включение TDE на существующих таблицах — операция, затрагивающая I/O.
- **План DR:** KEK/Master Key должен быть доступен на площадке катастрофического восстановления до инициализации СУБД.

### Сценарий 2: Установка TDE в MySQL 8.4 LTS

#### Шаг 1: Настройка Keyring-компонента

```ini
# /etc/mysql/my.cnf
[mysqld]
# Базовый вариант: файловый keyring (для тестов/разработки)
early-plugin-load=component_keyring_file.so
component_keyring_file_data=/var/lib/mysql-keyring/keyring

# Производственный вариант: HashiCorp Vault
# early-plugin-load=component_keyring_vault.so
# component_keyring_vault_config=/etc/mysql/keyring_vault.conf
```

> **Примечание:** В MySQL 8.4 плагин `keyring_file.so` устарел. Используется компонент `component_keyring_file.so`.

#### Шаг 2: Активация шифрования

```sql
-- Глобальное шифрование для новых таблиц
SET GLOBAL default_table_encryption = ON;

-- Шифрование существующей таблицы
ALTER TABLE sensitive_data ENCRYPTION = 'Y';

-- Шифрование логов (рекомендуется)
SET GLOBAL innodb_redo_log_encrypt = ON;
SET GLOBAL innodb_undo_log_encrypt = ON;
SET GLOBAL binlog_encryption = ON;
```

#### Шаг 3: Валидация

```sql
-- Проверка статуса шифрования таблицы
SELECT TABLE_SCHEMA, TABLE_NAME, CREATE_OPTIONS
FROM information_schema.TABLES
WHERE CREATE_OPTIONS LIKE '%ENCRYPTION%';
-- → Таблицы с ENCRYPTION='Y' будут показаны

-- Проверка статуса keyring
SELECT STATUS FROM information_schema.KEYRING_COMPONENT_STATUS;
-- → Должен показать активный компонент
```

#### Шаг 4: Ротация мастер-ключа

```sql
-- Ротация без перешифрования данных (меняется только обертка DEK)
ALTER INSTANCE ROTATE INNODB MASTER KEY;
-- → Ключ версии 1 → версии 2. Старые DEK перешифровываются новым KEK.
```

#### Очистка / Откат

```sql
-- Отключение шифрования для новой таблицы
SET GLOBAL default_table_encryption = OFF;

-- Снятие шифрования с таблицы (требует rebuild)
ALTER TABLE sensitive_data ENCRYPTION = 'N';

-- Отключение шифрования логов
SET GLOBAL innodb_redo_log_encrypt = OFF;
SET GLOBAL innodb_undo_log_encrypt = OFF;
SET GLOBAL binlog_encryption = OFF;
```

### Сценарий 3: Установка TDE в MariaDB 12.x

```sql
-- 1. Создание таблицы с шифрованием (InnoDB)
CREATE TABLE sensitive_data (
    id INT PRIMARY KEY AUTO_INCREMENT,
    data TEXT
) ENGINE=InnoDB ENCRYPTION='Y';

-- 2. Включение шифрования по умолчанию для новых таблиц
SET GLOBAL default_table_encryption = ON;

-- 3. Шифрование существующей таблицы
ALTER TABLE existing_table ENCRYPTION = 'Y';
-- Важно: ALTER с ENCRYPTION='Y' выполняет перешифрование данных InnoDB

-- 4. Проверка
SELECT TABLE_SCHEMA, TABLE_NAME, CREATE_OPTIONS
FROM information_schema.TABLES
WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys');
```

#### Очистка / Откат

```sql
-- Снятие шифрования с таблицы
ALTER TABLE sensitive_data ENCRYPTION = 'N';

-- Отключение шифрования по умолчанию
SET GLOBAL default_table_encryption = OFF;
```

### Сценарий 4: Шифрование в PostgreSQL 18

Ванильный PostgreSQL (Community Edition) не имеет нативного TDE. Для его реализации используются расширения:

- **pg_tde** (Percona): работает только с Percona Server for PostgreSQL 17/18
- **open_pg_tde** (Command Prompt): работает с ванильным PostgreSQL 16/17/18
- **pg_vault_tde** (Miriade): работает с ванильным PostgreSQL 17/18

#### Вариант A: Percona Server for PostgreSQL + pg_tde

##### Шаг 1: Установка

```bash
# Установка Percona Server for PostgreSQL 18
sudo apt-get install percona-postgresql-18
sudo apt-get install percona-postgresql-18-pg-tde
```

##### Шаг 2: Настройка провайдера ключей

```sql
-- Файловый провайдер (тесты/разработка)
SELECT pg_tde_add_key_provider_file('file-provider', '/var/lib/postgresql/keyring/tde_key');

-- HashiCorp Vault (производство)
-- SELECT pg_tde_add_key_provider_vault('vault-provider', 'https://vault.internal:8200', 'transit', 'tde-key');
```

##### Шаг 3: Установка мастер-ключа

```sql
SELECT pg_tde_set_principal_key('master-key-name', 'file-provider', true);
-- Параметр 'true' означает, что ключ генерируется, если не существует
```

##### Шаг 4: Шифрование таблицы

```sql
-- Включение TDE для существующей таблицы
ALTER TABLE sensitive_data SET ACCESS METHOD tde_heap;

-- Создание новой зашифрованной таблицы
CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    event TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
) ACCESS METHOD tde_heap;
```

##### Шаг 5: Валидация

```sql
-- Проверка статуса шифрования
SELECT * FROM pg_tde_is_encrypted('sensitive_data');
-- → true

-- Проверка доступных провайдеров
SELECT * FROM pg_tde_key_providers();
```

#### Вариант B: Ванильный PostgreSQL 18 + open_pg_tde

```bash
# Сборка и установка open_pg_tde для ванильного PostgreSQL 18
git clone https://github.com/commandprompt/open_pg_tde.git
cd open_pg_tde
make && sudo make install
```

```sql
-- Включение расширения
CREATE EXTENSION open_pg_tde;

-- Настройка ключевого провайдера (аналогично pg_tde)
-- Поддерживает HashiCorp Vault, OpenBao, PKCS#11 HSM
```

#### Ограничения расширений TDE для PostgreSQL (2026):
- Требуют PostgreSQL 17/18
- Не шифруют временные файлы и статистику (планируется в будущих версиях)
- Поддерживают HashiCorp Vault, OpenBao, файловый провайдер, PKCS#11

#### Очистка / Откат (PostgreSQL)

```sql
-- Снятие шифрования с таблицы (восстанавливает heap access method)
ALTER TABLE sensitive_data SET ACCESS METHOD heap;

-- Удаление расширения (все зашифрованные таблицы должны быть предварительно расшифрованы)
DROP EXTENSION pg_tde;
```

### Сценарий 5: Шифрование на уровне ФС (LUKS) для PostgreSQL

Рекомендуемый подход для Community PostgreSQL. Шифрование выполняется на уровне блочного устройства, до того как данные попадают в файловую систему.

#### Шаг 1: Создание зашифрованного раздела

```bash
# Предупреждение: ДЕСТРУКТИВНАЯ операция. Резервное копирование обязательно!
sudo cryptsetup luksFormat --type luks2 \
    --cipher aes-xts-plain64 \
    --key-size 512 \
    --hash sha512 \
    --iter-time 5000 \
    /dev/sdb

# Открытие зашифрованного устройства
sudo cryptsetup open /dev/sdb pgdata_encrypted

# Создание файловой системы
sudo mkfs.ext4 /dev/mapper/pgdata_encrypted

# Монтирование (временно для инициализации)
sudo mount /dev/mapper/pgdata_encrypted /var/lib/postgresql/data

# Инициализация кластера PostgreSQL
sudo -u postgres initdb -D /var/lib/postgresql/data
```

#### Шаг 2: Автоматическое открытие при загрузке

```bash
# Добавление устройства в /etc/crypttab
echo "pgdata_encrypted /dev/sdb /root/luks-keyfile luks" | sudo tee -a /etc/crypttab

# Настройка systemd для открытия до старта PostgreSQL
sudo systemctl edit postgresql@18-main
# Добавить:
# [Unit]
# After=cryptsetup.target
# Requires=local-fs.target
```

#### Шаг 3: Валидация

```bash
# Проверка, что раздел зашифрован
sudo cryptsetup status pgdata_encrypted
# → /dev/mapper/pgdata_encrypted is active and is in use.
#   type:    LUKS2
#   cipher:  aes-xts-plain64
#   keysize: 512 bits

# Проверка, что PostgreSQL работает
sudo systemctl status postgresql@18-main
# → active (running)
```

#### Очистка / Откат

```bash
# Остановка PostgreSQL
sudo systemctl stop postgresql@18-main

# Размонтирование
sudo umount /var/lib/postgresql/data

# Закрытие LUKS
sudo cryptsetup close pgdata_encrypted

# Удаление из crypttab и fstab
sudo sed -i '/pgdata_encrypted/d' /etc/crypttab /etc/fstab
```

### Сценарий 6: Тестирование восстановления зашифрованных данных

Тестирование восстановления — критически важная операция. Если KEK недоступен, БД не запустится.

```bash
# 1. Бэкап зашифрованной БД (MySQL)
mysqldump --all-databases > backup.sql
# → backup.sql содержит зашифрованные данные. Без keyring файла или доступа к KMS восстановление невозможно.

# 2. Восстановление на новом сервере
# 2.1. Скопировать keyring файл (или настроить доступ к Vault/HSM)
scp root@old-server:/var/lib/mysql-keyring/keyring /var/lib/mysql-keyring/keyring

# 2.2. Восстановление
mysql < backup.sql
# → Успех, если keyring доступен. Ошибка, если keyring отсутствует.

# 3. Проверка целостности
SELECT COUNT(*) FROM sensitive_data;
# → Данные доступны и расшифрованы корректно
```

## Сравнение реализаций TDE по СУБД

| СУБД | Механизм TDE | Гранулярность | Ключевое хранилище | Шифрование WAL/Redo | Шифрование TempDB | Примечания |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **MySQL 8.4 LTS** | Keyring Component | Tablespace | component_keyring_file / Vault / HSM | Да (redo, undo, binlog) | Нет (отдельно) | component_keyring_file для Community; KMIP для Enterprise |
| **MariaDB 12.x** | InnoDB Encryption | Tablespace | file_keyring / HashiCorp Vault / HSM | Да (redo, binlog) | Нет | Поддержка Roles для управления ключами |
| **PostgreSQL 18** | pg_tde / open_pg_tde | Tablespace | File / Vault / OpenBao / PKCS#11 HSM | Да (WAL) | Нет | pg_tde только для Percona Server; open_pg_tde для ванильного |
| **PostgreSQL < 18** | LUKS/dm-crypt | Раздел | ОС (Filesystem) | Да (на уровне ФС) | Да (на уровне ФС) | Не защищает от админа БД |
| **SQL Server 2022** | Встроенный TDE | БД (page-level) | Cert / EKM (HSM) | Да | Да (автоматически) | AES-256-CBC для данных и логов |
| **Oracle** | Advanced Security | Tablespace | Wallet / OKV / HSM | Да (redo, archive) | Да | Column-level TDE также доступен |
| **MongoDB 8.0** | WiredTiger (Enterprise) | Коллекция | KMIP / Local Keyfile | N/A (WiredTiger journal) | N/A | Community: LUKS / dm-crypt |

## Типичные ошибки и troubleshooting

### 1. Бэкап не расшифровывается после потери ключа

**Причина:** KEK/Master Key был утерян (файл keyring удалён, доступ к HSM утерян, пароль Vault забыт).

**Решение:**
- Восстановите keyring файл из резервной копии (если она была сделана).
- Восстановите доступ к HSM/KMS.
- Если KEK не восстановим — данные утеряны безвозвратно.

**Профилактика:**
- Храните резервные копии ключей в отдельном хранилище (не на том же сервере).
- Регулярно тестируйте восстановление.
- Используйте автоматическую ротацию ключей в KMS.

### 2. Ошибка «Unable to decrypt tablespace» при старте MySQL/MariaDB

**Причина:** Keyring-плагин не загружен или keyring файл недоступен.

**Диагностика:**
```bash
# Проверка наличия keyring файла
ls -la /var/lib/mysql-keyring/keyring

# Проверка логов MySQL
tail -100 /var/log/mysql/error.log | grep -i keyring
```

**Решение:**
1. Убедитесь, что `early-plugin-load` указан в `my.cnf`.
2. Убедитесь, что файл keyring существует и доступен пользователю mysql.
3. Проверьте права доступа: `chmod 600 /var/lib/mysql-keyring/keyring`.

### 3. PostgreSQL: pg_tde / open_pg_tde не загружается

**Причина:** Расширение установлено не в ту версию PostgreSQL или несовместимая версия.

**Диагностика:**
```sql
-- Проверка версии PostgreSQL
SELECT version();
-- → Должна быть PostgreSQL 17/18

-- Попытка подключения расширения
CREATE EXTENSION pg_tde;
-- → Ошибка, если расширение несовместимо
```

**Решение:**
1. Для pg_tde используйте Percona Server for PostgreSQL 18.
2. Для open_pg_tde используйте ванильный PostgreSQL 17/18.
3. Проверьте совместимость версий: pg_tde 2.2+ требует PostgreSQL 18.

### 4. Высокое использование CPU после включения TDE

**Причина:** Процессор не поддерживает AES-NI, или включено шифрование большого объема исторических данных.

**Диагностика:**
```bash
# Проверка поддержки AES-NI
grep -o aes /proc/cpuinfo | head -1
# → Должен вывести "aes"

# Проверка нагрузки CPU
top -bn1 | grep mysql
```

**Решение:**
1. Если AES-NI не поддерживается — рассмотрите обновление процессора или использование LUKS (ядро оптимизирует I/O путь шифрования).
2. Шифрование существующих данных — фоновая операция; дождитесь завершения.
3. Для ARM/старых x86 используйте ChaCha20-Poly1305 если поддерживается СУБД.

### 5. Бэкап MySQL не включает зашифрованные данные

**Причина:** Бэкап сделан инструментом, не поддерживающим keyring (например, копирование файлов `ibdata1` без keyring файла).

**Решение:** Используйте `mysqldump` или `xtrabackup` (Percona), которые корректно работают с TDE. При физическом копировании файлов всегда копируйте keyring файл вместе с данными.

### 6. Потеря заголовка LUKS

**Причина:** Заголовок LUKS поврежден или удален.

**Диагностика:**
```bash
# Проверка заголовка
sudo cryptsetup luksDump /dev/sdb
# → Ошибка, если заголовок поврежден
```

**Решение:**
1. Восстановите заголовок из резервной копии: `cryptsetup luksHeaderRestore`.
2. Если резервной копии нет — данные утеряны.

**Профилактика:**
- Создавайте резервную копию заголовка LUKS после инициализации: `cryptsetup luksHeaderBackup`.
- Храните бэкап заголовка отдельно от зашифрованного носителя.

## SRE/DevOps: мониторинг, автоматизация и соответствие

### Ключевые метрики для мониторинга

**Статус шифрования СУБД:**
```sql
-- MySQL: проверка шифрования таблиц
SELECT TABLE_SCHEMA, TABLE_NAME, CREATE_OPTIONS
FROM information_schema.TABLES
WHERE CREATE_OPTIONS LIKE '%ENCRYPTION%';

-- MariaDB: аналогично MySQL
-- PostgreSQL (pg_tde): проверка статуса
SELECT * FROM pg_tde_is_encrypted('sensitive_data');
```

**Статус LUKS:**
```bash
# Проверка статуса LUKS
sudo cryptsetup status pgdata_encrypted
# → type: LUKS2, cipher: aes-xts-plain64, keysize: 512 bits
```

**Поддержка AES-NI:**
```bash
# Быстрая проверка
grep -o "aes" /proc/cpuinfo | head -n 1
# → aes (если поддерживается)

# Бенчмарк производительности шифрования
cryptsetup benchmark
# → Algorithm | Key | Encryption | Decryption
# → aes-xts    256b      1.5 GB/s         1.5 GB/s
```

### Алерты и пороговые значения

На production-хостах настройте следующие алерты:

| Метрика | Порог | Действие |
| :--- | :--- | :--- |
| Доступность keyring/KMS | N/A | Критический алерт: СУБД не запустится без ключей |
| `cryptsetup status` — устройство не активно | N/A | Критический алерт: зашифрованный том не смонтирован |
| AES-NI не обнаружен | N/A | Предупреждение: производительность шифрования снижена |
| Срок действия KEK | < 30 дней | Предупреждение: запланируйте ротацию |
| Целостность заголовка LUKS | Изменение | Критический алерт: возможна попытка взлома или повреждение |

### Compliance и аудит

Для соответствия PCI DSS, GDPR, HIPAA:

1. **Реестр шифрования:** ведите реестр всех зашифрованных таблиц/табличных пространств с указанием:
   - Имя таблицы/БД
   - Алгоритм и размер ключа
   - Тип хранилища ключей (keyring_file, Vault, HSM)
   - Дата включения и последней проверки восстановления

2. **Аудит доступа:** логируйте все обращения к keyring, KMS, HSM и операции с ключами. Отправляйте логи в SIEM.

3. **Политика ротации ключей:**
   - Ротация KEK минимум раз в год (NIST SP 800-57)
   - Ротация DEK при каждой ротации KEK (automatic rewrap)
   - Сохранение истории KEK для расшифровки старых бэкапов

4. **Тестирование восстановления:** минимум раз в квартал выполняйте полное восстановление из зашифрованного бэкапа на изолированном сервере.

### Автоматизация

**Systemd-сервис для проверки шифрования:**
```ini
# /etc/systemd/system/db-encryption-check.service
[Unit]
Description=Check database encryption status
After=mysql.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check-db-encryption.sh
```

**Скрипт проверки (`/usr/local/bin/check-db-encryption.sh`):**
```bash
#!/bin/bash
# Проверка шифрования MySQL
mysql -u root -p"${MYSQL_ROOT_PASSWORD}" -e "
SELECT TABLE_SCHEMA, TABLE_NAME, CREATE_OPTIONS
FROM information_schema.TABLES
WHERE CREATE_OPTIONS NOT LIKE '%ENCRYPTION=Y%'
AND TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys');
" | grep -q . && echo "WARNING: Unencrypted tables found" || echo "OK: All user tables encrypted"

# Проверка LUKS
for vol in pgdata_encrypted; do
    if ! cryptsetup status $vol >/dev/null 2>&1; then
        echo "CRITICAL: LUKS volume $vol is not active"
        exit 1
    fi
done
```

## Лучшие практики

1. **Не храните KEK на том же сервере, что и данные.** Если сервер скомпрометирован, атакующий получит и данные, и ключи. Используйте HSM или локальный KMS (Vault/OpenBao).
2. **Регулярно тестируйте восстановление.** Минимум 1 раз в квартал выполняйте полное восстановление из зашифрованного бэкапа на изолированном сервере.
3. **Включайте шифрование WAL/Redo логов.** Логи транзакций содержат копии изменённых данных. Без шифрования логов TDE обеспечивает неполную защиту.
4. **Документируйте процедуру катастрофического восстановления.** Включите KEK в план DR. Укажите: где хранится резервная копия ключа, кто имеет доступ, как выполнить восстановление.
5. **Используйте Split-Knowledge для ручных операций.** При ручной ротации ключей пароль должен быть разделён между несколькими администраторами (N-of-M scheme).
6. **Ведите аудит доступа к ключам.** Все обращения к KMS/HSM должны логироваться и отправляться в SIEM.
7. **Шифруйте до сжатия в правильном порядке.** Сначала сжатие, затем шифрование. Зашифрованные данные не сжимаются.
8. **Используйте AEAD-режимы (AES-GCM, ChaCha20-Poly1305).** Они обеспечивают одновременно конфиденциальность и целостность данных. Избегайте ECB и CBC для новых развёртываний где возможно.

## Дополнительная информация

### Смежные темы
- **[Безопасность MariaDB](../MariaDB/security/tde.md)** — практическая настройка MariaDB + HashiCorp Vault.
- **[Безопасность MySQL](../MySQL/security.md)** — Keyring плагины и шифрование InnoDB.
- **[Безопасность PostgreSQL](../PostgreSQL/Concepts/security_and_encryption.md)** — TDE через pg_tde, pgcrypto и LUKS.
- **[Криптография в PostgreSQL](../PostgreSQL/Concepts/pgcrypto.md)** — шифрование на уровне столбцов.
- **[Безопасность бэкапов](./backup_security.md)** — Envelope Encryption и правило 3-2-1-1-0.
- **[Безопасная установка СУБД](../installation_security.md)** — эшелонированная защита и закалка.
