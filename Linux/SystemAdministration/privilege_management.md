# Управление привилегиями: su, sudo и Polkit

## Определения

- **Суперпользователь (root):** учетная запись, чьи абсолютные полномочия определяются исключительно идентификатором **UID 0**. Имя `root` является общепринятым псевдонимом; технически любая учетная запись с UID 0 (например, `toor` или кастомные имена) обладает идентичными правами.
- **Причины отказа от прямого входа под root:**
    1. **Обезличенность действий:** при использовании общей учетной записи несколькими администраторами невозможно установить авторство изменений.
    2. **Отсутствие аудита:** сессии суперпользователя по умолчанию не обеспечивают детальное протоколирование команд (в отличие от sudo). В случае взлома невозможно восстановить цепочку действий злоумышленника.
    3. **Риск случайных деструктивных действий:** отсутствие подтверждения (пароля) перед выполнением критических операций.
    4. **Запрет доступа:** в большинстве систем прямой вход под root заблокирован для всех терминалов и сетевых подключений (SSH), кроме системной консоли.
- **su (Switch User / Substitute User):** утилита для переключения идентификатора пользователя.
    - Требует пароль **целевого** пользователя (обычно root).
    - **su vs su - :** Использование `su` без параметров запускает оболочку, но не меняет переменные окружения. Использование `su -` (или `su -l`) включает **режим регистрации** (login shell): оболочка читает стартовые файлы (`.bash_profile` вместо `.bashrc`), подтягивает переменное окружение целевого пользователя и делает сессию максимально точной копией его среды.
    - Вызов рекомендуется делать по полному пути (`/usr/bin/su` или `/bin/su`) для защиты от поддельных бинарных файлов (Trojan horse), которые могут быть подсунуты в `PATH` для кражи пароля.
- **sudo (Superuser Do):** основной инструмент управления привилегиями.
    - Требует пароль **текущего** пользователя.
    - Обеспечивает детальное журналирование (syslog, journald) каждой команды с указанием автора, времени, терминала и рабочего каталога. Рекомендуется отправлять логи на отдельный защищенный сервер, чтобы их нельзя было подделать «задним числом».
    - Имеет встроенную защиту от оставленных сессий: по умолчанию пароль запрашивается повторно через 5 минут после последнего использования (таймаут).
    - Позволяет гранулярно ограничивать доступ через файл `/etc/sudoers`.


- **doas (Dedicated OpenBSD Application Submitter):** Минималистичная альтернатива `sudo`, изначально созданная для OpenBSD, набирающая популярность в Linux (Alpine, Arch) благодаря простоте конфигурации.
- **Polkit (PolicyKit):** Системная служба для управления привилегиями непривилегированных процессов. Работает через DBus и позволяет гранулярно разрешать системные действия (монтирование дисков, управление сетью) без предоставления полного root-доступа.
- **visudo:** Специализированный редактор для безопасного изменения файла `/etc/sudoers` с автоматической проверкой синтаксиса.
- **pkexec:** CLI-инструмент Polkit для выполнения команд от имени другого пользователя (аналог sudo в мире Polkit).
- **Запись сессий (session logging):** Механизм записи полного I/O потока sudo-сессии (`log_output`, `iolog_dir`) для последующего аудита и расследования инцидентов.
- **tty_tickets:** Директива sudo, требующая ввода пароля для каждого нового терминала (не только раз в N минут).
- **requiretty (устаревшая):** Директива, требующая наличия выделенного TTY для запуска sudo. Устарела в sudo 1.9.x+, заменена на `tty_tickets` и `pam_tty_audit`.
- **setuid на скрипты:** Ядро Linux **игнорирует** бит SUID на интерпретируемых файлах (скрипты bash, python, perl). Это поведение зафиксировано в man 2 execve и не может быть изменено. Для эмуляции SUID используется `sudo` или capabilities.
- **pam_tty_audit:** Модуль PAM, обеспечивающий запись всего ввода-вывода в аудит-логи для указанных пользователей или групп, независимо от sudo.
- **sudo_logsrvd:** Демон journald/syslog в sudo 1.9+, принимающий и централизующий логи удаленных хостов.
- **plugin-архитектура sudo (Sudo 1.9+):** Подключаемые модули (`audit`, `log_server`, `approval`) расширяют функциональность без перекомпиляции.
- **Linux Capabilities:** Гранулярное разделение полномочий UID 0 на отдельные биты (например, `CAP_NET_BIND_SERVICE`, `CAP_SYS_ADMIN`). Подробнее: [**Linux Capabilities**](../Security/Mechanisms/Capabilities.md).
- **auditd:** Демон аудита ядра Linux, фиксирующий все попытки повышения привилегий. Подробнее: [**auditd — аудит событий**](./Logging/auditd.md).
- **pam_wheel:** Модуль PAM, ограничивающий доступ к `su` только членам группы `wheel` (или другой указанной группы).

