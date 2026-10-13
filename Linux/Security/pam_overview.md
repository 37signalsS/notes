# PAM (Pluggable Authentication Modules) — Обзор

## Определения

**PAM (Pluggable Authentication Modules)** — универсальный интерфейс и модульный фреймворк для реализации сервисов аутентификации, авторизации и управления учётными записями в Linux.

**Фундаментальное разделение функций:**
*   **Аутентификация (Authentication):** проверка подлинности субъекта («Является ли пользователь тем, за кого себя выдает?»). Реализуется через пароли, биометрию или токены.
*   **Авторизация (Authorization/Account):** контроль прав доступа («Имеет ли подтвержденный пользователь право на выполнение данного действия?»).

PAM служит абстрактной прослойкой: системные утилиты (login, sudo, su) вызывают функции PAM, не вникая в детали реализации проверки (будь то локальный файл `/etc/shadow` или удаленный сервер LDAP).

**Четыре типа модулей PAM:**

| Тип | Назначение | Примеры задач |
| :--- | :--- | :--- |
| `auth` | Проверка подлинности | Аутентификация по паролю, ключу, отпечатку |
| `account` | Проверка правил учётной записи | Срок действия пароля, время/место доступа |
| `session` | Действия до/после доступа | Логирование, монтирование home-директорий, лимиты |
| `password` | Управление паролями | Проверка сложности, обновление токена аутентификации |

## Базовые концепции

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

### Наследование и подключение конфигураций (`@include`)

Каждый сервис имеет свой файл в `/etc/pam.d/<service>`. При отсутствии файла PAM использует `/etc/pam.d/other` (по умолчанию — минимальный стек с `pam_deny`). Файлы переиспользуют друг друга через директиву `@include`:

```text
# /etc/pam.d/sshd
auth       include   system-login
@include common-auth
@include common-account
@include common-session
```

`@include <file>` вставляет содержимое указанного файла и продолжает обработку в текущей секции. Порядок строк в файле — порядок выполнения модулей (см. *Структура строки конфигурации*).

| Дистрибутив | Сервис-файлы | Менеджер конфигураций |
| :--- | :--- | :--- |
| Debian/Ubuntu | `common-auth`, `common-account`, `common-password`, `common-session` + `<service>` (sshd, login, su, ...). `login` → `system-login` (systemd) | `pam-auth-update` |
| RHEL/CentOS/Fedora | `system-auth`, `password-auth`, `fingerprint-auth`, `smartcard-auth` + `<service>`. `system-auth` инклюдится в `sshd`, `login`, `su`, `sudo` | `authselect` |

На **systemd**-системах базовый вход идёт через `/etc/pam.d/login`, который `@include`-ит `/etc/pam.d/system-login` (определяет сессии, `pam_systemd.so`, `pam_namespace.so`). Это точка, где `logind`/`systemd --user` соединяются с PAM: [Управление сессиями logind](../Core/systemd/logind_session_management.md).

Ручное редактирование `common-*` (Debian) перезаписывается при следующем вызове `pam-auth-update`; на RHEL — `authselect` сбрасывает изменения `system-auth`, если профиль переключён. Так что прямую правку применяйте только с `backup` и проверкой через `pamtester`.

### Структура строки конфигурации

Формат: `[тип] [control_flag] [путь_к_модулю] [аргументы]`

**Control Flags (флаги управления):**

| Флаг | Поведение при успехе | Поведение при ошибке |
| :--- | :--- | :--- |
| `required` | Продолжить, итог — успех если все required успешны | Продолжить, итог — отказ |
| `requisite` | Продолжить | **Немедленный отказ**, остальные модули не выполняются |
| `sufficient` | **Немедленный успех** (если нет previous failure в required) | Игнорировать, продолжить |
| `optional` | Итог не зависит от этого модуля | Итог не зависит от этого модуля |

**Расширенный синтаксис (Stacking):**
В современных дистрибутивах часто используется синтаксис `[value1=action1 value2=action2 ...]`. Это позволяет точно настроить поведение PAM в зависимости от конкретного кода возврата модуля.
Пример: `[success=1 default=ignore]` — если модуль вернул успех, пропустить следующий модуль в стеке; в остальных случаях игнорировать результат.

### Инструменты управления конфигурацией

Прямое редактирование файлов в `/etc/pam.d/` допустимо, но в современных системах рекомендуется использовать специализированные утилиты для предотвращения ошибок:

*   **Debian/Ubuntu:** `pam-auth-update` — интерактивная настройка профилей PAM (автоматически обновляет `common-*` файлы).
*   **RHEL/CentOS/Fedora:** `authselect` — управление профилями (например, `sssd`, `winbind`). Заменяет устаревший `authconfig`.

### Часто используемые модули

