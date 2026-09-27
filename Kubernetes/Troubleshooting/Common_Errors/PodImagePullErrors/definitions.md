# Ошибки загрузки образов (Image Pull Errors): Определения

## Определения

**`ErrImagePull`** — непосредственная ошибка выполнения операции `PullImage`. Возникает, когда `kubelet` (через gRPC-вызов к CRI) получает отрицательный ответ от рантайма контейнеров. Это состояние фиксируется в момент неудачной попытки.

**`ImagePullBackOff`** — состояние ожидания (waiting state), в которое контейнер переходит после серии неудачных попыток загрузки. Это механизм защиты, предотвращающий "шторм" запросов к реестру и перегрузку сетевого канала узла.

**Экспоненциальная задержка (Exponential Backoff):** алгоритм планировщика `kubelet`, увеличивающий время между попытками скачивания: 10s → 20s → 40s → 80s → 160s → 300s. Максимальный порог — 5 минут.

**CRI (Container Runtime Interface)** — плагинный интерфейс на базе **gRPC**, позволяющий `kubelet` взаимодействовать с различными рантаймами (containerd, CRI-O). Для загрузки образа используется метод `PullImage(PullImageRequest)`, принимающий параметры `ImageSpec` и `AuthConfig`.

**Image Digest (SHA256)** — уникальный, криптографически неизменяемый идентификатор содержимого образа (Content Addressable Identifier). Использование digest (например, `image@sha256:...`) вместо мутабельных тегов (`:latest`, `:stable`) является стандартом безопасности, гарантирующим целостность артефакта.

**`imagePullSecret`** — объект типа `Secret` (`kubernetes.io/dockerconfigjson`), содержащий авторизационные данные (Auth Token, Basic Auth). Секреты имеют область видимости **Namespace**, что является частой причиной ошибок при попытке использования секрета из другого пространства имен.

