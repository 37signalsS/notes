# Мульти-кластерные паттерны в GitOps

Как только GitOps работает в одном кластере, следующий вопрос — управление парком: десятки кластеров (прод по регионам, стейджинг, выделенные кластеры команд) должны получать конфигурацию из Git с контролируемыми различиями и предсказуемой раскаткой. Этот файл систематизирует топологии, регистрацию кластеров и изоляцию fleet-конфигурации.

## Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| GitOps-агент | Argo CD v3.x (для hub-and-spoke) или Flux v2.9.x (pull-per-cluster); [сравнение моделей](../argo_vs_flux_manifests.md) |
| Учетные данные spoke | ServiceAccount с правами `cluster-admin`-подмножества либо kubeconfig; для Flux — deploy key/PAT на fleet-репозиторий в каждом кластере |
| Сеть | Доступ hub → Kubernetes API каждого spoke (Argo CD); для pull-per-cluster — только исходящие соединения к Git/OCI |
| Репозиторий | Fleet-репозиторий со структурой `clusters/<имя>/` и общими библиотеками конфигурации |

## Определения

- **Hub**: Центральный кластер/инстанс Argo CD, из которого управляются остальные.
- **Spoke**: Управляемый кластер без собственного «мозга» доставки — получает ресурсы от hub.
- **Fleet-репозиторий**: Git-репозиторий, описывающий конфигурацию всех кластеров: общие базовые компоненты + специфичные overlay на кластер.
- **Регистрация кластера (Registration)**: Процесс добавления spoke в область управления: создание учетных данных и объекта кластера в Argo CD (`Secret` типа `argocd.io/cluster`) либо bootstrap Flux в новом кластере.
- **Pull-per-cluster**: Топология, где каждый кластер самостоятельно тянет свою часть конфигурации из Git — центрального компонента доставки нет.
- **Fleet-wide drift**: Расхождение конфигураций между однотипными кластерами; главная проблема парков, которую GitOps решает структурой репозитория.

## Базовые концепции

### Выбор топологии

```text
Hub-and-Spoke                          Pull-per-cluster
┌──────────┐  управляет   ┌─────────┐   ┌─────────┐  тянет из Git  ┌────┐
│   Hub    │ ───────────> │ Spoke 1 │   │Spoke N  │ <───────────── │Git │
│ (ArgoCD) │              └─────────┘   └─────────┘                └────┘
└──────────┘  ───────────> ┌─────────┐   каждый кластер автономен:
                           │ Spoke 2 │   падение связи с Git ≠ потеря
                           └─────────┘   управления уже примененным
```

| Критерий | Hub-and-Spoke | Pull-per-cluster |
| :--- | :--- | :--- |
| Единая точка контроля и UI | Да | Нет (агрегация через внешние дашборды) |
| Входящая сеть к spoke | Нужна (hub ходит в API spoke) | Не нужна |
| Поведение при отказе hub | Спoke продолжают жить, но изменения не доставляются | Каждый кластер независим полностью |
| Секреты кластеров | Хранятся в hub (компрометация hub = компрометация флота) | Только локальные |
| Масштабирование | Шардирование application-controller'а | Естественное: кластеры не зависят друг от друга |
| Типичный размер | До нескольких десятков spoke | Сотни, edge |

Гибрид — распространенная зрелая практика: hub распространяет политики и системный стек, прикладные команды деплоят через локальные инстансы. Обзорная таблица выбора — в [обзоре методологии](../GitOps_overview.md).

### Регистрация кластеров

**В Argo CD** два способа, и их сочетание определяет безопасность:

1. Императивный: `argocd cluster add <context>` — создает Secret c kubeconfig в namespace argocd. Быстро, но не воспроизводимо.
2. Декларативный: манифест Secret с полем конфигурации коммитится в Git (или создается CI при создании кластера) — регистрация становится частью fleet-репозитория и переживает пересоздание hub.

Метка кластера (`metadata.labels`) — ключевой механизм маршрутизации: генераторы ApplicationSet выбирают целевые кластеры по меткам (`environment=prod`, `region=eu`), что отделяет инфраструктурный код от списка кластеров.

**Во Flux** регистрации как таковой нет: каждый кластер — самостоятельная единица, подключенная к своей ветке/пути fleet-репозитория через bootstrap. «Реестр» флота поддерживается внешне (таблица кластеров в infra-репозитории), а идемпотентность обеспечивается повторным запуском bootstrap ([сценарий DR во Flux](../flux.md)).

