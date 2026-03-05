# Права доступа к файлам и директориям

## Краткая справка

- **Владелец (User, `u`):** Пользователь, создавший файл
- **Группа (Group, `g`):** Группа пользователей с общими правами
- **Остальные (Others, `o`):** Все остальные пользователи

## Основные команды

```bash
# Просмотр прав
ls -l

# Изменение прав (chmod)
sudo chmod 755 script.sh    # Числовой режим
sudo chmod u+x script.sh    # Символьный режим

# Изменение владельца (chown)
sudo chown user:group file
```

## Подробная информация

- [Стандартная модель DAC](../../Security/Concepts/File_Permissions/overview_definitions.md) — владелец, группа, остальные
- [Специальные права](../../Security/Concepts/File_Permissions/special_permissions.md) — SUID, SGID, Sticky Bit
- [Маска umask](../../Security/Concepts/File_Permissions/umask.md) — права по умолчанию
- [ACL и атрибуты](../../Security/Concepts/File_Permissions/acl_immutable_timestamps.md) — расширенные права

См. также:

- [Определения пользователей](./users_definitions.md)
- [Управление группами](./group_commands.md)
- [Управление привилегиями](../privilege_management.md)
