# Argo CD: RBAC — модель доступа Casbin, policy.csv и проектные роли

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Kubernetes 1.28–1.32+; bare-metal / on-premise; Casbin-модель, granular sub-resource actions, AppProject scoped roles, policy.matchMode glob/regex)

## Предварительные требования

Перед развертыванием и конфигурированием ролевой модели доступа (RBAC) в Argo CD убедитесь в соблюдении следующих условий:

1. **Кластер Kubernetes:** версия v1.28–v1.32+ (on-premise, bare-metal или виртуализированный кластер под управлением kubeadm/talos/rke2).
2. **Работоспособный инстанс Argo CD:** версии v3.5.x (проверено на v3.5.0–v3.5.4+):
   ```bash
   kubectl get pods -n argocd -l app.kubernetes.io/part-of=argocd
   # → argocd-application-controller-0   1/1     Running   0          42d
   # → argocd-repo-server-xxx           1/1     Running   0          42d
   # → argocd-server-xxx                1/1     Running   0          42d
   ```
3. **Административный доступ к кластеру:** права `ClusterRoleBinding` с `cluster-admin` или полные права на чтение/запись ресурсов `ConfigMap` и `AppProject` в пространстве имен `argocd`.
4. **Утилиты командной строки (CLI):**
   - `kubectl` v1.28+ с настроенным `KUBECONFIG`.
   - `argocd` CLI v3.5+, авторизованный под учетной записью администратора:
     ```bash
     argocd version --short
     # → argocd: v3.5.4+2b47f48
     # → argocd-server: v3.5.4+2b47f48
     ```
   - Утилиты для работы с данными: `jq`, `base64`, `openssl`, `yq`.
5. **Корпоративный IdP / SSO (опционально, но рекомендуется для production):** настроенный поставщик OIDC/LDAP (Keycloak, GitLab, FreeIPA, Dex) с передачей клейма групп `groups` (см. [SSO с GitLab](./argocd_sso_gitlab.md)).
6. **Базовое понимание сущностей:** архитектура проектов [AppProject](./argocd_appproject_deep.md) и стратегия разграничения сред [Мультитенантность](./argocd_multi_tenancy.md).

---

## Определения

| Термин | Определение |
| :--- | :--- |
| **RBAC (Role-Based Access Control)** | Механизм разграничения прав доступа субъектов (пользователей, сервисных учетных записей, групп SSO) к ресурсам и операциям API/UI Argo CD. |
| **Casbin Engine** | Встроенный в Argo CD открытый движок авторизации (`github.com/casbin/casbin/v2`), исполняющий оценку правил на базе модели PERM (Policy, Effect, Request, Matchers). |
| **argocd-rbac-cm** | Системный `ConfigMap` в namespace `argocd`, хранящий глобальную конфигурацию RBAC: файл правил `policy.csv`, дефолтную роль `policy.default`, режим сопоставления `policy.matchMode` и перечень OIDC scopes `scopes`. |
| **policy.csv** | Многострочный CSV-текст с определениями политик (`p`) и связей субъектов с ролями (`g`), загружаемый и парсируемый Casbin-энфорсером. |
| **policy.default** | Имя роли, которая автоматически назначается любому аутентифицированному пользователю (а также анонимным сессиям, если они включены). По стандарту безопасности устанавливается в `role:readonly`. |
| **policy.matchMode** | Режим работы функции сопоставления объектов и действий в Casbin: `glob` (по умолчанию, подстановка `*`) либо `regex` (регулярные выражения синтаксиса Go). |
| **Role (`role:<name>`)** | Именованный контейнер привилегий. Имена глобальных ролей всегда начинаются с префикса `role:` (например, `role:readonly`, `role:developer`, `role:sre`). |
| **Subject (`sub`)** | Субъект авторизации — имя локального пользователя, уникальный ID пользователя OIDC или название внешней группы из SSO-токена. |
| **AppProject Scoped Role** | Локальная роль, определенная внутри CRD `AppProject` в массиве `.spec.roles[]`. Пространство имен роли в Casbin автоматически формируется как `proj:<project-name>:<role-name>`. |
| **Fine-grained Sub-resource Action** | Гранулярное действие над дочерними Kubernetes-ресурсами приложения в формате `<action>/<group>/<kind>/<namespace>/<name>` (например, `action/apps/Deployment/restart`, `delete/*/Pod/*/*`). |
| **Scopes (`scopes`)** | Список OIDC-клеймов, извлекаемых из токена IdP для наполнения списка групп пользователя (по умолчанию `[groups]`). |
| **JWT Token** | Подписанный JSON Web Token, удостоверяющий личность пользователя или сервисного аккаунта при обращении к REST/gRPC API. Содержит метаданные `sub`, `iss`, `iat`, `exp` и `id`. |

---

## Архитектура и принципы работы Casbin

### Конвейер авторизации (Defense-in-Depth)

При любом обращении к API Argo CD (через веб-интерфейс, утилиту `argocd` или автоматизированный REST/gRPC-клиент) запрос проходит трехступенчатый конвейер проверки:

```text
Входящий запрос (UI / CLI / REST / gRPC API)
   │
   ▼
[Уровень 1: Аутентификация (Authentication)]
   │ • Проверка валидности сессионной cookie или заголовка Authorization: Bearer <JWT>
   │ • Верификация подписи токена (локальный secretkey или OIDC IdP JWKS)
   │ • Извлечение идентификатора субъекта (sub) и списка групп (groups)
   ▼
[Уровень 2: Глобальный и проектный RBAC (Casbin Enforcer)]
   │ • Оценка запроса по модели Casbin: r = (sub, res, act, obj)
   │ • Поиск связок в g (группы пользователя -> роли)
   │ • Применение политик p (argocd-rbac-cm + AppProject spec.roles)
   │ • Проверка policy.default
   │ • Вычисление эффекта: allow && !deny
   ▼
[Уровень 3: Границы безопасности AppProject (Security Boundaries)]
   │ • Проверка допустимости репозитория манифестов (spec.sourceRepos)
   │ • Проверка целевого кластера и пространства имен (spec.destinations)
   │ • Проверка разрешенных типов манифестов (whitelists / blacklists)
   │ • Проверка активных регламентных окон синхронизации (spec.syncWindows)
   ▼
Исполнение операции (argocd-server / argocd-application-controller)
```

