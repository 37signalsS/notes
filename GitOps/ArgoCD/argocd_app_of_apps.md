# Argo CD: Паттерн App of Apps и структура GitOps-репозиториев

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; Kubernetes 1.28–1.32+; bare-metal / on-premise)

> **Контекст развертывания:** Паттерн **App of Apps** («Приложение приложений») — фундаментальный архитектурный шаблон Argo CD, позволяющий декларативно управлять десятками и сотнями независимых приложений через единый корневой ресурс `Application`. В отличие от `ApplicationSet`, генерирующего приложения по строгим однотипным шаблонам, App of Apps обеспечивает максимальную гибкость: каждое дочернее приложение может иметь собственный репозиторий, тип шаблонизатора (Helm, Kustomize, чистый YAML, CMP v2) и независимый жизненный цикл. Паттерн используется для полного бутстрапа кластера («Cluster Bootstrap from zero») и разделения ответственности между инфраструктурными и сервисными командами.

## Определения

**App of Apps (Приложение приложений)** — архитектурный паттерн GitOps, при котором один родительский (root) ресурс `Application` в Argo CD указывает на Git-директорию или Helm-чарт, содержащий манифесты других дочерних ресурсов `Application` (child apps).

**Root Application (Корневое приложение)** — экземпляр `Application`, развертываемый оператором вручную или через первичный bootstrap-скрипт. Его единственной задачей является синхронизация и отслеживание дочерних манифестов `Application`.

**Child Application (Дочернее приложение)** — декларативный ресурс `Application`, сгенерированный или примененный корневым приложением. Дочернее приложение непосредственно управляет рабочими нагрузками (Deployment, StatefulSet, Ingress, CRD) в целевом пространстве имен.

**Cluster Bootstrap (Первичная инициализация кластера)** — процесс развертывания всех базовых сервисов кластера (Ingress, Cert-Manager, мониторинг, CNI/CSI, хранилища) путем применения единственного манифеста корневого приложения.

**Directory-per-environment (Каталог на окружение)** — подход к организации GitOps-репозитория, при котором конфигурации для разных сред (`dev`, `stage`, `prod`) хранятся в отдельных директориях одной ветки (например, `envs/dev`, `envs/prod`). Является признанным индустриальным стандартом GitOps.

**Branch-per-environment (Ветка на окружение)** — подход, при котором каждая среда изолирована в отдельной ветке Git (`dev`, `stage`, `main`). В GitOps-сообществе считается антипаттерном из-за риска накопления дрейфа (configuration drift), конфликтов слияния и сложности поддержания идентичности манифестов.

**Каскадное удаление (Cascading Deletion)** — процесс, при котором удаление ресурса `Application` с установленным финалайзером `resources-finalizer.argocd.argoproj.io` приводит к автоматическому удалению всех дочерних ресурсов в кластере Kubernetes.

**Sync Waves на объектах Application** — использование аннотации `argocd.argoproj.io/sync-wave` непосредственно в манифестах `kind: Application` для задания строгой очередности развертывания между разными приложениями внутри App of Apps.

---

## Архитектура и базовые концепции

### Внутренний жизненный цикл App of Apps

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Архитектура паттерна App of Apps                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ 1. Git Repository (Инфраструктурный репозиторий)                            │
│    └── bootstrap/root-app/                                                  │
│        ├── 00-namespaces.yaml                                               │
│        ├── 10-infra-monitoring.yaml       (kind: Application, wave: "1")    │
│        ├── 20-infra-ingress.yaml          (kind: Application, wave: "1")    │
│        ├── 30-app-databases.yaml          (kind: Application, wave: "2")    │
│        └── 40-app-backend.yaml            (kind: Application, wave: "3")    │
│                     │                                                       │
│                     │ 1. kubectl apply -f root-application.yaml             │
│                     ▼                                                       │
│ 2. Argo CD Control Plane (Namespace: argocd)                                │
│    ┌──────────────────────────────────────────────────────────────┐         │
│    │  Root Application: "cluster-bootstrap"                       │         │
│    │  (Отслеживает состояние файлов в bootstrap/root-app/)        │         │
│    └──────────────────────────────┬───────────────────────────────┘         │
│                                   │ Синхронизирует child apps               │
│         ┌─────────────────────────┼─────────────────────────┐               │
│         ▼ (Wave 1)                ▼ (Wave 2)                ▼ (Wave 3)      │
│    ┌──────────────┐          ┌──────────────┐          ┌──────────────┐     │
│    │ Child App:   │          │ Child App:   │          │ Child App:   │     │
│    │ "monitoring" │          │ "databases"  │          │ "backend"    │     │
│    └──────┬───────┘          └──────┬───────┘          └──────┬───────┘     │
│           │                         │                         │             │
│           ▼                         ▼                         ▼             │
│ 3. Target Kubernetes Workloads (в целевых namespaces)                       │
│    Prometheus / Grafana      PostgreSQL StatefulSet    Deployment / Ingress │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Сравнительный анализ: App of Apps vs ApplicationSet

