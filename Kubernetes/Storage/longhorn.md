# Longhorn — распределённое блочное хранилище для Kubernetes

## Определения

**Longhorn** — cloud-native распределённое блочное хранилище с открытым исходным кодом для Kubernetes. Оно превращает локальные диски узлов в отказоустойчивый пул хранения, обеспечивая репликацию данных, создание снимков (snapshots) и инкрементальное резервное копирование.

**Data Engine (Движок данных)** — программный слой, отвечающий за операции ввода-вывода.
- **V1 (Engine)** — классический движок на базе разреженных файлов (sparse files) в `/var/lib/longhorn`.
- **V2 (SPDK)** — высокопроизводительный движок на базе Storage Performance Development Kit (доступен с версии 1.5.0), работающий напрямую с NVMe-дисками.

**defaultReplicaCount** — количество реплик тома по умолчанию. Для Production-сред рекомендуется значение **3**.

**ReplicaSoftAntiAffinity** — параметр, позволяющий размещать несколько реплик одного тома на одном узле (при значении `true`). Полезно для кластеров с малым количеством узлов (1-2), но снижает отказоустойчивость.

**Air-gapped (закрытый контур)** — изолированная среда без доступа к интернету. Полная процедура установки в такой среде описана в [Longhorn Air-gapped Installation](./longhorn-air-gapped.md).

## Основные концепции

### Архитектура Longhorn

Longhorn работает как набор микросервисов внутри Kubernetes. Управление осуществляется через Custom Resources (CRD).

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
| **Longhorn Manager** | DaemonSet, управляет жизненным циклом томов, реплик и узлов. |
| **Longhorn Engine** | Процесс, отвечающий за репликацию данных для конкретного тома. |
| **CSI Driver** | Обеспечивает интеграцию с Kubernetes (создание, монтирование томов). |
| **Instance Manager** | Управляет процессами Engine и Replica на каждом узле. |
| **Share Manager** | Обеспечивает поддержку RWX-томов через встроенный NFS-сервер. |
| **Backing Image Manager** | Управляет образами, которые могут использоваться как основа для томов. |

### Сценарии использования

| Сценарий | Реплики | AntiAffinity | StorageClass |
|---|---|---|---|
| **Dev/Test (1-2 узла)** | 1-2 | soft (`true`) | `longhorn` |
| **Production (3+ узлов)** | 3 | hard (`false`) | `longhorn` |
| **RWX (Shared Volumes)** | 2-3 | soft (`true`) | `longhorn` (accessMode: RWX) |

Сравнение с другими решениями: [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md). Для простейших сценариев без репликации см. [Local Path Provisioner](./local-path-provisioner.md).

## Практические сценарии

### Подготовка и проверка окружения

Перед установкой необходимо убедиться, что на всех узлах установлены зависимости: `open-iscsi` и `nfs-common`.

