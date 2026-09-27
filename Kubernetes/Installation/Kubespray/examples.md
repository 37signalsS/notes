# Kubespray: Примеры конфигураций

## Определения

**Addons (Дополнения)** — вспомогательные компоненты Kubernetes, которые расширяют функциональность кластера (мониторинг, балансировщики, хранилища). В Kubespray аддоны обычно разворачиваются в пространство имен `kube-system` или специализированные неймспейсы (например, `metallb-system`).

**kube-system** — системное пространство имен для критически важных компонентов кластера и базовых дополнений (DNS, прокси, CNI).

**Helm** — менеджер пакетов для Kubernetes. Kubespray позволяет автоматически установить Helm на мастер-узлы для последующего ручного управления сложными приложениями.

**group_vars** — иерархическая система настроек Ansible, используемая Kubespray для хранения переменных кластера. Основные файлы: `all/all.yml` (общие настройки), `k8s_cluster/k8s-cluster.yml` (параметры кластера), `k8s_cluster/addons.yml` (аддоны).

## Основные концепции

### Управление дополнениями в Kubespray

Kubespray использует Ansible для управления жизненным циклом дополнений. Основной файл конфигурации — `inventory/mycluster/group_vars/k8s_cluster/addons.yml`.

**Типы дополнений:**
1. **Core Apps:** системные утилиты (Metrics Server, CoreDNS, Local Path Provisioner).
2. **Network Addons:** сетевые компоненты (MetalLB, Ingress-контроллеры, Cilium).
3. **External Tools:** инструменты интеграции (Cert-manager, Node Feature Discovery).

> [!WARNING]
> Начиная с версии **v2.31.0 (2026)**, прямая поддержка `ingress-nginx` и `kubernetes-dashboard` была удалена из состава Kubespray. Рекомендуется использовать Helm для их установки.

### Состав системного пространства имен

Пример стандартного набора компонентов после развертывания:

| Компонент | Префикс подов | Назначение |
| :--- | :--- | :--- |
| **Control Plane** | `kube-apiserver-*` | Статические поды управления |
| **CNI** | `calico-node-*` / `cilium-*` | Сетевой плагин. См. [CNI и kube-proxy](../../Networking/Network/cni_kube_proxy_roles.md) |
| **DNS** | `coredns-*` | Резолвинг имен внутри кластера |
| **Metrics** | `metrics-server-*` | Сбор ресурсов для HPA и `kubectl top` |
| **DNS Cache** | `nodelocaldns-*` | Локальное кэширование DNS-запросов на узлах |

### Жизненный цикл аддонов

Аддоны, включенные через `addons.yml`, управляются Ansible-ролями Kubespray. При повторном запуске `cluster.yml` или `upgrade-cluster.yml` Kubespray переопределяет конфигурацию аддонов, управляемых им напрямую. Аддоны, установленные через Helm или `kubectl apply` (ручные), остаются без изменений при обновлении кластера.

**Важно:** При обновлении Kubespray (например, с v2.30 на v2.31) проверяйте changelog на предмет удаления или изменения переменных аддонов. Некоторые переменные могут стать несовместимыми.

### Порядок активации аддонов

Kubespray применяет аддоны в определенном порядке, определяемом Ansible-ролями. Порядок критичен для компонентов, зависящих друг от друга:

1. **CNI** (Calico/Cilium/Flannel) — базовая сетевая связность.
2. **CoreDNS** — сервис-дискавери (работает только после CNI).
3. **Metrics Server** — метрики (требует доступа к API).
4. **NodeLocal DNS** — оптимизация DNS (требует работающего CoreDNS).
5. **MetalLB** — балансировщик (требует CNI для сетевой связности).
6. **Helm** — менеджер пакетов (для ручной установки остальных аддонов).

## Практические сценарии

### 1. Настройка Metrics Server

Metrics Server необходим для работы Horizontal Pod Autoscaler (HPA) и команды `kubectl top`.

