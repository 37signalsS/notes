# Управление доступом (ACI) в 389DS

## Определения

**ACI (Access Control Instructions)** — основной механизм управления доступом в 389 Directory Server. В отличие от OpenLDAP, где права обычно хранятся в конфигурации сервера (`cn=config`), ACI в 389DS являются значениями атрибута `aci` (тип `DirectoryString`) самих записей в дереве LDAP. Это делает политику распределенной и переносимой вместе с данными.

**Target** — объект, на который распространяется действие правила. Может быть DN записи, набором атрибутов или LDAP-фильтром.
  - `target` — DN целевой записи или ветки в формате `ldap:///DN`.
  - `targetattr` — список атрибутов (например, `targetattr="attr1 || attr2"`). Символ `||` означает логическое ИЛИ. Значение `*` охватывает все **пользовательские** атрибуты (операционные атрибуты, такие как `creatorsName` или `entryUUID`, не включаются).
  - `targetfilter` — LDAP-фильтр для выбора объектов (например, `targetfilter="(objectClass=person)"`).
  - `targetscope` — область действия (`base`, `one`, `subtree`). По умолчанию `subtree`.
  - `targattrfilters` — фильтрация доступа на основе *значений* атрибутов при операциях записи/добавления.

**Permission** — разрешенное или запрещенное действие.
- `read`, `search`, `compare` — чтение и поиск.
- `write`, `add`, `delete` — модификация структуры и данных.
- `selfwrite` — право добавлять/удалять свой собственный DN из списков (например, в группах).
- `proxy` — право выполнять операции от имени другого пользователя (имперсонация).

**Subject** — субъект, которому предоставляются права.
- `userdn` — конкретный пользователь или список.
- `groupdn` — члены группы.
- `roledn` — пользователи с определённой ролью.
- `anyone` — анонимный доступ и все аутентифицированные пользователи.
- `self` — сам объект (для саморедактирования). Совпадает только если Bind DN в точности равен DN целевой записи.

**Bind Rule** — дополнительные условия, при которых правило вступает в силу (например, требование TLS, ограничение по IP или времени).

**acl "Name"** — уникальное имя правила в двойных кавычках. Используется в `access` логе для быстрого identification виновного правила при отладке.

**version 3.0** — обязательный префикс, указывающий версию синтаксиса ACI. Все современные правила должны начинаться с `(version 3.0; ...)`.

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

1.  **Явный запрет (Deny):** Если хотя бы одно правило `deny` совпадает с запросом (субъект, объект, действие, условия Bind Rule), доступ запрещается немедленно.
2.  **Явное разрешение (Allow):** Если правил `deny` нет, сервер ищет подходящее правило `allow`.
3.  **Запрет по умолчанию:** Если ни одно правило не разрешило доступ, он запрещается.
4.  **Наследование:** Правила, заданные на уровне `dc=example,dc=com`, применяются ко всем вложенным объектам. Более специфичные правила (ниже по дереву) дополняют или перекрывают родительские (в случае с `deny`).

### Эффективные права (Effective Rights)

В 389DS права вычисляются динамически при каждом запросе. Поскольку ACI могут быть распределены по всему дереву, расчет итоговых прав (Effective Rights) является ресурсоемкой операцией.
Сервер использует кэширование ACL (`acl` plugin cache) для оптимизации, но при большом количестве сложных ACI производительность поиска может снизиться. Изменения ACI обычно применяются сразу, но кэш может иметь задержку на несколько секунд.

Для отладки используется расширение `getEffectiveRights` (OID `1.3.6.1.4.1.42.2.27.9.5.2`). Ответ содержит атрибут `effectiveRights` с флагами:
- `r` — read
- `s` — search
- `c` — compare
- `w` — write
- `x` — add
- `d` — delete

Если флаг отсутствует, соответствующее действие запрещено.

### Синтаксис и структура ACI

```text
aci: (target="ldap:///DN")(targetattr="attr1 || attr2")(version 3.0; acl "Name"; permission subject bind_rule;)
```

**Основные компоненты:**

