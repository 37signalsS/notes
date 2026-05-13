# Установка GitLab в закрытом контуре Kubernetes

Руководство по развертыванию GitLab в изолированной среде (air-gapped) с использованием локального реестра образов (Harbor) и объектного хранилища (MinIO).

---

## Определения

| Термин | Описание |
|--------|----------|
| **Air-gapped (Закрытый контур)** | Изолированная сетевая среда, не имеющая прямого доступа к публичному интернету. |
| **OCI (Open Container Initiative)** | Стандарт для образов контейнеров и рантаймов. В контексте Helm позволяет хранить чарты в Docker-реестрах (например, Harbor). |
| **Object Storage (S3)** | Протокол и тип хранилища для неструктурированных данных (артефакты, LFS, бэкапы). В данном руководстве используется MinIO. |
| **Values-файл** | YAML-файл с конфигурацией параметров Helm-чарта. |

**Навигация:** [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md) | [Интеграция с Harbor](./k3s_dev_environment/gitlab_harbor_integration.md)

---

## Основные концепции

Установка в закрытом контуре разделена на два этапа:

1. **Внешний контур (с доступом в интернет):** подготовка артефактов, скачивание Helm-чарта, сбор списка образов и их архивация.
2. **Внутренний контур (без интернета):** загрузка образов в локальный реестр, пуш чарта и выполнение установки через Helm.

### Требования

**Внешний контур:**

- Docker
- Helm

**Закрытый контур:**

- Kubernetes кластер
- Docker или Nerdctl
- Helm
- Локальный реестр (Harbor или Nexus)
- Объектное хранилище (MinIO или Ceph)
- Система хранения (Longhorn или NFS)

---

## Практические сценарии

### 1. Подготовка артефактов (Внешний контур)

Сначала необходимо добавить репозиторий и скачать чарт:

```bash
helm repo add gitlab https://charts.gitlab.io
helm repo update
helm pull gitlab/gitlab --untar
```

Создайте тестовый `values.yaml` для генерации списка необходимых образов:

```yaml
# values.yaml
global:
  edition: ce
  hosts:
    domain: k8s.domain.local
    gitlab:
      name: gitlab.k8s.domain.local
  ingress:
    enabled: true
    configureCertmanager: false
    provider: nginx
    class: nginx
    tls:
      enabled: false
  registry:
    enabled: false
  minio:
    enabled: false
gitlab-runner:
  install: false
prometheus:
  install: false
grafana:
  enabled: false
```

Сгенерируйте список образов:

```bash
helm template gitlab ./gitlab -f values.yaml > rendered.yaml

# Выгрузка уникальных имен образов в файл
grep -oE 'image:\s*"?[^"]+' rendered.yaml | sed -E 's/^image:\s*"?//; s/"$//' | sort -u > git-images.txt
```

#### Загрузка и тегирование образов

Настройте переменные для вашего локального реестра:

```bash
export HARBOR="harbor.domain.local"
export PROJECT="gitlab"
```

Скрипт для скачивания и подготовки образов для Harbor:

```bash
cat git-images.txt | tr -d '\r' | while IFS= read -r img; do
  img="$(echo "$img" | tr -d '"' | xargs)"
  [ -z "$img" ] && continue

  # Удаление префиксов публичных реестров
  cleaned="$(echo "$img" | sed -E 's#^(docker\.io|registry\.gitlab\.com|quay\.io|gcr\.io|ghcr\.io|registry\.k8s\.io)/##')"
  new="${HARBOR}/${PROJECT}/${cleaned}"
  
  echo "PULL  $img"
  sudo docker pull "$img"
  
  echo "TAG   $img -> $new"
  sudo docker tag "$img" "$new"
done
```

Сохраните образы в архив для переноса:

```bash
# Формирование списка новых имен
cat git-images.txt | tr -d '\r' | while IFS= read -r img; do
  img="$(echo "$img" | tr -d '"' | xargs)"
  [ -z "$img" ] && continue
  cleaned="$(echo "$img" | sed -E 's#^(docker\.io|registry\.gitlab\.com|quay\.io|gcr\.io|ghcr\.io|registry\.k8s\.io)/##')"
  echo "${HARBOR}/${PROJECT}/${cleaned}"
done | sort -u > harbor-images.txt

# Сохранение в tar-архив
sudo docker save -o gitlab-harbor-images.tar $(cat harbor-images.txt)

# Упаковка чарта
tar -cvf gitlab-helm.tgz gitlab 
```

### 2. Развертывание в закрытом контуре

Перенесите файлы `harbor-images.txt`, `gitlab-harbor-images.tar` и `gitlab-helm.tgz` на сервер в закрытом контуре.

#### Импорт образов в Harbor

```bash
# Загрузка образов в локальный Docker
sudo docker load -i gitlab-harbor-images.tar

# Логин и пуш в Harbor
docker login ${HARBOR}

cat harbor-images.txt | tr -d '\r' | while IFS= read -r img; do
  img="$(echo "$img" | tr -d '"' | xargs)"
  [ -z "$img" ] && continue
  echo "PUSH $img"
  sudo docker push "$img"
done
```

#### Пуш Helm-чарта

Для использования OCI-репозитория в Harbor создайте проект `helm` и выполните пуш:

```bash
helm push gitlab-helm.tgz oci://harbor.domain.local/helm
```

### 3. Конфигурация Helm (values.yaml)

При установке необходимо переопределить пути к образам на локальный реестр и настроить интеграцию с внешними сервисами (S3, DB).

