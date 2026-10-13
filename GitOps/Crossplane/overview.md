# Crossplane: Обзор

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

---

## Определения

**Crossplane** — платформа с открытым исходным кодом (CNCF Graduated, лицензия Apache 2.0), расширяющая Kubernetes API и превращающая кластер в универсальный уровень управления (Control Plane). В отличие от классических утилит класса Infrastructure as Code (Terraform, OpenTofu), исполняющих изменения по push-модели (`plan/apply`), Crossplane функционирует по непрерывной pull-модели сверки (Reconciliation Loop), автономно отслеживая и устраняя дрейф конфигурации (drift detection & remediation) между манифестами в etcd и реальным состоянием инфраструктурных систем.

**Control Plane (управляющий контур)** — выделенный кластер Kubernetes с развернутым ядром Crossplane, провайдерами и функциями композиции, выступающий единой точкой оркестрации инфраструктурных компонентов (вспомогательные Kubernetes-кластеры, bare-metal серверы, сетевые фабрики, СХД, базы данных, хранилища секретов) через декларативный Kubernetes API.

**Provider (провайдер)** — OCI-пакет и расширение ядра (`kind: Provider`, API-группа `pkg.crossplane.io`), регистрирующее в кластере контроллеры и набор CustomResourceDefinitions (CRD) для взаимодействия с целевой подсистемой (например, `provider-kubernetes`, `provider-helm`, `provider-sql`, `provider-vault`, `provider-ansible`).

**ProviderConfig** — ресурс конфигурации провайдера (`kind: ProviderConfig`), определяющий сетевой эндпоинт, таймауты и способ аутентификации (ссылка на Kubernetes Secret или InjectedIdentity через проекцию токена ServiceAccount) для подключения к целевой инфраструктуре.

**Managed Resource (MR, управляемый ресурс)** — низкоуровневый декларативный ресурс Kubernetes, представляющий дискретный объект внешней или внутренней инфраструктуры (например, база данных в СУБД, роль в хранилище секретов, release в Helm или произвольный манифест `Object` в целевом кластере). Контролируется непосредственно контроллером соответствующего провайдера.

**CompositeResourceDefinition (XRD)** — схема декларативного пользовательского API платформы (`kind: CompositeResourceDefinition`, API-группа `apiextensions.crossplane.io`). Определяет структуру входных параметров (OpenAPI v3 schema), область видимости и спецификацию создаваемого составного ресурса (XR) и пользовательской заявки (Claim).

**Composition** — шаблон реализации XRD (`kind: Composition`, API-группа `apiextensions.crossplane.io`), связывающий абстрактный интерфейс с конкретным графом Managed Resources через последовательный конвейер вызова Composition Functions.

**Composite Resource (XR, составной ресурс)** — экземпляр абстракции платформы, порождаемый напрямую платформенными инженерами либо автоматически создаваемый в ответ на пользовательский Claim. В Crossplane v1.x являлся строго кластерным (`Cluster-scoped`), в архитектуре Crossplane v2.x поддерживает пространствозависимый режим (`Namespaced XR`).

**Composite Resource Claim (Claim / XRC, заявка на ресурс)** — пространствозависимый (`Namespace-scoped`) пользовательский манифест заказа инфраструктуры. Выступает интерфейсом самообслуживания (Self-Service) для разработчиков, скрывающим технические детали реализации за упрощенной схемой параметров.

**Composition Functions (функции композиции)** — независимые OCI-микросервисы (`kind: Function`, API-группа `pkg.crossplane.io`), исполняющие логику трансформации, валидации, циклов и генерации манифестов по протоколу gRPC. В Crossplane v2.x являются единственным механизмом композиции (`mode: Pipeline`), полностью заменившим устаревшие статические патчи (Patch & Transform).

**DeploymentRuntimeConfig (DRC)** — кластерный ресурс (`kind: DeploymentRuntimeConfig`), управляющий системными параметрами подов провайдеров и функций: ресурсными лимитами (`requests/limits`), привязкой к нодам (`nodeSelector`, `tolerations`), сервисными аккаунтами и флагами запуска контроллеров (`--poll`, `--max-reconcile-rate`). Заменил устаревший `ControllerConfig`.

**Management Policies (`spec.managementPolicies`)** — гранулярный перечень операций (`Observe`, `Create`, `Update`, `Delete`, `LateInitialize`), разрешенных контроллеру Crossplane над физическим ресурсом. Позволяет безопасно импортировать существующую инфраструктуру в режиме `ObserveOnly` или исключать случайное физическое удаление объектов.

**Deletion Policy (`spec.deletionPolicy`)** — директива жизненного цикла ресурса: `Delete` (удаление физического ресурса во внешней системе при удалении MR в Kubernetes) или `Orphan` (сохранение физического ресурса во внешней системе с удалением только представления в Kubernetes).

**External Name (`crossplane.io/external-name`)** — системная аннотация, содержащая уникальный идентификатор или имя объекта в целевой инфраструктуре. Гарантирует идемпотентность и связывание манифеста с существующей сущностью.

---

## Базовые концепции и архитектура

### Принцип работы: Kubernetes как универсальный Control Plane

