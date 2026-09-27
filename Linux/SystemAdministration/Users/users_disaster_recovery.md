# Disaster Recovery для пользователей и групп

## Определения

- **Disaster Recovery (Восстановление после сбоев)** — комплекс мер по восстановлению работоспособности системы после аварийных ситуаций (аппаратные сбои, ошибки администраторов, компрометация данных).
- **Backup конфигурационных файлов** — регулярное копирование критических файлов (`/etc/passwd`, `/etc/shadow`, `/etc/group`, `/etc/gshadow`) для возможности восстановления.
- **Recovery Mode (Режим восстановления)** — специальный режим загрузки ОС, позволяющий исправить критические ошибки конфигурации (битые пароли, некорректные UID/GID).
- **Break-glass (Аварийный доступ)** — процедура предоставления временных привилегий в аварийных ситуациях с обязательным последующим аудитом.
- **Forensic Image (Криминалистический образ)** — побайтовая копия диска или раздела для последующего анализа инцидентов.
- **Point-in-time Recovery (Восстановление на момент времени)** — возможность восстановить состояние системы на конкретный момент времени из резервных копий.
- **Golden Image (Эталонный образ)** — воспроизводимый образ ОС или контейнера, содержащий предопределенный набор пользователей и групп.

## Базовые концепции

### Критические файлы для восстановления

| Файл | Назначение | Приоритет |
| :--- | :--- | :--- |
| `/etc/passwd` | Учетные записи пользователей (UID, GID, home, shell) | Критический |
| `/etc/shadow` | Пароли и политики паролей (хэши, сроки действия) | Критический |
| `/etc/group` | Группы и их членство | Критический |
| `/etc/gshadow` | Пароли групп (если используются) | Высокий |
| `/etc/login.defs` | Глобальные политики (диапазоны UID, алгоритмы хэширования) | Высокий |
| `/etc/nsswitch.conf` | Источники данных NSS (LDAP, SSSD) | Средний |
| `/etc/sudoers` и `/etc/sudoers.d/*` | Правила делегирования привилегий | Средний |
| `/etc/pam.d/*` | Конфигурация PAM (аутентификация, авторизация) | Средний |
| `/etc/subuid` и `/etc/subgid` | Диапазоны для User Namespaces (контейнеры) | Низкий |

### Типы аварийных ситуаций

| Тип сбоя | Симптомы | Приоритет восстановления |
| :--- | :--- | :--- |
| **Повреждение /etc/passwd** | Невозможность входа, `id` не находит пользователя, UID/GID не отображаются | Критический |
| **Потеря /etc/shadow** | Невозможность аутентификации, пароли не работают | Критический |
| **Битые UID/GID** | Конфликты имен, некорректные права доступа к файлам | Высокий |
| **Некорректный /etc/nsswitch.conf** | Пользователи LDAP/SSSD не видны,缓慢 NSS-запросы | Средний |
| **Блокировка PAM** | Невозможность входа, бесконечный цикл аутентификации | Высокий |
| **Компрометация root** | Необходимость сброса пароля, ротация ключей, аудит | Критический |

## Практические сценарии

### 1. Резервное копирование

#### Автоматический backup через cron

```bash
# /etc/cron.daily/backup-users
#!/bin/bash
BACKUP_DIR="/var/backups/users"
DATE=$(date +%F_%H-%M)
mkdir -p "$BACKUP_DIR"

# Бэкап критических файлов
for FILE in /etc/passwd /etc/shadow /etc/group /etc/gshadow /etc/login.defs /etc/nsswitch.conf; do
    if [ -f "$FILE" ]; then
        cp "$FILE" "$BACKUP_DIR/$(basename $FILE).$DATE"
    fi
done

# Бэкап sudoers.d
cp -r /etc/sudoers.d "$BACKUP_DIR/sudoers.d.$DATE" 2>/dev/null

# Бэкап PAM конфигурации
cp -r /etc/pam.d "$BACKUP_DIR/pam.d.$DATE" 2>/dev/null

# Бэкап subuid/subgid
cp /etc/subuid /etc/subgid "$BACKUP_DIR/" 2>/dev/null

# Удаление старых бэкапов (старше 30 дней)
find "$BACKUP_DIR" -type f -mtime +30 -delete

echo "Backup completed: $DATE" >> /var/log/user-backup.log
```

