# ArgoCD — декларативный CI/CD для Kubernetes

**Актуально для:** Argo CD v3.6.x

> **Ключевые изменения v3.x:** Server-Side Apply по умолчанию, Progressive Sync для ApplicationSets, PreDelete-хуки (v3.3+), PostDelete-хуки (v2.10+), OCI-нативность (v3.1+), Shallow Git Cloning (v3.3+).

Установка:
```bash
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

См. также: [Сравнение с Flux](../argo_vs_flux_manifests.md), [Установка и настройка](./argocd_installation_and_setup.md), [Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md)

## Предварительные требования

Перед началом работы с Argo CD необходимо убедиться в следующем:

1. **Kubernetes кластер:** v1.26+ (рекомендуется v1.28+). Поддерживаются любые дистрибутивы (kubeadm, k3s, minikube, Kind, Talos, на bare metal).
2. **`kubectl`:** Установлен и настроен для доступа к целевому кластеру (v1.26+).
3. **Helm:** v3.10+ (опционально, для установки через чарты).
4. **Сеть:** Доступ из кластера к Git-репозиторию (HTTPS/SSH) и реестрам образов (Docker Hub, Harbor, GHCR, GCR).
5. **RBAC:** Администратор кластера для первоначальной установки и настройки CRD.
6. **Ресурсы:** Минимум 2 CPU / 4 GB RAM для контрольной плоскости Argo CD (не HA); для HA — 3 реплики каждого компонента.

## Определения

**ArgoCD** — это декларативный [GitOps-инструмент](../GitOps_overview.md) непрерывной доставки (CD) для Kubernetes. Он автоматизирует развертывание приложений и синхронизирует состояние кластера с Git-репозиторием, который выступает как основной источник конфигурации (Single Source of Truth).

Вся архитектура Argo CD базируется на **возможности расширения API Kubernetes** через механизмы пользовательских определений ресурсов (CRD) и операторов. Это позволяет управлять приложениями как нативными объектами кластера, обеспечивая глубокую интеграцию с экосистемой K8s.

**Желаемое состояние (Desired State)** — эталонная конфигурация ресурсов (YAML, Helm, Kustomize, Jsonnet, OCI-артефакты), хранящаяся в Git.
**Фактическое состояние (Live State)** — текущее состояние объектов, запущенных в кластере Kubernetes.
**Цикл сверки (Reconciliation Loop)** — непрерывный процесс сравнения желаемого и фактического состояний с последующим устранением расхождений.
**Application (Приложение)** — основная CRD Argo CD, связывающая источник в Git с целевым кластером и namespace.
**AppProject (Проект)** — логическая группа для реализации мультитенантности: ограничивает источники, назначения, типы ресурсов и роли доступа.
**ApplicationSet** — контроллер для массового управления приложениями на основе шаблонов и генераторов (входит в состав ядра v3.x).

## Основные концепции

### Назначение ArgoCD

- **Автоматизация развертывания:** устраняет ручное управление развертыванием через `kubectl apply`.
- **Мониторинг расхождений (Drift Detection):** постоянно следит за отклонением между состоянием Git и кластера и корректирует его.
- **Мультикластерность:** управление сотнями кластеров из одного экземпляра ArgoCD.
- **Контроль версий:** использование Git как единственного источника правды для аудита и отката.
- **Поддержка форматов:** работа с нативными манифестами Kubernetes, Helm-чартами, Kustomize, Jsonnet и **OCI-артефактами** (стандарт в v3.1+).

### Ключевые возможности

- **Веб-интерфейс и CLI:** визуальное отслеживание иерархии ресурсов и расширенное управление через терминал.
- **Интеграция с SSO:** поддержка OIDC, OAuth2, LDAP, SAML 2.0 (GitHub, GitLab, Microsoft Entra ID).
- **Гранулярный RBAC:** управление правами доступа (в v3.0+ разделены права на sync, update и delete).
- **ApplicationSet:** автоматизация создания приложений на основе шаблонов с поддержкой **ApplicationSet UI** (v3.5+).
- **Система уведомлений:** отправка оповещений через **[ArgoCD Notifications](./argocd_notifications.md)**.
- **Shallow Git Cloning (v3.3+):** ускорение работы с монорепозиториями за счет неглубокого клонирования.
- **Server-Side Apply (v3.x):** использование нативного механизма Kubernetes для разрешения конфликтов и применения больших манифестов.

### Архитектурный цикл сверки

Процесс синхронизации проходит следующие этапы:
1. **Refresh (Обновление):** `argocd-repo-server` клонирует репозиторий, рендерит манифесты (Helm/Kustomize/CMP) и кеширует результат.
2. **Diff (Сравнение):** `argocd-application-controller` запрашивает текущее состояние ресурсов из Kubernetes API и сравнивает его с отрендеренными манифестами.
3. **Sync (Синхронизация):** Если обнаружены расхождения (`OutOfSync`) и включен `Automated Sync`, контроллер применяет изменения.
4. **Health Check (Проверка здоровья):** Контроллер отслеживает успешность запуска подов и готовность сервисов.

### Статусы здоровья

ArgoCD отслеживает работоспособность ресурсов через следующие статусы:

| Статус | Описание |
| :--- | :--- |
| **Healthy** | Ресурс полностью работоспособен и готов к работе. |
| **Progressing** | Ресурс находится в процессе развертывания (например, обновление подов). |
| **Degraded** | Ошибка в работе ресурса (CrashLoopBackOff, ошибка конфигурации). |
| **Suspended** | Работа ресурса приостановлена (например, CronJob вне расписания). |
| **Missing** | Ресурс описан в Git, но отсутствует в кластере. |
| **Unknown** | Состояние не может быть определено (проблемы со связью с API-сервером). |

### Кастомные Health Checks (Lua)

Для CRD (Custom Resource Definitions) Argo CD использует Lua-скрипты для определения статуса здоровья. По умолчанию CRD считаются здоровыми сразу после создания, что может скрывать реальные проблемы.

**Пример Health Check для PostgreSQL Operator:**
```yaml
# argocd-cm ConfigMap
data:
  resource.customizations.health.acid.zalan.do_Postgresql: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.PostgresClusterStatus == "Running" then
        hs.status = "Healthy"
        hs.message = "Cluster is running"
        return hs
      end
    end
    hs.status = "Progressing"
    hs.message = "Waiting for cluster"
    return hs
