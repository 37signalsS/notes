# Управление доступом (ACI) в 389DS

## Определения

**ACI (Access Control Instructions)** — основной механизм управления доступом в 389 Directory Server. В отличие от OpenLDAP, где права обычно хранятся в конфигурации сервера (`cn=config`), ACI в 389DS являются атрибутами самих записей в дереве LDAP.

**Target** — объект, на который распространяется действие правила. Может быть DN записи, набором атрибутов или фильтром.

**Permission** — разрешенное или запрещенное действие (`read`, `write`, `add`, `delete`, `search`, `compare`, `selfwrite`, `proxy`).

**Subject** — субъект, которому предоставляются права (`userdn`, `groupdn`, `roledn`, `anyone`, `self`).

**Bind Rule** — дополнительные условия, при которых правило вступает в силу (например, требование TLS, ограничение по IP или времени).

## Базовые концепции

### Отличие от OpenLDAP

| Характеристика | OpenLDAP (ACL) | 389DS (ACI) |
| :--- | :--- | :--- |
| **Хранение** | Глобально в `cn=config` | В атрибутах записей (распределенно) |
| **Наследование** | Сверху вниз по списку правил | По иерархии DIT (от родителя к детям) |
| **Приоритет** | Первое совпадение | **Deny** всегда приоритетнее **Allow** |
| **Синтаксис** | Проприетарный `access to...` | Формат `(target)(version 3.0; acl...;)` |
| **Управление** | Текстовые файлы/LDIF | `dsconf`, `ldapmodify`, GUI |

### Логика обработки

1. **Явный запрет (Deny):** Если хотя бы одно правило `deny` совпадает с запросом, доступ запрещается немедленно.
2. **Явное разрешение (Allow):** Если правил `deny` нет, сервер ищет подходящее правило `allow`.
3. **Запрет по умолчанию:** Если ни одно правило не разрешило доступ, он запрещается.
4. **Наследование:** Правила, заданные на уровне `dc=example,dc=com`, применяются ко всем вложенным объектам, если они не перекрыты более специфичными правилами.

### Синтаксис ACI

```text
aci: (target="ldap:///DN")(targetattr="attr1 || attr2")(version 3.0; acl "Name"; permission subject bind_rule;)
```

**Основные параметры Bind Rule:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `ssf` | Уровень безопасности (TLS) | `ssf >= 128` |
| `ip` | Ограничение по IP-адресу | `ip = "192.168.1.*"` |
| `dns` | Ограничение по доменному имени | `dns = "*.example.com"` |
| `timeofday` | Время доступа (HHMM) | `timeofday >= "0800" and timeofday <= "1800"` |
| `dayofweek` | Дни недели | `dayofweek = "Mon, Tue, Wed, Thu, Fri"` |

### Продвинутые техники

- **Macro ACIs:** Позволяют использовать переменные в DN. Например, `($dn)` подставляет DN текущего пользователя. Это полезно для создания универсальных правил для множества однотипных веток.
- **Targattrfilters:** Позволяют фильтровать доступ на основе *значений* атрибутов. Например, разрешить пользователю менять статус только на определённые значения.

## Практические сценарии

### Настройка безопасного анонимного чтения (Root DSE)

В современных версиях 389DS рекомендуется ограничивать анонимный доступ только базовой информацией о сервере.

```ldif
dn: dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///dc=example,dc=com")(targetattr="objectClass || commonName || surfacingName")
  (version 3.0; acl "Limited anonymous read";
  allow (read, search, compare) userdn="ldap:///anyone";)
```

### Разрешение пользователю редактировать свои данные через TLS

Использование `ssf >= 128` гарантирует, что пароли и личные данные не будут переданы в открытом виде.

```ldif
dn: ou=people,dc=example,dc=com
changetype: modify
add: aci
aci: (targetattr = "userPassword || telephonenumber || description")
  (version 3.0; acl "Self-edit with TLS";
  allow (write) userdn="ldap:///self" and ssf >= 128;)
```

### Использование макросов для управления домашними ветками

Правило разрешает любому пользователю полный доступ к своей собственной ветке в `ou=personal`.

```ldif
dn: ou=personal,dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///uid=($dn),ou=personal,dc=example,dc=com")
  (targetattr="*")
  (version 3.0; acl "Personal branch management";
  allow (all) userdn="ldap:///self";)
```

### Ограничение доступа администраторов по сети

Разрешить группе `Directory Administrators` полный доступ, но только из внутренней сети.

```ldif
dn: dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///dc=example,dc=com")(targetattr="*")
  (version 3.0; acl "Internal admin access";
  allow (all) groupdn="ldap:///cn=Directory Administrators,ou=groups,dc=example,dc=com" and ip = "10.0.0.*";)
```

### Управление ACI через dsconf

Современный способ управления 389DS — утилита `dsconf`.

```bash
# Просмотр всех ACI в суффиксе
dsconf -D "cn=Directory Manager" ldap://localhost aci list "dc=example,dc=com"

# Добавление ACI (упрощенный пример)
dsconf -D "cn=Directory Manager" ldap://localhost aci add "dc=example,dc=com" \
  --name "Allow Search" --type "allow" --permission "search" --userdn "ldap:///anyone"
```

### Проверка эффективных прав (Effective Rights)

Для отладки сложных правил используйте расширение `getEffectiveRights`.

```bash
# Проверить, какие права имеет пользователь на конкретную запись
ldapsearch -H ldap://localhost -D "cn=Directory Manager" -W \
  -b "uid=jdoe,ou=people,dc=example,dc=com" \
  "(objectClass=*)" \
  "aclRights" "effectiveRights"
# → result: aclRights: read,search,compare,write,delete,add,proxy (зависит от прав)
```

## Дополнительная информация

### Рекомендации (Best Practices)

1. **Приоритет Allow:** Старайтесь строить политику на разрешающих правилах. Используйте `deny` только в исключительных случаях, так как он перекрывает всё и его сложно отлаживать.
2. **Security Strength Factor (SSF):** Всегда требуйте TLS (`ssf >= 128`) для операций записи и аутентификации.
3. **Имена ACI:** Всегда давайте осмысленные имена в поле `acl ""`. Это критично для аудита и логирования (пакет `389-ds-base` пишет имя ACI в `access` лог при отказах).
4. **Минимизация Target:** Не вешайте ACI с `targetattr="*"` на корень дерева без необходимости. Это может привести к утечке системных атрибутов.
5. **Тестирование:** Используйте `ldapsearch` с атрибутом `effectiveRights` перед применением правил в продакшн.

### Troubleshooting

| Ошибка / Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Insufficient access` | Нет подходящего `allow` или сработал `deny` | Проверьте `effectiveRights` для целевого DN |
| `Invalid syntax` | Ошибка в скобках или кавычках ACI | Проверьте синтаксис: все компоненты должны быть в скобках |
| ACI не наследуется | Используется `target` с конкретным DN | Проверьте, что `target` не ограничивает область действия слишком сильно |
| Ошибка TLS (SSF) | Клиент подключен без шифрования | Используйте `ldaps://` или `STARTTLS` |

### Репликация ACI

ACI хранятся в атрибуте `aci`, который является обычным атрибутом записи. Это означает:
- ACI реплицируются автоматически вместе с данными.
- Конфликты репликации разрешаются по стандартным правилам (последняя запись побеждает).
- Настройка прав на одном мастере применится ко всему кластеру.

### Связанные материалы

- [Обзор 389DS](./overview.md) — архитектура и основные возможности
- [Docker развёртывание](./docker.md) — запуск и базовая настройка
- [Репликация](./replication.md) — настройка Multi-Master окружения
