# Протокол LDAP: основы и терминология

## Определения

**LDAP (Lightweight Directory Access Protocol)** — протокол прикладного уровня (TCP порты 389/636) для доступа к распределённым службам каталогов. Определён в RFC 4511. Используется для централизованного хранения учётных записей пользователей, групп, хостов, сертификатов и политик доступа.

**DIT (Directory Information Tree)** — иерархическая структура данных LDAP, организованная в виде дерева записей. Каждая запись (Entry) имеет уникальное DN и состоит из атрибутов.

**DN (Distinguished Name)** — уникальный идентификатор записи в DIT. Состоит из цепочки RDN, разделённых запятыми. Пример: `uid=jdoe,ou=people,dc=example,dc=com`.

**RDN (Relative Distinguished Name)** — относительное отличительное имя, однозначно идентифицирующее запись в пределах родительского контейнера. Пример: `uid=jdoe`.

**Base DN** — корневая точка поиска в DIT. Указывается в LDAP-запросах для определения области поиска. Пример: `dc=example,dc=com`.

**Entry (Запись)** — объект в DIT, представляющий собой набор атрибутов. Каждая запись принадлежит одному или нескольким objectClass.

**Attribute (Атрибут)** — пара «имя-значение» в записи. Имя атрибута определено схемой (например, `uid`, `cn`, `mail`).

**ObjectClass (Объектный класс)** — определение из схемы, задающее набор обязательных (`MUST`) и опциональных (`MAY`) атрибутов. Примеры: `inetOrgPerson`, `posixAccount`, `groupOfNames`.

**Schema (Схема)** — набор правил, определяющих структуру данных: какие objectClass существуют, какие атрибуты они содержат. Схемы загружаются сервером при старте.

**LDIF (LDAP Data Interchange Format)** — текстовый формат для представления, импорта и экспорта данных LDAP. Используется для ручного редактирования, бэкапов и миграций.

**Bind (Привязка)** — операция аутентификации клиента к LDAP-серверу. Три режима:
- **Anonymous** — без учётных данных (часто отключён в production)
- **Simple** — передача DN и пароля (требует TLS)
- **SASL** — аутентификация через GSSAPI (Kerberos), DIGEST-MD5 и др.

**Scope (Область поиска)** — параметр, определяющий глубину поиска от Base DN:
- **base** — только сама запись Base DN
- **one** — непосредственные дети Base DN
- **subtree** — все потомки (включая Base DN)

**Filter (Фильтр)** — выражение для фильтрации записей. Примеры: `(uid=jdoe)`, `(&(objectClass=person)(!(sn=Admin)))`, `(|(cn=John*)(cn=Jane*))`.

**Referral (Перенаправление)** — ответ сервера, указывающий клиенту на другой LDAP-сервер.

**Operational Attribute** — атрибут, автоматически генерируемый сервером (например, `creatorsName`, `createTimestamp`, `entryCSN`, `entryUUID`). Не возвращается без явного указания.

---

## Базовые концепции

### Архитектура LDAP

```text
[ Приложение (SSH, SSSD, Keycloak, Nginx) ]
              │
              ▼
    ┌─────────────────────┐
    │   LDAP-клиент       │  ldapsearch, ldapadd, ldapmodify, SSSD
    │   (libldap)         │
    └─────────┬───────────┘
              │ TCP 389 (LDAP) или TCP 636 (LDAPS)
              ▼
    ┌─────────────────────┐
    │   LDAP-сервер       │  OpenLDAP (slapd), 389DS (ns-slapd)
    │  ┌───────────────┐  │
    │  │ Front-end     │  │  Парсинг протокола
    │  ├───────────────┤  │
    │  │ Slapi / Engine│  │  Плагины, ACL/ACI, репликация
    │  ├───────────────┤  │
    │  │ Back-end (DB) │  │  LMDB/MDB — хранение и индексы
    │  └───────────────┘  │
    └─────────────────────┘
```

