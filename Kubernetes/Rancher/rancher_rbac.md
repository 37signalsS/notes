# Управление пользователями и RBAC в Rancher

## Определения

**Rancher User** — объект в Management-кластере (local), представляющий личность или программного агента. Rancher хранит метаданные пользователя, но аутентификацию делегирует внешним провайдерам.

**Principal** — более низкоуровневая сущность, представляющая пользователя или группу, пришедших из конкретного механизма аутентификации (local, AD, GitHub, OIDC). Именно `Principal` (а не сам `User`) привязывается к ролям. Формат имени содержит префикс механизма: `local://u-xxxx`, `github_user://12345`, `activedirectory_user://...`.

**Global Role** — набор разрешений, действующих на уровне всей инсталляции Rancher Manager. Определяет права на создание новых кластеров, управление Auth-провайдерами и глобальными настройками. Начиная с 2026 г., поддерживает **Inherited Namespace Rules** для автоматического проброса прав в downstream-кластеры.

**GlobalRoleBinding** — CRD, связывающий субъект (пользователя или группу-Principal) с `GlobalRole`. В отличие от CRTB/PRTB, применяется в Management-кластере.

**Project (Проект)** — логическая группа нескольких Namespace внутри одного кластера. Позволяет агрегировать права доступа, квоты ресурсов и политики безопасности для группы пространств имен.

**RoleTemplate** — кастомный ресурс (CRD) в Rancher, служащий шаблоном для создания нативных `ClusterRole` и `Role` в управляемых кластерах. Является «строительным блоком» всей модели авторизации Rancher.

**ClusterRoleTemplateBinding (CRTB)** — CRD, привязывающий субъекта к `RoleTemplate` в контексте конкретного кластера. Создаёт RBAC-примитивы одновременно в Management-кластере (для видимости в UI) и в целевом downstream-кластере.

**ProjectRoleTemplateBinding (PRTB)** — CRD, привязывающий субъекта к `RoleTemplate` в контексте конкретного проекта. Распространяет права на все Namespace, входящие в проект.

**OIDC Aggregator (v2.8+)** — компонент (в т.ч. сторонние реализации, например, `rancher2-oidc`), агрегирующий JWKS и документы Discovery со всех подключенных кластеров для обеспечения единой точки входа (SSO) внешним инструментам.

## Базовые концепции

### Двухуровневая архитектура RBAC (Management vs User Cluster)

Ключевая особенность Rancher RBAC — работа в **двух плоскостях (planes)** одновременно, что принципиально отличает его от простой «замены» нативного RBAC Kubernetes.

| Плоскость | Назначение | Создаваемые примитивы RBAC |
| :--- | :--- | :--- |
| **Management Plane** (local) | Управление видимостью и членством ресурсов в UI Rancher (`Cluster`, `Project`, `GlobalRole`, `RoleTemplate`, пользователи) | `Roles`, `RoleBindings` в backing-неймспейсах, `ClusterRoleBindings` для membership |
| **User Cluster Plane** (downstream) | Фактическое применение прав в целевом кластере | `ClusterRole` + `ClusterRoleBinding` (для кластерных ролей), `Role` + `RoleBinding` (для проектных) |

Один и тот же `CRTB`/`PRTB` обрабатывается двумя наборами контроллеров: контроллером management-плоскости (отвечает за отображение и доступ к resources в UI) и контроллером user-кластера (синхронизирует нативные объекты RBAC в downstream). Это позволяет Rancher «транслировать» свои абстракции в стандартный Kubernetes RBAC, который реально выполняет API-сервер downstream-кластера.

### Механизм трансляции и Impersonation

Rancher не является "заменой" нативному RBAC Kubernetes, он выступает как оркестратор прав. При обращении пользователя к downstream-кластеру через Rancher Proxy используется механизм **Impersonation**:

1.  Rancher аутентифицирует пользователя (через токен или SSO).
2.  Запрос пересылается в downstream-кластер с заголовками `Impersonate-User: user-u-xxxxx` и `Impersonate-Group: system:authenticated`.
3.  Локальный API-сервер Kubernetes проверяет права для этого системного имени, используя объекты `ClusterRoleBinding`, которые Rancher заранее создал на основе **RoleTemplate**.

**Уточнение механизма:** Rancher сопоставляет каждую учётную запись пользователя с эквивалентным именем в downstream-кластере и impersonates от его имени. На каждый вызов API Authentication Proxy аутентифицирует вызывающую сторону и проставляет корректные заголовки impersonation. Это позволяет полноценно использовать нативные механизмы Kubernetes (например, `subjectaccessreviews` и Webhook-авторизацию внутри downstream-кластера).

