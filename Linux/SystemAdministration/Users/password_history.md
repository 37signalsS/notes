# Хранение истории паролей в Linux (неповторяемость паролей)

**Актуально для:** Linux с linux-PAM — Debian 12 / Ubuntu 24.04 / RHEL 9 / CentOS Stream 9 / openSUSE Leap 15

## Определения

- **История паролей (password history)** — механизм, запоминающий последние N паролей каждого пользователя и не позволяющий при смене пароля вернуться к одному из них.
- **Неповторяемость паролей (password non-reuse)** — политика, запрещающая повторное использование ранее применявшихся паролей; реализуется через историю.
- **`/etc/security/opasswd`** — файл, в котором хранятся хэши ранее использованных паролей (по одной строке на пользователя).
- **`pam_pwhistory`** — модуль PAM, предназначенный специально для истории паролей; предпочтительный механизм.
- **`remember=N`** — аргумент модуля `pam_unix.so`, включающий хранение N последних паролей (legacy-механизм).
- **TCB (Trusted Computing Base)** — альтернативная схема хранения паролей (ALT Linux, Mageia): отдельный shadow-файл на каждого пользователя в `/etc/tcb/`; модуль `pam_tcb` заменяет `pam_unix`.

## Базовые концепции

### Как работает механизм

История вступает в силу в момент смены пароля — фаза `password` стека PAM:

1. Пользователь запускает `passwd` (или меняет пароль через GUI/инструмент, использующий PAM).
2. Модуль проверки сложности (`pam_pwquality.so` и т. п.) проверяет новый пароль.
3. Модуль истории сравнивает новый пароль с хэшами из `/etc/security/opasswd`; совпадение → смена отклоняется.
4. Модуль записи (`pam_unix.so` / `pam_tcb.so`) сохраняет новый пароль в `/etc/shadow` (или `/etc/tcb/<user>/shadow`), а старый хэш — в историю.

Модуль истории должен быть подключён именно в секции `password` — одной из четырёх функций PAM (`auth`, `account`, `password`, `session`). Флаги управления (`required`, `requisite`, `sufficient`, `optional`) и расширенный синтаксис `[value=action ...]` определяют, прерывается ли обработка стека при успехе или неудаче — см. [PAM — обзор](../../Security/pam_overview.md).

Файл `/etc/security/opasswd` может присутствовать в дистрибутиве пустым — до настройки истории он не содержит записей.

### Файл истории `/etc/security/opasswd`

Формат строки: `login:uid:count:hash1,hash2,...`

| Поле | Описание |
| :--- | :--- |
| `login` | Символьный идентификатор пользователя |
| `uid` | Числовой идентификатор (UID) |
| `count` | Количество сохранённых хэшей |
| `hash1,hash2,...` | Хэши ранее использованных паролей через запятую |

```text
# → пример строки (legacy-механизм pam_unix remember=, хэши MD5 $1$)
testuser1:1001:2:$1$HjFAfYTG$qNDkF0zJ3v8ylCOrKB0kt0,$1$kcUjWZJX$E9uMSmiQeRh4pAAgzuvkq1
```

Хранятся хэши, а не пароли в открытом виде. Алгоритм хэширования зависит от механизма (см. ниже).

### Два механизма: pam_unix remember= и pam_pwhistory

| | `pam_unix.so remember=N` | `pam_pwhistory.so` |
| :--- | :--- | :--- |
| Назначение | встроенная опция модуля аутентификации | выделенный модуль истории |
| Алгоритм хранения | **MD5** (зафиксировано в man-странице `pam_unix(8)`) | системный алгоритм (yescrypt, SHA-512 и т. п.) |
| Дефолт | нет (нужно указать явно) | `remember=10` |
| Конфигурационный файл | — | `/etc/security/pwhistory.conf` (предпочтительный способ настройки) |
| Рекомендация | man-страница: «instead of this option the pam_pwhistory module should be used» | предпочтительный механизм |

Опции `pam_pwhistory.so`:

| Опция | Описание |
| :--- | :--- |
| `remember=N` | хранить N последних паролей; дефолт 10; `0` оставляет содержимое opasswd без изменений (не отключает модуль) |
| `retry=N` | сколько раз переспрашивать пароль при отказе; дефолт 1 |
| `use_authtok` | использовать новый пароль, полученный от предыдущего модуля в стеке |
| `enforce_for_root` | применять проверку и для root (по умолчанию root освобождён) |
| `file=/path` | хранить историю в другом файле (дефолт `/etc/security/opasswd`) |
| `conf=/path` | другой конфигурационный файл (дефолт `/etc/security/pwhistory.conf`) |
| `debug` | отладка через syslog |

Конфиг `/etc/security/pwhistory.conf` — формат `имя = значение` с теми же опциями; значения из командной строки модуля перекрывают файл.

Ограничения `pam_pwhistory` (man-страница `pam_pwhistory(8)`): не работает с Kerberos; не имеет смысла с NIS/LDAP — старые пароли хранятся локально и недоступны на других машинах.

### Кто попадает в историю

- **Пользователь меняет свой пароль** — проверка и запись работают штатно.
- **root меняет пароль пользователю** — по умолчанию проверка не применяется (`enforce_for_root` включает её); то же поведение у требований сложности (`pam_pwquality.so`).
- **Первичная установка пароля** — записывать нечего: предыдущего пароля ещё нет, поэтому после `useradd` + `passwd <user>` от администратора opasswd остаётся пустым.

## Практические сценарии

### Настройка в Debian/Ubuntu

Файл `/etc/pam.d/common-password` (общесистемные политики паролей; `passwd` и другие сервисы подключают его через `@include`):