### Спецификация Casbin-модели Argo CD

Ядро авторизации Argo CD инициализируется встроенным файлом конфигурации модели (`assets/model.conf`):

```text
[request_definition]
r = sub, res, act, obj

[policy_definition]
p = sub, res, act, obj, eft

[role_definition]
g = _, _

[policy_effect]
e = some(where (p.eft == allow)) && !some(where (p.eft == deny))

[matchers]
m = g(r.sub, p.sub) && globOrRegexMatch(r.res, p.res) && globOrRegexMatch(r.act, p.act) && globOrRegexMatch(r.obj, p.obj)
```

#### Математический принцип вычисления прав (Policy Effect)

Формула эффекта:
$$\text{Effect} = \exists (p.\text{eft} == \text{allow}) \land \neg \exists (p.\text{eft} == \text{deny})$$

Из формулы следуют критические правила для системного администратора:
1. **Безусловный приоритет запрета (Deny-Override):** Если для запрошенного действия совпало хотя бы одно правило со значением `deny`, запрос **немедленно отклоняется**, даже если на него распространяются десять разрешающих правил `allow`.
2. **Независимость от порядка строк в CSV:** В отличие от сетевых брандмауэров (где действует правило «first match wins»), в Casbin **порядок строк в `policy.csv` не имеет значения**. Размещение `allow` выше строки с `deny` не способно обойти запрещающее правило.
3. **Модель закрытого мира (Default Deny):** Если для субъекта не найдено ни одного правила `allow` (ни в назначенных ролях, ни в `policy.default`), запрос отклоняется с ошибкой `permission denied`.
4. **Неблокируемость дефолтной роли:** Правила, выданные через `policy.default` (например, `role:readonly`), применяются ко всем аутентифицированным пользователям. Попытка заблокировать дефолтное право через `deny` для кастомной роли заблокирует только саму эту роль, но если пользователь сохраняет членство в `policy.default`, базовое разрешение может сохраняться.

### Синтаксис policy.csv

Файл конфигурации содержит строки двух типов (комментарии начинаются с `#` и игнорируются парсером):

#### 1. Правило политики (`p`):
```csv
p, <subject/role>, <resource>, <action>, <object>, <allow|deny>
```
- `<subject/role>`: Роль (например, `role:dev-team`, `proj:payment:developer`) или прямой идентификатор пользователя/группы.
- `<resource>`: Тип системного ресурса Argo CD.
- `<action>`: Допустимая операция над ресурсом (включая составные подресурсы).
- `<object>`: Идентификатор объекта (маска или точный путь).
- `<allow|deny>`: Эффект правила (`allow` — разрешить, `deny` — явно запретить).

#### 2. Маппинг групп и пользователей (`g`):
```csv
g, <subject>, <role>
```
- `<subject>`: Имя пользователя (локального или SSO) либо группа, полученная из OIDC-клейма.
- `<role>`: Назначенная роль с префиксом `role:` (для глобальных ролей) или `proj:<project>:<role>` (для проектных ролей).

### Полная матрица ресурсов и действий

Argo CD v3.5+ поддерживает 12 типов системных ресурсов и 9 базовых действий:

| Ресурс (`resource`) | Допустимые действия (`action`) | Область объекта (`object`) | Назначение и контекст |
| :--- | :--- | :--- | :--- |
| `applications` | `get`, `create`, `update`, `delete`, `sync`, `rollback`, `action`, `override` | `<project>/<app>` или `<project>/<app-ns>/<app>` | Жизненный цикл приложений, синхронизация манифестов, откат ревизий. |
| `applicationsets` | `get`, `create`, `update`, `delete` | `<project>/<appset>` | Управление генераторами приложений ApplicationSet (v3.5+). |
| `clusters` | `get`, `create`, `update`, `delete` | `<server-url>` или `<name>` | Подключение и управление целевыми Kubernetes-кластерами. |
| `projects` | `get`, `create`, `update`, `delete` | `<project-name>` | Управление объектами `AppProject` и границами безопасности. |
| `repositories` | `get`, `create`, `update`, `delete` | `<repo-url>` | Управление учетными данными Git-репозиториев и Helm OCI-реестров (read-only доступ). |
| `write-repositories`| `get`, `create`, `update`, `delete` | `<repo-url>` | Управление репозиториями с правом записи (для Image Updater, commit-back). |
| `accounts` | `get`, `update` | `<account-name>` | Просмотр аккаунтов, смена паролей, генерация и отзыв API-токенов. |
| `certificates` | `get`, `create`, `delete` | `<server-name>` | Управление доверенными TLS/SSH-сертификатами хостов. |
| `gpgkeys` | `get`, `create`, `delete` | `<key-id>` | Управление публичными GPG-ключами для верификации подписей коммитов Git. |
| `logs` | `get` | `<project>/<app>` | Потоковое чтение логов контейнеров через API Argo CD. |
| `exec` | `create` | `<project>/<app>` | Открытие интерактивной терминальной сессии (web-shell / pod exec). |
| `extensions` | `invoke` | `<extension-name>` | Вызов расширений UI/бэкенда (Argo CD Extensions). |

#### Специфика действия `override`
Действие `override` на ресурсе `applications` наделяет пользователя правом принудительной синхронизации в обход ограничений:
- Использование флагов `--force` и `--replace` (удаление и пересоздание конфликтующих ресурсов).
- Отключение автоматической подчистки манифестов (`--prune=false`).
- Применение Server-Side Apply при наличии конфликтов владения полями (`managedFieldsManagers`).
По умолчанию `override` доступен **только** роли `role:admin`.

### Гранулярные действия подресурсов (Fine-grained Permissions)

Для ресурса `applications` действие может быть уточнено до конкретного Kubernetes-манифеста внутри целевого кластера:

```csv
p, <role>, applications, <action>/<group>/<kind>/<namespace>/<name>, <project>/<app>, allow
```

- **Вызов действий контроллера (Resource Actions):**
  `p, role:developer, applications, action/apps/Deployment/restart, team-backend/*, allow` — разрешает только операцию перезапуска деплойментов (`Restart`).
