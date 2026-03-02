# ACI (Access Control Instructions)

ACI в 389DS определяют права доступа на уровне отдельных записей. В отличие от OpenLDAP (ACL), ACI привязываются к конкретным записям в дереве LDAP.

## Отличие от OpenLDAP

| OpenLDAP | 389DS |
| :--- | :--- |
| ACL (Access Control List) | ACI (Access Control Instructions) |
| Конфигурация в `cn=config` | ACI в атрибутах записей |
| Глобальные правила | Правила на уровне записей |

## Примеры ACI

### Разрешить доступ всем (чтение)

```ldif
dn: dc=test,dc=local
changetype: modify
add: aci
aci: (target="ldap:///dc=test,dc=local")(targetattr="*")(version 3.0; acl "Allow read access"; allow (read,search,compare);)
```

### Разрешить доступ группе администраторов

```ldif
dn: dc=test,dc=local
changetype: modify
add: aci
aci: (target="ldap:///dc=test,dc=local")(targetattr="*")(version 3.0; acl "Admin group access"; allow (all)(groupdn="ldap:///cn=admins,ou=groups,dc=test,dc=local");)
```

## Применение ACI

```bash
docker exec 389ds ldapmodify -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W -f aci-config.ldif
```

## Проверка ACI

```bash
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W \
  -b "dc=test,dc=local" -A aci
```

> **Примечание:** ACI реплицируются между серверами вместе с данными.
