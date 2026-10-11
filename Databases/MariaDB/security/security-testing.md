# Тестирование безопасности MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**Тестирование безопасности (security testing)** — оценка защищённости инстанса MariaDB: конфигурации, аутентификации, TLS, привилегий и сетевого доступа. Включает автоматизированные проверки и ручной анализ.

**Пентест (penetration test)** — имитация атаки с целью обнаружения уязвимостей. **Требует письменного разрешения владельца системы.** Тестирование без разрешения — незаконно, независимо от намерений.

**Vulnerability scan** — автоматизированный поиск известных уязвимостей (CVE) и слабых конфигураций; менее инвазивен, чем пентест.

**nmap NSE scripts** — скрипты Nmap для MariaDB/MySQL: `mysql-brute`, `mysql-empty-password`, `mysql-vuln*`, `ssl-enum-ciphers`.

**testssl.sh** — инструмент аудита TLS-конфигурации сервера (версии, шифры, сертификат).

**sqlmap** — инструмент обнаружения SQL-инъекций; тестирует приложение, а не СУБД напрямую.

## Основные концепции

### Области тестирования

| Область | Что проверяется | Инструменты |
| :--- | :--- | :--- |
| Сеть | открытые порты, доступность 3306 | nmap, ss |
| Аутентификация | слабые пароли, анонимные пользователи | nmap NSE, mariadb CLI |
| TLS | версии, шифры, сертификат | testssl.sh, openssl, nmap |
| Привилегии | избыточные привилегии, SUPER/FILE | SQL-запросы |
| Конфигурация | my.cnf, дефолтные учётки, результат закалки | ручной анализ, SQL |
| ОС | права на datadir/my.cnf, процессы | `ls -l`, `stat`, `systemctl` |
| Приложение | SQL-инъекции | sqlmap |

### Методология

1. **Авторизация:** письменное разрешение, определение scope (IP, порты, время окна).
2. **Разведка:** открытые порты, версия, баннер.
3. **Конфигурационный аудит:** `my.cnf`, учётные записи, привилегии, результат `mariadb-secure-installation` (см. [Закалку](hardening.md)).
4. **Тестирование аутентификации:** политика паролей, анонимные пользователи.
5. **Тестирование TLS:** версии и шифры.
6. **Тестирование приложения:** SQL-инъекции (через приложение).
7. **Отчёт:** находки, риски, remediation.

### Что НЕ тестировать без разрешения

- Brute-force против production — даже с разрешением может вызвать блокировки и деградацию.
- Эксплуатация уязвимостей (RCE, privesc) — только в изолированной среде.
- Нагрузочные атаки (DoS) — запрещены без явного согласования.

## Предварительные требования

- Письменное разрешение на тестирование
- Инструменты: `nmap`, `testssl.sh`, `openssl`, `mariadb` CLI, `sqlmap`
- Доступ к `my.cnf` и учётной записи администратора (для конфигурационного аудита)
- Изолированная среда для эксплойт-тестов

## Практические сценарии

### Сценарий 1: Разведка сети

```bash
# Открытые порты и версия
nmap -sV -p 3306 10.0.5.20
# → 3306/tcp open  mysql  MariaDB (unauthorized)

# Скрипты по умолчанию для MariaDB (без инвазивных: brute, vuln, intrusive)
nmap -p 3306 --script "mysql-* and not (brute or vuln or intrusive)" 10.0.5.20
# → mysql-empty-password: no empty password accounts (или находка)

# Точная версия по handshake (нужны учётные данные; -sV пишет «unauthorized»,
# если сервер отвечает ошибкой аутентификации на probe)
nmap -p 3306 --script mysql-info --script-args mysqluser=auditor,mysqlpassword=<пароль> 10.0.5.20
# → mysql-info: Version: 10.11.7-MariaDB
```

### Сценарий 2: Проверка анонимных и слабых учётных записей

```bash
# Анонимный доступ (без пароля)
mariadb -h 10.0.5.20 -u '' -e "SELECT VERSION();"
# → ERROR 1045 (28000): Access denied (хорошо)

# Пустой пароль у root
mariadb -h 10.0.5.20 -u root -e "SELECT 1;"
# → ERROR 1045 (хорошо)

# Brute-force (только с разрешением, на изолированном стенде)
nmap -p 3306 --script mysql-brute --script-args userdb=users.txt,passdb=passwords.txt 10.0.5.20
```

### Сценарий 3: Аудит TLS

```bash
# Версии и шифры
testssl.sh 10.0.5.20:3306
# → TLS 1.2, TLS 1.3 supported; TLS 1.0/1.1 not offered (хорошо)

# Ручная проверка
openssl s_client -connect 10.0.5.20:3306 -tls1_2
# → New, TLSv1.2, Cipher is ECDHE-RSA-AES256-GCM-SHA384

# Перечисление шифров через nmap
nmap -p 3306 --script ssl-enum-ciphers 10.0.5.20
```

