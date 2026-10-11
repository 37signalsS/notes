# MongoDB: Безопасность

**Актуально для:** MongoDB 8.0.x

---

## Определения

**Безопасность в MongoDB** строится по модели эшелонированной защиты (Defense in Depth) и включает контроль доступа, сетевую изоляцию и шифрование данных на всех этапах жизненного цикла.

*   **RBAC (Role-Based Access Control):** Система разграничения прав, где привилегии привязываются к ролям, а роли — к пользователям или группам (в интеграции с LDAP/AD).
*   **SCRAM (Salted Challenge Response Authentication Mechanism):** Стандартный протокол аутентификации «пароль-ответ». Стандарт 2026 года — **SCRAM-SHA-256**. MongoDB 8.0 больше не поддерживает SHA-1.
*   **TLS 1.3:** Современный стандарт шифрования трафика. В MongoDB 8.0 поддержка TLS 1.3 является приоритетной для обеспечения минимальных задержек при рукопожатии.
*   **Queryable Encryption (FLE 2.0):** Технология шифрования полей на стороне клиента, позволяющая выполнять поиск по зашифрованным данным без их дешифрации на сервере. В MongoDB 8.0 добавлена поддержка range-запросов.
*   **Encryption at Rest (EaR):** Шифрование данных на диске. В Enterprise Edition — нативное шифрование WiredTiger; в Community Edition — через dm-crypt/LUKS или шифрование на уровне файловой системы.
*   **Audit Log:** Журнал событий безопасности, записываемый в JSON-формате. Позволяет восстанавливать последовательность действий пользователей и отслеживать подозрительные операции.
*   **x.509 Certificate Authentication:** Аутентификация клиентов и узлов кластера через сертификаты X.509, исключающая передачу паролей.
*   **Kerberos / LDAP:** Внешние механизмы аутентификации и авторизации, доступные в Enterprise Edition, интегрируемые с Active Directory.
*   **OIDC (OpenID Connect):** Аутентификация через внешний Identity Provider (Okta, Entra ID, Keycloak) — Workforce Identity Federation (пользователи) и Workload Identity Federation (сервисы). Enterprise Edition, MongoDB 7.0.11+, только Linux.

---

## Архитектура и основные принципы

### Модель эшелонированной защиты

MongoDB не имеет единой «кнопки безопасности». Защита строится из нескольких независимых слоев:

1.  **Сетевой слой:** Ограничение доступа к порту 27017 через firewall и `bindIp`.
2.  **Слой аутентификации:** Проверка подлинности каждого подключения (SCRAM, x.509, Kerberos).
3.  **Слой авторизации (RBAC):** Проверка прав на каждую операцию после аутентификации.
4.  **Слой шифрования:** Защита данных на диске (EaR) и в transit (TLS).
5.  **Слой аудита:** Фиксация событий безопасности для forensic анализа.

### Конвейер аутентификации и авторизации

При подключении клиента к mongod происходит следующая последовательность:

1.  Клиент отправляет запрос на подключение.
2.  Если включен TLS, выполняется рукопожатие и проверка сертификата.
3.  MongoDB запрашивает учетные данные согласно настроенным механизмам (`authenticationMechanisms`).
4.  После успешной аутентификации для каждой операции проверяется авторизация через RBAC.
5.  При отсутствии необходимых привилегий возвращается ошибка `not authorized`.

### Шифрование данных

| Тип шифрования | Уровень | Реализация в MongoDB 8.0 | Примечание для SRE |
| :--- | :--- | :--- | :--- |
| **Encryption in Transit** | Сеть | TLS 1.2/1.3, `requireTLS` | Проверять сертификаты через `openssl s_client`. |
| **Encryption at Rest (Enterprise)** | Диск | WiredTiger native encryption | Ключи хранятся в KMS (локальном или внешнем). |
| **Encryption at Rest (Community)** | Диск | dm-crypt / LUKS | Прозрачно для MongoDB, но влияет на I/O latency. |
| **Client-Side (FLE 2.0)** | Поле | Queryable Encryption | Позволяет range-запросы (MongoDB 8.0). Не поддерживается в sharded clusters. |

### Ограничения безопасности

