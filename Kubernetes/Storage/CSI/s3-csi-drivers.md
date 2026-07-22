# S3 CSI-драйверы в Kubernetes

S3 (Simple Storage Service) является объектным хранилищем, которое подходит для надежного и масштабируемого хранения данных большого объема. В Kubernetes S3 часто используется для приложений, требующих распределенного доступа к данным, хранения артефактов или резервных копий.

## Обзор CSI

**CSI (Container Storage Interface)** — это стандартный интерфейс, позволяющий Kubernetes взаимодействовать с различными системами хранения данных. Он унифицирует доступ и упрощает интеграцию внешних хранилищ в кластер.

### Основные компоненты CSI

Драйверы CSI состоят из компонентов, разрабатываемых сообществом Kubernetes и поставщиками хранилищ:

**Компоненты Kubernetes (Sidecars):**
*   **Driver registrar:** регистрирует CSI-драйверы в kubelet.
*   **External provisioner:** обрабатывает запросы на создание и удаление томов.
*   **External attacher:** управляет монтированием и размонтированием томов.

**Компоненты поставщика:**
*   **CSI Identity:** возвращает информацию о плагине.
*   **CSI Controller:** управляет жизненным циклом томов (create/delete).
*   **CSI Node:** управляет монтированием томов на конкретных узлах кластера.

---

## Подготовка инфраструктуры (IaC)

Для развертывания тестового стенда (кластер Managed Kubernetes и S3-хранилище) используется Terraform.

### Пример конфигурации провайдеров

```hcl
provider "helm" {
  kubernetes {
    host                   = module.mks.kube_config.server
    client_certificate     = base64decode(module.mks.kube_config.client_cert)
    client_key             = base64decode(module.mks.kube_config.client_key)
    cluster_ca_certificate = base64decode(module.mks.kube_config.cluster_ca_cert)
  }
}
```

### Основные ресурсы (Selectel)

Для работы с S3 в Managed Kubernetes необходимо создать:
1.  Проект и сервисного пользователя.
2.  S3-ключи доступа (Access Key / Secret Key).
3.  Кластер Kubernetes (MKS).

---

## Драйвер ctrox/csi-s3

Позволяет монтировать S3-контейнеры как файловые системы внутри подов.

*   **GitHub:** [ctrox/csi-s3](https://github.com/ctrox/csi-s3)
*   **Поддерживаемые маунтеры:** rclone, s3fs, goofys, s3backer.

### Установка (Helm/Terraform)

```hcl
resource "helm_release" "ctrox-csi-s3" {
  name             = "ctrox-csi-s3"
  repository       = "https://github.com/CloudVE/helm-charts/raw/master"
  chart            = "ctrox-csi-s3"
  namespace        = "ctrox-csi-s3"
  create_namespace = true

  values = [
    <<-EOT
      secret:
        create: true
        accessKey: ${module.s3-creds.s3_credentials_access_key}
        secretKey: ${module.s3-creds.s3_credentials_secret_key}
        endpoint: "https://s3.storage.selcloud.ru"
      storageClass:
        mounter: goofys
    EOT
  ]
}
```

> **Важно:** После установки может потребоваться обновление ClusterRole `external-attacher-runner` для добавления прав на `volumeattachments/status`.

---

## Драйвер yandex-cloud/k8s-csi-s3

Является форком `ctrox/csi-s3` с добавлением оптимизированного маунтера **GeeseFS**.

*   **GitHub:** [yandex-cloud/k8s-csi-s3](https://github.com/yandex-cloud/k8s-csi-s3)
*   **Ключевая особенность:** GeeseFS (основан на Goofys) минимизирует количество операций API, поддерживает частичное изменение и дозапись объектов.

### Установка

```hcl
resource "helm_release" "yandex-csi-s3" {
  name             = "yandex-csi-s3"
  chart            = "./yandex-csi-s3/deploy/helm/csi-s3"
  namespace        = "yandex-csi-s3"
  create_namespace = true

  values = [
    <<-EOT
      secret:
        accessKey: "${module.s3-creds.s3_credentials_access_key}"
        secretKey: "${module.s3-creds.s3_credentials_secret_key}"
        endpoint: "https://s3.storage.selcloud.ru"
        region: "ru-1"
    EOT
  ]
}
```

---

## Сравнение производительности (fio)

Результаты тестирования с использованием блока 4k (IOPS и задержка могут варьироваться от условий сети).

| Решение (Маунтер) | Операция | Пропускная способность (BW) | Средняя задержка (avg clat) | Пиковая задержка (max clat) |
| :--- | :--- | :--- | :--- | :--- |
| **ctrox/csi-s3 (Goofys)** | Чтение | 355 MiB/s | 10.24 мкс | 300.55 мс |
| **ctrox/csi-s3 (Goofys)** | Запись | 44.1 MiB/s | 87.78 мкс | 121.54 мс |
| **yandex-csi-s3 (GeeseFS)** | Чтение | 446 MiB/s | 8.04 мкс | 16.91 мс |
| **yandex-csi-s3 (GeeseFS)** | Запись | 24.7 MiB/s | 157.36 мкс | 8.98 мс |

### Анализ результатов
1.  **GeeseFS** значительно быстрее в операциях чтения и показывает более стабильную (низкую) пиковую задержку.
2.  **Goofys** в данном тесте показал лучшую пропускную способность на запись, но с более высокой вариативностью задержек.

---

## Практические рекомендации

1.  **Выбор маунтера:**
    *   `GeeseFS` — рекомендуется для высокопроизводительного чтения и работы с большими файлами.
    *   `Goofys` — хороший баланс, если GeeseFS не доступен или не совместим.
    *   `s3fs` — если требуется полная совместимость с POSIX (но с потерей производительности).
2.  **Тип данных:** S3 CSI лучше всего подходит для Read-Heavy нагрузок (статичный контент, медиа) или долгосрочного хранения. Для баз данных с интенсивной записью следует использовать блочные хранилища.
3.  **Безопасность:** Ключи доступа в Kubernetes Secrets должны быть защищены (RBAC, шифрование etcd или использование External Secrets/Vault).

---

## См. также
* [Обзор CSI](./csi_overview.md)
* [Сравнение CSI-драйверов](./csi_drivers_comparison.md)
* [Объектное хранилище (S3) — концепции](../../../Concepts/Storage/data_storage_overview.md)
