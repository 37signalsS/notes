# SQL-инъекции (SQL Injection)

## Определение

**SQL-инъекция (SQLi)** — это тип атаки на веб-приложения, при которой злоумышленник внедряет вредоносный SQL-код в запрос к базе данных через входные данные приложения. Если приложение недостаточно очищает ввод или неправильно формирует запрос, база данных может исполнить этот код как часть легитимной команды.

**Последствия успешной атаки:**
- **Компрометация данных:** кража персональной информации, паролей, финансовых данных.
- **Обход аутентификации:** вход в систему без знания пароля.
- **Нарушение целостности:** несанкционированное изменение или удаление записей в БД.
- **Удаленное выполнение команд (RCE):** выполнение команд на уровне ОС сервера через функции СУБД (например, `xp_cmdshell` в MSSQL).
- **Латеральное движение:** получение доступа к другим базам или сервисам внутри сегмента сети.

## Классификация типов SQL-инъекций

| Тип | Механизм | Особенности |
| :--- | :--- | :--- |
| **In-band (Классическая)** | Тот же канал используется для атаки и получения результата. | Включает **Error-based** (через ошибки) и **UNION-based** (объединение результатов). |
| **Inferential (Blind / Слепая)** | Ответ приложения не содержит данных напрямую, но меняется в зависимости от условий. | **Boolean-based** (ответ True/False) или **Time-based** (задержка через `SLEEP()` или `pg_sleep()`). |
| **Second-order (Второго порядка)** | Нагрузка сохраняется в БД и срабатывает позже при другом запросе. | Трудно обнаружить сканерами, так как инъекция "спит" до обращения к данным. |
| **Out-of-band (OOB / OAST)** | Данные выводятся через внешний канал (DNS/HTTP запрос от СУБД к серверу атакующего). | Используется, когда прямые каналы вывода заблокированы. В 2026 году автоматизируется через инструменты **OAST**. |

## Основные концепции и механизм атаки

### Уязвимый код (Конкатенация строк)

Проблема возникает, когда ввод пользователя напрямую склеивается со строкой запроса.

**PHP (УЯЗВИМО):**
```php
$query = "SELECT * FROM users WHERE username = '" . $_POST['user'] . "'";
```

Если пользователь введет `' OR '1'='1`, запрос превратится в:
`SELECT * FROM users WHERE username = '' OR '1'='1'` — условие всегда истинно, и атакующий авторизуется без пароля.

### Специфика популярных СУБД

1.  **MySQL / MariaDB:** Использование комментариев `#` или `-- ` для отсечения остатка запроса.
    - Пример: `admin' #`
2.  **PostgreSQL:** Поддержка "склеенных" запросов через `;`. Возможность использования `COPY` для чтения файлов.
    - Пример: `'; DROP TABLE logs; --`
3.  **MSSQL:** Выполнение системных процедур.
    - Пример: `'; EXEC xp_cmdshell 'whoami'; --`
4.  **Oracle:** Работа с системными таблицами `DUAL` и `ALL_TABLES`. Специфический синтаксис конкатенации через `||`.
    - Пример: `' UNION SELECT username, password FROM users --`

### Динамический SQL и хранимые процедуры

Динамический SQL внутри хранимых объектов — источник SQL-инъекций, если входные параметры не экранированы.

**PostgreSQL (PL/pgSQL) — ОПАСНО:**
```sql
CREATE OR REPLACE FUNCTION unsafe_search(p_table TEXT)
RETURNS TABLE(id INT, name TEXT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY EXECUTE format('SELECT id, name FROM ' || p_table);
END;
$$;
```

**PostgreSQL (PL/pgSQL) — БЕЗОПАСНО:**
```sql
CREATE OR REPLACE FUNCTION safe_search(p_table TEXT)
RETURNS TABLE(id INT, name TEXT)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY EXECUTE format('SELECT id, name FROM %I', p_table);
END;
$$;
```

Идентификатор `%I` экранирует значение как идентификатор (имя таблицы/колонки), предотвращая инъекцию.

## Предпосылки и системные требования

### Железо и ОС

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| **CPU** | 2 cores | 4+ cores для SAST/DAST агентов |
| **RAM** | 4 GB | 8+ GB для SonarQube/ZAP в CI |
| **Диск** | 20 GB | 50+ GB для логов аудита и бэкапов |
| **ОС** | Debian 12+, RHEL/Rocky 9+, Ubuntu 22.04 LTS | |

### Ядро и сетевые параметры

```bash
# Проверка версии ядра (требуются modern audit capabilities)
uname -r

# Включение аудита ядра (если не включен)
sudo auditctl -e 1
```