### Структура DIT

```text
dc=example,dc=com
├── ou=people
│   ├── uid=jdoe
│   │   ├── cn: John Doe
│   │   ├── sn: Doe
│   │   ├── uid: jdoe
│   │   ├── mail: jdoe@example.com
│   │   ├── uidNumber: 10000
│   │   ├── gidNumber: 10000
│   │   ├── homeDirectory: /home/jdoe
│   │   └── loginShell: /bin/bash
│   └── uid=asmith
├── ou=groups
│   ├── cn=developers
│   │   ├── cn: developers
│   │   └── member: uid=jdoe,ou=people,dc=example,dc=com
│   └── cn=admins
├── ou=hosts
├── ou=services
└── ou=sudoers
```

### Основные операции LDAP

| Операция | Назначение | Пример |
|:---|:---|:---|
| **Bind** | Аутентификация | `ldapwhoami -D "cn=admin,dc=example,dc=com" -W` |
| **Search** | Чтение данных | `ldapsearch -x -b "dc=example,dc=com" "(uid=jdoe)"` |
| **Add** | Добавление записи | `ldapadd -x -D "cn=admin,dc=example,dc=com" -W -f user.ldif` |
| **Modify** | Изменение атрибутов | `ldapmodify -x -D "cn=admin,dc=example,dc=com" -W -f modify.ldif` |
| **Delete** | Удаление записи | `ldapdelete -x -D "cn=admin,dc=example,dc=com" -W "uid=jdoe,ou=people,dc=example,dc=com"` |
| **Compare** | Проверка значения | `ldapcompare -x -D "cn=admin,dc=example,dc=com" -W "uid=jdoe" mail:jdoe@example.com` |
| **Modify DN** | Переименование | `ldapmoddn -x -D "cn=admin,dc=example,dc=com" -W "uid=jdoe,ou=people,dc=example,dc=com" -r "uid=john.doe"` |

### Синтаксис LDAP-фильтров

| Оператор | Описание | Пример |
|:---|:---|:---|
| `(attr=value)` | Точное совпадение | `(uid=jdoe)` |
| `(attr~=value)` | Нечёткое совпадение (approx) | `(cn~=John)` |
| `(attr>=value)` | Больше или равно | `(uidNumber>=1000)` |
| `(attr<=value)` | Меньше или равно | `(uidNumber<=5000)` |
| `(attr=*value*)` | Подстрока (substring) | `(cn=*John*)` |
| `(attr=*)` | Наличие атрибута (presence) | `(mail=*)` |
| `(!(attr=value))` | Отрицание | `(!(uid=root))` |
| `(&(f1)(f2))` | Логическое И | `(&(objectClass=person)(mail=*))` |
| `(\|(f1)(f2))` | Логическое ИЛИ | `(\|(cn=John*)(cn=Jane*))` |

### Схемы LDAP

#### RFC 2307 vs RFC 2307bis

| Характеристика | RFC 2307 | RFC 2307bis |
|:---|:---|:---|
| **Членство в группе** | `memberUid` (UID) | `member` (DN пользователя) |
| **Вложенные группы** | Не поддерживаются | Поддерживаются |
| **Рекомендация** | Legacy | Рекомендуется для новых систем |

#### Ключевые objectClass для Linux

| ObjectClass | Назначение | MUST | MAY |
|:---|:---|:---|:---|
| `inetOrgPerson` | Человек в организации | `cn`, `sn` | `givenName`, `mail`, `telephoneNumber` |
| `posixAccount` | POSIX-учётная запись | `uid`, `uidNumber`, `gidNumber`, `homeDirectory` | `loginShell`, `gecos` |
| `shadowAccount` | Учётные данные пароля | `uid` | `shadowLastChange`, `shadowMax`, `shadowWarning` |
| `groupOfNames` | Группа (членство по DN) | `cn`, `member` | `description` |
| `posixGroup` | POSIX-группа | `cn` | `gidNumber`, `memberUid`, `member` |

