# Kubespray: Offline установка — Шаг 5: Настройка MetalLB и Ingress

## Предварительные требования

| Компонент | Требование | Проверка |
| :--- | :--- | :--- |
| **Кластер Kubernetes** | Развёрнут и работоспособен | `kubectl get nodes` — все узлы `Ready` |
| **MetalLB** | Установлен Kubespray (если `metallb_enabled: true`) | `kubectl get pods -n metallb-system` |
| **Ingress-Nginx** | Установлен Kubespray (если `ingress_nginx_enabled: true`) | `kubectl get pods -n ingress-nginx` |
| **Локальный DNS** | Настроен для резолва доменов кластера | `dig hubble.k8s.domain.local` |
| **IP-диапазон** | Выделен статический диапазон вне DHCP | Координация с сетевой командой |

> **Примечание:** Если MetalLB или Ingress не были включены в `group_vars` на этапе установки, их можно установить отдельно через Helm или Kubespray. Подробнее: [SSoT: MetalLB](../../../Kubernetes/Networking/metallb.md), [SSoT: Ingress](../../../Kubernetes/Networking/Ingress/overview.md).

---

## Определения

**Ingress** — ресурс Kubernetes, предоставляющий правила для управления внешним доступом к сервисам в кластере (преимущественно HTTP/HTTPS). Обеспечивает балансировку нагрузки на прикладном уровне (L7), терминацию SSL/TLS и маршрутизацию на основе виртуальных хостов и путей URL.

**MetalLB** — сетевой балансировщик нагрузки для кластеров Kubernetes на bare-metal. Реализует тип сервиса `LoadBalancer` через протоколы ARP/NDP (режим Layer 2) или BGP.

**VIP (Virtual IP)** — виртуальный IP-адрес, динамически назначаемый MetalLB для обслуживания внешнего трафика.

Детальные концепции и теория:
- [SSoT: MetalLB — балансировщик для Bare-metal](../../../Kubernetes/Networking/metallb.md)
- [SSoT: Ingress — обзор и основные концепции](../../../Kubernetes/Networking/Ingress/overview.md)

---

## Основные концепции

### Цель этапа

Обеспечение отказоустойчивого внешнего доступа к сервисам кластера в изолированном контуре. Без этого этапа приложения доступны только внутри кластерной сети (ClusterIP) или через NodePort.

**Ключевые задачи:**

1. **Активация MetalLB:** настройка способа анонсирования адресов (в данном гайде — L2 как наиболее простой для закрытых сред).
2. **Конфигурация IP-пула:** выбор диапазона адресов, исключённого из DHCP.
3. **Валидация работоспособности:** проверка, что MetalLB корректно назначает и анонсирует IP.
4. **Настройка Ingress-ресурсов:** создание правил маршрутизации для конкретных сервисов.
5. **Интеграция с DNS:** привязка доменных имен к выделенным VIP.

### Архитектура прохождения трафика (Offline)

В закрытом контуре цепочка выглядит следующим образом:

1. **Клиент (браузер)** → обращается к `hubble.k8s.domain.local`.
2. **DNS (внутренний DNS-сервер)** → возвращает IP `192.168.1.200` (MetalLB VIP).
3. **Сетевой уровень** → пакет попадает на узел кластера, который в данный момент владеет этим VIP (выбирается через лидерство в MetalLB Speaker).
4. **Ingress-Nginx Pod** → принимает трафик на портах 80/443, анализирует заголовок `Host: hubble.k8s.domain.local`.
5. **Cilium Network** → перенаправляет трафик в соответствующий Pod сервиса `hubble-ui`.

---

## Практические сценарии

### 1. Проверка установки MetalLB

Если при развёртывании кластера были установлены переменные `metallb_enabled: true` и `metallb_speaker_enabled: true`, MetalLB уже развёрнут в кластере.

