# Keycloak — LDAP Federation

## Определения

**Keycloak** — система идентификации и управления доступом (Identity and Access Management, IAM) с открытым исходным кодом. Обеспечивает единую точку входа (SSO), поддерживает OAuth 2.0, OpenID Connect (OIDC) и SAML 2.0.

**User Federation** — механизм в Keycloak, позволяющий получать пользователей из внешних источников (LDAP, Active Directory и др.), не создавая их в собственной базе Keycloak.

---

## Базовые концепции

### Архитектура User Federation

Keycloak может выступать как:
1. **Читающий источник (Read-only):** Пользователи аутентифицируются через LDAP, но изменения (смена пароля, атрибутов) не синхронизируются обратно в LDAP.
2. **Источник записи (Writable):** Позволяет создавать, изменять и удалять пользователей в LDAP через Keycloak.

### Поддерживаемые провайдеры

- Active Directory
- Red Hat Directory Server
- Tivoli Directory Server
- Novell eDirectory
- **OpenLDAP** (generic LDAP)

---

## Практические сценарии

### Настройка LDAP Federation в Keycloak

#### Предварительные требования

1. Развёрнутый Keycloak (рекомендуется через Helm chart)
2. Настроенный OpenLDAP с пользователями
3. SSL/TLS на OpenLDAP (опционально, но рекомендуется)

#### Шаги настройки

1. **Создание Realm:**
   - В Keycloak создать новый Realm (или использовать существующий)

2. **Добавление User Federation:**
   - Перейти: **User Federation** → **Add provider** → **ldap**
   - Указать параметры подключения

3. **Основные параметры подключения:**

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Vendor** | `other` | Для OpenLDAP |
| **Connection URL** | `ldap://ldap.example.com:389` | URL LDAP-сервера |
| **Bind DN** | `cn=admin,dc=example,dc=com` | DN для подключения |
| **Bind Credentials** | `password` | Пароль администратора |
| **Test Connection** | — | Проверка соединения |
| **Test Authentication** | — | Проверка аутентификации |

4. **Режим синхронизации:**

| Параметр | Описание |
| :--- | :--- |
| **Import Users** | Импорт пользователей в Keycloak |
| **Edit Mode** | `READONLY` — только чтение из LDAP |
| | `WRITABLE` — чтение и запись в LDAP |
| | `UNSYNCED` — хранение в Keycloak без синхронизации |

5. **Параметры поиска пользователей:**

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Users DN** | `ou=users,dc=example,dc=com` | DN для поиска пользователей |
| **LDAP Username Attribute** | `uid` | Атрибут для логина (RDn) |
| **RDN Attribute** | `uid` | Атрибут RDN |
| **User Object Classes** | `person, organizationalPerson, inetOrgPerson, posixAccount` | Object Classes пользователя |

6. **Сохранение и тестирование:**
   - Сохранить настройки
   - Проверить подключение кнопкой **Test Connection**

#### Особенности работы с OpenLDAP

- **Атрибут `uid`:** Рекомендуется использовать `uid` в качестве username, так как:
  - Не содержит кириллицы
  - Однозначно идентифицирует пользователя
  - Используется в POSIX-совместимых системах

- **UUID:** Keycloak использует атрибут `UUID` для идентификации пользователей. В OpenLDAP это `entryUUID`. При настройке federation необходимо правильно маппить этот атрибут.

- **Пароли:** Для аутентификации используется атрибут `userPassword`. При режиме `WRITABLE` возможна смена пароля через Keycloak.

#### Синхронизация пользователей

- **Periodic Full Sync:** Полная синхронизация всех пользователей
- **Incremental Sync:** Синхронизация изменений (при наличии изменений в LDAP)

---

## Дополнительная информация

### Ограничения

1. **Сертификаты:** При использовании LDAPS (port 636) требуется добавить CA-сертификат в доверенные хранилища Keycloak
2. **StartTLS:** Для шифрования на порту 389 требуется дополнительная настройка
3. **Атрибуты:** Не все атрибуты LDAP автоматически маппируются в Keycloak

### Безопасность

- Использовать сертификаты SSL/TLS для production
- Применять принцип наименьших привилегий для Bind DN
- Рекомендуется режим `READONLY` для production-систем
- Хранить пароли в защищённом виде

### Инструменты

- **Apache Directory Studio** — для управления LDAP
- **Keycloak Admin Console** — веб-интерфейс управления

### Ссылки

- [OpenLDAP в Kubernetes](../LDAP/openldap_kubernetes.md)
- [LDAP в Linux](../../Linux/SystemAdministration/users_management.md#LDAP-Lightweight-Directory-Access-Protocol)
