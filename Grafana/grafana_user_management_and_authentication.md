# Grafana: Управление пользователями и аутентификация

## Определения

**Управление пользователями и аутентификация** в Grafana — комплекс механизмов для идентификации субъектов (пользователей и программных агентов) и разграничения их прав доступа к ресурсам платформы (дашбордам, источникам данных, алертам и настройкам). Состояние на 2026 год (версии 13.x) характеризуется окончательным переходом к модели **Service Accounts** как основному способу программного доступа и повсеместным использованием **Fine-grained access control (RBAC)** в Open Source версии.

**Grafana Admin (серверный администратор)** — особая глобальная роль, не привязанная ни к одной организации. Имеет доступ ко всем организациям и ко всем настройкам сервера (включая управление другими администраторами). Отличается от роли **Admin** уровня организации, которая властна только в рамках своей организации.

**Сессия и токен** — два способа доказать Grafana, кто делает запрос. Для веб-интерфейса после входа выдаётся подписанный cookie-сессии; для API и автоматизации используется `Authorization: Bearer <token>` (токен сервисного аккаунта или устаревший API-ключ). Токены и сессии привязаны к организации, в которой они созданы.

**Хранение идентификационных данных** — учётные записи, роли, токены и привязки команд хранятся в базе Grafana (SQLite по умолчанию, либо PostgreSQL/MySQL). Пароли пользователей хешируются (PBKDF2 по умолчанию), секреты (пароли источников данных, токены сервисных аккаунтов) шифруются с использованием `secret_key`.

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе, включая раздел безопасности
- [Провиженинг](./grafana_provisioning.md) — автоматизация конфигурации через YAML (в т.ч. сервисные аккаунты)
- [Безопасность и жёсткая настройка](./grafana_security_hardening.md) — hardening, TLS, секреты, защита источников данных
- [OAuth 2.0 и OIDC](../Security/Concepts/oauth2_overview.md) — теоретическая база протоколов аутентификации
- [LDAP и SSSD](../Linux/SystemAdministration/Users/LDAP_SSSD/operations.md) — интеграция с корпоративными каталогами

## Базовые концепции

### Иерархия доступа

1.  **Организации (Organizations):** Высший уровень изоляции. Дашборды, источники данных и пользователи полностью разделены.
    -   **Multi-org membership:** Один пользователь может состоять в нескольких организациях с разными ролями.
    -   **Переключение:** В интерфейсе через меню профиля; в API — через заголовок `X-Grafana-Org-Id` (допустим только для сессии Grafana Admin; токены сервисных аккаунтов жёстко привязаны к той организации, в которой созданы).
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

**Встроенные (fixed) роли** — предопределённые наборы прав, назначаемые графанами «из коробки»:
- `Grafana Admin` — серверный администратор (глобально, вне организаций).
- `Admin` / `Editor` / `Viewer` — роли уровня организации (см. выше).
- `None` — явное отсутствие прав в организации (пользователь аутентифицирован, но ничего не видит).

**Кастомные роли и экшены (RBAC):**
Позволяют создавать наборы разрешений для специфических задач. Примеры доступных экшен-областей:
- `dashboards:read`, `dashboards:write` — операции с дашбордами.
- `datasources:query`, `datasources:explore` — доступ к данным.
- `folders:create`, `folders:delete` — управление структурой.
- `org.users:add`, `org.users:remove` — управление пользователями.
- `alert.rules:read`, `alert.rules:write` — управление алертами.

Создание и назначение кастомных ролей доступно через API в Open Source версии. Расширенное управление в веб-интерфейсе (назначение ролей через UI, Team Sync для RBAC) относится к возможностям Enterprise.

**Назначение ролей** происходит на уровне организации и привязывается к субъекту (пользователю, команде или сервисному аккаунту). Итоговые права субъекта — объединение (union) всех назначенных ему ролей и ролей его команд.

### Тонкая модель прав доступа (permissions на ресурсы)

Помимо организационных ролей и RBAC, Grafana позволяет задавать явные права на конкретные ресурсы. Это необходимо, когда в одной организации разные команды должны видеть разные источники данных или разные наборы дашбордов при одинаковой базовой роли.

