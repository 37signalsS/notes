# ACI (Access Control Instructions)

## Определения

**ACI (Access Control Instructions)** — механизм управления доступом в 389DS. В отличие от ACL в OpenLDAP, ACI привязываются к конкретным записям в дереве LDAP как атрибуты.

**Target** — объект (DN, атрибут, фильтр), к которому применяется правило доступа.

**Permission** — действие (read, write, add, delete, search, compare).

**Subject** — субъект доступа (user, group, role, anonymous).

## Базовые концепции

### Отличие от OpenLDAP

| Характеристика | OpenLDAP (ACL) | 389DS (ACI) |
| :--- | :--- | :--- |
| **Хранение** | `cn=config` (глобально) | Атрибуты записей (на запись) |
| **Наследование** | По порядку правил | По иерархии дерева |
| **Приоритет** | Первое совпадение | Явные ACI переопределяют inherited |
| **Синтаксис** | `access to ... by ...` | `aci: (target)(targetattr)(version; acl "name"; permission subject);` |

### Синтаксис ACI

```
aci: (target=<target>)(targetattr=<attr>)(version 3.0; acl "<name>"; <permission> <subject>;)
```

**Компоненты:**

| Компонент | Описание | Пример |
| :--- | :--- | :--- |
| `target` | DN или фильтр для записей | `ldap:///ou=users,dc=example,dc=com` |
| `targetattr` | Атрибуты, к которым применяется | `*` (все), `userPassword` |
| `acl` | Имя правила (для аудита) | `"Allow read access"` |
| `permission` | Разрешённые действия | `read`, `write`, `all` |
| `subject` | Кому разрешено | `userdn`, `groupdn`, `roledn` |

### Типы субъектов

| Субъект | Синтаксис | Описание |
| :--- | :--- | :--- |
| **Все** | `all` | Любой (включая anonymous) |
| **Аноним** | `userdn="ldap:///anyone"` | Неаутентифицированный пользователь |
| **Пользователь** | `userdn="ldap:///self"` | Владелец записи |
| **Группа** | `groupdn="ldap:///cn=admins,ou=groups"` | Члены группы |
| **Роль** | `roledn="ldap:///cn=manager"` | Обладатели роли |
| **Public** | `all` | Любой аутентифицированный |

## Практические сценарии

### Разрешить чтение всем (anonymous read)

```ldif
dn: dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///dc=example,dc=com")(targetattr="*")
  (version 3.0; acl "Allow read access";
  allow (read,search,compare); userdn="ldap:///anyone";)
```

### Разрешить доступ группе администраторов

```ldif
dn: dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///dc=example,dc=com")(targetattr="*")
  (version 3.0; acl "Admin group access";
  allow (all); groupdn="ldap:///cn=admins,ou=groups,dc=example,dc=com";)
```

### Разрешить пользователю редактировать свой профиль

```ldif
dn: ou=users,dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///ou=users,dc=example,dc=com")(targetattr="*")
  (version 3.0; acl "Allow self edit";
  allow (write,search); userdn="ldap:///self";)
```

### Запретить чтение паролей (кроме админов)

```ldif
dn: dc=example,dc=com
changetype: modify
add: aci
aci: (targetattr="userPassword")
  (version 3.0; acl "Deny password read";
  deny (read,search); userdn!="ldap:///cn=admins,ou=groups,dc=example,dc=com";)
```

### Разрешить изменение пароля самому пользователю

```ldif
dn: ou=users,dc=example,dc=com
changetype: modify
add: aci
aci: (targetattr="userPassword")
  (version 3.0; acl "Allow self password change";
  allow (write); userdn="ldap:///self";)
```

### Применение ACI

```bash
# Создать файл с ACI
cat > aci-config.ldif << EOF
dn: dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///dc=example,dc=com")(targetattr="*")
  (version 3.0; acl "Allow read access";
  allow (read,search,compare); userdn="ldap:///anyone";)
EOF

# Применить ACI
docker exec 389ds ldapmodify -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W -f aci-config.ldif
```

### Проверка ACI

```bash
# Просмотр всех ACI для записи
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W \
  -b "dc=example,dc=com" -A aci

# Проверка эффективных прав пользователя
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "uid=user,ou=users,dc=example,dc=com" -W \
  -b "dc=example,dc=com" "(objectClass=*)"
```

## Дополнительная информация

### Best Practices

1. **Минимальные привилегии** — разрешать только необходимое
2. **Именовать ACI** — понятные имена для аудита (`"Allow read access"`)
3. **Тестировать** — проверять права перед production
4. **Документировать** — комментировать сложные правила
5. **Наследование** — учитывать, что ACI наследуются по дереву
6. **Порядок** — явные ACI переопределяют унаследованные

### Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| `Insufficient access` | Проверить ACI с `-A aci`, проверить членство в группах |
| `ACI not applied` | Убедиться, что ACI на правильном DN в иерархии |
| `Конфликт ACI` | Явные ACI имеют приоритет над inherited |

### Репликация ACI

> **Важно:** ACI хранятся как атрибуты записей и **реплицируются** вместе с данными. Изменение ACI на одном сервере автоматически применяется на всех репликах.

### Примеры сложных ACI

#### Разрешить HR читать профили сотрудников

```ldif
aci: (target="ldap:///ou=people,dc=example,dc=com")
  (targetattr="cn || sn || givenName || telephoneNumber || mail")
  (version 3.0; acl "HR read employees";
  allow (read,search);
  groupdn="ldap:///cn=hr,ou=groups,dc=example,dc=com";)
```

#### Запретить удаление администраторов

```ldif
aci: (target="ldap:///cn=admins,ou=groups,dc=example,dc=com")
  (targetattr="member")
  (version 3.0; acl "Protect admin members";
  deny (delete); userdn!="ldap:///cn=Directory Manager";)
```

### Связанные документы

- [Обзор 389DS](./overview.md) — общая информация
- [Плагины](./plugins.md) — модули расширения
- [Docker развёртывание](./docker.md) — запуск в контейнере
- [Репликация](./replication.md) — multi-master настройка
