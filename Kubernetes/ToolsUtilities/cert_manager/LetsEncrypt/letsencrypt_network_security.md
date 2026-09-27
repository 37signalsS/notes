# Let's Encrypt: Сетевая безопасность (Firewall, Egress, NetworkPolicy)

## Определения

**Egress-политики** — правила сетевого экрана, контролирующие исходящие подключения из pod'ов cert-manager к внешним сервисам (ACME API Let's Encrypt, DNS API провайдеров). Корректная настройка egress критична для работы HTTP-01 и DNS-01 проверок.

**NetworkPolicy** — ресурс Kubernetes для управления сетевым трафиком на уровне pod'ов и namespace'ов. Для cert-manager необходимо разрешить: исходящий HTTPS (443) к ACME API, исходящий DNS (53), входящий HTTP (80) для HTTP-01 проверки.

**Ingress-политики** — правила, контролирующие входящий трафик к подам cert-manager (webhook на порту 10250, controller). Минимальные права доступа снижают surface area атаки.

**Split-horizon DNS** — ситуация, когда внутренний DNS-резолвер возвращает другой IP, чем внешний DNS. Это может блокировать HTTP-01 проверку, если cert-manager не может достучаться до внешнего IP.

---

## Основные концепции

### Сетевые требования cert-manager

