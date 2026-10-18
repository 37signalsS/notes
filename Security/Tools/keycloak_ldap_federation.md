# Интеграция Keycloak с LDAP/AD

**Актуально для:** Keycloak 26.x

## Определения

**Keycloak** — современная open-source система управления идентификацией и доступом (Identity and Access Management, IAM) на базе Quarkus. Обеспечивает единую точку входа (SSO), централизованную аутентификацию и авторизацию.

**User Federation (Федерация пользователей)** — механизм Keycloak, позволяющий использовать внешние каталоги (LDAP, Active Directory) как хранилище учетных записей. Пользователи проецируются в базу Keycloak при первом входе или синхронизации; пароли не хранятся в Keycloak, а проверяются через bind-запрос к LDAP.

**LDAP (Lightweight Directory Access Protocol)** — протокол прикладного уровня для доступа к распределённым службам каталогов. В контексте enterprise-сред используется для централизованного хранения учетных записей, групп и политик.

**Active Directory (AD)** — каталоговая служба Microsoft, реализующая LDAP, Kerberos и другие протоколы. Хранит данные в формате NTDS.dit, использует `sAMAccountName` как логин и `objectGUID` как уникальный идентификатор.

**Bind DN (Distinguished Name)** — DN учетной записи, используемой для аутентификации при подключении к LDAP-серверу. Например: `cn=admin,dc=example,dc=com`.

**RDN (Relative Distinguished Name)** — относительное отличительное имя, определяющее атрибут, используемый как логин внутри базового DN. Например: `uid` для OpenLDAP, `sAMAccountName` для AD.

**Mapper** — компонент Keycloak, определяющий преобразование данных между LDAP-атрибутами и полями пользователя Keycloak. Включает User Attribute Mapper, Group LDAP Mapper, Role LDAP Mapper и специализированные мапперы для AD.

**Incremental Sync** — режим синхронизации, при котором обрабатываются только изменённые записи на основе атрибута `modifyTimestamp` (OpenLDAP) или `uSNChanged` (AD).

**LDAPS** —LDAP поверх TLS/SSL (порт 636). Рекомендуется для production-сред. Требует импорта CA-сертификата в truststore Keycloak.

**StartTLS** — механика повышения безопасности незащищённого LDAP-соединения (порт 389) до зашифрованного через TLS-рукопожатие.

---

## Базовые концепции

### Архитектура User Federation

Keycloak взаимодействует с LDAP через провайдеры пользователей. Процесс аутентификации и синхронизации:

1. **Аутентификация:** Пользователь вводит логин и пароль в Keycloak. Keycloak выполняет bind-запрос к LDAP-серверу с указанным Bind DN и паролем пользователя.
2. **Импорт атрибутов:** При успешном bind-запросе Keycloak импортирует атрибуты пользователя (email, имя, фамилия) в свою локальную базу данных согласно настроенным мапперам.
3. **Кэширование:** Данные кэшируются в Keycloak для снижения нагрузки на LDAP-сервер. Время жизни кэша настраивается через параметр `Cache Policy`.
4. **Синхронизация:** Периодические задачи (full sync или incremental sync) обновляют данные между LDAP и Keycloak.

### Режимы работы (Edit Mode)

Keycloak поддерживает три режима работы с федеративными пользователями:

1. **READ_ONLY:** Пользователи аутентифицируются через LDAP, атрибуты импортируются, но изменения (смена пароля, обновление email) в Keycloak запрещены или не синхронизируются обратно. Рекомендуется для большинства production-сценариев.
2. **WRITABLE:** Позволяет создавать, изменять и удалять пользователей в LDAP непосредственно через интерфейс или API Keycloak. Требует соответствующих прав на LDAP-сервере.
3. **UNSYNCED:** Пользователи импортируются из LDAP, после чего их данные в Keycloak и LDAP живут независимо. Подходит для миграции или тестовых окружений.

> **Важно:** `Edit Mode` и переключатель `Import Users` (см. ниже) определяются при создании провайдера. Поменять `Edit Mode` позже нельзя — Keycloak не перенастраивает мапперы автоматически. Решайте режим заранее.

### Хранилище и режим импорта (Import Users)

`Import Users` (Storage mode) определяет, сохраняет ли Keycloak копию пользователя в локальной базе:

- **Import Users = OFF (federated):** пользователи не кэшируются в БД Keycloak; каждый поиск и bind выполняются напрямую к LDAP. Меньший объём данных в Keycloak, но выше задержка и большая нагрузка на каталог. Подходит, когда LDAP — единственный источник правды.
- **Import Users = ON:** при первом входе или синхронизации атрибуты пользователя копируются в БД Keycloak (по мапперам). Последующие запросы читаются из локальной БД; LDAP задействуется только для проверки пароля и инкрементной синхронизации. Быстрее, но требует периодической синхронизации (`fullSyncPeriod`/`changedSyncPeriod`).

Мапперы создаются автоматически по комбинации `Vendor` + `Edit Mode` + `Import Users`; их можно дорогостить или заменить вручную (см. раздел "Работа с мапперами").

### Поддерживаемые провайдеры

Keycloak оптимизирован под следующие реализации:

- **Active Directory:** Специальный вендор с поддержкой специфичных атрибутов (`userAccountControl`, `objectGUID`).
- **OpenLDAP:** Универсальный провайдер (Generic LDAP).
- **Red Hat Directory Server / 389 Directory Server.**
- **Novell eDirectory / Tivoli Directory Server.**

---

## Практические сценарии

### Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| **Keycloak** | v26+ на базе Quarkus (Decode UUID для `objectGUID` в AD включён по умолчанию начиная с 26.6.x) |
| **LDAP/AD сервер** | Работающий сервер с доступом по портам 389 (LDAP/StartTLS) или 636 (LDAPS) |
| **Сеть** | Открытые порты между Keycloak и LDAP-сервером; для LDAPS — порт 636/TCP |
| **Учетная запись** | Bind DN с правами на поиск (search) в базовом DN пользователей и групп |
| **Truststore** | CA-сертификат LDAPS-сервера импортирован в truststore Keycloak (если используется LDAPS) |
| **Права на запись** | Для режима WRITABLE — учетная запись с правами на создание/изменение записей в LDAP |

### Настройка через Admin Console

#### Шаги настройки

1. **Создание Realm:** В Keycloak создать новый Realm или выбрать существующий.
2. **Добавление провайдера:** Перейти в раздел **User Federation** → **Add provider** → **ldap**.
3. **Настройка подключения:** Заполнить параметры подключения (см. таблицу ниже).
4. **Настройка мапперов:** Добавить мапперы для атрибутов пользователя, групп и ролей.
5. **Проверка соединения:** Нажать **Test connection** и **Test authentication** для валидации параметров.
6. **Синхронизация:** Запустить **Full Sync** для первичного импорта пользователей.

#### Параметры подключения

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Vendor** | `Active Directory` / `Other` | Выбор оптимизаций под конкретный сервер. |
| **Connection URL** | `ldaps://ldap.example.com:636` | Протокол и адрес сервера. Использование LDAPS крайне рекомендуется. |
| **Bind DN** | `cn=admin,dc=example,dc=com` | Учетная запись для выполнения запросов поиска. |
| **Bind Credentials** | `********` | Пароль для Bind DN. |
| **Truststore SPI** | `Only for ldaps` | Использование глобального хранилища сертификатов Keycloak. |
| **Connection Timeout** | `5000` (мс) | Время ожидания ответа от сервера. |

#### Параметры поиска пользователей

| Параметр | Значение (OpenLDAP) | Значение (AD) | Описание |
| :--- | :--- | :--- | :--- |
| **Users DN** | `ou=users,dc=ex,dc=com` | `cn=users,dc=corp` | Базовая точка поиска пользователей. |
| **Username LDAP Attribute** | `uid` | `sAMAccountName` | Атрибут, используемый как логин. |
| **RDN LDAP Attribute** | `uid` | `cn` | Атрибут относительного отличительного имени. |
| **UUID LDAP Attribute** | `entryUUID` | `objectGUID` | Уникальный идентификатор записи. |
| **User Object Classes** | `inetOrgPerson, posixAccount` | `person, user` | Список объектных классов пользователя. |
| **User LDAP Filter** | `(memberOf=cn=dev,...)` | `(objectClass=user)` | Дополнительный фильтр для ограничения выборки. |

#### Другие параметры конфигурации

Помимо параметров подключения и поиска, провайдер LDAP имеет параметры синхронизации, кэширования и поведения.
Ключи конфигурации соответствуют значениям, с которыми Keycloak создаёт компонент (заглавная `LDAP`
в атрибутах UUID, например `uuidLDAPAttribute`/`usernameLDAPAttribute`/`rdnLDAPAttribute`); регистр важен —
`LDAPConfig` читает их чувствительно к регистру. Задавать можно через Admin Console, Admin API или импорт realm.

| Параметр (Admin API) | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **editMode** | `READ_ONLY` | `READ_ONLY` / `WRITABLE` / `UNSYNCED`. Определяется при создании провайдера. |
| **importEnabled** (Import Users) | `true` | `true` — пользователи копируются в БД Keycloak; `false` — "федеративные", ищутся в LDAP напрямую. |
| **syncRegistrations** | `false` | `true` — новые пользователи, созданные в Keycloak, создаются в LDAP. Требует `WRITABLE`. |
| **fullSyncPeriod** | `-1` | Период (сек) полной синхронизации. `-1` отключает периодический full sync. |
| **changedSyncPeriod** | `-1` | Период (сек) инкрементной синхронизации (только изменённые). `-1` отключает. |
| **batchSizeForSync** | `1000` | Количество записей за одну транзакцию синхронизации. |
| **searchScope** | `1` | `1` — один уровень (children of Users DN); `2` — поддерево (subtree); `0` — объект. |
| **pagination** | `true` | Использовать LDAP pagination (RFC 2696) для больших каталогов. |
| **connectionPooling** | `true` | Включить пул соединений (настраивается JVM-свойствами, см. ниже). |
| **cachePolicy** | `DEFAULT` | `NO_CACHE` / `DEFAULT` / `EVICT_DAILY` / `EVICT_WEEKLY` / `MAX_LIFESPAN`. |
| **priority** | `0` | Приоритет провайдера при поиске пользователя (меньше = выше приоритет для чтения, но используется как fallback). |
| **trustEmail** | `false` | Доверять email из LDAP без верификации. |
| **validatePasswordPolicy** | `false` | Проверять пароль по политике Keycloak перед изменением в LDAP. |
| **usePasswordModifyExtendedOp** | `false` | Использовать extended-операцию изменения пароля (RFC 3062). |

> **Примечание про `-1`:** значение `-1` для `fullSyncPeriod`/`changedSyncPeriod` отключает периодическую синхронизацию. Такой провайдер синхронизируется только по вручную запущенным задачам (через Admin Console или Admin API).