- **target**: Принимает DN в формате URL (`ldap:///ou=people,dc=example,dc=com`) или `target="none"` для правил, применимых ко всему дереву.
- **targetattr**: Список атрибутов через `||` (OR). Экранирование специальных символов (`*`, `(`, `)`) в именах атрибутов не требуется, если они не используются как операторы.
- **targetfilter**: Стандартный LDAPv3 фильтр в скобках.
- **version 3.0**: Обязательный префикс. После него идет `acl "Name"`, затем список `permission`, `subject` и `bind_rule`, разделенных точкой с запятой. В конце обязательно `;`.

**Основные параметры Bind Rule:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `ssf` | Уровень безопасности (TLS) | `ssf >= 128` |
| `ip` | Ограничение по IP-адресу | `ip = "192.168.1.*"` |
| `dns` | Ограничение по доменному имени | `dns = "*.example.com"` |
| `timeofday` | Время доступа (HHMM) | `timeofday >= "0800" and timeofday <= "1800"` |
| `dayofweek` | Дни недели | `dayofweek = "Mon, Tue, Wed, Thu, Fri"` |

### Продвинутые техники

- **Macro ACIs:** Позволяют использовать переменные в DN. Например, `($dn)` подставляет DN текущего пользователя. Это полезно для создания универсальных правил для множества однотипных веток. Макросы также могут ссылаться на атрибуты записи: `($attr.uid)`.
- **Targattrfilters:** Позволяют фильтровать доступ на основе *значений* атрибутов. Например, разрешить пользователям службы поддержки менять статус только на `inactive` или `locked`. Синтаксис: `"add=attr:(value1||value2),delete=attr:(value3)"`.

## Практические сценарии

### Предварительные требования

Перед применением ACI убедитесь, что выполнены следующие условия:

- **Версия сервера:** 389DS 3.1 или выше (современный синтаксис `dsconf` и поддержка LMDB).
- **Инструменты:**
  - `dsconf` — для управления ACI в production (входит в пакет `389-ds-base`).
  - `ldapsearch`, `ldapmodify` — для отладки и bulk-операций (входят в `openldap-clients`).
  - `ldapvi` или `apache-directory-studio` — для визуального редактирования (опционально).
- **Доступ:** Учетные данные `cn=Directory Manager` или другой Bind DN с правами на запись в атрибут `aci` целевой записи.
- **Сеть:** Доступность портов 3389 (LDAP) и 3636 (LDAPS). Для отладки SSF требуется настроенный TLS.
- **Состояние сервера:** Инстанс запущен и отвечает на запросы. Суффикс и OU-структура (`ou=people`, `ou=groups`) созданы.

### Настройка безопасного анонимного чтения (Root DSE)

В современных версиях 389DS рекомендуется ограничивать анонимный доступ только базовой информацией о сервере.

**LDIF:**

```ldif
dn: dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///dc=example,dc=com")(targetattr="objectClass || commonName || surfacingName")
  (version 3.0; acl "Limited anonymous read";
  allow (read, search, compare) userdn="ldap:///anyone";)
```

**Через dsconf:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost aci add "dc=example,dc=com" \
  --name "Limited anonymous read" \
  --type "allow" \
  --permission "read,search,compare" \
  --userdn "ldap:///anyone" \
  --targetattr "objectClass || commonName || surfacingName"
```

**Валидация:**

```bash
ldapsearch -x -H ldap://localhost -b "dc=example,dc=com" "(objectClass=*)"
# Ожидается: запись возвращается, но чувствительные атрибуты (userPassword) скрыты.
```

### Разрешение пользователю редактировать свои данные через TLS

Использование `ssf >= 128` гарантирует, что пароли и личные данные не будут переданы в открытом виде.

**LDIF:**

```ldif
dn: ou=people,dc=example,dc=com
changetype: modify
add: aci
aci: (targetattr = "userPassword || telephonenumber || description")
  (version 3.0; acl "Self-edit with TLS";
  allow (write) userdn="ldap:///self" and ssf >= 128;)
