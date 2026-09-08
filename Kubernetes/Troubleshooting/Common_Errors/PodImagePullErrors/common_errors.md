# Ошибки загрузки образов (Image Pull Errors): Распространённые ошибки

## Определения

В данном разделе рассматриваются конкретные коды ошибок и технические ситуации, приводящие к состояниям `ErrImagePull` и `ImagePullBackOff`. Базовые термины и жизненный цикл процесса описаны в разделе [Определения](./definitions.md).

---

## Основные концепции

### Классификация типовых ошибок и статус-коды

Ошибки загрузки транслируются от реестра через Container Runtime Interface (CRI) в события Kubernetes. Понимание gRPC статус-кодов помогает при анализе логов `containerd` или `CRI-O`.

| Код / Сообщение | gRPC Code | Категория | Корневая причина |
| :--- | :--- | :--- | :--- |
| `manifest not found` | `NotFound` (5) | Образ / Тег | Опечатка в имени, отсутствие тега или архитектуры. |
| `unauthorized` (401) | `Unauthenticated` (16) | Аутентификация | Отсутствует `imagePullSecrets`, неверные креды. |
| `forbidden` (403) | `PermissionDenied` (7) | Авторизация | Нет прав на Pull (даже если логин верен). |
| `too many requests` (429) | `Unavailable` (14) | Лимиты | Превышена квота (Rate Limit) реестра (Docker Hub). |
| `connection refused` | `Internal` (13) | Сеть | Реестр недоступен, неверный порт, блокировка Firewall. |
| `deadline exceeded` | `DeadlineExceeded` (4) | Доступность | Таймаут сети, проблемы с MTU или прокси. |
| `failed to extract layer` | `Internal` (13) | Хранилище | Повреждение слоев, ошибки Snapshotter (OverlayFS). |
| `no space left on device` | `Internal` (13) | Хранилище | Переполнение `imagefs` или root FS, нет inodes. |
| `i/o timeout` / `TLS handshake timeout` | `DeadlineExceeded` (4) | Сеть | MTU/PMTUD, прокси, длинный путь через firewall. |
| `access denied` (на уровне ImagePolicyWebhook) | `PermissionDenied` (7) | Политика | Admission Controller отклонил образ. |

### Политика загрузки (`imagePullPolicy`) и её влияние на ошибки

`imagePullPolicy` управляет тем, **когда** `kubelet` пытается связаться с реестром. Неправильная комбинация политики и тега — частая косвенная причина `ImagePullBackOff`, особенно в CI/CD-сценариях.

| Политика | Когда обращается к реестру | Типичные ошибки |
| :--- | :--- | :--- |
| `Always` | При **каждом** запуске контейнера, даже если образ уже в локальном кэше | Лавина pull-запросов → `429 Too Many Requests`; нагрузка на реестр при массовом `kubectl rollout`. |
| `IfNotPresent` (по умолчанию для тегов, отличных от `:latest`) | Только если образа нет в кэше узла | Несоответствие тега локального образа и реестра: после `docker push :v1` старые поды продолжают использовать старый digest, новые — новый. |
| `Never` | Никогда | Если образ не предзагружен (`ctr image import`, `nerdctl load`), гарантированный `ImagePullBackOff`. Применяется только в air-gapped кластерах с предзагрузкой. |

**Антипаттерны, приводящие к ошибкам:**
- `image: myapp:latest` + `imagePullPolicy: IfNotPresent` (по умолчанию для latest — `Always`, но при перезаписи манифеста без тега возможно несоответствие). Исправить: явно указать тег и `IfNotPresent` или digest.
- `image: myapp:1.0` + `imagePullPolicy: Always` в кластере с высокой плотностью подов → превышение квоты Docker Hub.

### Параметры троттлинга pull-запросов

`kubelet` ограничивает частоту обращений к реестру параметрами `--registry-pull-qps` (queries per second, **по умолчанию 5**) и `--registry-burst` (пиковый размер burst, **по умолчанию 10**). Эти лимиты:
- Распространяются **на каждый реестр в отдельности**, не суммарно.
- Могут быть причиной медленной загрузки образов на узлах с большим количеством подов (например, при `Deployment` с replicas=100 и image=`:latest`).
- При `registryBurst: 10` параллельно стартующие поды сериализуются, что в сочетании с медленным реестром увеличивает `Back-off pulling image` задержки.

