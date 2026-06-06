# Плагины 389DS

## Определения

**Плагины 389DS** — модули расширения функциональности сервера. Включаются/отключаются через `cn=config`.

## Базовые концепции

### Категории плагинов

| Категория | Плагины |
| :--- | :--- |
| **Репликация** | Replication, Changelog |
| **Аутентификация** | PAM, Kerberos, GSSAPI |
| **Авторизация** | [ACI](./aci.md), Roles, CoS |
| **Аудит** | Audit Log, Retro Changelog |
| **Синхронизация** | AD Sync, DNA |
| **Утилиты** | MemberOf, Referential Integrity |

## Практические сценарии

### Retro Changelog

**Назначение:** Сохраняет все изменения в `cn=changelog` для аудита и отладки репликации.

**Включение:**

```ldif
dn: cn=Retro Changelog,cn=plugins,cn=config
changetype: modify
replace: nsslapd-pluginEnabled
nsslapd-pluginEnabled: on
```

**Применение:**

```bash
docker exec 389ds ldapmodify -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W -f retro-changelog.ldif
```

> Подробнее о развёртывании в [Docker](./docker.md).

**Проверка:**

```bash
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W \
  -b "cn=Retro Changelog,cn=plugins,cn=config"
```

### MemberOf

**Назначение:** Автоматически добавляет атрибут `memberOf` пользователям, указывая группы, в которых они состоят.

**Включение:**

```ldif
dn: cn=MemberOf Plugin,cn=plugins,cn=config
changetype: modify
replace: nsslapd-pluginEnabled
nsslapd-pluginEnabled: on

dn: cn=MemberOf Plugin,cn=plugins,cn=config
changetype: modify
replace: memberOfGroupAttr
memberOfGroupAttr: uniqueMember
```

**Применение:**

```bash
docker exec 389ds ldapmodify -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W -f memberof.ldif

# Перезапуск контейнера
docker restart 389ds
```

**Проверка:**

```bash
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W \
  -b "cn=MemberOf Plugin,cn=plugins,cn=config"
```

### Referential Integrity

**Назначение:** Автоматически удаляет пользователя из групп при его удалении (поддерживает целостность ссылок).

**Включение:**

```ldif
dn: cn=Referential Integrity Postop,cn=plugins,cn=config
changetype: modify
replace: nsslapd-pluginEnabled
nsslapd-pluginEnabled: on

dn: cn=Referential Integrity Postop,cn=plugins,cn=config
changetype: modify
replace: ref-integrity-attr
ref-integrity-attr: member
ref-integrity-attr: uniqueMember
ref-integrity-attr: owner
ref-integrity-attr: seeAlso
```

### DNA (Distributed Numeric Assignment)

**Назначение:** Автоматическая генерация уникальных UID/GID для POSIX-пользователей.

**Включение:**

```ldif
# Включить плагин
dn: cn=DNA,cn=plugins,cn=config
changetype: modify
replace: nsslapd-pluginEnabled
nsslapd-pluginEnabled: on

# Создать конфигурацию диапазона
dn: cn=posix-ids,cn=DNA,cn=plugins,cn=config
objectClass: top
objectClass: dnaPluginConfig
cn: posix-ids
dnaType: posixAccount
dnaAttrName: uidNumber
dnaNextValue: 10000
dnaNextRange: 100000
```

### Account Policy

**Назначение:** Управление блокировкой учётных записей, сроком действия паролей.

**Включение:**

```ldif
dn: cn=Account Policy Plugin,cn=plugins,cn=config
changetype: modify
replace: nsslapd-pluginEnabled
nsslapd-pluginEnabled: on
```

### Password Policy (встроенная)

**Назначение:** Требования к сложности паролей, история, срок действия.

**Настройка:**

```bash
# Создать политику
dsconf -D "cn=Directory Manager" ldap://localhost:3389 \
  pwpolicy set --minlength 12 --minclasses 3 --maxage 90 \
  --history 5 --checkdict true --dc=example,dc=com
```

## Дополнительная информация

### Проверка статуса плагинов

```bash
# Список всех плагинов
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W \
  -b "cn=plugins,cn=config" \
  "(objectClass=nsPlugin)" cn nsslapd-pluginEnabled
```

### Рекомендации (Best Practices)

1. **Retro Changelog** — включать в production для аудита
2. **MemberOf** — необходим для интеграции с сервисами, требующими обратного поиска групп
3. **Referential Integrity** — предотвращает "висячие" ссылки в группах
4. **DNA** — упрощает управление POSIX-аккаунтами
5. **Password Policy** — обязательна в production

### Репликация конфигурации плагинов

> **Важно:** Конфигурация плагинов (`cn=config`) **не реплицируется**. Настройки применяются на каждом сервере отдельно. Подробнее о репликации данных — в [настройке репликации](./replication.md).
