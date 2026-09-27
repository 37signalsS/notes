# kind — тестирование NetworkPolicy

## Определения

**NetworkPolicy** — объект Kubernetes, определяющий правила разрешения сетевого трафика между подами (Pod-to-Pod), подами и внешними источниками (Ingress/Egress), а также между неймспейсами. По умолчанию все поды в Kubernetes доступны друг для друга — NetworkPolicy позволяет настроить модель «deny-all» с явными разрешениями.

**kindnet** — встроенный CNI-плагин kind, обеспечивающий базовую маршрутизацию Pod-to-Pod. **Не поддерживает NetworkPolicy** — для тестирования политик необходимо устанавливать альтернативные CNI (Calico, Cilium).

**CNI (Container Network Interface)** — интерфейс, определяющий, как поды получают IP-адреса и как организовано сетевое взаимодействие между узлами и подами.

---

## Основные концепции

### Почему kindnet не поддерживает NetworkPolicy

kindnet — легковесный CNI, который реализует только маршрутизацию (Pod-to-Pod connectivity). Он не включает сетевые политики, потому что:

- kind предназначен для локальной разработки и тестирования, где сетевая изоляция обычно не требуется
- Поддержка NetworkPolicy требует реализации iptables/ipvs правил или eBPF-программ, что усложняет CNI

Для тестирования NetworkPolicy в kind необходимо заменить kindnet на Calico или Cilium.

### Когда нужна замена CNI в kind

| Сценарий | CNI по умолчанию | Рекомендуемый CNI |
|:---|:---|:---|
| Базовая маршрутизация Pod-to-Pod | kindnet | kindnet (достаточно) |
| Тестирование NetworkPolicy | kindnet | **Calico** или **Cilium** |
| Тестирование eBPF-политик | kindnet | **Cilium** |
| Тестирование BGP-маршрутизации | kindnet | **Calico** или **Cilium** |
| Тестирование DNS-политик | kindnet | **Cilium** |

### Сравнение Calico и Cilium для kind

| Параметр | Calico | Cilium |
|:---|:---|:---|
| **Поддержка NetworkPolicy** | Полная (Kubernetes + extensions) | Полная (Kubernetes + extensions) |
| **Механизм** | iptables / eBPF (op模式) | eBPF (по умолчанию) |
| **Дополнительные возможности** | BGP, IP-in-IP, VXLAN | eBPF, Hubble (UI), DNS-политики |
| **Ресурсы в kind** | ~100 MB RAM на узел | ~150 MB RAM на узел |
| **Скорость установки** | Быстрее | Чуть медленнее |
| **Сложность настройки** | Проще | Средняя |

---

## Практические сценарии

### Сценарий 1: Установка Calico и тестирование deny-all политики

```bash
# 1. Создание кластера без встроенного CNI
cat <<EOF | kind create cluster --name calico-test --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true    # Отключение kindnet
  podSubnet: "192.168.0.0/16"
nodes:
- role: control-plane
- role: worker
EOF

# 2. Установка Calico
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.27.0/manifests/calico.yaml

# 3. Ожидание готовности (все поды в Running)
kubectl -n kube-system rollout status daemonset/calico-node
kubectl -n kube-system get pods -l k8s-app=calico-node

# 4. Проверка: поды могут общаться друг с другом
kubectl run test-a --image=nginx --labels="app=test-a"
kubectl run test-b --image=busybox --rm -it --restart=Never -- wget -qO- --timeout=5 http://test-a.default.svc.cluster.local
# → Приветственная страница nginx (ответ 200)
```

**Применение deny-all политики:**

```yaml
# deny-all.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all
  namespace: default
spec:
  podSelector: {}          # Применяется ко всем подам в неймспейсе
  policyTypes:
  - Ingress                # Блокирует весь входящий трафик
  - Egress                 # Блокирует весь исходящий трафик
```

```bash
kubectl apply -f deny-all.yaml

# Проверка: трафик заблокирован
kubectl run test-c --image=busybox --rm -it --restart=Never -- wget -qO- --timeout=5 http://test-a.default.svc.cluster.local
# → wget: can't connect to remote host: Connection timed out
```

### Сценарий 2: Разрешение трафика только между конкретными подами

```yaml
# allow-frontend-to-backend.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: default
spec:
  podSelector:
    matchLabels:
      app: backend          # Применяется к подам с label app=backend
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend     # Разрешено ТОЛЬКО от подов с label app=frontend
    ports:
    - protocol: TCP
      port: 8080            # Разрешено ТОЛЬКО на порту 8080
---
# Egress для backend: разрешено только к DNS и базе данных
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-egress
  namespace: default
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53              # DNS
  - to:
    - podSelector:
        matchLabels:
          app: database
    ports:
    - protocol: TCP
      port: 5432            # PostgreSQL
```

```bash
kubectl apply -f allow-frontend-to-backend.yaml

# Проверка: frontend → backend разрешено
kubectl run frontend --image=curlimages/curl --labels="app=frontend" --rm -it --restart=Never -- \
  curl -s --max-time 5 http://backend.default.svc.cluster.local:8080
# → Ответ от backend

# Проверка: другой под → backend заблокировано
kubectl run attacker --image=curlimages/curl --rm -it --restart=Never -- \
  curl -s --max-time 5 http://backend.default.svc.cluster.local:8080
# → Connection timed out
```