```

**Через dsconf:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost aci add "ou=people,dc=example,dc=com" \
  --name "Self-edit with TLS" \
  --type "allow" \
  --permission "write" \
  --userdn "ldap:///self" \
  --ssf 128 \
  --targetattr "userPassword || telephonenumber || description"
```

**Валидация:**

```bash
# Попытка изменить свой номер без TLS — должна быть отклонена
ldapsearch -x -H ldap://localhost -D "uid=jdoe,ou=people,dc=example,dc=com" -w password \
  -b "uid=jdoe,ou=people,dc=example,dc=com" "(objectClass=*)"
# С использованием STARTTLS
ldapsearch -ZZ -x -H ldap://localhost -D "uid=jdoe,ou=people,dc=example,dc=com" -w password \
  -b "uid=jdoe,ou=people,dc=example,dc=com" "(objectClass=*)"
```

### Использование макросов для управления домашними ветками

Правило разрешает любому пользователю полный доступ к своей собственной ветке в `ou=personal`.

**LDIF:**

```ldif
dn: ou=personal,dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///uid=($dn),ou=personal,dc=example,dc=com")
  (targetattr="*")
  (version 3.0; acl "Personal branch management";
  allow (all) userdn="ldap:///self";)
```

**Важно:** Макрос `($dn)` подставляет полный DN пользователя, выполнившего bind. Правило работает только если DN пользователя попадает под `target`. Для операций добавления новых записей в `ou=personal` может потребоваться дополнительное правило, так как `target` проверяется против существующего DN.

**Через dsconf:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost aci add "ou=personal,dc=example,dc=com" \
  --name "Personal branch management" \
  --type "allow" \
  --permission "all" \
  --userdn "ldap:///self" \
  --target "ldap:///uid=($dn),ou=personal,dc=example,dc=com" \
  --targetattr "*"
```

### Ограничение доступа администраторов по сети

Разрешить группе `Directory Administrators` полный доступ, но только из внутренней сети.

**LDIF:**

```ldif
dn: dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///dc=example,dc=com")(targetattr="*")
  (version 3.0; acl "Internal admin access";
  allow (all) groupdn="ldap:///cn=Directory Administrators,ou=groups,dc=example,dc=com" and ip = "10.0.0.*";)
```

**Через dsconf:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost aci add "dc=example,dc=com" \
  --name "Internal admin access" \
  --type "allow" \
  --permission "all" \
  --groupdn "ldap:///cn=Directory Administrators,ou=groups,dc=example,dc=com" \
  --ip "10.0.0.*" \
  --targetattr "*"
```

### Тонкая фильтрация значений (targattrfilters)

Разрешить пользователям службы поддержки (`ou=support`) менять статус аккаунта только на `inactive` или `locked`.

**LDIF:**

```ldif
dn: ou=people,dc=example,dc=com
changetype: modify
add: aci
aci: (targetattr="nsAccountLock")
  (targattrfilters="add=nsAccountLock:(nsAccountLock=true),delete=nsAccountLock:(nsAccountLock=true)")
  (version 3.0; acl "Support can only lock accounts";
  allow (write) groupdn="ldap:///cn=Support,ou=groups,dc=example,dc=com";)
```

**Важно:** `targattrfilters` работает только для операций `add` и `delete` (указание значения при создании или удалении атрибута). Для операции `replace` (изменение значения) фильтр не применяется. Чтобы ограничить изменение на конкретные значения, используйте `targetfilter` в связке с deny-правилом или реализуйте проверку на уровне приложения.

**Через dsconf:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost aci add "ou=people,dc=example,dc=com" \
  --name "Support can only lock accounts" \
  --type "allow" \
  --permission "write" \
  --groupdn "ldap:///cn=Support,ou=groups,dc=example,dc=com" \
  --targetattr "nsAccountLock" \
  --targattrfilters "add=nsAccountLock:(nsAccountLock=true),delete=nsAccountLock:(nsAccountLock=true)"