**Конфигурация в `addons.yml`:**
```yaml
metrics_server_enabled: true
# Игнорировать проверку TLS сертификатов kubelet (часто нужно в Bare Metal)
metrics_server_kubelet_insecure_tls: true
# Настройка частоты сбора данных
metrics_server_metric_resolution: 15s
```

**Валидация:**
```bash
# Проверка регистрации API (AVAILABLE должен быть True)
kubectl get apiservice v1beta1.metrics.k8s.io
# → NAME                      SERVICE                      AVAILABLE   AGE
# → v1beta1.metrics.k8s.io    kube-system/metrics-server   True        1m

# Просмотр ресурсов узлов
kubectl top nodes
# → NAME        CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → control-1   150m         7%     1400Mi          36%

# Просмотр ресурсов подов с сортировкой
kubectl top pods -A --sort-by=cpu
```

**Troubleshooting:**
- Если `AVAILABLE` равен `False` — проверьте логи пода metrics-server: `kubectl logs -n kube-system -l k8s-app=metrics-server`.
- Ошибка `x509: cannot validate certificate` — используйте `metrics_server_kubelet_insecure_tls: true` для self-signed сертификатов kubelet.
- Под находится в `CrashLoopBackOff` — увеличьте ресурсы или проверьте совместимость версии metrics-server с версией Kubernetes.

> **Подробнее:** Детальная настройка, архитектура и Production-рекомендации — в [Metrics Server: Мониторинг ресурсов кластера](../../MonitoringLogging/metrics-server.md).

### 2. Конфигурация MetalLB (Layer 2)

MetalLB предоставляет External IP для сервисов типа `LoadBalancer` без использования облачных провайдеров.

**Конфигурация в `addons.yml`:**
```yaml
metallb_enabled: true
# Рекомендуется для большинства локальных сетей
metallb_protocol: "layer2"

# Определение пулов IP-адресов
metallb_config:
  address_pools:
    primary:
      ip_range:
        - "192.168.1.200-192.168.1.250"
      auto_assign: true
  # Обязательно для Layer 2
  l2_advertisements:
    default:
      ip_pools:
        - primary
```

**Валидация:**
```bash
# Проверка статуса MetalLB
kubectl get pods -n metallb-system
# → NAME                                      READY   STATUS    RESTARTS   AGE
# → speaker-xxxxx                             1/1     Running   0          5m
# → controller-xxxxx                          1/1     Running   0          5m

# Проверка назначенных IP-пулов
kubectl get ipaddresspool -n metallb-system

# Создание тестового сервиса
kubectl create deployment nginx --image=nginx --replicas=2
kubectl expose deployment nginx --port=80 --type=LoadBalancer

# Проверка внешнего IP (ожидается IP из диапазона 192.168.1.200-250)
kubectl get svc nginx
# → NAME    TYPE           CLUSTER-IP     EXTERNAL-IP     PORT(S)        AGE
# → nginx   LoadBalancer   10.96.100.50   192.168.1.200   80:31234/TCP   30s
```

**Troubleshooting:**
- Сервис остаётся в `Pending` — проверьте логи controller: `kubectl logs -n metallb-system -l app.kubernetes.io/component=controller`.
- IP назначен, но недоступен извне — убедитесь, что ARP-таблицы на маршрутизаторе обновились (может потребоваться до 30 секунд).
- Конфликт IP — убедитесь, что диапазон MetalLB не пересекается с DHCP-пулом вашей сети.

> **Подробнее:** Режим BGP, Dual-stack, FRR-K8s — в [MetalLB: Балансировщик нагрузки для Bare-metal](../../Networking/metallb.md).

### 3. Динамическое локальное хранилище (Local Path Provisioner)

Позволяет автоматически создавать `PersistentVolumes`, используя дисковое пространство узлов. Идеально для небольших кластеров или тестовых сред.

