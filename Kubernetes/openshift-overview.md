# Обзор Red Hat OpenShift

## Определения

**Red Hat OpenShift** — коммерческий дистрибутив Kubernetes корпоративного уровня от Red Hat (подразделение IBM). Представляет собой платформу класса PaaS (Platform as a Service) с интегрированными инструментами жизненного цикла разработки (DevSecOps), усиленной безопасностью и долгосрочной коммерческой поддержкой. Базируется на RHEL и оптимизирован для гибридных развёртываний on-premise и edge-сред.

**OKD (Origin Kubernetes Distribution)** — community-версия OpenShift с открытым исходным кодом. Служит upstream-проектом для всех коммерческих редакций OpenShift, содержит те же технологии, но без официальной поддержки и сертификации Red Hat.

**RHCOS (Red Hat CoreOS)** — специализированная неизменяемая (immutable) операционная система, на которой базируются узлы Control Plane и Worker в OpenShift 4.x. Все изменения конфигурации применяются declaratively через Machine Config Operator (MCO), а не вручную на узлах.

**CRI-O** — легковесная среда выполнения контейнеров, созданная Red Hat специально для Kubernetes. Является единственным официально поддерживаемым CRI-рантаймом в OpenShift. Строго привязан к релизным циклам Kubernetes и использует `runc` или `crun` как OCI-рантайм. Подробнее: [Container Runtime в Kubernetes](./Concepts/container_runtime.md).

**SCC (Security Context Constraints)** — механизм безопасности OpenShift, контролирующий, какие привилегии могут быть назначены подам и контейнерам. В отличие от Pod Security Standards (PSS) в ванильном Kubernetes, SCC применяются по умолчанию и требуют явного grants для работы привилегированных контейнеров.

**OLM (Operator Lifecycle Manager)** — встроенный механизм управления жизненным циклом операторов в OpenShift. Позволяет устанавливать, обновлять и управлять зависимостями Kubernetes-операторов через Catalog Sources и Subscriptions. В версии 4.19 стабилизирован OLM v1 с декларативным API.

**Routes** — ресурс OpenShift для управления внешним доступом к сервисам. По умолчанию реализован на базе HAProxy, обеспечивает балансировку нагрузки, терминацию TLS и маршрутизацию по хостам/путям. С версии 4.19 Gateway API имеет статус GA и предоставляет более гибкую ролевую модель управления трафиком.

**Image Streams** — абстракция OpenShift, представляющая собой историю версий образов контейнеров в реестре. Позволяет автоматически запускать деплой при появлении нового тега образа, не зная точный digest.

**S2I (Source-to-Image)** — механизм сборки контейнерных образов непосредственно из исходного кода (Git-репозиторий) без написания Dockerfile. Генерирует воспроизводимые образы и интегрирован в BuildConfig.

**BuildConfig** — ресурс OpenShift, описывающий процесс сборки образов. Поддерживает стратегии: Source (S2I), Docker (сборка из Dockerfile), Pipeline (через Tekton).

**`oc`** — официальный CLI-инструмент OpenShift, являющийся надмножеством `kubectl`. Поддерживает все команды Kubernetes и добавляет специфичные для платформы: `oc new-app`, `oc new-build`, `oc rollout history`, `oc adm policy`.

**`odo`** — CLI-инструмент для разработчиков, позволяющий развёртывать приложения на OpenShift без написания манифестов Kubernetes. Автоматически определяет runtime (Java, Node.js, Python, Go) и создаёт необходимые компоненты.

**Версия 4.19 (Июнь 2025):** актуальный релиз, базирующийся на **Kubernetes 1.32** и **CRI-O 1.32**.

## Основные концепции

### Архитектура и ключевые компоненты

OpenShift 4.x использует архитектуру с **управляемым Control Plane** и неизменяемыми рабочими узлами (RHCOS). Все компоненты управляются через Operators, что обеспечивает самовосстановление и автоматические обновления.

#### Компоненты Control Plane

