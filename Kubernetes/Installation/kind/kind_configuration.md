# kind — конфигурация кластера

## Определения

**Конфигурационный файл kind** — YAML-манифест, определяющий архитектуру и параметры локального кластера Kubernetes. Позволяет декларативно описывать топологию узлов, настройки сети, проброс портов и патчи для внутренних компонентов (kubeadm, containerd).

**kind.x-k8s.io/v1alpha4** — актуальная версия API конфигурации `kind` на август 2026 года.

---

## Основные концепции

### Структура конфигурации

Базовые поля конфигурационного файла:

| Поле | Описание | Обязательное |
| :--- | :--- | :--- |
| `kind` | Тип объекта, всегда `Cluster` | Да |
| `apiVersion` | Версия API, `kind.x-k8s.io/v1alpha4` | Да |
| `nodes` | Список узлов кластера | Да |
| `networking` | Настройки сети (подсети, CNI, kube-proxy, Dual-stack) | Нет |
| `containerdConfigPatches` | Патчи конфигурации containerd (например, для реестров) | Нет |
| `featureGates` | Включение экспериментальных функций Kubernetes | Нет |
| `runtimeConfig` | Включение/выключение групп API (например, `v1alpha1`) | Нет |

### Типы узлов

| Роль | Описание |
| :--- | :--- |
| `control-plane` | Управляющий узел (содержит API server, scheduler, controller-manager, etcd) |
| `worker` | Рабочий узел для размещения пользовательских подов |

### Параметры узла

Каждый элемент в списке `nodes` может содержать следующие параметры:

| Параметр | Описание |
| :--- | :--- |
| `role` | Роль узла: `control-plane` или `worker` |
| `image` | Docker-образ узла (например, `kindest/node:v1.37.0`) |
| `extraPortMappings` | Проброс портов с хоста в контейнер узла (необходимо для Ingress, NodePort) |
| `extraMounts` | Проброс директорий или файлов с хост-машины внутрь узла |
| `kubeadmConfigPatches` | Патчи конфигурации `kubeadm` (InitConfiguration, ClusterConfiguration, JoinConfiguration) |
| `labels` | Добавление Kubernetes-меток (Labels) на узел при его регистрации |

---

## Практические сценарии

### Минимальная конфигурация

Кластер с одним control-plane и одним worker:

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
- role: worker
```

### Проброс портов (extraPortMappings)

Используется для прямого доступа к сервисам кластера (например, к Ingress-контроллеру) с хост-машины без использования `kubectl port-forward`:

```yaml
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
  - containerPort: 30000
    hostPort: 30000
    listenAddress: "127.0.0.1"
    protocol: TCP
```

| Параметр | Описание |
| :--- | :--- |
| `containerPort` | Порт внутри контейнера узла (часто порт NodePort сервиса или порт Ingress контроллера) |
| `hostPort` | Порт на хост-машине |
| `listenAddress` | IP-адрес для прослушивания (по умолчанию `0.0.0.0`) |
| `protocol` | Протокол: `TCP`, `UDP` или `SCTP` |

### Монтирование томов (extraMounts)

Общий доступ к файлам между хостом и узлами (полезно для монтирования конфигураций, сертификатов или общих данных):

```yaml
nodes:
- role: control-plane
  extraMounts:
  - hostPath: /var/run/docker.sock
    containerPath: /var/run/docker.sock
    readOnly: true
  - hostPath: /data/local-storage
    containerPath: /mnt/storage
    propagation: Bidirectional
