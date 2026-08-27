# Argo CD: ApplicationSet — генераторы приложений и автоматизация флота

**ApplicationSet** решает главную проблему масштабирования Argo CD: ручное создание и сопровождение сотен однотипных объектов `Application`. Вместо копирования YAML для каждого приложения или кластера описывается один шаблон и правила генерации параметров — а ApplicationSet Controller сам создает, обновляет и удаляет дочерние приложения.

## Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| Argo CD | Линейка v3.x (ApplicationSet Controller входит в состав ядра, отдельная установка не требуется) |
| Права | Создание ApplicationSet — привилегированная операция (см. раздел «Безопасность»); для чтения источников — токен/PAT целевого Git-хостинга |
| CLI | `kubectl` с контекстом hub-кластера; `argocd` CLI той же минорной версии |
| Для PR-генератора | API-токен Git-хостинга (GitHub PAT / GitLab project access token) в объекте `Secret` |

Исходное состояние: установленный Argo CD ([руководство по установке](./argocd_installation_and_setup.md)), рабочий проект `default`, тестовый репозиторий со структурой `apps/<имя>/base` + `apps/<имя>/overlays`.

## Определения

- **ApplicationSet**: CRD (`argoproj.io/v1alpha1`), объединяющий один или несколько **генераторов** и **шаблон** объекта Application. Контроллер непрерывно сверяет множество сгенерированных приложений с текущими параметрами генераторов.
- **Генератор (Generator)**: Источник параметров — список кластеров, структура каталогов Git, открытые pull request'ы, файлы конфигурации. Каждый элемент источника превращается в набор переменных для подстановки в шаблон.
- **Шаблон (Template)**: Скелет объекта Application с плейсхолдерами (`{{.name}}`, `{{.cluster}}`). Рендерится один раз на каждый элемент параметров генератора.
- **Go-шаблоны (goTemplate)**: Современный режим шаблонизации (`spec.goTemplate: true`) с полным синтаксисом Go templates и функциями sprig; рекомендован во всей актуальной документации вместо устаревшего fasttemplate-подобного режима.
- **Владение (Ownership)**: Каждое сгенерированное приложение помечается аннотацией родительского ApplicationSet; контроллер имеет право изменять и удалять только свои приложения. При удалении ApplicationSet дочерние приложения удаляются согласно настроенной политике.

## Основные концепции

### Архитектура и цикл работы

```
┌─────────────────┐    параметры     ┌──────────────────┐   рендер   ┌──────────────┐
│  Генератор(ы)    │ ───────────────> │ ApplicationSet   │ ─────────> │ Applications │
│ (Git/API/список) │                  │ Controller       │  create/   │  в кластере   │
└─────────────────┘                  │ (цикл опроса)    │  update/   └──────────────┘
                                     └──────────────────┘  delete
```

Цикл контроллера:

```bash
# Наблюдение за работой контроллера в ядре v3.x
kubectl logs -n argocd deployment/argocd-applicationset-controller -f
# -> ApplicationSet preview-envs: generated 3 applications (MR #42, #43, #45)

# Все дочерние приложения видны как обычные Application
argocd app list
# → NAME                PROJECT        SYNC STATUS   HEALTH
# → billing-pr-42       finance-team   Synced        Healthy
# → billing-prod        finance-team   Synced        Healthy
```

Ключевые следствия модели:
- **Дочерние приложения — полноценные Application**: к ним применимы весь арсенал Argo CD (sync waves, hooks, RBAC, AppProject-ограничения, уведомления).
- **Источник правды — генератор**: чтобы удалить приложение из кластера, нужно удалить его источник (каталог, MR, элемент списка), а не сам Application.
- **Ручные правки дочерних приложений затираются** следующей итерацией контроллера — ApplicationSet всегда приводит свои приложения к отрендеренному виду.

### Каталог генераторов

