# Управление группами

## Создание группы

```bash
sudo groupadd new-group
# С указанием GID
sudo groupadd -g 1500 new-group
# Создание системной группы
sudo groupadd -r new-sys-group
```

## Изменение группы

```bash
# Изменить имя
sudo groupmod -n new-name old-name
# Изменить GID
sudo groupmod -g 1501 new-name
```

## Удаление группы

(нельзя удалить, если она является первичной для какого-либо пользователя)

```bash
sudo groupdel test-group
```

## Управление членством в группах

```bash
# Добавить пользователя в группу (рекомендуемый способ)
sudo usermod -aG groupname username

# Удалить пользователя из группы
sudo gpasswd -d username groupname

# Назначить администратора группы (может добавлять/удалять пользователей без прав root)
sudo gpasswd -A username groupname

# Добавить пользователей в группу (только администраторы группы могут это делать)
sudo gpasswd -M user1,user2 groupname
```

## Переключение группы в текущей сессии

```bash
# Запускает новую оболочку с измененной первичной группой
newgrp new-group
```

См. также:
- [Приватные группы пользователей](./user_private_groups.md)
- [Управление пользователями](./user_commands.md)
- [Определения](./users_definitions.md)