*   **FLE 2.0 не поддерживает шардирование:** Коллекции с Queryable Encryption нельзя использовать в sharded cluster. Это архитектурное ограничение версии 8.0.
*   **TLS 1.0/1.1 отключен по умолчанию:** В 8.0 эти версии протокола запрещены и не могут быть включены.
*   **SCRAM-SHA-1 удален:** В MongoDB 8.0 поддерживается только SCRAM-SHA-256. Пользователи, созданные под SHA-1, требуют миграции.

---

## Практические сценарии

### 1. Первоначальная настройка (Hardening)

После установки необходимо создать администратора и включить авторизацию в `mongod.conf`.

**Шаг 1: Создание суперпользователя (в mongosh без авторизации):**
```javascript
use admin
db.createUser({
  user: "security_admin",
  pwd: passwordPrompt(),
  roles: [ { role: "root", db: "admin" } ]
})
```
**Ожидаемый результат:**
```
Successfully added user: {
  "user" : "security_admin",
  "roles" : [ { "role" : "root", "db" : "admin" } ]
}
```

**Шаг 2: Включение защиты в `/etc/mongod.conf`:**
```yaml
security:
  authorization: enabled
  encryptionKeyStore: # Enterprise only: путь к ключевому хранилищу
  javascriptEnabled: false # Отключаем серверный JS (защита от инъекций)

net:
  port: 27017
  bindIp: 127.0.0.1,10.0.5.42 # Только локальный и внутренний IP
  tls:
    mode: requireTLS
    certificateKeyFile: /etc/ssl/mongodb.pem
    CAFile: /etc/ssl/ca.pem
    disabledProtocols: "TLS1_0,TLS1_1" # Явное отключение устаревших протоколов

systemLog:
  destination: file
  path: "/var/log/mongodb/mongod.log"
  logAppend: true
  logRotate: rename
```

### 2. Настройка роли для приложения

```javascript
use sales_db
db.createRole({
  role: "app_server_role",
  privileges: [
    { resource: { db: "sales_db", collection: "" }, actions: ["find", "insert", "update"] }
  ],
  roles: []
})

db.createUser({
  user: "app_user",
  pwd: passwordPrompt(),
  roles: [ { role: "app_server_role", db: "sales_db" } ]
})
```
**Ожидаемый результат:**
```
Successfully added user: {
  "user" : "app_user",
  "roles" : [ { "role" : "app_server_role", "db" : "sales_db" } ]
}
```

### 3. Аутентификация через x.509

```bash
# Создание сертификата для клиента (пример openssl)
openssl x509 -in client.pem -text -noout
# # → Serial Number, Subject: CN=client,O=Org,...
```

```javascript
// Подключение через mongosh с сертификатом
mongosh --tls --tlsCertificateKeyFile /etc/ssl/client.pem --tlsCAFile /etc/ssl/ca.pem --authenticationDatabase '$external' --authenticationMechanism MONGODB-X509
```

### 4. Аудит событий безопасности (Enterprise)

```yaml
# auditLog:
#   destination: file
#   format: JSON
#   path: "/var/log/mongodb/audit.json"
#   filter: '{ "atype": { "$in": [ "authCheck", "createCollection", "dropDatabase" ] } }'
```

**Валидация:**
```javascript
// Проверка формата аудита
db.adminCommand({ getParameter: 1, auditLog: 1 })
// # → { "auditLog" : { "format" : "JSON", ... }, "ok" : 1 }
```

### 5. Шифрование данных на диске (Community Edition)

```bash
# Форматирование раздела в LUKS
cryptsetup luksFormat /dev/sdb1
# # → WARNING: Device /dev/sdb1 already has a LUKS header.

# Открытие зашифрованного контейнера
cryptsetup open /dev/sdb1 mongodb_data
# # → Enter passphrase for /dev/sdb1:

# Создание файловой системы
mkfs.ext4 /dev/mapper/mongodb_data

# Монтирование
mount /dev/mapper/mongodb_data /var/lib/mongodb
```

### 6. Queryable Encryption (FLE 2.0) — MongoDB 8.0

```javascript
// Создание криптоключа через mongocryptd (требуется драйвер с поддержкой FLE)
const key = client.db("encryption").createDataKey("local", { keyAltNames: ["productsKey"] });
// # → { "_id" : { "$binary" : "...", "$type" : "04" }, "keyMaterial" : { "$binary" : "...", "$type" : "00" }, ... }

// Создание коллекции с шифрованием
db.createCollection("products", {
  encryptedFields: {
    fields: [
      { path: "ssn", keyId: key._id, bsonType: "string" },
      { path: "price", keyId: key._id, bsonType: "decimal" }
    ]
  }
})
```