## Основные концепции

### Принцип наименьших привилегий

Фундаментальное правило информационной безопасности: субъект (пользователь или процесс) должен обладать только тем набором прав, который минимально необходим для выполнения текущей задачи. Использование `sudo` или `Polkit` вместо постоянной работы под учетной записью `root` является практической реализацией этого принципа.

### Механизмы повышения прав

1. **su (Switch User):**
   - Требует пароль **целевого** пользователя (обычно root).
   - По умолчанию не меняет переменные окружения. Использование `su -` (login shell) рекомендуется для полной инициализации окружения.
   - **Недостаток:** Необходимость передачи пароля администратора другим пользователям.

2. **sudo (Superuser Do):**
   - Требует пароль **текущего** пользователя.
   - Позволяет гранулярно настраивать разрешения (кто, где и какие команды может запускать).
   - Все действия через `sudo` автоматически логируются, создавая аудиторский след.

3. **doas:**
   - Значительно меньше кодовая база по сравнению с `sudo` (меньше поверхность атаки).
   - Простая конфигурация в одном файле `/etc/doas.conf`.
   - Поддерживает временное кэширование пароля (`persist`).

4. **Polkit:**
   - Предназначен для тонкой настройки доступа к системным ресурсам.
   - Использует файлы действий (`.policy`) и правила (`.rules`).
   - Позволяет запрашивать аутентификацию через графические диалоги (Agent).

### Интеграция с PAM (Pluggable Authentication Modules)

И `su`, и `sudo` полагаются на систему PAM для аутентификации и управления сессиями.
- **/etc/pam.d/sudo**: определяет правила проверки пароля, лимиты ресурсов и переменные окружения для сессий sudo.
- **/etc/pam.d/su**: управляет доступом к переключению пользователей. Часто используется модуль `pam_wheel.so` для ограничения возможности вызова `su` только членами группы `wheel`.

### Масштабирование: Алиасы в sudoers

Для управления правами на множестве серверов и для больших групп пользователей в `sudoers` используются алиасы (псевдонимы):

1. **User_Alias**: объединение пользователей в логические группы (админы, разработчики).
   `User_Alias ADMINS = jdoe, msmith, %wheel`
2. **Runas_Alias**: список пользователей, от имени которых разрешен запуск.
   `Runas_Alias DB_USERS = postgres, mysql`
3. **Host_Alias**: группировка серверов по назначению.
   `Host_Alias WEB_SERVERS = www1, www2, 10.0.0.5`
4. **Cmnd_Alias**: группировка команд.
   `Cmnd_Alias NETWORKING = /sbin/route, /sbin/ifconfig, /usr/bin/ip`

Пример использования: `ADMINS WEB_SERVERS = (DB_USERS) NETWORKING` (Админы на веб-серверах могут выполнять сетевые команды от имени пользователей БД).

### Таймауты и TTY-ограничения

| Директива | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `timestamp_timeout=` | Время (минуты) кэширования пароля | 5 |
| `tty_tickets` | Запрашивать пароль для каждого нового TTY | отключено (пароль кэшируется глобально) |
| `requiretty` | (устаревшая) Разрешать sudo только из выделенного TTY | отключена в sudo 1.9+ |
| `passwd_timeout=` | Время ожидания ввода пароля (секунды) | 5 |
| `passwd_tries=` | Максимум попыток ввода пароля | 3 |

**TTY-ограничения в PAM:**
- `pam_tty_audit.so` — записывает все нажатия клавиш в аудит-лог (не зависит от sudo).
- `pam_time.so` — ограничивает время доступа к сессиям (например, запрет доступа root ночью).

### Plugin-архитектура sudo (Sudo 1.9+)

В sudo 1.9 и выше поддерживается подключаемая архитектура:

