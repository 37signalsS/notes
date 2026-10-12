# Argo CD: ApplicationSet — генераторы приложений и автоматизация флота

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; ApplicationSet Controller встроен в ядро, поддержка goTemplate v2, Matrix/Merge генераторы, Progressive Syncs)

**ApplicationSet** решает главную проблему масштабирования Argo CD: ручное создание и сопровождение сотен однотипных объектов `Application`. Вместо копирования YAML для каждого приложения или кластера описывается один шаблон и правила генерации параметров — а ApplicationSet Controller сам создает, обновляет и удаляет дочерние приложения в соответствии с настроенными политиками.

## Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| Argo CD | Линейка v3.x (ApplicationSet Controller входит в состав базового дистрибутива, отдельная установка не требуется) |
| Права доступа | Создание ApplicationSet — привилегированная операция уровня кластерного администратора; для чтения Git/SCM источников — токен с минимально необходимыми правами (read-only) |
| Инструменты CLI | `kubectl` с контекстом управляющего (hub) кластера; `argocd` CLI той же минорной версии |
| Секреты для генераторов | API-токен Git-хостинга (GitLab Project/Group Access Token, Gitea Token, Bitbucket Token) в объекте `Secret` в namespace `argocd` |
| Окружение | Bare-metal или on-premise Kubernetes кластеры (v1.28+), управляемые центральным hub-кластером Argo CD ([руководство по установке](./argocd_installation_and_setup.md)) |

Исходное состояние: рабочий Argo CD, целевые кластеры зарегистрированы через `argocd cluster add` (или Secret-манифесты), тестовый Git-репозиторий со структурой приложений и оверлеев Kustomize/Helm.

## Определения

- **ApplicationSet**: Пользовательский ресурс Kubernetes (`argoproj.io/v1alpha1`, kind: `ApplicationSet`), объединяющий один или несколько **генераторов** и **шаблон** объекта `Application`. Контроллер непрерывно сверяет состояние сгенерированных приложений с текущими параметрами генераторов.
- **Генератор (Generator)**: Источник параметров для шаблонизации (структура каталогов Git, конфигурационные файлы JSON/YAML, открытые Pull/Merge Requests, список зарегистрированных кластеров, фиксированные списки значений). Каждый элемент источника формирует набор пар ключ-значение.
- **Шаблон (Template)**: Каркас объекта `Application` с плейсхолдерами (`{{.name}}`, `{{.cluster}}`, `{{.path.basename}}`). Рендерится один раз для каждого набора параметров, возвращенного генератором.
- **goTemplate**: Режим шаблонизации (`spec.goTemplate: true`), использующий нативный синтаксис Go text/template и функции библиотеки Sprig. Рекомендован и является де-факто стандартом взамен устаревшего fasttemplate-синтаксиса.
- **Владение (Ownership & Finalizers)**: Каждое сгенерированное приложение помечается аннотацией владельца `argocd.argoproj.io/application-set-name: <имя-appset>` и контролируется финализатором `resources-finalizer.argocd.argoproj.io`. При удалении ApplicationSet дочерние приложения обрабатываются согласно параметру `preserveResourcesOnDeletion`.
- **Post Selector**: Механизм фильтрации параметров генератора с помощью выражений Kubernetes labelSelector над уже полученными переменными до передачи их в шаблон.
- **Progressive Syncs**: Механизм поэтапного выката (`spec.strategy.type: RollingSync`), управляющий последовательностью применения изменений на группе дочерних приложений с контролем состояния здоровья (health gating).

## Основные концепции и архитектура

### Архитектура и цикл работы контроллера

```
┌────────────────────────────────────────────────────────────────────────┐
│ Hub Kubernetes Cluster (Namespace: argocd)                             │
│                                                                        │
│  ┌────────────────────────┐      Опрос API / Webhook                   │
│  │ Git / SCM / Clusters   │ ───────────────────────────────┐           │
│  └────────────────────────┘                                │           │
│                                                            ▼           │
│  ┌────────────────────────┐  Параметры     ┌────────────────────────┐  │
│  │ ApplicationSet CRD     │ ─────────────> │ ApplicationSet         │  │
│  │ (Генераторы + Шаблон)  │                │ Controller             │  │
│  └────────────────────────┘                │ (Reconciliation Loop)  │  │
│                                            └────────────────────────┘  │
│                                                            │           │
│                                                            │ Рендеринг │
│                                                            │ и сверка  │
│                                                            ▼           │
│               ┌─────────────────────────────────────────────────────┐  │
│               │             Дочерние CRD Application                │  │
│               │ ┌─────────────────┐ ┌─────────────────┐ ┌─────────┐ │  │
│               │ │ app-cluster-01  │ │ app-cluster-02  │ │ app-... │ │  │
│               │ └─────────────────┘ └─────────────────┘ └─────────┘ │  │
│               └─────────────────────────────────────────────────────┘  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Application Controller применяет манифесты
                                    ▼
       ┌─────────────────────────────────────────────────────────┐
       │     Целевые кластеры и пространства имен (Spokes)       │
       │     (Workloads: Deployments, StatefulSets, Services)    │
       └─────────────────────────────────────────────────────────┘
```