### Настройка через Admin API (REST)

Для автоматизации и управления конфигурацией LDAP Federation используйте Admin API Keycloak (REST).

#### Получение токена администратора

```bash
# Получение access token для admin-cli
KEYCLOAK_URL="https://keycloak.example.com"
ADMIN_USER="admin"
ADMIN_PASS="admin-password"

TOKEN=$(curl -s -X POST "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" \
  -d "username=${ADMIN_USER}" \
  -d "password=${ADMIN_PASS}" | jq -r '.access_token')
```

#### Создание LDAP провайдера через Admin API

```bash
REALM="myrealm"

curl -s -X POST "${KEYCLOAK_URL}/admin/realms/${REALM}/components" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ldap",
    "providerType": "org.keycloak.storage.UserStorageProvider",
    "providerId": "ldap",
    "subType": "user",
    "config": {
      "priority": ["1"],
      "vendor": ["ad"],
      "connectionUrl": ["ldaps://ldap.corp.example.com:636"],
      "bindDn": ["cn=svc-keycloak,ou=service,dc=corp,dc=example,dc=com"],
      "bindCredential": ["S3cureP@ss!"],
      "usersDn": ["cn=users,dc=corp,dc=example,dc=com"],
      "usernameLDAPAttribute": ["sAMAccountName"],
      "rdnLDAPAttribute": ["cn"],
      "uuidLDAPAttribute": ["objectGUID"],
      "userObjectClasses": ["person, user"],
      "editMode": ["READ_ONLY"],
      "importEnabled": ["true"],
      "syncRegistrations": ["false"],
      "pagination": ["true"],
      "connectionPooling": ["true"],
      "searchScope": ["2"],
      "fullSyncPeriod": ["-1"],
      "changedSyncPeriod": ["3600"],
      "batchSizeForSync": ["1000"],
      "cachePolicy": ["DEFAULT"],
      "trustEmail": ["false"],
      "validatePasswordPolicy": ["false"],
      "usePasswordModifyExtendedOp": ["false"],
      "connectionTimeout": ["5000"],
      "useTruststoreSpi": ["ldapsOnly"]
    }
  }'
# → 201 Created
```

#### Создание мапперов через Admin API

```bash
# Создание User Attribute Mapper для email
curl -s -X POST "${KEYCLOAK_URL}/admin/realms/${REALM}/components" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "email",
    "providerType": "org.keycloak.storage.ldap.mappers.LDAPStorageMapper",
    "providerId": "user-attribute-ldap-mapper",
    "parentId": "<ldap_provider_id>",
    "config": {
      "ldap.attribute": ["mail"],
      "user.model.attribute": ["email"],
      "is.mandatory.in.ldap": ["false"],
      "read.only": ["true"]
    }
  }'
# → 201 Created
```

### Валидация подключения

#### Проверка через Admin API

```bash
# Проверка статуса провайдера
curl -s -X GET "${KEYCLOAK_URL}/admin/realms/${REALM}/components?type=org.keycloak.storage.UserStorageProvider" \
  -H "Authorization: Bearer ${TOKEN}" | jq '.[] | {name, providerId, config}'

# Проверка количества импортированных пользователей
curl -s -X GET "${KEYCLOAK_URL}/admin/realms/${REALM}/users?first=0&max=0" \
  -H "Authorization: Bearer ${TOKEN}" | jq '.total'
# → {"total": 1500}
```

#### Проверка через `ldapsearch`

```bash
# Проверка доступности LDAP-сервера
ldapsearch -x -H ldaps://ldap.corp.example.com:636 \
  -D "cn=svc-keycloak,ou=service,dc=corp,dc=example,dc=com" \
  -w "S3cureP@ss!" \
  -b "cn=users,dc=corp,dc=example,dc=com" \
  "(sAMAccountName=testuser)" mail givenName sn
# → dn: CN=Test User,CN=Users,DC=corp,DC=example,DC=com
# →  mail: testuser@example.com
# →  givenName: Test
# →  sn: User
```

#### Проверка аутентификации через Keycloak

```bash
# Получение токена для федеративного пользователя
curl -s -X POST "${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" \
  -d "username=testuser" \
  -d "password=LDAP-Password123!" | jq .
# → Должен вернуть access_token при успешной аутентификации
```

### Автоматизация

#### Ansible: настройка LDAP Federation