**Алгоритм Back-off** для неудачных pull: `10s → 20s → 40s → 80s → 160s → 300s` (cap 5 минут), сбрасывается при успешной попытке. После перезапуска kubelet счётчик сбрасывается — поды сразу повторяют попытку.

---

## Практические сценарии

### Сценарий 1: Неверное имя или тег образа (Manifest Not Found)

**Симптом:**
В `kubectl describe pod` отображается ошибка `manifest for <image>:<tag> not found`.

**Причина:**
Указанный тег не существует в реестре. Часто случается при использовании динамических версий (хеш коммита), которые еще не были запушены CI/CD.

**Решение:**
1.  Проверьте наличие образа через `skopeo inspect docker://registry.io/app:tag`.
2.  Убедитесь, что в имени образа нет лишних символов (пробелов, кавычек) и соблюден регистр (Case Sensitivity).

### Сценарий 2: Ошибки аутентификации в приватных реестрах (401 Unauthorized)

**Симптом:**
Ошибка `unauthorized: authentication required` или `pull access denied`.

**Причина:**
`kubelet` не смог найти или использовать валидные учетные данные.

**Решение:**
1.  Создайте секрет в нужном Namespace: `kubectl create secret docker-registry regcred ...`.
2.  **Глобальное решение:** Привяжите секрет к `ServiceAccount`, чтобы он автоматически добавлялся во все поды:
    ```bash
    kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}'
    ```

### Сценарий 3: Превышение лимитов Docker Hub (429 Too Many Requests)

**Симптом:**
Ошибка `toomanyrequests: You have reached your pull rate limit`.

**Решение:**
1.  **Auth:** Используйте `imagePullSecret` даже для бесплатных аккаунтов (лимиты повышаются со 100 до 200).
2.  **Mirroring:** Настройте локальное зеркало (Pull-through Cache) в Harbor.
3.  **Public Clouds:** Используйте зеркала облачных провайдеров (например, `mirror.gcr.io` или `public.ecr.aws`).

### Сценарий 4: Несоответствие архитектуры (Architecture Mismatch)

**Симптом:**
Образ скачивается, но контейнер не запускается с ошибкой `exec format error` или в логах CRI видна ошибка `no matching manifest for linux/amd64 in the manifest list`.

**Причина:**
Попытка запустить образ, собранный под `arm64`, на узле с архитектурой `amd64` (или наоборот).

**Решение:**
1.  Проверьте поддерживаемые архитектуры образа: `skopeo inspect --raw docker://registry.io/app:tag | jq .manifests`.
2.  Используйте Multi-arch сборки (Docker Buildx / Buildah) для поддержки обоих типов узлов.

### Сценарий 5: Истечение токенов в облачных реестрах (ECR / Artifact Registry)

**Симптом:**
Поды успешно запускались в течение первых 12 часов, но затем начали падать с `ImagePullBackOff`.

**Причина:**
Токены аутентификации AWS ECR или Google Artifact Registry временные (обычно 12ч). Если вы создали статический `Secret` вручную, он протухнет.

**Решение:**
1.  **IAM Roles:** Используйте механизмы интеграции провайдера (IRSA в AWS, Workload Identity в GCP). В этом случае `kubelet` сам получает токен.
2.  **Helper:** Используйте автоматические обновители секретов (например, `aws-ecr-credential-helper` или CronJob для `kubectl create secret`).

### Сценарий 6: Ошибки Snapshotter и Snapshot Layer Corruption

**Симптом:**
Ошибка `failed to get shared layer` или `failed to extract layer`.

**Причина:**
Повреждение локального кэша образов на узле из-за сбоев диска, жесткой перезагрузки узла или багов в драйвере OverlayFS.

