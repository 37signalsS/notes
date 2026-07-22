# Grafana: Управление пользователями и аутентификация

## Определения

**Управление пользователями и аутентификация** в Grafana — комплекс механизмов для идентификации субъектов (пользователей и сервисов) и разграничения их прав доступа к ресурсам платформы (дашбордам, источникам данных, настройкам). Современная архитектура Grafana (v11+) базируется на развитой системе RBAC, позволяющей гибко настраивать разрешения вплоть до конкретных действий над объектами.

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Провиженинг](./grafana_provisioning.md) — автоматизация конфигурации через YAML
- [OAuth 2.0 и OIDC](../../Security/Concepts/oauth2_overview.md) — теоретическая база протоколов аутентификации
- [LDAP и SSSD](../../Linux/SystemAdministration/Users/LDAP_SSSD/operations.md) — интеграция с корпоративными каталогами

## Базовые концепции

### Иерархия доступа

1. **Организации (Organizations)** — высший уровень изоляции. Дашборды, источники данных и пользователи в одной организации полностью отделены от других. Переключение между организациями требует повторной авторизации или настройки SSO.
2. **Команды (Teams)** — группы пользователей для упрощения управления правами. Позволяют назначать доступы к папкам и дашбордам не индивидуально, а на основе членства в команде.
3. **Папки (Folders)** — контейнеры для дашбордов. Права доступа (View, Edit, Admin), назначенные на папку, наследуются всеми объектами внутри неё.

### Роли и RBAC (Role-Based Access Control)

Начиная с версии 11, расширенное управление доступом (Fine-grained access control) стало доступно в Open Source версии.

**Базовые роли организации:**
- **Viewer:** Просмотр дашбордов, панелей и алертов. Не может вносить изменения.
- **Editor:** Создание и редактирование дашбордов, папок и источников данных.
- **Admin:** Полный административный доступ к настройкам Организации, управлению командами и пользователями.

**Кастомные роли (RBAC):**
Позволяют создавать наборы разрешений для специфических задач (например, `DataSource-Reader`, `Alert-Manager`) и назначать их пользователям или командам. Это реализует принцип минимальных привилегий (Least Privilege).

### Субъекты доступа

| Субъект | Назначение | Особенности |
| :--- | :--- | :--- |
| **User** | Реальный человек | Вход через логин/пароль или SSO (OAuth/LDAP). |
| **Service Account** | Программный доступ | Замена устаревшим API Keys. Принадлежит организации, поддерживает несколько токенов с разными сроками действия. |
| **Anonymous User** | Публичный доступ | Позволяет просматривать дашборды без входа (настраивается в `grafana.ini`). |

## Методы аутентификации

### Встроенная аутентификация
Использование локальной базы данных Grafana (SQLite/Postgres/MySQL) для хранения учетных записей. Подходит для небольших инсталляций или начального этапа.

### Внешняя аутентификация (SSO)
Рекомендуемый способ для корпоративных сред, позволяющий централизованно управлять доступом.

| Метод | Описание | Сценарий использования |
| :--- | :--- | :--- |
| **OAuth 2.0 / OIDC** | GitHub, GitLab, Google, Keycloak, Azure AD | Веб-ориентированные окружения, интеграция с провайдерами идентификации. |
| **LDAP** | Active Directory, OpenLDAP | Традиционные корпоративные каталоги. Поддерживает синхронизацию групп в команды (Team Sync). |
| **SAML** | Okta, Auth0, Ping Identity | Крупные корпорации (Enterprise/Pro функционал). |
| **JWT** | Аутентификация по токену | Интеграция Grafana в сторонние порталы (Embedding). |
| **WIF** | Workload Identity Federation | Аутентификация без статических ключей в облаках (GCP, AWS). Доступно в Grafana 13. |

## Практические сценарии

### 1. Настройка OAuth через GitHub

Позволяет пользователям входить в Grafana, используя свою учетную запись GitHub.

```ini
# grafana.ini
[auth.github]
enabled = true
allow_sign_up = true
client_id = ${GF_AUTH_GITHUB_CLIENT_ID}
client_secret = ${GF_AUTH_GITHUB_CLIENT_SECRET}
scopes = user:email,read:org
allowed_organizations = my-tech-org # Доступ только членам организации в GitHub
role_attribute_path = contains(groups[*], 'admins') && 'Admin' || contains(groups[*], 'devs') && 'Editor' || 'Viewer'
```

### 2. Настройка анонимного доступа

Используется для создания публичных мониторов (Wallboards).

```ini
# grafana.ini
[auth.anonymous]
enabled = true
org_name = Main Org.
org_role = Viewer
hide_version = true
```

### 3. Управление сервисными аккаунтами через API

Для автоматизации (CI/CD, Terraform) необходимо использовать токены сервисных аккаунтов.

```bash
# Пример использования токена для получения списка дашбордов
curl -H "Authorization: Bearer <SA_TOKEN>" \
     http://grafana.example.com/api/search?type=dash-db
```

### 4. Интеграция с LDAP (Active Directory)

Требует настройки файла `ldap.toml`.

```toml
# ldap.toml
[[servers]]
host = "ad.example.com"
port = 636
use_ssl = true
bind_dn = "cn=grafana_bind,ou=users,dc=example,dc=com"
bind_password = 'password'

[servers.attributes]
name = "givenName"
surname = "sn"
username = "sAMAccountName"
member_of = "memberOf"
email = "mail"

[[servers.group_mappings]]
group_dn = "cn=admins,ou=groups,dc=example,dc=com"
org_role = "Admin"

[[servers.group_mappings]]
group_dn = "cn=users,ou=groups,dc=example,dc=com"
org_role = "Viewer"
```

## Дополнительная информация

### Рекомендации по безопасности

- **Отказ от API-ключей:** В версиях 12+ API-ключи считаются Legacy. Всегда используйте Service Accounts для новой автоматизации.
- **Двухфакторная аутентификация (2FA):** Grafana не имеет встроенной 2FA для локальных пользователей; реализуйте её на уровне внешнего провайдера (Keycloak, Google, GitHub).
- **Синхронизация ролей (Role Mapping):** Настраивайте автоматическое назначение ролей (Admin/Editor) на основе групп в OAuth/LDAP, чтобы избежать ручного управления правами.
- **Secure Key:** Убедитесь, что `secret_key` в `grafana.ini` является сложной строкой и одинаков для всех узлов в HA-кластере.

### Полезные ссылки

- [Официальная документация: Authentication](https://grafana.com/docs/grafana/latest/administration/authentication/)
- [Настройка Service Accounts](https://grafana.com/docs/grafana/latest/administration/service-accounts/)
- [Grafana API Reference](https://grafana.com/docs/grafana/latest/developers/http_api/)
- [Terraform Provider: Access Control](https://registry.terraform.io/providers/grafana/grafana/latest/docs/resources/role)
