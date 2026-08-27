# Сетевая сегментация и микросегментация

## Определения

- **Сетевая сегментация (Network Segmentation):** Процесс разделения сети на изолированные фрагменты (сегменты) на уровнях L2/L3. Основная цель — локализация широковещательного трафика и создание базовых барьеров безопасности между крупными группами ресурсов.
- **Микросегментация (Microsegmentation):** Метод безопасности, позволяющий детализировать контроль доступа до уровня отдельных рабочих нагрузок (воркфлоу), контейнеров или даже процессов. Политики строятся на основе **идентичности (Identity)** и контекста приложения, а не на нестабильных IP-адресах.
- **East-West трафик:** Сетевое взаимодействие внутри периметра (между серверами/подами). Составляет до 80% трафика современных ЦОД и является основной целью микросегментации.
- **North-South трафик:** Трафик между внутренней сетью и внешним миром (входящий/исходящий через периметр).
- **Lateral Movement (Горизонтальное перемещение):** Техника, используемая злоумышленниками для перемещения внутри сети после первоначального взлома одного из узлов. Микросегментация — основной метод противодействия.
- **Deny-by-default (Запрет по умолчанию):** Принцип, при котором весь трафик запрещён, пока не разрешён явно политикой безопасности.
- **Assume Breach (Предположение о взломе):** Принцип проектирования сети так, будто один из сегментов уже скомпрометирован.

## Основные концепции

В рамках архитектуры [Zero Trust](./zero_trust_overview.md) сегментация и микросегментация реализуют принцип минимальных привилегий, сводя к минимуму «радиус поражения» (blast radius) при компрометации одного узла.

### Уровни и методы реализации

1.  **Макросегментация (L2/L3):**
    - Использование [VLAN](../OSI_TCP_IP_Model/data_link_layer.md) и VRF (Virtual Routing and Forwarding) для изоляции на сетевом оборудовании.
    - VRF создают несколько независимых таблиц маршрутизации на одном физическом устройстве, позволяя использовать пересекающиеся IP-адреса в разных VRF.
    - Фильтрация на межсетевых экранах (NGFW) между подсетями.
    - **Типичное применение:** Разделение Production/Staging/Development, изоляция сети управления.

2.  **Облачная сегментация:**
    - **Security Groups (SG):** Stateful-правила на уровне инстанса (vNIC). Разрешённый входящий трафик автоматически разрешает ответный. Могут ссылаться на другие Security Groups.
    - **Network ACLs (NACL):** Stateless-правила на уровне подсети. Требуют явного разрешения входящего и исходящего трафика. Обрабатываются раньше Security Groups.
    - Используется в AWS/GCP/Yandex Cloud — декларативные правила, привязанные к инстансам или подсетям.

3.  **Хостовая микросегментация (eBPF):**
    - **Cilium:** Использование eBPF для фильтрации пакетов непосредственно в ядре Linux. Поиск правил происходит за константное время $O(1)$ через BPF Maps.
    - **Tetragon:** Обеспечивает сегментацию на уровне системных вызовов и процессов, блокируя подозрительную активность еще до отправки пакета в сеть.
    - **Преимущества:** Независимость от сетевой инфраструктуры, детализация до уровня процессов, высокая производительность.

4.  **Прикладная сегментация (Service Mesh):**
    - **Istio / Linkerd:** Аутентификация через mTLS (Mutual TLS). Контроль на уровне L7 (разрешение конкретных HTTP методов и путей).
    - **Identity-based (SPIFFE):** Присвоение каждому сервису криптографически подтвержденной идентичности, не зависящей от инфраструктуры.
    - **Sidecar Tax:** Накладные расходы на sidecar-прокси. В 2026 году решается через Ambient Mesh или eBPF-ускорение.

### Ключевые принципы

