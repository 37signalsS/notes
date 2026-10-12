# Управление политиками безопасности через GitOps (GitOps-мозг)

**Актуально для:** Argo CD v3.5+ (ветка v3.x), Teleport 17.x / 18.x, Gatekeeper 3.23.x, Kyverno 1.19.x, Kubernetes 1.30–1.35 (on-premise / bare-metal)

Этот документ описывает архитектурный подход к централизованному управлению политиками безопасности в парке Kubernetes-кластеров с использованием Argo CD, Teleport и движков политик (Gatekeeper, Kyverno, ValidatingAdmissionPolicy). Такой подход превращает политики из разрозненных ручных настроек каждого кластера в версионируемый, тестируемый и автоматически доставляемый артефакт — то есть применяет к безопасности те же практики, что и к приложениям.

## Определения

**GitOps-мозг (Policy Brain)** — концепция централизованного управляющего кластера (Management/Hub Cluster), который выступает единым авторитетным источником для политик безопасности всей инфраструктуры. Он доставляет конфигурации во все подключенные кластеры, обеспечивая единообразие и наблюдаемость без прямого ручного вмешательства администраторов в целевые кластеры.

**Teleport Access Plane** — инфраструктурное решение для управления доступом, используемое в архитектуре как защищенный прокси-слой. Оно позволяет Argo CD подключаться к API-серверам удаленных кластеров без прямого сетевого доступа, VPN и открытия входящих портов в Spoke-сетях: соединение строится через аутентифицированный Proxy с кратковременными x509-сертификатами и полным аудитом сессий.

**tbot (Teleport Bot)** — компонент Teleport Machine & Workload Identity для машинной аутентификации: генерирует кратковременные сертификаты и обновляет их автоматически для работы Argo CD. В актуальных версиях Teleport (v17/v18) tbot имеет официальный выходной сервис `kubernetes/argo-cd`, который автоматически создает и ротирует секреты кластеров для Argo CD.

**Admission Webhook (Контроллер допуска)** — HTTP-коллбэк Kubernetes API-сервера, перехватывающий запросы к кластеру после аутентификации и авторизации (RBAC), но до сохранения объекта в etcd. Подразделяется на Mutating (мутирующий — модифицирует объект) и Validating (валидирующий — разрешает или запрещает запрос).

**Failure Policy (`Fail` vs `Ignore`)** — параметр конфигурации вебхука (`failurePolicy`), определяющий поведение API-сервера при недоступности admission-контроллера (таймаут, падение пода, сбой сети). `Fail` блокирует создание ресурсов, обеспечивая максимальную строгость, но несет риск отказа API-сервера; `Ignore` пропускает запрос, сохраняя доступность ценой временного снижения контроля.

**Gatekeeper (OPA)** — агент безопасности в целевых кластерах, выполняющий проверку ресурсов на соответствие политикам, написанным на языке **Rego** или **CEL**. Политики оформляются парой ресурсов: `ConstraintTemplate` (декларация логики и схемы параметров) и `Constraint` (экземпляр политики с параметрами и областью действия). Актуальная линейка — v3.23.x (на базе OPA v1.17.x).

**Kyverno** — K8s-native движок политик, использующий декларативный YAML для описания правил валидации, мутации и генерации ресурсов. Ресурсы политик: `ClusterPolicy` (кластерная область) и `Policy` (namespace-scoped). Актуальная линейка — v1.19.x (Kubernetes 1.33–1.35).

**ValidatingAdmissionPolicy (VAP)** — встроенный в ядро Kubernetes (GA с версии 1.30) механизм валидации на базе CEL (Common Expression Language). Работает внутри процесса kube-apiserver без обращения к внешним сетевым вебхукам, обеспечивая минимальную задержку и нулевую зависимость от сторонних подов.

**CEL (Common Expression Language)** — быстрый, безопасный, не тьюринг-полный язык выражений, используемый для написания логики валидации в VAP и современных версиях Gatekeeper/Kyverno.

**Server-Side Apply (SSA)** — механизм применения конфигураций Kubernetes API, при котором сервер отслеживает владение каждым полем через `metadata.managedFields`. Позволяет избежать конфликтов перезаписи между мутирующими политиками (Kyverno) и GitOps-контроллером (Argo CD).

**Gator CLI** — официальная утилита командной строки Gatekeeper для локального синтаксического анализа, запуска юнит-тестов манифестов политик (`gator test`, `gator verify`) и компиляции без развертывания Kubernetes.

**opus-scorecard** — специализированный экспортер для Gatekeeper, преобразующий детальную информацию о нарушениях (violations) из статусов CRD `Constraint` в серийные метрики формата Prometheus с метками ресурсов.

**execProviderConfig** — механизм в Argo CD, позволяющий использовать внешние исполняемые скрипты для генерации учетных данных (kubeconfig/tokens) при подключении к удаленным кластерам. Классический способ интеграции с Teleport до появления встроенного output-service tbot.

**PolicyReport** — стандартизованный формат CRD (рабочая группа policy-reporter-workgroup), описывающий результаты аудита ресурсов политиками: список нарушений, серьезность, категории. Нативно создается Kyverno и поддерживается через адаптеры для Gatekeeper.

**Режимы Audit и Enforce** — два фундаментальных режима работы любого движка политик. `Audit` (или `dryrun` в Gatekeeper) только фиксирует нарушения в отчетах и метриках, не блокируя операции; `Enforce` (`deny`) отклоняет некорректные запросы на уровне API.

---

## Базовые концепции

### Архитектура решения (Hub-and-Spoke)

Центральным звеном выступает **Management (Hub) Cluster**, в котором развернут Argo CD и демон машинной аутентификации Teleport (`tbot`). Hub управляет политиками во всем парке целевых кластеров (**Spokes**):

