# ArgoCD: Настройка SSO через GitLab

**Актуально для:** Argo CD v3.4+ (покрывает v3.4.x, v3.5.x, v3.6.x; отличаются `oidc.config` нативная интеграция, JWT `users.session.duration` дефолты, `groups` claim поведение). Dex остаётся обязательным посредником для GitLab-коннектора — нативный OIDC в v3.x не поддерживает GitLab-специфичные поля `groups` и вложенные группы.

Настройка Single Sign-On (SSO) в Argo CD через GitLab позволяет централизованно управлять доступом пользователей, используя существующие учетные записи и группы GitLab. Для реализации используется встроенный сервер **Dex** — федеративный OpenID Connect (OIDC) провайдер, выступающий посредником между Argo CD и внешними Identity Providers (IdP).

## Предварительные требования

Для успешной настройки SSO через GitLab необходимы следующие компоненты:

| № | Требование | Детали | Команда проверки | Ожидаемый результат |
|---|------------|--------|------------------|---------------------|
| 1 | **Kubernetes кластер** | v1.28+ (рекомендуется для полной поддержки OIDC и SSA) | `kubectl version --short` | `Server Version: v1.28.x` или выше |
| 2 | **Argo CD установлен** | v3.4+ (покрывает v3.4.x, v3.5.x, v3.6.x) | `kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-server` | Все поды `argocd-server`, `argocd-dex-server`, `argocd-repo-server`, `argocd-application-controller` в статусе `Running` |
| 3 | **Dex сервер работает** | Под `argocd-dex-server` в статусе `Running` | `kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-dex-server` | `argocd-dex-server-xxxxx   1/1     Running   0          5d` |
| 4 | **GitLab доступен** | SaaS (gitlab.com) или Self-managed 15.0+ | `curl -I https://gitlab.example.com` | `HTTP/2 200` (или `302` для редиректа на логин) |
| 5 | **HTTPS настроен для Argo CD** | Внешний URL с валидным TLS-сертификатом | `curl -I https://argocd.example.com` | `HTTP/2 200`; сертификат валиден (`openssl s_client -connect argocd.example.com:443 -servername argocd.example.com < /dev/null 2>&1 | grep -i verify`) |
| 6 | **Административный доступ к кластеру** | Права на редактирование ConfigMap/Secret в namespace `argocd` | `kubectl auth can-i patch configmap -n argocd` | `yes` |
| 7 | **CLI `argocd` установлен и настроен** | Версия, совместимая с сервером | `argocd version` | `argocd: v3.4.x`<br>`argocd-server: v3.4.x` |
| 8 | **GitLab Application зарегистрировано** | Application ID и Secret получены в GitLab | (проверяется на Шаге 1) | Application ID и Secret доступны |
| 9 | **DNS/Ingress настроен** | Callback URL `https://<argocd-url>/api/dex/callback` разрешается и доступен из интернета | `curl -I https://argocd.example.com/api/dex/callback` | `HTTP/2 200` или `302` (redirect к GitLab) |

> **Важно:** Для Self-managed GitLab с самоподписанным CA — подготовьте base64-кодированный корневой сертификат (`cat ca.crt | base64 -w0`) для параметра `rootCAData` в `dex.config`.

## Определения

| Термин | Определение |
|--------|-------------|
| **SSO (Single Sign-On)** | Технология единого входа, позволяющая пользователю аутентифицироваться один раз и получать доступ к множеству приложений без повторной аутентификации. В Argo CD реализуется через OIDC-посредник (Dex или нативный `oidc.config`). |
| **Dex** | Федеративный OpenID Connect (OIDC) провайдер, выступающий посредником между Argo CD и внешними Identity Providers (IdP). Dex поддерживает коннекторы: GitLab, GitHub, Google, LDAP, SAML, OIDC. В Argo CD развёртывается как под `argocd-dex-server`. Обязателен для GitLab-коннектора. |
| **OIDC (OpenID Connect)** | Протокол идентификации на базе OAuth 2.0, расширяющий его информацией о пользователе через Claims. Использует `Authorization Code Flow` с PKCE для веб-приложений. |
| **RBAC (Role-Based Access Control)** | Механизм разграничения прав доступа на основе ролей, сопоставленных с группами пользователей из OIDC-токена. Настраивается через `argocd-rbac-cm`. |
| **Claims** | Набор утверждений (атрибутов) о пользователе, возвращаемый IdP в OIDC ID Token: `sub` (subject), `email`, `groups`, `preferred_username`, `profile`. В GitLab `groups` содержит полные пути групп (`path/to/group`). |
| **ID Token** | JWT-токен, содержащий Claims пользователя, подписанный IdP. Используется Dex для извлечения групп и email. |
| **Authorization Code Flow** | OIDC-поток: 1) редирект к IdP → 2) вход пользователя → 3) callback с `code` → 4) обмен `code` на `access_token` + `id_token` → 5) извлечение Claims. |
| **groupMemberAttributes** | Параметр Dex-коннектора GitLab. При `true` — Dex запрашивает полную иерархию групп (включая вложенные) при каждом входе через GitLab API. При `false` (по умолчанию) — только прямые группы, кэшируются после первого входа. |
| **argocd-cm** | ConfigMap в namespace `argocd` для глобальной конфигурации Argo CD: `url`, `dex.config`, `oidc.config`, `users.session.duration`, `admin.enabled`. |
| **argocd-rbac-cm** | ConfigMap в namespace `argocd` для RBAC-политик: `policy.csv`, `policy.default`, `scopes`. |
| **argocd-secret** | Secret в namespace `argocd` для хранения чувствительных данных: `gitlab.clientSecret`, `oidc.clientSecret`, `admin.password`, `server.secretkey`. |
| **Callback URL** | URL, на который IdP возвращает пользователя после аутентификации: `https://<argocd-url>/api/dex/callback`. Должен совпадать точно с тем, что зарегистрировано в GitLab Application. |
| **Scopes (OIDC)** | Области доступа, запрашиваемые у IdP. Для GitLab: `openid`, `profile`, `email`, `groups`, `read_api`. В `argocd-rbac-cm` параметр `scopes: "[groups]"` определяет, какой claim используется для групп. |
| **users.session.duration** | Параметр в `argocd-cm`, определяющий TTL JWT-сессии (по умолчанию 24h). Влияет на время жизни токена и кэш групп из OIDC. |