```yaml
# tasks/keycloak_ldap_federation.yml
- name: "Получение admin токена Keycloak"
  uri:
    url: "{{ keycloak_url }}/realms/master/protocol/openid-connect/token"
    method: POST
    body:
      grant_type: "password"
      client_id: "admin-cli"
      username: "{{ keycloak_admin }}"
      password: "{{ keycloak_admin_password }}"
    body_format: form-urlencoded
  register: keycloak_token

- name: "Создание LDAP User Federation провайдера"
  uri:
    url: "{{ keycloak_url }}/admin/realms/{{ realm }}/components"
    method: POST
    headers:
      Authorization: "Bearer {{ keycloak_token.json.access_token }}"
      Content-Type: "application/json"
    body:
      name: "ldap"
      providerType: "org.keycloak.storage.UserStorageProvider"
      providerId: "ldap"
      subType: "user"
      config:
        priority: ["1"]
        vendor: ["ad"]
        connectionUrl: ["ldaps://{{ ldap_host }}:636"]
        bindDn: ["{{ ldap_bind_dn }}"]
        bindCredential: ["{{ ldap_bind_password }}"]
        usersDn: ["{{ ldap_users_dn }}"]
        usernameLDAPAttribute: ["sAMAccountName"]
        rdnLDAPAttribute: ["cn"]
        uuidLDAPAttribute: ["objectGUID"]
        userObjectClasses: ["person, user"]
        editMode: ["READ_ONLY"]
        importEnabled: ["true"]
        syncRegistrations: ["false"]
        connectionTimeout: ["5000"]
        useTruststoreSpi: ["ldapsOnly"]
    status_code: 201
    register: ldap_provider

- name: "Создание User Attribute Mapper (email)"
  uri:
    url: "{{ keycloak_url }}/admin/realms/{{ realm }}/components"
    method: POST
    headers:
      Authorization: "Bearer {{ keycloak_token.json.access_token }}"
      Content-Type: "application/json"
    body:
      name: "email"
      providerType: "org.keycloak.storage.ldap.mappers.LDAPStorageMapper"
      providerId: "user-attribute-ldap-mapper"
      parentId: "{{ ldap_provider.json.id }}"
      config:
        ldap.attribute: ["mail"]
        user.model.attribute: ["email"]
        is.mandatory.in.ldap: ["false"]
        read.only: ["true"]
    status_code: 201

- name: "Запуск Full Sync"
  uri:
    url: "{{ keycloak_url }}/admin/realms/{{ realm }}/user-storage/{{ ldap_provider.json.id }}/sync?action=triggerFullSync"
    method: POST
    headers:
      Authorization: "Bearer {{ keycloak_token.json.access_token }}"
    status_code: 200
    return_content: true
  register: sync_result
# sync_result.content → {"added":N,"updated":N,"removed":N,"failed":N,"ignored":N,"status":"..."}
```

#### SaltStack: валидация параметров

```yaml
# salt/keycloak/ldap.sls
keycloak_ldap_provider:
  http.query:
    - name: "{{ pillar['keycloak_url'] }}/admin/realms/{{ pillar['realm'] }}/components"
    - method: POST
    - header:
        Authorization: "Bearer {{ pillar['admin_token'] }}"
        Content-Type: "application/json"
    - data:
        name: "ldap"
        providerType: "org.keycloak.storage.UserStorageProvider"
        providerId: "ldap"
        config:
          priority: ["1"]
          vendor: ["ad"]
          connectionUrl: ["ldaps://{{ pillar['ldap_host'] }}:636"]
          bindDn: ["{{ pillar['ldap_bind_dn'] }}"]
          bindCredential: ["{{ pillar['ldap_bind_password'] }}"]
          usersDn: ["{{ pillar['ldap_users_dn'] }}"]
          usernameLDAPAttribute: ["sAMAccountName"]
          rdnLDAPAttribute: ["cn"]
          uuidLDAPAttribute: ["objectGUID"]
          userObjectClasses: ["person, user"]
    - status_code: 201
```

### Мониторинг и health checks

#### Проверка доступности LDAP-сервера

```bash
# Проверка порта LDAPS
nc -zv ldap.corp.example.com 636
# → Connection to ldap.corp.example.com 636 port [tcp/ldaps] succeeded!

# Проверка через ldapsearch с таймаутом
timeout 5 ldapsearch -x -H ldaps://ldap.corp.example.com:636 \
  -D "cn=svc-keycloak,ou=service,dc=corp,dc=example,dc=com" \
  -w "S3cureP@ss!" \
  -b "cn=users,dc=corp,dc=example,dc=com" \
  "(sAMAccountName=testuser)" 1.1
# → dn: CN=Test User,...
```

#### Мониторинг через Keycloak Admin API

```bash
# Проверка статуса и времени последней синхронизации провайдера
PROVIDER_ID=$(curl -s -X GET "${KEYCLOAK_URL}/admin/realms/${REALM}/components?type=org.keycloak.storage.UserStorageProvider" \
  -H "Authorization: Bearer ${TOKEN}" | jq -r '.[] | select(.providerId == "ldap") | .id')

curl -s -X GET "${KEYCLOAK_URL}/admin/realms/${REALM}/components/${PROVIDER_ID}" \
  -H "Authorization: Bearer ${TOKEN}" | jq '.config | {lastSync, fullSyncPeriod, changedSyncPeriod, batchSizeForSync, cachePolicy}'
# → {"lastSync":"1716367385","fullSyncPeriod":["-1"],"changedSyncPeriod":["3600"], ...}
```

#### Prometheus-метрики

Метрики включаются опцией `--metrics-enabled=true` (или env `KC_METRICS_ENABLED=true`).
`keycloak.conf` использует формат `key=value` (не YAML):

```bash
# keycloak.conf
metrics-enabled=true

# либо CLI при старте
/opt/keycloak/bin/kc.sh start --metrics-enabled=true --health-enabled=true
```

Метрики Keycloak открываются на **интерфейсе управления** по пути `/metrics`
(порт интерфейса управления задаётся параметром `--http-management-port`, по умолчанию **9000**).
Формат ответа — OpenMetrics/Prometheus (`application/openmetrics-text`).

LDAP-метрика, зарегистрированная в `org.keycloak.storage.ldap.LDAPStorageProviderFactory` — таймер запросов:

```bash
curl -s http://localhost:9000/metrics | grep -i "keycloak_ldap_requests"
# → # TYPE keycloak_ldap_requests_seconds counter
# → keycloak_ldap_requests_seconds_count{...} 1523
# → keycloak_ldap_requests_seconds_sum{...} 4.5123
# → # TYPE keycloak_ldap_requests_seconds_max gauge
# → keycloak_ldap_requests_seconds_max{...} 0.0521
```