### Уровни иерархии прав

| Уровень | Объект Rancher | Соответствие в K8s | Сфера действия |
| :--- | :--- | :--- | :--- |
| **Global** | `GlobalRole` / `GlobalRoleBinding` | Кластер-scoped роли (local) | Вся инсталляция Rancher |
| **Cluster** | `ClusterRoleTemplateBinding` | `ClusterRole` + `ClusterRoleBinding` | Весь конкретный кластер |
| **Project** | `ProjectRoleTemplateBinding` | `Role` + `RoleBinding` (множественные) + `ClusterRoleBinding` для глобальных правил | Все Namespace внутри проекта |
| **Namespace** | Принадлежность к Project | `RoleBinding` | Конкретный Namespace |

**Важный нюанс Project-ролей:** если в `RoleTemplate` проекта содержатся правила на resource-scoped (глобальные/кластерные) ресурсы, такие правила «промоутятся» в `ClusterRole` и связываются через `ClusterRoleBinding`. Это позволяет, например, дать участнику проекта права на чтение определённых кластерных ресурсов, не делая его кластерным владельцем.

### Наследование RoleTemplate (граф разрешений)

`RoleTemplate` может наследовать другие шаблоны через поле `roleTemplateNames`, образуя направленный граф разрешений. При обработке привязки контроллер рекурсивно собирает все унаследованные шаблоны (`gatherRoles`) и на их основе строит итоговый набор правил. На практике это означает:

- Встроенные роли построены как цепочки наследования. Например, `project-owner` наследует роль `admin`, а `project-member` — роль `edit`.
- Если заменить один RoleTemplate в цепочке, обновятся все зависящие от него привязки.
- Свойство `external: true` позволяет ссылаться на **нативные** `ClusterRole` Kubernetes вместо создания новых Rancher-ролей (удобно для «проброса» существующих ролей).

### Встроенные роли (Built-in Roles)

**GlobalRoles** (по умолчанию):
- `admin` — полный административный доступ ко всем ресурсам Rancher и всем кластерам.
- `user` (`Standard User`) — создание кластеров, использование каталога, управление собственными токенами и kubeconfig; назначается новым пользователям по умолчанию.
- `user-base` — минимальный набор прав для входа (preferences, собственные токены, kubeconfig).
- `users-manage` — полное управление пользователями и `GlobalRoleBinding`.

**RoleTemplates (Cluster)**:
- `cluster-owner` — полный контроль над кластером (может «владеть» им).
- `cluster-member` — просмотр ресурсов, создание проектов.
- `nodes-manage` — управление узлами и Node Pools.

**RoleTemplates (Project)**:
- `project-owner` (наследует `admin`) — полный контроль над проектом.
- `project-member` (наследует `edit`) — редактирование workloads и ресурсов, но не управление членами проекта.

**Ограничение:** встроенные роли (помечены `builtin: true`) неизменяемы. Если встроенная роль не подходит — создавайте собственную, не редактируя системную.

### Преимущества проектов (Projects)

*   **Multi-tenant изоляция:** разработчики видят только ресурсы своего проекта.
*   **Автоматизация прав:** при добавлении нового Namespace в проект, все `ProjectRoleTemplateBinding` автоматически распространяются на него.
*   **Resource Quotas:** возможность установить лимит на суммарное потребление ресурсов всеми Namespace проекта (например, "не более 16 CPU на весь проект Marketing").

**Механика привязки Namespace к проекту:** членство Namespace определяется аннотацией `field.cattle.io/projectId`. Когда Namespace создаётся или обновляется, handler проекта проверяет все `PRTB` данного проекта и создаёт/обновляет соответствующие `RoleBinding` в этом Namespace. Это и даёт эффект «автоматического распространения прав».

### Глобальные правила на downstream (2026)

Современные `GlobalRole` поддерживают несколько полей, расширяющих сферу действия за пределы local-кластера:

- `inheritedClusterRoles` (v2.8+) — список `RoleTemplate` (с `context: cluster`), которые выдаются **во всех** downstream-кластерах через единый `GlobalRoleBinding`. Пример: роль с `inheritedClusterRoles: [cluster-owner]` делает субъекта владельцем всех создаваемых кластеров.
- `inheritedFleetWorkspacePermissions` — права во всех Fleet workspaces.
- `namespacedRules` / `inheritedNamespacedRules` — правила уровня Namespace, автоматически применяемые в перечисленных Namespace (в т.ч. в downstream-кластерах), с reconciliation при создании нового Namespace.