**Container Image (Образ контейнера)** — немутируемый артефакт, содержащий файловую систему приложения, метаданные (entrypoint, env, labels) и инструкции для запуска. Образ состоит из набора слоёв (layers), каждый из которых представляет собой дельту предыдущего состояния файловой системы. Слои кэшируются и переиспользуются между образами, что уменьшает объём передаваемых данных. Структура образа определяется спецификациями [OCI Image Spec](https://github.com/opencontainers/image-spec) и [Docker Image Spec](https://github.com/moby/moby/blob/master/image/spec).

**Container Registry (Реестр контейнеров)** — серверное приложение, реализующее [OCI Distribution Spec](https://github.com/opencontainers/distribution-spec) для хранения, распространения и управления образами. Предоставляет REST API v2 для операций push/pull/inspect. Типы: публичные (Docker Hub, GitHub Container Registry), приватные (Harbor, Nexus, Nexus Repository), эфемерные (ttl.sh). В Kubernetes реестр является внешней зависимостью — kubelet обращается к нему напрямую из host network namespace.

**Image Reference (Ссылка на образ)** — полный путь к образу в реестре. Формат: `[registry/][repository:]tag[@digest]`. Примеры:
- `nginx` — Docker Hub, тег `latest` (неявно)
- `docker.io/library/nginx:1.25` — полный путь
- `harbor.local/myproject/app:v2.1.0` — приватный реестр
- `registry.k8s.io/pause:3.9@sha256:fe...` — с пиннингом на digest
Использование digest вместо тега гарантирует воспроизводимость: `image@sha256:...` всегда ссылается на один и тот же слой, в отличие от мутабельных тегов (`:latest`, `:stable`).

**Multi-arch Image (Мультиплатформенный образ)** — образ, представленный в виде **Manifest List** (или OCI Index), содержащего несколько манифестов для разных платформ (linux/amd64, linux/arm64 и т.д.). При pull рантайм автоматически выбирает совместимый манифест на основе архитектуры и ОС узла. Если совпадение не найдено — возникает ошибка `no matching manifest for linux/arm64/v8`. Спецификации: Docker Manifest List v2, OCI Image Index.

**OverlayFS (Union File System)** — filesystem, используемый рантаймами контейнеров (containerd, CRI-O) для организации слоёной файловой системы. Объединяет несколько директорий (lower layers) в единую виртуальную (upper layer + merged). В контексте containerd — это **snapshotter** (например, `overlayfs`, `fuse-overlayfs`), который управляет кэшем распакованных слоёв в `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/`. Проблемы с OverlayFS (переполнение, повреждение) приводят к ошибкам распаковки образов.

**Image Garbage Collection (Сборка мусора образов)** — механизм kubelet, автоматически удаляющий неиспользуемые образы с узла для освобождения дискового пространства. Управляется параметрами `imageGCHighThresholdPercent` (по умолчанию 85%) и `imageGCLowThresholdPercent` (по умолчанию 80%) в KubeletConfiguration. Когда использование `imagefs` превышает high threshold, kubelet удаляет образы, не используемые ни одним подом, пока использование не опустится ниже low threshold. Также работает параметр `imageMinimumGCAge` (по умолчанию 2m) — минимальный возраст образа перед удалением.

**Admission Controller (Контролер допуска)** — компонент API Server, перехватывающий запросы к Kubernetes и применяющий политики до сохранения объекта. В контексте образов relevantны:
- **ImagePolicyWebhook** — внешний вебхук, проверяющий образы по white/black list перед запуском.
- **ValidatingAdmissionPolicy** — нативная Kubernetes 1.26+ политика без внешних зависимостей.
- **Kyverno / Gatekeeper** — OPA-совместимые контроллеры для聲明式 проверки образов (подпись, источник, теги).

**Rate Limit (Ограничение частоты запросов)** — политика реестра, ограничивающая количество pull/push операций за период. Docker Hub: 100 pull/6h для анонимных, 200 pull/6h для авторизованных (бесплатный аккаунт), 5000 pull/6h (Pro). При превышении — ответ `429 Too Many Requests`. Решения: использовать pull-through cache (Harbor proxy cache), авторизованные запросы, или локальные зеркала.

**Pull-Through Cache (Кэш с проксированием)** — режим реестра (Harbor, Nexus, Docker Registry), при котором запросы к публичным образам проксируются на upstream-реестр, а результат кэшируется локально. Последующие pull идут из кэша без обращения к внешнему реестру. Снижает задержку, экономит трафик и защищает от rate limiting. В Harbor настраивается как "Proxy Cache Project", в containerd — через `hosts.toml` с указанием upstream server.

**Proxy Registry (Проксирующий реестр)** — реестр, работающий в режиме промежуточного звена между рантаймом и upstream-реестром. Отличается от Pull-Through Cache тем, что может выполнять трансформацию запросов (добавление заголовков, переименование репозиториев) и агрегацию нескольких upstream'ов в единый namespace. Примеры: Nexus Repository (docker-proxy + docker-group), Harbor (Proxy Cache), ChartMuseum для Helm-чартов. В Kubernetes используется через `hosts.toml` containerd или `registries.conf` CRI-O.

**Snapshotter (Драйвер снимков)** — плагин containerd, отвечающий за подготовку файловой системы контейнера из распакованных слоев образа. Каждый снимок (snapshot) — это записываемый слой, смонтированный поверх read-only базовых слоев через UnionFS (обычно OverlayFS). Типы: `overlayfs` (стандартный, ядро Linux), `fuse-overlayfs` (для rootless containerd), `btrfs`, `zfs`. Выбор snapshotter влияет на производительность распаковки и использования дискового пространства. Путь хранения: `/var/lib/containerd/io.containerd.snapshotter.v1.<driver>/`.

**OCI Artifacts** — механизм хранения произвольных данных (Helm-чарты,签名,SBOM,库存 образов) в OCI-совместимых реестрах, используя стандартный OCI Image Spec для описания манифестов. Артефакт presenting как OCI Artifact имеет `mediaType`, специфичный для типа данных (например, `application/vnd.cncf.helm.chart.v1+json` для Helm), и хранится в том же реестре, что и образы контейнеров. Это позволяет использовать единый реестр для всех артефактов CI/CD.

**dockerconfigjson** — JSON-формат файла аутентификации, используемый Kubernetes для доступа к приватным реестрам. Структура: `{"auths": {"<registry>": {"auth": "<base64(user:password)>"}}}`. Поле `auth` содержит base64-кодированную строку `username:password` (не токен). Kubernetes-объект `Secret` типа `kubernetes.io/dockerconfigjson` хранит этот JSON в ключе `.dockerconfigjson`. Рантайм (containerd, CRI-O) разбирает этот файл при попытке pull'а и передаёт credentials в HTTP-заголовке `Authorization: Basic <auth>`.

**Blob (Слой/Блоб)** — неизменяемый кусок данных, являющийся содержимым одного слоя образа. Идентифицируется SHA256-хешем содержимого (Content Addressable). Один blob может переиспользоваться между разными образами, если его digest совпадает (cross-repository mounting). При pull'е рантайм проверяет, существует ли blob локально (`/var/lib/containerd/io.containerd.content.v1.content/blobs/sha256/`), и скачивает только отсутствующие. При push'е blobs загружаются через POST → PATCH → PUT API OCI Distribution.

---

## Основные концепции

### Формат ссылки на образ (Image Reference)

Каждый образ в Kubernetes идентифицируется строкой, которая разбирается рантаймом следующим образом:

```
[registry/][repository/]name[:tag][@digest]
```

| Компонент | Описание | Пример | Обязательность |
| :--- | :--- | :--- | :--- |
| `registry` | DNS-имя сервера (с портом если нестандартный) | `harbor.local:5000` | Если не указан — Docker Hub |
| `repository` | Путь к репозиторию в реестре | `myproject/backend` | Если не указан — `library/` |
| `name` | Имя образа | `nginx` | Обязательный |
| `tag` | Мутабельный идентификатор версии | `1.25` | Если не указан — `latest` |
| `digest` | Иммутабельный SHA256 хеш манифеста | `@sha256:abc123...` | Полный пиннинг |

**Порядок разрешения:**
1. Если указан `@sha256:...` — используется только digest (тег игнорируется)
2. Если указан `:tag` — разрешается тег в реестре
3. Если ни тег, ни digest не указаны — подразумевается `:latest`

**Антипаттерн:** Использование `:latest` без явного указания `imagePullPolicy: Always` приводит к неочевидному поведению: kubelet может использовать устаревший локальный образ.

### Жизненный цикл загрузки образа (Image Pull Lifecycle)

Процесс загрузки образа — это многоэтапная операция, выполняемая рантаймом по запросу `kubelet`:

1. **Resolution:** Получение манифеста образа из реестра по имени/тегу или дайджесту.
2. **Layer Deduplication (Cross-repository blob mounting):** Рантайм проверяет локальный кэш слоев (`/var/lib/containerd` или `/var/lib/containers`). Если слой с таким же SHA256 уже существует (даже от другого образа), он не скачивается повторно.
3. **Parallel Download:** Скачивание недостающих слоев. Количество параллельных потоков управляется параметрами рантайма (например, `max_concurrent_downloads` в containerd).
4. **Verification:** Проверка контрольных сумм скачанных слоев.
5. **Unpacking & Snapshotting:** Распаковка слоев и создание "снимка" (snapshot) файловой системы, который будет смонтирован как Read-Only слой контейнера.

### Полный путь pull-операции: Kubelet -> CRI -> Registry

Понимание полного цепочки вызовов критично для диагностики: ошибка на каждом этапе даёт характерные симптомы.

```
Kubelet                        CRI-плагин                     containerd/CRI-O              OCI Registry
  │                                │                                │                            │
  ├─ PullImage(gRPC) ─────────────►│                                │                            │
  │                                ├─ Разбор imageRef ──────────────►│                            │
  │                                │  (имя, registry, тег/digest)   │                            │
  │                                │                                ├─ HTTP GET /v2/<name>       │
  │                                │                                │  /manifests/<ref> ────────►│
  │                                │                                │◄─── 200 + JSON манифест ───│
  │                                │                                ├─ HTTP GET /v2/<name>       │
  │                                │                                │  /blobs/<digest> ──────────►│
  │                                │                                │◄─── 200 + stream ──────────│
  │                                │                                ├─ verify digest              │
  │                                │                                ├─ unpack → snapshot ────────►│ /var/lib/containerd/
  │                                │◄─── PullImageResponse ─────────│                            │  io.containerd.snapshotter.v1/
  │◄─── Success/Error ────────────│                                │                            │
```

**Типичные точки отказа:**

| Этап | Компонент | Ошибка | Симптом |
| :--- | :--- | :--- | :--- |
| **1. Name Resolution** | DNS узла | `no such host` | Pull не начинается |
| **2. TLS Handshake** | containerd ↔ Registry | `x509: certificate signed by unknown authority` | Pull зависает на conectar |
| **3. Manifest Fetch** | Registry API | `manifest unknown` / `404` | `ErrImagePull` сразу |
| **4. Blob Download** | Network/Registry | `i/o timeout` / `connection refused` | `ErrImagePull` с задержкой |
| **5. Digest Verification** | containerd | `unauthorized` / `content verification failed` | `ErrImagePull` после скачивания |
| **6. Unpacking** | Snapshotter | `no space left on device` / `failed to extract layer` | `ErrImagePull` на финальном этапе |

**Важно:** Kubelet НЕ участвует в сетевом взаимодействии с реестром напрямую — он делает gRPC-вызов к CRI-плагину, который выполняет HTTP-запросы к реестру из host network namespace. Это означает, что NetworkPolicy уровня пода **не влияет** на pull; влияют только правила хоста (iptables/nftables) и GlobalNetworkPolicy (Calico/Cilium).

### Клиентская side: разрешение имён и конфигурация registry

Рантайм контейнеров (containerd, CRI-O) разбирает имя образа и определяет, к какому реестру обращаться, через несколько уровней конфигурации:

**Порядок разрешения имени образа:**

```
image: harbor.local/myproject/app:v1.2.0@sha256:abc123
  │         │           │        │         │
  │         │           │        │         └─ digest (если указан — тег игнорируется)
  │         │           │        └─ tag (defaults to "latest")
  │         │           └─ repository
  │         └─ registry (если не указан — Docker Hub)
  └─ полный путь
```

**Конфигурация реестров в containerd (`/etc/containerd/certs.d/`):**

```
/etc/containerd/certs.d/
├── _default/                          # Для реестров без явной конфигурации
│   └── hosts.toml
├── docker.io/                         # Для образов docker.io/*
│   └── hosts.toml
├── harbor.local/                      # Для образов harbor.local/*
│   └── hosts.toml
└── registry.k8s.io/                   # Для образов registry.k8s.io/*
    └── hosts.toml
```

**Пример `hosts.toml` для Docker Hub с зеркалом:**

```toml
# /etc/containerd/certs.d/docker.io/hosts.toml
server = "https://registry-1.docker.io"

[host."https://harbor.local/docker-hub-proxy"]
  capabilities = ["pull", "resolve"]
  override_path = true
  ca = "/etc/containerd/certs.d/harbor.local/ca.crt"
```

**Логика при pull'е:** containerd перебирает хосты в порядке их появления в `hosts.toml`. Первый успешный ответ используется. Если указан `server` (upstream) и дополнительные хосты (mirror), containerd сначала пробует mirror, при неудаче — upstream.

**Конфигурация в CRI-O (`/etc/containers/registries.conf`):**

```toml
# /etc/containers/registries.conf
unqualified-search-registries = ["docker.io"]

[[registry]]
prefix = "docker.io"
location = "docker.io"

[[registry.mirror]]
location = "harbor.local/docker-hub-proxy"
insecure = false
```

### Параллелизм и производительность

По умолчанию загрузка образов может быть узким местом при массовом запуске подов:

- **`serializeImagePulls` (Kubelet):** Параметр (по умолчанию `true` в старых версиях), заставляющий Kubelet скачивать образы строго по одному. В высоконагруженных кластерах рекомендуется устанавливать `false` для параллельной работы.
- **`maxParallelImagePulls` (Kubelet):** Ограничение количества одновременных gRPC-запросов `PullImage` к рантайму.
- **Lazy Pulling (stargz, nydus):** Продвинутые технологии, позволяющие запустить контейнер до полной загрузки всех слоев, скачивая данные "по требованию".

### Классификация ошибок и статус-коды CRI

Ошибки в логах рантайма (journalctl) обычно сопровождаются статус-кодами gRPC:

| Уровень | CRI/gRPC Error Code | Типовое сообщение | Возможная причина |
| :--- | :--- | :--- | :--- |
| **Реестр** | `NotFound` (5) | `manifest unknown` | Ошибка в имени или теге образа. |
| **Авторизация** | `Unauthenticated` (16) | `unauthorized` | Отсутствует или невалиден `imagePullSecret`. |
| **Права доступа** | `PermissionDenied` (7) | `access denied` | У учетной записи нет прав на `pull` в данном репозитории. |
| **Сеть** | `DeadlineExceeded` (4) | `connection timed out` | Проблемы DNS, Firewall или MTU. |
| **Ресурсы** | `ResourceExhausted` (8) | `no space left` | Переполнение диска на узле. |
| **Rate Limit** | `Unavailable` (14) | `429 Too Many Requests` | Превышены лимиты реестра (например, Docker Hub). |

### Политики загрузки (imagePullPolicy)

| Политика | Поведение | Рекомендация |
| :--- | :--- | :--- |
| **`Always`** | Проверка манифеста в реестре при каждом запуске. | Обязательно для `:latest` и изменчивых тегов. |
| **`IfNotPresent`** | Использование локального образа, если он есть. | Стандарт для версионных тегов (v1.2.3). |
| **`Never`** | Работа только с локальным кэшем. | Изолированные (Air-gapped) среды. |

**Важно:** Если `imagePullPolicy` не указана, но тег образа — `:latest`, Kubernetes автоматически установит политику `Always`.

### Манифест и Manifest List

**Манифест (Manifest)** — JSON-документ, описывающий структуру образа: список слоёв (config, rootfs layers), размеры, media type и digest каждого слоя. Каждый слой — это дельта файловой системы, aplikable через OverlayFS.

```json
{
  "schemaVersion": 2,
  "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
  "config": { "digest": "sha256:abc...", "size": 5246 },
  "layers": [
    { "digest": "sha256:def...", "size": 7322831 },
    { "digest": "sha256:ghi...", "size": 155 }
  ]
}
```

**Manifest List (Multi-platform)** — обёртка над несколькими манифестами для разных платформ. При pull рантайм фильтрует по `os` и `architecture`:

```json
{
  "mediaType": "application/vnd.docker.distribution.manifest.list.v2+json",
  "manifests": [
    { "platform": { "os": "linux", "architecture": "amd64" }, "digest": "sha256:aaa..." },
    { "platform": { "os": "linux", "architecture": "arm64" }, "digest": "sha256:bbb..." }
  ]
}
```

### OCI Distribution Spec и Registry API

Реестры реализуют [OCI Distribution Specification](https://github.com/opendistribution/spec) — REST API для управления образами:

| Эндпоинт | Метод | Назначение |
| :--- | :--- | :--- |
| `GET /v2/` | GET | Проверка поддержки API v2 |
| `GET /v2/<name>/manifests/<reference>` | GET | Получение манифеста (по тегу или digest) |
| `PUT /v2/<name>/manifests/<reference>` | PUT | Загрузка манифеста |
| `GET /v2/<name>/blobs/<digest>` | GET | Скачивание слоя (blob) |
| `POST /v2/<name>/blobs/uploads/` | POST | Инициация загрузки слоя |
| `GET /v2/<name>/tags/list` | GET | Список тегов в репозитории |

Аутентификация: реестр возвращает `401 Unauthorized` с заголовком `WWW-Authenticate`, содержащим URL-адрес токена. Клиент получает токен и повторяет запрос с `Authorization: Bearer <token>`.

### Image Garbage Collection — пороги и поведение

Kubelet мониторит использование `imagefs` (файловая система, содержащая образы) и запускает сборку мусора при достижении порогов:

```
imagefs.used > imageGCHighThresholdPercent (85%) → начало GC
  ↓
Удаление образов (приоритет: возраст, отсутствие подов)
  ↓
imagefs.used < imageGCLowThresholdPercent (80%) → остановка GC
```

**Параметры в KubeletConfiguration:**
```yaml
kubeletConfiguration:
  imageGCHighThresholdPercent: 85
  imageGCLowThresholdPercent: 80
  imageMinimumGCAge: "2m"
  imageMaximumGCAge: "0s"          # 0 = без ограничения возраста (K8s 1.30+)
  containerLogsMaxSize: "10Mi"
  maxPods: 110
```

**Важно:** Сборка мусора не удаляет образы, используемые запущенными подами. Это может привести к конфликту: disk pressure с одной стороны и невозможность удаления образов — с другой. Решение — увеличить диск или снизить `imageGCHighThresholdPercent`.

### Admission Controllers для проверки образов

Kubernetes позволяет блокировать запуск подов с непроверенными образами через admission control:

**1. ImagePolicyWebhook (встроенный):**
```yaml
# /etc/kubernetes/admission-config.yaml
apiVersion: apiserver.config.k8s.io/v1
kind: AdmissionConfiguration
plugins:
  - name: ImagePolicyWebhook
    configuration:
      imagePolicy:
        kubeConfigFile: /etc/kubernetes/webhook-config.yaml
        allowTTL: 50
        denyTTL: 50
        retryBackoff: 500ms
        defaultAllow: false
```

**2. Kyverno ( Community):**
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-image-source
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-registry
      match:
        resources:
          kinds: ["Pod"]
      validate:
        message: "Образы должны загружаться из Harbor"
        pattern:
          spec:
            containers:
              - image: "harbor.local/*"
```

**3. ValidatingAdmissionPolicy (Kubernetes 1.26+, нативный):**
```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: "image-policy.example.com"
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
  validations:
    - expression: "!object.spec.containers.exists(c, !c.image.startsWith('harbor.local/'))"
      message: "Все образы должны быть из Harbor"
```

### Способы предоставления учетных данных

**1. Pod Spec (`imagePullSecrets`):** Прямое указание в манифесте.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx
spec:
  containers:
    - name: nginx
      image: harbor.local/library/nginx:1.25
  imagePullSecrets:
    - name: registry-creds  # Secret в том же namespace
```

**2. ServiceAccount:** Секрет прописывается в SA, и все поды, использующие этот SA, наследуют доступ.

```bash
# Патч ServiceAccount по умолчанию в namespace
kubectl patch serviceaccount default -n my-namespace \
  -p '{"imagePullSecrets": [{"name": "registry-creds"}]}'

# Проверка
kubectl get serviceaccount default -n my-namespace -o yaml
```

**3. PodSecurity Admission (вместо ImagePolicyWebhook):**
Для простых случаев можно использовать PodSecurity Admission с policy `restricted`, которая требует указания `imagePullPolicy: Always` или digest-пиннинга.

---

## Практические сценарии

### Сценарий 1: Создание imagePullSecrets через kubectl

```bash
# Способ 1: Явное создание секрета
kubectl create secret docker-registry registry-creds \
  --docker-server=harbor.local \
  --docker-username=admin \
  --docker-password=Harbor12345 \
  --docker-email=admin@harbor.local \
  -n my-namespace

# Способ 2: Из существующего .docker/config.json
kubectl create secret generic registry-creds \
  --from-file=.dockerconfigjson=$HOME/.docker/config.json \
  --type=kubernetes.io/dockerconfigjson \
  -n my-namespace

# Способ 3: Из зашифрованного JSON (для GitOps)
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: registry-creds
  namespace: my-namespace
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: $(base64 < $HOME/.docker/config.json)
EOF
```

**Проверка валидности секрета:**
```bash
kubectl get secret registry-creds -n my-namespace \
  -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .
# → должен содержать {"auths":{"harbor.local":{"auth":"..."}}}
```

### Сценарий 2: Мониторинг фаз через события

Разделение фактической ошибки и периода ожидания:

```bash
kubectl describe pod <pod-name>
```

**Разбор событий (Events):**
- `Pulling image "..."`: Kubelet инициировал запрос.
- `Failed to pull image`: Фактический момент `ErrImagePull`.
- `Back-off pulling image`: Вход в состояние `ImagePullBackOff`.

**Детальный просмотр JSON-событий:**
```bash
kubectl get events --field-selector reason=Failed \
  --sort-by='.lastTimestamp' -n my-namespace

# Или для конкретного пода
kubectl get events --field-selector involvedObject.name=<pod-name> \
  --sort-by='.lastTimestamp' -o wide
```

### Сценарий 3: Анализ логов рантайма (низкий уровень)

Если `kubectl describe` не дает деталей, необходимо смотреть логи CRI на узле:

```bash
# Для containerd
journalctl -u containerd | grep -i "pull\|error\|fail"

# Для CRI-O
journalctl -u crio | grep -i "pull\|error\|fail"

# С фильтрацией по времени (последние 10 минут)
journalctl -u containerd --since "10 minutes ago" | grep -i "pull\|error"
```

*Здесь можно увидеть детальные ошибки TLS, проблемы с сертификатами или специфические ответы Registry.*

### Сценарий 4: Проверка наличия образа через skopeo

`skopeo inspect` позволяет проверить, существует ли образ в реестре, и получить его метаданные без скачивания:

```bash
# Проверка существования образа
skopeo inspect docker://harbor.local/library/nginx:1.25

# Проверка манифеста (включая multi-arch)
skopeo inspect --raw docker://harbor.local/library/nginx:1.25 | jq .

# Проверка аутентификации
skopeo inspect --raw --creds admin:password docker://harbor.local/private/app:v1

# Проверка конкретного digest (для пиннинга)
skopeo digest docker://harbor.local/library/nginx:1.25
```

### Сценарий 5: Диагностика архитектурного несоответствия

Когда образ существует, но не для архитектуры целевого узла:

```bash
# Проверка архитектуры узла
kubectl get node <node-name> -o jsonpath='{.status.nodeInfo.architecture}'
# → amd64 или arm64

# Проверка манифестов образа
skopeo inspect --raw docker://harbor.local/library/nginx:1.25 | \
  jq '.manifests[].platform'

# Пример вывода:
# {"os":"linux","architecture":"amd64"}
# {"os":"linux","architecture":"arm64","variant":"v8"}

# Если образ mono-arch — пересоберите для нужных платформ
# docker buildx build --platform linux/amd64,linux/arm64 -t harbor.local/app:v1 --push .
```

### Сценарий 6: Диагностика DNS-резолва для реестра

```bash
# С узла (kubelet работает в host network)
nslookup harbor.local
# → должен вернуть IP реестра

# Из пода (для проверки CoreDNS)
kubectl run dns-test --image=busybox --rm -it --restart=Never -- \
  nslookup harbor.local

# Проверка /etc/resolv.conf на узле
cat /etc/resolv.conf

# Если DNS не настроен — добавить в /etc/hosts на всех узлах
echo "192.168.1.100 harbor.local" | sudo tee -a /etc/hosts
```

### Сценарий 7: Проверка rate limit Docker Hub

```bash
# Проверка оставшихся pull (для Docker Hub)
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)
curl -I -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/manifests/latest
# → X-RateLimit-Remaining: 199 (для авторизованного)

# Для анонимных запросов
curl -I https://registry-1.docker.io/v2/library/nginx/manifests/latest
# → X-RateLimit-Limit: 100
# → X-RateLimit-Remaining: 97
```

### Сценарий 8: Использование crictl для отладки

```bash
# Проверка конфигурации рантайма
crictl info | jq .config

# Просмотр sandbox_image
crictl info | jq -r '.config.containerdConfigPath // empty'

# Ручной pull образа (с detailed output)
crictl pull --debug harbor.local/library/nginx:1.25

# Список локальных образов
crictl images | grep nginx

# Инспекция образа
crictl inspecti harbor.local/library/nginx:1.25
```

### Сценарий 9: Конфигурация containerd для приватного реестра

Настройка containerd для доступа к реестру с самоподписанным сертификатом и аутентификацией:

**1. Создание каталога конфигурации:**

```bash
# Создать каталог для конкретного реестра
sudo mkdir -p /etc/containerd/certs.d/harbor.local

# Для Docker Hub (зеркалирование)
sudo mkdir -p /etc/containerd/certs.d/docker.io
```

**2. Конфигурация `hosts.toml` для Harbor:**

```toml
# /etc/containerd/certs.d/harbor.local/hosts.toml
server = "https://harbor.local"

[host."https://harbor.local"]
  capabilities = ["pull", "resolve", "push"]
  ca = "/etc/containerd/certs.d/harbor.local/ca.crt"
  # Для аутентификации — credentials хранятся в imagePullSecrets пода,
  # а не в hosts.toml. hosts.toml настраивает TLS и capabilities.
```

**3. Включение `config_path` в `config.toml`:**

```bash
# Включить поддержку hosts.toml каталога
sudo sed -i 's|config_path = ""|config_path = "/etc/containerd/certs.d"|' \
  /etc/containerd/config.toml

# Проверить, что config_path установлен
grep 'config_path' /etc/containerd/config.toml
# → config_path = "/etc/containerd/certs.d"
```

**4. Проверка и перезапуск:**

```bash
# Валидация конфигурации
sudo containerd config dump > /dev/null && echo "OK"

# Перезапуск containerd
sudo systemctl restart containerd

# Проверка, что конфигурация применена
sudo ctr -n k8s.io images pull --host docker.io \
  harbor.local/library/nginx:1.25
```

### Сценарий 10: Настройка незащищенного реестра (HTTP)

Для реестров без TLS (разработка, lab-окружение) необходимо явно разрешить HTTP-доступ:

**1. containerd:**

```toml
# /etc/containerd/certs.d/registry.local:5000/hosts.toml
server = "http://registry.local:5000"

[host."http://registry.local:5000"]
  capabilities = ["pull", "resolve", "push"]
  # skip_verify не нужен для HTTP
```

**2. Дополнительно в `config.toml`:**

```toml
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".registry.mirrors."registry.local:5000"]
  endpoint = ["http://registry.local:5000"]

[plugins."io.containerd.grpc.v1.cri".registry.configs."registry.local:5000".tls]
  insecure_skip_verify = true
```

**3. CRI-O:**

```toml
# /etc/containers/registries.conf
[[registry]]
prefix = "registry.local:5000"
location = "registry.local:5000"
insecure = true
```

**4. kubelet (для `--image-credential-provider-config`):**

```yaml
# /etc/kubernetes/image-credential-provider-config.yaml
apiVersion: kubelet.config.k8s.io/v1
kind: CredentialProviderConfig
providers:
  - name: my-registry
    matchImages:
      - "registry.local:5000"
    defaultCacheDuration: "10m"
```

**Важно:** Незащищенные реестры допустимы только в dev/test. В production используйте TLS с валидным или самоподписанным сертификатом (CA должен быть в доверенных на узле).

### Сценарий 11: Диагностика через HTTP API реестра

Прямые HTTP-запросы к реестру позволяют отделить проблемы сети/TLS от проблем рантайма:

```bash
# 1. Проверка поддержки API v2
curl -s https://harbor.local/v2/ | jq .
# → {} (пустой JSON = OK)
# → {"errors":[{"code":"UNAUTHORIZED","message":"authentication required"}]} = нужна аутентификация

# 2. Получение токена (для реестров с токенной аутентификацией)
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/nginx:pull" | jq -r .token)

# 3. Проверка манифеста
curl -s -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/manifests/1.25 | jq .config.digest
# → "sha256:abc123..."

# 4. Проверка конкретного слоя (blob)
curl -sI -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/blobs/sha256:def456...
# → HTTP/1.1 200 OK
# → Content-Length: 7322831

# 5. Список тегов
curl -s -H "Authorization: Bearer $TOKEN" \
  https://registry-1.docker.io/v2/library/nginx/tags/list | jq .tags[:5]
# → ["1.25", "1.25-alpine", "1.25-bookworm", ...]
```

**Интерпретация результатов:**

| Ответ | Значение | Следующий шаг |
| :--- | :--- | :--- |
| `200 OK` + JSON | Реестр доступен, API v2 работает | Проверять auth и credentials |
| `401 Unauthorized` + `WWW-Authenticate` | Требуется аутентификация | Создать/обновить imagePullSecret |
| `403 Forbidden` | Auth прошла, но нет прав на pull | Проверить RBAC в реестре |
| `404 Not Found` | Образ/тег не существует | Проверить имя образа и тег |
| `429 Too Many Requests` | Rate limit | Подождать или использовать authenticated pull |
| `connection refused` | Реестр недоступен | Проверить сетевую доступность |
| `certificate signed by unknown authority` | CA не доверен | Добавить CA в `/usr/local/share/ca-certificates/` |

### Сценарий 12: Проверка и ротация imagePullSecrets

**1. Валидация содержимого секрета:**

```bash
# Декодирование и проверка JSON
kubectl get secret registry-creds -n my-namespace \
  -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .

# Ожидаемый вывод:
# {
#   "auths": {
#     "harbor.local": {
#       "auth": "YWRtaW46SGFyYm9yMTIzNDU=",
#       "email": ""
#     }
#   }
# }

# Проверка декодированного auth (username:password)
kubectl get secret registry-creds -n my-namespace \
  -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | \
  jq -r '.auths["harbor.local"].auth' | base64 -d
# → admin:Harbor12345
```

**2. Тест pull'а с конкретным секретом (на узле):**

```bash
# Извлечь токен из секрета и использовать с crictl
TOKEN=$(kubectl get secret registry-creds -n my-namespace \
  -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | \
  jq -r '.auths["harbor.local"].auth')

sudo crictl pull --creds "$(echo $TOKEN | base64 -d)" \
  harbor.local/library/nginx:1.25
```

**3. Массовая проверка секретов в кластере:**

```bash
# Список всех Secret типа docker-registry с указанием namespace
kubectl get secrets -A --field-selector type=kubernetes.io/dockerconfigjson \
  -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,AGE:.metadata.creationTimestamp

# Проверка, какие ServiceAccount используют какие секреты
kubectl get sa -A -o json | \
  jq -r '.items[] |
    select(.imagePullSecrets != null) |
    "\(.metadata.namespace)/\(.metadata.name): \([.imagePullSecrets[].name] | join(", "))"'
# → kube-system/default: regcred-cluster
# → production/app-sa: regcred-prod
```

**4. Проверка возраста секретов (для ротации):**

```bash
# Secrets старше 90 дней
kubectl get secrets -A --field-selector type=kubernetes.io/dockerconfigjson \
  -o json | jq -r '
  .items[] |
  select((now - (.metadata.creationTimestamp | fromdateiso8601)) > 7776000) |
  "\(.metadata.namespace)/\(.metadata.name) — создан: \(.metadata.creationTimestamp)"'
# → production/old-creds — создан: 2025-12-15T10:30:00Z
```

---

## Дополнительная информация

### Связанные темы

- [Распространённые ошибки и решения](./common_errors.md) — детальный разбор ошибок (404, 401, 403) и типовых сценариев.
- [Пошаговая диагностика](./diagnostics.md) — алгоритм действий для инженера (L1-L5).
- [Лучшие практики и предотвращение](./best_practices.md) — рекомендации по стабильности и безопасности.
- [Air-gapped кластеры](./airgapped.md) — особенности работы в изолированных сетях.
- [Сетевые проблемы](./network_issues.md) — отладка DNS, MTU и прокси.
- [NetworkPolicy и доступ к реестру](./network_policy_impact.md) — влияние NetworkPolicy и GlobalNetworkPolicy на image pull.
- [Pod Security Standards и image pull](./pod_security_standards.md) — PSS/PSA и их влияние на загрузку образов.
- [HPA и автоскейлинг](./hpa_and_scaling.md) — влияние масштабирования на image pull и rate limiting.
- [Init-контейнеры и image pull](./init_container_image_pulls.md) — проблемы pull в init-контейнерах.
- [Среды выполнения контейнеров](../../../Concepts/container_runtime.md) — детальный обзор архитектуры CRI и containerd.