| Компонент | Назначение |
| :--- | :--- |
| **API Server** | Центральный шлюз для всех запросов, совместимый с Kubernetes API. |
| **etcd** | Распределённое хранилище состояния кластера. |
| **Kube Scheduler** | Планирование подов на узлы с учётом ресурсов и политик. |
| **Kube Controller Manager** | Набор контроллеров, следящих за состоянием кластера. |
| **Machine Config Operator (MCO)** | Управляет конфигурацией RHCOS-узлов через MachineConfig и MachineConfigPool. |
| **Cluster Version Operator (CVO)** | Управляет обновлением всех компонентов кластера. |
| **Operator Lifecycle Manager (OLM)** | Жизненный цикл операторов и Catalog Sources. |

#### Компоненты Worker Plane

| Компонент | Назначение |
| :--- | :--- |
| **Kubelet** | Агент на узле, управляющий запуском контейнеров через CRI-O. |
| **Kube Proxy** | Сетевой агент, управляющий правилами iptables/nftables для Service. |
| **CRI-O** | Среда выполнения контейнеров. Подробнее: [Container Runtime в Kubernetes](./Concepts/container_runtime.md#2-cri-o). |
| **Container Runtime (runc/crun)** | Низкоуровневый OCI-рантайм для создания контейнеров. |

#### Встроенные сервисы платформы

- **Internal Registry** — контейнерный реестр, интегрированный в кластер для хранения образов.
- **Monitoring Stack** — на базе Prometheus, Thanos Ruler и Grafana. Собирает метрики узлов, подов и операторов.
- **Logging Stack** — агрегация логов через Elasticsearch/OpenSearch, Fluentd и Kibana/OpenSearch Dashboards.
- **Service Mesh** — основанная на Istio, опционально устанавливается через Operator.

### Ключевые отличия от ванильного Kubernetes

| Параметр | OpenShift | Kubernetes (vanilla) |
| :--- | :--- | :--- |
| **Безопасность** | SCC (Security Context Constraints) — строгие политики по умолчанию; Secrets Store CSI (GA) | PSS (Pod Security Standards) — требует ручной настройки |
| **Среда выполнения (Runtime)** | CRI-O (единственный поддерживаемый) | containerd / CRI-O / Docker (через адаптеры) |
| **Интерфейс командной строки (CLI)** | `oc` — надмножество над `kubectl`; `odo` для разработчиков | `kubectl` — базовое управление ресурсами |
| **Веб-интерфейс (Web UI)** | Полнофункциональная консоль (Admin + Developer Topology) | Требует отдельной установки (Dashboard) |
| **CI/CD и GitOps** | Встроенные OpenShift Pipelines (Tekton) и GitOps (ArgoCD) | Требует самостоятельной интеграции |
| **Виртуализация** | OpenShift Virtualization (KubeVirt) — глубокая интеграция VM | Требует ручной настройки KubeVirt |
| **Сетевой плагин (CNI)** | OVN-Kubernetes (стандарт); Gateway API (GA в 4.19) | Любой совместимый (Calico, Cilium, Flannel) |
| **Обновления** | Over-the-Air (OTA) — автоматизированы через Operators | Ручное или полуавтоматическое обновление |
| **Сборка образов** | S2I и BuildConfig из коробки | Требует отдельной настройки CI/CD |

### Сетевое взаимодействие и безопасность

#### Сетевая модель

OpenShift использует **OVN-Kubernetes** как стандартный CNI-плагин. OVN предоставляет:
- Логическую коммутацию и маршрутизацию между подами через GENEVE-туннели (порт 6081).
- Нативные NetworkPolicy без дополнительных компонентов.
- Поддержку IPv4/IPv6 dual-stack.

#### User Defined Networks (UDN)

Позволяет создавать изолированные L2/L3 сегменты для групп приложений или виртуальных машин. UDN реализуется через отдельные OVN-коммутаторы, что обеспечивает изоляцию трафика между командами (multi-tenancy).

#### Интеграция с BGP

Нативная поддержка Border Gateway Protocol для анонсирования IP-адресов подов и виртуальных машин во внешнюю сеть ЦОД через FRR (Free Range Routing). Позволяет использовать оборудование дата-центра без overlay-сетей.

#### Compliance Operator

Автоматизирует проверку кластера на соответствие стандартам PCI DSS, HIPAA и NIST. Использует профили OpenSCAP для сканирования узлов и корректировки (remediation) через MachineConfig.

#### Secrets Store CSI Driver

Позволяет подключать секреты из внешних хранилищ (HashiCorp Vault, Azure Key Vault) без их создания внутри Kubernetes. Секреты монтируются как in-memory том и автоматически ротируются.

### Хранение данных

- **OpenShift Data Foundation (ODF):** Программно-определяемое хранилище на базе Ceph/Rook, интегрированное в консоль управления. Поддерживает блоки (RBD), файловые системы (CephFS) и объектное хранилище (RGW).
- **Live Migration для хранилищ VM:** Возможность перемещения дисков виртуальных машин между разными Storage Class без остановки работы (GA в 4.18).
- **LVMO (Logical Volume Manager Operator):** Управление логическими томами LVM через Kubernetes API для блочного хранилища.

### Методы установки кластера

1.  **Installer-Provisioned Infrastructure (IPI):** Полностью автоматизированная установка, где инсталлятор сам создаёт ресурсы в виртуализации (vSphere) или Bare Metal.
2.  **User-Provisioned Infrastructure (UPI):** Установка на заранее подготовленную инфраструктуру (Bare Metal, сложные сетевые топологии).
3.  **Agent-Based Installer (ABI):** Гибридный метод для Edge и Bare Metal сред, использующий единый загрузочный образ (ISO) для автоматической настройки узлов.

### Редакции OpenShift

| Редакция | Среда развёртывания и особенности |
| :--- | :--- |
| **OpenShift Container Platform (OCP)** | Основная редакция для on-premise и частных инфраструктур. |
| **OpenShift Virtualization Engine (OVE)** | Специализированная редакция (4.18+) для замены традиционных гипервизоров. |
| **MicroShift** | Сверхлёгкий дистрибутив для Edge-устройств с минимальными ресурсами. |

## Требования к ресурсам

OpenShift требует значительных ресурсов для работы встроенных сервисов (мониторинг, логирование, реестр):

- **Control Plane (3 узла):** минимум 4 vCPU / 16 GB RAM на узел. Для HA рекомендуется 8 vCPU / 32 GB RAM.
- **Worker Nodes:** минимум 2 узла (рекомендуется от 3). Для ODF/Virtualization требования возрастают до 8 vCPU / 32 GB RAM на узел.
- **Дисковая подсистема:** Низкая задержка (low latency) обязательна для etcd. Минимум 100 GB SSD на узел Control Plane.
- **Сеть:** Минимум 2 NIC на узел. Рекомендуется разделение management- и workload-сетей.

## Практические сценарии

### Предварительные требования

Перед началом работы с кластером убедитесь, что выполнены следующие условия:

1.  **Кластер OpenShift 4.19+** с административным доступом (`cluster-admin`).
2.  **`oc` CLI** версии, совпадающей с версией кластера. Проверка:
    ```bash
    oc version --client
    # → Client Version: 4.19.0
    # → Kubernetes Server Version: 1.32.0
    ```
3.  **Файл `kubeconfig`** с правами администратора. По умолчанию: `~/.kube/config`.
4.  **Сеть:** Открытые порты 6443 (API), 22623 (Ignition), 80/443 (Ingress), 5353 (DNS).
5.  **Резервная копия etcd:** Перед обновлением или масштабированием создайте снапшот:
    ```bash
    oc get nodes -l node-role.kubernetes.io/master
    # → NAME        STATUS   ROLES    AGE   VERSION
    # → master-0    Ready    master   30d   v1.32.0

    ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
      --cacert=/etc/kubernetes/static-pod-resources/etcd-certs/ca.crt \
      --cert=/etc/kubernetes/static-pod-resources/etcd-certs/peer.crt \
      --key=/etc/kubernetes/static-pod-resources/etcd-certs/peer.key \
      snapshot save /backup/etcd-snapshot-$(date +%Y%m%d).db
    # → Snapshot saved at /backup/etcd-snapshot-20260903.db
    ```

### Базовое администрирование через CLI

#### Подключение к кластеру

```bash
# Аутентификация через bearer token
oc login https://api.ocp.example.com:6443 --token=sha256~abcdef...

# Аутентификация через kubeconfig
oc login --kubeconfig=/path/to/admin.kubeconfig

# Переключение контекста
oc config current-context
# → api.ocp.example.com:6443/admin

# Проверка доступа
oc get nodes
# → NAME        STATUS   ROLES    AGE   VERSION   INTERNAL-IP
# → master-0    Ready    master   30d   v1.32.0   10.0.1.10
# → master-1    Ready    master   30d   v1.32.0   10.0.1.11
# → master-2    Ready    master   30d   v1.32.0   10.0.1.12
# → worker-0    Ready    worker   30d   v1.32.0   10.0.2.10
# → worker-1    Ready    worker   30d   v1.32.0   10.0.2.11
```

#### Управление проектами (Namespaces)

```bash
# Создание нового проекта (namespace)
oc new-project myapp
# → Now using project "myapp" on server "https://api.ocp.example.com:6443".

# Список проектов
oc get projects
# → NAME        DISPLAY NAME   STATUS
# → default     Default        Active
# → kube-system                 Active
# → myapp       MyApp          Active
# → openshift-apiserver        Active

# Переключение проекта
oc project default
# → Now using project "default" on server "https://api.ocp.example.com:6443".

# Удаление проекта
oc delete project myapp
# → project.project.openshift.io "myapp" deleted
```

#### Информация о кластере

```bash
# Версия кластера и доступные обновления
oc get clusterversion
# → NAME      VERSION   AVAILABLE   PROGRESSING   SINCE   STATUS
# → version   4.19.0    True        False         30d     Cluster version is 4.19.0

# Состояние узлов
oc get nodes -o wide
# → NAME        STATUS   ROLES    AGE   VERSION   INTERNAL-IP   OS IMAGE
# → master-0    Ready    master   30d   v1.32.0   10.0.1.10     Red Hat Enterprise Linux CoreOS 419.94.202...

# Проверка состояния компонентов (Control Plane)
oc get co
# → NAME                                       VERSION   AVAILABLE   PROGRESSING   DEGRADED   SINCE
# → authentication                             4.19.0    True        False         False      30d
# → console                                    4.19.0    True        False         False      30d
# → ingress                                    4.19.0    True        False         False      30d
# → machine-config                             4.19.0    True        False         False      30d
```

### Управление безопасностью

#### Просмотр и проверка SCC

```bash
# Список всех SCC
oc get scc
# → NAME                        PRIV   CAPS   SELINUX   RUNASUSER   FSGROUP   SUPGROUP   PRIORITY   READONLYROOTFS   VOLUMES
# → restricted                  false          RunAsAny   MustRunAs  RunAsAny  <none>    10          false            [configMap downwardAPI emptyDir persistentVolumeClaim projected secret]
# → anyuid                      false          RunAsAny   RunAsAny   RunAsAny  <none>    20          false            [configMap downwardAPI emptyDir persistentVolumeClaim projected secret]
# → hostaccess                  false          MustRunAs  RunAsAny   RunAsAny  <none>    30          false            [configMap downwardAPI emptyDir persistentVolumeClaim projected secret]

# Проверка SCC для конкретного сервисного аккаунта
oc get scc restricted -o yaml | grep -A5 runAsUser
# → runAsUser:
# →   type: MustRunAsRange
# →   uidRangeMin: 1000640000
# →   uidRangeMax: 1000649999

# Проверка, какая SCC назначена поду
oc get pod mypod -o yaml | grep -A5 scc
# → openshift.io/scc: restricted
```

#### Настройка SCC для привилегированных workload

```bash
# Добавление сервисного аккаунта в группу privileged SCC
oc adm policy add-scc-to-user privileged -z myserviceaccount
# → scc.security.openshift.io/privileged added to: "system:serviceaccount:myapp:myserviceaccount"

# Проверка
oc adm policy who-can use scc privileged
# → system:serviceaccount:myapp:myserviceaccount
```

### Сетевое взаимодействие

#### Создание Route

```bash
# Создание Route для существующего Service
oc create route edge myapp --service=myapp --port=8080 --hostname=myapp.example.com
# → route.route.openshift.io/myapp created

# Проверка
oc get route myapp
# → NAME     HOSTNAME             SERVICES  PORT       TERMINATION   WILDCARD
# → myapp    myapp.example.com    myapp     8080-tcp   edge          None

# Проверка статуса
oc get route myapp -o yaml | grep -A3 ingress
# → ingress:
# → - conditions:
# →     lastTransitionTime: "2026-09-03T10:00:00Z"
# →     status: "True"
# →     type: Admitted
```

#### Gateway API (GA в 4.19)

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: myapp-gateway
  namespace: myapp
spec:
  gatewayClassName: openshift-default
  listeners:
  - name: http
    hostname: "*.example.com"
    port: 80
    protocol: HTTP
    allowedRoutes:
      namespaces:
        from: All
  - name: https
    hostname: "*.example.com"
    port: 443
    protocol: HTTPS
    tls:
      certificateRefs:
      - name: myapp-tls
        kind: Secret
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: myapp-route
  namespace: myapp
spec:
  parentRefs:
  - name: myapp-gateway
  hostnames:
  - "app.example.com"
  rules:
  - backendRefs:
    - name: myapp
      port: 8080
```

### Развертывание приложений

#### Развёртывание через S2I

```bash
# Автоматическое создание приложения из Git-репозитория
oc new-app https://github.com/sclorg/nodejs-ex.git --name=myapp
# → ...
# → --> Creating resources with label app=myapp ...
# →    imagestream.image.openshift.io "myapp" created
# →    buildconfig.build.openshift.io "myapp" created
# →    deployment.apps "myapp" created
# →    service "myapp" created

# Проверка сборки
oc get builds
# → NAME     TYPE      SOURCE                      FROM                    STATUS     STARTED         DURATION
# → myapp-1  Source    https://github.com/...      Base Image S2I Builder  Complete   5 minutes ago   1m30s

# Проверка ImageStream
oc get is
# → NAME     IMAGE REPOSITORY                                  TAGS
# → myapp    default-route-openshift-image-registry...        latest
```

#### Вручную через Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
  namespace: myapp
  labels:
    app: myapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: myapp
        image: registry.example.com/myapp:1.0.0
        ports:
        - containerPort: 8080
          protocol: TCP
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
        readinessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 20
---
apiVersion: v1
kind: Service
metadata:
  name: myapp
  namespace: myapp
spec:
  selector:
    app: myapp
  ports:
  - name: http
    port: 8080
    targetPort: 8080
    protocol: TCP
  type: ClusterIP
```

```bash
# Применение манифеста
oc apply -f myapp.yaml
# → deployment.apps/myapp created
# → service/myapp created

# Проверка статуса деплоя
oc rollout status deployment/myapp -n myapp
# → deployment "myapp" successfully rolled out

# Проверка подов
oc get pods -n myapp
# → NAME                    READY   STATUS    RESTARTS   AGE
# → myapp-5d9c7d9c9f-abc12 1/1     Running   0          2m
# → myapp-5d9c7d9c9f-def34 1/1     Running   0          2m
# → myapp-5d9c7d9c9f-ghi56 1/1     Running   0          2m

# Проверка здоровья
oc get endpoints myapp -n myapp
# → NAME     ENDPOINTS         AGE
# → myapp    10.244.0.5:8080   2m
```

### Установка и управление операторами

```bash
# Установка оператора через OperatorHub
oc create -f - <<EOF
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: my-operator
  namespace: openshift-operators
spec:
  channel: stable
  name: my-operator
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
EOF

# Проверка установки
oc get csv -n openshift-operators
# → NAME                              DISPLAY   VERSION   REPLACES   PHASE
# → my-operator.v1.2.3               My Operator 1.2.3                Succeeded

# Проверка CRD, созданных оператором
oc get crd | grep myoperator
# → myresources.myoperator.example.com   2026-09-03T10:00:00Z
```

### Мониторинг и логирование

```bash
# Проверка статуса встроенного мониторинга
oc get pods -n openshift-monitoring
# → NAME                                   READY   STATUS    RESTARTS   AGE
# → alertmanager-main-0                    3/3     Running   0          30d
# → prometheus-adapter-xxxxx               1/1     Running   0          30d
# → prometheus-k8s-0                       2/2     Running   0          30d

# Доступ к веб-интерфейсу Grafana
oc get route -n openshift-monitoring grafana
# → grafana     grafana-openshift-monitoring.apps.ocp.example.com    grafana   <none>           web

# Просмотр логов кластерных компонентов
oc logs -l app=oauth-openshift -n openshift-authentication
# → ... I0903 10:00:00.000000      1 oauth_server.go:123] Starting OAuth server

# Поиск событий кластера
oc get events --sort-by='.lastTimestamp' -n myapp
# → LAST SEEN   TYPE      REASON              OBJECT                     MESSAGE
# → 2m          Normal   Scheduled           pod/myapp-abc12            Successfully assigned myapp to worker-0
# → 2m          Normal   Pulling             pod/myapp-abc12            Pulling image "registry..."
# → 1m          Normal   Pulled              pod/myapp-abc12            Successfully pulled image
# → 1m          Normal   Created             pod/myapp-abc12            Created container myapp
# → 1m          Normal   Started             pod/myapp-abc12            Started container myapp
```

### Резервное копирование и восстановление

```bash
# Резервное копирование etcd (только на Control Plane)
ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/static-pod-resources/etcd-certs/ca.crt \
  --cert=/etc/kubernetes/static-pod-resources/etcd-certs/peer.crt \
  --key=/etc/kubernetes/static-pod-resources/etcd-certs/peer.key \
  snapshot save /backup/etcd-snapshot.db
# → Snapshot saved at /backup/etcd-snapshot.db

# Проверка снапшота
ETCDCTL_API=3 etcdctl --write-out=table snapshot status /backup/etcd-snapshot.db
# → +----------+----------+------------+------------+
# → |  HASH    | REVISION | TOTAL KEYS | TOTAL SIZE |
# → |  abcdef12 | 12345678  | 54321      | 1.2 GB     |
# → +----------+----------+------------+------------+

# Восстановление из снапшота
# (выполняется на остановленном кластере)
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-snapshot.db \
  --name=master-0 \
  --initial-cluster=master-0=https://10.0.1.10:2380 \
  --initial-cluster-token=etcd-restore-2026 \
  --data-dir=/var/lib/etcd-restore
```

### Устранение неполадок

#### Диагностика состояния кластера

```bash
# Проверка статуса всех компонентов
oc get co | grep -v True
# → Выход будет пустым, если все компоненты healthy

# Проверка состояния узлов
oc get nodes
# → NAME        STATUS   ROLES    AGE   VERSION
# → worker-2    NotReady worker   30d   v1.32.0

# Детальная информация о проблемном узле
oc describe node worker-2 | grep -A10 Conditions:
# → Conditions:
# →   Type             Status  LastHeartbeatTime                 LastTransitionTime                Reason              Message
# →   ----             ------  -------------------                 ------------------                ------              -------
# →   MemoryPressure   False   Thu, 03 Sep 2026 10:00:00...      Thu, 03 Sep 2026 09:00:00...      KubeletHasSufficientMemory   kubelet has sufficient memory available
# →   DiskPressure     False   Thu, 03 Sep 2026 10:00:00...      Thu, 03 Sep 2026 09:00:00...      KubeletHasNoDiskPressure  kubelet has no disk pressure
# →   PIDPressure      False   Thu, 03 Sep 2026 10:00:00...      Thu, 03 Sep 2026 09:00:00...      KubeletHasSufficientPID   kubelet has sufficient PID available
# →   Ready            False   Thu, 03 Sep 2026 10:00:00...      Thu, 03 Sep 2026 09:00:00...      KubeletNotReady      container runtime network not ready: NetworkReady=false reason:NetworkPluginNotReady message:Network plugin returns error: cni plugin not initialized

# Проверка логов kubelet на узле
sudo journalctl -u kubelet -f --since "10 minutes ago"
```

#### Частые проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **ImagePullBackOff** | Неверный образ, нет доступа к реестру, неверный секрет | `oc describe pod <pod>` → проверка events. Убедитесь, что `imagePullSecret` настроен для приватных реестров. |
| **CrashLoopBackOff** | Ошибка в приложении, неверная конфигурация, нехватка памяти | `oc logs <pod> --previous` → логи предыдущего контейнера. Проверьте `oc get events`. |
| **Pod Pending** | Нет подходящего узла, нехватка ресурсов, PVC не привязан | `oc describe pod <pod>` → проверка Conditions и Events. `oc get resourcequotas`, `oc get limitranges`. |
| **Node NotReady** | Проблемы с kubelet, сетью, CRI-O или ядром | `sudo systemctl status kubelet`, `sudo crictl info`, `oc get nodes -o yaml`. |
| **SCC denied** | Под пытается использовать запрещённые привилегии | `oc get events` → `pods "myapp" is forbidden: unable to validate against any security context constraint`. Добавьте SCC grants: `oc adm policy add-scc-to-user restricted -z myserviceaccount`. |

### Best Practices и очистка

1.  **Используйте `oc logout` и очистку кэша** после работы с кластером:
    ```bash
    oc logout
    rm -rf ~/.kube/cache ~/.kube/http-cache
    ```

2.  **Никогда не редактируйте ресурсы напрямую через `oc edit`** в production. Используйте GitOps (ArgoCD/Flux) для declarative управления.

3.  **Назначайте ресурсные запросы и лимиты** для всех контейнеров через LimitRange в namespace:
    ```bash
    oc create limitrange myapp-limits -n myapp -f - <<EOF
    apiVersion: v1
    kind: LimitRange
    metadata:
      name: myapp-limits
      namespace: myapp
    spec:
      limits:
      - default:
          cpu: 500m
          memory: 256Mi
        defaultRequest:
          cpu: 100m
          memory: 128Mi
        type: Container
    EOF
    ```

4.  **Используйте NetworkPolicy** для изоляции трафика между namespace:
    ```yaml
    apiVersion: networking.k8s.io/v1
    kind: NetworkPolicy
    metadata:
      name: deny-from-other-namespaces
      namespace: myapp
    spec:
      podSelector: {}
      policyTypes:
      - Ingress
      ingress:
      - from:
        - podSelector:
            matchLabels:
              namespace: myapp
    ```

5.  **Регулярно обновляйте `oc` CLI** до версии, совпадающей с сервером. Несовпадение версий может привести к неожиданному поведению.

### Ограничения и альтернативы

- **Малые проекты:** Для небольших приложений OpenShift может быть избыточен по стоимости и ресурсам. Рассмотрите ванильный Kubernetes или Managed K8s.
- **Экстремальная кастомизация:** Если требуется замена базовых компонентов (например, замена OVN на специфичный CNI), OpenShift может ограничивать гибкость из-за жёсткой связки с операторами.
- **Высокие требования к ресурсам:** Минимальный production-кластер требует минимум 9 узлов (3 Control Plane + 6 Worker), что нетеconomic для небольших команд.

## Дополнительная информация

### Ссылки

- [Официальная документация Red Hat OpenShift](https://docs.openshift.com/)
- [OKD Project — upstream-версия](https://www.okd.io/)
- [OpenShift Local — запуск на ноутбуке](https://developers.redhat.com/products/openshift-local/overview)

### См. также

- [Kubernetes — обзор](./kubernetes_overview.md)
- [Container Runtime в Kubernetes](./Concepts/container_runtime.md)
- [Kubernetes-операторы: автоматизация управления приложениями](./Concepts/kubernetes_operators.md)
