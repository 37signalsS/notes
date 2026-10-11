# CIS Benchmark для MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS (применяется CIS MariaDB Benchmark 10.11, v1.0.0); MariaDB 10.6 (CIS Benchmark v1.1.0) — legacy: EOL 6 июля 2026, только поддержка существующих развёртываний

## Определения

**CIS Benchmark** — набор рекомендаций по безопасной конфигурации от Center for Internet Security (CIS). Для MariaDB опубликованы CIS MariaDB Benchmark для **10.6 (v1.1.0)** и **10.11 (v1.0.0)**; для 11.x/12.x отдельного документа нет — применяются контрлы benchmark 10.11 (контроли стабильны между минорными сериями). Документ содержит пронумерованные контрлы с профилями Level 1 (базовый) и Level 2 (углублённый). Полный текст распространяется CIS **бесплатно в PDF** для некоммерческого использования (требуется бесплатная учётная запись CIS); данный файл не воспроизводит его, а маппит контрольные семейства на конкретные параметры MariaDB и команды проверки. Для MariaDB Enterprise отдельно выпускается CIS MariaDB Enterprise 10.x **STIG** (v1.1.0).

**Профиль Level 1 / Level 2** — уровни строгости контрлов CIS. Level 1 — минимальные меры, применимые без нарушения работоспособности; Level 2 — усиленные меры для сред с высокими требованиями (часть контрлов Level 2 может влиять на совместимость или производительность).

**Контроль (control)** — отдельная проверяемая рекомендация: утверждение о желаемом состоянии конфигурации, метод проверки и процедура исправления.

**Scoring / Not Scoring** — классификация контрлов CIS: scoring-контроли влияют на итоговый score соответствия, not-scoring — носят рекомендательный характер (например, рекомендации по мониторингу).

## Основные концепции

### Структура контроля CIS для СУБД

Каждый контроль CIS для MariaDB содержит:

1. **Описание** — что именно требуется (например, «убедиться, что анонимные учётные записи удалены»).
2. **Rationale** — обоснование риска.
3. **Audit** — команда или SQL-запрос для проверки текущего состояния.
4. **Remediation** — процедура приведения к требуемому состоянию.
5. **Impact** — возможные последствия применения.

### Контрольные семейства, релевантные MariaDB

| Семейство | Ключевые контрлы | Где в базе знаний |
| :--- | :--- | :--- |
| Инвентаризация и патчи | актуальная версия, удаление неиспользуемых плагинов | [Обзор](../overview.md) |
| Учётные записи | удаление анонимных пользователей, `test`-БД, сетевого root | [Начальная закалка](hardening.md) |
| Аутентификация | политика паролей, PAM, `unix_socket` | [Аутентификация](authentication.md) |
| Сеть | `bind-address`, файрвол, `skip-networking` | [Сетевая безопасность](network-security.md) |
| Шифрование трафика | TLS, `require_secure_transport` | [SSL/TLS](ssl-tls.md) |
| Авторизация | RBAC, запрет `SUPER`/`FILE` приложениям | [RBAC](rbac.md) |
| Аудит | `server_audit`, ротация логов | [Аудит](audit.md) |
| Шифрование данных | TDE, ключи отдельно от данных | [TDE](tde.md) |
| Файловая система | права на datadir, `my.cnf`, логи | ниже, раздел «Файловые контрлы» |
| Ресурсные лимиты | `max_user_connections`, таймауты | [Сетевая безопасность](network-security.md) |

### Почему CIS Benchmark не заменяет hardening-скрипт

`mariadb-secure-installation` закрывает только типовые ошибки (анонимные пользователи, `test`, сетевой root). CIS Benchmark охватывает большее: файловые права, ротацию логов, ограничение привилегий, TLS, аудит. Скрипт — первый шаг, Benchmark — целевое состояние.

## Предварительные требования