| Модуль | Назначение | Файл настроек |
| :--- | :--- | :--- |
| `pam_unix.so` | Стандартная аутентификация через `/etc/passwd` + `/etc/shadow` | — |
| `pam_faillock.so` | Блокировка учётной записи после неудачных попыток (современная замена `pam_tally2`) | `/etc/security/faillock.conf` |
| `pam_access.so` | Контроль доступа по IP/хосту/пользователю | `/etc/security/access.conf` |
| `pam_time.so` | Ограничение доступа по времени | `/etc/security/time.conf` |
| `pam_limits.so` | Лимиты ресурсов для сессий | `/etc/security/limits.conf` |
| `pam_pwquality.so` | Проверка сложности паролей | `/etc/security/pwquality.conf` |
| `pam_mkhomedir.so` | Автоматическое создание домашней директории при первом входе | — |
| `pam_wheel.so` | Ограничение `su` членам группы `wheel` | — |
| `pam_sss.so` | Аутентификация через SSSD/LDAP | — |
| `pam_systemd.so` | Интеграция с systemd (сессии, cgroups, `XDG_RUNTIME_DIR`) | — |
| `pam_env.so` | Установка переменных окружения | `/etc/environment`, `/etc/security/pam_env.conf` |
| `pam_exec.so` | Выполнение произвольных команд/скриптов при событиях PAM | — |
| `pam_cap.so` | Наследование Capabilities процессами пользователя | `/etc/security/capability.conf` |
| `pam_google_authenticator.so` | Многофакторная аутентификация (MFA/2FA) через TOTP | `~/.google_authenticator` |

### Аргументы часто используемых модулей

Аргументы передаются после пути к модулю и влияют на его поведение. Подробнее о выборе алгоритма хэширования — в [Хэширование паролей](../SystemAdministration/Users/password_hashing.md).

| Модуль | Ключевые аргументы | Описание |
| :--- | :--- | :--- |
| `pam_unix.so` | `nullok`, `obscure`, `remember=N`, `use_authtok`, `use_first_pass`, `try_first_pass`, `yescrypt`, `sha512`, `sha256`, `rounds=N` | `nullok` — разрешить пустой пароль; `obscure` — проверять простоту; `remember=N` — хранить N последних паролей (хэши MD5; предпочтительнее `pam_pwhistory` — см. [Хранение истории паролей](../SystemAdministration/Users/password_history.md)); `yescrypt`/`sha512`/... — алгоритм; `rounds=N` — количество раундов для SHA-* |
| `pam_faillock.so` | `preauth`, `authfail`, `authsucc`, `silent`, `deny=N`, `fail_interval=S`, `unlock_time=S`, `even_deny_root`, `root_unlock_time=S`, `nodelay`, `audit`, `dir=`, `conf=` | `preauth` — перед `pam_unix`; `authfail` — после провала; `authsucc` — после успеха (сброс счётчика); `even_deny_root` — блокировать root; `root_unlock_time` — таймаут разблокировки root (подразумевает `even_deny_root`); `nodelay` — отключить задержку после неудач; аргументы в строке модуля переопределяют значения из `/etc/security/faillock.conf` |
| `pam_pwquality.so` | `retry=N`, `minlen=N`, `minclass=N`, `difok=N`, `ucredit=`, `lcredit=`, `dcredit=`, `ocredit=`, `enforce_for_root`, `reject_username`, `gecoscheck` | Жёсткая проверка сложности пароля |
| `pam_limits.so` | `conf=/path/to/file`, `quiet` | `quiet` — не писать в syslog каждый вызов |
| `pam_access.so` | `fieldsep=`, `listsep=` | Разделители полей/списков в `access.conf` |
| `pam_time.so` | `fieldsep=`, `listsep=` | Разделители аналогично `pam_access` |
| `pam_env.so` | `conffile=`, `envfile=` | `conffile=` — путь к `pam_env.conf`; `envfile=` — путь к `/etc/environment` |
| `pam_mkhomedir.so` | `skel=/etc/skel`, `umask=0022`, `silent` | Шаблон, маска, без вывода в лог |
| `pam_google_authenticator.so` | `nullok`, `try_first_pass`, `use_first_pass`, `authtok=`, `no_increment` | `nullok` — допускать вход без OTP, если есть запасной метод |

### Дополнительные стандартные модули

| Модуль | Назначение |
| :--- | :--- |
| `pam_listfile.so` | Allowlist/denylist по списку (пользователи, группы, терминалы) |
| `pam_succeed_if.so` | Условие на атрибуты пользователя (UID, членство в группах, shell) |
| `pam_permit.so` | Всегда успех (заглушка-заглушка) |
| `pam_deny.so` | Всегда отказ (заглушка-отказ) |
| `pam_umask.so` | Установка `umask` для сессии |
| `pam_timestamp.so` | Кэш подтверждения аутентификации (например, таймаут `sudo`) |
| `pam_motd.so` | Вывод сообщения дня (MOTD) при входе |
| `pam_lastlog2.so` | Вывод информации о последнем входе |
| `pam_tty_log.so` | Аудит ввода терминала в журнал |
| `pam_namespace.so` | Автоматическое монтирование изолированных пространств имён |
| `pam_keyinit.so` | Инициализация keyring ядра для сессии |
| `pam_tmpdir.so` | Создание защищённого `$TMPDIR` |
| `pam_shells.so` | Проверка, что пользовательский shell входит в `/etc/shells` |
| `pam_issue.so` | Вывод `/etc/issue` и `/etc/issue.net` перед запросом пароля |
| `pam_xauth.so` | Передача `XAUTHORITY` между пользователями (`sudo`/`su`) |
| `pam_tally2.so` | **Устарел (deprecated)**; счётчик неудач в `/var/log/tallylog`. Заменяется `pam_faillock.so` (см. раздел 6) |