```

| Параметр | Описание |
| :--- | :--- |
| `hostPath` | Абсолютный путь на хост-машине |
| `containerPath` | Абсолютный путь внутри контейнера узла |
| `readOnly` | Монтировать только для чтения (по умолчанию `false`) |
| `propagation` | Режим проброса MountPropagation: `None`, `HostToContainer`, `Bidirectional` |
| `selinuxRelabel` | Перемаркировка файлов для совместимости с SELinux (по умолчанию `false`) |

### Патчи kubeadm (v1beta4)

Начиная с Kubernetes 1.36 (актуально для августа 2026), рекомендуется использовать версию API `kubeadm.k8s.io/v1beta4` для патчинга компонентов Control Plane. Патчи применяются **после** базовой конфигурации kind и позволяют тонко настроить каждый компонент кластера.

**Типы объектов для патчинга:**

| Kind | Назначение | Примеры настраиваемых полей |
| :--- | :--- | :--- |
| `InitConfiguration` | Параметры инициализации кластера и начальной настройки узла | `nodeRegistration`, `kubeletExtraArgs` |
| `ClusterConfiguration` | Глобальные настройки компонентов Control Plane | `apiServer`, `controllerManager`, `scheduler`, `etcd` |
| `JoinConfiguration` | Параметры присоединения worker-узлов к кластеру | `nodeRegistration`, `kubeletExtraArgs` |

**Пример 1: Базовый патч — labels и kubelet:**

```yaml
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
        fail-swap-on: "false"
```

> **Примечание:** Параметр `fail-swap-on: "false"` позволяет kubelet запускаться при включном swap на хосте. По умолчанию kubelet отказывается стартовать, если swap активен, что часто встречается на настольных Linux-системах.

**Пример 2: Аудит API-сервера и admission-плагины:**

```yaml
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: ClusterConfiguration
    apiVersion: kubeadm.k8s.io/v1beta4
    apiServer:
      extraArgs:
        enable-admission-plugins: NodeRestriction,PodSecurity
      extraVolumes:
      - name: audit-config
        hostPath: /etc/kubernetes/audit-policy.yaml
        mountPath: /etc/kubernetes/audit-policy.yaml
        readOnly: true
```

> **Примечание:** Плагин `PodSecurityPolicy` (удален в K8s 1.25) окончательно заменен на актуальный встроенный механизм `PodSecurity`. Не добавляйте `PodSecurityPolicy` в `enable-admission-plugins` — это вызовет ошибку запуска API-сервера.

**Пример 3: Настройка scheduler и controller-manager:**

```yaml
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: ClusterConfiguration
    apiVersion: kubeadm.k8s.io/v1beta4
    scheduler:
      extraArgs:
        # Включение профилирования scheduler (полезно для анализа производительности)
        profiling: "true"
        # Настройка максимального количества tentative узлов для scheduling (по умолчанию 50)
        maximum-failures: "3"
    controllerManager:
      extraArgs:
        # Увеличениеافة интервала между delete-операциями для GC (снижение нагрузки)
        terminated-pod-gc-threshold: "100"
        # Включение(metrics) для мониторинга controller-manager
        bind-address: "0.0.0.0"
```

> **Практический смысл:** `bind-address: "0.0.0.0"` для controller-manager и scheduler позволяет собирать их метрики через Prometheus с любого IP-адреса в сети. По умолчанию они слушают только `127.0.0.1`, что недоступно извне узла.

**Пример 4: kubelet — eviction thresholds и system-reserved:**

```yaml
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        # Резервирование ресурсов для системных процессов (не для подов)
        system-reserved: "cpu=500m,memory=512Mi,ephemeral-storage=1Gi"
        # Пороговые значения для eviction подов (защита от OOM и деградации диска)
        eviction-hard: "memory.available<256Mi,nodefs.available<10%"
        eviction-minimum-reclaim: "nodefs.available=5%"
        # Лимит максимального количества подов на узле
        max-pods: "110"