```

### Предоставление прав Proxy

Разрешить приложению (Bind DN приложения) выполнять поиск от имени любого пользователя. Это часто требуется для интеграции с внешними системами авторизации.

**LDIF:**

```ldif
dn: dc=example,dc=com
changetype: modify
add: aci
aci: (target="ldap:///dc=example,dc=com")
  (version 3.0; acl "App proxy rights";
  allow (proxy) userdn="ldap:///uid=auth-app,ou=services,dc=example,dc=com";)
```

**Через dsconf:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost aci add "dc=example,dc=com" \
  --name "App proxy rights" \
  --type "allow" \
  --permission "proxy" \
  --userdn "ldap:///uid=auth-app,ou=services,dc=example,dc=com"
```

**Валидация:**

```bash
# Проверка proxy от имени пользователя
ldapsearch -x -H ldap://localhost -D "uid=auth-app,ou=services,dc=example,dc=com" -w secret \
  -U "uid=jdoe,ou=people,dc=example,dc=com" \
  -b "dc=example,dc=com" "(objectClass=*)"
```

### Управление ACI через dsconf

Современный способ управления 389DS — утилита `dsconf`. Она обеспечивает идемпотентность и проверку синтаксиса на стороне клиента.

```bash
# Просмотр всех ACI в суффиксе
dsconf -D "cn=Directory Manager" ldap://localhost aci list "dc=example,dc=com"

# Добавление ACI (упрощенный пример)
dsconf -D "cn=Directory Manager" ldap://localhost aci add "dc=example,dc=com" \
  --name "Allow Search" --type "allow" --permission "search" --userdn "ldap:///anyone"

# Удаление ACI по имени
dsconf -D "cn=Directory Manager" ldap://localhost aci delete "dc=example,dc=com" --name "Allow Search"

# Проверка синтаксиса ACI в файле перед импортом
# dsconf не имеет встроенного линтера, используйте пробный импорт на тестовом инстансе
ldapmodify -x -H ldap://localhost -D "cn=Directory Manager" -W -c -f /tmp/aci.ldif
```

**Идемпотентность:** `dsconf aci add` проверяет наличие ACI с таким же именем. Если правило существует, команда завершится ошибкой. Для обновления используйте `aci replace` или удалите старое правило через `aci delete` перед добавлением.

### Проверка эффективных прав (Effective Rights)

Для отладки сложных правил используйте расширение `getEffectiveRights`. Оно позволяет увидеть "глазами сервера", какие права реально есть у пользователя.

```bash
# Проверить, какие права имеет пользователь на конкретную запись
ldapsearch -H ldap://localhost -D "cn=Directory Manager" -W \
  -b "uid=jdoe,ou=people,dc=example,dc=com" \
  -x "(objectClass=*)" \
  "aclRights" "effectiveRights"

# → result:
# dn: uid=jdoe,ou=people,dc=example,dc=com
# control: 1.3.6.1.4.1.42.2.27.9.5.2 false 
# effectiveRights: rscxd
```

**Расшифровка флагов:** `r` (read), `s` (search), `c` (compare), `x` (add), `d` (delete). Если флаг `w` присутствует, это означает право на запись (write/modify).

**Валидация в скриптах:**

```bash
# Проверка, что у пользователя есть право на чтение атрибута userPassword
RESULT=$(ldapsearch -x -H ldap://localhost -D "cn=Directory Manager" -W \
  -b "uid=jdoe,ou=people,dc=example,dc=com" \
  "(objectClass=*)" effectiveRights 2>/dev/null)

if echo "$RESULT" | grep -q 'effectiveRights:.*r'; then
  echo "OK: read allowed"
else
  echo "FAIL: read denied"
fi
```

### Резервное копирование и восстановление ACI

Поскольку ACI хранятся как атрибуты записей, их можно экспортировать стандартными средствами LDAP и хранить в системе контроля версий.

**Экспорт ACI суффикса:**

```bash
ldapsearch -x -H ldap://localhost -D "cn=Directory Manager" -W \
  -b "dc=example,dc=com" \
  "(aci=*)" dn aci > /backup/aci-backup-$(date +%Y%m%d).ldif
```

**Восстановление из бэкапа:**

```bash
ldapmodify -x -H ldap://localhost -D "cn=Directory Manager" -W \
  -c -f /backup/aci-backup-20240101.ldif
```

