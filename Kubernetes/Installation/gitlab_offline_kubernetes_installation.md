# Установка GitLab в закрытом контуре Kubernetes

Руководство по развертыванию, настройке и поддержке платформы GitLab в изолированных средах (air-gapped) с использованием локальных реестров и объектных хранилищ.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Air-gapped (Закрытый контур)** | Изолированная сетевая среда, не имеющая прямого доступа к публичному интернету. Требует пре-стейджинга всех зависимостей и их физического переноса (USB, SCP, выделенные шлюзы). |
| **OCI (Open Container Initiative)** | Стандарт для образов и артефактов. Позволяет хранить Docker-образы, Helm-чарты и другие артефакты в Docker-реестрах в едином формате. |
| **Private CA (Локальный УЦ)** | Центр сертификации, выпускающий сертификаты для внутренних сервисов (Harbor, MinIO, GitLab). Корневой ключ хранится на air-gapped системе. |
| **Helper Image** | Вспомогательный образ GitLab Runner (`gitlab-runner-helper`), используемый для служебных операций (кэширование, артефакты, клонирование) в Kubernetes. В оффлайн-среде必须指向 локальный реестр. |
| **KAS (Kubernetes Agent Server)** | Компонент GitLab для связи с кластерами через GitLab Agent. В оффлайн-режиме требует настройки внутренних адресов и TLS-сертификатов. |
| **Pre-staging (Пре-стейджинг)** | Процесс подготовки и переноса всех зависимостей из открытого контура в закрытый до начала развертывания. Включает загрузку, упаковку, физическую передачу и импорт в локальный реестр. |
| **Offline Bundle (Установочный бандл)** | Архивированная совокупность всех артефактов (образы, бинарники, чарты), упакованная для переноса в закрытый контур. Формируется на узле с доступом в интернет. |
| **Registry Mirror (Зеркало реестра)** | Локальная копия публичного реестра (Docker Hub, registry.gitlab.com), доступная из закрытого контура. Единственный источник образов для Kubernetes-кластера. |
| **Helm Chart Repository** | Хранилище Helm-чартов, доступное из закрытого контура. В air-gapped среде чарты публикуются в Harbor (OCI-репозиторий) или в специализированный ChartMuseum/ChartMuseum. |
| **skopeo / crane** | Утилиты для копирования OCI-артефактов между реестрами без pull на локальную машину. Идеальны для air-gapped переноса: `skopeo copy docker://... docker://...` |
| **Quay / Nexus** | Альтернативы Harbor для хранения OCI-артефактов в закрытом контуре. Quay专注于 безопасность; Nexus поддерживает Maven/PyPI/Docker. |
| **Podman / nerdctl** | Альтернативы Docker Daemon для управления контейнерами. Podman не требует root-привилегий; nerdctl работает через containerd. Оба поддерживают `podman save/load`. |
| **containerd / CRI** | Container Runtime Interface — стандарт взаимодействия kubelet с container runtime. containerd является основным runtime для Kubernetes 1.24+. |
| **Image Pull Policy** | Политика загрузки образов (`Always`, `IfNotPresent`, `Never`). В air-gapped среде必须使用 `IfNotPresent` или `Never` с предварительно загруженными образами. |
| **kubeadm** | Утилита для инициализации и управления кластером Kubernetes. В air-gapped среде требует предварительной загрузки всех зависимостей. |
| **etcd** | Распределённое хранилище ключ-значений, являющееся «мозгом» Kubernetes. В air-gapped среде必须确保 доступность и резервного копирования. |
| **CoreDNS** | DNS-сервер кластера, обеспечивающий разрешение имён сервисов. В закрытом контуре必须настроить forwarding на локальный DNS-сервер. |

---

## Основные концепции

### Архитектура оффлайн-развертывания

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ОТКРЫТЫЙ КОНТУР (INET)                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │   pc-inet    │    │   GitLab     │    │  Docker Hub  │              │
│  │  192.168.1.99│    │ registry.gitlab│   │  quay.io     │              │
│  └──────┬───────┘    └──────────────┘    └──────────────┘              │
│         │                                                               │
│         │  1. Загрузка артефактов (skopeo/crane/helm)                   │
│         │  2. Упаковка в bundle (tar.gz)                               │
└─────────┼───────────────────────────────────────────────────────────────┘
          │
          │  Физический перенос (USB / SCP / выделенный шлюз)
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     ЗАКРЫТЫЙ КОНТУР (AIR-GAPPED)                       │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │    Harbor    │◄───│   GitLab     │    │    MinIO     │              │
│  │ harbor.local │    │ gitlab.local │    │ minio.local  │              │
│  └──────┬───────┘    └──────┬───────┘    └──────────────┘              │
│         │                   │                                           │
│         │ 3. Импорт         │ 5. Pull образов                          │
│         │    образов        │    (internal DNS)                        │
│         ▼                   ▼                                           │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │  Kubernetes  │◄───│  GitLab      │    │  CoreDNS     │              │
│  │   Cluster    │    │  Runner      │    │ (forwarding) │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
└─────────────────────────────────────────────────────────────────────────┘
```

### Стратегия оффлайн-развертывания

Установка в закрытом контуре требует предварительной подготовки всех зависимостей во внешнем контуре (с доступом в интернет) и их последующего переноса. Ключевые аспекты:
1. **Зеркалирование образов:** Все образы (более 20 компонентов) должны быть перенесены в локальный Harbor. Используйте `skopeo copy` или `crane copy` для копирования без pull.
2. **Управление доверием:** Все компоненты системы должны доверять корневому сертификату Private CA. Сертификат必须安装 на всех узлах кластера.
3. **Локальные зависимости:** Отключение функций, требующих внешних вызовов (Gravatar, Google Analytics, встроенный cert-manager для публичных доменов).
4. **DNS-резолвинг:** Все внутренние сервисы必须 быть доступны по DNS-именам. CoreDNS必须转发 запросы на локальный DNS-сервер.
5. **Image Pull Policy:** В air-gapped среде必须使用 `IfNotPresent` или `Never` с предварительно загруженными образами.

### Жизненный цикл развёртывания

```
Этап 1: Открытый контур (INET)
  ├─ 1.1. Загрузка Helm-чарта GitLab
  ├─ 1.2. Рендеринг шаблонов (helm template)
  ├─ 1.3. Извлечение списка образов (grep image: rendered.yaml)
  ├─ 1.4. Зеркалирование образов (skopeo/crane copy)
  ├─ 1.5. Упаковка в bundle (tar.gz)
  └─ 1.6. Проверка целостности (sha256sum)