Crossplane использует архитектуру Kubernetes (API Server, etcd, контроллеры и кастомные ресурсы) для управления произвольными компонентами On-Premise и Bare-Metal инфраструктуры:

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             KUBERNETES CONTROL PLANE                             │
│                                                                                  │
│   GitOps Engine (Argo CD / Flux) ────▶ kube-apiserver + etcd                     │
│                                              │                                   │
│                     ┌────────────────────────┴───────────────────────┐           │
│                     ▼                                                ▼           │
│           Composite Resource (XR)                        Managed Resources (MR)  │
│                     │                                                ▲           │
│                     ▼                                                │           │
│         Composition Engine (Pipeline)                                │           │
│                     │                                                │           │
│          gRPC Calls │ (Proto3)                                       │           │
│                     ▼                                                │           │
│         Composition Functions Pods ──────────────────────────────────┘           │
│         (kcl / patch-and-transform / auto-ready)                                 │
└──────────────────────────────────────┬───────────────────────────────────────────┘
                                       │
                         Reconcile Loop (Watch / Poll)
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            CROSSPLANE PROVIDERS PODS                             │
│                                                                                  │
│   ┌───────────────────────────────┐      ┌───────────────────────────────────┐   │
│   │      provider-kubernetes      │      │           provider-sql            │   │
│   │   (SSA, Dynamic K8s Client)   │      │   (PostgreSQL / MySQL Driver)     │   │
│   └───────────────┬───────────────┘      └─────────────────┬─────────────────┘   │
└───────────────────┼────────────────────────────────────────┼─────────────────────┘
                    │                                        │
                    ▼                                        ▼
    ┌───────────────────────────────┐      ┌───────────────────────────────────┐
    │     Целевые кластеры K8s      │      │     Self-Hosted СУБД (On-Prem)    │
    │  Namespaces, RBAC, Workloads  │      │    Databases, Users, Privileges   │
    └───────────────────────────────┘      └───────────────────────────────────┘
```

1. **Декларативное описание:** Желаемое состояние инфраструктуры фиксируется в Git в виде YAML-манифестов и доставляется в кластер через GitOps-контроллеры (Argo CD, Flux).
2. **Watch-механизм:** Контроллеры Crossplane Core и установленных провайдеров отслеживают события жизненного цикла объектов через стандартный `watch` API Kubernetes.
3. **Конвейерная композиция:** Запрос на абстрактный ресурс (Claim или XR) передается в движок композиции. Crossplane последовательно вызывает зарегистрированные поды функций по протоколу gRPC, генерируя граф низкоуровневых Managed Resources.
4. **Непрерывная сверка:** Контроллеры провайдеров опрашивают целевые системы (целевые K8s-кластеры, серверы баз данных, сетевые коммутаторы), выявляют расхождения и приводят фактическое состояние к заданному в `spec`.
5. **Экспорт реквизитов подключения:** Чувствительные данные (пароли, сертификаты, токены доступа, сгенерированные целевыми системами) упаковываются в защищенные Kubernetes Secrets для использования прикладными подами.

---

### Архитектура компонентов Crossplane

Производственная инсталляция Crossplane Core состоит из следующих компонентов:

| Компонент | Назначение | Особенности эксплуатации SRE |
| :--- | :--- | :--- |
| **`crossplane` (Core Controller)** | Управляет жизненным циклом пакетов (`Provider`, `Function`, `Configuration`), обрабатывает XRD и выполняет конвейеры композиции. | Критичен к ресурсам CPU/памяти при большом количестве XR/Claim. Поддерживает Leader Election для высокой доступности (HA). |
| **`crossplane-rbac-manager`** | Автоматически генерирует и агрегирует роли Kubernetes (`ClusterRole`, `Role`) для каждого установленного CRD, связывая их с системными группами `admin`, `edit`, `view`. | Может быть отключен флагом `--rbac-manager-disabled=true` при наличии внешней системы управления правами или строгих требований ИБ. |
| **Provider Pods** | Отдельные Deployment'ы в `crossplane-system`, исполняющие reconciliation loop для конкретного домена инфраструктуры. | Потребляют память пропорционально числу управляемых CRD и объектов. Настраиваются через `DeploymentRuntimeConfig`. |
| **Function Pods** | Локальные gRPC-микросервисы, исполняющие пользовательские функции композиции. | Запускаются ядром Crossplane. Коммуникация происходит внутри кластера по протоколу HTTP/2 (gRPC). |

---

### Уровни абстракции платформы (XRD, Composition, XR, Claim)

Crossplane реализует паттерн разделения ответственности между платформенной командой и прикладными разработчиками:

```text
  Платформенная команда (SRE / Platform Engineers)
  ─────────────────────────────────────────────────────────────
  1. Описывает схему API:    CompositeResourceDefinition (XRD)
  2. Задает реализацию:      Composition (Pipeline Functions)
  3. Настраивает доступы:    ClusterProviderConfig / Secrets

                            │  Публикация API в кластере
                            ▼
  Прикладные команды (Developers / DevOps)
  ─────────────────────────────────────────────────────────────
  4. Создают заказ:          Composite Resource Claim (Claim)
  5. Получают результат:     Готовая инфраструктура + Connection Secret
