# Управление пользователями и RBAC в Rancher

## Определения

**Пользователь Rancher** — объект в Rancher Manager, представляющий личность. При аутентификации через внешние системы (LDAP, AD) Rancher создает внутренний объект пользователя с уникальным идентификатором (например, `u-bcdef`).

**Global Role (Глобальная роль)** — набор прав, определяющий доступ к ресурсам самого Rancher Manager (создание кластеров, управление пользователями, настройка Auth Providers).

**RoleTemplate** — кастомный ресурс (CRD) в Rancher, описывающий шаблон роли. Именно на базе этих шаблонов Rancher создает нативные `ClusterRole` и `Role` в управляемых кластерах.

**Project (Проект)** — уникальная для Rancher сущность, позволяющая объединять несколько Namespace в одну логическую единицу для применения общих квот и прав доступа.

**Auth Provider (Провайдер аутентификации)** — модуль интеграции с внешней системой управления учетными записями (Active Directory, FreeIPA, GitHub, Keycloak).

## Базовые концепции

### Механизм трансляции прав

Rancher не подменяет [Kubernetes RBAC](../Security/rbac/rbac_overview.md), а автоматизирует его настройку. Когда администратор назначает роль пользователю в интерфейсе Rancher, происходят следующие процессы:

1. **Создание RoleTemplate**: описание разрешений хранится в кластере `local` (где установлен Rancher).
2. **Генерация объектов**: Rancher создает нативные `ClusterRole` в целевом (downstream) кластере.
3. **Привязка (Binding)**: создаются `ClusterRoleBinding` или `RoleBinding`, связывающие субъекта (пользователя) с ролью.
4. **Идентификация**: в Kubernetes RBAC пользователи Rancher фигурируют под системными именами (например, `user-u-bcdef`).

### Уровни управления (Hierarchy)

1. **Global Permissions**: права на уровне всей инсталляции Rancher.
2. **Cluster Permissions**: права на уровне конкретного кластера (управление нодами, хранилищами).
3. **Project Permissions**: права на группу Namespace. Это основной уровень для разработчиков.
4. **Namespace Permissions**: гранулярный доступ к конкретному пространству имен внутри проекта.

### Проекты vs Пространства имен

Использование проектов (Projects) поверх стандартных Namespace дает ряд преимуществ:
* **Наследование прав**: пользователь, добавленный в проект, автоматически получает права во всех текущих и будущих Namespace этого проекта.
* **Агрегация квот**: лимиты CPU/RAM устанавливаются на проект целиком, распределяясь между его Namespace.
* **Изоляция**: проекты помогают логически разделить окружения (Dev, Staging, Prod) внутри одного кластера.

## Практические сценарии

### Настройка внешнего провайдера (на примере LDAP)

1. Перейдите в **Users & Authentication** → **Auth Provider**.
2. Выберите **LDAP** (или OpenLDAP/Active Directory).
3. Заполните данные сервера и **Service Account** для поиска пользователей.
4. Настройте **User/Group Search Config** (укажите базовые DN и фильтры).
5. Нажмите **Enable** и выполните тестовый вход.

### Создание кастомной роли (RoleTemplate)

Если стандартных ролей (Project Owner, Project Member) недостаточно:
1. Перейдите в **Users & Authentication** → **Role Based Access Control**.
2. Выберите нужную вкладку (Cluster Roles или Project Roles).
3. Нажмите **Create** и определите правила (Resources, Verbs).
4. **Важно:** флаг `Context` определяет, где будет доступна эта роль.
5. Флаг `Locked` запрещает редактирование встроенных ролей, но позволяет клонировать их для изменений.

### Диагностика прав доступа (Troubleshooting)

Если пользователь не может выполнить действие, разрешенное в Rancher:
1. Проверьте ID пользователя в Rancher (**Users & Authentication** → **Users**).
2. В управляемом кластере найдите привязки:
   ```bash
   kubectl get clusterrolebindings | grep user-u-xxxxx
   ```
3. Проверьте содержимое связанной `ClusterRole`:
   ```bash
   kubectl get clusterrole <name> -o yaml
   ```
4. Убедитесь, что Cattle Agent в кластере успешно синхронизировал объекты из Rancher Manager.

## Дополнительная информация

### Статус и рекомендации

| Компонент | Статус | Рекомендация |
|-----------|--------|--------------|
| Локальные пользователи | Актуально | Только для начальной настройки (admin) |
| Внешние группы | Стабильно | Назначать права группам, а не отдельным пользователям |
| Квоты проектов | Актуально | Обязательно для multi-tenant сред |

**Связанные разделы:**

* [rancher_overview](./rancher_overview.md) — общая архитектура Rancher.
* [Kubernetes RBAC](../Security/rbac/rbac_overview.md) — теоретические основы прав доступа в K8s.
* [Rancher Logging](./rancher_logging.md) — пример использования RBAC для системных сервисов.

**Внешние ссылки:**
* [Rancher RBAC Documentation](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/authentication-permissions-and-global-configuration/manage-role-based-access-control-rbac)
* [Authenticating with LDAP/AD](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/authentication-permissions-and-global-configuration/configure-adapter-for-authentication/configure-openldap)