Этап 2: Перенос
  ├─ 2.1. Копирование bundle на носитель (USB/SCP)
  └─ 2.2. Проверка на целевом узле (sha256sum -c)

Этап 3: Закрытый контур
  ├─ 3.1. Распаковка bundle
  ├─ 3.2. Импорт образов в Harbor
  ├─ 3.3. Импорт чартов в Harbor (OCI)
  ├─ 3.4. Настройка DNS (CoreDNS forwarding)
  ├─ 3.5. Настройка TLS-сертификатов
  ├─ 3.6. Конфигурация values.yaml
  └─ 3.7. Установка через Helm (helm upgrade --install)
```

### Требования к инфраструктуре

| Компонент | Минимум | Рекомендуется | Роль в оффлайн-схеме |
| :--- | :--- | :--- | :--- |
| **Harbor** | 2 vCPU, 4 GB RAM, 100 GB | 4 vCPU, 8 GB RAM, 500 GB | Хранение Docker-образов и Helm-чартов. Единый источник OCI-артефактов. |
| **MinIO** | 2 vCPU, 4 GB RAM, 100 GB | 4 vCPU, 8 GB RAM, 500+ GB | S3-совместимое хранилище для LFS, артефактов и бэкапов GitLab. |
| **Локальный DNS** | 1 vCPU, 1 GB RAM | 2 vCPU, 2 GB RAM (HA) | Резолвинг имен внутренних сервисов внутри кластера и для клиентов. BIND/dnsmasq/CoreDNS. |
| **GitLab Server** | 4 vCPU, 8 GB RAM, 200 GB | 8 vCPU, 16 GB RAM, 500 GB | Платформа GitLab (Webservice, Sidekiq, Gitaly, Registry). |
| **Kubernetes Cluster** | 3 master + 3 worker | 3 master + 5+ worker | Кластер для запуска всех компонентов. kubeadm/K3s/RKE2. |

### Сетевая топология в закрытом контуре

```text
Internet ──X── Firewall ──X── Закрытый контур
                              │
                    ┌─────────┴─────────┐
                    │    VLAN / Subnet   │
                    │  10.0.100.0/24     │
                    └─────────┬─────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   ┌────┴────┐          ┌────┴────┐          ┌────┴────┐
   │ master-1│          │ master-2│          │ master-3│
   │ .101    │          │ .102    │          │ .103    │
   └────┬────┘          └────┬────┘          └────┬────┘
        │                     │                     │
   ┌────┴────┐          ┌────┴────┐          ┌────┴────┐
   │ worker-1│          │ worker-2│          │ worker-3│
   │ .201    │          │ .202    │          │ .203    │
   └────┬────┘          └────┬────┘          └────┬────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │  harbor.local     │
                    │  gitlab.local     │
                    │  minio.local      │
                    │  dns.local        │
                    └───────────────────┘
```

### Настройка DNS в закрытом контуре

CoreDNS必须转发 все запросы на локальный DNS-сервер:

```yaml
# custom-coredns.yaml (Kubernetes ConfigMap)
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns-custom
  namespace: kube-system
data:
  custom.server: |
    forward . dns.local {
      health_check 5s
    }
```

Или через `Corefile`:

```yaml
# Corefile override
.53 {
    errors
    health
    kubernetes cluster.local in-addr.arpa ip6.arpa {
        pods insecure
        fallthrough in-addr.arpa ip6.arpa
    }
    forward . 10.0.100.10  # Локальный DNS-сервер
    cache 30
    loop
    reload
    loadbalance
}
```

### Настройка доверия (Custom CA)

Если Harbor или MinIO используют сертификаты от локального УЦ, GitLab должен им доверять. Полный цепочка:

1. **Корневой сертификат** (Root CA) — хранится на air-gapped системе
2. **Промежуточный сертификат** (Intermediate CA) — выпускает сертификаты для сервисов
3. **Сервисные сертификаты** — Harbor, MinIO, GitLab, Ingress

**Процесс установки:**

```bash
# 1. Создание секрета с корневым сертификатом
kubectl create secret generic gitlab-custom-ca \
  --from-file=ca.crt=/path/to/root-ca.crt \
  -n gitlab