## Практические сценарии

### Настройка OIDC с использованием PKCE (Рекомендовано 2026)

Для интеграции с современными IDP (Okta, Authentik, Keycloak):
1.  В Rancher UI: **Users & Authentication** → **Auth Provider** → **OIDC**.
2.  Укажите **Issuer URL** (Rancher автоматически загрузит метаданные через `.well-known/openid-configuration`).
3.  Включите **Use PKCE** для защиты потока авторизации. PKCE (Proof Key for Code Exchange) защищает Authorization Code даже при отсутствии/компрометации `client_secret` — обязателен для публичных клиентов и рекомендован для всех.
4.  Настройте **Group Search**: укажите атрибут (обычно `groups`), из которого Rancher будет извлекать членство пользователя для маппинга ролей.

**Нюанс с SAML:** для SAML провайдеров (например, Okta SAML) запрос атрибута групп через Group Search работает иначе — необходим выпуск утверждения о группах в командой атрибут.

### Маппинг внешних групп на роли Rancher

Лучшая практика — не добавлять пользователей по одному, а назначать роли группам:
1.  Создайте группу в вашем IDP (например, `k8s-platform-admins`).
2.  В Rancher перейдите в настройки нужного кластера → **Cluster Members** → **Add**.
3.  Выберите тип **Group** и введите точное имя группы из IDP.
4.  Назначьте роль `Cluster Owner`. Все участники группы автоматически получат доступ.

**Жизненный цикл членства:** при удалении пользователя из группы в IDP, на следующем логине/синхронизации его групповые публичные права отзываются (заголовок `Impersonate-Group` перестаёт включать эту группу). Это упрощает управление доступом без создания отдельных записей на каждого сотрудника. Для локальных (не-групповых) привязок необходимо явно удалять binding.

### Создание кастомного RoleTemplate

Если встроенных ролей недостаточно, создайте свою:
1.  **Users & Authentication** → **Role Based Access Control** → **Cluster/Project Roles**.
2.  Нажмите **Create**. В поле **Rules** определите `apiGroups`, `resources` и `verbs`.
3.  Используйте флаг **Hidden**, если роль предназначена только для системного использования и не должна выбираться в UI пользователями.

**Декларативный способ (CRD, рекомендуемый для GitOps):**

```yaml
# RoleTemplate в контексте кластера (management.cattle.io/v3)
apiVersion: management.cattle.io/v3
kind: RoleTemplate
metadata:
  name: crt-workload-viewer
rules:
  - apiGroups: [""]
    resources: ["pods", "services", "namespaces"]
    verbs: ["get", "list", "watch"]
context: cluster          # context может быть cluster или project
```

**Привязка к кластеру через CRTB (YAML):**

```yaml
apiVersion: management.cattle.io/v3
kind: ClusterRoleTemplateBinding
metadata:
  name: crtb-owner-jane
  namespace: c-xxxxx              # namespace = ID кластера
clusterName: c-xxxxx
clusterRoleTemplateName: cluster-owner
userPrincipalName: local://u-yyyy   # или groupPrincipalName для группы
```

**Привязка к проекту через PRTB (YAML):**

```yaml
apiVersion: management.cattle.io/v3
kind: ProjectRoleTemplateBinding
metadata:
  name: prtb-member-team
  namespace: p-xxxxx               # namespace = ID проекта
projectName: c-xxxxx:p-xxxxx       # формат <clusterID>:<projectID>
roleTemplateName: project-member
groupPrincipalName: github_team://developers
```

> Идентификаторы `c-...`, `p-...` генерируются Rancher и видны в URL кластера/проекта или через `kubectl get clusters`/`kubectl get projects`.

### Создание кастомного GlobalRole (2026)

```yaml
apiVersion: management.cattle.io/v3
kind: GlobalRole
metadata:
  name: user-clusters-creator
displayName: Clusters Creator
newUserDefault: false
rules:
  - apiGroups: ["management.cattle.io"]
    resources: ["clusters"]
    verbs: ["create"]
  - apiGroups: ["management.cattle.io"]
    resources: ["settings"]
    verbs: ["get", "list", "watch"]
# Опционально: выдать роль cluster-owner во всех downstream-кластерах
# inheritedClusterRoles:
#   - cluster-owner
```

