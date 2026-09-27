# Minikube: тестирование NetworkPolicy

## Определения

**NetworkPolicy** — ресурс Kubernetes, реализующий модель «белых списков» для управления сетевым доступом подов на уровнях L3/L4. Фактическое принудительное исполнение (enforcement) выполняет CNI-плагин. Подробнее: [NetworkPolicy: Определения](../../../Networking/Network/NetworkPolicy/definitions.md).

**CNI (Container Network Interface)** — плагин, ответственный за сетевой стек кластера. Поддержка NetworkPolicy зависит от CNI: Docker bridge (по умолчанию в Minikube) **не поддерживает** NetworkPolicy. Для тестирования необходим CNI-плагин с поддержкой policy (Calico, Cilium, Weave Net).

**Calico** — CNI-плагин, реализующий NetworkPolicy через iptables/ipvs. Поддерживает L3/L4 политики, NetworkPolicy, GlobalNetworkPolicy и BGP-маршрутизацию. В Minikube устанавливается как CNI при запуске с драйвером `none` или через Helm-чарт в среде Docker.

**Default Deny** — состояние изоляции пода, активируемое при наличии хотя бы одной NetworkPolicy, селектор которой match-ит под. Без явных разрешающих правил весь трафик (Ingress/Egress) отбрасывается.

---

## Базовые концепции

### Проблема NetworkPolicy в Minikube

По умолчанию Minikube (драйвер `docker`) использует **kubenet** — упрощённый сетевой плагин без поддержки NetworkPolicy. Это означает:

- NetworkPolicy-манифесты применяются (API-сервер принимает их), но **не оказывают воздействия** на трафик.
- Невозможно протестировать изоляцию, Default Deny, межсервисную фильтрацию.

Для полноценного тестирования NetworkPolicy необходим один из вариантов:

| Вариант | CNI | Поддержка NetworkPolicy | Сложность |
| :--- | :--- | :--- | :--- |
| **Minikube + Docker + Calico** | Calico | Полная | Средняя |
| **Minikube + драйвер `none`** | Calico/Cilium | Полная | Средняя |
| **kind** (альтернатива) | Calico/Cilium | Полная | Низкая |

### Когда использовать Minikube для тестирования NetworkPolicy

- Локальная отладка политик перед деплоем в staging/production.
- Проверка логики Default Deny + разрешающих правил.
- Тестирование DNS-политик (Egress к CoreDNS).
- Валидация взаимодействия NetworkPolicy с Service Account и RBAC.

---

## Практические сценарии

### Вариант 1: Calico на Minikube (Docker driver)

#### Шаг 1: Запуск Minikube с Calico

```bash
# Запуск Minikube с включенным CNI Calico
minikube start --network-plugin=cni --cni=calico \
  --cpus=4 --memory=8192

# Проверка, что Calico-поды запущены
kubectl get pods -n kube-system | grep calico
# → calico-kube-controllers-...   1/1     Running
# → calico-node-...               1/1     Running
```

> **Примечание:** Флаг `--cni=calico` доступен начиная с Minikube v1.32+. Если используете более раннюю версию, установите Calico через Helm (см. ниже).

#### Шаг 2: Альтернатива — установка Calico через Helm

```bash
# Добавление репозитория Tigera
helm repo add projectcalico https://docs.tigera.io/calico/charts
helm repo update

# Установка Calico (Operator + CRDs)
helm install calico projectcalico/tigera-operator \
  --namespace tigera-operator \
  --create-namespace \
  --set installation.calicoNetwork.ipPools[0].cidr=10.244.0.0/16 \
  --set installation.calicoNetwork.ipPools[0].encapsulation=VXLANCrossSubnet

# Ожидание готовности
kubectl get pods -n tigera-operator -w
# → calico-apiserver-...         1/1     Running
# → calico-kube-controllers-...  1/1     Running
# → calico-node-...              1/1     Running
```

#### Шаг 3: Создание тестовых подов