# 2. Проверка наличия секрета
kubectl get secret gitlab-custom-ca -n gitlab -o yaml
```

```yaml
# values.yaml — доверие к Custom CA
global:
  certificates:
    customCAs:
      - secret: gitlab-custom-ca
        key: ca.crt
```

> **Важно:** Сертификат必须 быть установлен также на уровне ОС на всех узлах кластера (см. раздел "Решение проблем").

### Зеркалирование образов (Image Mirroring)

Для air-gapped сред используются три основных стратегии:

**1. skopeo (рекомендуется):**
```bash
# Копирование без pull на локальную машину
skopeo copy docker://registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ee:v17.2.0 \
  docker://harbor.local/gitlab/gitlab-webservice-ee:v17.2.0

# Массовое копирование из списка
while IFS= read -r img; do
  skopeo copy "docker://$img" "docker://harbor.local/$(echo $img | sed 's|registry.gitlab.com/|gitlab/|')"
done < images.txt
```

**2. crane:**
```bash
# Копирование образа
crane copy registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ee:v17.2.0 \
  harbor.local/gitlab/gitlab-webservice-ee:v17.2.0

# Просмотр манифеста (для проверки)
crane manifest harbor.local/gitlab/gitlab-webservice-ee:v17.2.0
```

**3. docker save/load (классический):**
```bash
# На машине с интернетом
docker pull registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ee:v17.2.0
docker save registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ee:v17.2.0 \
  | gzip > gitlab-webservice-ee-v17.2.0.tar.gz

# Перенос на целевой узел
scp gitlab-webservice-ee-v17.2.0.tar.gz root@master-1:/tmp/

# На целевом узле
docker load < gitlab-webservice-ee-v17.2.0.tar.gz
docker tag registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ee:v17.2.0 \
  harbor.local/gitlab/gitlab-webservice-ee:v17.2.0
docker push harbor.local/gitlab/gitlab-webservice-ee:v17.2.0
```

### Объектное хранилище (MinIO)

GitLab требует настройки подключения к S3-совместимому хранилищу для всех типов данных. MinIO является рекомендуемым решением для on-prem сред.

**Компоненты, использующие MinIO:**
- **LFS (Large File Storage):** большие файлы (>10 MB по умолчанию)
- **Artifacts:** результаты выполнения задач CI/CD
- **Backups:** бэкапы GitLab (db.dump + repositories.tar.gz)
- **Uploads:** аватары, файлы в Issues/MRs
- **Packages:** встроенный реестр пакетов

**Настройка bucket'ов:**

```bash
# Установка mc (MinIO Client)
wget https://dl.min.io/client/mc/release/linux-amd64/mc
chmod +x mc && mv mc /usr/local/bin/

# Конфигурация подключения
mc alias set gitlab-minio https://minio.local MINIO_ACCESS_KEY MINIO_SECRET_KEY

# Создание bucket'ов для GitLab
mc mb gitlab-minio/gitlab-lfs
mc mb gitlab-minio/gitlab-artifacts
mc mb gitlab-minio/gitlab-backups
mc mb gitlab-minio/gitlab-uploads
mc mb gitlab-minio/gitlab-packages
mc mb gitlab-minio/gitlab-registry

# Настройка политики доступа (рекомендуется отдельный пользователь)
mc admin user add gitlab-minio gitlab_ci STRONG_PASSWORD
mc admin policy create gitlab-minio gitlab-ci-policy /path/to/policy.json
mc admin policy attach gitlab-minio gitlab-ci-policy --user gitlab_ci
```

**Пример политики доступа (policy.json):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::gitlab-*",
        "arn:aws:s3:::gitlab-*/*"
      ]
    }
  ]
}
```

### Полная конфигурация values.yaml для оффлайн-среды

```yaml
# values.yaml — GitLab в air-gapped среде
global:
  hosts:
    domain: gitlab.local
    https: true
    externalIP: 10.0.100.50
    ssh:
      enabled: true
  ingress:
    configureCertmanager: false
    tls:
      enabled: true
      secretName: gitlab-tls
  certificates:
    customCAs:
      - secret: gitlab-custom-ca
        key: ca.crt
  appConfig:
    gravatar:
      enabled: false
    gitlab_kas:
      externalUrl: wss://kas.gitlab.local
  pages:
    enabled: false

certmanager:
  install: false

prometheus:
  install: false

gitlab-runner:
  install: false

registry:
  hpa:
    minReplicas: 1
    maxReplicas: 1
  enabled: true

minio:
  install: true
  accessKey: "MINIO_ACCESS_KEY"
  secretKey: "MINIO_SECRET_KEY"
  persistence:
    size: 100Gi

postgresql:
  persistence:
    size: 50Gi

gitaly:
  persistence:
    size: 100Gi
```

---

## Практические сценарии

### 1. Подготовка артефактов (Внешний контур)

На машине с доступом в интернет скачайте чарт и извлеките список образов:

```bash
# Добавление репозитория и скачивание чарта
helm repo add gitlab https://charts.gitlab.io
helm repo update
helm pull gitlab/gitlab --untar

# Генерация списка всех образов из чарта
helm template gitlab ./gitlab --set global.hosts.domain=local > rendered.yaml
grep -oE 'image:\s*"?[^"]+' rendered.yaml | sed -E 's/^image:\s*"?//; s/"$//' | sort -u > images.txt

# Просмотр количества образов
wc -l images.txt
# → 42 (пример)
```

> **Важно:** Список образов зависит от включенных компонентов. Отключение Prometheus, cert-manager и GitLab Runner уменьшает список на 10-15 образов.

### 2. Перенос и импорт образов (Внутренний контур)

После переноса архивов импортируйте их в Harbor. Рекомендуется сохранять иерархию репозиториев для упрощения `values.yaml`.

```bash
# Пример тегирования и пуша (автоматизируйте через скрипт)
docker tag registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ee:v17.2.0 \
  harbor.local/gitlab/gitlab-webservice-ee:v17.2.0
docker push harbor.local/gitlab/gitlab-webservice-ee:v17.2.0
```

**Автоматизированный скрипт импорта:**

```bash
#!/bin/bash
# import_images.sh — массовый импорт образов в Harbor
HARBOR_URL="harbor.local"
PROJECT="gitlab"
IMAGES_FILE="images.txt"

while IFS= read -r img; do
  # Формирование имени в Harbor
  harbor_img="${HARBOR_URL}/${PROJECT}/$(basename $img)"

  echo "[+] Импорт: $img → $harbor_img"
  docker tag "$img" "$harbor_img"
  docker push "$harbor_img"
done < "$IMAGES_FILE"
```

### 3. Настройка Helm-репозитория в Harbor (OCI)

Вместо использования файлового сервера для Helm-чартов, публикуйте их в Harbor как OCI-артефакты:

```bash
# Включение OCI-поддержки в Harbor (если не включена)
# Settings → Configuration → Proxy Cache → OCI Support

# Логин в Harbor
helm registry login harbor.local -u admin -p Harbor@123

# Пуш чарта GitLab в Harbor
helm package gitlab  # Создаёт gitlab-7.3.2.tgz
helm push gitlab-7.3.2.tgz oci://harbor.local/gitlab-charts

# Установка из OCI-репозитория
helm upgrade --install gitlab oci://harbor.local/gitlab-charts/gitlab \
  --version 7.3.2 \
  --namespace gitlab \
  -f values.yaml
```

### 4. Конфигурация Runner и KAS в оффлайне

Раннеру необходим доступ к вспомогательному образу (`helper image`) в локальном реестре.

```yaml
# values.yaml (секция gitlab-runner)
gitlab-runner:
  runners:
    config: |
      [[runners]]
        [runners.kubernetes]
          helper_image = "harbor.local/gitlab/gitlab-runner-helper:x86_64-v17.2.0"
          allowed_images = ["harbor.local/gitlab/*", "alpine:3.*"]
```

Для KAS укажите внутренний адрес, доступный для агентов:
```yaml
global:
  appConfig:
    gitlab_kas:
      externalUrl: wss://kas.gitlab.local
```

### 5. Объектное хранилище (MinIO)

GitLab требует настройки подключения к S3-совместимому хранилищу для всех типов данных.

**Пример секрета `gitlab-s3-secret`:**
```yaml
provider: AWS
region: us-east-1
endpoint: "https://minio.local"
aws_access_key_id: "ADMIN"
aws_secret_access_key: "STRONG_PASSWORD"
path_style: true
```

**Создание секрета через kubectl:**

```bash
kubectl create secret generic gitlab-s3-secret \
  --from-literal=provider=AWS \
  --from-literal=region=us-east-1 \
  --from-literal=endpoint="https://minio.local" \
  --from-literal=aws_access_key_id="ADMIN" \
  --from-literal=aws_secret_access_key="STRONG_PASSWORD" \
  --from-literal=path_style=true \
  -n gitlab
```

### 6. Установка Harbor в air-gapped среде

**Внешний контур (загрузка):**

```bash
# Скачивание оффлайн-установщика Harbor
wget https://github.com/goharbor/harbor/releases/download/v2.10.0/harbor-offline-installer-v2.10.0.tgz
tar xzf harbor-offline-installer-v2.10.0.tgz
cd harbor

# Редактирование harbor.yml
cp harbor.yml.tmpl harbor.yml
```

```yaml
# harbor.yml — основные параметры
hostname: harbor.local
http:
  port: 80
https:
  port: 443
  certificate: /path/to/harbor.crt
  private_key: /path/to/harbor.key
harbor_admin_password: Harbor@123
database:
  password: root123
  max_idle_conns: 100
  max_open_conns: 900
data_volume: /data/harbor
storage:
  filesystem:
    maxthreads: 100
```

```bash
# Упаковка для переноса
tar czf harbor-bundle-v2.10.0.tar.gz harbor/
```

**Внутренний контур (установка):**

```bash
# Распаковка
tar xzf harbor-bundle-v2.10.0.tar.gz
cd harbor

# Установка
./install.sh --with-trivy

# Проверка
docker compose ps
# → harbor-core, harbor-jobservice, harbor-portal, nginx, postgresql, redis, registry, trivy-adapter
```

### 7. Установка MinIO в air-gapped среде

**Внешний контур:**