**Логика обработки (Stacking):**
PAM обрабатывает модули в стеке сверху вниз. Итоговое решение формируется на основе кодов возврата всех модулей в группе (тип):
1.  **Required:** Ошибка помечается, но стек идет дальше. Итог будет Fail.
2.  **Requisite:** Ошибка немедленно прерывает стек с результатом Fail.
3.  **Sufficient:** Успех немедленно прерывает стек с результатом Success (если ранее не было ошибок в Required).
4.  **Optional:** Результат учитывается только если это единственный модуль в стеке.

**Расширенный синтаксис управления:**
Синтаксис `[value1=action1 ...]` позволяет переопределить стандартные флаги.
- `ok`: Считать успех промежуточным успехом.
- `done`: Немедленный успех (аналог `sufficient`).
- `die`: Немедленная ошибка (аналог `requisite`).
- `bad`: Считать ошибку критической (аналог `required`).
- `ignore`: Игнорировать код возврата.
- `N` (число): Пропустить следующие N модулей в стеке.

Пример: `auth [success=1 default=ignore] pam_unix.so` — если `pam_unix` успешен, пропустить следующий модуль (например, проверку в LDAP).

### Коды возврата PAM

Каждый модуль возвращает код `PAM_*`. PAM сопоставляет его с действием согласно флагу управления либо переопределяет поведение через расширенный синтаксис `[имя_кода=действие]`.

| Константа | Код | Когда возвращается |
| :--- | :--- | :--- |
| `PAM_SUCCESS` | 0 | Успешное выполнение |
| `PAM_OPEN_ERR` | 1 | Ошибка загрузки модуля (dlopen) |
| `PAM_SYMBOL_ERR` | 2 | Не найден символ модуля |
| `PAM_SERVICE_ERR` | 3 | Ошибка модуля-сервиса |
| `PAM_SYSTEM_ERR` | 4 | Внутренняя ошибка PAM |
| `PAM_BUF_ERR` | 5 | Ошибка работы с буфером |
| `PAM_PERM_DENIED` | 6 | Доступ запрещён (например, `pam_access`) |
| `PAM_AUTH_ERR` | 7 | Ошибка аутентификации (неверный пароль) |
| `PAM_CRED_INSUFFICIENT` | 8 | Недостаточно прав для доступа к данным аутентификации |
| `PAM_AUTHINFO_UNAVAIL` | 9 | Данные аутентификации недоступны (LDAP недоступен) |
| `PAM_USER_UNKNOWN` | 10 | Пользователь не найден |
| `PAM_MAXTRIES` | 11 | Превышено число попыток (`pam_faillock`) |
| `PAM_NEW_AUTHTOK_REQD` | 12 | Требуется сменить токен (истёк пароль) |
| `PAM_ACCT_EXPIRED` | 13 | Учётная запись просрочена |
| `PAM_SESSION_ERR` | 14 | Ошибка создания/закрытия сессии |
| `PAM_CRED_UNAVAIL` | 15 | Учётные данные недоступны |
| `PAM_CRED_EXPIRED` | 16 | Учётные данные просрочены |
| `PAM_CRED_ERR` | 17 | Ошибка установки учётных данных |
| `PAM_NO_MODULE_DATA` | 18 | Нет данных модуля |
| `PAM_CONV_ERR` | 19 | Ошибка диалогового интерфейса |
| `PAM_AUTHTOK_ERR` | 20 | Ошибка работы с токеном аутентификации |
| `PAM_AUTHTOK_RECOVERY_ERR` | 21 | Старый токен не восстановим |
| `PAM_AUTHTOK_LOCK_BUSY` | 22 | Файл/БД токена занят (блокировка `/etc/shadow`) |
| `PAM_AUTHTOK_DISABLE_AGING` | 23 | Aging токена отключён |
| `PAM_TRY_AGAIN` | 24 | Не все модули смогли обновить токен |
| `PAM_IGNORE` | 25 | Результат модуля не учитывается |
| `PAM_ABORT` | 26 | Критическая ошибка, немедленный abort |
| `PAM_AUTHTOK_EXPIRED` | 27 | Токен аутентификации просрочен |
| `PAM_MODULE_UNKNOWN` | 28 | Неизвестный/несовместимый модуль |
| `PAM_BAD_ITEM` | 29 | Неверный параметр в `pam_*_item()` |
| `PAM_CONV_AGAIN` | 30 | Диалог event-driven, данные ещё недоступны |
| `PAM_INCOMPLETE` | 31 | Повторить вызов для завершения стека |