**Предупреждение о привязке `bind`/`escalate`:** начиная с Rancher v2.8, Webhook учитывает глаголы `bind` и `escalate` для `GlobalRole`. Пользователь, у которого в правилах стоит `*` или эти глаголы, потенциально может повысить собственные привилегии в Rancher. Перед обновлением пересматривайте кастомные GlobalRoles, содержащие широкие правила.

### API-токены и автоматизация (CI/CD, kubectl)

Для автоматизации (Terraform, Ansible, скрипты) используются **API-токены** Rancher и **kubeconfig**:

- **API-токены** (`/v3/tokens`) — для операций с Rancher API / Terraform / Ansible. Начиная с v2.8 срок действия: **auth-токены 90 дней**, **kubeconfig-токены 30 дней** (по умолчанию).
- **kubeconfig** — используйте выпукший через UI файл, который проксирует запросы через Authentication Proxy. Для обхода Rancher (например, для работы при недоступности Rancher) используйте **Authorized Cluster Endpoint (ACE)**.

**Тонкая настройка TTL:**

```bash
# Управление сроком действия kubeconfig-токенов (минуты)
kubectl -n cattle-system patch setting kubeconfig-default-token-ttl-minutes \
  --type=merge -p '{"value":"1440"}'
```

**Authorized Cluster Endpoint (ACE):** позволяет подключаться к API-серверу downstream-кластера **напрямую**, минуя Rancher (аутентификация через `kube-api-auth` webhook). Доступен только для кластеров **RKE2/K3s** (не для hosted-провайдеров EKS/AKS и т.п.). В kubeconfig появляется отдельный контекст; полезен при недоступности Rancher (break-glass) и для `helm`/`kubectl` без нагрузки на Rancher-прокси.

### Rancher как OIDC Provider (SSO для внешних систем)

Начиная с определённых версий Rancher может выступать не только потребителем, но и **провайдером OIDC** для сторонних приложений (feature flag `oidc-provider`). Это позволяет переиспользовать Rancher RBAC и единую авторизацию для инструментов экосистемы (наблюдаемость и т.п.), не держа отдельный IdP. Стандартные эндпоинты: `/oidc/authorize`, `/oidc/token`, `/oidc/.well-known/openid-configuration`; поддерживается Authorization Code Flow с PKCE. Клиенты регистрируются через ресурс `OIDCClient`, а секреты хранятся в неймспейсе `cattle-oidc-client-secrets`.

### Проверка и аудит прав (Validation & Audit)

**Проверка конкретного действия (от имени пользователя):**

```bash
# Подключитесь к Management-кластеру (local) или откройте kubeconfig конкретного кластера
# Может ли пользователь 'dev' создать deployment в namespace 'app'?
kubectl auth can-i create deployments -n app --as dev
# → yes / no

# Может ли имперсонация через Rancher Proxy корректно отработать группы?
kubectl auth can-i list pods -n app --as=dev --as-group=developers
```

**Инвентаризация привязок:**

```bash
# Все GlobalRoleBinding (субъект -> роль)
kubectl get globalrolebindings -o custom-columns=NAME:.metadata.name,ROLE:.globalRoleName,USER:.userName,GROUP:.groupPrincipalName

# Все GlobalRole и их флаг "по умолчанию для новых пользователей"
kubectl get globalroles -o custom-columns=NAME:.metadata.name,DISPLAY:.displayName,DEFAULT:.newUserDefault

# ClusterRoleTemplateBinding / ProjectRoleTemplateBinding
kubectl get clusterroletemplatebindings -A
kubectl get projectroletemplatebindings -A
```

**Валидация после изменения привязки:** после добавления члена группы в PRTB проверьте, что в целевом Namespace появились ожидаемые `RoleBinding`:

```bash
kubectl -n <namespace> get rolebindings
# → должны присутствовать записи, созданные Rancher (владелец-метка membership-binding-owner)
```

### Отслеживание и отзыв прав (Troubleshooting доступа)

- **Права не появились после добавления в группу IdP:** проверьте, что Rancher видит группу — очистите кэш сессии пользователя (в User & Authentication → Users → Refresh Principals) либо дождитесь перелогина. Для Active Directory/LDAP убедитесь, что включён Group Search и правильно задан базовый DN.
- **Пользователь не видит кластер/проект в UI:** вероятно, не хватает membership-binding в Management-плоскости. Убедитесь, что привязка создана на нужном уровне (CRTB для кластера/PRTB для проекта/GRB для глобального).
- **`Forbidden` при выполнении действия через kubectl:** проверьте `kubectl auth can-i ... --as <user>` в downstream-кластере; отличается ли реальный глагол/ресурс от того, что выдал RoleTemplate (rules в RBAC `apiGroups`/`resources`/`verbs` — чувствительны к регистру и точному имени ресурса, см. сравнение с нативным RBAC в [Субъекты и правила RBAC](../Security/rbac/roles.md)).
- **Сервисный аккаунт CI:** используйте отдельный токен (предпочтительно через `rancher-api-token` с ограниченным TTL в диапазоне 90 дней и последующей ротацией), а не долгоживущий административный токен. Назначьте ему минимально достаточную роль.

