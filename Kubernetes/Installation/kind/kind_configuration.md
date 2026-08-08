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

Начиная с Kubernetes 1.36 (актуально для августа 2026), рекомендуется использовать версию API `kubeadm.k8s.io/v1beta4` для патчинга компонентов Control Plane.

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
> **Примечание:** В примере выше плагин `PodSecurityPolicy` (удален в K8s 1.25) окончательно заменен на актуальный встроенный механизм `PodSecurity`.

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
