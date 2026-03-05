# vCluster

## 1. Определения

**vCluster** — это инструмент для создания легковесных виртуальных Kubernetes-кластеров, работающих внутри отдельных namespace'ов хостового кластера. Каждый vCluster имеет собственный Control Plane (API Server, Controller Manager, Scheduler, etcd) и полностью изолирован от других vCluster.

## 2. Основные концепции

### Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                      Host Cluster                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │   Namespace A   │  │   Namespace B   │  │   Namespace C   │ │
│  │  ┌───────────┐  │  │  ┌───────────┐  │  │  ┌───────────┐  │ │
│  │  │ vCluster  │  │  │  │ vCluster  │  │  │  │ vCluster  │  │ │
│  │  │ Control   │  │  │  │ Control   │  │  │  │ Control   │  │ │
│  │  │ Plane     │  │  │  │ Plane     │  │  │  │ Plane     │  │ │
│  │  │ (pods)    │  │  │  │ (pods)    │  │  │  │ (pods)    │  │ │
│  │  └───────────┘  │  │  └───────────┘  │  │  └───────────┘  │ │
│  │       │         │  │       │         │  │       │         │ │
│  │  ┌───────────┐  │  │  ┌───────────┐  │  │  ┌───────────┐  │ │
│  │  │ Workloads │  │  │  │ Workloads │  │  │  │ Workloads │  │ │
│  │  └───────────┘  │  │  └───────────┘  │  │  └───────────┘  │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### Компоненты vCluster

| Компонент | Описание |
| :--- | :--- |
| **Host Cluster** | Физический Kubernetes-кластер, на котором запускаются vCluster |
| **vCluster** | Виртуальный кластер, работающий внутри namespace'а host-кластера |
| **Control Plane** | Компоненты vCluster (API Server, etcd, CoreDNS), работающие как поды |
| **Syncer Controller** | Компонент, синхронизирующий ресурсы между vCluster и host-кластером |
| **etcd** | Встроенная база данных для хранения состояния vCluster |
| **CoreDNS** | DNS-сервер внутри vCluster |

### Варианты развёртывания Control Plane

| Тип | Описание | Использование ресурсов |
| :--- | :--- | :--- |
| **Kubernetes (vanilla)** | Полный K8s API, все функции | ~500MB RAM, 0.5 CPU |
| **K3s** | Облегчённый дистрибутив от Rancher | ~300MB RAM, 0.3 CPU |
| **K0s** | Минималистичный дистрибутив | ~250MB RAM, 0.2 CPU |

### Варианты Backing Store

| Тип | Описание | Когда использовать |
| :--- | :--- | :--- |
| **etcd** | Встроенный etcd | Production, полная изоляция |
| **Database (Enterprise)** | Внешняя БД (PostgreSQL, MySQL) | High Availability, backup |

### Матрица совместимости

| Host Cluster | Поддерживаемые версии vCluster |
| :--- | :--- |
| **1.28** | 1.28, 1.29, 1.30, 1.31 |
| **1.29** | 1.28, 1.29, 1.30, 1.31, 1.32 |
| **1.30** | 1.28, 1.29, 1.30, 1.31, 1.32 |
| **1.31** | 1.29, 1.30, 1.31, 1.32 |
| **1.32** | 1.30, 1.31, 1.32 |

**Примечание:** Рекомендуется использовать ту же версию для host и vCluster, или vCluster на 1-2 версии ниже host.

## 3. Практические сценарии

### 3.1. Установка vCluster CLI

**macOS (Homebrew):**

```bash
brew install loft-sh/vcluster/vcluster
```

**Linux:**

```bash
curl -L -o vcluster "https://github.com/loft-sh/vcluster/releases/latest/download/vcluster-linux-amd64"
sudo install -c -m 0755 vcluster /usr/local/bin
```

**Windows (Chocolatey):**

```bash
choco install vcluster
```

**Проверка установки:**

```bash
vcluster --version
```

### 3.2. Развертывание vCluster

**Базовая команда:**

```bash
vcluster create my-vcluster -n my-namespace
```

**С указанием версии Kubernetes:**