```yaml
# production-values.yaml
installCertmanager: false
nginx-ingress:
  enabled: false
gitlab-runner:
  install: false
prometheus:
  install: false
grafana:
  install: false

global:
  edition: ce
  hosts:
    domain: k8s.domain.local
    https: false
    gitlab:
      name: gitlab.k8s.domain.local
  image:
    registry: harbor.domain.local
  ingress:
    enabled: true
    configureCertmanager: false
    class: nginx
    tls:
      enabled: false
    annotations:
      kubernetes.io/ingress.class: nginx
  certificates:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/certificates
      tag: "v18.8.4"
    customCAs:
      - secret: gitlab-ca
  kubectl:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/kubectl
      tag: "v18.8.4"
  gitlabBase:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/gitlab-base
      tag: "v18.8.4"
  registry:
    enabled: false
  minio:
    enabled: false
  appConfig:
    object_store:
      enabled: true
      connection:
        secret: gitlab-storage
        key: config
    artifacts:
      enabled: true
      bucket: gitlab-artifacts
    lfs:
      enabled: true
      bucket: gitlab-lfs
    uploads:
      enabled: true
      bucket: gitlab-uploads
    packages:
      enabled: true
      bucket: gitlab-packages
    backups:
      bucket: gitlab-backups
      tmpBucket: tmp

gitlab:
  toolbox:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/gitlab-toolbox-ce
      tag: "v18.8.4"
    backups:
      objectStorage:
        config:
          secret: s3-credentials
          key: config
  webservice:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/gitlab-webservice-ce
    workhorse:
      image: harbor.domain.local/gitlab/gitlab-org/build/cng/gitlab-workhorse-ce
  migrations:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/gitlab-toolbox-ce
      tag: "v18.8.4"
  gitaly:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/gitaly
      tag: "v18.8.4"
    persistence:
      size: 20Gi
      storageClass: longhorn
  kas:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/gitlab-kas
      tag: "v18.8.4"
  sidekiq:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/gitlab-sidekiq-ce
  gitlab-shell:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/gitlab-shell
  gitlab-exporter:
    image:
      repository: harbor.domain.local/gitlab/gitlab-org/build/cng/gitlab-exporter

registry:
  enabled: false

redis:
  image:
    registry: harbor.domain.local
    repository: gitlab/bitnamilegacy/redis
  metrics:
    image:
      registry: harbor.domain.local
      repository: gitlab/bitnamilegacy/redis-exporter

postgresql:
  image:
    registry: harbor.domain.local
    repository: gitlab/bitnamilegacy/postgresql
  metrics:
    image:
      registry: harbor.domain.local
      repository: gitlab/bitnamilegacy/postgresql-exporter
```

> **Важно:** Для доверия к самоподписанным сертификатам (например, MinIO) необходимо добавить корневой CA в секрет:
> `kubectl -n gitlab create secret generic gitlab-ca --from-file=root-ca.crt=/path/to/root-ca.crt`

### 4. Настройка Object Storage (MinIO)

GitLab требует наличия бакетов для различных типов данных. Создайте следующие бакеты в MinIO:

- `gitlab-artifacts`
- `gitlab-backups`
- `gitlab-lfs`
- `gitlab-registry` (если включен)
- `gitlab-uploads`

#### Политика доступа (IAM Policy)

Создайте политику `gitlab` в MinIO:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:ListBucket"],
            "Resource": [
                "arn:aws:s3:::gitlab-artifacts",
                "arn:aws:s3:::gitlab-backups",
                "arn:aws:s3:::gitlab-lfs",
                "arn:aws:s3:::gitlab-uploads"
            ]
        },
        {
            "Effect": "Allow",
            "Action": ["s3:DeleteObject", "s3:GetObject", "s3:PutObject"],
            "Resource": [
                "arn:aws:s3:::gitlab-artifacts/*",
                "arn:aws:s3:::gitlab-backups/*",
                "arn:aws:s3:::gitlab-lfs/*",
                "arn:aws:s3:::gitlab-uploads/*"
            ]
        }
    ]
}
```

#### Создание секретов в Kubernetes

Создайте секрет `gitlab-storage` для основного приложения:

```yaml
# minio-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-storage
  namespace: gitlab
type: Opaque
stringData:
  config: |
    provider: AWS
    region: us-east-1
    endpoint: "https://s3.minio.domain.local"
    path_style: true
    aws_access_key_id: YOUR_ACCESS_KEY
    aws_secret_access_key: "YOUR_SECRET_KEY"
```

И секрет `s3-credentials` для бэкапов:

```yaml
# s3-gitlab.yaml
apiVersion: v1
kind: Secret
metadata:
  name: s3-credentials
  namespace: gitlab
type: Opaque
stringData:
  config: |
    s3:
      bucket: gitlab-registry-storage
      accesskey: YOUR_ACCESS_KEY
      secretkey: "YOUR_SECRET_KEY"
      region: us-east-1
      regionendpoint: "https://s3.minio.domain.local"
      v4auth: true
```

### 5. Запуск установки

```bash
kubectl create ns gitlab
kubectl apply -f minio-secret.yaml -f s3-gitlab.yaml

helm install gitlab oci://harbor.domain.local/helm/gitlab -n gitlab -f production-values.yaml
```

#### Проверка и получение пароля

```bash
# Проверка подов
kubectl get pods -n gitlab

# Получение начального пароля root
kubectl get secret -n gitlab gitlab-gitlab-initial-root-password -o jsonpath="{.data.password}" | base64 -d
```

---

## Дополнительная информация

- **[Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)** — общие сведения о параметрах и траблшутинге.
- **[Интеграция GitLab с Harbor](./k3s_dev_environment/gitlab_harbor_integration.md)** — настройка внешнего реестра.
- **[Harbor Overview](../../Docker/Docker_registries/Harbor/overview.md)** — обзор локального реестра образов.