**Важно:** Используйте флаг `-c` (continue on error), чтобы пропустить записи, которые уже содержат идентичные ACI. Храните LDIF-файлы в Git для отслеживания изменений. Это позволяет откатить политику до предыдущего состояния в случае ошибки.

### Массовое применение ACI

Для окружений с большим количеством OU или суффиксов используйте скрипты. Ниже пример на bash с циклом по списку OU:

```bash
#!/bin/bash
BASE_DN="dc=example,dc=com"
OUs=("ou=people" "ou=groups" "ou=services" "ou=contractors")

for ou in "${OUs[@]}"; do
  DN="$ou,$BASE_DN"
  dsconf -D "cn=Directory Manager" ldap://localhost aci add "$DN" \
    --name "Self write to own entry" \
    --type "allow" \
    --permission "selfwrite" \
    --userdn "ldap:///self" \
    --ssf 128 || echo "Warning: ACI might already exist on $DN"
done
```

Для более сложной логики (например, условное применение правил) используйте Python с библиотекой `ldap3`:

```python
from ldap3 import Server, Connection, MOD_ADD, ALL

server = Server('ldap://localhost')
conn = Connection(server, user='cn=Directory Manager', password='secret', auto_bind=True)

aci_value = (
    '(target="ldap:///ou=people,dc=example,dc=com")(targetattr="*")'
    '(version 3.0; acl "DevOps bulk rule"; allow (all) userdn="ldap:///self";)'
)

conn.modify('ou=people,dc=example,dc=com', {'aci': [(MOD_ADD, [aci_value])]})
print(conn.result)
```

## Дополнительная информация

### Аудит и логирование ACI

Все отказы в доступе (`Insufficient Access`) фиксируются в `access` логе сервера.

1.  **Access Log:** Ищите записи с кодом `err=50`. Если в ACI задано имя (`acl "Name"`), оно указывается в логе для облегчения поиска виновного правила. В 389DS 3.x логи поддерживают JSON-формат, что удобно для парсинга (например, через `jq`).
2.  **Audit Log:** При включенном аудите все изменения атрибута `aci` (добавление/удаление правил) записываются в `audit` лог с указанием того, кто и когда внес изменения. Убедитесь, что `nsslapd-auditlog` включен, если требуется соответствие compliance.
3.  **LogLevel:** Для глубокой отладки можно временно повысить уровень логирования ACL (параметр `nsslapd-accesslog-level` в `cn=config`), но это существенно замедляет сервер и создает большой объем логов. Возвращайте уровень к `0` (или `4` по умолчанию) после завершения диагностики.

```bash
# Включить отладочное логирование ACL временно
dsconf -D "cn=Directory Manager" ldap://localhost config replace nsslapd-accesslog-level=256

# ... выполнить диагностические запросы ...

# Вернуть стандартный уровень
dsconf -D "cn=Directory Manager" ldap://localhost config replace nsslapd-accesslog-level=4
```

### Рекомендации (Best Practices)

1.  **Приоритет Allow:** Старайтесь строить политику на разрешающих правилах. Используйте `deny` только в исключительных случаях, так как он перекрывает всё и его сложно отлаживать.
2.  **Security Strength Factor (SSF):** Всегда требуйте TLS (`ssf >= 128`) для операций записи и аутентификации.
3.  **Имена ACI:** Всегда давайте осмысленные имена в поле `acl ""`. Это критично для аудита и логирования (пакет `389-ds-base` пишет имя ACI в `access` лог при отказах).
4.  **Минимизация Target:** Не вешайте ACI с `targetattr="*"` на корень дерева без необходимости. Это может привести к утечке системных атрибутов и снижению производительности.
5.  **Тестирование:** Используйте `ldapsearch` с атрибутом `effectiveRights` перед применением правил в продакшн. Тестируйте от Bind DN обычного пользователя, а не только `cn=Directory Manager`.
6.  **Версионность:** Храните ACI в виде LDIF в Git. Используйте `dsconf aci list ... > aci.ldif` для регулярного бэкапа.
7.  **Идемпотентность:** Для автоматизации (Ansible, Puppet, Chef) используйте `dsconf` вместо сырых `ldapmodify`, так как `dsconf` корректно обрабатывает повторный запуск.

