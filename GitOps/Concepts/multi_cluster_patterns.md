# Мульти-кластерные паттерны в GitOps

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x), Flux v2.9.x (линейка v2.x), Kubernetes 1.28–1.32+ (bare-metal / on-premise)

Как только GitOps внедрен в одном кластере, следующим этапом становится управление распределенным парком (fleet management): десятки и сотни Kubernetes-кластеров (продуктивные площадки по нескольким дата-центрам, тестовые и стейджинг-контуры, изолированные edge-периметры) должны централизованно получать конфигурацию из Git. Главная инженерная задача SRE и DevOps — обеспечить контролируемые различия конфигураций между кластерами, предсказуемую поэтапную раскатку изменений, отсутствие неконтролируемого дрейфа (fleet-wide drift) и безопасность учетных данных без внешних облачных зависимостей.

---

## Определения

- **Hub-and-Spoke** — архитектурная топология доставки, при которой один центральный управляющий кластер (Hub) с запущенным GitOps-оператором подключается к внешним целевым кластерам (Spoke) через их `kube-apiserver` и синхронизирует состояние ресурсов.
- **Pull-per-cluster** — децентрализованная топология, в которой каждый кластер автономен: внутри него развернут собственный GitOps-агент (например, контроллеры Flux или локальный Argo CD), который самостоятельно опрашивает центральный Git/OCI-репозиторий и применяет манифесты.
- **Гибридная (иерархическая) топология** — модель, объединяющая оба подхода: центральный Hub управляет глобальными политиками безопасности, сетевыми стандартами и системными аддонами, а локальные агенты в кластерах отвечают за доставку прикладных сервисов команд.
- **Spoke-кластер (Target Cluster)** — подчиненный управляемый кластер, в который доставляются манифесты; в модели Hub-and-Spoke не содержит собственного управляющего контура доставки.
- **Fleet-репозиторий (Monorepo / Multi-repo)** — репозиторий конфигурации парка кластеров, разделяющий общую библиотеку манифестов (base/platform) и специфичные для каждого кластера оверлеи (overlays/environments).
- **Декларативная регистрация кластера (Cluster Registration)** — процедура добавления spoke-кластера в реестр управляющего оператора через манифест Secret в GitOps-репозитории вместо императивных CLI-команд.
- **Cluster Secret** — объект `Secret` в namespace `argocd` с меткой `argocd.argoproj.io/secret-type: cluster`, содержащий адрес API-сервера целевого кластера, CA-сертификат и токен аутентификации.
- **ApplicationSet Cluster Generator** — генератор контроллера ApplicationSet в Argo CD, автоматически создающий экземпляры `Application` для каждого зарегистрированного кластера на основе селектора меток (`selector.matchLabels`).
- **Шардирование контроллера (Controller Sharding)** — горизонтальное разделение нагрузки `argocd-application-controller` по репликам StatefulSet с распределением целевых кластеров и приложений между шардами.
- **Конфигурационный дрейф флота (Fleet-wide Drift)** — неконтролируемое расхождение версий манифестов, параметров и системных аддонов между однотипными кластерами парка из-за рассинхронизации или ручных правок.
- **Прогрессивная синхронизация (Progressive Syncs / RollingSync)** — стратегия оркестрации раскатки в ApplicationSet, разделяющая обновление приложений по группам кластеров с остановкой конвейера при деградации здоровья (Health Gating).
- **Радиус поражения (Blast Radius)** — объем инфраструктуры и сервисов, подвергающихся риску одновременного сбоя при выкатке ошибочной конфигурации.
- **Health Gating** — барьер проверки работоспособности: переход к синхронизации следующей группы кластеров блокируется до тех пор, пока все приложения текущего шага не перейдут в статус `Healthy` и `Synced`.

---

## Базовые концепции и архитектура

### 1. Сравнение топологий доставки

```text
Hub-and-Spoke (Argo CD)                  Pull-per-cluster (Flux CD)
┌──────────────┐                          ┌──────────────┐
│  Hub-кластер │                          │   Git/OCI    │
│  (Argo CD)   │                          │  Репозиторий │
└──────┬───────┘                          └─┬──────────┬─┘
       │ Входящий TLS (6443)                │          │ Исходящий HTTPS/SSH
       ├─────────────────────┐              │          │ (только pull)
       ▼                     ▼              ▼          ▼
┌──────────────┐      ┌──────────────┐ ┌─────────┐ ┌─────────┐
│ Spoke-DC1    │      │ Spoke-DC2    │ │ Cluster │ │ Cluster │
│ (Bare-Metal) │      │ (Bare-Metal) │ │   DC1   │ │   DC2   │
└──────────────┘      └──────────────┘ └─────────┘ └─────────┘
```

