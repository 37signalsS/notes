# vCluster — подключение и доступ

> Документ описывает все способы доступа к API виртуального кластера, сетевое взаимодействие между Control Plane, Syncer и удалёнными узлами, а также публикацию API и сервисов наружу. Внутренние механизмы (Syncer, Resource Patching, Backing Store, lifecycle) описаны в [обзоре](./vcluster_overview.md), установка и удаление — в [vcluster_installation.md](./vcluster_installation.md), а RBAC, PSA и изоляция — в [vcluster_security_and_sync.md](./vcluster_security_and_sync.md).

## Определения

**vCluster Connectivity** — совокупность методов и протоколов для обеспечения доступа к API виртуального кластера, а также организации сетевого взаимодействия между его компонентами, нагрузками и внешними ресурсами.

**vCluster VPN (Tailscale-powered)** — встроенный механизм (v0.30+) на базе протокола WireGuard, создающий защищенную P2P-сеть между Control Plane и узлами (особенно Private Nodes). Позволяет соединять компоненты, находящиеся за NAT или в разных сетевых зонах, без использования сложных VPN-решений.

**kubeconfig vCluster** — файл конфигурации для доступа к API-серверу виртуального кластера. Запросы обычно проходят через Syncer-прокси или напрямую (в Standalone-режиме), обеспечивая прозрачную работу стандартных инструментов (kubectl, Helm).

**Gateway API Integration** — нативная поддержка (v0.35+) современного стандарта Kubernetes для управления трафиком. Позволяет использовать ресурсы `Gateway`, `HTTPRoute` и `TLSRoute` для экспонирования API и сервисов vCluster.

**SSL Passthrough** — режим работы Ingress/Gateway, при котором TLS-трафик передается на API-сервер vCluster без терминации. Критически важен для сохранения mTLS-аутентификации между клиентом и виртуальным API.

**Port-Forward (kubectl port-forward)** — механизм туннелирования TCP-соединения от локальной машины к поду или сервису в Kubernetes через Kubelet API. Используется в `vcluster connect` для прозрачного проброса API наружу виртуального кластера.

**Kubeconfig Context** — именованная секция в `~/.kube/config`, объединяющая `cluster`, `user` и `namespace`. Позволяет переключаться между несколькими кластерами одной командой `kubectl config use-context`.

**Exec Credential Plugin** — механизм (kubeconfig `users.user.exec`), при котором клиент kubectl вызывает внешнюю программу для генерации токена. vCluster CLI использует этот механизм, чтобы токены автоматически обновлялись при истечении.

**extraSANs (Subject Alternative Names)** — расширение в `vcluster.yaml` (`networking.proxy.extraSANs`), добавляющее дополнительные DNS-имена и IP-адреса в TLS-сертификат API-сервера виртуального кластера. Необходимо, когда API доступен не только по внутреннему домену, но и по внешнему имени/IP.

**WireGuard** — современный VPN-протокол (UDP), используемый внутри vCluster VPN. Обеспечивает криптографию с минимальным оверхедом и нативно поддерживает P2P-соединения.

**Tailscale (в контексте vCluster)** — управляющая плоскость (control plane) для WireGuard-туннелей внутри vCluster VPN. vCluster использует только протокол, не требуя аккаунта Tailscale — все DERP-реле (Designated Encrypted Relay for Packets) работают внутри инфраструктуры vCluster.

**DERP-реле (Designated Encrypted Relay for Packets)** — резервный канал в vCluster VPN на случай, когда прямой P2P-путь заблокирован файрволом или NAT. Трафик шифруется WireGuard и проходит через релейный узел.

**TUN-устройство** — виртуальный сетевой интерфейс уровня ядра ОС, через который WireGuard-клиент vCluster прозрачно маршрутизирует трафик в виртуальную сеть.

**CNI Plugin (Container Network Interface)** — компонент, реализующий сетевую модель внутри пода (veth-пары, IPAM, маршрутизация). На хосте — Calico/Cilium/Flannel; в Standalone — встроенный CNI.

**CoreDNS** — DNS-сервер внутри vCluster (свой, изолированный от хоста). Резолвит имена сервисов в формате `<svc>.<ns>.svc.cluster.local` в виртуальном адресном пространстве.