```

**Пример Health Check для Cert-Manager:**
```yaml
data:
  resource.customizations.health.cert-manager.io_Certificate: |
    hs = {}
    if obj.status ~= nil then
      if obj.status.conditions ~= nil then
        for _, condition in ipairs(obj.status.conditions) do
          if condition.type == "Ready" and condition.status == "True" then
            hs.status = "Healthy"
            hs.message = "Certificate is ready"
            return hs
          end
        end
      end
    end
    hs.status = "Progressing"
    hs.message = "Waiting for certificate"
    return hs
```

### Двунаправленная синхронизация

ArgoCD не только применяет изменения, но и защищает кластер от ручных правок. Если ресурс изменен в обход Git, ArgoCD пометит его как `OutOfSync` и (при включенном `SelfHeal`) вернет к эталонному состоянию. Подробности: **[Синхронизация в ArgoCD](./synchronization.md)**.

### Методы отслеживания ресурсов (Resource Tracking)

Для того чтобы ArgoCD знал, какими ресурсами он управляет, используется механизм отслеживания. В v3.x поддерживаются следующие методы (настраиваются в `argocd-cm`):

| Метод | Механизм | Рекомендация |
| :--- | :--- | :--- |
| **Labels** | Метка `app.kubernetes.io/instance` | Стандарт, ограничение — длина значения метки (63 символа) |
| **Annotations** | Аннотация `argocd.argoproj.io/tracking-id` | Рекомендуется для избежания проблем с длиной имен |
| **annotation+label** | Оба метода одновременно | Максимальная совместимость |

**Важно:** При использовании Helm рекомендуется метод `annotation`, так как он не конфликтует с управлением аннотациями Helm.

**Подробное описание методов, миграция и примеры:** см. **[Отслеживание ресурсов](./argocd_resource_tracking.md)**.

### Ключевые абстракции

- **Application:** Основная единица управления (CRD). Представляет собой группу ресурсов, развертываемых как единое целое.
- **ApplicationSet:** Инструмент для массового управления приложениями на основе шаблонов.
- **AppProject (Project):** Логическая группа для реализации **мультитенантности**.

## Параметры синхронизации (Sync Options)

В манифесте `Application` поведение контроллера настраивается в двух секциях:
- `spec.syncPolicy.automated` — поля политики автоматической синхронизации (`enabled`, `prune`, `selfHeal`, `allowEmpty`);
- `spec.syncPolicy.syncOptions` — опции применения изменений:

| Параметр | Описание | По умолчанию |
| :--- | :--- | :--- |
| **CreateNamespace=true** | Автоматическое создание целевого Namespace, если он отсутствует. | false |
| **ServerSideApply=true** | Использование Server-Side Apply вместо Client-Side Apply. | false |
| **RespectIgnoreDifferences=true** | Использование настроек `ignoreDifferences` при синхронизации. | false |
| **SkipDryRunOnMissingResource=true** | Пропуск проверки `dry-run` для ресурсов, чьи CRD еще не созданы. | false |
| **Replace=true** | Использование `kubectl replace`/`create` вместо `apply` (для ресурсов, не помещающихся в аннотацию `last-applied-configuration`). | false |
| **ApplyOutOfSyncOnly=true** | Применение только ресурсов в статусе `OutOfSync` (оптимизация производительности). | false |

**Поля автоматической синхронизации (`spec.syncPolicy.automated`):** `prune` (удаление ресурсов, которых нет в Git), `selfHeal` (откат ручных правок), `allowEmpty` (синк при пустом репозитории) — все по умолчанию `false`; `enabled` (v3.1+) — явное вкл/выкл автосинка, `null` = включен.

**Пример использования:**
```yaml
spec:
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
    - ServerSideApply=true
    - RespectIgnoreDifferences=true
