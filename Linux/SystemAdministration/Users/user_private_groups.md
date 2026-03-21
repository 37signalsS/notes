# Приватные группы пользователей (UPG)

## Определения

- **UPG** (User Private Group) — схема именования групп, где для каждого пользователя создаётся группа с тем же именем
- **Первичная группа** — группа, указанная в `/etc/passwd` как основная для пользователя
- **USERGROUPS=yes** — настройка в `/etc/login.defs`, включающая автоматическое создание приватной группы

## Базовые концепции

### Как работает UPG

При создании пользователя без указания группы:

1. Автоматически создаётся группа с именем пользователя
2. Эта группа становится первичной для пользователя
3. GID группы обычно равен UID пользователя

**Пример:**

```bash
# Создание пользователя
sudo useradd alice

# Автоматически создано:
# Пользователь: alice (UID 1001)
# Группа: alice (GID 1001)
# Первичная группа alice для пользователя alice
```

### Проверка UPG

```bash
# Проверка настройки в login.defs
grep USERGROUPS /etc/login.defs
# USERGROUPS=yes — UPG включено

# Проверка пользователя и группы
id alice
# uid=1001(alice) gid=1001(alice) groups=1001(alice)

# Проверка в файлах
grep alice /etc/passwd
# alice:x:1001:1001::/home/alice:/bin/bash

grep alice /etc/group
# alice:x:1001:
```

## Практические сценарии

### Отключение UPG

```bash
# Временное отключение при создании
sudo useradd -N username  # -N = --no-user-group

# Глобальное отключение
# /etc/login.defs
USERGROUPS no

# Создание пользователя с общей группой
sudo groupadd users
sudo useradd -g users username
```

### UPG и общие директории

**Проблема:** Файлы создаются с первичной группой пользователя, что затрудняет совместный доступ.

**Решение 1: SGID на директории**

```bash
# Создание общей директории
sudo mkdir /shared/project
sudo groupadd project

# Установка SGID бита
sudo chown root:project /shared/project
sudo chmod 2775 /shared/project

# Добавление пользователей в группу
sudo usermod -aG project alice
sudo usermod -aG project bob

# Теперь все файлы в /shared/project будут с группой project
```

**Решение 2: Смена первичной группы**

```bash
# Смена первичной группы пользователя
sudo usermod -g project alice

# Проверка
id alice
# uid=1001(alice) gid=1002(project) groups=1002(project),1001(alice)
```

### UPG в скриптах

```bash
#!/bin/bash
# create_user_upg.sh - создание пользователя с UPG

USERNAME=$1
COMMENT=$2

if [[ -z "$USERNAME" ]]; then
    echo "Использование: $0 <username> [comment]"
    exit 1
fi

# Создание с UPG (по умолчанию)
sudo useradd -m -c "$COMMENT" "$USERNAME"

# Проверка
if id "$USERNAME" &>/dev/null; then
    echo "Пользователь $USERNAME создан"
    echo "UID/GID: $(id -u $USERNAME)/$(id -g $USERNAME)"
    echo "Группы: $(groups $USERNAME)"
else
    echo "Ошибка создания"
    exit 1
fi
```

### Миграция с UPG на общую группу

```bash
#!/bin/bash
# migrate_from_upg.sh - миграция пользователей на общую группу

COMMON_GROUP="$1"
shift
USERS="$@"

if [[ -z "$COMMON_GROUP" ]]; then
    echo "Использование: $0 <common_group> <user1> [user2](.."
    exit 1
fi

# Создание общей группы если не существует
if ! getent group "$COMMON_GROUP" &>/dev/null; then
    sudo groupadd "$COMMON_GROUP"
fi

# Миграция пользователей
for user in $USERS; do
    # Смена первичной группы
    sudo usermod -g "$COMMON_GROUP" "$user"
    
    # Добавление в группу (для доступа к файлам)
    sudo usermod -aG "$COMMON_GROUP" "$user"
    
    echo "Пользователь $user мигрирован на группу $COMMON_GROUP"
done

# Исправление прав на файлы
for user in $USERS; do
    home_dir=$(getent passwd "$user" | cut -d: -f6)
    sudo chown -R "$user:$COMMON_GROUP" "$home_dir"
done
```

## Лучшие практики

### Когда использовать UPG

| Сценарий | Рекомендация |
| :--- | :--- |
| **Персональные рабочие станции** | ✅ UPG подходит |
| **Многопользовательские серверы** | ⚠️ Рассмотрите общие группы |
| **Совместная работа над файлами** | ❌ Используйте SGID + общие группы |
| **Изолированные сервисы** | ✅ UPG подходит |

### Безопасность

1. **Проверка членства в группах:**

   ```bash
   # Все пользователи и их первичные группы
   awk -F: '{print $1, $4}' /etc/passwd | while read user gid; do
       group=$(getent group "$gid" | cut -d: -f1)
       echo "$user: primary group = $group"
   done
   ```

2. **Поиск пользователей без приватной группы:**

   ```bash
   # Пользователи с первичной группой не равной имени
   awk -F: '$1 != $4 {print $1}' /etc/passwd
   ```

3. **Аудит общих групп:**

   ```bash
   # Группы с несколькими участниками
   awk -F: 'NF==4 && $4!="" {n=split($4,a,","); if(n>1) print $1, n, $4}' /etc/group
   ```

### _umask_ и UPG

При UPG рекомендуется umask 002 для возможности совместной работы:

```bash
# /etc/profile или ~/.bashrc
umask 002  # Файлы: 664, Директории: 775

# Глобальная настройка
# /etc/login.defs
USERGROUPS_MOD 002
USERGROUPS_CHMOD 002
```

## Дополнительная информация

### Распространённые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Файлы не доступны группе | UPG создаёт файлы с личной группой | Используйте SGID на директории |
| Конфликты при совместной работе | Разные первичные группы | Смените первичную группу на общую |
| Скрипты не работают | Ожидается UPG, но отключено | Проверьте USERGROUPS в login.defs |

### Связанные темы

- [Определения](./users_definitions.md) — базовые понятия
- [Управление группами](./group_commands.md) — `groupadd`, `usermod`
- [Управление пользователями](./user_commands.md) — `useradd`
- [Права доступа](../../Security/Concepts/File_Permissions/special_permissions.md) — SGID бит
- [Файлы конфигурации](./users_config_files.md) — `/etc/login.defs`