| Критерий | Hub-and-Spoke | Pull-per-cluster | Иерархический гибрид |
| :--- | :--- | :--- | :--- |
| **Единая консоль и аудит** | Централизованный UI, аудит и RBAC из одной точки | Децентрализовано (требуется агрегация логов/метрик) | Единая консоль для платформы, локальный UI/CLI для команд |
| **Сетевые требования** | Требуется входящий сетевой доступ от Hub к `kube-apiserver` каждого spoke | Только исходящий доступ из кластеров в Git-сервер и реестр OCI | Исходящий доступ из spoke; доступ к Hub только для телеметрии |
| **Поведение при падении Hub** | Кластеры функционируют, но доставка новых версий полностью заблокирована | Отсутствует единая точка отказа; каждый кластер автономен | Платформенные обновления ждут Hub, локальные релизы продолжаются |
| **Хранение учетных данных** | Все токены и ключи доступа к API spoke хранятся на Hub | Токены внешних кластеров отсутствуют; права строго локальные | Токены spoke ограничены системными namespace'ами |
| **Масштабируемость парка** | Ограничена ресурсами Hub (требуется шардирование контроллера) | Неограниченная (сотни и тысячи edge/bare-metal узлов) | Высокая: Hub управляет десятками зон, локальные агенты — сервисами |
| **Сложность эксплуатации** | Низкий порог входа, удобный централизованный дебаг | Выше: требуется автоматизация bootstrap и мониторинга каждого агента | Средняя: четкое разделение зон ответственности |

---

### 2. Сетевая связность и безопасность в On-Premise / Bare-Metal

В корпоративных инфраструктурах без публичных облачных сетей организация связности между кластерами подчиняется строгим требованиям безопасности:

1. **Прямая маршрутизация L3 (Dedicated Direct Routing):**
   - Кластеры размещаются в корпоративной сети (MPLS, IPsec VPN, BGP/WireGuard).
   - Hub обращается напрямую к IP-адресам Control Plane узлов spoke через выделенный порт `6443`.
   - Необходима настройка списков доступа (ACL) на межсетевых экранах: доступ к API spoke разрешается строго с фиксированных IP-адресов подов `argocd-application-controller`.
2. **Изолированные периметры и NAT (Reverse Tunnels / API Gateways):**
   - Если spoke-кластер находится за NAT в закрытом контуре ЦОД или на удаленном edge-объекте, Hub не может инициировать TCP-сессию к его API-серверу.
   - Для решения проблемы в bare-metal средах применяются обратные туннели:
     - **Teleport Machine ID (`tbot`):** агент на spoke поднимает исходящее защищенное mTLS-соединение к корпоративному шлюзу Teleport, через который Argo CD проксирует вызовы к API-серверу.
     - **Kubernetes Konnectivity / SSH Reverse Tunnels:** туннелирование трафика от доверенного шлюза в закрытую зону.
3. **Преимущество Pull-модели (Flux):**
   - При наличии жестких политик межсетевого экранирования (запрет любых входящих соединений в DMZ/Production) архитектура Pull-per-cluster является безальтернативным выбором: кластер инициирует только стандартные исходящие сессии (HTTPS по порту 443 или SSH по порту 22) к локальному GitLab/Gitea и реестру Harbor.

---

### 3. Модель аутентификации и RBAC на Spoke-кластерах

Подключение Hub-контроллера к spoke-кластеру требует минимизации вектора атак:

- **Принцип наименьших привилегий (Scoped RBAC):** Назначение сервисному аккаунту Argo CD роли `cluster-admin` допустимо только на ранних этапах. В зрелых инфраструктурах формируется ограниченная `ClusterRole`, исключающая доступ к секретам `kube-system`, управлению узлами (`Node`), мутациям вебхуков безопасности и RBAC кластерного уровня (запрет эскалации привилегий).
- **Управление токенами:**
  - В Kubernetes 1.24+ токены сервисных аккаунтов больше не генерируются бессрочно в объектах `Secret`.
  - Рекомендуемый подход для долгосрочной автоматизации: явное создание объекта `Secret` с аннотацией `kubernetes.io/service-account.name` либо выпуск токена с длительным сроком действия через `kubectl create token --duration=...` с регламентной процедурой ротации.
- **Валидация TLS:** Поле `tlsClientConfig.caData` в секрете кластера обязательно должно содержать корневой CA-сертификат API-сервера spoke-кластера. Флаг `insecure: true` категорически запрещен, так как делает межцодовый трафик уязвимым для MITM-атак.

---

### 4. Структура и изоляция Fleet-репозитория