```

## Мультитенантность и AppProject

Объект `AppProject` обеспечивает изоляцию команд и проектов внутри одного экземпляра ArgoCD. Это ключевой механизм мультитенантности, определяющий границы (boundaries) того, **что** разрешено делать, тогда как RBAC определяет, **кто** может это делать.

**Основные возможности изоляции:**
- **Ограничение источников (Sources):** список разрешенных Git-репозиториев (`sourceRepos`).
- **Ограничение целей (Destinations):** список разрешенных кластеров и Namespaces (`destinations`).
- **Белые/чёрные списки ресурсов:** ограничение типов объектов (`clusterResourceWhitelist`, `namespaceResourceWhitelist`, `namespaceResourceBlacklist`).
- **Роли проекта (Project Roles):** внутренние роли для связки с группами в SSO/OIDC.
- **Окна синхронизации (Sync Windows):** временные периоды запрета/разрешения на деплой.
- **Квоты (Quotas):** лимиты на количество приложений и кластеров.

**Подробное руководство с примерами, квотами, кастомными ролями и best practices:** см. **[AppProject — изоляция проектов](./argocd_appproject_deep.md)**.

## Продвинутые шаблоны управления приложениями

### Шаблон «App-of-Apps»

Решает проблему управления самими объектами `Application` через GitOps. Вы создаете одно «корневое» приложение, которое указывает на директорию с описаниями дочерних приложений.

*   **Как это работает:**
    1.  **Корневое приложение (Root App):** Отслеживает директорию в Git, содержащую манифесты других приложений Argo CD (дочерних).
    2.  **Дочерние приложения (Child Apps):** Каждый манифест дочернего приложения указывает на директорию с фактическими ресурсами Kubernetes (Deployment, Service и т.д.).
    3.  **Рекурсивная синхронизация:** Argo CD синхронизирует корневое приложение, которое создает дочерние приложения, а те, в свою очередь, развертывают микросервисы в кластер.
*   **Преимущества:** Централизованное управление всей средой из одного источника, логическая группировка связанных сервисов и эффективный мониторинг статуса всей системы через один родительский объект.
*   **Когда использовать:**
    *   Начальная загрузка (bootstrapping) новых кластеров с фиксированным набором приложений.
    *   Группировка логически связанных микросервисов в единый блок управления.
    *   Реализация GitOps для самих ресурсов Argo CD при ограниченном количестве приложений.

#### Пример реализации

**1. Создание корневого приложения (root-app):**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/your-org/your-repo.git'
    targetRevision: HEAD
    path: root-apps
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

**2. Определение дочернего приложения (child-app1.yaml):**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: child-app1
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://github.com/your-org/your-repo.git'
    targetRevision: HEAD
    path: apps/child-app1
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### Шаблон «ApplicationSet»

**ApplicationSet** решает главную проблему масштабирования Argo CD: ручное создание и сопровождение сотен однотипных объектов `Application`. Вместо копирования YAML для каждого приложения или кластера описывается один шаблон и правила генерации параметров — а ApplicationSet Controller сам создаёт, обновляет и удаляет дочерние приложения.

**Ключевые возможности:**
- **Генераторы (Generators):** Источники параметров — List, Cluster, Git (Directories, Files), Pull Request, SCM Provider, Matrix, Merge, Plugin, Cluster Decision Resource.
- **goTemplate:** Современный режим шаблонизации с полным синтаксисом Go templates и функциями sprig.
- **Progressive Sync (RollingSync):** Поэтапная раскатка по группам кластеров (canary → production) с контролем `maxUpdate`.
- **Жизненный цикл:** Дочерние приложения — полноценные Application; ручные правки затираются следующей итерацией контроллера.

**Подробное руководство с каталогом генераторов, goTemplate, Pull Request generator, RollingSync и сравнением подходов:** см. **[ApplicationSet — генераторы приложений](./argocd_applicationsets.md)**.

## Сравнение: ArgoCD vs Flux

| Характеристика | ArgoCD | Flux (v2/v3) |
| :--- | :--- | :--- |
| **Архитектура** | Централизованный сервер + UI. | Распределенные контроллеров. |
| **Интерфейс** | Мощный Web UI и CLI. | Преимущественно CLI (`flux`). |
| **Мультикластерность** | Управление из одного "Hub" кластера. | Установка в каждый кластер (стандарт). |
| **Синхронизация** | Sync Waves, Hooks, политики. | Зависимости (DependsOn), лаконичность. |
| **Управление секретами** | Через плагины (AVP, SOPS). | Нативная поддержка SOPS. |

## Безопасность и мультитенантность

- **Принцип минимальных привилегий:** ArgoCD должен иметь доступ только к целевым Namespaces. Используйте `AppProject` для изоляции.
- **Аудит:** регулярный мониторинг журналов доступа и изменений.

### Механизмы отката

1.  **Git-откат (Рекомендуемый):** Выполнение `git revert` в репозитории. ArgoCD видит изменение в Git и синхронизирует кластер с предыдущим стабильным состоянием. Это сохраняет историю изменений в Git (SSoT).
2.  **UI-откат (Экстренный):** В веб-интерфейсе ArgoCD есть кнопка **Rollback**, позволяющая мгновенно откатиться к одной из предыдущих ревизий.
    - **Нюанс:** При UI-откате ArgoCD переходит в состояние `OutOfSync` относительно Git, так как версия в кластере больше не совпадает с версией в репозитории. Автоматическая синхронизация (`SelfHeal`) при этом временно отключается для этого приложения, чтобы не "перетереть" откат новым комитом из Git.
  3.  **CLI-откат:** Использование команды `argocd app rollback` для отката к указанной ревизии.

```bash
# Просмотр доступных ревизий
argocd app history my-app