```text
                                GITOPS MANAGEMENT (HUB) CLUSTER
               ┌─────────────────────────────────────────────────────────────┐
               │                                                             │
┌──────────┐   │  ┌───────────────┐     pull      ┌───────────────────────┐  │
│ Git Repo │ ──┼─>│  Argo CD Hub  │ <───────────> │ tbot (Machine Identity│  │
│ (Policy  │   │  │ Controller    │               │ kubernetes/argo-cd)   │  │
│   Brain) │   │  └───────┬───────┘               └──────────┬────────────┘  │
└──────────┘   │          │                                  │               │
               └──────────┼──────────────────────────────────┼───────────────┘
                          │ mTLS Session (short-lived certs) │ Cert rotation
                          ▼                                  ▼
               ┌─────────────────────────────────────────────────────────────┐
               │             TELEPORT ACCESS PLANE (Proxy / Auth)            │
               │   - Zero-Trust mTLS Проксирование                           │
               │   - Аудит и логирование вызовов Kubernetes API              │
               │   - Обратные туннели (Reverse Tunnels) из изолированных ЦОД  │
               └──────────────────────┬──────────────────────────────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            │ Outbound Reverse Tunnel (порт 443 / 3024)         │
            ▼                                                   ▼
┌───────────────────────────────────────┐   ┌───────────────────────────────────────┐
│       SPOKE CLUSTER 01 (Bare-Metal)   │   │       SPOKE CLUSTER 02 (DMZ / On-Prem)│
│                                       │   │                                       │
│  ┌─────────────────────────────────┐  │   │  ┌─────────────────────────────────┐  │
│  │ kube-apiserver                  │  │   │  │ kube-apiserver                  │  │
│  │   ├── ValidatingAdmissionPolicy │  │   │  │   ├── ValidatingAdmissionPolicy │  │
│  │   └── Admission Webhook Hook    │  │   │  │   └── Admission Webhook Hook    │  │
│  └────────────────┬────────────────┘  │   │  └────────────────┬────────────────┘  │
│                   │ Webhook Call      │   │                   │ Webhook Call      │
│                   ▼                   │   │                   ▼                   │
│  ┌─────────────────────────────────┐  │   │  ┌─────────────────────────────────┐  │
│  │ Gatekeeper / Kyverno Controller │  │   │  │ Gatekeeper / Kyverno Controller │  │
│  │  - Валидация / Мутация          │  │   │  │  - Валидация / Мутация          │  │
│  │  - Фоновый аудит etcd           │  │   │  │  - Фоновый аудит etcd           │  │
│  └────────────────┬────────────────┘  │   │  └────────────────┬────────────────┘  │
│                   │ Status / Reports  │   │                   │ Status / Reports  │
│                   ▼                   │   │                   ▼                   │
│  ┌─────────────────────────────────┐  │   │  ┌─────────────────────────────────┐  │
│  │ Policy Reporter / opus-scorecard│  │   │  │ Policy Reporter / opus-scorecard│  │
│  │ (Метрики нарушений в Prometheus)│  │   │  │ (Метрики нарушений в Prometheus)│  │
│  └─────────────────────────────────┘  │   │  └─────────────────────────────────┘  │
└───────────────────────────────────────┘   └───────────────────────────────────────┘
```

**Ключевые преимущества Hub-and-Spoke для SRE и системных администраторов:**
1. **Отсутствие прямого сетевого доступа в Spoke-сети**: Агенты Teleport в Spoke-кластерах устанавливают исходящие постоянные обратные туннели (Reverse Tunnels) к Teleport Proxy. Для управления Spoke-кластером не требуется открывать порты на вход в межсетевых экранах ЦОД и настраивать сложные VPN-сетки.
2. **Централизация аудита и контроля**: Любое изменение, доставляемое в кластеры, фиксируется в Git (автор, ревью, коммит) и в сессионном журнале Teleport (точный снимок mTLS-сессии, IP, субъект).
3. **Автономия Spoke-кластеров**: Argo CD отвечает исключительно за **доставку** манифестов политик. Исполнение политик происходит локально в каждом кластере (через контроллер вебхука или ядро kube-apiserver). Если связь с Hub-кластером или Teleport прерывается, существующие политики продолжают действовать без сбоев.

### Порядок обработки запросов API-сервером (Admission Lifecycle)

Понимание жизненного цикла запроса критично для настройки движков и отладки задержек в admission-цепочке:

```text
ЗАПРОС КЛИЕНТА (kubectl / CI / Argo CD Spoke)
     │
     ▼
[1. Authentication & Authorization] ──> Аутентификация mTLS/Token, проверка RBAC
     │
     ▼
[2. Mutating Admission Webhooks]    ──> Модификация ресурсов (Kyverno patchStrategicMerge)
     │                                  Ресурс дополняется labels, default requests, sidecars
     ▼
[3. Object Schema Validation]       ──> Проверка соответствия схеме OpenAPI v3
     │
     ▼
[4. Validating Admission Policies]  ──> Встроенный CEL (VAP) внутри kube-apiserver
     │
     ▼
[5. Validating Admission Webhooks]  ──> Внешние вызовы: Gatekeeper / Kyverno (validate)
     │                                  Решение: Allow или Deny (блокировка с HTTP 422)
     ▼
[6. etcd Storage]                   ──> Фиксация состояния в хранилище
     │
     ▼ (асинхронно)
[7. Background Audit Scan]          ──> Периодический аудит etcd (генерация PolicyReport)
```

### Выбор движка политик

Перед развертыванием важно сопоставить возможности доступных движков:

| Критерий | Gatekeeper (OPA) | Kyverno | ValidatingAdmissionPolicy (VAP) |
| :--- | :--- | :--- | :--- |
| **Язык политик** | Rego (или CEL в `spec.targets[].code`) | Чистый YAML (+ выражения JMESPath) | CEL (Common Expression Language) |
| **Порог входа** | Высокий (требуется знание Rego) | Низкий (нативный для K8s декларативный YAML) | Средний (выражения CEL) |
| **Мутация ресурсов** | Да (`Assign`, `AssignMetadata`) | Да (зрелая нативная поддержка `mutate`) | Нет (только валидация) |
| **Генерация ресурсов** | Ограниченно | Да (правила `generate` для синхронизации) | Нет |
| **Референциальные проверки** | Да (через кэш `data.inventory`) | Да (через `context.apiResource`) | Нет (только контекст одного объекта) |
| **Влияние на задержку API** | Сетевой вызов webhook (5–30 мс) | Сетевой вызов webhook (5–25 мс) | Нулевое сетевое влияние (внутри процесса, <1 мс) |
| **Зависимость от подов** | Требуются контроллеры в spoke | Требуются контроллеры в spoke | Полностью встроен в kube-apiserver |
| **Поддерживаемая база** | Библиотека gatekeeper-library | Библиотека kyverno/policies | Нативные CRD K8s 1.30+ |
| **Основное применение** | Сложные референциальные правила, ИБ | Мутации, генерация, правила платформы | Базовые инварианты, отсутствие накладных расходов |