| Plugin | Назначение |
| :--- | :--- |
| `sudo_audit` | Отправляет события аудита в системный аудит (auditd) |
| `sudo_logsrvd` | Централизованный сбор логов от удаленных хостов |
| `sudo_approval` | Внешние approval-хендлеры (например, Slack-уведомление перед выполнением) |
| `sudo_pair` | «Четыре глаза» — второе подтверждение для критических команд |

**Включение audit plugin:**
```text
# /etc/sudo.conf
Plugin audit sudo_audit.so
```

### Логирование и централизация аудита

**Локальное логирование sudo (syslog):**
```text
# /etc/sudoers
Defaults logfile="/var/log/sudo.log"
Defaults log_input, log_output
Defaults iolog_dir=/var/log/sudo-io
Defaults log_server="audit-host.example.com"
```

**Запись I/O (session recording):**
```text
# Включаем запись
Defaults log_output
Defaults iolog_dir=/var/log/sudo-io
Defaults iolog_flush=yes

# Просмотр
sudo sudoreplay -l
sudo sudoreplay replay/2026/09/13/username/
```

**Централизованный сбор логов (sudo_logsrvd):**
```bash
# На сервере-коллекторе
sudo /usr/libexec/sudo/sudo_logsrvd -n

# На клиентах
# /etc/sudo.conf
Plugin log_server sudo_logsrvd.so server=audit-host.example.com
```

### setuid/setgid на скрипты

Ядро Linux **намеренно игнорирует** бит SUID/SGID на интерпретируемых файлах (скрипты с shebang `#!/bin/bash`, `#!/usr/bin/python` и т.д.). Это защита от race condition, когда злоумышленник заменяет интерпретатор в момент выполнения.

**Почему SUID-скрипты опасны:**
```text
#!/bin/bash
# Если бы SUID работал, злоумышленник мог бы:
# 1. Создать /tmp/bash -> /bin/sh
# 2. Создать скрипт с SUID, вызывающий /bin/bash
# 3. В промежутке между exec() и open() подменить bash
# 4. Получить root-оболочку
```

**Альтернативы:**
- `sudo` с `NOPASSWD` на конкретный скрипт
- `setcap` для конкретных бинарников
- Политики Polkit для desktop-приложений

### systemd и привилегии

В systemd-юнитах есть несколько механизмов управления привилегиями без полного root-доступа:

| Директива | Назначение |
| :--- | :--- |
| `DynamicUser=` | Создание временного пользователя/группы (отсутствуют в /etc/passwd) |
| `SupplementaryGroups=` | Дополнительные группы (например, `wheel`, `docker`) |
| `CapabilityBoundingSet=` | Ограничивающий набор capabilities (whitelist) |
| `AmbientCapabilities=` | Capabilities, наследуемые дочерними процессами |
| `NoNewPrivileges=` | Запрет на повышение привилегий через SUID или fsuid |
| `PrivateTmp=` | Изолированный /tmp и /var/tmp |
| `ProtectSystem=` | Ограничение записи в / (full, strict, yes) |
| `ProtectHome=` | Ограничение доступа к /home (read-only, tmpfs) |

**Пример: безопасный unit для веб-приложения:**
```ini
[Service]
User=webapp
Group=webapp
DynamicUser=yes
SupplementaryGroups=wheel
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/lib/webapp
```

### SELinux и AppArmor

Модули MAC (Mandatory Access Control) работают **поверх** традиционных UID/GID-разрешений и могут дополнительно ограничивать root.

**SELinux:**
- Типы контекстов (`unconfined_t`, `httpd_t`, `svirt_lxc_net_t`)
- Даже root в домене `unconfined_t` может быть ограничен policy
- `sudo` работает, но действия sudo-пользователя получают контекст `staff_u:sysadm_r:staff_t` (не `root:sysadm_r:sysadm_t`)
- Политика `sudo` в SELinux отдельно разрешает переход между контекстами

**AppArmor:**
- Профили приложений в `/etc/apparmor.d/`
- Профиль для `sudo` редко кастомизируется, но профиль для исполняемого файла (например, `/usr/sbin/nginx`) действует и при запуске через sudo

**Взаимодействие:**
```bash
# Проверка контекста текущего пользователя
id -Z
# → unconfined_u:unconfined_r:unconfined_t:s0-s0:c0.c1023

# Проверка контекста после sudo
sudo id -Z
# → staff_u:sysadm_r:sysadm_t:s0-s0:c0.c1023

# Проверка denied событий в AppArmor
sudo aa-status
sudo dmesg | grep -i apparmor
```