```bash
# Скачивание MinIO Server и Client
wget https://dl.min.io/server/minio/release/linux-amd64/minio
wget https://dl.min.io/client/mc/release/linux-amd64/mc
chmod +x minio mc

# Упаковка
tar czf minio-bundle.tar.gz minio mc
```

**Внутренний контур:**

```bash
# Распаковка
tar xzf minio-bundle.tar.gz
mv minio mc /usr/local/bin/

# Создание директории данных
mkdir -p /data/minio

# Запуск MinIO (systemd)
cat > /etc/systemd/system/minio.service <<EOF
[Unit]
Description=MinIO
Documentation=https://docs.min.io
Wants=network-online.target
After=network-online.target

[Service]
User=minio
Group=minio
Environment="MINIO_ROOT_USER=ADMIN"
Environment="MINIO_ROOT_PASSWORD=STRONG_PASSWORD"
ExecStart=/usr/local/bin/minio server /data/minio --console-address ":9001"
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now minio

# Конфигурация mc
mc alias set local https://minio.local ADMIN STRONG_PASSWORD
mc mb local/gitlab-lfs
mc mb local/gitlab-artifacts
mc mb local/gitlab-backups
```

### 8. Настройка Image Pull Secrets для всех подов

В air-gapped среде必须настроить imagePullSecrets для доступа к Harbor:

```bash
# Создание секрета
kubectl create secret docker-registry harbor-registry-secret \
  --docker-server=harbor.local \
  --docker-username=robot_ci \
  --docker-password=<password> \
  -n gitlab

# Применение к default ServiceAccount
kubectl patch serviceaccount default -n gitlab \
  -p '{"imagePullSecrets": [{"name": "harbor-registry-secret"}]}'
```

```yaml
# values.yaml — imagePullSecrets для всех подов
global:
  imagePullSecrets:
    - name: harbor-registry-secret
```

### 9. Настройка Ingress с TLS (Self-Signed)

В закрытом контуре必须использовать Self-Signed или Internal CA сертификаты:

```bash
# Генерация Self-Signed сертификата
openssl req -x509 -nodes -days 3650 -newkey rsa:4096 \
  -keyout gitlab.key -out gitlab.crt \
  -subj "/CN=gitlab.local" \
  -addext "subjectAltName=DNS:gitlab.local,DNS:registry.gitlab.local,DNS:kas.gitlab.local"

# Создание TLS-секрета
kubectl create secret tls gitlab-tls \
  --cert=gitlab.crt \
  --key=gitlab.key \
  -n gitlab
```

```yaml
# values.yaml — Ingress с TLS
global:
  ingress:
    tls:
      enabled: true
      secretName: gitlab-tls
    annotations:
      nginx.ingress.kubernetes.io/ssl-redirect: "true"
      nginx.ingress.kubernetes.io/proxy-body-size: "250m"
```

### 10. Backup и Restore в air-gapped среде

**Создание бэкапа:**

```bash
# Бэкап через встроенный Job
kubectl create job --from=cronjob/gitlab-backup backup-manual-$(date +%Y%m%d) \
  -n gitlab

# Проверка статуса
kubectl get jobs -n gitlab | grep backup

# Экспорт бэкапа в MinIO
kubectl exec -it deployment/gitlab-toolbox -n gitlab -- \
  backup-cli create
```

**Восстановление:**

```bash
# 1. Копирование бэкапа из MinIO
mc cp local/gitlab-backups/1721531234_2024_07_21_17.2.0_gitlab_backup.tar /tmp/

# 2. Копирование в Pod
kubectl cp /tmp/1721531234_2024_07_21_17.2.0_gitlab_backup.tar \
  gitlab/toolbox-xxx:/tmp/backups/

# 3. Восстановление
kubectl exec -it deployment/gitlab-toolbox -n gitlab -- \
  backup-cli restore BACKUP=1721531234_2024_07_21_17.2.0

# 4. Переиндексация
kubectl exec -it deployment/gitlab-toolbox -n gitlab -- \
  gitlab-rake gitlab:elastic:index:recreate
```

### 11. Обновление GitLab в air-gapped среде

```bash
# 1. Внешний контур: загрузка новой версии чарта
helm pull gitlab/gitlab --untar --version 7.4.0

# 2. Зеркалирование новых образов
helm template gitlab ./gitlab --set global.hosts.domain=local > rendered-new.yaml
diff <(grep -oE 'image:\s*"?[^"]+' rendered.yaml | sort) \
     <(grep -oE 'image:\s*"?[^"]+' rendered-new.yaml | sort) > images-diff.txt

# Импорт только новых/обновленных образов
while IFS= read -r img; do
  skopeo copy "docker://$img" "docker://harbor.local/$(echo $img | sed 's|registry.gitlab.com/|gitlab/|')"
done < <(grep '^>' images-diff.txt | sed 's/^> //')

# 3. Пуш нового чарта в Harbor
helm push gitlab-7.4.0.tgz oci://harbor.local/gitlab-charts

# 4. Внутренний контур: обновление
helm upgrade gitlab oci://harbor.local/gitlab-charts/gitlab \
  --version 7.4.0 \
  --namespace gitlab \
  -f values.yaml \
  --wait --timeout 600s
```

### 12. Отключение внешних зависимостей

