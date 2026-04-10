# Longhorn Air-gapped Installation

## Definitions

**Air-gapped installation** — процедура развёртывания Longhorn в изолированном Kubernetes-кластере без доступа к интернету. Все артефакты (Docker-образы, Helm-чарты) переносятся вручную.

**Harbor** — приватный container registry, используемый как внутренний источник образов в закрытом контуре. Подробнее: [Harbor Usage](../../Docker/Docker_registries/Harbor/usage.md).

## Basic Concepts

### Общая схема процесса

```
┌──────────────────┐     Съёмный носитель     ┌──────────────────┐
│  Хост с          │     или одноразовый      │  Закрытый контур │
│  интернетом      │ ──────────────────────►   │  (air-gapped)    │
│                  │                           │                  │
│  1. Pull образов │                           │  1. Load образов │
│  2. Save в tar   │                           │  2. Push в Harbor│
│  3. Pull chart   │                           │  3. Push chart   │
│                  │                           │                  │
│                  │                           │  4. helm install │
│                  │                           │     из OCI       │
└──────────────────┘                           └──────────────────┘
```

### Необходимые компоненты

| Компонент | Назначение |
|---|---|
| Хост с интернетом | Скачивание образов и Helm-чарта |
| Docker | Pull/save/load образов |
| Helm | Pull/push чарта |
| Harbor (в контуре) | Хранение образов и чарта |
| Kubernetes cluster | Целевая платформа |

## Practical Scenarios

### Шаг 1. Подготовка образов (на хосте с интернетом)

**Установка инструментов:**

```bash
apt update -y
apt install helm docker.io -y
```

**Скачивание Helm-чарта:**

```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update
# Актуальная версия: https://github.com/longhorn/longhorn/releases
helm pull longhorn/longhorn --version v1.11.0 --untar
```

**Извлечение списка образов из values.yaml:**

```bash
cd longhorn
awk '
  $1 ~ /repository:/ { repo=$2 }
  $1 ~ /tag:/        { tag=$2; if (repo != "" && tag != "") { print repo ":" tag; repo=""; tag="" } }
' ./longhorn/values.yaml | sort -u > lh-images.txt
```

**Pull образов:**

```bash
while read -r img; do
  docker pull "${img}"
done < lh-images.txt
```

**Сохранение в tar-архивы:**

```bash
mkdir -p lh-tars
while read -r img; do
  safe=$(echo "$img" | tr '/:' '_')
  docker save -o "lh-tars/${safe}.tar" "${img}"
done < lh-images.txt
```

**Упаковка Helm-чарта:**

```bash
tar -cvf longhorn-helm.tar longhorn
```

**Перенос:** `lh-tars/` и `longhorn-helm.tar` в закрытый контур.

### Шаг 2. Пуш образов в приватный репозиторий (в закрытом контуре)

**Загрузка образов из tar:**

```bash
for f in lh-tars/*.tar; do
  docker load -i "$f"
done
```

**Логин в Harbor:**

```bash
docker login harbor.domain.local
helm login harbor.domain.local
```

**Пуш Helm-чарта в OCI registry:**

```bash
helm push longhorn-helm.tgz oci://harbor.domain.local/helm
```

**Тегирование и пуш образов:**

```bash
HARBOR="harbor.domain.local"
PROJECT="platform"

docker login "$HARBOR"
while read -r img; do
  new="${HARBOR}/${PROJECT}/${img}"
  docker tag "${img}" "$new"
  docker push "$new"
done < lh-images.txt
```

### Шаг 3. Подготовка values-файла для Harbor

```yaml
global:
  imageRegistry: harbor.domain.local

defaultSettings:
  defaultReplicaCount: 2
  replicaSoftAntiAffinity: true
  storageOverProvisioningPercentage: 200
  storageMinimalAvailablePercentage: 10

longhornUI:
  replicas: 1

image:
  registry: harbor.domain.local
  longhorn:
    manager:
      repository: platform/longhorn/longhorn-manager
    engine:
      repository: platform/longhorn/longhorn-engine
    ui:
      repository: platform/longhorn/longhorn-ui
    instanceManager:
      repository: platform/longhorn/longhorn-instance-manager
    shareManager:
      repository: platform/longhorn/longhorn-share-manager
    backingImageManager:
      repository: platform/longhorn/backing-image-manager
    supportBundleKit:
      repository: platform/longhorn/support-bundle-kit
  csi:
    attacher:
      repository: platform/longhorn/csi-attacher
    provisioner:
      repository: platform/longhorn/csi-provisioner
    nodeDriverRegistrar:
      repository: platform/longhorn/csi-node-driver-registrar
    resizer:
      repository: platform/longhorn/csi-resizer
    snapshotter:
      repository: platform/longhorn/csi-snapshotter
    livenessProbe:
      repository: platform/longhorn/livenessprobe
```

> **Важно:** Замените `harbor.domain.local` на свой адрес, `platform` — на имя проекта в Harbor.

### Шаг 4. Установка в кластер

```bash
helm install longhorn oci://harbor.domain.local/helm/longhorn \
  --version v1.11.0 \
  -n longhorn-system \
  --create-namespace \
  -f longhorn-values.yaml
```

**Проверка:**

```bash
kubectl get pods -n longhorn-system
kubectl get storageclass
```

Все поды должны быть в статусе `Running`.

**Настройка доступа к UI** (аналогично онлайн-установке):

Port-forward:

```bash
kubectl port-forward service/longhorn-frontend 8080:80 -n longhorn-system
```

Ingress — см. [Longhorn — онлайн-установка](./longhorn.md#доступ-к-ui).

## Additional Information

### Troubleshooting

| Проблема | Причина | Решение |
|---|---|---|
| Поды в `ImagePullBackOff` | Образы не загружены в Harbor | Проверить `docker pull` и `docker push` всех образов из `lh-images.txt` |
| `helm install` — chart not found | OCI chart не запушен или неверный URL | Проверить `helm push` и `helm search repo oci://harbor...` |
| Volume не создаётся | Недостаточно нод с диском | Проверить `defaultReplicaCount` и доступные ноды в Longhorn UI |

### Связанные темы

- Основная статья: [Longhorn — обзор и онлайн-установка](./longhorn.md)
- Аналогичный процесс для мониторинга: [Air-gapped kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md)