#### Бэкап через Ansible

```yaml
- name: Backup user configuration files
  hosts: all
  become: yes
  tasks:
    - name: Create backup directory
      ansible.builtin.file:
        path: "/var/backups/users/{{ ansible_date_time.date }}"
        state: directory
        mode: '0700'

    - name: Backup critical user files
      ansible.builtin.copy:
        src: "{{ item }}"
        dest: "/var/backups/users/{{ ansible_date_time.date }}/{{ item | basename }}"
        remote_src: yes
      loop:
        - /etc/passwd
        - /etc/shadow
        - /etc/group
        - /etc/gshadow
        - /etc/login.defs
        - /etc/nsswitch.conf

    - name: Backup sudoers.d directory
      ansible.builtin.copy:
        src: /etc/sudoers.d
        dest: "/var/backups/users/{{ ansible_date_time.date }}/sudoers.d"
        remote_src: yes

    - name: Backup PAM configuration
      ansible.builtin.copy:
        src: /etc/pam.d
        dest: "/var/backups/users/{{ ansible_date_time.date }}/pam.d"
        remote_src: yes

    - name: Backup subuid/subgid
      ansible.builtin.copy:
        src: "{{ item }}"
        dest: "/var/backups/users/{{ ansible_date_time.date }}/{{ item | basename }}"
        remote_src: yes
      loop:
        - /etc/subuid
        - /etc/subgid
```

### 2. Восстановление поврежденного /etc/passwd

#### Вариант 1: Восстановление из бэкапа (Live CD/USB)

```bash
# 1. Загрузиться с Live CD/USB
# 2. Смонтировать раздел с корнем системы
mount /dev/sda1 /mnt

# 3. Восстановить файл
cp /mnt/var/backups/users/passwd.2024-01-15 /mnt/etc/passwd

# 4. Проверить целостность
chroot /mnt /usr/sbin/pwck

# 5. Восстановить shadow (если поврежден)
cp /mnt/var/backups/users/shadow.2024-01-15 /mnt/etc/shadow
chroot /mnt /usr/sbin/pwck -s
```

#### Вариант 2: Экстренное восстановление через single-user mode

```bash
# 1. При загрузке в GRUB добавить в строку ядра:
#    init=/bin/bash

# 2. Смонтировать корень в read-write режим
mount -o remount,rw /

# 3. Восстановить из бэкапа
cp /var/backups/users/passwd.2024-01-15 /etc/passwd

# 4. Перезагрузка
reboot -f
```

#### Вариант 3: Ручное восстановление (если нет бэкапа)

```bash
# Если /etc/passwd полностью утерян, восстановить минимально необходимые записи:

# Root
echo "root:x:0:0:root:/root:/bin/bash" >> /etc/passwd

# Текущий пользователь (найти через mounting и ls -la /home)
echo "admin:x:1000:1000:Admin:/home/admin:/bin/bash" >> /etc/passwd

# Системные учетные записи (восстановить из памяти или документации)
echo "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin" >> /etc/passwd
```

### 3. Восстановление заблокированного root

#### Сброс пароля root через GRUB

```bash
# 1. При загрузке в GRUB нажать 'e' для редактирования
# 2. Найти строку с Linux и добавить:
#    init=/bin/bash

# 3. Смонтировать корень:
mount -o remount,rw /

# 4. Сбросить пароль root:
passwd root

# 5. Восстановить SELinux контекст (если используется)
restorecon -R /etc/shadow

# 6. Перезагрузка
reboot -f
```

#### Восстановление через livecd

```bash
# 1. Загрузиться с Live CD/USB
# 2. Смонтировать раздел
mount /dev/sda1 /mnt

# 3. Сбросить пароль root
chroot /mnt passwd root

# 4. Восстановить SELinux контекст
chroot /mnt restorecon -R /etc/shadow

# 5. Перезагрузка
reboot
```

### 4. Восстановление после компрометации root