В air-gapped среде必须отключить все функции, требующие доступа в интернет:

```yaml
# values.yaml — отключение внешних зависимостей
global:
  appConfig:
    gravatar:
      enabled: false  # Запросы к gravatar.com будут блокироваться
    sentry:
      enabled: false  # Sentry DSN не работает
    signing_key:
      enabled: false  # Функции подписи артефактов
    pingdom:
      enabled: false  # Мониторинг
    google_analytics:
      enabled: false  # Аналитика
    snowplow:
      enabled: false  # Трекинг

pages:
  enabled: false  # GitLab Pages требует DNS

apparmor:
  enabled: false  # AppArmor не доступен в air-gapped

certmanager:
  install: false  # Встроенный cert-manager не нужен

prometheus:
  install: false  # Внешний Prometheus

grafana:
  enabled: false  # Внешний Grafana
```

### 13. Настройка GitLab Runner в air-gapped среде

```yaml
# values.yaml — Runner в air-gapped среде
gitlab-runner:
  install: true
  rbac:
    create: true
  runners:
    config: |
      concurrent = 5
      check_interval = 3

      [[runners]]
        name = "kubernetes-runner"
        url = "https://gitlab.local"
        token = "glrt-..."
        executor = "kubernetes"

        [runners.kubernetes]
          namespace = "gitlab-runner"
          image = "alpine:3.19"
          helper_image = "harbor.local/gitlab/gitlab-runner-helper:x86_64-v17.2.0"
          allowed_images = ["harbor.local/gitlab/*", "alpine:3.*"]
          image_pull_secrets = ["harbor-registry-secret"]

          [runners.kubernetes.resources.requests]
            cpu = "500m"
            memory = "1Gi"
          [runners.kubernetes.resources.limits]
            cpu = "2"
            memory = "4Gi"
```

### 14. Настройка DNS для всех сервисов

```bash
# Добавление DNS-записей для всех сервисов
cat >> /etc/bind/db.gitlab.local <<EOF
gitlab.local.    IN  A  10.0.100.50
registry.gitlab.local.  IN  A  10.0.100.50
kas.gitlab.local.       IN  A  10.0.100.50
minio.local.            IN  A  10.0.100.60
harbor.local.           IN  A  10.0.100.70
EOF

# Перезапуск DNS
systemctl restart named
```

### 15. Проверка целостности развёртывания

```bash
#!/bin/bash
# validate_deployment.sh — проверка всех компонентов

echo "=== GitLab Pods ==="
kubectl get pods -n gitlab

echo ""
echo "=== GitLab Services ==="
kubectl get svc -n gitlab

echo ""
echo "=== Ingress ==="
kubectl get ingress -n gitlab

echo ""
echo "=== PVC ==="
kubectl get pvc -n gitlab

echo ""
echo "=== Harbor Health ==="
curl -sk https://harbor.local/api/v2.0/health | jq .

echo ""
echo "=== MinIO Health ==="
curl -sk https://minio.local/minio/health/live

echo ""
echo "=== DNS Resolution ==="
nslookup gitlab.local
nslookup harbor.local
nslookup minio.local

echo ""
echo "=== TLS Certificate ==="
echo | openssl s_client -connect gitlab.local:443 2>/dev/null | openssl x509 -noout -subject
```

---

## Решение проблем

### Ошибка "X509: Certificate Signed by Unknown Authority"

- **Причина:** Под не доверяет сертификату Harbor/MinIO.
- **Решение:** Проверьте наличие сертификата в `global.certificates.customCAs` и перезапустите поды.
- **Диагностика:**
  ```bash
  # Проверка наличия сертификата в поде
  kubectl exec -it deployment/gitlab-webservice -n gitlab -- \
    cat /etc/gitlab/custom_certs/ca.crt

  # Проверка доверия в containerd
  crictl pull harbor.local/gitlab/test:latest 2>&1 | grep -i x509
  ```

### Ошибка "ImagePullBackOff"

- **Причина:** Узлы Kubernetes не авторизованы в Harbor или не доверяют его сертификату.
- **Решение:**
  1. Добавьте CA сертификат на **все узлы кластера** в `/etc/pki/ca-trust/source/anchors/` (для CentOS/RHEL) или `/usr/local/share/ca-certificates/` (для Ubuntu).
  2. Настройте `imagePullSecrets` в `values.yaml`.
  3. Перезапустите containerd на каждом узле:
  ```bash
  # CentOS/RHEL
  update-ca-trust
  systemctl restart containerd

  # Ubuntu
  update-ca-certificates
  systemctl restart containerd
  ```

### Ошибка "dial tcp: lookup harbor.local: no such host"

- **Причина:** DNS-резолвинг не работает в кластере.
- **Решение:**
  1. Проверьте настройки CoreDNS:
  ```bash
  kubectl get configmap coredns -n kube-system -o yaml
  kubectl logs -n kube-system -l k8s-app=kube-dns
  ```
  2. Добавьте DNS-записи в CoreDNS:
  ```yaml
  apiVersion: v1
  kind: ConfigMap
  metadata:
    name: coredns-custom
    namespace: kube-system
  data:
    custom.server: |
      harbor.local:53 {
          errors
          cache 30
          forward . 10.0.100.10  # Локальный DNS-сервер
      }
  ```