**Рекомендуемый архитектурный стек:**
- **Kyverno**: используется как основной движок для мутаций (добавление дефолтных resource requests, меток владения) и валидации типовых манифестов.
- **Gatekeeper**: применяется там, где требуются сложные проверки нескольких ресурсов одновременно (например, проверка уникальности Ingress host во всем кластере через `data.inventory`).
- **ValidatingAdmissionPolicy (VAP)**: базовые структурные ограничения (запрет `privileged: true`, обязательные лейблы) непосредственно силами API-сервера без накладных расходов на вебхуки.

---

## Практические сценарии

### Сценарий 1: Подключение Spoke-кластеров через Teleport

**Предварительные требования:**
- Teleport Auth & Proxy развернуты в корпоративной сети (on-premise, например, `teleport.corp.internal:443`).
- Целевые кластеры зарегистрированы в Teleport (`tctl status` и `tsh kube ls` показывают кластеры со статусом подключен).
- В Hub-кластере установлен Argo CD v3.5+ в namespace `argocd`.
- Создан ServiceAccount `argocd:tbot` с правами создания и обновления `Secret` в namespace `argocd`.

#### Вариант A (рекомендуемый): официальный output-service tbot

Начиная с Teleport v17/v18, интеграция выполняется без использования промежуточных bash-скриптов: агент `tbot` развертывается внутри Hub-кластера рядом с Argo CD, считывает метки кластеров из Teleport и автоматически генерирует и обновляет K8s-секреты типа `argocd.argoproj.io/secret-type: cluster`.

1. **Создайте бота и join-токен в Teleport (на Auth-сервере):**

```yaml
# bot-argocd-token.yaml
kind: token
version: v2
metadata:
  name: tbot-argocd-join-token
spec:
  roles: [Bot]
  bot_name: argocd-sync-bot
  join_method: kubernetes
  kubernetes:
    type: static_jwks
    static_jwks:
      jwks: |
        {"keys":[{"kty":"RSA","n":"...","e":"AQAB","kid":"..."}]}
  allow:
    - service_account: "argocd:tbot" # namespace:serviceaccount в Hub-кластере
```

Примените токен:
```bash
tctl create -f bot-argocd-token.yaml
# → result: token "tbot-argocd-join-token" has been created
```

2. **Сконфигурируйте и установите Helm-чарт `tbot` в Hub-кластере:**

```yaml
# tbot-argocd-values.yaml
clusterName: "corp.teleport"
teleportProxyAddress: "teleport.corp.internal:443"
token: "tbot-argocd-join-token"
defaultOutput:
  enabled: false
argocd:
  enabled: true
  # Фильтр кластеров, которые отдаются под управление Argo CD:
  clusterSelectors:
    - labels:
        env: "production"
        management: "gitops-brain"
  # Шаблонизация меток секретов для генераторов ApplicationSet (Teleport v18+)
  secretLabels:
    environment: '{{index .Labels "env"}}'
    datacenter: '{{index .Labels "dc"}}'
    security-tier: '{{index .Labels "tier"}}'
```

Разверните `tbot`:
```bash
helm repo add teleport https://charts.releases.teleport.dev && helm repo update
# → result: "teleport" already exists with the latest version
helm upgrade --install tbot teleport/tbot \
  --namespace argocd \
  --values tbot-argocd-values.yaml
# → result: Release "tbot" has been upgraded. Status: deployed
```

3. **Валидация регистрации кластеров в Argo CD:**

```bash
# Проверка созданных секретов кластеров
kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster
# → result:
# NAME                                TYPE     DATA   AGE
# argocd-cluster-spoke-dc1-k8s-01     Opaque   4      45s
# argocd-cluster-spoke-dc2-k8s-01     Opaque   4      45s

# Проверка статуса подключения со стороны Argo CD CLI
argocd cluster list
# → result:
# SERVER                          NAME                STATUS      MESSAGE
# https://spoke-dc1-k8s-01...     spoke-dc1-k8s-01    Successful  
# https://spoke-dc2-k8s-01...     spoke-dc2-k8s-01    Successful  
```

#### Вариант B (legacy): execProviderConfig и скрипт аутентификации

Используется в изолированных окружениях со старыми версиями Teleport (<v17) или специфическими требованиями к кастомной маршрутизации.

1. **Манифест секрета удаленного кластера в Hub Argo CD:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: cluster-spoke-baremetal-01
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
    environment: production
    datacenter: dc1
type: Opaque
stringData:
  name: spoke-baremetal-01
  server: https://spoke-baremetal-01-proxy.argocd.svc.cluster.local:3026
  config: |
    {
      "execProviderConfig": {
        "command": "/usr/local/bin/teleport-k8s-auth.sh",
        "args": ["--cluster", "spoke-baremetal-01"],
        "apiVersion": "client.authentication.k8s.io/v1beta1"
      },
      "tlsClientConfig": {
        "insecure": false,
        "caData": "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0t..."
      }
    }
```

2. **Скрипт аутентификации (`/usr/local/bin/teleport-k8s-auth.sh`):**

Скрипт читает актуальные mTLS-сертификаты, поддерживаемые `tbot`, работающим как sidecar:

```bash
#!/bin/bash
set -euo pipefail

CLUSTER_NAME="$2"
CERT_DIR="/var/run/secrets/tbot/${CLUSTER_NAME}"