| Критерий | App of Apps | ApplicationSet |
| :--- | :--- | :--- |
| **Принцип работы** | Статические манифесты `Application` в Git | Динамическая генерация через контроллер по шаблонам |
| **Гетерогенность источников** | **Высокая:** каждое приложение может иметь свой репозиторий, плагин (Helm, Kustomize, CMP) и параметры | **Средняя/Низкая:** все сгенерированные приложения подчиняются единой структуре генератора |
| **Сложность внедрения** | Минимальная (чистый Kubernetes YAML без дополнительных CRD) | Требует изучения генераторов (Git, Cluster, List, Matrix) |
| **Массовое масштабирование** | Трудоемко при добавлении сотен однотипных сервисов (требует ручного создания YAML) | **Идеально:** автоматическое добавление приложений при создании папки или ветки |
| **Каскадное удаление** | Управляется финалайзерами на каждом конкретном `Application` | Удаление ApplicationSet удаляет все сгенерированные им `Application` |
| **Очередность деплоя** | **Да:** поддерживаются Sync Waves на манифестах `Application` | Поддерживается через механизм Progressive Sync (rolling sync) |
| **Основное назначение** | Бутстрап кластера, развертывание разнородной инфраструктуры | Массовый деплой микросервисов по множеству кластеров |

---

## Практические сценарии

### Сценарий 1: Классический Bootstrapping кластера с разделением слоев

Сценарий реализует развертывание кластера с тремя уровнями зависимости:
1. Системный уровень (Волна 1: cert-manager, ingress-nginx).
2. Хранилище данных (Волна 2: postgresql).
3. Бизнес-приложение (Волна 3: payment-api).

**1. Манифест корневого приложения (`root-application.yaml`):**

> [!WARNING]
> Никогда не добавляйте финалайзер `resources-finalizer.argocd.argoproj.io` на корневое приложение (`Root Application`)! Если на корневом приложении висит финалайзер, случайное удаление root-app приведет к немедленному каскадному удалению всех дочерних приложений и уничтожению всей инфраструктуры кластера.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cluster-root
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd-bootstrap
spec:
  project: default
  source:
    repoURL: 'https://git.company.internal/gitops/cluster-management.git'
    targetRevision: main
    path: bootstrap/root
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: argocd
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ApplyOutOfSyncOnly=true
```

**2. Дочерние манифесты в директории `bootstrap/root/` репозитория:**

**Файл `bootstrap/root/01-infra-ingress.yaml`:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: infra-ingress-nginx
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "1"
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: 'https://git.company.internal/gitops/cluster-management.git'
    targetRevision: main
    path: infrastructure/ingress-nginx
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: ingress-nginx
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**Файл `bootstrap/root/02-database-postgres.yaml`:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: storage-postgres
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "2"
  finalizers:
    # Защита PVC и базы данных при удалении
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: 'https://git.company.internal/gitops/cluster-management.git'
    targetRevision: main
    path: infrastructure/postgres
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: storage
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

**Файл `bootstrap/root/03-app-payment.yaml`:**
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: app-payment-api
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "3"
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: 'https://git.company.internal/apps/payment-service.git'
    targetRevision: main
    path: envs/prod
  destination:
    server: 'https://kubernetes.default.svc'
    namespace: payment
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

```bash
# Бутстрап кластера одной командой
kubectl apply -f root-application.yaml
# → result: application.argoproj.io/cluster-root created