**Конфигурация в `addons.yml`:**
```yaml
local_path_provisioner_enabled: true
local_path_provisioner_storage_class: "local-path"
local_path_provisioner_reclaim_policy: Delete
local_path_provisioner_claim_root: /opt/local-path-provisioner
```

**Валидация:**
```bash
# Проверка StorageClass
kubectl get sc local-path
# → NAME                 PROVISIONER             RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION   AGE
# → local-path           rancher.io/local-path   Delete          WaitForFirstConsumer   false                  1m

# Создание тестового PVC
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-lpp
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-path
  resources:
    requests:
      storage: 1Gi
EOF

# Проверка привязки (BOUND)
kubectl get pvc test-lpp
# → NAME       STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → test-lpp   Bound    pvc-xxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx       1Gi        RWO            local-path     30s

# Проверка создания директории на узле (на узле, где запущен под)
ls -la /opt/local-path-provisioner/pvc-*
```

**Ограничения:**
- Данные привязаны к конкретному узлу. При перемещении пода на другой узел данные недоступны.
- Нет контроля ёмкости — приложение может занять всё пространство диска.
- Только режим `ReadWriteMany` не поддерживается.

> **Подробнее:** Сравнение с альтернативами, бэкап, безопасность — в [Local Path Provisioner](../../Storage/local-path-provisioner.md).

### 4. Оптимизация DNS: Node Local DNS

Уменьшает задержки и количество запросов к CoreDNS за счет запуска локального кэширующего агента на каждом узле. Решает проблему race conditions в `conntrack` при UDP-запросах.

**Конфигурация в `group_vars/k8s_cluster/k8s_cluster.yml`:**
```yaml
enable_nodelocaldns: true
# IP-адрес для локального прослушивания (обычно 169.254.20.10)
nodelocaldns_ip: 169.254.20.10
```

**Валидация:**
```bash
# Проверка DaemonSet
kubectl get daemonset -n kube-system node-local-dns
# → NAME               DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
# → node-local-dns     3         3         3       3            3           <none>          5m

# Проверка доступности DNS через локальный кэш
kubectl run dns-test --image=busybox:1.37 --rm -it --restart=Never -- nslookup kubernetes.default
# → Server:    169.254.20.10    ( должен отвечать локальный кэш )
# → Address:   169.254.20.10#53
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1

# Проверка логов на наличие ошибок
kubectl logs -n kube-system -l k8s-app=node-local-dns --tail=20
```

**Troubleshooting:**
- Поды не могут резолвить DNS — проверьте, что `node-local-dns` запущен на всех узлах: `kubectl get pods -n kube-system -l k8s-app=node-local-dns -o wide`.
- Задержки 1-5 секунд — убедитесь, что `conntrack` не блокирует UDP-трафик: `conntrack -S | grep -i drop`.
- Конфликт IP `169.254.20.10` — измените `nodelocaldns_ip` на другой link-local адрес.

> **Подробнее:** Архитектура, конфигурация upstream, диагностика — в [DNS в Kubernetes](../../Networking/dns_deep_dive.md).

### 5. Использование Helm (для удаленных аддонов)

Если вам нужен Ingress NGINX в версиях 2.31+, включите Helm в Kubespray и установите чарт вручную.

**Включение Helm в `addons.yml`:**
```yaml
helm_enabled: true
```

**Пример установки Ingress после развертывания кластера:**
```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm install my-ingress ingress-nginx/ingress-nginx --namespace ingress-nginx --create-namespace
```

**Валидация:**
```bash
# Проверка установки
helm list -n ingress-nginx
# → NAME       NAMESPACE       REVISION   UPDATED                                   STATUS    CHART            APP VERSION
# → my-ingress ingress-nginx   1          2026-08-31 10:00:00.000000000 +0000 UTC   deployed  ingress-nginx-4.x  x.x.x

# Проверка подов Ingress
kubectl get pods -n ingress-nginx
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → ingress-nginx-controller-xxxxxxxxx-xxxxx    1/1     Running   0          2m
```