### Сценарий 3: Установка Cilium и тестирование eBPF-политик

```bash
# 1. Создание кластера без CNI и kube-proxy
cat <<EOF | kind create cluster --name cilium-test --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
  kubeProxyMode: "none"     # Cilium заменяет kube-proxy через eBPF
nodes:
- role: control-plane
- role: worker
EOF

# 2. Установка Cilium через Helm
helm repo add cilium https://helm.cilium.io/
helm install cilium cilium/cilium --namespace kube-system \
  --set kubeProxyReplacement=true

# 3. Ожидание готовности
kubectl -n kube-system rollout status daemonset/cilium

# 4. Проверка состояния Cilium
cilium status --wait
```

**Тестирование DNS-политики Cilium:**

```yaml
# cilium-dns-policy.yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-dns-only
  namespace: default
spec:
  endpointSelector:
    matchLabels:
      app: backend
  egress:
  - toEndpoints:
    - matchLabels:
        k8s:io.kubernetes.pod.namespace: kube-system
        k8s-app: kube-dns
    toPorts:
    - ports:
      - port: "53"
        protocol: UDP
      - port: "53"
        protocol: TCP
```

```bash
kubectl apply -f cilium-dns-policy.yaml

# Проверка: backend может резолвить DNS
kubectl exec <backend-pod> -- nslookup kubernetes.default.svc.cluster.local
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1

# Проверка: backend НЕ может обращаться к внешним IP
kubectl exec <backend-pod> -- wget -qO- --timeout=5 http://example.com
# → Connection timed out
```

### Сценарий 4: Тестирование изоляции между неймспейсами

```yaml
# namespace-isolation.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-cross-namespace
  namespace: app-team-a
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    # Разрешено: только из того же неймспейса
    - podSelector: {}
    # Разрешено: из неймспейса ingress-nginx (для Ingress-контроллера)
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
```

```bash
kubectl create namespace app-team-a
kubectl create namespace app-team-b
kubectl apply -f namespace-isolation.yaml

# В app-team-a запускаем тестовый под
kubectl run server-a --image=nginx --namespace=app-team-a

# В app-team-b запускаем под-клиент
kubectl run client-b --image=curlimages/curl --namespace=app-team-b --rm -it --restart=Never -- \
  curl -s --max-time 5 http://server-a.app-team-a.svc.cluster.local
# → Connection timed out (межнеймспейсная изоляция)

# Из того же неймспейса — разрешено
kubectl run client-a --image=curlimages/curl --namespace=app-team-a --rm -it --restart=Never -- \
  curl -s --max-time 5 http://server-a.app-team-a.svc.cluster.local
# → Ответ от nginx
```

### Сценарий 5: Диагностика NetworkPolicy

**Команды для диагностики:**

```bash
# Просмотр всех NetworkPolicy в неймспейсе
kubectl get networkpolicies -n default

# Детальный просмотр политики
kubectl describe networkpolicy deny-all -n default

# Проверка: разрешен ли трафик между двумя подами (с Calico)
calicoctl get policy -o wide

# Проверка: разрешен ли трафик между двумя подами (с Cilium)
cilium policy get

# Логи Cilium для диагностики заблокированного трафика
kubectl -n kube-system logs -l k8s-app=cilium --tail=50 | grep -i "denied\|policy"
```

**Типичные ошибки:**

| Проблема | Причина | Решение |
|:---|:---|:---|
| Под не может достучаться до DNS | Egress-политика не разрешает порт 53 | Добавить egress-правило для DNS (port 53, UDP/TCP) |
| Ingress-контроллер не видит поды | NetworkPolicy блокирует входящий трафик от ingress-nginx | Добавить ingress-правило с `namespaceSelector` для ingress-nginx |
| Pod-to-Pod трафик заблокирован | Deny-all политика без исключений | Добавить явные разрешения для необходимых соединений |
| Политика не применяется | CNI не поддерживает NetworkPolicy | Убедитесь, что установлен Calico или Cilium (не kindnet) |

### Сценарий 6: Экспорт и анализ политики

```bash
# Экспорт всех NetworkPolicy в YAML
kubectl get networkpolicies --all-namespaces -o yaml > all-network-policies.yaml

# Анализ: какие поды изолированы
kubectl get pods --all-namespaces -o json | jq -r '
  .items[] |
  "\(.metadata.namespace)/\(.metadata.name): \(.metadata.labels // {} | to_entries | map("\(.key)=\(.value)") | join(","))"
'

# Проверка: есть ли политики с пустым podSelector (влияют на ВСЕ поды)
kubectl get networkpolicies --all-namespaces -o json | jq -r '
  .items[] |
  select(.spec.podSelector == {}) |
  "\(.metadata.namespace)/\(.metadata.name)"
'
```

---

## Дополнительная информация

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — архитектура и внутреннее устройство узлов
- [NetworkPolicy](../../Networking/Network/NetworkPolicy/) — полная теория сетевых политик
- [Cilium](../../Networking/Network/CNI/cilium.md) — detailed обзор Cilium
- [Calico](../../Networking/Network/CNI/) — обзор CNI-плагинов
- [Официальная документация NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
