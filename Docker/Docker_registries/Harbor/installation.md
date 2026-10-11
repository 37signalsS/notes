# Harbor: Установка

**Актуально для:** Harbor 2.15.x

## Определения

* **Docker Compose**: Инструмент для определения и запуска многоконтейнерных приложений Docker. Используется для установки Harbor на отдельном хосте.
* **Helm**: Менеджер пакетов для Kubernetes, упрощающий развертывание сложных приложений через чарты (наборы манифестов).
* **Онлайн/оффлайн-установщик**: Два варианта дистрибутива Harbor. Онлайн-установщик мал по размеру и скачивает образы с Docker Hub в момент установки. Оффлайн-установщик содержит готовые образы и применяется на хостах без доступа к интернету.
* **Оффлайн-установка (Air-gapped)**: Развертывание в изолированной среде без доступа к интернету. Требует предварительной загрузки артефактов и настройки локальных репозиториев.
* **Объектное хранилище (Object Storage)**: Внешний сервис хранения данных (S3, MinIO, Azure Blob), используемый Harbor для хранения слоев образов. Рекомендуется для высокодоступных (HA) сред.

## Основные концепции

Harbor поддерживает два основных способа развертывания:

| Способ | Назначение | Требования |
| :--- | :--- | :--- |
| **Docker Compose** | Тестовые среды, небольшие продакшен-развертывания | Один хост с Docker Engine >20.10 и Compose >2.3, доменное имя или IP, порты 80/443 |
| **Helm (Kubernetes)** | Продакшен-среды, масштабируемые HA-кластеры | Kubernetes 1.20+, Helm 3.2.0+, ingress-контроллер, внешние PostgreSQL и Redis (рекомендуется) |

**Ключевые требования для обоих способов:**

* **TLS-сертификаты**: Все клиенты должны доверять сертификату Harbor. См. **[Управление сертификатами и TLS](./certificates.md)**.
* **Доменное имя**: `hostname` должен совпадать с CN/SAN в сертификате. Не используйте `localhost`, `127.0.0.1` или `0.0.0.0` — реестр должен быть доступен внешним клиентам.
* **Пароли**: `harbor.yml` содержит пароли в открытом виде — ограничьте права доступа к файлу. В Kubernetes используйте Secrets (значения `existingSecretAdminPassword`, `database.external.existingSecret`, `redis.external.existingSecret`).

**Оффлайн-режим:** Для закрытых контуров без доступа к интернету конфигурация Trivy требует дополнительных настроек (`skip_update: true`). Обновление баз уязвимостей выполняется вручную (см. **[оффлайн-обновление Trivy](./offline_trivy_update.md)**).

## Требования

**Ресурсы хоста (Docker Compose):**

| Ресурс | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| CPU | 2 CPU | 4 CPU |
| Память | 4 GB | 8 GB |
| Диск | 40 GB | 160 GB |

**Программный стек:**