**Service ClusterIP** — виртуальный IP из диапазона service-cluster-ip-range, выделяемый kube-proxy'ем сервисам внутри vCluster. Из хоста напрямую недоступен — только через Syncer.

**NodePort / LoadBalancer (sync)** — типы сервисов, которые Syncer умеет пробрасывать из vCluster в хост при включённом `sync.toHost.services.enabled`. На хосте создаётся соответствующий объект с `externalTrafficPolicy` по умолчанию.

**mTLS (mutual TLS)** — TLS с двусторонней аутентификацией. Клиент kubectl проверяет сертификат API vCluster; API проверяет клиентский сертификат (или токен в SA-флоу). Обязательное условие для SSL Passthrough.

**OIDC (OpenID Connect)** — протокол внешней аутентификации, который можно подключить к API vCluster для централизованного SSO (Keycloak, Dex, Authentik).

**RBAC Impersonation** — механизм Kubernetes, при котором пользователь с `impersonate` verb может действовать от имени другого (`kubectl --as=system:serviceaccount:ns:sa`). vCluster использует его, чтобы тенант-админ не получал прав на хост-API.

**Helm Release-метка** — метка `app.kubernetes.io/managed-by=Helm`, по которой Syncer умеет отличать объекты, созданные Helm, и корректно их пересинхронизировать (включая rollback).

## Основные концепции

### Способы получения и управления доступом (kubeconfig)

| Метод | Описание | Сценарий использования |
| :--- | :--- | :--- |
| **vcluster connect** | Автоматическая генерация контекста и проброс портов (port-forward). | Локальная разработка, отладка. |
| **Флаг --export-kubeconfig** | Сохранение конфига в файл по заданному пути. | CI/CD, автоматизация, внешние пользователи. |
| **Background Mode** | Запуск `vcluster connect` в фоновом режиме (через флаг `-b`). | Работа в нескольких терминалах одновременно. |
| **Secret в хост-кластере** | Прямое чтение данных из Secret `vc-<name>` в namespace хоста. | Интеграция с GitOps (ArgoCD/Flux). |
| **vCluster Platform API** | Получение доступа через централизованный портал управления. | Корпоративные среды, SSO-интеграция. |
| **Static kubeconfig (extraSANs)** | Экспорт конфига с фиксированным внешним DNS/IP для долгосрочного использования. | Внешние потребители API, клиенты B2B. |
| **Exec Plugin** | kubeconfig с `user.exec` — клиент сам вызывает `vcluster connect` при первом запросе. | Удобство для разработчиков, прозрачный rotation. |

### Внутренняя архитектура `vcluster connect`

Команда `vcluster connect` под капотом выполняет три действия:

1. **Поиск Syncer-пода** в namespace хоста через клиентский kubeconfig (label selector `app=vcluster,release=<name>`).
2. **Установка port-forward** на TCP-порт подa Syncer (по умолчанию `8443` — это и есть API-сервер виртуального кластера). Соединение идёт через Kubernetes API → apiserver-proxy → kubelet → сетевой namespace пода Syncer.
3. **Генерация kubeconfig**, в котором `server: https://127.0.0.1:<random>` указывает на локальный конец туннеля, а в `user.exec` прописан вызов `vcluster connect ...` для авто-обновления.

```text
┌──────────────┐      kube API       ┌──────────────┐      :8443      ┌────────────┐
│ kubectl      │ ───────────────────>│ kube-apiserver│ ───────────>   │ Syncer pod │
│ (127.0.0.1)  │ <───────────────────│ (host)        │ <───────────   │  (vCluster)│
└──────────────┘   :xxxxx             └──────────────┘                └────────────┘
       ▲                                                                     │
       │                          TCP :8443 внутри vCluster                 │
       └─────────────────────────────────────────────────────────────────────┘
```

Поскольку туннель живёт в одном TCP-соединении, при его разрыве (например, при рестарте Syncer) все текущие kubectl-команды вернут ошибку. Соединение автоматически пересоздаётся при следующем вызове kubectl (благодаря `user.exec`).

### Структура сгенерированного kubeconfig