**Важно:** При обновлении Kubespray Helm-чарты, установленные вручную, не затрагиваются. Обновляйте их отдельно через `helm upgrade`.

### 6. Выделенные узлы для Ingress (Архивный метод)

Для версий Kubespray **ниже 2.31**, где Ingress еще встроен, можно использовать изоляцию:

**Конфигурация в `addons.yml`:**
```yaml
ingress_nginx_enabled: true
ingress_nginx_host_network: true
ingress_nginx_nodeselector:
  node-role.kubernetes.io/ingress: ""
ingress_nginx_tolerations:
- key: "node-role.kubernetes.io/ingress"
  operator: "Exists"
  effect: "NoSchedule"
```

**Примечание:** Для Kubespray v2.31+ используйте Helm (сценарий 5) вместо этого метода.

### 7. Cert-manager (автоматизация TLS-сертификатов)

Cert-manager автоматизирует выдачу и ротацию TLS-сертификатов из Let's Encrypt или внутренних CA. Критически важен для production-кластеров.

**Установка через Helm (рекомендуется, так как встроенная поддержка Kubespray ограничена):**
```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true
```

**Валидация:**
```bash
# Проверка подов cert-manager
kubectl get pods -n cert-manager
# → NAME                                       READY   STATUS    RESTARTS   AGE
# → cert-manager-xxxxxxxxx-xxxxx               1/1     Running   0          2m
# → cert-manager-cainjector-xxxxxxxxx-xxxxx    1/1     Running   0          2m
# → cert-manager-webhook-xxxxxxxxx-xxxxx       1/1     Running   0          2m

# Проверка регистрации API
kubectl get apiservice v1.cert-manager.io
# → NAME                     SERVICE                      AVAILABLE   AGE
# → v1.cert-manager.io       cert-manager/cert-manager    True        2m
```

**Пример создания ClusterIssuer для Let's Encrypt:**
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - http01:
        ingress:
          class: nginx
```

**Troubleshooting:**
- Поды `CrashLoopBackOff` — проверьте, что CRD установлены: `kubectl get crd | grep cert-manager`.
- Сертификат не выдаётся — проверьте логи cert-manager: `kubectl logs -n cert-manager deploy/cert-manager`.
- Ошибка DNS-validated挑战 — убедитесь, что DNS-записи настроены правильно для DNS01-challendge.

### 8. Выбор CNI-плагина (Calico vs Cilium)

Kubespray поддерживает несколько CNI-плагинов. Выбор зависит от требований к функциональности и производительности.

**Конфигурация в `group_vars/k8s_cluster/k8s-cluster.yml`:**
```yaml
# Вариант 1: Calico (по умолчанию)
kube_network_plugin: calico

# Вариант 2: Cilium (рекомендуется для eBPF и NetworkPolicy)
# kube_network_plugin: cilium
# cilium_enable_bgp: false
# cilium_enable_hubble: true
```

**Сравнение:**

| Критерий | Calico | Cilium |
| :--- | :--- | :--- |
| **Производительность** | iptables/ipvs | eBPF (выше) |
| **NetworkPolicy** | Полная поддержка | Полная поддержка + расширения |
| **Мониторинг** | Felix exporter | Hubble (встроенный) |
| **Зрелость** | Очень высокая | Высокая (активно развивается) |
| **Совместимость** | Широкая | Требует eBPF-capable ядро (4.19+) |

**Валидация (для Cilium):**
```bash
# Проверка статуса Cilium
cilium status
# →    /¯¯\
# → /¯¯\__/¯¯\    Cilium:             OK
# → \__/¯¯\__/    Operator:           OK
# → /¯¯\__/¯¯\    Hubble:             OK
# → \__/¯¯\__/    ClusterMesh:        disabled

