# Longhorn — установка в закрытом контуре (Air-gapped)

## Определения

**`Air-gapped installation`** — процедура развёртывания Longhorn в изолированном Kubernetes-кластере без прямого доступа к интернету. Все артефакты (Docker-образы, Helm-чарты) скачиваются заранее на хосте с доступом в сеть и переносятся во внутренний контур вручную (через съемные носители или одноразовые SSH-бастионы).

**`Container Registry`** — сервер для хранения и распространения OCI-образов. В air-gapped среде используется приватный registry (Harbor, Nexus, Docker Registry) как единственный источник образов для кластера.

**`Harbor`** — приватный container registry с поддержкой RBAC, сканирования уязвимостей и OCI-артефактов. Рекомендуется для air-gapped сред. Подробнее: [Использование Harbor](../../Docker/Docker_registries/Harbor/usage.md).

**`OCI (Open Container Initiative)`** — стандарт хранения и распространения образов и Helm-чартов внутри registry. Позволяет использовать единый формат для всех артефактов.

**`Skopeo`** — инструмент для работы с OCI-образами без Docker-демона. Позволяет копировать, зеркалировать и проверять образы между реестрами. Основной инструмент для air-gapped сред.

**`ImagePullSecret`** — Kubernetes Secret типа `kubernetes.io/dockerconfigjson`, содержащий учётные данные для доступа к приватному registry. Обязателен для air-gapped сред.

**`containerd`** — CRI-рантайм, используемый в большинстве современных Kubernetes-дистрибутивов. В air-gapped среде требует настройки `hosts.toml` для перенаправления pull-запросов на внутренний registry.

**`Sandbox Image (Pause container)`** — вспомогательный образ (`registry.k8s.io/pause`), используемый Kubernetes для создания сетевого пространства имён пода. В air-gapped среде должен присутствовать в registry.

**`V2 Data Engine (SPDK)`** — движок хранения Longhorn на базе SPDK (Storage Performance Development Kit). Обеспечивает производительность на уровне NVMe. Требует HugePages и выделенных CPU ядер.

**`Backup Target`** — удалённое хранилище для резервных копий томов Longhorn (NFS, S3-compatible). В air-gapped среде используется только NFS или локальное хранилище.

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

### Шаг 0. Требования к сети и инфраструктуре

| Параметр | Значение |
| :--- | :--- |
| **Сеть** | Кластер и registry должны быть в одной L3-сети или иметь маршрутизацию |
| **Порты registry** | 443 (HTTPS), 5000 (HTTP, если без TLS) |
| **Порты NFS** | 2049 (TCP/UDP), 20048 (mountd), 111 (rpcbind) |
| **DNS** | Внутренний DNS должен резолвить имя registry (например, `harbor.domain.local`) |
| **TLS** | Self-signed сертификаты требуют добавления CA на все узлы |
| **Диск** | Минимум 50Gi свободного места на узле для образов и данных Longhorn |

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

**2. Настройка containerd для работы с приватным registry:**

В air-gapped среде containerd должен перенаправлять все pull-запросы на внутренний registry. Создайте/отредактируйте файл `hosts.toml`:

```toml
# /etc/containerd/certs.d/harbor.domain.local/hosts.toml
server = "https://harbor.domain.local"

[host."https://harbor.domain.local"]
  capabilities = ["pull", "resolve"]
  skip_verify = false  # true для self-signed CA (если CA добавлен в system)
  ca = "/etc/containerd/certs.d/ca.crt"  # Путь к CA-сертификату Harbor

  [host."https://harbor.domain.local".header]
    x-custom-header = ["value"]
```

**Для перенаправления всех pull-запросов (mirror):**
```toml
# /etc/containerd/certs.d/docker.io/hosts.toml
server = "https://docker.io"

[host."https://harbor.domain.local"]
  capabilities = ["pull", "resolve", "push"]
  override_path = true  # Используйте точный путь проекта Harbor
```

**Применение изменений:**
```bash
# Проверка конфигурации
sudo containerd config dump | grep -A 5 "harbor"

# Перезапуск containerd
sudo systemctl restart containerd

# Проверка pull
sudo crictl pull harbor.domain.local/longhornio/longhorn-manager:v1.12.0
```

**3. Настройка imagePullSecrets для подов Longhorn:**

```bash
kubectl create secret docker-registry longhorn-registry-secret \
  --docker-server=harbor.domain.local \
  --docker-username="robot-longhorn" \
  --docker-password="<password>" \
  -n longhorn-system
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

### Шаг 6. Backup и восстановление в закрытом контуре

**Настройка BackupTarget (NFS):**

В air-gapped среде BackupTarget должен указывать на NFS-сервер в той же сети:

```bash
# Через Longhorn UI
Settings → Backup Target → nfs://10.0.0.100/backup/longhorn

