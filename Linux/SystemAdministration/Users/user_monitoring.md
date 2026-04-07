# Мониторинг пользователей и сессий

## Определения

- **Сессия** — период активности пользователя в системе (локально или удалённо)
- **Вход в систему** — процесс аутентификации и начала сессии
- **Логин** — запись о входе пользователя в системных журналах

## Базовые концепции

### Типы информации о пользователях

| Тип | Описание | Команды |
| :--- | :--- | :--- |
| **Идентификаторы** | UID, GID, группы | `id`, `groups` |
| **Активные сессии** | Кто сейчас в системе | `who`, `w`, `users` |
| **История входов** | Журнал последних входов | `last`, `lastb` |
| **Процессы** | Запущенные процессы | `ps`, `pgrep`, `top` |
| **Файлы** | Принадлежащие файлы | `find`, `lsof` |

## Практические сценарии

### Проверка идентификаторов

```bash
# UID, GID и все группы пользователя
id username

# Только UID
id -u username

# Только GID (первичная группа)
id -g username

# Только имя группы
id -gn username

# Все группы (имена)
id -Gn username

# Все группы (GID)
id -G username

# Группы конкретного пользователя
groups username
```

### Активные сессии

```bash
# Кто сейчас в системе (кратко)
who

# Подробная информация (время, IP, чем занят)
w

# Только имена пользователей
users

# Все сессии с деталями
who -a

# Сессии конкретного пользователя
who | grep username
w username

# Сессии с терминалами
who -T  # + показывает статус записи (-/+ означает can/cannot write)

# Сессии с хостами
who -H  # заголовки
who -u  # подробный вывод с временем бездействия
```

### История входов

```bash
# Последние входы в систему
last

# Последние входы конкретного пользователя
last username

# Последние входы на конкретный терминал
last pts/0

# Входы за определённое время
last -s 2026-01-01
last -s 2026-01-01 -t 2026-02-01

# Количество записей
last -n 20

# Неудачные попытки входа (требует root)
sudo lastb

# Входы с указанием IP
last -i

# Время сессий
last -F  # полное время и дата
last -x  # входы/выходы и runlevel
```

### Проверка процессов пользователя

```bash
# Все процессы пользователя
ps -u username

# Процессы в формате дерева
pstree -p username

# Поиск процессов по имени
pgrep -l -u username

# Подробная информация о процессах
ps aux | grep username

# Top процессы пользователя
top -u username

# В реальном времени (htop)
htop -u username

# Проверка запущенных демонов
systemctl --user list-units
```

### Проверка файлов пользователя

```bash
# Все файлы пользователя в home
find /home/username -type f

# Файлы по всему диску (требует времени)
sudo find / -user username 2>/dev/null

# Файлы, изменённые за последние 7 дней
find /home/username -type f -mtime -7

# Большие файлы (>100MB)
find /home/username -type f -size +100M -exec ls -lh {} \;

# Открытые файлы (требует lsof)
sudo lsof -u username

# Сетевые соединения
sudo lsof -i -u username
```

### Аудит действий пользователя

```bash
# История команд (если доступна)
cat /home/username/.bash_history

# Последние авторизации
sudo grep username /var/log/auth.log  # Debian/Ubuntu
sudo grep username /var/log/secure     # RHEL/CentOS

# Успешные входы
grep "Accepted" /var/log/auth.log | grep username

# Неудачные попытки
grep "Failed" /var/log/auth.log | grep username

# Использование sudo
grep "sudo:" /var/log/auth.log | grep username

# Systemd journal
journalctl _SYSTEMD_USER_UNIT=username
```

### Мониторинг в реальном времени

```bash
# Кто заходит в реальном времени
watch -n 1 'who'

# Мониторинг сессий
watch -n 1 'w'

# Новые входы (требует root)
sudo tail -f /var/log/auth.log

# Все действия пользователя (если настроен auditd)
sudo ausearch -i -ua username

# Сетевая активность
sudo iftop -u username
```

## Дополнительная информация

### Файлы логов

| Файл | Описание | Дистрибутив |
| :--- | :--- | :--- |
| `/var/log/auth.log` | Аутентификация | Debian/Ubuntu |
| `/var/log/secure` | Аутентификация | RHEL/CentOS |
| `/var/log/wtmp` | История входов | Все |
| `/var/log/btmp` | Неудачные входы | Все |
| `/var/log/lastlog` | Последние входы | Все |

### Лучшие практики

#### Безопасность

1. **Регулярно проверяйте активные сессии** — особенно привилегированных пользователей
2. **Мониторьте неудачные входы** — признак brute force атаки
3. **Аудит sudo** — все команды через sudo должны логироваться
4. **Проверяйте «зомби» сессии** — зависшие сессии могут быть признаком компрометации
5. **Настройте centralised logging** — для ретроспективного анализа инцидентов

#### Скрипт отчёта по пользователю

```bash
#!/bin/bash
# user_activity_report.sh - отчёт по активности пользователя

USERNAME="$1"

if [[ -z "$USERNAME" ]]; then
    echo "Использование: $0 <username>"
    exit 1
fi

echo "=== Отчёт по пользователю: $USERNAME ==="
echo

echo "--- Идентификаторы ---"
id "$USERNAME"
echo

echo "--- Активные сессии ---"
who | grep "$USERNAME" || echo "Нет активных сессий"
echo

echo "--- Последние входы ---"
last -n 5 "$USERNAME"
echo

echo "--- Процессы ---"
ps -u "$USERNAME" -o pid,ppid,cmd --no-headers || echo "Нет процессов"
echo

echo "--- Домашняя директория ---"
du -sh /home/"$USERNAME" 2>/dev/null || echo "Директория не найдена"
echo

echo "--- Последние файлы (изменённые за 7 дней) ---"
find /home/"$USERNAME" -type f -mtime -7 2>/dev/null | head -10
```

#### Скрипт оповещения о входе

```bash
#!/bin/bash
# alert_on_login.sh - оповещение о входе привилегированного пользователя

PRIVILEGED_USERS="root admin dbadmin"

for user in $PRIVILEGED_USERS; do
    if who | grep -q "^$user"; then
        echo "ALERT: User $user logged in at $(date)" | \
            mail -s "Login Alert: $user" admin@example.com
    fi
done
```

### Связанные темы

- [Управление пользователями](./user_commands.md) — `useradd`, `usermod`
- [Диагностика процессов](../../Diagnostics/Processes/w.md) — `ps`, `top`
- [PAM](../../../Linux/Security/pam_overview.md) — аутентификация
- [Аудит безопасности](../../../Security/audit_and_compliance_overview.md) — логирование
- [Аудит действий через auditd](../../Logging/auditd.md) — системный аудит
- [Управление loginctl-сессиями](../../../Linux/Core/systemd/logind_session_management.md) — `loginctl`
