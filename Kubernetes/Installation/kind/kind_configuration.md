# kind: Конфигурация кластера

## Definitions

**Конфигурационный файл kind** — YAML-манифест, определяющий параметры кластера Kubernetes: количество узлов, их роли, сетевые настройки, монтируемые тома и патчи компонентов.

**apiVersion: kind.x-k8s.io/v1alpha4** — текущая версия API конфигурации kind.

---

## Basic Concepts

### Структура конфигурации

Базовые поля конфигурационного файла:

| Поле | Описание | Обязательное |
| :--- | :--- | :--- |
| `kind` | Тип объекта, всегда `Cluster` | Да |
| `apiVersion` | Версия API, `kind.x-k8s.io/v1alpha4` | Да |
| `nodes` | Список узлов кластера | Да |
| `networking` | Настройки сети (опционально) | Нет |
| `containerdConfigPatches` | Патчи containerd | Нет |
| `featureGates` | Функциональные флаги | Нет |

### Типы узлов

| Роль | Описание |
| :--- | :--- |
| `control-plane` | Управляющий узел (API server, scheduler, controller-manager) |
| `worker` | Рабочий узел для размещения подов |

### Параметры узла

| Параметр | Описание |
| :--- | :--- |
| `role` | Роль узла: `control-plane` или `worker` |
| `image` | Docker-образ узла (по умолчанию актуальная версия K8s) |
| `extraPortMappings` | Проброс портов с хоста в контейнер |
| `extraMounts` | Монтирование томов хоста в контейнер |
| `kubeadmConfigPatches` | Патчи конфигурации kubeadm |
| `labels` | Метки узла |

---

## Practical Scenarios

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

Доступ к сервисам кластера с хост-машины:

```yaml
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30000
    hostPort: 30000
    listenAddress: "127.0.0.1"
    protocol: TCP
  - containerPort: 80
    hostPort: 8080
    protocol: TCP
```

| Параметр | Описание |
| :--- | :--- |
| `containerPort` | Порт внутри контейнера узла |
| `hostPort` | Порт на хост-машине |
| `listenAddress` | IP-адрес для прослушивания |
| `protocol` | Протокол: `TCP` или `UDP` |

### Монтирование томов (extraMounts)

Общий доступ к файлам между хостом и узлами:

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
| `hostPath` | Путь на хост-машине |
| `containerPath` | Путь внутри контейнера |
| `readOnly` | Только чтение (по умолчанию `false`) |
| `propagation` | Режим проброса: `None`, `HostToContainer`, `Bidirectional` |
| `selinuxRelabel` | SELinux-маркировка (по умолчанию `false`) |

### Патчи kubeadm (kubeadmConfigPatches)

Настройка компонентов Kubernetes через патчи:

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
        enable-admission-plugins: NodeRestriction,PodSecurityPolicy
      extraVolumes:
      - name: audit-config
        hostPath: /etc/kubernetes/audit-policy.yaml
        mountPath: /etc/kubernetes/audit-policy.yaml
        readOnly: true
```

### Выбор версии Kubernetes

Использование конкретной версии через образ узла:

```yaml
nodes:
- role: control-plane
  image: kindest/node:v1.34.0
- role: worker
  image: kindest/node:v1.34.0
```

**Поддерживаемые версии на 2026 год:**

| Версия | Образ | Статус |
| :--- | :--- | :--- |
| 1.35 | `kindest/node:v1.35.0` | Активная |
| 1.34 | `kindest/node:v1.34.0` | Активная |
| 1.33 | `kindest/node:v1.33.0` | Активная |

> **Примечание:** Версии 1.32 и ниже достигли EOL (февраль 2026). Проверяйте [release notes](https://github.com/kubernetes-sigs/kind/releases) для доступных образов.

### HA-кластер (multi-node)

Конфигурация для тестирования отказоустойчивости:

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
  extraPortMappings:
  - containerPort: 6443
    hostPort: 6443
    protocol: TCP
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
- role: worker
- role: worker
```

### Сетевая конфигурация

Настройка сети кластера:

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  ipFamily: dual  # ipv4, ipv6, dual
  podSubnet: "10.244.0.0/16"
  serviceSubnet: "10.96.0.0/12"
  disableDefaultCNI: false
  kubeProxyMode: "iptables"  # iptables, ipvs
nodes:
- role: control-plane
- role: worker
```

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `ipFamily` | Семейство IP: `ipv4`, `ipv6`, `dual` | `ipv4` |
| `podSubnet` | Подсеть для подов | `10.244.0.0/16` |
| `serviceSubnet` | Подсеть для сервисов | `10.96.0.0/12` |
| `disableDefaultCNI` | Отключить CNI по умолчанию | `false` |
| `kubeProxyMode` | Режим kube-proxy: `iptables`, `ipvs` | `iptables` |

### Полный пример конфигурации

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  ipFamily: ipv4
  podSubnet: "10.244.0.0/16"
  serviceSubnet: "10.96.0.0/12"
nodes:
- role: control-plane
  image: kindest/node:v1.34.0
  extraPortMappings:
  - containerPort: 6443
    hostPort: 6443
    protocol: TCP
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
  extraMounts:
  - hostPath: /data/storage
    containerPath: /mnt/storage
    propagation: Bidirectional
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
- role: worker
  image: kindest/node:v1.34.0
- role: worker
  image: kindest/node:v1.34.0
```

---

## Additional Information

### Применение конфигурации

```bash
# Создание кластера с конфигурацией
kind create cluster --name my-cluster --config kind-config.yaml

# Проверка
kubectl cluster-info
kind get clusters
```

### Сброс конфигурации

```bash
# Удаление кластера
kind delete cluster --name my-cluster

# Удаление всех кластеров
kind delete clusters --all
```

### Ссылки

- [kind: Концепции](./kind_concepts.md) — определения, архитектура, сравнение
- [kind: Практические сценарии](./kind_practical_scenarios.md) — установка, создание кластеров, примеры
- [Официальная документация kind](https://kind.sigs.k8s.io/docs/user/configuration/)
