# Ошибки загрузки образов (Image Pull Errors): Air-gapped кластеры

## Определения

**Air-gapped кластер (Offline)** — инфраструктура Kubernetes, развернутая в полностью изолированной сетевой среде без прямого или косвенного доступа к публичным сетям и внешним реестрам образов. Общие стратегии синхронизации описаны в разделе **[Изолированные среды (Air-gapped)](../../../CI-CD/Core_Concepts/air_gapped_environments.md)**.

**Закрытый контур** — периметр безопасности, ограничивающий сетевые взаимодействия только внутренними доверенными ресурсами. Требует наличия локальных сервисов для всех внешних зависимостей (образы, пакеты ОС, Helm-чарты).

**Локальный реестр (Internal Registry)** — служба хранения образов внутри контура (например, Harbor, Nexus, Docker Distribution). Является единственным легитимным источником образов для узлов кластера.

**Зеркалирование образов (Image Mirroring)** — процесс синхронизации образов между внешним и внутренним реестрами с сохранением структуры слоев и метаданных.

**Перехват реестра (Registry Redirection)** — конфигурация рантайма контейнеров (containerd, CRI-O), позволяющая прозрачно перенаправлять запросы с публичных адресов (например, `docker.io`) на локальные зеркала без изменения манифестов подов.

**Sandbox Image (Pause container)** — вспомогательный образ (обычно `registry.k8s.io/pause`), используемый Kubernetes для создания сетевого пространства имен пода. В air-gapped средах это критическая точка отказа, если рантайм пытается скачать его извне.

**Crane** — утилита от Google (`github.com/google/go-containerregistry`) для работы с OCI-образами без Docker-демона. Поддерживает копирование, инспекцию, мутацию тегов и работу с multi-arch манифестами. В air-gapped средах используется как альтернатива skopeo: `crane copy`, `crane digest`, `crane manifest`.

**Regctl** — CLI-клиент от RegCCE (`github.com/regclient/regclient`) для управления OCI-реестрами. Предоставляет низкоуровневый доступ к тегам, манифестам и слоям: `regctl tag list`, `regctl tag set`, `regctl image copy`. Полезен для управления ретенцией тегов в локальном реестре.

**Nerdctl (nerd control)** — Docker-совместимый CLI для containerd с поддержкой Kubernetes namespaces, ленивой загрузки (lazy pulling), P2P-дистрибуции и подписи образов. Позволяет использовать привычный синтаксис Docker без самого Docker Engine.

**Ctr** — низкоуровневый CLI для прямого взаимодействия с containerd. Используется исключительно для отладки: `ctr -n k8s.io images ls`, `ctr -n k8s.io images pull`. Не рекомендуется для production-операций.

**Content Trust (Доверие контента)** — механизм верификации целостности и подлинности образа через криптографическую подпись. В air-gapped средах подпись образов (Cosign, Notation) гарантирует, что в кластер попадают только артефакты, прошедшие Quality Gates.

**Image Retention Policy (Политика ретенции образов)** — правила автоматического удаления старых тегов/образов из реестра для предотвращения переполнения диска. В air-gapped средах критична из-за ограниченного пространства и отсутствия внешнего бэкапа.

---

## Основные концепции

### Специфика ошибок Image Pull в изолированных средах

В air-gapped кластерах ошибки загрузки практически всегда связаны с конфигурацией инфраструктуры или отсутствием данных, а не с временными сетевыми сбоями.

| Корневая причина | Сообщение об ошибке | Особенности в Air-gapped |
| :--- | :--- | :--- |
| **Отсутствие образа** | `manifest not found` / `404 Not Found` | Образ не был синхронизирован или загружен в локальный реестр. |
| **Проблемы DNS** | `no such host` / `lookup failed` | Узлы кластера не могут разрешить имя локального реестра. |
| **TLS/SSL ошибки** | `x509: certificate signed by unknown authority` | Отсутствие корневого CA локального реестра в доверенном хранилище узла. |
| **Ошибка маршрутизации** | `connection timed out` | Сетевые политики (NetworkPolicies) или firewall блокируют доступ к реестру. |
| **Sandbox Failure** | `failed to pull sandbox image` | Рантайм не может запустить под из-за отсутствия локального образа `pause`. |

### Проблема Sandbox Image (Pause container)

Для работы любого пода Kubelet требует наличия образа "паузы". По умолчанию рантайм пытается скачать его с `registry.k8s.io/pause`.
В изолированной среде необходимо:
1. Заранее загрузить образ `pause` в локальный реестр.
2. Явно переопределить путь к нему в конфигурации рантайма (`containerd` или `CRI-O`) или через аргументы запуска `kubelet` (`--pod-infra-container-image`).

### Выбор инструмента для работы с образами

В air-gapped средах доступны несколько инструментов. Выбор зависит от задачи:

| Инструмент | Назначение | Преимущества | Ограничения |
| :--- | :--- | :--- | :--- |
| **skopeo** | Копирование, инспекция, зеркалирование | Массовая синхронизация (`sync`), работа с `dir:` и `oci:` форматами, подписи | Не поддерживает `docker build` |
| **crane** | Копирование, мутация тегов | Быстрый, Go-бинарник, интеграция с CI | Нет массовой синхронизации |
| **regctl** | Управление тегами в реестре | Точечная ротация тегов, проверка манифестов | Только для OCI-реестров |
| **nerdctl** | Полный цикл (build/pull/push) | Docker-совместимый синтаксис, lazy pulling | Требует containerd на хосте |
| **ctr** | Отладка containerd | Низкоуровневый доступ, работа с namespaces | Недружелюбный CLI, только для отладки |

**Рекомендация:** Для air-gapped синхронизации используйте `skopeo sync`, для точечных операций — `crane copy`, для ротации тегов — `regctl`.

### imagePullPolicy в air-gapped средах

В изолированных средах выбор `imagePullPolicy` критически влияет на стабильность: обращение к недоступному внешнему реестру гарантирует `ImagePullBackOff`.

| Политика | Поведение в air-gapped | Рекомендация |
| :--- | :--- | :--- |
| **`Never`** | Контейнер запускается только из локального кэша рантайма. Pull не выполняется. | Для образов, гарантированно предзагруженных на все узлы ( DaemonSet Image Puller, `ctr image import`). |
| **`IfNotPresent`** | Pull выполняется, если образа нет в кэше узла. При air-gapped реестре — обращается к нему. | **Основной выбор.** Образы уже в локальном реестре, pull идет по внутренней сети. |
| **`Always`** | Pull при каждом запуске контейнера. | **Избегать** в air-gapped — каждый restart генерирует запрос к реестру, что критично при большом количестве реплик. |

**Правило для air-gapped:** Если образ гарантированно предзагружен на все узлы — `Never`. Если образ в локальном реестре — `IfNotPresent`. Использование `Always` допустимо только при работающем и доступном локальном реестре.

**Важно:** При `imagePullPolicy: Never` kubelet не обращается к реестру вообще. Если образ отсутствует на узле — под не запустится с ошибкой `ImagePullBackOff`. Перед применением `Never` убедитесь, что образ доступен на каждом узле через `crictl images`.

### imagePullSecrets для локальных реестров

В air-gapped средах `imagePullSecrets` используются для аутентификации в локальном реестре (Harbor, Nexus, Docker Distribution). Секреты имеют область видимости **Namespace** — секрет в `production` не будет доступен поду в `staging`.

**Формат секрета:**

```json
{
  "auths": {
    "harbor.local": {
      "auth": "<base64(username:password)>",
      "email": ""
    }
  }
}
```

**Создание секрета:**

```bash
# Способ 1: Через kubectl (рекомендуется)
kubectl create secret docker-registry regcred \
  --docker-server=harbor.local \
  --docker-username=admin \
  --docker-password=Harbor12345 \
  -n production

# Способ 2: Из существующего docker/config.json
kubectl create secret generic regcred \
  --from-file=.dockerconfigjson=$HOME/.docker/config.json \
  --type=kubernetes.io/dockerconfigjson \
  -n production

# Способ 3: YAML-манифест (для GitOps)
kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: regcred
  namespace: production
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: $(base64 < $HOME/.docker/config.json)
EOF
```

**Привязка к ServiceAccount (рекомендуется вместо Pod-level):**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-sa
  namespace: production
imagePullSecrets:
  - name: regcred
```

**Автоматическая инъекция во все namespace (admission webhook):**

Для кластеров с множеством namespace используйте Kyverno или MutatingWebhook для автоматической инъекции `imagePullSecrets` в каждый под:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: inject-image-pull-secret
spec:
  rules:
    - name: add-image-pull-secret
      match:
        any:
          - resources:
              kinds: ["Pod"]
      mutate:
        patchStrategicMerge:
          spec:
            containers:
              - name: "{{request.operation}}"
            imagePullSecrets:
              - name: regcred
```

### Настройка сетевых правил для доступа к реестру

В air-gapped средах доступ к реестру должен быть разрешен на всех узлах кластера. Три уровня сетевого контроля:

**1. Firewall (iptables/nftables) на узлах:**

```bash
# Разрешить исходящий трафик к реестру (443 — HTTPS, 80 — HTTP)
iptables -A OUTPUT -d <registry_ip> -p tcp --dport 443 -j ACCEPT
iptables -A OUTPUT -d <registry_ip> -p tcp --dport 80 -j ACCEPT

# Если реестр в другом VLAN — разрешить маршрутизацию
ip route add <registry_subnet> via <gateway_ip>

# Для nftables (современный вариант)
nft add rule ip filter output ip daddr <registry_ip> tcp dport {443, 80} accept
```

**2. Kubernetes NetworkPolicy:**

Если в кластере используется CNI с поддержкой NetworkPolicy (Calico, Cilium, kube-router), убедитесь, что политики не блокируют трафик к реестру:

```yaml
# Разрешить DNS и трафик к реестру во всех namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-registry-access
  namespace: kube-system
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    # DNS (CoreDNS)
    - to: []
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Локальный реестр
    - to:
        - ipBlock:
            cidr: <registry_ip>/32
      ports:
        - protocol: TCP
          port: 443
```

**3. Проверка доступности реестра с узла:**

```bash
# Проверка TCP-соединения
nc -zv harbor.local 443
# → Connection to harbor.local 443 port [tcp/https] succeeded!

# Проверка через TLS
openssl s_client -connect harbor.local:443 -brief
# → Verification: OK

# Проверка из пода (если DNS настроен)
kubectl run test --image=busybox --rm -it -- nslookup harbor.local
```

### Конфигурация рантайма: containerd

Для современных версий containerd (1.5+) рекомендуется использовать систему `hosts.toml`, которая позволяет настраивать зеркала и параметры TLS без перезагрузки демона.

**1. Включение поддержки в `/etc/containerd/config.toml`:**
```toml
[plugins."io.containerd.grpc.v1.cri".registry]
  config_path = "/etc/containerd/certs.d"
```

**2. Настройка зеркала для `docker.io` в `/etc/containerd/certs.d/docker.io/hosts.toml`:**
```toml
server = "https://registry-1.docker.io"

[host."https://harbor.local/v2/proxy-docker-io"]
  capabilities = ["pull", "resolve"]
```

**3. Переопределение Sandbox Image:**
В `/etc/containerd/config.toml`:
```toml
[plugins."io.containerd.grpc.v1.cri"]
  sandbox_image = "harbor.local/k8s/pause:3.9"
```

**4. Настройка DNS для внутреннего реестра:**

В air-gapped средах узлы должны разрешать имя реестра через внутренний DNS. Проверьте, что CoreDNS или NodeLocal DNSCache настроены на резолв внутренних имен:

```bash
# Проверка резолва из пода
kubectl run dns-test --image=busybox --rm -it -- nslookup harbor.local

# Проверка резолва из узла
nslookup harbor.local
```

Если DNS не настроен, добавьте запись в `/etc/hosts` на всех узлах или настройте CoreDNS через ConfigMap:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns
  namespace: kube-system
data:
  Corefile: |
    .:53 {
        hosts {
            192.168.1.100 harbor.local
            fallthrough
        }
        kubernetes cluster.local in-addr.arpa ip6.arpa {
           pods insecure
        }
        forward . /etc/resolv.conf
    }
```

### Конфигурация рантайма: CRI-O

CRI-O использует файл `/etc/containers/registries.conf` (или файлы в `/etc/containers/registries.conf.d/`) для управления зеркалами.

Пример настройки в формате TOML:
```toml
[[registry]]
location = "docker.io"

[[registry.mirror]]
location = "harbor.local/v2/proxy-docker-io"

[unqualified-search-registries]
registries = ['harbor.local', 'docker.io']
```

Переопределение образа паузы в `/etc/crio/crio.conf`:
```toml
[crio.image]
pause_image = "harbor.local/k8s/pause:3.9"
```

---

## Практические сценарии

### Сценарий 1: Синхронизация образов через Skopeo

`skopeo` — основной инструмент для air-gapped сред. Он позволяет работать с образами без локального Docker-демона.

**1. Копирование одного образа (с поддержкой всех архитектур):**
```bash
# --all копирует все платформы (amd64, arm64 и т.д.), что критично для мультиплатформенных кластеров
skopeo copy --all docker://docker.io/library/nginx:1.25 dir:/tmp/nginx-image
```

**2. Массовая синхронизация (skopeo sync):**
Позволяет синхронизировать целые репозитории или списки образов.
```bash
# Файл images.yaml
# docker.io/library:
#   images:
#     nginx: [ "1.25", "latest" ]
#     redis: [ "7.0" ]

skopeo sync --all --src yaml --dest docker images.yaml harbor.local/library
```

### Сценарий 2: Добавление сертификата и аутентификация

Если локальный реестр защищен паролем и использует самоподписанный TLS, настройки выполняются в `hosts.toml` (для containerd).

**Конфигурация `/etc/containerd/certs.d/harbor.local/hosts.toml`:**
```toml
server = "https://harbor.local"

[host."https://harbor.local"]
  capabilities = ["pull", "resolve"]
  # Путь к CA сертификату для этого конкретного хоста
  ca = "/etc/containerd/certs.d/harbor.local/ca.crt"
  
  [host."https://harbor.local".header]
    # base64(username:password)
    authorization = "Basic dXNlcm5hbWU6cGFzc3dvcmQ="