**Карта кодов к флагам управления.** При стандартных флагах `required`/`requisite`/`sufficient`/`optional` поведение определяется таблицей в разделе *Структура строки конфигурации*. В расширенном синтаксисе `[имя_кода=действие]` переопределяет реакцию PAM на конкретный код. Имена кодов: `success`, `open_err`, `symbol_err`, `system_err`, `buf_err`, `perm_denied`, `auth_err`, `cred_insufficient`, `authinfo_unavail`, `user_unknown`, `maxtries`, `new_authtok_reqd`, `acct_expired`, `authtok_err`, `authtok_lock_busy`, `authtok_disable_aging`, `no_module_data`, `conv_err`, `module_unknown`, `bad_item`, `conv_again`, `incomplete`, `default`. Допустимые действия: `ignore`, `ok`, `done`, `die`, `bad`, `reset`, `N` (пропустить следующие N модулей).

**Ключевая особенность:** изменения в конфигурации PAM применяются немедленно, перезапуск сервисов не требуется.

## Практические сценарии

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

**Шаг 1:** настроить `/etc/security/limits.conf`. Синтаксис: `<домен> <тип> <item> <значение>`.

```
# <domain> <type>  <item>    <value>
*       soft    nofile      65536
*       hard    nofile      1048576
@admin  soft    nproc       8192
@admin  hard    nproc       16384
root    soft    maxlogins   10
nginx   -       nofile      1048576
```

Типы: `soft` (мягкий — можно превысить до hard), `hard` (жёсткий — верхний предел), `-` (оба). Предусмотренные item-ы: `nofile`, `nproc`, `stack`, `fsize`, `core`, `as`, `memlock`, `priority`, `nice`, `maxlogins`, `maxsyslogins`.

**Шаг 2:** отдельные профили удобно выносить в drop-in `/etc/security/limits.d/*.conf` — они обрабатываются после `limits.conf`, а при конфликте **поздний файл побеждает**.

**Шаг 3:** убедиться, что модуль подключён в `/etc/pam.d/common-session` (Debian/Ubuntu) или `/etc/pam.d/system-auth` (RHEL):

```text
session    required    pam_limits.so
```

**Шаг 4:** проверить применение в активной сессии после перелогина:

```bash
# Открытые файлы (soft/hard)
ulimit -n          # 65536
# Жёсткие лимиты процесса
ulimit -Hn         # 1048576
# Полный набор RLIMIT через prlimit (без перелогина)
prlimit -o -p $$   # → nofile: 65536,1048576
```

**Важно:** `pam_limits.so` применяется только к пользовательским сессиям (SSH, GUI, `login`), **не** к `systemd`-сервисам — их лимиты задаются в unit-файлах (`LimitNOFILE=`, `LimitNPROC=` и др.). Лимиты вступают в силу после перелогина.

Подробнее: [Лимиты ресурсов](../Core/processes/resource_limits_concepts.md).

### 6. Защита от перебора паролей (`pam_faillock.so`)

Защита от перебора паролей — ограничение количества неудачных попыток аутентификации: после заданного числа подряд идущих неудачных попыток учётная запись блокируется на определённое время. Реализуется на нескольких уровнях:

*   **Уровень PAM (низкоуровневый):** модули `pam_faillock.so` (современный) или `pam_tally2.so` (устаревший) считают неудачи в подсистеме аутентификации — действует на все сервисы, использующие PAM (`login`, `sshd`, `su`, `sudo`, графический вход).
*   **Уровень сетевой службы:** собственные настройки службы, если она поддерживает ограничение попыток.
*   **Внешние решения:** например, [fail2ban](./Tools/fail2ban.md) — следит за журналом неудачных SSH-аутентификаций, высчитывает количество попыток и блокирует трафик с IP-адреса атакующего средствами пакетного фильтра.

Ниже — низкоуровневый вариант: настройка на уровне PAM.

**Задача:** заблокировать пользователя на 15 минут после 3 неудачных попыток входа.

**Шаг 1:** настроить параметры в `/etc/security/faillock.conf`:

```text
deny = 3
unlock_time = 900
silent
```

Полный набор опций `faillock.conf` со значениями по умолчанию: `deny = 3` (порог блокировки), `fail_interval = 900` (окно в секундах, в течение которого считаются подряд идущие неудачи), `unlock_time = 600` (время блокировки; `0` — без автоматической разблокировки, только `faillock --reset`), `dir = /var/run/faillock` (каталог счётчиков; очищается при перезагрузке — для сохранения счётчиков между перезагрузками задайте постоянный путь, например `/var/log/faillock`), `silent`, `audit`, `nodelay`. По умолчанию модуль выдерживает задержку после каждой неудачной попытки перед повторным запросом пароля — это замедляет автоматизированный перебор; опция `nodelay` её отключает.