# Откат к указанной ревизии
argocd app rollback my-app <revision>
```

### Архитектурные компоненты

Система состоит из следующих микросервисов:

| Компонент | Роль |
| :--- | :--- |
| **ArgoCD Repo Server (`argocd-repo-server`)** | Отвечает за работу с Git-репозиториями и рендеринг манифестов. Поддерживает **локальный кеш**, что оптимизирует производительность и снижает частоту операций выборки (git fetch). |
| **ArgoCD Application Controller (`argocd-application-controller`)** | Сердце системы, установленное в кластере. Реализует стандартный **Kubernetes controller pattern** для непрерывного мониторинга и согласования состояний. |
| **ArgoCD API Server (`argocd-server`)** | API-сервер, обслуживающий UI и CLI через **RESTful API**, что упрощает автоматизацию и интеграцию с внешними системами. |
| **ArgoCD Dex Server (`argocd-dex-server`)** | Обеспечивает интеграцию с внешними системами аутентификации. |
| **Redis (`argocd-redis`)** | Используется для кеширования данных и оптимизации запросов к API Kubernetes. |

### Манифест приложения

Основной ресурс ArgoCD, связывающий источник в Git с целевым окружением:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/argoproj/argocd-example-apps.git
    targetRevision: HEAD
    path: guestbook
  destination:
    server: https://kubernetes.default.svc
    namespace: guestbook
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
```