```

### Сценарий 3: Использование ImagePolicyWebhook

В крупных организациях для автоматической подмены путей к образам (например, с `docker.io/nginx` на `internal-registry.io/nginx`) используется **ImagePolicyWebhook** или мутирующие Admission-контроллеры (Kyverno, Gatekeeper). Это позволяет разработчикам использовать стандартные манифесты, которые автоматически корректируются под инфраструктуру air-gapped.

### Сценарий 4: Диагностика и проверка через crictl

`crictl` — CLI для взаимодействия с CRI-совместимыми рантаймами. Он позволяет проверить настройки "глазами" Kubernetes, минуя Docker.

**1. Проверка настроек рантайма:**
```bash
# Проверка используемого sandbox_image
crictl info | grep -A 5 "sandboxImage"
```

**2. Ручная проверка загрузки образа:**
```bash
# Тестовый пулл образа через рантайм
# Если зеркала настроены верно, запрос к docker.io уйдет на локальный реестр
crictl pull docker.io/library/nginx:1.25
```

**3. Просмотр логов рантайма:**
Если пулл не удается, причины (DNS, TLS, Auth) будут видны в системном логе:
```bash
journalctl -u containerd -f
# или
journalctl -u crio -f
```

**4. Низкоуровневая отладка через ctr (containerd):**
Если `crictl` не дает достаточно деталей, используйте `ctr` для прямого взаимодействия с containerd:

```bash
# Список всех образов в namespace k8s.io (управляемых kubelet)
sudo ctr -n k8s.io images ls

# Прямой pull образа через containerd (с логированием)
sudo ctr -n k8s.io images pull --tlscacert /etc/containerd/certs.d/ca.crt \
  harbor.local/library/nginx:1.25

# Проверка конкретного образа
sudo ctr -n k8s.io images info harbor.local/library/nginx:1.25

# Принудительное удаление образа из кэша (для перезагрузки)
sudo ctr -n k8s.io images rm harbor.local/library/nginx:1.25
```

*Важно:* `ctr` работает в namespace `k8s.io` — образы, управляемые kubelet, находятся именно там. Использование `default` namespace приведет к конфликту с рантаймом.

### Сценарий 5: Начальная настройка air-gapped кластера (с нуля)

Полный цикл подготовки изолированного контура — от скачивания образов до запуска подов.

**1. Сбор манифеста необходимых образов (на хосте с интернетом):**

```bash
# Определяем версию Kubernetes и необходимые компоненты
K8S_VERSION="v1.30.0"

# Базовые образы для кластера (kubeadm)
cat <<EOF > k8s-images.txt
registry.k8s.io/kube-apiserver:${K8S_VERSION}
registry.k8s.io/kube-controller-manager:${K8S_VERSION}
registry.k8s.io/kube-scheduler:${K8S_VERSION}
registry.k8s.io/kube-proxy:${K8S_VERSION}
registry.k8s.io/pause:3.9
registry.k8s.io/coredns/coredns:v1.11.1
registry.k8s.io/etcd:3.5.12-0
EOF

# Добавляем образы приложений и инструментов
cat <<EOF >> k8s-images.txt
harbor.local/library/nginx:1.25
harbor.local/library/alpine:3.19
harbor.local/monitoring/prometheus:v2.53.0
EOF
```

**2. Зеркалирование в локальный реестр:**

```bash
# Через skopeo sync (массовое копирование)
skopeo sync --all --src yaml --dest docker k8s-images.txt harbor.local/k8s

# Или через crane (по одному образу)
while read -r img; do
  crane copy "${img}" "harbor.local/k8s/${img##*/}"
done < k8s-images.txt
```

**3. Настройка узлов (на каждом узле):**

```bash
# Добавление CA-сертификата Harbor
sudo cp harbor-ca.crt /usr/local/share/ca-certificates/harbor.crt
sudo update-ca-certificates

# Настройка containerd: включение hosts.toml
sudo mkdir -p /etc/containerd/certs.d/harbor.local
cat <<EOF | sudo tee /etc/containerd/certs.d/harbor.local/hosts.toml
server = "https://harbor.local"

[host."https://harbor.local"]
  capabilities = ["pull", "resolve"]
  ca = "/etc/containerd/certs.d/harbor.local/ca.crt"
EOF

# Включение config_path в containerd
sudo sed -i 's|config_path = ""|config_path = "/etc/containerd/certs.d"|' /etc/containerd/config.toml

# Переопределение sandbox_image
sudo sed -i 's|sandbox_image = "registry.k8s.io/pause:.*"|sandbox_image = "harbor.local/k8s/pause:3.9"|' /etc/containerd/config.toml

# Перезапуск containerd
sudo systemctl restart containerd
```

**4. Проверка работоспособности:**

```bash
# Проверка pull через crictl
sudo crictl pull harbor.local/k8s/pause:3.9

