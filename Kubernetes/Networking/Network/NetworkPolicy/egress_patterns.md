# NetworkPolicy: Паттерны управления исходящим трафиком (Egress)

## Определения

**Egress-политика (Egress Policy)** — правило NetworkPolicy, определяющее, куда и на какие порты подам разрешено отправлять исходящий трафик. Активируется через `policyTypes: [Egress]`. Без явного включения Egress-политики исходящий трафик не фильтруется, даже если правила `egress` определены.

**Default Deny Egress** — стратегия, при которой весь исходящий трафик блокируется, если он не разрешен явным правилом. Критически важна для предотвращения data exfiltration и C2-соединений из компрометированных подов.

**ipBlock** — секция правил NetworkPolicy, разрешающая или блокирующая трафик по CIDR-диапазонам. Поддерживает поле `except` для исключения подсетей. Предназначена для внешнего трафика; не рекомендуется для East-West взаимодействий из-за эфемерности IP подов.

**Egress Gateway** — выделенный узел кластера, через который маршрутизируется весь исходящий трафик подов. Позволяет централизованно контролировать NAT, аудит и фильтрацию. Требует настройки IP forwarding и маршрутизации на шлюзе.

**FQDN-фильтрация (Domain-based Filtering)** — механизм ограничения исходящего трафика по доменным именам вместо IP-адресов. Решает проблему эфемерных IP CDN и cloud-сервисов. Поддерживается Cilium (native eBPF DNS proxy) и Calico (DNS-based policies).

**Cloud Metadata Endpoint** — URL `169.254.169.254`, предоставляющий доступ к метаданным виртуальных машин (IAM-роли, токены, конфигурация). Критическая цель для атак (SSRF, credential theft). Требует обязательной блокировки из подов приложений.

**Source NAT (SNAT)** — трансляция исходящего IP-адреса пода на IP узла или шлюза при выходе трафика за пределы кластера. Необходима для маршрутизации трафика через egress gateway.

## Базовые Концепции

### Зачем контролировать Egress

Контроль входящего трафика (Ingress) — это половина безопасности. Без контроля исходящего трафика (Egress) компрометированный под может:
- Устанавливать C2-соединения с внешними серверами управлений
- Экспортировать данные (data exfiltration) на внешние IP
- Сканировать внутреннюю сеть кластера и внешние ресурсы
- Обращаться к cloud metadata endpoints для кражи credentials
- Использовать DNS для туннелирования данных (DNS exfiltration)

> **Статистика:** В среднем 70% трафика в Kubernetes-кластерах — это East-West (межсервисный), но наиболее опасен uncontrolled Egress, так как он выходит за пределы кластера.

### Иерархия Egress-фильтрации

```
┌─────────────────────────────────────────────────────────┐
│                 Egress Traffic Flow                      │
├─────────────────────────────────────────────────────────┤
│  Pod → DNS Resolution → Service → External API          │
│    │         │              │           │                │
│    ▼         ▼              ▼           ▼                │
│  Egress NP  DNS Policy   Egress NP   ipBlock/FQDN      │
│  (port/proto) (UDP 53)   (dest IP)   (CIDR/domains)    │
│    │         │              │           │                │
│    ▼         ▼              ▼           ▼                │
│  SNAT (egress gateway) → NAT → Internet                 │
└─────────────────────────────────────────────────────────┘
```

### Типы Egress-политик

| Паттерн | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Allow DNS Only** | Разрешает только UDP/TCP 53 к CoreDNS | Базовый Default Deny + DNS |
| **Allow Specific CIDR** | Разрешает доступ к конкретным IP-диапазонам | Доступ к API внешних сервисов |
| **Allow by Namespace** | Разрешает доступ к подам в других namespace | Межсервисное взаимодействие |
| **Egress Gateway** | Направляет весь трафик через выделенный узел | Аудит, контроль, фиксированный IP |
| **FQDN-based** | Фильтрует по доменным именам | Доступ к SaaS, CDN, внешним API |
| **Default Deny Egress** | Блокирует весь исходящий трафик | Zero Trust, PCI DSS, HIPAA |