# Формирование JSON-ответа по спецификации K8s Client Authentication v1beta1
cat <<EOF
{
  "apiVersion": "client.authentication.k8s.io/v1beta1",
  "kind": "ExecCredential",
  "status": {
    "clientCertificateData": "$(base64 -w0 < "${CERT_DIR}/client.crt")",
    "clientKeyData": "$(base64 -w0 < "${CERT_DIR}/client.key")"
  }
}
EOF
```

3. **Служба ExternalName для обхода ограничения Argo CD на уникальность URL:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: spoke-baremetal-01-proxy
  namespace: argocd
spec:
  type: ExternalName
  externalName: teleport.corp.internal
```

---

### Сценарий 2: Git-структура флота и доставка через ApplicationSet

Для масштабирования на десятки и сотни кластеров политики организуются по принципу трехуровневого наследования:

```text
gitops-policies/
├── white/                          # 1. Глобальные базовые политики (все кластеры без исключения)
│   ├── gatekeeper-templates/       #    - ConstraintTemplates (CRD логики)
│   ├── baseline-constraints/       #    - Запрет privileged-контейнеров, hostNetwork
│   └── kyverno-cluster-policies/   #    - Обязательные лейблы app/tier, дефолтные лимиты
├── zones/                          # 2. Зональные политики (сегменты инфраструктуры)
│   ├── pci-dss/                    #    - Ограничения для контура обработки платежей
│   ├── dmz/                        #    - Запрет NodePort, строгий контроль Ingress
│   └── internal/                   #    - Политики для внутренних сервисов
└── clusters/                       # 3. Точечные исключения конкретных кластеров
    ├── spoke-dc1-k8s-01/
    │   └── custom-registry.yaml    #    - Специфичный локальный Harbor registry
    └── spoke-dc2-k8s-01/
```

**Доставка политик через `ApplicationSet`:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: fleet-security-policies
  namespace: argocd
spec:
  generators:
    - clusters:
        selector:
          matchLabels:
            management: "gitops-brain"
  template:
    metadata:
      name: 'policies-{{name}}'
    spec:
      project: default
      sources:
        # Слой 1: Базовые политики безопасности (White list)
        - repoURL: https://git.corp.internal/security/k8s-policies.git
          targetRevision: main
          path: white
        # Слой 2: Зональные политики на основе метки кластера из Teleport
        - repoURL: https://git.corp.internal/security/k8s-policies.git
          targetRevision: main
          path: 'zones/{{metadata.labels.security-tier}}'
      destination:
        server: '{{server}}'
        namespace: kube-system
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - ServerSideApply=true
          - CreateNamespace=false
```

**Критические параметры настройки:**
- `ServerSideApply=true`: обязателен. Большие `ConstraintTemplate` с кодом Rego/CEL превышают предельный размер аннотации `kubectl.kubernetes.io/last-applied-configuration` (лимит 262144 байт в etcd) при Client-Side Apply.
- **Sync Waves для упорядочивания доставки**:
  - `ConstraintTemplate` должен иметь аннотацию: `argocd.argoproj.io/sync-wave: "-10"`
  - `Constraint` (экземпляр): `argocd.argoproj.io/sync-wave: "-5"`
  Если sync-waves не заданы, Argo CD попытается применить Constraint параллельно с шаблоном, что приведет к ошибке API-сервера `no matches for kind`.

---

### Сценарий 3: Развертывание политики в Gatekeeper

Политика Gatekeeper состоит из пары: шаблон логики (`ConstraintTemplate`) и экземпляр с параметрами (`Constraint`).

1. **ConstraintTemplate (схема OpenAPI v3 + Rego):**

```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8sdisallowprivileged
  annotations:
    argocd.argoproj.io/sync-wave: "-10"
spec:
  crd:
    spec:
      names:
        kind: K8sDisallowPrivileged
      validation:
        openAPIV3Schema:
          type: object
          properties:
            exemptImages:
              type: array
              items:
                type: string
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8sdisallowprivileged

        violation[{"msg": msg}] {
          container := input.review.object.spec.containers[_]
          container.securityContext.privileged == true
          not is_exempt(container.image)
          msg := sprintf("Привилегированный контейнер запрещен: %v", [container.name])
        }

        is_exempt(image) {
          exempt := input.parameters.exemptImages[_]
          exempt == image
        }
```

2. **Constraint (экземпляр политики):**

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sDisallowPrivileged
metadata:
  name: disallow-privileged-containers
  annotations:
    argocd.argoproj.io/sync-wave: "-5"
spec:
  enforcementAction: dryrun              # Фаза 1: dryrun (только аудит) -> warn -> deny
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Pod"]
    excludedNamespaces:
      - kube-system
      - gatekeeper-system
      - calico-system
  parameters:
    exemptImages:
      - "registry.corp.internal/infra/node-exporter:v1.9.0"
```

3. **Валидация применения в целевом кластере:**

```bash
# Проверка компиляции шаблона
kubectl get constrainttemplates k8sdisallowprivileged
# → result: NAME                    AGE
#           k8sdisallowprivileged   2m

# Проверка нарушений в режиме dryrun
kubectl get k8sdisallowprivileged disallow-privileged-containers -o jsonpath='{.status.totalViolations}'
# → result: 3

# Детальный просмотр нарушивших ресурсов
kubectl get k8sdisallowprivileged disallow-privileged-containers -o jsonpath='{.status.violations[*].name}'
# → result: legacy-monitoring-agent debug-pod test-runner
```

---

### Сценарий 4: Развертывание политики в Kyverno

Kyverno объединяет валидацию, мутацию и генерацию ресурсов в рамках единого манифеста `ClusterPolicy`.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: baseline-pod-governance
  annotations:
    policies.kyverno.io/category: "Pod Security"
    policies.kyverno.io/severity: "medium"