- **Удаление конкретных сущностей:**
  `p, role:developer, applications, delete/*/Pod/*/*, team-backend/*, allow` — разрешает удаление подов (для отладки/перезапуска), но запрещает удаление сервисов, ingress и самого приложения `Application`.
- **Обновление дочерних ресурсов:**
  `p, role:developer, applications, update/*, team-backend/*, allow` — разрешает прямое редактирование манифестов подов/деплойментов через UI, но запрещает редактировать спецификацию самого `Application` (например, подменять Git-репозиторий).

### Маски объектов и режим сопоставления (`policy.matchMode`)

Конфигурация `policy.matchMode` в `argocd-rbac-cm` определяет функцию сопоставления строк:

#### 1. Режим `glob` (по умолчанию)
Использует функцию сопоставления glob-паттернов.
> [!WARNING]
> Встроенная функция сопоставления glob в Casbin **не рассматривает символ слэша (`/`) как специальный разделитель директорий**. Маска `delete/*/kind/*` совпадет как с `delete/<group>/kind/<namespace>/<name>`, так и с `delete/<group>/<kind>/kind/<name>`. Для однозначного разделения групп всегда используйте паттерны с 4 слэшами: `delete/<group>/<kind>/<namespace>/<name>`.

- `*/*` — все проекты, все приложения.
- `payment-proj/*` — любые приложения внутри проекта `payment-proj`.
- `payment-proj/billing-*` — приложения проекта, чьи имена начинаются с `billing-`.
- `*/app-payment` — приложение с именем `app-payment` в любом проекте.
- `payment-proj/team-ns/*` — все приложения в неймспейсе `team-ns` (при включенном режиме *Applications in any namespace*).

#### 2. Режим `regex`
Включается параметром `policy.matchMode: regex` в `argocd-rbac-cm`. Все объекты, ресурсы и субъекты сопоставляются по правилам регулярных выражений языка Go:
```yaml
data:
  policy.matchMode: regex
  policy.csv: |
    # Разрешить чтение только для проектов, начинающихся с prod-
    p, role:auditor, applications, get, ^prod-.*/.*$, allow
```

---

## Практические сценарии конфигурации

### Сценарий 1: Базовый Hardening — Least Privilege и отключение Anonymous

В корпоративной среде доступ по умолчанию должен предоставлять минимальные права только на чтение, а анонимный доступ должен быть гарантированно отключен.

#### 1. Конфигурация `argocd-cm` (отключение анонимного доступа)
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Запрет неавторизованного доступа
  users.anonymous.enabled: "false"
  # Стандартное время жизни сессионного токена (8 часов для рабочего дня)
  users.session.duration: "8h"
```

#### 2. Конфигурация `argocd-rbac-cm`
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  # Дефолтная роль для всех аутентифицированных пользователей
  policy.default: role:readonly
  policy.matchMode: glob
  scopes: "[groups]"
  policy.csv: |
    # Явное закрепление прав встроенной роли readonly
    p, role:readonly, applications, get, */*, allow
    p, role:readonly, certificates, get, *, allow
    p, role:readonly, clusters, get, *, allow
    p, role:readonly, repositories, get, *, allow
    p, role:readonly, projects, get, *, allow
    p, role:readonly, accounts, get, *, allow
```

#### 3. Валидация применения
```bash
# Проверка синтаксической корректности политик
argocd admin settings rbac validate
# → RBAC configuration is valid

# Тестирование дефолтных прав на чтение
argocd admin settings rbac can role:readonly get applications 'default/core-service'
# → Yes

# Проверка запрета деструктивных операций
argocd admin settings rbac can role:readonly delete applications 'default/core-service'
# → No
```

---

### Сценарий 2: Многопользовательское разделение команд (Developers vs SRE vs Security)

Разграничение обязанностей для классической структуры IT-департамента без использования облачных IAM.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    # =========================================================================
    # РОЛЬ: role:developer (Разработчики сервисов)
    # Полный доступ к dev/stage, чтение и синхронизация в prod (без удаления)
    # =========================================================================
    p, role:developer, applications, get, staging-*/*, allow
    p, role:developer, applications, create, staging-*/*, allow
    p, role:developer, applications, update, staging-*/*, allow
    p, role:developer, applications, sync, staging-*/*, allow
    p, role:developer, applications, delete, staging-*/*, allow
    p, role:developer, applications, rollback, staging-*/*, allow
    p, role:developer, logs, get, staging-*/*, allow
    p, role:developer, exec, create, staging-*/*, allow

    # Production: просмотр, запуск синхронизации и просмотр логов
    p, role:developer, applications, get, production-*/*, allow
    p, role:developer, applications, sync, production-*/*, allow
    p, role:developer, logs, get, production-*/*, allow
    # Запрет терминала и удаления в production
    p, role:developer, exec, create, production-*/*, deny
    p, role:developer, applications, delete, production-*/*, deny

    # =========================================================================
    # РОЛЬ: role:sre (Дежурные инженеры эксплуатации)
    # Полный доступ к приложениям, логам и терминалам, управление кластерами
    # =========================================================================
    p, role:sre, applications, *, */*, allow
    p, role:sre, logs, get, */*, allow
    p, role:sre, exec, create, */*, allow
    p, role:sre, clusters, get, *, allow
    p, role:sre, repositories, *, *, allow
    p, role:sre, certificates, *, *, allow

    # =========================================================================
    # РОЛЬ: role:sec-auditor (Аудит информационной безопасности)
    # Только чтение логов, манифестов и ключей верификации
    # =========================================================================
    p, role:sec-auditor, applications, get, */*, allow
    p, role:sec-auditor, logs, get, */*, allow
    p, role:sec-auditor, gpgkeys, get, *, allow
    p, role:sec-auditor, certificates, get, *, allow

    # =========================================================================
    # МАППИНГ ЛОКАЛЬНЫХ ПОЛЬЗОВАТЕЛЕЙ И ГРУПП
    # =========================================================================
    g, lead-developer, role:developer
    g, oncall-sre, role:sre
    g, audit-officer, role:sec-auditor