#### Управление ключами (Key Management)

Queryable Encryption использует двухуровневую схему шифрования (envelope encryption):

```
KEK (Key Encryption Key) — в KMS (AWS/Azure/GCP/KMIP/local)
   │
   └─► DEK (Data Encryption Key) — в key vault (MongoDB collection)
            │
            └─► Зашифрованные поля документов
```

**Провайдеры KMS (для DEK):**

| Провайдер | Конфигурация | Применение |
| :--- | :--- | :--- |
| `local` | Локальный мастер-ключ (файл) | Только dev/test. Не для production. |
| `aws` | AWS KMS | Production на AWS. |
| `azure` | Azure Key Vault | Production на Azure. |
| `gcp` | Google Cloud KMS | Production на GCP. |
| `kmip` | KMIP-совместимый HSM (Thales, Utimaco) | Enterprise, on-prem, compliance. |

**Настройка KMIP (Enterprise):**
```yaml
# mongod.conf
security:
  encryption:
    kmip:
      serverName: "kmip.example.com"
      clientCertificateFile: /etc/ssl/mongodb-kmip.pem
      # Опционально: pinCertificateToServer
```

**Создание DEK через KMS (пример AWS):**
```javascript
// Драйвер создаёт DEK, зашифрованный KEK из AWS KMS
const key = client.db("encryption").createDataKey("aws", {
  region: "us-east-1",
  key: "arn:aws:kms:us-east-1:123456789012:key/...",
  keyAltNames: ["productsKey"]
});
```

**Key Vault (хранилище DEK):**
*   DEK хранятся в коллекции `encryption.__keyVault` (по умолчанию) или в указанной `keyVaultNamespace`.
*   Key Vault должен быть в отдельной БД, с ограниченным доступом (только приложение с ролью `readWrite` на keyVault).
*   **Никогда не храните мастер-ключ (KEK) в MongoDB** — он должен быть только в KMS.

**Ротация ключей:**
```javascript
// Ротация DEK: создать новый DEK, перешифровать данные
// 1. Создать новый DEK
const newKey = client.db("encryption").createDataKey("aws", {
  region: "us-east-1",
  key: "arn:aws:kms:...",
  keyAltNames: ["productsKey_v2"]
});

// 2. Перешифровать поля (через приложение или mongosh с FLE)
// Приложение читает старый DEK, дешифрует, шифрует новым DEK, записывает

// 3. Удалить старый DEK после миграции всех данных
db.getSiblingDB("encryption").__keyVault.deleteOne({ _id: oldKey._id });
```

> **Важно:** Ротация KEK (в KMS) не требует перешифрования данных — DEK остаются, меняется только их обёртка. Ротация DEK требует перешифрования всех полей, использующих этот DEK.

**Best Practices для ключей:**
1.  **KEK в KMS, DEK в key vault** — никогда не смешивайте.
2.  **Ротация DEK** — раз в 90 дней (compliance) или при компрометации.
3.  **keyVaultNamespace** — отдельная БД/коллекция с минимальными правами.
4.  **Аудит доступа к key vault** — логируйте все чтения DEK.
5.  **Backup ключей** — потеря DEK = потеря данных (невозможно дешифровать).
6.  **KMIP для on-prem** — Enterprise Edition + HSM для compliance (PCI DSS, HIPAA).

См. также: **[Безопасность бэкапов](../Concepts/backup_security.md)** — шифрование бэкапов, KMS, envelope encryption.

### 7. LDAP-аутентификация (Enterprise)

MongoDB делегирует проверку пароля LDAP-серверу (AD/389ds), а авторизацию выполняет локально через RBAC (или через LDAP-группы).

**Конфигурация `mongod.conf`:**
```yaml
security:
  authorization: enabled
  ldap:
    servers: "ldap.example.com:389"   # или ldaps://ldap.example.com:636
    bind:
      method: simple
      dn: "cn=mongodb,ou=service,dc=example,dc=com"
      password: "{{ vault_ldap_bind_password }}"
    userToDNMapping: '[{ match: "(.+)", substitution: "cn={0},ou=users,dc=example,dc=com" }]'
    authz:
      queryTemplate: "member={USER}?member?sub?(objectClass=group)"

setParameter:
  authenticationMechanisms: "SCRAM-SHA-256,PLAIN"
```