**Шаг 1. Установка зависимостей (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install -y open-iscsi nfs-common
sudo systemctl enable --now iscsid
```

**Шаг 2. Проверка соответствия требованиям:**
Используйте официальный скрипт для автоматической проверки (замените версию на актуальную):
```bash
curl -sSfL https://raw.githubusercontent.com/longhorn/longhorn/v1.7.2/scripts/environment_check.sh | bash
```

### Онлайн установка через Helm

**Требования:** Kubernetes ≥ 1.25, Helm 3.x.

**Шаг 1. Настройка параметров (`longhorn-values.yaml`):**
```yaml
defaultSettings:
  defaultReplicaCount: 3
  replicaSoftAntiAffinity: false
  storageOverProvisioningPercentage: 200
  storageMinimalAvailablePercentage: 15
  backupTarget: "s3://my-backup-bucket@us-east-1/"
  backupTargetCredentialSecret: "s3-secret"
longhornUI:
  replicas: 1
```

**Шаг 2. Установка:**
```bash
helm repo add longhorn https://charts.longhorn.io
helm repo update
helm install longhorn longhorn/longhorn \
  -n longhorn-system \
  --create-namespace \
  -f longhorn-values.yaml
```

### Настройка хранилища бэкапов (S3)

Для обеспечения сохранности данных Longhorn должен сохранять бэкапы во внешнее хранилище.

**Шаг 1. Создание секрета с учетными данными:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: s3-secret
  namespace: longhorn-system
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "your_key"
  AWS_SECRET_ACCESS_KEY: "your_secret"
  AWS_ENDPOINTS: "https://s3.your-provider.com" # Для S3-совместимых хранилищ
```

**Шаг 2. Обновление настроек:**
В UI: `Settings` → `General` → `Backup Target`. Укажите путь (например, `s3://bucket@region/`) и имя секрета.

### Управление томами

#### Расширение тома (Volume Expansion)
Longhorn поддерживает расширение томов "на лету" (Online expansion), если файловая система это поддерживает (ext4, XFS).
1. Отредактируйте PVC в Kubernetes:
   ```bash
   kubectl edit pvc <pvc_name>
   ```
2. Измените значение `spec.resources.requests.storage` на большее.
3. Longhorn автоматически расширит том и файловую систему.

#### Доступ к панели управления (UI)
**Через Port-forward:**
```bash
kubectl port-forward service/longhorn-frontend 8080:80 -n longhorn-system
# Доступ по адресу http://localhost:8080
```

**Через Ingress (рекомендуется):**
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: longhorn-ui
  namespace: longhorn-system
  annotations:
    nginx.ingress.kubernetes.io/auth-type: basic # Рекомендуется защитить UI паролем
    nginx.ingress.kubernetes.io/auth-secret: basic-auth
spec:
  ingressClassName: nginx
  rules:
  - host: longhorn.example.com
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

### Обслуживание и обновление

#### Регламентное обслуживание узлов (Node Maintenance)
При необходимости вывести узел из эксплуатации (например, для обновления ядра ОС):
1. В UI Longhorn перейдите в `Node`.
2. Выберите узел и установите `Edit Node` -> `Allow Scheduling` -> `Disable`.
3. Дождитесь завершения репликации данных на другие узлы (если включен `Eviction`).
4. Выполните `kubectl drain <node_name>`.

#### Обновление Longhorn
1. Прочитайте Release Notes для вашей целевой версии.
2. Обновите Helm-репозиторий: `helm repo update`.
3. Примените новую версию:
   ```bash
   helm upgrade longhorn longhorn/longhorn -n longhorn-system --version <new_version>
   ```
4. После обновления Manager-а Longhorn предложит обновить Engine для каждого тома через UI (раздел `Volume` -> кнопка `Upgrade Engine`).

## Дополнительная информация

### Важные параметры values.yaml

| Параметр | Описание | Значение по умолчанию |
|---|---|---|
| `defaultSettings.defaultReplicaCount` | Количество реплик для новых томов. | 3 |
| `defaultSettings.replicaSoftAntiAffinity` | Разрешить реплики на одном узле. | `false` |
| `defaultSettings.storageOverProvisioningPercentage` | Множитель "виртуального" места. | 200 |
| `defaultSettings.storageMinimalAvailablePercentage` | Порог остановки выделения места (%). | 25 |
| `defaultSettings.taintToleration` | Толерантность для запуска компонентов на специфичных узлах. | (пусто) |
| `global.imageRegistry` | Общий префикс для всех образов (для приватных репозиториев). | (пусто) |

### Устранение неполадок (Troubleshooting)

| Проблема | Возможная причина | Решение |
|---|---|---|
| Поды в `ImagePullBackOff` | Нет доступа к Docker Hub или образы не в Harbor. | Проверить доступность сети и `image.registry` в values. |
| Ошибка `iscsid not found` | На узлах не запущен сервис iSCSI. | Установить `open-iscsi` и выполнить `systemctl start iscsid`. |
| Volume застрял в `Attaching` | Проблема с CSI-драйвером или `iscsid`. | Проверить логи `longhorn-manager` и статус сервиса `iscsid` на узле. |
| Низкая производительность | Высокая задержка сети или медленные диски. | Проверить сетевой канал (рекомендуется 10Gbps) и использовать SSD. |
| RWX Volume не монтируется | Не установлен `nfs-common`. | Установить `nfs-common` на всех рабочих узлах. |

### Связанные темы

- Концепции хранилищ: [Persistent Volumes и StorageClass](./pv_and_pvc.md)
- Сравнение CSI-драйверов: [CSI Drivers Comparison](./CSI/csi_drivers_comparison.md)
- Установка в закрытом контуре: [Longhorn Air-gapped Installation](./longhorn-air-gapped.md)
- Использование Harbor: [Harbor Usage](../../Docker/Docker_registries/Harbor/usage.md)