spec:
  validationFailureAction: Audit        # Audit | Enforce
  background: true                      # Проверять существующие ресурсы в фоне
  rules:
    # Правило 1: Валидация наличия resource requests
    - name: check-resources
      match:
        any:
          - resources:
              kinds: ["Pod"]
              namespaces: ["prod-*", "stage-*"]
      validate:
        message: "Все контейнеры обязаны определять spec.resources.requests (cpu и memory)."
        pattern:
          spec:
            containers:
              - resources:
                  requests:
                    cpu: "?*"
                    memory: "?*"

    # Правило 2: Мутация дефолтного pullPolicy для bare-metal реестра
    - name: mutate-image-pull-policy
      match:
        any:
          - resources:
              kinds: ["Pod"]
      mutate:
        patchStrategicMerge:
          spec:
            containers:
              - (image): "registry.corp.internal/*"
                imagePullPolicy: "IfNotPresent"

    # Правило 3: Исключение для системных инфраструктурных утилит
    - name: exclude-system-daemonsets
      match:
        any:
          - resources:
              kinds: ["Pod"]
              selector:
                matchLabels:
                  tier: "node-infra"
      preconditions:
        all:
          - key: "{{ request.operation }}"
            operator: Equals
            value: "CREATE"
      validate:
        allowExistingUsername: true
```

**Валидация:**
```bash
# Проверка готовности политики
kubectl get clusterpolicy baseline-pod-governance
# → result:
# NAME                      BACKGROUND   VALIDATE ACTION   READY   AGE
# baseline-pod-governance   true         Audit             true    1m

# Проверка созданных отчетов PolicyReport
kubectl get policyreports -A
# → result:
# NAMESPACE   NAME                       PASS   FAIL   WARN   ERROR   AGE
# prod-app    polr-prod-app-cluster      12     2      0      0       3m
```

---

### Сценарий 5: Тестирование политик в CI/CD до доставки в кластеры

Ошибочная политика безопасности способна остановить развертывание приложений во всем парке серверов. Тестирование политик выполняется изолированно на этапе CI/CD до слияния изменений в ветку `main`.

1. **Юнит-тестирование Gatekeeper через `gator`:**

Создается декларативный тестовый набор (Suite):

```yaml
# tests/suite-privileged.yaml
apiVersion: test.gatekeeper.sh/v1alpha1
kind: Suite
metadata:
  name: privileged-suite
tests:
  - name: disallow-privileged
    template: ../white/gatekeeper-templates/k8sdisallowprivileged.yaml
    constraint: ../white/baseline-constraints/disallow-privileged.yaml
    cases:
      - name: bad-privileged-pod
        object: fixtures/pod-privileged.yaml
        assertions:
          - violations: yes
            message: "Привилегированный контейнер запрещен"
      - name: good-unprivileged-pod
        object: fixtures/pod-standard.yaml
        assertions:
          - violations: no
```

Запуск тестирования в пайплайне:
```bash
gator verify ./tests/...
# → result:
# ok      tests/suite-privileged.yaml    disallow-privileged/bad-privileged-pod
# ok      tests/suite-privileged.yaml    disallow-privileged/good-unprivileged-pod
# PASS
```

2. **Офлайн-тестирование манифестов Kyverno через `kyverno test`:**

```yaml
# tests/kyverno-test.yaml
apiVersion: cli.kyverno.io/v1alpha1
kind: Test
metadata:
  name: pod-resource-test
policies:
  - ../white/kyverno-cluster-policies/baseline-pod-governance.yaml
resources:
  - fixtures/pod-without-requests.yaml
  - fixtures/pod-with-requests.yaml
results:
  - policy: baseline-pod-governance
    rule: check-resources
    resource: bad-pod
    status: fail
  - policy: baseline-pod-governance
    rule: check-resources
    resource: good-pod
    status: pass
```

```bash
kyverno test ./tests/
# → result:
# Executing pod-resource-test...
# │───│─────────────────────────│─────────────────│──────────│────────│
# │ # │ POLICY                  │ RULE            │ RESOURCE │ RESULT │
# │───│─────────────────────────│─────────────────│──────────│────────│
# │ 1 │ baseline-pod-governance │ check-resources │ bad-pod  │ Pass   │
# │ 2 │ baseline-pod-governance │ check-resources │ good-pod │ Pass   │
# │───│─────────────────────────│─────────────────│──────────│────────│
# Test Summary: 2 tests passed and 0 tests failed
```

---

### Сценарий 6: Аварийный обход и восстановление доступа (Break-Glass Admission Bypass)

Если дефектная политика заблокировала кластер (например, упавший контроллер вебхука блокирует создание подов CNI или контроллеров), системный администратор применяет пошаговую процедуру аварийного обхода.

**Шаг 1: Исключение конкретного namespace через аварийную метку**
Все ValidatingWebhookConfiguration должны содержать селектор `namespaceSelector`, исключающий управляющие неймспейсы. Для спасения прикладного namespace:
```bash
kubectl label namespace emergency-restore admission.gatekeeper.sh/ignore="true" --overwrite
# → result: namespace/emergency-restore labeled
```

**Шаг 2: Временный перевод `failurePolicy` в режим `Ignore`**
Если контроллер упал в OOMKilled, а API-сервер возвращает таймауты:
```bash
kubectl patch validatingwebhookconfigurations gatekeeper-validating-webhook-configuration \
  --type='json' \
  -p='[{"op": "replace", "path": "/webhooks/0/failurePolicy", "value": "Ignore"}]'