- **Data source permissions.** По умолчанию источник данных виден всем пользователям организации с ролью Viewer и выше (они могут к нему обращаться). Включение тонких прав на источник (`datasources:*` permissions) меняет поведение на «по умолчанию запрещено»: после включения источник видят только явно назначенные субъекты (пользователи/команды/сервисные аккаунты). Это добавляет в RBAC экшены уровня источника (`datasources:read`, `datasources:query`, `datasources:explore`).
- **Folder permissions.** Права на папку (View/Edit/Admin) наследуются всеми вложенными дашбордами и вложенными папками. Удобны для изоляции команд: одна команда — одна папка.
- **Dashboard permissions.** Дашборд наследует права своей папки, но право можно переопределить непосредственно на дашборде (View/Edit/Admin), если отключить наследование.
- **Annotation permissions.** Кто может создавать аннотации на дашборде, настраивается отдельно и независимо от прав на редактирование самого дашборда.

Тонкие права включаются в UI (Connections → Data sources → Permissions; Dashboard → Folder permissions) либо через API. Они ортогональны RBAC: RBAC определяет, может ли субъект вообще выполнять экшен (например, `datasources:query`), а permissions на ресурс — к каким конкретно источникам/папкам это применимо.

### Субъекты доступа

| Субъект | Назначение | Особенности (2026) |
| :--- | :--- | :--- |
| **User** | Реальный человек | Вход через логин/пароль или SSO (OAuth/LDAP). |
| **Service Account** | Программный доступ | **Замена устаревшим API Keys**. Принадлежит организации, поддерживает несколько токенов с разными сроками действия и RBAC. |
| **Anonymous User** | Публичный доступ | Просмотр без входа (Wallboards). Настраивается в `grafana.ini`. |

### Жизненный цикл аутентификации и токенов

- **Веб-вход (UI):** пользователь открывает `/login` → Grafana перенаправляет на провайдера (OAuth/SAML) или показывает локальную форму → после успеха Grafana создаёт/обновляет запись пользователя в БД и выдаёт подписанный cookie-сессии (подпись проверяется через `secret_key`). Дальнейшие запросы аутентифицируются по cookie.
- **API / автоматизация:** клиент передаёт `Authorization: Bearer <token>`. Grafana сверяет токен с хешем в БД (для токенов сервисных аккаунтов), проверяет срок действия и область организации. Чтобы обратиться от имени другой организации, Grafana Admin использует заголовок `X-Grafana-Org-Id`; токен сервисного аккаунта всегда «заперт» в своей организации.
- **Ротация и отзыв:** токены сервисных аккаунтов можно отозвать по одному (`DELETE /api/serviceaccounts/{id}/tokens/{tokenId}`) без затрагивания остальных. Токены могут быть бессрочными (поле `expires` не задано) — этого следует избегать из соображений безопасности.

### Хранение и защита секретов

- **`secret_key`** (в `grafana.ini` секция `[security]` или переменная `GF_SECURITY_SECRET_KEY`): используется для подписи cookie-сессий и шифрования секретов в БД (пароли источников данных, токены сервисных аккаунтов, пароль LDAP-bind). Должен быть сложным и **одинаковым на всех узлах в HA-кластере** — иначе сессии одного узла не принимаются другим, а зашифрованные секреты не расшифровываются.
- **Пароли пользователей** хешируются (PBKDF2 по умолчанию); при внешней аутентификации локальный пароль не используется, но запись всё равно создаётся.
- **Токены** сервисных аккаунтов хранятся в БД в виде хеша; само значение токена показывается только один раз в момент создания.

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
| **Auth proxy** | Заголовки от обратного прокси (nginx/Apache) | SSO без OAuth/SAML: прокси аутентифицирует пользователя и передаёт его имя/группы в заголовках. |

### Встроенная аутентификация

Использование локальной БД (SQLite/Postgres/MySQL). В Grafana 13 реализованы строгие политики сложности паролей и защита от перебора (Brute-force protection).

### Auth proxy (аутентификация через обратный прокси)

