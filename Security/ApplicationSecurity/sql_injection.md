# SQL Injection (SQLi)

## Определения

**SQL Injection (SQLi — SQL-инъекция)** — атака на веб-приложения, при которой вредоносный SQL (Structured Query Language — язык структурированных запросов) код внедряется в запрос, отправляемый приложением в базу данных. Эксплуатирует недостаточную обработку пользовательского ввода.

Успешная атака позволяет: обойти аутентификацию, прочитать, изменить или удалить данные, выполнить команды на уровне ОС (Operating System — операционная система) через такие механизмы, как `xp_cmdshell` в MSSQL или `COPY TO PROGRAM` в PostgreSQL.

### Классификация типов SQLi

| Тип | Механизм | Характеристика |
| :--- | :--- | :--- |
| **In-band (Классическая)** | Данные извлекаются через тот же канал, что и инъекция | UNION-based, Error-based — самый быстрый способ получения данных |
| **Blind (Boolean-based)** | Ответ приложения не содержит данных напрямую, но различается для TRUE/FALSE условий | Перебор по одному биту, требует множества запросов |
| **Blind (Time-based)** | Задержка ответа (`SLEEP`, `WAITFOR DELAY`) сигнализирует об истинности условия | Используется, когда нет видимой разницы в ответах |
| **Second-order (Второго порядка)** | Вредоносная нагрузка сохраняется в БД (базе данных) и активируется позже, в другом запросе | Сложнее обнаружить — инъекция «спит» до срабатывания триггера |
| **Out-of-band (OOB — Внеполосная)** | Данные передаются через внешний канал (DNS, HTTP) | Зависит от возможностей СУБД (Система управления базами данных) |

## Основные концепции

### Механизм атаки

Атака эксплуатирует конкатенацию (склеивание) пользовательского ввода с SQL-запросом. Рассмотрим типичный небезопасный код:

```php
$sql = "SELECT * FROM users WHERE username = '$username' AND password = '$password'";
```

Ввод `' OR '1'='1` в поле имени пользователя превращает запрос в:

```sql
SELECT * FROM users WHERE username = '' OR '1'='1' AND password = '...';
```

Условие `OR '1'='1'` всегда истинно, что позволяет обойти аутентификацию.

### Примеры для разных СУБД

**MySQL — использование комментариев для игнорирования остатка запроса:**

```sql
' OR 1=1 --
' OR 1=1 #
```

**PostgreSQL — stacked queries (множественные запросы):**

```sql
'; DROP TABLE users; --
```

**MSSQL — xp_cmdshell для выполнения команд операционной системы:**

```sql
'; EXEC xp_cmdshell 'whoami'; --
```

### UNION-based извлечение данных

Позволяет получить данные из других таблиц через объединение результатов:

```sql
' UNION SELECT username, password FROM admin_users --
```

Метод требует совпадения количества и типов столбцов с исходным запросом.

## Практические сценарии

### Подготовленные выражения (Prepared Statements)

Самый надёжный метод защиты. SQL-запрос отправляется с плейсхолдерами (`?`, `:name`, `%s`), а данные передаются отдельно — СУБД разделяет код и данные на уровне протокола.

**Python (`psycopg2`, PostgreSQL):**

```python
# НЕПРАВИЛЬНО (уязвимо)
cursor.execute(f"SELECT * FROM users WHERE username = '{username}'")

# ПРАВИЛЬНО (безопасно)
cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
```

**PHP (PDO — PHP Data Objects):**

```php
// НЕПРАВИЛЬНО
$sql = "SELECT * FROM users WHERE email = '$email'";

// ПРАВИЛЬНО
$stmt = $pdo->prepare("SELECT * FROM users WHERE email = :email");
$stmt->execute(['email' => $email]);
```

**Go (`database/sql`):**

```go
// ПРАВИЛЬНО — Query автоматически использует prepared statement
row, err := db.Query("SELECT name FROM users WHERE id = ?", userID)
```

### Защита через ORM (Object-Relational Mapping)

Инструменты ORM (SQLAlchemy, Hibernate, Django ORM, GORM) по умолчанию используют параметризованные запросы. Тем не менее, методы `.raw()` или `.execute()` в ORM остаются уязвимыми при некорректном использовании:

```python
# SQLAlchemy — УЯЗВИМО
session.execute(text(f"SELECT * FROM users WHERE id = {user_id}"))

# SQLAlchemy — БЕЗОПАСНО
session.query(User).filter(User.id == user_id).first()
```

### Валидация и экранирование

Дополнительный слой защиты:

- **Валидация (белый список):** Проверка, что ID (идентификатор) содержит только числа, email соответствует формату, а статус входит в список разрешённых значений.
- **Экранирование:** Специальные символы (`'`, `"`, `\`, `;`) заменяются на безопасные последовательности. Метод менее надёжен, чем использование prepared statements.

### Принцип наименьших привилегий

Пользователь базы данных, от имени которого работает приложение, должен иметь минимально необходимые права:

- Доступ только к `SELECT`, `INSERT`, `UPDATE`, `DELETE` для необходимых таблиц.
- Отсутствие прав `DROP`, `GRANT`, `FILE`, `SUPER`.
- Запрет на чтение системных таблиц (кроме необходимых, например, `information_schema`).

Это не предотвратит инъекцию, но существенно ограничит возможный ущерб.

### Инструменты обнаружения SQLi

| Инструмент | Тип | Назначение |
| :--- | :--- | :--- |
| [sqlmap](https://sqlmap.org/) | Эксплуатация | Автоматическое обнаружение и эксплуатация SQLi |
| SAST (SonarQube, Semgrep, Checkmarx) | Статический анализ | Поиск уязвимых паттернов в коде — [обзор SAST](../../CI-CD/DevSecOps/sast_overview.md) |
| DAST (OWASP ZAP, Burp Suite) | Динамический анализ | Тестирование работающего приложения — [обзор DAST](../../CI-CD/DevSecOps/dast_overview.md) |
| WAF (ModSecurity, CloudFlare) | Защита во время выполнения | Блокировка известных SQLi-паттернов — [WAF](./waf.md) |

## Дополнительная информация

### Связанные уязвимости

- **NoSQL Injection:** Внедрение в запросы NoSQL баз данных (MongoDB, CouchDB) — [SAST/DAST уязвимости](../../CI-CD/DevSecOps/sast_dast_vulnerabilities.md)
- **Command Injection:** Внедрение системных команд — [SAST/DAST уязвимости](../../CI-CD/DevSecOps/sast_dast_vulnerabilities.md)
- **LDAP Injection:** Внедрение в LDAP-запросы — [SAST/DAST уязвимости](../../CI-CD/DevSecOps/sast_dast_vulnerabilities.md)

### OWASP и стандарты

- **OWASP Top 10:** A03:2021 — Injection ([OWASP Top 10 2021](https://owasp.org/Top10/A03_2021-Injection/))
- **OWASP SQLi Prevention Cheat Sheet:** [SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- **CWE-89:** [SQL Injection (CWE)](https://cwe.mitre.org/data/definitions/89.html)

### WAF как виртуальный патч

WAF (Web Application Firewall) не устраняет уязвимость, но обеспечивает временную защиту до исправления кода ([Virtual Patching](./waf.md)):

```apache
# Пример правила ModSecurity (OWASP CRS)
SecRule ARGS "@detectSQLi" \
    "id:942100,\
    phase:2,\
    deny,\
    status:403,\
    msg:'SQL Injection Attack Detected'"
```

**Важно:** WAF является дополнительным слоем защиты и не заменяет исправление кода. Обход WAF возможен через специфическое кодирование, обфускацию или логические ошибки.

### Многоуровневая защита

Эффективная защита от SQLi требует комбинации мер:

1. **Prepared Statements / ORM** — основной рубеж (разделение кода и данных).
2. **Валидация ввода (белый список)** — фильтрация по формату и типу.
3. **Принцип наименьших привилегий** — ограничение последствий.
4. **WAF** — защита от известных паттернов и zero-day.
5. **SAST/DAST в CI/CD (Continuous Integration / Continuous Deployment)** — автоматическое обнаружение до попадания в промышленную среду — [DevSecOps процесс](../../CI-CD/DevSecOps/devsecops_overview.md).
6. **Мониторинг и логирование** — обнаружение аномальных SQL-запросов в режиме реального времени.