Цикл работы контроллера (`Reconciliation Loop`):
1. **Сбор параметров генераторов**: Контроллер опрашивает источники данных (Git-репозитории, API локального кластера с объектами Secrets кластеров, API Git-хостинга).
2. **Фильтрация и трансформация**: Применение Post Selectors, слияние генераторов (Merge) или вычисление декартова произведения (Matrix).
3. **Рендеринг шаблона**: Подстановка параметров в блок `spec.template` через движок `goTemplate`.
4. **Сверка множества приложений (Reconciliation)**:
   - Если приложение из параметров отсутствует в кластере — оно создается (`create`).
   - Если спецификация существующего приложения отличается от отрендеренной — она обновляется (`update`).
   - Если приложение пропало из генератора — оно удаляется (`delete`) в зависимости от политики `spec.syncPolicy.applicationsSync`.

```bash
# Проверка работы контроллера ApplicationSet в namespace argocd
kubectl logs -n argocd deployment/argocd-applicationset-controller -f --tail=50
# → time="2026-10-11T21:40:12Z" level=info msg="generated 6 applications for ApplicationSet default/infra-fleet"
# → time="2026-10-11T21:40:12Z" level=info msg="syncing Application default/infra-fleet-prod-db-01"

# Просмотр созданных дочерних приложений
argocd app list -l argocd.argoproj.io/application-set-name=infra-fleet
# → NAME                 PROJECT   SYNC STATUS   HEALTH STATUS
# → infra-fleet-dc1-k8s  infra     Synced        Healthy
# → infra-fleet-dc2-k8s  infra     Synced        Healthy
```

Важные свойства модели:
- **Дочерние объекты — стандартные Application**: к ним применимы все штатные механизмы Argo CD: волны синхронизации ([Sync Waves и Hooks](./synchronization/scenarios/sync_waves_hooks.md)), [Окна синхронизации (Sync Windows)](./synchronization/scenarios/sync_windows.md), [RBAC](./argocd_rbac_deep.md).
- **Идемпотентность и затирание локальных правок**: если администратор вручную изменит параметры дочернего `Application` через `kubectl edit`, следующая итерация ApplicationSet Controller вернет манифест к отрендеренному шаблону.
- **Очистка и защита**: удаление самого ресурса `ApplicationSet` приводит к удалению всех дочерних приложений, если не установлена опция `spec.syncPolicy.preserveResourcesOnDeletion: true`.

---

### Каталог генераторов

| Генератор | Источник параметров | Назначение и типовой сценарий |
| :--- | :--- | :--- |
| **List** | Явный статический массив элементов в YAML | Небольшие статические окружения (`dev`, `stage`, `prod`) с индивидуальными портами/репликами |
| **Cluster** | Секреты целевых кластеров, зарегистрированные в Argo CD | Раскатка системного ПО (Ingress, мониторинг, CNI) по меткам кластеров во всем парке серверов |
| **Git: Directories** | Структура подкаталогов в Git-репозитории | Монорепозиторий микросервисов: один каталог — одно приложение |
| **Git: Files** | Файлы JSON или YAML в репозитории | Data-driven подход: каждый сервис описывается файлом параметров `config.json` / `values.yaml` |
| **Pull Request** | API Git-хостинга (GitLab, Gitea, Bitbucket) | Автоматические динамические preview-окружения на каждый открытый Merge Request |
| **SCM Provider** | API организации Git-хостинга | Сканирование всех репозиториев команды/организации и онбординг сервисов без ручных манифестов |
| **Matrix** | Декартово произведение двух независимых генераторов | Мультипликация: `Кластеры × Микросервисы` или `Окружения × Регионы` |
| **Merge** | Объединение списков с переопределением по ключам (`mergeKeys`) | Базовый шаблон для 20 кластеров + специфические оверлеи/реплики для 2 критичных кластеров |
| **Plugin** | Внешний gRPC/HTTP сервис, возвращающий JSON-параметры | Интеграция с корпоративной CMDB, NetBox или внутренней базой инвентаря оборудования |
| **Cluster Decision Resource** | Внешний CRD в Kubernetes (например, Open Cluster Management Placement) | Размещение нагрузок динамическими планировщиками на основе загрузки нод и топологии |

---

### Pull Request Generator (Preview-окружения)

Генератор Pull Request опрашивает API Git-хостинга с периодичностью `requeueAfterSeconds` (по умолчанию 30 минут — в боевых условиях рекомендуется уменьшать до 180–300 секунд либо настраивать прием Webhook).

Поддерживаемые on-premise и корпоративные провайдеры:
- `gitlab`: локальные и self-hosted инсталляции GitLab CE/EE.
- `gitea`: легковесный self-hosted Git-сервис.
- `bitbucketServer`: корпоративный Bitbucket Data Center / Server.
- `github`: Enterprise Server / Cloud.