# → result: validatingwebhookconfiguration.admissionregistration.k8s.io/gatekeeper-validating-webhook-configuration patched
```

**Шаг 3: Полное удаление зависшей конфигурации вебхука (крайняя мера)**
```bash
kubectl delete validatingwebhookconfiguration gatekeeper-validating-webhook-configuration
# → result: validatingwebhookconfiguration.admissionregistration.k8s.io "gatekeeper-validating-webhook-configuration" deleted
```
> [!IMPORTANT]
> Удаление вебхука не удаляет сами политики (CRD остаются в etcd). После перезапуска контроллера или исправления конфигурации в Git Argo CD автоматически восстановит конфигурацию вебхука благодаря свойству `selfHeal: true`.

---

## Операции и команды

Сводка команд для повседневной эксплуатации и мониторинга флота политик:

| Категория | Команда | Назначение |
| :--- | :--- | :--- |
| **Teleport tbot** | `kubectl get secrets -n argocd -l argocd.argoproj.io/secret-type=cluster` | Проверка наличия и актуальности секретов кластеров Argo CD |
| **Teleport tbot** | `kubectl exec -n argocd deploy/tbot -- pkill -USR1 tbot` | Принудительное форсирование немедленной ротации сертификатов |
| **Argo CD** | `argocd cluster list` | Проверка статуса доступности API-серверов Spoke-кластеров |
| **Gatekeeper** | `kubectl get constrainttemplates` | Список зарегистрированных CRD шаблонов политик |
| **Gatekeeper** | `kubectl get constraints` | Проверка всех развернутых политик и суммарного количества violations |
| **Gatekeeper** | `kubectl get pods -n gatekeeper-system -l control-plane=audit-controller` | Проверка статуса пода фонового аудитора |
| **Kyverno** | `kubectl get clusterpolicies` | Статус готовности и текущий режим (`Audit`/`Enforce`) политик Kyverno |
| **Kyverno** | `kubectl get policyreports -A -o wide` | Сводный отчет о нарушениях политик во всех пространствах имен |
| **Kyverno** | `kubectl get clusterpolicyreports` | Отчет о нарушениях кластерных ресурсов (Nodes, ClusterRoles) |
| **Тестирование** | `gator verify ./...` | Прогон юнит-тестов Gatekeeper в репозитории политик |
| **Тестирование** | `kyverno test ./policies/` | Офлайн-валидация политик Kyverno против набора манифестов |
| **Авария** | `kubectl get validatingwebhookconfigurations` | Проверка зарегистрированных сетевых вебхуков в API-сервере |

---

## Наблюдаемость и мониторинг нарушений

Стандартный Gatekeeper агрегирует метрики, но не передает имена конкретных объектов-нарушителей в Prometheus из коробки. Для полноценного SRE-мониторинга используются три уровня наблюдаемости.

### Использование opus-scorecard

Внутренний компонент `opus-scorecard` опрашивает поле `.status.violations` каждого объекта `Constraint` и экспортирует детальные метрики в формате Prometheus:

```text
# HELP gatekeeper_violations Количество обнаруженных нарушений политик безопасности
# TYPE gatekeeper_violations gauge
gatekeeper_violations{constraint="disallow-privileged-containers",namespace="billing",resource_kind="Pod",resource_name="payment-worker"} 1
gatekeeper_violations{constraint="k8srequiredlabels",namespace="default",resource_kind="Service",resource_name="test-svc"} 1
```

**Примеры PromQL-запросов для дашбордов Grafana:**
- Топ-5 неймспейсов по количеству нарушений:
  ```promql
  topk(5, sum by (namespace) (gatekeeper_violations))
  ```
- Динамика появления новых нарушений за последние 2 часа:
  ```promql
  sum(delta(gatekeeper_violations[2h])) by (constraint) > 0
  ```

### Нативные средства Gatekeeper

1. **Статус Constraint**: поле `.status.violations` содержит последние обнаруженные нарушения (по умолчанию до 20 элементов на политику, настраивается параметром `--constraint-violations-limit`).
2. **Метрики контроллера**:
   - `gatekeeper_constraints{enforcement_action="deny"}` — количество активных политик.
   - `gatekeeper_webhook_request_duration_seconds_bucket` — задержка обработки admission-вебхука (SLI доступности API-сервера).
   - `gatekeeper_audit_duration_seconds` — время полного цикла фонового сканирования etcd.

### Policy Reporter

Для Kyverno и мультикластерных окружений развертывается **Policy Reporter UI**, который парсит нативные объекты `PolicyReport` и агрегирует нарушения в едином графическом интерфейсе:

```bash
helm repo add policy-reporter https://kyverno.github.io/policy-reporter && helm repo update
helm upgrade --install policy-reporter policy-reporter/policy-reporter \
  --namespace policy-reporter --create-namespace \
  --set ui.enabled=true \
  --set rest.enabled=true \
  --set metrics.enabled=true
# → result: Release "policy-reporter" has been deployed.
```

**Проверка работы UI:**
```bash
kubectl -n policy-reporter port-forward svc/policy-reporter-ui 8080:8080
# → result: Forwarding from 127.0.0.1:8080 -> 8080
```
Интерфейс доступен по адресу `http://localhost:8080` и предоставляет матрицу нарушений с фильтрацией по кластерам, серьезности и неймспейсам.

---

## Диагностика и устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **API-сервер зависает или выдает 504 Gateway Timeout при создании любых подов** | Вебхук Gatekeeper/Kyverno недоступен, при этом задан `failurePolicy: Fail` с большим таймаутом | `kubectl get validatingwebhookconfigurations -o yaml \| grep -E "(failurePolicy\|timeoutSeconds)"` | Установить таймаут вебхука не более 3 секунд; временно переключить `failurePolicy: Ignore` (Сценарий 6); проверить логи подов контроллера |
| **Constraint создан, но не проверяет ресурсы** | Ошибка валидации схемы OpenAPI v3 в ConstraintTemplate или синтаксическая ошибка в коде | `kubectl get constrainttemplates <name> -o yaml` (секция `status.byPod`) | Убедиться, что в схеме параметров указан `type: object`; проверить синтаксис через `gator verify` |
| **Бесконечный цикл синхронизации Argo CD (OutOfSync drift)** | Kyverno мутирует поля ресурса (например, добавляет дефолтные лейблы), а Argo CD пытается откатить их по Client-Side Apply | `kubectl get <kind> <name> -o jsonpath='{.metadata.managedFields}'` | Включить Server-Side Apply (`ServerSideApply=true`) в ApplicationSet либо настроить `ignoreDifferences` в Argo CD на мутируемые поля |
| **Ошибка при синхронизации ApplicationSet: `no matches for kind`** | Constraint доставляется одновременно или раньше ConstraintTemplate | `argocd app get policies-<cluster>` | Настроить sync-waves: ConstraintTemplate `-10`, Constraint `-5`; включить `ServerSideApply=true` |
| **Spoke-кластеры теряют статус `Successful` каждые 12–24 часа** | Сертификаты tbot истекают из-за разрыва связи с Teleport Proxy или падения демона tbot | `kubectl logs -n argocd deploy/tbot` | Проверить сетевой доступ Hub → Teleport Proxy (443); убедиться, что токен присоединения бота валиден; перезапустить под tbot |
| **Аудит Gatekeeper не видит нарушений, хотя невалидные объекты есть в кластере** | Цикл аудита еще не завершился либо ресурсы исключены по `match` | `kubectl logs -n gatekeeper-system -l control-plane=audit-controller` | Проверить флаг `--audit-interval` (по умолчанию 60с в dev, до 1ч в prod); проверить `match.excludedNamespaces` |
| **Ошибка Argo CD: `cluster server URL must be unique`** | При использовании execProviderConfig несколько кластеров имеют один адрес Teleport | Проверить конфигурацию секретов кластеров в namespace `argocd` | Создать уникальные `Service` типа `ExternalName` для каждого кластера (Сценарий 1B) либо перейти на tbot (Сценарий 1A) |