```yaml
# ~/.kube/config (фрагмент после vcluster connect)
apiVersion: v1
kind: Config
current-context: vcluster_my-vc_my-namespace
contexts:
- name: vcluster_my-vc_my-namespace
  context:
    cluster: vcluster_my-vc_my-namespace
    user: vcluster_my-vc_my-namespace
    namespace: default
clusters:
- name: vcluster_my-vc_my-namespace
  cluster:
    server: https://127.0.0.1:18443          # <- локальный конец port-forward
    insecure-skip-tls-verify: false
    certificate-authority-data: <base64>      # <- CA vCluster
users:
- name: vcluster_my-vc_my-namespace
  user:
    exec:                                    # <- авто-обновление контекста
      apiVersion: client.authentication.k8s.io/v1
      command: vcluster
      args:
      - connect
      - my-vc
      - -n
      - my-namespace
      - --background
```

> **Важно:** поле `insecure-skip-tls-verify` отсутствует. TLS проверяется по CA, который выдан API-сервером vCluster. Этот CA уникален для каждого vCluster и не совпадает с CA хоста.

### Механизмы синхронизации ресурсов для связности

Связность обеспечивается Syncer через два основных направления синхронизации:

1.  **fromHost (Импорт):** Проброс ресурсов хост-кластера (`StorageClasses`, `IngressClasses`, `GatewayClasses`, `Nodes`) внутрь vCluster для их использования тенантами.
2.  **toHost (Экспорт):** Публикация объектов vCluster (`Pods`, `Services`, `Ingresses`, `HTTPRoutes`) в хост-кластер для фактического исполнения и сетевой доступности.

### Маршрутизация DNS внутри vCluster

Внутри vCluster работает собственный CoreDNS. Цепочка резолва:

```text
pod-в-vCluster → CoreDNS (10.96.0.10 внутри vCluster)
                       │
                       ├─ → cache hit (все запросы)
                       ├─ → forward . (kube-dns в хост-кластере, если forwardPlugin настроен)
                       └─ → NXDOMAIN для внешних имён (по умолчанию)
```

По умолчанию CoreDNS в vCluster изолирован: имена `*.svc.cluster.local` резолвятся только в виртуальном пространстве. Чтобы тенант мог обращаться к внешним сервисам хоста, необходимо включить `sync.fromHost.services` либо настроить stub-domains через `coredns.stubs`.

### Сетевая архитектура vCluster VPN

При использовании **Private Nodes** или **Standalone-режима** классический port-forward может быть недоступен. vCluster VPN решает эту задачу:
- **P2P Соединение:** Control Plane и узлы устанавливают прямые туннели по WireGuard.
- **DERP-реле:** Если прямой путь заблокирован файрволом, трафик автоматически ретранслируется через защищённые реле.
- **Автономность:** Не требует внешнего аккаунта Tailscale, работает полностью внутри инфраструктуры vCluster.
- **Маппинг сервисов:** VPN автоматически публикует ClusterIP виртуального кластера узлам через wg-интерфейс, делая `svc.cluster.local` доступным с удалённой ноды.

### Внешний доступ через Gateway API и Ingress

Для доступа к API vCluster извне (North-South трафик) используются два основных подхода:
- **Ingress (NGINX/Traefik):** Требует аннотации `ssl-passthrough`.
- **Gateway API (Cilium/Envoy):** Использует `TLSRoute` с режимом `Passthrough`, что является более современным и гибким стандартом.

#### Сравнение Ingress и Gateway API для vCluster

| Критерий | Ingress (NGINX/Traefik) | Gateway API (Cilium/Envoy) |
| :--- | :--- | :--- |
| **Стандарт** | Kubernetes Ingress (v1) | Gateway API (GA с 1.28) |
| **TLS Passthrough** | Аннотация `ssl-passthrough: "true"` | `TLSRoute` с `mode: Passthrough` |
| **Multi-tenant** | Один контроллер — много namespaces | Gateway может шарить на namespaces через `listeners` |
| **Конфигурация для vCluster** | `networking.ingress.*` | `networking.gatewayAPI.*` |
| **Когда выбирать** | Legacy-инфраструктура, NGINX-привычки | Новый кластер, Cilium/Envoy, мульти-тенант |
| **Стоимость поддержки** | Средняя (аннотации) | Низкая (CRD-декларативность) |

## Практические сценарии

### Подключение через vCluster CLI