Доступные переменные шаблона:
- `{{ .number }}` — номер PR / MR.
- `{{ .branch }}` — имя ветки источника (head branch).
- `{{ .branch_slug }}` — DNS-безопасная строка из имени ветки (длина до 63 символов, спецсимволы заменены на `-`).
- `{{ .target_branch }}` — целевая ветка (base branch, например `main`).
- `{{ .head_sha }}` — полный SHA коммита, на который указывает PR.
- `{{ .labels }}` — список меток PR (позволяет фильтровать окружения, например создавать только при наличии метки `deploy-preview`).

---

### Движок шаблонизации: goTemplate

Современный режим шаблонизации включается директивой `spec.goTemplate: true`. Он исключает двусмысленности парсинга и дает доступ к 100+ функциям трансформации строк и структур данных:

```yaml
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  template:
    metadata:
      name: '{{ .name | lower | trunc 50 | trimSuffix "-" }}'
    spec:
      project: default
      source:
        repoURL: '{{ .repoURL | default "https://git.internal.corp/platform/base.git" }}'
        targetRevision: '{{ .revision | default "HEAD" }}'
        helm:
          values: |
            replicaCount: {{ .replicas | default 2 }}
            environment: {{ .env | quote }}
```

Критические правила безопасного шаблонирования:
1. **Опция `missingkey=error` обязательна**: по умолчанию Go template при отсутствии ключа подставляет пустую строку. Это приводит к созданию приложений с именами `app--prod` или пустым `repoURL`, которые ломают синхронизацию. `missingkey=error` немедленно переводит ApplicationSet в статус ошибки и логирует имя отсутствующего поля.
2. **DNS-1123 валидация имен**: имена объектов `Application` и пространств имен должны состоять только из строчных букв, цифр и дефисов, начинаться и заканчиваться буквой/цифрой и не превышать 63 символов. Всегда используйте фильтры `lower`, `replace "/" "-"`, `trunc 50`.
3. **Экранирование конфигураций**: при генерации многострочных values или вставке строк со спецсимволами используйте `quote` или `toJson`.

---

### Политики жизненного цикла дочерних приложений

Поле `spec.syncPolicy` управляет тем, как контроллер обрабатывает расхождения между генератором и состоянием кластера:

```yaml
spec:
  syncPolicy:
    applicationsSync: create-update       # create-update | create-update-delete | create-only
    preserveResourcesOnDeletion: true     # не удалять Application при удалении ApplicationSet
```

| Режим `applicationsSync` | Создание | Обновление | Удаление пропавших | Сценарий применения |
| :--- | :---: | :---: | :---: | :--- |
| `create-update` (по умолчанию) | Да | Да | **Нет** | Безопасный production: случайное удаление каталога из Git не уничтожит приложение |
| `create-update-delete` | Да | Да | **Да** | Строгий GitOps и preview-окружения: если ветка/каталог удалены, приложение вычищается |
| `create-only` | Да | **Нет** | **Нет** | Bootstrap шаблонов: генерирует базовый Application, далее разработчики правят его независимо |

Удаление ресурсов и каскадность:
- Если `preserveResourcesOnDeletion: false` (по умолчанию), удаление ApplicationSet запускает финализатор, который каскадно удаляет все порожденные объекты `Application`. Если у этих `Application` включен каскадный финализатор `resources-finalizer.argocd.argoproj.io`, Kubernetes **физически удалит все поды, сервисы и PVC в кластерах**!
- Для production-инсталляций **всегда** выставляйте `preserveResourcesOnDeletion: true`.

---

### Безопасность и многопользовательская изоляция (SRE / DevOps)

1. **Разграничение прав RBAC**:
   - Манифест `ApplicationSet` обладает кластерными полномочиями: шаблон может указать любой целевой кластер и любой репозиторий.
   - Обычные пользователи и команды разработчиков **не должны** иметь прав на создание/редактирование CRD `applicationsets`.
   - В политиках Argo CD RBAC доступ ограничивается администраторами платформы:
     ```csv
     p, role:platform-admin, applicationsets, *, */*, allow
     p, role:developer, applicationsets, get, */*, allow
     ```
2. **Уязвимость подмены проекта (`spec.template.spec.project`)**:
   - Если генератор читает непроверенный источник (например, PR от внешних контрибьюторов или Git Files Generator, где разработчик сам правит `config.json`), параметр `{{ .project }}` нельзя брать напрямую из генератора.
   - Злоумышленник может указать `project: default` вместо ограниченного `project: team-isolated`, обойдя белые списки кластеров и репозиториев ([подробнее в изоляции проектов](./argocd_appproject_deep.md)).
   - Правило: жестко фиксируйте проект (`project: tenant-apps`) в самом манифесте ApplicationSet.
3. **Хранение токенов Git**:
   - Токены доступа к SCM должны монтироваться исключительно через ссылки на секреты:
     ```yaml
     tokenRef:
       secretName: gitlab-token-secret
       key: token
     ```
   - Токены должны обладать правами `read_repository` / `read_api` без права записи.

---

## Практические сценарии

### Сценарий 1: Preview-окружение для Merge Request (PR Generator в self-hosted GitLab)

