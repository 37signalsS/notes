# Harbor: Установка

## Определения

* **Docker Compose**: Инструмент для определения и запуска многоконтейнерных приложений Docker. Используется для установки Harbor на отдельном хосте.
* **Helm**: Менеджер пакетов для Kubernetes, упрощающий развертывание сложных приложений через чарты (наборы манифестов).
* **Оффлайн-установка (Air-gapped)**: Развертывание в изолированной среде без доступа к интернету. Требует предварительной загрузки артефактов и настройки локальных репозиториев.

## Основные концепции

Harbor поддерживает два основных способа развертывания:

| Способ | Назначение | Требования |
| :--- | :--- | :--- |
| **Docker Compose** | Тестовые среды, небольшие продакшен-развертывания | Один хост с Docker, доменное имя или IP |
| **Helm (Kubernetes)** | Продакшен-среды, масштабируемые кластеры | Kubernetes-кластер, внешние БД и кэш (рекомендуется) |

**Ключевые требования для обоих способов:**

* **TLS-сертификаты**: Все клиенты должны доверять сертификату Harbor. См. [создание CA и сертификатов](./certificates.md).
* **Доменное имя**: `hostname` должен совпадать с CN/SAN в сертификате.
* **Пароли**: Храните в защищённом месте (`.env` с правами `600`, Kubernetes Secrets).

**Оффлайн-режим:** Для закрытых контуров без доступа к интернету конфигурация Trivy требует дополнительных настроек (`skip_update: true`, `offline_scan: true`). Обновление баз уязвимостей выполняется вручную (см. [оффлайн-обновление Trivy](./offline_trivy_update.md)).

## Практические сценарии

### Сценарий 1: Установка Harbor с Docker Compose

#### 1. Установка Docker

```bash
apt update
apt install -y containerd docker.io docker-compose
systemctl enable --now docker
usermod -aG docker $USER
```

#### 2. Загрузка Harbor

```bash
# Загрузка оффлайн-установщика последней версии
LATEST=$(curl -s https://api.github.com/repos/goharbor/harbor/releases/latest \
  | grep browser_download_url | grep offline-installer | cut -d '"' -f 4)

FILE=$(basename "$LATEST")
wget "$LATEST"
tar xvzf "$FILE"
rm "$FILE"
cd harbor
```

#### 3. Настройка переменных окружения

Создайте файл `.env` с паролями:

```bash
sudo nano .env
```

```ini
HARBOR_ADMIN_PASSWORD=<надёжный_пароль_администратора>
DB_PASSWORD=<надёжный_пароль_БД>
```

Установите права доступа:

```bash
sudo chmod 600 .env
```

#### 4. Настройка harbor.yml

Создайте резервную копию и отредактируйте конфигурацию:

```bash
cp harbor.yml harbor.yml.bak
sudo nano harbor.yml
```

Минимальная конфигурация:

```yaml
hostname: harbor.example.local
http:
  port: 80
https:
  port: 443
  certificate: /opt/harbor/harbor.example.local.crt
  private_key: /opt/harbor/harbor.example.local.key
harbor_admin_password: ${HARBOR_ADMIN_PASSWORD}
database:
  password: ${DB_PASSWORD}
  max_idle_conns: 200
  max_open_conns: 100
  conn_max_lifetime: 5m
  conn_max_idle_time: 5m
data_volume: /data
trivy:
  ignore_unfixed: false
  skip_update: true
  skip_java_db_update: true
  offline_scan: true
  security_check: vuln
  insecure: false
  timeout: 5m0s
jobservice:
  max_job_workers: 10
  max_job_duration_hours: 24
  job_loggers:
    - STD_OUTPUT
    - FILE
  logger_sweeper_duration: 1
notification:
  webhook_job_max_retry: 3
  webhook_job_http_client_timeout: 3
log:
  level: info
  local:
    rotate_count: 50
    rotate_size: 200M
    location: /var/log/harbor
_version: 2.14.0
proxy:
  http_proxy:
  https_proxy:
  no_proxy:
  components:
    - core
    - jobservice
    - trivy
upload_purging:
  enabled: true
  age: 168h
  interval: 24h
  dryrun: false
cache:
  enabled: false
  expire_hours: 24
```

