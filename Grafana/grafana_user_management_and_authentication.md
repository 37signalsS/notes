# Grafana: Управление пользователями и аутентификация

## Определения

**Управление пользователями и аутентификация** в Grafana — комплекс механизмов для идентификации субъектов (пользователей и программных агентов) и разграничения их прав доступа к ресурсам платформы (дашбордам, источникам данных, алертам и настройкам). Состояние на 2026 год (версии 13.x) характеризуется окончательным переходом к модели **Service Accounts** как основному способу программного доступа и повсеместным использованием **Fine-grained access control (RBAC)** в Open Source версии.

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Провиженинг](./grafana_provisioning.md) — автоматизация конфигурации через YAML
- [OAuth 2.0 и OIDC](../../Security/Concepts/oauth2_overview.md) — теоретическая база протоколов аутентификации
- [LDAP и SSSD](../../Linux/SystemAdministration/Users/LDAP_SSSD/operations.md) — интеграция с корпоративными каталогами

## Базовые концепции

### Иерархия доступа

1.  **Организации (Organizations):** Высший уровень изоляции. Дашборды, источники данных и пользователи полностью разделены.
    -   **Multi-org membership:** Один пользователь может состоять в нескольких организациях с разными ролями.
    -   **Переключение:** В интерфейсе через меню профиля; в API — через заголовок `X-Grafana-Org-Id`.
2.  **Команды (Teams):** Группы пользователей внутри одной организации.
    -   **Назначение:** Группировка для упрощения выдачи прав на папки и дашборды.
    -   **Team Sync:** Автоматическая синхронизация членства в командах на основе групп из внешних провайдеров (LDAP, GitHub, SAML).
3.  **Папки (Folders):** Логические контейнеры. Права доступа (View, Edit, Admin), назначенные на папку, наследуются всеми объектами внутри неё.

### Роли и RBAC (Role-Based Access Control)

Начиная с версии 11, расширенное управление доступом (Fine-grained access control) стало доступно в Open Source версии.

**Базовые роли организации:**
- **Viewer:** Просмотр дашбордов, панелей и алертов. Не может вносить изменения.
- **Editor:** Создание и редактирование дашбордов, папок и источников данных.
- **Admin:** Полный административный доступ к настройкам организации, управлению командами и пользователями.

**Кастомные роли и экшены (RBAC):**
Позволяют создавать наборы разрешений для специфических задач. Примеры доступных экшен-областей:
- `dashboards:read`, `dashboards:write` — операции с дашбордами.
- `datasources:query`, `datasources:explore` — доступ к данным.
- `folders:create`, `folders:delete` — управление структурой.
- `org.users:add`, `org.users:remove` — управление пользователями.
- `alert.rules:read`, `alert.rules:write` — управление алертами.

### Субъекты доступа

| Субъект | Назначение | Особенности (2026) |
| :--- | :--- | :--- |
| **User** | Реальный человек | Вход через логин/пароль или SSO (OAuth/LDAP). |
| **Service Account** | Программный доступ | **Замена устаревшим API Keys**. Принадлежит организации, поддерживает несколько токенов с разными сроками действия и RBAC. |
| **Anonymous User** | Публичный доступ | Просмотр без входа (Wallboards). Настраивается в `grafana.ini`. |

## Методы аутентификации

### Внешняя аутентификация (SSO)
Рекомендуемый способ для корпоративных сред.

| Метод | Описание | Сценарий использования |
| :--- | :--- | :--- |
| **OAuth 2.0 / OIDC** | GitHub, GitLab, Google, Keycloak, Azure AD | Основной метод для веб-сред. Поддерживает динамическое сопоставление ролей (Role Mapping). |
| **LDAP** | Active Directory, OpenLDAP | Корпоративные каталоги. Поддерживает глубокую синхронизацию групп в команды (Team Sync). |
| **Workload Identity Federation (WIF)** | GCP, AWS, Azure | **Новое в v13**. Аутентификация без статических секретов для Grafana, запущенной в облачных кластерах. |
| **JWT** | Аутентификация по токену | Интеграция Grafana в сторонние порталы (Embedding). |
| **SAML** | Okta, Auth0, Ping Identity | Крупные корпорации (Enterprise функционал). |