### Программный стек

| Инструмент | Версия | Назначение |
| :--- | :--- | :--- |
| **nftables** | 1.0+ | Фильтрация сетевого трафика |
| **fail2ban** | 0.11+ | Автоматическая блокировка IP |
| **Prometheus** | 2.40+ | Сбор метрик и алертинг |
| **sqlmap** | 1.7+ | Тестирование на проникновение |
| **Semgrep** | 1.50+ | Статический анализ кода |
| **OWASP ZAP** | 2.12+ | Динамическое сканирование |

### Базовая настройка окружения

```bash
# Установка зависимостей (Debian/Ubuntu)
sudo apt update
sudo apt install -y nftables fail2ban prometheus-node-exporter \
    sqlmap semgrep openjdk-17-jre-headless

# Включение и запуск fail2ban
sudo systemctl enable --now fail2ban

# Проверка nftables
sudo nft list ruleset | head -5
```

## Методы защиты

### 1. Подготовленные выражения (Prepared Statements)

**Это основной и наиболее надежный метод защиты.** Код запроса и данные разделяются на уровне протокола СУБД.

- **Python (`psycopg2`):** `cursor.execute("SELECT * FROM users WHERE email = %s", (user_email,))`
- **Java (Spring Data JPA):** использование `@Param` и именованных параметров в `@Query`.
- **Go (`database/sql`):** `db.Query("SELECT id FROM users WHERE age > ?", minAge)`
- **Rust (`sqlx`):** `sqlx::query!("SELECT * FROM users WHERE id = ?", id)` (проверка типов на этапе компиляции).
- **Node.js (`pg`):** `client.query('SELECT * FROM users WHERE id = $1', [userId])`
- **Bash (psql):** Использование параметризованных скриптов через `--set` и `:variable`.

### 2. Использование ORM (Object-Relational Mapping)

Современные ORM (SQLAlchemy, Django ORM, Hibernate) по умолчанию используют параметризацию.
**ОПАСНОСТЬ:** Использование "сырых" (raw) запросов внутри ORM без параметров:
```python
# ОПАСНО (Django)
User.objects.raw("SELECT * FROM users WHERE name = %s" % user_name) 

# БЕЗОПАСНО
User.objects.raw("SELECT * FROM users WHERE name = %s", [user_name])
```

### 3. Принцип наименьших привилегий

- Учетная запись приложения не должна иметь прав на `DROP`, `TRUNCATE`, `ALTER`.
- Отключение опасных функций (`xp_cmdshell`, `LOAD_FILE`, `COPY` для суперпользователя).
- Использование Row-Level Security (RLS) для ограничения доступа к строкам.
- Подробнее: **[Безопасность СУБД](../../Databases/installation_security.md)**.

### 4. Валидация и санитизация

- **Allowlisting:** Белый список имен таблиц и колонок для динамических запросов.
- **Типизация:** Строгое приведение к типу (например, `(int)$user_id`).
- **Цифровая подпись запросов:** В высокоценных системах — подпись параметров запроса HMAC для предотвращения подделки.

### 4a. Защита на стороне MariaDB (Server-side defenses)

Даже при наличии уязвимости в приложении СУБД может ограничить ущерб. Эти меры — второй рубеж, не замена prepared statements.

**Запрет чтения файлов клиента:**
```ini
[mariadb]
# Отключает LOAD DATA LOCAL INFILE (чтение файлов с клиента через инъекцию)
local-infile = 0
```
```sql
-- Проверка
SHOW VARIABLES LIKE 'local_infile';
-- → OFF
```

**Ограничение файловых операций:**
```ini
[mariadb]
# Директория для LOAD DATA INFILE / SELECT ... INTO OUTFILE
secure_file_priv = /var/lib/mysql-files/
```
```sql
-- Проверка: только указанная директория доступна
SHOW VARIABLES LIKE 'secure_file_priv';
-- → /var/lib/mysql-files/
```

**Безопасный sql_mode:**
```ini
[mariadb]
sql_mode = STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION
```

**Принцип наименьших привилегий (MariaDB RBAC):**
```sql
-- Приложение не должно иметь FILE, SUPER, PROCESS
CREATE ROLE app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON app_db.* TO app_role;
-- НЕ выдавайте: FILE, SUPER, PROCESS, SHUTDOWN
```

**Аудит доступа к таблицам (TABLE event):**
```ini
[mariadb]
# Логирование доступа к таблицам без полного текста запроса
server_audit_events = CONNECT,TABLE,QUERY_DDL
```

