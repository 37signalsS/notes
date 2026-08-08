# Longhorn — распределённое блочное хранилище для Kubernetes

## Определения

**Longhorn** — cloud-native распределённое блочное хранилище с открытым исходным кодом для Kubernetes. Оно превращает локальные диски узлов в отказоустойчивый пул хранения, обеспечивая репликацию данных, создание снимков (snapshots) и инкрементальное резервное копирование.

**Data Engine (Движок данных)** — программный слой, отвечающий за операции ввода-вывода.
- **V1 (Engine)** — классический движок на базе разреженных файлов (sparse files) в `/var/lib/longhorn`. Стабилен, является выбором по умолчанию.
- **V2 (SPDK)** — высокопроизводительный движок на базе Storage Performance Development Kit (SPDK), работающий напрямую с NVMe-дисками. Находится в статусе Preview (в версии 1.8), требует предварительной настройки узлов (HugePages, выделенные CPU).

**defaultReplicaCount** — количество реплик тома по умолчанию. Для Production-сред рекомендуется значение **3**.

**ReplicaSoftAntiAffinity** — параметр, позволяющий размещать несколько реплик одного тома на одном узле (при значении `true`). Полезно для кластеров с малым количеством узлов (1-2), но значительно снижает отказоустойчивость.

**DR Volume (Disaster Recovery Volume)** — специальный тип тома, который создается из бэкапа в другом кластере и находится в режиме ожидания (Standby). Позволяет быстро переключить нагрузку при отказе основного кластера.

**Air-gapped (закрытый контур)** — изолированная среда без доступа к интернету. Полная процедура установки в такой среде описана в [Longhorn — установка в закрытом контуре](./longhorn-air-gapped.md).

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

### Особенности движка V2 (SPDK)

Начиная с версии 1.7/1.8, движок V2 предоставляет значительный прирост производительности I/O, но имеет специфические требования:
1. **HugePages:** Необходимо выделить минимум 2Gi HugePages (2MB size) на каждом узле.
2. **CPU Isolation:** Для стабильной работы `spdk_tgt` рекомендуется выделять отдельные ядра CPU.
3. **NVMe:** Оптимизирован для работы с NVMe-накопителями через пользовательское пространство (userspace).

### Сценарии использования

| Сценарий | Реплики | AntiAffinity | StorageClass |
|---|---|---|---|
| **Dev/Test (1-2 узла)** | 1-2 | soft (`true`) | `longhorn` |
| **Production (3+ узлов)** | 3 | hard (`false`) | `longhorn` |
| **RWX (Shared Volumes)** | 2-3 | soft (`true`) | `longhorn` (accessMode: RWX) |

Сравнение с другими решениями: [Сравнение CSI-драйверов](./CSI/csi_drivers_comparison.md). Для простейших сценариев без репликации см. [Local Path Provisioner](./local-path-provisioner.md).

## Практические сценарии

### Подготовка и проверка окружения

Перед установкой необходимо убедиться, что на всех узлах установлены зависимости: `open-iscsi` и `nfs-common`.

**Шаг 1. Установка зависимостей (Ubuntu/Debian):**
```bash
sudo apt update && sudo apt install -y open-iscsi nfs-common
sudo systemctl enable --now iscsid
```

**Шаг 2. Проверка соответствия требованиям:**
Используйте официальный скрипт для автоматической проверки (замените версию на актуальную, например, `v1.8.0`):
```bash
curl -sSfL https://raw.githubusercontent.com/longhorn/longhorn/v1.8.0/scripts/environment_check.sh | bash
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
  # Настройка бэкапов (S3)
  backupTarget: "s3://my-backup-bucket@us-east-1/"
  backupTargetCredentialSecret: "s3-secret"
  # Автоматическое перераспределение реплик (1.7+)
  replicaAutoBalance: "best-effort"
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

### Настройка мониторинга

Longhorn экспортирует метрики в формате Prometheus через сервис `longhorn-backend`.

1. **ServiceMonitor:** Если используется `kube-prometheus-stack`, включите создание ServiceMonitor в `values.yaml`:
   ```yaml
   metrics:
     serviceMonitor:
       enabled: true
   ```
2. **Дашборды:** Официальные дашборды доступны в Grafana Labs (ID: 13070, 16888 для V2).
3. **Ключевые метрики:**
   - `longhorn_volume_state`: статус тома.
   - `longhorn_node_disk_capacity_bytes`: свободное место на дисках.
   - `longhorn_instance_manager_cpu_usage`: потребление ресурсов.

### Безопасность и шифрование

Longhorn поддерживает шифрование томов "на лету" с использованием `dm-crypt`.

**Настройка через StorageClass:**
```yaml
kind: StorageClass
apiVersion: storage.k8s.io/v1
metadata:
  name: longhorn-crypto
provisioner: driver.longhorn.io
parameters:
  numberOfReplicas: "3"
  staleReplicaTimeout: "2880"
  encrypted: "true"
  # Имя секрета с ключом шифрования
  csi.storage.k8s.io/node-publish-secret-name: "longhorn-crypto-key"
  csi.storage.k8s.io/node-publish-secret-namespace: "longhorn-system"