# Или через kubectl
kubectl patch settings default-backup-target \
  -n longhorn-system \
  --type merge \
  -p '{"value":"nfs://10.0.0.100/backup/longhorn"}'
```

**Ручной бэкап тома:**
```bash
# Создание снимка
kubectl get volumes.longhorn.io -n longhorn-system
kubectl create -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: Backup
metadata:
  name: backup-vol-001
  namespace: longhorn-system
spec:
  volume: pvc-12345678-abcd-1234-abcd-1234567890ab
  snapshot: ""
EOF

# Проверка статуса
kubectl get backups.longhorn.io -n longhorn-system
```

**Восстановление из бэкапа:**
```bash
# Через UI: Backup → Volume → Restore
# Или через kubectl:
kubectl create -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: Restore
metadata:
  name: restore-vol-001
  namespace: longhorn-system
spec:
  backup: backup-vol-001
  frontend: blockdev
  restoreMode: restore
  pvcName: restored-pvc
  pvcNamespace: default
EOF
```

**Автоматические Scheduled Backups:**
```bash
kubectl create -f - <<EOF
apiVersion: longhorn.io/v1beta2
kind: RecurringJob
metadata:
  name: daily-backup
  namespace: longhorn-system
spec:
  concurrency: 1
  cron: "0 2 * * *"  # Каждый день в 02:00
  groups:
    - daily
  retain: 7
  task: backup
  tags:
    - daily
    - air-gapped
EOF
```

### Шаг 7. Мониторинг Longhorn в закрытом контуре

**Метрики Longhorn:**

Longhorn экспортирует метрики через Prometheus exporter на порту 9500:

```bash
# Проверка метрик с пода Longhorn Manager
kubectl exec -it -n longhorn-system longhorn-manager-xxxxx -- \
  wget -qO- http://localhost:9500/metrics
```

**Ключевые метрики для мониторинга:**

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `longhorn_volume_capacity_bytes` | Общий размер тома | Нет |
| `longhorn_volume_actual_size_bytes` | Фактический размер данных | `actual > capacity * 0.9` |
| `longhorn_volume_robustness` | Состояние тома (1=OK) | `robustness < 1` |
| `longhorn_node_storage_available_bytes` | Свободное место на ноде | `< 10Gi` |
| `longhorn_node_storage_reservation_bytes` | Зарезервированное место | `reservation > available` |
| `longhorn_manager_up` | Статус менеджера | `up == 0` |

**ServiceMonitor для Prometheus (air-gapped):**
```bash
kubectl create -f - <<EOF
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: longhorn
  namespace: longhorn-system
  labels:
    release: prometheus  # Подключить к существующему Prometheus
spec:
  namespaceSelector:
    matchNames:
      - longhorn-system
  selector:
    matchLabels:
      app.kubernetes.io/name: longhorn-manager
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
EOF
```

## Дополнительная информация

### Особенности V2 Data Engine (SPDK)
В версии **v1.12.0** новый движок на базе SPDK официально объявлен стабильным (GA). Его использование в закрытом контуре требует:
1. **Образы:** Движок V2 использует специфические образы `instance-manager` (с SPDK). Убедитесь, что они присутствуют в `lh-images.txt`.
2. **Системные требования:** На узлах должны быть выделены HugePages (минимум 2Gi на узел) и свободные CPU ядра. Так как доступа к интернету нет, эти настройки должны быть вшиты в базовый образ ОС или применены через IaC (Ansible/Salt).
3. **Настройка HugePages (на каждом узле):**
```bash
# Проверка текущих HugePages
cat /proc/meminfo | grep HugePages

# Настройка (через sysctl)
echo "vm.nr_hugepages=1024" >> /etc/sysctl.d/99-longhorn-hugepages.conf
sysctl -p /etc/sysctl.d/99-longhorn-hugepages.conf