## Базовые концепции

### Архитектура взаимодействия

```
┌─────────────────────────────────────────────────────────────────────┐
│              Argo CD SSO через GitLab: Архитектура OIDC            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   Пользователь│───▶│ argocd-server│───▶│ argocd-dex   │          │
│  │   (Браузер)  │◀───│ (API/UI)     │◀───│ (OIDC-посредник)│        │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         │                   │                   │                   │
│         │                   │                   ▼                   │
│         │                   │         ┌──────────────┐             │
│         │                   │         │    GitLab     │             │
│         │                   │         │  (IdP/Issuer) │             │
│         │                   │         └──────────────┘             │
│         │                   │                   │                   │
│         │                   ▼                   ▼                   │
│         │         ┌──────────────┐    ┌──────────────┐             │
│         │         │ argocd-rbac  │    │ OIDC-токен   │             │
│         │         │ (Политики)   │    │ (Claims:     │             │
│         │         └──────────────┘    │  email,      │             │
│         │                             │  groups)     │             │
│         │                             └──────────────┘             │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────┐                                                   │
│  │ Доступ к UI  │                                                   │
│  │ и API ArgoCD │                                                   │
│  └──────────────┘                                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Пошаговый процесс OIDC Authorization Code Flow:**

1. **Запрос:** Пользователь инициирует вход в веб-интерфейсе Argo CD (через UI или CLI `argocd login --sso`).
2. **Редирект к Dex:** `argocd-server` перенаправляет запрос к `argocd-dex-server` (endpoint `/auth`).
3. **Редирект к IdP (GitLab):** Dex формирует authorize URL с параметрами `client_id`, `redirect_uri`, `scope`, `state`, `nonce` и перенаправляет браузер пользователя к GitLab (`/oauth/authorize`).
4. **Аутентификация в GitLab:** Пользователь вводит учетные данные (или использует существующую сессию GitLab).
5. **Авторизация (согласие):** GitLab запрашивает согласие пользователя на доступ к запрошенным scopes (`openid`, `profile`, `email`, `groups`, `read_api`).
6. **Callback к Dex:** После успешного входа GitLab возвращает authorization `code` на `redirect_uri` Dex (`/callback`).
7. **Обмен токена:** Dex обменивает `code` на `access_token` и `id_token` через Token Endpoint GitLab (`/oauth/token`).
8. **Валидация и извлечение Claims:** Dex валидирует подпись `id_token` (JWKS от GitLab), извлекает Claims: `sub`, `email`, `preferred_username`, `groups` (полные пути), `groups_direct`.
9. **Создание сессии:** Dex создает сессию (хранится в Redis или in-memory), устанавливает session cookie (`dex.session`), перенаправляет пользователя обратно в Argo CD.
10. **Авторизация в Argo CD:** `argocd-server` читает session cookie, получает Claims из Dex, применяет политики из `argocd-rbac-cm` (`policy.csv`, `g,` маппинг групп на роли), выдает JWT-токен пользователю (TTL = `users.session.duration`).

### Почему Dex обязателен для GitLab (v3.4+)

| Особенность | Нативный `oidc.config` (v3.0+) | Dex GitLab Connector |
|-------------|-------------------------------|---------------------|
| **Вложенные группы** | ❌ Не поддерживает | ✅ `groupMemberAttributes: true` |
| **Автообновление групп** | ❌ Только при первом логине | ✅ При каждом входе (с `groupMemberAttributes: true`) |
| **`groups` claim** | ❌ Не извлекается корректно | ✅ Полные пути `path/to/group` |
| **Централизованная конфигурация** | ❌ Разделена между `argocd-cm` и `argocd-rbac-cm` | ✅ Вся конфигурация в `argocd-cm` (`dex.config`) |
| **Мульти-провайдерность** | ✅ Поддерживается | ✅ Несколько коннекторов в одном `dex.config` |

**Вывод:** Для GitLab **всегда используйте Dex**. Нативный `oidc.config` подходит только для GitHub, Google, LDAP, Azure AD (SAML/OIDC), где структура групп проще.

### Claims в GitLab OIDC

GitLab возвращает следующие Claims в OIDC ID Token:

| Claim | Описание | Пример | Примечание |
|-------|----------|--------|------------|
| `sub` | Уникальный идентификатор пользователя (immutable) | `gitlab|12345678` | Формат: `gitlab\|<user_id>` |
| `email` | Email пользователя | `user@example.com` | Может быть скрыт в настройках профиля |
| `preferred_username` | Имя пользователя в GitLab | `john-doe` | Используется для отображения в UI |
| `groups` | **Все группы** (включая вложенные, если `groupMemberAttributes: true`) | `["infra/team", "shop/backend", "org/suborg/team"]` | **Полные пути**, case-sensitive |
| `groups_direct` | Только прямые группы (без вложенных) | `["infra/team"]` | Доступно всегда |
| `profile` | URL профиля в GitLab | `https://gitlab.com/john-doe` | — |

