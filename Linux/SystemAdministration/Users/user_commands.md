# Управление пользователями

## Определения

- **`useradd`** — низкоуровневая утилита для создания пользователей, удобна для скриптов
- **`adduser`** — интерактивная обертка над `useradd`, более дружелюбна для пользователя
- **`usermod`** — модификация параметров существующего пользователя
- **`userdel`** — удаление учетной записи пользователя

## Базовые концепции

### Настройки по умолчанию

Параметры для `useradd` задаются в файлах:

- `/etc/default/useradd` — параметры создания (домашняя директория, shell по умолчанию)
- `/etc/login.defs` — политики паролей, диапазоны UID/GID

```bash
# Просмотр настроек по умолчанию
useradd -D

# Пример вывода:
# GROUP=100
# HOME=/home
# INACTIVE=-1
# EXPIRE=
# SHELL=/bin/bash
# SKEL=/etc/skel
```

## Практические сценарии

### Создание пользователей

```bash
# Интерактивное создание (Debian/Ubuntu)
sudo adduser test-user

# Создание с базовыми параметрами
sudo useradd test-user

# Создание с домашней директорией и shell
sudo useradd -m -d /home/test-user -s /bin/bash test-user

# Создание с комментарием (GECOS)
sudo useradd -m -c "Иван Иванов" test-user

# Создание с указанием первичной группы
sudo useradd -m -g test-group test-user

# Создание с дополнительными группами
sudo useradd -m -G wheel,sudo test-user

# Создание системного пользователя (без домашней директории и права входа)
# -r — системный, -s — установка shell (nologin запрещает вход)
sudo useradd -r -s /usr/sbin/nologin app-user

# Создание с конкретным UID
sudo useradd -m -u 1500 test-user

# Создание с датой истечения срока действия
sudo useradd -m -e 2026-12-31 test-user

# Создание с блокировкой по истечении пароля (через 3 дня)
sudo useradd -m -f 3 test-user
```

> **Важно:** Ключ `-m` обязателен для создания домашней директории. Без него пользователь будет создан, но не сможет войти в систему.

### Установка пароля

```bash
# Установка пароля интерактивно
sudo passwd test-user

# Установка пустого пароля (не рекомендуется!)
sudo passwd -d test-user

# Блокировка пароля (запрет входа по паролю)
sudo passwd -l test-user

# Разблокировка пароля
sudo passwd -u test-user

# Принудительная смена пароля при следующем входе
sudo passwd --expire test-user
```

> **Примечание:** Для полноценного управления сроком действия паролей используйте [`chage`](./password_policy_chage.md).

### Изменение пользователей

```bash
# Проверка активности пользователя перед изменениями
pgrep -l -u username
pinky username
who | grep username

# Изменение имени пользователя
sudo usermod -l new-name old-name

# Изменение домашней директории с переносом файлов
sudo usermod -d /home/new-dir -m username

# Изменение комментария (GECOS)
sudo usermod -c "Новый Комментарий" username

# Добавление в дополнительную группу (сохраняя текущие группы!)
sudo usermod -aG wheel username

# ⚠️ Без ключа -a пользователь будет удален из всех остальных доп. групп!
sudo usermod -G wheel username

# Изменение первичной группы
sudo usermod -g new_group username

# Изменение shell
sudo usermod -s /bin/bash username

# Блокировка учетной записи
sudo usermod -L username

# Разблокировка учетной записи
sudo usermod -U username

# Отключение входа (установка nologin)
sudo usermod -s /usr/sbin/nologin username

# Изменение UID
sudo usermod -u 1501 username

# Изменение даты истечения срока
sudo usermod -e 2027-01-01 username
```

### Удаление пользователей

```bash
# Удаление с домашней директорией и почтовым ящиком
sudo userdel -r username

# Удаление без домашней директории
sudo userdel username

# Принудительное удаление (если пользователь активен)
# Внимание: Использовать с осторожностью!
sudo userdel -f username
```

### Дублирование root (создание пользователя с UID 0)

В Linux права определяются UID. У root всегда UID=0. Если создать пользователя с тем же UID, система будет воспринимать его как root.

#### Метод 1: Использование useradd

Команда `useradd` по умолчанию запрещает дублирование UID, но это можно обойти флагам `-o`.

```bash
# Создание пользователя superadmin с UID 0
sudo useradd -o -u 0 -g 0 -d /root -s /bin/bash superadmin

# Установка пароля
sudo passwd superadmin
```

#### Метод 2: Прямое редактирование /etc/passwd

```bash
# Открытие файла через безопасную утилиту
sudo vipw

# Добавление строки в конец файла:
# superadmin:x:0:0:Super Admin:/root:/bin/bash
```

#### Настройка sudo и проверка

Если вы используете `sudo`, добавьте нового пользователя в `/etc/sudoers` через `visudo`:
`superadmin ALL=(ALL:ALL) ALL`

```bash
# Проверка идентификатора
id superadmin
# uid=0(root) gid=0(root) groups=0(root)
```

> **Важно:** Два аккаунта с UID 0
 удваивают поверхность атаки. Используйте этот подход только для специфических задач (аварийный доступ, раздельная автоматизация) и обеспечьте аудит действий через [auditd](../Logging/auditd.md).

## Лучшие практики

### Безопасность при создании

1. **Всегда создавайте домашнюю директорию:** `useradd -m`
2. **Указывайте shell явно:** `-s /bin/bash` или `-s /usr/sbin/nologin` для сервисов
3. **Используйте надежные пароли:** Минимум 12 символов, разные типы символов
4. **Принцип наименьших привилегий:** Не добавляйте в `wheel`/`sudo` без необходимости
5. **Системные пользователи:** Используйте `-r` для сервисных аккаунтов

### Проверка перед удалением

```bash
# Проверить процессы пользователя
ps -u username

# Проверить активные сессии
who | grep username
loginctl list-sessions | grep username

# Проверить cron-задания
crontab -u username -l

# Проверить файлы пользователя
find / -user username 2>/dev/null | head -20
```

### Автоматизация

```bash
# Скрипт создания пользователя с проверкой
#!/bin/bash
USERNAME=$1
if id "$USERNAME" &>/dev/null; then
    echo "Пользователь существует"
    exit 1
fi
sudo useradd -m -s /bin/bash -c "Created on $(date)" "$USERNAME"
sudo passwd "$USERNAME"
```

## Дополнительная информация

### Распространенные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `useradd: группа не существует` | Указана несуществующая группа `-g` | Создайте группу или используйте `-G` |
| `useradd: UID уже существует` | UID занят другим пользователем | Используйте другой UID или `-u` |
| Пользователь не может войти | Нет домашней директории | Используйте `-m` при создании |
| Пользователь удален из групп | `usermod -G` без `-a` | Используйте `usermod -aG` |
| Конфликт UID | Одинаковые UID на системах | Проверьте перед миграцией |
| Не работает sudo | Нет в группе wheel/sudo | `usermod -aG wheel username` |

Смежные темы: [управление группами](./group_commands.md), [политики паролей](./password_policy_chage.md), [мониторинг пользователей](./user_monitoring.md), [файлы конфигурации](./users_config_files.md), [управление привилегиями](../privilege_management.md).
ge_management.md).