**Шаг 2:** подключить модуль в стек `auth`. Порядок важен: `pam_faillock.so preauth` **в начале**, `pam_unix.so` после него, `pam_faillock.so authfail` **в конце**.

**Полный стек (`pam_faillock`), включающий аутентификацию, учётную запись и сессию** (эталонный пример из `pam_faillock(8)`; для RHEL разместите строки в `/etc/pam.d/system-auth`):

```text
#%PAM-1.1.3
# 1. preauth — считать счётчики попыток перед проверкой
auth        required      pam_faillock.so preauth silent
# 2. основной метод — локальный пароль
auth        sufficient    pam_unix.so
# 3. authfail — зафиксировать провал (default=die → отказ при блокировке)
auth        [default=die] pam_faillock.so authfail
# 4. резервный метод через SSSD/LDAP
auth        sufficient    pam_sss.so
# 5. окончательный отказ
auth        required      pam_deny.so
# учётная запись и сессия применяют тот же модуль для блокировок
account     required      pam_unix.so
account     required      pam_faillock.so
password    requisite     pam_pwquality.so retry=3
password    required      pam_unix.so sha512 shadow
session     optional      pam_sss.so
session     required      pam_unix.so
session     optional      pam_faillock.so
session     required      pam_limits.so
session     optional      pam_keyinit.so force revoke
```

**Порядок действий:** `preauth` считывает счётчик; если `pam_unix` возвращает `PAM_SUCCESS` — стек проходит (`sufficient`) и `authfail` пропускается; иначе выполнение доходит до `[default=die] pam_faillock.so authfail`, который фиксирует неудачу и, при превышении `deny`, возвращает `PAM_MAXTRIES` — из‑за `die` это немедленный отказ. Флаг `silent` подавляет пользовательские сообщения о блокировке.

**Альтернатива — аргументы прямо в строке модуля** (переопределяют значения из `faillock.conf`). Пример — блокировка на 2 часа после 4 неудачных попыток:

```text
auth        required      pam_faillock.so preauth silent deny=4 unlock_time=7200
auth        [default=die] pam_faillock.so authfail deny=4 unlock_time=7200
```

**Эквивалент через `authselect` (RHEL 8+):** профиль `sssd` с включённым faillock:

```bash
sudo authselect select sssd with-faillock --force
# кастомный профиль: правка /etc/authselect/custom/<profile>/system-auth
```

На Debian/Ubuntu аналогичный стек генерируется утилитой `pam-auth-update` из профилей в `/usr/share/pam-configs/`; ручное редактирование `common-auth` перезаписывается при следующем вызове.

**Шаг 3 — проверка поведения:**

```bash
# Имитация неудачных входов (3 попытки с неверным паролем для существующего пользователя)
# → после 3-й неудачи faillock блокирует аккаунт; последующие входы отклонены даже с верным паролем

# Просмотр накопленных попыток и счётчика
faillock --user alice
# Сброс блокировки (разблокировка)
faillock --user alice --reset
# root не блокируется, если even_deny_root не задан:
faillock --user root
```

**Утилита управления:**
*   Просмотр попыток: `faillock --user <имя>` (или `faillock --all`)
*   Сброс блокировки: `faillock --user <имя> --reset`
*   Сброс всех: `faillock --reset --all`

**Почему root исключён по умолчанию.** Ограничивающие настройки аутентификации по умолчанию не действуют на суперпользователя — и это осознанный выбор, а не упущение. Имя `root` известно любому атакующему, поэтому блокировка учётной записи после N неудачных попыток превращается в тривиальную атаку отказа в обслуживании: достаточно извне подбирать пароль к `root`, чтобы заблокировать учётную запись. Для root применяют дополнительные средства защиты: опции `even_deny_root` и `root_unlock_time` (блокировать root, но с отдельным таймаутом разблокировки), SELinux, запрет входа под root по сетевым службам (`PermitRootLogin no` в `sshd_config` — см. [SSH hardening](./ssh/server/ssh_hardening_best_practices.md)).

**Устаревший вариант — `pam_tally2.so`.** До `pam_faillock` учёт неудачных попыток вёл `pam_tally2`: счётчик хранится в `/var/log/tallylog`, управление — утилитой `pam_tally2 --user <имя>` (просмотр) и `pam_tally2 --user <имя> --reset` (сброс). Форматы счётчиков `pam_tally2` (`/var/log/tallylog`) и `pam_faillock` (`/var/run/faillock` или `dir=` из `faillock.conf`) несовместимы, поэтому в конфигурации должен использоваться только один из модулей. В RHEL 8+, CentOS 8+ и Fedora `pam_tally2` заменён на `pam_faillock`; базовые опции (`deny=`, `unlock_time=`, `even_deny_root`, `root_unlock_time=`, `audit`) задаются аналогично.

