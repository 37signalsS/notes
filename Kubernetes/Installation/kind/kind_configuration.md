# kind — конфигурация кластера

## Определения

**Конфигурационный файл kind** — YAML (YAML Ain't Markup Language)-манифест, определяющий параметры кластера Kubernetes: количество узлов, их роли, сетевые настройки, монтируемые тома и патчи компонентов.

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
| `image` | Docker-образ узла (по умолчанию актуальная версия K8s (Kubernetes)) |
| `extraPortMappings` | Проброс портов с хоста в контейнер |
| `extraMounts` | Монтирование томов хоста в контейнер |
| `kubeadmConfigPatches` | Патчи конфигурации kubeadm |
| `labels` | Метки узла |

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

Используется для доступа к сервисам кластера (например, `NodePort` или `Ingress`) с хост-машины:

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
| `containerPort` | Порт внутри контейнера узла (например, 30000 для NodePort) |
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

Список поддерживаемых образов доступен в разделе **[Версии Kubernetes](./kind_concepts.md#поддерживаемые-версии-kubernetes)**.

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

---

## Дополнительная информация

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

- [kind — определения и концепции](./kind_concepts.md) — архитектура, сравнение
- [kind — практические сценарии](./kind_practical_scenarios.md) — установка, создание кластеров, примеры
- [Официальная документация kind](https://kind.sigs.k8s.io/docs/user/configuration/)
