# Управление пользователями и RBAC в Rancher

## Определения

**Rancher User** — объект в Management-кластере (local), представляющий личность или программного агента. Rancher хранит метаданные пользователя, но аутентификацию делегирует внешним провайдерам.

**Global Role** — набор разрешений, действующих на уровне всей инсталляции Rancher Manager. Определяет права на создание новых кластеров, управление Auth-провайдерами и глобальными настройками. Начиная с 2026 г., поддерживает **Inherited Namespace Rules** для автоматического проброса прав в downstream-кластеры.

**Project (Проект)** — логическая группа нескольких Namespace внутри одного кластера. Позволяет агрегировать права доступа, квоты ресурсов и политики безопасности для группы пространств имен.

**RoleTemplate** — кастомный ресурс (CRD) в Rancher, служащий шаблоном для создания нативных `ClusterRole` и `Role` в управляемых кластерах.

**OIDC Aggregator (v2.8+)** — компонент, агрегирующий JWKS и документы Discovery со всех подключенных кластеров для обеспечения единой точки входа (SSO) внешним инструментам.

## Базовые концепции

### Механизм трансляции и Impersonation

Rancher не является "заменой" нативному RBAC Kubernetes, он выступает как оркестратор прав. При обращении пользователя к downstream-кластеру через Rancher Proxy используется механизм **Impersonation**:

1.  Rancher аутентифицирует пользователя (через токен или SSO).
2.  Запрос пересылается в downstream-кластер с заголовками `Impersonate-User: user-u-xxxxx` и `Impersonate-Group: system:authenticated`.
3.  Локальный API-сервер Kubernetes проверяет права для этого системного имени, используя объекты `ClusterRoleBinding`, которые Rancher заранее создал на основе **RoleTemplate**.

### Уровни иерархии прав

| Уровень | Объект Rancher | Соответствие в K8s | Сфера действия |
| :--- | :--- | :--- | :--- |
| **Global** | `GlobalRole` | N/A (local cluster only) | Вся инсталляция Rancher |
| **Cluster** | `ClusterRoleTemplateBinding` | `ClusterRoleBinding` | Весь конкретный кластер |
| **Project** | `ProjectRoleTemplateBinding` | `RoleBinding` (множественные) | Все Namespace внутри проекта |
| **Namespace** | N/A | `RoleBinding` | Конкретный Namespace |

### Преимущества проектов (Projects)

*   **Multi-tenant изоляция:** разработчики видят только ресурсы своего проекта.
*   **Автоматизация прав:** при добавлении нового Namespace в проект, все `ProjectRoleTemplateBinding` автоматически распространяются на него.
*   **Resource Quotas:** возможность установить лимит на суммарное потребление ресурсов всеми Namespace проекта (например, "не более 16 CPU на весь проект Marketing").

## Практические сценарии

### Настройка OIDC с использованием PKCE (Рекомендовано 2026)

Для интеграции с современными IDP (Okta, Authentik, Keycloak):
1.  В Rancher UI: **Users & Authentication** → **Auth Provider** → **OIDC**.
2.  Укажите **Issuer URL** (Rancher автоматически загрузит метаданные через `.well-known/openid-configuration`).
3.  Включите **Use PKCE** для защиты потока авторизации.
4.  Настройте **Group Search**: укажите атрибут (обычно `groups`), из которого Rancher будет извлекать членство пользователя для маппинга ролей.

### Маппинг внешних групп на роли Rancher

Лучшая практика — не добавлять пользователей по одному, а назначать роли группам:
1.  Создайте группу в вашем IDP (например, `k8s-platform-admins`).
2.  В Rancher перейдите в настройки нужного кластера → **Cluster Members** → **Add**.
3.  Выберите тип **Group** и введите точное имя группы из IDP.
4.  Назначьте роль `Cluster Owner`. Все участники группы автоматически получат доступ.

### Создание кастомного RoleTemplate

Если встроенных ролей недостаточно, создайте свою:
1.  **Users & Authentication** → **Role Based Access Control** → **Cluster/Project Roles**.
2.  Нажмите **Create**. В поле **Rules** определите `apiGroups`, `resources` и `verbs`.
3.  Используйте флаг **Hidden**, если роль предназначена только для системного использования и не должна выбираться в UI пользователями.

## Дополнительная информация

### Рекомендации и статус (2026)

*   **Policy-as-Code:** Всегда определяйте `RoleTemplates` и `GlobalRoles` через Terraform/OpenTofu или Fleet. Избегайте ручных правок в UI в Production-средах.
*   **Hide Local Auth:** После настройки внешнего IDP рекомендуется включить опцию `hide-local-auth`, чтобы минимизировать риск атак на локальные учетные записи.
*   **RKE1 EOL:** Учитывайте, что расширенные функции RBAC 2026 года (OIDC Aggregator, гранулярные роли Fleet) полноценно работают только на **RKE2** и **K3s**.

---

**См. также:**

*   [Kubernetes RBAC](../Security/rbac/rbac_overview.md) — основы прав доступа в K8s.
*   [Rancher Overview](./rancher_overview.md) — архитектура платформы.
*   [Rancher Logging](./rancher_logging.md) — разграничение доступа к логам.

**Внешние ресурсы:**

*   [Official Rancher RBAC Guide](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/authentication-permissions-and-global-configuration/manage-role-based-access-control-rbac)
*   [OIDC PKCE Explained](https://oauth.net/2/pkce/)
*   [Rancher API Documentation](https://rancher.com/docs/rancher/v2.x/en/api/)
