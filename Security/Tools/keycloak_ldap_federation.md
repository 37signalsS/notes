# Интеграция Keycloak с LDAP/AD

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
| **Keycloak** | v22+ на базе Quarkus (рекомендуется v26+ для поддержки `Decode UUID to UUID Format`) |
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

### Настройка через CLI (`kc.sh`)

Для автоматизации и управления конфигурацией LDAP Federation через CLI используйте Admin API Keycloak.

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
      "cachePolicy": ["NO_CACHE"],
      "maxBatchSize": ["1000"],
      "editMode": ["READ_ONLY"],
      "usersDn": ["cn=users,dc=corp,dc=example,dc=com"],
      "usernameLdapAttribute": ["sAMAccountName"],
      "rdnLdapAttribute": ["cn"],
      "uuidLdapAttribute": ["objectGUID"],
      "userObjectClasses": ["person, user"],
      "connectionTimeout": ["5000"],
      "useTruststoreSpi": ["ldapsOnly"]
    }
  }'
# → 201 Created
```

#### Создание маппераов через Admin API

```bash
# Создание User Attribute Mapper для email
curl -s -X POST "${KEYCLOAK_URL}/admin/realms/${REALM}/components" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "email",
    "providerType": "org.keycloak.storage.ldap.mappers.LDAPStorageMapper",
    "providerId": "user-attribute-ldap-mapper",
    "config": {
      "ldap.attribute": ["mail"],
      "user.model.attribute": ["email"],
      "is.mandatory.in.ldap": ["false"]
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
        usernameLdapAttribute: ["sAMAccountName"]
        uuidLdapAttribute: ["objectGUID"]
        userObjectClasses: ["person, user"]
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
      config:
        ldap.attribute: ["mail"]
        user.model.attribute: ["email"]
        is.mandatory.in.ldap: ["false"]
    status_code: 201

- name: "Запуск Full Sync"
  uri:
    url: "{{ keycloak_url }}/admin/realms/{{ realm }}/user-storage/{{ ldap_provider.json.id }}/sync?direction=fedToKeycloak"
    method: POST
    headers:
      Authorization: "Bearer {{ keycloak_token.json.access_token }}"
    status_code: 204
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
          usernameLdapAttribute: ["sAMAccountName"]
          uuidLdapAttribute: ["objectGUID"]
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
# Проверка статуса провайдера
curl -s -X GET "${KEYCLOAK_URL}/admin/realms/${REALM}/components?type=org.keycloak.storage.UserStorageProvider" \
  -H "Authorization: Bearer ${TOKEN}" | jq '.[] | select(.providerId == "ldap")'

# Проверка количества ошибок синхронизации
curl -s -X GET "${KEYCLOAK_URL}/admin/realms/${REALM}/user-storage/{{ provider_id }}/sync" \
  -H "Authorization: Bearer ${TOKEN}"
# → Возвращает статус последней синхронизации
```

#### Prometheus-метрики (если включены)

```yaml
# keycloak.conf для включения метрик
quarkus-micrometer:
  export:
    prometheus:
      enabled: true
      path: /q/metrics
```

```bash
# Запрос метрик
curl -s http://localhost:8080/q/metrics | grep -i "keycloak.*ldap"
# → keycloak_user_storage_provider_errors_total{provider="ldap"} 0
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
curl -s -X POST "${KEYCLOAK_URL}/admin/realms/${REALM}/user-storage/${PROVIDER_ID}/sync?direction=fedToKeycloak" \
  -H "Authorization: Bearer ${TOKEN}"
```

---

## Технические детали и оптимизация

### Работа с мапперами (Mappers)

Мапперы определяют логику преобразования данных. Ключевые типы:

1. **User Attribute Mapper:** Связывает поля LDAP (например, `mail`, `givenName`, `sn`) с полями пользователя Keycloak.
2. **Group LDAP Mapper:** 
   - Синхронизирует иерархию групп.
   - `LDAP Groups DN`: точка поиска групп.
   - `Mode`: `LDAP_AS_READ_ONLY` (по умолчанию) или `WRITABLE`.
3. **Role LDAP Mapper:** Позволяет сопоставлять членство в группах LDAP с ролями Keycloak (Realm или Client roles).
4. **MSAD User Account Control Mapper:** (Только для AD) Обрабатывает состояние учетной записи (активна/заблокирована/истек пароль).

### Особенности Keycloak 26+

- **Decode UUID to UUID Format:** Для Active Directory добавлена опция декодирования бинарного `objectGUID` непосредственно в формат UUID, что устраняет проблемы с Base64-кодировкой.
- **Кластерная синхронизация:** Периодическая синхронизация теперь выполняется строго на одном узле кластера, что предотвращает "шторм" запросов к LDAP-серверу.
- **LDAP Password Policy:** Keycloak может считывать флаги о необходимости смены пароля из LDAP и принудительно отправлять пользователя на форму обновления пароля.

### Синхронизация пользователей

- **Full Sync:** Полное сканирование LDAP. Рекомендуется только при первичной настройке или восстановлении.
- **Incremental Sync:** Синхронизация только измененных объектов на основе атрибута `modifyTimestamp` (OpenLDAP) или `uSNChanged` (AD).
- **Batch Size:** Настройка количества записей, обрабатываемых за одну итерацию (по умолчанию 1000). Увеличьте для больших каталогов.

### Производительность и масштабирование

- **Connection Pooling:** Keycloak использует пул соединений к LDAP-серверу. Настройте `Connection Pooling` параметры для высоконагруженных сред.
- **Batch Size:** Увеличение `Batch Size` до 5000-10000 записей ускоряет полную синхронизацию для каталогов с >10 000 пользователей.
- **Кэширование:** Используйте `DEFAULT` или `EVICT_DAILY` кэш-политику для снижения нагрузки на LDAP. Для часто изменяемых атрибутов используйте `NO_CACHE`.
- **Лимиты LDAP-сервера:** Убедитесь, что `sizeLimit` и `timeLimit` на LDAP-сервере соответствуют ожиданиям Keycloak.
- **Режим READ_ONLY:** Для production-сред рекомендуется READ_ONLY режим для снижения нагрузки и предотвращения несанкционированных изменений.

### Безопасность и жёсткая настройка

- **Принцип минимальных привилегий:** Bind DN должен иметь только права на чтение (search) вUsers DN и Groups DN. Для режима WRITABLE — дополнительно права на создание/изменение.
- **Сетевая изоляция:** Keycloak должен иметь доступ только к портам 389/636 LDAP-сервера. Ограничьте доступ через firewall или security groups.
- **Таймауты:** Установите `Connection Timeout` и `Read Timeout` для предотвращения зависаний при недоступности LDAP-сервера.
- **Аудит:** Включите логирование подключений LDAP на стороне сервера для отслеживания подозрительной активности.
- **Парольная политика:** Используйте политику паролей LDAP-сервера; Keycloak не должен хранить пароли в WRITABLE режиме без необходимости.

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

### Диагностические команды

```bash
# Проверка доступности LDAP-сервера
nc -zv ldap.corp.example.com 636

# Тест bind-запроса
ldapsearch -x -H ldaps://ldap.corp.example.com:636 \
  -D "cn=svc-keycloak,ou=service,dc=corp,dc=example,dc=com" \
  -w "S3cureP@ss!" \
  -b "cn=users,dc=corp,dc=example,dc=com" \
  "(sAMAccountName=testuser)"

# Проверка сертификата LDAPS
openssl s_client -connect ldap.corp.example.com:636 -showcerts </dev/null 2>/dev/null | openssl x509 -text -noout

# Логи Keycloak
journalctl -u keycloak -f --since "1 hour ago"

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
2. **StartTLS (порт 389):** Шифрование устанавливается поверх незащищенного соединения. Требует поддержки со стороны LDAP-сервера.
3. **Referrals:** Если AD-инфраструктура распределена по нескольким доменам, необходимо включить `Allow LDAP Referrals`.

### Ограничения и риски

- **Производительность:** Большое количество мапперов или глубокие фильтры поиска могут замедлять аутентификацию.
- **Кириллица:** Использование кириллических символов в атрибутах RDN (`uid`, `cn`) может приводить к ошибкам в некоторых старых интеграциях; рекомендуется использовать латиницу.
- **Бэкапы:** Данные LDAP не хранятся в БД Keycloak постоянно (только метаданные и кэш). Бэкап LDAP-сервера обязателен.
- **Однопоточность:** В кластерной среде периодические задачи синхронизации выполняются только на одном узле, что может создавать bottleneck при очень больших каталогах.

### См. также

- [Keycloak: Обзор](./keycloak_overview.md) — общая архитектура системы.
- [OpenLDAP в Kubernetes](../../LDAP/openldap_kubernetes.md) — развёртывание тестового окружения.
- [Диагностика LDAP/SSSD](../../Linux/SystemAdministration/Users/LDAP_SSSD/operations.md) — отладка соединений и поиск через `ldapsearch`.
- [OAuth 2.0 и OIDC](../Concepts/oauth2_overview.md) — протоколы, использующие федеративные данные.