**Восстановление после блокировки (lockout recovery):** если доступ потерян, придите в одиночный режим (init=/bin/bash), смонтируйте `/` для записи (`mount -o remount,rw /`) и выполните `faillock --user <имя> --reset`. Безопаснее — держать резервный root-доступ по ключу (без `pam_faillock` на пути `auth`). См. [Восстановление пароля и доступа](../SystemAdministration/linux_password_recovery.md).

### 7. Двухфакторная аутентификация (`pam_google_authenticator.so`)

**Задача:** требовать OTP-код (TOTP) при входе по SSH.

**Шаг 1:** установка модуля и генерация ключа пользователем:
```bash
sudo apt install libpam-google-authenticator
google-authenticator  # следовать инструкциям мастера
```

**Шаг 2:** добавить модуль в `/etc/pam.d/sshd`:
```text
auth required pam_google_authenticator.so
```

**Шаг 3:** включить поддержку в `/etc/ssh/sshd_config`:
```text
KbdInteractiveAuthentication yes  # или ChallengeResponseAuthentication в старых версиях
UsePAM yes
```

### 8. Автоматическое создание домашних директорий (`pam_mkhomedir.so`)

**Задача:** автоматически создавать `/home/<user>` при первом входе пользователя из LDAP/Active Directory.

**Debian/Ubuntu:** добавить строку в `/etc/pam.d/common-session`:
```text
session required pam_mkhomedir.so skel=/etc/skel umask=0022
```

**RHEL/CentOS:** рекомендуется использовать сервис `oddjobd` и его модуль:
```bash
sudo yum install oddjob-mkhomedir
sudo systemctl enable --now oddjobd
# authselect автоматически настроит использование pam_oddjob_mkhomedir.so
```

| Аргумент | Описание |
| :--- | :--- |
| `skel` | Шаблон файлов для новой директории |
### 9. Выполнение скриптов при входе (`pam_exec.so`)

**Задача:** отправлять уведомление в Telegram при каждом входе пользователя по SSH.

**Шаг 1:** создать скрипт `/usr/local/bin/login-notify.sh`:
```bash
#!/bin/bash
if [ "$PAM_TYPE" = "open_session" ]; then
  curl -s -X POST "https://api.telegram.org/bot<token>/sendMessage" \
    -d chat_id="<id>" -d text="User $PAM_USER logged in to $(hostname) from $PAM_RHOST"
fi
```

**Шаг 2:** добавить модуль в `/etc/pam.d/sshd`:
```text
session optional pam_exec.so /usr/local/bin/login-notify.sh
```

| Переменная PAM | Описание |
| :--- | :--- |
| `PAM_USER` | Имя пользователя |
| `PAM_RHOST` | Удалённый хост (для SSH) |
| `PAM_SERVICE` | Имя PAM-сервиса (`sshd`, `login`, `su`, ...) |
| `PAM_TYPE` | Тип вызова (`auth`, `acctmgmt`, `open_session`, `close_session`, `chauthtok`) |
| `PAM_TTY` | Имя терминала (для SSH — `ssh`) |
| `PAM_AUTHTOK` | Текущий токен аутентификации (пароль). Содержит **чувствительные данные** |
| `PAM_OLDAUTHTOK` | Предыдущий токен (при смене пароля) |
| `PAM_CONV` | Указатель на функцию диалога |
| `PAM_XDISPLAY` | Отображение X11 |
| `PAM_RUSER` | Имя пользователя на удалённой стороне |

> **Безопасность:** `PAM_AUTHTOK` и `PAM_OLDAUTHTOK` передаются в процесс окружающей среды. Скрипты `pam_exec` должны работать с правами, ограниченными для обычных пользователей, и **никогда не писать токен в лог**. Используйте `pam_exec` с `quiet` и ограничивайте права скрипта через `umask`/`setpriv`. Для одностороннего уведомления предпочтительно тип `session` (как в сценарии ниже), чтобы не зависеть от фазы `auth`.

### 10. Жёсткий allowlist для входа (`pam_listfile.so`)

**Задача:** разрешить вход по SSH только пользователям из явного списка, игнорируя остальных.

**Шаг 1:** создать файл списка (`/etc/security/ssh_allow.txt`):

```text
alice
bob
deploy
```

**Шаг 2:** добавить в `/etc/pam.d/sshd` (секция `account`):

```text
account required pam_listfile.so item=user sense=allow onerr=succeed file=/etc/security/ssh_allow.txt
```

**Поведение:** `sense=allow` — если пользователь найден в файле → `PAM_SUCCESS`; если нет → `PAM_AUTH_ERR`/отказ. `onerr=succeed` — если файл отсутствует или недоступен, вход не блокируется (избегаем самоблокировки админа при ошибке прав). Для строгого режима используйте `onerr=fail`.

Проверка:

```bash
# Попытка входа от имени пользователя не из списка → rejected в /var/log/auth.log
pamtester sshd charlie authenticate   # → Permission denied
```

### 11. Установка переменных окружения (`pam_env.so`)

