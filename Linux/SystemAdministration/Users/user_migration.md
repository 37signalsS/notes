# Перенос пользователей между системами Linux

## Определения

- **Миграция пользователей** — процесс переноса учётных записей, домашних директорий и настроек между системами
- **UID/GID конфликт** — ситуация, когда один идентификатор принадлежит разным пользователям на разных системах

## Базовые концепции

### Типы миграции

| Тип | Описание | Сложность |
| :--- | :--- | :--- |
| **Ручная** | Пошаговый перенос файлов и записей | Низкая |
| **Автоматизированная** | Скрипты и утилиты | Средняя |
| **Централизованная** | LDAP/AD вместо локальных пользователей | Высокая |

### Риски

- **Конфликты UID/GID** — разные пользователи с одинаковыми ID
- **Потеря данных** — файлы могут остаться на старой системе
- **Нарушение прав** — права доступа могут сбиться при копировании
- **Блокировка входа** — ошибки в /etc/shadow могут заблокировать вход

## Практические сценарии

### Подготовка

#### Шаг 1: Аудит исходной системы

```bash
# Список всех пользователей с UID >= 1000
awk -F: '$3 >= 1000 {print $1, $3, $4}' /etc/passwd

# Список всех групп с GID >= 1000
awk -F: '$3 >= 1000 {print $1, $3}' /etc/group

# Проверка на дублирующиеся UID
cut -d: -f3 /etc/passwd | sort | uniq -d

# Проверка на дублирующиеся GID
cut -d: -f3 /etc/group | sort | uniq -d
```

#### Шаг 2: Резервное копирование на целевой системе

```bash
# Создание резервных копий файлов конфигурации
sudo cp /etc/passwd /etc/passwd.bak.$(date +%Y%m%d)
sudo cp /etc/shadow /etc/shadow.bak.$(date +%Y%m%d)
sudo cp /etc/group /etc/group.bak.$(date +%Y%m%d)
sudo cp /etc/gshadow /etc/gshadow.bak.$(date +%Y%m%d)

# Резервное копирование существующих домашних директорий
sudo tar -czvf /backup/home_backup_$(date +%Y%m%d).tar.gz /home/
```

### Метод 1: Ручной перенос (для нескольких пользователей)

#### Шаг 1: Экспорт данных с исходной системы

```bash
# Экспорт записей пользователей
sudo grep username /etc/passwd > user_passwd.txt
sudo grep username /etc/shadow > user_shadow.txt
sudo grep username /etc/group > user_group.txt

# Или для всех пользователей с UID >= 1000
sudo awk -F: '$3 >= 1000' /etc/passwd > all_users_passwd.txt
sudo awk -F: 'NR==FNR {a[$1]; next} $1 in a' \
    <(cut -d: -f1 /etc/passwd) /etc/shadow > all_users_shadow.txt
```

#### Шаг 2: Копирование домашних директорий

```bash
# Копирование с сохранением прав (rsync предпочтителен)
rsync -avz --progress /home/ user@newserver:/home/

# Или через tar для сохранения всех атрибутов
sudo tar -czf /tmp/home_backup.tar.gz /home/
scp /tmp/home_backup.tar.gz user@newserver:/tmp/
# На целевой системе:
sudo tar -xzf /tmp/home_backup.tar.gz -C /

# Копирование одного пользователя
rsync -avz /home/username/ user@newserver:/home/username/
```

#### Шаг 3: Импорт на целевой системе

```bash
# Проверка записей перед импортом
cat user_passwd.txt

# Добавление записей (убедитесь в отсутствии конфликтов UID!)
sudo cat user_passwd.txt >> /etc/passwd
sudo cat user_shadow.txt >> /etc/shadow
sudo cat user_group.txt >> /etc/group

# Исправление прав
sudo chown -R username:username /home/username
sudo chmod 755 /home/username
```

### Метод 2: Автоматизированный перенос (скрипт)

```bash
#!/bin/bash
# migrate_user.sh - скрипт миграции пользователя

SOURCE_HOST="$1"
USERNAME="$2"

if [[ -z "$SOURCE_HOST" || -z "$USERNAME" ]]; then
    echo "Использование: $0 <source_host> <username>"
    exit 1
fi

# Проверка существования пользователя на исходной системе
if ! ssh root@$SOURCE_HOST "id $USERNAME" 2>/dev/null; then
    echo "Пользователь $USERNAME не найден на $SOURCE_HOST"
    exit 1
fi

# Проверка существования на целевой
if id "$USERNAME" &>/dev/null; then
    echo "Пользователь $USERNAME уже существует локально"
    exit 1
fi

# Экспорт записей
ssh root@$SOURCE_HOST "grep ^$USERNAME: /etc/passwd" > /tmp/passwd_entry
ssh root@$SOURCE_HOST "grep ^$USERNAME: /etc/shadow" > /tmp/shadow_entry
ssh root@$SOURCE_HOST "grep ^$USERNAME: /etc/group" > /tmp/group_entry

# Проверка UID на конфликты
UID_VAL=$(cut -d: -f3 /tmp/passwd_entry)
if grep -q ":$UID_VAL:" /etc/passwd; then
    echo "CONFLICT: UID $UID_VAL уже существует!"
    exit 1
fi

# Импорт записей
sudo cat /tmp/passwd_entry >> /etc/passwd
sudo cat /tmp/shadow_entry >> /etc/shadow
sudo cat /tmp/group_entry >> /etc/group

# Копирование домашней директории
rsync -avz root@$SOURCE_HOST:/home/$USERNAME/ /home/$USERNAME/

# Исправление прав
sudo chown -R $USERNAME:$USERNAME /home/$USERNAME

# Очистка
rm -f /tmp/passwd_entry /tmp/shadow_entry /tmp/group_entry

echo "Миграция пользователя $USERNAME завершена успешно"
```

