# SQL Injection (SQLi)

## Definitions

**SQL Injection (SQLi)** — атака на веб-приложения, при которой вредоносный SQL-код внедряется в запрос, отправляемый приложением в базу данных. Эксплуатирует недостаточную обработку пользовательского ввода.

Успешная атака позволяет: обойти аутентификацию, прочитать/изменить/удалить данные, выполнить команды на уровне ОС (через `xp_cmdshell`, `COPY TO PROGRAM` и аналоги).

### Классификация типов SQLi

| Тип | Механизм | Характеристика |
| :--- | :--- | :--- |
| **In-band (Classic)** | Данные извлекаются через тот же канал, что и инъекция | UNION-based, Error-based — самый быстрый способ получения данных |
| **Blind (Boolean-based)** | Ответ приложения не содержит данных напрямую, но различается для TRUE/FALSE условий | Перебор по одному биту, требует множества запросов |
| **Blind (Time-based)** | Задержка ответа (`SLEEP`, `WAITFOR DELAY`) сигнализирует об истинности условия | Используется, когда нет видимой разницы в ответах |
| **Second-order** | Вредоносная нагрузка сохраняется в БД и активируется позже, в другом запросе | Сложнее обнаружить — инъекция «спит» до триггера |
| **Out-of-band (OOB)** | Данные передаются через внешний канал (DNS, HTTP) | Зависит от возможностей СУБД (UTL_HTTP в Oracle, `xp_dirtree` в MSSQL) |

## Basic Concepts

### Механизм атаки

Атака эксплуатирует конкатенацию пользовательского ввода с SQL-запросом. Рассмотрим типичный небезопасный код:

```php
$sql = "SELECT * FROM users WHERE username = '$username' AND password = '$password'";
```

Ввод `' OR '1'='1` в поле имени пользователя превращает запрос в:

```sql
SELECT * FROM users WHERE username = '' OR '1'='1' AND password = '...';
```

Условие `OR '1'='1'` всегда истинно — аутентификация обойдена.

### Примеры для разных СУБД

**MySQL — комментарий для игнорирования остатка запроса:**

```sql
' OR 1=1 --
' OR 1=1 #
```

**PostgreSQL —STACKED queries (множественные запросы):**

```sql
'; DROP TABLE users; --
```

**MSSQL —xp_cmdshell для выполнения команд ОС:**

```sql
'; EXEC xp_cmdshell 'whoami'; --
```

### UNION-based извлечение данных

Позволяет получить данные из других таблиц через объединение результатов:

```sql
' UNION SELECT username, password FROM admin_users --
```

Требует совпадения количества и типов столбцов с исходным запросом.

## Practical Scenarios

### Подготовленные выражения (Prepared Statements)

Самый надёжный метод защиты. SQL-запрос отправляется с плейсхолдерами (`?`, `:name`, `%s`), данные передаются отдельно — СУБД разделяет код и данные на уровне протокола.

**Python (`psycopg2`, PostgreSQL):**

```python
# НЕПРАВИЛЬНО (уязвимо)
cursor.execute(f"SELECT * FROM users WHERE username = '{username}'")

# ПРАВИЛЬНО (безопасно)
cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
```

**PHP (PDO):**

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

### Защита через ORM

ORM (SQLAlchemy, Hibernate, Django ORM, GORM) по умолчанию используют параметризованные запросы. **Однако** методы `.raw()`, `.execute()` в ORM уязвимы при некорректном использовании:

```python
# SQLAlchemy — УЯЗВИМО
session.execute(text(f"SELECT * FROM users WHERE id = {user_id}"))

# SQLAlchemy — БЕЗОПАСНО
session.query(User).filter(User.id == user_id).first()
```

### Валидация и экранирование

Дополнительный (не основной!) слой защиты:

- **Валидация (allowlist):** ID — только числа, email — только формат email, статус — только из перечисленных значений
- **Экранирование:** Специальные символы (`'`, `"`, `\`, `;`) заменяются на безопасные последовательности. Менее надёжен, чем prepared statements

### Принцип наименьших привилегий

Пользователь БД, от имени которого работает приложение, должен иметь минимально необходимые права:

- Только `SELECT`, `INSERT`, `UPDATE`, `DELETE` для нужных таблиц
- Без `DROP`, `GRANT`, `FILE`, `SUPER`
- Без прав на чтение системных таблиц (`information_schema` — исключение)

Это не предотвратит инъекцию, но ограничит последствия.

### Инструменты обнаружения SQLi

| Инструмент | Тип | Назначение |
| :--- | :--- | :--- |
| [sqlmap](https://sqlmap.org/) | Exploitation | Автоматическое обнаружение и эксплуатация SQLi |
| SAST (SonarQube, Semgrep, Checkmarx) | Static analysis | Поиск уязвимых паттернов в коде — [обзор SAST](../../CI-CD/DevSecOps/sast_overview.md) |
| DAST (OWASP ZAP, Burp Suite) | Dynamic analysis | Тестирование работающего приложения — [обзор DAST](../../CI-CD/DevSecOps/dast_overview.md) |
| WAF (ModSecurity, CloudFlare) | Runtime protection | Блокировка известных SQLi-паттернов — [WAF](./waf.md) |

## Additional Information

### Связанные уязвимости

- **NoSQL Injection:** Внедрение в запросы MongoDB, CouchDB — [SAST/DAST уязвимости](../../CI-CD/DevSecOps/sast_dast_vulnerabilities.md)
- **Command Injection:** Внедрение системных команд — [SAST/DAST уязвимости](../../CI-CD/DevSecOps/sast_dast_vulnerabilities.md)
- **LDAP Injection:** Внедрение в LDAP-запросы — [SAST/DAST уязвимости](../../CI-CD/DevSecOps/sast_dast_vulnerabilities.md)

### OWASP и стандарты

- **OWASP Top 10:** A03:2021 — Injection ([OWASP Top 10 2021](https://owasp.org/Top10/A03_2021-Injection/))
- **OWASP SQLi Prevention Cheat Sheet:** [SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- **CWE-89:** [SQL Injection (CWE)](https://cwe.mitre.org/data/definitions/89.html)

### WAF как виртуальный патч

WAF не устраняет уязвимость, но обеспечивает временную защиту до исправления кода ([Virtual Patching](./waf.md)):

```
# Пример правила ModSecurity (OWASP CRS)
SecRule ARGS "@detectSQLi" \
    "id:942100,\
    phase:2,\
    deny,\
    status:403,\
    msg:'SQL Injection Attack Detected'"
```

**Важно:** WAF — дополнительный слой, а не замена исправления кода. Обход WAF возможен через кодирование, обфускацию, логические ошибки.

### Многоуровневая защита

Эффективная защита от SQLi требует комбинации мер:

1. **Prepared Statements / ORM** — основной рубеж (разделение кода и данных)
2. **Валидация ввода (allowlist)** — фильтрация по формату и типу
3. **Принцип наименьших привилегий** — ограничение последствий
4. **WAF** — защита от известных паттернов и zero-day
5. **SAST/DAST в CI/CD** — автоматическое обнаружение до попадания в production — [DevSecOps процесс](../../CI-CD/DevSecOps/devsecops_overview.md)
6. **Мониторинг и логирование** — обнаружение аномальных SQL-запросов в runtime