**Примечание по API:** Несмотря на то, что `v1alpha1` может выглядеть как предварительная версия, для Argo CD это стабильная и основная версия API, поддерживаемая в течение длительного времени для обеспечения обратной совместимости. Использование этой версии является стандартной практикой для ресурсов `Application` и `ApplicationSet`.

### Продвинутая сетевая связность (Teleport)

В крупномасштабных инфраструктурах ArgoCD подключается к удаленным кластерам через **Teleport Proxy** с использованием механизма `execProviderConfig`. Это позволяет:
- Исключить прямой сетевой доступ от ArgoCD до API-серверов целевых кластеров.
- Централизованно управлять доступом и аудитом через Access Plane.
- Использовать динамические учетные данные (через `tbot`).

Подробности реализации см. в руководстве: **[Управление политиками безопасности через GitOps (GitOps-мозг)](../Concepts/gitops-policy-management.md)**.

### Управление секретами

Для GitOps-подхода критически важно не хранить секреты в открытом виде:
- **[Sealed Secrets](../../Kubernetes/Security/sealed_secrets_overview.md):** шифрование для хранения в Git.
- **[ArgoCD Vault Plugin (AVP)](./argocd_vault_integration.md):** подстановка данных из Vault.
- **[SOPS](../../Security/Tools/sops_overview.md):** шифрование YAML-файлов.
- **VaultStaticSecret:** современный метод доставки секретов через Vault Secrets Operator, интегрированный в GitOps-пайплайны.

### Автоматическое обновление образов (Image Updater)

Компонент для автоматизации обновления тегов образов.
**Детальное руководство:** **[Argo CD Image Updater](./argocd_image_updater.md)**.

**Принцип работы:**
1. Мониторинг реестров образов (Harbor, Docker Hub).
2. Обновление манифестов через Git write-back или API.

## Практические сценарии

### Быстрый старт

```bash
# 1. Установка ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd --server-side --force-conflicts -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# 2. Ожидание готовности
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s

# 3. Получение первичного пароля
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo

# 4. Доступ к UI
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Откройте http://localhost:8080 (логин: admin, пароль из шага 3)

# 5. Установка CLI
brew install argocd  # macOS
# или
curl -sSL -o argocd https://github.com/argoproj/argo-cd/releases/latest/download/argocd-darwin-amd64
chmod +x argocd && sudo mv argocd /usr/local/bin/

# 6. Вход в CLI
argocd login localhost:8080 --username admin --password <password> --insecure
```

### Создание первого приложения

```bash
# Создание Application через CLI
argocd app create my-app \
  --repo https://github.com/argoproj/argocd-example-apps.git \
  --path guestbook \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace guestbook \
  --sync-policy automated \
  --auto-prune \
  --self-heal

# Синхронизация
argocd app sync my-app

# Просмотр состояния
argocd app get my-app
```

### Детальные руководства