**Задача:** Автоматически разворачивать изолированное окружение приложения в тестовом bare-metal кластере на каждый открытый MR с меткой `deploy-preview`. При закрытии или мерже MR — полностью удалять окружение и освобождать ресурсы.

1. Создание секрета с токеном доступа GitLab:

```bash
kubectl create secret generic gitlab-ci-token -n argocd \
  --from-literal=token='glpat-SecretTokenReadOnly2026'
# → secret/gitlab-ci-token created
```

2. Манифест `ApplicationSet`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: billing-preview-environments
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  syncPolicy:
    applicationsSync: create-update-delete   # удалять приложения при закрытии MR
    preserveResourcesOnDeletion: false
  generators:
    - pullRequest:
        gitlab:
          project: "158"                     # ID проекта в GitLab
          api: https://git.internal.corp/    # Внутренний self-hosted GitLab
          tokenRef:
            secretName: gitlab-ci-token
            key: token
          pullRequestState: opened
          labels:
            - deploy-preview
        requeueAfterSeconds: 180             # Интервал резервного опроса (3 минуты)
  template:
    metadata:
      name: 'preview-billing-mr-{{ .number }}'
      labels:
        environment: preview
        mr-id: '{{ .number }}'
    spec:
      project: previews                      # AppProject с жесткими лимитами квот
      source:
        repoURL: https://git.internal.corp/fintech/billing-service.git
        targetRevision: '{{ .head_sha }}'
        path: deploy/kustomize/overlays/preview
        kustomize:
          namePrefix: 'mr{{ .number }}-'
          images:
            - 'registry.internal.corp/fintech/billing:{{ .head_sha | trunc 8 }}'
      destination:
        server: https://kubernetes-test.internal.corp:6443
        namespace: 'preview-billing-{{ .number }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

3. Проверка жизненного цикла:

```bash
# Разработчик выставил метку deploy-preview в MR #104
kubectl get applications -n argocd -l mr-id=104
# → NAME                     PROJECT    SYNC STATUS   HEALTH STATUS
# → preview-billing-mr-104   previews   Synced        Healthy

# Проверка созданных ресурсов в целевом кластере
kubectl --context=k8s-test get pods -n preview-billing-104
# → NAME                               READY   STATUS    RESTARTS   AGE
# → mr104-billing-58797f77b8-x2k41     1/1     Running   0          2m

# После закрытия MR в GitLab контроллер удаляет Application
kubectl logs -n argocd deployment/argocd-applicationset-controller --tail=20 | grep "mr-104"
# → time="2026-10-11T21:42:00Z" level=info msg="Deleting Application preview-billing-mr-104 as PR #104 is closed"
```

---

### Сценарий 2: Раскатка системного платформенного стека (Cluster Generator)

**Задача:** Обеспечить единый набор системных сервисов (например, Node Exporter, Promtail, локальный Ingress NGINX) на всех подключенных bare-metal кластерах. При добавлении нового кластера стек должен раскатываться автоматически.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: fleet-node-monitoring
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  syncPolicy:
    applicationsSync: create-update          # не удалять при временном сбое связи
    preserveResourcesOnDeletion: true        # сохранить мониторинг при манипуляциях с AppSet
  generators:
    - clusters:
        selector:
          matchExpressions:
            - key: environment
              operator: In
              values: ["staging", "production"]
            - key: node-exporter-enabled
              operator: NotIn
              values: ["false"]
  template:
    metadata:
      name: 'node-exporter-{{ .name }}'
    spec:
      project: platform-system
      sources:
        - repoURL: https://git.internal.corp/infra/k8s-platform.git
          targetRevision: main
          path: manifests/system/node-exporter
          helm:
            values: |
              clusterName: {{ .name | quote }}
              datacenter: {{ index .metadata.labels "datacenter" | default "dc-default" | quote }}
      destination:
        server: '{{ .server }}'
        namespace: monitoring-system
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

Проверка применения:

```bash
# Список целевых кластеров и их меток
argocd cluster list
# → SERVER                                      NAME        STATUS      LABELS
# → https://k8s-core-dc1.internal.corp:6443     dc1-prod    Successful  environment=production,datacenter=dc1
# → https://k8s-core-dc2.internal.corp:6443     dc2-prod    Successful  environment=production,datacenter=dc2

# Проверка созданных приложений мониторинга
kubectl get applications -n argocd -l argocd.argoproj.io/application-set-name=fleet-node-monitoring
# → NAME                    SYNC STATUS   HEALTH STATUS
# → node-exporter-dc1-prod  Synced        Healthy
# → node-exporter-dc2-prod  Synced        Healthy
```

---

### Сценарий 3: Монорепозиторий микросервисов (Git Directory Generator)

