# NetworkPolicy: Изоляция тенантов (Multi-tenancy)

## Определения

**Multi-tenancy NetworkPolicy** — набор правил сетевой изоляции, обеспечивающих разделение трафика между тенантами (командами, проектами, клиентами) в рамках одного Kubernetes-кластера. Комбинирует стандартные NetworkPolicy, ANP/BANP и CNI-специфичные расширения.

**Namespace-as-Tenant** — модель мультитенантности, при которой каждый тенант представлен одним или несколькими Namespace с изолированной сетью, RBAC и ResourceQuotas.

**Tenant Isolation (Изоляция тенанта)** — стратегия, при которой тенант не может видеть или взаимодействовать с ресурсами других тенантов без явного разрешения. Включает сетевую (NetworkPolicy), вычислительную (ResourceQuota) и управление доступом (RBAC) изоляцию.

**Shared Services (Общие сервисы)** — компоненты инфраструктуры (monitoring, logging, CI/CD), доступные всем тенантам. Требуют осторожного применения NetworkPolicy для баланса между изоляцией и доступностью.

**Soft Tenancy** — программная изоляция через Namespace + RBAC. Предполагает кооперативных тенантов (внутренние команды). NetworkPolicy защищает от случайных ошибок, а не от атак.

**Hard Tenancy** — аппаратная изоляция для враждебных тенантов. NetworkPolicy — дополнение к выделенным узлам/кластерам, не замена.

## Базовые Концепции

### Модель сетевой изоляции тенантов

```
┌─────────────────────────────────────────────────────────┐
│                    Cluster Level                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  ANP: Default Deny + Allow Shared Services      │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌──────────────────┐  ┌──────────────────┐            │
│  │ Tenant A          │  │ Tenant B          │            │
│  │ (team-alpha ns)   │  │ (team-beta ns)    │            │
│  │                   │  │                   │            │
│  │ ┌──────────────┐ │  │ ┌──────────────┐ │            │
│  │ │ Default Deny  │ │  │ │ Default Deny  │ │            │
│  │ │ + Allow Apps  │ │  │ │ + Allow Apps  │ │            │
│  │ └──────────────┘ │  │ └──────────────┘ │            │
│  └──────────────────┘  └──────────────────┘            │
│              │                    │                      │
│              └────────┬───────────┘                      │
│                       ▼                                  │
│            ┌──────────────────┐                         │
│            │ Shared Namespace  │                         │
│            │ (monitoring, ci)  │                         │
│            │ Restricted access │                         │
│            └──────────────────┘                         │
└─────────────────────────────────────────────────────────┘
```

### Три слоя сетевой изоляции

| Слой | Механизм | Ответственность | Пример |
| :--- | :--- | :--- | :--- |
| **Tier 1 (Global)** | ANP | Platform Team: блокировка metadata, меж-tenant трафик | `Deny` трафик между tenant namespaces |
| **Tier 2 (Namespace)** | NetworkPolicy | Dev Team: изоляция сервисов внутри tenant | Default Deny + Allow frontend→backend |
| **Tier 3 (Baseline)** | BANP | Fallback: если tenant не настроил свои правила | Default Deny для всех |

### Паттерны сетевой изоляции

| Паттерн | Описание | Уровень изоляции |
| :--- | :--- | :--- |
| **Default Deny + DNS** | Базовый: все заблокировано, разрешен только DNS | Базовый |
| **Tenant Namespace Isolation** | Полная изоляция между namespaces | Средний |
| **Cross-Tenant Deny (ANP)** | Глобальный запрет меж-tenant трафика | Высокий |
| **Shared Services Pattern** | Контролируемый доступ к общим сервисам | Средний |
| **Egress Isolation** | Блокировка внешнего трафика для tenant | Средний |
| **Pod Security + NetworkPolicy** | Комбинирование PSS с сетевой изоляцией | Высокий |

## Практические сценарии

### Сценарий 1: Базовая изоляция Tenant (Default Deny)

Каждый тенант получает свой namespace с Default Deny:

```yaml
# Tenant A: team-alpha
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: team-alpha
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
---
# Tenant B: team-beta
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: team-beta
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
```

#### Валидация

```bash
# Создание namespace
kubectl create namespace team-alpha
kubectl create namespace team-beta

# Применение политик
kubectl apply -f tenant-isolation.yaml

# Проверка: поды team-alpha НЕ могут достичь team-beta
kubectl run test-alpha --image=busybox --restart=Never -n team-alpha -- \
  wget -qO- --timeout=3 http://service-beta.team-beta.svc
# → connection timed out

# Проверка: поды team-alpha НЕ могут достичь друг друга (Default Deny Ingress)
kubectl run test-1 --image=busybox --restart=Never -n team-alpha -- sleep 3600
kubectl run test-2 --image=busybox --restart=Never -n team-alpha -- sleep 3600
kubectl exec -n team-alpha test-1 -- wget -qO- --timeout=3 http://test-2.team-alpha.svc
# → connection timed out
```

### Сценарий 2: Разрешение внутри-tenant трафика + DNS