**Решение:**
1.  Очистите кэш образов на проблемном узле: `crictl rmi --prune`.
2.  Если проблема сохраняется, удалите содержимое `/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs` и перезапустите рантайм.

### Сценарий 7: Проблемы с TLS и сертификатами (x509)

**Симптом:**
`x509: certificate signed by unknown authority`.

**Решение:**
1.  Добавьте CA сертификат в `/usr/local/share/ca-certificates/` на всех узлах и выполните `update-ca-certificates`.
2.  Для `containerd` используйте `hosts.toml` для настройки `ca = "/path/to/ca.crt"` без изменения системного хранилища.

### Сценарий 8: Использование неизменяемых (Immutable) образов

**Проблема:**
Использование тега `:latest` или изменяемых версий (например, `:stable`) может привести к тому, что разные узлы кластера будут запускать разные версии одного и того же образа из-за кэширования.

**Рекомендация:**
Используйте SHA256 digest для гарантированной идентичности:
```yaml
image: myregistry.io/my-app@sha256:45b23dee...
```
Это полностью исключает ошибки `manifest not found` для уже запущенных систем и повышает безопасность.

### Сценарий 9: Лавина pull-запросов из-за `imagePullPolicy: Always`

**Симптом:**
После `kubectl rollout restart deployment/app` или при первом деплое на свежем кластере значительная часть подов уходит в `ImagePullBackOff` с ошибкой `toomanyrequests` или `429 Too Many Requests`. На реестре (Docker Hub) видны сотни pull-запросов в минуту с одного IP-диапазона.

**Причина:**
`imagePullPolicy: Always` в сочетании с высокой плотностью подов (`replicas > 50`) и медленным реестром вызывает лавину запросов: `kubelet` обращается к реестру при каждом запуске контейнера, а `--registry-pull-qps` ограничивает только QPS на реестр, не учитывая уже активные соединения. Каждый retry при ответе 429 увеличивает back-off, но параллельные поды продолжают долбить реестр.

**Решение:**
1. **Снизить частоту pull:** Перейти на `imagePullPolicy: IfNotPresent` для версионных тегов (`v1.2.3`, sha256-digest). Это устраняет обращение к реестру при перезапуске пода, если образ уже на узле.
2. **Pin на digest:**
   ```yaml
   image: myregistry.io/my-app@sha256:45b23dee...
   imagePullPolicy: IfNotPresent
   ```
3. **Поднять лимиты kubelet** (если архитектурно допустимо): `--registry-pull-qps=20 --registry-burst=40` в конфигурации kubelet.
4. **Аутентификация для Docker Hub:** использовать `imagePullSecret` с токеном — лимит увеличивается с 100 до 200 pull/6h.

### Сценарий 10: Переполнение диска (`no space left on device`)

**Симптом:**
Поды успешно создаются, но переходят в `ErrImagePull` с сообщениями в логах рантайма:
```text
level=error msg="failed to extract layer" error="no space left on device"
level=error msg="failed to prepare extraction snapshot" error="no space left on device"
```
В `kubectl describe node` видны условия `DiskPressure=True` и `FreeDiskSpacePressure=True`.

**Причина:**
Недостаточно места на `imagefs` (том, где хранятся распакованные слои — обычно `/var/lib/containerd` или отдельный раздел) или на root FS для метаданных. Kubelet не может распаковать новый слой. Распространённый случай — множество уникальных образов на одном узле при активном CI/CD.

**Диагностика:**
```bash
# Свободное место и inodes
df -h /var/lib/containerd
df -ih /var/lib/containerd

# Размер кэша образов в containerd
sudo du -sh /var/lib/containerd/io.containerd.content.v1.content/

# Топ-10 самых тяжёлых образов
sudo crictl images | head

# Состояние ImageGC на узле (через API)
kubectl get <node-name> -o jsonpath='{.status.images[*].names}{"\n"}' | tr ',' '\n' | sort -u
```

**Решение:**
1. **Очистить неиспользуемые образы:**
   ```bash
   sudo crictl rmi --prune
   # или для containerd напрямую
   sudo ctr -n k8s.io images gc
   ```