**Задача:** Автоматически регистрировать приложения при появлении нового подкаталога в Git-каталоге `services/*`, игнорируя служебные каталоги и шаблоны.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: backend-services-monorepo
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  syncPolicy:
    applicationsSync: create-update-delete
    preserveResourcesOnDeletion: true
  generators:
    - git:
        repoURL: https://git.internal.corp/backend/monorepo.git
        revision: master
        directories:
          - path: services/*
          - path: services/_*                # исключение вспомогательных каталогов
            exclude: true
          - path: services/shared-libs       # исключение библиотек общего пользования
            exclude: true
  template:
    metadata:
      name: 'svc-{{ .path.basename }}'
    spec:
      project: backend
      source:
        repoURL: https://git.internal.corp/backend/monorepo.git
        targetRevision: master
        path: '{{ .path.path }}/k8s'
      destination:
        server: https://kubernetes.default.svc
        namespace: 'backend-{{ .path.basename }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

Параметры пути, предоставляемые генератором:
- `{{ .path.path }}`: полный путь относительно корня репозитория (например, `services/auth-service`).
- `{{ .path.basename }}`: имя конечного каталога (например, `auth-service`).
- `{{ .path.filename }}`: имя родительского каталога или файла.

---

### Сценарий 4: Параметры как данные (Git Files Generator)

**Задача:** Делегировать командам настройку параметров приложений без прямого доступа к манифестам Kubernetes. Команда коммитит в репозиторий файл `app-config.json` с описанием реплик, образов и ресурсов.

Содержимое файла `services/payment-gateway/app-config.json`:

```json
{
  "appName": "payment-gateway",
  "team": "billing-team",
  "replicas": 4,
  "ingressHost": "payments.internal.corp",
  "resources": {
    "requests": { "cpu": "200m", "memory": "512Mi" },
    "limits": { "cpu": "1000m", "memory": "1Gi" }
  }
}
```

Манифест `ApplicationSet`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: data-driven-microservices
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    - git:
        repoURL: https://git.internal.corp/deployments/apps-configs.git
        revision: main
        files:
          - path: "services/*/app-config.json"
  template:
    metadata:
      name: '{{ .appName }}'
    spec:
      project: default
      source:
        repoURL: https://git.internal.corp/helm/universal-microservice.git
        chart: universal-microservice
        targetRevision: 1.8.0
        helm:
          values: |
            replicaCount: {{ .replicas }}
            ingress:
              enabled: true
              host: {{ .ingressHost | quote }}
            resources:
              requests:
                cpu: {{ .resources.requests.cpu | quote }}
                memory: {{ .resources.requests.memory | quote }}
              limits:
                cpu: {{ .resources.limits.cpu | quote }}
                memory: {{ .resources.limits.memory | quote }}
      destination:
        server: https://kubernetes.default.svc
        namespace: 'app-{{ .appName }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

---

### Сценарий 5: Матричная генерация (Matrix) и переопределения (Merge)

**Задача:** Развернуть набор приложений во всех окружениях (`staging`, `production`) на нескольких датацентрах, при этом для production в DC2 переопределить количество реплик.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: fleet-matrix-deploy
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    # Merge генератор объединяет базовую матрицу и точечные переопределения
    - merge:
        mergeKeys:
          - app
          - clusterName
        generators:
          # Базовая матрица: Сервисы × Кластеры
          - matrix:
              generators:
                - list:
                    elements:
                      - app: user-api
                        replicas: "2"
                      - app: order-api
                        replicas: "3"
                - clusters:
                    selector:
                      matchLabels:
                        tier: workload
          # Точечные оверлеи для высоконагруженного кластера dc2-prod
          - list:
              elements:
                - app: order-api
                  clusterName: dc2-prod
                  replicas: "10"             # переопределяет replicas для order-api на dc2-prod
  template:
    metadata:
      name: '{{ .app }}-{{ .name }}'
    spec:
      project: default
      source:
        repoURL: https://git.internal.corp/helm/services.git
        chart: '{{ .app }}'
        targetRevision: 1.0.0
        helm:
          parameters:
            - name: replicaCount
              value: '{{ .replicas }}'
      destination:
        server: '{{ .server }}'
        namespace: 'services'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

---

### Сценарий 6: Отказоустойчивая конфигурация для Production

**Задача:** Настроить управление флотом критических приложений с гарантией защиты от случайного удаления, опечаток в ветках Git и блокировкой непреднамеренного каскадного удаления сервисов.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: core-banking-fleet
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  syncPolicy:
    applicationsSync: create-update          # исключено автоматическое удаление
    preserveResourcesOnDeletion: true        # запрет каскадного удаления дочерних приложений
  generators:
    - clusters:
        selector:
          matchLabels:
            criticality: tier-0
  template:
    metadata:
      name: 'core-banking-{{ .name }}'
      annotations:
        # Предотвращает каскадное удаление физических ресурсов внутри k8s при удалении Application
        argocd.argoproj.io/sync-options: Prune=false
    spec:
      project: core-banking                  # изолированный AppProject с проверкой подписей коммитов
      source:
        repoURL: https://git.internal.corp/banking/core-ledger.git
        targetRevision: v2.14.2              # жестко зафиксированный релизный тег
        path: k8s/overlays/production
      destination:
        server: '{{ .server }}'
        namespace: banking-production
      syncPolicy:
        # Автоматический синк без prune для исключения случайного удаления баз и очередей
        automated:
          prune: false
          selfHeal: true
```

Проверка защиты:

```bash
# Удаление ApplicationSet не приводит к удалению дочерних Application
kubectl delete applicationset core-banking-fleet -n argocd
# → applicationset.argoproj.io "core-banking-fleet" deleted