После Default Deny разрешаем необходимый трафик:

```yaml
# 1. DNS (обязательно)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: team-alpha
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
---
# 2. Frontend → Backend (внутри tenant)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: team-alpha
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - protocol: TCP
      port: 8080
---
# 3. Backend → Database (внутри tenant)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-backend-to-db
  namespace: team-alpha
spec:
  podSelector:
    matchLabels:
      app: database
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: backend
    ports:
    - protocol: TCP
      port: 5432
```

### Сценарий 3: ANP — Глобальный запрет меж-tenant трафика

Запрет любого трафика между tenant namespaces на уровне Platform Team:

```yaml
apiVersion: policy.networking.k8s.io/v1alpha1
kind: AdminNetworkPolicy
metadata:
  name: deny-cross-tenant
spec:
  priority: 10
  selector:
    matchLabels:
      multi-tenant: "true"
  ingress:
  - action: Deny
    from:
    - namespaceSelector:
        matchLabels:
          multi-tenant: "true"
  egress:
  - action: Deny
    to:
    - namespaceSelector:
        matchLabels:
          multi-tenant: "true"
```

> **Примечание:** ANP блокирует трафик между tenant namespaces, но разрешает трафик к shared services (monitoring, logging), если они не помечены `multi-tenant: "true"`.

### Сценарий 4: Shared Services — контролируемый доступ

Доступ к общим сервисам (monitoring, CI/CD) для всех tenant:

```yaml
# 1. Monitoring namespace: разрешить доступ от tenant namespaces
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-tenant-to-monitoring
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app: prometheus
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          multi-tenant: "true"
    ports:
    - protocol: TCP
      port: 9090
---
# 2. Tenant namespace: разрешить доступ к monitoring
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-monitoring
  namespace: team-alpha
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - protocol: TCP
      port: 9090
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Сценарий 5: Egress Isolation для Tenant

Блокировка внешнего трафика для tenant, доступ только к internal ресурсам:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: restrict-egress-internal-only
  namespace: team-beta
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  # DNS
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # Только внутренние сети (RFC1918)
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
    - ipBlock:
        cidr: 172.16.0.0/12
    - ipBlock:
        cidr: 192.168.0.0/16
    # Кластерный под CIDR
    - ipBlock:
        cidr: 100.64.0.0/16
```

### Сценарий 6: Namespace Labeling Strategy

Стандартизация меток для управления тенантами:

```bash
# Навешивание меток на namespace
kubectl label namespace team-alpha \
  multi-tenant=true \
  tenant=team-alpha \
  tier=application \
  env=production

kubectl label namespace team-beta \
  multi-tenant=true \
  tenant=team-beta \
  tier=application \
  env=production

kubectl label namespace monitoring \
  shared-service=true \
  tier=platform

kubectl label namespace kube-system \
  shared-service=true \
  tier=platform
```

**Рекомендуемые метки:**

| Метка | Значение | Назначение |
| :--- | :--- | :--- |
| `multi-tenant` | `true` | Идентификация tenant namespace |
| `tenant` | `<name>` | Имя тенанта для селекторов |
| `shared-service` | `true` | Общий сервис (monitoring, CI/CD) |
| `tier` | `platform` / `application` | Уровень: платформа или приложение |
| `env` | `production` / `staging` | Окружение |

## Дополнительная информация

### Чек-лист сетевой изоляции тенантов

| # | Действие | Приоритет |
| :--- | :--- | :--- |
| 1 | Создать Default Deny в каждом tenant namespace | Критический |
| 2 | Разрешить DNS (UDP/TCP 53) | Критический |
| 3 | Разрешить intra-tenant трафик | Высокий |
| 4 | Создать ANP для глобального запрета cross-tenant | Высокий |
| 5 | Настроить доступ к shared services | Средний |
| 6 | Блокировать cloud metadata endpoint | Высокий |
| 7 | Включить Egress isolation (опционально) | Средний |
| 8 | Добавить ResourceQuotas для tenant | Средний |

### Soft vs Hard Tenancy: NetworkPolicy

| Критерий | Soft Tenancy | Hard Tenancy |
| :--- | :--- | :--- |
| **Доверие** | Кооперативные тенанты | Враждебные тенанты |
| **NetworkPolicy** | Достаточен | Дополнение к выделенным кластерам |
| **Изоляция** | Namespace + RBAC + NP | Выделенные узлы, k8s-controllers, gVisor |
| **Пример** | Команды внутри компании | SaaS с внешними клиентами |
| **Риск** | Случайные ошибки | Целенаправленные атаки |

### Связанные темы

* [Мульти-тенантность в Kubernetes](../../Concepts/multi-tenancy.md) — общие концепции
* [NetworkPolicy: Определения](./definitions.md) — базовые определения
* [Лучшие практики](./best_practices.md) — рекомендации по изоляции
* [Паттерны Egress](./egress_patterns.md) — управление исходящим трафиком
* [RBAC и Tenant](../../Security/rbac/resource_quota_rbac.md) — RBAC для тенантов