**Важно:** Перед запуском убедитесь, что сертификаты созданы и размещены в директории, указанной в `https.certificate` и `https.private_key` (см. [создание сертификатов](./certificates.md)).

#### 5. Запуск установки

```bash
sudo ./install.sh --with-trivy
```

#### 6. Вход в веб-интерфейс

Откройте `https://harbor.example.local` и войдите под учётной записью:

* **Логин:** `admin`
* **Пароль:** значение из `HARBOR_ADMIN_PASSWORD`

---

### Сценарий 2: Установка Harbor в Kubernetes через Helm

#### Предварительные требования

* Kubernetes-кластер (например, k3s)
* Установленный [Helm](https://helm.sh/)
* Установленный [cert-manager](../../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) (опционально, для автоматических TLS-сертификатов)
* Внешние PostgreSQL и Redis (рекомендуется для продакшена)

#### 1. Подготовка базы данных

Создайте базу данных для Harbor в PostgreSQL:

```sql
CREATE DATABASE harbor;
```

#### 2. Выбор Helm-чарта

Рекомендуется использовать чарты от [Bitnami](https://bitnami.com/stack/harbor/helm):

* Хорошо поддерживаются
* Запуск контейнеров от non-root пользователя (безопасность)
* Образы доступны на альтернативных реестрах (Quay.io)

#### 3. Конфигурация values.yaml

Ключевые параметры:

* **`expose.ingress`**: Ingress-ресурс для доступа к веб-интерфейсу
* **`externalDatabase` / `externalRedis`**: Подключение к внешним сервисам
* **`persistence`**: Persistent Volumes для хранения данных
* **`image`**: Переопределение реестра и тегов образов

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
    targetRevision: 19.3.5
    helm:
      values: |
        harborAdminPassword: "<смените_после_установки>"
        expose:
          type: ingress
          tls:
            enabled: true
            secretName: harbor-tls
          ingress:
            hostname: registry.krukov.local
            annotations:
              cert-manager.io/cluster-issuer: "letsencrypt-staging"
              cert-manager.io/renew-before: "360h"
        persistence:
          enabled: true
          registry:
            size: 30Gi
          jobservice:
            size: 1Gi
          database:
            size: 1Gi
          redis:
            size: 1Gi
          trivy:
            size: 5Gi
        postgresql:
          enabled: false
        externalDatabase:
          host: "postgresql.database.svc.cluster.local"
          port: 5432
          user: "postgres"
          password: "<пароль>"
          database: "harbor"
        redis:
          enabled: false
        externalRedis:
          host: "redis-master.database.svc.cluster.local"
          port: 6379
          password: "<пароль>"
          database: 0
```

**Ключевые моменты:**

* **`expose.ingress.annotations`**: cert-manager автоматически выпустит сертификат для `registry.krukov.local`
* **`persistence`**: Том реестра увеличен до 30Gi
* **`postgresql.enabled: false`**: Отключает встроенную БД, используется внешняя
* **`externalDatabase`**: Параметры подключения к существующему PostgreSQL

## Дополнительная информация

### Архитектура с внешними зависимостями

Для продакшен-сред рекомендуется использовать внешние сервисы:

* **PostgreSQL**: Централизованное управление БД, резервное копирование, настройка производительности. См. [PostgreSQL overview](../../../Databases/PostgreSQL/overview.md).
* **Redis**: Внешний кэш для сессий и очередей. См. [Redis overview](../../../Databases/redis_overview.md).

### Безопасность

* **Пароли в values.yaml**: Некоторые чарты требуют указания паролей в открытом виде. По возможности используйте чарты с поддержкой Kubernetes Secrets.
* **TLS-сертификаты**: Для публичных сервисов используйте доверенные CA (Let's Encrypt). Для внутренних — собственный CA (см. [certificates.md](./certificates.md)).

### Связанные документы

[Обзор Harbor](./overview.md) описывает возможности и назначение. [Создание сертификатов](./certificates.md) — создание CA и серверных сертификатов. [Работа с Harbor](./usage.md) — аутентификация, тегирование, push/pull. [Оффлайн-обновление Trivy](./offline_trivy_update.md) — обновление баз уязвимостей.