### Проблема DNS при Default Deny

При включении Egress Default Deny поды **теряют способность разрешать DNS-имена**, что ломает:
- Сервис-дискавери (`my-service.my-ns.svc.cluster.local`)
- Внешние API (`api.stripe.com`, `api.sentry.io`)
- Пакетные менеджеры и обновления

**Решение:** Всегда создавайте разрешающую политику для DNS **до** применения Default Deny:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: production
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
```

> **Кросс-ссылка:** Подробности о DNS в Kubernetes — [DNS в Kubernetes](../../Protocols/DNS/dns_resolution.md)

### conntrack и Egress

NetworkPolicy является **stateful**: если Egress-трафик разрешен, ответный Ingress-трафик (return traffic) разрешается автоматически через conntrack. Это означает:
- Достаточно разрешить только Egress для двустороннего соединения
- Не нужно создавать зеркальные Ingress-правила для ответов
- При переполнении conntrack таблицы новые Egress-соединения могут блокироваться

> **Кросс-ссылка:** conntrack и NetworkPolicy — [Логика правил](./rule_logic.md)

## Практические сценарии

### Сценарий 1: Базовый Default Deny Egress + DNS

Создание защищенной среды с полной изоляцией исходящего трафика:

```yaml
# 1. Default Deny Egress (все поды в namespace)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-egress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress: []  # Пустой список = запретить всё
---
# 2. Разрешение DNS (высокий приоритет)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: production
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
```

#### Валидация

```bash
# Применение
kubectl apply -f default-deny-egress.yaml
kubectl apply -f allow-dns-egress.yaml

# Проверка: DNS работает
kubectl exec -n production <pod> -- nslookup kubernetes.default
# → Server:    10.96.0.10
# → Name:      kubernetes.default.svc.cluster.local

# Проверка: внешний трафик заблокирован
kubectl exec -n production <pod> -- wget -qO- --timeout=3 https://google.com
# → connection timed out
```

### Сценарий 2: Доступ к внешнему API по CIDR

Разрешение доступа к конкретным внешним сервисам:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-api
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: payment-processor
  policyTypes:
  - Egress
  egress:
  # Stripe API (CIDR)
  - ports:
    - protocol: TCP
      port: 443
    to:
    - ipBlock:
        cidr: 3.18.0.0/16
  # Sentry
  - ports:
    - protocol: TCP
      port: 443
    to:
    - ipBlock:
        cidr: 34.120.0.0/14
  # DNS (обязательно)
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

#### Валидация

```bash
kubectl exec -n production <payment-pod> -- wget -qO- --timeout=5 https://api.stripe.com
# → successful

kubectl exec -n production <payment-pod> -- wget -qO- --timeout=3 https://google.com
# → connection timed out
```

### Сценарий 3: Блокировка Cloud Metadata Endpoint

Защита от атак через метаданные облачных провайдеров:

```yaml
# ANP: Блокировка metadata для всех подов (Tier 1)
apiVersion: policy.networking.k8s.io/v1alpha1
kind: AdminNetworkPolicy
metadata:
  name: block-metadata
spec:
  priority: 1
  selector: {}
  ingress:
  - action: Deny
    from:
    - ipBlock:
        cidr: 0.0.0.0/0
    to:
    - ipBlock:
        cidr: 169.254.169.254/32
  egress:
  - action: Deny
    to:
    - ipBlock:
        cidr: 169.254.169.254/32
