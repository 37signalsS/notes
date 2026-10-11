# Безопасная установка и закалка СУБД

**Актуально для:** MySQL 8.4 LTS / 9.x · MariaDB 11.8 LTS / 12.3 LTS · PostgreSQL 17 / 18 · MongoDB 8.x · Redis 8.x / Valkey 9.x

## Определения

**Закалка (Hardening)** — комплекс мер по настройке СУБД и операционной среды, направленный на минимизацию поверхности атаки (Attack Surface), устранение уязвимых конфигураций по умолчанию и усиление механизмов защиты.

**Принцип наименьших привилегий (Principle of Least Privilege, PoLP)** — фундаментальная концепция безопасности, требующая предоставления субъектам (пользователям, сервисам) только тех прав доступа, которые минимально необходимы для выполнения их бизнес-функций.

**Эшелонированная защита (Defense in Depth)** — стратегия многоуровневого обеспечения безопасности, при которой провал одного механизма защиты компенсируется наличием других уровней (Сеть, ОС, СУБД, Объект, Данные).

**Радиус поражения (Blast Radius)** — объем данных или систем, к которым злоумышленник может получить доступ в случае компрометации конкретной учетной записи или сервиса. Закалка направлена на минимизацию этого радиуса.

**Уязвимая конфигурация по умолчанию (Insecure Default)** — параметр, с которым СУБД устанавливается «из коробки» и который раскрывает данные или управление: отсутствие авторизации (MongoDB), открытые порты, тестовые базы, аккаунты по умолчанию. Скрипты `*secure-installation` и чек-листы CIS Benchmark существуют именно для их устранения.

## Основные концепции: Эшелонированная защита

Эффективная защита СУБД не ограничивается только установкой пароля. Она строится по модели слоев:

1.  **Сетевой уровень (Network):**
    *   **Zero Trust:** отказ от доверия внутренним сетям. Сегментация (отдельный VLAN/VRF для СУБД), Network Policies (в Kubernetes) и Firewall (UFW/Firewalld/nftables).
    *   **mTLS (Mutual TLS):** взаимная аутентификация клиента и сервера с использованием сертификатов.
2.  **Уровень хоста (Host/OS):**
    *   **Изоляция:** запуск СУБД под непривилегированным пользователем (UID/GID).
    *   **Hardening ОС:** применение CIS Benchmarks для Linux, настройка SELinux/AppArmor в режиме `enforce`.
3.  **Уровень инстанса (Instance):**
    *   **Отключение лишнего:** удаление тестовых БД, плагинов и функций (например, доступ к ФС через SQL).
    *   **Аутентификация:** использование сильных алгоритмов хеширования (SCRAM, SHA-2, ed25519).