> **Критично для RBAC:** Группы в Claims передаются как **полные пути** (`path/to/group`), а не просто имена. В `policy.csv` маппинг должен использовать точное совпадение строки: `g, "infra/kubernetes-admins", role:admin`.

### Политики доступа: Синтаксис и логика

Argo CD использует собственный синтаксис политик в `argocd-rbac-cm` (Casper/Go RBAC):

**Структура политики:**
```
p, <роль>, <ресурс>, <действие>, <объект>, <решение>
g, <субъект>, <роль>
```

**Параметры политики (`p,`):**

| Поле | Описание | Примеры |
|------|----------|---------|
| **Роль** | Имя роли (префикс `role:`) | `role:admin`, `role:dev-shop`, `role:readonly` |
| **Ресурс** | Тип ресурса Argo CD | `applications`, `clusters`, `repositories`, `projects`, `certificates`, `accounts`, `gpgkeys`, `extensions` |
| **Действие** | Операция над ресурсом | `get`, `create`, `update`, `delete`, `sync`, `override`, `action/<custom>` |
| **Объект** | Паттерн имени ресурса (glob: `*`, `?`) | `*/*`, `shop/*`, `shop/frontend-*`, `prod/cluster-*` |
| **Решение** | Разрешение или запрет | `allow`, `deny` |

**Группировка / Маппинг групп (`g,`):**
```
g, "<-gitlab-group-path>", <роль>
```

**Пример полной конфигурации `argocd-rbac-cm`:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    # Полные права для группы infra/kubernetes-admins
    g, "infra/kubernetes-admins", role:admin
    
    # Кастомная роль для разработчиков проекта shop
    p, role:dev-shop, applications, get, shop/*, allow
    p, role:dev-shop, applications, sync, shop/*, allow
    p, role:dev-shop, applications, override, shop/*, allow
    
    # Маппинг вложенной группы GitLab на роль
    g, "shop-team/backend-devs", role:dev-shop
    
    # Явный запрет удаления для разработчиков
    p, role:dev-shop, applications, delete, shop/*, deny
    
    # Доступ к репозиториям для CI-бота
    g, "ci/cd-bots", role:ci-bot
    p, role:ci-bot, repositories, get, *, allow
    p, role:ci-bot, repositories, create, *, allow

  # Области для OIDC claims (только для OIDC/SSO пользователей)
  scopes: "[groups]"
```

**Приоритет правил:**
1. `deny` всегда имеет приоритет над `allow` (explicit deny wins).
2. Правила проверяются сверху вниз (first match wins для одного действия).
3. Если ни одно правило не совпало — действие запрещено (default: `policy.default: role:readonly`).

**Стандартные роли Argo CD:**

| Роль | Описание |
|------|----------|
| `role:readonly` | Только `get` для всех ресурсов |
| `role:admin` | Полный доступ ко всем ресурсам (`*/*, allow`) |
| `role:developer` | `get`, `sync`, `override` для applications (по умолчанию для новых пользователей до v3.0) |

## Практические сценарии

### Шаг 1: Регистрация приложения в GitLab

1. В GitLab перейдите в **Settings → Applications** (на уровне инстанса или конкретной группы).
2. Заполните параметры:

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Name** | `ArgoCD` | Отображаемое имя приложения |
| **Redirect URI** | `https://<argocd-url>/api/dex/callback` | URI для возврата после аутентификации |
| **Confidential** | `Yes` (включено) | Обязательно для OIDC |
| **Scopes** | `openid`, `profile`, `email`, `read_api` | Минимально необходимые области доступа |
| **_expire_token_after** | `3600` | Время жизни токена (рекомендуется 1 час) |

3. Сохраните **Application ID** и **Secret**.

**Примечание для Self-managed GitLab:**
- Убедитесь, что GitLab доступен по HTTPS с валидным сертификатом.
- Если используется внутренний CA — добавьте корневой сертификат в `argocd-cm` (см. Шаг 3).

### Шаг 2: Хранение секрета в Kubernetes

Для обеспечения безопасности `clientSecret` рекомендуется хранить в `argocd-secret`.

**Вариант А: Редактирование существующего секрета**
```bash
# Кодирование секрета в base64
echo -n "ваш_секрет_gitlab" | base64

# Добавление в argocd-secret
kubectl edit secret -n argocd argocd-secret
```
Добавьте поле `gitlab.clientSecret` в секцию `data`.