# Проверка создания дерева приложений
argocd app list
# → result:
# NAME                 CLUSTER                         NAMESPACE      STATUS    HEALTH
# cluster-root         https://kubernetes.default.svc  argocd         Synced    Healthy
# infra-ingress-nginx  https://kubernetes.default.svc  ingress-nginx  Synced    Healthy
# storage-postgres     https://kubernetes.default.svc  storage        Synced    Healthy
# app-payment-api      https://kubernetes.default.svc  payment        Synced    Healthy
```

---

### Сценарий 2: Защита от катастрофического каскадного удаления

При эксплуатации App of Apps самой частой критической ошибкой инженера является удаление корневого приложения без флага сохранения ресурсов: `kubectl delete app cluster-root` или `argocd app delete cluster-root`.

**Матрица поведения финалайзеров в App of Apps:**

| Наличие финалайзера на Root App | Наличие финалайзера на Child App | Результат выполнения `kubectl delete app cluster-root` |
| :--- | :--- | :--- |
| **ДА (`resources-finalizer`)** | **ДА** | **КАТАСТРОФА:** Удаляются все объекты `Application`, и немедленно удаляются ВСЕ поды, БД, Ingress во всем кластере! |
| **НЕТ (рекомендуется!)** | **ДА** | **БЕЗОПАСНО:** Удаляется только манифест `cluster-root`. Все дочерние `Application` и их рабочие нагрузки продолжают функционировать без изменений. |
| **НЕТ** | **НЕТ** | **БЕЗОПАСНО:** Удаляется только `cluster-root`. Дочерние `Application` остаются. |

**Регламент безопасного удаления корневого приложения:**
```bash
# Удаление root-приложения БЕЗ каскадного удаления дочерних объектов
argocd app delete cluster-root --cascade=false
# → result: application 'cluster-root' deleted

# Если случайно запущено удаление с финалайзером, немедленно снять финалайзер:
kubectl patch application cluster-root -n argocd -p '{"metadata":{"finalizers":null}}' --type=merge
# → result: application.argoproj.io/cluster-root patched
```

---

### Сценарий 3: Организация структуры GitOps-репозитория для Production

В корпоративных on-premise инфраструктурах рекомендуется организация репозитория по схеме **Directory-per-environment** с использованием монорепозитория манифестов (Config Monorepo):

```text
gitops-repository/
├── bootstrap/                          # Точки входа App of Apps
│   ├── dev-root.yaml                   # Корневое приложение для Dev-кластера
│   ├── stage-root.yaml                 # Корневое приложение для Stage-кластера
│   └── prod-root.yaml                  # Корневое приложение для Prod-кластера
│
├── apps/                               # Манифесты дочерних приложений
│   ├── dev/                            # Директория child apps для Dev
│   │   ├── auth-service.yaml
│   │   └── billing-service.yaml
│   └── prod/                           # Директория child apps для Prod
│       ├── auth-service.yaml
│       └── billing-service.yaml
│
└── infrastructure/                     # Инфраструктурный слой (Kustomize/Helm)
    ├── base/
    │   ├── ingress-nginx/
    │   ├── cert-manager/
    │   └── monitoring/
    └── overlays/
        ├── dev/
        └── prod/
```

**Почему `Directory-per-environment` превосходит `Branch-per-environment`:**
1. **Отсутствие дрейфа:** В модели веток коммит в `dev` требует `git merge` в `stage` и затем в `prod`. Если между средами есть различия (разные реплики, пути), слияние вызывает постоянные конфликты (`merge conflicts`) или затирание production-параметров.
2. **Атомарность изменений:** Изменение глобальной инфраструктуры или обновление схемы сразу для всех сред выполняется одним коммитом и одним Pull Request в ветке `main`.
3. **Единый источник истины:** Ветка `main` содержит исчерпывающее состояние всех кластеров компании в любой момент времени.

---

### Сценарий 4: App of Apps на базе Helm-чарта (Параметризованный Root App)

Если дочерних приложений много, хранение десятков статичных файлов `Application` приводит к дублированию. Решение — использовать Helm-чарт в качестве корневого приложения, где дочерние приложения генерируются по списку из `values.yaml`.

**Структура чарта `bootstrap-chart/`:**
```text
bootstrap-chart/
├── Chart.yaml
├── templates/
│   └── applications.yaml
└── values.yaml
```

**Манифест `templates/applications.yaml`:**
```yaml
{{- range .Values.applications }}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {{ .name }}
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: {{ .wave | default "0" | quote }}
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: {{ .project | default "default" }}
  source:
    repoURL: {{ .repoURL }}
    targetRevision: {{ .targetRevision | default "main" }}
    path: {{ .path }}
  destination:
    server: {{ .destinationServer | default "https://kubernetes.default.svc" }}
    namespace: {{ .namespace }}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