```
Секрет должен содержать поле `CRYPTO_KEY_VALUE`. Также поддерживается интеграция с внешними KMS.

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
В UI: `Settings` → `General` → `Backup Target`. Укажите путь (например, `s3://bucket@region/`) и имя секрета. В версии 1.8 поддерживается работа с несколькими Backup Targets одновременно.

### Управление томами

#### Расширение тома
Longhorn поддерживает расширение томов "на лету" (Online expansion), если файловая система это поддерживает (ext4, XFS).
1. Отредактируйте PVC в Kubernetes: `kubectl edit pvc <pvc_name>`.
2. Измените значение `spec.resources.requests.storage` на большее.
3. Longhorn автоматически расширит том и файловую систему.

#### Создание Disaster Recovery (DR) тома
1. Имея настроенный `Backup Target`, перейдите в UI -> `Backup`.
2. Выберите нужный бэкап и нажмите `Create DR Volume`.
3. Укажите имя тома. Он будет создан в режиме `Standby`, периодически скачивая инкрементальные обновления из бэкапа.
4. Для активации тома (превращения в обычный) нажмите `Activate` в UI.

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

#### Регламентное обслуживание узлов
При необходимости вывести узел из эксплуатации (например, для обновления ядра ОС):
1. В UI Longhorn перейдите в `Node`.
2. Выберите узел и установите `Edit Node` -> `Allow Scheduling` -> `Disable`.
3. Дождитесь завершения репликации данных на другие узлы (если включен `Eviction`).
4. Выполните `kubectl drain <node_name>`.

#### Очистка свободного места (Volume Trim)
Longhorn поддерживает команду `fstrim`. Для автоматической очистки неиспользуемых блоков на разреженных файлах (sparse files) можно запустить CronJob внутри пода или включить периодический Trim в настройках Longhorn (начиная с 1.7).

#### Обновление Longhorn
1. Прочитайте Release Notes для вашей целевой версии (например, при переходе с 1.7 на 1.8).
2. Обновите Helm-репозиторий: `helm repo update`.
3. Примените новую версию:
   ```bash
   helm upgrade longhorn longhorn/longhorn -n longhorn-system --version 1.8.0
   ```
4. После обновления Manager-а Longhorn предложит обновить Engine для каждого тома через UI (раздел `Volume` -> кнопка `Upgrade Engine`). **Важно:** Обновление Engine приводит к кратковременному прерыванию I/O (в движке V1).

## Дополнительная информация

### Важные параметры values.yaml

| Параметр | Описание | Значение по умолчанию |
|---|---|---|
| `defaultSettings.defaultReplicaCount` | Количество реплик для новых томов. | 3 |
| `defaultSettings.replicaSoftAntiAffinity` | Разрешить реплики на одном узле. | `false` |
| `defaultSettings.storageOverProvisioningPercentage` | Множитель "виртуального" места. | 200 |
| `defaultSettings.storageMinimalAvailablePercentage` | Порог остановки выделения места (%). | 25 |
| `defaultSettings.replicaAutoBalance` | Автобалансировка реплик (`disabled`, `least-effort`, `best-effort`). | `disabled` |
| `defaultSettings.taintToleration` | Толерантность для запуска компонентов на специфичных узлах. | (пусто) |
| `global.imageRegistry` | Общий префикс для всех образов (для приватных репозиториев). | (пусто) |

### Устранение неполадок

| Проблема | Возможная причина | Решение |
|---|---|---|
| Поды в `ImagePullBackOff` | Нет доступа к Docker Hub или образы не в Harbor. | Проверить доступность сети и `global.imageRegistry` в values. |
| Ошибка `iscsid not found` | На узлах не запущен сервис iSCSI. | Установить `open-iscsi` и выполнить `systemctl start iscsid`. |
| Volume застрял в `Attaching` | Проблема с CSI-драйвером или `iscsid`. | Проверить логи `longhorn-manager` и статус сервиса `iscsid` на узле. |
| Низкая производительность | Высокая задержка сети или медленные диски. | Проверить сетевой канал (рекомендуется 10Gbps) и использовать SSD. |
| RWX Volume не монтируется | Не установлен `nfs-common`. | Установить `nfs-common` на всех рабочих узлах. |
| V2 Engine не запускается | Не настроены HugePages. | Проверить `/proc/meminfo` на наличие `HugePages_Total`. |

### Связанные темы

- Концепции хранилищ: [Persistent Volumes и StorageClass](./pv_and_pvc.md)
- Сравнение CSI-драйверов: [Сравнение CSI-драйверов](./CSI/csi_drivers_comparison.md)
- Установка в закрытом контуре: [Longhorn — установка в закрытом контуре](./longhorn-air-gapped.md)
- Использование Harbor: [Использование Harbor](../../Docker/Docker_registries/Harbor/usage.md)