### Ошибка "connection refused" при обращении к MinIO

- **Причина:** MinIO не доступен или сертификат недействителен.
- **Решение:**
  ```bash
  # Проверка доступности MinIO
  kubectl run minio-test --rm -it --image=curlimages/curl:latest -- \
    curl -sk https://minio.local/minio/health/live

  # Проверка статуса MinIO подов
  kubectl get pods -n minio -o wide

  # Просмотр логов
  kubectl logs -n minio deployment/minio
  ```

### Ошибка "Error: timed out waiting for the condition"

- **Причина:** Helm-установка не завершается в течение timeout (по умолчанию 600s).
- **Решение:**
  ```bash
  # Проверка статуса всех подов
  kubectl get pods -n gitlab

  # Проверка PVC (частая причина — Pending PVC)
  kubectl get pvc -n gitlab

  # Проверка StorageClass
  kubectl get storageclass

  # Проверка последних событий
  kubectl get events -n gitlab --sort-by='.lastTimestamp' | tail -20
  ```

### Ошибка "permission denied" в MinIO

- **Причина:** Неверные credentials или policy в MinIO.
- **Решение:**
  ```bash
  # Проверка credentials
  mc alias set local https://minio.local MINIO_ACCESS_KEY MINIO_SECRET_KEY

  # Проверка доступа к bucket'ам
  mc ls local/

  # Проверка policy
  mc admin user list local
  mc admin policy entities local --user gitlab_ci
  ```

### GitLab не запускается после установки

- **Причина:** Ошибка в `values.yaml` или зависимость не готова.
- **Диагностика:**
  ```bash
  # Проверка всех подов
  kubectl get pods -n gitlab

  # Просмотр логов проблемного пода
  kubectl logs -n gitlab deployment/gitlab-webservice --tail=100

  # Проверка Secrets
  kubectl get secrets -n gitlab | grep -v Opaque

  # Проверка ConfigMap
  kubectl get configmap -n gitlab
  ```

---

## Дополнительная информация

### Полезные команды для отладки

| Команда | Описание |
| :--- | :--- |
| `kubectl get pods -n gitlab` | Статус всех подов GitLab |
| `kubectl describe pod <pod> -n gitlab` | Детальная информация о поде |
| `kubectl logs -f deployment/gitlab-webservice -n gitlab` | Логи Webservice в реальном времени |
| `kubectl logs -n minio deployment/minio` | Логи MinIO |
| `kubectl top pods -n gitlab` | Фактическое потребление ресурсов |
| `kubectl get pvc -n gitlab` | Статус PersistentVolumeClaims |
| `kubectl get events -n gitlab --sort-by='.lastTimestamp'` | Хронология событий |
| `helm status gitlab -n gitlab` | Статус Helm-релиза |
| `helm get values gitlab -n gitlab` | Текущие values релиза |

### Диагностический скрипт (one-shot)

```bash
#!/bin/bash
# gitlab-offline-diagnose.sh — быстрая диагностика GitLab в air-gapped среде
NAMESPACE=${1:-gitlab}

echo "=== Helm Release Status ==="
helm status gitlab -n $NAMESPACE 2>/dev/null || echo "Release not found"

echo ""
echo "=== GitLab Pods ==="
kubectl get pods -n $NAMESPACE -o wide

echo ""
echo "=== PVC Status ==="
kubectl get pvc -n $NAMESPACE

echo ""
echo "=== Services ==="
kubectl get svc -n $NAMESPACE

echo ""
echo "=== Ingress ==="
kubectl get ingress -n $NAMESPACE

echo ""
echo "=== Events (last 20) ==="
kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp' | tail -20

echo ""
echo "=== Harbor Health ==="
curl -sk https://harbor.local/api/v2.0/health 2>/dev/null | jq . || echo "Harbor unreachable"

echo ""
echo "=== MinIO Health ==="
curl -sk https://minio.local/minio/health/live 2>/dev/null || echo "MinIO unreachable"

echo ""
echo "=== DNS Resolution ==="
nslookup gitlab.local 2>/dev/null || echo "DNS lookup failed"
```

### Runbook: инциденты по приоритетам

| Приоритет | Инцидент | Время отклика | Действия |
| :--- | :--- | :--- | :--- |
| **P1 (Critical)** | GitLab недоступен, все сервисы в CrashLoop | 15 мин | Проверить логи, PVC, DNS, TLS-сертификаты. При необходимости — `helm rollback`. |
| **P1 (Critical)** | Harbor недоступен, ImagePullBackOff на всех подах | 15 мин | Проверить Harbor, DNS, TLS-сертификаты на узлах. |
| **P2 (High)** | MinIO недоступен, артефакты не сохраняются | 30 мин | Проверить MinIO, credentials, bucket'ы, network. |
| **P2 (High)** | Runner не подключается к GitLab | 30 мин | Проверить helper_image, imagePullSecrets, network policies. |
| **P3 (Medium)** | Медленная загрузка страниц | 2 часа | Проверить ресурсы, PVC IOPS, network latency. |
| **P4 (Low)** | Gravatar не отображается | 4 часа | Отключить `gravatar.enabled: false`. |

### Эскалация (Escalation Matrix)