```bash
# Интерактивное подключение (автоматический port-forward)
vcluster connect my-vcluster -n my-namespace

# Запуск подключения в фоновом режиме (флаг --background или -b)
vcluster connect my-vcluster -n my-namespace --background

# Экспорт kubeconfig в файл для CI/CD или внешних инструментов
vcluster connect my-vcluster -n my-namespace \
  --export-kubeconfig ./vcluster_kubeconfig.yaml

# Обновление текущего контекста в системном ~/.kube/config (флаг --update-current)
vcluster connect my-vcluster -n my-namespace --update-current

# Выполнение разовой команды внутри vCluster без смены контекста
vcluster connect my-vcluster -n my-namespace -- kubectl get pods -A

# Указать конкретный локальный порт (по умолчанию — случайный свободный)
vcluster connect my-vc -n my-namespace --local-port 18443

# Подключение к Standalone-кластеру (прямой API на хосте)
vcluster connect standalone-vc --kubeconfig /var/lib/vcluster/mgmt/kubeconfig.yaml

# Использовать существующий контекст (для multi-context CI)
vcluster connect my-vc -n my-namespace --context my-host-context
```

### Извлечение kubeconfig из Kubernetes Secret

Если CLI недоступен, конфиг можно получить напрямую из секрета хост-кластера. Данные хранятся в секрете `vc-<vcluster-name>`.

```bash
# Извлечение и декодирование конфигурации
kubectl get secret -n <vcluster-namespace> vc-<vcluster-name> \
  -o jsonpath='{.data.config}' | base64 -d > kubeconfig.yaml

export KUBECONFIG=kubeconfig.yaml
kubectl get nodes
```

> **Альтернативный путь к данным:** в некоторых версиях данные конфигурации лежат в поле `kubeconfig` (не `config`). Проверяется через `kubectl get secret vc-<name> -o jsonpath='{.data}' | jq 'keys'`.

### Генерация read-only kubeconfig для внешних потребителей

Часто требуется выдать внешнему клиенту доступ только на чтение namespace. vCluster позволяет создать ServiceAccount, пробросить его токен в host-secret и сгенерировать kubeconfig с фиксированными extraSANs.

```bash
# 1. Создаём SA внутри vCluster с минимальными правами
vcluster connect my-vc -n my-namespace -- bash -c '
kubectl -n tenant-ns create serviceaccount viewer
kubectl -n tenant-ns create rolebinding viewer --clusterrole=view --serviceaccount=tenant-ns:viewer
'

# 2. Долгоиграющий токен (Kubernetes <1.24 или явный Secret)
cat <<EOF | kubectl -n tenant-ns apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: viewer-token
  annotations:
    kubernetes.io/service-account.name: viewer
type: kubernetes.io/service-account-token
EOF

# 3. Собираем kubeconfig вручную (пример для выдачи наружу)
SERVER=https://vcluster-api.example.com
CA=$(kubectl get secret -n my-namespace vc-my-vc -o jsonpath='{.data.ca\.crt}' | base64 -d | base64 -w0)
TOKEN=$(kubectl -n tenant-ns get secret viewer-token -o jsonpath='{.data.token}' | base64 -d)

cat > viewer-kubeconfig.yaml <<EOF
apiVersion: v1
kind: Config
clusters:
- name: my-vc
  cluster:
    server: ${SERVER}
    certificate-authority-data: ${CA}
contexts:
- name: viewer
  context:
    cluster: my-vc
    user: viewer
    namespace: tenant-ns
current-context: viewer
users:
- name: viewer
  user:
    token: ${TOKEN}
EOF
```

> В v0.34+ поддерживается `vcluster token create` — CLI сам собирает read-only kubeconfig с указанным TTL и extraSANs.

### Подключение ArgoCD/Flux к vCluster через Secret

GitOps-агенту не нужен `vcluster connect` — он читает данные напрямую из хоста:

```yaml
# argocd-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-vc-apps
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/myorg/manifests.git
    targetRevision: main
    path: overlays/dev
  destination:
    # Внутренний API через Syncer-прокси
    server: https://kubernetes.default.svc
    namespace: tenant-ns
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

> **Тонкий момент:** ArgoCD-оператор, развёрнутый на хосте, может ходить в Syncer через тот же Service Account (ClusterRole с `impersonate`), либо ArgoCD-приложение может таргетить `https://<vc-host-service>:443` — в этом случае потребуется проброс через Ingress/Gateway.