### Troubleshooting

| Ошибка / Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Insufficient access` | Нет подходящего `allow` или сработал `deny` | Проверьте `effectiveRights` для целевого DN |
| `Invalid syntax` | Ошибка в скобках или кавычках ACI | Проверьте синтаксис: все компоненты должны быть в скобках, `version 3.0` обязателен |
| ACI не наследуется | Используется `target` с конкретным DN | Проверьте, что `target` не ограничивает область действия слишком сильно |
| Ошибка TLS (SSF) | Клиент подключен без шифрования | Используйте `ldaps://` или `STARTTLS` (`-ZZ`) |
| `No such object` (dsconf) | DN не существует или опечатка в суффиксе | Проверьте DN через `ldapsearch -x -b "" -s base "(objectClass=*)"` |
| `Constraint violation` | Неверный синтаксис ACI или экранирование | Проверьте кавычки и спецсимволы в LDIF |
| `effectiveRights` пустой | У пользователя нет права на чтение самой записи | Effective Rights требует `read` на запись для возврата данных |
| `proxy` не работает | ACI на `proxy` есть, но нет права на чтение целевого атрибута | `proxy` дает только возможность выполнить операцию; права на доступ к данным все еще проверяются |
| Изменения ACI не видны | Кэш ACL не обновился | Подождите несколько секунд или перезапустите инстанс (`dsctl localhost restart`) |

### Репликация ACI

ACI хранятся в атрибуте `aci`, который является обычным атрибутом записи. Это означает:
- ACI реплицируются автоматически вместе с данными в Multi-Master окружении.
- Конфликты репликации разрешаются по стандартным правилам (последняя запись побеждает, сравнение по CSN).
- Настройка прав на одном мастере применится ко всему кластеру.
- **Важно:** При репликации убедитесь, что все мастера имеют одинаковые плагины ACI и ACL. Различия в версиях могут привести к неожиданному поведению Effective Rights.

### Ограничения и edge cases

- **Операционные атрибуты:** `targetattr="*"` никогда не включает операционные атрибуты (`creatorsName`, `modifiersName`, `entryUUID`, `entryCSN`). Для управления доступом к ним нужно указывать их явно.
- **Производительность Effective Rights:** Контроль `getEffectiveRights` (OID `1.3.6.1.4.1.42.2.27.9.5.2`) вызывает полную оценку ACL для запрошенной записи. Не используйте его в высоконагруженных циклах поиска — это создает существенную нагрузку на CPU.
- **Макросы при создании записей:** При операции `add` запись еще не существует, поэтому макрос `($dn)` в `target` может не совпасть. Используйте `targetfilter` для выбора родительской ветки при добавлении.
- **Взаимодействие с MemberOf:** Плагин `MemberOf` модифицирует атрибут `member` в группе при добавлении/удалении пользователя. Если ACI запрещает запись `member` для субъекта, операция будет отклонена, даже если пользователь имеет права на изменение своей записи.
- **Self vs Selfwrite:** `self` (в subject) означает совпадение Bind DN с DN целевой записи. `selfwrite` (в permission) означает право изменять свой DN в мультизначительных атрибутах (например, удалять себя из списка `member`). Это разные концепции.
- **Размер ACI:** Теоретических лимитов на количество ACI на запись нет, но каждый ACI добавляет накладные расходы при вычислении Effective Rights. Рекомендуется не превышать 50-100 правил на узел без серьезного тестирования производительности.

### Связанные материалы

- [Обзор 389DS](./overview.md) — архитектура и основные возможности
- [Docker развёртывание](./docker.md) — запуск и базовая настройка
- [Репликация](./replication.md) — настройка Multi-Master окружения
- [Плагины](./plugins.md) — особенности работы авторизации и MemberOf
- [Интеграция с SSSD](../../Linux/SystemAdministration/Users/LDAP_SSSD/index.md) — настройка клиентов для работы с 389DS