```

> **Важно:** `169.254.169.254` — link-local адрес. Даже при наличии Egress Default Deny рекомендуется создавать явный запрет через ANP, так как some CNI не фильтруют link-local по умолчанию.

### Сценарий 4: Межсервисный Egress (namespace-to-namespace)

Разрешение доступа между namespace:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: app-backend
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Разрешить вход от frontend
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: app-frontend
      podSelector:
        matchLabels:
          app: webapp
  egress:
  # Разрешить доступ к database
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: app-database
      podSelector:
        matchLabels:
          app: postgresql
    ports:
    - protocol: TCP
      port: 5432
  # DNS
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Сценарий 5: Egress Gateway через Calico

Централизованный контроль исходящего трафика:

```yaml
# 1. Пометка узла как egress gateway
# kubectl label nodes egress-node-1 node-role.kubernetes.io/egress-gateway=true

# 2. IPPool с фиксированными IP
apiVersion: projectcalico.org/v3
kind: IPPool
metadata:
  name: egress-pool
spec:
  cidr: 203.0.113.0/24
  encapsulation: None
  natOutgoing: true
  nodeSelector: "node-role.kubernetes.io/egress-gateway == 'true'"
---
# 3. GlobalNetworkPolicy для маршрутизации через egress
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: route-through-egress
spec:
  order: 500
  selector: "app == 'external-caller'"
  types: [Egress]
  egress:
  - action: Allow
    destination:
      nets: ["0.0.0.0/0"]
```

> **Кросс-ссылка:** Подробный сценарий — [Calico: Egress Gateway](../../Security/network_policies/Calico/scenarios.md)

### Сценарий 6: Egress с исключением internal CIDR

Доступ к внешним API, но запрет доступа к внутренним сетям:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-except-internal
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: external-caller
  policyTypes:
  - Egress
  egress:
  # Всё кроме внутренних сетей
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 10.0.0.0/8
        - 172.16.0.0/12
        - 192.168.0.0/16
    ports:
    - protocol: TCP
      port: 443
  # DNS
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

## Дополнительная информация

### Лучшие практики Egress

1. **Всегда начинайте с DNS:** Любая Egress-политика начинается с разрешения UDP/TCP 53 к CoreDNS.
2. **Не используйте ipBlock для East-West:** IP подов эфемерны; для межсервисного взаимодействия используйте `namespaceSelector` + `podSelector`.
3. **Блокируйте metadata endpoint:** Даже при наличии Egress Default Deny создавайте явный ANP для блокировки `169.254.169.254`.
4. **Используйте именованные порты:** Заменяйте числовые порты на имена (`https`, `http`) для гибкости.
5. **Тестируйте поэтапно:** Начинайте с Ingress-only изоляции, затем добавляйте Egress.
6. **FQDN вместо CIDR:** Для сервисов с динамическими IP (CDN, SaaS) используйте FQDN-фильтрацию (Cilium/Calico).
7. **Аудит перед Enforce:** Включайте audit mode перед применением Egress-политик в production.

### Ограничения

| Ограничение | Описание | Решение |
| :--- | :--- | :--- |
| **Нет FQDN в стандартном API** | Стандартная NetworkPolicy не поддерживает фильтрацию по доменам | Используйте Cilium (toFQDNs) или Calico (DNS-based) |
| **ipBlock не видит Pod IP** | Внешние сервисы не могут фильтровать по IP подов | Используйте Service mesh для identity-based фильтрации |
| **conntrack timeout** | Соединения могут оставаться active до 1ч после применения политики | Перезапускайте поды или снижайте conntrack timeouts |
| **NodePort + Egress** | Egress-политики не фильтруют трафик к NodePort снаружи | Используйте `preDNAT` (Calico) для фильтрации до DNAT |

### Связанные темы

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые определения и model
* [Calico: Egress Gateway](../../Security/network_policies/Calico/scenarios.md) — сценарий egress gateway
* [DNS в Kubernetes](../../Protocols/DNS/dns_resolution.md) — настройка DNS и ndots
* [conntrack и NetworkPolicy](./rule_logic.md) — поведение stateful соединений