Поддержание единого монорепозитория для флота кластеров исключает дублирование манифестов и гарантирует консистентность:

```text
fleet-infra/
├── clusters/                       # Точки входа (entrypoints) каждого кластера
│   ├── dc1-prod-01/
│   │   ├── cluster-config.yaml     # Параметры кластера (имя, DC, CIDR)
│   │   ├── infrastructure.yaml     # Подключение платформенного стека
│   │   └── apps.yaml               # Подключение прикладных приложений
│   ├── dc2-prod-02/
│   └── dc1-stage-01/
├── platform/                       # Базовые системные аддоны
│   ├── monitoring/                 # Prometheus, Alertmanager, Node Exporters
│   │   ├── base/
│   │   └── overlays/
│   │       ├── prod/
│   │       └── staging/
│   ├── ingress/                    # Nginx Ingress / Gateway API
│   ├── storage/                    # Local-path-provisioner / CSI драйверы
│   └── security/                   # Kyverno / Gatekeeper политики
├── apps/                           # Прикладные микросервисы (base + overlays)
└── policies/                       # Глобальные политики аудита и безопасности
```

**Правила структурирования:**
- **Запрет копирования манифестов:** Одинаковые компоненты хранятся в каталоге `base/`. Индивидуальные параметры (реплики, IP-пулы MetalLB, DNS-домены) описываются исключительно через Kustomize overlays или JSON/YAML-файлы параметров.
- **Разделение прав (CODEOWNERS):** Инфраструктурные инженеры валидируют изменения в каталогах `platform/` и `policies/`, в то время как продуктовые команды коммитят манифесты в свои подкаталоги `apps/*`.
- **Изоляция на уровне Argo CD AppProject:** Каждый кластер или группа сред привязывается к своему `AppProject`. Это блокирует возможность случайной выкатки тестового приложения на продуктивный кластер даже при ошибке в генераторе ApplicationSet.

---

### 5. Масштабирование и производительность компонентов доставки

При росте флота свыше 10–15 кластеров центральный Hub сталкивается с физическими ограничениями:

```text
                               ┌─────────────────────────────┐
                               │ StatefulSet Controller Pod 0│ ──> Кластеры 0, 3, 6...
┌──────────────────────────┐   ├─────────────────────────────┤
│ argocd-cmd-params-cm     │──>│ StatefulSet Controller Pod 1│ ──> Кластеры 1, 4, 7...
│ sharding.algorithm:      │   ├─────────────────────────────┤
│ "round-robin"            │   │ StatefulSet Controller Pod 2│ ──> Кластеры 2, 5, 8...
└──────────────────────────┘   └─────────────────────────────┘
```

1. **Шардирование `argocd-application-controller`:**
   - По умолчанию один экземпляр контроллера держит постоянные TCP-соединения (HTTP/2 streams) ко всем API-серверам всех кластеров.
   - Масштабирование достигается переводом контроллера в `StatefulSet` и включением алгоритма `round-robin`:
     ```yaml
     controller.sharding.algorithm: "round-robin"
     ```
   - Каждая реплика StatefulSet вычисляет свой порядковый номер (`ARGOCD_CONTROLLER_SHARD`) и обслуживает строго назначенное подмножество кластеров, динамически адаптируясь к изменению количества реплик.
2. **Оптимизация сетевых потоков и пулов соединений:**
   - Для предотвращения насыщения очередей тюнятся параметры параллельной обработки:
     - `--status-processors` (по умолчанию 20) — количество воркеров обновления статусов ресурсов. Для парка из 30+ кластеров увеличивается до 50–100.
     - `--operation-processors` (по умолчанию 10) — число параллельных операций синхронизации.
3. **Кэширование в Redis:**
   - Все информирующие кэши (Kubernetes Informers) сериализуются и складываются в Redis. Для высоконагруженного Hub обязательна настройка Redis Sentinel или Redis Cluster с достаточным объемом оперативной памяти (не менее 4–8 ГБ).
4. **Flux CD в децентрализованной модели:**
   - Отсутствует централизованный узкий узел. Каждый кластер расходует строго локальные ресурсы (обычно 100–300 МБ RAM суммарно на все контроллеры Source, Kustomize и Helm), что делает архитектуру линейно масштабируемой до тысяч узлов.

---

## Практические сценарии

### Сценарий 1: Декларативная регистрация On-Premise Spoke в Hub Argo CD

**Контекст:** Требуется зарегистрировать целевой bare-metal кластер `spoke-dc1-prod` в Hub Argo CD с ограниченными правами доступа и валидацией CA.

#### Шаг 1. Создание сервисного аккаунта и RBAC на Spoke-кластере