# Проверка из пода
kubectl run test-nginx --image=harbor.local/library/nginx:1.25 --rm -it --restart=Never -- curl -s localhost
```

### Сценарий 6: Префетчинг образов через DaemonSet

В больших кластерах или при автоскейлинге задержка загрузки тяжелых образов может нарушить SLA. DaemonSet Image Puller гарантирует наличие образов на всех узлах заранее.

**1. Создание DaemonSet для предварительной загрузки:**

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: image-prefetcher
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: image-prefetcher
  template:
    metadata:
      labels:
        app: image-prefetcher
    spec:
      initContainers:
        - name: prefetch
          image: harbor.local/library/alpine:3.19
          command: ["sh", "-c", "echo 'Image prefetched' && sleep infinity"]
          resources:
            requests:
              cpu: 1m
              memory: 1Mi
            limits:
              cpu: 1m
              memory: 1Mi
      containers:
        - name: pause
          image: harbor.local/k8s/pause:3.9
          resources:
            requests:
              cpu: 1m
              memory: 1Mi
            limits:
              cpu: 1m
              memory: 1Mi
      tolerations:
        - operator: Exists
```

**2. Альтернатива: CronJob для периодической синхронизации:**

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: image-sync
  namespace: kube-system
spec:
  schedule: "0 */6 * * *"  # Каждые 6 часов
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: sync
              image: harbor.local/library/skopeo:latest
              command:
                - /bin/sh
                - -c
                - |
                  skopeo sync --all --src yaml --dest docker \
                    /config/images.yaml harbor.local/k8s
              volumeMounts:
                - name: config
                  mountPath: /config
          volumes:
            - name: config
              configMap:
                name: image-list
          restartPolicy: OnFailure
```

### Сценарий 7: Подпись и верификация образов в air-gapped среде

В изолированных средах критически важно гарантировать, что в кластер попадают только проверенные образы. Cosign позволяет подписывать образы offline и верифицировать их перед запуском.

**1. Генерация ключей на машине с интернетом:**

```bash
# Генерация ключевой пары
cosign generate-key-pair

# Ключи: cosign.key (приватный), cosign.pub (публичный)
# Приватный ключ остается на машине с интернетом
# Публичный ключ переносится в air-gapped контур
```

**2. Подпись образа (на машине с интернетом):**

```bash
cosign sign --key cosign.key harbor.local/library/nginx:1.25
```

**3. Верификация в air-gapped контуре:**

```bash
# Импорт публичного ключа
cosign verify --key cosign.pub harbor.local/library/nginx:1.25
# →湾区: verified
```

**4. Блокировка неподписанных образов через Kyverno:**

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-image-signature
spec:
  validationFailureAction: Enforce
  rules:
    - name: verify-cosign-signature
      match:
        resources:
          kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["harbor.local/*"]
          attestors:
            - entries:
                - keys:
                    publicKeys: |-
                      -----BEGIN PUBLIC KEY-----
                      MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
                      -----END PUBLIC KEY-----
```

### Сценарий 8: Кэширование Helm-чартов в air-gapped среде

Helm-чарты, как и образы, требуют предварительной загрузки в изолированной среде.

**1. Скачивание чартов (на хосте с интернетом):**

```bash
# Добавление репозитория
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Скачивание чарта с зависимостями
helm pull bitnami/nginx --version 15.0.0 --untar --dependency-update

# Пакетирование для переноса
tar -czf helm-charts-airgapped.tar.gz nginx/
```

**2. Загрузка в OCI-реестр (в air-gapped контуре):**

```bash
# Включение OCI в Harbor (или другой реестр)
# Пуш чарта как OCI-артефакта
helm push nginx-15.0.0.tgz oci://harbor.local/charts

# Использование из OCI-реестра
helm install nginx oci://harbor.local/charts/nginx --version 15.0.0
```

**3. Локальное кэширование (без реестра):**

```bash
# Копирование чартов в локальную директорию
mkdir -p /opt/helm-charts
cp -r nginx/ /opt/helm-charts/

# Установка из файловой системы
helm install nginx /opt/helm-charts/nginx --namespace production
```

### Сценарий 9: Типовые ошибки в air-gapped среде и их решение