### Встроенная аутентификация
Использование локальной БД (SQLite/Postgres/MySQL). В Grafana 13 реализованы строгие политики сложности паролей и защита от перебора (Brute-force protection).

## Практические сценарии

### 1. Настройка OAuth через GitHub

Позволяет пользователям входить в Grafana, используя свою учетную запись GitHub, с автоматическим назначением ролей.

```ini
# grafana.ini
[auth.github]
enabled = true
allow_sign_up = true
client_id = ${GF_AUTH_GITHUB_CLIENT_ID}
client_secret = ${GF_AUTH_GITHUB_CLIENT_SECRET}
scopes = user:email,read:org
allowed_organizations = my-tech-org
# Сопоставление ролей на основе команд в GitHub
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

### 3. Управление сервисными аккаунтами (API и Провиженинг)

Для автоматизации (CI/CD, Terraform) необходимо использовать токены сервисных аккаунтов.

**Пример использования через curl:**
```bash
# Получение списка дашбордов с использованием токена SA
curl -H "Authorization: Bearer <SA_TOKEN>" \
     http://grafana.example.com/api/search?type=dash-db
```

**Декларативное создание (Провиженинг):**
```yaml
# /etc/grafana/provisioning/service-accounts/sa.yaml
apiVersion: 1
serviceAccounts:
  - name: "Terraform-Deployer"
    role: "Admin"
    orgId: 1
    tokens:
      - name: "tf-token-2026"
        expires: "2027-01-01"
```

### 4. Интеграция с LDAP (Active Directory)

Требует настройки файла `ldap.toml`. Поддерживает сопоставление групп AD с ролями Grafana.

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

### 5. Миграция с API Keys на Service Accounts

API-ключи (Legacy) привязаны к пользователю, создавшему их. Service Accounts — это самостоятельные сущности.

1.  **Создайте Service Account:** В UI (Administration > Users and access > Service accounts) или через API.
2.  **Назначьте роль:** Выберите соответствующую RBAC-роль (например, `Editor`).
3.  **Сгенерируйте токен:** Скопируйте новый Bearer-токен.
4.  **Обновите интеграции:** Замените старый API Key на новый токен в Terraform/Ansible/скриптах.

### 6. Настройка Workload Identity Federation (WIF) для GCP

Позволяет Grafana аутентифицироваться в Google Cloud без использования JSON-ключей сервисных аккаунтов.

```ini
# grafana.ini (v13+)
[auth.generic_oauth]
enabled = true
name = Google Cloud WIF
client_id = ${GCP_WIF_CLIENT_ID}
use_pkce = true
auth_url = https://accounts.google.com/o/oauth2/v2/auth
token_url = https://oauth2.googleapis.com/token
# Identity Provider доверяет токенам пода из K8s
```

## Дополнительная информация

### Рекомендации по безопасности

- **Отказ от API-ключей:** В версиях 12+ API-ключи считаются Legacy. Всегда используйте Service Accounts для новой автоматизации.
- **Двухфакторная аутентификация (2FA):** Grafana не имеет встроенной 2FA для локальных пользователей; реализуйте её на уровне внешнего провайдера (Keycloak, Google, GitHub) через OIDC/SAML.
- **Синхронизация ролей (Role Mapping):** Настраивайте автоматическое назначение ролей (Admin/Editor) на основе групп в OAuth/LDAP, чтобы избежать ручного управления правами.
- **Защита `secret_key`:** Убедитесь, что `secret_key` в `grafana.ini` является сложной строкой и одинаков для всех узлов в HA-кластере. Он используется для шифрования секретов в БД.

### Полезные ссылки

- [Официальная документация: Authentication](https://grafana.com/docs/grafana/latest/administration/authentication/)
- [Настройка Service Accounts](https://grafana.com/docs/grafana/latest/administration/service-accounts/)
- [Grafana RBAC Actions List](https://grafana.com/docs/grafana/latest/administration/access-control/permissions/)
- [Grafana API Reference](https://grafana.com/docs/grafana/latest/developers/http_api/)
- [Terraform Provider: Access Control](https://registry.terraform.io/providers/grafana/grafana/latest/docs/resources/role)