- **Изоляция Lateral Movement:** Ограничение возможности связи между узлами в одной подсети (например, Client-to-Client isolation в Kubernetes).
- **Контекстная осведомленность:** Использование метаданных (метки Kubernetes, теги облака, состояние процесса) для принятия решения о доступе.
- **Принцип минимальных привилегий:** Разрешать только тот трафик, который необходим для работы приложения.
- **Эшелонированная защита (Defense in Depth):** Комбинация нескольких уровней сегментации (VLAN + Security Groups + NetworkPolicy).

### Сравнение технологий

| Характеристика | VLAN / ACL | Security Groups | eBPF (Cilium) | Service Mesh |
| :--- | :--- | :--- | :--- | :--- |
| **Гранулярность** | Подсеть | Инстанс / Роль | Контейнер / Под | Метод API / gRPC |
| **Производительность** | Высокая (Hardware) | Высокая | Экстремальная | Средняя (Sidecar) |
| **Уровень OSI** | L2 - L4 | L3 - L4 | L3 - L7 | L7 |
| **Контекст** | Нет | Теги облака | Метки K8s, Процессы | Identity (SPIFFE) |
| **Сложность внедрения**| Низкая | Средняя | Высокая | Очень высокая |
| **Stateful/Stateless** | Зависит | Stateful | Stateful | Stateful |

## Наблюдаемость и аудит (Day 2 Operations)

Микросегментация неэффективна без визуализации трафика. Инструменты 2026 года:

-   **Cilium Hubble:** Визуализация потоков East-West, выявление заблокированных пакетов и анализ производительности на уровне L7.
-   **Kiali:** Граф зависимостей сервисов в Service Mesh, отображение статуса mTLS и ошибок маршрутизации.
-   **Анализ потоков (Flow Logs):** Экспорт сетевых логов в SIEM для обнаружения аномалий и попыток Lateral Movement.
-   **Network Policy Audit:** Инструменты анализа политик (напrium, Cilium Editor) для выявления избыточных или конфликтующих правил.

## Практические сценарии

### Сценарий 1: Предотвращение Lateral Movement в Kubernetes

**Задача:** При захвате одного Frontend-пода злоумышленник пытается просканировать сеть. Необходимо заблокировать любые попытки обращения к соседним Frontend-подам или к базе данных напрямую, минуя Backend.

**Предусловия:**
- Kubernetes кластер с CNI, поддерживающим NetworkPolicy (Cilium, Calico, Weave)
- Метки (labels) настроены для подов: `app: frontend`, `app: backend`, `app: mongodb`
- Политика Default Deny применена

**Конфигурация:**

```yaml
# 1. Политика Default Deny для всех ingress-подключений в namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress

---
# 2. Разрешить frontend -> backend по порту 8080
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: production
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
# 3. Разрешить backend -> mongodb по порту 27017
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-backend-to-mongodb
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: mongodb
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: backend
    ports:
    - protocol: TCP
      port: 27017
```

**Валидация:**
```bash
# Тест: frontend -> backend (должен работать)
kubectl exec frontend-pod -- curl -s http://backend-service:8080/health
# → {"status": "ok"}

# Тест: frontend -> mongodb (должен быть заблокирован)
kubectl exec frontend-pod -- nc -zv mongodb-service 27017 -w 3
# → (hangs or times out)

# Визуализация с Hubble (Cilium)
hubble observe --namespace production --follow
# → TIMESTAMP             SOURCE                    DESTINATION               TYPE
# → 2026-01-01T00:00:00Z  frontend-pod:port → mongodb:27017  POLICY_DENIED
```

### Сценарий 2: L7-микросегментация с Cilium

**Задача:** Ограничить доступ к базе данных на уровне HTTP-методов (разрешить только POST /query, запретить GET).

**Предусловия:**
- Установлен Cilium CNI (версия 1.14+)
- Доступ к kubectl с правами администратора

**Конфигурация:**

```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: "secure-db-access"
  namespace: production
spec:
  endpointSelector:
    matchLabels:
      app: mongodb
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: backend
    toPorts:
    - ports:
      - port: "27017"
        protocol: TCP
      rules:
        http:
        - method: "POST"
          path: "/query"
```