Счётчиков ошибок на уровне провайдера отдельных нет; ошибки аутентификации
(в т.ч. провалы bind к LDAP) попадают в пользовательские события. Чтобы ловить их в метриках — включите
event metrics: `--metrics-enabled=true --event-metrics-user-enabled=true`, затем:

```bash
curl -s http://localhost:9000/metrics | grep 'keycloak_user_events_total{.*error='
# → keycloak_user_events_total{realm="myrealm",event="login",error="invalid_user_credentials",...} 7
#   (тип: counter; теги: realm, client_id, idp, event, error)
```

### Резервное копирование конфигурации

#### Экспорт конфигурации провайдера

```bash
# Экспорт конфигурации LDAP провайдера
curl -s -X GET "${KEYCLOAK_URL}/admin/realms/${REALM}/components?type=org.keycloak.storage.UserStorageProvider" \
  -H "Authorization: Bearer ${TOKEN}" | jq '.[] | select(.providerId == "ldap")' > ldap_provider_backup.json

# Экспорт мапперов
curl -s -X GET "${KEYCLOAK_URL}/admin/realms/${REALM}/components?type=org.keycloak.storage.ldap.mappers.LDAPStorageMapper" \
  -H "Authorization: Bearer ${TOKEN}" | jq '.[]' > ldap_mappers_backup.json
```

#### Восстановление конфигурации

```bash
# Восстановление провайдера
PROVIDER_ID=$(jq -r '.[0].id' ldap_provider_backup.json)
curl -s -X PUT "${KEYCLOAK_URL}/admin/realms/${REALM}/components/${PROVIDER_ID}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d @ldap_provider_backup.json

# Перезапуск синхронизации после восстановления
curl -s -X POST "${KEYCLOAK_URL}/admin/realms/${REALM}/user-storage/${PROVIDER_ID}/sync?action=triggerFullSync" \
  -H "Authorization: Bearer ${TOKEN}"
# → {"added":N,"updated":N,"removed":N,"failed":N,"ignored":N,"status":"..."}
```

---

## Технические детали и оптимизация

### Работа с мапперами (Mappers)

Мапперы определяют логику преобразования данных между LDAP-атрибутами и полями Keycloak. При создании провайдера
Keycloak создаёт набор начальных мапперов автоматически, исходя из комбинации `Vendor` + `Edit Mode` +
`Import Users`; их можно удалять, заменять или добавлять вручную.

#### Типы мапперов и конфигурация

| Маппер | `providerId` | Ключевые параметры конфигурации |
| :--- | :--- | :--- |
| **User Attribute Mapper** | `user-attribute-ldap-mapper` | `ldap.attribute` (mail/givenName/sn), `user.model.attribute` (email/firstName/lastName), `is.mandatory.in.ldap`, `read.only` |
| **User Attribute Mapper (UPN)** | `user-attribute-ldap-mapper` | `ldap.attribute=userPrincipalName`, `user.model.attribute=username` (для AD) |
| **Full Name Mapper** | `full-name-ldap-mapper` | `ldap.full.name.attribute=cn` (или `displayName`), `read.only`, `write.only` |
| **Group LDAP Mapper** | `group-ldap-mapper` | `groups.dn`, `group.name.ldap.attribute`, `group.object.classes`, `membership.ldap.attribute`, `mode` (`LDAP_ONLY`/`IMPORT`/`READ_ONLY`, default `READ_ONLY`), `decode.group.uuid.attribute` |
| **Role LDAP Mapper** | `role-ldap-mapper` | `roles.dn`, `role.name.ldap.attribute`, `role.object.classes`, `membership.ldap.attribute`, `mode`, `use.realm.roles.mapping`, `client.id` |
| **Hardcoded LDAP Attribute Mapper** | `hardcoded-ldap-attribute-mapper` | `ldap.attribute.name`, `ldap.attribute.value` (жёстко заданное значение) |
| **MS AD User Account Control Mapper** | `msad-user-account-control-mapper` | `ldap.password.policy.hints.enabled` (управление паролями через OID `LDAP_SERVER_POLICY_HINTS_OID`, только WRITABLE MSAD), `always.read.enabled.value.from.ldap` (всегда читать enabled/disabled из `userAccountControl`) |

Пример создания User Attribute Mapper для `mail` через Admin API:

```bash
curl -s -X POST "${KEYCLOAK_URL}/admin/realms/${REALM}/components" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "email",
    "providerType": "org.keycloak.storage.ldap.mappers.LDAPStorageMapper",
    "providerId": "user-attribute-ldap-mapper",
    "parentId": "<ldap_provider_id>",
    "config": {
      "ldap.attribute": ["mail"],
      "user.model.attribute": ["email"],
      "is.mandatory.in.ldap": ["false"],
      "read.only": ["true"]
    }
  }'
# → 201 Created (mapper привязан к провайдеру через parentId)
```

> **AD:** состояние учётной записи (отключена/истёк срок действия) и необходимость смены пароля обрабатываются
> маппером `msad-user-account-control-mapper` (см. таблицу). Для атрибутов вроде `userPrincipalName` добавляйте
> User Attribute Mapper с `ldap.attribute=userPrincipalName`. Для `objectGUID` включайте `Decode UUID Attribute to UUID Format`
> (`decode.group.uuid.attribute` в group-маппере) — см. "Особенности Keycloak 26+".