| Симптом | Корневая причина | Решение |
| :--- | :--- | :--- |
| `x509: certificate signed by unknown authority` | CA-сертификат реестра не добавлен на узел | Добавить CA в `/usr/local/share/ca-certificates/` и выполнить `update-ca-certificates` |
| `connection timed out` к реестру | Firewall блокирует порт 443 к внутреннему реестру | Добавить правило firewall: `iptables -A OUTPUT -d <registry_ip> -p tcp --dport 443 -j ACCEPT` |
| `no such host` при pull | DNS не резолвит имя реестра | Добавить запись в `/etc/hosts` или настроить CoreDNS |
| `unauthorized` при pull | Отсутствует или невалиден imagePullSecret | Проверить Secret: `kubectl get secret <name> -o jsonpath='{.data.\.dockerconfigjson}' \| base64 -d` |
| `failed to pull sandbox image` | Pause-образ не загружен в локальный реестр | Загрузить `registry.k8s.io/pause:3.9` и настроить `sandbox_image` в конфиге рантайма |
| Поды не запускаются после перезагрузки узла | containerd не стартовал из-за невалидного config.toml | Проверить конфигурацию: `containerd config dump` и исправить синтаксические ошибки |
| `ImagePullBackOff` на всех узлах одновременно | Реестр недоступен (Harbor упал или диск переполнен) | Проверить статус Harbor: `docker ps -a`, проверить место на диске: `df -h` |
| `imagePullBackOff` с `imagePullPolicy: Never` | Образ не предзагружен на узел | Предзагрузить образ через `ctr image import` или DaemonSet Image Puller |
| `ImagePullBackOff` после перезагрузки узла | containerd не восстановил кэш образов | Проверить `crictl images`, при необходимости выполнить `crictl pull` |
| `TLS handshake timeout` к локальному реестру | Невалидный или истекший сертификат реестра | Проверить сертификат: `openssl x509 -in ca.crt -text -noout`, обновить при необходимости |
| `no such host` для harbor.local | DNS не резолвит имя реестра | Добавить запись в `/etc/hosts` или настроить CoreDNS через ConfigMap |
| `connection refused` к реестру | Firewall блокирует порт 443/80 | Проверить iptables/nftables: `iptables -L OUTPUT -n`, добавить规则 |
| `unauthorized` для локального реестра | Отсутствует или невалиден imagePullSecret | Создать Secret и привязать к ServiceAccount |
| `failed to pull sandbox image` | Pause-образ не загружен в локальный реестр | Загрузить `registry.k8s.io/pause:3.9` и настроить `sandbox_image` |
| `ImagePullBackOff` при `imagePullPolicy: Always` | Реестр доступен, но rate limit или задержка | Перейти на `IfNotPresent` или digest-пиннинг |
| Поды не запускаются после перезагрузки узла | containerd не стартовал из-за невалидного config.toml | Проверить конфигурацию: `containerd config dump` и исправить синтаксические ошибки |
| `no matching manifest for linux/arm64` | Multi-arch образ не содержит нужной архитектуры | Проверить манифест: `skopeo inspect --raw docker://image \| jq .manifests` |
| `error: unable to upgrade connection` | Pod-сеть не работает (CNI не загружен) | Проверить CNI-плагины: `ls /etc/cni/net.d/`, убедиться что образы CNI зеркалированы |

### Сценарий 10: Физический перенос образов (Sneakernet)

При полной изоляции (no network connection) образы переносятся через физические носители (USB, HDD).

**1. Подготовка на внешнем хосте:**

```bash
# Установка инструментов
sudo apt install -y skopeo jq

# Создание рабочей директории
WORKDIR="/opt/airgap-bundle"
mkdir -p "${WORKDIR}/images" "${WORKDIR}/checksums"

# Манифест необходимых образов
cat <<EOF > "${WORKDIR}/images.txt"
docker.io/library/nginx:1.25
docker.io/library/redis:7.0
docker.io/library/alpine:3.19
harbor.local/myproject/app:v1.2.0
registry.k8s.io/pause:3.9
registry.k8s.io/kube-apiserver:v1.30.0
registry.k8s.io/coredns/coredns:v1.11.1
EOF
```

**2. Скачивание в локальный каталог (dir:):**

```bash
# Скачивание всех образов в dir-формате (сжатые слои)
while IFS= read -r img; do
  # Очищаем имя для директории
  dir_name=$(echo "$img" | tr '/:' '_')
  skopeo copy --all "docker://${img}" "dir:${WORKDIR}/images/${dir_name}"
  echo "Скопирован: ${img}"
done < "${WORKDIR}/images.txt"

# Генерация контрольных сумм
cd "${WORKDIR}"
find images -type f -exec sha256sum {} + > checksums/manifest.sha256

# Создание архива для переноса
tar -czf /mnt/usb/airgap-bundle.tar.gz -C "${WORKDIR}" images checksums images.txt
echo "Размер бандла: $(du -sh /mnt/usb/airgap-bundle.tar.gz | cut -f1)"
```

**3. Импорт в air-gapped контуре:**

```bash
# Распаковка
WORKDIR="/opt/airgap-bundle"
mkdir -p "${WORKDIR}"
tar -xzf /mnt/usb/airgap-bundle.tar.gz -C "${WORKDIR}"

# Проверка целостности
cd "${WORKDIR}"
sha256sum -c checksums/manifest.sha256
# → images/nginx_1.25/manifest.json: OK
# → images/redis_7.0/manifest.json: OK

# Загрузка в локальный реестр
while IFS= read -r img; do
  dir_name=$(echo "$img" | tr '/:' '_')
  skopeo copy --all "dir:${WORKDIR}/images/${dir_name}" "docker://${REGISTRY}/${img}"
  echo "Загружен: ${img}"
done < "${WORKDIR}/images.txt"
```

**4. Импорт напрямую в containerd (без реестра):**

```bash
# Импорт образа в containerd из OCI-архива
sudo ctr -n k8s.io images import --no-unpack "${WORKDIR}/nginx-1.25.tar"

# Импорт из dir-формата через skopeo
skopeo copy "dir:${WORKDIR}/images/nginx_1.25" "containers-storage:docker.io/library/nginx:1.25"

# Проверка
sudo crictl images | grep nginx
```

