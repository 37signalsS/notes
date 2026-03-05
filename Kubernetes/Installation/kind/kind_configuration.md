# kind: Конфигурация кластера

Конфигурация кластера `kind` определяется с помощью YAML-файла. Это позволяет точно настроить количество и роли узлов, проброс портов и другие параметры.

## Минимальная конфигурация

Пример минимальной конфигурации кластера с одним управляющим узлом и одним рабочим узлом:

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
- role: worker
```

---

## Дополнительные параметры узлов

### extraPortMappings: Проброс портов

Проброс портов с хост-машины в контейнеры узлов. Это позволяет обращаться к сервисам внутри кластера напрямую с хоста по определенным портам.

**Пример:**

```yaml
extraPortMappings:
- containerPort: 30000    # Порт внутри контейнера узла
  hostPort: 30000         # Порт на хост-машине
  listenAddress: "127.0.0.1"  # IP-адрес на хосте
  protocol: TCP
```

### extraMounts: Монтирование томов

Добавление дополнительных монтирований (bind mounts) в контейнеры узлов. Полезно для локальной разработки, передачи файлов или использования локальных хранилищ.

**Пример:**

```yaml
extraMounts:
- hostPath: /path/on/host       # Путь на хост-машине
  containerPath: /path/in/container  # Путь внутри контейнера узла
```

### kubeadmConfigPatches: Патчи kubeadm

Применение патчей к конфигурации `kubeadm` для более тонкой настройки компонентов Kubernetes. Это может быть полезно для изменения параметров `kube-apiserver`, `kube-controller-manager` и других.

**Пример:**

```yaml
kubeadmConfigPatches:
- |
  apiVersion: kubeadm.k8s.io/v1beta3
  kind: InitConfiguration
  nodeRegistration:
    kubeletExtraArgs:
      node-labels: "ingress-ready=true"
```

### image: Пользовательский образ узла

Указание пользовательского образа Docker для узла (например, с определенной версией Kubernetes или предварительно установленными инструментами).

**Пример:**

```yaml
image: kindest/node:v1.28.0  # Использование конкретного образа узла
```

---

## Полный пример конфигурации

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30000
    hostPort: 30000
    listenAddress: "127.0.0.1"
    protocol: TCP
  extraMounts:
  - hostPath: /path/on/host
    containerPath: /path/in/container
- role: worker
  image: kindest/node:v1.28.0  # Использование конкретного образа узла
- role: worker
```

---

## Связанные документы

- **[kind: Концепции](./kind_concepts.md)** — определения, архитектура, сравнение
- **[kind: Практические сценарии](./kind_practical_scenarios.md)** — установка, создание кластеров, примеры