2. **Настроить параметры ImageGC в KubeletConfiguration** (`/var/lib/kubelet/config.yaml`):
   ```yaml
   imageGCHighThresholdPercent: 85
   imageGCLowThresholdPercent: 80
   imageMinimumGCAge: 2m
   maxImagesInContainerd: 200  # удаление по количеству (опционально)
   ```
3. **Расширить том:** выделить отдельный раздел/диск под `/var/lib/containerd` (LVM, второй диск в облаке).
4. **Снизить разнообразие образов:** ввести единый базовый image (`FROM`), использовать Buildpacks, multi-stage для уменьшения слоёв.
5. **Проверить inode pressure:**
   ```bash
   df -ih /var/lib/containerd
   ```
   При малом числе inodes даже при наличии свободного места overlay-слои не создаются.

### Сценарий 11: Локальный pull-through кэш (Harbor/Nexus) для on-prem

**Симптом:**
Кластер за NAT или в изолированной сети. Все поды с образами из Docker Hub падают в `ImagePullBackOff` с `i/o timeout`. Прямой pull с узлов невозможен.

**Причина:**
Отсутствие on-prem зеркала публичных реестров. Каждый узел самостоятельно тянет образы через WAN, что медленно и приводит к превышению лимитов.

**Решение (Harbor Proxy Cache):**
1. В Harbor создать проект типа **Proxy Cache** (например, `docker-hub-proxy`), указать upstream = `https://registry-1.docker.io` и опционально фильтр по репозиториям.
2. Настроить перенаправление на уровне containerd через `hosts.toml`:
   ```toml
   # /etc/containerd/certs.d/docker.io/hosts.toml
   server = "https://registry-1.docker.io"
   [host."https://harbor.local"]
     capabilities = ["pull", "resolve"]
     skip_verify = true  # только если Harbor с self-signed
   ```
3. Образ `nginx:latest` теперь прозрачно резолвится через `harbor.local` — первый pull уходит на Docker Hub, последующие из кэша.

**Решение (Nexus Repository 3):**
- Создать `docker (proxy)` репозиторий с remote URL = `https://registry-1.docker.io` и настроить `http connector` для проксирования.
- В `hosts.toml`:
   ```toml
   server = "https://registry-1.docker.io"
   [host."https://nexus.local:18443"]
     capabilities = ["pull", "resolve"]
     override_path = true
   ```
- Для приватных образов в Nexus дополнительно настроить `docker (hosted)` и `docker (group)`.

**Альтернатива без изменения containerd:** использовать rewrite правило в `cri-containerd-cri` через `plugins."io.containerd.grpc.v1.cri".registry.configs.paths` в `/etc/containerd/config.toml`.

### Сценарий 12: HTTP-прокси с аутентификацией (Squid)

**Симптом:**
В корпоративной сети с прокси-сервером pull образов завершается с `407 Proxy Authentication Required` или `connection refused`. Напрямую Docker Hub недоступен (egress только через прокси).

**Решение:**
1. Настроить переменные окружения прокси в systemd-юните containerd:
   ```ini
   # /etc/systemd/system/containerd.service.d/http-proxy.conf
   [Service]
   Environment="HTTP_PROXY=http://proxy.local:3128"
   Environment="HTTPS_PROXY=http://proxy.local:3128"
   Environment="NO_PROXY=localhost,127.0.0.1,10.96.0.0/12,192.168.0.0/16,10.0.0.0/8,.svc,.cluster.local,<NODE_IPS>"
   ```
2. Для прокси с Basic/NTLM-аутентификацией — добавить credentials в URL:
   ```ini
   Environment="HTTPS_PROXY=http://username:password@proxy.local:3128"
   ```
   Или через файлы:
   ```ini
   EnvironmentFile=/etc/containerd/proxy.env
   ```
   `/etc/containerd/proxy.env`:
   ```bash
   HTTPS_PROXY=http://svc-proxy:P@ssw0rd@proxy.local:3128
   ```
   Ограничить права на файл: `chmod 600 /etc/containerd/proxy.env`.
