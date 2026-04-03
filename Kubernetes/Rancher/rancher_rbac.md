# Управление пользователями и RBAC в Rancher

## Определения

* **Пользователь Rancher**: Учётная запись, созданная в Rancher (локально или через внешние провайдеры), позволяющая получить доступ к UI и управляемым кластерам.
* **Global Role (Глобальная роль)**: Определяет права доступа пользователя к функционалу самого Rancher.
* **Cluster Role (Роль уровня кластера)**: Определяет права доступа пользователя в рамках конкретного кластера Kubernetes.
* **Project (Проект)**: Уровень абстракции в Rancher, группирующий один или несколько `namespaces`.
* **Project/Namespace Role (Роль уровня проекта/неймспейса)**: Определяет права доступа пользователя в рамках конкретного проекта или `namespace`.
* **Аутентификационный провайдер (Auth Provider)**: Внешняя система для аутентификации пользователей (Active Directory, OpenLDAP, GitHub, Keycloak).

## Базовые концепции

### Концепция пользователя в Rancher vs. Kubernetes

В отличие от "ванильного" Kubernetes, где отсутствует явное понятие "пользователя" с паролем и UID, Rancher вводит полноценную сущность пользователя. Rancher управляет пользователями, а затем транслирует их права в нативные механизмы [Kubernetes RBAC](../../Kubernetes/Security/rbac/rbac_overview.md).

### Rancher Project vs. Kubernetes Namespace

**Rancher Project** — это логическая группировка одного или нескольких **Kubernetes Namespaces**. При создании `Project` в Rancher определяются границы для RBAC и ресурсных квот.

**Важно**: Если пользователь, имеющий права только на `Project` в Rancher, создаст `Namespace` напрямую через `kubectl`, этот `namespace` не будет автоматически связан с его `Project` в Rancher. Для корректной работы `namespaces` должны быть созданы *внутри* Rancher `Project` через UI Rancher.

### Иерархия доступа

* **Global**: Определяет, что пользователь может делать с самим Rancher.
* **Cluster**: Определяет, что пользователь может делать в конкретном кластере (владелец, член).
* **Project**: В рамках кластера, `Project` группирует `namespaces`.
* **Namespace**: Самый гранулярный уровень.

### Типы пользователей

* **Локальные пользователи**: Создаются и управляются непосредственно в Rancher.
* **Внешние пользователи**: Аутентифицируются через внешние провайдеры (LDAP, Active Directory, FreeIPA, Keycloak).

### Преимущества RBAC в Rancher

* **Удобство**: Упрощенное управление правами доступа через UI.
* **Делегирование**: Возможность делегировать управление частями кластера или проектами.
* **Ограничение ресурсов**: Интегрированные механизмы квоты на уровне проектов.

## Практические сценарии

### Создание локального пользователя и назначение глобальных прав

1. В Rancher UI перейдите в **Global Settings** → **User & Authentication** → **Users**.
2. Нажмите **Add User**.
3. Укажите `Username`, `Display Name`, `Description` и `Password`.
4. В разделе **Global Permissions** выберите глобальную роль:
    * **Standard User**: Может создавать новые кластеры, управлять своими кластерами и проектами.
    * **User-Base**: Может только логиниться в Rancher UI и видеть доступные кластеры/проекты.

### Создание проекта с ресурсными квотами и добавление пользователя

1. В Rancher UI перейдите в **Global** → **Clusters** → (ваш кластер) → **Projects/Namespaces**.
2. Нажмите **Create Project**.
3. Укажите `Project Name` и `Description`.
4. В разделе **Project Members** добавьте пользователя и назначьте роль:
    * **Project Owner**: Полные права на управление проектом.
    * **Project Member**: Может создавать и управлять ресурсами внутри проекта.
    * **Read-only**: Только просмотр всех ресурсов проекта, кроме секретов.
5. **Настройка Resource Quotas**:
    * **Project Limits**: Лимиты ресурсов для всего проекта (CPU, Memory).
    * **Namespace Default Limits**: Значения по умолчанию для новых `namespaces`.

### Работа пользователя в проекте

1. Пользователь видит только кластеры и проекты, к которым предоставлен доступ.
2. **Скачивание Kubeconfig**: **Cluster Explorer** → **Kubeconfig File**.
3. **Создание Namespace (через Rancher UI)**:
    * **Projects/Namespaces** → (ваш проект) → **Namespaces** → **Create Namespace**.
    * **Настройка Resource Limits**: Распределение квот на конкретный `namespace`.
    * **Container Default Resource Limits**: Не рекомендуется устанавливать.
4. **Развертывание приложения**:
    * Через Rancher UI: Image, Port Mapping, Resource Requests/Limits.
    * Или через `kubectl apply -f your-app.yaml`.

### Настройка RBAC для просмотра мониторинга приложений

Для просмотра метрик в Grafana Rancher пользователю необходимы права на `Project Monitoring`:

* `View Monitoring`: Просмотр Grafana, Prometheus, Alertmanager.
* `Manage Services`: Обязательное дополнение — без него пользователь сталкивается с ошибками в UI.

**Процесс:** `Project/Namespaces` → (проект мониторинга) → `Members` → добавить пользователя с обеими ролями.

### Создание и привязка кастомных ролей

1. В Rancher UI: **Global Settings** → **Role Based Access Control** → **Cluster Roles** (или **Project/Namespace Roles**).
2. **Create Cluster Role** → укажите `Name`, `Description`.
3. В разделе **Rules** укажите `Verbs` и `Resources`.
4. Привяжите роль к пользователю через Members проекта или кластера.

### Ограничения RBAC для логирования

Ограничения для `ClusterFlow`/`ClusterOutput` и `Flow`/`Output` описаны в разделе [логирование Rancher](./rancher_logging.md#ограничения-rbac).

## Дополнительная информация

### Актуальность версий

> **Внимание:** Rancher RBAC стабильно развивается. Ключевые изменения привязаны к мажорным версиям Rancher.

| Компонент | Указанная информация | Статус | Рекомендация |
|-----------|---------------------|--------|--------------|
| **Global/Cluster/Project Roles** | Базовая модель RBAC | ✅ Evergreen | Не менялась с 2.x |
| **Auth Providers** | LDAP, AD, Keycloak, GitHub | ✅ Актуален | [Auth Providers Docs](https://ranchermanager.docs.rancher.com/how-to-guides/new-user-guides/authentication-permissions-and-global-configuration/authentication-config) |
| **Custom Roles** | Создание через UI и API | ✅ Актуален | Расширяется в каждой версии |

Rancher RBAC транслирует права в нативный [Kubernetes RBAC](../../Kubernetes/Security/rbac/rbac_overview.md). Альтернативы для управления доступом: [ArgoCD](../../GitOps/ArgoCD/argocd_overview.md).

См. также: [rancher_overview](./rancher_overview.md) — обзор платформы Rancher.