```bash
# 1. Создание пространства имен и сервисного аккаунта
kubectl create namespace argocd-system --context spoke-dc1-prod
# → namespace/argocd-system created

kubectl create serviceaccount argocd-manager -n argocd-system --context spoke-dc1-prod
# → serviceaccount/argocd-manager created

# 2. Создание роли с необходимым набором прав для управления платформой
kubectl apply -f - --context spoke-dc1-prod <<'EOF'
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: argocd-manager-role
rules:
  - apiGroups: ["*"]
    resources: ["*"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - nonResourceURLs: ["*"]
    verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: argocd-manager-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: argocd-manager-role
subjects:
  - kind: ServiceAccount
    name: argocd-manager
    namespace: argocd-system
EOF
# → clusterrole.rbac.authorization.k8s.io/argocd-manager-role created
# → clusterrolebinding.rbac.authorization.k8s.io/argocd-manager-binding created
```

#### Шаг 2. Выпуск статического токена и извлечение сертификата CA

```bash
# Создание постоянного секрета для токена (актуально для K8s 1.24–1.32+)
kubectl apply -f - --context spoke-dc1-prod <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: argocd-manager-token
  namespace: argocd-system
  annotations:
    kubernetes.io/service-account.name: argocd-manager
type: kubernetes.io/service-account-token
EOF
# → secret/argocd-manager-token created

# Ожидание генерации токена контроллером токенов
sleep 2

# Извлечение токена и CA
TOKEN=$(kubectl get secret argocd-manager-token -n argocd-system --context spoke-dc1-prod -o jsonpath='{.data.token}' | base64 -d)
CA_DATA=$(kubectl get secret argocd-manager-token -n argocd-system --context spoke-dc1-prod -o jsonpath='{.data.ca\.crt}')
```

#### Шаг 3. Создание декларативного секрета кластера на Hub

Манифест коммитится в Git-каталог управления инфраструктурой Hub:

```yaml
# clusters/management/spoke-dc1-prod-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: cluster-spoke-dc1-prod
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    environment: prod
    datacenter: dc1
    tier: platform
type: Opaque
stringData:
  name: spoke-dc1-prod
  server: https://k8s-api.dc1.internal:6443
  config: |
    {
      "bearerToken": "eyJhGciOi...",
      "tlsClientConfig": {
        "insecure": false,
        "caData": "LS0tLS1CRUdJTi..."
      }
    }
```

```bash
# Применение секрета на Hub
kubectl apply -f clusters/management/spoke-dc1-prod-secret.yaml --context hub-admin
# → secret/cluster-spoke-dc1-prod created

# Проверка регистрации в Argo CD
argocd cluster list
# → SERVER                             NAME             STATUS      MESSAGE
# → https://k8s-api.dc1.internal:6443  spoke-dc1-prod   Successful  
```

---

### Сценарий 2: Автоматическое развертывание платформенного стека через ApplicationSet Cluster Generator

**Контекст:** При добавлении любого кластера с меткой `tier: platform` на него должен автоматически разворачиваться системный стек мониторинга и ingress-контроллера.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: fleet-platform-stack
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    - clusters:
        selector:
          matchLabels:
            tier: platform
        values:
          # Передача дополнительных значений на основе меток кластера
          env: '{{ .metadata.labels.environment }}'
          dc: '{{ .metadata.labels.datacenter }}'
  template:
    metadata:
      name: 'platform-{{ .name }}'
      labels:
        environment: '{{ .values.env }}'
    spec:
      project: default
      source:
        repoURL: https://git.internal/platform/fleet-infra.git
        targetRevision: main
        path: 'platform/overlays/{{ .values.env }}'
      destination:
        name: '{{ .name }}'
        namespace: platform-system
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
          - ApplyOutOfSyncOnly=true
