# Harbor: Установка

## Определения

* **Docker Compose**: Инструмент для определения и запуска многоконтейнерных приложений Docker. Используется для установки Harbor на отдельном хосте.
* **Helm**: Менеджер пакетов для Kubernetes, упрощающий развертывание сложных приложений через чарты (наборы манифестов).
* **Оффлайн-установка (Air-gapped)**: Развертывание в изолированной среде без доступа к интернету. Требует предварительной загрузки артефактов и настройки локальных репозиториев.
* **Объектное хранилище (Object Storage)**: Внешний сервис хранения данных (S3, MinIO, Azure Blob), используемый Harbor для хранения слоев образов. Рекомендуется для высокодоступных (HA) сред.

## Основные концепции

Harbor поддерживает два основных способа развертывания:

| Способ | Назначение | Требования |
| :--- | :--- | :--- |
| **Docker Compose** | Тестовые среды, небольшие продакшен-развертывания | Один хост с Docker, доменное имя или IP |
| **Helm (Kubernetes)** | Продакшен-среды, масштабируемые кластеры | Kubernetes-кластер, внешние БД и кэш (рекомендуется) |

**Ключевые требования для обоих способов:**

* **TLS-сертификаты**: Все клиенты должны доверять сертификату Harbor. См. **[Управление сертификатами и TLS](./certificates.md)**.
* **Доменное имя**: `hostname` должен совпадать с CN/SAN в сертификате.
* **Пароли**: Храните в защищённом месте (`.env` с правами `600`, Kubernetes Secrets).

**Оффлайн-режим:** Для закрытых контуров без доступа к интернету конфигурация Trivy требует дополнительных настроек (`skip_update: true`, `offline_scan: true`). Обновление баз уязвимостей выполняется вручную (см. **[оффлайн-обновление Trivy](./offline_trivy_update.md)**).

## Практические сценарии

### Сценарий 1: Установка Harbor с Docker Compose

#### 1. Установка Docker и Docker Compose

Для работы Harbor требуется установленный Docker Engine и плагин Docker Compose.
> **Полная инструкция:** см. SSoT-файл **[Установка Docker на Ubuntu](../../docker_install_ubuntu.md)**.

#### 2. Загрузка Harbor

```bash
# Загрузка оффлайн-установщика последней версии
LATEST=$(curl -s https://api.github.com/repos/goharbor/harbor/releases/latest \
  | grep browser_download_url | grep offline-installer | cut -d '"' -f 4)

FILE=$(basename "$LATEST")
wget "$LATEST"
# → Saving to: ‘harbor-offline-installer-v2.x.x.tgz’

tar xvzf "$FILE"
# → harbor/
# → harbor/harbor.yml.tmpl
# → harbor/install.sh

rm "$FILE"
cd harbor
```

#### 3. Настройка переменных окружения

Создайте файл `.env` с паролями для подстановки в конфигурацию:

```bash
sudo nano .env
```

```ini
HARBOR_ADMIN_PASSWORD=<надёжный_пароль_администратора>
DB_PASSWORD=<надёжный_пароль_БД>
```

Установите права доступа (только для текущего пользователя):

```bash
sudo chmod 600 .env
# → (no output)
```

#### 4. Настройка harbor.yml

Создайте рабочий файл конфигурации из шаблона:

```bash
cp harbor.yml.tmpl harbor.yml
sudo nano harbor.yml
```

**Пример конфигурации (версия 2.15.x):**

```yaml
hostname: harbor.example.local
http:
  port: 80
https:
  port: 443
  certificate: /opt/harbor/harbor.example.local.crt
  private_key: /opt/harbor/harbor.example.local.key
harbor_admin_password: "admin_password_here" # Используйте значение из .env
database:
  password: "db_password_here" # Используйте значение из .env
data_volume: /data
trivy:
  skip_update: true
  offline_scan: true
```

#### 5. Использование внешнего S3/MinIO (Опционально)

В `harbor.yml` измените секцию `storage_service`:

```yaml
storage_service:
  s3:
    accesskey: <ACCESS_KEY>
    secretkey: <SECRET_KEY>
    region: us-east-1
    bucket: harbor-bucket
    regionendpoint: http://192.168.1.100:9000 # Для MinIO
```

#### 6. Запуск установки

```bash
sudo ./install.sh --with-trivy
# → ✔ ----Harbor has been installed and started successfully.----
```

---

### Сценарий 2: Установка Harbor в Kubernetes через Helm

Используется чарт от **Bitnami** для обеспечения гибкости и поддержки Enterprise-стандартов.

#### Предварительные требования

* Kubernetes-кластер (v1.25+)
* Установленный Helm (v3.10+)
* Установленный **[cert-manager](../../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md)**
* Внешние PostgreSQL и Redis (рекомендуется)

#### 1. Подготовка базы данных

Если используется внешний PostgreSQL, создайте базу данных:

```sql
CREATE DATABASE harbor;
# → CREATE DATABASE
```

#### 2. Добавление репозитория Helm

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
```

#### 3. Конфигурация для объектного хранилища (S3)

Для использования S3 (MinIO, AWS) добавьте в `values.yaml`:

```yaml
persistence:
  enabled: true
  imageChartStorage:
    type: s3
    s3:
      region: us-east-1
      bucket: harbor-artifacts
      accesskey: <ACCESS_KEY>
      secretkey: <SECRET_KEY>
      regionendpoint: http://minio-service:9000
```

#### 4. Развертывание через ArgoCD

Пример манифеста `Application`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: harbor
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://charts.bitnami.com/bitnami'
    chart: harbor
    targetRevision: 19.3.x
    helm:
      values: |
        harborAdminPassword: "<смените_после_установки>"
        expose:
          type: ingress
          tls:
            enabled: true
            secretName: harbor-tls
          ingress:
            hostname: registry.example.com
            annotations:
              cert-manager.io/cluster-issuer: "letsencrypt-prod"
        postgresql:
          enabled: false
        externalDatabase:
          host: "postgres-host"
          user: "harbor"
          database: "harbor"
          password: "<password>"
```

## Дополнительная информация

### Архитектура с внешними зависимостями

Для продакшен-сред рекомендуется использовать внешние сервисы:
* **PostgreSQL**: см. **[PostgreSQL overview](../../../Databases/PostgreSQL/overview.md)**.
* **Redis**: см. **[Redis overview](../../../Databases/redis_overview.md)**.
* **S3 Storage**: обеспечивает масштабируемость Registry.

### Безопасность

* **Пароли в values.yaml**: Используйте Kubernetes Secrets или внешние Secret Stores.
* **TLS**: Для внутренних сред используйте собственный CA (см. **[certificates.md](./certificates.md)**).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — архитектура и возможности.
* **[Работа с Harbor](./usage.md)** — аутентификация и управление.
* **[Создание сертификатов](./certificates.md)** — настройка TLS.
* **[Оффлайн-обновление Trivy](./offline_trivy_update.md)** — работа в закрытых контурах.