### Сценарий 4: Аудит привилегий

```sql
-- Глобальные привилегии (SUPER, FILE, PROCESS — только админам)
SELECT User, Host, Super_priv, File_priv, Process_priv, Grant_priv
FROM mysql.user WHERE Super_priv='Y' OR File_priv='Y' OR Grant_priv='Y';

-- Анонимные пользователи
SELECT User, Host FROM mysql.user WHERE User = '';

-- Пользователи с пустым хешем у парольных плагинов
-- (ed25519/pam/gssapi не содержат 'password' в имени — NOT LIKE '%password%' даёт ложные находки)
SELECT User, Host, Plugin FROM mysql.user
WHERE Plugin IN ('mysql_native_password','sha256_password','caching_sha2_password','ed25519','mysql_old_password')
  AND (authentication_string = '' OR authentication_string IS NULL);
-- → пусто (хорошо)

-- Учётные записи с незаданным плагином (legacy: сервер выберет mysql_native_password)
SELECT User, Host FROM mysql.user WHERE Plugin = '';
-- → пусто (хорошо)

-- Анонимные привилегии на уровне баз: тестовая БД может оставаться доступной
-- через mysql.db, даже если в mysql.user анонимных строк нет
SELECT Host, Db, User FROM mysql.db WHERE User = '';
-- → пусто (хорошо); строки с test / test_% — находка

-- Тестовая база (должна отсутствовать в production)
SHOW DATABASES LIKE 'test';
-- → пусто (хорошо)

-- Привилегии конкретного приложения
SHOW GRANTS FOR 'app_svc'@'10.0.5.%';
-- → GRANT USAGE ON *.* TO `app_svc`@`10.0.5.%`
-- → GRANT SELECT, INSERT, UPDATE ON `app_db`.* TO `app_svc`@`10.0.5.%`
```

### Сценарий 5: Конфигурационный аудит

```bash
# Ключевые параметры
mariadb -e "SHOW VARIABLES WHERE Variable_name IN
  ('local_infile','skip_show_database','symbolic_links','require_secure_transport',
   'bind_address','skip_name_resolve','general_log','slow_query_log','log_bin');"

# Ожидания для production:
# → local_infile = OFF
# → require_secure_transport = ON
# → general_log = OFF
# → log_bin = ON
# → skip_name_resolve = ON   (гранты должны соответствовать IP, не hostname)
# → symbolic_links = OFF
# → skip_show_database = ON
# → bind_address = 10.0.5.20 (не 0.0.0.0, если доступ из всех сетей не требуется)

# Политика паролей (validate_password) и результат закалки — см.
# [Аутентификацию](authentication.md) и [Закалку](hardening.md)
mariadb -e "SHOW VARIABLES LIKE 'validate_password%';"
```

### Сценарий 6: Тестирование SQL-инъекций (через приложение)

```bash
# sqlmap против приложения (НЕ против СУБД напрямую)
sqlmap -u "https://app.example.com/products?id=1" --batch --level=2
# → возможные находки: injectable parameter, DBMS MariaDB

# Проверка, что приложение использует prepared statements
# → код-ревью: PDO/MySQLi с параметризованными запросами
```

## Проверка и валидация

### Критерии успешного тестирования

| Проверка | Ожидаемый результат |
| :--- | :--- |
| Анонимный доступ | отклонён |
| Root без пароля | отклонён |
| TLS 1.0/1.1 | не предлагаются |
| Слабые шифры (RC4, DES) | не предлагаются |
| `SUPER`/`FILE` у приложений | отсутствуют |
| `local_infile` | OFF |
| `general_log` | OFF |
| `require_secure_transport` | ON |
| `skip_name_resolve` | ON |
| `symbolic_links` | OFF |
| `skip_show_database` | ON |
| `bind_address` | не 0.0.0.0 (кроме явной политики) |
| Тестовая БД и анонимные пользователи | отсутствуют (в т.ч. строки в `mysql.db`) |
| Политика паролей | `validate_password` включён, не ниже MEDIUM |
| `mariadb-secure-installation` | выполнен (см. [Закалку](hardening.md)) |
| Порт 3306 | не опубликован в интернет |

### Отчёт о тестировании

Структура отчёта:
1. Scope и разрешение
2. Методология
3. Находки (критичность: Critical/High/Medium/Low)
4. Доказательства (выводы команд)
5. Remediation (ссылки на файлы базы знаний)

## Устранение неполадок

### `mysql-brute` блокирует учётные записи

**Причина:** слишком много попыток подключения.