```

**Проверка генерации приложений:**

```bash
# Проверка созданных приложений после добавления кластера
argocd app list -l argocd.argoproj.io/application-set-name=fleet-platform-stack
# → NAME                        CLUSTER           STATUS    HEALTH
# → platform-spoke-dc1-prod     spoke-dc1-prod    Synced    Healthy
# → platform-spoke-dc2-prod     spoke-dc2-prod    Synced    Healthy
```

---

### Сценарий 3: Поэтапная прогрессивная раскатка (Progressive Sync / RollingSync) на флот

**Контекст:** Требуется раскатить обновление конфигурации ingress-контроллера по цепочке: сначала Canary-кластер (100%), затем Staging (100%), и только при их абсолютном здоровье — продуктивные кластеры порциями не более чем по одному кластеру за раз (`maxUpdate: 1`).

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: fleet-ingress-rollout
  namespace: argocd
spec:
  goTemplate: true
  strategy:
    type: RollingSync
    rollingSync:
      steps:
        # Шаг 1: Канареечный продуктивный кластер
        - matchExpressions:
            - key: environment
              operator: In
              values:
                - canary
          maxUpdate: 100%
        # Шаг 2: Тестовые и предпродуктивные среды
        - matchExpressions:
            - key: environment
              operator: In
              values:
                - staging
          maxUpdate: 100%
        # Шаг 3: Основной продуктивный флот по 1 кластеру за шаг
        - matchExpressions:
            - key: environment
              operator: In
              values:
                - prod
          maxUpdate: 1
  generators:
    - clusters:
        selector:
          matchLabels:
            component: ingress
  template:
    metadata:
      name: 'ingress-{{ .name }}'
      labels:
        environment: '{{ .metadata.labels.environment }}'
    spec:
      project: default
      source:
        repoURL: https://git.internal/platform/fleet-infra.git
        targetRevision: main
        path: 'platform/ingress/overlays/{{ .name }}'
      destination:
        name: '{{ .name }}'
        namespace: ingress-system
      syncPolicy:
        retry:
          limit: 3
          backoff:
            duration: 10s
            factor: 2
            maxDuration: 2m
```

**Отслеживание прогресса раскатки:**

```bash
# Контроль статуса выполнения шагов
kubectl get applicationset fleet-ingress-rollout -n argocd -o yaml
# → status:
# →   applicationStatus:
# →   - application: ingress-spoke-canary
# →     status: Healthy
# →     step: "1"
# →   - application: ingress-spoke-dc1-prod
# →     status: Progressing
# →     step: "3"
```

---

### Сценарий 4: Развертывание парка кластеров во Flux v2 с параметризацией и SOPS

**Контекст:** Настройка pull-per-cluster топологии во Flux v2. Каждый bare-metal кластер подключается к общему монорепозиторию, подтягивает единый базовый стек и подставляет уникальные кластерные переменные (IP-адреса шлюзов, имена ЦОД) без дублирования манифестов.

#### 1. Структура точки входа кластера (`clusters/dc1-prod/kustomization.yaml`)

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: cluster-platform
  namespace: flux-system
spec:
  interval: 15m
  path: ./platform/overlays/prod
  prune: true
  wait: true
  timeout: 10m
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  # Подстановка переменных окружения для конкретного кластера
  postBuild:
    substituteFrom:
      - kind: ConfigMap
        name: cluster-vars
      - kind: Secret
        name: cluster-secrets
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: cluster-apps
  namespace: flux-system
spec:
  dependsOn:
    - name: cluster-platform
  interval: 15m
  path: ./apps/overlays/prod
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
```

#### 2. Переменные кластера (`clusters/dc1-prod/cluster-vars.yaml`)

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-vars
  namespace: flux-system
data:
  CLUSTER_NAME: "dc1-prod"
  DATACENTER: "datacenter-primary"
  METALLB_IP_RANGE: "192.168.10.200-192.168.10.240"
  INGRESS_DOMAIN: "apps.dc1.internal"
```

#### 3. Инициализация кластера (Bootstrap)

```bash
# Запуск bootstrap на целевом bare-metal кластере
flux bootstrap git \
  --url=ssh://git@git.internal/platform/fleet-infra.git \
  --branch=main \
  --path=clusters/dc1-prod \
  --private-key-file=/root/.ssh/id_ed25519_deploy \
  --silent
# → ► connecting to ssh://git@git.internal/platform/fleet-infra.git
# → ► verifying sync configuration
# → ✔ bootstrap finished
```

---

### Сценарий 5: Горизонтальное масштабирование и шардирование контроллера Argo CD

**Контекст:** На Hub-кластере зарегистрировано более 25 кластеров. Цикл реконсиляции `argocd-application-controller` превышает 180 секунд. Требуется включить шардирование и смасштабировать контроллер до 3 реплик.

```yaml
# 1. Включение алгоритма round-robin в argocd-cmd-params-cm
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  controller.sharding.algorithm: "round-robin"
  controller.status.processors: "50"
  controller.operation.processors: "25"
```

```bash
# Применение обновленной конфигурации
kubectl apply -f argocd-cmd-params-cm.yaml -n argocd
# → configmap/argocd-cmd-params-cm configured

# 2. Масштабирование StatefulSet контроллера
kubectl scale statefulset argocd-application-controller -n argocd --replicas=3
# → statefulset.apps/argocd-application-controller scaled

# 3. Проверка запуска подов шардов
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-application-controller
# → NAME                             READY   STATUS    RESTARTS   AGE
# → argocd-application-controller-0   1/1     Running   0          5m
# → argocd-application-controller-1   1/1     Running   0          2m
# → argocd-application-controller-2   1/1     Running   0          1m

# 4. Проверка балансировки кластеров по шардам
argocd admin cluster stats
# → SHARD  CLUSTERS  APPLICATIONS
# → 0      9         142
# → 1      9         138
# → 2      8         145
```