# Проверка Hubble UI (если включен)
kubectl get svc -n kube-system hubble-ui
```

> **Подробнее:** Детальное сравнение, NetworkPolicy, BGP — в [Выбор CNI и методы внешнего доступа](../../Networking/Network/CNI/selection_and_external_access.md).

### 9. Kubernetes Dashboard (через Helm)

Начиная с Kubespray v2.30+, Dashboard не входит в состав аддонов. Установка через Helm.

**Установка:**
```bash
helm repo add kubernetes-dashboard https://kubernetes.github.io/dashboard/
helm repo update

helm install kubernetes-dashboard kubernetes-dashboard/kubernetes-dashboard \
  --namespace kubernetes-dashboard \
  --create-namespace
```

**Валидация и доступ:**
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: admin-user
  namespace: kubernetes-dashboard
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: admin-user
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: admin-user
  namespace: kubernetes-dashboard
```

```bash
# Создание сервис-аккаунта с правами admin
kubectl apply -f dashboard-admin.yaml

# Получение токена для входа
kubectl -n kubernetes-dashboard create token admin-user
# → eyJhbGciOiJSUzI1NiIs...

# Запуск port-forward для доступа
kubectl port-forward -n kubernetes-dashboard svc/kubernetes-dashboard 8443:443
# → Доступ: https://localhost:8443
```

**Troubleshooting:**
- Ошибка `Unauthorized` — убедитесь, что токен не истёк (по умолчанию 1 час) и сервис-аккаунт имеет нужные права.
- Под Dashboard в `CrashLoopBackOff` — проверьте совместимость версии чарта с версией Kubernetes.

### 10. Настройка дополнительных StorageClass

Для production-сред часто требуется настроить дополнительные StorageClass помимо Local Path Provisioner.

**Пример: NFS-провижинер через Helm:**
```bash
helm repo add nfs-subdir-external-provisioner https://kubernetes-sigs.github.io/nfs-subdir-external-provisioner
helm repo update

helm install nfs-provisioner nfs-subdir-external-provisioner/nfs-subdir-external-provisioner \
  --namespace nfs-system \
  --create-namespace \
  --set nfs.server=192.168.1.10 \
  --set nfs.path=/exports/k8s \
  --set storageClass.name=nfs-client \
  --set storageClass.defaultClass=true
```

**Валидация:**
```bash
kubectl get sc
# → NAME                   PROVISIONER                                     RECLAIMPOLICY   VOLUMEBINDINGMODE      ALLOWVOLUMEEXPANSION   AGE
# → nfs-client (default)   cluster.local/nfs-provisioner-nfs-subdir...    Delete          Immediate              true                   1m
# → local-path             rancher.io/local-path                           Delete          WaitForFirstConsumer   false                  1d
```

**Важно:** При наличии нескольких StorageClass укажите нужный в PVC через `storageClassName` или назначьте `defaultClass: true` для предпочтительного провизионера.

### 11. Мониторинг: Prometheus и Grafana

Kubespray не включает Prometheus/Grafana в состав аддонов, но их легко установить через Helm после развертывания кластера.

**Установка kube-prometheus-stack (рекомендуется):**

```bash
# Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Создание неймспейса
kubectl create namespace monitoring

# Установка (включает Prometheus, Grafana, Alertmanager)
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set grafana.adminPassword=admin \
  --set prometheus.prometheusSpec.retention=15d \
  --set prometheus.prometheusSpec.storageSpec.volumeClaimTemplate.spec.resources.requests.storage=20Gi
```

**Валидация:**