**Параметры:**

| Параметр | Назначение |
| :--- | :--- |
| `security.ldap.servers` | LDAP-серверы (список через запятую). Для LDAPS — порт 636 + `transportSecurity: tls`. |
| `security.ldap.bind` | Service account для поиска пользователя (bind + search). Альтернатива — SASL/GSSAPI. |
| `userToDNMapping` | Маппинг username → DN (regex + substitution). |
| `authz.queryTemplate` | LDAP-запрос для получения групп пользователя (авторизация). |

**Создание пользователя, привязанного к LDAP-группе:**
```javascript
use admin
db.createUser({
  user: "cn=dba,ou=groups,dc=example,dc=com",
  roles: [ { role: "dbAdminAnyDatabase", db: "admin" } ]
})
// Пользователь входит с LDAP-логином; MongoDB сопоставляет его с группой
```

**Подключение:**
```bash
mongosh --host mongo1:27017 \
  --authenticationMechanism PLAIN \
  --authenticationDatabase '$external' \
  -u "jdoe" -p
```

**Валидация:**
```javascript
db.getCmdLineOpts()
// # → "security" → "ldap" → { "servers" : "ldap.example.com:389", ... }

db.serverStatus().security
// # → { "LDAPServer" : "ldap.example.com:389", ... }
```

### 8. Kerberos-аутентификация (Enterprise)

**Подготовка:**
1.  Создать SPN (Service Principal Name) в AD: `mongodb/mongo1.example.com@EXAMPLE.COM`.
2.  Создать keytab-файл для `mongod` (секрет, права `chmod 400`, владелец `mongodb`).

**Конфигурация `mongod.conf`:**
```yaml
security:
  authorization: enabled
  kerberos:
    serviceName: "mongodb"
    keyFile: "/etc/mongodb/mongodb.keytab"

setParameter:
  authenticationMechanisms: "SCRAM-SHA-256,GSSAPI"
```

**Создание пользователя в MongoDB (соответствует Kerberos principal):**
```javascript
use admin
db.createUser({
  user: "jdoe@EXAMPLE.COM",
  roles: [ { role: "readWrite", db: "sales_db" } ]
})
```

**Подключение (Linux, после `kinit`):**
```bash
kinit jdoe@EXAMPLE.COM
# # → kinit: Password for jdoe@EXAMPLE.COM:

mongosh --host mongo1.example.com:27017 \
  --authenticationMechanism GSSAPI \
  --authenticationDatabase '$external' \
  --gssapiServiceName mongodb
```

**Валидация:**
```javascript
db.serverStatus().security
// # → { "KerberosServiceName" : "mongodb", ... }

// Провка ticket
klist
// # → Valid starting     Expires            Service principal
// # → 10/04/26 10:00:00  10/04/26 20:00:00  mongodb/mongo1.example.com@EXAMPLE.COM
```

### 9. OIDC-аутентификация (Enterprise 7.0.11+, Linux)

**Workforce Identity Federation** (человеческие пользователи) и **Workload Identity Federation** (сервисы, OAuth 2.0).

**Конфигурация `mongod.conf`:**
```yaml
setParameter:
  authenticationMechanisms: "SCRAM-SHA-256,MONGODB-OIDC"
  oidcIdentityProviders: |
    [
      {
        "issuer": "https://okta.example.com/oauth2/default",
        "audience": "api://mongodb",
        "authNamePrefix": "okta-issuer",
        "authorizationClaim": "groups",
        "clientId": "0zzw3ggfd2ase33"
      }
    ]
```

**Параметры `oidcIdentityProviders`:**

| Поле | Назначение |
| :--- | :--- |
| `issuer` | Issuer URL IdP (без `/.well-known/openid-configuration`). |
| `audience` | Application ID URI / audience токена. |
| `authNamePrefix` | Префикс для имён пользователей MongoDB (`okta-issuer/jdoe`). |
| `authorizationClaim` | Claim с группами для авторизации (например, `groups`). |
| `clientId` | Client ID (для Workforce Flow). |
| `supportsHumanFlows` | `false` — только Workload (машинные) токены. |
| `useAuthorizationClaim` | `false` — авторизация из user-документа в `$external`, а не из claim. |

**Создание пользователя (авторизация из claim):**
```javascript
use admin
db.createUser({
  user: "okta-issuer/jdoe",
  roles: [ { role: "readWrite", db: "sales_db" } ]
})
```

