# NetworkPolicy: FQDN-фильтрация (Domain-based Filtering)

## Определения

**FQDN-фильтрация (Fully Qualified Domain Name Filtering)** — механизм ограничения сетевого трафика по доменным именам вместо IP-адресов. Решает проблему эфемерных IP CDN, cloud-сервисов и микросервисной архитектуры, где backend IP постоянно меняется.

**DNS Proxy** — компонент CNI, перехватывающий DNS-запросы подов и извлекающий из ответов IP-адреса для разрешенных домен. IP-адреса динамически добавляются в eBPF maps или iptables правила. Используется Cilium и Calico.

**ToFQDNs** — поле в `CiliumNetworkPolicy`, определяющее список разрешенных доменных шаблонов. Поддерживает wildcard (`*.github.com`). Автоматически обновляет правила при DNS-резолвинге.

**DNS-based Policy (Calico)** — механизм Calico для фильтрации по DNS-именам через GlobalNetworkPolicy. Использует DNS resolver для разрешения домен в IP и применения правил. Требует DNS-проксирования на уровне узла.

**Wildcard Matching** — подстановочный знак (`*`) в FQDN-политиках, позволяющий разрешать все поддомены домена (например, `*.amazonaws.com` для всех сервисов AWS).

**DNS TTL (Time To Live)** — время жизни кеша DNS-записи. Влияет на то, как часто FQDN-политика обновляет IP-адреса в правилах. При низком TTL обновления происходят чаще, что нагружает DNS proxy.

## Базовые Концепции

### Проблема, которую решает FQDN-фильтрация

Стандартная NetworkPolicy работает с IP-адресами через `ipBlock`:

```yaml
# Проблема: IP-адреса меняются
egress:
- to:
  - ipBlock:
      cidr: 3.18.0.0/16  # Stripe API
```

**Почему это ненадежно:**
- CDN (Cloudflare, Akamai) используют hundreds of IP, которые меняются
- Cloud-сервисы (AWS, GCP) имеют динамические IP-пулы
- Microservices discovery через DNS (Service → ClusterIP)
- IPv4/IPv6 dual-stack требует two sets of rules

**FQDN-решение:**
```yaml
# Надежно: домен стабилен
egress:
- toFQDNs:
  - matchPattern: "api.stripe.com"
```

### Как работает FQDN-фильтрация

```
Pod → DNS Query (api.stripe.com) → DNS Proxy (Cilium/Calico)
                                         │
                                         ├── Перехват запроса
                                         ├── Резолвинг: api.stripe.com → 3.18.0.0/16
                                         ├── Проверка: разрешен ли домен в политике?
                                         ├── Если да → добавление IP в eBPF map
                                         └── Ответ поду + разрешение трафика к IP
```

**Этапы работы:**
1. Под отправляет DNS-запрос (UDP 53)
2. DNS proxy перехватывает запрос
3. Проверяет, соответствует ли домен разрешенным FQDN-политикой
4. Если да — резолвит домен в IP-адреса
5. Добавляет IP в eBPF hash map (Cilium) или iptables chain (Calico)
6. Под получает DNS-ответ и может отправлять трафик к разрешенным IP

### Сравнение FQDN-подходов по CNI

| CNI | Механизм | API | Wildcard | L7 | Кеш TTL |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cilium** | eBPF DNS Proxy | `CiliumNetworkPolicy` → `toFQDNs` | Да (`matchPattern`) | Да (HTTP) | Настраиваемый |
| **Calico** | DNS Resolver | `GlobalNetworkPolicy` → `domain` | Ограниченно | Нет | Настраиваемый |
| **Antrea** | DNS Proxy | `ClusterNetworkPolicy` → `fqdn` | Да | Нет | Настраиваемый |
| **Стандартный K8s** | Нет | `ipBlock` (CIDR only) | Нет | Нет | N/A |

> **Кросс-ссылка:** Сравнение CNI — [Реализация NetworkPolicy в CNI](./cni_implementation.md)

### Обязательные компоненты

Для работы FQDN-фильтрации необходимы:

1. **DNS-политика:** Явное разрешение UDP/TCP 53 к CoreDNS
2. **DNS Proxy:** Включенный в CNI (Cilium, Calico)
3. **Egress Default Deny:** Иначе трафик идет напрямую, минуя proxy
4. **Ядро Linux:** 5.3+ для eBPF (Cilium), 4.15+ для Calico DNS-based

```yaml
# Минимальная конфигурация для FQDN (Cilium)
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: fqdn-example
spec:
  endpointSelector:
    matchLabels:
      app: my-app
  egress:
  # 1. DNS (обязательно)
  - toEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": kube-system
        "k8s:k8s-app": kube-dns
    toPorts:
    - ports:
      - port: "53"
        protocol: ANY
      rules:
        dns:
        - matchPattern: "*"
  # 2. FQDN разрешения
  - toFQDNs:
    - matchPattern: "api.stripe.com"
    - matchPattern: "*.sentry.io"
```

## Практические сценарии

### Сценарий 1: Cilium — Доступ только к конкретным SaaS-сервисам

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: allow-egress-to-saas
  namespace: production
spec:
  endpointSelector:
    matchLabels:
      app: payment-processor
  egress:
  # DNS
  - toEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": kube-system
        "k8s:k8s-app": kube-dns
    toPorts:
    - ports:
      - port: "53"
        protocol: ANY
      rules:
        dns:
        - matchPattern: "*"
  # Stripe API
  - toFQDNs:
    - matchPattern: "api.stripe.com"
    - matchPattern: "*.stripe.com"
    toPorts:
    - ports:
      - port: "443"
        protocol: TCP
  # Sentry
  - toFQDNs:
    - matchPattern: "*.sentry.io"
    toPorts:
    - ports:
      - port: "443"
        protocol: TCP
