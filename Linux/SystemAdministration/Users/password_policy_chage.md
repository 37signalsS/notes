# Управление политиками паролей (`chage`)

## Определения

- **`chage`** (change age) — утилита для управления сроком действия паролей и учётных записей
- **Срок действия пароля** — период, через который пароль должен быть сменён
- **Период неактивности** — время после истечения пароля, после которого учётная запись блокируется

## Базовые концепции

### Параметры политик

| Параметр | Описание | Единица |
| :--- | :--- | :--- |
| **Last password change** | Дата последней смены пароля | Дни с 01.01.1970 |
| **Minimum** | Мин. срок между сменами пароля | Дни |
| **Maximum** | Макс. срок действия пароля | Дни |
| **Warning** | Период предупреждения до истечения | Дни |
| **Inactive** | Период неактивности до блокировки | Дни |
| **Account expires** | Дата истечения учётной записи | Дата |

## Практические сценарии

### Просмотр текущих политик

```bash
# Подробная информация о пользователе
sudo chage -l username

# Пример вывода:
# Last password change					: Jan 01, 2026
# Password expires					: Apr 01, 2026
# Password inactive					: (never)
# Account expires						: (never)
# Minimum number of days between password change	: 0
# Maximum number of days between password change	: 90
# Number of days of warning before password expires	: 7
```

### Установка политик

```bash
# Максимальный срок действия пароля (90 дней)
sudo chage -M 90 username

# Минимальный срок между сменами (14 дней)
sudo chage -m 14 username

# Предупреждение за 7 дней до истечения
sudo chage -W 7 username

# Период неактивности до блокировки (30 дней)
sudo chage -I 30 username

# Дата истечения учётной записи
sudo chage -E 2026-12-31 username

# Сделать учётную запись бессрочной
sudo chage -E -1 username

# Комбинированная установка всех параметров
sudo chage -m 7 -M 90 -W 7 -I 30 -E 2026-12-31 username
```

### Принудительная смена пароля

```bash
# Сброс счётчика дней (пароль нужно сменить при следующем входе)
sudo chage -d 0 username

# Установка даты последней смены (например, сегодня)
sudo chage -d $(date +%Y-%m-%d) username
```

### Сценарии использования

#### Сценарий 1: Стандартная корпоративная политика

```bash
# Для всех пользователей
for user in $(awk -F: '$3 >= 1000 {print $1}' /etc/passwd); do
    sudo chage -m 7 -M 90 -W 7 -I 30 "$user"
done
```

#### Сценарий 2: Временная учётная запись

```bash
# Создание временного пользователя (действует до конца года)
sudo useradd -m tempuser
sudo chage -E 2026-12-31 tempuser
sudo chage -M 30 tempuser  # Смена пароля каждые 30 дней
```

#### Сценарий 3: Сервисная учётная запись

```bash
# Для сервисных аккаунтов (пароль не истекает)
sudo chage -M -1 service-account
sudo chage -E -1 service-account
```

#### Сценарий 4: Блокировка по истечении

```bash
# Если пользователь не сменил пароль за 90 дней — блокировка
sudo chage -M 90 -I 0 username
```

## Лучшие практики

### Рекомендуемые политики

| Тип пользователя | Min дней | Max дней | Warning | Inactive |
| :--- | :--- | :--- | :--- | :--- |
| **Обычные пользователи** | 7 | 90 | 7 | 30 |
| **Привилегированные** | 7 | 60 | 14 | 14 |
| **Сервисные аккаунты** | 0 | -1 | 0 | -1 |
| **Временные** | 0 | 30 | 7 | 7 |

### Глобальная настройка политик

```bash
# /etc/login.defs
PASS_MAX_DAYS   90
PASS_MIN_DAYS   7
PASS_WARN_AGE   7

# После изменения файла применить к существующим пользователям:
for user in $(awk -F: '$3 >= 1000 {print $1}' /etc/passwd); do
    sudo chage -M 90 -m 7 -W 7 "$user"
done
```

### Аудит политик

```bash
# Пользователи с бессрочным паролем
sudo chage -l $(whoami) | grep -E "Maximum|expires"

# Все пользователи с истекающим паролем
for user in $(awk -F: '$3 >= 1000 {print $1}' /etc/passwd); do
    echo "=== $user ==="
    sudo chage -l "$user" | grep -E "expires|Maximum"
done

# Пользователи, у которых пароль истёк
sudo awk -F: '($5 != 99999 && $5 != -1) {print $1}' /etc/shadow

# Проверка конкретной даты истечения
sudo chage -l username | grep "Account expires"
```

### Автоматизация

```bash
# Скрипт проверки即将 истекающих паролей
#!/bin/bash
WARNING_DAYS=14

for user in $(awk -F: '$3 >= 1000 {print $1}' /etc/passwd); do
    expire_date=$(sudo chage -l "$user" | grep "Password expires" | cut -d: -f2)
    if [[ "$expire_date" != " never" ]]; then
        expire_epoch=$(date -d "$expire_date" +%s)
        now_epoch=$(date +%s)
        days_left=$(( (expire_epoch - now_epoch) / 86400 ))
        if [[ $days_left -le $WARNING_DAYS ]]; then
            echo "WARNING: Password for $user expires in $days_left days"
        fi
    fi
done
```

## Дополнительная информация

### Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `chage: пользователь не существует` | Неверное имя пользователя | Проверьте имя через `id username` |
| `chage: требуется привилегия` | Нет прав root | Используйте `sudo` |
| Политики не применяются | Пользователь уже вошёл | Пользователь должен перелогиниться |

### Взаимодействие с PAM

PAM-модуль `pam_unix.so` использует параметры из `/etc/shadow`, установленные через `chage`.

```bash
# /etc/pam.d/common-password (Debian/Ubuntu)
password [success=1 default=ignore] pam_unix.so obscure sha512

# Для применения политик сложности
password requisite pam_pwquality.so retry=3 minlen=12
```

### Связанные темы

- [Хэширование паролей](./password_hashing.md) — алгоритмы хэширования
- [Файлы конфигурации](./users_config_files.md) — `/etc/shadow`, `/etc/login.defs`
- [Управление пользователями](./user_commands.md) — `passwd`, `usermod`
- [PAM](../../Security/pam_overview.md) — модули аутентификации