**Важно:** При использовании `dir:` формата структура каталога соответствует OCI Layout. Для ручного монтирования USB-накопителя убедитесь, что файловая система поддерживается (ext4, xfs, или vfat для кратких имен).

### Сценарий 11: Управление реестром в air-gapped среде

**1. Очистка неиспользуемых слоев (Garbage Collection):**

В air-gapped средах диск реестра — критический ресурс. Регулярная очистка обязательна.

```bash
# Harbor: запуск GC через API
curl -X POST "https://harbor.local/api/v2.0/projects/library/gc" \
  -H "Authorization: Basic $(echo -n admin:password | base64)" \
  -H "Content-Type: application/json" \
  -d '{"delete_untagged": true, "dry_run": false}'

# Docker Distribution (registry): GC через переменную окружения
docker exec -it registry bin/registry garbage-collect /etc/docker/registry/config.yml

# Проверка занятого места
du -sh /var/lib/registry/
# → 45G /var/lib/registry/
```

**2. Настройка ретенции тегов (Image Retention Policy):**

```yaml
# Harbor: проект с политикой ретенции
# Сохранять последние 10 тегов для каждого репозитория, не старше 90 дней
apiVersion: goharbor.io/v1beta1
kind: TagRetentionRule
metadata:
  name: keep-recent
spec:
  projectSelectors:
    - library
  tagSelectors:
    - kind: reposAndTags
      pattern: ".*"
  retainedTags:
    - mostRecent: 10
    - olderThanDays: 90
```

**3. Мониторинг здоровья реестра:**

```bash
# Проверка доступности Harbor API
curl -s https://harbor.local/api/v2.0/systeminfo | jq .harbor_version
# → "2.10.0"

# Проверка статуса всех сервисов Harbor
curl -s https://harbor.local/api/v2.0/systeminfo/volumes | jq '.total.storage'
# → {"total": {"storage": 107374182400}, "free": {"storage": 64424509440}}

# Prometheus-метрики Harbor
curl -s http://harbor.local:8001/metrics | grep harbor_project
```

**4. Восстановление реестра из резервной копии:**

```bash
# Бэкап метаданных PostgreSQL (Harbor)
pg_dump -U postgres -d registry -F c -f /backup/registry-db.dump

# Бэкап слоев (rsync или snapshot тома)
rsync -avz /var/lib/registry/ /backup/registry-data/

# Восстановление
pg_restore -U postgres -d registry -c /backup/registry-db.dump
rsync -avz /backup/registry-data/ /var/lib/registry/
systemctl restart harbor-core
```

### Сценарий 12: Безопасность air-gapped реестра

**1. mTLS (Mutual TLS) для реестра:**

В air-gapped средах mTLS обеспечивает взаимную аутентификацию клиента и сервера:

```bash
# Генерация клиентского сертификата
openssl req -new -x509 -days 365 -nodes \
  -keyout client.key -out client.crt \
  -subj "/CN=kubelet/O=system:nodes"

# Настройка containerd для mTLS
cat <<EOF > /etc/containerd/certs.d/harbor.local/hosts.toml
server = "https://harbor.local"

[host."https://harbor.local"]
  capabilities = ["pull", "resolve"]
  ca = "/etc/containerd/certs.d/harbor.local/ca.crt"
  client = [["/etc/containerd/certs.d/harbor.local/client.crt", "/etc/containerd/certs.d/harbor.local/client.key"]]
EOF
```

**2. RBAC для доступа к реестру (Harbor):**

```bash
# Создание robot-аккаунта для CI/CD в Harbor
curl -X POST "https://harbor.local/api/v2.0/users" \
  -H "Authorization: Basic $(echo -n admin:password | base64)" \
  -H "Content-Type: application/json" \
  -d '{"username": "robot-deployer", "password": "SecurePass123", "realname": "CI/CD Deployer"}'

# Назначение прав на проект
curl -X POST "https://harbor.local/api/v2.0/projects/library/members" \
  -H "Authorization: Basic $(echo -n admin:password | base64)" \
  -H "Content-Type: application/json" \
  -d '{"role_id": 2, "member_user": {"username": "robot-deployer"}}'
# role_id: 1 = Admin, 2 = Developer, 3 = Guest
```

**3. Сканирование образов в air-gapped среде:**

Trivy и Clair требуют периодического обновления баз уязвимостей. В air-gapped среде обновление выполняется через физические носители:

```bash
# На внешнем хосте: обновление базы Trivy
trivy image --download-db-only
# База хранится в ~/.cache/trivy/db/trivy.db

# Перенос на USB
tar -czf /mnt/usb/trivy-db.tar.gz -C ~/.cache/trivy/db/ .

# В air-gapped контуре: импорт базы
mkdir -p ~/.cache/trivy/db/
tar -xzf /mnt/usb/trivy-db.tar.gz -C ~/.cache/trivy/db/

# Сканирование образа
trivy image --skip-db-update harbor.local/library/nginx:1.25
```