### Метод 3: Массовая миграция

```bash
#!/bin/bash
# migrate_all_users.sh - массовая миграция пользователей

SOURCE_HOST="$1"
MIN_UID="${2:-1000}"

# Создание временной директории
WORKDIR=$(mktemp -d)
cd "$WORKDIR"

# Экспорт всех пользователей с UID >= MIN_UID
ssh root@$SOURCE_HOST "awk -F: '\$3 >= $MIN_UID' /etc/passwd" > passwd.export
ssh root@$SOURCE_HOST "awk -F: '\$3 >= $MIN_UID' /etc/shadow" > shadow.export

# Проверка конфликтов
echo "Проверка конфликтов UID..."
while IFS=: read -r user pass uid rest; do
    if grep -q ":$uid:" /etc/passwd; then
        echo "CONFLICT: UID $uid (user: $user)"
    fi
done < passwd.export

# Импорт (после ручной проверки конфликтов)
read -p "Продолжить импорт? (y/n): " confirm
if [[ "$confirm" == "y" ]]; then
    cat passwd.export | sudo tee -a /etc/passwd
    cat shadow.export | sudo tee -a /etc/shadow
    
    # Копирование домашних директорий
    rsync -avz root@$SOURCE_HOST:/home/ /home/
    
    echo "Миграция завершена"
fi

# Очистка
cd -
rm -rf "$WORKDIR"
```

### Метод 4: Миграция с изменением UID

```bash
#!/bin/bash
# migrate_user_remap.sh - миграция с переназначением UID

USERNAME="$1"
NEW_UID="$2"

if [[ -z "$USERNAME" || -z "$NEW_UID" ]]; then
    echo "Использование: $0 <username> <new_uid>"
    exit 1
fi

# Создание пользователя с новым UID
sudo useradd -m -u "$NEW_UID" "$USERNAME"

# Копирование домашней директории
rsync -avz /source/home/$USERNAME/ /home/$USERNAME/

# Исправление прав (на случай если файлы с старым UID)
sudo chown -R $USERNAME:$USERNAME /home/$USERNAME

# Копирование скрытых файлов настроек
rsync -avz /source/home/$USERNAME/.[!.]* /home/$USERNAME/

echo "Пользователь $USERNAME создан с UID $NEW_UID"
```

## Лучшие практики

### Перед миграцией

1. **Проверьте конфликты UID/GID** — используйте `getent passwd` и `cut -d: -f3`
2. **Создайте резервные копии** — всегда备份ируйте /etc/* и /home
3. **Тестируйте на тестовой системе** — не миграйте сразу на production
4. **Запланируйте downtime** — пользователи не должны быть активны

### Во время миграции

1. **Используйте rsync** — сохраняет права и атрибуты
2. **Проверяйте права** — `ls -la /home/username`
3. **Тестируйте вход** — сразу проверяйте возможность входа
4. **Проверяйте sudo** — если пользователь должен иметь привилегии

### После миграции

```bash
# Проверка владельца домашней директории
ls -la /home/ | grep username

# Проверка UID/GID
id username

# Проверка возможности входа
su - username

# Проверка файлов пользователя
find /home/username -not -user username

# Исправление прав (если нужно)
find /home/username -exec chown username:username {} \;
```

### Альтернатива: Централизованное управление

Вместо миграции рассмотрите LDAP/SSSD:

```bash
# Установка SSSD
apt install sssd sssd-ldap

# Настройка /etc/sssd/sssd.conf
# См. ldap_sssd.md для подробной конфигурации
```

## Дополнительная информация

### Распространённые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Пользователь не может войти | Неправильные права на /home | `chown -R user:user /home/user` |
| Потеряны файлы | Неполное копирование | Используйте `rsync -avz` |
| Конфликт UID | Одинаковые UID на системах | Измените UID через `usermod -u` |
| Не работает sudo | Пользователь не в группе sudo | `usermod -aG sudo username` |

### Связанные темы

- [Управление пользователями](./user_commands.md) — `useradd`, `usermod`
- [Файлы конфигурации](./users_config_files.md) — `/etc/passwd`, `/etc/shadow`
- [LDAP/SSSD](./LDAP_SSSD/operations.md) — централизованное управление
- [Права доступа](../../Security/Concepts/File_Permissions/overview_definitions.md) — `chmod`, `chown`