```

#### Валидация прав
```bash
# Проверка прав разработчика в staging
argocd admin settings rbac can role:developer delete applications 'staging-shop/frontend'
# → Yes

# Проверка запрета разработчика на удаление в production
argocd admin settings rbac can role:developer delete applications 'production-shop/frontend'
# → No

# Проверка запрета запуска exec в production
argocd admin settings rbac can role:developer create exec 'production-shop/frontend'
# → No
```

---

### Сценарий 3: Fine-grained права на подресурсы Kubernetes

Предоставление разработчикам возможности перезапускать поды и деплойменты в production без права редактировать спецификации или удалять манифесты.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    # Базовое чтение приложений
    p, role:prod-operator, applications, get, production/*, allow
    
    # Разрешить вызов restart для Deployment
    p, role:prod-operator, applications, action/apps/Deployment/restart, production/*, allow
    
    # Разрешить удаление конкретных Pods для аварийного перезапуска
    p, role:prod-operator, applications, delete/*/Pod/*/*, production/*, allow
    
    # Запретить любые другие деструктивные операции над приложением и ресурсами
    p, role:prod-operator, applications, delete, production/*, deny
    p, role:prod-operator, applications, update, production/*, deny
    
    g, "prod-support-group", role:prod-operator
```

#### Валидация команды в CLI
```bash
# Проверка права на restart деплоймента
argocd admin settings rbac can role:prod-operator action/apps/Deployment/restart applications 'production/billing'
# → Yes

# Проверка права на удаление Pod
argocd admin settings rbac can role:prod-operator delete/*/Pod/*/* applications 'production/billing'
# → Yes

# Проверка запрета удаления самого приложения
argocd admin settings rbac can role:prod-operator delete applications 'production/billing'
# → No
```

---

### Сценарий 4: Делегирование прав через AppProject-роли (Production Pattern)

В крупных инсталляциях редактирование единого `argocd-rbac-cm` приводит к конфликтам в GitOps-репозиториях платформы. Рекомендуемый шаблон — описание ролей внутри самого CRD `AppProject`.

#### Манифест `AppProject` с локальными ролями
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-billing
  namespace: argocd
spec:
  description: "Проект микросервисов биллинга и платежей"
  sourceRepos:
    - "https://git.internal.corp/billing/*"
  destinations:
    - namespace: "billing-prod"
      server: "https://kubernetes.default.svc"
  clusterResourceWhitelist: []
  namespaceResourceWhitelist:
    - group: "apps"
      kind: "Deployment"
    - group: ""
      kind: "Service"
    - group: ""
      kind: "ConfigMap"
  # Локальные роли проекта
  roles:
    # 1. Роль для CI/CD автоматизации с scoped JWT-токеном
    - name: cicd-deployer
      description: "Пайплайн деплоя биллинга (GitLab CI runner)"
      policies:
        - p, proj:team-billing:cicd-deployer, applications, get, team-billing/*, allow
        - p, proj:team-billing:cicd-deployer, applications, sync, team-billing/*, allow
        - p, proj:team-billing:cicd-deployer, applications, override, team-billing/*, allow
      jwtTokens: []

    # 2. Роль для разработчиков, привязанная к группе OIDC
    - name: developer
      description: "Команда разработки биллинга"
      policies:
        - p, proj:team-billing:developer, applications, get, team-billing/*, allow
        - p, proj:team-billing:developer, applications, sync, team-billing/*, allow
        - p, proj:team-billing:developer, logs, get, team-billing/*, allow
        - p, proj:team-billing:developer, applications, action/apps/Deployment/restart, team-billing/*, allow
      groups:
        - "internal-gitlab/billing/developers"
```

#### Генерация scoped JWT-токена для роли проекта через CLI
```bash
# Выпуск токена с временем жизни 90 дней (2160 часов)
argocd proj role create-token team-billing cicd-deployer --expires-in 2160h
# → eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjE3MzU2ODk2MDAiLCJpc3MiOiJhcmdvY2QiLCJuYmYiOjE3MzU2ODk2MDAsInN1YiI6InByb2o6dGVhbS1iaWxsaW5nOmNpY2QtZGVwbG95ZXIifQ...

# Просмотр активных токенов роли проекта
argocd proj role list-tokens team-billing cicd-deployer
# → ID           ISSUED AT              EXPIRES AT
# → 1735689600   2026-10-12T14:40:00Z   2027-01-10T14:40:00Z

# Тестирование прав токена
argocd admin settings rbac can proj:team-billing:cicd-deployer sync applications 'team-billing/billing-api'
# → Yes

argocd admin settings rbac can proj:team-billing:cicd-deployer sync applications 'other-team/payment-api'
# → No
```

---

### Сценарий 5: Сервисные аккаунты автоматизации в `argocd-cm`

Создание статических системных учетных записей для bash-скриптов, мониторинга и интеграций.

#### 1. Декларация аккаунта в `argocd-cm`
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  # Создание аккаунта prometheus-scraper с возможностью генерации API-ключей
  accounts.prometheus-scraper: apiKey
  accounts.gitlab-ci-bot: apiKey,login
```

#### 2. Назначение прав в `argocd-rbac-cm`
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.csv: |
    # Прометею нужно только читать статус приложений
    p, role:metrics-reader, applications, get, */*, allow
    g, prometheus-scraper, role:metrics-reader

    # CI-боту нужны права на синхронизацию
    p, role:global-ci, applications, get, */*, allow
    p, role:global-ci, applications, sync, */*, allow
    g, gitlab-ci-bot, role:global-ci
```

#### 3. Генерация токена аккаунта и проверка
```bash
# Генерация API-токена для prometheus-scraper на 1 год
argocd account generate-token --account prometheus-scraper --expires-in 8760h
# → eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Запрос статуса через REST API от имени сервисного аккаунта
curl -s -k -H "Authorization: Bearer <TOKEN>" \
  https://argocd.internal.corp/api/v1/applications | jq '.items[].metadata.name'
