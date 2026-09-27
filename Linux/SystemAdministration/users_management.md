# Управление пользователями и группами в Linux

## Определения

- **Идентификация:** Процесс распознавания субъекта по его уникальному идентификатору (имя пользователя, UID).
- **Аутентификация:** Процесс подтверждения подлинности субъекта (пароли, SSH-ключи, биометрия, FIDO2-токены).
- **Авторизация:** Предоставление субъекту определенных прав доступа (чтение, запись, выполнение) на основе его идентификатора и членства в группах.
- **NSS (Name Service Switch):** Механизм диспетчеризации в библиотеке C (glibc), определяющий источники данных для системных баз (passwd, group, hosts). Конфигурируется в `/etc/nsswitch.conf`.
- **PAM (Pluggable Authentication Modules):** Модульный фреймворк для реализации различных методов проверки подлинности и политик безопасности (блокировка, сложность пароля).
- **SSSD (System Security Services Daemon):** Служба-посредник для интеграции Linux с внешними провайдерами идентификации (LDAP, Active Directory, FreeIPA), обеспечивающая кэширование и офлайн-вход.
- **Жизненный цикл пользователя (User Lifecycle):** Процесс, включающий создание (provisioning), настройку прав, мониторинг активности и удаление/архивацию (offboarding) учетной записи.
- **GECOS (General Electric Comprehensive Operating System):** Поле комментария в `/etc/passwd`, historically содержащее информацию о пользователе (имя, телефон, кабинет). В современных системах используется для хранения полного имени и контактных данных.
- **umask (User File Creation Mask):** Маска создания файлов, определяющая права по умолчанию для новых файлов и директорий. Вычисляется как инверсия от максимальных прав (666 для файлов, 777 для директорий).
- **Шаблон `/etc/skel`:** Набор файлов и директорий, копируемых в домашнюю директорию нового пользователя при создании учетной записи. Содержит конфигурации оболочки (`.bashrc`, `.profile`) и стандартные файлы среды.
- **Истечение срока действия (Account Expiration):** Механизм временного доступа, при котором учетная запись автоматически блокируется после указанной даты (`sp_expire` в `/etc/shadow`).
- **Старение пароля (Password Aging):** Политика принудительной смены пароля через поля `sp_max`, `sp_min`, `sp_warn` в `/etc/shadow`. Управляется утилитой `chage`.
- **Break-glass (Аварийный доступ):** Процедура предоставления временных привилегий в аварийных ситуациях с обязательным последующим аудитом.

## Основные концепции

Система управления доступом в Linux (2025–2026) строится на четырехуровневой архитектуре:

### 1. Уровень хранения (Configuration Layer)
Данные о пользователях хранятся в локальных файлах или внешних каталогах:
- **Локально:** `/etc/passwd`, `/etc/shadow`, `/etc/group`. Подробнее: **[Файлы конфигурации](Users/users_config_files.md)**.
- **Централизованно:** LDAP, Active Directory. Подробнее: **[LDAP и SSSD](Users/LDAP_SSSD/index.md)**.

### 2. Уровень диспетчеризации (Dispatching Layer — NSS)
Механизм **NSS** определяет, где искать информацию. Например, при вызове команды `ls -l` система обращается к NSS, чтобы узнать, в каких базах искать имя для UID.
- Файл `/etc/nsswitch.conf` управляет приоритетами: `passwd: files sssd` (сначала локальные файлы, затем LDAP через SSSD).

### 3. Уровень аутентификации (Authentication Layer — PAM)
**PAM** отделяет приложения от методов проверки подлинности. Когда пользователь вводит пароль, SSH или `sudo` обращаются к PAM.
- **pam_unix.so:** Проверка пароля в `/etc/shadow`.
- **pam_faillock.so:** Защита от перебора паролей (заменил устаревший `pam_tally2`).
- **pam_u2f.so:** Поддержка аппаратных ключей FIDO2.
- Подробнее: **[Обзор PAM](../Security/pam_overview.md)**.

### 4. Уровень управления сессиями (Session Management — logind)
Служба **`systemd-logind`** управляет жизненным циклом сессии: создает контекст при входе, выделяет ресурсы через cgroups, управляет ингибиторами питания и очищает временные файлы при выходе.
- Утилита `loginctl` позволяет отслеживать активные сессии и управлять ими.
- **Режим linger:** Позволяет фоновым процессам пользователя продолжать работать после выхода из сессии. Включается через `sudo loginctl enable-linger <user>`. Подробнее: **[Управление сессиями logind](../../Linux/Core/systemd/logind_session_management.md)**.