### Лучшие практики (Best Practices) 2026

*   **Policy-as-Code:** Всегда определяйте `RoleTemplates`, `GlobalRoles`, `CRTB`/`PRTB` через Terraform/OpenTofu или Fleet + Rancher API. Избегайте ручных правок в UI в Production-средах.
*   **Группы вместо пользователей:** назначайте роли группам из IdP, а не отдельным учётным записям — упрощает жизненный цикл доступа и отзыв прав.
*   **Hide Local Auth:** После настройки внешнего IDP рекомендуется включить опцию `hide-local-auth`, чтобы минимизировать риск атак на локальные учетные записи. Локальную аутентификацию оставляйте только для break-glass администратора.
*   **Лестница привилегий:** старайтесь выдавать пользователям минимально достаточные роли (User-Base + Project/Cluster roles), а не глобального администратора. Не назначайте `Manage Users` и другие глобальные permission широкому кругу (риск эскалации привилегий).
*   **Аудит и ротация токенов:** регулярно пересматривайте выпущенные API-токены в **Users & Authentication → API & Keys**, отзывайте неиспользуемые и ротируйте CI-токены до истечения TTL.
*   **Celebrate ACE для CI:** для доставки в downstream-кластеры используйте Authorized Cluster Endpoint с выделенным kubeconfig, чтобы не нагружать Rancher-прокси и сохранить доступ при остановке Rancher.

## Дополнительная информация

### Ограничения и границы применимости

- RBAC Rancher **не заменяет** нативный Kubernetes RBAC, а транслирует свои абстракции в него. Итоговое исполнение прав всегда выполняет API-сервер downstream-кластера.
- **Imported (kubeadm/EKS/AKS) кластеры:** жизненным циклом Кubernetes Rancher не управляет, и механизмы типа ACE для hosted-провайдеров недоступны; RBAC работает через Rancher-прокси по impersonation.
- **Сервисные аккаунты:** Rancher хранит в downstream-кластере служебный ServiceAccount (`cattle`), через который выполняются операции от имени пользователя. Изменение issuer/ключевой конфигурации ServiceAccount в downstream-кластере может сломать аутентификацию Rancher (см. связанные issue в экосистеме Rancher).
- **Масштабные инсталляции:** при тысячах привязок и ролей возможна деградация синхронизации; рекомендуется агрегация ролей (feature flag `aggregated-roletemplates`) для снижения числа объектов в downstream-кластерах.

### Рекомендации и статус (2026)

*   **Policy-as-Code:** Всегда определяйте `RoleTemplates` и `GlobalRoles` через Terraform/OpenTofu или Fleet. Избегайте ручных правок в UI в Production-средах.
*   **Hide Local Auth:** После настройки внешнего IDP рекомендуется включить опцию `hide-local-auth`, чтобы минимизировать риск атак на локальные учетные записи.
*   **RKE1 EOL:** Учитывайте, что расширенные функции RBAC 2026 года (OIDC Aggregator, гранулярные роли Fleet) полноценно работают только на **RKE2** и **K3s**.
*   **Токены:** учитывайте стандартные TTL (auth 90 дней, kubeconfig 30 дней) и настраивайте через setting `kubeconfig-default-token-ttl-minutes`.

---

**См. также:**

*   [Kubernetes RBAC](../Security/rbac/rbac_overview.md) — основы прав доступа в K8s.
*   [Rancher Overview](./rancher_overview.md) — архитектура платформы.
*   [Rancher Logging](./rancher_logging.md) — разграничение доступа к логам.

**Внешние ресурсы:**

*   [Official Rancher RBAC Guide](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/authentication-permissions-and-global-configuration/manage-role-based-access-control-rbac)
*   [OIDC PKCE Explained](https://oauth.net/2/pkce/)
*   [Rancher Global Permissions](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/authentication-permissions-and-global-configuration/manage-role-based-access-control-rbac/global-permissions)