```bash
# 1. Немедленная изоляция системы
#    - Отключить от сети (если возможно)
#    - Заблокировать SSH-доступ

# 2. Аудит изменений
#    - Проверить /etc/passwd на наличие подозрительных записей
awk -F: '$3 == 0 {print "UID 0 accounts:", $1}' /etc/passwd
awk -F: '$3 >= 1000 && $3 < 65534 {print "Regular users:", $1}' /etc/passwd

# 3. Проверка SSH-ключей
find / -name "authorized_keys" -type f 2>/dev/null
cat /root/.ssh/authorized_keys  # Проверить на подозрительные ключи

# 4. Ротация паролей
passwd root
for user in $(awk -F: '$3 >= 1000 && $3 < 65534 {print $1}' /etc/passwd); do
    passwd "$user"
done

# 5. Ротация SSH-ключей
ssh-keygen -t ed25519 -C "post-incident-$(date +%F)"

# 6. Проверка cron
crontab -l
ls -la /etc/cron.d/
cat /var/spool/cron/* 2>/dev/null

# 7. Проверка systemd сервисов
systemctl list-unit-files --state=enabled
systemctl list-timers

# 8. Аудит файлов с SUID/SGID битами
find / -perm -4000 -type f 2>/dev/null
find / -perm -2000 -type f 2>/dev/null
```

### 5. Восстановление UID/GID конфликтов

```bash
# Проблема: Два пользователя с одинаковым UID
# Симптомы: Невозможность отличить файлы, некорректная работаchmod

# 1. Найти конфликтные UID
awk -F: '{print $3, $1}' /etc/passwd | sort -n | uniq -d -f0

# 2. Временно исправить (если есть доступ)
usermod -u 1001 conflicting_user

# 3. Исправить права доступа к файлам
find / -uid <старый_UID> -exec chown <новый_пользователь>:{} \;

# 4. Проверить и исправить группу
find / -gid <старый_GID> -exec chgrp <новая_группа>:{} \;
```

### 6. Восстановление после некорректного PAM

```bash
# Проблема: Невозможность входа из-за ошибки в PAM
# Решение: Восстановить PAM конфигурацию

# 1. Загрузиться в single-user mode
# 2. Восстановить из бэкапа
cp /var/backups/users/pam.d.2024-01-15/* /etc/pam.d/

# 3. Или восстановить минимально необходимые файлы
cat > /etc/pam.d/login << 'EOF'
auth       required     pam_securetty.so
auth       include      system-login
account    include      system-login
password   include      system-login
session    include      system-login
EOF

# 4. Проверить целостность
pam_tally2 --user=root --reset
```

## Дополнительная информация

### Ссылки на смежные темы

- **[Файлы конфигурации пользователей](./users_config_files.md)** — структура `/etc/passwd`, `/etc/shadow`, `/etc/group`.
- **[Команды управления пользователями](./user_commands.md)** — императивный подход к управлению.
- **[Миграция пользователей](./user_migration.md)** — перенос учетных записей между системами.
- **[Управление привилегиями](../../SystemAdministration/privilege_management.md)** — sudo, su, Polkit.
- **[Обзор PAM](../../Security/pam_overview.md)** — модульный фреймворк аутентификации.

### Рекомендации по disaster recovery

1. **Регулярное тестирование:** Периодически проверяйте восстановление из бэкапов в изолированной среде (VM, контейнер).
2. **Версионирование:** Используйте Git или другой VCS для хранения конфигурационных файлов.
3. **Автоматизация:** Настройте автоматическое создание бэкапов через cron или systemd timers.
4. **Документирование:** Фиксируйте процедуры восстановления в runbooks.
5. **Мониторинг:** Настраивайте алерты на изменения критических файлов (auditd, AIDE).
6. **Golden Image:** Для критических систем используйте воспроизводимые образы с предопределенным набором пользователей.

### Инструменты для мониторинга изменений

```bash
# AIDE (Advanced Intrusion Detection Environment)
aide --init
aide --check

# Tripwire
tripwire --init
tripwire --check

#auditd правила для мониторинга
auditctl -w /etc/passwd -p wa -k user_changes
auditctl -w /etc/shadow -p wa -k password_changes
auditctl -w /etc/group -p wa -k group_changes
```