4.  **Уровень объектов и данных (Database/Data):**
    *   **RBAC (Role-Based Access Control):** гранулярное управление правами на таблицы, схемы и представления.
    *   **Encryption at Rest:** шифрование данных на диске (TDE) и бэкапов.
        *   Подробнее для MySQL: **[TDE в MySQL](./MySQL/security.md#1-настройка-шифрования-данных-tde)**.
        *   Подробнее для MariaDB: **[TDE в MariaDB](./MariaDB/security/tde.md)**.
        *   Подробнее для PostgreSQL: **[Шифрование в PostgreSQL](./PostgreSQL/Concepts/security_and_encryption.md#1-шифрование-данных-в-покое-tde)**.
        *   Теория: **[Шифрование в покое](./Concepts/encryption_at_rest.md)**.

## Предварительные требования

- СУБД установлена из официальных пакетов дистрибутива или вендора (не из сторонних сборок без проверки подписей).
- Доступ к хосту по SSH с правами `sudo` и учётная запись администратора СУБД (root/postgres).
- Бэкап системных баз (`mysql`, `postgres`, `admin`) перед изменениями — откат конфигурации невозможен без него.
- Инструменты диагностики: `ss` (проверка слушаемых портов), `sestatus`/`apparmor_status` (статус MAC), `openssl s_client` (проверка TLS).
- Понимание модели аутентификации целевой СУБД: детали реализации — в файлах раздела (ссылки в «Смежных темах»).

## Практические сценарии по типам СУБД

### MySQL и MariaDB: закалка инстанса

Для MySQL 8.4 LTS / 9.x и MariaDB 11.8 LTS / 12.3 LTS аудит безопасности является неотъемлемой частью жизненного цикла. Детальная спецификация: **[Безопасность MySQL](./MySQL/security.md)** и **[Безопасность MariaDB](./MariaDB/security/index.md)**.

**1. Скрипты защиты (разовый базовый уровень):**
```bash
# MySQL — обязательный запуск после инсталляции
sudo mysql_secure_installation
# MariaDB — аналогичный скрипт
sudo mariadb-secure-installation
```
Скрипт меняет только данные в системных таблицах (удаляет анонимных пользователей, тестовую БД, удалённый root-доступ). Он **не** изменяет `my.cnf`, файрвол, права ОС и плагины — эти уровни закаливаются отдельно (полная таблица ответов скрипта — в **[Начальной закалке MariaDB](./MariaDB/security/hardening.md)**).

**Ключевые рекомендации:**
- **caching_sha2_password:** в MySQL 8.4+ это стандарт. `mysql_native_password` объявлен устаревшим в 8.0.34, отключён по умолчанию в 8.4 и **удалён в 9.0** — включение в 8.4 (`mysql_native_password=ON`) только как временная мера совместимости. Миграция аккаунтов — в **[Аутентификации MySQL](./MySQL/security.md)**.
- **unix_socket:** `root@localhost` в MariaDB создаётся с двумя плагинами — `unix_socket` (первый: вход без пароля по UID ОС через `sudo mariadb`) и `mysql_native_password` (резервный, с «невалидным» паролем до `SET PASSWORD`). Локальный административный вход через сокет исключает передачу пароля root по сети; резервный плагин можно удалить: `ALTER USER 'root'@'localhost' IDENTIFIED VIA unix_socket;`.
- **Внешняя аутентификация:** MySQL Enterprise и MariaDB поддерживают LDAP/Active Directory и PAM через плагины внешней аутентификации. Это **external authentication**, а не MFA. Настоящая многофакторная схема (несколько плагинов на аккаунт, например `IDENTIFIED VIA unix_socket OR ed25519`) доступна в MariaDB с 10.4.
- **Политика паролей:** компонент `validate_password` (MySQL 8.4: включён по умолчанию в пакетах Oracle) и `simple_password_check`/`cracklib_password_check` в MariaDB.

**2. Сетевая привязка (`my.cnf`):**
```ini
[mysqld]
# Слушать только на внутреннем интерфейсе (пример адреса — замените на свой)
bind-address = 10.0.5.20
# Запрет использования символических ссылок (защита от чтения файлов)
symbolic-links = 0
# Запрет загрузки локальных файлов через SQL
local_infile = 0
```

**3. Валидация:**
```sql
-- Аккаунты на устаревшем плагине (в MySQL 8.4 — список для миграции; в 9.x таких аккаунтов быть не может)
SELECT user, host, plugin FROM mysql.user WHERE plugin = 'mysql_native_password';
-- → пустой результат

-- Анонимные пользователи (должны быть удалены скриптом)
SELECT user, host FROM mysql.user WHERE user = '';
-- → пустой результат
```
```bash
# Проверка, на каком интерфейсе слушает сервер
ss -tlnp | grep mysqld
# → LISTEN 0 151 10.0.5.20:3306 ...
```

### PostgreSQL: pg_hba.conf, SCRAM и аудит

PostgreSQL 17/18 поставляется с безопасными настройками по умолчанию: сервер слушает только `localhost`, а хост-подключения хешируются по SCRAM-SHA-256 (`password_encryption` по умолчанию с версии 14). Ключевое — не ослабить это при настройке.

**1. Аутентификация (`pg_hba.conf`):**
Используйте только **SCRAM-SHA-256** для сетевых подключений и `peer` для локального администратора.
```conf
# TYPE  DATABASE        USER            ADDRESS                 METHOD
# Только локальный вход через сокет для администратора
local   all             postgres                                peer
# Доступ для приложения по сети с шифрованием (пример адреса — замените на свой)
hostssl my_app_db      app_user        10.0.5.10/32            scram-sha-256
```
`hostssl` разрешает подключение только по TLS. Для полного запрета незашифрованных соединений дополнительно включите `ssl = on` в `postgresql.conf` и выдайте серверу сертификат (`ssl_cert_file`, `ssl_key_file`).

**2. Глубокий аудит (pgAudit):**
Расширение `pgaudit` необходимо для комплаенса (PCI DSS, HIPAA).
```sql
-- Включение в конфигурации (требует перезапуска: shared_preload_libraries)
ALTER SYSTEM SET shared_preload_libraries = 'pgaudit';
-- Логирование всех DDL и операций с правами
ALTER SYSTEM SET pgaudit.log = 'read, write, function, role, ddl';
```

**3. Валидация:**
```sql
-- Синтаксические ошибки и фактические правила pg_hba.conf
SELECT line_number, type, database, user_name, address, auth_method, error
FROM pg_hba_file_rules WHERE error IS NOT NULL;
-- → 0 строк при корректном файле

SHOW password_encryption;
-- → scram-sha-256
```
```bash
# Применить изменения pg_hba.conf без перезапуска
sudo -u postgres psql -c "SELECT pg_reload_conf();"
```

### MongoDB: RBAC и защита WiredTiger

В MongoDB 8.x авторизация **выключена по умолчанию** в автономных инстансах — это критическая уязвимость конфигурации по умолчанию (сервер выдаёт предупреждение при старте). Включайте её до подключения инстанса к сети.

**1. Включение авторизации (`mongod.conf`):**
```yaml
security:
  authorization: enabled
  javascriptEnabled: false # Отключение выполнения JS на сервере
net:
  bindIp: 127.0.0.1,10.0.5.30 # По умолчанию только localhost — не расширяйте без необходимости
```

**2. Создание администратора (mongosh):**
Первый пользователь обязан быть администратором пользователей в базе `admin` (иначе после включения `authorization` невозможно управлять аккаунтами):
```javascript
use admin
db.createUser({
  user: "siteAdmin",
  pwd: passwordPrompt(),
  roles: [{ role: "userAdminAnyDatabase", db: "admin" }]
})
```

**3. Валидация и граничный случай:**
```javascript
// Статус аутентификации текущего подключения
db.runCommand({connectionStatus: 1})
// → "authenticatedUsers": [ { "user": "siteAdmin", "db": "admin" } ]
```
- **Localhost exception:** при включённом `authorization` и отсутствии пользователей MongoDB разрешает создать первого пользователя только с localhost. Это окно закрывается сразу после создания первого аккаунта — создавайте администратора до вывода инстанса в сеть.
- LDAP-аутентификация и LDAP-авторизация в MongoDB 8.0 объявлены устаревшими и будут удалены в будущем релизе — для новых развёртываний используйте SCRAM-SHA-256 или X.509.

### Redis: ACL и изоляция команд

Redis 8.x (и форк Valkey 9.x) больше не является «просто кэшем без пароля»: по умолчанию `protected-mode yes` и прослушивание только localhost, но при открытии порта в сеть требуется явная авторизация.

**1. Использование ACL (Access Control Lists):**
Вместо глобального пароля `requirepass` создавайте пользователей с ограниченными правами:
```bash
# В redis-cli
ACL SETUSER app-user on >StrongPass2026! ~cached:* +get +set -@dangerous
ACL SAVE   # сохранить пользователей в файл, заданный директивой aclfile в redis.conf
```
*Команда запрещает категории опасных команд (`@dangerous`) и разрешает доступ только к ключам с префиксом `cached:`.* Без директивы `aclfile` в `redis.conf` изменения ACL живут только в памяти и теряются при перезапуске.

**2. Отключение опасных команд:**
Если вы не используете ACL, переименуйте или отключите опасные команды в `redis.conf`:
```conf
rename-command FLUSHALL ""
rename-command CONFIG "SUPER_SECRET_CONFIG_CMD"
```
*`rename-command` читается только при старте сервера — изменение требует перезапуска. Учтите: переименование `CONFIG` ломает утилиты мониторинга, которые его используют.*

**3. Валидация:**
```bash
redis-cli ACL LIST          # → список пользователей и их масок
redis-cli ACL WHOAMI        # → default (или имя текущего пользователя)
redis-cli CONFIG GET requirepass   # → пустое значение: глобальный пароль не задан
```

## Системная закалка (Host Hardening)

Безопасность СУБД невозможна без защиты ОС.

1.  **Привилегии процесса:**
    *   Никогда не запускайте СУБД от имени `root`.
    *   Ограничьте права на директории данных: `chmod 700 /var/lib/postgresql/data` (PostgreSQL), владелец `mysql:mysql` и права `750` на `datadir` (MySQL/MariaDB), `mongodb:mongodb 700` на `/var/lib/mongodb`.
2.  **SELinux / AppArmor:**
    *   Профили защищают от эксплуатации уязвимостей типа «выход за пределы директории» (Path Traversal).
    *   Проверка статуса: `sestatus` или `apparmor_status`.
3.  **Лимиты и квоты:**
    *   Настройте `/etc/security/limits.conf` для предотвращения атак на исчерпание ресурсов (DoS).
4.  **Дампы памяти и swap:**
    *   Отключите core dumps для сервиса СУБД (`LimitCORE=0` в systemd-юните, `fs.suid_dumpable=0` в sysctl) — дамп содержит ключи и данные.
    *   Шифруйте swap (LUKS/cryptswap): страницы памяти СУБД могут содержать ключи шифрования.
5.  **Аудит доступа к данным на уровне ОС:**
    *   Правило auditd на каталог данных: `-w /var/lib/mysql -p wa -k mysql_data` — фиксация записей в `datadir` вне СУБД.

## Управление секретами и аудит

1.  **HashiCorp Vault:**
    *   Используйте **Database Secrets Engine** для генерации динамических учетных данных с коротким TTL (например, 1 час). Это исключает риск утечки долгоживущих паролей.
2.  **Мониторинг безопасности (SIEM/Wazuh):**
    *   Настройте сбор логов ошибок и аутентификации.
    *   Используйте eBPF для мониторинга аномальных сетевых соединений от процесса БД.
    *   Ключевые сигналы для алертов: всплеск `Access denied` / `Failed login`, отключение аудита, подключения с нехарактерных IP, сетевое использование аккаунтов `root`/`postgres`.

## Валидация конфигурации (сводная таблица команд)

| СУБД | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| MySQL/MariaDB | `SELECT user,host,plugin FROM mysql.user;` | Нет анонимных (`user=''`) и удалённых root-аккаунтов; плагин — `caching_sha2_password`/`unix_socket`/`ed25519` |
| PostgreSQL | `SELECT * FROM pg_hba_file_rules WHERE error IS NOT NULL;` | 0 строк; сетевые правила — `scram-sha-256` |
| MongoDB | `show dbs` без учетных данных | Ошибка `command ... requires authentication` |
| Redis | `redis-cli ACL LIST` | Пользователи с масками ключей и команд; `default` либо отключён, либо с паролем |
| Все | `ss -tlnp \| grep -E '3306\|5432\|27017\|6379'` | Слушание только на ожидаемых интерфейсах |

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| MySQL `ERROR 1524 (HY000): Plugin 'mysql_native_password' is not loaded` | Аккаунт использует плагин, удалённый в 9.0 (или отключённый по умолчанию в 8.4) | В 8.4: временно `mysql_native_password=ON`, затем `ALTER USER ... IDENTIFIED WITH caching_sha2_password`; в 9.x — войти под другим админом и мигрировать аккаунт. Детали: **[MySQL security](./MySQL/security.md)** |
| PostgreSQL `FATAL: no pg_hba.conf entry for host "..."` | Нет правила для пары (база, пользователь, адрес) | Добавить строку в `pg_hba.conf`, выполнить `SELECT pg_reload_conf();` |
| PostgreSQL `FATAL: password authentication failed` при верном пароле | Хэш пароля в формате md5, а метод в `pg_hba.conf` — `scram-sha-256` | Сбросить пароль (`ALTER ROLE ... PASSWORD '...'`) — хэш перевычислится по `password_encryption` |
| MongoDB `command ... requires authentication` | Включено `authorization`, подключение без учетных данных | Аутентифицироваться (`mongosh -u ... -p ... --authenticationDatabase admin`) или создать первого пользователя с localhost |
| Redis `WRONGPASS invalid username-password pair` | ACL-пользователь не создан или неверный пароль | `ACL SETUSER ...`, контроль через `ACL LIST` |
| Redis `NOPERM ... command not allowed` | Команда запрещена маской ACL пользователя | Расширить права: `ACL SETUSER user +command` |
| После `bind-address` / `bindIp` — нет подключений | Сервер слушает другой интерфейс или блокирует файрвол | `ss -tlnp`, проверка правил UFW/firewalld |

## Best Practices и откат изменений

- **Перед изменениями:** копия конфигов (`cp my.cnf my.cnf.bak.$(date +%F)` и аналогично для `pg_hba.conf`, `mongod.conf`, `redis.conf`) и бэкап системных баз.
- **Откат:** MySQL/MariaDB — убрать параметр из `my.cnf` и перезапустить; PostgreSQL — `pg_reload_conf()` для `pg_hba.conf` (перезапуск нужен только для `shared_preload_libraries`); Redis — `CONFIG SET` для runtime-параметров, перезапуск для `rename-command`; MongoDB — перезапуск без `--auth` только как крайняя мера восстановления доступа (с немедленным исправлением пользователей).
- **Непрерывная закалка:** разовые скрипты — только базовый уровень. Регулярно проверяйте: актуальность версий и CVE-обновлений, лишние привилегии, срок TLS-сертификатов, статус аудита. Методология — в **[CIS Benchmark для MariaDB](./MariaDB/security/cis-benchmark.md)**.

## Дополнительная информация

### Чек-лист безопасности (Production Readiness)
- [ ] Пароли по умолчанию удалены, анонимные пользователи и тестовые БД удалены.
- [ ] Удаленный доступ для суперпользователей запрещен (только `localhost`/unix_socket).
- [ ] Используется TLS для всех соединений (`hostssl` в PostgreSQL, `requireTLS` в MongoDB, `tls-port` в Redis).
- [ ] Учетные данные приложения имеют доступ только к необходимым таблицам (DML, но не DDL).
- [ ] Бэкапы зашифрованы и проверяются на восстановление.
- [ ] Регулярное сканирование на уязвимости (CVE) и обновление пакетов.
- [ ] Аудит включён, логи отправляются в SIEM, настроены алерты на всплеск отказов аутентификации.
- [ ] Секреты — динамические (Vault) или ротируемые; статические пароли не хранятся в конфигах.
- [ ] `datadir` принадлежит непривилегированному пользователю, права 700/750; SELinux/AppArmor в `enforce`.
- [ ] Core dumps отключены, swap зашифрован.

### Смежные темы
- Настройка PostgreSQL — **[Обзор PostgreSQL](./PostgreSQL/overview.md)**
- Настройка MySQL — **[Установка MySQL](./MySQL/installation.md)**
- Безопасность MySQL (TDE, TLS, аудит) — **[MySQL security](./MySQL/security.md)**
- Безопасность MariaDB — **[Обзор безопасности MariaDB](./MariaDB/security/index.md)**
- Безопасность и шифрование PostgreSQL — **[PostgreSQL security](./PostgreSQL/Concepts/security_and_encryption.md)**
- Redis: версии, ACL, форки — **[Обзор Redis](./redis_overview.md)**
- Безопасность Neo4j — **[Neo4j security](./Neo4j/security.md)**
- Безопасность Cassandra/ScyllaDB — **[Cassandra security](./cassandra-scylladb/security.md)**
- Безопасность ClickHouse — **[ClickHouse Operations](./ClickHouse/clickhouse-operations.md)**
- Резервное копирование — **[Безопасность бэкапов](./Concepts/backup_security.md)**
- Управление секретами — **[HashiCorp Vault](../Vault/overview.md)**
- Комплаенс и аудит — **[Аудит и комплаенс](../Security/audit_and_compliance_overview.md)**