**Валидация:**
```bash
# Проверка что политика применена
kubectl get cnp -n production
# → NAME               AGE
# → secure-db-access   5m

# Проверка через Cilium CLI
kubectl -n kube-system exec -it ds/cilium -- cilium policy get
# → [Rule]
# → - Allows from labels app=backend
# →   - to port 27017/tcp
# →   - with HTTP method POST path /query
```

### Сценарий 3: Сегментация в гибридном облаке

**Задача:** Распространить политики микросегментации на несколько кластеров в разных облаках, обеспечивая единый периметр безопасности на основе идентичности сервисов.

**Предусловия:**
- Несколько Kubernetes кластеров в разных облачных провайдерах
- Cilium установлен во всех кластерах
- Настроен Cilium ClusterMesh

**Конфигурация:**

```bash
# 1. Включение ClusterMesh в первом кластере
cilium clustermesh enable --context cluster1

# 2. Подключение второго кластера
cilium clustermesh connect --context cluster1 --destination-context cluster2

# 3. Проверка состояния ClusterMesh
cilium clustermesh status --context cluster1
# → ClusterMesh:   2/2 clusters ready
```

**Пример политики для нескольких кластеров:**
```yaml
apiVersion: "cilium.io/v2"
kind: CiliumNetworkPolicy
metadata:
  name: cross-cluster-access
  namespace: production
spec:
  endpointSelector:
    matchLabels:
      app: payment-service
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: order-service
        k8s:io.cilium.k8s.policy.cluster: cluster-aws  # Доступ только из AWS кластера
    toPorts:
    - ports:
      - port: "8443"
        protocol: TCP
```

**Валидация:**
```bash
# Проверка доступности сервисов между кластерами
kubectl exec -n production deploy/order-service -- curl -s https://payment-service.production.svc.clusterset.local:8443/health
# → {"status": "ok"}

# Проверка заблокированного доступа
kubectl exec -n production deploy/unauthorized-app -- nc -zv payment-service 8443 -w 3
# → (connection refused or timeout)
```

### Сценарий 4: Настройка VRF для изоляции в Linux

**Задача:** Создать полную изоляцию трафика между Production и Staging средами на одном сервере с пересекающимися IP-адресами.

**Предусловия:**
- Linux ядро 4.15+ (поддержка VRF)
- Утилита iproute2
- Два или более сетевых интерфейса

**Конфигурация:**

```bash
# 1. Создание VRF-инстансов
ip link add vrf-production type vrf table 100
ip link add vrf-staging type vrf table 200

# 2. Активация VRF
ip link set vrf-production up
ip link set vrf-staging up

# 3. Привязка интерфейсов к VRF
ip link set eth1 master vrf-production
ip link set eth2 master vrf-staging

# 4. Настройка IP-адресов внутри VRF
ip addr add 192.168.1.10/24 dev eth1 vrf vrf-production
ip addr add 192.168.1.10/24 dev eth2 vrf vrf-staging  # Одинаковый IP в разных VRF!

# 5. Маршруты по умолчанию в каждом VRF
ip route add default via 192.168.1.1 dev eth1 vrf vrf-production
ip route add default via 192.168.1.1 dev eth2 vrf vrf-staging

# 6. Защита от утечки трафика между VRF
ip route add unreachable default table 100 metric 8192
ip route add unreachable default table 200 metric 8192

# 7. Настройка sysctl для работы с VRF
sysctl -w net.ipv4.tcp_l3mdev_accept=1
sysctl -w net.ipv4.udp_l3mdev_accept=1
```

**Валидация:**
```bash
# Проверка что VRF созданы и интерфейсы привязаны
ip vrf show
# → Name              Table
# → vrf-production    100
# → vrf-staging       200

# Проверка маршрутизации внутри VRF
ip route show vrf vrf-production
# → default via 192.168.1.1 dev eth1
ip route show vrf vrf-staging
# → default via 192.168.1.1 dev eth2

# Проверка изоляции — трафик из vrf-production не должен попадать в vrf-staging
ip vrf exec vrf-production ping 192.168.1.100
# → (должен работать)
ip vrf exec vrf-staging ping 192.168.1.100
# → (должен работать, но это другой хост)

# Проверка что приложение слушает в правильном VRF
ip vrf exec vrf-production ss -tlnp | grep :8080
# → LISTEN  0  128  192.168.1.10:8080  *:*  users:(("app",pid=1234))
```