### Изоляция fleet-конфигурации

Структура репозитория важнее выбора инструмента:

```text
fleet-infra/
├── clusters/                  # точка входа каждого кластера
│   ├── prod-eu/
│   │   ├── infrastructure.yaml   # Kustomization/Application на аддоны
│   │   ├── apps.yaml             # Kustomization/Application на приложения
│   │   └── cluster-vars.json     # файлы-параметры (Git Files Generator)
│   └── staging/
├── platform/                  # общие аддоны: monitoring, ingress, policies
│   ├── base/ … overlays/{prod,staging}/
├── apps/                      # приложения: base + per-env overlays
└── policies/                  # Rego/Kyverno-политики флота
```

Правила гигиены:
- Различия кластеров — только через overlays и файлы параметров; копипаста манифестов между каталогами кластеров запрещена (иначе fleet-wide drift возвращается).
- Права на каталоги — через CODEOWNERS: платформенная команда ревьюит `platform/`, команды — свои `apps/*`.
- AppProject в hub ограничивает destination конкретными серверами/неймспейсами — ApplicationSet физически не сможет создать приложение в чужом кластере ([изоляция проектов](../ArgoCD/argocd_appproject_deep.md)).

### Распространение системного стека

Аддоны (monitoring, ingress, операторы политик) раскатываются теми же механизмами, что и приложения:

| Инструмент | Механизм |
| :--- | :--- |
| Argo CD | Root Application (App-of-Apps) либо ApplicationSet c Cluster Generator — см. [Сценарий 2 в ApplicationSet](../ArgoCD/argocd_applicationsets.md) |
| Flux | Общая Kustomization `platform` с `dependsOn`, подключаемая из `clusters/*/infrastructure.yaml`; вариации — через overlays |
| Политики безопасности | Отдельный контур: hub распространяет ConstraintTemplates/ClusterPolicy на все spoke — разбор в [управлении политиками](./gitops-policy-management.md) |

### Day-2: обновление конфигурации флота

- Поэтапность обязательна: сначала staging, затем прод по группам регионов — реализуется Progressive Sync ([Rolling Sync](../ArgoCD/synchronization/scenarios/progressive_sync.md)) либо группами в List Generator.
- Версионный перекос контролируется политикой поддержки N-2: одновременно в парке допустимы не более трех минорных версий инструмента.
- Аудит расхождений: регулярная сверка фактических версий аддонов по кластерам (запросы к API каждого spoke / агрегированные метрики) против ожиданий fleet-репозитория.

## Практические сценарии

### Сценарий 1: Декларативная регистрация spoke в hub Argo CD

```bash
# 1. В spoke-кластере создать ServiceAccount для hub
kubectl create serviceaccount argocd-manager -n kube-system --context spoke-prod-eu
kubectl apply -f - --context spoke-prod-eu <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argocd-manager
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin          # в строгих средах — урезанная роль без escalation
subjects:
  - kind: ServiceAccount
    name: argocd-manager
    namespace: kube-system
EOF
# → clusterrolebinding.rbac.authorization.k8s.io/argocd-manager created

# 2. Получить токен SA (v1.30+ рекомендуют TokenRequest вместо вечных секретов)
kubectl create token argocd-manager -n kube-system --context spoke-prod-eu \
  --duration=8760h > /tmp/spoke-token
```

```yaml
# 3. Декларативная регистрация — коммитится в fleet-репозиторий
apiVersion: v1
kind: Secret
metadata:
  name: spoke-prod-eu
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster     # маркер для Cluster Generator
    environment: prod                            # метки маршрутизации
    region: eu
type: Opaque
stringData:
  name: prod-eu
  server: https://prod-eu.k8s.internal:6443
  config: |
    {
      "bearerToken": "<значение из /tmp/spoke-token>",
      "tlsClientConfig": { "insecure": false, "caData": "<base64 CA>" }
    }
```

Проверка:

```bash
argocd cluster list
# → SERVER                              NAME      VERSION  LABELS
# → https://prod-eu.k8s.internal:6443   prod-eu   1.35     environment=prod,region=eu

# Ротация токенов — плановая процедура (раз в год или при утечке):
kubectl create token argocd-manager ... && kubectl patch secret spoke-prod-eu ...
```

### Сценарий 2: Автоматическая раскатка аддонов на весь флот