### Активация vCluster VPN (v0.30+)

Используется для обеспечения прозрачной сетевой связности с удаленными узлами через WireGuard туннель.

**Настройка в vcluster.yaml:**

```yaml
# vcluster.yaml
networking:
  vpn:
    enabled: true
    # Автоматическое подключение агентов (опционально)
    autoConnect: true
```

### Настройка синхронизации StorageClass (fromHost)

Позволяет пользователям vCluster использовать существующие системы хранения хост-кластера.

**Шаг 1: Настройка в vcluster.yaml**

```yaml
# vcluster.yaml
sync:
  fromHost:
    storageClasses:
      enabled: true
```

**Шаг 2: Создание PVC внутри виртуального кластера**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc
spec:
  storageClassName: fast-ssd-storage  # Имя SC из хост-кластера
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 10Gi
```

### Настройка синхронизации Ingress (toHost)

Позволяет публиковать приложения vCluster через Ingress-контроллер хост-кластера.

**Шаг 1: Активация синхронизации в vcluster.yaml**

```yaml
# vcluster.yaml
sync:
  fromHost:
    ingressClasses:
      enabled: true
  toHost:
    ingresses:
      enabled: true
```

**Шаг 2: Создание Ingress внутри vCluster**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-ingress
spec:
  ingressClassName: nginx-public  # Класс из хост-кластера
  rules:
    - host: app.vcluster.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend-svc
                port: { number: 80 }
```

### Доступ к API через Gateway API (TLSRoute)

Современный метод предоставления доступа к API-серверу виртуального кластера (v0.35+).

**Настройка в vcluster.yaml:**

```yaml
# vcluster.yaml
networking:
  gatewayAPI:
    enabled: true
    apiServer:
      enabled: true
      host: "vcluster-api.example.com"
      gatewayRef:
        name: "external-gateway"
        namespace: "infra"
  proxy:
    extraSANs:
      - "vcluster-api.example.com"
```

### Доступ к API vCluster через Ingress хост-кластера

Традиционный метод экспонирования API с использованием SSL Passthrough.

**Конфигурация vcluster.yaml:**

```yaml
# vcluster.yaml
networking:
  ingress:
    enabled: true
    host: "vcluster-api.example.com"
    annotations:
      # Настройка для NGINX Ingress Controller
      nginx.ingress.kubernetes.io/ssl-passthrough: "true"
  proxy:
    extraSANs:
      - "vcluster-api.example.com"
      - "1.2.3.4" # Опционально: внешний IP
```

### Проброс дополнительных портов (UI, dashboard, debugging)

Команда `vcluster connect` пробрасывает только API (порт 8443 внутри Syncer). Если внутри vCluster работает UI (Lens, headlamp, dashboard) или отладочный сервис, port-forward нужно поднять отдельно:

```bash
# Dashboard внутри vCluster — проброс наружу на локальный порт
vcluster connect my-vc -n my-namespace --background --local-port 18443
kubectl --kubeconfig ./vcluster_kubeconfig.yaml -n kubernetes-dashboard port-forward svc/kubernetes-dashboard 8443:443 --address 0.0.0.0
# → открыть https://localhost:8443

# Headlamp (мульти-кластер UI)
kubectl --kubeconfig ./vcluster_kubeconfig.yaml -n headlamp port-forward svc/headlamp 8080:80
# → http://localhost:8080
```

> **Предупреждение:** пробрасывая `--address 0.0.0.0`, вы открываете сервис на всех интерфейсах хоста. На публичных машинах обязательно ограничьте через firewall или используйте SSH-туннель.

### Прокидывание пользовательского CA (Private CA / корпоративный прокси)

Когда корпоративный egress перехватывает TLS через корпоративный CA, kubectl внутри CI-агента не может проверить сертификат API. Решение — прокинуть CA в extraSANs/CA-bundle.

```bash
# Вариант 1: глобальный CA-bundle на стороне клиента
export SSL_CERT_FILE=/etc/ssl/certs/corp-ca-bundle.pem
vcluster connect my-vc -n my-namespace --update-current

# Вариант 2: сертификат встроен прямо в kubeconfig
vcluster connect my-vc -n my-namespace \
  --export-kubeconfig ./vcluster_kubeconfig.yaml
CERT=$(cat corp-ca.crt | base64 -w0)
yq -i ".clusters[0].cluster.certificate-authority-data = \"${CERT}\"" ./vcluster_kubeconfig.yaml
```