**Задача:** вынудительно задать `TMOUT=3600` (автоотключение через час) и `LANG` для всех интерактивных сессий.

**Шаг 1:** в `/etc/pam.d/common-session` (Debian/Ubuntu) или `/etc/pam.d/login` (RHEL) убедиться, что `pam_env` включён — по умолчанию он уже присутствует:

```text
session required pam_env.so
```

Один вызов `pam_env.so` без аргументов читает **два** файла: `/etc/environment` (формат `KEY=VALUE`) и `/etc/security/pam_env.conf` (формат `VAR [DEFAULT=|OVERRIDE=]value`). Чтобы задействовать сторонний файл правил, укажите `conffile=`:

```text
session required pam_env.so conffile=/etc/security/custom_env.conf
```

**Шаг 2:** правила в `/etc/security/pam_env.conf`:

```text
# Формат: ПЕРЕМЕННАЯ   ЗНАЧЕНИЕ  (поддерживает ${VAR} и @{HOME})
TMOUT   DEFAULT=3600
LANG    DEFAULT=ru_RU.UTF-8
PATH    DEFAULT=${PATH}:/usr/local/sbin
```

А в `/etc/environment` (читается `pam_env` по умолчанию) простой синтаксис `KEY=VALUE`:

```text
TMOUT=3600
LANG=ru_RU.UTF-8
```

**Поведение:** `DEFAULT=` применяется, если переменная ранее не задана; `OVERRIDE=` перезаписывает; `VALUE` — всегда. `${VAR}` раскрывается в значение другой переменной. Переменные попадают в среду процесса логина и наследуются дочерними.

### 12. Управление PAM через Ansible

Прямые правки `lineinfile` в `/etc/pam.d/*` рискованны (порядок строк, дубли). В продакшене используйте `authselect` (RHEL) / `pam-auth-update` (Debian) и шаблоны.

```yaml
- name: Включить блокировку после перебора (pam_faillock) в system-auth
  ansible.builtin.lineinfile:
    path: /etc/pam.d/system-auth
    regexp: '^#?auth.*pam_faillock.so preauth'
    line: 'auth        required      pam_faillock.so preauth silent'
    backup: true

- name: Отключить вход с пустым паролем (убрать nullok из common-auth)
  ansible.builtin.replace:
    path: /etc/pam.d/common-auth
    regexp: '(pam_unix\.so)\s+nullok'
    replace: '\1'
    backup: true

- name: Убедиться, что pam_access включён для sshd
  ansible.builtin.lineinfile:
    path: /etc/pam.d/sshd
    regexp: '^account\s+required\s+pam_access.so'
    line: 'account    required     pam_access.so'
    backup: true
```

> **Best practice:** всегда `backup: true` и делать `pamtester <service> <user> authenticate` после изменения, прежде чем закрывать root-сессию. Не меняйте `common-auth` в учась: ошибка блокирует всех локальных пользователей.

## Диагностика и отладка

### 1. Анализ журналов

Все события PAM записываются в системные логи. Это первый источник информации при ошибках доступа. Идентификатор записи содержит имя модуля и сервис (`pam_unix(sshd:auth)`, `pam_faillock(sshd:auth)`).

- **Debian/Ubuntu:** `/var/log/auth.log` (или `journalctl`)
- **RHEL/CentOS/Fedora:** `/var/log/secure`
- **Универсально:** `journalctl -u sshd` или `journalctl -t PAM`

Полезные запросы:

```bash
# Неудачные аутентификации конкретного пользователя
grep "pam_unix(sshd:auth).*user=alice" /var/log/auth.log
# События блокировки faillock
journalctl -u sshd --since "1 hour ago" | grep -i faillock
# Аудит попыток перебора
journalctl -u sshd --since "today" | grep -c "Failed password\|Invalid user"
```

Подробнее о построении алертов на неудачные входы: [Мониторинг и устранение SSH](./ssh/server/ssh_monitoring_and_troubleshooting.md).

### 2. Режим отладки (Debug)

Большинство модулей поддерживают аргумент `debug`, который пишет детальную информацию в `syslog` (facility `authpriv`/`security`).

```text
auth    [success=1 default=ignore] pam_unix.so debug
account required pam_faillock.so audit
```

`pam_faillock.so audit` — логировать имя пользователя в системный журнал, если пользователь не найден. Чтобы включить отладку на уровне системы, можно задать переменную `PAM_DEBUG` или собрать `pamtester` с флагом `-v`.

> **Важно:** `debug`/`audit` в продакшене избыточно шумят и растут логи. Включайте таймбоксированно, а после диагностики убирайте аргумент.

### 3. Тестирование без риска блокировки

`pamtester` прогоняет конфиг `/etc/pam.d/<service>` для заданного пользователя без реального входа. Поддерживаются все управляющие группы (фазы):

```bash
pamtester sshd alice authenticate     # auth    — проверка пароля
pamtester sshd alice acctmgmt         # account — проверка срока/блокировки
pamtester sshd alice open_session     # session — создание сессии
pamtester sshd alice close_session    # session — закрытие сессии
pamtester sshd alice chauthtok        # password — смена токена
```