**Решение:** используйте `--script-args mysql-brute.threads=1` и паузу; тестируйте на изолированном стенде.

### testssl.sh не может определить версию MariaDB

**Причина:** testssl.sh ориентирован на HTTP(S): многие проверки требуют HTTP-ответов, а MariaDB не поддерживает STARTTLS — часть тестов к не-HTTP TLS-сервису неприменима.

**Решение:** используйте `openssl s_client` и `nmap ssl-enum-ciphers` для точного перечисления.

### `nmap -sV` показывает «mysql» без версии или «MariaDB (unauthorized)»

**Причина:** сервер отвечает ошибкой аутентификации на probe nmap; версия в баннере недоступна без учётных данных.

**Решение:** `--script mysql-info` с `--script-args mysqluser=...,mysqlpassword=...` читает версию из handshake; либо `SELECT VERSION()` на сервере.

### Аккаунты `mariadb.sys` / `mysql` помечены как «без пароля»

**Причина:** это системные аккаунты 10.4+: `mariadb.sys` — владелец view `mysql.user` (`ACCOUNT LOCK PASSWORD EXPIRE`), `mysql@localhost` — placeholder с хешем `invalid`.

**Решение:** не удалять и не помечать как находку; находка — только реальные аккаунты с пустым `authentication_string` (см. Сценарий 4).

## Лучшие практики

1. **Авторизация прежде всего.** Без письменного разрешения — не тестируйте, даже «в учебных целях».
2. **Изолированный стенд для эксплойтов.** Эксплуатация уязвимостей — только на копии среды.
3. **Тестируйте конфигурацию, а не только уязвимости.** Большинство инцидентов — слабая конфигурация, а не CVE.
4. **Регулярность.** Сканирование — ежеквартально; пентест — ежегодно и после значимых изменений.
5. **Не тестируйте production нагрузкой.** DoS-тесты — только в изолированной среде.
6. **Фильтруйте NSE-выражения.** Wildcard `mysql-*` захватывает инвазивные скрипты; явно исключайте `brute`/`vuln`/`intrusive` или перечисляйте скрипты списком.

## Граничные случаи

- **`mysql.user` — view с 10.4.** С MDEV-17658 учётные записи и глобальные привилегии хранятся в `mysql.global_priv`; `mysql.user` остался как совместимый view (владелец — `mariadb.sys`). Запросы к `mysql.user` работают, но прямое чтение `mysql.global_priv` требует разбора JSON-формата `priv`.
- **Инвазивные скрипты в wildcard.** Выражение `mysql-*` захватывает `mysql-brute` и `mysql-vuln*` (категории brute/vuln/intrusive) — запускайте с фильтром `and not (brute or vuln or intrusive)` или явным списком; инвазивные скрипты — только в scope с разрешения.
- **`mysql-vuln*` на современных версиях.** `mysql-vuln-cve2012-2122` эксплуатирует аутентификационный баг версий ≤ 5.5.22; на 10.x+ «уязвимость» — ложное срабатывание, проверяйте вручную.
- **`skip_name_resolve` меняет аудит грантов.** При `ON` matching грантов идёт по IP: в `mysql.user`/`mysql.db` в поле `Host` должны быть IP-адреса, не hostname — иначе гранты «пропадают».
- **Проверка «без пароля» по имени плагина не работает.** `ed25519`, `pam`, `gssapi` не содержат `password` в имени — только явный список парольных плагинов + `authentication_string` (Сценарий 4).

## Дополнительная информация

### Ограничения

- NSE-скрипты `mysql-*` могут давать ложные срабатывания; проверяйте находки вручную. Скрипты категорий `brute`/`vuln`/`intrusive` инвазивны — их запуск требует явного согласования в scope.
- Точность `-sV` зависит от версии nmap и его `nmap-service-probes`; старые сборки nmap не распознают новые версии MariaDB.
- sqlmap тестирует приложение; защита на стороне СУБД (prepared statements) — задача разработчиков. Подробнее: [SQL Injection](../../../Security/ApplicationSecurity/sql_injection.md).

### Смежные темы

- **[CIS Benchmark](cis-benchmark.md)** — контрольные семейства.
- **[Начальная закалка](hardening.md)** — что делает `mariadb-secure-installation` (здесь проверяется результат).
- **[Аутентификация](authentication.md)** — плагины и политика паролей.
- **[SSL/TLS](ssl-tls.md)** — аудит TLS.
- **[RBAC](rbac.md)** — аудит привилегий.
- **[Сетевая безопасность](network-security.md)** — сетевая разведка.
- **[SQL Injection](../../../Security/ApplicationSecurity/sql_injection.md)** — тестирование инъекций.
- **[Мониторинг безопасности](security-monitoring.md)** — обнаружение атак.