```bash
# Проверка подов
kubectl get pods -n monitoring
# → NAME                                                     READY   STATUS    RESTARTS   AGE
# → monitoring-grafana-xxxxxxxxx-xxxxx                       3/3     Running   0          2m
# → monitoring-kube-prometheus-operator-xxxxxxxxx-xxxxx      1/1     Running   0          2m
# → monitoring-prometheus-node-exporter-xxxxx                1/1     Running   0          2m
# → alertmanager-monitoring-kube-prometheus-alertmanager-0   2/2     Running   0          2m
# → prometheus-monitoring-kube-prometheus-prometheus-0        2/2     Running   0          2m

# Проверка сервисов
kubectl get svc -n monitoring
# → NAME                                   TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)                        AGE
# → monitoring-grafana                     ClusterIP   10.233.0.100   <none>        80/TCP                         2m
# → monitoring-kube-prometheus-alertmanager ClusterIP   10.233.0.101   <none>        9093/TCP                       2m
# → monitoring-kube-prometheus-prometheus   ClusterIP   10.233.0.102   <none>        9090/TCP                       2m

# Доступ к Grafana (port-forward)
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
# → Доступ: http://localhost:3000 (admin/admin)
```

**Настройка доступа через Ingress (если Ingress установлен):**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: monitoring
  namespace: monitoring
  annotations:
    kubernetes.io/ingress.class: nginx
spec:
  rules:
  - host: grafana.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: monitoring-grafana
            port:
              number: 80
  - host: prometheus.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: monitoring-kube-prometheus-prometheus
            port:
              number: 9090
```

**Базовые алертинг-правила (добавляются через Values):**

```yaml
# В файле custom-values.yaml для helm install
alertmanager:
  config:
    route:
      receiver: 'slack'
    receivers:
    - name: 'slack'
      slack_configs:
      - api_url: 'https://hooks.slack.com/services/xxx/yyy/zzz'
        channel: '#alerts'
        text: 'ALERT: {{ .GroupLabels.alertname }}'
```

**Troubleshooting:**
- Под `prometheus-0` в `CrashLoopBackOff` — проверьте место на диске: `kubectl exec -n monitoring prometheus-0 -- df -h /prometheus`.
- Grafana не загружается — проверьте логи: `kubectl logs -n monitoring -l app.kubernetes.io/name=grafana`.
- Нет метрик — убедитесь, что Prometheus scrape Prometheus-оператора: `kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 9090` → Status → Targets.

> **Подробнее:** Детальная настройка, дашборды, интеграция с Loki — в [Prometheus Kubernetes](../../MonitoringLogging/prometheus/kubernetes_prometheus.md).

### 12. Сбор логов: Loki + Alloy

Для централизованного сбора логов в Kubespray рекомендуется использовать Grafana Loki (хранилище) и Grafana Alloy (агент сбора).

**Установка Loki:**

```bash
# Добавление репозитория
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Создание неймспейса
kubectl create namespace logging

# Установка Loki
helm install loki grafana-community/loki \
  --namespace logging \
  --set persistence.enabled=true \
  --set persistence.size=10Gi
```

**Установка Alloy (агент сбора логов):**

```bash
# Добавление репозитория
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

# Установка Alloy
helm install alloy grafana/alloy \
  --namespace logging \
  --set alloy.configFromString="
    loki.source.kubernetes \"all\" {
      forward_to = [loki.write.default.receiver]
    }
    loki.write \"default\" {
      endpoint {
        url = \"http://loki.logging.svc.cluster.local:3100/loki/api/v1/push\"
      }
    }
  "
```

**Валидация:**

```bash
# Проверка подов
kubectl get pods -n logging
# → NAME                                     READY   STATUS    RESTARTS   AGE
# → loki-0                                   1/1     Running   0          3m
# → alloy-xxxxx                              1/1     Running   0          1m

# Проверка доступности Loki
kubectl port-forward -n logging svc/loki 3100:3100
curl http://localhost:3100/ready
# → ready
```

**Интеграция с Grafana (если Grafana установлен через Prometheus):**

```bash
# Добавление Loki как источника данных в Grafana
kubectl port-forward -n monitoring svc/monitoring-grafana 3000:80
# → Доступ: http://localhost:3000
# → Configuration → Data Sources → Add data source → Loki
# → URL: http://loki.logging.svc.cluster.local:3100
```

**Примеры запросов LogQL в Grafana:**
- Все логи из неймспейса `default`: `{namespace="default"}`
- Ошибки в `kube-system`: `{namespace="kube-system"} |= "error"`
- Логи конкретного пода: `{pod="nginx-xxx"}`

**Troubleshooting:**
- Alloy не отправляет логи — проверьте連続ность: `kubectl exec -n logging -it alloy-xxx -- wget -qO- http://loki.logging.svc.cluster.local:3100/ready`.
- Loki не хранит логи — проверьте PVC: `kubectl get pvc -n logging`.
- Задержки в логах — уменьшите `batch_wait` в конфигурации Alloy.

