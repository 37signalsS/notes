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

| Компонент | Назначение / Требование |
|---|---|
| **Хост с интернетом** | ОС Linux, установленные Docker/Podman или Skopeo, Helm v3.8+ |
| **Kubernetes cluster** | Версия **v1.25** или выше (для работы CSI и Longhorn v1.12.0+) |
| **Registry (Harbor)** | Должен поддерживать OCI для хранения чартов и иметь настроенный TLS. |
| **iSCSI / NFS** | На узлах K8s должны быть установлены `open-iscsi` и `nfs-common`. |
| **Доверие (TLS)** | Узлы кластера должны доверять корневому сертификату (CA) Harbor. |

## Практические сценарии

### Шаг 1. Подготовка артефактов (на хосте с интернетом)

**1. Скачивание Helm-чарта:**

```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update
# Актуальная версия на август 2026: v1.12.0
helm pull longhorn/longhorn --version v1.12.0 --untar
```

**2. Получение списка образов и скриптов проверки:**

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

*Скрипт проверки окружения (Environment Check):*
```bash
curl -sSfL "https://raw.githubusercontent.com/longhorn/longhorn/${VERSION}/scripts/environment_check.sh" -o environment_check.sh
chmod +x environment_check.sh
```

**3. Зеркалирование и упаковка образов:**

*Вариант А: Через Skopeo (эффективный)*
Позволяет сохранить образы сразу в формате OCI-директории без Docker-демона.
```bash
mkdir -p lh-images-oci
while read -r img; do
  skopeo copy "docker://${img}" "dir:lh-images-oci/$(echo $img | tr '/:' '_')"
done < lh-images.txt
```

*Вариант Б: Через Docker (традиционный)*
```bash
# Pull и Save
while read -r img; do docker pull "${img}"; done < lh-images.txt
mkdir -p lh-tars
while read -r img; do
  safe=$(echo "$img" | tr '/:' '_')
  docker save -o "lh-tars/${safe}.tar" "${img}"
done < lh-images.txt
```

**4. Подготовка чарта к переносу:**
```bash
tar -cvzf longhorn-helm-v1.12.0.tar.gz longhorn/
```

### Шаг 2. Загрузка в приватный репозиторий (в закрытом контуре)

**1. Настройка доверия к Harbor (TLS):**

Если Harbor использует самоподписанный сертификат, его необходимо добавить на все узлы кластера (Control Plane и Worker Nodes), чтобы Kubelet и рантайм могли скачивать образы.

```bash
# Пример для Ubuntu/Debian
sudo cp harbor-ca.crt /usr/local/share/ca-certificates/harbor.crt
sudo update-ca-certificates
sudo systemctl restart containerd # Или docker
```

**2. Импорт и Пуш образов:**

Предположим, адрес Harbor `harbor.domain.local` и проект `longhornio`.

```bash
REGISTRY="harbor.domain.local"
PROJECT="longhornio" 

# При использовании Skopeo (из директории)
while read -r img; do
  skopeo copy "dir:lh-images-oci/$(echo $img | tr '/:' '_')" "docker://${REGISTRY}/${PROJECT}/${img##*/}"
done < lh-images.txt

# При использовании Docker (из tar-архивов)
# for f in lh-tars/*.tar; do docker load -i "$f"; done
# while read -r img; do
#   docker tag "${img}" "${REGISTRY}/${PROJECT}/${img##*/}"
#   docker push "${REGISTRY}/${PROJECT}/${img##*/}"
# done < lh-images.txt
```

**3. Пуш чарта в OCI-репозиторий:**
```bash
helm login "$REGISTRY"
helm push longhorn-helm-v1.12.0.tar.gz oci://${REGISTRY}/helm
```

### Шаг 3. Детальная конфигурация values.yaml

В версии v1.12.0 рекомендуется использовать `global.imageRegistry` для упрощения.

#### Вариант 1: Упрощенный (Global Registry)
Подходит, если все образы лежат в одном проекте Harbor.