### Сценарий 5: Миграция с VLAN на Zero Trust (поэтапное внедрение)

**Задача:** Поэтапно внедрить микросегментацию в существующей инфраструктуре без прерывания работы приложений.

**Предусловия:**
- Существующая сеть с VLAN-сегментация
- Kubernetes кластер с CNI, поддерживающим NetworkPolicy
- Инструмент анализа траекта (Cilium Hubble, ksniff)

**Этап 1: Аудит текущего трафика (Monitor Mode)**
```bash
# Установка Cilium в режиме мониторинга (без блокировки)
helm install cilium cilium/cilium --namespace kube-system \
  --set hubble.relay.enabled=true \
  --set hubble.ui.enabled=true \
  --set policyEnforcementMode=never

# Сбор информации о трафике в течение 1-2 недель
hubble observe --namespace production --last 24h --output jsonpb > traffic-audit.json

# Анализ потоков для создания политик
# Используйте Cilium Editor или policy-forger для генерации NetworkPolicy
```

**Этап 2: Создание Default Deny политик**
```yaml
# Применять по одному namespace!
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
```

**Этап 3: Добавление разрешительных правил**
```yaml
# Разрешить DNS (критически важно!)
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
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

**Этап 4: Переход в блокирующий режим**
```bash
# После того как все необходимые потоки разрешены
helm upgrade cilium cilium/cilium --namespace kube-system \
  --set policyEnforcementMode=default
```

**Валидация:**
```bash
# Проверка что все необходимые потоки работают
kubectl exec -n production deploy/app -- curl -s https://external-api.example.com
# → {"status": "ok"}

# Проверка что неавторизованный трафик заблокирован
kubectl exec -n production deploy/app -- nc -zv unauthorized-service 8080 -w 3
# → (connection refused)

# Мониторинг заблокированных потоков
hubble observe --namespace production --verdict DROPPED
# → TIMESTAMP             SOURCE              DESTINATION         VERDICT
# → 2026-01-01T00:00:00Z  app-pod → unauthorized:8080  DROPPED
```

## Валидация и диагностика

### Проверка корректности политик

```bash
# 1. Проверка что NetworkPolicy применены
kubectl get networkpolicy -A
# → NAMESPACE     NAME                     POD-SELECTOR
# → production    default-deny-ingress     <none>
# → production    allow-frontend-backend   app=backend

# 2. Проверка через Cilium (если используется)
kubectl -n kube-system exec -it ds/cilium -- cilium endpoint list
# → IDENTITY   ENDPOINT   LABELS              POLICY
# → 12345      pod-1      app=frontend         ingress: enabled, egress: enabled

# 3. Проверка через Hubble
hubble observe --namespace production --type policy-verdict
# → TIMESTAMP             SOURCE              DESTINATION         VERDICT   POLICY
# → 2026-01-01T00:00:00Z  frontend → backend  ALLOWED   allow-frontend-backend
# → 2026-01-01T00:00:01Z  frontend → mongodb  DENIED    default-deny

# 4. Тестирование connectivity matrix
# Используйте tools типа kConnectivity или cilium connectivity test
cilium connectivity test --namespace test
```

### Аудит безопасности

```bash
# Поиск избыточных политик
kubectl get networkpolicy -A -o yaml | grep -A5 "ingress:"

# Поиск подов без политик (не защищённых)
kubectl get pods -A -o json | jq '.items[] | select(.metadata.labels.app != null) | .metadata.name'