Когда перед Grafana уже стоит корпоративный обратный прокси (nginx/Apache/Traefik), который сам аутентифицирует пользователя (например, через `auth_request` к Keycloak, mTLS или Apache mod_auth), Grafana может доверять заголовкам, переданным прокси. Это даёт SSO без настройки отдельного OAuth/SAML и полезно в закрытых контурах.

Принцип: прокси проверяет учётные данные клиента, затем добавляет заголовок с именем пользователя (и опционально — группами/ролями) и проксирует запрос в Grafana. Grafana читает `X-WEBAUTH-USER` (имя настраивается), при `auto_sign_up = true` создаёт/обновляет пользователя в БД и, при наличии заголовка групп, назначает роль через `role_attribute_path` (аналогично сценарию 1).

**Критическое требование безопасности:** Grafana доверяет заголовку без проверки подписи. Прокси обязан жёстко отсекать любые входящие от клиента заголовки с этим именем (например, `proxy_set_header X-WEBAUTH-USER ""` перед внешним `auth_request`, либо `proxy_hide_header`/фильтрация на входе), иначе пользователь может подделать свою личность. Подробности по защите прокси — в разделе безопасности.

### Проверка текущей идентификации

Универсальная проверка для любого токена/сессии — запрос к `GET /api/user`:

```bash
# Кто я от имени этого токена? (SA-токен или сессия)
curl -s -H "Authorization: Bearer <SA_TOKEN>" \
     http://grafana.example.com/api/user
# → {"id":2,"login":"terraform-deployer","orgId":1,"role":"Admin","isGrafanaAdmin":false}
```

Поле `role` показывает базовую роль в текущей организации, `isGrafanaAdmin` — признак серверного администратора, `orgId` — организацию, к которой привязан токен.

## Практические сценарии

### Предварительные требования

- **Grafana 13.x** (актуально на 2026 год; 12.x — LTS; 11.x — EOL с июня 2026). Для RBAC в OSS требуется не ниже v11; для WIF — не ниже v13.
- Доступ к файлу `grafana.ini` (или переменным окружения `GF_*`) и к каталогу провиженинга (`/etc/grafana/provisioning/...`).
- Для внешней аутентификации — заранее зарегистрированное приложение OAuth (client_id/client_secret), либо доступный LDAP-сервер, либо настроенный провайдер SAML/OIDC.
- Для запросов к API — токен сервисного аккаунта с нужной ролью (см. сценарий 5) или сессия администратора. Базовый URL API: `http://grafana.example.com/api` (порт 3000 по умолчанию).
- Корректный `root_url` в `[server]` — от него зависят callback-адреса OAuth/SAML и ссылки в письмах сброса пароля.
- **Единый `secret_key`** на всех узлах, если Grafana работает в отказоустойчивой конфигурации.

### 1. Настройка OAuth через GitHub

Позволяет пользователям входить в Grafana, используя свою учетную запись GitHub, с автоматическим назначением ролей.

```ini
# grafana.ini
[server]
root_url = https://grafana.example.com

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

**Параметры:**
- `root_url` — полный внешний URL; callback для GitHub формируется как `<root_url>/login/github`.
- `scopes = read:org` — обязателен, чтобы Grafana могла прочитать членство в организации/командах для `role_attribute_path`.
- `allowed_organizations` — ограничивает вход только участникам указанной GitHub-организации.
- `role_attribute_path` — выражение (синтаксис JMESPath) для преобразования утверждений провайдера в роль Grafana.

**Валидация:**
1. В GitHub OAuth App укажите Authorization callback URL = `https://grafana.example.com/login/github`.
2. Перезапустите Grafana и откройте `/login` → нажмите значок GitHub → авторизуйтесь.
3. Убедитесь, что роль применилась, запросом от нового токена/сессии:

```bash
curl -s -H "Authorization: Bearer <TOKEN>" http://grafana.example.com/api/user
# → {"login":"alice","orgId":1,"role":"Editor",...}   # роль из role_attribute_path
```

Если возвращается `role:"Viewer"` вопреки ожиданиям — проверьте, что у GitHub-токена есть scope `read:org`, пользователь состоит в `allowed_organizations` и выражение `role_attribute_path` корректно (см. раздел «Типичные ошибки»).

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