argocd app list -l project=core-banking
# → NAME                         PROJECT        SYNC STATUS   HEALTH STATUS
# → core-banking-dc1-prod        core-banking   Synced        Healthy
# → core-banking-dc2-prod        core-banking   Synced        Healthy
# Приложения остались активными благодаря preserveResourcesOnDeletion: true
```

---

## Операции, администрирование и мониторинг

### Параметры запуска контроллера (SRE / Sysadmin)

Контроллер ApplicationSet запускается как Kubernetes Deployment `argocd-applicationset-controller` в пространстве имен `argocd`. Параметры конфигурации передаются через аргументы командной строки или ConfigMap `argocd-cmd-params-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  # Включение поэтапного выката Progressive Syncs
  applicationsetcontroller.enable.progressive.syncs: "true"
  # Настройка параллелизма reconciler workers (по умолчанию 50)
  applicationsetcontroller.concurrent.reconciliations: "30"
  # Адрес для экспорта метрик Prometheus
  applicationsetcontroller.metrics.addr: ":8080"
  # Лимит запросов к Git-серверу для предотвращения DoS
  applicationsetcontroller.git.submodule.enabled: "false"
```

Основные флаги запуска контейнера контроллера:
- `--enable-progressive-syncs`: включает поддержку `RollingSync` стратегий ([Progressive Syncs](./synchronization/scenarios/progressive_sync.md)).
- `--concurrent-reconciliations <int>`: число воркеров сверки ApplicationSet (при наличии 100+ AppSet увеличьте с 10 до 30–50).
- `--policy <sync|create-only|create-update|create-delete>`: глобальное переопределение политики создания/удаления приложений для всех ApplicationSet кластера.
- `--metrics-addr :8080`: порт для сбора метрик Prometheus.
- `--probe-addr :8081`: порт liveness/readiness проб Kubernetes.

### Мониторинг и метрики Prometheus

Контроллер отдает стандартные метрики в формате Prometheus на порту `8080` по пути `/metrics`.

| Метрика | Тип | Описание и применение в алертах |
| :--- | :--- | :--- |
| `argocd_appset_reconcile_total` | Counter | Общее количество циклов сверки (лейблы: `name`, `result="success"\|"error"`) |
| `argocd_appset_reconcile_duration_seconds` | Histogram | Длительность цикла сверки контроллера. Рост p99 указывает на троттлинг Git API |
| `argocd_appset_generator_reconcile_duration_seconds` | Histogram | Длительность опроса конкретного генератора (`generator_type="pullRequest"\|"git"\|...`) |
| `argocd_appset_application_changes_total` | Counter | Количество изменений в дочерних Application (`change="create"\|"update"\|"delete"`) |

Пример Prometheus AlertRule для мониторинга сбоев генераторов:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: argocd-applicationset-alerts
  namespace: argocd
spec:
  groups:
    - name: argocd-applicationset
      rules:
        - alert: ApplicationSetReconcileErrors
          expr: |
            rate(argocd_appset_reconcile_total{result="error"}[5m]) > 0
          for: 10m
          labels:
            severity: warning
            team: platform-sre
          annotations:
            summary: "Ошибки сверки ApplicationSet {{ $labels.name }}"
            description: "Контроллер не может отрендерить или обновить дочерние приложения более 10 минут. Проверьте токены SCM, синтаксис goTemplate или доступность Git."
```

### Эксплуатационные команды (CLI Reference)