| ПО | Версия | Описание |
| :--- | :--- | :--- |
| Docker Engine | > 20.10 | [Установка Docker Engine](https://docs.docker.com/engine/install/) |
| Docker Compose | > 2.3 | Входит в состав Docker Engine |
| OpenSSL | Latest (опционально) | Генерация сертификатов и ключей |

**Сетевые порты:**

| Порт | Протокол | Описание |
| :--- | :--- | :--- |
| 443 | HTTPS | Harbor Portal и Core API (порт меняется в `harbor.yml`) |
| 80 | HTTP | Harbor Portal и Core API (порт меняется в `harbor.yml`) |

> Пользователь, запускающий `install.sh`, должен иметь права на выполнение Docker-команд (обычно — членство в группе `docker`).

## Практические сценарии

### Сценарий 1: Установка Harbor с Docker Compose

#### 1. Установка Docker и Docker Compose

Для работы Harbor требуется установленный Docker Engine и плагин Docker Compose.
> **Полная инструкция:** см. **[Установка Docker на Ubuntu](../../docker_install_ubuntu.md)**.

#### 2. Загрузка установщика

Установщики доступны на [странице релизов](https://github.com/goharbor/harbor/releases). Выберите версию явно — не используйте `latest` в копируемых командах:

```bash
VERSION=v2.15.2

# Оффлайн-установщик: для хостов без доступа к интернету (содержит готовые образы)
wget "https://github.com/goharbor/harbor/releases/download/${VERSION}/harbor-offline-installer-${VERSION}.tgz"
# → 'harbor-offline-installer-v2.15.2.tgz'

# Онлайн-установщик: мал по размеру, скачивает образы с Docker Hub при установке
# wget "https://github.com/goharbor/harbor/releases/download/${VERSION}/harbor-online-installer-${VERSION}.tgz"
```

**Верификация подлинности (опционально):** к каждому установщику прилагается `.asc`-файл с OpenPGP-подписью:

```bash
gpg --keyserver hkps://keyserver.ubuntu.com --receive-keys 644FF454C0B4115C
# → public key "Harbor-sign (The key for signing Harbor build)" imported

gpg -v --keyserver hkps://keyserver.ubuntu.com --verify harbor-offline-installer-v2.15.2.tgz.asc
# → gpg: Good signature from "Harbor-sign (The key for signing Harbor build)"
```

Распаковка:

```bash
tar xzvf harbor-offline-installer-v2.15.2.tgz
# → harbor/
# → harbor/harbor.yml.tmpl
# → harbor/install.sh
# → harbor/prepare

rm harbor-offline-installer-v2.15.2.tgz
cd harbor
```

> Директория установщика используется только для установки и конфигурации — данные Harbor хранятся в Docker-томах (`data_volume`). Директорию нужно сохранить: она потребуется для обновлений и перенастройки.

#### 3. Настройка harbor.yml

Создайте рабочий файл конфигурации из шаблона и отредактируйте его напрямую — пароли задаются в самом `harbor.yml`, механизма подстановки переменных из `.env` в Harbor нет:

```bash
cp harbor.yml.tmpl harbor.yml
sudo nano harbor.yml
sudo chmod 600 harbor.yml   # файл содержит пароли
```

**Пример конфигурации (версия 2.15.x, HTTPS):**

```yaml
hostname: harbor.example.local

# HTTP допустим только в air-gapped test/dev-контурах без внешнего интернета.
# В шаблоне секция http активна по умолчанию — для HTTPS закомментируйте её.
# http:
#   port: 80

https:
  port: 443
  certificate: /opt/harbor/harbor.example.local.crt
  private_key: /opt/harbor/harbor.example.local.key

# Пароль администратора: применяется только при первом запуске,
# далее пароль меняется в Harbor Portal. Дефолт: admin / Harbor12345.
harbor_admin_password: "<надёжный_пароль>"

database:
  password: "<надёжный_пароль_локальной_БД>"   # обязательно сменить в production

data_volume: /data

trivy:
  skip_update: true    # air-gapped / CI: не обновлять базы из GitHub
                       # полная настройка оффлайн-сканирования — см. offline_trivy_update.md
```

> Пути сертификатов в примере (`/opt/harbor/...`) — альтернатива директории по умолчанию `/data/cert/`. Процедура генерации сертификатов — в **[certificates.md](./certificates.md)**.

#### 4. Использование внешнего S3/MinIO (опционально)

В `harbor.yml` раскомментируйте секцию `storage_service` (полное описание бэкендов — S3/Azure/GCS, redirect, cache layer, S3-гигиена — в [storage.md](./storage.md)):

```yaml
storage_service:
  # ca_bundle: /path/to/ca.crt   # если хранилище использует самоподписанный сертификат
  s3:
    accesskey: <ACCESS_KEY>
    secretkey: <SECRET_KEY>
    region: us-east-1
    bucket: harbor-bucket
    regionendpoint: http://192.168.1.100:9000   # для MinIO
  redirect:
    deactivate: true   # MinIO не поддерживает redirect
```

#### 5. Запуск установки

```bash
sudo ./install.sh --with-trivy
# → ✔ ----Harbor has been installed and started successfully.----
```

Без сканера: `sudo ./install.sh`. Онлайн-установщик может работать долго — он скачивает все образы Harbor с Docker Hub.

#### 6. Валидация

```bash
docker compose ps
# → все сервисы Harbor в состоянии Up
```

1. Откройте в браузере `https://harbor.example.local` (для HTTPS предварительно настройте доверие клиентов к сертификату — см. **[certificates.md](./certificates.md)**, сценарий 3).
2. Войдите как `admin` с паролем из `harbor_admin_password` и **немедленно смените пароль** в Harbor Portal.
3. Создайте проект (например, `myproject`) и выполните smoke-тест:

```bash
docker login harbor.example.local
# → Login Succeeded

docker push harbor.example.local/myproject/myrepo:mytag
# → pushed
```

---

### Сценарий 2: Установка Harbor в Kubernetes через Helm

Используется **официальный чарт `goharbor/harbor-helm`** (репозиторий `https://helm.goharbor.io`). Чарт Bitnami распространяется отдельно через OCI (`oci://registry-1.docker.io/bitnamicharts/harbor`) и имеет несовместимую схему значений (`adminPassword`, `exposureType`, `ingress.core.hostname`) — не смешивайте значения двух чартов.

#### Предварительные требования

* Kubernetes-кластер 1.20+
* Helm v3.2.0+
* Ingress-контроллер (при `expose.type: ingress`)
* Внешние PostgreSQL и Redis (рекомендуется для HA)
* **[cert-manager](../../../Kubernetes/ToolsUtilities/cert_manager/LetsEncrypt/letsencrypt_scenarios.md)** — только если используется автоматическая выдача TLS (Let's Encrypt); для самоподписанных или собственных сертификатов не требуется

#### 1. Подготовка внешней базы данных

Если используется внешний PostgreSQL, создайте пустую базу. Имя по умолчанию — `registry` (меняется через `coreDatabase`); таблицы Harbor создаются автоматически при первом запуске:

```sql
CREATE DATABASE registry;
# → CREATE DATABASE
```

#### 2. Добавление репозитория Helm

```bash
helm repo add harbor https://helm.goharbor.io
helm repo update
```

#### 3. Конфигурация values.yaml

```yaml
externalURL: https://registry.example.com   # формат protocol://domain[:port], только корень домена (без path)

harborAdminPassword: "<смените_после_установки>"   # дефолт Harbor12345

expose:
  type: ingress          # ingress | clusterIP | nodePort | loadBalancer
  tls:
    enabled: true
    certSource: secret   # auto (самоподписанный) | secret | none
    secret:
      secretName: harbor-tls   # секрет с ключами tls.crt и tls.key
  ingress:
    hosts:
      core: registry.example.com
    className: nginx
    annotations:
      cert-manager.io/cluster-issuer: "letsencrypt-prod"   # только при авто-выдаче TLS

database:
  type: external         # internal (встроенный) | external
  external:
    host: "postgres-host"
    port: 5432
    username: "harbor"
    password: "<password>"
    coreDatabase: "registry"
    sslmode: "require"   # disable | require | verify-ca | verify-full

redis:
  type: external
  external:
    addr: "redis-host:6379"   # Sentinel: "host1:port1,host2:port2,host3:port3"
    # sentinelMasterSet: "mymaster"   # только в режиме Sentinel
    password: "<password>"

persistence:
  enabled: true
  resourcePolicy: keep   # PVC сохраняются при helm uninstall
  imageChartStorage:
    type: s3             # filesystem | azure | gcs | s3 | swift | oss
    disableredirect: true   # обязательно для MinIO
    s3:
      region: us-east-1
      bucket: harbor-artifacts
      accesskey: <ACCESS_KEY>
      secretkey: <SECRET_KEY>
      regionendpoint: http://minio-service:9000

jobservice:
  jobLogger: database    # логи jobservice в БД — обязательно при использовании object storage
```

> Внутренний TLS между компонентами Harbor (core, jobservice, portal, registry, trivy) включается значением `internalTLS.enabled: true` — см. **[certificates.md](./certificates.md)**, сценарий 4.

#### 4. Развертывание

```bash
helm install my-release harbor/harbor --version 1.19.2 -n harbor --create-namespace
```

> Версия чарта `1.19.x` соответствует Harbor `2.15.x` (проверяется в [index.yaml](https://helm.goharbor.io/index.yaml): поле `appVersion`).

#### 5. Валидация

```bash
kubectl get pods -n harbor
# → все поды в состоянии Running

helm status my-release -n harbor
```

Откройте `https://registry.example.com` в браузере, войдите как `admin` и выполните smoke-тест `docker login registry.example.com` (доверие к сертификату — см. **[certificates.md](./certificates.md)**).

> **Примечание для Harbor 2.15.2:** при использовании встроенной PostgreSQL чарт автоматически обновляет базу **с PostgreSQL 15 до PostgreSQL 18** через `pg_upgrade` при старте пода. Убедитесь, что бэкап БД сделан до апгрейда или первой установки. Для сред с не-ASCII данными после обновления может потребоваться `reindexdb --all-databases`. В 2.15.2 внутренний кэш-бэкенд заменён с Redis на **Valkey**; внешний Redis по-прежнему поддерживается для очередей.

#### 6. High Availability

Для HA-развертывания (официальная страница [Deploying Harbor with High Availability via Helm](https://goharbor.io/docs/2.15.0/install-config/harbor-ha-helm/)):

* Реплики stateless-компонентов: `portal.replicas`, `core.replicas`, `jobservice.replicas`, `registry.replicas` — значение `n >= 2`
* Хранилище: общий PVC с `ReadWriteMany` (`persistence.persistentVolumeClaim.registry.storageClass` / `jobservice.storageClass`, `accessMode: ReadWriteMany`) **либо** внешнее object storage (см. выше) с `jobservice.jobLogger: database`
* Если StorageClass не поддерживает RWM: `updateStrategy.type: Recreate`
* Требуется HA ingress-контроллер и HA PostgreSQL 9.6+ (Harbor не управляет их доступностью)
* **Redis**: поддерживается Sentinel, но **не поддерживаются** Redis Cluster и TLS-подключения к Redis

#### 7. Развертывание через ArgoCD

Пример манифеста `Application` (GitOps, значения — схема официального чарта):

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: harbor
  namespace: argocd
spec:
  project: default
  source:
    repoURL: 'https://helm.goharbor.io'
    chart: harbor
    targetRevision: 1.19.2
    helm:
      values: |
        externalURL: https://registry.example.com
        harborAdminPassword: "<смените_после_установки>"
        expose:
          type: ingress
          tls:
            enabled: true
            certSource: secret
            secret:
              secretName: harbor-tls
          ingress:
            hosts:
              core: registry.example.com
            annotations:
              cert-manager.io/cluster-issuer: "letsencrypt-prod"
        database:
          type: external
          external:
            host: "postgres-host"
            port: 5432
            username: "harbor"
            password: "<password>"
            coreDatabase: "registry"
            sslmode: "require"
        redis:
          type: external
          external:
            addr: "redis-host:6379"
            password: "<password>"
        persistence:
          imageChartStorage:
            type: s3
            disableredirect: true
            s3:
              region: us-east-1
              bucket: harbor-artifacts
              accesskey: <ACCESS_KEY>
              secretkey: <SECRET_KEY>
              regionendpoint: http://minio-service:9000
        jobservice:
          jobLogger: database
```

#### 8. Удаление

```bash
helm uninstall my-release -n harbor
```

При `persistence.resourcePolicy: keep` (дефолт) PVC сохраняются — для полного удаления данных удалите PVC вручную.

---

### Сценарий 3: Harbor за обратным прокси / балансировщиком

Когда Harbor развёрнут за reverse proxy или LB (TLS терминируется на прокси), активируется параметр `external_url` — при этом `hostname` перестаёт использоваться.

```yaml
# harbor.yml (Docker Compose)
external_url: https://registry.example.com   # внешний URL, видимый клиентам
# hostname: harbor.example.local             # больше не используется
```

В Helm-чарте внешний URL задаётся значением `externalURL` (см. [сценарий 2](#сценарий-2-установка-harbor-в-kubernetes-через-helm)).

Требования к прокси:

* Проксировать `https://registry.example.com` на внутренний Harbor (порт `https.port`, дефолт 443).
* Health check: `GET /api/v2.0/health` → `{"status":"healthy"}`.
* Не дублируйте заголовок `proxy_set_header X-Forwarded-Proto $scheme;` в Nginx-конфигурации Harbor — дублирование вызывает циклические редиректы (см. [Troubleshooting TLS](./certificates.md#troubleshooting)).
* Если TLS терминируется на прокси, Harbor внутри контура может работать по HTTP — допустимо только в изолированном контуре без внешнего доступа.

```bash
# Валидация через прокси
curl -sk https://registry.example.com/api/v2.0/health
# → {"status":"healthy"}

docker login registry.example.com
# → Login Succeeded
```

---

### Сценарий 4: Исходящий прокси (proxy)

Когда Harbor работает в сети с обязательным исходящим прокси, задаётся секция `proxy` в `harbor.yml` — Harbor использует прокси для исходящих HTTPS-запросов:

```yaml
# harbor.yml
proxy:
  http_proxy: http://proxy.corp.local:3128
  https_proxy: http://proxy.corp.local:3128
  no_proxy: 127.0.0.1,localhost,.corp.local,harbor.corp.local,core,registry,registryctl,jobservice,portal,trivy-adapter
```

**Кто использует прокси:**

| Компонент | Что идёт через прокси |
| :--- | :--- |
| **Trivy adapter** | Обновление баз уязвимостей (GitHub, OSDB) |
| **Job Service** | Задачи репликации (push/pull к удалённым реестрам) |
| **Harbor core** | Прочие исходящие HTTPS-вызовы |

**Whitelist для Trivy:** даже через прокси Trivy требует прямого доступа к `github.com`, `github-releases.githubusercontent.com` и `*.s3.amazonaws.com` — добавьте их в `no_proxy` или разрешите напрямую на сетевом уровне, иначе обновление баз Trivy не работает (в air-gapped — `skip_update: true`, см. [offline_trivy_update.md](./offline_trivy_update.md)).

В Helm-чарте исходящий прокси задаётся переменными окружения `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` для соответствующих компонентов (см. [harbor-helm](https://github.com/goharbor/harbor-helm)).

```bash
# Валидация: Trivy обновляет базы через прокси
docker logs trivy-adapter 2>&1 | grep -i "downloaded"
# → базы скачаны без ошибок timeout
```

## Управление жизненным циклом (Docker Compose)

Команды выполняются в директории с `docker-compose.yml`:

```bash
sudo docker compose stop    # остановка контейнеров
sudo docker compose start   # запуск
```

**Перенастройка** (после изменения `harbor.yml`):

```bash
sudo docker compose down -v
sudo nano harbor.yml
sudo ./prepare              # или sudo ./prepare --with-trivy
sudo docker compose up -d
```

**Очистка:**

```bash
sudo docker compose down -v   # контейнеры удаляются, данные (/data) сохраняются

# Полная очистка перед чистой переустановкой:
sudo rm -r /data/database /data/registry /data/redis
```

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Клиенты не доверяют сертификату Harbor | Сертификат не добавлен в trust store / Docker | См. **[certificates.md](./certificates.md)**, сценарий 3 |
| `docker login` по HTTP отказывается | Docker блокирует небезопасные реестры | `insecure-registries` в `/etc/docker/daemon.json`, затем `systemctl restart docker`, `docker compose down -v && docker compose up -d` (только для air-gapped) |
| Онлайн-установщик зависает на скачивании образов | Нет доступа к Docker Hub | Используйте оффлайн-установщик |
| Изменения в `harbor.yml` не применяются | Не запущен `./prepare` | `docker compose down -v` → `./prepare` → `docker compose up -d` |
| Trivy не обновляет базы в air-gapped | Нет доступа к GitHub | `skip_update: true` + процедура из **[offline_trivy_update.md](./offline_trivy_update.md)** |
| Установка завершилась с ошибкой | Различные причины | Логи в `/var/log/harbor/`; официальная страница [Troubleshooting Harbor Installation](https://goharbor.io/docs/2.15.0/install-config/troubleshoot-installation/) |

## Best Practices

### Предустановочная проверка сети и хоста

* **DNS**: убедитесь, что `hostname` из `harbor.yml` разрешается на всех клиентах и на самом хосте Harbor. Проверка: `dig harbor.example.local`, `nslookup harbor.example.local`, `ping -c 3 harbor.example.local`.
* **Фаерволл**: порт 443 (и 80, если используется) должен быть доступен из сетей клиентов. Проверка: `sudo ss -tlnp | grep -E ':(80|443)'`, `nc -zv harbor.example.local 443`.
* **NTP**: время на хосте Harbor и клиентах должно быть синхронизировано ( drift < 1 сек ). TLS- handshake и логирование зависят от корректного времени. Проверка: `timedatectl status`, `chronyc tracking`.
* **SELinux/AppArmor**: на RHEL/CentOS/Fedora SELinux может блокировать запись в нестандартные пути сертификатов. Для теста: `sudo setenforce 0`; для production — правильные контексты (`semanage fcontext`, `restorecon`).
* **Docker daemon**: убедитесь, что для `harbor.example.local` не установлен флаг `insecure-registries` в `/etc/docker/daemon.json` — иначе `docker login` по HTTPS будет использовать небезопасный путь.

### Бэкап до первой установки

* Данные Harbor хранятся в `data_volume` (дефолт `/data`) и директории установщика. Перед первой установкой создайте пустые директории и назначьте права:
  ```bash
  sudo mkdir -p /data /backup
  sudo chown -R 1000:1000 /data
  ```
* Полный runbook бэкапа и восстановления — в **[upgrade_backup.md](./upgrade_backup.md)**. Для внешней PostgreSQL — `pg_dump` до начала установки.

### Мониторинг и валидация после установки

* **Health endpoint**: добавьте в мониторинг проверку `GET /api/v2.0/health` — ожидается `{"status":"healthy"}`. Для внешнего прокси проверяйте через прокси.
* **Prometheus метрики**: включите `metrics` в `harbor.yml` или Helm и скрейпите `harbor_up`, `harbor_health`. Полный список метрик и alert-правила — в **[operations.md](./operations.md#сценарий-2-мониторинг-и-алерты-prometheus)**.
* **Smoke-тест**: после установки выполните `docker login`, push и pull тегового образа. Проверьте, что артефакт виден в Portal.

### Очистка неудачной установки

* **Docker Compose**: `sudo docker compose down -v` удаляет контейнеры, но сохраняет данные в `/data`. Для полной очистки перед переустановкой:
  ```bash
  sudo rm -rf /data/database /data/registry /data/redis
  ```
* **Helm**: `helm uninstall my-release -n harbor` удаляет развёртывание, но при `persistence.resourcePolicy: keep` PVC сохраняются. Удалите их вручную: `kubectl delete pvc -n harbor -l app.kubernetes.io/instance=my-release`.
* **Директория установщика** сохраняется для повторного использования; при переустановке той же версии можно повторно запустить `./install.sh`.

## Граничные случаи

* **`harbor_admin_password` игнорируется** после первого запуска — далее пароль администратора управляется в Harbor Portal.
* **Директория установщика ≠ данные**: данные Harbor живут в Docker-томах (`data_volume`, дефолт `/data`), а не в директории установщика; директорию установщика нужно сохранять для обновлений.
* **Внешняя БД**: таблицы Harbor создаются автоматически при первом запуске — создавать их вручную не нужно.
* **Redis**: Sentinel поддерживается, Redis Cluster и TLS-подключения — нет.
* **`externalURL`** (Helm): только корень домена (`https://registry.example.com`), harbor-helm не поддерживает развёртывание на path.
* **MinIO**: redirect должен быть отключён (`redirect.deactivate: true` в `harbor.yml`, `persistence.imageChartStorage.disableredirect: true` в чарте).
* **HTTP**: допустим только в air-gapped test/dev-контурах без внешнего интернета; во всех остальных средах — HTTPS.
* **`external_url`** (Docker Compose): включается при развёртывании за обратным прокси — при этом `hostname` перестаёт использоваться.
* **Обновление Harbor**: требует миграции конфигурации и схемы БД — см. официальную документацию [Upgrading Harbor](https://goharbor.io/docs/2.15.0/administration/upgrade/).
* **PostgreSQL 18 (Harbor 2.15.2+)**: при использовании встроенной PostgreSQL чарт автоматически обновляет базу с PostgreSQL 15 до PostgreSQL 18 через `pg_upgrade`. Убедитесь, что бэкап сделан; для сред с не-ASCII данными после обновления может потребоваться `reindexdb --all-databases`.
* **Valkey (Harbor 2.15.2+)**: внутренний кэш-бэкенд заменён с Redis на Valkey. Внешний Redis по-прежнему поддерживается для очередей задач; Sentinel работает, Redis Cluster и TLS-подключения — нет.

## Дополнительная информация

### Архитектура с внешними зависимостями

Для продакшен-сред рекомендуется использовать внешние сервисы:
* **PostgreSQL**: см. **[PostgreSQL overview](../../../Databases/PostgreSQL/overview.md)**.
* **Redis**: см. **[Redis overview](../../../Databases/redis_overview.md)**.
* **S3 Storage**: обеспечивает масштабируемость Registry.

### Безопасность

* **Пароли**: в Docker Compose — права `600` на `harbor.yml`; в Kubernetes — внешние Secret Stores и значения `existingSecret*`.
* **TLS**: для внутренних сред используйте собственный CA (см. **[certificates.md](./certificates.md)**).
* **Установщик**: проверяйте GPG-подпись `.asc`-файла перед установкой (ключ `644FF454C0B4115C`).
* **Hardening после установки**: смена пароля admin, выключенная self-registration, RBAC, приватные production-проекты — чек-лист в **[hardening.md](./hardening.md)**.

### Связанные документы

* **[Обзор Harbor](./overview.md)** — архитектура и возможности.
* **[Работа с Harbor](./usage.md)** — аутентификация и управление.
* **[Создание сертификатов](./certificates.md)** — настройка TLS.
* **[Оффлайн-обновление Trivy](./offline_trivy_update.md)** — работа в закрытых контурах.
* **[Hardening](./hardening.md)** — защита инстанса после установки.
* **[harbor-helm (GitHub)](https://github.com/goharbor/harbor-helm)** — полный список значений чарта.