Подробнее: **[Безопасность MariaDB](../../Databases/MariaDB/security/index.md)**, **[RBAC](../../Databases/MariaDB/security/rbac.md)**, **[Дополнительные параметры](../../Databases/MariaDB/security/additional-parameters.md)**.

### 5. Аудит и логирование на уровне СУБД

Включение аудита позволяет обнаружить попытки SQL-инъекций, которые прошли через WAF.

**PostgreSQL (pgAudit):**
```sql
-- В postgresql.conf
shared_preload_libraries = 'pgaudit'
pgaudit.log = 'all, -read'
pgaudit.log_catalog = 'off'
pgaudit.log_level = 'log'
```

**MySQL Enterprise Audit:**
```sql
-- В my.cnf
[mysqld]
plugin-load-add = audit_log.so
audit_log_policy = "ALL"
audit_log_format = "JSON"
audit_log_handler = "FILE"
audit_log_file = "/var/log/mysql/audit.log"
```

**MariaDB (server_audit — бесплатный, в Community):**
```ini
# В my.cnf
[mariadb]
plugin_load_add = server_audit
server_audit = FORCE_PLUS_PERMANENT
server_audit_logging = ON
server_audit_events = CONNECT,QUERY,TABLE,QUERY_DDL
server_audit_output_type = SYSLOG
server_audit_syslog_facility = LOG_LOCAL6
```

Подробнее о настройке `server_audit`: **[Аудит в MariaDB](../../Databases/MariaDB/security/audit.md)**.

**MSSQL:**
```sql
-- Создание спецификации аудита
CREATE SERVER AUDIT SPECIFICATION [SQLiAudit]
FOR SERVER AUDIT [ServerAudit]
ADD (SELECT ON DATABASE::[appdb] BY [public]);
```

### 6. Сетевая фильтрация и автоматический ответ

Использование `fail2ban` для анализа логов приложения и автоматической блокировки IP при обнаружении признаков SQL-инъекций.

**fail2ban — фильтр для Nginx/SQLi:**
```ini
# /etc/fail2ban/filter.d/nginx-sqli.conf
[Definition]
failregex = ^<HOST> -.* "(GET|POST) .*(?:union.*select|select.*from|insert.*into|update.*set|delete.*from).* HTTP/.*" \d+ \d+
ignoreregex =
```

**fail2ban — jail:**
```ini
[nginx-sqli]
enabled = true
port = http,https
filter = nginx-sqli
logpath = /var/log/nginx/access.log
maxretry = 2
bantime = 86400
findtime = 600
banaction = nftables-multiport
```

### 7. Защита на уровне kernel и сети

- **nftables:** Rate limiting на соединения к БД, блокировка известных malicious IP.
- **SELinux/AppArmor:** Ограничение прав доступа процессов СУБД к файловой системе и сети.
- **Seccomp:** В контейнерных средах — ограничение системных вызовов.

## Практические сценарии

### Обнаружение попыток SQL-инъекций

#### Анализ логов веб-сервера

```bash
# Поиск классических паттернов в access.log
grep -iE "union.*select|select.*from|insert.*into|update.*set|delete.*from|sleep\(|benchmark\(" /var/log/nginx/access.log | tail -20

# Поиск по коду ответа (например, 403 от WAF)
grep " 403 " /var/log/nginx/access.log | grep -iE "sql|injection|union|select" | tail -20

# Топ IP по подозрительной активности
grep -iE "union.*select|select.*from" /var/log/nginx/access.log \
    | awk '{print $1}' | sort | uniq -c | sort -rn | head -10
```

#### Анализ логов СУБД

**PostgreSQL:**
```bash
# Поиск ошибок синтаксиса (признак инъекций)
grep -i "syntax error" /var/log/postgresql/postgresql-*.log | tail -20

# Поиск необычных запросов (долгие или сложные)
grep -i "duration:" /var/log/postgresql/postgresql-*.log \
    | awk -F'[: ]+' '{print $NF}' | sort -nr | head -20
```

**MySQL:**
```bash
# Включение общего лога (временно для расследования)
mysql -e "SET GLOBAL general_log = 'ON';"

# Просмотр лога
tail -f /var/log/mysql/mysql.log | grep -iE "union|select.*from|sleep"
```

### fail2ban: Автоматическая блокировка

Создание кастомного фильтра для SQL-инъекций:

```ini
# /etc/fail2ban/filter.d/nginx-sqli.conf
[Definition]
failregex = ^<HOST> -.* "(GET|POST) .*(?:union\s+select|select\s+.*\s+from|insert\s+into|update\s+.*\s+set|delete\s+from|sleep\s*\(|benchmark\s*\().* HTTP/\d\.\d"\s+\d{3}\s+\d+
ignoreregex =
```

