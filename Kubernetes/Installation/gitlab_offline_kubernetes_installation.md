# Установка GitLab в закрытом контуре Kubernetes

Руководство по развертыванию GitLab в изолированной среде (air-gapped) с использованием локального реестра образов (Harbor) и объектного хранилища (MinIO).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Air-gapped (Закрытый контур)** | Изолированная сетевая среда, не имеющая прямого доступа к публичному интернету. |
| **OCI (Open Container Initiative)** | Стандарт для образов контейнеров и рантаймов. В контексте Helm позволяет хранить чарты в Docker-реестрах (например, Harbor). |
| **Object Storage (S3)** | Протокол и тип хранилища для неструктурированных данных (артефакты, LFS, бэкапы). В данном руководстве используется MinIO. |
| **Values-файл** | YAML-файл для переопределения параметров чарта при установке. |

---

## Основные концепции

### Двухэтапный процесс установки

Развертывание в изолированной среде состоит из двух фаз:

1. **Внешний контур (Интернет)**: подготовка артефактов. Скачивание Helm-чарта, определение списка необходимых образов, их загрузка и упаковка в архивы.
2. **Внутренний контур (Air-gapped)**: развертывание. Перенос архивов, импорт образов в локальный реестр (Harbor), публикация чарта и выполнение установки.

### Требования к инфраструктуре

Для успешной работы GitLab в закрытом контуре должны быть развернуты:

- **Kubernetes кластер**: версия 1.24+.
- **Локальный реестр**: Harbor (рекомендуется) или Nexus для хранения образов и Helm-чартов.
- **Объектное хранилище**: MinIO или Ceph для хранения артефактов CI/CD, LFS и бэкапов.
- **Persistent Storage**: StorageClass (NFS, Longhorn, Ceph) для базы данных и Git-репозиториев.

---

## Практические сценарии

### Подготовка артефактов (Внешний контур)

На машине с доступом в интернет необходимо скачать чарт и подготовить список образов.

```bash
# Добавление репозитория и скачивание чарта
helm repo add gitlab https://charts.gitlab.io
helm pull gitlab/gitlab --untar

# Генерация манифестов для извлечения имен образов
helm template gitlab ./gitlab -f minimal-values.yaml > rendered.yaml

# Получение уникального списка образов
grep -oE 'image:\s*"?[^"]+' rendered.yaml | sed -E 's/^image:\s*"?//; s/"$//' | sort -u > gitlab-images.txt
```

#### Загрузка и упаковка образов

Используйте скрипт для скачивания и тегирования образов для вашего Harbor:

```bash
export HARBOR="harbor.domain.local"
export PROJECT="gitlab"

cat gitlab-images.txt | while read img; do
  # Очистка имени от префикса публичного реестра
  cleaned=$(echo "$img" | sed -E 's#^(docker\.io|registry\.gitlab\.com|quay\.io|gcr\.io|ghcr\.io|registry\.k8s\.io)/##')
  new_tag="${HARBOR}/${PROJECT}/${cleaned}"
  
  docker pull "$img"
  docker tag "$img" "$new_tag"
  echo "$new_tag" >> images-to-save.txt
done

# Сохранение в архив и упаковка чарта
docker save -o gitlab-images.tar $(cat images-to-save.txt)
tar -czvf gitlab-helm-chart.tar.gz gitlab/
```

### Развертывание в изолированной среде

После переноса файлов во внутренний контур необходимо импортировать образы и опубликовать чарт.

#### Импорт в Harbor

```bash
# Загрузка в локальный Docker/Podman
docker load -i gitlab-images.tar

# Пуш в локальный реестр
docker login harbor.domain.local
cat images-to-save.txt | xargs -L 1 docker push

# Пуш Helm-чарта в OCI-репозиторий Harbor
helm push gitlab-helm-chart.tar.gz oci://harbor.domain.local/helm
```

### Конфигурация GitLab (values.yaml)

В закрытом контуре необходимо перенаправить все запросы образов на локальный реестр и настроить внешнее хранилище.

**Ключевые параметры конфигурации:**

```yaml
global:
  image:
    registry: harbor.domain.local # Глобальный реестр для всех образов
  hosts:
    domain: gitlab.local
  ingress:
    configureCertmanager: false # Cert-manager обычно не используется в оффлайне
  appConfig:
    object_store:
      enabled: true
      connection:
        secret: gitlab-s3-secret # Секрет с параметрами подключения к MinIO
```

### Настройка объектного хранилища MinIO

GitLab требует наличия бакетов для артефактов, бэкапов, LFS и загрузок.

**Создание секрета подключения в Kubernetes:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-s3-secret
  namespace: gitlab
stringData:
  config: |
    provider: AWS
    region: us-east-1
    endpoint: "http://minio.local"
    aws_access_key_id: "ACCESS_KEY"
    aws_secret_access_key: "SECRET_KEY"
    path_style: true
```

---

## Дополнительная информация

### Рекомендации по безопасности

- **Доверенные сертификаты**: Если Harbor или MinIO используют самоподписанные сертификаты, их необходимо добавить в секрет `gitlab-custom-ca` и указать в `global.certificates.customCAs`.
- **Обновление образов**: Процесс синхронизации образов должен быть регулярным для получения патчей безопасности.

### См. также

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Интеграция GitLab с Harbor](./k3s_dev_environment/gitlab_harbor_integration.md)
- [Обзор Harbor](../../Docker/Docker_registries/Harbor/overview.md)