## Практические сценарии

### 1. Запись в защищённые файлы

При попытке дописать данные в файл, доступный только root, через перенаправление (`>>`), `sudo` применяется только к команде слева от знака перенаправления.

**Правильные варианты:**

```bash
# Через tee (запись из stdin от root)
echo "new parameter" | sudo tee -a /etc/sysctl.conf

# Через sudo bash -c (вся строка выполняется от root)
sudo bash -c 'echo "1" > /proc/sys/net/ipv4/ip_forward'
```

### 2. Безопасное редактирование прав

Всегда используйте `visudo` для предотвращения ошибок, которые могут заблокировать доступ к системе.

```bash
# Редактирование основного файла
sudo visudo

# Создание модульного правила с валидацией
sudo visudo -f /etc/sudoers.d/web-admin
# Содержимое: webuser ALL=(root) NOPASSWD: /usr/sbin/nginx -t, /usr/bin/systemctl reload nginx
```

### 3. Управление окружением и сессиями в sudo

- `sudo -E`: Попытаться сохранить переменные окружения текущего пользователя (работает, если разрешено в sudoers через `SETENV`).
- `sudo -i`: Запуск интерактивной оболочки входа (login shell).
- `sudo -v`: Обновить метку времени (продлить сессию без ввода пароля).
- `sudo -k`: Аннулировать текущую сессию (следующий вызов sudo потребует пароль).
- `sudo -l`: Посмотреть список разрешенных команд для текущего пользователя.

### 4. Аварийное восстановление sudo

**Сценарий: ошибка в sudoers заблокировала все sudo-сессии**

Если вы ошиблись в `/etc/sudoers` или каталоге `/etc/sudoers.d/`, следующая же проверка может вернуть `parse error`. В худшем случае вы потеряете способность выполнения любых команд через sudo.

**Решение на уровне GRUB (без root-пароля):**

```bash
# 1. Перезагрузите сервер и в меню GRUB выберите ядро
# 2. Добавьте к строке загрузки: init=/bin/bash
#    (или systemd.unit=emergency.target для systemd)

# 3. После загрузки в emergency shell:
mount -o remount,rw /
chmod 644 /etc/sudoers
# или если кастомные файлы сломаны:
rm /etc/sudoers.d/breaking-file
visudo -c /etc/sudoers  # проверка синтаксиса
mount -o remount,ro /
reboot -f
```

**Восстановление из live-среды (физический доступ):**
```bash
# 1. Загрузитесь с USB/live CD
# 2. Смонтируйте корневой раздеол
mount /dev/sda1 /mnt
# 3. Исправьте файлы
chroot /mnt visudo
# 4. Перезагрузитесь
exit
reboot
```

**Проверка синтаксиса перед сохранением:**
```bash
# всегда запускайте перед закрытием visudo:
visudo -c
# → /etc/sudoers: parsed OK
# → /etc/sudoers.d/extra: parsed OK
```

### 5. Настройка doas

Конфигурация в `/etc/doas.conf` предельно лаконична:

```text
# Разрешить пользователю bob выполнять команды от root с кэшированием пароля
permit persist bob as root

# Разрешить группе wheel выполнять любые команды
permit :wheel

# Разрешить запуск конкретной команды без пароля
permit nopass bob as root cmd /sbin/reboot
```

### 6. Правила Polkit

Polkit разделяет определение действий и авторизацию:
- **Файлы действий (`/usr/share/polkit-1/actions/*.policy`):** XML-файлы, определяющие само действие (например, `org.freedesktop.login1.reboot`), описание и стандартные разрешения (yes, no, auth_admin).
- **Файлы правил (`/etc/polkit-1/rules.d/*.rules`):** JavaScript-файлы, переопределяющие стандартное поведение для конкретных пользователей или групп.

**Пример разрешения на перезагрузку без пароля:**

```javascript
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.login1.reboot" &&
        subject.isInGroup("wheel")) {
        return polkit.Result.YES;
    }
});
```

### 7. Аудит и sudoreplay

Sudo позволяет записывать полные сессии ввода-вывода (I/O logging), что полезно для обучения и детального расследования.

