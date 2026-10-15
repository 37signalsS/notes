# Реестры Docker: хранение и распространение артефактов

**Актуально для:** Docker Engine 29.x, distribution/distribution v3.1.x (образ `registry:3`), Harbor 2.11+, Zot v2.1.x, ORAS v1.3.x (2026)

## Определения

- **Реестр Docker (Registry):** Сервис для хранения и распространения образов и OCI-артефактов. Реализует Distribution API v2 (OCI Distribution Spec). Является специализированным типом **[репозитория артефактов](../CI-CD/artifact_management.md)**.
- **OCI Artifacts:** Стандарт, позволяющий хранить в реестре не только образы, но и любые бинарные объекты (Helm-чарты, SBOM, подписи, политики OPA, аттестации).
- **Дайджест (Digest):** Неизменяемый уникальный идентификатор содержимого (обычно SHA-256). Использование дайджеста вместо тега гарантирует скачивание именно той версии артефакта, которая была протестирована.
- **Referrers (OCI 1.1):** Механизм связи между артефактами. Позволяет «прикреплять» метаданные (например, отчет о сканировании или аттестацию) к образу через поле `subject` без изменения самого образа. При push манифеста с полем `subject` корректный реестр отвечает заголовком `OCI-Subject: sha256:<digest>`.
- **Referrers API:** Эндпоинт `GET /v2/<name>/referrers/<digest>`, возвращающий OCI image index со списком дескрипторов всех артефактов, ссылающихся на данный дайджест. Поддерживает серверную фильтрацию по `?artifactType=` (заголовок ответа `OCI-Filters-Applied`).
- **artifactType:** Поле в манифесте OCI 1.1, определяющее тип контента (например, `application/vnd.example.sbom.v1+json`). Позволяет реестрам и клиентам фильтровать связанные артефакты.
- **Credential Helper:** Внешняя утилита для безопасного хранения учетных данных реестра в системном хранилище ключей (вместо открытого текста в `config.json`).
- **Pull-through Cache (прокси-кэш):** Реестр, который прозрачно кэширует образы из внешнего (upstream) реестра при первом запросе и отдаёт их из локального хранилища при последующих.

## Основные концепции

### Эволюция в универсальное хранилище (OCI 1.1)

Современные реестры перешли от простого хранения слоев к модели **графа зависимостей**. Благодаря стандарту OCI 1.1 реестр выполняет функции базы данных метаданных:
- **Связывание метаданных:** При публикации образа CI-пайплайн автоматически прикрепляет к нему **SBOM** (состав пакетов) и **Provenance** (доказательство сборки) через поле `subject`.
- **Referrers API:** Позволяет клиентам запрашивать список всех артефактов, ссылающихся на конкретный дайджест образа (`oras discover`, `crane manifest`). Инструменты безопасности (Trivy, Docker Scout, ORAS) используют это для верификации образов перед запуском.
- **Индексация связей:** Для быстрого поиска по полю `subject` реестры используют встроенные хранилища (BoltDB в Zot) или реляционные БД (PostgreSQL в Harbor), исключая полное сканирование хранилища манифестов.
- **Устаревший протокол:** Registry v1 (legacy) удалён из Docker Engine — современные реестры реализуют только Distribution API v2. Параметр демона `disable-legacy-registry` запрещает работу с v1 (см. **[усиление демона](./Docker_security/host_daemon_hardening.md)**).

### Архитектура хранилищ (Storage Backends)

Реестры поддерживают различные типы бэкендов для хранения данных:
- **Локальная файловая система:** Стандарт для небольших инсталляций и кэширующих прокси (драйвер `filesystem` в distribution).
- **S3-совместимые хранилища (MinIO, Ceph RGW):** On-prem вариант для масштабируемых систем с высокой доступностью. Драйвер `s3` поддерживается в distribution v2 и v3; драйверы OSS и Swift удалены в v3.
- **Дедупликация на уровне контента:** Реестр хранит только одну копию каждого слоя (blob), даже если он используется в сотнях разных образов и репозиториев.