> **Альтернатива (v0.36+):** `vcluster connect --server-ca-bundle <path>` — CLI сам встраивает CA в экспортированный конфиг.

### Подключение через корпоративный HTTP/HTTPS-прокси

В закрытых контурах kubectl может ходить через `HTTPS_PROXY`. vcluster CLI учитывает стандартные переменные окружения:

```bash
export HTTPS_PROXY=http://proxy.corp.local:3128
export NO_PROXY=127.0.0.1,localhost,.svc.cluster.local
vcluster connect my-vc -n my-namespace --update-current
```

> **Ограничение:** port-forward туннелируется через Kubernetes API (apiserver-proxy), который ходит через тот же прокси. Если прокси терминирует TLS на своей стороне (SSL-инспекция), сертификат API vCluster будет подменён — потребуется прописать `NO_PROXY` для endpoint'а apiserver.

### Подключение OIDC (Keycloak/Dex) для SSO-доступа

Если в компании уже развёрнут Keycloak/Dex, можно подключить его к API vCluster, избавившись от локальных токенов.

```yaml
# vcluster.yaml
controlPlane:
  distro:
    k8s:
      enabled: true
  apiserver:
    # Передача флагов напрямую в kube-apiserver
    extraArgs:
      - --oidc-issuer-url=https://keycloak.corp.local/realms/k8s
      - --oidc-client-id=vcluster
      - --oidc-username-claim=preferred_username
      - --oidc-groups-claim=groups
      - --oidc-ca-file=/etc/ssl/certs/keycloak-ca.crt
```

После применения пользователи смогут получать kubeconfig через стандартный OIDC-флоу:

```bash
vcluster oidc login my-vc -n my-namespace \
  --oidc-issuer https://keycloak.corp.local/realms/k8s \
  --oidc-client-id vcluster
# → откроется браузер, после аутентификации kubeconfig обновится
```

> **Ограничение:** OIDC-флаг нельзя поменять в Standalone-режиме без рестарта процесса. Для Hot-reload используйте внешний `kubectl auth-proxy` (oauth2-proxy) перед vCluster API.

### Smoke-test: проверка корректности подключения

После развёртывания vCluster и активации `connect` необходимо проверить, что все уровни связности работают:

```bash
# 1. Туннель живой
curl -k https://127.0.0.1:18443/healthz
# → ok

# 2. API отвечает
kubectl --kubeconfig ./vcluster_kubeconfig.yaml get --raw=/version
# → {"major":"1","minor":"36","gitVersion":"v1.36.0",...}

# 3. Виртуальные ноды видны
kubectl --kubeconfig ./vcluster_kubeconfig.yaml get nodes
# → NAME           STATUS   ROLES                  VERSION
# → vcluster-node  Ready    control-plane,master   v1.36.0

# 4. DNS внутри vCluster
kubectl --kubeconfig ./vcluster_kubeconfig.yaml -n kube-system \
  run dnstest --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default
# → Server: 10.96.0.10
# → Address 1: 10.96.0.10 kube-dns.kube-system.svc.cluster.local
# → Name: kubernetes.default
# → Address 1: 10.96.0.1

# 5. Workload стартует и виден на хосте
kubectl --kubeconfig ./vcluster_kubeconfig.yaml run nginx --image=nginx
sleep 5
kubectl -n my-namespace get pods -l vcluster.loft.sh/managed-by
# → nginx-my-vc-xxx  1/1  Running
```