### Порты и протоколы

| Порт | Протокол | Описание |
|:---|:---|:---|
| 389 | TCP LDAP | Незашифрованное соединение (или StartTLS) |
| 636 | TCP LDAPS | Зашифрованное соединение (TLS с момента установки) |
| 389/636 | UDP | Редко используется, не рекомендуется |

### Типы LDAP-серверов

| Решение | Особенности | Использование |
|:---|:---|:---|
| **OpenLDAP** | Свободная реализация, MDB-бэкенд, overlays | Минималистичные окружения, Linux-интеграция |
| **389DS** | Multi-Master, Slapi-плагины, JSON-логи | Enterprise, FreeIPA, корпоративные каталоги |
| **Active Directory** | LDAP + Kerberos + DNS + GPO | Гетерогенные сети (Windows + Linux) |
| **FreeIPA** | 389DS + Kerberos + BIND + Dogtag CA | Централизованное управление Linux-доменом |

## Практические сценарии

### Базовые команды ldapsearch

```text
# Анонимный поиск всех записей
ldapsearch -x -b "dc=example,dc=com" "(objectClass=*)"

# Поиск конкретного пользователя
ldapsearch -x -b "ou=people,dc=example,dc=com" "(uid=jdoe)"

# Поиск с авторизацией
ldapsearch -x -D "cn=readonly,ou=services,dc=example,dc=com" -W \
  -b "dc=example,dc=com" "(&(objectClass=person)(mail=*))" cn mail

# Вывод только DN и атрибутов cn, mail
ldapsearch -x -b "dc=example,dc=com" "(objectClass=person)" cn mail

# Поиск через LDAPS (порт 636)
ldapsearch -H ldaps://ldap.example.com:636 \
  -D "cn=admin,dc=example,dc=com" -W \
  -b "dc=example,dc=com" "(uid=jdoe)"

# Постраничная выборка (для больших каталогов)
ldapsearch -x -b "dc=example,dc=com" "(objectClass=*)" -E pr=1000/noprint
```

### Формат LDIF для добавления пользователя

```text
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
```

### Формат LDIF для модификации

```text
dn: uid=jdoe,ou=people,dc=example,dc=com
changetype: modify
add: mail
mail: newemail@example.com
-
replace: loginShell
loginShell: /bin/zsh
-
delete: telephoneNumber
```

### Проверка схемы на сервере

```text
# Просмотр всех загруженных objectClass
ldapsearch -x -b "cn=schema,cn=config" "(objectClass=*)" objectclasses

# Просмотр атрибутов конкретного objectClass
ldapsearch -x -b "cn=schema,cn=config" "(&(objectClass=schemaObjectclass)(cn=inetOrgPerson))"

# Проверка наличия атрибута в схеме
ldapsearch -x -b "cn=schema,cn=config" "(&(objectClass=schemaAttribute)(cn=mail))" ldapSyntaxes
```

### Проектирование схем (Schema Design)

#### Принципы проектирования DIT

| Принцип | Описание | Пример |
|:---|:---|:---|
| **Плоское vs Иерархическое** | Баланс между вложенностью и количеством записей в контейнере | < 500 записей в одном ou — плоское; > 500 — разбить на подразделы |
| **Уникальность RDN** | RDN должен быть уникальным в пределах родителя | `uid=jdoe` (не `cn=john`) |
| **Стабильность DN** | Изменение RDN требует Modify DN операции | Не используйте атрибуты, которые меняются (mail) |
| **Отделение данных** | Разные objectClass для разных целей | `inetOrgPerson` для людей, `groupOfNames` для групп |

#### Рекомендуемые objectClass

