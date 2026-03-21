# Установка Harbor

Harbor устанавливается с помощью Docker Compose.

## Шаг 1.1 Ставим docker

Установим docker и docker-compose:

```bash
apt update && 
apt install containerd docker.io docker-compose -y
systemctl enable docker --now && 
sudo usermod -aG docker $USER
```

## Шаг 1.2 Скачиваем Harbor и готовим конфиги

Клонируем репозиторий Harbor, используя актуальную версию:

```bash
LATEST=$(curl -s https://api.github.com/repos/goharbor/harbor/releases/latest 
  | grep browser_download_url 
  | grep offline-installer 
  | cut -d '"' -f 4)

FILE=$(basename "$LATEST")

wget "$LATEST" && 
tar xvzf "$FILE" && 
rm "$FILE" && 
cd harbor
```

Создаём файл `.env` для хранения паролей:

```bash
sudo nano .env
```

Прописываем в переменных пароль Админа и БД:

```
HARBOR_ADMIN_PASSWORD=super_admin_pazzword
DB_PASSWORD=super_db_mazafaka
```

Изменяем права:

```bash
sudo chmod 600 .env
```

Далее работаем с файлом `harbor.yml`. Создаём резервную копию:

```bash
sudo cp harbor.yml.copy harbor.yml
```

Чтобы хосты доверяли этому репозиторию, нужно создать сертификаты в Центре Сертификации (CA).
Создайте сертификаты в вашем ЦА с именами:
`harbor.example.local.key`
`harbor.example.local.crt`
где `harbor.example.local` доменное имя вашего будущего репозитория.
Или перейдите на Шаг 3 (в отдельном разделе ниже), затем вернитесь сюда.

Открываем на редактирование:

```bash
sudo nano harbor.yml
```

Удаляем содержимое файла и вставляем следующие параметры:

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
  skip_update: true           # Если нет интернета, базу Trivy нужно обновлять вручную
  skip_java_db_update: true   # Если нет интернета, базу Trivy нужно обновлять вручную
  offline_scan: true          # Если нет интернета, то сканирование будет в оффлайн режиме
  security_check: vuln
  insecure: false
  timeout: 5m0s
jobservice:
  max_job_workers: 10
  max_job_duration_hours: 24
  job_loggers:
    - STD_OUTPUT
    - FILE
  logger_sweeper_duration: 1 #days
notification:
  webhook_job_max_retry: 3
  webhook_job_http_client_timeout: 3 #seconds
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

*Примечание: Данная конфигурация Trivy предназначена для работы в закрытом контуре (без доступа к интернету). Это означает, что базы сканера уязвимостей Trivy не будут обновляться напрямую, а только вручную (см. [Оффлайн обновление Trivy](./offline_trivy_update.md)). Настройки конфигурации `skip_update: true` и `offline_scan: true` сделаны исходя из этого требования.*

## Шаг 2. Запуск установки

Запустите установку с компонентом Trivy:

```bash
sudo ./install.sh --with-trivy
```

## Шаг 2.1 Вход в UI

После установки вы сможете войти в веб-интерфейс Harbor по адресу, указанному в `hostname` (например, `https://harbor.example.local`). Логин и пароль администратора были заданы в `.env` файле.

## Установка в Kubernetes через Helm