3. **Важно:** `NO_PROXY` должен включать Service CIDR (по умолчанию `10.96.0.0/12`), Pod CIDR (зависит от CNI: Calico `192.168.0.0/16`, Cilium `10.0.0.0/8`), `localhost` и `.cluster.local`. Иначе kubelet не сможет связаться с API Server через прокси.
4. **Whitelist на Squid:** добавить домены реестров в `acl SSL_ports` и `http_access allow`:
   ```text
   acl registry_domains dstdomain registry-1.docker.io auth.docker.io harbor.local
   http_access allow localnet registry_domains
   ```
5. Применить:
   ```bash
   systemctl daemon-reload && systemctl restart containerd
   ```

**Проверка:** выполнить pull напрямую через containerd для исключения kubelet:
```bash
sudo ctr -n k8s.io images pull docker.io/library/alpine:3.19
```
Если ошибка воспроизводится — проблема на уровне рантайма/прокси. Если ctr успешен, а kubelet нет — проблема в `imagePullSecrets` или `imagePullPolicy`.

### Сценарий 13: Admission Controller блокирует pull (Kyverno/ImagePolicyWebhook)

**Симптом:**
Под не создаётся, в Events — `FailedCreate` или `Error from server (Forbidden)`. В логах webhook видно:
```text
resource Pod was blocked due to the following policies:
  restrict-image-registries:
    image 'docker.io/library/nginx:latest' is not allowed:
      registry 'docker.io' is not in the allowed list: ['harbor.local', 'registry.k8s.io']
```

**Причина:**
Политика Kyverno (или OPA Gatekeeper, или встроенный `ImagePolicyWebhook`) валидирует источник образа и отклоняет все реестры, не входящие в whitelist. Это нормальное поведение для security-первережного кластера, но при миграции или добавлении нового приложения образ может не проходить проверку.

**Диагностика:**
```bash
# Получить причину отказа
kubectl describe pod <pod> | grep -A 20 Events
kubectl get events --field-selector reason=FailedCreate

# Для Kyverno — посмотреть политику
kubectl get cpol restrict-image-registries -o yaml
```

**Решение:**
1. **Добавить реестр в whitelist политики:**
   ```yaml
   # Kyverno ClusterPolicy
   spec:
     validationFailureAction: Enforce
     rules:
     - name: allowed-registries
       match:
         any:
         - resources: kinds: ["Pod"]
       validate:
         message: "registry 'docker.io' is not allowed"
         pattern:
           spec:
             containers:
             - image: "harbor.local/* | registry.k8s.io/* | quay.io/*"
   ```
2. **Использовать исключение** для конкретного namespace:
   ```yaml
   match:
     any:
     - resources:
         kinds: ["Pod"]
         namespaces: ["kube-system", "monitoring"]
   ```
3. **Для ImagePolicyWebhook:** отредактировать `/etc/kubernetes/admission-config.yaml` на API Server и перезапустить `kube-apiserver`.

### Сценарий 14: Eviction подов из-за ImageGC и перезапуск после GC

**Симптом:**
Поды получают статус `Evicted`, в Events:
```text
The node was low on resource: ephemeral-storage. Container <name> is using more than requested.
```
После перезапуска новые реплики падают в `ImagePullBackOff`, хотя образ ранее работал.

**Причина:**
`kubelet` эвикнул под из-за нехватки ephemeral-storage или disk pressure. При попытке перезапуска — `imageGC` уже удалил распакованные слои как неиспользуемые (или удалил сами образы под давлением). kubelet вынужден заново pull'ить.

**Решение:**
1. **Отключить GC для конкретного образа нельзя**, но можно:
   - Зафиксировать `requests.ephemeral-storage` в манифесте, чтобы kubelet учитывал нужду пода в диске.
   - Увеличить размер root FS / imagefs на узле.
2. **Снизить порог GC** для предотвращения удаления часто используемых образов:
   ```yaml
   imageGCHighThresholdPercent: 90
   imageGCLowThresholdPercent: 85
   ```
3. **Настроить node-level лимиты:**
   ```yaml
   # KubeletConfiguration
   imageFs: /var/lib/containerd
   podMaxStorage: "10Gi"  # лимит на под
   ```