```

#### Валидация

```bash
kubectl apply -f fqdn-saas.yaml -n production

# Проверка: Stripe доступен
kubectl exec -n production <pod> -- wget -qO- --timeout=5 https://api.stripe.com
# → successful

# Проверка: другой сервис заблокирован
kubectl exec -n production <pod> -- wget -qO- --timeout=3 https://google.com
# → connection timed out
```

### Сценарий 2: Calico — DNS-based политика

```yaml
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: allow-fqdn-external
spec:
  order: 100
  selector: "app == 'external-caller'"
  types: [Egress]
  egress:
  # DNS (обязательно)
  - action: Allow
    protocol: UDP
    destination:
      selector: "k8s-app == 'kube-dns'"
      namespaceSelector: "kubernetes.io/metadata.name == 'kube-system'"
      ports: [53]
  - action: Allow
    protocol: TCP
    destination:
      selector: "k8s-app == 'kube-dns'"
      namespaceSelector: "kubernetes.io/metadata.name == 'kube-system'"
      ports: [53]
  # FQDN-based правила
  - action: Allow
    destination:
      domain: "api.stripe.com"
    protocol: TCP
    destination:
      ports: [443]
  - action: Allow
    destination:
      domain: "*.sentry.io"
    protocol: TCP
    destination:
      ports: [443]
```

### Сценарий 3: Защита от DNS exfiltration

Ограничение DNS-запросов только до CoreDNS и блокировка попыток туннелирования:

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: restrict-dns
  namespace: production
spec:
  endpointSelector:
    matchLabels: {}
  egress:
  # Разрешить DNS только к CoreDNS
  - toEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": kube-system
        "k8s:k8s-app": kube-dns
    toPorts:
    - ports:
      - port: "53"
        protocol: ANY
      rules:
        dns:
        # Только разрешенные домены
        - matchPattern: "*.production.svc.cluster.local"
        - matchPattern: "*.default.svc.cluster.local"
        - matchPattern: "api.stripe.com"
        # Блокировка любых других DNS-запросов
  # Заблокировать внешний DNS (53 к IP вне кластера)
  - toFQDNs:
    - matchPattern: ""  # Нет других разрешений
```

### Сценарий 4: Обработка wildcard-доменов

Доступ ко всем сервисам AWS:

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: allow-aws-services
spec:
  endpointSelector:
    matchLabels:
      app: aws-backup
  egress:
  - toEndpoints:
    - matchLabels:
        "k8s:io.kubernetes.pod.namespace": kube-system
        "k8s:k8s-app": kube-dns
    toPorts:
    - ports:
      - port: "53"
        protocol: ANY
      rules:
        dns:
        - matchPattern: "*"
  - toFQDNs:
    # Все сервисы AWS
    - matchPattern: "*.amazonaws.com"
    # S3 bucket specific
    - matchPattern: "*.s3.amazonaws.com"
    toPorts:
    - ports:
      - port: "443"
        protocol: TCP
```

### Сценарий 5: TTL и кеширование

Настройка времени жизни DNS-кеша:

```bash
# Cilium: TTL по умолчанию = 1 минута
# Увеличение для снижения нагрузки на DNS proxy
cilium config set dns-policy-ttl 5m

# Проверка кеша
cilium fqdn cache list
# → ENDPOINT   FQDN                    IPs                TTL
# → 1234       api.stripe.com          [3.18.0.0/16]      4m30s
```

**Рекомендации по TTL:**
- **<1 минута:** Агрессивное обновление, высокая точность, высокая нагрузка
- **1-5 минут:** Баланс для production
- **>5 минут:** Низкая нагрузка, но риск пропускать изменения IP

## Дополнительная информация

### Ограничения FQDN-фильтрации

| Ограничение | Описание | Решение |
| :--- | :--- | :--- |
| **Только UDP/TCP 53** | Не работает для DoH (DNS over HTTPS, порт 443) | Блокируйте DoH через IP или L7 |
| **Нет поддержки в standard K8s API** | Требуется Cilium, Calico или Antrea | Используйте CIDR + регулярное обновление |
| **Дополнительная нагрузка** | DNS proxy перехватывает каждый DNS-запрос | Мониторьте CPU DNS proxy |
| **IPv4/IPv6** | Нужны отдельные правила для каждого протокола | Используйте dual-stack политики |
| **Internal DNS** | FQDN для internal сервисов может быть избыточен | Для internal используйте namespaceSelector |

### DNS exfiltration — угроза и защита

**Угроза:** Злоумышленник может кодировать данные в DNS-запросах (subdomain encoding):
```
data-to-exfil.evil.com → DNS query → attacker's server
```

**Защита:**
1. Ограничение DNS-трафика только до CoreDNS
2. FQDN-политика с allowed domains only
3. Мониторинг аномальных DNS-запросов (длина, частота, тип)
4. Блокировка DoH/DoT ( ports 443/853 к не CoreDNS)

> **Кросс-ссылка:** DNS безопасность — [DNS Security](../../Protocols/DNS/dns_security.md)

### Связанные темы

* [Паттерны Egress](./egress_patterns.md) — общие паттерны исходящего трафика
* [Cilium: FQDN-политики](../../Networking/Network/CNI/cilium.md) — детали Cilium
* [Реализация NetworkPolicy в CNI](./cni_implementation.md) — сравнение CNI
* [DNS в Kubernetes](../../Protocols/DNS/dns_resolution.md) — настройка DNS
* [Лучшие практики](./best_practices.md) — рекомендации
