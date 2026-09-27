# LDAP: проектирование схем и DIT

## Определения

**Schema (Схема)** — набор правил, определяющих структуру данных LDAP: какие objectClass существуют, какие атрибуты они содержат, какие атрибуты обязательны (MUST), а какие опциональны (MAY). Схема garantирует целостность данных и типобезопасность.

**ObjectClass (Объектный класс)** — определение из схемы, задающее набор атрибутов для конкретного типа объекта (пользователь, группа, хост и т.д.). Каждая запись LDAP принадлежит одному или нескольким objectClass.

**DIT (Directory Information Tree)** — иерархическая структура данных LDAP, организованная в виде дерева записей. Правила проектирования DIT определяют удобство поиска, масштабируемость и производительность.

**RFC 2307** — стандарт схемы для хранения information about network entities (users, groups, hosts) в LDAP. Используется в OpenLDAP по умолчанию.

**RFC 2307bis** — расширение RFC 2307, добавляющее поддержку вложенных групп (nested groups) через атрибут `member` вместо `memberUid`. Используется в 389DS и Active Directory.

**Schema Migration** — процесс преобразования данных из одной схемы в другую (например, memberUid -> member при миграции OpenLDAP -> 389DS).

---

## Базовые концепции

### Сравнение схем

| Характеристика | RFC 2307 | RFC 2307bis | Active Directory |
|:---|:---|:---|:---|
| **Группы** | `memberUid` (uid пользователей) | `member` (DN пользователей) | `member` (DN) |
| **Вложенные группы** | Не поддерживаются | `member` + `memberOf` overlay | Вложенные группы нативно |
| **Пользователи** | `posixAccount` + `inetOrgPerson` | `posixAccount` + `inetOrgPerson` | `user` (AD-specific) |
| **Хосты** | `ipHost` | `ipHost` | `computer` |
| **sudo правила** | `sudoRole` (openldap-schemas) | `sudoRole` | GPO |

### Выбор objectClass для пользователя

| objectClass | Атрибуты | Когда использовать |
|:---|:---|:---|
| **`posixAccount`** | uid, uidNumber, gidNumber, homeDirectory, loginShell | Linux/UNIX-системы (обязателен для SSSD) |
| **`inetOrgPerson`** | cn, sn, givenName, mail, telephoneNumber | Корпоративный каталог (имя, email, телефон) |
| **`person`** | cn, sn | Минимальная запись пользователя |
| **`organizationalPerson`** | + title, ou, physicalDeliveryOfficeName | Расширенный профиль |
| **`inetUser`** | + userPassword, uid | Для аутентификации |

**Рекомендация:** Использовать `inetOrgPerson` + `posixAccount` одновременно. Это покрывает и корпоративную информацию, и POSIX-атрибуты для Linux.

### Выбор objectClass для группы

| objectClass | Атрибуты | Когда использовать |
|:---|:---|:---|
| **`groupOfNames`** | cn, member (DN), (обязателен member) | Стандартная группа (RFC 2307bis) |
| **`groupOfUniqueNames`** | cn, uniqueMember (DN) | Альтернатива groupOfNames |
| **`posixGroup`** | cn, gidNumber, memberUid | POSIX-группы (RFC 2307) |
| **`groupOfURLs`** | cn, memberURL | Динамические группы |

**Рекомендация:** Использовать `groupOfNames` с атрибутом `member` (DN). Для POSIX-совместимости добавлять `gidNumber`. Для вложенных групп включить `memberOf` overlay (OpenLDAP) или использовать нативные вложенные группы (389DS).

### Правила проектирования DIT

#### Принцип 1: Минимальная глубина

```text
ПЛОХО (слишком глубоко):
dc=example,dc=com
  +-- ou=divisions
       +-- ou=engineering
            +-- ou=backend
                 +-- ou=devops
                      +-- uid=jdoe

ХОРОШО (плоская структура):
dc=example,dc=com
  +-- ou=people        (все пользователи)
  +-- ou=groups        (все группы)
  +-- ou=hosts         (все хосты)
  +-- ou=services      (сервисные учётные записи)
  +-- ou=sudoers       (sudo правила)
```

#### Принцип 2: Разделение по типам объектов

```text
dc=example,dc=com
+-- ou=people         (objectClass: inetOrgPerson, posixAccount)
+-- ou=groups         (objectClass: groupOfNames, posixGroup)
+-- ou=hosts          (objectClass: ipHost, ieee802Device)
+-- ou=services       (objectClass: organizationalRole)
+-- ou=sudoers        (objectClass: sudoRole)
+-- ou=policies       (objectClass: pwdPolicy)
+-- cn=config         (конфигурация сервера)
```