4. **Уменьшить размер образа:** multi-stage build, `.dockerignore`, удаление слоёв с большими файлами (`apt-get clean`, очистка кэшей).

### Сценарий 15: Ручная отладка через `ctr` и `crictl`

Когда `kubectl describe pod` показывает ошибку, но первопричина неясна (особенно для проблем с `manifest`, сжатием или TLS на конкретном узле), полезно выполнить pull напрямую от рантайма.

**1. Проверка состояния рантайма:**
```bash
# Список образов в кэше
sudo crictl images

# Детальная информация о поде (от CRI)
sudo crictl inspectp <pod-id>

# Логи конкретного контейнера (если контейнер успел стартовать)
sudo crictl logs <container-id>
```

**2. Прямой pull от containerd (минуя kubelet):**
```bash
# Полная диагностика с verbose
sudo ctr -n k8s.io images pull --user agent.example.com \
  docker.io/library/nginx:1.25 -v debug

# Pull с указанием платформы (для multi-arch)
sudo ctr -n k8s.io images pull --platform linux/arm64 \
  docker.io/library/nginx:1.25

# Проверка существования образа в локальном кэше
sudo ctr -n k8s.io images check
```

**3. Проверка состояния snapshotter:**
```bash
# Список snapshots (распакованных слоёв)
sudo ctr -n k8s.io snapshots ls

# Удалить повреждённый snapshot
sudo ctr -n k8s.io snapshots rm <snapshot-key>

# Очистка неиспользуемых snapshot'ов (garbage collection)
sudo ctr -n k8s.io snapshots gc
```

**4. Тестирование с другого узла:**
Если ошибка проявляется только на части узлов — выполнить `crictl pull` с «здорового» и «больного» узла:
```bash
time ssh node-1 "sudo crictl pull harbor.local/my-app:1.0"
time ssh node-2 "sudo crictl pull harbor.local/my-app:1.0"
```
Большое расхождение по времени или отказ на одном узле указывает на локальную проблему (сеть, snapshotter, диск).

**Связь с kubelet:** если `ctr pull` успешен, а kubelet получает `ErrImagePull` — проблема в конфигурации kubelet (`imagePullSecrets`, `imagePullPolicy`, `--registry-pull-qps`), а не в сети/реестре.

### Сценарий 16: Проблемы с DNS-именем реестра

**Симптом:**
Ошибка `dial tcp: lookup registry.example.com: no such host` или `i/o timeout` при попытке загрузить образ.

**Причина:**
Рантайм контейнеров не может разрешить DNS-имя реестра образов.

**Диагностика:**

1.  **Проверка DNS из тестового пода:**
    ```bash
    kubectl run dns-debug --image=busybox --rm -it -- nslookup registry.example.com
    ```

2.  **Проверка CoreDNS:**
    ```bash
    kubectl get pods -n kube-system -l k8s-app=kube-dns
    kubectl logs -n kube-system -l k8s-app=kube-dns
    ```

3.  **Проверка NodeLocal DNSCache:**
    ```bash
    kubectl get daemonset -n kube-system node-local-dns
    kubectl logs -n kube-system -l k8s-app=node-local-dns
    ```

**Возможные причины и решения:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| CoreDNS не работает | `kubectl get pods -n kube-system` — поды в `CrashLoopBackOff` | Перезапуск CoreDNS, проверка конфигурации |
| NetworkPolicy блокирует DNS | Проверка политик в неймспейсе | Добавить разрешение на UDP/TCP порт 53 |
| NodeLocal DNSCache не работает на узлах | Логи `node-local-dns` содержат ошибки | Перезапустить DaemonSet, проверить конфигурацию |
| Внешний DNS не резолвится | `nslookup` из тестового пода не работает | Проверить upstream DNS в CoreDNS Corefile |
| Проблема с `/etc/resolv.conf` пода | Проверка конфигурации пода | Настроить `dnsConfig` или `dnsPolicy` |