**Параметры:**
- `org_name` — организация, от лица которой действует анонимный пользователь (должна существовать).
- `org_role` — роль анонима в этой организации (обычно `Viewer`).
- `hide_version` — не показывать версию Grafana в футере публичной страницы.

**Валидация:**

```bash
# Без токена — должен вернуть данные организации (аноним имеет хотя бы Viewer)
curl -s http://grafana.example.com/api/org
# → {"id":1,"name":"Main Org.","url":"..."}
# Если 401 — анонимный доступ выключен или org_role/org_name указаны неверно.
```

### 3. Создание организации, команды и добавление пользователя через API

Программное управление идентификационными данными (вместо ручных действий в UI), например, из Ansible/Terraform.

```bash
# 3.1 Создать организацию (требуется роль Grafana Admin)
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"name":"team-infra"}' \
     http://grafana.example.com/api/orgs
# → {"orgId":2,"message":"Organization created"}

# 3.2 Создать команду внутри организации
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"name":"sre-team"}' \
     http://grafana.example.com/api/teams
# → {"teamId":3,"message":"Team created"}

# 3.3 Создать пользователя (локальная БД)
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"name":"Bob","email":"bob@example.com","login":"bob","password":"<strong-password>"}' \
     http://grafana.example.com/api/admin/users
# → {"id":4,"message":"User created"}

# 3.4 Добавить пользователя в организацию с ролью Editor (X-Grafana-Org-Id задаёт целевую org)
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
     -H "Content-Type: application/json" -H "X-Grafana-Org-Id: 2" \
     -d '{"loginOrEmail":"bob","role":"Editor"}' \
     http://grafana.example.com/api/org/users
# → {"message":"User added to organization"}

# 3.5 Добавить пользователя в команду
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"loginOrEmail":"bob"}' \
     http://grafana.example.com/api/teams/3/members
# → {"message":"Member added to Team"}
```

**Валидация:** `GET /api/org/users` (с нужным `X-Grafana-Org-Id`) возвращает список с `bob` и ролью `Editor`; `GET /api/teams/3/members` — список участников команды.

### 4. Управление сервисными аккаунтами (API и Провиженинг)

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

**Создание через API (полный цикл):**
```bash
# 4.1 Создать сервисный аккаунт с базовой ролью
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"name":"ci-runner","role":"Editor","isDisabled":false}' \
     http://grafana.example.com/api/serviceaccounts
# → {"id":5,"name":"ci-runner","role":"Editor",...}

# 4.2 Создать токен для этого аккаунта
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"name":"ci-token","secondsToLive":31536000}' \
     http://grafana.example.com/api/serviceaccounts/5/tokens
# → {"id":7,"name":"ci-token","key":"glsa_xxxxxxxxxxxxxxxx"}   # key показывается ОДИН раз

# 4.3 Проверить токен
curl -s -H "Authorization: Bearer <KEY>" http://grafana.example.com/api/user
# → {"login":"ci-runner","orgId":1,"role":"Editor",...}

# 4.4 Перечислить токены аккаунта (само значение не возвращается)
curl -s -H "Authorization: Bearer <ADMIN_TOKEN>" \
     http://grafana.example.com/api/serviceaccounts/5/tokens

# 4.5 Отозвать конкретный токен (например, при компрометации), не трогая остальные
curl -s -X DELETE -H "Authorization: Bearer <ADMIN_TOKEN>" \
     http://grafana.example.com/api/serviceaccounts/5/tokens/7
# → {"message":"Service account token deleted"}
```

**Ротация:** создавайте новый токен (4.2), обновляйте его в секретнице/CI, затем отзывайте старый (4.5). Используйте `secondsToLive` (или `expires` в провиженинге), чтобы токены не были бессрочными.

### 5. Создание кастомной RBAC-роли и назначение через API

Вместо выдачи широкой роли `Admin`/`Editor` можно создать минимально необходимый набор прав.

