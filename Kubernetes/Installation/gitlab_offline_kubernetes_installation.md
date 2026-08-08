# Установка GitLab в закрытом контуре Kubernetes

Руководство по развертыванию, настройке и поддержке платформы GitLab в изолированных средах (air-gapped) с использованием локальных реестров и объектных хранилищ.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **Air-gapped (Закрытый контур)** | Изолированная сетевая среда, не имеющая прямого доступа к публичному интернету. |
| **OCI (Open Container Initiative)** | Стандарт для образов и артефактов. Позволяет хранить Helm-чарты в Docker-реестрах. |
| **Private CA (Локальный УЦ)** | Центр сертификации, выпускающий сертификаты для внутренних сервисов (Harbor, MinIO, GitLab). |
| **Helper Image** | Вспомогательный образ GitLab Runner, используемый для служебных операций (кэширование, артефакты) в Kubernetes. |
| **KAS (Kubernetes Agent Server)** | Компонент для связи GitLab с кластерами, требующий настройки внутренних адресов в оффлайн-режиме. |

---

## Основные концепции

### Стратегия оффлайн-развертывания

Установка в закрытом контуре требует предварительной подготовки всех зависимостей во внешнем контуре (с доступом в интернет) и их последующего переноса. Ключевые аспекты:
1.  **Зеркалирование образов:** Все образы (более 20 компонентов) должны быть перенесены в локальный Harbor.
2.  **Управление доверием:** Все компоненты системы должны доверять корневому сертификату Private CA.
3.  **Локальные зависимости:** Отключение функций, требующих внешних вызовов (Gravatar, Google Analytics, встроенный cert-manager для публичных доменов).

### Требования к инфраструктуре

| Компонент | Роль в оффлайн-схеме |
| :--- | :--- |
| **Harbor / Nexus** | Хранение Docker-образов и Helm-чартов. |
| **MinIO / Ceph S3** | Замена облачным S3 для хранения LFS, артефактов и бэкапов. |
| **Локальный DNS** | Резолвинг имен внутренних сервисов внутри кластера и для клиентов. |

---

## Практические сценарии

### 1. Подготовка артефактов (Внешний контур)

На машине с доступом в интернет скачайте чарт и извлеките список образов:

```bash
# Добавление репозитория и скачивание чарта
helm repo add gitlab https://charts.gitlab.io
helm pull gitlab/gitlab --untar

# Генерация списка всех образов из чарта
helm template gitlab ./gitlab --set global.hosts.domain=local > rendered.yaml
grep -oE 'image:\s*"?[^"]+' rendered.yaml | sed -E 's/^image:\s*"?//; s/"$//' | sort -u > images.txt
```

### 2. Перенос и импорт образов (Внутренний контур)

После переноса архивов импортируйте их в Harbor. Рекомендуется сохранять иерархию репозиториев для упрощения `values.yaml`.

```bash
# Пример тегирования и пуша (автоматизируйте через скрипт)
docker tag registry.gitlab.com/gitlab-org/build/cng/gitlab-webservice-ee:v17.2.0 \
  harbor.local/gitlab/gitlab-webservice-ee:v17.2.0
docker push harbor.local/gitlab/gitlab-webservice-ee:v17.2.0
```

### 3. Настройка доверия (Custom CA)

Если Harbor или MinIO используют сертификаты от локального УЦ, GitLab должен им доверять.

```yaml
# values.yaml
global:
  certificates:
    customCAs:
      - secret: gitlab-custom-ca
        key: root-ca.crt
```
*Создайте секрет `gitlab-custom-ca` с содержимым вашего корневого сертификата.*

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

---

## Решение проблем

### Ошибка "X509: Certificate Signed by Unknown Authority"
- **Причина:** Под не доверяет сертификату Harbor/MinIO.
- **Решение:** Проверьте наличие сертификата в `global.certificates.customCAs` и перезапустите поды.

### Ошибка "ImagePullBackOff"
- **Причина:** Узлы Kubernetes не авторизованы в Harbor или не доверяют его сертификату.
- **Решение:** 
  1. Добавьте CA сертификат на **все узлы кластера** в `/etc/pki/ca-trust/source/anchors/` (для CentOS/RHEL) или `/usr/local/share/ca-certificates/` (для Ubuntu).
  2. Настройте `imagePullSecrets` в `values.yaml`.

---

## Дополнительная информация

### Рекомендации

- **Отключение Gravatar:** В изолированной среде запросы к `gravatar.com` приведут к задержкам загрузки страниц. Установите `global.appConfig.gravatar.enabled: false`.
- **Локальный реестр Helm:** Публикуйте чарты в Harbor (OCI), чтобы иметь версионированную копию внутри контура.

### См. также

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Интеграция GitLab с Harbor](./k3s_dev_environment/gitlab_harbor_integration.md)
- [Обзор Harbor](../../Docker/Docker_registries/Harbor/overview.md)
- [Системы хранения данных и S3](../../Concepts/Storage/data_storage_overview.md)
- [S3 CSI-драйверы](../../Kubernetes/Storage/CSI/s3-csi-drivers.md)