**Специфика NodeLocal DNSCache:**
Если `node-local-dns` работает на части узлов, а на других — нет, это приводит к неконсистентному поведению: поды на одних узлах могут загружать образы, а на других — нет.

**Алгоритм диагностики при проблемах с NodeLocal DNSCache:**
1.  Проверить статус DaemonSet: `kubectl get ds -n kube-system node-local-dns`.
2.  Проверить логи подов: `kubectl logs -n kube-system -l k8s-app=node-local-dns`.
3.  Если поды в `CrashLoopBackOff`, проверить:
    - Доступность CoreDNS Service IP (обычно `10.96.0.10`).
    - Корректность ConfigMap с конфигурацией.
    - Наличие необходимых ресурсов (CPU/Memory).
4.  Временное решение: удалить проблемные поды DaemonSet для перезапуска.
5.  Для полного восстановления: `kubectl rollout restart daemonset node-local-dns -n kube-system`.

**Важно:** NodeLocal DNSCache использует IP `169.254.20.10` (по умолчанию) для локального кэширования. Убедитесь, что этот IP не конфликтует с другими сервисами в кластере.

### Универсальный чек-лист диагностики ImagePull

При систематическом возникновении `ImagePullBackOff` рекомендуется выполнить последовательность проверок — от высокого уровня к низкому:

| Шаг | Команда / Проверка | Что ожидать |
| :--- | :--- | :--- |
| 1 | `kubectl describe pod <pod>` → секция `Events` | Конкретное сообщение: `manifest unknown`, `unauthorized`, `i/o timeout`, `no space left on device`. |
| 2 | `kubectl get pod <pod> -o jsonpath='{.spec.containers[*].image}{"\n"}{.spec.imagePullSecrets}'` | Корректность имени образа и наличие секрета. |
| 3 | `kubectl get secret regcred -o jsonpath='{.data.\.dockerconfigjson}' \| base64 -d` | Содержимое секрета содержит правильный auth (base64(user:pass)). |
| 4 | `kubectl get sa default -o yaml` | `imagePullSecrets` привязаны к ServiceAccount, если используется глобальный подход. |
| 5 | `skopeo inspect docker://<image>` (с узла или с dev-машины) | Образ доступен, тег существует, манифест корректен. |
| 6 | `sudo crictl pull <image>` (на проблемном узле) | Воспроизводится ли ошибка на уровне рантайма. |
| 7 | `sudo ctr -n k8s.io images ls` | Образ уже в кэше → проблема в `imagePullPolicy`. |
| 8 | `df -h /var/lib/containerd; df -ih /var/lib/containerd` | Достаточно места и inodes. |
| 9 | `kubectl get events --field-selector reason=Pulled,Failed` | История pull-запросов за последний час. |
| 10 | `kubectl logs -n kube-system -l k8s-app=kube-dns` (если DNS) | CoreDNS работает, upstream доступен. |
| 11 | `journalctl -u containerd --since "10 min ago"` (на проблемном узле) | TLS ошибки, rate limit ответы, проблемы со snapshotter. |
| 12 | `kubectl get cpol` (если установлен Kyverno) | Политики не блокируют источник образа. |

**Эскалация:** если шаги 1–12 не дали результата — собрать bundle:
```bash
kubectl get pod <pod> -o yaml > pod.yaml
kubectl describe pod <pod> > pod-describe.txt
sudo crictl info > crictl-info.txt
sudo ctr -n k8s.io images ls > ctr-images.txt
journalctl -u kubelet --since "30 min ago" > kubelet.log
journalctl -u containerd --since "30 min ago" > containerd.log
```

---

## Дополнительная информация

### Связанные темы

- [Определения и базовые концепции](./definitions.md) — терминология и жизненный цикл загрузки.
- [Пошаговая диагностика](./diagnostics.md) — алгоритм поиска неисправностей (L1-L5).
- [Лучшие практики](./best_practices.md) — предотвращение ошибок в продакшене.
- [Сетевые проблемы](./network_issues.md) — диагностика DNS, Proxy и MTU.
- [Air-gapped кластеры](./airgapped.md) — настройка `hosts.toml` и работа в изоляции.