---

## Лучшие практики

### 1. Архитектурное эшелонирование (Defense in Depth)

Управление политиками должно быть многоуровневым:
1. **Pre-commit / Локально у разработчика**: валидация схемы YAML манифестов и запуск `gator test` / `kyverno test` локально.
2. **CI-пайплайн (Gate 1)**: блокировка PR при наличии грубых нарушений базовых стандартов безопасности (запуск офлайн-тестов на раннерах).
3. **Admission Control в кластере (Gate 2)**: блокировка создания небезопасных объектов через kube-apiserver вебхуки в режиме `Enforce`.
4. **Фоновый аудит (Gate 3)**: непрерывное сканирование объектов в etcd для выявления отклонений, появившихся до внедрения политики или при обновлении движков.

### 2. Безопасность и отказоустойчивость Admission Webhooks

- **Строгие исключения для системных пространств имен**: вебхуки **никогда** не должны перехватывать запросы в `kube-system`, `kube-node-lease`, `gatekeeper-system` и пространства имен CNI-плагинов. Перехват системных неймспейсов может привести к невозможности запуска подов сети и фатальной блокировке кластера после перезагрузки нод.
- **Таймауты вебхука**: параметр `timeoutSeconds` в `ValidatingWebhookConfiguration` не должен превышать 3 секунд (значение по умолчанию 10 секунд создает чрезмерную нагрузку на etcd при сетевых задержках).
- **High Availability контроллеров**: контроллеры Gatekeeper и Kyverno должны развертываться минимум в 3 репликах с `PodDisruptionBudget` (`minAvailable: 2`) и `topologySpreadConstraints` по зонам/узлам.

### 3. Управление исключениями (Exceptions Management)

- **Запрет глобальных исключений**: исключения на уровне всего кластера запрещены. Каждое исключение оформляется точечно в манифесте `Constraint` или `PolicyException` (Kyverno).
- **Обязательные атрибуты исключения**:
  1. `reason` — техническое обоснование необходимости послабления.
  2. `owner` — ответственная команда / сервис.
  3. `expiresAt` (или TTL) — срок действия исключения (регулярный аудит устаревших правил).
- Все исключения версионируются в Git и проходят обязательное ревью команды платформы/безопасности.

### 4. Жизненный цикл и безопасный роллаут политик

Внедрение новой блокирующей политики выполняется строго по стадиям:
1. **Разработка и юнит-тесты**: создание правила и прогон через `gator verify` / `kyverno test` на синтетических данных.
2. **Аудит (Dryrun/Audit)**: публикация политики в кластеры с `enforcementAction: dryrun` (Gatekeeper) или `validationFailureAction: Audit` (Kyverno).
3. **Анализ отчетов**: сбор метрик через Prometheus/Policy Reporter в течение 7–14 дней. Исправление легитимных приложений и добавление точечных исключений.
4. **Предупреждение (Warn)**: перевод в `enforcementAction: warn` — разработчики видят предупреждения в выводе CI/CD и CLI, но деплой не ломается.
5. **Принудительное соблюдение (Enforce/Deny)**: перевод в боевой режим блокировки отдельным Git-коммитом.

### 5. Производительность и масштабирование на 100+ кластеров (Bare-Metal)

- **Шардирование Argo CD Application Controller**: при управлении сотнями кластеров масштабируйте контроллер (`argocd-application-controller`) горизонтально, задавая переменную `ARGOCD_CONTROLLER_SHARDING_ALGORITHM: consistent-hashing`.
- **Оптимизация tbot в памяти**: монтируйте директорию генерации временных сертификатов tbot в `emptyDir` с `medium: Memory` (tmpfs), чтобы исключить деградацию дискового ввода-вывода при частой ротации сотен секретов.
- **Тюнинг фонового аудита Gatekeeper**: не запускайте аудит слишком часто. Оптимальный интервал для больших кластеров (10 000+ подов) — 30–60 минут (`--audit-interval=1800`). Используйте флаг `--audit-match-kind-only` для ограничения типов проверяемых ресурсов.

### 6. Безопасная очистка и декоммиссия политик (Cleanup & Rollback)

- **Порядок удаления ресурсов**:
  1. Удалите экземпляры политик (`Constraint` / `ClusterPolicy`).
  2. Дождитесь очистки статусов и удаления финализаторов.
  3. Удалите шаблоны политик (`ConstraintTemplate`).
  4. При полном выводе движка удалите `ValidatingWebhookConfiguration` **до** удаления подов контроллера, чтобы избежать зависания API-сервера.
- В Argo CD настройка `prune: true` удаляет политики автоматически при их исключении из Git, сохраняя кластер в чистом состоянии.

---

## Дополнительная информация