| Генератор | Источник параметров | Типовой сценарий |
| :--- | :--- | :--- |
| **List** | Явный YAML-список пар «параметр-значение» | Небольшое фиксированное множество окружений |
| **Cluster** | Зарегистрированные в Argo CD кластеры (и их метки) | Раскатка стека на все/часть кластеров флота |
| **Git: Directories** | Подкаталоги репозитория | Монорепозиторий: приложение на каждый каталог `apps/*` |
| **Git: Files** | JSON/YAML-файлы в репозитории | Конфигурация как данные: параметры каждого приложения в отдельном файле |
| **Pull Request** | Открытые MR/PR через API Git-хостинга | Preview-окружения на каждый merge request |
| **SCM Provider** | Список репозиториев организации через API GitHub/GitLab/Bitbucket | Онбординг всех репозиториев с манифестами автоматически |
| **Matrix** | Декартово произведение двух генераторов | Окружения × кластеры |
| **Merge** | Объединение выводов нескольких генераторов с переопределением | Базовый список + локальные исключения/правки |
| **Plugin** | Внешний сервис, возвращающий параметры по HTTP/RPC | Интеграция с внутренними реестрами сервисов |
| **Cluster Decision Resource** | Внешний контроллер решает, на какие кластеры деплоить | Продвинутые сценарии размещения (placement) |

Любой генератор можно дополнительно фильтровать **Post Selector**'ом — выражением над уже сгенерированными параметрами, что позволяет строить сложные условия без вложенности.

### Pull Request Generator

Механика: контроллер опрашивает API Git-хостинга каждые `requeueAfterSeconds` (по умолчанию 30 минут — обязательно уменьшайте или настраивайте вебхук), для каждого подходящего MR рендерит приложение; при закрытии MR или потере соответствия критериям приложение **удаляется автоматически**. Доступные параметры шаблона: `.branch`, `.number`, `.head_sha`, `.author`, `.title` и другие.

Поддерживаемые провайдеры: `github`, `gitlab`, `gitea`, `bitbucketServer`, `bitbucket` (Cloud). Фильтрация — по меткам, состоянию (`pullRequestState`) или регулярным выражениям (`filters.branchMatch`, `filters.titleMatch`).

Жизненный цикл делает генератор идеальным для preview-окружений: создали MR — появилось окружение, смержили/закрыли — исчезло вместе со всеми ресурсами.

### Шаблонизация: goTemplate

```yaml
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]   # ошибка вместо пустой строки при отсутствии поля
  template:
    metadata:
      name: 'app-{{.values.env}}'
    spec:
      source:
        # функции sprig доступны напрямую
        targetRevision: '{{ .branch | trimPrefix "release/" | default "main" }}'
```

Практические правила:
- Всегда включайте `missingkey=error`: молчаливая подстановка пустых строк порождает приложения с невалидными именами и путями, которые трудно диагностировать.
- Имена приложений обязаны быть DNS-совместимыми: нормализуйте параметры (`{{ .branch | lower | replace "/" "-" }}`).
- Экранирование: если значение может содержать спецсимволы Go-шаблонов (например, содержимое файлов из Git Files Generator), используйте `{{ .value | quote }}` или функции `toJson`.

### Политики жизненного цикла дочерних приложений

Поле `spec.syncPolicy` управляет тем, как контроллер обращается с созданными приложениями:

| Значение `applicationsSync` | Поведение | Когда использовать |
| :--- | :--- | :--- |
| `create-update` (по умолчанию) | Создает и обновляет; удаления вручную созданных не производит | Большинство случаев |
| `create-update-delete` | Полный контроль: удаляет приложения, пропавшие из генератора | Строгие флоты, где источник — единственная правда |
| `create-only` | Создает один раз, дальше приложения живут своей жизнью | Делегирование командам: шаблон задает стартовую точку |

Дополнительно:
- `preserveResourcesOnDeletion: true` — при удалении самого ApplicationSet дочерние приложения остаются в кластере (защита от случайного каскада; детали механизмов удаления — в [Удалении и очистке](./argocd_deletion_and_cleanup.md)).
- Приложения можно защитить от prune-удалений индивидуально аннотацией `argocd.argoproj.io/sync-options: Prune=false`.
- Устаревший механизм `strategy.spotStrategy`/`updatePolicy` заменен единой схемой `applicationsSync` — в новых манифестах используйте ее.

### Безопасность ApplicationSet

ApplicationSet — самая мощная абстракция Argo CD, и потому самая опасная при неправильном доступе:

1. **Только администраторы должны иметь право создавать/изменять ApplicationSet**: шаблон может сослаться на любой репозиторий и любой кластер, разрешенные на уровне сервера. RBAC-правило: `p, role:admin, applicationsets, *, */*, allow`.
2. **Шаблонизация поля `project` в связке с PR/SCM-генераторами опасна**: внешний пользователь, создающий MR, потенциально управляет значением `project` — и, следовательно, обходит ограничения AppProject. Если поле проекта шаблонизировано, доверять можно только MR из защищенных веток/репозиториев.
3. **Токены генераторов храните в Secrets** (`tokenRef.secretName`) и ограничивайте scope токена одним репозиторием/организацией — утечка такого токена раскрывает только метаданные MR, но не код.
4. Ограничения на конечные ресурсы все равно enforced на уровне AppProject и RBAC приложений — ApplicationSet не отменяет [изоляцию проектов](./argocd_appproject_deep.md).

## Практические сценарии

### Сценарий 1: Preview-окружение на каждый merge request (PR Generator)

Задача: для каждого MR в репозиторий приложения автоматически развернуть изолированное окружение с адресом вида `pr-<номер>.preview.example.com`; при закрытии MR — удалить.

```bash
# 1. Токен для чтения MR
kubectl create secret generic gitlab-mr-token -n argocd \
  --from-literal=token='glpat-xxxxxxxxxxxx'
# → secret/gitlab-mr-token created
```

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: preview-envs
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    - pullRequest:
        gitlab:
          project: "42"                      # ID проекта
          api: https://gitlab.example.com/   # для self-hosted
          tokenRef:
            secretName: gitlab-mr-token
            key: token
          pullRequestState: opened           # только открытые MR
          labels:
            - deploy-preview                 # и только с меткой
        requeueAfterSeconds: 300             # опрос раз в 5 минут
  template:
    metadata:
      name: 'preview-{{ .branch | lower | replace "/" "-" }}'
    spec:
      project: previews
      source:
        repoURL: https://gitlab.example.com/team/billing-api.git
        targetRevision: '{{ .head_sha }}'    # ровно коммит MR
        path: kubernetes/
        kustomize:
          namePrefix: 'pr-{{ .number }}-'
          images:
            - 'ghcr.io/org/billing-api:pr-{{ .number }}'
      destination:
        server: https://kubernetes.default.svc
        namespace: 'preview-pr-{{ .number }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

Проверка полного цикла:

```bash
# Разработчик открывает MR с меткой deploy-preview
sleep 320 && argocd app list | grep preview-
# → preview-feature-new-api   previews   Synced   Healthy

kubectl get ingress -n preview-pr-42
# → NAME              HOSTS                        ADDRESS
# → pr-42-billing     pr-42.preview.example.com    203.0.113.10

# MR закрыт — приложение исчезнет само после следующего опроса
sleep 320 && argocd app get preview-feature-new-api
# → ERROR: application 'preview-feature-new-api' not found
```

Чтобы реакция была мгновенной, настройте вебхук Git-хостинга на endpoint ApplicationSet-контроллера (`/api/webhook` того же сервиса, что и основной Argo CD) — тогда опрос остается лишь страховкой.

Богатая инфраструктура для preview (отдельные БД, очереди) поверх этого паттерна разбирается в [динамических окружениях с Crossplane](./dynamic_environments_crossplane.md).

### Сценарий 2: Раскатка платформенного стека на все кластера (Cluster Generator)

Задача: monitoring, ingress-контроллер и политики должны присутствовать в каждом кластере флота; новые кластеры получают стек автоматически после регистрации.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: platform-stack
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    - clusters:
        selector:
          matchExpressions:
            - key: tier
              operator: In
              values: ["platform", "workload"]   # кроме служебных
  template:
    metadata:
      name: 'stack-{{ .name }}'
    spec:
      project: platform
      sources:
        - repoURL: https://github.com/org/fleet-infra.git
          targetRevision: main
          path: 'platform/{{ .metadata.labels.environment }}'   # overlay по окружению кластера
          kustomize:
            patches:
              - target: { kind: ConfigMap, name: cluster-info }
                patch: |-
                  - op: replace
                    path: /data/clusterName
                    value: {{ .name }}
      destination:
        server: '{{ .server }}'                   # адрес конкретного spoke
        namespace: platform
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

Проверка:

```bash
argocd cluster list
# → SERVER                          NAME         VERSION   LABELS
# → https://prod-eu.k8s.internal    prod-eu      1.35      tier=workload,environment=prod
# → https://staging.k8s.internal    staging      1.36      tier=platform,environment=staging

kubectl get applications -n argocd -l argocd.argoproj.io/application-set-name=platform-stack
# → NAME            SYNC STATUS   HEALTH
# → stack-prod-eu   Synced        Healthy
# → stack-staging   Synced        Healthy
```

Механика регистрации самих кластеров, выбор топологии и изоляция fleet-конфигурации разобраны в [мульти-кластерных паттернах](../Concepts/multi_cluster_patterns.md).

### Сценарий 3: Монорепозиторий приложений (Git Directory Generator)

Задача: команда добавляет каталог `apps/<новый-сервис>` — приложение появляется без изменения инфраструктурного кода.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: monorepo-apps
  namespace: argocd
spec:
  goTemplate: true
  generators:
    - git:
        repoURL: https://github.com/org/apps-monorepo.git
        revision: main
        directories:
          - path: apps/*
          - path: apps/system-*       # второй путь с ведущим дефисом = исключение
            exclude: true
  template:
    metadata:
      name: '{{ .path.basename }}'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/apps-monorepo.git
        targetRevision: main
        path: '{{ .path.path }}/overlays/prod'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{ .path.basename }}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

Переменная `.path.path` содержит полный путь (`apps/billing`), `.path.basename` — последний сегмент (`billing`). Удаление каталога из Git приведет к удалению приложения контроллером (при политике `create-update-delete`) либо останется осиротевшим (при `create-update`) — выбирайте политику осознанно.

### Сценарий 4: Параметры приложений как данные (Git Files Generator)

Задача: владельцы сервисов описывают желаемые параметры в собственных файлах, платформа читает их без ревью инфраструктурного кода.

```yaml
# apps/billing/config.json в монорепозитории
{ "team": "finance", "replicas": 3, "image": "ghcr.io/org/billing:v1.9.2" }
```

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: data-driven-apps
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    - git:
        repoURL: https://github.com/org/apps-monorepo.git
        revision: main
        files:
          - path: 'apps/*/config.json'
  template:
    metadata:
      name: '{{ .path.basename }}'
    spec:
      project: '{{ .team }}'
      source:
        repoURL: https://github.com/org/charts.git
        chart: universal-service
        targetRevision: 2.4.1
        helm:
          parameters:
            - name: image.tag
              value: '{{ .image }}'
            - name: replicaCount
              value: '{{ .replicas }}'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{ .path.basename }}'
```

Файл целиком становится набором параметров шаблона: `.team`, `.replicas`, `.image` — плюс стандартные `.path.*`. Это основа паттерна self-service: команды меняют только свой JSON, PR проходит ревью владельцев каталога по CODEOWNERS.

### Сценарий 5: Комбинирование генераторов (Matrix) и исключений (Merge)

Матрица «приложение × кластер» и поэтапная раскатка по группам кластеров подробно показаны в [прогрессивной синхронизации](./synchronization/scenarios/progressive_sync.md) (Rolling Sync поверх Matrix Generator). Генератор Merge полезен, когда базовый список нужно переопределить точечно:

```yaml
generators:
  - list:
      elements:
        - env: dev
          replicas: "1"
        - env: prod
          replicas: "5"
  - merge:
      mergeKeys:
        - env
      generators:
        - list:
            elements:
              - env: prod
                replicas: "7"      # переопределяет базовое значение для prod
```

### Сценарий 6: Защита продакшена при работе с ApplicationSet

Комбинация политик для безопасной эксплуатации:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: production-apps
  namespace: argocd
spec:
  goTemplate: true
  syncPolicy:
    applicationsSync: create-update        # не удалять приложения, выпавшие из генератора
    preserveResourcesOnDeletion: true      # удаление ApplicationSet не трогает приложения
  generators:
    - list:
        elements:
          - name: payments
            namespace: payments
  template:
    metadata:
      annotations:
        argocd.argoproj.io/manifest-generate-cm-annotation: ""   # см. типовые проблемы
    spec:
      project: critical
      # ...
```

Проверка защиты:

```bash
# Попытка удалить ApplicationSet — приложения остаются
kubectl delete applicationset production-apps -n argocd && sleep 15
argocd app list | grep payments
# → payments   critical   Synced   Healthy    ← живо благодаря preserveResourcesOnDeletion
```

## Дополнительная информация

### App-of-Apps против ApplicationSet