### Разделение сред и жизненный цикл

1. **Эфемерные/Dev-реестры:** Предназначены для промежуточных сборок. Требуют агрессивных политик очистки (**Garbage Collection**) для удаления неиспользуемых слоев.
2. **Продуктовые реестры (Trusted):** Содержат только проверенные артефакты.
   - **Promotion:** Перенос образа из Dev в Prod реестр через `retag` и `push` без пересборки (гарантия неизменности бинарного кода). Реализуется через `skopeo copy` или `regctl` (см. **[управление артефактами](../CI-CD/artifact_management.md)**).
   - **Immutable Tags:** Запрет перезаписи существующих тегов для обеспечения воспроизводимости инфраструктуры.
   - **Signing:** Обязательная проверка подписи (Cosign/Notation) через Admission Controllers в кластере.

### Проксирование и кэширование (Pull-through Cache)

Для обхода лимитов Docker Hub (Rate Limiting) и ускорения деплоя:
- **Registry Mirror:** Настройка демона Docker (`registry-mirrors` в `daemon.json`) на автоматическое использование локального зеркала. **Ограничение:** зеркала работают только для Docker Hub, но не для других реестров (docs.docker.com/docker-hub/image-library/mirror/). При containerd image store (дефолт в Docker 29.x) известна регрессия (moby/moby#51994): демон опрашивает и зеркало, и upstream — для надёжной маршрутизации используйте `hosts.toml` containerd.
- **Proxy Cache:** Реестр (distribution с `proxy.remoteurl`, Harbor, Zot, Nexus) прозрачно кэширует внешние образы при первом запросе, снижая нагрузку на внешний канал и ускоряя последующие скачивания.

## Предварительные требования

| Требование | Проверка | Примечание |
| :--- | :--- | :--- |
| Docker Engine 29.x | `docker version` | containerd image store включён по умолчанию |
| Место на диске | `df -h /var/lib/docker` | Реестр хранит все слои; рост не ограничен без GC/quota |
| Сеть | Открытый порт 5000 (или 443 для TLS) | Для production — TLS с валидным сертификатом |
| Инструменты | `helm`, `oras`, `skopeo`, `crane` | Для работы с OCI-артефактами и миграцией |
| htpasswd (опционально) | `htpasswd -v` | Пакет `apache2-utils` для базовой аутентификации |

## Практические сценарии

### Сценарий 1: Локальный реестр на distribution (registry:3)

Официальный реестр на базе distribution/distribution. Начиная с v3.0.0 (2026) актуален образ `registry:3`; `registry:2` (последняя версия 2.8.3, окт 2023) больше не развивается.

```bash
# Запуск с сохранением данных и поддержкой удаления манифестов
docker run -d -p 5000:5000 --restart always --name registry \
  -e REGISTRY_STORAGE_DELETE_ENABLED=true \
  -v registry-data:/var/lib/registry \
  registry:3

# Проверка доступности API
curl http://localhost:5000/v2/
# → {}

# Публикация и загрузка образа
docker tag my-app:1.0 localhost:5000/my-app:1.0
docker push localhost:5000/my-app:1.0
# → 1.0: digest: sha256:abcd... size: 1024
docker pull localhost:5000/my-app:1.0
```

Конфигурационный файл (в образе `registry:3` путь по умолчанию изменился с `/etc/docker/registry/config.yml` на `/etc/distribution/config.yml`):

```yaml
version: 0.1
log:
  level: info
storage:
  filesystem:
    rootdirectory: /var/lib/registry
  delete:
    enabled: true
http:
  addr: :5000
```

Базовая аутентификация (htpasswd):

```bash
# Генерация учётных данных на хосте (apache2-utils)
mkdir auth && htpasswd -Bbn user password > auth/htpasswd

docker run -d -p 5000:5000 --name registry \
  -v "$(pwd)/auth:/auth" \
  -e "REGISTRY_AUTH=htpasswd" \
  -e "REGISTRY_AUTH_HTPASSWD_REALM=Registry Realm" \
  -e "REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd" \
  registry:3

docker login localhost:5000 -u user
```

Для production добавьте TLS (монтирование сертификата и ключа через `REGISTRY_HTTP_TLS_CERTIFICATE` / `REGISTRY_HTTP_TLS_KEY`). Для разработки с HTTP реестром добавьте его в небезопасные:

```json
// /etc/docker/daemon.json
{
  "insecure-registries": ["registry.local:5000"]
}
```

### Сценарий 2: Pull-through cache (кэш Docker Hub)

Реестр-кэш снижает нагрузку на канал и обходит лимиты Docker Hub в локальной сети:

```bash
# Запуск кэширующего реестра (upstream — Docker Hub)
docker run -d -p 5000:5000 --restart always --name registry-cache \
  -e REGISTRY_PROXY_REMOTEURL=https://registry-1.docker.io \
  -v registry-cache-data:/var/lib/registry \
  registry:3

# Первый pull кэширует образ, последующие отдаются из локального хранилища
docker pull localhost:5000/library/nginx:latest
```

Для приватных образов Docker Hub передайте учётные данные через `REGISTRY_PROXY_USERNAME` / `REGISTRY_PROXY_PASSWORD`. Подключение демонов к кэшу — через `registry-mirrors` (только для Docker Hub, см. ограничения выше) или прямое обращение `localhost:5000/library/<image>`.

### Сценарий 3: Работа с OCI-артефактами (Helm и ORAS)

Современный способ распространения манифестов и метаданных без традиционных HTTP-репозиториев.

```bash
# Упаковка и пуш Helm-чарта в OCI-реестр
helm package ./my-chart
helm push my-chart-0.1.0.tgz oci://registry.example.com/charts

# Установка напрямую из OCI
helm install my-app oci://registry.example.com/charts/my-chart --version 0.1.0

# Пуш произвольного артефакта (SBOM) через ORAS
oras push registry.example.com/my-app:v1.0 ./sbom.cdx.json

# Просмотр связанных артефактов (Referrers API)
oras discover registry.example.com/my-app:v1.0
# → name: registry.example.com/my-app
# → digest: sha256:...
# → referrers: 1 (SBOM, attestation)
```

Полные сценарии с аттестациями и provenance — в **[управлении артефактами](../CI-CD/artifact_management.md)** (Сценарий 3 и Сценарий 6).

### Сценарий 4: Аутентификация (Credential Helpers и CI)

Обеспечение безопасности учетных данных на рабочих станциях и серверах.

```json
// ~/.docker/config.json
{
  "credsStore": "osxkeychain",
  "credHelpers": {
    "registry.example.com": "pass"
  }
}
```

- **`credsStore`:** глобальный хелпер для всех реестров (`osxkeychain` — macOS, `wincred` — Windows, `pass`/`secretservice` — Linux).
- **`credHelpers`:** переопределение хелпера для конкретного реестра.
- После `docker login` пароль сохраняется в системной связке ключей, а не в открытом виде.

В CI-пайплайнах передавайте пароль через stdin, чтобы он не попал в историю команд и лог процесса:

```bash
echo "$CI_REGISTRY_PASSWORD" | docker login registry.example.com -u "$CI_REGISTRY_USER" --password-stdin
# → Login Succeeded
```

### Сценарий 5: Zot — легковесный OCI-реестр

Zot (CNCF Sandbox, Apache 2.0) — реестр в виде одного бинарника без внешних зависимостей, с акцентом на строгое соответствие OCI-стандартам (Distribution и Image Spec). Подходит для edge-инсталляций и air-gapped сред:

```json
// config.json
{
  "distSpecVersion": "1.1.0",
  "storage": { "rootDirectory": "/var/lib/zot" },
  "http": { "address": "0.0.0.0", "port": "5000" },
  "extensions": {
    "search": { "enable": true },
    "metrics": { "enable": true },
    "scrub": { "enable": true }
  }
}
```

```bash
# Запуск (в production зафиксируйте тег из GitHub Releases project-zot/zot)
docker run -d -p 5000:5000 \
  -v zot-data:/var/lib/zot \
  -v "$(pwd)/config.json:/etc/zot/config.json" \
  ghcr.io/project-zot/zot-linux-amd64:latest
```

Расширение `scrub` выполняет периодическую проверку целостности и удаление повреждённых blob'ов — аналог GC для Zot.

### Сценарий 6: Harbor — корпоративный стандарт

Используется для on-premise инсталляций с требованиями к RBAC, сканированию уязвимостей (Trivy), репликации, retention и GC. Полное руководство (аутентификация, робот-аккаунты, Cosign, Helm OCI, proxy cache, webhooks, репликация, GC) — в **[работе с Harbor](./Docker_registries/Harbor/usage.md)**, управление TLS — в **[управлении сертификатами](./Docker_registries/Harbor/certificates.md)**.

### Сценарий 7: Promotion между средами

Перенос артефактов между реестрами (dev → staging → prod) без пересборки и без Docker-демона:

```bash
# skopeo: копирование образа между реестрами
skopeo copy docker://dev-registry.example.com/app:v1.0 docker://prod-registry.example.com/app:v1.0

# regctl: retag того же digest (blob'ы не копируются, меняется только ссылка)
regctl tag create dev-registry.example.com/app:v1.0 prod-registry.example.com/app:v1.0
```

Детали и сравнение методов — в **[управлении артефактами](../CI-CD/artifact_management.md)** (Сценарий 5) и **[skopeo](../Podman/skopeo_overview.md)**.

### Сценарий 8: Self-hosted registry в Kubernetes (NodePort, PVC, GC)

Развёртывание официального `registry:3` в Kubernetes с NodePort-сервисом, PVC и автоматизированной GC. Подходит для on-premise и air-gapped кластеров без внешних зависимостей.

**Deployment + Service (NodePort):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: registry
  namespace: registry
spec:
  replicas: 1
  selector:
    matchLabels:
      app: registry
  template:
    metadata:
      labels:
        app: registry
    spec:
      containers:
        - name: registry
          image: registry:3
          ports:
            - containerPort: 5000
          env:
            - name: REGISTRY_STORAGE_FILESYSTEM_ROOTDIRECTORY
              value: /var/lib/registry
            - name: REGISTRY_HTTP_SECRET
              valueFrom:
                secretKeyRef:
                  name: registry-secret
                  key: http-secret
            - name: REGISTRY_STORAGE_DELETE_ENABLED
              value: "true"
          volumeMounts:
            - name: registry-data
              mountPath: /var/lib/registry
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
      volumes:
        - name: registry-data
          persistentVolumeClaim:
            claimName: registry-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: registry
  namespace: registry
spec:
  type: NodePort
  selector:
    app: registry
  ports:
    - port: 5000
      targetPort: 5000
      nodePort: 30500
```

NodePort `30500` доступен с любой машины, которая может достучаться до ноды. `REGISTRY_STORAGE_DELETE_ENABLED: "true"` включает API удаления манифестов — необходимо для работы garbage collection.

**HTTP-секрет (Secret):**

```bash
# Сгенерировать 32-байтовый secret и создать Secret
kubectl create secret generic registry-secret \
  --from-literal=http-secret=$(openssl rand -hex 32) \
  -n registry
```

**Постоянное хранилище (PVC):**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: registry-pvc
  namespace: registry
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 50Gi
  storageClassName: local-path
```

Для production вместо PVC можно использовать S3-совместимое хранилище (MinIO, Ceph RGW). Переключение через env-переменные (см. **[архитектуру хранилищ](#архитектура-хранилищ-storage-backends)**):

```yaml
env:
  - name: REGISTRY_STORAGE
    value: s3
  - name: REGISTRY_STORAGE_S3_BUCKET
    value: my-registry-bucket
  - name: REGISTRY_STORAGE_S3_REGION
    value: us-east-1
  - name: REGISTRY_STORAGE_S3_ACCESSKEY
    valueFrom:
      secretKeyRef:
        name: s3-creds
        key: access-key
  - name: REGISTRY_STORAGE_S3_SECRETKEY
    valueFrom:
      secretKeyRef:
        name: s3-creds
        key: secret-key
```

**Настройка Docker для HTTP-реестра:**

Docker отклоняет HTTP-реестры по умолчанию — добавьте адрес в `insecure-registries`:

```json
// /etc/docker/daemon.json
{
  "insecure-registries": ["registry.registry:30500"]
}
```

```bash
sudo systemctl restart docker
```

> **Примечание для containerd:** в Docker 29.x containerd image store включён по умолчанию. Для надёжной маршрутизации через зеркала используйте `hosts.toml` (см. **[Сценарий 2](#сценарий-2-pull-through-cache-кэш-docker-hub)**).

**Push и Pull образов:**

```bash
# Тегировать, запушить
docker tag myapp:latest registry.registry:30500/myapp:latest
docker push registry.registry:30500/myapp:latest

# Проверить теги
curl -s http://registry.registry:30500/v2/myapp/tags/list | jq .
# → {"name":"myapp","tags":["latest"]}
```

В Kubernetes-подах:

```yaml
containers:
  - name: app
    image: registry.registry:30500/myapp:abc1234
    imagePullPolicy: IfNotPresent
```

Если нода обращается к реестру без аутентификации, `imagePullSecret` не нужен. Для защищённых реестров (см. **[Сценарий 4](#сценарий-4-аутентификация-credential-helpers-и-ci)**):

```bash
kubectl create secret docker-registry registry-creds \
  --docker-server=registry.registry:30500 \
  --docker-username=robot \
  --docker-password=TOKEN \
  --namespace=app
```

```yaml
spec:
  imagePullSecrets:
    - name: registry-creds
```

**Удаление старых тегов через API:**

```bash
DIGEST=$(curl -sI \
  -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
  "http://registry.registry:30500/v2/myapp/manifests/old-tag" \
  | grep -i Docker-Content-Digest | awk '{print $2}' | tr -d '\r')

curl -X DELETE "http://registry.registry:30500/v2/myapp/manifests/${DIGEST}"
# → 202 Accepted
```

После удаления тега запустите GC для физического освобождения места на диске.

**Garbage collection:**

API реестра не удаляет блобы физически при удалении тега — слои (blobs) остаются на диске до GC. Перед GC удалите теги через API (см. выше), затем запустите GC. Для предотвращения записи во время GC рекомендуется перевести реестр в read-only режим (`storage.maintenance.readonly.enabled: true` в config.yml, или `REGISTRY_STORAGE_MAINTENANCE_READONLY_ENABLED=true`):

```bash
# Прогон с dry-run
kubectl exec -n registry deploy/registry -- \
  registry garbage-collect --dry-run --delete-untagged /etc/distribution/config.yml

# Если результат удовлетворительный — реальный GC
kubectl exec -n registry deploy/registry -- \
  registry garbage-collect --delete-untagged /etc/distribution/config.yml
```

> **Важно:** В контейнере `registry:3` конфиг находится по пути `/etc/distribution/config.yml` (в v2 путь был `/etc/docker/registry/config.yml`). Бинарник `bin/registry` в v2 соответствует `registry` в v3.

**CronJob для автоматизации GC:**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: registry-gc
  namespace: registry
spec:
  schedule: "0 3 * * 0"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: gc
              image: registry:3
              command:
                - registry
                - garbage-collect
                - --delete-untagged
                - /etc/distribution/config.yml
              volumeMounts:
                - name: registry-data
                  mountPath: /var/lib/registry
          volumes:
            - name: registry-data
              persistentVolumeClaim:
                claimName: registry-pvc
```

> **Best practice:** для production CronJob лучше сочетать с read-only режимом. Автоматизированная смена конфига через ConfigMap + rolling restart Deployment описана в **[операциях Harbor](../Docker_registries/Harbor/operations.md)**.

## Устранение неполадок

| Симптом | Вероятная причина | Диагностика и решение |
| :--- | :--- | :--- |
| `404` на пути `/referrers/` | Реестр или прокси перед ним не поддерживают OCI 1.1; Docker Engine может пытаться интерпретировать HTML-страницу ошибки как JSON | Проверьте версию реестра (Harbor 2.11+, Zot, distribution v3). Проверьте поддержку API через `oras discover` |
| Высокая задержка при запросах метаданных | Реестр не индексирует поле `subject` и ищет по всему хранилищу манифестов | Используйте реестр с индексацией (Zot — BoltDB, Harbor — PostgreSQL) |
| Пропажа подписей при параллельных сборках | Использование fallback-тегов (схема `sha256-<digest>.sig`) в реестрах без нативной поддержки Referrers API | Перейдите на нативную поддержку OCI 1.1 (Harbor 2.11+, Zot, GHCR, Docker Hub) |
| Место не освобождается после удаления манифестов | Удаление через API лишь помечает манифест; слои (blobs) остаются на диске | Включите `delete.enabled`, переведите реестр в read-only (`storage.maintenance.readonly.enabled: true`) и запустите `registry garbage-collect --dry-run --delete-untagged /etc/distribution/config.yml`; для реестра в контейнере — `docker exec -it registry registry garbage-collect --dry-run --delete-untagged /etc/distribution/config.yml`. В Harbor — GC через UI/API |
| `429 Too Many Requests` при pull | Лимит Docker Hub: 100 pulls/6h для анонимных (per IPv4/IPv6 /64), 200 pulls/6h для Personal | `docker login` (аутентификация увеличивает лимит), pull-through cache, проверка заголовков `ratelimit-*` — **[Сценарий 4](./Docker_registries/public_registry_security.md)** |
| `x509: certificate signed by unknown authority` при pull | Самоподписанный или недоверенный сертификат реестра | Добавьте CA в `/etc/docker/certs.d/<registry>/ca.crt` и перезапустите демон (для containerd — `/etc/containerd/certs.d/`) |
| Зеркало (`registry-mirrors`) не используется для `myregistry.example.com` | `registry-mirrors` работает только для Docker Hub | Обращайтесь к реестру напрямую или настраивайте маршрутизацию через `hosts.toml` containerd |
| `unauthorized: authentication required` | Нет `docker login` или истёк токен | Выполните `docker login`; в CI используйте `--password-stdin` |

## Валидация

```bash
# 1. Доступность API реестра
curl http://localhost:5000/v2/
# → {}

# 2. Каталог репозиториев
curl http://localhost:5000/v2/_catalog
# → {"repositories":["my-app"]}

# 3. Теги репозитория
curl http://localhost:5000/v2/my-app/tags/list
# → {"name":"my-app","tags":["1.0"]}

# 4. Поддержка Referrers API (OCI 1.1)
oras discover localhost:5000/my-app:v1.0
# → список связанных артефактов или пустой результат без ошибки 404

# 5. Состояние демона (для mirror-конфигураций)
docker info --format '{{json .RegistryMirrors}}'
# → ["http://registry.local:5000"]
```

## Лучшие практики и очистка

- **Фиксация по дайджесту** в production-манифестах вместо плавающих тегов — стратегии и ловушки `:latest` в **[версионировании](./Docker_registries/image_versioning_and_tagging.md)**.
- **Immutable tags** и **retention** на уровне реестра (Harbor) — запрет перезаписи тегов и автоматическое удаление старых.
- **GC по расписанию:** для distribution на bare metal — cron-задача с предварительным read-only; в Kubernetes — CronJob (см. **[Сценарий 8](#сценарий-8-self-hosted-registry-в-kubernetes-nodeport-pvc-gc)**); для Harbor — расписание в UI; для Zot — расширение `scrub`.
- **Сканирование на push** (Harbor + Trivy) и **проверка подписей** (Cosign/Notation) перед деплоем — **[безопасность публичных реестров](./Docker_registries/public_registry_security.md)**.
- **Мониторинг места:** quota на проект (Harbor), алерты на заполнение тома реестра.
- **Очистка после тестов:** `docker logout <registry>`, `docker volume rm registry-data registry-cache-data`, удаление htpasswd-файлов.

## Дополнительная информация

### Сравнение функциональности реестров

| Реестр | Поддержка OCI 1.1 | Типы артефактов | Особенности |
| :--- | :--- | :--- | :--- |
| **Docker Hub** | Полная | Любые OCI | Интеграция Docker Scout, официальные образы; лимиты 100 pulls/6h (анонимно) и 200 pulls/6h (Personal), безлимит для Pro/Team/Business |
| **Harbor** | Полная (с v2.11+) | Любые OCI | RBAC, сканирование Trivy, репликация, retention, GC; on-prem |
| **Sonatype Nexus** | Полная | Любые OCI | Универсальный артефактори (Maven, npm, PyPI, Helm) с proxy-репозиториями; on-prem и SaaS |
| **JFrog Artifactory** | Полная (с v7.90.1) | Любые OCI | Кроссплатформенный артефактори (Docker, Helm, Maven, npm, PyPI), гео-репликация, интеграция с Xray |
| **GitHub (GHCR)** | Полная | Любые OCI | Бесшовная интеграция с GitHub Actions, OIDC keyless signing |
| **Zot** | Полная | Любые OCI | Один бинарник без зависимостей, CNCF Sandbox, строгая OCI-конформность, расширение scrub |

### См. также

- **[Безопасность реестров](./Docker_registries/public_registry_security.md)** — защита от Typosquatting, проверка лимитов Docker Hub, Kyverno.
- **[Версионирование и тегирование](./Docker_registries/image_versioning_and_tagging.md)** — стратегии SemVer, фиксация по Digest, многоархитектурные образы.
- **[Harbor: работа с реестром](./Docker_registries/Harbor/usage.md)** — корпоративный реестр: RBAC, робот-аккаунты, Cosign, репликация, GC.
- **[Команды Docker CLI](./docker_commands.md)** — подробнее о `login`, `push`, `pull`.
- **[Управление артефактами](../CI-CD/artifact_management.md)** — концептуальный обзор репозиториев артефактов, ORAS, promotion.
- **[skopeo](../Podman/skopeo_overview.md)** — копирование и инспекция образов без демона.

### Глубокое изучение

- **[distribution/distribution](https://github.com/distribution/distribution)** — исходный код реестра `registry:3` (актуальная версия v3.1.x, 2026; v2.8.3 — последняя версия линии 2.x).
- **[Docker Hub](https://hub.docker.com)** — официальный реестр. Лимиты: 100 pulls/6h (анонимно, per IPv4/IPv6 /64), 200 pulls/6h (Personal), безлимит для Pro/Team/Business; Docker Scout для анализа образов.
- **[GitHub Container Registry (GHCR)](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)** — интеграция с GitHub: `docker buildx build --push -t ghcr.io/owner/repo:tag`, OIDC keyless signing через GitHub Actions.
- **[GitLab Container Registry](https://docs.gitlab.com/ee/user/packages/container_registry/)** — встроенный реестр: автоматическая очистка через Cleanup Policy, интеграция с GitLab CI/CD (детали — в **[Container Registry в GitLab CI/CD](../CI-CD/GitLab_CI/Advanced/container_registry.md)**).
- **[ORAS](https://oras.land)** — CLI для OCI-артефактов (v1.3.x): `oras push`, `oras pull`, `oras discover`, `oras attach`.
- **[crane](https://github.com/google/go-containerregistry/blob/main/cmd/crane/README.md)** — манипуляции с образами (v0.21.x): `crane ls`, `crane copy`, `crane mutate` для управления тегами и слоями без демона.
- **[Zot](https://zotregistry.dev)** — OCI-native реестр: документация, конфигурация, расширения (search, metrics, scrub).