### См. также
- **[Эшелонированная защита в IaC](../../CI-CD/DevSecOps/iac-security-defense-in-depth.md)** — многоуровневая стратегия статического анализа манифестов и политик.
- **[OPA Gatekeeper: детали и Rego](../../Kubernetes/Security/rbac/limitations_opa.md)** — глубокий разбор языка Rego, структуры ConstraintTemplates и ограничений RBAC.
- **[Интеграция Kyverno с Argo CD](../../Kubernetes/Security/kyverno/argo-cd.md)** — нюансы Server-Side Diff, разрешения конфликтов managedFields и мутаций.
- **[Мульти-кластерные паттерны в GitOps](./multi_cluster_patterns.md)** — топологии Hub-and-Spoke, регистрация кластеров и изоляция флота.
- **[Аудит в GitOps](./audit_logs.md)** — сбор и хранение аудиторских следов доставки конфигураций.
- **[Argo CD: обзор архитектуры](../ArgoCD/argocd_overview.md)** — базовые принципы и компоненты контроллера доставки.
- **[Управление секретами в GitOps](../secrets_encryption.md)** — методы работы с конфиденциальными данными в репозитории.

### Внешние ресурсы
- [Gatekeeper Documentation](https://open-policy-agent.github.io/gatekeeper/website/docs/) — официальное руководство по OPA Gatekeeper.
- [Gator CLI Guide](https://open-policy-agent.github.io/gatekeeper/website/docs/gator/) — документация по тестированию и верификации через gator.
- [Teleport Machine & Workload Identity with Argo CD](https://goteleport.com/docs/machine-workload-identity/access-guides/argocd/) — официальное руководство по настройке tbot для Argo CD.
- [Kyverno Documentation](https://kyverno.io/docs/) — официальная документация по движку Kyverno.
- [Policy Reporter](https://kyverno.github.io/policy-reporter/) — проект мониторинга и дашбординга PolicyReports.

---

## Вопросы для собеседования

### 1. В чем архитектурное отличие проверки политик в CI/CD от проверки через Admission Webhooks?
CI/CD валидация (Shift-Left: conftest, gator test, kyverno test) проверяет статические манифесты в Git и дает мгновенную обратную связь разработчику при создании Pull Request, экономя время и ресурсы. Однако она бессильна против прямых вызовов API (`kubectl edit`, ручной аварийный доступ, действия операторов и контроллеров внутри кластера). Admission Webhooks перехватывают абсолютно все запросы на входе в etcd независимо от источника, гарантируя соблюдение инвариантов безопасности в runtime. Надежная система строится на обязательном сочетании обоих уровней.

### 2. Чем опасен параметр `failurePolicy: Fail` у admission-вебхука и как минимизировать риски в production?
При `failurePolicy: Fail` любая недоступность контроллера политик (падение пода, сетевой сбой, OOMKilled, истечение таймаута при перегрузке) приводит к тому, что kube-apiserver отклоняет все перехватываемые запросы. Если вебхук перехватывает системные ресурсы, кластер теряет способность создавать поды CNI, CoreDNS, ingress и контроллеров, что может привести к полному отказу.
Для минимизации рисков:
1. Исключать `kube-system` и инфраструктурные неймспейсы через `namespaceSelector`.
2. Устанавливать жесткий таймаут вебхука (`timeoutSeconds: 2` или `3`).
3. Развертывать вебхук минимум в 3 репликах с PodDisruptionBudget.
4. Для второстепенных политик (не связанных с критической изоляцией ядра) использовать `failurePolicy: Ignore`.

### 3. Почему при совместном использовании Kyverno и Argo CD возникает бесконечный цикл синхронизации (Sync Drift) и как его устранить?
Цикл возникает, когда Kyverno мутирует ресурс на этапе admission (например, подставляет дефолтные параметры или лейблы), а Argo CD использует устаревший Client-Side Apply. Argo CD сравнивает измененный ресурс в кластере с оригиналом в Git, видит расхождение (`OutOfSync`) и перезаписывает ресурс, что снова триггерит мутацию Kyverno.
Решение:
1. Переход на Server-Side Apply (`ServerSideApply=true`), где Kubernetes сам отслеживает владельцев конкретных полей через `managedFields`.
2. Явное исключение мутируемых полей из сверки через директиву `ignoreDifferences` в конфигурации Application/ApplicationSet в Argo CD.

### 4. Каковы преимущества использования Teleport tbot перед хранением статических kubeconfig-секретов в Hub-кластере Argo CD?
Хранение статических kubeconfig с долгоживущими токенами или клиентскими сертификатами для десятков Spoke-кластеров в Hub создает критическую уязвимость: компрометация Hub-кластера означает мгновенную компрометацию всего флота серверов. Статические сертификаты сложно централизованно отзывать и ротировать.
`tbot` использует концепцию Machine Identity:
- Генерирует кратковременные mTLS-сертификаты со сроком жизни от нескольких десятков минут до пары часов.
- Автоматически ротирует их на лету в K8s-секретах.
- Соединения идут через Teleport Proxy с единым журналированием всех действий и возможностью мгновенно заблокировать доступ конкретного бота на Auth-сервере без изменения конфигурации Spoke-кластеров.

### 5. Как устроен процесс перевода политики безопасности из аудита в блокировку на парке из 100+ кластеров?
Процесс реализуется поэтапно через GitOps:
1. **Тестирование**: верификация правила на синтетических манифестах через `gator verify` или `kyverno test` в CI.
2. **Аудит**: публикация политики через ApplicationSet во все зоны в режиме `dryrun` (Gatekeeper) или `Audit` (Kyverno).
3. **Мониторинг**: агрегация метрик через Prometheus / Policy Reporter в течение 1–2 недель для выявления всех несоответствующих сервисов.
4. **Устранение и исключения**: оповещение продуктовых команд, исправление манифестов приложений в их репозиториях, оформление точечных временных исключений (с TTL и обоснованием) для легитимных легаси-сервисов.
5. **Предупреждение (Warn)**: включение `enforcementAction: warn` для информирования команд при деплое.
6. **Канареечный Enforce**: перевод в `deny`/`Enforce` сначала на тестовых/staging зонах, затем в production-кластерах с интервалом в несколько дней через Git PR.