- [**Установка и настройка ArgoCD**](./argocd_installation_and_setup.md) — пошаговое развёртывание.
- [**Интеграция с Helm**](./helm_integration.md) — работа с чартами.
- [**Синхронизация и политики**](./synchronization.md) — Sync Waves, Hooks и фазы.
- [**Настройка уведомлений**](./argocd_notifications.md) — Slack, Telegram, Email.
- [**Настройка SSO через GitLab**](./argocd_sso_gitlab.md) — авторизация и RBAC.
- [**Автоматизация через API и Ansible**](./argocd_api_automation.md) — управление без UI.
- [**Custom Tooling и плагины (CMP)**](./argocd_custom_tooling.md) — расширение функционала (QBEC, Helmwave).
- [**Динамические окружения с Crossplane**](./dynamic_environments_crossplane.md) — автоматизация стеков.

## Диагностика и мониторинг

### Базовые команды диагностики

```bash
# Просмотр состояния всех приложений
argocd app list

# Просмотр деталей конкретного приложения
argocd app get my-app

# Просмотр логов контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller -f

# Просмотр логов repo server
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server -f

# Просмотр событий в namespace argocd
kubectl get events -n argocd --sort-by='.lastTimestamp'

# Просмотр подов ArgoCD
kubectl get pods -n argocd -o wide
```

### Prometheus метрики

| Метрика | Описание |
| :--- | :--- |
| `argocd_app_info` | Информация о приложении (health_status, sync_status, project). |
| `argocd_app_sync_total` | Общее количество синхронизаций. |
| `argocd_app_reconcile` | Гистограмма длительности сверки, секунды. |
| `argocd_app_sync_duration_seconds_total` | Суммарная длительность синхронизаций, секунды. |

**Пример PromQL-запроса для поиска деградированных приложений:**
```promql
argocd_app_info{health_status="Degraded"} > 0
```

**Полное руководство по диагностике, мониторингу, типичным ошибкам, логам, метрикам и алертингу:** см. **[Диагностика и мониторинг Argo CD](./argocd_troubleshooting_and_monitoring.md)**.

## Валидация и проверка работоспособности

После установки и настройки Argo CD выполните следующие проверки:

**1. Проверка состояния компонентов:**
```bash
# Все поды должны быть в статусе Running
kubectl get pods -n argocd -o wide

# Проверка готовности API сервера
kubectl wait --for=condition=available deployment/argocd-server -n argocd --timeout=300s
```

**2. Проверка подключения к кластерам:**
```bash
# Список подключенных кластеров
argocd cluster list
# → SERVER                          NAME        STATUS      MESSAGE
# → https://kubernetes.default.svc  in-cluster  Successful
```

**3. Проверка синхронизации тестового приложения:**
```bash
# Создание тестового приложения
argocd app create test-app \
  --repo https://github.com/argoproj/argocd-example-apps.git \
  --path guestbook \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace guestbook

# Синхронизация и проверка статуса
argocd app sync test-app
argocd app get test-app
# → Status: Synced, Healthy
```

**4. Проверка метрик (если настроен Prometheus):**
```bash
# Запрос к метрикам контроллера
curl -s http://argocd-metrics:8082/metrics | grep argocd_app_info
```

## Лучшие практики

### Производительность

- **Используйте Server-Side Apply:** Включайте `ServerSideApply=true` для больших манифестов и кластеров с мутирующими контроллерами (HPA, cert-manager).
- **Ограничьте частоту сверки:** Настройте `selfHeal: false` для приложений, где ручные правки допустимы.
- **Используйте `ApplyOutOfSyncOnly=true`:** Оптимизирует применение только измененных ресурсов.
- **Shallow Git Cloning:** Используйте `--depth` для монорепозиториев (>1000 файлов).

### Безопасность

- **Используйте AppProject:** Всегда создавайте отдельные проекты для разных команд/окружений.
- **RBAC:** Ограничьте права доступа через AppProject Roles и SSO-группы.
- **Sync Windows:** Настройте окна запрета для Production в нерабочее время.
- **Sealed Secrets / AVP:** Никогда не храните секреты в открытом виде в Git.