Тестирование фильтра:

```bash
# Тестовый запуск fail2ban-regex
sudo fail2ban-regex /var/log/nginx/access.log /etc/fail2ban/filter.d/nginx-sqli.conf

# Ожидаемый вывод: найденные совпадения с IP и временем
```

Проверка статуса jail:

```bash
# Статус конкретного jail
sudo fail2ban-client status nginx-sqli

# Список забаненных IP
sudo fail2ban-client get nginx-sqli banip
```

### Мониторинг и оповещения

#### Метрики для Prometheus

| Метрика | Источник | Описание |
| :--- | :--- | :--- |
| `nginx_http_requests_total{status="403"}` | Node Exporter (nginx-vts) | Запросы с отказом |
| `modsecurity_requests_total` | ModSecurity Prometheus Exporter | Все запросы через WAF |
| `modsecurity_denied_requests_total` | ModSecurity Prometheus Exporter | Заблокированные запросы |
| `fail2ban_banned_ip` | Custom Exporter | Забаненные IP |
| `pg_stat_activity_count` | postgres_exporter | Активные соединения |
| `mysql_global_status_aborted_clients` | mysqld_exporter | Абортированные соединения |

#### Recording Rules (Prometheus)

```yaml
# /etc/prometheus/rules/sql_injection_alerts.yml
groups:
  - name: sql_injection_alerts
    rules:
      - alert: HighSQLInjectionAttemptRate
        expr: rate(modsecurity_denied_requests_total[5m]) > 10
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Высокий rate попыток SQL-инъекций"
          description: "{{ $value }} отказов в секунду от ModSecurity"

      - alert: Fail2BanHighBanRate
        expr: rate(fail2ban_banned_ip[10m]) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Активная блокировка IP fail2ban"
          description: "Заблокировано {{ $value }} IP за 10 минут"

      - alert: DatabaseHighAbortedConnections
        expr: rate(mysql_global_status_aborted_clients[5m]) > 20
        for: 3m
        labels:
          severity: critical
        annotations:
          summary: "Высокое число абортированных соединений к MySQL"
          description: "Возможна атака на БД"
```

#### Alertmanager маршрутизация

```yaml
# /etc/alertmanager/alertmanager.yml
route:
  receiver: 'security-team'
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h

  routes:
    - match:
        severity: critical
      receiver: 'security-team-pagerduty'
    - match:
        severity: warning
      receiver: 'security-team-slack'
```

### Валидация и нагрузочное тестирование

#### Тестирование подготовленных выражений

**Python:**
```python
import psycopg2

conn = psycopg2.connect("dbname=test user=app password=secret")
cur = conn.cursor()

# ПРОВЕРКА: попытка инъекции должна завершиться ошибкой или возвратить пустой результат
test_payloads = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "' UNION SELECT password FROM users --"
]

for payload in test_payloads:
    cur.execute("SELECT * FROM users WHERE username = %s", (payload,))
    result = cur.fetchall()
    assert len(result) == 0, f"Уязвимость! Payload: {payload}"
    print(f"OK: {payload[:20]}...")

conn.close()
```

#### Тестирование с sqlmap

```bash
# Безопасное тестирование на тестовом стенде
sqlmap -u "http://test-app.local/login?user=test&pass=test" \
    --batch --level=3 --risk=2 \
    --tamper=space2comment \
    --output-dir=/tmp/sqlmap-results

# Проверка, что уязвимостей не найдено
grep -c "vulnerable" /tmp/sqlmap-results/*/*.txt
# Ожидаемый результат: 0
```

#### Проверка конфигурации БД

**PostgreSQL — проверка RLS:**
```sql
-- Проверка: все чувствительные таблицы должны иметь RLS
SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
AND rowsecurity = 'f';
-- Ожидаемый результат: пустой (все таблицы защищены)
```

**MySQL — проверка пользователей:**
```sql
-- Поиск пользователей с опасными правами
SELECT user, host FROM mysql.user
WHERE Super_priv = 'Y'
OR File_priv = 'Y'
OR Shutdown_priv = 'Y';
-- Ожидаемый результат: только root@localhost (если вообще)
```

### Реагирование на инцидент

#### Пошаговый план реагирования

1.  **Изоляция:** Блокировка источника атаки на уровне LB или firewall.
    ```bash
    # Быстрая блокировка через nftables
    sudo nft add element inet filter blocklist { <attacker_ip> }
    ```

