# Production Hardening сетевого стека Kubernetes

## Определения

**Production Hardening** — процесс ужесточения конфигурации сетевого стека Kubernetes до уровня, соответствующего требованиям production-среды: отказоустойчивость, безопасность, производительность, наблюдаемость.

**Defense in Depth** — многоуровневая стратегия безопасности, при которой каждый слой сети защищает независимо от других: CNI policies, NetworkPolicy, kube-proxy, Service Mesh, host-level firewall.

**Graceful Shutdown** — корректное завершение работы пода с обработкой всех активных соединений перед удалением из EndpointSlice. Предотвращает потерю запросов при обновлениях.

**Connection Draining** — механизм отключения пода от балансировки нагрузки с ожиданием завершения активных соединений. Критичен для zero-downtime deploys.

---

## Основные концепции

### Уровни production hardening

```
┌─────────────────────────────────────────────────────────────────┐
│ Level 5: Application (preStop hooks, SIGTERM handling)         │
├─────────────────────────────────────────────────────────────────┤
│ Level 4: Service (ExternalTrafficPolicy, topology-aware)       │
├─────────────────────────────────────────────────────────────────┤
│ Level 3: NetworkPolicy (default deny, egress control)          │
├─────────────────────────────────────────────────────────────────┤
│ Level 2: kube-proxy / eBPF (conntrack tuning, MTU)            │
├─────────────────────────────────────────────────────────────────┤
│ Level 1: CNI (encryption, native routing, BGP)                │
├─────────────────────────────────────────────────────────────────┤
│ Level 0: Node (sysctl tuning, firewall, conntrack limits)      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: Graceful Shutdown для нулевого даунтайма

**Проблема:** При удалении пода он удаляется из EndpointSlice до завершения обработки активных соединений, что приводит к 5xx ошибкам.

**Решение:** Использование `preStop` hook + `terminationGracePeriodSeconds`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
  namespace: production
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0  # Не допускать даунтайма
  template:
    spec:
      terminationGracePeriodSeconds: 45
      containers:
      - name: app
        image: nginx:1.27-alpine
        ports:
        - containerPort: 80
        lifecycle:
          preStop:
            exec:
              # Ждем 10 секунд для завершения активных соединений
              # + обновления iptables правил на других узлах
              command: ["/bin/sh", "-c", "sleep 10 && nginx -s quit"]
        readinessProbe:
          httpGet:
            path: /healthz
            port: 80
          initialDelaySeconds: 5
          periodSeconds: 5
          # Проверка готовности обновляется каждые 5 секунд
          # что критично для graceful shutdown
```

**Порядок действий при graceful shutdown:**

```
1. Pod получает SIGTERM
2. preStop hook выполняется (sleep 10)
3. kubelet удаляет pod из EndpointSlice
4. kube-proxy/eBPF обновляет правила балансировки
5. Новые запросы не идут на этот pod
6. Активные соединения завершаются
7. Приложение обрабатывает SIGTERM и завершается
8. terminationGracePeriodSeconds истекает (принудительное завершение)
```

### Сценарий 2: Оптимизация conntrack для production

**Проблема:** По умолчанию conntrack table limit = 262144, что недостаточно для высоконагруженных кластеров.

**Решение:** Настройка sysctl на всех узлах:

```bash
# /etc/sysctl.d/99-k8s-networking.conf

# Увеличение лимита conntrack (по умолчанию 262144)
net.netfilter.nf_conntrack_max=1048576

# Уменьшение таймаутов для освобождения слотов
net.netfilter.nf_conntrack_tcp_timeout_established=3600
net.netfilter.nf_conntrack_tcp_timeout_time_wait=30
net.netfilter.nf_conntrack_tcp_timeout_close_wait=15
net.netfilter.nf_conntrack_tcp_timeout_fin_wait=30

# Увеличение размера хеш-таблицы
net.netfilter.nf_conntrack_buckets=262144

# Защита отSYN flood
net.ipv4.tcp_syncookies=1
net.ipv4.tcp_max_syn_backlog=8192
net.ipv4.tcp_synack_retries=2

# Оптимизация TCP
net.ipv4.tcp_tw_reuse=1
net.ipv4.tcp_fin_timeout=15
net.core.somaxconn=65535
net.core.netdev_max_backlog=16384
```

**Применение через ansible:**

```yaml
- name: Optimize kernel networking parameters
  ansible.builtin.sysctl:
    name: "{{ item.key }}"
    value: "{{ item.value }}"
    sysctl_file: /etc/sysctl.d/99-k8s-networking.conf
    reload: yes
  loop:
    - { key: "net.netfilter.nf_conntrack_max", value: "1048576" }
    - { key: "net.netfilter.nf_conntrack_tcp_timeout_established", value: "3600" }
    - { key: "net.netfilter.nf_conntrack_tcp_timeout_time_wait", value: "30" }
    - { key: "net.ipv4.tcp_syncookies", value: "1" }
    - { key: "net.core.somaxconn", value: "65535" }
```

### Сценарий 3: MTU согласование для overlay сетей

**Проблема:** MTU mismatch между интерфейсами вызывает фрагментацию и потерю пакетов.

**Решение:** Настройка MTU с учетом overlay overhead:

```bash
# Определение overhead CNI
# VXLAN: 50 bytes (8 UDP + 20 IP + 8 VXLAN + 14 Ethernet)
# Geneve: 60 bytes
# IPIP: 20 bytes

# Настройка MTU на физическом интерфейсе
ip link set eth0 mtu 1500

# Настройка MTU для CNI (пример для Calico)
# В конфигурации Calico:
# - name: CALICO_MTU
#   value: "1440"  # 1500 - 60 (Geneve overhead)
```