### Надежность

- **App-of-Apps:** Используйте для bootstrapping и группировки связанных приложений.
- **ApplicationSet:** Используйте для динамических сред и масштабируемых инфраструктур.
- **Skip Reconcile:** Используйте `argocd.argoproj.io/skip-reconcile: "true"` (Alpha с v2.7.0) для полной остановки обработки приложения; на секрете кластера (с v3.4) — для всех приложений кластера.
- **HA режим:** Для production обязательно используйте HA установку (3 реплики каждого компонента, Redis HA, внешний Redis).

### Операции и очистка

**Удаление приложения с очисткой ресурсов:**
```bash
# Удаление приложения и всех управляемых ресурсов (prune)
argocd app delete my-app --cascade --yes

# Только удаление объекта Application, ресурсы в кластере остаются
argocd app delete my-app --no-cascade
```

**Очистка завершённых операций:**
```bash
# Удаление завершённых операций старше 24 часов
argocd app operations delete my-app --all --older-than 24h
```

**Полное удаление Argo CD (включая CRD и данные):**
```bash
# Удаление всех Application и ApplicationSet
argocd app list -o name | xargs -I {} argocd app delete {} --cascade --yes
argocd appset list -o name | xargs -I {} argocd appset delete {} --cascade --yes

# Удаление манифестов установки
kubectl delete -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Удаление CRD (требует кластер-админа)
kubectl get crd -l app.kubernetes.io/part-of=argocd -o name | xargs kubectl delete

# Удаление namespace
kubectl delete namespace argocd
```

**Очистка кэша repo-server (при проблемах с рендерингом):**
```bash
# Перезапуск repo-server для сброса кэша
kubectl rollout restart deployment/argocd-repo-server -n argocd
```

## Ограничения и edge cases

### Ограничения

1. **Лимит ресурсов:** Argo CD имеет внутренние лимиты на количество управляемых ресурсов. Для очень больших приложений (>1000 ресурсов) рекомендуется разбивать на несколько ApplicationSets.
2. **Cross-namespace ресурсы:** Приложение может управлять ресурсами в нескольких namespaces (включая cluster-scoped), если это разрешено AppProject и RBAC. Отдельные ApplicationSets нужны для логической группировки.
3. **ApplicationSet и `automated`:** Политика `syncPolicy.automated` из шаблона применяется для обычных приложений ApplicationSet; при стратегии RollingSync автосинк принудительно отключается контроллером ApplicationSet.
4. **Множественные ApplicationSets:** Если ресурс управляется несколькими ApplicationSets, возникает конфликт. Используйте `FailOnSharedResource=true`.
5. **Skip Reconcile:** Аннотация `argocd.argoproj.io/skip-reconcile: "true"` (на приложении или, с v3.4, на секрете кластера) останавливает всю обработку — статус не обновляется, синхронизации не выполняются.

### Edge Cases

1. **UI-откат и `OutOfSync`:** После UI-отката приложение переходит в состояние `OutOfSync` относительно Git. `SelfHeal` временно отключается для этого приложения.
2. **PreSync Hook и Sync Windows:** Если PreSync Hook (миграция БД) выполняется дольше Allow-окна: без `syncOverrun` операция приостанавливается контроллером (`Sync operation blocked by sync window`) и возобновляется, когда окно снова разрешит синхронизацию; с `syncOverrun: true` (v3.5+, на всех подходящих окнах) — завершается.
3. **Progressive Sync и Deny окно:** Если приложение попадает в Deny окно во время Progressive Sync, оно не будет синхронизировано до открытия Allow окна.
4. **Progressive Sync и ручная синхронизация:** Если вы вручную нажмете "Sync" на приложении, которое еще не подошло по очереди, оно будет синхронизировано, но это может нарушить логику `maxUpdate` текущего шага.
5. **PreDelete Hook и удаление ApplicationSet:** Если ApplicationSet удален во время выполняющейся синхронизации, операция завершится, но новые синхронизации будут невозможны.

## Дополнительная информация