# Или через systemd
mkdir -p /etc/systemd/system/longhorn-hugepages.service.d
```

### Автоматизация air-gapped развёртывания (Ansible)

Для массового развёртывания в air-gapped среде используйте Ansible-плейбуки:

**Пример плейбука для подготовки узлов:**
```yaml
# prepare-nodes.yml
---
- name: Prepare nodes for Longhorn air-gapped
  hosts: longhorn_nodes
  become: yes
  vars:
    harbor_ca_cert: "./certs/harbor-ca.crt"
    longhorn_images_dir: "./lh-tars"
  
  tasks:
    - name: Install dependencies
      apt:
        name:
          - open-iscsi
          - nfs-common
          - nfs-utils
        state: present
        update_cache: yes

    - name: Copy Harbor CA certificate
      copy:
        src: "{{ harbor_ca_cert }}"
        dest: /usr/local/share/ca-certificates/harbor.crt
        mode: '0644'
      notify: update-ca-certificates

    - name: Configure containerd mirror
      template:
        src: templates/hosts.toml.j2
        dest: /etc/containerd/certs.d/harbor.domain.local/hosts.toml
      notify: restart-containerd

    - name: Load Longhorn images from tar
      shell: |
        for f in {{ longhorn_images_dir }}/*.tar; do
          docker load -i "$f" || true
        done
      args:
        creates: /var/lib/containerd

  handlers:
    - name: update-ca-certificates
      shell: update-ca-certificates

    - name: restart-containerd
      systemd:
        name: containerd
        state: restarted
```

**Запуск:**
```bash
ansible-playbook -i inventory.ini prepare-nodes.yml --ask-vault-pass
```

### Диагностика и отладка

**Полная диагностика проблем с Longhorn в air-gapped среде:**

```bash
# 1. Проверка статуса всех подов Longhorn
kubectl get pods -n longhorn-system -o wide
kubectl get pods -n longhorn-system | grep -v Running

# 2. Логи менеджера (ошибки桂编织 и движка)
kubectl logs -n longhorn-system longhorn-manager-xxxxx --tail=100

# 3. Проверка GPU/SPDK (V2 Data Engine)
kubectl logs -n longhorn-system instance-manager-xxx | grep -i spdk

# 4. Проверкаcsi-driver
kubectl get csidrivers
kubectl describe csidriver driver.longhorn.io

# 5. Проверка storageclass
kubectl get storageclass
kubectl describe storageclass longhorn

# 6. Проверкаcsi-attacher/provisioner
kubectl logs -n longhorn-system csi-attacher-xxxxx --tail=50

# 7. Диагностика сетевой доступности к registry
kubectl run debug --rm -it --image=alpine -- sh
apk add --no-cache curl
curl -k https://harbor.domain.local/api/v2.0/health

# 8. Проверка HRBAC и Secrets
kubectl get secrets -n longhorn-system
kubectl get serviceaccount -n longhorn-system

# 9. Проверка BackupTarget
kubectl get settings -n longhorn-system | grep backup

# 10. Longhorn UI доступ (port-forward)
kubectl port-forward -n longhorn-system svc/longhorn-frontend 8080:80
```

**Типичные ошибки и решения:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `x509: certificate signed by unknown authority` | Кластер не доверяет CA Harbor | См. Шаг 2.1. Добавьте сертификат в доверенные на всех узлах. |
| `ImagePullBackOff` | Образ отсутствует в Harbor или неверно указан путь | Проверить логи `describe pod`. Убедиться, что `global.imageRegistry` применился корректно. |
| `iscsid not found` | На рабочих узлах не запущен сервис iSCSI | Пакет `open-iscsi` должен быть в локальном репозитории ОС. Выполнить `apt install open-iscsi && systemctl enable --now iscsid`. |
| Ошибка монтирования RWX | Отсутствует NFS клиент | Установить `nfs-common` (Debian/Ubuntu) или `nfs-utils` (RHEL/CentOS) из локального зеркала. |
| CSI-аттачер висит в `Pending` | Конфликт версий K8s | Longhorn v1.12+ требует K8s v1.25+. Проверьте версию: `kubectl version`. |
| `context deadline exceeded` | Сетевая проблема между узлом и Harbor | Проверьте маршрутизацию, DNS-резолв, файервол (порт 443). |
| `unable to create backup` | BackupTarget недоступен или неверные права | Проверьте NFS-экспорт, права доступа, и что BackupTarget доступен со всех узлов. |
| `volume not ready` | Движок Longhorn не запущен | Проверьте логи `longhorn-manager`, `instance-manager`. |
| `HugePages not configured` | V2 Data Engine требует HugePages | См. раздел V2 Data Engine. Настрой HugePages на каждом узле. |
| `storage minimal available` | Недостаточно места для нового тома | Увеличьте `storageMinimalAvailablePercentage` или освободите место на нодах. |

### Связанные темы

- [Longhorn — основной обзор и архитектура](./longhorn.md)
- [CSI Drivers — сравнение и принципы работы](./CSI/csi_drivers_comparison.md)
- [Harbor — управление OCI артефактами](../../Docker/Docker_registries/Harbor/usage.md)
- [containerd — настройка registry mirrors](../../Kubernetes/Concepts/container_runtime.md)
- [Air-gapped ошибки Image Pull — диагностика](../../Kubernetes/Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)
- [Skopeo — работа с OCI-образами](../../Podman/skopeo_overview.md)
- [Ansible — роли и коллекции](../../Ansible/Roles/galaxy.md)
- [Air-gapped установка мониторинга](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md)