```

| Параметр kubelet | Описание | Рекомендация |
| :--- | :--- | :--- |
| `system-reserved` | Ресурсы, зарезервированные для системных демонов (kubelet, containerd, OS). Не участвуют в scheduling подов. | `cpu=250m-500m`, `memory=256Mi-512Mi` для разработки; увеличьте в зависимости от нагрузки. |
| `eviction-hard` | Пороги, при которых kubelet начинает удалять поды для защиты узла. | `memory.available<256Mi` — стандарт для dev; `nodefs.available<10%` — защита от заполнения диска. |
| `eviction-minimum-reclaim` | Минимальный объем ресурсов, который kubelet должен освободить после eviction. | `nodefs.available=5%` — предотвращает циклические eviction-циклы. |
| `max-pods` | Максимальное количество подов на узле. | `110` (по умолчанию). Увеличивайте осторожно — каждый под потребляет ресурсы kubelet и CNI. |

**Пример 5: Настройка etcd (размер snapshot и quota):**

```yaml
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: ClusterConfiguration
    apiVersion: kubeadm.k8s.io/v1beta4
    etcd:
      local:
        extraArgs:
          # Максимальный размер базы данных etcd (в байтах). По умолчанию 8GB.
          quota-backend-bytes: "8589934592"
          # Интервал автоматического compaction (по умолчанию 5 минут)
          auto-compaction-retention: "5"
```

> **Важно:** Для кластеров kind (тестовые среды) стандартных значений etcd достаточно. Увеличение `quota-backend-bytes` необходимо только при большом количестве объектов (10000+ подов/секвисов). При заполнении etcd API-сервер начнет отклонять write-операции.

**Полный пример с несколькими патчами:**

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
        system-reserved: "cpu=500m,memory=512Mi"
        eviction-hard: "memory.available<256Mi,nodefs.available<10%"
        fail-swap-on: "false"
  - |
    kind: ClusterConfiguration
    apiVersion: kubeadm.k8s.io/v1beta4
    apiServer:
      extraArgs:
        enable-admission-plugins: NodeRestriction,PodSecurity
        audit-log-path: /var/log/kubernetes/audit/audit.log
      extraVolumes:
      - name: audit-log
        hostPath: /var/log/kubernetes/audit
        mountPath: /var/log/kubernetes/audit
        readOnly: false
    scheduler:
      extraArgs:
        profiling: "true"
    controllerManager:
      extraArgs:
        bind-address: "0.0.0.0"
- role: worker
  kubeadmConfigPatches:
  - |
    kind: JoinConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        system-reserved: "cpu=250m,memory=256Mi"
        eviction-hard: "memory.available<256Mi,nodefs.available<10%"
```

> **Примечание:** worker-узлы используют `JoinConfiguration` вместо `InitConfiguration`, так как они присоединяются к уже существующему кластеру, а не инициализируют его.

### Настройка containerd (containerdConfigPatches)

Позволяет изменять конфигурацию Container Runtime внутри узла. Самый частый сценарий — настройка mirror-реестров или insecure-registry.

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
containerdConfigPatches:
- |-
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
    endpoint = ["https://mirror.gcr.io", "https://registry-1.docker.io"]
  [plugins."io.containerd.grpc.v1.cri".registry.configs."my-registry.local:5000".tls]
    insecure_skip_verify = true
nodes:
- role: control-plane
```

### Сетевая конфигурация (Networking)

Позволяет переопределить подсети кластера, включить поддержку IPv6 (или Dual-Stack) и отключить стандартный CNI-плагин (kindnet).

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  ipFamily: dual  # ipv4, ipv6, dual
  podSubnet: "10.244.0.0/16,fd00:10:244::/56"
  serviceSubnet: "10.96.0.0/12,fd00:10:96::/108"
  disableDefaultCNI: true  # Полезно для установки Calico или Cilium
  kubeProxyMode: "iptables"  # iptables, ipvs, или none
nodes:
- role: control-plane
- role: worker
```

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `ipFamily` | Семейство IP: `ipv4`, `ipv6`, `dual` | `ipv4` |
| `podSubnet` | Подсеть для подов | `10.244.0.0/16` |
| `serviceSubnet` | Подсеть для ClusterIP сервисов | `10.96.0.0/12` |
| `disableDefaultCNI` | Не устанавливать `kindnet` | `false` |
| `kubeProxyMode` | Режим работы kube-proxy: `iptables`, `ipvs`, `none` | `iptables` |
| `apiServerAddress` | IP-адрес API-сервера для прослушивания | `127.0.0.1` |
| `apiServerPort` | Порт API-сервера | Случайный порт |