### Основные изменения в ветке v3.x

- **Progressive Sync:** поэтапное развёртывание ApplicationSets.
- **Server-Side Apply:** стандарт для разрешения конфликтов.
- **PreDelete Hooks (v3.3):** выполнение Jobs перед удалением приложения.
- **OCI-нативность (v3.1):** поддержка Helm-чартов в OCI.

### Стратегии развертывания

ArgoCD интегрируется с **Argo Rollouts** для реализации:
- **Canary Deployment:** постепенное переключение трафика.
- **Blue/Green Deployment:** быстрое переключение между окружениями.

### См. также
- **[Сравнение ArgoCD и Flux](../argo_vs_flux_manifests.md)** — детальное сравнение инструментов GitOps.
- **[Установка и настройка ArgoCD](./argocd_installation_and_setup.md)** — пошаговое руководство.
- **[Диагностика и мониторинг](./argocd_troubleshooting_and_monitoring.md)** — поиск и устранение сбоев.
- **[RBAC — модель доступа](./argocd_rbac_deep.md)** — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- **[AppProject — изоляция проектов](./argocd_appproject_deep.md)** — Изоляция проектов, квоты, restrictions, кастомные роли.
- **[Multiple Sources и sourceHydrator](./argocd_multi_source_apps.md)** — Multiple Sources, sourceHydrator, Helm+Git, CI-рендеринг vs Multi-Source.
- **[Отслеживание ресурсов](./argocd_resource_tracking.md)** — Методы отслеживания ресурсов: Label, Annotation, Annotation+Label.
- **[Удаление и очистка](./argocd_deletion_and_cleanup.md)** — Prune, Cascading Deletion, Propagation Policy, Orphan, Finalizers.
- **[Disaster Recovery](./argocd_disaster_recovery.md)** — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.
- **[Безопасность](./argocd_security_hardening.md)** — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- **[Мультитенантность](./argocd_multi_tenancy.md)** — Паттерны мультитенантности, tenant isolation, project-per-team.

## Вопросы для собеседования

### Чем Server-Side Apply лучше client-side и когда без него не обойтись?
CSA хранит снимок в аннотации last-applied-configuration (лимит ~262 KB ломает большие CRD) и конфликтует с контроллерами, меняющими те же поля. SSA ведет владение полями на стороне API-сервера: корректные конфликты с HPA/cert-manager, поддержка больших ресурсов. Обязателен для крупных CRD и при нескольких менеджерах полей; в v3.x — рекомендуемый дефолт.

### Что произойдет при UI-Rollback при включенных automated + selfHeal?
Откат применит старую ревизию, но приложение уйдет OutOfSync относительно Git; Argo CD временно отключит автосинк для этого приложения, чтобы не перетереть откат. Follow-up обязателен: `git revert` приводит источник правды в соответствие, иначе после повторного включения автосинка вернется «плохая» ревизия.

### Методы tracking ресурсов — какой выбрать и почему?
Label `app.kubernetes.io/instance` — стандарт, но значение ограничено 63 символами и конфликтует с ownership Helm. Annotation `tracking-id` — длинные имена не проблема, рекомендован для Helm. `annotation+label` — максимальная совместимость ценой избыточности. Смена метода на живой системе требует миграции всех объектов.

### Как масштабировать Argo CD на тысячи приложений?
Sharding application-controller (`controller.sharding.algorithm`, кол-во реплик по нодам), `ApplyOutOfSyncOnly=true`, shallow git cloning монорепозиториев, масштабирование repo-server (реплики + кеш рендеринга), пересмотр `timeout.reconciliation`, Redis под нагрузкой. Диагностика узких мест — по метрикам reconcile/sync duration.

### AppProject и глобальный RBAC — зачем оба?
Глобальный RBAC отвечает «кто может нажимать кнопки» (UI/CLI/API). AppProject — границы того, ЧТО вообще можно сделать: whitelist источников, destinations, типов ресурсов, sync windows. Вместе это defense-in-depth: скомпрометированный аккаунт разработчика ограничен проектом даже при ошибках в policy.csv.
