# PAM (Pluggable Authentication Modules) — Обзор

## Definitions

**PAM (Pluggable Authentication Modules)** — модульный фреймворк для реализации сервисов аутентификации, авторизации и управления учётными записями в Linux. Ключевая идея — отделение приложений от механизмов аутентификации, позволяющее изменять политики безопасности без перекомпиляции приложений.

Этот документ — SSoT для архитектуры и конфигурации PAM.

**Четыре типа модулей PAM:**

| Тип | Назначение | Примеры задач |
| :--- | :--- | :--- |
| `auth` | Проверка подлинности | Аутентификация по паролю, ключу, отпечатку |
| `account` | Проверка правил учётной записи | Срок действия пароля, время/место доступа |
| `session` | Действия до/после доступа | Логирование, монтирование home-директорий, лимиты |
| `password` | Управление паролями | Проверка сложности, обновление токена аутентификации |

## Basic Concepts

### Архитектура PAM

```
Приложение (sshd, login, su) → PAM Library → Конфигурация (/etc/pam.d/) → Модули → Результат
```

1. Приложение вызывает PAM с запросом (например, аутентифицировать пользователя)
2. PAM читает конфигурацию из `/etc/pam.d/<имя_сервиса>`
3. Модули выполняются в указанном порядке
4. Результаты возвращаются приложению

### Конфигурационные файлы

| Директория | Назначение |
| :--- | :--- |
| `/etc/pam.d/` | Конфигурация для каждого сервиса (`sshd`, `su`, `login`) |
| `/etc/security/` | Файлы настроек модулей (`access.conf`, `time.conf`, `limits.conf`) |

**Общие конфигурационные файлы (Debian/Ubuntu):**
- `/etc/pam.d/common-auth` — общая аутентификация
- `/etc/pam.d/common-account` — общие правила учётных записей
- `/etc/pam.d/common-password` — общие правила управления паролями
- `/etc/pam.d/common-session` — общие настройки сессий

### Структура строки конфигурации

Формат: `[тип] [control_flag] [путь_к_модулю] [аргументы]`

**Control Flags:**

| Флаг | Поведение при успехе | Поведение при ошибке |
| :--- | :--- | :--- |
| `required` | Продолжить, итог — успех если все required успешны | Продолжить, итог — отказ |
| `requisite` | Продолжить | **Немедленный отказ**, остальные модули не выполняются |
| `sufficient` | **Немедленный успех** (если нет previous failure в required) | Игнорировать, продолжить |
| `optional` | Итог не зависит от этого модуля | Итог не зависит от этого модуля |

### Часто используемые модули

| Модуль | Назначение | Файл настроек |
| :--- | :--- | :--- |
| `pam_unix.so` | Стандартная аутентификация через `/etc/passwd` + `/etc/shadow` | — |
| `pam_access.so` | Контроль доступа по IP/хосту/пользователю | `/etc/security/access.conf` |
| `pam_time.so` | Ограничение доступа по времени | `/etc/security/time.conf` |
| `pam_limits.so` | Лимиты ресурсов для сессий | `/etc/security/limits.conf` |
| `pam_wheel.so` | Ограничение `su` членам группы `wheel` | — |
| `pam_pwquality.so` | Проверка сложности паролей | `/etc/security/pwquality.conf` |
| `pam_sss.so` | Аутентификация через SSSD/LDAP | — |

**Ключевая особенность:** изменения в конфигурации PAM применяются немедленно, перезапуск сервисов не требуется.

## Practical Scenarios

### 1. Ограничение доступа по IP (`pam_access.so`)

**Задача:** разрешить `root`-доступ по SSH только с IP `192.168.52.1`.

**Шаг 1:** настроить правила в `/etc/security/access.conf`:

```
+ : root : 192.168.52.1
- : root : ALL
```

**Шаг 2:** подключить модуль в `/etc/pam.d/sshd` (секция `account`):

```
account    required     pam_access.so
```

### 2. Ограничение доступа по времени (`pam_time.so`)

**Задача:** запретить пользователю `lessons` вход по SSH с 18:00 до 24:00 в рабочие дни.

**Шаг 1:** настроить правило в `/etc/security/time.conf`:

```
sshd;*;lessons;!Wk1800-2400
```

| Поле | Значение |
| :--- | :--- |
| service | `sshd` |
| ttys | `*` (любой) |
| users | `lessons` |
| times | `!Wk1800-2400` (запрет в рабочие дни 18:00–24:00) |

**Шаг 2:** подключить модуль в `/etc/pam.d/sshd`:

```
account    required     pam_time.so
```

### 3. Ограничение `su` для группы `wheel` (`pam_wheel.so`)

**Задача:** разрешить `su` только членам группы `wheel`.

Раскомментировать строку в `/etc/pam.d/su`:

```
auth    required    pam_wheel.so
```

Подробнее: [Управление доступом ФСТЭК](./Fstec/user_access_control.md).

### 4. Отключение входа с пустым паролем (`pam_unix.so`)

**Задача:** запретить аутентификацию с пустым паролем.

Удалить `nullok` из `/etc/pam.d/common-auth`:

```
# Было:
auth    [success=1 default=ignore]    pam_unix.so nullok

# Стало:
auth    [success=1 default=ignore]    pam_unix.so
```

Подробнее: [Управление доступом ФСТЭК](./Fstec/user_access_control.md).

### 5. Лимиты ресурсов для сессий (`pam_limits.so`)

**Задача:** установить максимальное количество открытых файлов для пользователей.

**Шаг 1:** настроить `/etc/security/limits.conf`:

```
*    soft    nofile    65536
*    hard    nofile    1048576
```

**Шаг 2:** убедиться, что модуль подключён в `/etc/pam.d/common-session`:

```
session    required    pam_limits.so
```

**Важно:** `pam_limits.so` применяется только к пользовательским сессиям (SSH, GUI), не к systemd-сервисам. Лимиты вступают в силу после перелогина.

Подробнее: [Лимиты ресурсов](../Core/processes/resource_limits_concepts.md).

## Additional Information

### Связанные документы

**PAM-модули и конфигурация:**
- [Управление доступом ФСТЭК](./Fstec/user_access_control.md)
- [Лимиты ресурсов](../Core/processes/resource_limits_concepts.md)
- [Персистентные лимиты](../Core/processes/persistent_limits_configuration.md)

**Парольные политики:**
- [Хэширование паролей](../SystemAdministration/Users/password_hashing.md)
- [Политика паролей](../SystemAdministration/Users/password_policy_chage.md)

**Интеграция с LDAP/SSSD:**
- [Настройка SSSD](../SystemAdministration/Users/LDAP_SSSD/configuration.md)

**Смежные темы:**
- [Управление пользователями](../SystemAdministration/users_management.md)
- [Управление привилегиями](../SystemAdministration/privilege_management.md)
