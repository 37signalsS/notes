# Harbor: Аутентификация и управление доступом

**Актуально для:** Harbor 2.15.x

## Определения

* **Auth Mode**: Режим аутентификации Harbor — источник учётных записей. Поддерживаются три режима: Database (локальная БД), LDAP/AD и OIDC. **SAML не поддерживается** — это частый вопрос на собеседованиях; для SAML-Only окружений Harbor не подходит без дополнительного IdP-брокера.
* **LDAP/AD (Lightweight Directory Access Protocol / Active Directory)**: Протокол доступа к корпоративному каталогу. В этом режиме пользователи не создаются в Harbor — они аутентифицируются напрямую против каталога.
* **OIDC (OpenID Connect)**: Протокол SSO поверх OAuth 2.0. Пользователи входят в Harbor через провайдера (Keycloak, Okta, Dex, Google Identity, Ping Identity, Auth0 — официально верифицированные адаптеры).
* **memberof**: Фича LDAP/AD-сервера, автоматически обновляющая атрибут `memberOf` пользователя при изменении членства в группе. Обязательна для управления доступом через LDAP-группы.
* **CLI Secret**: Токен для CLI-аутентификации вместо пароля — обязателен для OIDC/LDAP-пользователей в Docker/Helm CLI (см. [работу с Harbor](./usage.md#сценарий-2-использование-робот-аккаунтов-в-cicd)).
* **System Robot Account**: Робот-аккаунт системного уровня (создаётся администратором), в отличие от проектных робот-аккаунтов.
* **imagePullSecret**: Kubernetes-секрет типа `docker-registry` с учётными данными реестра, используемый kubelet при загрузке образов.

## Основные концепции

### Режимы аутентификации

| Режим | Где хранятся пользователи | Применение |
| :--- | :--- | :--- |
| **Database** | Локальная PostgreSQL Harbor | Малые инсталляции, тестовые стенды, air-gapped без каталога |
| **LDAP/AD** | Корпоративный каталог | Enterprise on-prem: единый источник пользователей и групп |
| **OIDC** | Провайдер идентификации | SSO, гибридные и распределённые окружения |

**Ключевые ограничения (важно для продакшена):**

1. **Смена auth mode** с Database на LDAP или OIDC возможна только при отсутствии локальных пользователей в БД (кроме `admin`). Если есть хотя бы один локальный пользователь — переключение заблокировано.
2. В режимах LDAP/OIDC **нельзя** создавать, удалять пользователей, менять пароли и включать self-registration — пользователи управляются внешним источником.
3. Docker/Helm CLI не обрабатывают OIDC-редирект: для них используется **CLI Secret** из профиля пользователя. Если провайдер не выдаёт refresh token, секрет инвалидируется после истечения ID token.

### Как работает аутентификация на уровне протокола

Docker/containerd при обращении к Harbor используют двухфазный обмен Registry API v2: пробный запрос `GET /v2/` → `401` с `WWW-Authenticate: Bearer realm=".../service/token"` → запрос JWT-токена с `scope=repository:<project>/<repo>:pull` → повторный запрос с `Authorization: Bearer <token>`. Harbor (core) выступает token service и выдаёт JWT с правами из RBAC-роли пользователя. Полная диагностика этого flow (включая декод JWT и разбор `DENIED`) — в [Registry HTTP API v2, сценарий 6](../registry_api_v2.md#сценарий-6-отладка-авторизации-401403).

## Практические сценарии

### Сценарий 1: Настройка LDAP/AD

Конфигурация выполняется в интерфейсе (значения хранятся в БД Harbor, не в `harbor.yml`).

1. Войдите как системный администратор: **Administration → Configuration → Authentication**.
2. В **Auth Mode** выберите **LDAP**.
3. Заполните параметры:

| Параметр | Пример | Назначение |
| :--- | :--- | :--- |
| **LDAP URL** | `ldaps://ldap.corp.local` | Адрес каталога. Для AD обычно `ldaps://` (порт 636) |
| **LDAP Search DN** | `cn=harbor-bind,dc=corp,dc=local` | Учётка для bind-поиска пользователей |
| **LDAP Search Password** | `<password>` | Пароль bind-учётки |
| **LDAP Base DN** | `dc=corp,dc=local` | База поиска (включая поддерево) |
| **LDAP Scope** | `Subtree` / `Base` / `OneLevel` | Глубина поиска |
| **LDAP UID** | `sAMAccountName` (AD) / `uid` (OpenLDAP) | Атрибут-логин пользователя |
| **LDAP Filter** | `(memberOf=cn=devs,...)` | Дополнительный фильтр пользователей |
| **LDAP Group Admin DN** | `cn=harbor-admins,dc=corp,dc=local` | Все пользователи этой группы — системные админы Harbor |
| **LDAP Group Membership** | `memberOf` | Атрибут членства в группе (по умолчанию `memberof`) |

4. Снимите **LDAP Verify Cert**, если каталог использует самоподписанный сертификат (только для тестов).
5. Нажмите **Test LDAP Server** — проверка связности и bind.
6. **Save**.

> Для управления доступом через LDAP-группы на сервере каталога должна быть включена фича **memberof** — иначе атрибут членства не обновляется при изменении групп.

### Сценарий 2: Настройка OIDC

1. **Administration → Configuration → Authentication → Auth Mode: OIDC**.
2. Параметры:

| Параметр | Пример (Keycloak) | Назначение |
| :--- | :--- | :--- |
| **Primary Auth Mode** | `true` | OIDC как основной режим; при `false` — вход через БД доступен по явному URL `/account/sign-in` |
| **OIDC Provider Name** | `Keycloak` | Отображаемое имя провайдера |
| **OIDC Provider Endpoint** | `https://keycloak.corp.local/realms/harbor` | Endpoint провайдера (должен отдавать `.well-known/openid-configuration`) |
| **OIDC Client ID** | `harbor` | Client ID, с которым Harbor зарегистрирован у провайдера |
| **OIDC Client Secret** | `<secret>` | Секрет клиента |
| **OIDC Scope** | `openid,profile,email,offline_access` | Обязательно `openid`; `offline_access` — для refresh token |
| **Group Claim Name** | `groups` | Claim токена со списком групп |
| **OIDC Group Filter** | `.*harbor.*` | Regex-фильтр групп из claim (не ограничивает вход) |
| **OIDC Auto Onboard** | `true` | Автоматическое создание учётной записи при первом входе |
| **OIDC User Claim** | `preferred_username` | Claim для имени пользователя |
| **OIDC Admin Group** | `harbor-admins` | Группа, получающая системный админ-доступ |

3. **Test OIDC Server** → **Save**.

Пример регистрации Harbor как клиента в Keycloak:

```bash
# Создание клиента через kcadm (на хосте Keycloak)
kcadm create clients -r harbor \
  -s clientId=harbor \
  -s enabled=true \
  -s protocol=openid-connect \
  -s 'redirectUris=["https://harbor.corp.local/callback"]' \
  -s 'scope=openid profile email offline_access' \
  -s serviceAccountsEnabled=true
# → Created client harbor
```

### Сценарий 3: Управление пользователями и членством в проектах

В режиме Database (или для администрирования в любом режиме):

```bash
# Создание локального пользователя (Database auth mode)
curl -u "admin:$HARBOR_ADMIN_PASS" -X POST "https://harbor.corp.local/api/v2.0/users" \
  -H "Content-Type: application/json" \
  -d '{"username":"dev1","email":"dev1@corp.local","password":"<надёжный_пароль>","realname":"Dev One"}'
# → 201 Created

# Добавление пользователя в проект с ролью Developer (1=Guest, 2=Developer, 3=Project Admin)
curl -u "admin:$HARBOR_ADMIN_PASS" -X POST \
  "https://harbor.corp.local/api/v2.0/projects/myproject/members" \
  -H "Content-Type: application/json" \
  -d '{"member_user":{"username":"dev1"},"role_id":2}'
# → 201 Created

# Список членов проекта
curl -u "admin:$HARBOR_ADMIN_PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject/members" | jq '.[] | {username: .member_user.username, role_id}'
```

Роли в проекте: **Guest** (pull в приватном проекте), **Developer** (push), **Project Admin** (управление проектом). Системные роли: **System Admin** и **Security Officer** (управление политиками безопасности). Ролевая модель применяется независимо от auth mode — робот-аккаунты и LDAP/OIDC-пользователи получают права через маппинг групп.

### Self-registration

Self-registration позволяет пользователям создавать учётные записи самостоятельно в Database-режиме. По умолчанию **выключена**. Включить: **Administration → Configuration → Security → Self-registration** (или API: `PUT /api/v2.0/configs` с `self_registration: true`). В LDAP/OIDC-режимах переключатель недоступен — пользователи создаются только через внешний каталог или OIDC `auto_onboard`.

## Best Practices

### LDAP/AD — безопасность и надёжность

* **Принцип минимальных привилегий для bind-учётки**: учётная запись `LDAP Search DN` должна иметь права только на чтение атрибутов пользователей и групп в указанном `Base DN`. Никаких прав на запись или модификацию схемы.
* **LDAPS вместо LDAP**: всегда используйте `ldaps://` (порт 636) с проверкой сертификата. Для самоподписанных сертификатов импортируйте CA в trust store хоста Harbor (`/usr/local/share/ca-certificates/` + `update-ca-certificates`), а не отключайте `Verify Cert` в production.
* **Сетевая изоляция**: хост Harbor должен иметь доступ только к порту 636 LDAP-сервера; никаких других исходящих правил не требуется.
* **Группы**: включайте `memberof` overlay на LDAP-сервере до подключения Harbor — иначе групповые права не обновятся динамически.

### OIDC — безопасность и совместимость

* **PKCE (Proof Key for Code Exchange)**: если провайдер поддерживает PKCE — включите его в конфигурации клиента. Это защищает от interception-атак на код авторизации.
* **Scope минимизации**: запрашивайте только необходимые scope (`openid`, `profile`, `email`, `offline_access`). Дополнительные scope увеличивают токен и поверхность атаки.
* **Group Claim**: проверяйте, что провайдер действительно включает группы в `id_token` или `userinfo` ответ. Некоторые провайдеры требуют явного указания группы в client scope.
* **Redirect URI**: строго зафиксируйте `https://<harbor_host>/callback` в клиенте провайдера. Дополнительные URI упростят атаку перехвата.

### Self-registration

* **Выключена по умолчанию** — включайте только в Database-режиме и только для тестовых контуров.
* **В production** с LDAP/OIDC self-registration не нужна и не поддерживается.
* **Проверка**: метрика `harbor_system_info{self_registration="true"}` должна отсутствовать в production.

### Робот-аккаунты

* **Срок действия**: всегда задавайте `Expiration` для CI-роботов (например, 30–90 дней). Используйте `Never Expired` только для системных аккаунтов с ручной ротацией.
* **Минимальные права**: создавайте отдельные робот-аккаунты для pipeline и staging, с ровно теми правами, которые нужны (Pull Only, Push Only).
* **Ротация секретов**: храните секреты в Vault/Sealed Secrets/AWS Secrets Manager, а не в переменных CI. Ротация: `Refresh Secret` в Harbor → обновление соответствующего Kubernetes Secret (если используется `imagePullSecret`) → перезапуск deployment.
* **Номенклатура**: используйте осмысленные имена с префиксом окружения: `robot$production+deploy-bot`, `robot$staging+scan-bot`.

### CLI Secret

* **Хранение**: не храните CLI Secret в скриптах или репозиториях. Используйте `harbor login --password-stdin` или переменные окружения с ограниченным доступом.
* **Жизненный цикл**: в OIDC без refresh token секрет инвалидируется с ID token. Настройте провайдера на выдачу refresh token (`offline_access` scope) или планируйте периодический re-login.
* **Ротация**: для смены CLI Secret пользователю достаточно перелогиниться в Portal — старый секрет автоматически отменяется.

### API-доступ

* **Basic Auth**: используйте робот-аккаунты вместо личных учёток для автоматизации. Полный справочник эндпоинтов и примеры — в **[Harbor REST API](./api.md)**.
* **HTTPS обязательно**: Basic Auth передаёт учётные данные в base64 (не шифр). Без TLS пароль виден в трафике.

### Сценарий 4: imagePullSecrets из робот-аккаунтов в Kubernetes

Kubelet загружает образы от имени хоста — для приватных проектов Harbor требуется `imagePullSecret`.

```bash
# 1. Создание секрета из робот-аккаунта (см. usage.md, сценарий 2)
kubectl create secret docker-registry harbor-pull \
  --docker-server=harbor.corp.local \
  --docker-username='robot$production+ci-bot' \
  --docker-password="$ROBOT_SECRET" \
  -n production
# → secret/harbor-pull created

# 2. Автоматическая инъекция во все Pod namespace (лучше, чем imagePullSecrets в каждом манифесте)
kubectl patch serviceaccount default -n production \
  -p '{"imagePullSecrets": [{"name": "harbor-pull"}]}'
# → serviceaccount/default patched

# 3. Ротация: refresh секрета робот-аккаунта → обновление K8s-секрета
#    (старый секрет немедленно отменяется при refresh — окно пересечения минимально)
kubectl create secret docker-registry harbor-pull \
  --docker-server=harbor.corp.local \
  --docker-username='robot$production+ci-bot' \
  --docker-password="$NEW_ROBOT_SECRET" \
  -n production --dry-run=client -o yaml | kubectl apply -f -
# → secret/harbor-pull configured
```

> Ротация секрета требует перезапуска подов: kubelet кэширует учётные данные до пересоздания Pod. Планируйте ротацию в окна редеплоя.

## Валидация

```bash
# Проверка текущего auth mode
curl -sk -u "admin:$HARBOR_ADMIN_PASS" \
  "https://harbor.corp.local/api/v2.0/systeminfo" | jq '{auth_mode: .auth_mode, harbor_version}'
# → {"auth_mode": "ldap_auth", "harbor_version": "2.15.2"}

# Тест LDAP-подключения через API (system admin)
curl -sk -u "admin:$HARBOR_ADMIN_PASS" -X POST \
  "https://harbor.corp.local/api/v2.0/ldap/ping" \
  -H "Content-Type: application/json" \
  -d '{"ldap_url":"ldaps://ldap.corp.local","ldap_base_dn":"dc=corp,dc=local"}'
# → 200 — каталог доступен

# Тест OIDC-endpoint через API (system admin)
curl -sk -u "admin:$HARBOR_ADMIN_PASS" -X POST \
  "https://harbor.corp.local/api/v2.0/system/oidc/ping" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://keycloak.corp.local/realms/harbor","verify_cert":true}'
# → 200 — endpoint доступен

# Проверка входа пользователя LDAP (UI: вход под доменной учёткой)
# Проверка CLI Secret для OIDC-пользователя:
docker login harbor.corp.local -u 'oidc-user' -p '<CLI_SECRET>'
# → Login Succeeded

# Проверка pull из приватного проекта с imagePullSecret
kubectl run test-pull --image=harbor.corp.local/production/my-app:v1.2.0 --restart=Never -n production
# → Pod Running (ImagePullBackOff = проблема с секретом или правами)
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `LDAP connection failed` | Неверный URL/порт, сеть, сертификат | Проверьте `ldaps://` URL, доступность порта 636, снимите Verify Cert для теста |
| `Invalid credentials` при входе | Неверный Search DN/Password или фильтр | Проверьте bind-учётку через `ldapsearch -x -H ldaps://... -D "<search_dn>" -W`; проверьте LDAP Filter и UID-атрибут |
| Пользователь входит, но без прав | Группы не маппятся | Включите `memberof` на LDAP-сервере; проверьте Group Membership-атрибут и Group Admin DN |
| Кнопка **Test LDAP Server** не проходит | Самоподписанный сертификат каталога | Импортируйте CA в trust store хоста Harbor или снимите Verify Cert |
| OIDC: циклический редирект | Неверный redirect URI у провайдера | Зарегистрируйте `https://<harbor_host>/callback` в клиенте провайдера |
| OIDC: нет групп в Harbor | Claim не настроен | Проверьте Group Claim Name и что scope включает groups; проверьте OIDC Group Filter |
| `docker login` не работает для OIDC-пользователя | CLI использует пароль, а не CLI Secret | Возьмите CLI Secret из профиля пользователя в Harbor Portal |
| Смена auth mode заблокирована | Есть локальные пользователи | Удалите локальных пользователей (кроме admin) или мигрируйте их в каталог |

## Граничные случаи

* **SAML не поддерживается** — только Database, LDAP/AD, OIDC. Для SAML-требований используйте IdP-брокер (например, Dex, который сам поддерживает SAML и предъявляется Harbor как OIDC-провайдер).
* **Auth mode хранится в БД**, не в `harbor.yml` — изменение через UI/API, не через конфиг-файл.
* **LDAP без memberof**: вход работает, но групповой маппинг не обновляется при изменении групп — права «застывают».
* **OIDC без refresh token**: CLI Secret живёт ровно столько, сколько ID token — пользователю нужно перелогиниваться через провайдера для нового секрета.
* **Robot-аккаунты** работают при любом auth mode — они не зависят от источника пользователей (см. [работу с Harbor](./usage.md#сценарий-2-использование-робот-аккаунтов-в-cicd)).
* **OIDC: группы не обновляются автоматически** при изменении членства в IdP — пользователь должен выйти и зайти снова, чтобы Harbor подтянул новые группы из claim.
* **LDAP paging**: при каталогах >1000 пользователей включите пейджинг в настройках Harbor (`page_size`), иначе поиск может вернуть неполный результат.
* **Миграция auth mode**: переключение с Database на LDAP/OIDC возможно только после удаления всех локальных пользователей (кроме `admin`). Лучшая практика — предварительно создать пользователей в LDAP/OIDC, затем удалить локальных и переключить режим.
* **Robot-аккаунт legacy-формат**: `robot$<name>` без имени проекта — deprecated, работает только для обратной совместимости (Harbor < 2.2, JWT). Для новых аккаунтов используйте `robot$<project>+<name>`.
* **API-аутентификация**: Basic Auth с личным паролем пользователя работает, но для автоматизации используйте робот-аккаунты (они не привязаны к личности и не блокируются при смене пароля). Справочник API — в **[Harbor REST API](./api.md)**.
* **LDAP user enumeration**: если `LDAP Filter` возвращает слишком много пользователей (тысячи), поиск при входе может замедлиться. Ограничьте `Base DN` и используйте фильтр по бизнес-правилам.

## Дополнительная информация

* **Токенный flow Registry v2** (401 → bearer token → retry, разбор JWT) — [Registry HTTP API v2, сценарий 6](../registry_api_v2.md#сценарий-6-отладка-авторизации-401403).
* **OIDC Federation GitLab → Harbor** (беспарольная интеграция CI) — [Интеграция GitLab с Harbor](../../../Kubernetes/Installation/k3s_dev_environment/gitlab_harbor_integration.md).
* **Workload Identity через Dex/Keycloak + Harbor** (без imagePullSecrets) — [CI/CD интеграция](../../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/ci_cd_integration.md).
* **Подписи образов и Cosign** — [Проверка подписей образов](../../Docker_security/image_signature_and_verification.md).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — архитектура и RBAC-модель.
* **[Работа с Harbor](./usage.md)** — робот-аккаунты, CLI Secret.
* **[Установка Harbor](./installation.md)** — развёртывание.
* **[Harbor REST API](./api.md)** — автоматизация пользователей и членов проектов.