**Вариант Б: Декларативный манифест (External Secrets / SOPS)**
Если вы используете GitOps для секретов, определите поле в `stringData`:
```yaml
stringData:
  gitlab.clientSecret: "ваш_секрет_gitlab"
```

**Важно:**
- Никогда не храните секреты в `argocd-cm` — используйте `argocd-secret`.
- Для продакшена рекомендуется использовать External Secrets Operator или Sealed Secrets.

### Шаг 3: Настройка коннектора в ConfigMap

Отредактируйте `argocd-cm` для настройки связи с GitLab.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  url: https://argocd.example.com
  dex.config: |
    connectors:
      - type: gitlab
        id: gitlab
        name: GitLab
        config:
          baseURL: https://gitlab.example.com # URL вашего GitLab инстанса
          clientID: <application_id>
          clientSecret: $gitlab.clientSecret
          redirectURI: https://argocd.example.com/api/dex/callback
          # Дополнительные настройки для безопасности и групп:
          requestedScopes: ["openid", "profile", "email", "groups"]
          # Автоматическое обновление Groups при каждом входе
          # groupMemberAttributes: true
          # Фильтрация групп (опционально)
          # groups: ["infra/*", "shop/*"]
```

**Примечание для Self-managed GitLab с внутренним CA:**
Если GitLab использует самоподписанный сертификат, добавьте корневой сертификат в `argocd-cm`:
```yaml
dex.config: |
  logger:
    level: debug
  connectors:
    - type: gitlab
      ...
      config:
        rootCAData: <base64_encoded_ca_cert>
```

**Примечание для GitLab.com (SaaS):**
```yaml
dex.config: |
  connectors:
    - type: gitlab
      id: gitlab
      name: GitLab
      config:
        baseURL: https://gitlab.com
        clientID: <application_id>
        clientSecret: $gitlab.clientSecret
        requestedScopes: ["openid", "profile", "email", "groups"]
```

### Шаг 4: Настройка политик доступа (RBAC)

Маппинг групп GitLab на роли ArgoCD выполняется в `argocd-rbac-cm`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    # Группа 'infra-admins' получает полные права
    g, "infra/kubernetes-admins", role:admin
    
    # Кастомная роль для разработчиков проекта 'shop'
    p, role:dev-shop, applications, get, shop/*, allow
    p, role:dev-shop, applications, sync, shop/*, allow
    
    # Маппинг вложенной группы GitLab на роль
    g, "shop-team/backend-devs", role:dev-shop
```

*Важно: Названия групп в GitLab при использовании OIDC передаются как полные пути (`path/to/group`).*

### Шаг 5: Верификация и тестирование

**1. Проверка логов Dex:**
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server --tail=50 -f
```

**2. Вход через UI:**
- Откройте URL ArgoCD в браузере.
- Нажмите **LOGIN VIA GITLAB**.
- Введите учетные данные GitLab.
- Проверьте, что вы авторизованы и видите нужные приложения.

**3. Проверка Claims:**
```bash
# Просмотр информации о текущем пользователе
argocd account get

# Просмотр Roles и Groups
argocd admin settings rbac
```

**4. Проверка политик:**
```bash
# Проверка доступа конкретного пользователя к конкретному приложению
argocd admin settings rbac can role:dev-shop get applications shop/frontend
# → YES или NO

# Проверка доступа группы
argocd admin settings rbac can role:admin get clusters
# → YES
```

### Шаг 6: Обновление групп при входе (Auto-Refresh)

По умолчанию Dex обновляет Claims (группы) только при первом входе. Для автоматического обновления групп при каждом входе включите параметр `groupMemberAttributes`:

```yaml
dex.config: |
  connectors:
    - type: gitlab
      config:
        groupMemberAttributes: true
        requestedScopes: ["openid", "profile", "email", "groups"]
```

**Важно:** Это может увеличить время входа на 1-2 секунды из-за дополнительных запросов к GitLab API.

## Валидация и верификация конфигурации

Следующие процедуры позволяют подтвердить корректность настройки SSO на каждом этапе.

### 1. Проверка доступности GitLab и регистрации Application

```bash
# Проверка доступности GitLab
curl -I https://gitlab.example.com
# → HTTP/2 200 или 302 (редирект на логин)

# Проверка OIDC Discovery Endpoint (GitLab)
curl -s https://gitlab.example.com/.well-known/openid-configuration | jq '.authorization_endpoint, .token_endpoint, .jwks_uri'
# → "https://gitlab.example.com/oauth/authorize"
# → "https://gitlab.example.com/oauth/token"
# → "https://gitlab.example.com/oauth/discovery/keys"
```

### 2. Проверка Callback URL и TLS

```bash
# Проверка доступности callback URL из интернета
curl -I https://argocd.example.com/api/dex/callback
# → HTTP/2 200 или 302 (redirect к GitLab authorize)

# Проверка TLS сертификата Argo CD
openssl s_client -connect argocd.example.com:443 -servername argocd.example.com < /dev/null 2>&1 | grep -i "verify return code"
# → verify return code: 0 (ok)
```

### 3. Проверка конфигурации Dex (argocd-cm)

```bash
# Просмотр dex.config
kubectl get configmap argocd-cm -n argocd -o jsonpath='{.data.dex\.config}' | head -50
# → connectors:...
# →   - type: gitlab
# →     id: gitlab
# →     config:
# →       baseURL: https://gitlab.example.com
# →       clientID: <application_id>
# →       clientSecret: $gitlab.clientSecret