```bash
# 1. Проверка статуса условий и ошибок генерации ApplicationSet
kubectl describe applicationset fleet-matrix-deploy -n argocd
# Секция Status -> Conditions отображает точные сообщения об ошибках парсинга

# 2. Форсирование немедленного пересканирования источников (Hard Refresh)
# Контроллер перерендерит шаблон без ожидания таймера requeueAfterSeconds
kubectl annotate applicationset billing-preview-environments -n argocd \
  argocd.argoproj.io/refresh="hard" --overwrite
# → applicationset.argoproj.io/billing-preview-environments annotated

# 3. Поиск всех приложений, созданных конкретным ApplicationSet
kubectl get applications -n argocd \
  -l argocd.argoproj.io/application-set-name=fleet-matrix-deploy \
  -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status
# → NAME                 SYNC     HEALTH
# → user-api-dc1-prod    Synced   Healthy
# → order-api-dc1-prod   Synced   Healthy

# 4. Проверка логов контроллера на предмет ошибок валидации Go-шаблонов
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-applicationset-controller \
  --tail=100 | grep -E "error|level=error"
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Сводная таблица типовых сбоев

| Симптом / Ошибка | Первопричина | Метод диагностики и исправление |
| :--- | :--- | :--- |
| `failed to execute template: map has no entry for key "..."` | Отсутствует ключ в источнике данных при включенном `missingkey=error` | 1. Выполните `kubectl describe applicationset <name>`.<br>2. Проверьте имена полей в файле JSON/YAML.<br>3. Используйте функцию Sprig `default`: `{{ .env \| default "dev" }}`. |
| `Application ... is invalid: metadata.name: Invalid value` | Имя приложения нарушает RFC 1123 (содержит `/`, `_`, прописные буквы или >63 знаков) | В шаблоне нормализуйте имя:<br>`{{ .branch \| lower \| replace "/" "-" \| trunc 50 }}`. |
| `HTTP 429 Too Many Requests` в логах при работе PR/SCM генератора | Исчерпан лимит запросов к API GitLab/Gitea/GitHub из-за частого опроса | 1. Увеличьте `requeueAfterSeconds` (минимум 300–600 с).<br>2. Настройте отправку Webhook от Git-хостинга на endpoint Argo CD. |
| При закрытии MR preview-приложение не удаляется | В `spec.syncPolicy` установлено значение `create-update` вместо `create-update-delete` | Измените манифест: установите `spec.syncPolicy.applicationsSync: create-update-delete`. |
| После правки шаблона в ApplicationSet приложения не обновляются | Кэширование параметров или длительный интервал реконсиляции | 1. Добавьте аннотацию `argocd.argoproj.io/refresh: hard`.<br>2. Проверьте права сервис-аккаунта контроллера на обновление ресурсов `Application`. |
| Дочернее приложение создается в ошибочном namespace | Отсутствует параметр создания namespace в политике синхронизации | Добавьте в `spec.template.spec.syncPolicy.syncOptions` директиву `- CreateNamespace=true`. |
| `Permission denied` при создании ApplicationSet пользователем | Отсутствуют права в кластерном RBAC Kubernetes или Argo CD RBAC | Пользователь должен обладать кластерными правами на CRD `applicationsets.argoproj.io`. Выдавайте только администраторам. |

### Пошаговый алгоритм отладки зависшего генератора

Если ApplicationSet не генерирует ожидаемые приложения:
1. **Проверьте условия в CRD**:
   ```bash
   kubectl get applicationset <имя-appset> -n argocd -o yaml
   ```
   В поле `status.conditions` ищите тип `ErrorOccurred` или `ParametersGenerated`.
2. **Проверьте сетевую связность и аутентификацию SCM**:
   Если используется self-hosted GitLab/Gitea, убедитесь, что Pod `argocd-applicationset-controller` имеет доступ к корпоративному Git через внутренний DNS и HTTP-прокси, а сертификат TLS доверен кластеру (вмонтирован в CA trust store).
3. **Проверьте фильтры Post Selector**:
   Если используется `selector.matchLabels` или `postSelector`, временно закомментируйте фильтр, чтобы убедиться, что генератор вообще отдает записи.
4. **Проверьте права на AppProject**:
   Если шаблон создает приложение в проекте `payments`, убедитесь, что в этом проекте разрешен доступ к целевому кластеру и репозиторию ([диагностика проектов](./argocd_appproject_deep.md)).

---

## Лучшие практики (Best Practices)

1. **Всегда включайте `spec.goTemplate: true` и `missingkey=error`**: Устаревший fasttemplate скрывает ошибки и подставляет пустые строки. Строгая валидация предотвращает развертывание испорченных конфигураций.
2. **Защищайте Production через `preserveResourcesOnDeletion: true`**: Случайное удаление манифеста `ApplicationSet` в Git не должно приводить к каскадной ликвидации продакшн-сервисов.
3. **Ограничивайте права на создание ApplicationSet**: Предоставляйте доступ к `kind: ApplicationSet` только инженерам платформы через жесткий кластерный RBAC.
4. **Никогда не берите `project` из недоверенных данных генератора**: Фиксируйте имя проекта жесткой константой, чтобы внешний PR или конфигурационный файл не мог развернуть нагрузку в чужой изолированный namespace.
5. **Используйте Webhook вместо агрессивного Polling**: Для PR и Git генераторов настраивайте вебхуки на `/api/webhook`. Это снижает нагрузку на Git-сервер и обеспечивает мгновенную реакцию на коммиты.
6. **Нормализуйте все генерируемые имена через Sprig**: Все имена объектов и пространств имен должны принудительно обрезаться (`trunc 50`) и приводиться к нижнему регистру (`lower`) во избежание сбоев валидации Kubernetes API.
7. **Используйте `requeueAfterSeconds` осознанно**: Не выставляйте опрос чаще одного раза в 180 секунд без реальной необходимости, чтобы не исчерпать квоты внутренних API.
8. **Разделяйте генерацию инфраструктуры и бизнес-приложений**: Не объединяйте раскатку Ingress/CNI и приложений команд в один гигантский ApplicationSet.
9. **Контролируйте размер Matrix Generator**: Декартово произведение 20 кластеров на 50 веток генерирует 1000 объектов `Application`, создавая пиковую нагрузку на etcd и Kubernetes API.
10. **Интегрируйте Progressive Syncs для критических раскаток**: Для обновлений на десятках кластеров используйте стратегию `RollingSync` с canary-шагами вместо одновременного обновления всего флота.

---

## Дополнительная информация

### Сравнение подходов: App-of-Apps и ApplicationSet

| Критерий сравнения | Паттерн App-of-Apps | Контроллер ApplicationSet |
| :--- | :--- | :--- |
| **Механизм управления** | Корневой объект `Application`, разворачивающий дочерние манифесты `Application` из Git | Специализированный контроллер, генерирующий `Application` на основе внешних источников данных |
| **Добавление нового сервиса** | Ручное написание и коммит нового YAML-файла `Application` в репозиторий | Автоматическое обнаружение по факту появления каталога, файла, MR или кластера |
| **Динамические сценарии (PR)** | Не поддерживаются (требуют внешних скриптов в CI/CD) | Нативная поддержка через Pull Request Generator |
| **Масштабирование на флот** | Сложное сопровождение сотен файлов манифестов | Один декларативный манифест масштабируется на сотни кластеров |
| **Порог входа** | Минимальный (стандартный синтаксис Argo CD) | Средний (требуется понимание генераторов и Go-шаблонов) |
| **Рекомендуемая сфера** | Начальный bootstrap самого Argo CD и базовых системных чартов | Автоматизация флота кластеров, self-service платформы, динамические окружения |

### Связанные документы

- [Обзор архитектуры Argo CD](./argocd_overview.md) — базовые компоненты, цикл синхронизации и паттерн App-of-Apps.
- [Установка и базовая настройка Argo CD](./argocd_installation_and_setup.md) — развертывание управляющего hub-кластера.
- [Глубокое погружение в RBAC](./argocd_rbac_deep.md) — настройка политик разграничения доступа к ApplicationSet и проектам.
- [Изоляция и AppProject](./argocd_appproject_deep.md) — разграничение доступа к кластерам и пространствам имен.
- [Прогрессивная синхронизация (Progressive Syncs)](./synchronization/scenarios/progressive_sync.md) — стратегии RollingSync и канареечные раскатки на флоте.
- [Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md) — механика финализаторов, каскадное удаление и защита ресурсов.
- [Мультикластерные паттерны GitOps](../Concepts/multi_cluster_patterns.md) — сетевые топологии и управление парком кластеров.

---

## Вопросы для собеседования

### 1. Как устроен жизненный цикл дочерних приложений при удалении самого ApplicationSet?
**Ответ:** По умолчанию контроллер регистрирует финализатор на ресурсе `ApplicationSet`. При удалении `ApplicationSet` контроллер каскадно удаляет все созданные им объекты `Application`. Если у этих `Application` настроен стандартный финализатор ресурсов `resources-finalizer.argocd.argoproj.io`, Argo CD удалит все связанные нагрузки в Kubernetes. Чтобы разорвать каскад и сохранить работающие приложения при удалении или пересоздании ApplicationSet, в спецификации манифеста задается параметр `spec.syncPolicy.preserveResourcesOnDeletion: true`.

### 2. Почему опасно динамически шаблонизировать поле `spec.template.spec.project`?
**Ответ:** Если значение для `project` берется из ненадежного источника данных (например, из PR открытого репозитория или пользовательского `config.json`), автор изменений может подставить привилегированный проект (например, `default` или `platform-admins`). Это позволит приложению развернуться в защищенные пространства имен (например, `kube-system`) или на production-кластеры в обход установленных в AppProject ограничений белых списков. Для предотвращения таких атак проект должен быть жестко зафиксирован в манифесте ApplicationSet.

### 3. Чем генератор Matrix отличается от генератора Merge?
**Ответ:** Генератор **Matrix** выполняет декартово произведение (Cartesian product) двух генераторов. Например, 3 кластера × 4 микросервиса сформируют 12 приложений. Генератор **Merge** берет результат работы первого (базового) генератора и обновляет или дополняет параметры записей на основе совпадения ключей `mergeKeys` со вторым генератором. Это позволяет задать единые дефолтные параметры для десятков кластеров и точечно переопределить значения (например, реплики или URL) для выделенных кластеров.

### 4. Для чего включается параметр `spec.goTemplateOptions: ["missingkey=error"]`?
**Ответ:** По умолчанию Go-шаблонизатор при обращении к несуществующему ключу объекта возвращает пустую строку без генерации ошибки. В результате формируются некорректные имена (`app--staging`), пустые пути к репозиториям или дефектные селекторы, которые приводят к труднодиагностируемым сбоям в работе контроллера. Опция `missingkey=error` заставляет рендерер немедленно завершать генерацию с явной ошибкой в статусе ApplicationSet при отсутствии любого ожидаемого параметра.

### 5. Как защитить Git-хостинг от исчерпания API rate limits при использовании PR Generator на крупном флоте?
**Ответ:** Основные меры:
1. Увеличить значение `requeueAfterSeconds` (например, с дефолтных или частых опросов до 300–600 секунд).
2. Настроить входящие Webhooks от GitLab/Gitea/GitHub на контроллер Argo CD (endpoint `/api/webhook`), что позволяет перевести обнаружение событий в режим push, оставив периодический опрос только в качестве страховки.
3. Использовать фильтрацию по меткам (`labels`) или регулярным выражениям веток (`branchMatch`), чтобы контроллер не опрашивал метаданные всех открытых запросов в организации.