> **Практический пример:** параметр `apiServerPort` полезен при запуске нескольких кластеров одновременно — каждый кластер получает уникальный порт API-сервера, что исключает конфликты. Порт отображается в выводе `kubectl cluster-info` после создания кластера.

### Включение экспериментальных функций (featureGates)

Поле `featureGates` позволяет включить или выключить экспериментальные функции Kubernetes на уровне кластера. Каждая функция задается парой ключ-значение, где значение — строка `true` или `false`.

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
featureGates:
  # Включение SidecarContainers (бета-функция для init-контейнеров с restartPolicy: Always)
  SidecarContainers: "true"
  # Включение токен-обновления ServiceAccount
  UpdateTokenBudgets: "true"
  # Отключение устаревшего плагина (пример)
  DisableKubeletLogDump: "false"
nodes:
- role: control-plane
- role: worker
```

| Параметр | Описание |
| :--- | :--- |
| `featureGates` | Объект с парами `имя_функции: "true"/"false"`. Значения обязательно задаются строками, а не булевыми типами. |

> **Важно:** Список доступных feature gates зависит от версии Kubernetes. Актуальный перечень можно найти в [документации Kubernetes](https://kubernetes.io/docs/reference/command-line-tools-reference/feature-gates/). Включение экспериментальных функций не рекомендуется для стабильных сред, но полезно для тестирования новых возможностей перед их стабилизацией.

### Управление группами API (runtimeConfig)

Поле `runtimeConfig` позволяет включить или выключить группы API (API Groups) на уровне кластера. Это полезно для включения бета- или альфа- API, которые по умолчанию отключены, или для отключения устаревших API.

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
runtimeConfig:
  # Включение бета-группы API FlowSchema
  "flowcontrol.apiserver.k8s.io/v1beta3": "true"
  # Отключение устаревшей альфа-группы
  "extensions/v1beta1": "false"
nodes:
- role: control-plane
- role: worker
```

| Параметр | Описание |
| :--- | :--- |
| `runtimeConfig` | Объект с парами `группа_API: "true"/"false"`. Ключи — полные имена API-групп с версией. |

> **Практический пример:** для тестирования новой функциональности API-сервера (например, `APISelfSubjectReview`, доступного с K8s 1.26+) включите соответствующую группу через `runtimeConfig`, а после завершения тестов — отключите, чтобы не нарушать совместимость при обновлении версии Kubernetes.

### Высокодоступный кластер (HA / multi-node)

Для развертывания нескольких управляющих узлов (Control Plane) kind автоматически настраивает внешний балансировщик нагрузки. Начиная с v0.32.0+, по умолчанию используется **Envoy**.

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
- role: control-plane
- role: control-plane
- role: worker
- role: worker
```
> **Примечание:** kind создаст контейнер-балансировщик, который будет распределять запросы kubectl на все три узла `control-plane` через единый Endpoint.

### Метки узлов (Labels)

Параметр `labels` позволяет добавить Kubernetes-метки на узел при его регистрации. Метки используются для `nodeSelector`, `affinity`, `tolerations` и других механизмов размещения подов.

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  labels:
    node-role.kubernetes.io/control-plane: ""
    topology.kubernetes.io/zone: "zone-a"
- role: worker
  labels:
    node-role.kubernetes.io/worker: ""
    topology.kubernetes.io/zone: "zone-a"
    team: backend
    environment: staging
```

**Применение меток для targetNode в Deployment:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      # Размещение подов только на узлах с меткой team=backend
      nodeSelector:
        team: backend
      containers:
      - name: nginx
        image: nginx:1.27