```

* **CompositeResourceDefinition (XRD):** Определяет схему нового ресурса. Валидирует входные данные разработчика через OpenAPI v3 schema.
* **Composition:** Реализует логику развертывания. В Crossplane v2.x манифест Composition состоит из массива `pipeline`, где каждый шаг вызывает специализированную функцию (`function-patch-and-transform`, `function-kcl`, `function-auto-ready`).
* **Namespaced XR (v2.x) против Cluster-Scoped (v1.x):** Исторически составные ресурсы существовали только на уровне кластера, что затрудняло разграничение прав и квотирование. В Crossplane v2.x составные ресурсы могут быть локализованы в пространстве имен команды (`Namespaced XR`), что исключает коллизии имен и изолирует видимость.

---

### Механизм непрерывной сверки (Reconciliation Loop)

Жизненный цикл каждого Managed Resource подчиняется циклу сверки, состоящему из 5 дискретных фаз:

```text
 ┌──────────────┐      ┌─────────────────────────┐      ┌──────────────────┐
 │ 1. Observe   │─────▶│ 2. Late-Initialize      │─────▶│ 3. Create /      │
 │ (Опрос API)  │      │ (Фиксация авто-полей)   │      │    Update        │
 └──────────────┘      └─────────────────────────┘      └─────────┬────────┘
        ▲                                                         │
        │                                                         ▼
 ┌──────┴──────────────────┐                            ┌──────────────────┐
 │ 5. Sleep & Exponential  │◀───────────────────────────│ 4. Publish       │
 │    Backoff / Poll Period│                            │    Connection    │
 └─────────────────────────┘                            │    Details       │
                                                        └──────────────────┘
```

1. **Observe (Наблюдение):** Провайдер обращается к целевой системе для выяснения текущего состояния ресурса. Если объект существует, считываются его атрибуты.
2. **Late-Initialization:** Если в целевой системе присутствуют параметры, не заданные явно в `spec` манифеста (но сгенерированные системой по умолчанию), контроллер может зафиксировать их в `spec.forProvider`, чтобы исключить ложный дрейф при последующих итерациях.
3. **Create / Update:** Если объект отсутствует — вызывается процедура создания. Если параметры объекта в `spec` отличаются от параметров в целевой системе — контроллер отправляет патч/обновление.
4. **Publish Connection Details:** При успешном создании контроллер извлекает учетные данные (хосты, порты, логины, пароли) и записывает их в целевой Kubernetes Secret.
5. **Requeue:** Контроллер засыпает на интервал опроса (`poll interval`, по умолчанию 1 минута). При возникновении ошибки включается экспоненциальный backoff для предотвращения лавинообразной перегрузки целевого API.

#### Различие статусов: Synced и Ready

Каждый ресурс Crossplane содержит два ключевых индикатора в `status.conditions`:
* `Synced = True`: Желаемая конфигурация из etcd успешно отправлена и принята целевым провайдером без синтаксических или сетевых ошибок.
* `Ready = True`: Физический ресурс во внешней системе полностью инициализирован, прошел проверки работоспособности (readiness checks) и готов к приему нагрузки.
* **Типовая ситуация:** Ресурс может быть `Synced=True`, но `Ready=False` (например, база данных находится в процессе создания или целевой Kubernetes-под ожидает монтирования томов).

---

### Модель пакетов и DeploymentRuntimeConfig

Начиная с ветки v1.x и как фундаментальный стандарт в v2.x, Crossplane использует модель пакетирования OCI (Open Container Initiative). Провайдеры и функции распространяются в виде OCI-артефактов (`.xpkg`), загружаемых из контейнерных реестров.

#### Требования к реестрам пакетов в Crossplane v2.x
В Crossplane v2.x **удалена поддержка неявного реестра по умолчанию**. Поле `spec.package` всегда должно содержать полностью квалифицированный URL образа (`registry.domain.tld/repository/package:tag`).

#### Тюнинг контроллеров через DeploymentRuntimeConfig (DRC)
Для настройки производительности подов провайдеров и функций используется ресурс `DeploymentRuntimeConfig`:

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: tuned-provider-runtime
spec:
  deploymentTemplate:
    spec:
      replicas: 1
      template:
        spec:
          nodeSelector:
            node-role.kubernetes.io/infra: "true"
          tolerations:
            - key: "infra"
              operator: "Exists"
              effect: "NoSchedule"
          containers:
            - name: package-runtime
              args:
                - --poll=5m
                - --max-reconcile-rate=20
              resources:
                requests:
                  cpu: 250m
                  memory: 512Mi
                limits:
                  cpu: 1000m
                  memory: 2Gi
```

* `--poll`: интервал регулярного опроса целевой инфраструктуры. Увеличение (например, до `5m` или `10m`) снижает нагрузку на сеть и целевые API в больших инсталляциях.
* `--max-reconcile-rate`: максимальное количество параллельных операций сверки. Защищает целевую систему от перегрузки при массовом накате манифестов.

---

### Жизненный цикл ресурсов и политики управления (Management Policies)

Управление ресурсами через `spec.managementPolicies` гарантирует полный контроль SRE над уровнем вмешательства контроллера:

| Политика | Действие контроллера Crossplane |
| :--- | :--- |
| `["*"]` или `["All"]` | Полный цикл: создание, регулярная сверка, обновление, удаление и фиксация автополей. |
| `["Observe"]` (или `ObserveOnly`) | Режим инспекции. Контроллер считывает состояние ресурса, но не вносит изменений и не удаляет его. Идеально для безопасного аудита существующей On-Prem инфраструктуры. |
| `["Create", "Update", "Observe"]` | Создание и поддержание конфигурации без права на физическое удаление. Если объект MR удаляется из Kubernetes, физический ресурс во внешней системе сохраняется. |