```bash
vcluster create my-vcluster -n my-namespace \
  --kubernetes-version 1.31.0
```

**С использованием K3s:**

```bash
vcluster create my-vcluster -n my-namespace \
  --distro k3s
```

**С кастомными values:**

```bash
vcluster create my-vcluster -n my-namespace \
  -f values.yaml
```

**Пример values.yaml:**

```yaml
# values.yaml
controlPlane:
  statefulSet:
    scheduling:
      podManagementPolicy: Parallel
    resources:
      requests:
        cpu: 200m
        memory: 512Mi
      limits:
        cpu: 1000m
        memory: 2Gi

syncer:
  extraArgs:
    - --service-account=my-vcluster-sa
```

### 3.3. Подключение к vCluster

**Автоматическое создание kubeconfig:**

```bash
vcluster connect my-vcluster -n my-namespace
```

**Экспорт kubeconfig в файл:**

```bash
vcluster connect my-vcluster -n my-namespace \
  --export-kubeconfig > kubeconfig.yaml

# Использование
export KUBECONFIG=kubeconfig.yaml
kubectl get nodes
```

**Подключение с указанием команды:**

```bash
vcluster connect my-vcluster -n my-namespace -- kubectl get pods
```

### 3.4. Получение kubeconfig из Secret

```bash
# kubeconfig хранится в Secret
kubectl get secret -n <vcluster-namespace> <vcluster-name> \
  -o jsonpath='{.data.config}' | base64 -d > kubeconfig.yaml

# Использование
export KUBECONFIG=kubeconfig.yaml
kubectl get nodes
```

### 3.5. Использование Storage из Host-кластера

**Шаг 1: Включение синхронизации StorageClass**

```yaml
# values.yaml
sync:
  fromHost:
    storageClasses:
      enabled: true
```

**Примечание:** Синхронизируются все StorageClasses хост-кластера.

**Шаг 2: Создание PVC в vCluster**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  storageClassName: managed-nfs-storage  # Из host-кластера
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 1Gi
```

### 3.6. Использование Ingress из Host-кластера

**Шаг 1: Включение синхронизации IngressClass**

```yaml
# values.yaml
sync:
  fromHost:
    ingressClasses:
      enabled: true
  toHost:
    ingresses:
      enabled: true
```

**Шаг 2: Создание Ingress в vCluster**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
spec:
  ingressClassName: system-ingress  # Из host-кластера
  rules:
    - host: myapp.vcluster.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-app
                port:
                  number: 80
```

### 3.7. Ingress для доступа к API vCluster

Для доступа к Kubernetes API vCluster извне через Ingress controller host-кластера:

```yaml
# values.yaml
controlPlane:
  ingress:
    enabled: true
    host: "vcluster1.example.com"
    annotations:
      nginx.ingress.kubernetes.io/ssl-passthrough: "true"
  proxy:
    extraSANs:
      - "vcluster1.example.com"
      - "192.168.1.100"
```

**Требования:**
- Ingress Controller с поддержкой SSL passthrough
- DNS запись на vcluster1.example.com

### 3.8. Безопасность: ResourceQuota и LimitRange

**Ограничение ресурсов vCluster:**

```yaml
# values.yaml
policies:
  resourceQuota:
    hard:
      requests.cpu: "4"
      requests.memory: 8Gi
      pods: "20"
      services: "10"
      secrets: "50"
      configmaps: "50"
  limitRange:
    default:
      memory: 512Mi
      cpu: 500m
    defaultRequest:
      memory: 256Mi
      cpu: 250m
```

**Важно:** При накладывании квот учитывайте ресурсы Control Plane vCluster:
- etcd: ~100-200MB RAM, 100m CPU
- API Server: ~200-300MB RAM, 200m CPU
- CoreDNS: ~50MB RAM, 50m CPU
- Syncer: ~100MB RAM, 100m CPU

### 3.9. Безопасность: Rootless Mode

**Запуск без привилегий суперпользователя:**

```yaml
# values.yaml
controlPlane:
  statefulSet:
    security:
      runAsUser: 10000
      runAsGroup: 10000
      fsGroup: 10000
      runAsNonRoot: true
```

### 3.10. Синхронизация ресурсов