### Диагностика проблем подключения

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `vcluster connect` зависает на 30s, потом `context deadline exceeded` | Syncer-под не Ready или CrashLoopBackOff. | `kubectl -n my-namespace get pods`; `kubectl -n my-namespace logs <syncer-pod>`. |
| `dial tcp 127.0.0.1:xxxx: connect: connection refused` | port-forward упал, фоновая задача завершилась. | Перезапустить `vcluster connect --background`. |
| `x509: certificate is valid for vcluster-my-vc, not vcluster-api.example.com` | Не добавлен extraSAN для внешнего домена. | Прописать `networking.proxy.extraSANs` и `vcluster restart`. |
| `forbidden: User "system:anonymous" cannot get path "/api"` | Exec-плагин не отработал (kubectl не нашёл vcluster CLI в PATH). | `which vcluster`; проверить `PATH` в окружении kubectl. |
| `Unable to connect to the server: net/http: TLS handshake timeout` | Через корпоративный прокси, либо MTU несоответствие. | Проверить `HTTPS_PROXY`, уменьшить MTU на интерфейсе pod (через CNI host). |
| `kubectl get pods` показывает только kube-system, а workload'ы в Pending | Syncer не зарегистрировал виртуальные ноды. | Включить `sync.fromHost.nodes.enabled: true` в `vcluster.yaml`. |
| Внутри vCluster DNS не резолвит сервисы хоста | `sync.fromHost.services` отключён или CoreDNS не знает о stub-зонах. | Включить sync или прописать `coredns.stubs: { corp.local: ["10.96.0.10"] }`. |
| `vcluster oidc login` редиректит на localhost, но порт закрыт | Браузер не может достучаться до localhost:port после редиректа Keycloak. | Открыть порт через SSH-туннель: `ssh -L 8000:localhost:8000 user@ci-runner`. |
| `Gateway API: route not reconciled` | В vCluster не установлен GatewayClass, либо `gatewayRef` указывает на чужой namespace. | `kubectl get gatewayclasses`; проверить RBAC между namespace. |
| VPN-туннель не поднимается (WireGuard handshake fail) | Блокирующий UDP-порт или MTU >1450 в сети узла. | Включить `--vpn.useDERP=true`; снизить MTU через CNI. |
| `kubectl exec` через port-forward падает с EOF | Соединение рвётся при простое; некоторые версии kubectl не делают reconnect. | Использовать `vcluster connect --background` с перезапуском. |

### Наблюдаемость сетевой связности

Для SRE важно видеть, что туннели и proxy живы. Снимаются три потока метрик:

| Источник | Что показывает | Способ сбора |
| :--- | :--- | :--- |
| **Syncer logs (stdout JSON)** | Успешность синхронизации каждого объекта, watch-таймауты, ошибки. | Loki Promtail / Vector / Fluent Bit. |
| **API Server metrics (`:8443/metrics`)** | Задержки запросов, watch-коннекты, RBAC-отказы. | Prometheus (scrape через serviceMonitor внутри vCluster). |
| **WireGuard stats (на хосте)** | Handshake-время, передано байт, активные пиры. | `wg show all` через node-exporter textfile collector. |

Ключевые алерты:

- `vcluster_syncer_watch_errors_total > 5 за 5m` — деградация связности с хостом.
- `apiserver_request_duration_seconds{verb="CONNECT"} > 1s` в течение 10m — туннель медленный.
- `wireguard_latest_handshake_seconds > 180` — peer vCluster VPN отвалился.
- `kube_pod_container_status_restarts_total{pod=~"vcluster-.*"} > 0` — рестарт Syncer.

### Логирование и аудит доступа

```yaml
# vcluster.yaml — включение audit-лога API vCluster
controlPlane:
  apiserver:
    auditLog:
      enabled: true
      policy:
        level: Metadata
        path: /var/log/vcluster/audit.log
```

```bash
# Просмотр последних событий доступа
kubectl -n my-namespace exec <syncer-pod> -- tail -f /var/log/vcluster/audit.log
# → {"kind":"Event","apiVersion":"audit.k8s.io/v1","level":"Metadata",...}
```

> **Для SRE:** audit-log лучше сразу направлять в Loki/Elasticsearch. На хост-кластере pod-Syncer обычно уже подключён к log-agent'у — дополнительной настройки не требуется.

### Лучшие практики связности