- MariaDB 10.11 / 11.4 / 11.8 / 12.3 LTS (MariaDB 10.6 — EOL 6 июля 2026: только поддержка существующих развёртываний, планируйте миграцию на 10.11+)
- Права root/sudo для изменения `my.cnf` и прав на файлы
- Доступ к файрволу хоста
- Для автоматизации проверки: `mariadb` CLI, `ss`, `stat`

## Практические сценарии

### Сценарий 1: Быстрая оценка соответствия (self-assessment)

Последовательность проверок, покрывающая основные контролы CIS. Выполняется от root и от пользователя MariaDB.

```bash
# 1. Версия и патч-уровень (должна быть в поддерживаемой серии)
mariadb --version
# → mariadb  Ver 15.1 Distrib 11.4.12-MariaDB ...
# → 10.6.x — EOL с 6 июля 2026: контроль не проходит, требуется апгрейд

# 2. Отсутствие анонимных пользователей
mariadb -e "SELECT User, Host FROM mysql.user WHERE User = '';"
# → (пустой результат — хорошо)

# 3. Отсутствие сетевого root
mariadb -e "SELECT User, Host FROM mysql.user WHERE User = 'root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');"
# → (пустой результат — хорошо)

# 4. Отсутствие test-БД
mariadb -e "SHOW DATABASES LIKE 'test';"
# → (пустой результат — хорошо)

# 5. Привязка к внутреннему интерфейсу
ss -tlnp | grep 3306
# → LISTEN 0 80 10.0.5.20:3306 (не 0.0.0.0:3306)

# 6. Права на datadir
stat -c '%a %U:%G' /var/lib/mysql
# → 750 mysql:mysql (или 700)

# 7. Права на my.cnf
stat -c '%a %U:%G' /etc/my.cnf /etc/mysql/my.cnf 2>/dev/null
# → 644 root:root (конфиг не должен быть записываемым для mysql)

# 8. Принудительный TLS
mariadb -e "SHOW VARIABLES LIKE 'require_secure_transport';"
# → require_secure_transport | ON

# 9. local-infile отключён
mariadb -e "SHOW VARIABLES LIKE 'local_infile';"
# → local_infile | OFF

# 10. Аудит активен
mariadb -e "SHOW PLUGINS LIKE 'server_audit';"
# → server_audit | ACTIVE
```

### Сценарий 2: Приведение конфигурации к профилю Level 1

```ini
[mariadb]
# Учётные записи и сеть
bind-address        = 10.0.5.20
# skip-name-resolve: гранты задаются по IP/CIDR ('user'@'10.0.5.%');
# hostname-гранты перестанут матчить TCP-подключения (см. «Граничные случаи»)
skip-name-resolve   = 1

# Принудительный TLS
require_secure_transport = ON
ssl_cert = /etc/mysql/ssl/server-cert.pem
ssl_key  = /etc/mysql/ssl/server-key.pem

# Ограничения
max_user_connections = 50
wait_timeout         = 600
interactive_timeout  = 600

# Hardening
local-infile      = 0
skip-show-database = 1
symbolic-links    = 0

# Аудит
plugin_load_add     = server_audit
server_audit_events = CONNECT, QUERY, TABLE
server_audit_logging = ON
server_audit_syslog  = ON
```

### Сценарий 3: Файловые контрлы

```bash
# datadir: доступ только mysql-пользователю
sudo chown -R mysql:mysql /var/lib/mysql
sudo chmod 750 /var/lib/mysql

# Конфиг: читаем всем, пишут только root
sudo chown root:root /etc/my.cnf
sudo chmod 644 /etc/my.cnf

# Логи: не доступны для чтения посторонним
sudo chown mysql:mysql /var/log/mysql/
sudo chmod 750 /var/log/mysql/

# Проверка
ls -ld /var/lib/mysql /var/log/mysql
# → drwxr-x--- mysql mysql /var/lib/mysql
# → drwxr-x--- mysql mysql /var/log/mysql
```

## Проверка и валидация

### Критерии соответствия профилю Level 1