**Включение записи в sudoers:**
```text
Defaults log_output
Defaults iolog_dir=/var/log/sudo-io
```

**Просмотр записанных сессий:**
```bash
# Список записей
sudo sudoreplay -l

# Воспроизведение конкретной сессии
sudo sudoreplay <ID>
```

### 8. Централизованный аудит sudo через journald

```bash
# Просмотр всех sudo-сессий через journalctl
journalctl _COMM=sudo --since "1 hour ago"
# или по имени пользователя
journalctl _AUDIT_USER=john --since "today"

# Поиск по командной строке
journalctl SUDO_COMMAND=/usr/bin/apt
```

### 9. Восстановление заблокированного sudo через rescue.target

Если `/etc/sudoers` поврежден и обычный root-доступ заблокирован, используйте `emergency.target`:

```bash
# В GRUB добавьте: systemd.unit=emergency.target
# После загрузки:
mount -o remount,rw /
# Исправьте sudoers или временно:
usermod -aG wheel username
# или восстановите из бэкапа:
cp /etc/sudoers.bak /etc/sudoers
```

### 10. Делегирование через скрипты (wrapper scripts)

Вместо того чтобы предоставлять пользователю права на отдельные команды, можно объединить последовательность действий в скрипт и разрешить запуск только этого скрипта через sudo. Это снижает поверхность атаки: пользователь не может изменить логику, так как скрипт редактируется root, и не может выполнить отдельное действие, если оно не в скрипте.

```bash
# 1. Создаем скрипт от root
sudo tee /usr/local/bin/restart-nginx-status.sh << 'EOF'
#!/bin/bash
/usr/bin/systemctl status nginx.service
/usr/bin/systemctl restart nginx.service
EOF

# 2. Делаем исполняемым
sudo chmod 755 /usr/local/bin/restart-nginx-status.sh

# 3. Разрешаем пользователю batman запускать только этот скрипт
sudo visudo -f /etc/sudoers.d/batman
# Содержимое:
# batman ALL=(root) NOPASSWD: /usr/local/bin/restart-nginx-status.sh
```

**Проверка:**
```bash
# От администратора: что может делать пользователь
sudo sudo -l -U batman

# От самого пользователя
sudo -l
```

## Укрепление безопасности (Hardening)

- **sudoedit вместо sudo vim:** Используйте `sudoedit` (`sudo -e`) для редактирования файлов. Это предотвращает побег в оболочку (shell escape) через функции редактора.
- **Глубокий аудит (Sudo 1.9+):** Опции `intercept` и `log_subcmds` позволяют отслеживать не только команду, запущенную через sudo, но и все подкоманды, которые она порождает.
- **GTFOBins:** Избегайте предоставления прав `sudo` на утилиты, позволяющие запускать оболочку (`less`, `find`, `git`, `vi`). См. подробнее: [**GTFOBins**](../../Security/Tools/gtfobins.md).
- **Редакторы и интерпретаторы:** Утилиты `vim`, `nano`, `python`, `perl`, `bash`, `ash` при запуске через sudo с полными правами становятся комбайнами для получения root-оболочки. Даже право на `vim /etc/nginx/nginx.conf` небезопасно: через `:!bash` можно получить интерактивный shell. Используйте `sudoedit` или ограничьте право конкретным файлом без NOPASSWD.
- **Важность обновлений (CVE-2021-3156):** Уязвимость "Baron Samedit" показала, что даже в таких зрелых инструментах, как `sudo`, могут годами существовать критические дыры переполнения буфера. Регулярное обновление утилит управления привилегиями критично.
- **requiretty:** Устаревшая опция, часто мешающая автоматизации (например, Ansible). В современных системах обычно отключена.
- **pwfeedback:** Опция, отображающая звездочки при вводе пароля. Считается менее безопасной, так как выдает длину пароля.
- **Secure PATH:**
  ```text
  # /etc/sudoers
  Defaults secure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  ```
  Защита от подстановки вредоносных путей в `PATH` пользователя.
- **Запрет на shell-escape в редакторах:**
  ```text
  # Запрет запуска внешних команд из vim через sudo
  Defaults!vim        !syslog
  Defaults!/usr/bin/vim  !sudoedit
  ```
- **pam_securetty vs pam_wheel:** Используйте `pam_wheel.so` вместо `pam_securetty` — `wheel`-группа позволяет управлять доступом динамически без редактирования `/etc/securetty`.

