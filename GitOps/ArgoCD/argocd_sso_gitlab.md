# Argo CD: Настройка SSO через GitLab

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Kubernetes 1.28–1.32+; bare-metal / on-premise; Dex v2.41+; GitLab Self-managed 16.x–17.x / SaaS; Casbin RBAC, OIDC / PKCE flow)

Настройка Single Sign-On (SSO) в Argo CD через GitLab позволяет централизованно управлять доступом инженеров, используя корпоративные учетные записи и иерархию групп GitLab. В архитектуре Argo CD аутентификация через GitLab реализуется с помощью встроенного федеративного провайдера **Dex** (`argocd-dex-server`), выступающего OIDC-посредником между сервером Argo CD (`argocd-server`) и API/OAuth2 GitLab. Использование Dex является стандартом для GitLab, так как обеспечивает поддержку вложенных подгрупп (nested subgroups), сопоставление уровней доступа участников (`getGroupsPermission`) и фильтрацию списков групп.

---

## Предварительные требования

Перед настройкой интеграции SSO убедитесь в выполнении следующих условий в on-premise окружении:

| № | Компонент / Требование | Описание и контекст | Команда проверки | Ожидаемый результат |
|---|------------------------|---------------------|------------------|---------------------|
| 1 | **Kubernetes кластер** | v1.28–v1.32+ (bare-metal / on-premise под управлением kubeadm, RKE2, Talos) | `kubectl version --short 2>/dev/null \|\| kubectl version` | `Server Version: v1.28.x` (или выше) |
| 2 | **Компоненты Argo CD** | v3.5.x установлены в пространстве имен `argocd` | `kubectl get pods -n argocd -l app.kubernetes.io/part-of=argocd` | Поды `argocd-server`, `argocd-dex-server`, `argocd-repo-server`, `argocd-application-controller` в статусе `Running` |
| 3 | **Сервер Dex** | Под `argocd-dex-server` запущен и готов к обработке gRPC-запросов | `kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-dex-server` | `argocd-dex-server-xxxxx   1/1     Running   0          5d` |
| 4 | **Инстанс GitLab** | GitLab Self-managed (v16.0–v17.x) или SaaS (gitlab.com), доступный по сети из кластера | `curl -k -s -o /dev/null -w "%{http_code}\n" https://gitlab.example.com` | `200` или `302` |
| 5 | **Внешний HTTPS Ingress** | Доменное имя Argo CD с валидным TLS-сертификатом (Let's Encrypt / внутренний корпоративный CA) | `openssl s_client -connect argocd.example.com:443 -servername argocd.example.com < /dev/null 2>&1 \| grep -i "verify return code"` | `Verify return code: 0 (ok)` |
| 6 | **Административные права** | Права на чтение и запись ресурсов `ConfigMap` и `Secret` в пространстве имен `argocd` | `kubectl auth can-i patch configmap -n argocd` | `yes` |
| 7 | **Утилиты командной строки** | `argocd` CLI v3.5+, `kubectl`, `jq`, `base64`, `openssl` установлены на рабочей станции | `argocd version --client --short` | `argocd: v3.5.x` |
| 8 | **Сетевой маршрут Dex → GitLab** | Отсутствие блокировок сетевых политик (NetworkPolicy / фаервол) для Egress из подов Dex в порт 443 GitLab | `kubectl exec -n argocd deploy/argocd-dex-server -- nc -zv gitlab.example.com 443` | `gitlab.example.com (x.x.x.x:443) open` |

> **Важно:** Если корпоративный GitLab использует внутренний самоподписанный центр сертификации (Internal Enterprise CA), подготовьте base64-кодированный корневой сертификат (`cat internal-ca.crt | base64 -w0`) для директивы `rootCAData` в конфигурации коннектора.

---

## Определения

| Термин | Определение |
|--------|-------------|
| **SSO (Single Sign-On)** | Технология единой точки входа, позволяющая пользователю единожды пройти аутентификацию в IdP (GitLab) и получить доступ к API и веб-интерфейсу Argo CD без локальных паролей. |
| **Dex** | Легковесный федеративный OpenID Connect (OIDC) провайдер с открытым исходным кодом (`github.com/dexidp/dex`), поставляемый в составе дистрибутива Argo CD (`argocd-dex-server`). Выступает шлюзом между Argo CD и коннекторами внешних систем идентификации. |
| **OIDC (OpenID Connect)** | Протокол идентификации поверх спецификации OAuth 2.0, передающий профиль пользователя и списки групп через криптографически подписанный токен ID Token (JWT). |
| **IdP (Identity Provider)** | Поставщик удостоверений — система, хранящая учетные записи пользователей и групп (в данном контексте — инстанс GitLab). |
| **Authorization Code Flow с PKCE** | Стандартный поток OIDC для веб-приложений: браузер получает временный авторизационный код в IdP с защитой от перехвата (Proof Key for Code Exchange), который сервер обменивает на токены по защищенному каналу бэкенда. |
| **ID Token** | Формат JSON Web Token (JWT), подписанный ключами IdP или Dex, содержащий набор клеймов (`claims`) о пользователе: `sub`, `email`, `groups`, `preferred_username`. |
| **Claims** | Пары «ключ-значение» внутри полезной нагрузки JWT, содержащие идентификаторы субъекта, почту и перечень групп. В GitLab группы передаются в виде полных путей с учетом регистра: `path/to/subgroup`. |
| **getGroupsPermission** | Специфичный параметр Dex GitLab Connector: при включении (`true`) дополняет список групп суффиксом роли участника в GitLab (например, `infra/k8s-admins:maintainer`, `shop/devs:developer`). |
| **useLoginAsID** | Параметр Dex GitLab Connector: при значении `true` использует строковый логин GitLab (`preferred_username`) в качестве клейма `sub` вместо неизменяемого числового ID (`12345`). |
| **argocd-cm** | Системный ConfigMap глобальных настроек Argo CD: внешний URL (`url`), конфигурация Dex (`dex.config`), параметры сессий (`users.session.duration`), статус локального админа (`admin.enabled`). |
| **argocd-rbac-cm** | Системный ConfigMap Casbin RBAC: файл правил `policy.csv`, дефолтная роль `policy.default`, режим сопоставления `policy.matchMode` и источники клеймов `scopes`. |
| **argocd-secret** | Системный Secret пространства имен `argocd`, используемый для безопасного хранения `gitlab.clientSecret`, пароля администратора и ключей подписи сессий. |
| **Callback URL** | Эндпоинт обратного вызова Dex: `https://<argocd-url>/api/dex/callback`, на который GitLab перенаправляет браузер пользователя после успешного ввода учетных данных. |
| **Casbin Engine** | Встроенный механизм авторизации Argo CD, сопоставляющий субъектов (`g`, группы из OIDC) с ролями и правилами доступа (`p`, политики к ресурсам приложений, репозиториев и проектов). |

---

## Архитектура и базовые концепции

### Архитектура компонентов аутентификации

В архитектуре Argo CD сервер управления интерфейсом и API (`argocd-server`) не общается напрямую с GitLab OAuth API. Роль шлюза выполняет встроенный сервис `argocd-dex-server`:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│               Argo CD SSO: Топология взаимодействия компонентов                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ┌──────────────┐     HTTPS (TLS 443)      ┌─────────────────────────────┐     │
│   │   Браузер    │─────────────────────────▶│    Ingress Controller       │     │
│   │ Пользователя │                          │   (NGINX / HAProxy / Envoy) │     │
│   └──────────────┘                          └─────────────────────────────┘     │
│          ▲   ▲                                             │                    │
│          │   │                                      Маршрутизация               │
│          │   │                                ┌────────────┴────────────┐       │
│          │   │                                ▼                         ▼       │
│          │   │                       ┌─────────────────┐       ┌──────────────┐ │
│          │   │                       │  argocd-server  │       │  argocd-dex  │ │
│          │   │                       │   (UI & API)    │       │   (Порт 5556)│ │
│          │   │                       └─────────────────┘       └──────────────┘ │
│          │   │                                │ gRPC (Внутренний)       ▲       │
│          │   │                                └─────────────────────────┘       │
│          │   │                                                          │       │
│          │   └────────────────────── OAuth2 Flow ───────────────────────┤       │
│          │                          (Авторизация в браузере)            │       │
│          ▼                                                              ▼       │
│   ┌────────────────────────────────────────────────────────────────────────┐    │
│   │                    Корпоративный GitLab (IdP)                          │    │
│   │        OAuth Application: /oauth/authorize, /oauth/token, /api/v4/user │    │
│   └────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Пошаговый протокол OIDC Authorization Code Flow

Процесс сквозной аутентификации пользователя строится по следующему алгоритму:

1. **Инициация входа:** Пользователь открывает веб-интерфейс Argo CD и нажимает кнопку **«LOG IN VIA GITLAB»** (или выполняет команду `argocd login argocd.example.com --sso`).
2. **Формирование редиректа:** `argocd-server` запрашивает у `argocd-dex-server` URL авторизации и возвращает браузеру HTTP-редирект (302) на эндпоинт `/api/dex/auth/gitlab`.
3. **Запрос авторизации к GitLab:** Dex генерирует параметры `state`, криптографический `nonce`, хэш `code_challenge` (PKCE) и перенаправляет браузер на GitLab:
   `https://gitlab.example.com/oauth/authorize?client_id=...&redirect_uri=https://argocd.example.com/api/dex/callback&response_type=code&scope=openid+profile+email+read_user&state=...`
4. **Аутентификация пользователя:** Пользователь вводит логин и пароль в GitLab (или использует активную сессию / 2FA).
5. **Подтверждение прав (Consent):** При первой авторизации GitLab запрашивает подтверждение доступа приложения Argo CD к профилю и списку групп.
6. **Возврат кода (Authorization Callback):** GitLab перенаправляет браузер на `https://argocd.example.com/api/dex/callback?code=AUTH_CODE&state=...`.
7. **Обмен кода на токены (Backchannel):** Под `argocd-dex-server` напрямую (через внутрикластерный Egress) отправляет POST-запрос на GitLab `/oauth/token`, передавая `code`, `client_id`, `client_secret` и `code_verifier`.
8. **Получение данных профиля и групп:** Dex отправляет запрос к GitLab API (`/api/v4/user` и `/api/v4/groups`) с полученным `access_token` для извлечения полного дерева групп пользователя.
9. **Генерация внутреннего токена Dex:** Dex сохраняет сессию во внутреннем хранилище (in-memory или Redis) и передает подписанный JWT ID Token обратно в `argocd-server`.
10. **Авторизация в Casbin:** `argocd-server` валидирует токен Dex, извлекает клеймы `email` и `groups`, сопоставляет их с правилами в `argocd-rbac-cm` (`policy.csv`) и генерирует собственную сессионную куку `argocd.token` со сроком жизни `users.session.duration`.

### Сравнение: Встроенный Dex vs Нативный `oidc.config`

В Argo CD v3.5+ существует возможность прямой интеграции с OIDC-провайдерами через секцию `oidc.config` в обход Dex. Однако для GitLab использование Dex является критически важным:

| Функциональность | Нативный `oidc.config` (Argo CD) | Dex GitLab Connector (`dex.config`) |
|------------------|----------------------------------|-------------------------------------|
| **Вложенные подгруппы (Subgroups)** | Ограниченная поддержка (требуются специальные клеймы в GitLab CI/OIDC) | Полная поддержка (Dex рекурсивно опрашивает дерево групп через GitLab API) |
| **Уровни доступа (`getGroupsPermission`)** | ❌ Не поддерживается | ✅ Поддерживается (добавляет `:maintainer`, `:developer`, `:owner`) |
| **Фильтрация групп (Whitelist)** | ❌ Отсутствует (все группы пользователя попадают в токен) | ✅ Поддерживается директивой `groups: [...]` |
| **Защита от переполнения HTTP-заголовков** | ❌ Риск падения с HTTP 431 при >50 групп у пользователя | ✅ Фильтрация уменьшает размер ID Token |
| **Запрос к GitLab API** | Работает только по стандартному OIDC UserInfo | Использует специализированный REST клиент GitLab v4 API |
| **Кастомный CA для IdP** | Требует монтирования томов с сертификатами в `argocd-server` | Настраивается декларативно через строковый параметр `rootCAData` |

**Вывод:** Для GitLab Self-managed и SaaS в производственных средах всегда настраивайте интеграцию через **`dex.config`**.

### Структура клеймов (Claims) GitLab и сопоставление групп

При успешном запросе Dex формирует для Argo CD следующий набор клеймов:

```json
{
  "iss": "https://argocd.example.com/api/dex",
  "sub": "CiQxMjM0NTY3OBIGZ2l0bGFi",
  "aud": "argo-cd",
  "exp": 1776000000,
  "iat": 1775913600,
  "email": "alex.sre@example.com",
  "email_verified": true,
  "name": "Alex SRE",
  "preferred_username": "alex-sre",
  "groups": [
    "infrastructure",
    "infrastructure/kubernetes",
    "infrastructure/kubernetes:maintainer",
    "projects/payment-gateway",
    "projects/payment-gateway:developer"
  ]
}
```

> **Критическое правило сопоставления групп в Casbin:**
> 1. Пути групп всегда передаются **полными путями от корня инстанса** через прямой слеш (`infrastructure/kubernetes`), а не просто конечным именем подгруппы.
> 2. Строки путей чувствительны к регистру (**case-sensitive**): `Infrastructure/Kubernetes` и `infrastructure/kubernetes` считаются разными группами.
> 3. Если включен параметр `getGroupsPermission: true`, Dex генерирует две записи для каждой группы: имя группы и имя группы с суффиксом роли (`:owner`, `:maintainer`, `:developer`, `:reporter`, `:guest`).

---

## Практические сценарии и конфигурация

### Шаг 1: Регистрация приложения в GitLab

Приложение можно зарегистрировать на уровне всего инстанса (Admin Area) или на уровне корневой группы команд. Для производственных инсталляций рекомендуется регистрация на уровне инстанса:

1. В GitLab откройте **Admin Area → Applications** (или **Settings → Applications** в корневой группе).
2. Заполните параметры приложения:
   - **Name:** `Argo CD Production`
   - **Redirect URI:** `https://argocd.example.com/api/dex/callback`
   - **Trusted:** `No` (или `Yes`, если хотите пропустить экран подтверждения consent screen для сотрудников).
   - **Confidential:** `Yes` (Обязательно! Включает валидацию Client Secret на бэкенде Dex).
   - **Scopes:**
     - `openid` — обязателен для протокола OIDC.
     - `profile` — получение имени и логина пользователя.
     - `email` — получение корпоративного email адреса.
     - `read_user` — **критически необходим** для Dex: позволяет запрашивать членство в группах через GitLab REST API v4.
3. Нажмите кнопку **Save application**.
4. Скопируйте сгенерированные значения:
   - **Application ID** (публичный идентификатор клиента).
   - **Secret** (секретный ключ клиента, отображается единожды).

### Шаг 2: Безопасное хранение секрета в Kubernetes

В соответствии со стандартом GitOps и практиками безопасности, секреты никогда не должны храниться в открытом виде в `ConfigMap`. Значение `clientSecret` размещается в секрете `argocd-secret` в пространстве имен `argocd`.

**Вариант А: Быстрое добавление через kubectl:**
```bash
# Добавление/обновление ключа gitlab.clientSecret в существующий секрет
kubectl patch secret argocd-secret -n argocd --type merge -p "{\"stringData\": {\"gitlab.clientSecret\": \"glcpr-9876543210abcdeffedcba0123456789\"}}"
# → secret/argocd-secret patched
```

**Вариант Б: Декларативный манифест (SOPS / Sealed Secrets для bare-metal):**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-secret
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-secret
    app.kubernetes.io/part-of: argocd
type: Opaque
stringData:
  # Ключ, на который ссылается $gitlab.clientSecret в dex.config
  gitlab.clientSecret: "glcpr-9876543210abcdeffedcba0123456789"
```

### Шаг 3: Конфигурация Dex в ConfigMap `argocd-cm`

Отредактируйте `argocd-cm`, указав внешний базовый URL инстанса и параметры коннектора Dex.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-cm
    app.kubernetes.io/part-of: argocd
data:
  # Внешний URL интерфейса Argo CD (строго без завершающего слеша)
  url: https://argocd.example.com

  # Длительность сессии JWT токена пользователя (по умолчанию 24h)
  users.session.duration: "24h"

  # Конфигурация встроенного сервера Dex
  dex.config: |
    logger:
      level: info
      format: json
    connectors:
      - type: gitlab
        id: gitlab
        name: GitLab
        config:
          # URL корпоративного GitLab (для SaaS: https://gitlab.com)
          baseURL: https://gitlab.example.com
          clientID: "1a2b3c4d5e6f7a8b9c0d1e2f"
          # Подстановка значения из Secret argocd-secret (ключ gitlab.clientSecret)
          clientSecret: $gitlab.clientSecret
          redirectURI: https://argocd.example.com/api/dex/callback
          
          # Опционально: фильтрация групп (whitelist).
          # Если указано, в токен попадут ТОЛЬКО перечисленные группы.
          # Если пользователь не состоит ни в одной из них, вход будет отклонен.
          groups:
            - infrastructure/kubernetes
            - infrastructure/sre-team
            - development/platform-devs
            - security/secops
          
          # Включение ролевых суффиксов к группам (:owner, :maintainer, :developer)
          getGroupsPermission: true
          
          # Использовать логин пользователя вместо числового ID в качестве sub
          useLoginAsID: false
```

#### Настройка для GitLab с корпоративным самоподписанным CA

Если инстанс GitLab защищен внутренним центром сертификации, Dex завершит рукопожатие с ошибкой `x509: certificate signed by unknown authority`. Добавьте корневой сертификат в директиву `rootCAData`:

```bash
# Получение base64 строки сертификата в одну строку
cat /etc/ssl/certs/corporate-internal-ca.crt | base64 -w0
# → LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCg==...
```

Фрагмент манифеста `argocd-cm`:
```yaml
data:
  dex.config: |
    connectors:
      - type: gitlab
        id: gitlab
        name: Corporate GitLab
        config:
          baseURL: https://gitlab.internal.lan
          clientID: "corporate_app_id"
          clientSecret: $gitlab.clientSecret
          redirectURI: https://argocd.example.com/api/dex/callback
          getGroupsPermission: true
          # Base64-кодированный PEM-сертификат внутреннего CA
          rootCAData: "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCg=="
```

### Шаг 4: Конфигурация Ingress для поддержки Dex Callback

Для корректной работы OIDC Ingress Controller обязан корректно передавать заголовки `X-Forwarded-*` и проксировать эндпоинты `/api/dex/*` на сервис `argocd-server`.

Пример манифеста для **NGINX Ingress Controller**:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server-ingress
  namespace: argocd
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-buffer-size: "128k"
    nginx.ingress.kubernetes.io/proxy-buffers-number: "8"
    nginx.ingress.kubernetes.io/proxy-busy-buffers-size: "256k"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - argocd.example.com
      secretName: argocd-server-tls
  rules:
    - host: argocd.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: argocd-server
                port:
                  name: https
```

> **Важно:** Обратите внимание на аннотации `proxy-buffer-size: "128k"`. Если пользователь состоит в нескольких десятках групп GitLab, размер куки авторизации и заголовка HTTP может превысить дефолтные 4KB NGINX, что вызовет ошибку `502 Bad Gateway`.

### Шаг 5: Настройка политик доступа (RBAC) в `argocd-rbac-cm`

Управление правами доступа осуществляется в `argocd-rbac-cm`. Политики сопоставляют группы GitLab (извлеченные Dex) со стандартными и пользовательскими ролями Casbin.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-rbac-cm
    app.kubernetes.io/part-of: argocd
data:
  # Дефолтная роль для любого аутентифицированного пользователя
  policy.default: role:readonly

  # Включение регулярных выражений или glob-паттернов (glob по умолчанию)
  policy.matchMode: glob

  # Извлечение групп из клейма groups в токене Dex
  scopes: "[groups]"

  policy.csv: |
    # =========================================================================
    # 1. Администраторы инфраструктуры (SRE / Platform Team)
    # Полный доступ ко всем ресурсам и кластерам
    # =========================================================================
    g, "infrastructure/sre-team", role:admin
    g, "infrastructure/kubernetes:maintainer", role:admin
    g, "infrastructure/kubernetes:owner", role:admin

    # =========================================================================
    # 2. Роль для разработчиков платформенных сервисов (Platform Devs)
    # Доступ к просмотру, синхронизации и оверрайду параметров приложений проекта core
    # =========================================================================
    p, role:platform-developer, applications, get, core/*, allow
    p, role:platform-developer, applications, sync, core/*, allow
    p, role:platform-developer, applications, action/*, core/*, allow
    p, role:platform-developer, logs, get, core/*, allow
    p, role:platform-developer, exec, create, core/*, allow
    # Явный запрет на удаление приложений
    p, role:platform-developer, applications, delete, core/*, deny

    # Привязка группы разработчиков с правами Maintainer в GitLab
    g, "development/platform-devs:maintainer", role:platform-developer
    g, "development/platform-devs:developer", role:platform-developer

    # =========================================================================
    # 3. Роль аудиторов и инженеров безопасности (SecOps)
    # Чтение приложений, просмотр логов и событий в режиме read-only
    # =========================================================================
    p, role:secops-auditor, applications, get, *, allow
    p, role:secops-auditor, logs, get, *, allow
    p, role:secops-auditor, clusters, get, *, allow
    p, role:secops-auditor, repositories, get, *, allow
    g, "security/secops", role:secops-auditor

    # =========================================================================
    # 4. Сервисные аккаунты CI/CD автоматизации
    # =========================================================================
    p, role:ci-deployer, applications, sync, *, allow
    p, role:ci-deployer, applications, get, *, allow
    g, "ci/pipeline-runner", role:ci-deployer
```

### Шаг 6: Маппинг групп на уровне AppProject (Изоляция команд)

В мультитенантных средах права можно делегировать напрямую внутри манифеста `AppProject` через секцию `.spec.roles`. Это исключает разрастание глобального файла `policy.csv`.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: billing-system
  namespace: argocd
spec:
  description: "Проект биллинговых сервисов компании"
  sourceRepos:
    - "https://gitlab.example.com/billing/*"
  destinations:
    - namespace: "billing-prod"
      server: "https://kubernetes.default.svc"
    - namespace: "billing-stage"
      server: "https://kubernetes.default.svc"
  
  # Локальные роли проекта с привязкой к OIDC-группам GitLab
  roles:
    - name: billing-lead
      description: "Тимлиды биллинга: полный контроль приложений проекта"
      policies:
        - p, proj:billing-system:billing-lead, applications, *, billing-system/*, allow
      groups:
        - "billing/team-leads"
        - "billing/core-service:maintainer"

    - name: billing-developer
      description: "Разработчики: просмотр и ручной запуск синхронизации"
      policies:
        - p, proj:billing-system:billing-developer, applications, get, billing-system/*, allow
        - p, proj:billing-system:billing-developer, applications, sync, billing-system/*, allow
      groups:
        - "billing/developers:developer"
```

---

## Операции и команды

Сводка типовых команд системного инженера для управления, верификации и тестирования SSO.

### Проверка работоспособности компонентов и логов

| Цель операции | Команда CLI / kubectl | Ожидаемый результат / Примечание |
|---------------|-----------------------|----------------------------------|
| Проверка статуса подов Dex и API | `kubectl get pods -n argocd -l "app.kubernetes.io/name in (argocd-server,argocd-dex-server)"` | `Running` у всех реплик |
| Проверка логов Dex в реальном времени | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server -c dex --tail=50 -f` | JSON-логи Dex с сообщениями коннектора |
| Проверка gRPC эндпоинта Dex изнутри пода | `kubectl exec -n argocd deploy/argocd-server -- nc -zv argocd-dex-server 5556` | `argocd-dex-server (x.x.x.x:5556) open` |
| Проверка OIDC Discovery в GitLab | `curl -s https://gitlab.example.com/.well-known/openid-configuration \| jq '.issuer, .authorization_endpoint'` | Вывод эндпоинтов авторизации GitLab |

### Тестирование аутентификации и сессий

```bash
# 1. Вход через SSO в командной строке (открывает локальный порт и браузер)
argocd login argocd.example.com --sso
# → Opening browser for authentication
# → Successfully logged in to 'argocd.example.com'

# 2. Проверка учетных данных текущего пользователя и перечня групп
argocd account get
# → Username: alex.sre@example.com
# → Logged In: true
# → Roles: role:admin
# → Groups: infrastructure/kubernetes, infrastructure/kubernetes:maintainer

# 3. Валидация синтаксиса политик в ConfigMap
argocd admin settings rbac validate
# → Policy is valid

# 4. Проверка прав конкретной роли или группы к ресурсу (Dry-Run проверка)
argocd admin settings rbac can role:platform-developer sync applications "core/backend"
# → Yes

argocd admin settings rbac can role:platform-developer delete applications "core/backend"
# → No
```

### Декодирование и инспекция сессионного токена

Для отладки переданных групп можно извлечь токен текущей сессии и распарсить полезную нагрузку JWT:

```bash
# Извлечение токена из локального конфига ~/.argocd/config и парсинг payload
grep "auth-token" ~/.argocd/config | awk '{print $2}' | tr -d '"' | cut -d. -f2 | base64 -d 2>/dev/null | jq '{sub, iss, exp, groups}'
# → {
# →   "sub": "alex.sre@example.com",
# →   "iss": "argo-cd",
# →   "exp": 1776000000,
# →   "groups": [
# →     "infrastructure/kubernetes",
# →     "infrastructure/kubernetes:maintainer"
# →   ]
# → }
```

### Применение изменений и ротация секретов

```bash
# 1. Применение обновленного argocd-cm без перезапуска кластера
kubectl apply -f argocd-cm.yaml
# → configmap/argocd-cm configured

# 2. Перезапуск подов Dex и Argo CD Server для гарантированного сброса кэша
kubectl rollout restart deployment argocd-dex-server argocd-server -n argocd
# → deployment.apps/argocd-dex-server restarted
# → deployment.apps/argocd-server restarted

# 3. Ожидание завершения перезапуска
kubectl rollout status deployment argocd-server -n argocd --timeout=60s
# → deployment "argocd-server" successfully rolled out
```

---

## Диагностика и устранение неисправностей

### Алгоритм диагностики сбоев SSO

При возникновении проблем со входом следуйте поэтапному алгоритму локализации:

```
Проблема: Ошибка авторизации SSO / нет доступа к приложениям
│
├── 1. Проверка доступности пода Dex:
│    `kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-dex-server`
│    └── Статус CrashLoopBackOff? → Синтаксическая ошибка в dex.config (YAML/отступы)
│
├── 2. Проверка логов Dex:
│    `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server -c dex --tail=100`
│    ├── "redirect_uri_mismatch" → Несовпадение URL в GitLab и argocd-cm (Шаг 3)
│    ├── "certificate signed by unknown authority" → Ошибка TLS CA GitLab (Шаг 4)
│    ├── "invalid_client" → Неверный Secret в argocd-secret (Шаг 5)
│    └── "failed to get user groups" → Недостаточно прав у OAuth App (нет scope read_user)
│
├── 3. Проверка совпадения Callback URL:
│    В GitLab: https://argocd.example.com/api/dex/callback
│    В argocd-cm: redirectURI: https://argocd.example.com/api/dex/callback
│
├── 4. Проверка TLS и сертификата CA:
│    Проверьте rootCAData в dex.config и доступность gitlab по HTTPS из пода Dex.
│
├── 5. Проверка Secret:
│    `kubectl get secret argocd-secret -n argocd -o jsonpath='{.data.gitlab\.clientSecret}' | base64 -d`
│
└── 6. Пользователь авторизован, но видит пустой экран (Нет прав):
     ├── Выполните `argocd account get` — присутствуют ли группы в выводе?
     ├── Если групп нет: проверьте scope `read_user` в GitLab и членство пользователя.
     └── Если группы есть: сравните вывод групп со строками в `policy.csv` (регистр, слэши, суффиксы).
```

### Матрица типовых ошибок и их устранение

| Симптом / Ошибка в логах | Первопричина | Метод диагностики | Способ решения |
|--------------------------|--------------|-------------------|----------------|
| `redirect_uri_mismatch` / `The redirect URI provided is missing or not allowed` | Несовпадение адреса обратного вызова в настройках GitLab Application и параметре `redirectURI` в `dex.config` | Сравните значение в GitLab с `kubectl get cm argocd-cm -n argocd -o yaml \| grep redirectURI` | Установите точный URL: `https://argocd.example.com/api/dex/callback` (проверьте схему HTTPS и отсутствие завершающего слэша). |
| `x509: certificate signed by unknown authority` | Инстанс GitLab использует самоподписанный сертификат или внутренний корпоративный CA, которому не доверяет контейнер Dex | Логи `argocd-dex-server`: `tls: failed to verify certificate` | Экспортируйте корневой CA в base64 и добавьте его в параметр `rootCAData` в `dex.config`. |
| `invalid_client` / `Client authentication failed` | Ключ `clientSecret` в Kubernetes Secret `argocd-secret` не соответствует секрету приложения в GitLab | Проверьте значение секрета: `kubectl get secret argocd-secret -n argocd -o jsonpath='{.data.gitlab\.clientSecret}' \| base64 -d` | Скопируйте актуальный Secret из GitLab Application и обновите `argocd-secret` через patch или SOPS. |
| Группы отсутствуют (`Groups: []` в выводе `argocd account get`) | 1. В GitLab Application не выдан scope `read_user`.<br>2. Пользователь не состоит в группах.<br>3. Группа приватная и токен приложения не имеет к ней доступа. | 1. Проверьте scopes в настройках GitLab Application.<br>2. Запустите curl от имени полученного токена к `/api/v4/groups`. | Добавьте scope `read_user` в GitLab Application. Если в `dex.config` задан список `groups: [...]`, убедитесь, что целевые группы включены в whitelist. |
| `HTTP 431 Request Header Fields Too Large` / `502 Bad Gateway` | Пользователь состоит в >50 группах GitLab; суммарный размер заголовка `Cookie` и ID Token превысил буфер Ingress | Ошибка `431` в браузере или `upstream sent too big header` в логах NGINX Ingress | 1. Увеличьте `proxy-buffer-size: "128k"` в аннотациях Ingress.<br>2. Ограничьте размер токена с помощью фильтрации `groups: [...]` в `dex.config`. |
| Пользователь входит, но получает ошибку доступа (`Permission Denied`) | Несовпадение имен групп в `argocd-rbac-cm` (`policy.csv`) с реальными клеймами токена (разница в регистре или неполный путь) | Выполните `argocd account get` под проблемным пользователем и изучите поле `Groups` | Исправьте `policy.csv`. Пути должны быть полными: `infrastructure/kubernetes`, а не просто `kubernetes`. Учитывайте суффикс `:maintainer`, если включен `getGroupsPermission: true`. |
| `argocd-dex-server` в статусе `CrashLoopBackOff` | Синтаксическая ошибка в блоке `dex.config` (неправильный отступ YAML, использование табуляций вместо пробелов) | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server` выдает `error parsing config file` | Проверьте YAML валидатором (`yq`). Исправьте отступы в `ConfigMap` `argocd-cm`. |
| Ошибка соединения `dial tcp ...:5556: connect: connection refused` | `argocd-server` не может достучаться до `argocd-dex-server` из-за правил NetworkPolicy или сбоя Service | `kubectl exec -n argocd deploy/argocd-server -- nc -zv argocd-dex-server 5556` | Проверьте Service `argocd-dex-server` в namespace `argocd` и сетевые политики NetworkPolicy, блокирующие внутренний трафик. |
| Изменения прав в GitLab не применяются у пользователя | Dex кэширует сессию, а `argocd-server` использует действующий JWT-токен до истечения его TTL | `users.session.duration` по умолчанию составляет 24 часа | Пользователь должен выполнить явный логаут в UI (кнопка Log Out) и войти повторно, либо администратор уменьшает `users.session.duration`. |

---

## Рекомендации и лучшие практики

### Архитектура и отказоустойчивость (SRE)

- **Отказоустойчивость Dex (High Availability):** По умолчанию под `argocd-dex-server` развертывается в единственной реплике с хранилищем сессий in-memory. Для production увеличьте количество реплик до 2 и настройте общее хранилище сессий в Redis:
  ```yaml
  # В dex.config:
  storage:
    type: redis
    config:
      host: argocd-redis:6379
      db: 1
  ```
- **Защита доступности (PDB):** Создайте `PodDisruptionBudget` для `argocd-dex-server` (`minAvailable: 1`), чтобы плановые обновления нод кластера не приводили к недоступности аутентификации инженеров.
- **Мониторинг метрик Dex:** Настройте сбор метрик Prometheus со встроенного порта Dex (порт 5558). Ключевые метрики для алертинга:
  - `dex_oidc_requests_total{status="error"}` — количество неудачных запросов авторизации к IdP.
  - `dex_grpc_requests_total{grpc_code!="OK"}` — сбои межкомпонентного взаимодействия между `argocd-server` и Dex.

### Практики безопасности (SecOps & Sysadmin)

- **Аварийный доступ (Break-Glass Account):** Не удаляйте локального пользователя `admin` полностью. Задайте ему сложный 32-значный случайный пароль, сохраните его в корпоративном Vault и активируйте только в случае аварийной недоступности GitLab/Dex:
  ```yaml
  # В argocd-cm для production:
  admin.enabled: "false" # Включайте временно при падении IdP
  ```
- **Принцип наименьших привилегий (Least Privilege):** Никогда не устанавливайте `policy.default: role:admin`. Дефолтным значением всегда должно быть `role:readonly` либо полное отсутствие прав (пользователь без маппинга группы не видит ни одного приложения).
- **Минимальный набор Scopes:** Ограничьте запрашиваемые у GitLab области доступа только необходимыми: `openid`, `profile`, `email`, `read_user`. Никогда не выдавайте scope `api` (полный доступ к GitLab API с правами записи).
- **Своевременная ротация секретов:** Внедрите регламент ротации OAuth Client Secret (каждые 90–180 дней). Процедура выполняется без простоя: генерация второго секрета в GitLab Application → обновление `argocd-secret` → перезапуск `argocd-dex-server`.
- **Аудит входов в систему:** Настройте экспорт логов `argocd-server` и `argocd-dex-server` в централизованную систему сбора логов (Elasticsearch / OpenSearch / Loki). Логируйте события `successful login` и `authentication failure` с фиксацией IP-адресов и email.

---

## Ограничения и граничные случаи

1. **Ограничение на размер заголовков и OIDC-токена:** Если инженер состоит более чем в 80–100 группах GitLab, размер ID Token превысит стандартный лимит HTTP-заголовков (4–8 KB). Решение: обязательное использование директивы `groups: [...]` (whitelist) в `dex.config`, которая отсекает посторонние группы на этапе формирования токена.
2. **Задержка отзыва прав при блокировке пользователя:** При увольнении сотрудника или удалении его из группы GitLab активный токен сессии Argo CD остается валидным до истечения срока `users.session.duration` (до 24 часов). Для немедленного отзыва доступа выполните сброс сессий в Redis либо уменьшите `users.session.duration` до `4h`–`8h`.
3. **Регистрозависимость подгрупп GitLab:** GitLab допускает создание групп с заглавными буквами в отображаемом имени, но в системных путях нормализует их к нижнему регистру (slug). При сопоставлении в Casbin используйте именно URL-путь группы: если URL группы `https://gitlab.example.com/Infra-Core/K8s`, то в `policy.csv` указывается `infra-core/k8s`.
4. **Сервисные аккаунты и автоматизация CI/CD:** Попытка использовать SSO для пайплайнов GitLab CI — частая архитектурная ошибка. OIDC Authorization Code Flow требует браузера и интерактивного входа человека. Для автоматизации CI/CD используйте локальные сервисные аккаунты Argo CD (`argocd account create <bot-name>`) с долгоживущими JWT API токенами или короткоживущими проектными токенами AppProject.
5. **Влияние `useLoginAsID`:** По умолчанию (`useLoginAsID: false`) клейм `sub` формируется из внутреннего числового ID пользователя в GitLab. Если включить `useLoginAsID: true`, идентификатором станет логин пользователя. Помните: если пользователь изменит свой username в GitLab, Argo CD воспримет его как нового пользователя с потерей персональных настроек.

---

## Дополнительная информация

### Использование нескольких провайдеров в Dex

Dex позволяет одновременно поддерживать несколько коннекторов, что актуально для сред с разделением между штатными сотрудниками и подрядчиками:

```yaml
dex.config: |
  connectors:
    - type: gitlab
      id: gitlab-corp
      name: GitLab Corporate
      config:
        baseURL: https://gitlab.example.com
        clientID: "corp_client_id"
        clientSecret: $gitlab.clientSecret
        redirectURI: https://argocd.example.com/api/dex/callback
        getGroupsPermission: true

    - type: ldap
      id: ldap-corp
      name: Active Directory
      config:
        host: ldap.example.com:636
        insecureNoSSL: false
        bindDN: "cn=argocd,ou=services,dc=example,dc=com"
        bindPW: $ldap.bindPW
        userSearch:
          baseDN: "ou=users,dc=example,dc=com"
          filter: "(sAMAccountName={{login}})"
          username: sAMAccountName
          idAttr: sAMAccountName
          emailAttr: mail
          nameAttr: displayName
```

### См. также

- [Argo CD: RBAC — модель доступа Casbin, policy.csv и проектные роли](./argocd_rbac_deep.md) — Исчерпывающее руководство по Casbin, гранулярным правам и синтаксису политик.
- [Argo CD: AppProject — изоляция проектов](./argocd_appproject_deep.md) — Настройка мультитенантности, локальных проектных ролей и ограничений репозиториев.
- [Argo CD: Установка и настройка HA](./argocd_installation_and_setup.md) — Развертывание отказоустойчивой инфраструктуры Argo CD в Kubernetes.
- [Безопасность и харденинг Argo CD](./argocd_security_hardening.md) — Сетевые политики NetworkPolicy, mTLS, защита секретов и харденинг подов.
- [Мультитенантность в Argo CD](./argocd_multi_tenancy.md) — Стратегии разделения команд, сред и кластеров.
- [Диагностика и мониторинг Argo CD](./argocd_troubleshooting_and_monitoring.md) — Мониторинг Prometheus, метрики Dex и решение эксплуатационных проблем.
- [Автоматизация через API и CLI](./argocd_api_automation.md) — Генерация токенов сервисных аккаунтов для CI/CD без использования браузерного SSO.

### Официальные ресурсы

- [Документация Argo CD — Управление пользователями и SSO](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/)
- [Спецификация коннектора Dex GitLab](https://dexidp.io/docs/connectors/gitlab/)
- [Руководство по Casbin RBAC в Argo CD](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)
- [Документация GitLab — OAuth 2.0 Identity Provider](https://docs.gitlab.com/ee/integration/oauth_provider.html)