---

### Сценарий 6: Аварийное восстановление (Zero-Touch DR) и вывод кластера из флота

#### Процедура А: Полный вывод (Decommissioning) кластера из парка

Во избежание зависания финализаторов и фантомных ресурсов удаление выполняется строго по регламенту:

```bash
# 1. Удаление приложений, привязанных к кластеру, либо снятие метки с секрета кластера
kubectl label secret cluster-spoke-dc1-prod -n argocd tier-
# → secret/cluster-spoke-dc1-prod unlabeled
# (ApplicationSet автоматически удалит каскадные Application)

# 2. Ожидание завершения удаления ресурсов на spoke
sleep 30

# 3. Удаление самого секрета кластера из Argo CD
kubectl delete secret cluster-spoke-dc1-prod -n argocd
# → secret "cluster-spoke-dc1-prod" deleted

# Либо через CLI
argocd cluster rm spoke-dc1-prod -y
# → Cluster 'https://k8s-api.dc1.internal:6443' removed
```

#### Процедура Б: Аварийное пересоздание (Zero-Touch Disaster Recovery)

При катастрофическом отказе bare-metal оборудования:
1. Физический сервер переустанавливается через PXE / Ansible / Talos с чистым Control Plane.
2. Применяется Сценарий 1 (создание сервисного аккаунта и обновление секрета кластера на Hub с новым CA/токеном, если они изменились).
3. ApplicationSet подхватывает кластер и выполняет полную регидрацию инфраструктурного и прикладного состояния из Git:
   ```bash
   argocd app sync -l argocd.argoproj.io/application-set-name=fleet-platform-stack
   # → 24/24 resources synchronized
   ```
4. Данные Stateful-сервисов восстанавливаются из резервных копий (снимки хранилища / Velero).

---

## Операции и команды

Сводка типовых команд системного администратора и SRE для эксплуатации распределенного парка кластеров:

### Управление кластерами в Argo CD

| Операция | Команда | Ожидаемый результат / Описание |
| :--- | :--- | :--- |
| **Список всех кластеров** | `argocd cluster list` | Вывод таблицы с URL, именами, статусом соединения и метками |
| **Детальная информация** | `argocd cluster get spoke-dc1-prod` | Отображение версии K8s, кэша ресурсов и назначенной реплики шарда |
| **Добавление кластера из kubeconfig** | `argocd cluster add <context> --name <name> --label env=prod` | Императивное создание секрета кластера (для временных тестовых зон) |
| **Обновление меток кластера** | `kubectl label secret cluster-spoke-dc1-prod -n argocd env=canary --overwrite` | Обновление меток для переключения кластера в ApplicationSet |
| **Статистика шардинга** | `argocd admin cluster stats` | Отображение распределения нагрузки (число кластеров и приложений на шард) |
| **Удаление кластера** | `argocd cluster rm spoke-dc1-prod` | Удаление секрета кластера из реестра Argo CD |

### Диагностика сетевой связности и TLS

```bash
# 1. Проверка доступности API-сервера spoke с пода контроллера Hub
kubectl exec -it argocd-application-controller-0 -n argocd -- \
  curl -k -m 5 -s -o /dev/null -w "%{http_code}\n" https://k8s-api.dc1.internal:6443/version
# → 401 (401 свидетельствует о нормальной сетевой связности и ожидании Bearer-токена)

# 2. Проверка валидности сертификата API-сервера spoke
openssl s_client -connect k8s-api.dc1.internal:6443 -showcerts </dev/null 2>/dev/null | \
  openssl x509 -noout -dates -subject
# → notBefore=Jan 10 12:00:00 2026 GMT
# → notAfter=Jan 10 12:00:00 2027 GMT
# → subject=CN = kube-apiserver
```

### Мониторинг и управление во Flux v2

```bash
# 1. Просмотр состояния всех точек синхронизации в кластере
flux get kustomizations
# → NAME              REVISION    SUSPENDED   READY   MESSAGE
# → cluster-platform  main@sha1:e3f8  False       True    Applied revision: main@sha1:e3f8
# → cluster-apps      main@sha1:e3f8  False       True    Applied revision: main@sha1:e3f8

# 2. Принудительная сверка с источником Git
flux reconcile kustomization cluster-platform --with-source
# → ► fetching GitRepository
# → ► reconciling Kustomization
# → ✔ Kustomization reconciled
```