**Sync to Host (из vCluster в Host):**

Ресурсы, синхронизируемые по умолчанию:
- Pods
- Services
- Endpoints
- Secrets
- ConfigMaps
- PersistentVolumeClaims
- Ingresses (требует включения)

**Sync from Host (из Host в vCluster):**

```yaml
# values.yaml
sync:
  fromHost:
    storageClasses:
      enabled: true
    ingressClasses:
      enabled: true
    nodes:
      enabled: true
      # Выбор узлов по лейблам
      selector:
        matchLabels:
          vcluster-ready: "true"
    persistentVolumes:
      enabled: true
```

### 3.11. Удаление vCluster

**Через vCluster CLI:**

```bash
vcluster delete my-vcluster -n my-namespace
```

**Вручную:**

```bash
# Удаление Helm релиза
helm uninstall my-vcluster -n my-namespace

# Удаление namespace
kubectl delete namespace my-namespace
```

## 4. Дополнительная информация

### Варианты использования

| Сценарий | Преимущества |
| :--- | :--- |
| **Разработка контроллеров** | Изоляция CRD, быстрое развёртывание |
| **Изоляция окружений** | Dev/Stage/Prod в одном host-кластере |
| **Multi-tenancy** | Полная изоляция между командами |
| **Тестирование версий K8s** | Разные версии vCluster на одном host |
| **CI/CD пайплайны** | Временные кластеры для тестов |

### Сравнение: Namespace vs vCluster

| Характеристика | Namespace | vCluster |
| :--- | :--- | :--- |
| **Собственный API Server** | ❌ Нет | ✅ Да |
| **Изоляция RBAC** | ⚠️ Ограниченная | ✅ Полная |
| **Изоляция CRD** | ❌ Нет | ✅ Да |
| **Изоляция etcd** | ❌ Нет | ✅ Да |
| **Управление через kubectl** | ⚠️ Частично | ✅ Полностью |
| **Ресурсы** | Минимальные | ~500MB RAM на кластер |
| **Время развёртывания** | Мгновенно | 30-60 секунд |

### Требования

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Host Kubernetes | 1.28+ | Проверено до 1.32 |
| vCluster CLI | 0.19+ | Для управления |
| Helm | 3.0+ | Для установки |

### Ресурсы Control Plane

| Компонент | CPU Request | Memory Request | CPU Limit | Memory Limit |
| :--- | :--- | :--- | :--- | :--- |
| **API Server** | 200m | 256Mi | 500m | 512Mi |
| **etcd** | 100m | 128Mi | 200m | 256Mi |
| **Controller Manager** | 50m | 64Mi | 100m | 128Mi |
| **Scheduler** | 50m | 64Mi | 100m | 128Mi |
| **CoreDNS** | 50m | 32Mi | 100m | 64Mi |
| **Syncer** | 100m | 128Mi | 200m | 256Mi |
| **Итого** | ~550m | ~672Mi | ~1200m | ~1.3Gi |

### Ограничения

- **Ресурсы на кластер** — ~500MB-1GB RAM на каждый vCluster
- **Сетевая сложность** — требуется настройка Network Policies
- **Не все ресурсы синхронизируются** — некоторые CRD требуют Enterprise

### Лучшие практики

1. **Изолируйте по командам** — один vCluster на команду
2. **Настройте квоты** — ResourceQuota для контроля ресурсов
3. **Мониторьте Control Plane** — метрики самого vCluster
4. **Используйте Helm** — для управления конфигурацией
5. **Backup etcd** — для production-кластеров

### Связанные документы

- **[Namespaces](../Base/namespace.md)** — основы namespace'ов
- **[RBAC](../Security/rbac/rbac_overview.md)** — управление доступом
- **[Storage](../Storage/storage_overview.md)** — управление хранилищем
- **[Helm](./Helm/helm_overview.md)** — установка через Helm

### Репозиторий и документация

- [GitHub: loft-sh/vcluster](https://github.com/loft-sh/vcluster)
- [Официальная документация](https://www.vcluster.com/docs)
- [Helm Chart](https://github.com/loft-sh/vcluster/tree/main/chart)