| Уровень | Условие | Действие |
| :--- | :--- | :--- |
| **L1 (Junior SRE)** | Типичные проблемы: DNS, TLS, credentials | Следовать данному runbook,搜集 логи |
| **L2 (Senior SRE)** | Не типичные проблемы, данные runbook не помогает | Глубокая диагностика, `kubectl debug`, проверка кластера |
| **L3 (Platform Team)** | Проблемы с Helm-чартом, баги, необходимость форка чарта | Обращение к GitLab Support, GitHub issue |
| **External (GitLab Support)** | Проблемы с лицензией, баги в GitLab Runner | Тикет в GitLab Support (https://support.gitlab.com) |

### Метрики для мониторинга (alerting rules)

```yaml
# gitlab-offline-alerts.yaml
groups:
  - name: gitlab-offline-health
    rules:
      - alert: GitLabDown
        expr: up{job="gitlab-webservice"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "GitLab Webservice is down"

      - alert: GitLabHighErrorRate
        expr: rate(http_requests_total{job="gitlab-webservice",code=~"5.."}[5m]) > 0.05
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "GitLab error rate > 5%"

      - alert: HarborDown
        expr: up{job="harbor-core"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Harbor is down"

      - alert: MinIODown
        expr: up{job="minio"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "MinIO is down"

      - alert: GitLabPVCFull
        expr: kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "GitLab PVC usage > 85%"
```

### Часто задаваемые вопросы

**Q: Как проверить, все ли образы импортированы в Harbor?**
```bash
# Сравнение списка образов с тем, что есть в Harbor
while IFS= read -r img; do
  harbor_img="harbor.local/$(echo $img | sed 's|registry.gitlab.com/|gitlab/|')"
  status=$(curl -sk -o /dev/null -w "%{http_code}" "https://$harbor_img/v2/")
  if [ "$status" != "200" ]; then
    echo "MISSING: $harbor_img"
  fi
done < images.txt
```

**Q: Как обновить сертификат Harbor без простоя GitLab?**
```bash
# 1. Обновить сертификат в Harbor
# 2. Обновить секрет в Kubernetes
kubectl create secret generic gitlab-custom-ca \
  --from-file=ca.crt=/path/to/new-root-ca.crt \
  -n gitlab \
  --dry-run=client -o yaml | kubectl apply -f -

# 3. Перезапустить поды GitLab
kubectl rollout restart deployment/gitlab-webservice -n gitlab
```

**Q: Как перенести bundle на целевой узел?**
```bash
# Вариант 1: SCP (если есть выделенный шлюз)
scp gitlab-bundle.tar.gz root@master-1:/tmp/

# Вариант 2: USB-носитель
# На исходном узле:
dd if=/dev/sdb of=/mnt/usb/gitlab-bundle.tar.gz bs=4M
# На целевом узле:
dd if=/mnt/usb/gitlab-bundle.tar.gz of=/dev/sdb bs=4M

# Вариант 3: rsync (если есть промежуточный сервер)
rsync -avz --progress gitlab-bundle.tar.gz root@bastion:/tmp/
```

**Q: Как проверить, что DNS работает корректно?**
```bash
# Проверка CoreDNS логов
kubectl logs -n kube-system -l k8s-app=kube-dns | grep -i error

# Проверка разрешения из пода
kubectl run dns-test --rm -it --image=busybox:1.36 -- nslookup gitlab.local

# Проверка CoreDNS конфигурации
kubectl get configmap coredns -n kube-system -o yaml
```

**Q: Как добавить новый образ в Harbor после установки?**
```bash
# На машине с интернетом
skopeo copy docker://registry.gitlab.com/new-image:latest \
  docker://harbor.local/gitlab/new-image:latest

# Проверка в Harbor
curl -sk -u admin:Harbor@123 "https://harbor.local/api/v2.0/projects/gitlab/repositories"
```

**Q: Как настроить бэкап в air-gapped среде?**
```bash
# Бэкап через MinIO (рекомендуется)
# 1. Создание CronJob
cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gitlab-backup
  namespace: gitlab
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: harbor.local/gitlab/gitlab-toolbox-ee:v17.2.0
            command: ["/bin/bash", "-c"]
            args:
            - |
              backup-cli create
              mc cp /tmp/backups/*.tar.gz local/gitlab-backups/
          restartPolicy: OnFailure
EOF
```

**Q: Как отключить GitLab Runner, если он не нужен?**
```yaml
# values.yaml
gitlab-runner:
  install: false
```

### Рекомендации

- **Отключение Gravatar:** В изолированной среде запросы к `gravatar.com` приведут к задержкам загрузки страниц. Установите `global.appConfig.gravatar.enabled: false`.
- **Локальный реестр Helm:** Публикуйте чарты в Harbor (OCI), чтобы иметь версионированную копию внутри контура.
- **Регулярные бэкапы:** Настройте CronJob для автоматического бэкапа GitLab в MinIO. Храните бэкапы вне кластера.
- **Мониторинг:** Настройте Prometheus + Grafana для мониторинга GitLab, Harbor и MinIO.
- **Документация:** Ведите документацию по IP-адресам, DNS-именам и TLS-сертификатам всех сервисов.

### См. также

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Интеграция GitLab с Harbor](./k3s_dev_environment/gitlab_harbor_integration.md)
- [Обзор Harbor](../../Docker/Docker_registries/Harbor/overview.md)