> **Подробнее:** Детальная настройка, архитектура, LogQL — в [Loki Overview](../../Loki/loki_overview.md).

### 13. Управление ресурсами: Resource Quotas и Limit Ranges

Для контроля потребления ресурсов в кластере используются Resource Quotas (на уровень Namespace) и Limit Ranges (на уровень пода/контейнера).

**Resource Quota (ограничение на Namespace):**

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute-quota
  namespace: production
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    pods: "50"
    services: "10"
    persistentvolumeclaims: "20"
```

**Limit Range (ограничения на под/контейнер):**

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
  - default:
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:
      cpu: "100m"
      memory: "128Mi"
    type: Container
```

**Валидация:**

```bash
# Проверка квот
kubectl get resourcequota -n production
# → NAME            AGE   REQUEST                                          LIMIT
# → compute-quota   5m    requests.cpu: 5/10, requests.memory: 10Gi/20Gi   limits.cpu: 10/20, limits.memory: 20Gi/40Gi

# Проверка limit range
kubectl get limitrange -n production
# → NAME              CREATED AT
# → default-limits    2026-01-01T00:00:00Z

# Проверка подов (если limits не заданы, применяются default)
kubectl get pods -n production -o custom-columns=NAME:.metadata.name,CPU_REQ:.spec.containers[*].resources.requests.cpu,CPU_LIM:.spec.containers[*].resources.limits.cpu
```

**HPA (Horizontal Pod Autoscaler) с Metrics Server:**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: nginx-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: nginx
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

**Troubleshooting:**
- Pod в `Pending` из-за квот — проверьте `kubectl describe pod <name>` → Events → `exceeded quota`.
- HPA не масштабируется — убедитесь, что Metrics Server установлен: `kubectl get apiservice v1beta1.metrics.k8s.io`.

> **Подробнее:** Детальная настройка HPA, VPA, Cluster Autoscaler — в [Autoscaling](../../Autoscaling/overview.md).

### 14. Services в Kubernetes

Services обеспечивают стабильную точку доступа к подам, которые могут пересоздаваться и перемещаться между узлами.

**Типы Services:**

| Тип | Назначение | Пример |
| :--- | :--- | :--- |
| **ClusterIP** | Внутренний доступ в кластере (по умолчанию) | Доступ к базе данных из других подов |
| **NodePort** | Доступ через порт узла (30000-32767) | Временный доступ для отладки |
| **LoadBalancer** | Внешний балансировщик (MetalLB в bare-metal) | Доступ к веб-приложению извне |
| **ExternalName** | CNAME-запись для внешнего сервиса | Доступ к внешнему API |

**ClusterIP Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend-service
  namespace: production
spec:
  type: ClusterIP
  selector:
    app: backend
  ports:
  - port: 80
    targetPort: 8080
    protocol: TCP
```

**NodePort Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: backend-nodeport
  namespace: production
spec:
  type: NodePort
  selector:
    app: backend
  ports:
  - port: 80
    targetPort: 8080
    nodePort: 30080
    protocol: TCP
```

**LoadBalancer Service (с MetalLB):**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: frontend-lb
  namespace: production
  annotations:
    metallb.universe.tf/address-pool: primary-pool
spec:
  type: LoadBalancer
  selector:
    app: frontend
  ports:
  - port: 80
    targetPort: 80
    protocol: TCP
```

**ExternalName Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: external-api
  namespace: production
spec:
  type: ExternalName
  externalName: api.external.example.com
```