---

## Диагностика и устранение неисправностей

| Симптом / Ошибка | Первопричина | Команда диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **`Unauthorized (401)` в логах контроллера** | Истек срок действия `TokenRequest` либо удален ServiceAccount на spoke | `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller \| grep "401"` | Выпустить новый токен (Сценарий 1) и обновить поле `bearerToken` в секрете кластера |
| **`x509: certificate signed by unknown authority`** | Ошибка в значении `tlsClientConfig.caData` либо ротация CA на spoke | `argocd cluster get <name>` | Извлечь актуальный `ca.crt` из `kube-root-ca.crt` ConfigMap spoke и занести base64 в секрет |
| **`dial tcp ...:6443: i/o timeout` или `Connection refused`** | Межсетевой экран блокирует трафик между дата-центрами; упал keepalived/HAProxy API-сервера | `nc -zv -w 3 k8s-api.dc1.internal 6443` | Настроить ACL на физических фаерволах; проверить статус VIP на Control Plane узлах spoke |
| **Кластер не попадает в выборку ApplicationSet** | Не задана метка `argocd.argoproj.io/secret-type: cluster` либо не совпадает `matchLabels` | `kubectl get secret -n argocd --show-labels` | Добавить системную метку `argocd.argoproj.io/secret-type: cluster` и сверить селектор ApplicationSet |
| **Дисбаланс шардов: один шард перегружен** | Устаревший алгоритм шардинга `legacy` вместо `round-robin` | `argocd admin cluster stats` | Установить `controller.sharding.algorithm: "round-robin"` в `argocd-cmd-params-cm` и перезапустить StatefulSet |
| **Флуд запросами и троттлинг `kube-apiserver`** | Слишком частый polling или слишком много приложений на spoke | Логи API-сервера spoke: `apiserver_request_total` | Увеличить интервал `timeout.reconciliation`, включить Server-Side Diff, использовать вебхуки вместо поллинга |
| **`Field Manager conflict` (борьба за ресурс)** | Конфликт Server-Side Apply между Argo CD на Hub и локальным оператором на spoke | `kubectl get <resource> -o yaml \| grep -A 10 managedFields` | Настроить `ignoreDifferences` в Application либо разграничить зоны ответственности по namespace'ам |

---

## Лучшие практики

1. **Разграничение сетевых контуров и нулевое доверие (Zero-Trust):**
   - Запрещайте выставление портов `kube-apiserver` в публичный доступ. Для межкластерного взаимодействия используйте только шифрованные каналы (IPsec/WireGuard, mTLS) или реверс-прокси.
2. **Минимальные привилегии агента доставки (Scoped RBAC):**
   - Никогда не используйте дефолтный `cluster-admin` без аудита. Исключайте возможность модификации пространств имен платформы безопасности, манипуляций с секретами нод и захвата Control Plane.
3. **Автоматизация проверки конфигурационного дрейфа (Drift Audit):**
   - Настройте Prometheus-алерты на метрики расхождения версий:
     ```promql
     sum by (cluster) (argocd_app_info{sync_status="OutOfSync"}) > 0
     ```
   - Раз в сутки запускайте аудит соответствия версий системных аддонов по кластерам.
4. **Контроль радиуса поражения через RollingSync:**
   - Все глобальные изменения (обновление CNI, Ingress, политик безопасности) раскатывайте исключительно через канареечные кластеры с барьерами здоровья (Health Gating). При первых признаках деградации метрик раскатка должна блокироваться автоматически.
5. **Строгая политика версионной совместимости N-2:**
   - Не допускайте одновременного присутствия в парке кластеров с разницей версий Kubernetes более чем на две минорные версии. Это гарантирует валидность API (`apiVersion`) и предотвращает сбои при генерации манифестов.
6. **Декларативное управление выводом из эксплуатации (Decommissioning Hygiene):**
   - Перед выводом сервера или кластера из эксплуатации снимайте метки назначения в GitOps-репозитории, позволяя контроллерам штатно удалить ресурсы и очистить финализаторы (`finalizers`), исключая зависание объектов в etcd.

---

## Дополнительная информация