# → "billing-service"
# → "payment-service"
```

---

### Сценарий 6: Интеграция корпоративного OIDC/LDAP (Keycloak / GitLab)

Сопоставление групп из корпоративного каталога на локальные роли Argo CD с учетом вложенности и путей.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  # Указываем claim из токена IdP (Keycloak или GitLab Dex)
  scopes: "[groups, email]"
  policy.csv: |
    # =========================================================================
    # МАППИНГ КОРПОРАТИВНЫХ ГРУПП (Keycloak / FreeIPA / GitLab)
    # Внимание: чувствительно к регистру и полным путям групп!
    # =========================================================================
    g, "infra-admins", role:admin
    g, "sec-ops/audit", role:sec-auditor
    g, "development/frontend-team", role:frontend-dev
    g, "development/backend-team", role:backend-dev

    # Политики для проектных групп
    p, role:frontend-dev, applications, *, frontend-apps/*, allow
    p, role:frontend-dev, logs, get, frontend-apps/*, allow
    p, role:backend-dev, applications, *, backend-apps/*, allow
    p, role:backend-dev, logs, get, backend-apps/*, allow
```

#### Проверка групп после авторизации через UI/CLI
```bash
# Проверка пользователя, вошедшего через OIDC
argocd account get-user-info
# → Logged In: true
# → Name: ivan.ivanov
# → Groups: [development/backend-team, internal-users]
# → Iss: https://keycloak.internal.corp/realms/production

# Проверка доступности операции для текущего вошедшего пользователя
argocd account can-i sync applications 'backend-apps/api-gateway'
# → Yes

argocd account can-i sync applications 'frontend-apps/web-portal'
# → No
```

---

### Сценарий 7: RBAC для ApplicationSet и Applications in any namespace

В кластерах с мультитенантной структурой ApplicationSet может порождать приложения во внешних пространствах имен. Создание ApplicationSet дает возможность массового изменения инфраструктуры, поэтому доступ к ресурсу `applicationsets` строго ограничивается.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.csv: |
    # Разрешить платформенным инженерам полный цикл управления генераторами
    p, role:platform-admin, applicationsets, *, */*, allow
    
    # Разработчикам разрешить только просмотр генераторов своего проекта
    p, role:developer, applicationsets, get, team-billing/*, allow
    p, role:developer, applicationsets, create, team-billing/*, deny
    p, role:developer, applicationsets, delete, team-billing/*, deny

    # Правило для Applications in any namespace: <project>/<app-namespace>/<app-name>
    p, role:developer, applications, sync, team-billing/billing-apps/*, allow
```

#### Валидация прав
```bash
# Проверка запрета создания генератора для разработчика
argocd admin settings rbac can role:developer create applicationsets 'team-billing/customer-appset'
# → No

# Проверка права платформенного инженера
argocd admin settings rbac can role:platform-admin create applicationsets '*/*'
# → Yes
```

---

### Сценарий 8: Pre-commit валидация и CI/CD тестирование политик (Оффлайн-режим)

Для предотвращения деградации доступа перед мерджем изменений в Git-репозиторий платформы политики Casbin должны тестироваться в изолированном CI runner без прямого доступа к API Kubernetes.

#### Файл локального тестирования `policy-test.csv`
```csv
p, role:test-role, applications, sync, test-proj/my-app, allow
p, role:test-role, applications, delete, test-proj/my-app, deny
g, test-user, role:test-role
```

#### Команды оффлайн-валидации в скрипте пайплайна
```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Синтаксическая валидация локального файла политик
argocd admin settings rbac validate --policy-file=./policy-test.csv
# → RBAC configuration is valid

# 2. Оффлайн-проверка разрешения sync
RES_SYNC=$(argocd admin settings rbac can role:test-role sync applications 'test-proj/my-app' --policy-file=./policy-test.csv)
if [ "$RES_SYNC" != "Yes" ]; then
  echo "ERROR: Expected sync to be allowed" && exit 1
fi

# 3. Оффлайн-проверка запрета delete
RES_DEL=$(argocd admin settings rbac can role:test-role delete applications 'test-proj/my-app' --policy-file=./policy-test.csv)
if [ "$RES_DEL" != "No" ]; then
  echo "ERROR: Expected delete to be denied" && exit 1
fi

echo "All RBAC pre-commit assertions passed successfully."
# → All RBAC pre-commit assertions passed successfully.
```

---

## Операции и команды управления (CLI Cheatsheet)

Сводная таблица команд администратора и оператора для управления доступом:

| Команда | Описание операции | Пример использования | Ожидаемый результат |
| :--- | :--- | :--- | :--- |
| `argocd admin settings rbac validate` | Проверка синтаксиса `argocd-rbac-cm` в кластере | `argocd admin settings rbac validate` | `RBAC configuration is valid` |
| `argocd admin settings rbac validate --policy-file` | Оффлайн-проверка синтаксиса локального CSV | `argocd admin settings rbac validate --policy-file=./policy.csv` | `RBAC configuration is valid` |
| `argocd admin settings rbac can` | Симуляция разрешения для роли/субъекта | `argocd admin settings rbac can role:dev sync applications 'dev/*'` | `Yes` или `No` |
| `argocd account can-i` | Проверка прав текущего вошедшего пользователя | `argocd account can-i sync applications 'billing/api'` | `Yes` или `No` |
| `argocd account get-user-info` | Вывод сведений о текущей сессии и группах | `argocd account get-user-info` | Таблица с `Name`, `Groups`, `Issuer` |
| `argocd account list` | Список локальных учетных записей | `argocd account list` | Имя, статус (enabled), capabilities |
| `argocd account generate-token` | Выпуск JWT для сервисного аккаунта | `argocd account generate-token --account ci-bot --expires-in 720h` | Строка JWT-токена |
| `argocd account revoke-token` | Отзыв JWT-токена по ID | `argocd account revoke-token --account ci-bot --token-id 1735689600` | `Token revoked` |
| `argocd proj role list` | Список ролей внутри AppProject | `argocd proj role list team-billing` | Список локальных ролей проекта |
| `argocd proj role create-token` | Выпуск JWT для проектной роли | `argocd proj role create-token team-billing deployer -e 720h` | Строка JWT-токена |
| `argocd proj role delete-token` | Удаление JWT-токена роли проекта | `argocd proj role delete-token team-billing deployer 1735689600` | `Token deleted` |
| `argocd proj role add-policy` | Добавление правила `p` в роль проекта | `argocd proj role add-policy team-billing deployer -a sync -o 'team-billing/*'` | `Role policy added` |

---

## Мониторинг, логирование и аудит RBAC (SRE)

### Включение расширенного аудита решений

По умолчанию `argocd-server` не регистрирует успешные проверки RBAC в стандартный вывод подов во избежание чрезмерного объема логов. Для compliance-аудита и расследования инцидентов безопасности включите детальное логирование в `argocd-cmd-params-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # Активация логирования каждого решения Casbin Enforcer
  server.rbac.log.enforce.enable: "true"