| Критерий | App-of-Apps | ApplicationSet |
| :--- | :--- | :--- |
| Механика | Корневой Application указывает на каталог с манифестами других Application | Генераторы + шаблон, приложения создает контроллер |
| Добавление члена | Коммит нового Application-YAML в Git | Появление источника (каталог, MR, кластер, элемент списка) |
| Динамика | Статичен: состав меняется только коммитами | Динамичен: реагирует на внешние события (MR, новые кластеры) |
| Владение | Приложения независимы | Приложения принадлежат ApplicationSet и им управляются |
| Когда выбирать | Bootstrapping самого Argo CD, явный контроль состава | Однотипные множества, self-service, флоты |

Паттерны не конкурируют, а вкладываются: ApplicationSet часто живет внутри корневого приложения App-of-Apps.

### Типовые проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `initial generation attempted... failed` в событиях ApplicationSet | Ошибка шаблона или генератора (опечатка в параметре, недоступен API Git) | `kubectl describe applicationset <name>` — секция условий содержит точную причину; проверьте `missingkey=error` и токены |
| Приложение называется `app-` или путь пустой | Параметр отсутствует, fasttemplate подставил пустоту | Включить `goTemplate: true` c `missingkey=error` |
| MR закрыт, но приложение висит | Политика `applicationsSync: create-update` не удаляет пропавшие | Либо `create-update-delete`, либо ручная чистка; для preview-генератора удаление работает всегда |
| PR Generator не замечает новый MR часами | Дефолтный интервал опроса 30 минут | `requeueAfterSeconds: 300` + вебхук на `/api/webhook` |
| `Permission denied` при создании ApplicationSet пользователем | RBAC: право на `applications` не дает прав на `applicationsets` | Добавить отдельную политику `p, ..., applicationsets, ...` — выдавать только администраторам |
| Внешний MR создал приложение в чужом проекте | Шаблонизированное поле `project` берется из данных MR | Не шаблонизировать `project` для недоверенных источников либо ограничить MR защищенными ветками |
| После правки шаблона дочерние приложения не обновились | Кэш рендеринга / интервал реконсиляции | Аннотация `argocd.argoproj.io/refresh: hard` на ApplicationSet либо ожидание интервала контроллера |

**Связанные документы:**
- [Динамические окружения с Crossplane](./dynamic_environments_crossplane.md) — богатые preview-окружения с БД и S3.
- [Прогрессивная синхронизация](./synchronization/scenarios/progressive_sync.md) — Rolling Sync для поэтапной раскатки на флоте.
- [Обзор ArgoCD](./argocd_overview.md) — архитектура и паттерн App-of-Apps.

## Вопросы для собеседования

### Чем Pull Request Generator отличается от SCM Provider?
PR Generator опрашивает API открытых merge request'ов одного репозитория — классика preview-окружений на каждый MR. SCM Provider перечисляет **репозитории** организации (GitLab/GitHub/Bitbucket) и создает приложение на каждый подходящий репо — сценарий «мультитенантный монорепо-хостинг», когда команды приносят свои репозитории.

### Что произойдет с дочерними приложениями при удалении ApplicationSet?
По умолчанию — каскадное удаление всех сгенерированных Application (и их ресурсов). Защита: `preserveResourcesOnDeletion: true` оставляет приложения жить; дополнительно `policy.annotations` управляют тем, что происходит при потере связи с генератором.

### Зачем включать goTemplate вместо legacy fasttemplate?
Sprig-функции в шаблонах (default, upperCase, toJson), строгий контроль отсутствующих ключей (`missingkey=error` вместо молчаливой подстановки пустой строки) и валидация параметров до рендеринга — меньше «приложение называется app-» сюрпризов.

### Как не дать ApplicationSet задеть прод?
Фиксированный `project` в шаблоне (не из данных генератора), AppProject с жесткими destinations/resource whitelist'ами, sync windows для prod, RollingSync с maxUpdate для поэтапной раскатки, RBAC: права на `applicationsets` только у администраторов платформы.

### Назовите разницу между Matrix и Merge генераторами.
Matrix комбинирует параметры двух генераторов декартовым произведением (кластеры × ветки). Merge берет первый генератор как базу и **исключает/добавляет** элементы по правилам дополнительных — способ вырезать проблемные кластеры или переопределить параметры точечно.