**Подключение (с токеном IdP):**
```bash
mongosh --host mongo1:27017 \
  --authenticationMechanism MONGODB-OIDC \
  --authenticationDatabase '$external' \
  --oidcToken "<access_token>"
```

**Валидация:**
```javascript
db.adminCommand({ getParameter: 1, authenticationMechanisms: 1 })
// # → { "authenticationMechanisms" : { "SCRAM-SHA-256" : 1, "MONGODB-OIDC" : 1 }, "ok" : 1 }
```

**Ограничения OIDC:**
*   Только Linux (не поддерживается на Windows/macOS).
*   Только Enterprise Edition (проверка: `mongod --version` → `modules: subscription` или `modules: enterprise`).
*   Требуется MongoDB 7.0.11+ для Workforce/Workload Identity Federation.

### 10. Управление пользователями через Ansible (IaC)

```yaml
- name: Создание пользователя MongoDB
  community.mongodb.mongodb_user:
    login_user: "{{ mongo_admin_user }}"
    login_password: "{{ mongo_admin_password }}"
    database: "admin"
    user: "app_user"
    password: "{{ vault_app_password }}"
    roles:
      - { role: "readWrite", db: "sales_db" }
    state: present
```

---

## Операции и команды

### Управление пользователями и ролями

```javascript
// Список всех пользователей
db.getUsers()
// # → [ { "user" : "app_user", "db" : "sales_db", "roles" : [...] }, ... ]

// Проверка прав текущего пользователя
db.runCommand({ connectionStatus: 1 })
// # → { "authInfo" : { "authenticatedUsers" : [ { "user" : "app_user", "db" : "sales_db" } ], "authenticatedRoles" : [...] }, ... }

// Просмотр привилегий конкретной роли
db.getRole("app_server_role", { showPrivileges: true })
// # → { "role" : "app_server_role", "privileges" : [ { "resource" : { "db" : "sales_db", "collection" : "" }, "actions" : [ "find", "insert", "update" ] } ], ... }
```

### Валидация конфигурации безопасности

```javascript
// Проверка включенной авторизации
db.getCmdLineOpts()
// # → ищем "security" → "authorization": "enabled"

// Проверка TLS-режима
db.serverStatus().security
// # → { "SSLServerConfigured" : true, "SSLServerSubjectName" : "CN=mongodb.example.com", ... }

// Проверка активных механизмов аутентификации
db.getAdminCmd({ getParameter: 1, authenticationMechanisms: 1 })
// # → { "authenticationMechanisms" : { "SCRAM-SHA-256" : 1 }, "ok" : 1 }
```

### Мониторинг и диагностика

```javascript
// Поиск активных соединений без аутентификации
db.currentOp({ "client": { "$ne": "127.0.0.1" }, "authInfo": { "authenticatedUsers": [] } })
// # → [] (в production — пустой результат или { "inprog" : [] })

// Проверка парольных политик (если настроены)
db.runCommand({ getParameter: 1, passwordPolicy: 1 })
// # → { "passwordPolicy" : { "minPasswordLength" : 8, "passwordExpirationDays" : 90, ... }, "ok" : 1 }
```

---

## Ограничения и Edge Cases

*   **Серверный JavaScript:** Включение `javascriptEnabled: true` открывает поверхность атаки для инъекций. В production отключайте, если приложение не требует `mapReduce` или `$where`.
*   **Локальный исключение (localhost exception):** После включения `authorization: enabled` первый пользователь в `admin` может быть создан только с localhost. Это мера предотвращения блокировки.
*   **Replica Set Keyfile:** При использовании `keyFile` для intra-cluster auth длина секрета должна быть не менее 1024 байт (MongoDB 8.0 требование). Короткие секреты недопустимы.
*   **Certificate Revocation:** MongoDB 8.0 проверяет CRL (Certificate Revocation List) только при явном указании `CAFile`. Без этого отозванный сертификат остается валидным для подключения.
*   **FLE 2.0 и Sharding:** Queryable Encryption несовместим с шардированными кластерами. Если требуется FLE — используйте нешардированную replica set или выносите зашифрованные данные в отдельный сервис.
*   **Время жизни паролей:** Встроенной функции истечения пароля нет. Реализуйте политику через LDAP/AD или периодическое принудительное обновление через приложение.