### 5. Параметры учетной записи и политики по умолчанию

Создание пользователя — не просто добавление строки в `/etc/passwd`. Система применяет набор политик, определяющих среду, права и ограничения:

- **`/etc/login.defs`:** Глобальные настройки по умолчанию для `useradd` и `userdel`. Определяет диапазоны UID/GID для системных и обычных пользователей, алгоритм хэширования паролей (YESCRYPT в 2025+), сроки действия паролей и параметры создания домашних директорий.
- **`/etc/skel/`:** Шаблон домашней директории. Содержит начальные файлы оболочки и окружения. Изменения в `/etc/skel` затрагивают только новых пользователей; существующие остаются без изменений.
- **GECOS:** Поле в `/etc/passwd` (5-е поле), содержащее полное имя, номер комнаты, рабочий телефон и другие комментарии. Используется командами `finger` и `chfn`.
- **Маска создания файлов (umask):** Наследуется из `/etc/login.defs` или `~/.profile`. Определяет, с какими правами создаются новые файлы. Для безопасности рекомендуется `027` или более строгие значения.
- **Наследование групп:** При создании пользователя ему присваивается первичная группа (по умолчанию группа с тем же именем — UPG). Дополнительные группы добавляются через `usermod -aG`.

### 6. Современные методы аутентификации

Парольная аутентификация уступает место многофакторным и ключевым методам:

- **SSH-ключи:** Асимметричная криптография (RSA 4096, Ed25519). Хранятся в `~/.ssh/authorized_keys`. Рекомендуется использовать `ssh-keygen -t ed25519 -C "user@host"` и защищать приватный ключ парольной фразой.
- **Сертификаты SSH:** Подпись публичных ключей доверенным CA (Certificate Authority). Позволяет управлять доступом centrally без распространения authorized_keys.
- **FIDO2 / Passkeys:** Аппаратные токены (YubiKey) или биометрия. В Linux поддерживается через `pam_u2f.so` и `pam_fido2.so`. Подходит для защиты `sudo` и локального входа.
- **Kerberos:** Сетевая аутентификация с тикетами (tickets). Используется в enterprise-средах через SSSD и `pam_krb5.so`.