#### Защита от удаления: DeletionPolicy и Usage CRD
* `spec.deletionPolicy: Orphan`: При удалении манифеста MR из кластера Kubernetes снимает системный финалайзер `finalizer.managedresource.crossplane.io`, но контроллер **не отправляет** вызов на удаление физического объекта.
* `Usage` CRD (`protection.crossplane.io/v1beta1`): Механизм блокировки удаления базовых ресурсов (например, сетевого пространства или СУБД) до тех пор, пока существуют зависимые ресурсы (например, базы данных или рабочие нагрузки). См. [Защита зависимостей (Usage)](./usage_protection.md).

#### Заморозка сверки: аннотация paused
Для проведения регламентных работ на целевой инфраструктуре любой ресурс Crossplane может быть изолирован от reconciler-цикла установкой аннотации:

```bash
kubectl annotate managed <resource-name> crossplane.io/paused="true"
# → managed annotated
```

Контроллер мгновенно прекращает попытки обновления или удаления целевого объекта до снятия аннотации: `crossplane.io/paused-`.

---

## Практические сценарии

Ниже приведено развертывание отказоустойчивого Control Plane Crossplane v2.x для управления On-Premise инфраструктурой и Kubernetes-кластерами без привязки к публичным облакам.

### Предварительные требования

* Кластер Kubernetes v1.28–1.32+ с доступом администратора (`kubectl cluster-info`).
* Установленный пакетный менеджер **Helm v3.14+**.
* Установленный бинарный файл **Crossplane CLI v2.x**.
* Доступ к OCI-реестру с образами провайдеров (для закрытых контуров — внутренний Harbor / Nexus).

Установка Crossplane CLI на рабочую станцию SRE / Bastion (Linux x86_64):

```bash
curl -sL "https://raw.githubusercontent.com/crossplane/crossplane/master/install.sh" | bash
# → crossplane installed to ./crossplane
sudo mv crossplane /usr/local/bin/
crossplane version
# → Client Version: v2.4.0
```

---

### Сценарий 1: Развертывание Crossplane Core в High Availability (HA) режиме

Для промышленных сред Crossplane разворачивается с включенным режимом лидер-выборов, несколькими репликами и выделением системных ресурсов:

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update
# → "crossplane-stable" has been added to your repositories
# → Update Complete. ⎈Successfully got an update from the "crossplane-stable" chart repository

helm install crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --create-namespace \
  --set replicas=2 \
  --set leaderElection=true \
  --set resourcesCrossplane.requests.cpu="500m" \
  --set resourcesCrossplane.requests.memory="1Gi" \
  --set resourcesCrossplane.limits.cpu="2000m" \
  --set resourcesCrossplane.limits.memory="4Gi" \
  --set args='{"--enable-composition-functions=true"}'
# → NAME: crossplane
# → LAST DEPLOYED: Mon Oct 13 17:15:00 2026
# → NAMESPACE: crossplane-system
# → STATUS: deployed
```

Проверка статуса подов и регистрация системных CRD:

```bash
kubectl -n crossplane-system get pods -o wide
# → crossplane-79bfbd4895-4k8qx               1/1     Running   0          42s   10.244.1.15   node-infra-01
# → crossplane-79bfbd4895-x9z2p               1/1     Running   0          42s   10.244.2.18   node-infra-02
# → crossplane-rbac-manager-699cb4cf8f-7w8q2  1/1     Running   0          42s   10.244.1.16   node-infra-01

kubectl get crds | grep 'crossplane.io' | head -n 5
# → compositeresourcedefinitions.apiextensions.crossplane.io   2026-10-13T14:15:20Z
# → compositions.apiextensions.crossplane.io                   2026-10-13T14:15:20Z
# → configurationrevisions.pkg.crossplane.io                   2026-10-13T14:15:20Z
# → configurations.pkg.crossplane.io                           2026-10-13T14:15:20Z
# → deploymentruntimeconfigs.pkg.crossplane.io                 2026-10-13T14:15:20Z
```

---

### Сценарий 2: Установка провайдера и настройка DeploymentRuntimeConfig

Развернем `provider-kubernetes` (v1.3.0) с привязкой к тюнингованному `DeploymentRuntimeConfig`:

```yaml
# 1. runtime-config.yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: k8s-provider-config
spec:
  deploymentTemplate:
    spec:
      template:
        spec:
          containers:
            - name: package-runtime
              args:
                - --poll=2m
                - --max-reconcile-rate=15
              resources:
                requests:
                  cpu: 200m
                  memory: 256Mi
                limits:
                  cpu: 1000m
                  memory: 1Gi
---
# 2. provider-install.yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.3.0
  runtimeConfigRef:
    name: k8s-provider-config
```

Применение и контроль установки:

```bash
kubectl apply -f runtime-config.yaml
# → deploymentruntimeconfig.pkg.crossplane.io/k8s-provider-config created

kubectl apply -f provider-install.yaml
# → provider.pkg.crossplane.io/provider-kubernetes created

kubectl get providers
# → NAME                  INSTALLED   HEALTHY   PACKAGE                                                         AGE
# → provider-kubernetes   True        True      xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.3.0   45s

kubectl get providerrevisions
# → NAME                             HEALTHY   REVISION   IMAGE                                                           STATE    DEP-FOUND   DEP-INSTALLED   AGE
# → provider-kubernetes-8b2c4e09f1   True      1          xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.3.0   Active                               50s
```

Также установим стандартную функцию композиции `function-patch-and-transform` и функцию автоматической фиксации готовности `function-auto-ready`:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-patch-and-transform
spec:
  package: xpkg.upbound.io/crossplane-contrib/function-patch-and-transform:v0.8.1
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-auto-ready
spec:
  package: xpkg.upbound.io/crossplane-contrib/function-auto-ready:v0.5.1
```