---

## Устранение неполадок

| Проблема | Возможная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`Authentication failed`** | Неверные учетные данные, неверная база аутентификации, или SCRAM-SHA-256 не поддерживается клиентом. | `db.getUser(username)`, проверка `authenticationMechanisms`. | Убедитесь, что пользователь создавался в базе `admin` и при входе указано `--authenticationDatabase admin`. Проверьте версию драйвера. |
| **`SSL peer certificate validation failed`** | Истек срок сертификата, неверный CA или расхождение времени (NTP). | `openssl verify -CAfile /etc/ssl/ca.pem /etc/ssl/mongodb.pem`. | Обновить сертификат, проверить цепочку, синхронизировать время через NTP. |
| **`Unauthorized` при выполнении команды** | Недостаточно прав в роли или роль создана не в той БД. | `db.getUser(username)`, `connectionStatus`. | Проверить привилегии через `db.getRole()`. Добавить недостающие `actions`. |
| **Зависание при подключении** | Блокировка портов firewall, неверный `bindIp`, или TLS handshake timeout. | `telnet host 27017`, `nc -zv host 27017`, `tcpdump`. | Проверить сетевую доступность, конфигурацию `bindIp`, версии TLS. |
| **`This MongoDB deployment does not support Queryable Encryption`** | Попытка использовать FLE 2.0 в sharded cluster или версии ниже 8.0. | `db.serverStatus().version`. | Использовать Queryable Encryption только в нешардированной replica set на MongoDB 8.0+. |
| **`Authentication failed` после обновления до 8.0** | Пользователи созданы под SCRAM-SHA-1, удаленный в 8.0. | `db.getUser(username)`, `db.system.users.find({ mechanisms: { $exists: true } })`. | Пересоздать пользователя или обновить механизм аутентификации. |
| **Высокая латентность при включенном TLS** | Неоптимальные cipher suites или отсутление session resumption. | `openssl s_client -connect host:27017 -brief`. | Настроить `tlsDisabledCipherSuites`, включить TLS session tickets. |
| **`LDAP: authentication failed`** | Неверный `userToDNMapping`, недоступен LDAP-сервер, или неверный bind DN. | `mongosh` с `--authenticationMechanism PLAIN`; логи `mongod`: `grep "LDAP" /var/log/mongodb/mongod.log`. | Проверить `security.ldap.servers`, `bind.dn`, `userToDNMapping`; тестировать через `ldapsearch`. |
| **`GSSAPI: Cannot find key table`** | Keytab не найден, неверные права или SPN не совпадает с `kerberos.serviceName`. | `klist -k /etc/mongodb/mongodb.keytab`; `kinit -kt`. | Создать keytab с правильным SPN (`mongodb/host@REALM`), `chmod 400`, владелец `mongodb`. |
| **`MONGODB-OIDC: not supported`** | Community Edition, версия < 7.0.11, или не-Linux платформа. | `mongod --version` → `modules: subscription`. | Enterprise 7.0.11+ на Linux; проверить `oidcIdentityProviders` в `setParameter`. |
| **OIDC: `token expired`** | Access token истёк (типично 5–60 мин). | Логи IdP; время жизни токена. | Обновлять токен перед подключением; для Workload — использовать client credentials flow. |

---

## Чек-лист аудита безопасности (MongoDB 8.0)

1.  [ ] **Авторизация:** Параметр `security.authorization` установлен в `enabled`.
2.  [ ] **Сетевая изоляция:** База недоступна из публичного интернета, `bindIp` ограничен внутренними интерфейсами.
3.  [ ] **Шифрование трафика:** Используется TLS 1.3, `disabledProtocols` включает TLS1_0 и TLS1_1.
4.  [ ] **Версионность:** Установлены последние патчи безопасности v8.0.x.
5.  [ ] **Секреты:** Пароли и ключи не хранятся в открытом виде (используйте Vault или HashiCorp Vault, Ansible Vault, OS keychain).
6.  [ ] **Аудит:** Включен аудит событий в `systemLog.auditLog` (Enterprise) или перенаправлен во внешний SIEM.
7.  [ ] **Шифрование на диске:** Включено для Enterprise Edition или через LUKS/dm-crypt в Community Edition.
8.  [ ] **Аутентификация:** Используется SCRAM-SHA-256 или x.509. SCRAM-SHA-1 отсутствует.
9.  [ ] **Intra-cluster auth:** Для replica set используется x.509 или keyfile длиной не менее 1024 байт.
10. [ ] **JavaScript отключен:** `javascriptEnabled: false` в `mongod.conf`.
11. [ ] **Привилегии:** Все прикладные пользователи имеют минимально необходимые привилегии (principle of least privilege).
12. [ ] **Резервное копирование:** Бэкапы хранятся в зашифрованном виде и в изолированном хранилище.