```bash
# 5.1 Создать кастомную роль с нужными экшенами (в текущей организации)
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"name":"dashboard-viewer-explorer","description":"Только просмотр и explore",
          "version":1,
          "global":false,
          "permissions":[
            {"action":"dashboards:read"},
            {"action":"datasources:explore"},
            {"action":"datasources:query"}
          ]}' \
     http://grafana.example.com/api/access-control/roles
# → {"role":{"name":"dashboard-viewer-explorer","uid":"...","version":1}}

# 5.2 Назначить роль сервисному аккаунту (по uid роли и login субъекта)
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"roleUid":"<ROLE_UID>","users":[],"serviceAccounts":[5]}' \
     http://grafana.example.com/api/access-control/roles/<ROLE_UID>/assignments
# → {"message":"Role assigned"}
```

**Валидация:** запрос от токена этого аккаунта к защищённому экшену проходит, к запрещённому (например, `POST /api/dashboards/db` при отсутствии `dashboards:write`) — возвращает `403`. Список назначений: `GET /api/access-control/roles/<ROLE_UID>/assignments`.

> Полный список экшенов — в [Grafana RBAC Actions List](https://grafana.com/docs/grafana/latest/administration/access-control/permissions/).

### 6. Интеграция с LDAP (Active Directory)

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

**Валидация:**
1. Отдельно проверьте bind вне Grafana (диагностика до запуска):

```bash
ldapsearch -H ldaps://ad.example.com:636 -D "cn=grafana_bind,ou=users,dc=example,dc=com" \
           -W -b "dc=example,dc=com" "(sAMAccountName=alice)" memberOf
# → возвращает запись пользователя и список memberOf (должен содержать group_dn из mappings)
```

2. В Grafana включите `[auth.ldap] enabled = true`, перезапустите, выполните вход пользователем из AD. Проверьте роль через `GET /api/user` от его сессии.
3. При проблемах включите трассировку: `[log] filters = ldap:debug` в `grafana.ini` и смотрите логи Grafana.

### 7. Миграция с API Keys на Service Accounts

API-ключи (Legacy) привязаны к пользователю, создавшему их. Service Accounts — это самостоятельные сущности.

1.  **Создайте Service Account:** В UI (Administration > Users and access > Service accounts) или через API.
2.  **Назначьте роль:** Выберите соответствующую RBAC-роль (например, `Editor`).
3.  **Сгенерируйте токен:** Скопируйте новый Bearer-токен.
4.  **Обновите интеграции:** Замените старый API Key на новый токен в Terraform/Ansible/скриптах.

**Валидация:** старый API-ключ можно отозвать в UI (Administration > Service accounts > API keys) или API `DELETE /api/auth/keys/{id}`; убедитесь, что интеграции продолжают работать с новым SA-токеном (см. 4.3). API-ключи считаются Legacy начиная с версии 12.

### 8. Настройка Workload Identity Federation (WIF) для GCP

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

**Валидация:** после настройки и перезапуска выполните вход через провайдера WIF; проверьте, что сессия создаётся без ошибок обмена токеном (отсутствие `oauth2: token exchange failed` в логах). Убедитесь, что audience/client_id соответствует пулу Workload Identity в GCP, а ServiceAccount в кластере аннотирован нужным email.

### 9. Auth proxy через nginx (SSO без OAuth/SAML)

Позволяет переиспользовать уже настроенную аутентификацию на обратном прокси. Grafana доверяет заголовку с именем пользователя.

```ini
# grafana.ini
[server]
root_url = https://grafana.example.internal/

[auth.proxy]
enabled = true
header_name = X-WEBAUTH-USER
header_property = username
auto_sign_up = true
# Имя заголовка с группами (через запятую), для сопоставления ролей
headers = X-WEBAUTH-GROUPS:X-Webauth-Groups
ldap_sync_ttl = 60
```

```nginx
# nginx: прокси аутентифицирует пользователя и ПЕРЕЗАПИСЫВАЕТ заголовок
location / {
    auth_request /auth;                       # внешняя проверка у прокси/IdP
    proxy_set_header X-WEBAUTH-USER $authenticated_user;
    proxy_set_header X-WEBAUTH-GROUPS $authenticated_groups;
    # Защита: запретить клиенту протащить поддельный заголовок
    proxy_hide_header X-WEBAUTH-USER;
    proxy_pass http://127.0.0.1:3000;
}
```

**Параметры:**
- `header_name` — имя заголовка, из которого берётся логин (чувствительно к регистру в `headers`).
- `auto_sign_up` — создавать пользователя в БД при первом входе; иначе должен быть заведён заранее.
- `headers` — маппинг `имя_заголовка:внутреннее_имя`; группы используются в `role_attribute_path`.

**Валидация:** войдите через прокси → Grafana создаёт/обновляет пользователя по `X-WEBAUTH-USER` и назначает роль по группам; проверьте `GET /api/user` от сессии (возвращает ожидаемый `login` и `role`). Если пользователь не создаётся — проверьте, что прокси действительно проставляет заголовок (в логах Grafana: `auth.proxy: ...`).

### 10. Тонкие права на источник данных и папку/дашборд

Ограничение видимости конкретных источников данных и назначение прав на папку через API (аналогично настраивается и в UI).

```bash
# 10.1 Включить тонкие права на источник данных (по uid)
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"enabled":true}' \
  http://grafana.example.com/api/datasources/uid/<DS_UID>/enable-permissions
# → {"message":"Data source permissions enabled"}  (после этого источник видят только назначенные)

# 10.2 Назначить команде право на источник (permission: 1=View, 2=Edit, 4=Admin)
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"teamId":3,"permission":1}' \
  http://grafana.example.com/api/datasources/uid/<DS_UID>/permissions
# → {"message":"Data source permission added"}

# 10.3 Назначить команде право на папку (наследуется вложенными дашбордами/папками)
curl -s -X POST -H "Authorization: Bearer <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"role":"Viewer"}' \
  http://grafana.example.com/api/folders/<FOLDER_UID>/teams/3
# → права команды 3 на папку заданы
```

**Валидация:** пользователь вне назначенной команды при запросе источника получает `403`/`404` (источник «невидим»), пользователь команды — успешный запрос. Дашборд в папке виден только тем, у кого есть право View на папку. Перечисление прав: `GET /api/datasources/uid/<DS_UID>/permissions` и `GET /api/folders/<FOLDER_UID>/permissions`. Включение прав на дашборд напрямую — через `POST /api/dashboards/<uid>/permissions` (аналогичная модель `permission`).

### 11. Квоты организации (Quotas)

Лимиты на число пользователей, дашбордов, источников и сессий — защита от «зоопарка» при самообслуживании команд.

```ini
# grafana.ini
[quota]
enabled = true

# Лимиты по умолчанию для каждой организации
org_user = 50            # участников в организации
org_dashboard = 200      # дашбордов
org_data_source = 20     # источников данных
org_api_key = 10         # устаревшие API keys (SA не лимитируются этой квотой)
org_alert_rule = 100     # правил алертинга

# Глобальные серверные лимиты
global_user = 500
global_session = 100     # одновременные сессии
```

Изменение квот конкретной организации через API:

```bash
# Посмотреть действующие квоты org=2
curl -s -H "Authorization: Bearer <ADMIN_TOKEN>" \
  http://grafana.example.com/api/orgs/2/quotas | jq .
# → [{"target":"org_user","limit":50}, ...]

# Поднять лимит дашбордов для этой организации
curl -s -X PUT -H "Authorization: Bearer <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" -d '{"limit":400}' \
  http://grafana.example.com/api/orgs/2/quotas/org_dashboard
# → {"message":"Quota updated","target":"org_dashboard"}
```

**Валидация:** попытка создать (N+1)-й дашборд под лимитом возвращает ошибку с сообщением о quota exceeded; `GET /api/org/quotas` от Org Admin отражает актуальные лимиты. Квоты проверяются при создании ресурса, а не задним числом: существующие ресурсы сверх нового лимита не удаляются автоматически.

## Дополнительная информация

### Рекомендации по безопасности

- **Отказ от API-ключей:** В версиях 12+ API-ключи считаются Legacy. Всегда используйте Service Accounts для новой автоматизации.
- **Двухфакторная аутентификация (2FA):** Grafana не имеет встроенной 2FA для локальных пользователей; реализуйте её на уровне внешнего провайдера (Keycloak, Google, GitHub) через OIDC/SAML.
- **Синхронизация ролей (Role Mapping):** Настраивайте автоматическое назначение ролей (Admin/Editor) на основе групп в OAuth/LDAP, чтобы избежать ручного управления правами.
- **Защита `secret_key`:** Убедитесь, что `secret_key` в `grafana.ini` является сложной строкой и одинаков для всех узлов в HA-кластере. Он используется для шифрования секретов в БД.

### Рекомендации по эксплуатации

- **Наименьшие привилегии:** выдавайте минимальную роль; для программного доступа предпочитайте кастомные RBAC-роли с только необходимыми экшенами (см. сценарий 5), а не широкие `Admin`/`Editor`.
- **Короткое время жизни токенов:** задавайте `secondsToLive`/`expires`; регулярно ротируйте токены сервисных аккаунтов, отзывая скомпрометированные по одному.
- **Централизация входа:** при наличии SSO отключайте локальную форму для пользователей (`[auth] disable_login_form = true`, `oauth_auto_login = true`), оставляя резервного Grafana Admin для аварийного доступа.
- **Team Sync:** используйте синхронизацию команд из LDAP/OAuth/SAML, чтобы не назначать права вручную при изменении состава групп.
- **Проверка email:** для OAuth включайте `require_verified_email = true`, чтобы исключить вход по неподтверждённым аккаунтам.
- **Аудит и бэкап:** периодически перечисляйте сервисные аккаунты и токены (`GET /api/serviceaccounts`); БД Grafana (SQLite `grafana.db` или `pg_dump` для Postgres) содержит пользователей и токены — включайте её в бэкап.

### Типичные ошибки и их решение

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `redirect_uri_mismatch` при входе по OAuth | Callback в приложении провайдера ≠ `<root_url>/login/github` (или другой суффикс) | Укажите в OAuth App корректный Authorization callback URL, совпадающий с `root_url` Grafana |
| Пользователь входит, но всегда получает `Viewer` | `role_attribute_path` пуст/некорректен, нет scope `read:org`, либо не в `allowed_organizations` | Проверьте scopes, выражение JMESPath и членство; отладьте через `GET /api/user` |
| LDAP: `invalid credentials` при bind | Неверный `bind_dn`/`bind_password` или пароль задан не как переменная | Проверьте `ldapsearch -D ... -W` вне Grafana; используйте `GF_AUTH_LDAP_BIND_PASSWORD` |
| LDAP: неверная роль после входа | `member_of` указан неверно (в AD — `memberOf`), `group_dn` не совпадает | Сверьте атрибуты через `ldapsearch`, скорректируйте `group_mappings` |
| SA-токен возвращает `401` | Токен истёк/отозван или создан в другой организации | Создайте новый токен в нужной org; для Grafana Admin используйте `X-Grafana-Org-Id` |
| Разрывы сессий / не расшифровываются секреты в HA | Разный `secret_key` на узлах | Задайте идентичный `GF_SECURITY_SECRET_KEY` на всех узлах, перезапустите |
| Анонимный доступ всё равно требует логин | `[auth.anonymous] enabled = false` или неверный `org_name`/`org_role` | Установите `enabled = true` и корректные `org_name`/`org_role` |
| WIF: `token exchange failed` | Несовпадение audience/client_id или SA в кластере не аннотирован | Сверьте пул Workload Identity в GCP и аннотацию ServiceAccount |
| API-ключ отклоняется (`401`) | API-ключи Legacy/отключены в v12+ | Перейдите на сервисные аккаунты (сценарий 7) |
| `X-Grafana-Org-Id` игнорируется | Заголовок работает только для сессии Grafana Admin; SA-токены привязаны к своей org | Создайте токен в целевой организации |
| Блокировка после нескольких неудачных входов | Brute-force protection в `[security]` | Подождите снятия блокировки или скорректируйте лимиты |
| Auth proxy: любой заходит под чужим именем | Прокси не фильтрует входящий `X-WEBAUTH-USER` от клиента | На прокси переопределяйте/скрывайте заголовок (`proxy_set_header X-WEBAUTH-USER ""` до внешней проверки), доверяйте только после auth |
| После включения прав на источник он «пропал» | Тонкие права меняют поведение на «по умолчанию запрещено» | Назначьте нужные команды/пользователей/SA через `.../permissions` |
| `403` на дашборд вне своей папки | Нет права View на папку (или наследование отключено) | Назначьте право на папку/дашборд явно; проверьте `GET .../permissions` |

### Ограничения и особые случаи

- **Multi-org и токены:** токены сервисных аккаунтов жёстко привязаны к организации создания. Для доступа к другой организации создавайте отдельный токен в ней либо используйте сессию Grafana Admin с `X-Grafana-Org-Id`.
- **Встроенный admin:** учётная запись `admin` (логин `admin`, пароль `admin` по умолчанию) — серверный администратор, глобальна. Смените пароль через `GF_SECURITY_ADMIN_PASSWORD` или `grafana cli admin reset-admin-password`.
- **RBAC по редакциям:** Fine-grained RBAC доступен в OSS с v11 (создание и назначение через API); расширенное UI-управление и Team Sync для RBAC — возможности Enterprise.
- **API-ключи:** продолжают работать, но помечены Legacy с v12; для новых интеграций обязателен переход на сервисные аккаунты.
- **Бессрочные токены:** если `expires`/`secondsToLive` не заданы, токен не истекает — избегайте этого в продакшене.
- **`disable_login_form`** отключает только локальную форму входа, но не анонимный доступ и не SSO.
- **Локальные пароли:** для пользователей внешних провайдеров локальный пароль не используется; сброс пароля применим только к локальным учётным записям.
- **Auth proxy:** Grafana безусловно доверяет заголовку `X-WEBAUTH-USER`; без фильтрации на прокси возможна подделка личности. Auth proxy не заменяет шифрование (используйте TLS на прокси) и не даёт второй фактор — 2FA реализуйте на стороне прокси/IdP.
- **Тонкие права на ресурсы:** включение прав на источник данных переключает его в режим «по умолчанию запрещено» — не забудьте назначить хотя бы одного субъекта, иначе источник станет недоступен всем, включая Editor/Admin организации.

### Очистка и откат изменений

- **Отключить метод аутентификации:** установите `enabled = false` в соответствующей секции `[auth.*]` и перезапустите Grafana.
- **Отозвать токен сервисного аккаунта:** `DELETE /api/serviceaccounts/{id}/tokens/{tokenId}` (см. 4.5) или удалите аккаунт целиком.
- **Удалить пользователя из организации / организацию:** `DELETE /api/orgs/{orgId}/users/{userId}` и `DELETE /api/orgs/{orgId}` (требуется Grafana Admin).
- **Вернуть анонимный доступ:** `enabled = false` в `[auth.anonymous]`.
- **Выйти из режима «только SSO»:** `disable_login_form = false` (и при необходимости `oauth_auto_login = false`).

### Актуальность и статус

- Актуальная линейка: **13.x** (текущая), **12.x** (LTS), **11.x** (EOL с июня 2026).
- **RBAC в OSS** — доступен с v11; **API Keys — Legacy** с v12; **Workload Identity Federation** — с v13.
- Рекомендуемый подход 2026 года: внешняя аутентификация (OIDC/SAML/LDAP) + сервисные аккаунты с кастомными RBAC-ролями для автоматизации; локальные пароли — только для резервного Grafana Admin.

### Полезные ссылки

- [Официальная документация: Authentication](https://grafana.com/docs/grafana/latest/administration/authentication/)
- [Настройка Service Accounts](https://grafana.com/docs/grafana/latest/administration/service-accounts/)
- [Grafana RBAC Actions List](https://grafana.com/docs/grafana/latest/administration/access-control/permissions/)

### Связанные темы

- [Fine-grained RBAC — кастомные роли](./grafana_rbac_fine_grained.md) — создание и назначение кастомных ролей через API/Terraform
- [Enterprise SSO — SAML/JWT/LDAP Team Sync](./grafana_sso_saml_jwt.md) — корпоративные провайдеры аутентификации
- [Grafana API Reference](https://grafana.com/docs/grafana/latest/developers/http_api/)
- [Terraform Provider: Access Control](https://registry.terraform.io/providers/grafana/grafana/latest/docs/resources/role)