## Диагностика и устранение неисправностей

| Симптом | Вероятная причина | Действие |
| :--- | :--- | :--- |
| `sudo: parse error in /etc/sudoers near line 42` | Ошибка синтаксиса | Исправьте строку через `pkexec visudo` или rescue mode |
| `sudo: no tty present and no askpass program specified` | `requiretty` или отсутствие TTY в SSH/Ansible | `Defaults !requiretty` или `Defaults !tty_tickets` |
| `sudo: PERM_ROOT_USER: command not allowed` | Команда не в sudoers | Добавьте полный путь через `visudo -f /etc/sudoers.d/...` |
| `sudo: unknown uid: 1000` | `/etc/passwd` поврежден или NFS | Проверьте `getent passwd 1000` |
| `sudo: unable to resolve host` | Несоответствие hostname в sudoers и `/etc/hostname` | Исправьте `Host_Name_` в `/etc/hostname` |
| `sudo: command not allowed after authentication` | `Cmnd_Alias` конфликтует с путями | Проверьте `sudo -l` и точные пути |
| `polkit: Authentication is required` | Правило Polkit не сработало | Проверьте `journalctl -u polkit` и логи Action IDs |
| `sudo: syntax error` после установки плагина | Ошибка в `/etc/sudo.conf` | Переименуйте файл и перезагрузите `sudo` |
| `sudo -l` показывает `(root) NOPASSWD: /usr/bin/less` | Риск shell escape (GTFOBins) | Немедленно удалите правило, используйте `sudoedit` |

## Граничные случаи и edge cases

### 1. setuid-скрипты не работают

```bash
# Это НЕ сработает (SUID игнорируется на скриптах):
sudo chmod u+s /usr/local/bin/myscript.sh
# → -rwrwsr-x 1 root root ... myscript.sh

# Правильное решение:
sudo visudo -f /etc/sudoers.d/myscript
# → username ALL=(root) NOPASSWD: /usr/local/bin/myscript.sh
```

### 2. Sudo в chroot-окружении

```bash
# В chroot /mnt/rootfs должен быть /etc/sudoers
# и все зависимости (libs, /etc/passwd, /etc/group):
sudo chroot /mnt/rootfs visudo -c
```

### 3. Sudo и канары (pipes)

```bash
# sudo НЕ передает привилегии через pipe:
echo "data" | sudo tee /root/file    # ✓ работает (tee запускается от root)
echo "data" | cat | sudo tee /root/file  # ✗ cat запускается от user, ошибка доступа
```

### 4. Sudo в systemd-юнитах

```ini
[Service]
User=deploy
ExecStart=/usr/bin/sudo /opt/app/start.sh
# Лучше: избегать sudo в юнитах, использовать DynamicUser= и capabilities
```

### 5. Sudo и NOPASSWD с устаревшими правилами

```text
# Опасное правило (все команды без пароля):
%wheel ALL=(ALL) NOPASSWD: ALL

# Безопасное правило (конкретные команды):
%wheel ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart nginx, /usr/bin/systemctl reload nginx
```

### 6. Sudo в Docker-контейнерах

```dockerfile
# Проблема: в контейнере обычно нет sudo, а root уже есть
# Решение 1: использовать gosu/su-exec для демона
ENTRYPOINT ["/usr/bin/gosu","appuser"]
CMD ["app","start"]

# Решение 2: установить sudo и настроить NOPASSWD
RUN apt install -y sudo && \
    echo "appuser ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/appuser
```

### 7. Sudo с пользовательским prompt

```text
# /etc/sudoers
Defaults passprompt="[sudo] пароль для %u на %H: "
Defaults badpass_message="Неверный пароль — попробуйте еще раз"
```

## Сравнение механизмов

| Характеристика | su | sudo | doas | Polkit |
| :--- | :--- | :--- | :--- | :--- |
| **Пароль** | Целевого пользователя | Текущего пользователя | Текущего пользователя | Текущего (или Agent) |
| **Гибкость** | Низкая (все или ничего) | Очень высокая | Средняя | Высокая (по действиям) |
| **Аудит** | Ограничен | Полный (syslog + journald) | Есть | Через journald |
| **Сложность** | Минимальная | Высокая | Низкая | Высокая |
| **Окружение** | Сохраняет (или `-`) | Сбрасывает (по умолчанию) | Сбрасывает | Сбрасывает |
| **Гранулярность** | Нет | Команды, хосты, пользователи | Команды, пользователи | Действия (Actions) |
| **Запись сессий** | Нет | I/O logging (1.9+) | Нет | Нет |
| **Совместимость** | Универсальна | Универсальна | OpenBSD/Unix-like | systemd-системы |