**4. Подпись и верификация образов (Cosign):**

```bash
# На внешнем хосте: подпись образа
cosign sign --key cosign.key harbor.local/library/nginx:1.25

# Экспорт подписи для переноса
cosign verify --key cosign.pub harbor.local/library/nginx:1.25 \
  --output-text > /mnt/usb/nginx-signature.txt

# В air-gapped контуре: импорт публичного ключа
cosign verify --key cosign.pub harbor.local/library/nginx:1.25
```

### Сценарий 13: Подготовка CNI-плагинов и компонентов кластера

В air-gapped среде все компоненты кластера должны быть предзагружены до установки.

**1. CNI-плагины (Calico, Cilium):**

```bash
# Список необходимых CNI-образов (пример для Calico)
cat <<EOF > cni-images.txt
docker.io/calico/cni:v3.27.0
docker.io/calico/node:v3.27.0
docker.io/calico/kube-controllers:v3.27.0
docker.io/calico/pod2daemon-flexvol:v3.27.0
EOF

# Синхронизация
while IFS= read -r img; do
  skopeo copy --all "docker://${img}" "docker://${REGISTRY}/calico/${img##*/}"
done < cni-images.txt
```

**2. Kubeadm компоненты:**

```bash
# Базовые образы Kubernetes (kubeadm)
K8S_VERSION="v1.30.0"
cat <<EOF > k8s-images.txt
registry.k8s.io/kube-apiserver:${K8S_VERSION}
registry.k8s.io/kube-controller-manager:${K8S_VERSION}
registry.k8s.io/kube-scheduler:${K8S_VERSION}
registry.k8s.io/kube-proxy:${K8S_VERSION}
registry.k8s.io/pause:3.9
registry.k8s.io/etcd:3.5.12-0
registry.k8s.io/coredns/coredns:v1.11.1
EOF

# Зеркалирование
skopeo sync --all --src yaml --dest docker k8s-images.txt ${REGISTRY}/k8s
```

**3. Конфигурация kubeadm для air-gapped:**

```yaml
# kubeadm-config.yaml
apiVersion: kubeadm.k8s.io/v1beta3
kind: ClusterConfiguration
kubernetesVersion: v1.30.0
imageRepository: harbor.local/k8s  # Локальный реестр вместо registry.k8s.io
networking:
  podSubnet: "192.168.0.0/16"
  serviceSubnet: "10.96.0.0/12"
---
apiVersion: kubeadm.k8s.io/v1beta3
kind: InitConfiguration
nodeRegistration:
  criSocket: unix:///run/containerd/containerd.sock
```

**4. Настройка DNS для разрешения локального реестра:**

```bash
# В kubeadm-config.yaml добавить DNS-конфигурацию
apiVersion: kubeadm.k8s.io/v1beta3
kind: ClusterConfiguration
dns:
  imageRepository: harbor.local/k8s/coredns  # Локальный реестр
```

---

## Дополнительная информация

### Связанные темы

- [Kubespray: Offline установка](../../../Installation/Kubespray/offline_installation/offline_definitions.md) — базовые понятия и подготовка артефактов для оффлайн-кластера.
- [Kubespray: Диагностика оффлайн-установки](../../../Installation/Kubespray/offline_installation/troubleshooting.md) — решение проблем с Cilium digest и доверием к сертификатам.
- [Определения и терминология](./definitions.md) — базовые статусы `ErrImagePull` и `ImagePullBackOff`.
- [Распространённые ошибки](./common_errors.md) — детальный разбор кодов ошибок (401, 403, 429).
- [Лучшие практики](./best_practices.md) — рекомендации по imagePullPolicy, imagePullSecrets и безопасной цепочке поставок.
- [Пошаговая диагностика](./diagnostics.md) — общий алгоритм поиска причин ошибок загрузки (L1-L5).
- [Сетевые проблемы](./network_issues.md) — отладка DNS, MTU и прокси в Kubernetes.
- [Среды выполнения контейнеров](../../../Concepts/container_runtime.md) — архитектура CRI, containerd и CRI-O.
- [Harbor: Обзор](../../../../Docker/Docker_registries/Harbor/overview.md) — настройка и эксплуатация корпоративного реестра образов.
- [Harbor: Сертификаты](../../../../Docker/Docker_registries/Harbor/certificates.md) — настройка TLS и mTLS для Harbor.
- [Longhorn: Установка в закрытом контуре](../../../Storage/longhorn-air-gapped.md) — практический пример массового переноса образов и деплоя в изоляции.
- [Skopeo: Манипуляции образами](../../../../Podman/skopeo_overview.md) — подробное руководство по синхронизации и зеркалированию.
- [CI/CD: Изолированные среды](../../../../CI-CD/Core_Concepts/air_gapped_environments.md) — общие стратегии синхронизации артефактов и безопасность цепочки поставок.