# Проверка секрета в argocd-secret
kubectl get secret argocd-secret -n argocd -o jsonpath='{.data.gitlab\.clientSecret}' | base64 -d
# → ваш_секрет_gitlab (должен совпадать с GitLab Application Secret)
```

### 4. Проверка статуса пода Dex

```bash
# Статус пода
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-dex-server -o wide
# → argocd-dex-server-xxxxx   1/1     Running   0          5d   10.244.1.5   node-1   <none>

# Логи успешного старта Dex
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server --tail=20
# → time="2026-01-15T10:30:00Z" level=info msg="Starting Dex"
# → time="2026-01-15T10:30:01Z" level=info msg="Listening on 0.0.0.0:5556"
# → time="2026-01-15T10:30:01Z" level=info msg="Connector gitlab configured"
```

### 5. Проверка RBAC конфигурации (argocd-rbac-cm)

```bash
# Просмотр policy.csv и scopes
kubectl get configmap argocd-rbac-cm -n argocd -o jsonpath='{.data.policy\.csv}'
# → g, "infra/kubernetes-admins", role:admin
# → p, role:dev-shop, applications, get, shop/*, allow
# → ...

# Проверка scopes
kubectl get configmap argocd-rbac-cm -n argocd -o jsonpath='{.data.scopes}'
# → "[groups]"

# Проверка policy.default
kubectl get configmap argocd-rbac-cm -n argocd -o jsonpath='{.data.policy\.default}'
# → role:readonly
```

### 6. Тестовый вход и проверка Claims (End-to-End)

```bash
# Вход через CLI (откроет браузер)
argocd login argocd.example.com --sso

# Проверка информации о пользователе после входа
argocd account get
# → User: user@example.com
# → Groups: ["infra/kubernetes-admins", "shop/backend"]
# → Logged In: true
# → Authenticated: true

# Проверка групп через RBAC can
argocd admin settings rbac can role:admin get applications
# → YES

argocd admin settings rbac can role:dev-shop sync applications shop/frontend
# → YES
```

### 7. Проверка автоматического обновления групп (groupMemberAttributes)

```bash
# 1. Добавьте пользователя в новую группу в GitLab
# 2. Выйдите и зайдите снова (или подождите истечения сессии)
argocd login argocd.example.com --sso

# 3. Проверьте, что новая группа появилась
argocd account get
# → Groups: [..., "new/group/path"]
```

## Диагностика и устранение неисправностей

### Алгоритм диагностики (8 шагов)

```
ПРОБЛЕМА: SSO не работает / ошибка входа / нет прав
│
├─ 1. Проверка подов: `kubectl get pods -n argocd` — все ли Running?
│   └─ Нет → Логи падающего пода → Исправьте конфигурацию/секреты
│
├─ 2. Проверка Dex логов: `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server`
│   ├─ "Invalid redirect URI" → Шаг 3
│   ├─ "TLS handshake failed" → Шаг 4
│   ├─ "Client secret mismatch" → Шаг 5
│   └─ "Connector not found" → Проверьте dex.config в argocd-cm
│
├─ 3. Проверка Callback URL: совпадает ли в GitLab и argocd-cm точно?
│   └─ Исправьте redirect URI в GitLab или argocd-cm
│
├─ 4. Проверка TLS/CA: самоподписанный сертификат GitLab?
│   └─ Добавьте rootCAData в dex.config
│
├─ 5. Проверка секрета: clientSecret в argocd-secret совпадает с GitLab?
│   └─ Обновите секрет: base64encode(new_secret) → argocd-secret
│
├─ 6. Пользователь вошел, но нет прав → Проверка RBAC
│   ├─ `argocd account get` → Groups: [] → Шаг 7
│   └─ Groups есть, но не совпадают с policy.csv → Шаг 8
│
├─ 7. Группы не приходят из GitLab
│   ├─ requestedScopes включает "groups"?
│   ├─ groupMemberAttributes: true (для вложенных)?
│   ├─ Пользователь член хотя бы одной группы в GitLab?
│   └─ GitLab API доступен из кластера (нет NetworkPolicy)?
│
└─ 8. Несовпадение групп в policy.csv
    ├─ `argocd account get` показывает точные имена групп (case-sensitive, полные пути)
    ├─ policy.csv: g, "exact/path/from/claims", role:xxx
    └─ scopes: "[groups]" в argocd-rbac-cm