Связка Cluster Generator + структура fleet-репозитория (манифесты — в [ApplicationSet, Сценарий 2](../ArgoCD/argocd_applicationsets.md)); здесь — проверка сквозной механики на примере добавления нового кластера:

```bash
# 1. Зарегистрировали spoke (Сценарий 1) с метками environment=prod, region=apac

# 2. ApplicationSet platform-stack подхватил кластер на следующей итерации
sleep 60 && argocd app list -l argocd.argoproj.io/application-set-name=platform-stack
# → stack-prod-apac   platform   OutOfSync   Progressing

# 3. Стек (monitoring + ingress + policies) применился автоматически
argocd app get stack-prod-apac
# → Status: Synced   Health: Healthy
# → Group Kind        Name                Status
# → apps Deployment   prometheus-server   Synced
# → networking Ingress ingress-public     Synced

# 4. Новый кластер получил ту же версию аддонов, что и остальные
kubectl --context spoke-prod-apac get deploy -n platform \
  -o jsonpath='{range .items[*]}{.metadata.name}={.spec.template.spec.containers[0].image}{"\n"}{end}'
# → prometheus-server=prom/prometheus:v3.7.2   ← совпадает с prod-eu
```

### Сценарий 3: Standalone-кластеры Flux из общего базового репозитория

Каждый кластер подключается к своему пути, но использует общие библиотеки:

```yaml
# clusters/prod-apac/apps.yaml — входная точка кластера
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
  namespace: flux-system
spec:
  interval: 30m
  dependsOn: [{ name: platform }]
  path: ./apps/prod                       # общий overlay для всего прода
  prune: true
  sourceRef: { kind: GitRepository, name: fleet-infra }
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: platform
  namespace: flux-system
spec:
  interval: 30m
  path: ./platform/overlays/prod          # общая платформа, региональных отличий нет
  prune: true
  wait: true
  timeout: 15m
  sourceRef: { kind: GitRepository, name: fleet-infra }
```

Bootstrap нового кластера сводится к одной команде с другим `--path` — идентичность флота обеспечивается общими путями, а не синхронизацией состояний. Полный план восстановления отдельного кластера — в [сценарии DR во Flux](../flux.md).

### Сценарий 4: Поэтапное обновление конфигурации флота

Задача: выкатить новую версию ingress-контроллера сначала на staging, затем на регионы prod по одному, с паузой для наблюдения.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: ingress-upgrade
  namespace: argocd
spec:
  goTemplate: true
  generators:
    - list:
        elements:
          - cluster: staging
            wave: "1"
          - cluster: prod-eu
            wave: "2"
          - cluster: prod-apac
            wave: "3"
  template:
    metadata:
      name: 'ingress-{{ .cluster }}'
      annotations:
        argocd.argoproj.io/sync-wave: '{{ .wave }}'
    spec:
      project: platform
      source:
        repoURL: https://github.com/org/fleet-infra.git
        targetRevision: main
        path: 'platform/ingress/overlays/{{ .cluster }}'
      destination:
        name: '{{ .cluster }}'
        namespace: ingress-system
      syncPolicy:
        automated: { prune: true, selfHeal: true }
```

Sync waves дают последовательность: wave 2 не начнется, пока wave 1 не достигнет Healthy — грубый, но надежный механизм; для проверки метрик между этапами используется Rolling Sync ([прогрессивная синхронизация](../ArgoCD/synchronization/scenarios/progressive_sync.md)), а внутри одного кластера — канарейка ([прогрессивная доставка](./progressive_delivery_gitops.md)). Три уровня осторожности дополняют друг друга.

### Сценарий 5: Потеря spoke-кластера

Порядок действий при полной потере кластера парка:

```bash
# 1. Исключить мертвый кластер из маршрутизации трафика (балансировщик/DNS) — вне GitOps

# 2. Пересоздать кластер средствами IaC с тем же именем и метками

# 3a. Для Argo CD: перерегистрировать (Сценарий 1, шаги 1–3) —
#     ApplicationSet восстановит стек и приложения автоматически
argocd app list -l argocd.argoproj.io/application-set-name=platform-stack | grep prod-eu
# → stack-prod-eu   Synced   Healthy

# 3b. Для Flux: повторный bootstrap того же пути
flux bootstrap github --owner=my-org --repository=fleet-infra \
  --branch=main --path=clusters/prod-apac

