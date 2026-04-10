# Longhorn — Distributed Block Storage for Kubernetes

## Definitions

**Longhorn** — cloud-native распределённое блочное хранилище для Kubernetes. Создаёт storage pool из локальных дисков каждой ноды, реплицирует данные между нодами, предоставляет dynamic provisioning через CSI-драйвер.

**Air-gapped (закрытый контур)** — изолированная среда без доступа к интернету. Все артефакты (образы, Helm-чарты) переносятся через съёмные носители или одноразовый канал. Полная процедура описана в [Longhorn Air-gapped Installation](./longhorn-air-gapped.md).

**defaultReplicaCount** — количество реплик Volume по умолчанию. Должно соответствовать количеству worker-нод в кластере для равномерного распределения.

**ReplicaSoftAntiAffinity** — разрешение размещения реплик на одной ноде (при `true`). Используется в dev/test или при малом количестве нод.

## Basic Concepts

### Архитектура Longhorn

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                    │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ Node 1   │  │ Node 2   │  │ Node N   │              │
│  │ /var/    │  │ /var/    │  │ /var/    │              │
│  │ longhorn │  │ longhorn │  │ longhorn │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                   │
│       └──────────────┼──────────────┘                   │
│                      │                                  │
│              ┌───────▼────────┐                         │
│              │ Longhorn       │                         │
│              │ Manager        │                         │
│              └───────┬────────┘                         │
│                      │                                  │
│              ┌───────▼────────┐                         │
│              │ CSI Driver     │                         │
│              │ (attacher,     │                         │
│              │  provisioner,  │                         │
│              │  node-driver)  │                         │
│              └────────────────┘                         │
└─────────────────────────────────────────────────────────┘
```

### Ключевые компоненты

| Компонент | Назначение |
|---|---|
| **Longhorn Manager** | DaemonSet, управляет логикой хранения, создаёт volumes, реплики |
| **Longhorn Engine** | Ядро репликации, работает на нодах где смонтирован volume |
| **CSI Driver** | Интеграция с Kubernetes (provisioning, attach, mount) |
| **Longhorn UI** | Веб-интерфейс для мониторинга и управления |
| **Instance Manager** | Управляет процессами engine/replica на ноде |
| **Share Manager** | Поддержка RWX volumes через NFS |

### Сценарии использования

| Сценарий | ReplicaCount | AntiAffinity | StorageClass |
|---|---|---|---|
| **Dev/Test (1-2 ноды)** | 1-2 | soft (true) | longhorn |
| **Production (3+ нод)** | 3 | hard (false) | longhorn |
| **RWX (shared volumes)** | 2-3 | soft (true) | longhorn + share-manager |

Сравнение с другими CSI-драйверами: [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md). Альтернатива для простых сценариев: [Local Path Provisioner](./local-path-provisioner.md).

## Practical Scenarios

### Онлайн установка Longhorn

**Требования:** Kubernetes cluster, Helm, доступ к интернету.

**Шаг 1. Создание values-файла:**

```bash
nano longhorn-values.yaml
```

```yaml
defaultSettings:
  defaultReplicaCount: 2
  replicaSoftAntiAffinity: true
  storageOverProvisioningPercentage: 200
  storageMinimalAvailablePercentage: 10
longhornUI:
  replicas: 1
```

**Шаг 2. Установка:**

```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update
helm install longhorn -n longhorn-system --create-namespace -f longhorn-values.yaml
```

**Шаг 3. Доступ к UI:**

**Без Ingress (port-forward):**

```bash
kubectl port-forward service/longhorn-frontend 8080:80 -n longhorn-system
```

Доступ: `http://localhost:8080`

**Через Ingress:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: longhorn-ui
  namespace: longhorn-system
spec:
  ingressClassName: nginx
  rules:
  - host: longhorn.k8s.domain.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: longhorn-frontend
            port:
              number: 80
```

```bash
kubectl apply -f ingress-longhorn.yaml
```

Требуется DNS-запись `longhorn.k8s.domain.local` → IP ingress-ноды.

## Additional Information

### Ключевые настройки values.yaml

| Параметр | Описание | Значение по умолчанию |
|---|---|---|
| `defaultSettings.defaultReplicaCount` | Количество реплик volume | 3 |
| `defaultSettings.replicaSoftAntiAffinity` | Размещение реплик на одной ноде | false |
| `defaultSettings.storageOverProvisioningPercentage` | Процент over-provisioning | 100 |
| `defaultSettings.storageMinimalAvailablePercentage` | Мин. свободное место (%) | 25 |
| `global.imageRegistry` | Приватный registry для всех образов | (пусто) |
| `image.registry` | Registry для Longhorn образов | docker.io |

### Troubleshooting

| Проблема | Причина | Решение |
|---|---|---|
| Поды в `ImagePullBackOff` | Образы не загружены в Harbor | Проверить `docker pull` и `docker push` всех образов |
| `helm install` — chart not found | OCI chart не запушен или неверный URL | Проверить `helm push` и `helm search repo oci://harbor...` |
| Volume не создаётся | Недостаточно нод с диском | Проверить `defaultReplicaCount` и доступные ноды в Longhorn UI |
| CSI driver не работает | Старая версия Kubernetes | Требуется K8s ≥ 1.20 для CSI v1 |

### Связанные темы

- Основы работы с хранилищами: [Persistent Volumes и StorageClass](./pv_and_pvc.md)
- Работа с приватным репозиторием: [Harbor Usage](../../Docker/Docker_registries/Harbor/usage.md)
- Оффлайн-установка: [Longhorn Air-gapped Installation](./longhorn-air-gapped.md)