```

### Расширенная таблица ошибок

| Ошибка / Симптом | Причина | Диагностика | Решение |
|------------------|---------|-------------|---------|
| `Invalid redirect URI` | Несоответствие URL в GitLab и `argocd-cm` (протокол, хост, путь, слэш) | Сравните `redirectURI` в `argocd-cm` и GitLab Application | Исправьте на точное совпадение: `https://<argocd-url>/api/dex/callback` (HTTPS, без лишних слэшей) |
| `Internal Server Error (500)` в Dex | Ошибка связи с GitLab, неверный Secret, или ошибка парсинга конфига | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server` | Проверьте `clientSecret` в `argocd-secret`; доступность GitLab из кластера; валидность YAML в `dex.config` |
| `TLS handshake failed` / `x509: certificate signed by unknown authority` | Самоподписанный/недоверенный CA сертификат GitLab | `curl -v https://gitlab.example.com`; логи Dex | Добавьте `rootCAData: <base64_ca>` в `dex.config` коннектора |
| `Client secret mismatch` / `invalid_client` | `clientSecret` в `argocd-secret` не совпадает с GitLab Application | `kubectl get secret argocd-secret -n argocd -o jsonpath='{.data.gitlab\.clientSecret}' \| base64 -d` | Обновите секрет в `argocd-secret` (base64) или пересоздайте GitLab Application |
| `Groups not received` / `groups: []` | `requestedScopes` не включает `groups`; пользователь не в группах; `groupMemberAttributes: false` для вложенных | `argocd account get` → Groups: []; проверьте `requestedScopes` в `dex.config` | Добавьте `"groups"` в `requestedScopes`; включите `groupMemberAttributes: true`; проверьте членство в GitLab |
| `Groups truncated` / `claims too large` | OIDC токен >4KB (много групп у пользователя) | `argocd account get` → Groups обрезаны; логи Dex: `claims size exceeds limit` | Используйте `groups` filter в `dex.config`: `groups: ["infra/*", "shop/*"]`; или уменьшите кол-во групп пользователя |
| `User logged in but no permissions` | Несовпадение имен групп в `policy.csv` с Claims (case-sensitive, полные пути) | `argocd account get` → Groups: ["Infra/Admins"]; `policy.csv`: `g, "infra/admins", role:admin` | Исправьте `policy.csv` на точное совпадение: `g, "Infra/Admins", role:admin` |
| `Dex pod CrashLoopBackOff` | Синтаксическая ошибка в `dex.config` (YAML, отступы, незакрытые кавычки) | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server` | Исправьте YAML в `argocd-cm`; проверьте `kubectl apply -f <(kubectl get cm argocd-cm -n argocd -o yaml)` |
| `argocd-server` не видит Dex | Сетевая недоступность между подами; Dex не слушает порт 5556 | `kubectl exec -it argocd-server-xxx -n argocd -- wget -qO- http://argocd-dex-server:5556/healthz` | Проверьте Service `argocd-dex-server`; NetworkPolicies; ClusterDNS |
| `Token expired` / `401 Unauthorized` | JWT токен истек (`users.session.duration` дефолт 24h) | `argocd account generate-token ... \| cut -d. -f2 \| base64 -d \| jq '.exp'` | Увеличьте `users.session.duration` в `argocd-cm` (например, `720h`); перелогиньтесь |
| `SSO groups not updated` | Dex кэширует группы; `groupMemberAttributes: false` (дефолт) | Группы в GitLab изменились, но `argocd account get` показывает старые | Включите `groupMemberAttributes: true` в `dex.config`; или требуйте релогин пользователей |
| `Native OIDC groups not working` | Попытка использовать нативный `oidc.config` для GitLab | `oidc.config` в `argocd-cm` настроен, но группы не приходят | Переключитесь на Dex (`dex.config` с `type: gitlab`) — нативный OIDC не поддерживает GitLab groups |
| `Multiple connectors conflict` | Два коннектора с одинаковым `id` в `dex.config` | Логи Dex: `duplicate connector id` | Убедитесь, что у каждого коннектора уникальный `id` (`gitlab`, `google`, `ldap`...) |
| `AppProject denies access despite RBAC allow` | RBAC разрешает, но AppProject `sourceRepos`/`destinations` запрещает ресурс | `argocd app get <app>` → Project: `my-project`; проверьте AppProject spec | Настройте AppProject: `sourceRepos`, `destinations`, `clusterResourceWhitelist` |
| `Callback URL returns 404` | Ingress/Route не пробрасывает `/api/dex/callback` на `argocd-dex-server` | `curl -I https://argocd.example.com/api/dex/callback` → 404 | Настройте Ingress: path `/api/dex/*` → service `argocd-dex-server:5556` |

### Команды для глубокой диагностики

```bash
# 1. Полный дамп конфигурации SSO
kubectl get configmap argocd-cm -n argocd -o yaml > argocd-cm-backup.yaml
kubectl get configmap argocd-rbac-cm -n argocd -o yaml > argocd-rbac-cm-backup.yaml
kubectl get secret argocd-secret -n argocd -o yaml > argocd-secret-backup.yaml

# 2. Проверка OIDC flow вручную (для отладки)
# Получите authorize URL из логов Dex или соберите вручную:
# https://gitlab.example.com/oauth/authorize?client_id=<client_id>&redirect_uri=https%3A%2F%2Fargocd.example.com%2Fapi%2Fdex%2Fcallback&response_type=code&scope=openid+profile+email+groups&state=<state>&nonce=<nonce>

# 3. Проверка JWKS GitLab (валидация id_token)
curl -s https://gitlab.example.com/oauth/discovery/keys | jq '.keys[] | {kid, kty, use, n, e}'

# 4. Декодирование id_token (после успешного входа, из браузера DevTools → Application → Cookies → dex.session)
# Скопируйте значение cookie, декодируйте JWT payload (часть между точками):
echo "<id_token_payload_base64>" | base64 -d | jq '.sub, .email, .groups, .preferred_username'

# 5. Проверка сессий в Dex (если Redis)
kubectl exec -it -n argocd deployment/argocd-dex-server -- redis-cli KEYS "session:*"
kubectl exec -it -n argocd deployment/argocd-dex-server -- redis-cli GET "session:<session_id>"

# 6. Проверка RBAC кэша в argocd-server
kubectl exec -it -n argocd deployment/argocd-server -- argocd admin settings rbac

# 7. События в namespace argocd
kubectl get events -n argocd --sort-by='.lastTimestamp' | tail -30
```