| Контроль | Команда проверки | Ожидаемый результат |
| :--- | :--- | :--- |
| Нет анонимных пользователей | `SELECT User FROM mysql.user WHERE User='';` | пустой результат |
| Нет сетевого root | `SELECT Host FROM mysql.user WHERE User='root' AND Host NOT LIKE 'localhost';` | пустой результат |
| Нет test-БД | `SHOW DATABASES LIKE 'test';` | пустой результат |
| Слушает на внутреннем IP | `ss -tlnp \| grep 3306` | конкретный IP, не 0.0.0.0 |
| TLS обязателен | `SHOW VARIABLES LIKE 'require_secure_transport';` | `ON` |
| local-infile выключен | `SHOW VARIABLES LIKE 'local_infile';` | `OFF` |
| Аудит активен | `SHOW PLUGINS LIKE 'server_audit';` | `ACTIVE` |
| Права datadir | `stat -c '%a' /var/lib/mysql` | `750` или `700` |
| Версия в поддержке | `mariadb --version` | 10.11 / 11.4 / 11.8 / 12.3 (10.6 — EOL) |
| Конфиг не пишет mysql | `stat -c '%a %U:%G' /etc/my.cnf` | `644 root:root` |
| Ротация аудит-логов | см. [Аудит](audit.md) | настроена ротация, логи не на datadir |

### Регулярный аудит

```bash
# Ежемесячная проверка привилегий
mariadb -e "SELECT User, Host, Super_priv, File_priv, Process_priv FROM mysql.user WHERE Super_priv='Y' OR File_priv='Y';"
# → только административные учётные записи

# Учётные записи с hostname-грантами (перевести на IP/CIDR до включения skip-name-resolve)
mariadb -e "SELECT User, Host FROM mysql.user WHERE Host NOT IN ('localhost', '%') AND Host NOT REGEXP '^[0-9.:%]+$';"
# → пустой результат или список для конвертации
```

## Устранение неполадок

### Контроль «сломан» после обновления пакета

**Симптом:** после `yum update` / `apt upgrade` конфигурация вернулась к дефолтам.

**Причина:** пакетный менеджер установил новый `my.cnf` или `rpmnew`/`dpkg-dist` файл, а сервис перечитал конфигурацию.

**Решение:**
1. Сравните конфиги: `diff /etc/my.cnf /etc/my.cnf.rpmnew`
2. Внесите изменения в свой файл в `/etc/mysql/conf.d/` (приоритет при загрузке)
3. Перезапустите: `sudo systemctl restart mariadb`

### `require_secure_transport` блокирует легитимных клиентов

**Симптом:** клиенты без TLS получают `ERROR 2026 (HY000): SSL connection error`.

**Решение:** обновите клиентские драйверы или выдайте сертификаты; временный обход — не отключайте переменную, а настройте TLS на клиентах. Подробнее: [SSL/TLS](ssl-tls.md).

### `skip-name-resolve` ломает гранты по hostname

**Симптом:** после включения `skip-name-resolve` клиенты получают `ERROR 1045 (28000): Access denied`; в логе — предупреждения вида `'user' entry 'app@db.example.internal' ignored in --skip-name-resolve mode`.

**Причина:** при `skip-name-resolve` сервер не выполняет обратный DNS-резолвинг IP клиента, поэтому гранты вида `'user'@'hostname'` не матчат TCP-подключения. Имя `localhost` (Unix-сокет) работает всегда.

**Решение:**
1. Переведите гранты на IP/CIDR: `CREATE USER 'app'@'10.0.5.%' IDENTIFIED BY '...'; GRANT SELECT, INSERT ON db.* TO 'app'@'10.0.5.%';`
2. Удалите hostname-гранты: `REVOKE ... FROM 'app'@'db.example.internal'; DROP USER 'app'@'db.example.internal';`
3. Переменная read-only (`SET GLOBAL` не работает): отключается удалением параметра из `my.cnf` или опцией `disable-skip-name-resolve = 1` (MariaDB)

## Лучшие практики