Для установки в [Kubernetes](../../../Kubernetes/kubernetes_overview.md) рекомендуется использовать [Helm](https://helm.sh/). Это предпочтительный способ для производственных сред, так как он упрощает управление сложным приложением, каким является Harbor.

### Выбор Helm-чарта

* **Bitnami Charts**: Рекомендуется использовать чарты от [Bitnami](https://bitnami.com/stack/harbor/helm). Они хорошо поддерживаются и имеют ряд преимуществ с точки зрения безопасности, например, запуск контейнеров от имени non-root пользователя. Кроме того, их образы часто хранятся на альтернативных реестрах, таких как `Quay.io`, что может быть полезно при ограничениях доступа к Docker Hub.

### Архитектура с внешними зависимостями

Для максимального контроля и надежности рекомендуется разворачивать Harbor с внешними сервисами, а не использовать встроенные в чарт зависимости.

* **База данных**: Используйте внешний кластер [PostgreSQL](../../../Databases/PostgreSQL/postgresql_overview.md). Это позволяет централизованно управлять резервным копированием, восстановлением и настройками производительности БД.
* **Кэш**: Используйте внешний [Redis](../../../Databases/redis_overview.md).

### Конфигурация через `values.yaml`

Вся конфигурация производится через файл `values.yaml`. Ключевые параметры для настройки:

* **`ingress`**: Настройка Ingress-ресурса для доступа к веб-интерфейсу Harbor. Важно правильно указать `hostname` и `annotations` для вашего Ingress-контроллера.
* **`externalPsql` и `externalRedis`**: Секции для указания параметров подключения к внешним экземплярам PostgreSQL и Redis. Здесь прописываются хосты, порты, имена пользователей и пароли.
  * **Важно:** Некоторые Helm-чарты могут требовать указания паролей в открытом виде в `values.yaml`. Это является их недостатком. Если возможно, следует использовать чарты, поддерживающие чтение паролей из Kubernetes Secrets.
* **`persistence`**: Настройка Persistent Volumes для хранения данных реестра, логов и других компонентов. Необходимо указать `storageClass` и требуемый объем.
* **`image`**: Возможность переопределить реестр и тег для каждого из образов компонентов Harbor, что полезно для работы в закрытых контурах или при использовании прокси-реестров.

### Пример: Установка в k3s с помощью ArgoCD

Этот пример демонстрирует установку Harbor в кластер k3s с использованием GitOps-подхода через ArgoCD.

**Предварительные условия:**

* Установлен и настроен [ArgoCD](../../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md#argocd).
* Установлен [cert-manager](../../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md) для автоматического выпуска TLS-сертификатов.
* Присутствуют внешние экземпляры PostgreSQL и Redis.

#### 1. Подготовка базы данных

Перед установкой необходимо создать базу данных для Harbor в вашем кластере PostgreSQL.

```sql
CREATE DATABASE harbor;
```

#### 2. Манифест Application для ArgoCD

Создайте манифест `Application` для развертывания Harbor. Этот манифест описывает, откуда брать Helm-чарт, в какой namespace его устанавливать и с какими параметрами.

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
    targetRevision: 19.3.5 # Укажите актуальную версию чарта
    helm:
      values: |
        # Админ пароль по умолчанию, смените его после установки
        harborAdminPassword: "password"

        # Внешний URL, по которому будет доступен Harbor
        expose:
          type: ingress
          tls:
            enabled: true
            secretName: harbor-tls
          ingress:
            hostname: registry.krukov.local
            # Аннотации для cert-manager
            annotations:
              cert-manager.io/cluster-issuer: "letsencrypt-staging"
              cert-manager.io/renew-before: "360h"
              # ... другие аннотации

        # Настройка хранилища (PV/PVC)
        persistence:
          enabled: true
          # Используется StorageClass по умолчанию (в примере это local-path-provisioner)
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

        # Отключение встроенной базы данных PostgreSQL
        postgresql:
          enabled: false

        # Подключение к внешней базе данных PostgreSQL
        externalDatabase:
          host: "postgresql.database.svc.cluster.local"
          port: 5432
          user: "postgres"
          password: "password"
          database: "harbor"

        # Отключение встроенного Redis
        redis:
          enabled: false

        # Подключение к внешнему Redis
        externalRedis:
          host: "redis-master.database.svc.cluster.local"
          port: 6379
          password: "password"
          database: 0
```

**Ключевые моменты конфигурации:**

* **`expose.ingress`**: Настраивает Ingress-ресурс. Аннотации `cert-manager.io/*` указывают `cert-manager` выпустить сертификат для домена `registry.krukov.local` и сохранить его в секрете `harbor-tls`.
* **`persistence`**: Включает постоянное хранилище. Размер тома для реестра (`registry`) увеличен до 30Gi. Так как `storageClass` не указан, будет использован `StorageClass` по умолчанию в кластере.
* **`postgresql.enabled: false`**: Отключает развертывание PostgreSQL в составе чарта.
* **`externalDatabase`**: Содержит данные для подключения к вашему существующему экземпляру PostgreSQL.
* **`redis.enabled: false`**: Отключает развертывание Redis в составе чарта.
* **`externalRedis`**: Содержит данные для подключения к вашему существующему экземпляру Redis.
