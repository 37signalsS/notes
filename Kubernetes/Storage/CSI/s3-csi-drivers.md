# S3 CSI-драйверы в Kubernetes

S3 (Simple Storage Service) — это объектное хранилище, которое при использовании специальных драйверов можно монтировать в Kubernetes как файловую систему. Это решение идеально подходит для Read-Heavy нагрузок (статический контент, медиа-архивы, датасеты для ML), но имеет ограничения по сравнению с традиционными блочными хранилищами.

## Определения

**S3 CSI Driver** — программный интерфейс, позволяющий Kubernetes-кластеру взаимодействовать с объектными хранилищами по протоколу S3, представляя бакеты как стандартные тома (`PersistentVolumes`).

**Маунтер (Mounter)** — утилита (обычно на базе FUSE), которая выполняет фактическое преобразование вызовов файловой системы (POSIX) в API-запросы S3 (GET, PUT, LIST).
*   **GeeseFS** — высокопроизводительный маунтер (форк Goofys), оптимизированный для работы в облачных средах с минимизацией количества мета-операций.
*   **Mountpoint for Amazon S3** — официальный маунтер от AWS, ориентированный на максимальную пропускную способность (throughput) при чтении.
*   **JuiceFS** — распределенная файловая система, использующая S3 для хранения данных и внешнюю БД (Redis, SQL) для метаданных, обеспечивающая полную POSIX-совместимость.

---

## Базовые концепции

### Архитектура и компоненты
Типичный S3 CSI-драйвер состоит из стандартных Sidecar-контейнеров и специфичных компонентов поставщика:

1.  **Controller Plugin (Deployment):** Отвечает за создание/удаление бакетов (Dynamic Provisioning) и управление `VolumeAttachments`.
2.  **Node Plugin (DaemonSet):** Работает на каждом узле, выполняет монтирование бакета через FUSE в файловую систему хоста, а затем в контейнер пода.

### Типы монтирования
*   **Статическое (Static):** Бакет уже существует, драйверу передаются только учетные данные и имя бакета.
*   **Динамическое (Dynamic):** Драйвер сам создает бакет в S3 при создании `PersistentVolumeClaim`. Поддерживается не всеми драйверами (например, AWS Mountpoint не поддерживает динамику на август 2026).

---

## Обзор актуальных решений (2026)

### 1. Yandex Cloud CSI (k8s-csi-s3)
Универсальное решение для S3-совместимых хранилищ (Yandex Object Storage, MinIO, Ceph RGW).

*   **GitHub:** [yandex-cloud/k8s-csi-s3](https://github.com/yandex-cloud/k8s-csi-s3)
*   **Маунтер:** GeeseFS.
*   **Преимущества:** Поддержка динамического провизионирования, высокая стабильность, частичная поддержка записи (overwrite).

#### Установка через Terraform (Helm)
```hcl
resource "helm_release" "yandex-csi-s3" {
  name             = "yandex-csi-s3"
  repository       = "https://yandex-cloud.github.io/k8s-csi-s3/charts"
  chart            = "csi-s3"
  namespace        = "kube-system"

  values = [
    <<-EOT
      secret:
        accessKey: "${var.s3_access_key}"
        secretKey: "${var.s3_secret_key}"
        endpoint: "https://s3.storage.selcloud.ru"
        region: "ru-1"
    EOT
  ]
}
```

### 2. AWS Mountpoint S3 CSI Driver (v2.x)
Стандарт для инфраструктуры в AWS.

*   **GitHub:** [aws-mountpoint-s3-csi-driver](https://github.com/awslabs/aws-mountpoint-s3-csi-driver)
*   **Особенность:** Поддержка **Mountpoint Pod Sharing** (общий инстанс маунтера на ноде для экономии ресурсов).

### 3. JuiceFS CSI Driver
Рекомендуется для высокопроизводительных вычислений (HPC) и AI/ML задач.

*   **GitHub:** [juicedata/juicefs-csi-driver](https://github.com/juicedata/juicefs-csi-driver)
*   **Преимущества:** Полная POSIX-совместимость, атомарные операции, кэширование на локальных дисках нод.

#### Пример установки JuiceFS
```bash
helm upgrade --install juicefs-csi-driver juicefs-csi-driver/juicefs-csi-driver \
  --namespace kube-system \
  --set storageClasses[0].name=juicefs-s3 \
  --set storageClasses[0].backend.type=s3 \
  --set storageClasses[0].backend.name=my-bucket \
  --set storageClasses[0].backend.metaurl=redis://redis.storage.svc.cluster.local:6379/1
```

### 4. ctrox/csi-s3 (DEPRECATED)
> [!WARNING]
> Проект **архивирован** и не поддерживается с 2025 года. Использование в продуктовых средах запрещено. Рекомендуется миграция на `yandex-cloud/k8s-csi-s3`.

---

## Практические сценарии

### Динамическое выделение ресурсов (Yandex/MinIO)

Пример `StorageClass` для драйвера Yandex Cloud:

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: s3-geesefs
provisioner: s3.csi.yandex.cloud
parameters:
  mounter: geesefs
  options: "--max-flush-interval 5 --dir-mode 0777 --file-mode 0666"
  bucket: "" # Если пусто, бакет будет создан автоматически
```

### Использование S3 в Поде (PVC)

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: s3-pvc
spec:
  accessModes:
    - ReadWriteMany # S3 по своей природе RWX
  resources:
    requests:
      storage: 50Gi
  storageClassName: s3-geesefs
```

---

## Сравнение производительности и лимитов

| Характеристика | AWS Mountpoint | Yandex (GeeseFS) | JuiceFS |
| :--- | :--- | :--- | :--- |
| **POSIX-совместимость** | Низкая | Средняя | **Полная** |
| **Dynamic Provisioning** | Нет | **Да** | **Да** |
| **Производительность (Small Files)** | Низкая | Средняя | **Высокая** |
| **Сценарии** | Big Data, Датасеты | CMS, Архивы | AI/ML, Shared Home |

---

## Диагностика и устранение проблем

1.  **Ошибка монтирования (Mount failed):**
    *   Проверьте наличие установленного `fuse` на рабочих узлах кластера.
    *   Убедитесь, что `endpoint` S3 доступен с узлов (проверка через `curl -I`).
2.  **Проблемы с правами (403 Forbidden):**
    *   Проверьте `Secret` с ключами доступа.
    *   Для AWS: проверьте IAM Role for Service Accounts (IRSA).
3.  **Низкая скорость:**
    *   Увеличьте количество параллельных потоков в параметрах маунтера (`--max-parallel-parts`).
    *   Настройте локальное кэширование метаданных.

---

## См. также
* [Обзор CSI](./csi_overview.md)
* [Сравнение CSI-драйверов](./csi_drivers_comparison.md)
* [Объектное хранилище (S3) — концепции](../../../Concepts/Storage/data_storage_overview.md)
* [Persistent Volumes и PVC в Kubernetes](../pv_and_pvc.md)