```text
# legacy-вариант: remember= в строке pam_unix
password [success=1 default=ignore] pam_unix.so obscure yescrypt remember=10

# предпочтительный вариант: pam_pwhistory перед pam_unix
password requisite pam_pwhistory.so remember=10 retry=3 use_authtok
password [success=1 default=ignore] pam_unix.so obscure yescrypt use_authtok
```

Внимание: ручная правка `common-*` перезаписывается при следующем вызове `pam-auth-update`.

### Настройка в RHEL/CentOS/Fedora

Файл `/etc/pam.d/system-auth` (управляется через `authselect`); проверку сложности выполняет `pam_pwquality.so` (в старых выпусках — `pam_cracklib`/`pam_pwcheck`):

```text
password requisite pam_pwquality.so retry=3 minlen=12 minclass=4
password sufficient pam_unix.so sha512 shadow nullok try_first_pass use_authtok remember=10
```

или с выделенным модулем истории:

```text
password requisite pam_pwquality.so retry=3
password requisite pam_pwhistory.so remember=10 retry=3 use_authtok
password sufficient pam_unix.so sha512 shadow use_authtok
```

### Настройка в openSUSE

Файл `/etc/pam.d/passwd`: строка `password` с модулем `pam_unix.so`, к которой в конец добавляется `remember=N`:

```text
password sufficient pam_unix.so remember=10
```

### ALT Linux (схема TCB) — кратко

В ALT Linux вместо единого `/etc/shadow` используется схема TCB: хэш каждого пользователя лежит в `/etc/tcb/<имя>/shadow`, модуль `pam_tcb` заменяет `pam_unix`, переключение схем — командой `control passwd tcb|traditional|restricted`. История настраивается тем же `pam_pwhistory` (в `/etc/pam.d/system-auth-local-only`):

```text
password required pam_pwhistory.so use_authtok remember=10 retry=3
```

Предупреждение из документации ALT: при TCB файл `/etc/security/opasswd` должен быть доступен на запись группе `pw_users`, поэтому пользователи могут читать хэши других пользователей — на многопользовательских системах такая конфигурация не рекомендуется.

### Проверка работы механизма

```bash
# 1. Настроить remember=10 (см. разделы выше) и сохранить конфигурацию

# 2. Создать тестового пользователя; начальный пароль задаёт администратор
sudo useradd -m -s /bin/bash testuser1
sudo passwd testuser1
sudo cat /etc/security/opasswd
# → файл пуст или без строки testuser1 (предыдущего пароля нет)

# 3. Войти как пользователь и сменить пароль
su - testuser1
passwd
# → текущий пароль, затем новый; пароль успешно обновлён

# 4. История заполнилась
sudo cat /etc/security/opasswd
# → testuser1:1001:1:$y$...   (login:uid:count:hash)

# 5. Попытка вернуть старый пароль
passwd
# → текущий пароль, затем в качестве нового — предыдущий
# → Password has already been used. Choose another.
#    (в русской локализации: «Этот пароль уже использовался, выберите другой»)

# 6. Отказ фиксируется в журнале
journalctl -u sshd --since "5 minutes ago" | grep -i pam
# → записи о неудачной смене токена аутентификации
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Password has already been used. Choose another.` | штатный отказ: пароль в истории | выбрать другой пароль |
| opasswd остаётся пустым после смены | пароль менял root, а не сам пользователь; либо первичная установка; либо модуль не в секции `password` | проверить строку в `/etc/pam.d/`; сменить пароль от имени пользователя |
| `passwd: Authentication token manipulation error` | нарушен порядок строк в стеке `password`, не передан `use_authtok` | поставить `pam_pwhistory` до `pam_unix`, добавить `use_authtok` |
| Ложный отказ при создании пользователя с прежним именем | в opasswd осталась строка удалённого пользователя | удалить строку с этим login из `/etc/security/opasswd` |
| После уменьшения `remember=N` старые пароли разрешились | штатное поведение: хэши за пределом нового N больше не проверяются | при необходимости вернуть прежнее значение |
| `pam_pwhistory` не срабатывает в домене | модуль не работает с Kerberos/NIS/LDAP | настраивать политику на контроллере домена |

## Best Practices

1. **Предпочитать `pam_pwhistory`** над `pam_unix.so remember=`: последний хранит старые пароли в MD5-хэшах, что слабее системного алгоритма (yescrypt/SHA-512).
2. **Комбинировать со сложностью**: `pam_pwquality.so` (или `pam_passwdqc.so`) перед модулем истории — сначала проверяется сложность, потом неповторяемость, потом запись.
3. **Разумный баланс**: чрезмерно жёсткие требования (длинная история, сложные пароли, частая смена) толкают пользователей записывать пароли на стикеры — меры безопасности сводятся к нулю.
4. **Аудит**: `/etc/security/opasswd` содержит хэши — ограничивать доступ; при удалении учётной записи очищать её строку.
5. **Не использовать `remember=0` как «выключатель»**: для `pam_pwhistory` это оставляет существующую историю нетронутой, а не отключает проверку.

## Дополнительная информация

- [PAM — обзор](../../Security/pam_overview.md) — архитектура, флаги управления, стеки модулей
- [Хэширование паролей](./password_hashing.md) — алгоритмы и формат `/etc/shadow`
- [Политики паролей (chage)](./password_policy_chage.md) — срок действия пароля
- [Файлы конфигурации пользователей](./users_config_files.md) — структура базы данных учётных записей
- man-страницы: `pam_unix(8)`, `pam_pwhistory(8)`, `pwhistory.conf(5)`