# Проверка что нет "any-any" правил
kubectl get networkpolicy -A -o yaml | grep -B2 -A2 "ingress: - {}"
```

## Устранение неполадок

### Типичные проблемы и решения

| Проблема | Симптомы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Потеря DNS** | Поды не резолвят имена после применения Default Deny | `kubectl exec pod -- nslookup kubernetes.default` | Добавить политику разрешающую UDP/TCP 53 к kube-dns |
| **Неожиданная блокировка** | Приложение не работает после применения политики | `hubble observe --verdict DROPPED` | Проанализировать заблокированные потоки, добавить разрешающие правила |
| **Политика не применяется** | Трафик идёт несмотря на запрет | `kubectl get cnp -o wide` — проверить селекторы | Проверить что endpointSelector соответствует меткам подов |
| **Сетевая петля** | Высокий broadcast-трафик, деградация | `tcpdump -i any broadcast` | Включить STP, проверить NetworkPolicy на конфликты |
| **Slow performance** | Высокая задержка между подами | `kubectl exec pod -- iperf3 -c remote-pod` | Проверить eBPF maps (Cilium), ресурсы CPU на нодах |

### Диагностика NetworkPolicy в Kubernetes

```bash
# 1. Проверка что CNI поддерживает NetworkPolicy
kubectl get crd networkpolicies.networking.k8s.io
# → NAME                                    CREATED AT
# → networkpolicies.networking.k8s.io        2024-01-01T00:00:00Z

# 2. Проверка что политики применяются на конкретный под
kubectl describe networkpolicy allow-frontend-to-backend -n production
# → PodSelector: app=backend
# → Allowing ingress traffic:
# →    From:
# →      PodSelector: app=frontend
# →    Port: 8080/TCP

# 3. Использование ksniff для захвата трафика на поде
kubectl ksniff frontend-pod -n production -f "port 8080"
# → Capturing traffic on pod frontend-pod

# 4. Визуализация политик через Cilium Editor
# https://editor.cilium.io — загрузите YAML для визуализации
```

## Дополнительная информация

### Рекомендации по внедрению

1.  **Начинайте с аудита:** Перед внедрением микросегментации соберите данные о текущих потоках (1-2 недели в режиме Monitor).
2.  **Постепенное внедрение:** Применяйте Default Deny политики по одному namespace, начиная с наименее критичных.
3.  **DNS — критически важно:** Всегда разрешайте DNS (порт 53) перед применением Default Deny.
4.  **Тестирование:** Используйте staging-среду для тестирования политик перед production.
5.  **Документирование:** Каждая политика должна иметь комментарий о назначении (через аннотации).

### Ограничения и граничные случаи

- **NetworkPolicy не работает с hostNetwork:** Поды с `hostNetwork: true` не подчиняются NetworkPolicy.
- **Performance impact:** При большом количестве политик (>1000) возможно снижение производительности. Используйте агрегирующие селекторы.
- **Сложность отладки:** Микросегментация усложняет диагностику проблем связности. Требуется инструментарий визуализации.
- **StatefulSet и DaemonSet:** Учитывайте специфику при создании политик для таких типов подов.
- **Мультикластер:** Cross-cluster политики требуют дополнительной настройки (ClusterMesh, Federation).

### Связанные документы

- **[Концепция Zero Trust (Нулевое доверие)](./zero_trust_overview.md)** — архитектурная основа микросегментации.
- **[Сетевые зоны безопасности (DMZ и управление)](./network_security_zones.md)** — традиционное зонирование и его связь с микросегментацией.
- **[Cilium: Высокопроизводительный CNI](../../Kubernetes/Networking/Network/CNI/cilium.md)** — детальная реализация eBPF и политик.
- **[Service Mesh: Идеология и инструменты](../../Service_Mesh/service_mesh_concepts.md)** — прикладная сегментация на уровне L7.
- **[SDN: Программно-определяемые сети](../Concepts/sdn/sdn_overview.md)** — технологии реализации микросегментации.

### Первоисточники

- **NIST SP 800-207**: [Zero Trust Architecture](https://csrc.nist.gov/publications/detail/sp/800-207/final).
- **Cilium Documentation**: [Network Policy Guides](https://docs.cilium.io/en/stable/security/policy/).
- **Kubernetes Documentation**: [Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/).