**Связанные документы базы знаний:**
- [Обзор методологии GitOps](../GitOps_overview.md) — обзорная таблица топологий и классификация подходов.
- [Организация Flux CD monorepo](./flux_monorepo_organization.md) — детальный кейс миграции и структуры монорепозитория для 20+ кластеров.
- [ApplicationSet: генераторы](../ArgoCD/argocd_applicationsets.md) — разбор генераторов Cluster, Git, Matrix и Merge.
- [Argo CD: Прогрессивная синхронизация](../ArgoCD/synchronization/scenarios/progressive_sync.md) — детальное руководство по механизму RollingSync.
- [Установка и настройка Argo CD (шардирование)](../ArgoCD/argocd_installation_and_setup.md) — конфигурация `argocd-cmd-params-cm` и масштабирование StatefulSet.
- [Управление политиками через GitOps](./gitops-policy-management.md) — централизованное распространение политик Gatekeeper/Kyverno на spoke-кластеры.
- [Argo CD: Аварийное восстановление](../ArgoCD/argocd_disaster_recovery.md) — резервное копирование и Zero-Touch восстановление.
- [Шифрование секретов в GitOps](../secrets_encryption.md) — управление зашифрованными секретами (SOPS, age, HashiCorp Vault).

---

## Вопросы для собеседования

### 1. Как выбрать между топологиями Hub-and-Spoke и Pull-per-cluster для enterprise-инфраструктуры?
**Ответ:** Выбор определяется сетевой топологией и масштабом парка. 
- *Hub-and-Spoke (Argo CD)* оптимален, если число кластеров не превышает нескольких десятков (до 50–100), имеется прямое надежное сетевое соединение между дата-центрами, а команде критически важна единая точка визуализации, централизованный RBAC, SSO и единый аудит действий. Главный риск — Hub является единой точкой отказа деплоя (SPOF) и хранит критичные учетные данные всего флота.
- *Pull-per-cluster (Flux)* выбирается при строгой сетевой изоляции (запрет входящих портов в DMZ/Production), слабой связанности каналов (edge-локации), требованиях к полной автономности каждого кластера при падении центрального офиса и при масштабировании на сотни и тысячи кластеров.
- *Гибридный подход* объединяет преимущества: Hub распространяет базовые платформенные контракты и политики, а команды работают через локальные агенты.

### 2. Что происходит с рабочими нагрузками на Spoke-кластерах при аварии или недоступности Hub Argo CD?
**Ответ:** Никакого немедленного влияния на запущенные пользовательские приложения не происходит: все поды, сервисы и контроллеры на Spoke продолжают штатно функционировать на последнем примененном состоянии из etcd. Однако доставка новых изменений, автоисправление дрейфа (self-healing) и мониторинг состояния блокируются до момента восстановления Hub или его переключения на резервный узел по процедуре Disaster Recovery.

### 3. Почему прямое указание `argocd.argoproj.io/sync-wave` в шаблоне ApplicationSet не упорядочивает раскатку между кластерами?
**Ответ:** Аннотация `sync-wave` предназначена для управления порядком применения манифестов *внутри одного приложения* (например, сначала Namespace, затем Secret, затем Deployment), либо при использовании паттерна App-of-Apps. Для оркестрации порядка развертывания *между различными кластерами или экземплярами Application* в ApplicationSet используется специализированный контроллер Progressive Syncs со стратегией `spec.strategy.type: RollingSync`. Он группирует приложения по шагам (`steps`) с помощью `matchExpressions` и ожидает перехода каждого кластера в статус `Healthy` перед переходом к следующей волне.

### 4. Как организовать безопасное обновление токенов доступа к Spoke-кластерам без даунтайма деплоя?
**Ответ:** В Kubernetes 1.24+ предпочтительна автоматизация ротации учетных данных:
1. Выпуск временного `TokenRequest` с разумным TTL (например, 30–90 дней).
2. Автоматизированный процесс (CI-пайплайн, HashiCorp Vault Agent или внешний контроллер), который за N дней до экспирации генерирует новый токен на Spoke, выполняет валидацию доступа и обновляет поле `bearerToken` в секрете кластера на Hub.
3. Контроллер Argo CD динамически перечитывает Secret без перезапуска подов контроллера.
4. В качестве альтернативы для статических on-premise сред создается явный объект `Secret` типа `kubernetes.io/service-account-token`, ротируемый вручную по регламенту безопасности.

### 5. Как устроено шардирование `argocd-application-controller` и как избежать перекоса нагрузки?
**Ответ:** Контроллер масштабируется как `StatefulSet`. Каждая реплика получает порядковый номер (индекс) через переменную `ARGOCD_CONTROLLER_SHARD`. При использовании современного алгоритма `controller.sharding.algorithm: "round-robin"` кластеры сортируются детерминированно и распределяются по шардам по круговому алгоритму (модуль деления индекса). Это предотвращает концентрацию тяжелых кластеров на одном шарде, которая была характерна для устаревшего hash-алгоритма (`legacy`). Контроль распределения осуществляется командой `argocd admin cluster stats`.