2.  **Сбор доказательств:** Архивирование логов до их ротации.
    ```bash
    # Архивирование логов
    tar -czf /tmp/incident-$(date +%Y%m%d-%H%M%S).tar.gz \
        /var/log/nginx/access.log \
        /var/log/postgresql/postgresql-*.log \
        /var/log/fail2ban.log
    ```

3.  **Аудит запросов:** Поиск несанкционированных изменений в БД.
    ```sql
    -- PostgreSQL: поиск необычных DDL-операций
    SELECT * FROM pg_stat_activity
    WHERE state = 'active'
    AND query NOT ILIKE '%SELECT%'
    AND query NOT ILIKE '%INSERT INTO audit_log%';
    ```

4.  **Восстановление:** Откат изменений из резервной копии.
    ```bash
    # Восстановление PostgreSQL
    pg_restore -d appdb /backups/appdb-$(date +%Y%m%d).dump
    ```

5.  **Устранение причины:** Исправление уязвимого кода, развертывание патча.

## Типичные проблемы и устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **WAF не блокирует SQLi** | Правила ModSecurity отключены или перезаписаны | Проверить `SecRuleEngine On`, `Include` CRS, проверить `audit.log` |
| **False Positive: блокировка легитимных запросов** | Слишком строгие правила, отсутствие allowlist | Настроить `SecRuleRemoveById`, добавить исключения для API |
| **ORM уязвим, несмотря на параметризацию** | Использование raw-запросов с конкатенацией | Аудит кода через Semgrep: `semgrep --config p/sql-injection` |
| **Вторая степень SQLi не обнаруживается сканерами** | Инъекция "спит" в БД | Проводить тестирование с учетом всего цикла данных, не только входной точки |
| **SQLi через JSON/API параметры** | Сканеры проверяют только query params | Включить в правила WAF проверку `REQUEST_BODY`, использовать DAST на API |
| **Высокая нагрузка от ModSecurity** | CPU overhead при RPS > 10 000 | Перейти на Coraza/NAXSI, вынести WAF на отдельный хост, использовать hardware acceleration |
| **fail2ban не банит IP** | Неправильный путь к логам или regex | Проверить `fail2ban-regex`, убедиться что jail активен |
| **Аудит СУБД не работает** | Расширение не загружено, нет прав | Проверить `shared_preload_libraries`, права на директорию логов |

## Дополнительная информация

### Инструменты анализа

| Инструмент | Категория | Назначение |
| :--- | :--- | :--- |
| **sqlmap** | DAST / Exploitation | Автоматизация поиска и эксплуатации SQLi. |
| **Semgrep** | SAST | Быстрый статический анализ по правилам. |
| **[SonarQube](../../CI-CD/Tools/sonarqube.md)** | SAST | Комплексный контроль качества и безопасности кода. |
| **OWASP ZAP** | DAST | Бесплатный сканер безопасности веб-приложений. |
| **pgAudit** | Database Audit | Аудит PostgreSQL. |
| **MySQL Enterprise Audit** | Database Audit | Аудит MySQL/MariaDB. |

### Связанные уязвимости
- **NoSQL Injection:** Инъекции в MongoDB, Redis (через операторы фильтрации).
- **LDAP Injection:** Манипуляция запросами к каталогам.
- **GraphQL Injection:** Атаки на API через специфику синтаксиса GraphQL.

### Внутренние ссылки
- **[WAF (Web Application Firewall)](./waf.md)** — детализация защиты L7.
- **[SAST/DAST в DevSecOps](../../CI-CD/DevSecOps/devsecops_overview.md)** — автоматизация проверок.
- **[Безопасность СУБД](../../Databases/installation_security.md)** — системное ужесточение баз данных.
- **[fail2ban — Automated Response](../../Linux/Security/Tools/fail2ban.md)** — автоматическая блокировка IP.
- **[nftables — threat modeling](../../Linux/Networking/Settings/tools/nftables/threat_modeling.md)** — стратегии фильтрации.
- **[PostgreSQL: безопасность и шифрование](../../Databases/PostgreSQL/Concepts/security_and_encryption.md)** — RLS, аудит, шифрование.
- **[PostgreSQL: управление ролями](../../Databases/PostgreSQL/Operations/role_management.md)** — RBAC и RLS в практике.

### Внешние ресурсы
- [OWASP SQL Injection Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- [PortSwigger Academy: SQL Injection](https://portswigger.net/web-security/sql-injection)
- [sqlcommenter](https://google.github.io/sqlcommenter/) — аудит запросов через метаданные.