```

| Параметр | Описание |
| :--- | :--- |
| `labels` | Объект с парами `ключ: значение`. Значения — строки. Ключи должны соответствовать синтаксису Kubernetes labels. |

> **Практический смысл:** метки узлов позволяют эмулировать реальную топологию (зоны, регионы, hardware-классы) в локальной среде kind. Это критично для тестирования `podAntiAffinity`, `topologySpreadConstraints` и `nodeAffinity` перед деплоем в production.

### Валидация конфигурации

После создания кластера с конфигурационным файлом необходимо проверить, что все настройки применены корректно.

**Проверка настроек API-сервера:**

```bash
# Просмотр всех аргументов API-сервера (включая примененные через kubeadmConfigPatches)
kubectl -n kube-system get pod kube-apiserver-kind-control-plane -o jsonpath='{.spec.containers[0].args}' | jq .

# Проверка enabled admission-плагинов
kubectl -n kube-system get pod kube-apiserver-kind-control-plane -o yaml | grep "enable-admission-plugins"
```

**Проверка настроек kubelet:**

```bash
# Просмотр конфигурации kubelet на узле
docker exec kind-control-plane cat /var/lib/kubelet/config.yaml

# Проверка аргументов kubelet (включая system-reserved, eviction-hard)
docker exec kind-control-plane ps aux | grep kubelet

# Проверка лимитов подов
kubectl get node kind-control-plane -o jsonpath='{.status.capacity.pods}'
```

**Проверка featureGates:**

```bash
# Проверка включенных feature gates через API-сервер
kubectl -n kube-system get pod kube-apiserver-kind-control-plane -o jsonpath='{.spec.containers[0].args}' | grep feature-gates
```

**Проверка network-настроек:**

```yaml
# Проверка Pod CIDR и Service CIDR
kubectl cluster-info dump | grep -E "cluster-cidr|service-cluster-ip-range"
```

**Проверка меток узлов:**

```bash
kubectl get nodes --show-labels
# → NAME                      STATUS   ROLES           AGE   VERSION   LABELS
# → kind-control-plane        Ready    control-plane   5m    v1.37.0   ...
# → kind-worker               Ready    <none>          5m    v1.37.0   team=backend,...
```

**Диагностические команды при проблемах с конфигурацией:**

| Команда | Назначение |
| :--- | :--- |
| `kubectl describe node <node>` | Детальная информация об узле, включая conditions, capacity, allocated resources |
| `kubectl -n kube-system logs <pod>` | Логи компонентов Control Plane для выявления ошибок запуска |
| `docker exec <node> journalctl -u kubelet` | Системные логи kubelet внутри узла |
| `kubectl get events --sort-by='.lastTimestamp'` | События кластера (ошибки scheduling, failed mounts и т.д.) |

### Готовые шаблоны конфигураций

Ниже представлены полные, готовые к использованию конфигурации для типичных сценариев.

**Шаблон 1: Ingress-ready кластер (NGINX Ingress Controller)**

Кластер, настроенный для доступа к Ingress-контроллеру NGINX напрямую с хоста:

```yaml
# kind-ingress.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  # HTTP
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  # HTTPS
  - containerPort: 443
    hostPort: 443
    protocol: TCP
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
```

```bash
# Создание кластера
kind create cluster --name ingress --config kind-ingress.yaml

# Установка NGINX Ingress Controller (с nodeSelector для kind)
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml

# Ожидание готовности
kubectl -n ingress-nginx rollout status deployment/ingress-nginx-controller

# Проверка
kubectl -n ingress-nginx get pods
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → ingress-nginx-controller-xxxxx-yyyyy        1/1     Running   0          30s
```

> **Важно:** при установке Ingress Controller через YAML из документацииkind автоматически добавляет `nodeSelector: ingress-ready=true` к поду контроллера. Этот label совпадает с `node-labels: "ingress-ready=true"` в конфигурации узла.

**Шаблон 2: Кластер для CI/CD (быстрый, минимальный)**

Однонодовый кластер с ресурсными ограничениями для быстрых интеграционных тестов:

```yaml
# kind-ci.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        # Резервирование ресурсов для системных процессов
        system-reserved: "cpu=500m,memory=512Mi"
        # Агрессивный eviction для экономии RAM
        eviction-hard: "memory.available<256Mi,nodefs.available<10%"
        # Уменьшение лимита подов (для CI достаточно)
        max-pods: "50"
  - |
    kind: ClusterConfiguration
    apiVersion: kubeadm.k8s.io/v1beta4
    scheduler:
      extraArgs:
        # Ускорение scheduling (уменьшение probing узлов)
        maximum-failures: "2"