```bash
# Проверка подов MetalLB
kubectl get pods -n metallb-system
# → NAME                          READY   STATUS    RESTARTS   AGE
# → controller-5f7b6d8c9-xxxxx    1/1     Running   0          10m
# → speaker-xxxxx                 1/1     Running   0          10m

# Проверка DaemonSet speaker (должен быть на каждом узле)
kubectl get ds -n metallb-system
# → NAME      DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
# → speaker   3         3         3       3            3           <none>          10m
```

Если MetalLB не установлен, его можно установить через Helm:

```bash
helm repo add metallb https://metallb.github.io/metallb
helm install metallb metallb/metallb \
  --namespace metallb-system \
  --create-namespace \
  --set frrk8s.enabled=true
```

> Подробнее об установке: [SSoT: MetalLB — установка](../../../Kubernetes/Networking/metallb.md#установка).

### 2. Конфигурация MetalLB в режиме Layer 2

Для активации балансировщика создайте два ресурса: `IPAddressPool` (где брать адреса) и `L2Advertisement` (как сообщать сети о них).

**Манифест конфигурации (`metallb-l2-setup.yaml`):**

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: primary-pool
  namespace: metallb-system
spec:
  # Используйте диапазон из вашей подсети, исключенный из DHCP
  addresses:
  - 192.168.1.200-192.168.1.210
  autoAssign: true
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: l2-adv
  namespace: metallb-system
spec:
  # Привязка анонсирования к созданному пулу
  ipAddressPools:
  - primary-pool
```

**Применение манифеста:**

```bash
kubectl apply -f metallb-l2-setup.yaml
# → ipaddresspool.metallb.io/primary-pool created
# → l2advertisement.metallb.io/l2-adv created
```

### 3. Валидация работоспособности MetalLB

Перед созданием Ingress-ресурсов убедитесь, что MetalLB корректно назначает IP-адреса.

**Проверка конфигурации:**

```bash
# Проверка созданных пулов
kubectl get ipaddresspools -n metallb-system
# → NAME           AUTO-ASSIGN   AVOID-BUGGY-IPs   ADDRESSES
# → primary-pool   true          false             192.168.1.200-192.168.1.210

# Проверка анонсов
kubectl get l2advertisements -n metallb-system
# → NAME      IPADDRESSPOOLS   INTERFACES
# → l2-adv    [primary-pool]
```

**Тестовый сервис для проверки:**

```yaml
# test-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: test-lb
  namespace: default
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 80
  selector:
    app: test
```

```bash
kubectl apply -f test-service.yaml

# Проверка назначения IP
kubectl get svc test-lb -n default
# → NAME      TYPE           CLUSTER-IP      EXTERNAL-IP     PORT(S)
# → test-lb   LoadBalancer   10.233.15.204   192.168.1.200   80:31234/TCP
```

**Проверка ARP-анонсов (с узла кластера):**

```bash
# На узле, которому назначен IP
ip neigh | grep 192.168.1.200
# → 192.168.1.200 dev eth0 lladdr 00:xx:xx:xx:xx:xx REACHABLE

# Или с клиентской машины
arping -I eth0 192.168.1.200
# → 60 bytes from 00:xx:xx:xx:xx:xx (192.168.1.200): index=0 time=1.234 msec
```

После успешной проверки удалите тестовый сервис:

```bash
kubectl delete svc test-lb -n default
```

### 4. Валидация Ingress-Nginx

Если в `group_vars` Kubespray было указано `ingress_nginx_enabled: true`, контроллер развёрнут автоматически.

```bash
# Проверка подов Ingress
kubectl get pods -n ingress-nginx
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → ingress-nginx-controller-xxxxx               1/1     Running   0          15m

# Проверка сервиса (должен получить EXTERNAL-IP от MetalLB)
kubectl get svc -n ingress-nginx ingress-nginx-controller
# → NAME                       TYPE           CLUSTER-IP      EXTERNAL-IP     PORT(S)
# → ingress-nginx-controller   LoadBalancer   10.233.15.204   192.168.1.200   80:31234/TCP,443:32456/TCP
```

> **Важно по версиям (2026):** Community-версия `ingress-nginx` (v1.x) перешла в стадию ограниченной поддержки (EOL). В новых инсталляциях на базе Cilium рекомендуется использовать **Cilium Ingress Controller**, который работает нативно через eBPF без лишних прослоек. Подробнее: [SSoT: Ingress — обзор](../../../Kubernetes/Networking/Ingress/overview.md).

### 5. Настройка доступа к Hubble UI через Ingress

Для доступа к визуализации Cilium в закрытом контуре создайте правило Ingress.

**Манифест Ingress (`hubble-ui-rules.yaml`):**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hubble-ui
  namespace: kube-system
  annotations:
    # Использование Nginx в качестве контроллера
    kubernetes.io/ingress.class: nginx
spec:
  rules:
  - host: hubble.k8s.domain.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: hubble-ui
            port:
              number: 80
```

**Применение:**

```bash
kubectl apply -f hubble-ui-rules.yaml
# → ingress.networking.k8s.io/hubble-ui created
```

**Проверка:**

```bash
# Проверка статуса Ingress
kubectl get ingress -n kube-system
# → NAME        CLASS   HOSTS                      ADDRESS        PORTS   AGE
# → hubble-ui   nginx   hubble.k8s.domain.local    192.168.1.200  80      2m

# Проверка доступности
curl -I http://hubble.k8s.domain.local
# → HTTP/1.1 200 OK
# → Server: nginx
```

### 6. Настройка DNS в закрытом контуре

Для работы через браузер необходимо, чтобы клиентская машина разрешала домен `hubble.k8s.domain.local`.

**Вариант А: Локальный DNS (рекомендуется)**

Добавьте A-запись на вашем DNS-сервере (который часто совмещён с Harbor):

```bash
# Пример для BIND
hubble.k8s.domain.local.  IN  A  192.168.1.200
```

**Вариант Б: Ручная настройка на клиенте**

Отредактируйте файл `/etc/hosts` (Linux/macOS) или `C:\Windows\System32\drivers\etc\hosts` (Windows):

```
192.168.1.200  hubble.k8s.domain.local
```

**Проверка DNS:**

```bash
dig hubble.k8s.domain.local +short
# → 192.168.1.200

# Или
nslookup hubble.k8s.domain.local
# → Name:    hubble.k8s.domain.local
# → Address: 192.168.1.200
```

### 7. Управление IP-пулами

**Добавление нового диапазона в существующий пул:**

```bash
kubectl edit ipaddresspool primary-pool -n metallb-system
# Добавьте новый диапазон в spec.addresses:
#   addresses:
#   - 192.168.1.200-192.168.1.210
#   - 192.168.1.220-192.168.1.230  # ← новый диапазон
```

**Создание отдельного пула для конкретных сервисов:**

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: services-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.240-192.168.1.250
  autoAssign: false  # Только явное назначение через аннотации
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: services-adv
  namespace: metallb-system
spec:
  ipAddressPools:
  - services-pool
```

**Назначение конкретного IP сервису:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
  annotations:
    metallb.universe.tf/loadBalancerIPs: 192.168.1.245
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 8080
  selector:
    app: my-app
```

### 8. Мониторинг MetalLB

MetalLB экспортирует метрики в формате Prometheus на порту `9128`.

**Проверка метрик вручную:**

```bash
# Получение метрик с пода controller
kubectl port-forward -n metallb-system svc/metallb-controller 9128:9128 &
curl -s http://localhost:9128/metrics | grep metallb
# → metallb_allocator_addresses_in_use_total{pool="primary-pool"} 3
# → metallb_speaker_announce_count{pool="primary-pool"} 150
```

**Ключевые метрики:**

| Метрика | Описание |
| :--- | :--- |
| `metallb_allocator_addresses_in_use_total` | Количество выделенных IP из пула |
| `metallb_allocator_addresses_total` | Общее количество доступных IP в пуле |
| `metallb_bgp_session_up` | Статус BGP-сессий (0 — down, 1 — up) |
| `metallb_speaker_announce_count` | Счётчик анонсов, отправленных speaker |

**Настройка ServiceMonitor для Prometheus Operator:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: metallb
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: metallb
  endpoints:
  - port: metrics
    interval: 30s
  namespaceSelector:
    matchNames:
    - metallb-system
```

---

## Дополнительная информация

### Диагностика и устранение неполадок

**1. Статус External IP застрял в `<pending>`:**

```bash
# Проверка логов MetalLB Controller
kubectl logs -n metallb-system -l app.kubernetes.io/component=controller --tail=50
# → E0831 12:00:00.000000       1 controller.go:123] "failed to allocate IP" ...

# Проверка конфигурации
kubectl get configurationstate -n metallb-system
# → NAME      STATUS   REASON
# → speaker   Valid

# Убедитесь, что IP-пул находится в той же L2-подсети, что и интерфейсы узлов
kubectl get ipaddresspools -n metallb-system -o yaml
```

**2. IP назначен, но сервис недоступен по сети:**

```bash
# Проверка ARP-ответов
arping -I eth0 192.168.1.200
# → 60 bytes from 00:xx:xx:xx:xx:xx (192.168.1.200): index=0 time=1.234 msec

# Проверка логов speaker
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker --tail=50

# Убедитесь, что strictARP включён в kube-proxy (для режима L2)
kubectl get configmap -n kube-system kube-proxy -o yaml | grep strictARP
# → strictARP: true
```

**3. Ошибка 404 при обращении по DNS:**

```bash
# Проверка Ingress-ресурса
kubectl describe ingress hubble-ui -n kube-system
# → Rules:
# →   Host                      Path  Backends
# →   ----                      ----  --------
# →   hubble.k8s.domain.local   /   hubble-ui:80 (10.244.x.x:80)

# Проверка логов Ingress-контроллера
kubectl logs -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx --tail=20
```

**4. MetalLB не анонсирует IP (offline-специфично):**

```bash
# Проверка, что все узлы в одной L2-подсети
ansible -i inventory/offline_cluster/inventory.ini all -m setup -a 'filter=ansible_default_ipv4'

# Проверка firewall — порты 7946 (MetalLB speaker) должны быть открыты между узлами
nc -zv <node-ip> 7946
```

**5. Ошибка ImagePullBackOff для MetalLB или Ingress:**

```bash
# Проверка наличия образов в Harbor
curl -sk https://harbor.domain.local/v2/k8s/registry.k8s.io/ingress-nginx/controller/tags/list

# Если образы отсутствуют — загрузите их в Harbor (см. Шаг 3)
```

### Откат изменений

**Удаление Ingress-ресурса:**

```bash
kubectl delete ingress hubble-ui -n kube-system
```

**Удаление IP-пула:**

```bash
kubectl delete ipaddresspool primary-pool -n metallb-system
kubectl delete l2advertisement l2-adv -n metallb-system
```

**Полное удаление MetalLB:**

```bash
# Если установлен через Helm
helm uninstall metallb -n metallb-system

# Если установлен через манифесты
kubectl delete -f https://raw.githubusercontent.com/metallb/metallb/v0.16.1/config/manifests/metallb-native.yaml
```

### См. также

- **[Шаг 4: Развёртывание кластера](./step4_cluster_deploy.md)** — процедура запуска Ansible.
- **[Проверка кластера](./cluster_verification.md)** — глубокое тестирование сетевой связности и DNS.
- **[SSoT: MetalLB — детальный справочник](../../../Kubernetes/Networking/metallb.md)** — настройка BGP режима и продвинутых пулов.
- **[SSoT: Ingress — обзор и концепции](../../../Kubernetes/Networking/Ingress/overview.md)** — архитектура, аннотации, безопасность.
