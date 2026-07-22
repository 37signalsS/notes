# kind — конфигурация кластера

## Определения

**Конфигурационный файл kind** — YAML (YAML Ain't Markup Language)-манифест, определяющий параметры кластера Kubernetes: количество узлов, их роли, сетевые настройки, монтируемые тома, патчи компонентов Kubernetes и настройки Container Runtime.

**apiVersion: kind.x-k8s.io/v1alpha4** — актуальная версия API (Application Programming Interface) конфигурации `kind`.

---

## Основные концепции

### Структура конфигурации

Базовые поля конфигурационного файла:

| Поле | Описание | Обязательное |
| :--- | :--- | :--- |
| `kind` | Тип объекта, всегда `Cluster` | Да |
| `apiVersion` | Версия API, `kind.x-k8s.io/v1alpha4` | Да |
| `nodes` | Список узлов кластера | Да |
| `networking` | Настройки сети (подсети, CNI, kube-proxy) | Нет |
| `containerdConfigPatches` | Патчи конфигурации containerd (например, для приватных реестров) | Нет |
| `featureGates` | Включение экспериментальных функций Kubernetes (Feature Gates) | Нет |

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
| `image` | Docker-образ узла (например, `kindest/node:v1.36.0`) |
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

### Патчи kubeadm (kubeadmConfigPatches)

Настройка внутренних компонентов Kubernetes (API Server, Kubelet) путем патчинга конфигурации, которую `kind` передает в утилиту `kubeadm` при инициализации кластера.

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
  - |
    kind: ClusterConfiguration
    apiServer:
      extraArgs:
        enable-admission-plugins: NodeRestriction,PodSecurity
      extraVolumes:
      - name: audit-config
        hostPath: /etc/kubernetes/audit-policy.yaml
        mountPath: /etc/kubernetes/audit-policy.yaml
        readOnly: true
```
> **Примечание:** В примере выше плагин `PodSecurityPolicy` (удален в K8s 1.25) заменен на актуальный встроенный механизм `PodSecurity`. Установка `ingress-ready=true` часто используется Ingress-контроллерами (например, NGINX Ingress) для размещения подов именно на этом узле.

### Настройка containerd (containerdConfigPatches)

Позволяет изменять конфигурацию Container Runtime внутри узла. Самый частый сценарий — настройка insecure-registry или registry-mirrors (полезно в закрытых контурах).

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
containerdConfigPatches:
- |-
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
    endpoint = ["https://my-local-registry.local:5000"]
nodes:
- role: control-plane
```

### Сетевая конфигурация (Networking)

Позволяет переопределить подсети кластера, включить поддержку IPv6 (или Dual-Stack) и отключить стандартный CNI-плагин (kindnet) для последующей установки собственного (например, Cilium, Calico или Flannel).

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  ipFamily: dual  # ipv4, ipv6, dual
  podSubnet: "10.244.0.0/16,fd00:10:244::/56"
  serviceSubnet: "10.96.0.0/12,fd00:10:96::/108"
  disableDefaultCNI: true  # Полезно для установки Calico или Cilium
  kubeProxyMode: "iptables"  # iptables, ipvs, или none (если CNI заменяет kube-proxy, например Cilium)
nodes:
- role: control-plane
- role: worker
```

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `ipFamily` | Семейство IP: `ipv4`, `ipv6`, `dual` | `ipv4` |
| `podSubnet` | Подсеть, из которой подам выдаются IP адреса | `10.244.0.0/16` |
| `serviceSubnet` | Подсеть для ClusterIP сервисов | `10.96.0.0/12` |
| `disableDefaultCNI` | Не устанавливать `kindnet` | `false` |
| `kubeProxyMode` | Режим работы kube-proxy: `iptables`, `ipvs`, `none` | `iptables` |

### Высокодоступный кластер (HA / multi-node)

Для развертывания нескольких управляющих узлов (Control Plane) kind автоматически настраивает внешний балансировщик нагрузки (HAProxy) в отдельном контейнере.

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
> **Примечание:** kind создаст контейнер-балансировщик, который будет распределять запросы kubectl на все три узла `control-plane`.

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

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — архитектура, внутреннее устройство узлов
- [kind — практические сценарии](./kind_practical_scenarios.md) — установка, загрузка образов, полезные команды
- [Kubernetes Pod Security Admission](../../Security/pod_security_context.md) — информация о замене PodSecurityPolicy