```

```bash
# Создание минимального кластера для CI
kind create cluster --name ci --config kind-ci.yaml --wait 60s

# Быстрая проверка готовности
kubectl wait --for=condition=Ready nodes --all --timeout=30s

# ... запуск тестов ...

# Удаление после тестов
kind delete cluster --name ci
```

**Шаблон 3: Кластер с мониторингом (Prometheus + metrics-server)**

Кластер с предустановленными компонентами для сбора метрик:

```yaml
# kind-monitoring.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  # Порт Prometheus UI (доступ с хоста)
  - containerPort: 30090
    hostPort: 9090
    protocol: TCP
  # Порт Grafana UI (доступ с хоста)
  - containerPort: 30030
    hostPort: 3000
    protocol: TCP
  kubeadmConfigPatches:
  - |
    kind: ClusterConfiguration
    apiVersion: kubeadm.k8s.io/v1beta4
    controllerManager:
      extraArgs:
        # Включение bind-address для сбора метрик controller-manager
        bind-address: "0.0.0.0"
    scheduler:
      extraArgs:
        # Включение profiling для анализа scheduler
        profiling: "true"
```

```bash
# Создание кластера
kind create cluster --name monitoring --config kind-monitoring.yaml

# Установка metrics-server
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Патч для работы metrics-server в kind (self-signed CA)
kubectl patch deployment metrics-server -n kube-system --type='json' -p='[
  {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"},
  {"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-preferred-address-types=InternalIP"}
]'

# Ожидание готовности
kubectl -n kube-system rollout status deployment/metrics-server

# Проверка сбора метрик
kubectl top nodes
kubectl top pods --all-namespaces
```

> **Примечание:** дополнительные порты для Prometheus и Grafana доступны через NodePort сервисы (30090, 30030). Для доступа с хоста используйте `http://localhost:9090` (Prometheus) и `http://localhost:3000` (Grafana) после проброса портов в конфигурации kind.

**Шаблон 4: Multi-node кластер с разными ролями узлов**

Кластер с выделенными узлами для Control Plane и пользовательских нагрузок:

```yaml
# kind-production-like.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  labels:
    node-role.kubernetes.io/control-plane: ""
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        system-reserved: "cpu=500m,memory=512Mi"
- role: worker
  labels:
    node-role.kubernetes.io/worker: ""
    workload-type: general
  extraPortMappings:
  - containerPort: 30080
    hostPort: 8080
    protocol: TCP
- role: worker
  labels:
    node-role.kubernetes.io/worker: ""
    workload-type: gpu
  extraMounts:
  - hostPath: /dev/dri
    containerPath: /dev/dri
    readOnly: true
```

```bash
# Создание кластера
kind create cluster --name dev --config kind-production-like.yaml

# Проверка ролей узлов
kubectl get nodes --show-labels
# → NAME                 STATUS   ROLES           AGE     VERSION   LABELS
# → kind-control-plane   Ready    control-plane   2m      v1.37.0   node-role.kubernetes.io/control-plane=,...
# → kind-worker          Ready    worker          2m      v1.37.0   node-role.kubernetes.io/worker=,workload-type=general,...
# → kind-worker2         Ready    worker          2m      v1.37.0   node-role.kubernetes.io/worker=,workload-type=gpu,...

# Размещение пода на конкретный узел по label
kubectl run test-pod --image=nginx --overrides='{"spec":{"nodeSelector":{"workload-type":"gpu"}}}'
```

### Ограничения и особенности конфигурации

