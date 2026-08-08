# vCluster — подключение и доступ

## Определения

**vCluster Connectivity** — совокупность методов и протоколов для обеспечения доступа к API виртуального кластера, а также организации сетевого взаимодействия между его компонентами, нагрузками и внешними ресурсами.

**vCluster VPN (Tailscale-powered)** — встроенный механизм (v0.30+) на базе протокола WireGuard, создающий защищенную P2P-сеть между Control Plane и узлами (особенно Private Nodes). Позволяет соединять компоненты, находящиеся за NAT или в разных облачных провайдерах, без использования сложных VPN-решений.

**kubeconfig vCluster** — файл конфигурации для доступа к API-серверу виртуального кластера. Запросы обычно проходят через Syncer-прокси или напрямую (в Standalone-режиме), обеспечивая прозрачную работу стандартных инструментов (kubectl, Helm).

**Gateway API Integration** — нативная поддержка (v0.35+) современного стандарта Kubernetes для управления трафиком. Позволяет использовать ресурсы `Gateway`, `HTTPRoute` и `TLSRoute` для экспонирования API и сервисов vCluster.

**SSL Passthrough** — режим работы Ingress/Gateway, при котором TLS-трафик передается на API-сервер vCluster без терминации. Критически важен для сохранения mTLS-аутентификации между клиентом и виртуальным API.

## Основные концепции

### Способы получения и управления доступом (kubeconfig)

| Метод | Описание | Сценарий использования |
| :--- | :--- | :--- |
| **vcluster connect** | Автоматическая генерация контекста и проброс портов (port-forward). | Локальная разработка, отладка. |
| **Флаг --export-kubeconfig** | Сохранение конфига в файл по заданному пути. | CI/CD, автоматизация, внешние пользователи. |
| **Background Mode** | Запуск `vcluster connect` в фоновом режиме (через флаг `-b`). | Работа в нескольких терминалах одновременно. |
| **Secret в хост-кластере** | Прямое чтение данных из Secret `vc-<name>` в namespace хоста. | Интеграция с GitOps (ArgoCD/Flux). |
| **vCluster Platform API** | Получение доступа через централизованный портал управления. | Корпоративные среды, SSO-интеграция. |

### Механизмы синхронизации ресурсов для связности

Связность обеспечивается Syncer через два основных направления синхронизации:

1.  **fromHost (Импорт):** Проброс ресурсов хост-кластера (`StorageClasses`, `IngressClasses`, `GatewayClasses`, `Nodes`) внутрь vCluster для их использования тенантами.
2.  **toHost (Экспорт):** Публикация объектов vCluster (`Pods`, `Services`, `Ingresses`, `HTTPRoutes`) в хост-кластер для фактического исполнения и сетевой доступности.

### Сетевая архитектура vCluster VPN

При использовании **Private Nodes** или **Standalone-режима** классический port-forward может быть недоступен. vCluster VPN решает эту задачу:
- **P2P Соединение:** Control Plane и узлы устанавливают прямые туннели.
- **DERP-реле:** Если прямой путь заблокирован файрволом, трафик автоматически ретранслируется через защищенные реле.
- **Автономность:** Не требует внешнего аккаунта Tailscale, работает полностью внутри инфраструктуры vCluster.

### Внешний доступ через Gateway API и Ingress

Для доступа к API vCluster извне (North-South трафик) используются два основных подхода:
- **Ingress (NGINX/Traefik):** Требует аннотации `ssl-passthrough`.
- **Gateway API (Cilium/Envoy):** Использует `TLSRoute` с режимом `Passthrough`, что является более современным и гибким стандартом.

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

## Дополнительная информация

### Внутренние ссылки

- [vCluster — обзор и архитектура](./vcluster_overview.md)
- [vCluster — установка и развертывание](./vcluster_installation.md)
- [vCluster — безопасность и синхронизация ресурсов](./vcluster_security_and_sync.md)

### См. также

- [Gateway API — Определения и концепции](../../Networking/gateway_api/definitions.md)
- [Kubeconfig и управление доступом](../../Operations/kubeconfig_and_connection.md)

### Внешние ссылки

- [vCluster Networking & Connectivity](https://www.vcluster.com/docs/architecture/networking)
- [Gateway API Integration Guide](https://www.vcluster.com/docs/features/gateway-api)
- [vCluster VPN (Tailscale) Deep Dive](https://www.vcluster.com/docs/features/vpn)