- **Не использовать port-forward в production:** port-forward предназначен для разработки и CI. Для стабильного production-доступа разворачивайте API через Gateway API или Ingress с SSL Passthrough.
- **extraSANs для каждого внешнего имени:** если API vCluster доступен по нескольким DNS-именам, все они должны быть в `proxy.extraSANs` Иначе клиенты увидят `x509: certificate is valid for ...`.
- **Exec-credential plugin в проде:** kubeconfig с `user.exec` сам обновляет токены и переподнимает port-forward — меньше ручных операций, меньше забытых сертификатов.
- **Healthcheck перед скриптами:** любая автоматизация, использующая `vcluster connect`, должна сначала проверить `/healthz` через `curl -k` — иначе первый kubectl-вызов отдаст EOF.
- **DNS-форвардинг только при необходимости:** изоляция CoreDNS — фича, а не баг. Включайте stub-зоны только для конкретных внешних доменов (например, `.corp.local`).
- **VPN-маршрутизация для Private Nodes:** привязывайте `cidrs` строго к нужным подсетям; широкое `0.0.0.0/0` через WireGuard-туннель создаст ненужный routing loop.
- **TTL токенов ServiceAccount:** для короткоживущих CI-токенов используйте BoundServiceAccountToken (TTL 1h); для долгоживущих — ручной Secret + ротация каждые 30 дней.
- **Audit-log в WORM-хранилище:** если vCluster обрабатывает ПДн, audit-log API vCluster должен уходить в S3/WORM-бакет с retention ≥1 год.
- **Контроль `sync.fromHost.services`:** проброс сервисов хоста во vCluster открывает внутренние endpoint'ы. Включайте точечно, с whitelist по namespace.

### Ограничения и edge-cases

| Сценарий | Поведение | Обходной путь |
| :--- | :--- | :--- |
| **kubectl exec через port-forward** | Может зависнуть при простое >60s | Использовать `--request-timeout=30s` и retry |
| **IPv6-only хост** | vCluster пока тестируется на dual-stack; IPv6-single может не работать в `connect` | Включить dual-stack CNI на хосте |
| **MTU < 1500 (VXLAN, IPSec)** | WireGuard-пакеты фрагментируются, деградация | Снизить MTU внутри vCluster до 1380 через CNI |
| **Корпоративный SSL-inspection прокси** | Подмена сертификата API vCluster | Прописать `NO_PROXY` для endpoint kube-apiserver; внести CA в trust |
| **Параллельный `vcluster connect` в одном терминале** | Каждый запуск создаёт свой контекст; конфликта портов не будет (рандом) | Указывать `--local-port` явно |
| **vCluster за NAT, обращение извне** | Прямой Ingress/Gateway не сработает без проброса портов | Включить vCluster VPN; туннелировать API через WireGuard |
| **Множество тенантов на одном LoadBalancer** | Разделение по SNI/host — не SNI-mutual | Использовать отдельный IP или SAN на сертификате |
| **ArgoCD `selfHeal` + Sleep Mode** | ArgoCD будет будить vCluster чаще, чем ожидалось | Настроить `ignoreDifferences` или отключить selfHeal на спящих средах |
| **IPv4/IPv6 dual-stack Service** | `sync.toHost.services` пока копирует только `clusterIP`, dual-stack игнорируется | Создавать Service вручную в namespace хоста |
| **SOCKS/HTTPS-прокси с auth** | vcluster CLI не запрашивает интерактивно пароль прокси | Использовать `connect-proxy` обёртку или `corkscrew` |

### Очистка

```bash
# Остановить фоновый port-forward
vcluster disconnect my-vc -n my-namespace

# Удалить контекст из ~/.kube/config
kubectl config delete-context vcluster_my-vc_my-namespace
kubectl config delete-user vcluster_my-vc_my-namespace
kubectl config delete-cluster vcluster_my-vc_my-namespace

# Полная очистка (cluster + secret + контекст)
vcluster delete my-vc -n my-namespace
kubectl config delete-context vcluster_my-vc_my-namespace
```

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — установка и развертывание](./vcluster_installation.md)
- [vCluster — безопасность и синхронизация ресурсов](./vcluster_security_and_sync.md)

### См. также

- [Gateway API — Определения и концепции](../../Networking/gateway_api/definitions.md)
- [Kubeconfig и управление доступом](../../Operations/kubeconfig_and_connection.md)
- [Pod — практические команды](../../Base/Pod/pod_practical_scenarios_commands.md) (port-forward, exec)

### Внешние ссылки

- [vCluster Networking & Connectivity](https://www.vcluster.com/docs/architecture/networking)
- [Gateway API Integration Guide](https://www.vcluster.com/docs/features/gateway-api)
- [vCluster VPN (Tailscale) Deep Dive](https://www.vcluster.com/docs/features/vpn)
- [kubectl port-forward RFC](https://github.com/kubernetes/kubernetes/blob/master/pkg/kubectl/cmd/portforward/portforward.go)
