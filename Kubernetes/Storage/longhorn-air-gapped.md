# Longhorn — установка в закрытом контуре (Air-gapped)

## Определения

**Air-gapped installation (установка в закрытом контуре)** — процедура развёртывания Longhorn в изолированном Kubernetes-кластере без прямого доступа к интернету. Все артефакты (Docker-образы, Helm-чарты) скачиваются заранее на хосте с доступом в сеть и переносятся во внутренний контур вручную (через съемные носители или одноразовые SSH-бастионы).

**Harbor** — приватный container registry, используемый как внутренний источник образов и Helm-чартов. Подробнее: [Использование Harbor](../../Docker/Docker_registries/Harbor/usage.md).

**OCI (Open Container Initiative)** — стандарт хранения и распространения не только образов, но и Helm-чартов внутри registry.

## Основные концепции

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

### Необходимые компоненты и требования

| Компонент | Назначение / Версия |
|---|---|
| Хост с интернетом | ОС Linux, установленные Docker/Podman, Helm v3.8+ |
| Kubernetes cluster | Версия **v1.25** или выше (для работы CSI и Longhorn v1.12.0+) |
| Registry (Harbor) | Должен поддерживать OCI для хранения чартов |
| iSCSI / NFS | На узлах K8s должны быть установлены `open-iscsi` и `nfs-common` |

## Практические сценарии

### Шаг 1. Подготовка артефактов (на хосте с интернетом)

**1. Скачивание Helm-чарта:**

```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update
# Актуальная версия на июль 2026: v1.12.0
helm pull longhorn/longhorn --version v1.12.0 --untar
```

**2. Получение списка образов:**

Существует два способа. Первый — использовать официальный манифест. Второй — извлечь список напрямую из скачанного чарта (полезно для кастомных сборок или если нет доступа к GitHub).

*Способ А (Официальный список):*
```bash
VERSION="v1.12.0"
curl -sSfL "https://raw.githubusercontent.com/longhorn/longhorn/${VERSION}/deploy/longhorn-images.txt" | tr ',' '\n' > lh-images.txt
```

*Способ Б (Извлечение через awk из values.yaml):*
```bash
cd longhorn
awk '
  $1 ~ /repository:/ { repo=$2 }
  $1 ~ /tag:/        { tag=$2; if (repo != "" && tag != "") { print repo ":" tag; repo=""; tag="" } }
' ./values.yaml | sort -u > ../lh-images.txt
cd ..
```

**3. Скачивание и сохранение образов:**

```bash
# Pull всех образов
while read -r img; do
  docker pull "${img}"
done < lh-images.txt

# Сохранение в tar-архивы для переноса
mkdir -p lh-tars
while read -r img; do
  # Замена спецсимволов / и : на подчеркивание для имени файла
  safe=$(echo "$img" | tr '/:' '_')
  docker save -o "lh-tars/${safe}.tar" "${img}"
done < lh-images.txt
```

**4. Подготовка чарта к переносу:**

```bash
tar -cvzf longhorn-helm-v1.12.0.tar.gz longhorn/
```

### Шаг 2. Загрузка в приватный репозиторий (в закрытом контуре)

**1. Импорт образов из архивов:**

```bash
for f in lh-tars/*.tar; do
  docker load -i "$f"
done
```

**2. Пуш образов в Harbor:**

Предположим, адрес Harbor `harbor.domain.local`. Рекомендуется использовать проект `longhornio`, чтобы структура путей совпадала с оригиналом.

```bash
REGISTRY="harbor.domain.local"
PROJECT="longhornio" 

docker login "$REGISTRY"

while read -r img; do
  # Пример: longhornio/longhorn-manager:v1.12.0 -> harbor.domain.local/longhornio/longhorn-manager:v1.12.0
  # Если оригинальный образ уже содержит префикс (например, для CSI sidecars), 
  # логика тегирования может потребовать корректировки под структуру ваших проектов в Harbor.
  
  new_img="${REGISTRY}/${img}"
  docker tag "${img}" "${new_img}"
  docker push "${new_img}"
done < lh-images.txt
```

**3. Пуш чарта в OCI-репозиторий:**

```bash
helm login "$REGISTRY"
helm push longhorn-helm-v1.12.0.tar.gz oci://${REGISTRY}/helm
```

### Шаг 3. Детальная конфигурация values.yaml

В версии v1.12.0 есть два подхода к конфигурации реестра.