1. **Документируйте отклонения.** Контролы CIS, которые не применяются (например, Level 2), фиксируйте с обоснованием — это часть комплаенс-отчётности.
2. **Автоматизируйте проверку.** Превратите сценарий 1 в скрипт или Ansible-таск и запускайте по расписанию; Ansible-реализация — в [Автоматизация hardening](automation-hardening.md). CIS-CAT Pro — официальный инструмент оценки соответствия бенчмаркам (платная подписка CIS SecureSuite); для MariaDB практическую проверку обычно строят по сценарию 1.
3. **Применяйте Level 2 осознанно.** Контролы Level 2 (например, жёсткие таймауты, ограничение `PROCESS`) могут сломать мониторинг и пулы соединений — тестируйте на staging.
4. **CIS — не замена угрозному моделированию.** Benchmark задаёт базовый уровень; специфику приложения (маскирование, RLS) решайте отдельно.

## Дополнительная информация

### Ограничения

- Полный текст CIS MariaDB Benchmark — бесплатный PDF для некоммерческого использования (требуется учётная запись CIS); данный файл содержит только маппинг семейств контролей.
- Отдельного benchmark для MariaDB 11.x/12.x не опубликовано: для этих серий применяются контрлы CIS MariaDB Benchmark 10.11 (v1.0.0).
- Нумерация контрлов в официальном документе меняется между релизами; ориентируйтесь на семейства, а не на номера.

### Граничные случаи

- **`skip-name-resolve` и hostname-гранты.** Контроль из сценария 2 ломает гранты по DNS-именам; предварительная проверка — в разделе «Регулярный аудит», решение — в «Устранении неполадок».
- **Проверка «нет test-БД» на свежих инсталляциях.** С MariaDB 10.4 база `test` не создаётся по умолчанию — контроль проходит «всегда истинно». На апгрейдах с 10.3 и старше база может сохраниться; проверяйте её наличие, а не отсутствие ошибки.
- **`local_infile = 0` ломает дампы.** `mariadb-dump --tab` и `LOAD DATA LOCAL INFILE` в клиентах перестают работать; отключайте, только если приложения не используют эти механизмы.
- **`skip-show-database` ломает introspect-схемы.** ORM и агенты мониторинга, делающие `SHOW DATABASES`, перестают видеть схемы; выдайте привилегию `SHOW DATABASES` сервисным аккаунтам или отключите контроль.
- **Права datadir и SELinux/AppArmor.** `chmod 750` не меняет контекст безопасности; при SELinux проверяйте `ls -Z /var/lib/mysql` и применяйте `restorecon` при переносе datadir.
- **Ключи TLS и молчаливый отказ.** `ssl_key` должен читаться пользователем `mysql` (`600`/`640`, owner `mysql` или `root:mysql`). Начиная с MariaDB 10.6.11 некорректный TLS больше не отключается молча (MDEV-29811) — сервер сообщает ошибку при старте вместо работы в plaintext.
- **`mysql.user` — view.** Начиная с MariaDB 10.4 таблица `mysql.user` является представлением над `mysql.global_priv`; SQL-проверки из сценария 1 остаются валидны, но прямые `UPDATE mysql.user` не поддерживаются — используйте `GRANT`/`CREATE USER`.

### Смежные темы

- **[Начальная закалка](hardening.md)** — `mariadb-secure-installation`.
- **[Аутентификация и политика паролей](authentication.md)** — плагины, `validate_password`.
- **[SSL/TLS](ssl-tls.md)** — TLS-конфигурация.
- **[Сетевая безопасность](network-security.md)** — `bind-address`, файрвол.
- **[Аудит](audit.md)** — `server_audit`.
- **[Шифрование данных (TDE)](tde.md)** — шифрование на диске.
- **[Ролевая модель (RBAC)](rbac.md)** — привилегии.
- **[Автоматизация hardening](automation-hardening.md)** — Ansible-плейбук.
- **[Комплаенс](compliance.md)** — маппинг PCI DSS / GDPR / ФСТЭК.
- **[CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks)** — официальный сайт проекта (внешний ресурс).