## Рекомендации и лучшие практики

### Безопасность

- **HTTPS обязателен:** Argo CD должен быть доступен по HTTPS с валидным TLS-сертификатом (Let's Encrypt, cert-manager, или корпоративный CA).
- **Секреты в argocd-secret:** Никогда не храните `clientSecret` в `argocd-cm`. Используйте `argocd-secret` или External Secrets Operator / Sealed Secrets для GitOps.
- **Минимальные Scopes:** Используйте только необходимые scopes: `openid`, `profile`, `email`, `groups`. Избегайте `api` scope (дает полный доступ к GitLab API).
- **Время жизни токенов:** Настройте `_expire_token_after` в GitLab Application (рекомендуется 3600 секунд / 1 час). В Argo CD установите `users.session.duration: "720h"` (30 дней) для пользователей, `8760h` (1 год) для bot-аккаунтов.
- **AppProject:** Всегда создавайте отдельные AppProject для разных команд/окружений с ограничениями по источникам (`sourceRepos`), назначениям (`destinations`) и кластерным ресурсам.
- **Dex rootCAData:** Для Self-managed GitLab с внутренним CA всегда добавляйте `rootCAData` в `dex.config` — не отключайте проверку TLS.
- **Admin пользователь:** Оставьте локального `admin` с паролем (в `argocd-secret`) как аварийный доступ на случай недоступности Dex/GitLab. Отключите только в продакшене после проверки SSO: `admin.enabled: "false"` в `argocd-cm`.

### Производительность

- **Кеширование Groups:** Если GitLab содержит много групп (>100 на пользователя), используйте `groupMemberAttributes: false` для ускорения входа (обновление групп только при первом входе). Включайте `true` только если критически важны вложенные группы.
- **Фильтрация групп:** Используйте `groups: ["infra/*", "shop/*"]` в `dex.config` для ограничения запрашиваемых групп — уменьшает размер ID Token и нагрузку на GitLab API.
- **Dex Logging:** В продакшене установите `logger.level: info` (не `debug`) для снижения нагрузки на логирование и диски.
- **Redis для Dex:** В HA-режиме настройте `storage.config.redis` в `dex.config` для общего кэша сессий между репликами `argocd-dex-server`.

### Надежность

- **Мониторинг Dex:** Добавьте алерты на `CrashLoopBackOff` пода `argocd-dex-server` и на `dex_grpc_requests_total{grpc_code!="OK"}` (Prometheus метрики Dex).
- **Fallback:** Настройте `policy.default: role:readonly` для пользователей без явного маппинга групп — безопасный дефолт.
- **Тестирование:** Перед изменением политик проверяйте доступ через `argocd admin settings rbac can <role> <action> <resource>`.
- **Backup конфигурации:** Регулярно делайте бэкап `argocd-cm`, `argocd-rbac-cm`, `argocd-secret` (например, через Velero или `kubectl get ... -o yaml > backup.yaml`).
- **Disaster Recovery:** Документируйте процедуру восстановления SSO: 1) восстановить секреты, 2) восстановить ConfigMaps, 3) перезапустить `argocd-dex-server` и `argocd-server`.

### Операционные практики

- **Логирование:** Для отладки временно включайте `logger.level: debug` в `dex.config`, после диагностики возвращайте `info`.
- **Группы:** Если группы не отображаются — проверяйте `requestedScopes` (должен включать `groups`) и членство пользователя в GitLab.
- **Вложенные группы:** Для поддержки вложенных групп обязательно `groupMemberAttributes: true` в `dex.config`.
- **Ротация секретов:** Регулярно ротируйте `clientSecret` в GitLab и обновляйте в `argocd-secret` (без даунтайма: обновите секрет → перезапустите `argocd-dex-server`).
- **Аудит входов:** Логи Dex содержат `user_login` события — настройте сбор в SIEM для аудита доступа.

## Ограничения и edge cases

### Ограничения

1. **GitLab Groups через Dex:** Вложенные группы поддерживаются только через Dex (не через нативный OIDC Argo CD).
2. **Лимит Claims:** OIDC-токен ограничен размером (обычно 4KB). Если у пользователя >50 групп, некоторые группы могут быть обрезаны. Решение: фильтр `groups: ["pattern/*"]` в `dex.config`.
3. **Кеширование сессий:** Dex кэширует сессии в Redis (или in-memory). При изменении групп в GitLab пользователю необходимо перезайти (или истечение сессии по `users.session.duration`).
4. **Нативный OIDC vs Dex:** Для GitLab **обязательно** использовать Dex (нативный `oidc.config` не поддерживает GitLab-специфичные поля `groups` и вложенные группы).
5. **Dex Single Replica по умолчанию:** В стандартной установке `argocd-dex-server` — 1 реплика. Для HA увеличьте `replicas` и настройте Redis storage.
6. **Нет поддержки SAML в Dex для GitLab:** GitLab коннектор в Dex — только OIDC. Для SAML используйте нативный `oidc.config` с SAML IdP (не GitLab).