```

Применение конфигурации требует перезапуска `argocd-server`:
```bash
kubectl rollout restart deployment argocd-server -n argocd
# → deployment.apps/argocd-server restarted
```

### Формат логов в argocd-server

Каждая авторизационная проверка формирует JSON/Logrus-запись:
```json
{
  "level": "info",
  "ts": "2026-10-12T14:42:15.123Z",
  "msg": "RBAC decision",
  "sub": "proj:team-billing:cicd-deployer",
  "res": "applications",
  "act": "sync",
  "obj": "team-billing/billing-api",
  "result": "allow"
}
```

При отклонении операции:
```json
{
  "level": "warning",
  "ts": "2026-10-12T14:42:19.456Z",
  "msg": "RBAC decision",
  "sub": "petr.sidorov",
  "res": "applications",
  "act": "delete",
  "obj": "production/payment-gw",
  "result": "deny"
}
```

### Prometheus-метрики Casbin

Компонент `argocd-server` экспортирует встроенные метрики для Prometheus:

- `argocd_rbac_requests_total{result="allow|deny"}` — суммарный счетчик обращений к RBAC с разделением по исходу проверки.

#### Пример PromQL-запроса для SRE-дашборда
```promql
# Доля отклоненных запросов (Deny Rate) за 5 минут:
sum(rate(argocd_rbac_requests_total{result="deny"}[5m])) 
/ 
sum(rate(argocd_rbac_requests_total[5m])) * 100
```

#### SRE AlertRule: Аномальный всплеск ошибок 403 Forbidden
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: argocd-rbac-alerts
  namespace: argocd
spec:
  groups:
    - name: argocd-rbac.rules
      rules:
        - alert: ArgoCDHighRBACDenialRate
          expr: sum(rate(argocd_rbac_requests_total{result="deny"}[5m])) > 5
          for: 2m
          labels:
            severity: warning
            team: platform-security
          annotations:
            summary: "High RBAC authorization failure rate in Argo CD"
            description: "More than 5 RBAC requests per second are being denied. Potential misconfiguration or brute-force access attempt."
```

---

## Валидация и тестирование политик

### 1. Комплексная проверка синтаксиса
```bash
kubectl get configmap argocd-rbac-cm -n argocd -o yaml | argocd admin settings rbac validate
# → RBAC configuration is valid
```

### 2. Тестирование разрешений роли
```bash
# Синтаксис: argocd admin settings rbac can <role> <action> <resource> <object>
argocd admin settings rbac can role:developer sync applications 'development/core'
# → Yes

argocd admin settings rbac can role:developer delete applications 'production/core'
# → No
```

### 3. Тестирование прав роли проекта
```bash
argocd admin settings rbac can proj:team-billing:cicd-deployer sync applications 'team-billing/billing-api'
# → Yes
```

### 4. Тестирование прав текущего пользователя (онлайн)
```bash
argocd account can-i sync applications 'team-billing/billing-api'
# → Yes

argocd account can-i create clusters '*'
# → No
```

### 5. Инспекция claims и времени жизни JWT-токена
```bash
# Извлечение payload токена и форматирование даты истечения
TOKEN="<JWT_TOKEN_STRING>"
echo "$TOKEN" | cut -d. -f2 | base64 -d 2>/dev/null | jq '{sub: .sub, iss: .iss, exp: (.exp | todate)}'
# → {
# →   "sub": "proj:team-billing:cicd-deployer",
# →   "iss": "argocd",
# →   "exp": "2027-01-10T14:40:00Z"
# → }
```

### 6. Проверка параметров ConfigMap
```bash
# Проверка дефолтной роли
kubectl get configmap argocd-rbac-cm -n argocd -o jsonpath='{.data.policy\.default}'
# → role:readonly

# Проверка режима сопоставления
kubectl get configmap argocd-rbac-cm -n argocd -o jsonpath='{.data.policy\.matchMode}'
# → glob

# Проверка OIDC scopes
kubectl get configmap argocd-rbac-cm -n argocd -o jsonpath='{.data.scopes}'
# → [groups]
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Пошаговый SRE-алгоритм локализации `Permission Denied`

```text
Ошибка: Permission denied (в UI, CLI или пайплайне)
   │
   ▼
1. Проверка субъекта: кто выполняет запрос?
   │ Выполнить: argocd account get-user-info
   ├── Имя пустое / 401 Unauthorized?
   │   └── Причина: Проблема аутентификации (токен истёк, SSO-cookie невалидна)
   └── Пользователь определен (например sub: alexey.petrov, groups: [devs])
       │
       ▼
2. Симуляция через админский CLI:
   │ Выполнить: argocd admin settings rbac can <role/group> <act> <res> <obj>
   ├── Результат "No"?
   │   ├── Проверить argocd-rbac-cm: есть ли p, правило со значением allow?
   │   ├── Проверить: нет ли перекрывающего правила deny? (Помните: Deny-Override)
   │   ├── Проверить: точен ли регистр группы в g, маппинге?
   │   └── Проверить AppProject: определена ли роль в spec.roles проекта?
   │
   └── Результат "Yes" (RBAC разрешает, но запрос всё равно блокируется)?
       │
       ▼
3. Проверка ограничений AppProject (Уровень 3):
   │ Выполнить: kubectl get appproject <project-name> -o yaml
   ├── sourceRepos: разрешен ли Git-репозиторий манифестов?
   ├── destinations: разрешен ли целевой cluster/namespace?
   ├── namespaceResourceBlacklist / clusterResourceWhitelist блокируют ресурс?
   └── syncWindows: не заблокирована ли синхронизация активным окном deny?