Код завершения — код `PAM_*` (0 = `PAM_SUCCESS`, 6 = `PAM_AUTH_ERR`, 9 = `PAM_USER_UNKNOWN`, ...). Пример:

```bash
pamtester sshd alice authenticate; echo "→ exit=$?"   # → exit=0
```

Список установленных сервисов и их стеков:

```bash
ls /etc/pam.d/
grep -H "pam_" /etc/pam.d/sshd
```

Для одностороннего пробного прогона (никогда не ломая вход) используйте `-v` и отдельный `pamtester` над тестовым сервисом-копией.

### 4. Типичные ошибки и восстановление

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `pam_unix(...): authentication failure` | Неверный пароль | Проверить `/etc/shadow`, `passwd -S <user>` |
| `pam_faillock(...): Consecutive login failures` | Достигнут порог `deny` | `faillock --user <user> --reset`; войти с резервного root |
| `pam_limits(...): Permission denied` | Модуль не подключён/пакет отсутствует | Debian: `apt install libpam-modules`; RHEL: пакет `pam`; добавить `session required pam_limits.so` |
| `pam_systemd(...): Failed to connect to bus` | `pam_systemd.so` отсутствует в `/etc/pam.d/login` | Добавить `session optional pam_systemd.so` |
| `Failed to create session: Already running in a session` | `pam_systemd` вызван дважды | Убрать дублирующую строку `pam_systemd.so` |
| `Module is unknown` / `cannot open shared object file: No such file or directory` | `.so` отсутствует в `/lib/security` | Установить пакет (например, `libpam-google-authenticator`, `libpam-sss`) |
| `pam_tally2: Unknown option` | Устаревший модуль/опция | Заменить `pam_tally2` на `pam_faillock` |
| `Authentication token manipulation error` | Ошибка в фазе `password`/модуле | Проверить стек `password` в `common-password`/`system-auth`; отключить `pam_unix` временно |

**Локальный recovery-чеклист:**
1.  Держите ВКЛЮЧЁННУЮ root-сессию в отдельном окне (см. [Управление доступом ФСТЭК](./Fstec/user_access_control.md)).
2.  Перед правкой `/etc/pam.d/*` делайте бэкап: `cp -a /etc/pam.d /etc/pam.d.bak.$(date +%F)`.
3.  Проверяйте каждое правило через `pamtester` до перезапуска сервиса.
4.  При блокировке входа — одиночный режим (`init=/bin/bash`), `mount -o remount,rw /`, `faillock --user <user> --reset`.

## Лучшие практики безопасности

1.  **Правило "Открытой сессии":** При редактировании файлов в `/etc/pam.d/` ВСЕГДА держите открытой одну сессию с правами `root`. Если вы допустите ошибку и заблокируете вход, вы сможете исправить её из этой сессии.
2.  **Использование стандартных утилит:** Предпочитайте `pam-auth-update` (Debian) или `authselect` (RHEL) ручному редактированию. Они минимизируют риск синтаксических ошибок.
3.  **Порядок имеет значение:** Модули `pam_faillock.so` (или устаревший `pam_tally2`) должны стоять в самом начале стека `auth`, чтобы учитывать все попытки, включая системные.
4.  **Принцип минимизации:** Не включайте `optional` модули, если они не несут практической пользы, чтобы уменьшить поверхность атаки и упростить отладку.
5.  **Защита от lockout:** Никогда не ставьте `requisite` или `required` на модули, зависящие от внешних сервисов (LDAP/AD) без наличия локального резервного метода аутентификации (`pam_unix.so`).

## Дополнительная информация

### Связанные документы

**PAM и лимиты:**
- [Управление доступом ФСТЭК](./Fstec/user_access_control.md)
- [Постоянная настройка лимитов (limits.d)](../Core/processes/persistent_limits_configuration.md)

**Аутентификация и политики:**
- [Хэширование паролей](../SystemAdministration/Users/password_hashing.md)
- [Интеграция с LDAP/SSSD](../SystemAdministration/Users/LDAP_SSSD/configuration.md)

**Безопасность модулей ядра:**
- [Безопасность модулей ядра](./Mechanisms/kernel_module_security.md) — подпись и контроль загрузки модулей

**Защита от перебора паролей:**
- [fail2ban](./Tools/fail2ban.md) — внешняя блокировка IP-адресов по журналам неудачных аутентификаций

**Мониторинг и аудит:**
- [Аудит системы (auditd)](../SystemAdministration/Logging/auditd.md)
- [Логирование в Linux](../SystemAdministration/Logging/logging_overview.md)
- [Мониторинг пользователей](../SystemAdministration/Users/user_monitoring.md)
- [Мониторинг и устранение SSH](./ssh/server/ssh_monitoring_and_troubleshooting.md) — brute-force, неудачные входы, `faillock`