```yaml
global:
  imageRegistry: harbor.domain.local/longhornio
  imagePullSecrets:
    - name: longhorn-registry-secret

defaultSettings:
  defaultReplicaCount: 3
  # Проверка iSCSI на узлах при старте
  check-pre-requisite: true
  # V2 Data Engine (SPDK) — статус GA в v1.12.0
  v2-data-engine: false 
  storageOverProvisioningPercentage: 200
  storageMinimalAvailablePercentage: 10

longhornUI:
  replicas: 2
```

#### Вариант 2: Детальный (Manual Overrides)
Необходим, если образы переименованы или распределены по разным проектам.

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

**1. Проверка окружения:**
Перед установкой запустите скрипт проверки на узлах (через Ansible или вручную):
```bash
./environment_check.sh
```

**2. Создание секрета и установка:**
```bash
kubectl create namespace longhorn-system
kubectl create secret docker-registry longhorn-registry-secret \
  --docker-server=harbor.domain.local \
  --docker-username="robot-longhorn" \
  --docker-password="password" \
  -n longhorn-system

helm install longhorn oci://harbor.domain.local/helm/longhorn \
  --version v1.12.0 \
  -n longhorn-system \
  -f values.yaml
```

**3. Проверка статуса:**
```bash
kubectl get pods -n longhorn-system -o wide
# Все поды должны быть в Running. Проверьте, что образы тянутся из Harbor.
```

### Шаг 5. Обновление в закрытом контуре

Процесс обновления (например, на v1.13.0) выполняется по той же схеме:

1. **Миграция артефактов:** Скачайте новый чарт и список образов. Перенесите их в Harbor.
2. **Upgrade чарта:**
   ```bash
   helm upgrade longhorn oci://harbor.domain.local/helm/longhorn \
     --version v1.13.0 \
     -n longhorn-system \
     -f values.yaml
   ```
3. **Upgrade Engine:** После обновления `longhorn-manager` поды управления обновятся автоматически, но **движки существующих томов** требуют ручного подтверждения. В UI Longhorn (раздел `Volume`) нажмите кнопку `Upgrade Engine` для каждого тома. Это обеспечит переход на новую версию бинарного файла engine без потери данных.

## Дополнительная информация

### Особенности V2 Data Engine (SPDK)
В версии **v1.12.0** новый движок на базе SPDK официально объявлен стабильным (GA). Его использование в закрытом контуре требует:
1. **Образы:** Движок V2 использует специфические образы `instance-manager` (с SPDK). Убедитесь, что они присутствуют в `lh-images.txt`.
2. **Системные требования:** На узлах должны быть выделены HugePages (минимум 2Gi на узел) и свободные CPU ядра. Так как доступа к интернету нет, эти настройки должны быть вшиты в базовый образ ОС или применены через IaC (Ansible/Salt).

### Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
|---|---|---|
| `x509: certificate signed by unknown authority` | Кластер не доверяет CA Harbor | См. Шаг 2.1. Добавьте сертификат в доверенные на всех узлах. |
| `ImagePullBackOff` | Образ отсутствует в Harbor или неверно указан путь | Проверить логи `describe pod`. Убедиться, что `global.imageRegistry` применился корректно. |
| `iscsid not found` | На рабочих узлах не запущен сервис iSCSI | Пакет `open-iscsi` должен быть в локальном репозитории ОС. Выполнить `apt install open-iscsi && systemctl enable --now iscsid`. |
| Ошибка монтирования RWX | Отсутствует NFS клиент | Установить `nfs-common` (Debian/Ubuntu) или `nfs-utils` (RHEL/CentOS) из локального зеркала. |
| CSI-аттачер висит в `Pending` | Конфликт версий K8s | Longhorn v1.12+ требует K8s v1.25+. Проверьте версию: `kubectl version`. |

### Связанные темы

- [Longhorn — основной обзор и архитектура](./longhorn.md)
- [CSI Drivers — сравнение и принципы работы](./CSI/csi_drivers_comparison.md)
- [Harbor — управление OCI артефактами](../../Docker/Docker_registries/Harbor/usage.md)
- [Air-gapped установка мониторинга](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md)