### Особенности Keycloak 26+

- **Decode UUID to UUID Format:** Начиная с 26.6.0 (#45917), бинарный `objectGUID` — UUID LDAP-атрибут AD — декодируется
  в строку UUID вместо Base64 (для `LDAP_ID` пользователя и group-атрибутов). Остальные бинарные атрибуты
  остаются Base64. Переключить формат можно в маппере: в group-маппере — опция `decode.group.uuid.attribute`
  (*Decode UUID Attribute to UUID Format*); в user-attribute маппере — аналогичный переключатель (UUID/Base64),
  добавленный в 26.7.0 (PR #49623). Реализация — `LDAPUtil.decodeBase64ToUuid` / `decodeObjectGUID`.
  > **Регрессия 26.6.1–26.6.2:** декодирование `objectGUID`→UUID сломано — атрибут возвращается как сырой массив байт
  > (`[B@...`). Исправление — PR [#49623](https://github.com/keycloak/keycloak/pull/49623), включённое в 26.7.0,
  > также добавляет в маппер переключатель формата (UUID/Base64). Обход: зафиксировать 26.6.0 или обновиться до 26.7.0+;
  > добавление атрибута в `Binary Attributes` **не помогает** (см. issue [#49189](https://github.com/keycloak/keycloak/issues/49189)).
- **Кластерная синхронизация:** периодическая синхронизация **не координируется** между узлами кластера — каждый узел
  запускает собственный планировщик. В кластере из N узлов sync выполняется на каждом (известное ограничение, см. issue #43752,
  Red Hat solution 7129453), что умножает нагрузку на LDAP в N раз. Обход: отключить периодический sync на всех узлах,
  кроме одного (`fullSyncPeriod`/`changedSyncPeriod = -1`), либо запускать ручной sync из одного узла.
- **LDAP Password Policy:** Keycloak умеет читать флаг необходимости смены пароля из LDAP и принудительно отправлять
  пользователя на форму смены пароля. Реализовано через `PasswordPolicyControl` (реализует IETF
  `draft-behera-ldap-password-policy`); включается переключателем *Enable LDAP password policy* в Advanced settings
  (добавлен в 24.0.5). Для Active Directory вместо политики паролей используйте маппер **MSAD User Account Control Mapper**.

### Синхронизация пользователей

- **Full Sync** (`triggerFullSync`): полное сканирование `Users DN`. Рекомендуется только при первичной
  настройке или восстановлении. Анализирует все записи LDAP и создаёт/обновляет/удаляет импортированных пользователей.
- **Incremental Sync** (`triggerChangedUsersSync`): синхронизация только изменённых объектов на основе
  атрибута `modifyTimestamp` (OpenLDAP) или `uSNChanged` (AD). Экономит нагрузку на каталог.
- **Batch Size** (`batchSizeForSync`): количество записей за одну транзакцию (по умолчанию 1000).
  Увеличьте для больших каталогов, но помните, что каждый батч — отдельная транзакция в БД Keycloak.

#### Периодическая синхронизация

Периодические задачи включаются через параметры провайдера (в секундах; `-1` отключает):

| Параметр | Действие | Примечание |
| :--- | :--- | :--- |
| **fullSyncPeriod** | Полный sync всех пользователей | `-1` — отключить. |
| **changedSyncPeriod** | Инкрементный sync изменённых | `-1` — отключить. |
| **batchSizeForSync** | Размер пакета | 1000 по умолчанию. |

В кластере периодический sync **не координируется** между узлами (см. "Особенности Keycloak 26+"),
поэтому в production рекомендуется либо отключить периодические задачи на всех, кроме одного узла,
либо полностью полагаться на ручной/планируемый sync.

#### Ручной sync через Admin API

```bash
# Полный sync: LDAP -> Keycloak
curl -s -X POST "${KEYCLOAK_URL}/admin/realms/${REALM}/user-storage/${PROVIDER_ID}/sync?action=triggerFullSync" \
  -H "Authorization: Bearer ${TOKEN}"
# → {"added":120,"updated":30,"removed":2,"failed":0,"ignored":0,"status":"..."}

# Инкрементный sync (только изменённые с момента последней синхронизации)
curl -s -X POST "${KEYCLOAK_URL}/admin/realms/${REALM}/user-storage/${PROVIDER_ID}/sync?action=triggerChangedUsersSync" \
  -H "Authorization: Bearer ${TOKEN}"
```

> Параметр `action` (а не `direction`) используется на уровне провайдера. `direction=fedToKeycloak`/`keycloakToFed` применяется только к синхронизации отдельных мапперов
> (`/{mapperId}/sync?direction=...`). Ответ — JSON `SynchronizationResult` с полями `added`, `updated`, `removed`, `failed`.

### Производительность и масштабирование

- **Connection Pooling:** Keycloak использует пул соединений к LDAP-серверу (JNDI LDAP connection pool).
  Пул включается автоматически; его параметры задаются **JVM-свойствами** `-Dcom.sun.jndi.ldap.connect.pool.*`
  (настраиваются для всего процесса, а не на уровне провайдера):
  - `com.sun.jndi.ldap.connect.pool.initsize` — стартовый размер пула
  - `com.sun.jndi.ldap.connect.pool.prefsize` — предпочитаемый размер
  - `com.sun.jndi.ldap.connect.pool.maxsize` — максимум соединений в пуле
  - `com.sun.jndi.ldap.connect.pool.timeout` — время простоя соединения (мс)
  - `com.sun.jndi.ldap.connect.timeout` — таймаут установки соединения (мс)
  - `com.sun.jndi.ldap.read.timeout` — таймаут чтения (мс)
  - `com.sun.jndi.ldap.connect.pool.debug` — уровни логирования пула (`all`/`fine`/`trace`)
  ```bash
  # пример: Keycloak via JAVA_OPTS
  export JAVA_OPTS="-Dcom.sun.jndi.ldap.connect.pool.initsize=10 \
  -Dcom.sun.jndi.ldap.connect.pool.maxsize=50 \
  -Dcom.sun.jndi.ldap.connect.pool.timeout=300000 \
  -Dcom.sun.jndi.ldap.connect.timeout=5000 \
  -Dcom.sun.jndi.ldap.read.timeout=15000"
  ```
  После смены параметров пула перезапустите Keycloak. В кластере каждый узел держит свой пул.
- **Batch Size:** Увеличение `batchSizeForSync` до 5000–10000 ускоряет полную синхронизацию для каталогов с >10 000 пользователей.
- **Кэширование:** Используйте `DEFAULT` или `EVICT_DAILY` кэш-политику для снижения нагрузки на LDAP. Для часто изменяемых атрибутов используйте `NO_CACHE`.
- **Лимиты LDAP-сервера:** Убедитесь, что `sizeLimit` и `timeLimit` на LDAP-сервере соответствуют ожиданиям Keycloak. Включённая `pagination` помогает обходить `sizeLimit`.
- **Режим READ_ONLY:** Для production-сред рекомендуется READ_ONLY режим для снижения нагрузки и предотвращения несанкционированных изменений.

### Безопасность и жёсткая настройка

- **Принцип минимальных привилегий:** Bind DN должен иметь только права на чтение (search) в `Users DN` и `Groups DN`. Для режима WRITABLE — дополнительно права на создание/изменение записей.
- **Сетевая изоляция:** Keycloak должен иметь доступ только к портам 389/636 LDAP-сервера. Ограничьте доступ через firewall (iptables/nftables).
- **Таймауты:** Установите `Connection Timeout` и `Read Timeout` для предотвращения зависаний при недоступности LDAP-сервера.
- **Аудит:** Включите логирование подключений LDAP на стороне сервера для отслеживания подозрательной активности.
- **Парольная политика:** Используйте политику паролей LDAP-сервера; Keycloak не должен хранить пароли в WRITABLE режиме без необходимости.
- **Рефералы:** если AD-инфраструктура распределена по нескольким доменам, включите `Allow LDAP Referrals`.
  Начиная с **26.4.3** (CVE-2025-13467) рефералы по умолчанию **отфильтровываются** — разрешены только LDAP-URL.
  Отключить можно опцией `spi-storage-ldap-secure-referral=false` (опция **устарела** и будет удалена) — только при необходимости.

---

## Устранение неполадок

| Симптом | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Ошибка подключения** | Неверный Bind DN или пароль | Проверьте логи Keycloak: `journalctl -u keycloak -f` | Убедитесь в правильности Bind DN и пароля; проверьте доступность LDAP-сервера |
| **Таймаут при аутентификации** | LDAP-сервер перегружен или недоступен | `nc -zv ldap.example.com 636` | Увеличьте `Connection Timeout`; проверьте нагрузку на LDAP-сервер |
| **Пользователи не найдены** | Неверный Users DN или фильтр | Проверьте через `ldapsearch` | Убедитесь в правильности `Users DN` и `User LDAP Filter` |
| **Кириллица в атрибутах** | Проблемы с кодировкой | Проверьте логи на наличие `Invalid byte` ошибок | Используйте латиницу в RDN; при необходимости настройте `normalize` в мапперах |
| **Медленная синхронизация** | Большой каталог или глубокие фильтры | Мониторинг времени синхронизации через Admin API | Увеличьте `Batch Size`; упростите фильтры; используйте `Incremental Sync` |
| **Ошибки TLS/SSL** | Неверный сертификат или CA | Проверьте truststore Keycloak | Импортируйте CA-сертификат в truststore; проверьте срок действия сертификата |
| **Дубликаты пользователей** | Неверный `Username LDAP Attribute` | Проверьте уникальность атрибута в LDAP | Убедитесь, что атрибут уникален в пределах `Users DN` |
| **Пользователь заблокирован в AD** | `userAccountControl` флаг | Проверьте маппер MSAD User Account Control | Настройте маппер для обработки состояния учетной записи |
| **`sizeLimit` / sizelimit exceeded** | Превышен лимит по количеству записей на сервере | В логах `Size limit exceeded`; ldapsearch возвращает часть | Включите `pagination`; поднимите `sizeLimit` на LDAP; сузьте `User LDAP Filter`/`usersDn` |
| **`timeLimit` / timelimit exceeded** | Поиск превысил лимит времени | В логах `Time limit exceeded` | Увеличьте `timeLimit` на LDAP; упростите фильтр; используйте `Incremental Sync` |
| **`Invalid credentials` (bind)** | Неверный Bind DN/пароль или аккаунт заблокирован | `ldapsearch -D ... -W` возвращает `Invalid credentials` | Проверьте Bind DN/пароль; сбросьте пароль; проверьте `userAccountControl` |
| **`No such object` / `NameNotFoundException`** | Неверный базовый DN | Bind succeeds, но поиск по `Users DN` пуст | Проверьте `usersDn`/`groupsDn` через `ldapsearch -b`; поправьте DN |
| **`LDAP_OPERATIONS_ERROR`** | Недостаточно прав на чтение/ACL | Ошибка в логах Keycloak; `ldapsearch` без `-D` падает | Дайте bind-аккаунту права на чтение в `usersDn`/`groupsDn` |
| **Пул соединений исчерпан** | Превышен `maxsize`; соединения не возвращаются в пул | Повторяющиеся `connect` timeouts; в issue #38660 — blocking on search | Увеличьте `com.sun.jndi.ldap.connect.pool.maxsize`; включите `pool.debug=trace` для диагностики; проверьте протекание соединений |
| **`objectGUID = [B@...` (сырой массив байт)** | Регрессия 26.6.1–26.6.2 | Атрибут `objectGUID` в user attribute выглядит как сырой массив | Добавьте в `Binary Attributes`; либо понизьте/повесьте 26.6.3+ (см. "Особенности Keycloak 26+") |

### Диагностические команды

```bash
# Проверка доступности LDAP-сервера
nc -zv ldap.corp.example.com 636
# → Connection to ldap.corp.example.com 636 port [tcp/ldaps] succeeded!

# Тест bind-запроса (запрос с таймаутами)
LDAPTLS_REQCERT=try timeout 15 ldapsearch -x -H ldaps://ldap.corp.example.com:636 \
  -o nettimeout=10 -l 15 \
  -D "cn=svc-keycloak,ou=service,dc=corp,dc=example,dc=com" \
  -w "S3cureP@ss!" \
  -b "cn=users,dc=corp,dc=example,dc=com" \
  "(sAMAccountName=testuser)"
# → dn: CN=Test User,...

# Проверка сертификата LDAPS
openssl s_client -connect ldap.corp.example.com:636 -showcerts </dev/null 2>/dev/null | openssl x509 -text -noout

# Логи Keycloak — фильтр ошибок LDAP
journalctl -u keycloak -f --since "1 hour ago" | grep -iE "ldap|user-storage|UserStorage"

# Проверка конфигурации Keycloak
/opt/keycloak/bin/kc.sh show-config
```

---

## Дополнительная информация

### Безопасность и TLS

1. **LDAPS (порт 636):** Предпочтительный метод. Требует импорта CA-сертификата в Truststore Keycloak.
   ```bash
   # Пример импорта сертификата в truststore
   keytool -import -alias ldap-ca -file ca.crt -keystore truststore.p12
   ```
2. **StartTLS (порт 389):** Шифрование устанавливается поверх незащищенного соединения. Требует поддержки со стороны LDAP-сервера (`startTls=true` в конфиге провайдера).
3. **Referrals:** если AD-инфраструктура распределена по нескольким доменам, включите `Allow LDAP Referrals`.

### Отказоустойчивость и репликация LDAP

Keycloak поддерживает **несколько `connectionUrl`** в одном провайдере (через пробел) — запросы распределяются
по серверам round-robin. Ограничения:

- Все перечисленные LDAP-серверы должны быть репликами **одного и того же каталога** (например, контроллеры домена AD
  или реплики OpenLDAP).
- Уникальный идентификатор пользователя (`entryUUID`/`objectGUID`) должен быть **одинаковым** на всех серверах, иначе
  KeyCloak создаст дубликаты при синхронизации.
- Bind DN, Users DN и группы должны быть согласованы на всех репликах.
- `pagination` рекомендуется включить для согласованного скольжения окна `sizeLimit`/`timeLimit`.

Для балансировки нагрузки на сам KeyCloak: в кластере отключайте периодический sync на лишних узлах
(см. "Кластерная синхронизация" в ограничениях) и используйте отдельный сервис/Virtual IP для LDAP,
чтобы переключение на реплику было прозрачно для приложения.

### Ограничения и риски

- **Производительность:** Большое количество мапперов или глубокие фильтры поиска могут замедлять аутентификацию.
- **Кириллица:** Использование кириллических символов в атрибутах RDN (`uid`, `cn`) может приводить к ошибкам в некоторых старых интеграциях; рекомендуется использовать латиницу.
- **Бэкапы:** Данные LDAP не хранятся в БД Keycloak постоянно (только метаданные и кэш). Бэкап LDAP-сервера обязателен.
- **Кластерная синхронизация:** периодические задачи sync **не координируются** между узлами — каждый узел KeyCloak
  запускает синхронизацию самостоятельно, что умножает нагрузку на LDAP в N раз (N = число узлов). Отключайте периодические
  sync во всех узлах, кроме одного, либо пользуйтесь ручным `triggerChangedUsersSync`/`triggerFullSync`.
- **Сброс кэша реалма:** после `fullSync`/`changedSync` Keycloak очищает кэш реалма (см. issue #43752); в большом
  кластере это может вызывать spike нагрузки. Планируйте sync вне пиковых нагрузок.
- **Рост логов:** `DEBUG`/`TRACE` для `org.keycloak.storage.ldap` сильно увеличивает логи и сам по себе добавляет нагрузку — включайте только для диагностики.

### См. также

- [Keycloak: Обзор](./keycloak_overview.md) — общая архитектура системы.
- [OpenLDAP в Kubernetes](../../LDAP/openldap_kubernetes.md) — развёртывание тестового окружения.
- [Диагностика LDAP/SSSD](../../Linux/SystemAdministration/Users/LDAP_SSSD/operations.md) — отладка соединений и поиск через `ldapsearch`.
- [OAuth 2.0 и OIDC](../Concepts/oauth2_overview.md) — протоколы, использующие федеративные данные.