### Edge Cases

1. **Пользователь в нескольких группах:** Argo CD объединяет права всех ролей, назначенных пользователю через группы (union of permissions). `deny` правила имеют приоритет над `allow` из других ролей.
2. **Группа не существует в GitLab:** Если группа удалена из GitLab, Dex не вернет её в Claims при следующем входе. Соответствующая роль в Argo CD перестанет применяться.
3. **Самоподписанный сертификат GitLab:** Добавьте `rootCAData` в конфигурацию коннектора. Без этого TLS handshake упадет.
4. **GitLab Group Membership через LDAP:** Если пользователь является членом группы через LDAP-синхронизацию в GitLab, GitLab все равно возвращает эту группу в OIDC Claims — Dex не отличает источник членства.
5. **Несколько коннекторов:** Каждый коннектор должен иметь уникальный `id`. Пользователь может войти через любой доступный коннектор. Claims объединяются по `sub` (если совпадает).
6. **RBAC и AppProject:** Политики RBAC работают совместно с AppProject. Даже если роль разрешает `sync`, AppProject может запретить этот ресурс через `sourceRepos`, `destinations`, `clusterResourceWhitelist`.
7. **Отзыв доступа в GitLab:** При отзыве доступа пользователя в GitLab (удаление из групп, блокировка аккаунта) его сессия в Argo CD остается активной до истечения времени жизни JWT токена (`users.session.duration`, дефолт 24h). Принудительный логаут: удалите сессию в Redis или перезапустите `argocd-server`.
8. **Case-sensitivity групп:** Маппинг `g, "Infra/Admins", role:admin` не сработает для группы `infra/admins` из OIDC — требуется точное совпадение строки (включая регистр и слеши). Проверяйте через `argocd account get`.
9. **scopes влияет только на OIDC:** Параметр `scopes: "[groups]"` в `argocd-rbac-cm` влияет только на группы из OIDC-токена. Локальные пользователи и JWT-токены не используют scopes.
10. **Token lifetime vs Session duration:** GitLab `_expire_token_after` (access token TTL) ≠ Argo CD `users.session.duration` (JWT TTL). Настраивайте независимо: GitLab — 1h, Argo CD — 30d.
11. **Redirect URI mismatch при Ingress path-based routing:** Если Ingress использует path-based routing (`/argocd/*`), callback URL должен включать путь: `https://domain.com/argocd/api/dex/callback`. И в GitLab, и в `argocd-cm` должен быть полный путь.
12. **Dex не обновляет email при смене в GitLab:** Email в Claims обновляется только при релогина. Для критических изменений требуйте перезаход.
13. **NetworkPolicy блокирует Dex → GitLab:** Если применяете NetworkPolicies, разрешите egress от `argocd-dex-server` к GitLab IP/домену на 443 порт.
14. **argocd-server не перезапускается при изменении argocd-cm:** Изменения в `argocd-cm` (dex.config, oidc.config, users.session.duration) требуют перезапуска `argocd-server` для применения: `kubectl rollout restart deployment argocd-server -n argocd`.
15. **Bot-аккаунты (CI/CD):** Для сервисных аккаунтов используйте локальные аккаунты Argo CD (`argocd account create bot --password ...`) или JWT с длительным TTL (`users.session.duration: "8760h"`), а не SSO — SSO требует интерактивного браузера.

## Дополнительная информация

## Дополнительная информация

### Использование нескольких коннекторов

Dex позволяет одновременно настроить несколько провайдеров (например, GitLab для сотрудников и Google для подрядчиков). Каждый коннектор должен иметь уникальный `id`.

**Пример: GitLab + Google:**
```yaml
dex.config: |
  connectors:
    - type: gitlab
      id: gitlab
      name: GitLab (Corporate)
      config:
        baseURL: https://gitlab.example.com
        clientID: <gitlab_client_id>
        clientSecret: $gitlab.clientSecret
        requestedScopes: ["openid", "profile", "email", "groups"]
    - type: google
      id: google
      name: Google (Contractors)
      config:
        clientID: <google_client_id>
        clientSecret: $google.clientSecret
        redirectURI: https://argocd.example.com/api/dex/callback
        hostedDomains: ["contractor.example.com"]
```

### См. также

- [ArgoCD: Установка и настройка HA](./argocd_installation_and_setup.md)
- [Диагностика и мониторинг ArgoCD](./argocd_troubleshooting_and_monitoring.md)
- [ArgoCD: Автоматизация через API и Ansible](./argocd_api_automation.md)
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Изоляция проектов, квоты, restrictions, кастомные роли.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.

### Официальные ресурсы

- [ArgoCD OIDC Configuration](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/gitlab/)
- [Dex GitLab Connector Specs](https://dexidp.io/docs/connectors/gitlab/)
- [ArgoCD RBAC Configuration](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)