#### Принцип 3: Филиалы через контейнеры

```text
dc=example,dc=com
+-- ou=people
|   +-- uid=jdoe      (атрибут: ou=moscow или departmentNumber=moscow)
|   +-- uid=asmith    (атрибут: ou=spb)
+-- ou=groups
|   +-- cn=devops-moscow
|   +-- cn=devops-spb
+-- ou=locations
    +-- ou=moscow
    +-- ou=spb
```

**Не создавайте отдельные DIT для филиалов** -- используйте атрибуты (ou, departmentNumber, localityName) для фильтрации.

---

## Практические сценарии

### 1. Загрузка стандартных схем (OpenLDAP)

```bash
# Загрузка базовых схем
sudo ldapadd -Y EXTERNAL -H ldapi:/// \
  -f /etc/openldap/schema/cosine.ldif
sudo ldapadd -Y EXTERNAL -H ldapi:/// \
  -f /etc/openldap/schema/inetorgperson.ldif
sudo ldapadd -Y EXTERNAL -H ldapi:/// \
  -f /etc/openldap/schema/nis.ldif

# Проверка загруженных схем
ldapsearch -Y EXTERNAL -H ldapi:/// \
  -b "cn=schema,cn=config" "(objectClass=*)" dn | grep -c "cn="
# -> Типичное значение: 15-25 схем
```

### 2. Добавление схемы sudo (OpenLDAP)

```bash
# Создание LDIF-файла sudo-схемы
cat > /tmp/sudo.ldif << 'EOF'
dn: cn=sudo,cn=schema,cn=config
objectClass: olcSchemaConfig
cn: sudo
olcAttributeTypes: ( 1.3.6.1.4.1.2312.4.1.1.1
  NAME 'sudoUser'
  DESC 'User(s) who may run sudo'
  EQUALITY caseExactIA5Match
  SUBSTR caseIgnoreIA5SubstringsMatch
  SYNTAX 1.3.6.1.4.1.1466.115.121.1.26 )
olcAttributeTypes: ( 1.3.6.1.4.1.2312.4.1.1.2
  NAME 'sudoHost'
  DESC 'Host(s) who may run sudo'
  EQUALITY caseExactIA5Match
  SUBSTR caseIgnoreIA5SubstringsMatch
  SYNTAX 1.3.6.1.4.1.1466.115.121.1.26 )
olcAttributeTypes: ( 1.3.6.1.4.1.2312.4.1.1.3
  NAME 'sudoCommand'
  DESC 'Command(s) to be executed by sudo'
  EQUALITY caseExactIA5Match
  SYNTAX 1.3.6.1.4.1.1466.115.121.1.26 )
olcAttributeTypes: ( 1.3.6.1.4.1.2312.4.1.1.4
  NAME 'sudoRunAs'
  DESC 'User(s) impersonated by sudo'
  EQUALITY caseExactIA5Match
  SYNTAX 1.3.6.1.4.1.1466.115.121.1.26 )
olcAttributeTypes: ( 1.3.6.1.4.1.2312.4.1.1.5
  NAME 'sudoOption'
  DESC 'Options(s) followed by sudo'
  EQUALITY caseExactIA5Match
  SYNTAX 1.3.6.1.4.1.1466.115.121.1.26 )
olcObjectClasses: ( 1.3.6.1.4.1.2312.4.1.2.1
  NAME 'sudoRole'
  DESC 'Sudoer Entries'
  SUP top STRUCTURAL
  MUST cn
  MAY ( sudoUser $ sudoHost $ sudoCommand $ sudoRunAs $ sudoOption $
        description ) )
EOF

sudo ldapadd -Y EXTERNAL -H ldapi:/// -f /tmp/sudo.ldif
```

### 3. Создание начальной структуры DIT (OpenLDAP)

```bash
cat > /tmp/base-dit.ldif << 'EOF'
dn: dc=example,dc=com
objectClass: top
objectClass: domain
dc: example

dn: ou=people,dc=example,dc=com
objectClass: top
objectClass: organizationalUnit
ou: people

dn: ou=groups,dc=example,dc=com
objectClass: top
objectClass: organizationalUnit
ou: groups

dn: ou=hosts,dc=example,dc=com
objectClass: top
objectClass: organizationalUnit
ou: hosts

dn: ou=services,dc=example,dc=com
objectClass: top
objectClass: organizationalUnit
ou: services

dn: ou=sudoers,dc=example,dc=com
objectClass: top
objectClass: organizationalUnit
ou: sudoers
EOF

ldapadd -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W -f /tmp/base-dit.ldif
```