| Компонент | Протокол | Порт | Направление | Назначение |
| :--- | :--- | :--- | :--- | :--- |
| **cert-manager controller** | TCP | 443 | Egress | ACME API (Let's Encrypt) |
| **cert-manager controller** | TCP | 53 | Egress | DNS-резолвер (для DNS-01) |
| **cert-manager controller** | UDP | 53 | Egress | DNS-резолвер (для DNS-01) |
| **cert-manager controller** | TCP | 80 | Egress | DNS API провайдера (Cloudflare, Route53) |
| **cert-manager webhook** | TCP | 10250 | Ingress | Kubernetes API Server |
| **cert-manager controller** | TCP | 9402 | Ingress | Prometheus metrics |
| **HTTP-01 solver pod** | TCP | 8089 | Ingress | Self-check от controller |
| **cert-manager controller** | TCP | 80 | Ingress | ACME HTTP-01 challenge |

### Минимальная NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cert-manager-default-deny
  namespace: cert-manager
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
---
# Разрешение egress только на нужные порты
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cert-manager-egress
  namespace: cert-manager
spec:
  podSelector:
    matchLabels:
      app: cert-manager
  policyTypes:
  - Egress
  egress:
  # ACME API (Let's Encrypt)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 443
  # DNS
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
---
# Разрешение ingress для webhook
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cert-manager-webhook-ingress
  namespace: cert-manager
spec:
  podSelector:
    matchLabels:
      app: cert-manager-webhook
  policyTypes:
  - Ingress
  ingress:
  # Kubernetes API Server
  - ports:
    - protocol: TCP
      port: 10250
```

---

## Практические сценарии

### Сценарий 1: NetworkPolicy для HTTP-01 проверки

HTTP-01 требует, чтобы под cert-manager мог:
1. Создавать временный Ingress для `/.well-known/acme-challenge/`
2. Достучаться до этого Ingress извне (ACME API) и изнутри (self-check)

```yaml
# NetworkPolicy для HTTP-01: self-check с подов controller
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cert-manager-http01-self-check
  namespace: cert-manager
spec:
  podSelector:
    matchLabels:
      app: cert-manager
  policyTypes:
  - Egress
  egress:
  # Self-check HTTP-01 ( pod'ы solver на порту 8089)
  - to:
    - podSelector:
        matchLabels:
          acme.cert-manager.io/http-solver: "true"
    ports:
    - protocol: TCP
      port: 8089
  # ACME API
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 443
  # DNS
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

```bash
# Проверка, что NetworkPolicy не блокирует HTTP-01
kubectl run test-pod --image=curlimages/curl --rm -it --restart=Never -- \
  curl -s http://<domain>/.well-known/acme-challenge/test-token

# Если таймаут — проверьте NetworkPolicy
kubectl get networkpolicy -n cert-manager -o yaml
```

### Сценарий 2: NetworkPolicy для DNS-01 проверки

DNS-01 требует доступа к API DNS-провайдера и DNS-резолверам.

```yaml
# NetworkPolicy для DNS-01: доступ к Cloudflare API
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cert-manager-dns01-cloudflare
  namespace: cert-manager
spec:
  podSelector:
    matchLabels:
      app: cert-manager
  policyTypes:
  - Egress
  egress:
  # Cloudflare API
  - to:
    - ipBlock:
        cidr: 104.16.0.0/12
    ports:
    - protocol: TCP
      port: 443
  # Google DNS (для проверки propagation)
  - to:
    - ipBlock:
        cidr: 8.8.8.8/32
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # Локальный DNS-резолвер
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Сценарий 3: Разделение egress для HTTP-01 и DNS-01

Для безопасности рекомендуется создавать отдельные ClusterIssuer с отдельными NetworkPolicy:

```yaml
# ClusterIssuer для HTTP-01 (требует порт 80 для входящего ACME)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-http01
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-http01-account
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
---
# ClusterIssuer для DNS-01 (требует доступ к DNS API)
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns01
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-dns01-account
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
```

### Сценарий 4: Диагностика сетевых проблем

```bash
# 1. Проверка доступности ACME API из pod cert-manager
kubectl run acme-test --image=curlimages/curl --rm -it --restart=Never -n cert-manager -- \
  curl -sI https://acme-v02.api.letsencrypt.org/directory

# 2. Проверка DNS-резолвера
kubectl run dns-test --image=busybox --rm -it --restart=Never -n cert-manager -- \
  nslookup acme-v02.api.letsencrypt.org

# 3. Проверка Cloudflare API
kubectl run cloudflare-test --image=curlimages/curl --rm -it --restart=Never -n cert-manager -- \
  curl -s -X GET "https://api.cloudflare.com/client/v4/zones" \
  -H "Authorization: Bearer <token>" | jq '.result'

# 4. Проверка NetworkPolicy (block / allow)
kubectl get networkpolicy -n cert-manager -o custom-columns=\
  NAME:.metadata.name,\
  POD-SELECTOR:.spec.podSelector.matchLabels,\
  POLICY-TYPES:.spec.policyTypes

# 5. Проверка, какие pod'ы подпадают под NetworkPolicy
kubectl get pods -n cert-manager -l app=cert-manager -o json | jq '.items[].metadata.labels'

# 6. Проверка egress-подключений через tcpdump
kubectl debug -it <cert-manager-pod> --image=nicolaka/netshoot -n cert-manager -- \
  tcpdump -i eth0 -n port 443 or port 53
```

### Сценарий 5: Firewall-правила для внешнего сервера

Для standalone-серверов (не Kubernetes) с certbot/acme.sh:

```bash
# iptables: разрешение только нужных подключений
# ACME API
iptables -A OUTPUT -d acme-v02.api.letsencrypt.org -p tcp --dport 443 -j ACCEPT
iptables -A OUTPUT -d acme-staging-v02.api.letsencrypt.org -p tcp --dport 443 -j ACCEPT

# DNS (Cloudflare)
iptables -A OUTPUT -d 1.1.1.1 -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -d 1.0.0.1 -p udp --dport 53 -j ACCEPT

# HTTP-01 проверка (входящий трафик на порт 80)
iptables -A INPUT -p tcp --dport 80 -j ACCEPT

# Блокировка всего остального
iptables -A OUTPUT -j DROP
```

```bash
# ufw (Ubuntu)
ufw allow out 443/tcp    # ACME API
ufw allow out 53/udp     # DNS
ufw allow out 53/tcp     # DNS
ufw allow in 80/tcp      # HTTP-01 check
ufw deny out             # Все остальное
```

---

## Дополнительная информация

### Типичные ошибки NetworkPolicy

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| HTTP-01 self-check failed | NetworkPolicy блокирует egress на порт 8089 | Добавить egress-правило на порт 8089 |
| DNS-01 не propagates | NetworkPolicy блокирует DNS (порт 53) | Добавить egress-правило на порт 53 |
| ACME API timeout | NetworkPolicy блокирует egress на порт 443 | Добавить egress-правило на порт 443 |
| Webhook не отвечает | NetworkPolicy блокирует ingress на порт 10250 | Добавить ingress-правило на порт 10250 |
| cert-manager OOM | Слишком много Challenge, не хватает памяти | Увеличить resource limits |

### Рекомендации по сегментации

1. **Отдельный namespace**: cert-manager в выделенном namespace.
2. **Minimal egress**: Разрешать только ACME API (443), DNS (53) и HTTP-01 (80).
3. **Minimal ingress**: webhook (10250) только от API Server.
4. **RBAC**: Ограниченные права для ServiceAccount cert-manager.
5. **Audit**: Логирование всех egress-подключений через NetworkPolicy logging.

### Смотрите также

- **[Let's Encrypt: Обзор](./index.md)** — ACME solvers и требования
- **[Let's Encrypt: Диагностика](./letsencrypt_advanced.md)** — HTTP-01 и DNS-01 troubleshooting
- **[Kubernetes Network Policies](../../../../Kubernetes/Security/network_policies.md)** — общие принципы NetworkPolicy
- **[Let's Encrypt: Performance](./letsencrypt_performance.md)** — производительность TLS
- **[cert-manager: Network Policies](../../../../Kubernetes/Networking/Network/NetworkPolicy/service_mesh_interaction.md)** — взаимодействие с Service Mesh