```yaml
# test-pods.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: netpol-test
---
apiVersion: v1
kind: Pod
metadata:
  name: frontend
  namespace: netpol-test
  labels:
    app: frontend
spec:
  containers:
  - name: nginx
    image: nginx:1.27
    ports:
    - containerPort: 80
---
apiVersion: v1
kind: Pod
metadata:
  name: backend
  namespace: netpol-test
  labels:
    app: backend
spec:
  containers:
  - name: nginx
    image: nginx:1.27
    ports:
    - containerPort: 80
---
apiVersion: v1
kind: Pod
metadata:
  name: client
  namespace: netpol-test
  labels:
    app: client
spec:
  containers:
  - name: curl
    image: curlimages/curl:latest
    command: ["sleep", "3600"]
```

```bash
kubectl apply -f test-pods.yaml

# Проверка connectivity ДО политик
kubectl exec -n netpol-test client -- curl -s --max-time 3 frontend
# → <!DOCTYPE html>... (успешно)
kubectl exec -n netpol-test client -- curl -s --max-time 3 backend
# → <!DOCTYPE html>... (успешно)
```

#### Шаг 4: Default Deny + разрешающие правила

```yaml
# default-deny-and-allow.yaml
# 1. Default Deny Ingress в namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: netpol-test
spec:
  podSelector: {}
  policyTypes:
  - Ingress
---
# 2. Разрешить трафик к backend ТОЛЬКО от frontend
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: netpol-test
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
      port: 80
```

```bash
kubectl apply -f default-deny-and-allow.yaml

# Проверка: frontend -> backend (разрешено)
kubectl exec -n netpol-test frontend -- curl -s --max-time 3 backend
# → <!DOCTYPE html>... (OK)

# Проверка: client -> backend (заблокировано)
kubectl exec -n netpol-test client -- curl -s --max-time 3 backend
# → < timeout / connection refused ( Blocked by NetworkPolicy)

# Проверка: client -> frontend (заблокировано — Default Deny)
kubectl exec -n netpol-test client -- curl -s --max-time 3 frontend
# → < timeout / connection refused
```

#### Шаг 5: Egress-политика (блокировка DNS)

```yaml
# deny-egress-except-dns.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-egress-except-dns
  namespace: netpol-test
spec:
  podSelector:
    matchLabels:
      app: client
  policyTypes:
  - Egress
  egress:
  # Разрешить DNS (TCP/UDP порт 53)
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

```bash
kubectl apply -f deny-egress-except-dns.yaml

# DNS работает
kubectl exec -n netpol-test client -- nslookup frontend.netpol-test.svc.cluster.local
# → Name: frontend.netpol-test.svc.cluster.local

# Внешний трафик заблокирован
kubectl exec -n netpol-test client -- curl -s --max-time 3 http://example.com
# → < timeout (Egress blocked)
```

### Вариант 2: Драйвер `none` с Calico

```bash
# Требуется Linux + root
minikube start --driver=none --cni=calico \
  --kubernetes-version=v1.36.0

# Все компоненты запускаются на хосте
kubectl get pods -n kube-system | grep calico
```

> **Важно:** Драйвер `none` устанавливает компоненты Kubernetes прямо на хост. Используйте только в изолированных средах (VM, контейнер).

### Диагностика NetworkPolicy

```bash
# Список всех политик в namespace
kubectl get networkpolicy -n netpol-test

# Детали конкретной политики
kubectl describe networkpolicy default-deny-ingress -n netpol-test

# Проверка правил через Calico
calicoctl get networkpolicy -n netpol-test
calicoctl get globalnetworkpolicy

# Логи Calico Node (packet drops)
kubectl logs -n kube-system -l k8s-app=calico-node --tail=50 | grep -i drop
```

### Очистка

```bash
kubectl delete namespace netpol-test
minikube stop
```

---

## Дополнительная информация

### См. также

- [NetworkPolicy: Определения](../../../Networking/Network/NetworkPolicy/definitions.md) — базовая теория
- [NetworkPolicy: Логика правил](../../../Networking/Network/NetworkPolicy/rule_logic.md) — аддитивность и селекторы
- [NetworkPolicy: Production-диагностика](../../../Networking/Network/NetworkPolicy/production_debugging.md) — чек-лист
- [Minikube: Определения и концепции](./minikube_concepts.md) — архитектура и CNI

### Полезные ссылки

- [Calico on Minikube](https://docs.tigera.io/calico/latest/getting-started/kubernetes/minikube)
- [NetworkPolicy Validators](https://kubernetes.io/docs/concepts/services-networking/network-policies/) — официальная документация