```

### Расширенная матрица ошибок

| Ошибка / Симптом | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| `permission denied: applications, sync, proj/app` | Отсутствует разрешающее правило `p` или действует явный `deny`. | `argocd admin settings rbac can <role> sync applications 'proj/app'` | Добавить `p, <role>, applications, sync, proj/app, allow` либо устранить перекрывающее правило `deny`. |
| `permission denied` (sync) при наличии `allow` | Сработало общее правило `deny` (например, `p, role:X, applications, delete, *, deny`). Внимание: в Casbin `deny` перекрывает `allow` по всей маске! | Проанализировать все правила с `deny` в `argocd-rbac-cm` и `AppProject`. | Сузить маску `deny` (например, с `*/*` до конкретного приложения) или разделить роли. |
| `groups: []` в выводе `get-user-info` | Поставщик OIDC (Keycloak/GitLab) передает группы в нестандартном claim либо параметр `scopes` не запрашивает группы. | Проверить сырой ID Token через `jwt.io` и ключ `scopes` в `argocd-rbac-cm`. | Указать `scopes: "[groups]"` в `argocd-rbac-cm` и настроить Client Scope / Mappers в IdP. |
| Группы есть, но права роли не применяются | Несоответствие строк в маппинге `g,`: пробелы, слэши, расхождение регистра (`Devs` vs `devs`). | Сравнить точный вывод `argocd account get-user-info` со строками `g,` в `policy.csv`. | Использовать точное строковое совпадение с кавычками: `g, "gitlab/group/subgroup", role:dev`. |
| `permission denied` для подресурса (Restart Deployment) | Не задано правило для granular action (`action/apps/Deployment/restart`). | `argocd admin settings rbac can <role> action/apps/Deployment/restart applications 'proj/app'` | Добавить правило `p, <role>, applications, action/apps/Deployment/restart, proj/*, allow`. |
| `token has expired` (401) | Истек срок действия JWT-токена сессии или сервисного аккаунта. | `echo $TOKEN \| cut -d. -f2 \| base64 -d \| jq .exp` | Сгенерировать новый токен `argocd account generate-token` или перелогиниться. |
| Изменения в `policy.csv` не вступили в силу | Задержка инвалидации внутреннего кэша Casbin в памяти `argocd-server`. | Проверить логи `argocd-server` на наличие ошибок парсинга ConfigMap. | Выполнить рестарт пода: `kubectl rollout restart deployment argocd-server -n argocd`. |
| `ApplicationSet: permission denied` | Отсутствует разрешение на ресурс `applicationsets`. | `argocd admin settings rbac can <role> create applicationsets 'proj/*'` | Добавить `p, <role>, applicationsets, create, proj/*, allow` в глобальный `policy.csv`. |

### Отладка кэша Casbin и форсированная инвалидация

Внутренний энфорсер Argo CD кэширует скомпилированные правила в памяти (`defaultRBACSyncPeriod = 10m`). При редактировании `argocd-rbac-cm` контроллер ConfigMap Informer обновляет политики автоматически, однако при возникновении рассинхронизации:

```bash
# 1. Просмотр ошибок парсера RBAC в логах сервера
kubectl logs -n argocd deployment/argocd-server --tail=200 | grep -E "rbac|casbin"
# → time="2026-10-12T14:43:01Z" level=info msg="RBAC ConfigMap 'argocd-rbac-cm' updated"

# 2. Форсированная очистка in-memory кэша через мягкий перезапуск
kubectl rollout restart deployment argocd-server -n argocd
kubectl rollout status deployment argocd-server -n argocd --timeout=60s
# → deployment "argocd-server" successfully rolled out
```

---

## Лучшие практики и регламент очистки (Best Practices & Cleanup)

### Архитектура и безопасность

1. **Принцип минимальных привилегий (Least Privilege):** Никогда не устанавливайте `policy.default: role:admin`. Единственно безопасное значение — `role:readonly` (или пустая строка для полного закрытия доступа).
2. **Делегирование через AppProject вместо глобального файла:** Держите глобальный `argocd-rbac-cm` компактным (только общесистемные роли: админы, аудиторы, дежурные). Права конкретных команд разработки описывайте в `.spec.roles[]` соответствующих `AppProject`. Это устраняет риск повреждения глобальной авторизации одной синтаксической ошибкой.
3. **Раздельные токены для каждого CI/CD пайплайна:** Не используйте один общий JWT-токен на всю компанию. Выпускайте отдельные токены через `argocd proj role create-token` с ограниченным TTL (например, 90 дней) и фиксированным описанием.
4. **Контроль действия `override`:** Исключите выдачу права `applications, override` рядовым разработчикам. Право позволяет обходить хуки безопасности и перезаписывать конфликты ресурсов без контроля.
5. **Предотвращение разрастания regex:** Режим `policy.matchMode: regex` существенно увеличивает время оценки правил при тысячах приложений. Используйте `glob` везде, где это возможно.

### Производительность

- Ограничивайте размер `policy.csv`: ConfigMap в etcd имеет жесткий лимит 1 МБ, а большое число правил замедляет рендеринг UI-страниц с сотнями объектов.
- Группируйте пользователей через OIDC-группы в `g,`, избегая сотен индивидуальных записей на конкретных сотрудников.

---

### Пошаговый регламент отката и очистки (Reversion & Cleanup)

При ошибочной конфигурации RBAC, компрометации сервисного аккаунта или завершении тестирования выполните регламентные шаги:

#### 1. Отзыв скомпрометированного JWT-токена сервисного аккаунта
```bash
# Просмотр ID выпущенных токенов аккаунта
argocd account get --account gitlab-ci-bot
# → Tokens:
# →   ID: 1735689600, IssuedAt: 2026-10-12, ExpiresAt: 2027-10-12

# Немедленный отзыв токена
argocd account revoke-token --account gitlab-ci-bot --token-id 1735689600
# → Token '1735689600' revoked successfully
```

#### 2. Отзыв токена роли проекта `AppProject`
```bash
# Удаление токена проектной роли
argocd proj role delete-token team-billing cicd-deployer 1735689600
# → Token '1735689600' deleted successfully
```

#### 3. Экстренная глобальная инвалидация всех JWT-токенов
Если скомпрометирован ключ подписи или произошла утечка мастер-доступа:
```bash
# Ротация серверного ключа подписи токенов в secret argocd-secret
# (приведет к инвалидации всех сессий пользователей и токенов API)
NEW_KEY=$(openssl rand -base64 32)
kubectl patch secret argocd-secret -n argocd -p "{\"stringData\": {\"server.secretkey\": \"$NEW_KEY\"}}"
# → secret/argocd-secret patched

# Перезапуск argocd-server для загрузки нового ключа
kubectl rollout restart deployment argocd-server -n argocd
# → deployment.apps/argocd-server restarted
```

#### 4. Откат изменений `argocd-rbac-cm` до эталонного состояния
```bash
# Создание аварийного бэкапа перед правками
kubectl get configmap argocd-rbac-cm -n argocd -o yaml > /tmp/argocd-rbac-cm-backup.yaml

# Восстановление эталонной базовой конфигурации при сбое
cat << 'EOF' | kubectl apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.matchMode: glob
  scopes: "[groups]"
  policy.csv: |
    p, role:readonly, applications, get, */*, allow
    p, role:readonly, clusters, get, *, allow
    p, role:readonly, repositories, get, *, allow
    p, role:readonly, projects, get, *, allow