**Проверка MTU:**

```bash
# Изнутри пода
ping -M do -s 1400 <target-ip>  # 1400 + 28 (ICMP header) + overhead

# Проверка path MTU
tracepath <target-ip>

# Проверка на хосте
ip link show eth0 | grep mtu
ethtool -i eth0 | grep mtu
```

### Сценарий 4: NetworkPolicy для control plane

**Проблема:** Control plane компоненты (API server, etcd, scheduler) не защищены NetworkPolicy.

**Решение:** Изоляция control plane:

```yaml
# 1. Защита etcd (если stacked)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-etcd-only
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: etcd
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    # Только API server
    - podSelector:
        matchLabels:
          component: kube-apiserver
    ports:
    - protocol: TCP
      port: 2379
    - protocol: TCP
      port: 2380
  egress:
  - {}  # etcd может подключаться к другим узлам etcd

---
# 2. Защита API server
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-apiserver-only
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      component: kube-apiserver
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Внешний LB + control plane узлы
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 6443
    - protocol: TCP
      port: 443
```

### Сценарий 5: Rate limiting на уровне сети

**Проблема:** Нет защиты от DDoS или аномального трафика на уровне кластера.

**Решение:** Использование Cilium для rate limiting:

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: rate-limit-api
  namespace: production
spec:
  endpointSelector:
    matchLabels:
      app: api-gateway
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: frontend
    toPorts:
    - ports:
      - port: "8080"
        protocol: TCP
      rules:
        http:
        - method: GET
          path: "/api/v1/.*"
          rateLimit:
            requests: 100
            burst: 50
```

### Сценарий 6: Мониторинг и алертинг

**Проблема:** Нет visibility в сетевые проблемы до того, как они станут инцидентами.

**Решение:** Минимальный набор алертов:

```yaml
groups:
- name: network-critical
  rules:
  # conntrack table filling up
  - alert: ConntrackTableNearFull
    expr: node_nf_conntrack_entries / node_nf_conntrack_entries_limit > 0.8
    for: 5m
    labels:
      severity: warning

  # DNS resolution failures
  - alert: CoreDNSHighErrorRate
    expr: |
      sum(rate(core_dns_dns_requests_total{rcode="SERVFAIL"}[5m]))
      / sum(rate(core_dns_dns_requests_total[5m])) > 0.05
    for: 5m
    labels:
      severity: warning

  # kube-proxy sync latency
  - alert: KubeProxySyncLatencyHigh
    expr: |
      histogram_quantile(0.99,
        rate(kube_proxy_sync_proxy_rules_duration_seconds_bucket[5m])
      ) > 0.5
    for: 5m
    labels:
      severity: warning

  # Network policy drops
  - alert: HighNetworkPolicyDropRate
    expr: |
      sum(rate(hubble_flows_processed_total{verdict="DROPPED"}[5m]))
      / sum(rate(hubble_flows_processed_total[5m])) > 0.1
    for: 5m
    labels:
      severity: warning

  # Pod restarts due to network issues
  - alert: PodNetworkErrors
    expr: rate(kube_pod_container_status_restarts_total[15m]) > 0.1
    for: 15m
    labels:
      severity: warning
```

---

## Дополнительная информация

### Чеклист production-ready сети

**Before deploy:**
- [ ] conntrack max >= 524288 (рекомендуется 1048576)
- [ ] TCP timeout'и оптимизированы (established <= 3600s)
- [ ] MTU согласован на всех интерфейсах
- [ ] Default deny NetworkPolicy в production namespace
- [ ] DNS-политика (allow DNS для всех подов)
- [ ] Graceful shutdown настроен (preStop + terminationGracePeriodSeconds)
- [ ] Readiness probe настроен и работает

**Monitoring:**
- [ ] ServiceMonitor для kube-proxy, CoreDNS, CNI
- [ ] Алерты на conntrack saturation
- [ ] Алерты на DNS errors
- [ ] Алерты на kube-proxy sync latency
- [ ] Flow-level visibility (Hubble/NetFlow)

**Security:**
- [ ] Control plane изолирован NetworkPolicy
- [ ] Default deny all ingress + egress
- [ ] Разрешен только необходимый трафик
- [ ] mTLS для sensitive сервисов
- [ ] Audit logging для network policy changes

### Частые ошибки production

| Ошибка | Последствие | Решение |
| :--- | :--- | :--- |
| conntrack max = default (262144) | Потеря соединений при нагрузке | Увеличить до 1M+ |
| MTU mismatch | Фрагментация, timeout'и | Согласовать MTU на всех уровнях |
| Нет graceful shutdown | 5xx при обновлениях | preStop + terminationGracePeriodSeconds |
| Default deny без DNS правила | Все поды теряют DNS | Всегда добавлять allow-DNS правило |
| terminationGracePeriodSeconds < preStop | Принудительное завершение | terminationGracePeriodSeconds > preStop + buffer |
| readinessProbe не настроен | Трафик идет на неготовый pod | Настроить readiness с периодом <= 10s |

### См. также

- [Диагностика сетевых проблем](./kubernetes_network_troubleshooting.md) — методология troubleshooting
- [Оптимизация производительности](./kubernetes_network_performance_tuning.md) — conntrack, MTU, TCP tuning
- [NetworkPolicy best practices](./NetworkPolicy/best_practices.md) — production-ready policies
- [Graceful shutdown в Deployment](../../Base/Deployment/deployment_manifest.md) — полная конфигурация
- [conntrack tuning](./kubernetes_network_performance_tuning.md#настройка-conntrack) — детальная настройка