| Ограничение | Описание | Решение |
| :--- | :--- | :--- |
| **Нет подстановки переменных окружения** | kind не поддерживает переменные окружения ($VAR, ${VAR}) внутри YAML-конфигурации. | Используйте `envsubst` перед передачей файла: `envsubst < kind-config.yaml.tmpl > kind-config.yaml` |
| **Приоритет CLI над YAML** | Аргументы командной строки (`--image`, `--name`) перезаписывают соответствующие поля в YAML. | Указывайте уникальные значения в YAML и избегайте дублирования с CLI. |
| **Одна версия Kubernetes на кластер** | Все узлы кластера должны использовать одинаковую версию Kubernetes (один и тот же `image`). | Для тестирования разных версий создавайте отдельные кластеры с разными именами. |
| **Нет динамического обновления** | Изменение конфигурационного файла после `kind create cluster` не применяется к существующему кластеру. | Пересоздайте кластер: `kind delete cluster --name <name> && kind create cluster --config kind-config.yaml` |
| **Ограничение на количество узлов** | Практический лимит: 50-100 узлов (зависит от ресурсов хоста). | Для крупных нагрузок используйте kubeadm на VM или bare-metal. |
| **macOS/Windows: виртуализация** | На macOS и Windows kind запускается внутри VM (Docker Desktop / Lima), что добавляет еще один уровень абстракции. | Учитывайте additional overhead при планировании ресурсов (RAM, CPU). |
| **Только Linux-образы** | kind поддерживает только Linux-контейнеры как узлы (включая Windows-хосты через WSL2). | Windows-контейнеры (nanoserver, servercore) не поддерживаются. |

**Подстановка переменных окружения (обходной путь):**

```bash
# Создание шаблона конфигурации
cat > kind-config.yaml.tmpl << 'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: ${APP_PORT}
    hostPort: ${APP_PORT}
    protocol: TCP
EOF

# Подстановка переменных и создание кластера
APP_PORT=8080 envsubst < kind-config.yaml.tmpl > kind-config.yaml
kind create cluster --name dev --config kind-config.yaml
```

**Проверка приоритета CLI vs YAML:**

```bash
# Если указаны оба, CLI имеет приоритет:
kind create cluster --name dev --config kind-config.yaml --image kindest/node:v1.36.0
# → Будет использована версия 1.36.0 из CLI, даже если в YAML указан другой image

# Чтобы избежать путаницы, не дублируйте параметры:
kind create cluster --name dev --config kind-config.yaml
# → Версия берется из YAML (image: kindest/node:v1.37.0)
```

---

## Дополнительная информация

### Применение конфигурации

```bash
# Создание кластера с использованием конфигурационного файла
kind create cluster --name my-cluster --config kind-config.yaml
# → Creating cluster "my-cluster" ...

# Проверка списка запущенных кластеров
kind get clusters
# → my-cluster

# Проверка контекста kubectl
kubectl cluster-info --context kind-my-cluster
# → Kubernetes control plane is running at https://127.0.0.1:<port>
```

### Сброс конфигурации

```bash
# Удаление конкретного кластера
kind delete cluster --name my-cluster
# → Deleting cluster "my-cluster" ...

# Удаление всех существующих кластеров kind
kind delete clusters --all
# → Deleted clusters: ["my-cluster", "other-cluster"]
```

### Типичные ошибки конфигурации

1.  **Конфликты портов:** Ошибка `bind: address already in use` возникает, если `hostPort` занят другим процессом на хосте. Решение: изменить `hostPort` или остановить конфликтующий сервис.
2.  **YAML отступы:** Некорректные отступы внутри многострочных патчей (`kubeadmConfigPatches`) часто не вызывают ошибки валидации kind, но приводят к игнорированию настроек компонентами Kubernetes.
3.  **Лимиты ресурсов:** При запуске больших (HA) кластеров на Docker Desktop может не хватить выделенной памяти, что приведет к зависанию узлов на этапе `Starting control-plane`.

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — архитектура, внутреннее устройство узлов
- [kind — практические сценарии](./kind_practical_scenarios.md) — установка, загрузка образов, полезные команды
- [Kubeadm API (v1beta4)](https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/) — подробное описание полей для патчинга
- [Kubernetes Pod Security Admission](../../Security/pod_security_context.md) — информация о замене PodSecurityPolicy