EOF
# → configmap/argocd-rbac-cm configured

# Перезапуск сервера для немедленного вступления в силу
kubectl rollout restart deployment argocd-server -n argocd
```

---

## Ограничения и Edge Cases

1. **Deny-Override эффект:** В Casbin невозможно разрешить действие правилом `allow`, если для субъекта совпадает более широкое правило `deny`. Решение: не используйте глобальные отрицания (`p, role:X, applications, *, */*, deny`), а стройте роли по модели позитивных разрешений (Whitelist-only).
2. **Невозможность переопределения `policy.default` через `deny`:** Если `policy.default: role:readonly` выдает `applications, get, */*`, добавление `p, role:custom, applications, get, secret-proj/*, deny` заблокирует доступ только субъектам, привязанным исключительно к `role:custom`. Если сессия пользователя считается валидной для `policy.default`, отсечение может оказаться неэффективным. Для изоляции секретных проектов удалите `get` на `*/*` из дефолтной роли и выдавайте доступ адресно.
3. **Globbing без разделителя слэша:** Маска `*` в glob-режиме Casbin совпадает с символом `/`. Запись `prod-*` в поле объекта совпадет со строкой `prod-project/app-name`. Для разграничения проекта и приложения всегда используйте явный слэш: `prod-*/*`.
4. **Отсутствие наследования между ролями (Role Hierarchy):** Роли в Argo CD плоские: роль `role:senior-dev` не может автоматически наследовать все правила роли `role:junior-dev`. Маппинг `g, role:senior-dev, role:junior-dev` в Casbin не поддерживается по умолчанию. Пользователю необходимо назначать обе роли либо дублировать правила.
5. **Отсутствие условной логики времени (Time Conditions):** RBAC не поддерживает ограничение доступа по расписанию (например, «запретить deploy после 18:00»). Для временных ограничений деплоя используйте [Sync Windows](./synchronization/scenarios/sync_windows.md) в `AppProject`.
6. **Ограничение ConfigMap 1 МБ:** При разрастании компании `policy.csv` может упереться в лимит размера объекта Kubernetes. Решение — перенос ролей в `AppProject`.
7. **Кэширование групп OIDC:** При изменении состава групп пользователя в корпоративном IdP Argo CD не узнает об этом до истечения сессии JWT (по умолчанию 8–24 часа). Пользователь обязан выполнить Logout/Login или администратор должен уменьшить `users.session.duration` в `argocd-cm`.
8. **Изоляция проектных ролей:** Роли, созданные в `AppProject`, имеют префикс `proj:<project>:<role>` и по умолчанию не могут получить доступ к ресурсам за пределами своего проекта (например, к кластерам `clusters` или репозиториям `repositories`), если соответствующие правила не добавлены в глобальный `argocd-rbac-cm`.

---

## Дополнительная информация

### Связанные документы в базе знаний

- [Установка и базовая настройка Argo CD](./argocd_installation_and_setup.md) — Первоначальное конфигурирование `argocd-cm` и `argocd-rbac-cm`.
- [SSO с GitLab (OIDC / Dex)](./argocd_sso_gitlab.md) — Интеграция корпоративного каталога пользователей и маппинг групп.
- [AppProject — границы безопасности и мультитенантность](./argocd_appproject_deep.md) — Детальное описание изоляции проектов, whitelists и проектных ролей.
- [Мультитенантность в Argo CD](./argocd_multi_tenancy.md) — Архитектурные паттерны soft и hard мультитенантности на bare-metal кластерах.
- [API автоматизация и сервисные аккаунты](./argocd_api_automation.md) — Использование REST/gRPC API, программная генерация токенов.
- [Регламентные окна синхронизации (Sync Windows)](./synchronization/scenarios/sync_windows.md) — Управление временными окнами деплоя на уровне проектов.
- [Мониторинг и траблшутинг Argo CD](./argocd_troubleshooting_and_monitoring.md) — Диагностика контроллеров, метрики Prometheus и алертинг.
- [Управление генераторами ApplicationSet](./argocd_applicationsets.md) — Безопасное использование генераторов приложений в мультитенантной среде.
- [Безопасность и Hardening инсталляции](./argocd_security_hardening.md) — Сетевые политики, mTLS, GPG-подписи и защита кластера.
- [Disaster Recovery и резервное копирование](./argocd_disaster_recovery.md) — Регламент бэкапа и восстановления конфигурации `argocd-rbac-cm`.

### Официальные спецификации

- [Argo CD RBAC Documentation](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/) — Официальное руководство оператора по настройке RBAC.
- [Casbin Model & Syntax](https://casbin.org/docs/supported-models) — Документация движка Casbin и синтаксис конфигурации моделей.
- [Argo CD AppProject Roles Guide](https://argo-cd.readthedocs.io/en/stable/user-guide/projects/#project-roles) — Руководство пользователя по управлению проектными ролями.