---
{{- end }}
```

**Манифест `values.yaml`:**
```yaml
applications:
  - name: infra-cert-manager
    wave: "1"
    repoURL: "https://git.company.internal/infra/cert-manager.git"
    path: "envs/prod"
    namespace: "cert-manager"
  - name: core-database
    wave: "2"
    repoURL: "https://git.company.internal/infra/databases.git"
    path: "envs/prod"
    namespace: "db"
  - name: payment-backend
    wave: "3"
    repoURL: "https://git.company.internal/apps/payment.git"
    path: "envs/prod"
    namespace: "payment"
```

---

## Диагностика и устранение неполадок

| Проблема | Причина | Команда диагностики | Решение |
| :--- | :--- | :--- | :--- |
| **Корневое приложение постоянно в `OutOfSync`** | Корневое приложение отслеживает изменяемые контроллером поля дочерних `Application` (`status`, `operationState`). | `argocd app diff cluster-root` | Добавить исключение полей `status` и динамических аннотаций в секцию `ignoreDifferences` корневого приложения или глобально в `argocd-cm`. |
| **Случайное каскадное удаление всех сервисов** | Удален объект `cluster-root` с активным `resources-finalizer`. | `kubectl get events -n argocd --sort-by='.metadata.creationTimestamp'` | Немедленно выполнить `kubectl patch app <child-app> -p '{"metadata":{"finalizers":null}}'` для спасения рабочих нагрузок. |
| **Зависание фазы Sync Wave** | Дочернее приложение на волне `N` не переходит в статус `Healthy` (например, CrashLoopBackOff подов), блокируя волну `N+1`. | `argocd app get <child-app>` | Устранить проблему в дочернем приложении либо временно отключить зависимость, выставив одинаковый `sync-wave`. |
| **Дочерние приложения не создаются** | Некорректный `destination.namespace` у корневого приложения. Корневое приложение обязано разворачивать объекты `Application` в namespace `argocd`! | `kubectl describe app cluster-root -n argocd` | Убедиться, что в `spec.destination.namespace` корневого приложения указан именно `argocd`. |

---

## Лучшие практики

1. **Никогда не ставьте finalizer на Root Application:** Защищайте только дочерние приложения (`Child Applications`). Корневое приложение должно быть легко удаляемым и пересоздаваемым без риска для кластера.
2. **Используйте Sync Waves для инфраструктуры:** Базовые сервисы (CRD, CNI, Ingress, Cert-Manager) обязаны запускаться на волне `1`, хранилища данных — на волне `2`, а бизнес-сервисы — на волне `3`.
3. **Игнорируйте статус дочерних приложений в Root App:** Настройте в `cluster-root`:
   ```yaml
   ignoreDifferences:
     - group: argoproj.io
       kind: Application
       jsonPointers:
         - /status
   ```
4. **Ограничивайте права проектов (AppProject):** Разделяйте инфраструктурные дочерние приложения и прикладные сервисы по разным `AppProject` с ограничением разрешенных неймспейсов и типов ресурсов.
5. **Предпочитайте каталоги веткам:** Всегда используйте схему `Directory-per-environment`.

---

## Дополнительная информация

- [Argo CD: Архитектура и установка](./argocd_installation_and_setup.md) — Первичное развертывание и HA-архитектура.
- [Argo CD: ApplicationSets](./argocd_applicationsets.md) — Альтернативный метод массового развертывания по генераторам.
- [Argo CD: Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md) — Детальное описание работы финалайзеров и флага `--cascade`.
- [Синхронизация, Sync Waves и Hooks](./synchronization/scenarios/sync_waves_hooks.md) — Механика фаз и волн синхронизации.
- [Изоляция проектов AppProject](./argocd_appproject_deep.md) — Разграничение прав и квот для дочерних приложений.
- [Декомпозиция GitOps-репозиториев](../Concepts/gitops_decomposition.md) — Стратегии монорепозиториев и полирепозиториев.