**Валидация:**

```bash
# Проверка Services
kubectl get svc -n production
# → NAME              TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)        AGE
# → backend-service   ClusterIP   10.233.0.100   <none>        80/TCP         5m
# → frontend-lb       LoadBalancer   10.233.0.101   192.168.1.200   80:31234/TCP   5m

# Проверка endpoints
kubectl get endpoints -n production
# → NAME              ENDPOINTS                          AGE
# → backend-service   10.233.0.10:8080,10.233.0.11:8080  5m

# Тест доступа к Service из пода
kubectl run test-svc --image=busybox:1.37 --rm -it --restart=Never -- wget -qO- --timeout=5 http://backend-service.production.svc.cluster.local
```

**Headless Service (для StatefulSet):**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-headless
  namespace: production
spec:
  clusterIP: None  # Headless Service
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
```

**Troubleshooting:**
- Сервис в `Pending` — проверьте, что поды с нужными лейблами существуют: `kubectl get pods -n production -l app=backend`.
- Endpoints пустые — проверьте selector и лейблы подов: `kubectl get pods -n production --show-labels`.
- DNS не резолвит — проверьте CoreDNS: `kubectl run test-dns --image=busybox:1.37 --rm -it --restart=Never -- nslookup backend-service.production.svc.cluster.local`.

> **Подробнее:** Детальная настройка, NetworkPolicy, Ingress — в [Networking](../../Networking/overview.md).

## Дополнительная информация

### Частые ошибки при настройке аддонов

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Сервис `LoadBalancer` в `Pending` | MetalLB не установлен или IP-пул исчерпан | Проверьте `kubectl get ipaddresspool -n metallb-system` |
| `kubectl top` не работает | Metrics Server не установлен или API не зарегистрирован | Проверьте `kubectl get apiservice v1beta1.metrics.k8s.io` |
| PVC в `Pending` | Нет доступного StorageClass или провизионер не работает | Проверьте `kubectl get sc` и логи провизионера |
| DNS не резолвит имена | CoreDNS или NodeLocal DNS не работают | Проверьте `kubectl get pods -n kube-system -l k8s-app=kube-dns` |
| Ingress не пропускает трафик | Ingress-контроллер не установлен (v2.31+) | Установите через Helm (сценарий 5) |

### Взаимодействие аддонов с обновлением кластера

При обновлении кластера через `upgrade-cluster.yml`:
- **Аддоны Kubespray** (Metrics Server, CoreDNS, MetalLB если включены через `addons.yml`) обновляются автоматически.
- **Helm-чарты** (Ingress, Dashboard, cert-manager) обновляются вручную: `helm upgrade <release> <chart>`.
- **Ручные манифесты** (`kubectl apply`) не затрагиваются, но могут потребовать обновления API-версий.

**Рекомендация:** Используйте GitOps (ArgoCD, Flux) для управления Helm-чартами и манифестами, чтобы версионировать изменения и автоматизировать обновления.

## Дополнительная информация

- [Обзор Kubespray](./overview.md) — базовые принципы.
- [Установка кластера](./kubespray_install/basic_concepts.md) — пошаговое руководство.
- [Управление кластером](./cluster_management.md) — масштабирование и обновление.
- [MetalLB: Балансировщик для Bare-metal](../../Networking/metallb.md) — детальная настройка сети.
- [Persistent Volumes](../../Storage/pv_and_pvc.md) — работа с хранилищами.
- [Local Path Provisioner](../../Storage/local-path-provisioner.md) — детальное описание провизионера.
- [Metrics Server](../../MonitoringLogging/metrics-server.md) — мониторинг ресурсов кластера.
- [DNS в Kubernetes](../../Networking/dns_deep_dive.md) — CoreDNS, NodeLocal DNSCache, диагностика.
- [Выбор CNI](../../Networking/Network/CNI/selection_and_external_access.md) — сравнение Calico, Cilium, Flannel.