## Дополнительная информация

### Системные механизмы

- **SUID/SGID:** Специальные биты прав доступа. Подробнее: [**Специальные права доступа**](../Security/Concepts/File_Permissions/special_permissions.md).
- **Capabilities:** Гранулярное разделение полномочий UID 0. Подробнее: [**Linux Capabilities**](../Security/Mechanisms/Capabilities.md).
- **auditd:** Детальное отслеживание всех попыток повышения прав. Подробнее: [**auditd — аудит событий**](./Logging/auditd.md).
- **LDAP-интеграция sudo:** В крупных инфраструктурах `/etc/sudoers` может храниться в LDAP (Centrify, SSSD), что позволяет централизованно управлять политиками. Конфигурация в `/etc/nsswitch.conf`: `sudoers: files ldap`.
- **Сравнение оболочек через sudo:**
  - `sudo -i`: Полная имитация входа root (login shell, читает `.profile`).
  - `sudo -s`: Запуск оболочки `$SHELL` с сохранением большинства переменных окружения пользователя.
  - `sudo su -`: "Грязный" способ получения root-оболочки, не рекомендуемый в пользу `sudo -i`.
  - `sudo -u #0`: Прямой вызов как UID 0 (эквивалентно `sudo -i`, но без входа).

### Типовые конфигурации sudoers.d

**Сценарий A: DevOps-инженер (деплой, мониторинг, логи)**
```text
# /etc/sudoers.d/devops-team
# Члены группы devops могут управлять сервисами и читать логи
%devops ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *, /usr/bin/systemctl reload *
%devops ALL=(ALL) NOPASSWD: /usr/bin/journalctl *, /usr/bin/tail -f /var/log/*
Defaults!systemctl !logfile
```

**Сценарий B: SRE-инженер (только перезагрузка и вывод из standby)**
```text
# /etc/sudoers.d/sre-oncall
%sre ALL=(ALL) NOPASSWD: /usr/sbin/reboot, /usr/sbin/shutdown -r now, /usr/bin/systemctl suspend
Defaults!reboot log_input, log_output
```

**Сценарий C: Jenkins/CI-агент (деплой без полного root)**
```text
# /etc/sudoers.d/jenkins-deploy
jenkins ALL=(www-data) NOPASSWD: /usr/bin/git pull, /usr/bin/systemctl reload nginx
Defaults!/usr/bin/systemctl !requiretty
```

### Корпоративные сценарии (Enterprise)

**Централизованный сбор логов через syslog:**
```bash
# На каждом хосте:
Defaults log_host="audit-collector.corp.local"

# На audit-collector:
# /etc/rsyslog.d/sudo.conf
if $programname == 'sudo' then /var/log/sudo/sudo.log
```

**Интеграция с SIEM (ELK/Graylog):**
```bash
# Формат JSON через sudo 1.9+
Defaults log_format=json
Defaults log_server="siem.corp.local"
```

### Рекомендации по размеру sudoers

- Держите `/etc/sudoers` минимальным: только глобальные `Defaults` и включение каталога `#includedir /etc/sudoers.d`.
- Каждый отдельный набор правил — в отдельном файле `/etc/sudoers.d/<название_команды>`.
- **Для каждого пользователя, которому нужны sudo-права, создавайте отдельный файл** с именем учетной записи (например, `/etc/sudoers.d/peter`). Это упрощает аудит и отзыв прав: достаточно удалить один файл, а не править общий.
- Файлы в `sudoers.d` должны иметь права `0440` (владелец `root:root`).
- Исключайте комментарии и пустые строки из критичных файлов — проверяйте через `visudo -c`.

## См. также

- [**Linux Capabilities**](../Security/Mechanisms/Capabilities.md) — гранулярное разделение привилегий UID 0 без SUID
- [**Специальные права доступа**](../Security/Concepts/File_Permissions/special_permissions.md) — SUID, SGID, sticky bit
- [**auditd — аудит событий**](./Logging/auditd.md) — детальный аудит всех попыток повышения прав