**Дополнительные ресурсы:**
- **[Обзор PAM](../Security/pam_overview.md)** — модульный фреймворк аутентификации, MFA, SSH integration.
- **[Kerberos](../Security/Concepts/kerberos.md)** — основы сетевой аутентификации, билеты, KDC, keytab.
- **[LDAP и SSSD](Users/LDAP_SSSD/index.md)** — централизованное управление пользователями.
- **[NSS (Name Service Switch)](Users/users_config_files.md#диспетчер-name-service-switch-etcnsswitchconf)** — механизм поиска данных о пользователях.

## Практические сценарии

### 1. Стандартное управление (Императивный подход)
Используется для ручного администрирования или простых bash-скриптов.
- **Создание:** `useradd` (базовая) или `adduser` (интерактивная обертка в Debian/Ubuntu).
- **Модификация:** `usermod`, `passwd`, `chage`.
- **Группы:** `groupadd`, `gpasswd` (добавление пользователей в группы).
- Подробнее: **[Команды управления пользователями](Users/user_commands.md)**.

### 2. Декларативное управление (Современный подход)
Рекомендуется для автоматизации инфраструктуры, создания образов (Golden Images) и систем с неизменяемой ФС (Immutable OS).
- **Системные пользователи:** **[systemd-sysusers](Users/systemd-sysusers.md)**. Создание через файлы `.conf` в `/etc/sysusers.d/`.
- **Портативные аккаунты:** **[systemd-homed](Users/systemd-homed.md)**. Домашние директории как зашифрованные LUKS2-образы.
- **Автоматизация IaC:** Модули `user` и `group` в **[Ansible](../../Ansible/Modules/ansible_security_and_user_management_modules.md)**.

### 3. Учетные записи служб (Service Accounts)
Специальные аккаунты для запуска демонов.
- **Безопасность:** В качестве оболочки всегда используется `/usr/sbin/nologin` (выдает сообщение об отказе) или `/bin/false` (тихо завершается).
- **UID:** Обычно в диапазоне **100–999**.
- **Конвенция именования:** Использование префикса подчеркивания (например, `_nginx`, `_postgres`) для отличия от людей.
- **Группы:** Рекомендуется создавать уникальную системную группу для каждого сервиса (UPG для служб), чтобы минимизироватьblast radius при компрометации.
- **Домашние директории:** Для большинства служб домашняя директория не требуется (`-r -m` в `useradd`). Используйте `--system --no-user-group` для минимальных аккаунтов.

### 4. Аудит и комплаенс (Compliance)
Проверка системы на соответствие стандартам (CIS Benchmark, DISA STIG, PCI DSS):
- **Быстрая проверка:** Поиск пустых паролей, дубликатов UID 0, некорректных прав.
- **Автоматический аудит:** OpenSCAP, Ansible, специализированные скрипты.
- **Мониторинг drift:** auditd, AIDE, Tripwire для отслеживания изменений.
- **Исправление (Remediation):** Автоматическое приведение в соответствие через Ansible.
- Подробнее: **[Compliance для пользователей](Users/users_compliance.md)** — CIS, STIG, PCI DSS, OpenSCAP.

### 5. Аварийный доступ и break-glass процедуры

В аварийных ситуациях (отказ администратора, compromised root, блокировка) требуется быстрый контролируемый доступ:

```bash
# Создание аварийного пользователя с истечением срока действия через 24 часа
sudo useradd -m -s /bin/bash -e $(date -d "+1 day" +%F) emergency-admin

# Назначение временных прав sudo (действительно до перезагрузки)
echo "emergency-admin ALL=(ALL) ALL, !/usr/bin/passwd root, !/usr/bin/rm -rf /" | sudo tee /etc/sudoers.d/emergency-admin

# Логирование всех команд emergency-admin в отдельный файл
sudo usermod -aG adm emergency-admin
```

**Политика:**
- Все break-glass аккаунты должны иметь срок истечения не более 24–72 часов.
- Использование обязательного через `sudo` с session recording (`tlog`).
- Автоматическое уведомление команды безопасности (Slack, PagerDuty, email) при активации.

**Disaster Recovery:** Восстановление после сбоев, backup/restore, forensic analysis.
- Подробнее: **[Disaster Recovery для пользователей](Users/users_disaster_recovery.md)** — backup, recovery, forensic.

### 6. Автоматизация жизненного цикла (Provisioning и Offboarding)

**Onboarding (Provisioning):**
```bash
#!/bin/bash
# provision_user.sh — пример массового создания пользователей из CSV
# Формат: login,full_name,groups,ssh_key_file

while IFS=, read -r login full_name groups ssh_key; do
    sudo useradd -m -c "$full_name" -s /bin/bash -G "$groups" "$login"
    sudo mkdir -p /home/$login/.ssh
    sudo cp "$ssh_key" /home/$login/.ssh/authorized_keys
    sudo chown -R $login:$login /home/$login/.ssh
    sudo chmod 700 /home/$login/.ssh
    sudo chmod 600 /home/$login/.ssh/authorized_keys
    echo "Создан пользователь: $login"
done < users.csv
```

**Offboarding:**
```bash
#!/bin/bash
# offboard_user.sh — удаление/архивация учетной записи

USERNAME="$1"
ARCHIVE_DIR="/archive/users"

# Архивирование домашней директории
sudo tar -czf "$ARCHIVE_DIR/$USERNAME-$(date +%F).tar.gz" /home/$USERNAME

# Блокировка учетной записи (сохранение UID и файлов)
sudo usermod -L -s /usr/sbin/nologin "$USERNAME"
sudo chage -E 0 "$USERNAME"

# Удаление спустя 30 дней (через cron)
# sudo userdel -r "$USERNAME"
```

### 7. Очистка устаревших учетных записей (Stale Account Cleanup)

Периодическая аудита неактивных учетных запей предотвращает "устаревание" прав:

```bash
# Список пользователей, не входивших в систему более 90 дней
sudo lastlog -b 90 -t 0 | tail -n +4 | awk '($1 != "**Never") {print $1}'

# Поиск пользователей с expired паролем, но активной учетной записью
sudo awk -F: '$8 == "" {print $1}' /etc/shadow

# Массовая блокировка неактивных сервисных аккаунтов (UID < 1000, без входа)
sudo awk -F: -v d="$(date -d '-180 days' +%F)" '$3 < 1000 && $7 != "/sbin/nologin" && $7 != "/bin/false" {print $1}' /etc/passwd | while read svc; do
    sudo usermod -s /usr/sbin/nologin "$svc"
done
```

**Политика:** В enterprise-средах рекомендуется запускать скрипт очистки ежеквартально через cron/systemd timer с уведомлением ответственных.

**Дополнительные ресурсы:**
- **[Управление привилегиями (sudo, Polkit)](privilege_management.md)** — делегирование прав, audit, LDAP-интеграция.
- **[Disaster Recovery для пользователей](Users/users_disaster_recovery.md)** — backup/restore, recovery, forensic.

### 8. Управление SSH-ключами и паролями

**SSH-ключи:**
```bash
# Просмотр всех authorized_keys в системе (поиск устаревших ключей)
sudo find /home -name authorized_keys -exec grep -H "ssh-rsa" {} \; | sort

# Проверка strength ключей (исключаем DSA, RSA < 2048)
sudo find /home -name authorized_keys -exec sh -c '
    for f; do
        echo "=== $f ==="
        grep -o "ssh-[a-z0-9]* [A-Za-z0-9+/=]*" "$f" | while read -r type key comment; do
            bits=$(echo "$key" | base64 -d | ssh-keygen -l -F /dev/stdin 2>/dev/null | awk "{print \$1}")
            echo "$type $bits bits — $comment"
        done
    done
' sh {} +

# Отзыв compromised ключа (если используется ssh-agent)
ssh-add -d /path/to/compromised/key
```

**Ротация паролей:**
```bash
# Принудительная смена пароля для всех пользователей с пустым паролем
sudo awk -F: '($2 == "") {print $1}' /etc/shadow | while read user; do
    sudo passwd -e "$user"
    echo "Пароль для $user истечен, требуется смена при следующем входе"
done
```

### 9. Аудит, мониторинг и реагирование

**Интеграция с auditd:**
```bash
# Мониторинг изменений /etc/passwd, /etc/shadow, /etc/group
sudo auditctl -w /etc/passwd -p wa -k user_db_modification
sudo auditctl -w /etc/shadow -p wa -k shadow_access
sudo auditctl -w /etc/group -p wa -k group_db_modification

# Поиск событий за последний час
sudo ausearch -k user_db_modification -ts recent
```

**Интеграция с journald:**
```bash
# Все события auth с 2026-01-01
sudo journalctl -u sshd --since "2026-01-01" | grep "Accepted publickey"

# Отказ в доступе по UID
sudo journalctl _PID=1 | grep "pam_unix(sshd:auth): authentication failure"
```

**Алертинг в Prometheus (node_exporter):**
- Метрики `node_user_sessions_total` (если включен `textfile collector` или экспортер).
- Алерт на пользователей с UID 0, отличных от root.

### 10. Интеграция с контейнерами и инфраструктурой

**Rootless containers (Podman):**
```bash
# Создание пользователя с диапазоном subuid/subgid для rootless Podman
sudo useradd -m -s /bin/bash podman-user
echo "podman-user:100000:65536" | sudo tee -a /etc/subuid
echo "podman-user:100000:65536" | sudo tee -a /etc/subgid

# Проверка
podman-user$ podman run --rm alpine id
# → uid=1000(podman-user) gid=1000(podman-user) groups=1000(podman-user)
```

**CI/CD раннеры (GitLab CI, Jenkins):**
```bash
# Создание изолированного пользователя для раннера
sudo useradd -r -s /usr/sbin/nologin -m -d /home/ci-runner -c "CI/CD Runner" ci-runner
sudo mkdir -p /home/ci-runner/.ssh
sudo cp runner_ssh_key.pub /home/ci-runner/.ssh/authorized_keys
sudo chown -R ci-runner:ci-runner /home/ci-runner/.ssh
```

**Ограничение ресурсов:**
```bash
# Ограничение процессов и памяти для пользователя через systemd slice
sudo systemctl set-property ci-runner.service CPUQuota=50% MemoryMax=2G

# Или через loginctl для интерактивных сессий
sudo loginctl enable-linger ci-runner
sudo systemctl set-property user@1001.service CPUQuota=50% MemoryMax=2G
```

### 11. Аварийное восстановление

Потеря `/etc/passwd` или `/etc/shadow` критична. Восстановление:

```bash
# Из резервной копии
sudo cp /backup/etc/passwd /etc/passwd
sudo cp /backup/etc/shadow /etc/shadow
sudo cp /backup/etc/group /etc/group
sudo chmod 644 /etc/passwd /etc/group
sudo chmod 600 /etc/shadow

# Если резервной копии нет — вход через single-user mode или livecd
# В single-user mode пароль root не требуется

# Проверка целостности после восстановления
sudo pwck  # Проверка /etc/passwd
sudo grpck  # Проверка /etc/group
sudo getent passwd
```

**Best practices:**
- Регулярное резервное копирование `/etc/passwd`, `/etc/shadow`, `/etc/group`, `/etc/gshadow`.
- Хранение резервных копий в версионном контроль (Git) или на отдельном носителе.
- Тестирование восстановления раз в квартал.

## Типичные ошибки и диагностика

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `useradd: UID 0 already exists` | Дублирование UID 0 | `awk -F: '$3 == 0 {print $1}' /etc/passwd` → удалите лишнего |
| `passwd: Authentication token manipulation error` | Неверные права на `/etc/shadow` | `sudo chmod 600 /etc/shadow`; проверка FS на errors |
| `sudo: unknown user` | Пользователь не существует | `getent passwd username`; проверка NSS/SSSD |
| `su: Authentication failure` | Пользователь заблокирован или пароль истек | `sudo passwd -S username`; проверка `chage -l` |
| `Permission denied (publickey)` | Неверные права на `.ssh` | `chmod 700 ~/.ssh`; `chmod 600 ~/.ssh/authorized_keys`; SELinux context |
| `PAM: Account has expired` | `sp_expire` в `/etc/shadow` истек | `sudo usermod -e "" username` или `chage -E -1` |
| `cannot create home directory` | `/etc/skel` поврежден или нет прав | Проверка `sudo useradd -D`; права на `/etc/skel` |

## Дополнительная информация

### Тренды 2025–2026: Passwordless и Аппаратная защита
- **FIDO2 / Passkeys:** Использование аппаратных токенов (YubiKey) и биометрии для входа и `sudo` вместо паролей.
- **Интеграция с TPM2:** Автоматическая разблокировка домашних директорий и SSH-ключей только при условии успешной проверки **Secure Boot**.
- **Иммутабельность:** Переход к декларативному описанию пользователей в конфигурации ОС, где `/etc/passwd` генерируется динамически при сборке системы.

### Управление сервисными аккаунтами
- **Принцип:** Каждый сервис = отдельный аккаунт с уникальным UID/GID.
- **Валидация:** Периодический скрипт, проверяющий, что все сервисные аккаунты имеют `/usr/sbin/nologin` и не входят в группы с человеческими пользователями.
- **Автоматизация:** Использование `systemd-sysusers` в Docker-образах и immutable OS.

### Безопасность и делегирование
- **Принцип наименьших привилегий:** Использование `sudo` с ограниченными командами вместо полного доступа root. Подробнее: **[Управление привилегиями](privilege_management.md)**.
- **Централизация:** Для инфраструктур от 10 серверов обязательна интеграция с централизованным каталогом (FreeIPA/Active Directory) через SSSD.
- **Мониторинг сессий:** В high-security средах рекомендуется включить запись сессий через `tlog` или `script` для аудита действий администраторов.

### Смежные темы
- **[Определения пользователей и групп](Users/users_definitions.md)** — глубокий разбор UID/GID и типов ID (Real, Effective, Saved).
- **[Команды управления пользователями](Users/user_commands.md)** — детальный разбор `useradd`, `usermod`, `passwd`.
- **[Управление группами](Users/group_commands.md)** — команды `groupadd`, `gpasswd` и UPG.
- **[Мониторинг пользователей и сессий](Users/user_monitoring.md)** — `last`, `loginctl`, `utmp`.
- **[Политики паролей (chage)](Users/password_policy_chage.md)** — управление сроком действия паролей.
- **[Хэширование паролей](Users/password_hashing.md)** — алгоритмы Yescrypt, Argon2.
- **[Файлы конфигурации](Users/users_config_files.md)** — структура `/etc/passwd` и `/etc/shadow`.
- **[Миграция пользователей](Users/user_migration.md)** — как перенести аккаунты между серверами с сохранением прав.
- **[Приватные группы (UPG)](Users/user_private_groups.md)** — архитектура парадигмы User=Group.
- **[PAM (Pluggable Authentication Modules)](../Security/pam_overview.md)** — модульная аутентификация.
- **[Аудит через auditd](Logging/auditd.md)** — отслеживание изменений в конфигурациях.
- **[Управление привилегиями](privilege_management.md)** — `sudo`, `su`, Polkit.
- **[Права доступа к файлам](../Security/Concepts/File_Permissions/overview_definitions.md)** — связь UID/GID с моделью `rwx` и ACL.
- **[LDAP/SSSD](Users/LDAP_SSSD/index.md)** — централизованное управление пользователями.
- **[systemd-homed](Users/systemd-homed.md)** — портативные домашние директории.
- **[systemd-sysusers](Users/systemd-sysusers.md)** — автоматическое создание системных пользователей.
- **[Файловые дескрипторы](../FileSystems/file_descriptors.md)** — лимиты nofile и архитектура FD.
- **[Базовый чеклист производительности](performance_baseline.md)** — limits.conf и sysctl для серверов.