# 4. Восстановить данные (PVC/БД) из бэкапов — Git восстанавливает только состояние
```

Полный разбор восстановления — в [DR для Argo CD](../ArgoCD/argocd_disaster_recovery.md) и [сценарии 11 для Flux](../flux.md).

## Дополнительная информация

### Масштабирование самих инструментов доставки

| Параметр | Argo CD (hub-and-spoke) | Flux (pull-per-cluster) |
| :--- | :--- | :--- |
| Узкое место | Application-controller hub: число приложений и частота сверок | Ресурсы каждого кластера независимо |
| Горизонтальное масштабирование | Шардирование application-controller'а по шардам кластеров; реплики repo-server | Flux Operator: шардирование реконсиляции, несколько инстансов в одном кластере |
| Ограничение API-нагрузки | Интервалы реконсиляции + webhook-режим вместо polling | Интервалы Kustomization; source-watcher снижает пересборку артефактов |

Признак необходимости шардинга Argo CD: время цикла сверки растет линейно с числом приложений и превышает интервал. Признак для Flux: реконсиляция отдельных Kustomization не укладывается в interval — ресурс переносится в отдельный шард.

### Типовые проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Connection refused` к spoke в логах application-controller | Недоступен API spoke / устаревший bearerToken | Проверить сеть и ротировать токен (Сценарий 1); мониторить возраст токенов |
| Новый кластер не попадает в ApplicationSet | Нет нужных меток у Secret кластера | `argocd cluster list` — колонка LABELS; добавить метку и дождаться итерации генератора |
| Одинаковые аддоны разъехались по версиям между кластерами | Копипаста манифестов вместо общих base+overlays | Привести к структуре fleet-репозитория; аудит расхождений запросом образов по кластерам |
| Hub стал единой точкой отказа деплоя | Все spoke зависят от живого hub | Гибридная топология: критичные кластеры получают собственный агент; hub только для контроля |
| Конфликт двух агентов над одним ресурсом (Argo CD в spoke + локальный Flux) | Пересечение зон ответственности | Разделить владение по field managers/namespace'ам; правила игнорирования полей |
| Токен SA истек, флот «ослеп» посреди релиза | Краткоживущие TokenRequest без процедуры обновления | Автоматизировать ротацию (CronJob/CI) либо использовать долгосрочные секреты с плановой заменой |

**Связанные документы:**
- [Обзор методологии GitOps](../GitOps_overview.md) — обзорная таблица топологий.
- [ApplicationSet: генераторы](../ArgoCD/argocd_applicationsets.md) — Cluster Generator и политики жизненного цикла.
- [Управление политиками через GitOps](./gitops-policy-management.md) — распространение политик на spoke через Teleport.

## Вопросы для собеседования

### Hub-and-Spoke или pull-per-cluster — как выбирать?
Hub (центральный Argo CD): единый UI, RBAC и точка контроля, но hub = SPOF деплоя; до десятков кластеров. Pull-per-cluster (Flux-стиль): каждый кластер автономен, масштабируется на сотни, деградация Git не останавливает флота; ценой — отсутствие центральной визуализации. Гибрид закрывает оба риска.

### Что произойдет со spoke-кластерами при смерти hub Argo CD?
Ничего немедленного: приложения продолжают работать на последней синхронизированной ревизии, дрейф начнет копиться без коррекции. Восстановление — из бэкапа/DR-процедуры ([disaster recovery](../ArgoCD/argocd_disaster_recovery.md)); критичные spoke могут иметь собственные агенты как страховку.

### Как безопасно зарегистрировать spoke в hub?
ServiceAccount с минимальными правами только на целевые namespace'ы, краткоживущие TokenRequest с плановой ротацией, kubeconfig хранится в Secret кластера hub, а не в Git; сетевой доступ — по белым спискам или через Teleport/exec-provider.

### Как раскатить изменение конфигурации на флот без одновременного отказа?
Версионировать через fleet-репозиторий (base+overlays), таргетировать по меткам кластеров (environment/tier), раскатывать поэтапно: RollingSync ApplicationSet с maxUpdate (сначала canary-кластер), наблюдение между шагами, алерты на Degraded до продолжения.

### Как избежать конфликта двух агентов над одним ресурсом?
Разделить зоны владения: field managers + SSA показывают владельцев полей; namespace'ы и типы ресурсов закрепляются за одним агентом; ignoreDifferences/.spec.ignore для пограничных полей. Два агента на один объект без явного разделения — гарантированный «пинг-понг» мутаций.