#### Вариант 1: Упрощенный (Global Registry)
Подходит, если все образы лежат в одном проекте Harbor с сохранением оригинальных имен.

```yaml
global:
  imageRegistry: harbor.domain.local
  imagePullSecrets:
    - name: longhorn-registry-secret

defaultSettings:
  defaultReplicaCount: 3
  # V2 Data Engine (SPDK) — статус GA в v1.12.0
  v2-data-engine: false 
  storageOverProvisioningPercentage: 200
  storageMinimalAvailablePercentage: 10

longhornUI:
  replicas: 2
```

#### Вариант 2: Детальный (Manual Overrides)
Необходим, если образы переименованы или распределены по разным проектам (например, `platform/lh-manager` вместо `longhornio/longhorn-manager`).

```yaml
image:
  longhorn:
    manager:
      repository: platform/lh-manager
      tag: v1.12.0
    engine:
      repository: platform/lh-engine
      tag: v1.12.0
    ui:
      repository: platform/lh-ui
      tag: v1.12.0
    instanceManager:
      repository: platform/lh-instance-manager
      tag: v1.12.0
    shareManager:
      repository: platform/lh-share-manager
      tag: v1.12.0
    backingImageManager:
      repository: platform/lh-backing-image-manager
      tag: v1.12.0
  csi:
    attacher:
      repository: platform/csi-attacher
      tag: v4.11.0-20260428
    provisioner:
      repository: platform/csi-provisioner
      tag: v5.3.0-20260428
    nodeDriverRegistrar:
      repository: platform/csi-node-driver-registrar
      tag: v2.16.0-20260428
    resizer:
      repository: platform/csi-resizer
      tag: v2.1.0-20260428
    snapshotter:
      repository: platform/csi-snapshotter
      tag: v8.5.0-20260428
    livenessProbe:
      repository: platform/livenessprobe
      tag: v2.18.0-20260428
```

### Шаг 4. Установка и проверка

**Создание секрета:**
```bash
kubectl create namespace longhorn-system
kubectl create secret docker-registry longhorn-registry-secret \
  --docker-server=harbor.domain.local \
  --docker-username="robot-longhorn" \
  --docker-password="password" \
  -n longhorn-system
```

**Запуск установки:**
```bash
helm install longhorn oci://harbor.domain.local/helm/longhorn \
  --version v1.12.0 \
  -n longhorn-system \
  -f values.yaml
```

**Проверка статуса:**
```bash
# Проверка запуска компонентов
kubectl get pods -n longhorn-system -w

# Проверка используемых образов
kubectl get pods -n longhorn-system -o jsonpath='{.items[*].spec.containers[*].image}' | tr ' ' '\n' | sort -u
```

## Дополнительная информация

### Особенности V2 Data Engine (SPDK)
В версии **v1.12.0** новый движок на базе SPDK официально объявлен стабильным (GA). Его использование в закрытом контуре имеет свои нюансы:
1. **Образы:** Движок V2 использует специфические образы `instance-manager`. Убедитесь, что они присутствуют в `lh-images.txt`.
2. **Системные требования:** На узлах должны быть выделены HugePages (минимум 2Gi на узел) и свободные CPU ядра для `longhorn-spdk-io-proxy`.
3. **Ядро Linux:** Рекомендуется версия ядра 5.15+ для полноценной поддержки NVMe-over-Fabrics.

### Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
|---|---|---|
| `ImagePullBackOff` | Образ отсутствует в Harbor или неверно указан путь | Проверить логи `describe pod`. Убедиться, что `image.registry` или `global.imageRegistry` применились корректно. |
| `iscsid not found` | На рабочих узлах не запущен сервис iSCSI | Выполнить `apt install open-iscsi && systemctl enable --now iscsid` на всех нодах. |
| Ошибка монтирования RWX | Отсутствует NFS клиент | Установить `nfs-common` (Debian/Ubuntu) или `nfs-utils` (RHEL/CentOS). |
| CSI-аттачер висит в `Pending` | Конфликт версий K8s | Longhorn v1.12+ использует API, появившиеся в K8s v1.25. Проверьте версию кластера: `kubectl version`. |

### Связанные темы

- [Longhorn — основной обзор и архитектура](./longhorn.md)
- [CSI Drivers — сравнение и принципы работы](./CSI/csi_drivers_comparison.md)
- [Harbor — управление OCI артефактами](../../Docker/Docker_registries/Harbor/usage.md)
- [Air-gapped установка мониторинга](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md)