```bash
kubectl apply -f functions.yaml
# → function.pkg.crossplane.io/function-patch-and-transform created
# → function.pkg.crossplane.io/function-auto-ready created

kubectl get functions
# → NAME                           INSTALLED   HEALTHY   PACKAGE                                                                    AGE
# → function-auto-ready            True        True      xpkg.upbound.io/crossplane-contrib/function-auto-ready:v0.5.1               30s
# → function-patch-and-transform   True        True      xpkg.upbound.io/crossplane-contrib/function-patch-and-transform:v0.8.1      30s
```

---

### Сценарий 3: Настройка ProviderConfig с безопасной аутентификацией

Для управления локальным кластером (In-Cluster) настроим `ProviderConfig`, использующий ServiceAccount пода провайдера, с выдачей минимально необходимых прав через scoped RBAC:

```bash
# Определение системного ServiceAccount, созданного для пода провайдера
SA_NAME=$(kubectl -n crossplane-system get sa -o jsonpath='{.items[?(@.metadata.annotations.pkg\.crossplane\.io/package=="provider-kubernetes")].metadata.name}')
echo "ServiceAccount провайдера: ${SA_NAME}"
# → ServiceAccount провайдера: provider-kubernetes-8b2c4e09f1
```

Создание ограниченной роли и привязки:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: crossplane-provider-k8s-scoped
rules:
  - apiGroups: [""]
    resources: ["namespaces", "configmaps", "resourcequotas", "limitranges", "serviceaccounts"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: crossplane-provider-k8s-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: crossplane-provider-k8s-scoped
subjects:
  - kind: ServiceAccount
    name: provider-kubernetes-8b2c4e09f1
    namespace: crossplane-system
```

```bash
kubectl apply -f provider-rbac.yaml
# → clusterrole.rbac.authorization.k8s.io/crossplane-provider-k8s-scoped created
# → clusterrolebinding.rbac.authorization.k8s.io/crossplane-provider-k8s-binding created
```

Создание `ProviderConfig`:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ProviderConfig
metadata:
  name: default
spec:
  credentials:
    source: InjectedIdentity
```

```bash
kubectl apply -f providerconfig.yaml
# → providerconfig.kubernetes.crossplane.io/default created

kubectl get providerconfig
# → NAME      AGE
# → default   12s
```

*(Для удаленных bare-metal кластеров в поле `spec.credentials.source` указывается `Secret`, а в `secretRef` передается kubeconfig целевого кластера).*

---

### Сценарий 4: Развертывание Managed Resource (MR)

Создадим изолированное рабочее пространство (Namespace) с политикой квотирования через Managed Resource `Object`:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: Object
metadata:
  name: tenant-billing-namespace
spec:
  providerConfigRef:
    name: default
  managementPolicies:
    - Create
    - Update
    - Observe
    - Delete
  forProvider:
    manifest:
      apiVersion: v1
      kind: Namespace
      metadata:
        name: tenant-billing
        labels:
          environment: production
          managed-by: crossplane
```

Применение и проверка статуса сверки:

```bash
kubectl apply -f mr-namespace.yaml
# → object.kubernetes.crossplane.io/tenant-billing-namespace created

kubectl get object tenant-billing-namespace
# → NAME                       SYNCED   READY   AGE
# → tenant-billing-namespace   True     True    18s

kubectl get namespace tenant-billing --show-labels
# → NAME             STATUS   AGE   LABELS
# → tenant-billing   Active   22s   environment=production,kubernetes.io/metadata.name=tenant-billing,managed-by=crossplane
```

Проверка деталей объекта в кластере:

```bash
kubectl get object tenant-billing-namespace -o jsonpath='{.status.conditions}' | jq .
# → [
#     {
#       "lastTransitionTime": "2026-10-13T14:18:02Z",
#       "reason": "Available",
#       "status": "True",
#       "type": "Ready"
#     },
#     {
#       "lastTransitionTime": "2026-10-13T14:18:02Z",
#       "reason": "ReconcileSuccess",
#       "status": "True",
#       "type": "Synced"
#     }
#   ]
```

---

### Сценарий 5: Построение Self-Service платформы (XRD + Composition Pipeline + Claim)

Создадим абстрактный интерфейс заказа изолированного окружения разработчика (`XEnvironment`), автоматически разворачивающий Namespace и сетевую политику NetworkPolicy изоляции трафика.

#### 1. Определение схемы API (XRD)

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xenvironments.platform.internal
spec:
  group: platform.internal
  names:
    kind: XEnvironment
    plural: xenvironments
  claimNames:
    kind: EnvironmentClaim
    plural: environmentclaims
  versions:
    - name: v1alpha1
      served: true
      referenceable: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                teamName:
                  type: string
                  description: "Идентификатор проектной команды"
                cpuQuota:
                  type: string
                  default: "4"
                  description: "Лимит ядер CPU для окружения"
              required:
                - teamName
```

```bash
kubectl apply -f xrd-env.yaml
# → compositeresourcedefinition.apiextensions.crossplane.io/xenvironments.platform.internal created

kubectl get xrd
# → NAME                              ESTABLISHED   OFFERED   AGE
# → xenvironments.platform.internal   True          True      15s
```

#### 2. Определение шаблона реализации (Composition с Pipeline Functions)

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: xenvironment-standard
  labels:
    provider: internal-k8s
spec:
  compositeTypeRef:
    apiVersion: platform.internal/v1alpha1
    kind: XEnvironment
  mode: Pipeline
  pipeline:
    - step: patch-resources
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: team-namespace
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              spec:
                providerConfigRef:
                  name: default
                forProvider:
                  manifest:
                    apiVersion: v1
                    kind: Namespace
                    metadata:
                      labels:
                        platform-tier: team-sandbox
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.teamName
                toFieldPath: spec.forProvider.manifest.metadata.name
          - name: default-deny-networkpolicy
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              spec:
                providerConfigRef:
                  name: default
                forProvider:
                  manifest:
                    apiVersion: networking.k8s.io/v1
                    kind: NetworkPolicy
                    metadata:
                      name: default-deny-ingress
                    spec:
                      podSelector: {}
                      policyTypes:
                        - Ingress
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.teamName
                toFieldPath: spec.forProvider.manifest.metadata.namespace
    - step: automatically-detect-readiness
      functionRef:
        name: function-auto-ready
```

```bash
kubectl apply -f composition-env.yaml
# → composition.apiextensions.crossplane.io/xenvironment-standard created

kubectl get compositions
# → NAME                    XR-KIND        XR-APIVERSION               AGE
# → xenvironment-standard   XEnvironment   platform.internal/v1alpha1   10s
```

#### 3. Пользовательская заявка (Claim) от команды разработчиков

Прикладная команда создает простой манифест в своем пространстве имен (например, `team-dev`):

```yaml
apiVersion: platform.internal/v1alpha1
kind: EnvironmentClaim
metadata:
  name: payments-env
  namespace: default
spec:
  teamName: payments-sandbox
  cpuQuota: "8"
```

```bash
kubectl apply -f claim.yaml
# → environmentclaim.platform.internal/payments-env created

kubectl get claim payments-env
# → NAME           SYNCED   READY   CONNECTION-SECRET   AGE
# → payments-env   True     True                        25s

kubectl get composite
# → NAME                      SYNCED   READY   COMPOSITION              AGE
# → payments-env-2b89f        True     True    xenvironment-standard    30s
```

Трассировка созданной иерархии через Crossplane CLI:

```bash
crossplane beta trace environmentclaim/payments-env -n default
# → NAME                                                  SYNCED   READY   STATUS
# → EnvironmentClaim/payments-env (default)               True     True    Available
# → └─ XEnvironment/payments-env-2b89f                    True     True    Available
# →    ├─ Object/payments-env-2b89f-team-namespace        True     True    Available
# →    └─ Object/payments-env-2b89f-default-deny-net...  True     True    Available
```

---

## Операции и команды

### Утилита crossplane CLI

Справочник команд Crossplane CLI (v2.x) для разработчиков платформ и SRE:

| Команда | Описание | Пример вызова |
| :--- | :--- | :--- |
| `crossplane render` | Локальный рендеринг и отладка композиций без кластера | `crossplane render xr.yaml comp.yaml funcs.yaml` |
| `crossplane beta trace` | Построение дерева зависимостей (Claim → XR → MRs) | `crossplane beta trace xenvironments/my-env` |
| `crossplane beta validate` | Валидация манифестов на соответствие схемам CRD и XRD | `crossplane beta validate schemas/ manifests/` |
| `crossplane xpkg build` | Сборка OCI-пакета Configuration или Provider | `crossplane xpkg build --package-root=. -o pkg.xpkg` |
| `crossplane xpkg push` | Публикация пакета во внутренний OCI-реестр | `crossplane xpkg push pkg.xpkg harbor.corp.local/cp/pkg:v1.0.0` |

#### Пример локального тестирования композиции (crossplane render)

```bash
crossplane render xr.yaml composition.yaml functions.yaml
# → ---
# → apiVersion: kubernetes.crossplane.io/v1alpha1
# → kind: Object
# → metadata:
# →   annotations:
# →     crossplane.io/composition-resource-name: team-namespace
# → spec:
# →   forProvider:
# →     manifest:
# →       apiVersion: v1
# →       kind: Namespace
# →       metadata:
# →         name: payments-sandbox
```

---

### Эксплуатационные команды kubectl для SRE

Агрегированные ресурсы и манипуляции с жизненным циклом в кластере:

| Задача | Команда |
| :--- | :--- |
| Просмотр всех Managed Resources | `kubectl get managed` |
| Просмотр всех Composite Resources | `kubectl get composite` |
| Просмотр всех пользовательских заявок | `kubectl get claim --all-namespaces` |
| Статус всех установленных провайдеров | `kubectl get providers -o wide` |
| Статус функций композиции | `kubectl get functions` |
| Поиск ресурсов с ошибкой сверки | `kubectl get managed -A -l '!crossplane.io/paused' -o json \| jq '.items[] \| select(.status.conditions[]? \| select(.type=="Synced" and .status=="False")) \| .metadata.name'` |
| Экстренная заморозка сверки ресурса | `kubectl annotate managed <name> crossplane.io/paused="true" --overwrite` |
| Разморозка сверки ресурса | `kubectl annotate managed <name> crossplane.io/paused-` |
| Принудительный мгновенный reconcile | `kubectl annotate managed <name> crossplane.io/reconcile-time="$(date +%s)" --overwrite` |

---

## Диагностика и устранение неполадок

### Сбои установки пакетов (PackagePullBackOff)

**Симптом:** При установке `Provider` или `Function` статус остается `INSTALLED=False`, состояние `PackagePullBackOff`.

**Причины:**
1. Не указан FQDN реестра (нарушение стандарта Crossplane v2.x).
2. Ошибка сетевого доступа к реестру из закрытого контура (Airgap).
3. Отсутствуют секреты доступа к приватному OCI-реестру (`imagePullSecrets`).

**Диагностика:**
```bash
kubectl describe provider <provider-name>
# → Look at Events: Failed to pull package: ... 401 Unauthorized / dial tcp: i/o timeout
```

**Решение:**
Настройте `packagePullSecrets` в манифесте `Provider`:
```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: harbor.corp.local/crossplane/provider-kubernetes:v1.3.0
  packagePullSecrets:
    - name: harbor-pull-secret
```

---

### Анализ статусов: расхождение Synced vs Ready

**Симптом:** Объект завис в состоянии `SYNCED=True, READY=False` или `SYNCED=False`.

**Алгоритм локализации:**
1. Проверить события Kubernetes:
   ```bash
   kubectl describe <kind> <resource-name>
   # → Events: Type     Reason             Message
   #           Warning  CannotObserve      ... dial tcp 192.168.10.50:6443: connect: connection refused
   ```
2. Если `SYNCED=False`: ошибка в учетных данных `ProviderConfig`, сетевом доступе к целевой системе или правах RBAC.
3. Если `SYNCED=True`, но `READY=False`: целевой ресурс создан во внешней системе, но не прошел internal readiness check (например, целевой под ожидает PV, база данных инициализирует таблицы).
4. Проверить логи пода конкретного провайдера:
   ```bash
   kubectl -n crossplane-system logs -l pkg.crossplane.io/provider=provider-kubernetes -c package-runtime --tail=100
   ```

---

### Зависание удаления ресурсов и deadlock финалайзеров

**Симптом:** Манифест MR или XR находится в статусе `Terminating` неограниченное время после команды `kubectl delete`.

**Причина:** На ресурсе установлен системный финалайзер `finalizer.managedresource.crossplane.io`. Контроллер пытается удалить физический объект в целевой системе, но не может выполнить запрос (недоступен сетевой эндпоинт, удален секрет `ProviderConfig`, либо целевой ресурс защищен внешней блокировкой).

**Безопасный алгоритм устранения deadlock:**
1. Если физический ресурс уже удален во внешней системе вручную, либо его сохранение допустимо:
   Смените политику удаления на `Orphan`:
   ```bash
   kubectl patch <kind> <name> --type='json' -p='[{"op": "replace", "path": "/spec/deletionPolicy", "value": "Orphan"}]'
   # → patched
   ```
2. Если контроллер по-прежнему не снимает финалайзер из-за сбоя провайдера:
   ```bash
   kubectl patch <kind> <name> --type='json' -p='[{"op": "remove", "path": "/metadata/finalizers"}]'
   # → patched
   ```
   *Внимание: Снятие финалайзера вручную оставляет физический ресурс во внешней системе без присмотра ("осиротевшим"). Убедитесь в его фактическом статусе во внешней инфраструктуре.*

---

### Деградация kube-apiserver и нагрузка на etcd

**Симптом:** Рост времени ответа `kube-apiserver`, увеличение потребления памяти API-сервером, предупреждения о размере БД etcd (`etcdserver: mvcc: database space exceeded`).

**Причины:**
1. Установка монолитных провайдеров старых версий (сотни неиспользуемых CRD).
2. Слишком частый опрос инфраструктуры (`--poll=10s`) при десятках тысяч управляемых объектов.
3. Разрастание истории ревизий объектов.

**Решение для SRE:**
* Использовать раздельные модульные провайдеры (Family Providers) или избирательную регистрацию ресурсов (MRD — Managed Resource Definitions).
* Увеличить интервал сверки через `DeploymentRuntimeConfig`: `--poll=10m`.
* Настроить агрессивную очистку завершенных ревизий пакетов (`spec.revisionHistoryLimit: 1` в ресурсах `Provider` и `Configuration`).
* Вынести тяжелые тенанты в архитектуру vcluster (Hard Multi-Tenancy).

---

### Ошибки в конвейере Composition Functions

**Симптом:** При создании Claim составной ресурс получает статус `Synced=False` с ошибкой вида `cannot run composition pipeline: rpc error: code = Unavailable desc = connection error`.

**Причины:**
1. Под функции (`kind: Function`) аварийно завершился по OOM (`OOMKilled`).
2. Сетевая изоляция (NetworkPolicy) в namespace `crossplane-system` блокирует gRPC-трафик между подом `crossplane` и подом функции.

**Диагностика:**
```bash
kubectl -n crossplane-system get pods -l pkg.crossplane.io/function=function-patch-and-transform
# → NAME                                                  READY   STATUS      RESTARTS   AGE
# → function-patch-and-transform-6b45f-7f89b             0/1     OOMKilled   3          5m

kubectl -n crossplane-system describe pod -l pkg.crossplane.io/function=function-patch-and-transform
```

**Решение:**
Выделите функции адекватные ресурсы через `DeploymentRuntimeConfig` и проверьте сетевые политики в `crossplane-system`.

---

## Лучшие практики

### Архитектурные требования и сайзинг кластера

1. **Выделенный Control Plane:** Для крупных инфраструктур (>500 серверов/кластеров) Crossplane должен функционировать в выделенном инфраструктурном кластере Kubernetes, изолированном от пользовательских прикладных нагрузок.
2. **Изоляция узлов:** Размещайте поды Crossplane и провайдеров на выделенных системных нодах (`nodeSelector: node-role.kubernetes.io/infra: "true"`, `tolerations`), защищенных от OOM-событий сторонних приложений.
3. **Сайзинг etcd:** База данных etcd управляющего кластера должна размещаться на быстрых NVMe-накопителях с гарантированным fsync latency < 10ms. Лимит квоты etcd рекомендуется увеличивать до 8GB (`--quota-backend-bytes=8589934592`).

---

### Безопасность и модель наименьших привилегий

1. **Запрет глобального cluster-admin для провайдеров:** Никогда не назначайте `ClusterRole/cluster-admin` сервисным аккаунтам провайдеров. Формируйте узконаправленные `ClusterRole` (Scoped RBAC) строго под управляемые API-группы.
2. **Изоляция секретов через External Secrets Operator (ESO):** Храните мастер-пароли и учетные данные целевых систем в корпоративном HashiCorp Vault. Доставляйте секреты в `crossplane-system` через ESO непосредственно перед монтированием в `ProviderConfig`.
3. **Валидация манифестов через политики:** Используйте ValidatingAdmissionPolicy (Kubernetes 1.30+) или Kyverno для принудительного контроля входных параметров в XRD/Claim, блокируя опасные конфигурации на этапе поступления в API-сервер. См. [Политики и Governance (Kyverno/OPA)](./policy_governance.md).

---

### Надежность и предотвращение потери данных (Disaster Prevention)

1. **Политика Orphan для критических баз данных и хранилищ:** Для всех производственных ресурсов СХД и баз данных задавайте `spec.deletionPolicy: Orphan`. Это исключит уничтожение данных при случайном удалении пространства имен в GitOps.
2. **Использование Usage CRD:** Блокируйте удаление нижележащих инфраструктурных компонентов при наличии зависимых сервисов через `kind: Usage`.
3. **Регулярный бэкап метаданных:** Регулярно создавайте снимки etcd и резервные копии CRD/Secret через Velero. Подробный план аварийного восстановления описан в [Backup и Disaster Recovery control plane](./backup_dr.md).

---

### Эксплуатация в On-Premise и изоляция Control Plane

1. **Приватные OCI-реестры:** В закрытых промышленных контурах (Airgap) зеркалируйте OCI-пакеты провайдеров и функций во внутренний Harbor. Всегда фиксируйте пакеты по неизменяемым тегам или sha256-дайджестам.
2. **Namespaced XR для мультитенантности:** В Crossplane v2.x переходите на использование namespaced XR. Это позволяет прикладным командам работать внутри своих пространств имен, подчиняться локальным `ResourceQuota` и не иметь доступа к инфраструктуре соседних проектов. См. [Мультитенантность и изоляция](./multi_tenancy.md).

---

## Дополнительная информация

### Связанные разделы базы знаний

* [Управление Kubernetes ресурсами](./provider_kubernetes_setup.md) — детальная настройка `provider-kubernetes`, Server-Side Apply и управление внешними кластерами.
* [Composition Functions и EnvironmentConfig](./composition_functions.md) — глубокое погружение в gRPC-конвейеры функций, KCL и контекст окружений.
* [Интеграция с GitOps](./gitops_integration.md) — совместная работа Crossplane с Argo CD и Flux, настройка синхронизации и Health Checks.
* [Мультитенантность и изоляция](./multi_tenancy.md) — архитектура Soft/Hard мультитенантности, namespaced XR и vcluster.
* [Защита зависимостей (Usage)](./usage_protection.md) — блокировка каскадного удаления связанных ресурсов.
* [Observability](./observability.md) — мониторинг Crossplane, метрики Prometheus, алерты и дашборды Grafana.
* [Backup и Disaster Recovery control plane](./backup_dr.md) — защита etcd, резервное копирование Velero и сценарии восстановления.
* [Тестирование платформы](./testing_crossplane.md) — модульное и интеграционное тестирование Composition (`crossplane render`, chainsaw).
* [Обновление и миграция](./upgrade_migration.md) — регламент обновления версий ядра и миграции с v1.x на v2.x.
* [Политики и Governance (Kyverno/OPA)](./policy_governance.md) — применение политик валидации к инфраструктурным объектам.
* [Self-Service и IDP](./self_service.md) — построение внутренних платформ разработчика на базе Claims и Backstage.
* [Безопасность пакетов](./package_security.md) — проверка подписей OCI-образов (Cosign) и работа в Airgap.
* [Сравнение с Terraform](./terraform_comparison.md) — архитектурные различия Push и Pull моделей IaC.
* [GitOps Overview](../GitOps_overview.md) — методологический обзор декларативного управления конфигурациями.
* [ArgoCD Overview](../ArgoCD/argocd_overview.md) — архитектура и эксплуатация GitOps-оператора.

### Внешние ресурсы

* Официальная документация проекта: [Crossplane Documentation](https://docs.crossplane.io/)
* CNCF проект: [Crossplane Graduation Announcement](https://www.cncf.io/announcements/2025/11/06/cloud-native-computing-foundation-announces-graduation-of-crossplane/)
* Исходный код ядра: [GitHub crossplane/crossplane](https://github.com/crossplane/crossplane)