### 4. Создание пользователя (комбинированный objectClass)

```bash
cat > /tmp/user.ldif << 'EOF'
dn: uid=jdoe,ou=people,dc=example,dc=com
objectClass: inetOrgPerson
objectClass: posixAccount
objectClass: shadowAccount
uid: jdoe
cn: John Doe
sn: Doe
givenName: John
mail: jdoe@example.com
uidNumber: 10000
gidNumber: 10000
homeDirectory: /home/jdoe
loginShell: /bin/bash
userPassword: {SSHA}hash_here
ou: DevOps
title: Senior DevOps Engineer
telephoneNumber: +7 495 123-45-67
EOF

ldapadd -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W -f /tmp/user.ldif
```

### 5. Создание группы с вложенными группами

```bash
# Родительская группа
cat > /tmp/group-parent.ldif << 'EOF'
dn: cn=engineering,ou=groups,dc=example,dc=com
objectClass: top
objectClass: groupOfNames
cn: engineering
member: uid=jdoe,ou=people,dc=example,dc=com
member: uid=asmith,ou=people,dc=example,dc=com
description: All engineering staff
EOF

# Дочерняя группа (члены родительской автоматически входят)
cat > /tmp/group-child.ldif << 'EOF'
dn: cn=devops,ou=groups,dc=example,dc=com
objectClass: top
objectClass: groupOfNames
cn: devops
member: uid=jdoe,ou=people,dc=example,dc=com
description: DevOps team (subset of engineering)
EOF

ldapadd -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W -f /tmp/group-parent.ldif
ldapadd -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W -f /tmp/group-child.ldif
```

### 6. Частые ошибки проектирования

| Ошибка | Проблема | Решение |
|:---|:---|:---|
| Использование `memberUid` (uid) вместо `member` (DN) | Невозможно определить уникальность, проблемы с вложенными группами | Использовать `member` с DN |
| Слишком глубокая DIT | Медленные поиски, сложные ACL | Плоская структура ou=people, ou=groups |
| Нет `posixAccount` для Linux-пользователей | SSSD не может определить UID/GID | Добавить `posixAccount` |
| Нет индексов для `member` | Медленные запросы групп | Добавить индекс `member eq` |
| Один ou для всего (people, groups, hosts) | Сложно управлять ACL и масштабировать | Разделить по типам объектов |

---

## Дополнительная информация

### Миграция схем между реализациями

| FROM | TO | Конвертация |
|:---|:---|:---|
| **OpenLDAP (memberUid)** | **389DS (member)** | Скрипт конвертации uid -> DN |
| **OpenLDAP (RFC 2307)** | **AD** | memberUid -> member, posixAccount -> user |
| **389DS** | **OpenLDAP** | ACI -> olcAccess, member -> memberUid (опционально) |

### Полезные команды

```bash
# Просмотр всех objectClass в схеме
ldapsearch -Y EXTERNAL -H ldapi:/// \
  -b "cn=schema,cn=config" \
  "(objectClass=olcSchemaConfig)" olcObjectClasses

# Просмотр атрибутов конкретного objectClass
ldapsearch -Y EXTERNAL -H ldapi:/// \
  -b "cn=schema,cn=config" \
  "(olcObjectClasses=*inetOrgPerson*)" olcObjectClasses olcAttributeTypes

# Просмотр записей с определённым objectClass
ldapsearch -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W \
  -b "dc=example,dc=com" "(objectClass=posixAccount)" dn

# Проверка: какие атрибуты есть у записи
ldapsearch -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W \
  -b "uid=jdoe,ou=people,dc=example,dc=com" "*" +
```

### См. также

- **[LDAP: основы протокола](./ldap_fundamentals.md)** -- objectClass, атрибуты, DIT
- **[OpenLDAP: установка](./openldap_basics.md)** -- загрузка схем, cn=config
- **[LDAP миграция](./ldap_migration.md)** -- конвертация схем между реализациями
- **[LDAP + SSSD](../Linux/SystemAdministration/Users/LDAP_SSSD/configuration.md)** -- POSIX-атрибуты для SSSD
- **[389DS: ACI](./389ds/aci.md)** -- управление доступом на основе DIT