| Класс | Назначение | RDN атрибут | Членство |
|:---|:---|:---|:---|
| `inetOrgPerson` | Человек | `uid` | `member` (DN) |
| `posixAccount` | POSIX-пользователь | `uid` | `memberUid` (UID) |
| `posixGroup` | POSIX-группа | `cn` | `memberUid` или `member` |
| `groupOfNames` | Группа (LDAP-стиль) | `cn` | `member` (DN) |
| `groupOfUniqueNames` | Группа (UNIQUE) | `cn` | `uniqueMember` (DN) |
| `organizationalUnit` | Подразделение | `ou` | — |

#### Создание собственной схемы

```bash
# Пример: добавление атрибута posEmail в стандартную схему
ldapadd -Y EXTERNAL -H ldapi:/// <<EOF
dn: cn=module{0},cn=config
changetype: modify
add: olcModuleLoad
olcModuleLoad: back_mdb

dn: cn=schema,cn=config
changetype: modify
add: olcAttributeTypes
olcAttributeTypes: ( 1.3.6.1.4.1.99999.1.1.1
  NAME 'posEmail'
  EQUALITY caseIgnoreMatch
  SUBSTR caseIgnoreSubstringsMatch
  SYNTAX 1.3.6.1.4.1.1466.115.121.1.15
  SINGLE-VALUE )
EOF

# Или через LDIF-файл
cat > /tmp/custom-schema.ldif <<LDIF
dn: cn=schema,cn=config
changetype: modify
add: olcObjectClasses
olcObjectClasses: ( 1.3.6.1.4.1.99999.2.1.1
  NAME 'posixUserWithEmail'
  SUP top
  AUXILIARY
  MAY ( posEmail $ homePhone ) )
LDIF

ldapmodify -Y EXTERNAL -H ldapi:/// -f /tmp/custom-schema.ldif
```

## Дополнительная информация

### Частые ошибки при работе с LDAP

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `No such object` | Неверный Base DN или запись не существует | Проверьте DN через `ldapsearch -x -b "" -s base "(objectClass=*)"` |
| `Invalid credentials` | Неверный Bind DN или пароль | Проверьте DN и пароль; используйте `ldapwhoami` |
| `Size limit exceeded` | Превышен `sizelimit` сервера | Увеличьте лимит или используйте постраничную выборку |
| `Protocol error` | Несовместимая версия протокола | Укажите `-VV` для отладки версии |
| `Referral` | Запись на другом сервере | Используйте флаг `-C` для автоматического перенаправления |
| `Operations error` | Нет прав на чтение или серверная ошибка | Проверьте ACL/ACI на целевом DN |

### LDAP vs DNS vs NIS

| Характеристика | LDAP | DNS | NIS |
|:---|:---|:---|:---|
| **Данные** | Произвольные (пользователи, группы, хосты) | Имена -> IP-адреса | POSIX-файлы (passwd, group) |
| **Структура** | Иерархическое дерево (DIT) | Дерево зон | Плоские карты |
| **Безопасность** | TLS, ACL/ACI, SASL | DNSSEC | SYS (устарел) |
| **Масштабируемость** | Высокая (репликация) | Очень высокая | Низкая |
| **Производительность** | Средняя (зависит от индексов) | Высокая (кэширование) | Средняя |

### См. также

- **[OpenLDAP: установка и конфигурация](./openldap_basics.md)** — bare-metal развертывание
- **[389 Directory Server](./389ds/overview.md)** — архитектура и возможности
- **[LDAP + SSSD](../Linux/SystemAdministration/Users/LDAP_SSSD/index.md)** — интеграция с Linux
- **[LDAP Security Hardening](./ldap_security.md)** — настройка безопасности
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
- **[LDAP: проектирование схем и DIT](./ldap_schema_design.md)** — выбор objectClass и структуры DIT
- **[LDAP: интеграция с внешними системами](./ldap_integrations.md)** — Grafana, GitLab, Vault, Keycloak
- **[LDAP: продвинутые операции](./ldap_advanced_operations.md)** — proxied auth, chaining, rate limiting