---

## Лучшие практики (SRE)

1.  **Принцип минимальных привилегий (PoLP):** Ни один пользователь, кроме администраторов, не должен иметь роль `root` или `clusterAdmin`. Создавайте кастомные роли с точно указанными `actions`.
2.  **SCRAM-SHA-256 по умолчанию:** MongoDB 8.0 исключает SHA-1. При создании пользователя явно указывайте `mechanisms: ["SCRAM-SHA-256"]`.
3.  **TLS везде:** Даже внутри доверенной сети. Включайте `requireTLS` на всех интерфейсах, не только на внешних.
4.  **Сепарация окружений:** Пользователи и ключи для Production, Staging и Development — раздельные. Не используйте одни и те же учетные данные.
5.  **Аудит — непрерывный:** Настройте `auditLog` с ротацией и отправкой в SIEM (Elastic, Splunk, Graylog). Без аудита невозможно расследовать инцидент.
6.  **Шифрование бэкапов:** Логические (`mongodump`) и физические (`mongod` hot backup) бэкапы должны храниться в зашифрованном виде. Включите шифрование на уровне хранилища бэкапов.
7.  **Секреты не в конфигах:** Не храните пароли в `mongod.conf` или приложении. Используйте Vault, Ansible Vault, environment variables, или system keychain.
8.  **Парольная политика:** Если используется LDAP/AD — делегируйте политику туда. В противном случае реализуйте ротацию через CI/CD pipeline.
9.  **Certificate Rotation:** Планируйте ротацию TLS-сертификатов заранее (за 30-60 дней до истечения). Настройте мониторинг срока действия через `openssl` и алерты.
10. **Инцидентный план:** Имейте процедуру отзыва привилегий (`db.revokeRolesFromUser`), блокировки пользователя (`db.updateUser` с пустым паролем или ролью) и ротации ключей в случае компрометации.

---

## Навигация по разделам

Для углубленного изучения выберите соответствующую тему:

*   **[Общий обзор MongoDB](./mongodb.md)** — архитектура и WiredTiger.
*   **[Движок WiredTiger](./mongodb-storage-engine.md)** — кэширование, сжатие, чекпоинты.
*   **[Индексы в MongoDB](./mongodb-indexes.md)** — ESR правило, типы индексов, профилирование.
*   **[Репликация](./mongodb-replication.md)** — Replica Set, кворум, отказоустойчивость.
*   **[Шардирование](./mongodb-sharding.md)** — масштабирование, распределение данных.
*   **[Агрегация](./mongodb-aggregation.md)** — конвейеры обработки денормализованных данных.
*   **[Транзакции](./mongodb-transactions.md)** — атомарность при работе с несколькими документами.
*   **[Time-series коллекции](./mongodb-time-series.md)** — особенности автоматической индексации.
*   **[Решардинг (Live Resharding)](./mongodb-resharding.md)** — изменение ключа без простоя.
*   **[Администрирование](./mongodb-administration.md)** — резервное копирование, обновление, мониторинг.
*   **[Высокая доступность](./high_availability.md)** — архитектуры HA, диагностика отказов.

---

## Дополнительная информация

*   **[Администрирование MongoDB](./mongodb-administration.md)** — обновление версий и мониторинг.
*   **[Установка на Ubuntu](./installation_ubuntu.md)** — пошаговый гайд.
*   **[Безопасная установка СУБД](../installation_security.md)** — общие принципы закалки баз данных.
*   **[Ansible: модули БД](../../Ansible/Modules/ansible_database_modules.md)** — автоматизация развертывания и управления пользователями.
*   **[Kerberos: концепции](../../Security/Concepts/kerberos.md)** — теория Kerberos.
*   **[LDAP: фундамент](../../LDAP/ldap_fundamentals.md)** — теория LDAP и каталогов.
*   **[LDAP: интеграции](../../LDAP/ldap_integrations.md)** — интеграция LDAP с сервисами.
