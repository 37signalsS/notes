# Day-2 операции HA кластера Kubernetes на Bare-Metal

## Определения

**Day-2 Operations** — операции по эксплуатации и обслуживанию кластера после первичного развертывания: обновления, мониторинг, бэкапы, управление ресурсами, безопасность и обслуживание узлов.

**External Access (Внешний доступ)** — обеспечение доступа к сервисам внутри кластера извне. На bare-metal реализуется через MetalLB (L2/BGP) + Ingress-контроллер или Gateway API.

**Observability (Наблюдаемость)** — совокупность метрик (Metrics), логов (Logs) и трассировки (Traces), позволяющих понять внутреннее состояние кластера и приложений.

**Disaster Recovery (DR)** — стратегия восстановления кластера после катастрофического сбоя (потеря узлов, данных, целого дата-центра).

---

## Основные концепции

### Архитектура Day-2 для bare-metal HA

После развертывания кластера (Step 1-8 в [Обзоре HA](./k8s_ha_cluster_overview.md)) начинается фаза эксплуатации. Ключевые направления:

```
Внешний доступ          Мониторинг            Безопасность
(MetalLB + Ingress)     (Prometheus/Grafana)   (PSS/PSA, RBAC)
       │                      │                      │
       └──────────┬───────────┴──────────────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
Обновления   Бэкапы/DR    Управление
(cluster     (Velero +    ресурсами
 upgrade)     etcd)       (Quotas/PDB)
```

### Приоритет Day-2 операций

| Приоритет | Операция | Периодичность | Критичность |
| :--- | :--- | :--- | :--- |
| 1 | Мониторинг и алертинг | Непрерывно | Критично |
| 2 | Бэкап etcd | Каждые 1-6 ч | Критично |
| 3 | Обновление кластера | Ежеквартально | Высокая |
| 4 | Ротация сертификатов | Раз в год (или до истечения) | Высокая |
| 5 | Обслуживание узлов (drain/cordon) | По необходимости | Средняя |
| 6 | Управление ресурсами (quotas) | Ежемесячно | Средняя |

---

## Практические сценарии

### 1. Внешний доступ: MetalLB + Ingress

На bare-metal нет облачного балансировщика. MetalLB решает проблему внешних IP для `LoadBalancer` сервисов, а Ingress-контроллер обеспечивает маршрутизацию L7-трафика.

#### Шаг 1: Установка MetalLB

```bash
# Добавление репозитория и установка через Helm
helm repo add metallb https://metallb.github.io/metallb
helm repo update

helm install metallb metallb/metallb \
  --namespace metallb-system \
  --create-namespace \
  --version 0.14.9
```

#### Шаг 2: Конфигурация IP-пула

```yaml
# metallb-config.yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: bare-metal-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.240-192.168.1.250  # Диапазон внешних IP из физической сети
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: l2-advertisement
  namespace: metallb-system
spec:
  ipAddressPools:
  - bare-metal-pool
```

```bash
kubectl apply -f metallb-config.yaml

# Проверка
kubectl get ipaddresspool -n metallb-system
kubectl get l2advertisement -n metallb-system
```

#### Шаг 3: Включение strictARP (обязательно для L2)

```bash
# На всех узлах
sudo sysctl -w net.ipv4.conf.all.arp_ignore=1
sudo sysctl -w net.ipv4.conf.all.arp_announce=2

# Перманентно
cat <<EOF | sudo tee /etc/sysctl.d/99-metallb-strictarp.conf
net.ipv4.conf.all.arp_ignore = 1
net.ipv4.conf.all.arp_announce = 2
EOF
sudo sysctl --system
```

> **Подробнее:** Архитектура MetalLB, режимы L2/BGP, FRR-K8s -- см. [MetalLB: Балансировщик для Bare-metal](../../Networking/metallb.md).

#### Шаг 4: Установка Ingress-контроллера

Для bare-metal рекомендуется Nginx Ingress Controller с `hostNetwork` или MetalLB для внешнего IP:

```bash
# Nginx Ingress Controller через Helm
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update

helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --create-namespace \
  --set controller.service.type=LoadBalancer \
  --set controller.hostNetwork=true \
  --set controller.kind=DaemonSet \
  --set controller.watchIngressWithoutClass=true
```

#### Шаг 5: Публикация сервиса через Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-ingress
  namespace: production
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - app.example.com
    secretName: app-tls
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: app-service
            port:
              number: 80
```

#### Верификация внешнего доступа

```bash
# Проверка MetalLB назначил IP
kubectl get svc -n ingress-nginx ingress-nginx-controller
# → TYPE: LoadBalancer, EXTERNAL-IP: 192.168.1.240

# Проверка доступности
curl -k https://192.168.1.240 -H "Host: app.example.com"

# Проверка Ingress
kubectl get ingress -n production
kubectl describe ingress app-ingress -n production
```

> **Подробнее:** Сравнение Ingress-контроллеров, миграция на Gateway API -- см. [Ingress: обзор](../../Networking/Ingress/overview.md), [Ingress: установка bare-metal](../../Networking/Ingress/installation/bare-metal-installation.md).

---

### 2. Мониторинг и наблюдаемость

Для bare-metal HA кластера мониторинг -- не опция, а необходимость. Отсутствие облачных сервисов (CloudWatch, Stackdriver) делает самодостаточный стек мониторинга критичным.

#### Что мониторить (обязательные метрики)

| Компонент | Метрика | Порог алерта | Описание |
| :--- | :--- | :--- | :--- |
| **etcd** | `etcd_server_has_leader` | == 0 | Потеря лидера -- кластер read-only |
| **etcd** | `etcd_disk_wal_fsync_duration_seconds` (p99) | > 10ms | Медленный диск -- нестабильность |
| **etcd** | `etcd_server_leader_changes_seen_total` | Рост > 5/час | Частые смены лидера |
| **API** | `apiserver_request_duration_seconds` (p99) | > 1s | Медленные запросы к API |
| **API** | `apiserver_request_total{code="5.."}` | Рост | Серверные ошибки API |
| **Kubelet** | `kubelet_node_name` (отсутствие) | < N узлов | Узел Lost/NotReady |
| **Pod** | `kube_pod_status_phase{phase="Pending"}` | > 5 мин | Поды не планируются |
| **Pod** | `kube_pod_container_status_restarts_total` | Рост | Частые перезапуски |
| **Сеть** | `node_netstat_Tcp_CurrEstab` | > 50000 | Приближение к лимиту conntrack |
| **Disk** | `node_filesystem_avail_bytes` | < 20% | Мало места на диске |

#### Установка Prometheus Operator (kube-prometheus-stack)

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install kube-prom prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --create-namespace \
  --set grafana.adminPassword=<password> \
  --set alertmanager.config.global.resolve_timeout=5m
```

#### Базовые алерты для HA

```yaml
# ha-alerts.yaml (PrometheusRule)
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ha-cluster-alerts
  namespace: monitoring
spec:
  groups:
  - name: etcd-health
    rules:
    - alert: EtcdNoLeader
      expr: etcd_server_has_leader == 0
      for: 1m
      labels:
        severity: critical
      annotations:
        summary: "etcd потерял лидера"
    - alert: EtcdHighFsyncLatency
      expr: histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) > 0.01
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "etcd: высокая задержка fsync (p99 > 10ms)"
  - name: api-server
    rules:
    - alert: ApiServerHighLatency
      expr: histogram_quantile(0.99, rate(apiserver_request_duration_seconds_bucket[5m])) > 1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "API Server: p99 latency > 1s"
  - name: node-health
    rules:
    - alert: NodeNotReady
      expr: kube_node_status_condition{condition="Ready",status="true"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Узел {{ $labels.node }} в статусе NotReady"
```

> **Подробнее:** Установка и настройка -- см. [Kube Prometheus Stack](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/), [Мониторинг Master-нод](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/master_nodes_monitoring.md), [Мониторинг etcd](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/etcd-monitoring.md).

#### Сбор логов (EFK/Loki)

```bash
# Вариант 1: Loki + Grafana (легковесный)
helm repo add grafana https://grafana.github.io/helm-charts
helm install loki grafana/loki-stack \
  --namespace logging \
  --create-namespace \
  --set loki.persistence.enabled=true \
  --set promtail.enabled=true

# Вариант 2: EFK (Elasticsearch + Fluent Bit + Kibana)
# Подробнее: см. [EFK Stack Setup](../../MonitoringLogging/EFK/efk_stack_setup_guide.md)
```

---

### 3. Обновление кластера (Upgrade)

Обновление HA bare-metal кластера -- 가장 ответственная Day-2 операция. Порядок: Control Plane (по одному мастеру) -> Worker-узлы (rolling).

#### Pre-upgrade чек-лист

```bash
# 1. Бэкап etcd (ОБЯЗАТЕЛЬНО)
sudo ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-pre-upgrade-$(date +%F).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# 2. Проверка здоровья кластера
kubectl get nodes
kubectl get pods -A --field-selector status.phase!=Running,status.phase!=Succeeded
kubeadm certs check-expiration

# 3. Проверка PDB (允不允许 drain)
kubectl get pdb -A

# 4. Проверка устаревших API
kubeadm upgrade plan
```

#### Последовательность обновления

```
1. etcd (Stacked: вместе с первым мастером)
   ↓
2. Первый Control Plane узел (kubeadm upgrade apply)
   ↓  (пауза 2-5 мин, проверка кворума)
3. Второй Control Plane узел (kubeadm upgrade node)
   ↓  (пауза 2-5 мин)
4. Третий Control Plane узел (kubeadm upgrade node)
   ↓  (последовательно, НЕ параллельно!)
5. Worker-узлы (cordon -> drain -> upgrade -> uncordon, по одному)
```

> **ВАЖНО:** Никогда не обновляйте более одного Control Plane узла одновременно. Потеря кворума etcd = полная недоступность кластера.

> **Подробнее:** Полное руководство -- см. [Обновление кластера Kubernetes](../../Operations/upgrading_clusters.md).

---

### 4. Управление сертификатами

Сертификаты kubeadm истекают через 1 год. Если кластер не обновляется (версионно), сертификаты нужно продлевать вручную.

#### Мониторинг срока действия

```bash
# Проверка на всех мастерах
kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME
# → admin.conf                 Sep 15, 2026 12:00 UTC   364d
# → apiserver                  Sep 15, 2026 12:00 UTC   364d

# Алерт через Prometheus (метрика из kubelet):
# kubelet_certificate_manager_client_cert_expiration_seconds < 604800 (7 дней)
```

#### Ручное продление (если не обновляете версию K8s)

```bash
# На КАЖДОМ мастере последовательно:
sudo kubeadm certs renew all

# Перезапуск статических подов (они подхватят новые сертификаты)
sudo crictl pods --name kube-apiserver -q | xargs -I {} sudo crictl stopp {}
sudo crictl pods --name kube-controller-manager -q | xargs -I {} sudo crictl stopp {}
sudo crictl pods --name kube-scheduler -q | xargs -I {} sudo crictl stopp {}

# Копирование нового admin.conf на рабочую машину
scp master-1:/etc/kubernetes/admin.conf ~/.kube/config

# Проверка
kubectl get nodes
```

> **Подробнее:** Структура PKI, ротация Root CA, ServiceAccount Keys -- см. [Управление сертификатами](../../Operations/certificate_management.md), [Предотвращение истечения SSL](../../Operations/ssl_expiration_prevention.md).

---

### 5. Резервное копирование и DR

Для bare-metal HA кластера нужны два уровня бэкапов:

| Уровень | Что бэкапим | Инструмент | RPO | RTO |
| :--- | :--- | :--- | :--- | :--- |
| **etcd** | Всее состояние кластера | `etcdctl snapshot` | 1-6 ч | < 30 мин |
| **Приложения** | Манифесты + PV данные | Velero + CSI Snapshots | 1-24 ч | < 1 ч |

#### Автоматический бэкап etcd

```bash
# CronJob на каждом мастере (crontab)
0 */4 * * * ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +\%F-\%H\%M).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key && \
  etcdutl snapshot status /backup/etcd-$(date +\%F-\%H\%M).db && \
  find /backup/ -name "etcd-*.db" -mtime +7 -delete
```

#### Установка Velero для бэкапа приложений

```bash
# Velero с локальным MinIO (bare-metal)
# 1. Установка MinIO
kubectl apply -f https://raw.githubusercontent.com/minio/minio-operator/master/deploy/minio-operator.yaml

# 2. Установка Velero
velero install \
  --provider aws \
  --bucket velero-backups \
  --secret-file ./credentials-velero \
  --plugins velero/velero-plugin-for-aws:v1.13.0 \
  --backup-location-config region=minio,s3ForcePathStyle=true,s3Url=http://minio.minio.svc:9000 \
  --use-node-agent
```

#### Периодический бэкап приложений

```yaml
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: daily-production-backup
  namespace: velero
spec:
  schedule: "0 2 * * *"  # Каждый день в 02:00
  template:
    includedNamespaces:
    - production
    - staging
    snapshotVolumes: true
    ttl: 720h0m0s  # Хранить 30 дней
    storageLocation: default
```

#### Восстановление кластера из снапшота etcd

```bash
# 1. Остановить Control Plane на всех узлах
for master in master-1 master-2 master-3; do
  ssh $master "sudo mv /etc/kubernetes/manifests/*.yaml /tmp/k8s-manifests/"
done

# 2. Восстановить etcd на первом мастере
sudo etcdutl snapshot restore /backup/etcd-pre-upgrade-2026-09-01.db \
  --data-dir=/var/lib/etcd-restored \
  --name=master-1 \
  --initial-cluster=master-1=https://192.168.1.11:2380,master-2=https://192.168.1.12:2380,master-3=https://192.168.1.13:2380 \
  --initial-cluster-token=etcd-cluster-restored \
  --initial-advertise-peer-urls=https://192.168.1.11:2380

# 3. Обновить --data-dir в манифесте etcd.yaml на новую директорию
# 4. Вернуть манифесты
for master in master-1 master-2 master-3; do
  ssh $master "sudo mv /tmp/k8s-manifests/*.yaml /etc/kubernetes/manifests/"
done
```

> **Подробнее:** Архитектура Velero, CRD, Data Mover -- см. [Обзор Velero](../../ToolsUtilities/velero-overview.md). Стратегии -- [Backup Strategies](../../Operations/backup-strategies.md).

---

### 6. Обслуживание узлов (Cordon/Drain)

#### Безопасное выведение узла из кластера

```bash
# 1. Пометить как недоступный для планирования
kubectl cordon <node-name>

# 2. Выселить поды (с учетом PDB)
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --timeout=5m \
  --force=false

# 3. Проверить, что поды мигрировали
kubectl get pods -A -o wide | grep <node-name>
# → Должны остаться только DaemonSet поды

# 4. После обслуживания -- вернуть в строй
kubectl uncordon <node-name>
```

#### Типичные проблемы drain

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Drain зависает | PDB не позволяет выселить поды | `kubectl get pdb -A`, проверить `disruptionsAllowed` |
| Ошибка: unreachable node | Узел уже недоступен | `kubectl drain --force --ignore-unreachable` |
| Поды не мигрируют | Нет контроллера (bare pod) | Добавить контроллер или использовать `--force` |

> **Подробнее:** Детали drain, Node Maintenance API -- см. [Обслуживание узлов](../../Operations/node_maintenance.md).

---

### 7. Управление ресурсами: ResourceQuota и LimitRange

На bare-metal ресурсы ограничены физическим железом. Квоты предотвращают исчерпание ресурсов.

#### ResourceQuota для namespace

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: production-quota
  namespace: production
spec:
  hard:
    requests.cpu: "20"
    requests.memory: 40Gi
    limits.cpu: "40"
    limits.memory: 80Gi
    pods: "50"
    services: "20"
    persistentvolumeclaims: "10"
```

#### LimitRange (значения по умолчанию)

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
  - default:
      cpu: "1"
      memory: 512Mi
    defaultRequest:
      cpu: 100m
      memory: 128Mi
    max:
      cpu: "4"
      memory: 8Gi
    min:
      cpu: 50m
      memory: 64Mi
    type: Container
```

#### Проверка использования квот

```bash
kubectl get resourcequota -n production
kubectl describe resourcequota -n production

# Алерт: использование > 80%
# kube_resourcequota_status{resource="pods",type="used"} / kube_resourcequota_status{resource="pods",type="hard"} * 100 > 80
```

> **Подробнее:** Расчет requests/limits, взаимодействие с HPA -- см. [Управление ресурсами: Requests, Limits, Quotas](../../Scheduling/qos_limit_and_requests.md).

---

### 8. Pod Security Admission (PSA)

С Kubernetes 1.25+ Pod Security Policy удалены. Их заменяет Pod Security Admission через метки на Namespace.

#### Включение PSA для namespace

```bash
# Baseline (минимальные ограничения) -- рекомендуется для всех
kubectl label ns production \
  pod-security.kubernetes.io/enforce=baseline \
  pod-security.kubernetes.io/enforce-version=latest \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/warn-version=latest \
  pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/audit-version=latest
```

#### Три уровня PSS

| Уровень | Описание | Примеры ограничений |
| :--- | :--- | :--- |
| **Privileged** | Без ограничений | hostNetwork, privileged, hostPath |
| **Baseline** | Минимальные ограничения | Запрещает privileged, hostPath, CapAdd NET_ADMIN |
| **Restricted** | Строгие ограничения | Запрещает特权 контейнеры, требует runAsNonRoot, drop ALL capabilities |

#### Проверка

```bash
# Проверка меток PSA на namespace
kubectl get ns -o custom-columns=NAME:.metadata.name,ENFORCE:.metadata.labels.pod-security\.kubernetes\.io/enforce

# Попытка создания привилегированного пода в restricted namespace (должна быть отклонена)
kubectl run test --image=nginx --restart=Never -n production --privileged
# → Error: pods "test" is forbidden: violates PodSecurity "restricted:latest"
```

> **Подробнее:** Профили PSS, миграция с PSP -- см. [Pod Security Standards и Secret](../../Base/secrets/pod_security_and_secrets.md), [Pod Security Testing in kind](../../Installation/kind/kind_pod_security_testing.md).

---

### 9. kube-proxy: выбор режима (IPVS vs iptables)

Режим kube-proxy влияет на производительность и стабильность сети кластера.

| Критерий | iptables | IPVS | nftables (K8s 1.31+) |
| :--- | :--- | :--- | :--- |
| **Алгоритмы балансировки** | Random | rr, wrr, lc, sh, dh | Random |
| **Производительность при >1000 сервисов** | O(n) -- деградация | O(1) -- стабильно | O(1) -- стабильно |
| **Обновление правил** | Полная перезапись | Инкрементальное | Атомарное |
| **Session Affinity** | conntrack | хеш-таблица IPVS | conntrack |
| **Graceful Termination** | Ограниченно | Полная поддержка | Полная поддержка |
| **Рекомендация** | <500 сервисов | >500 сервисов (рекомендуется) | K8s 1.31+ (будущее) |

#### Включение IPVS

```bash
# Убедитесь, что модули загружены (обычно уже есть после подготовки узлов)
lsmod | grep ip_vs
# → ip_vs_rr, ip_vs_wrr, ip_vs_sh, nf_conntrack

# Проверка текущего режима
kubectl get configmap -n kube-system kube-proxy -o yaml | grep mode
# → mode: "ipvs"  или  mode: "" (iptables по умолчанию)

# Переключение на IPVS
kubectl edit configmap -n kube-system kube-proxy
# mode: "ipvs"

# Перезапуск kube-proxy
kubectl rollout restart daemonset kube-proxy -n kube-system

# Проверка IPVS таблиц
sudo ipvsadm -Ln
```

> **Подробнее:** Архитектура IPVS, troubleshooting, Graceful Termination -- см. [kube-proxy: Сетевой прокси](../../Networking/Network/kube-proxy.md), [IPVS в Kubernetes](../../Networking/Network/CNI/ipvs.md).

---

### 10. Pod Disruption Budget (PDB)

PDB защищает критичные сервисы от чрезмерного выселения подов при обслуживании узлов.

#### Пример PDB для критичного сервиса

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api-server-pdb
  namespace: production
spec:
  minAvailable: 2  # Минимум 2 из 3 реплик должны быть доступны
  selector:
    matchLabels:
      app: api-server
```

#### Проверка перед drain

```bash
# Проверка всех PDB
kubectl get pdb -A

# Проверка конкретного PDB
kubectl get pdb api-server-pdb -o yaml
# → status.disruptionsAllowed: 1  (можно выселить 1 под)

# Если disruptionsAllowed = 0 -- drain зависнет!
```

> **Подробнее:** Тонкая настройка, взаимодействие с drain/upgrade -- см. [Pod Disruption Budget](../../Autoscaling/pod_disruption_budget.md).

---

## Дополнительная информация

### Чек-лист Day-2 готовности HA кластера

- [ ] MetalLB установлен, IP-пул настроен, strictARP включен
- [ ] Ingress-контроллер установлен, внешний доступ работает через VIP
- [ ] Prometheus + Grafana установлены, ключевые алерты настроены
- [ ] Сбор логов настроен (Loki/EFK)
- [ ] Бэкапы etcd работают по расписанию (каждые 4-6 ч), проверяются
- [ ] Velero установлен, Scheduled Backup создан для production namespace
- [ ] Сертификаты проверены (`kubeadm certs check-expiration`), мониторинг истечения настроен
- [ ] ResourceQuota и LimitRange установлены для каждого namespace
- [ ] Pod Security Admission включен (baseline/restricted) для production
- [ ] kube-proxy работает в рекомендуемом режиме (IPVS для >500 сервисов)
- [ ] PDB созданы для всех критичных сервисов (minAvailable >= 2)
- [ ] Playbook обновления кластера подготовлен и протестирован на staging
- [ ] Runbook для инцидентов (потеря кворума, отказ мастера) актуален

### Связи с другими документами

| Тема | Файл |
| :--- | :--- |
| Установка HA кластера | [Обзор HA кластера](./k8s_ha_cluster_overview.md) |
| Требования к среде | [Требования](./k8s_ha_environment_requirements.md) |
| Подготовка узлов | [Подготовка ОС](./k8s_ha_node_preparation.md) |
| Установка компонентов | [Компоненты](./k8s_ha_component_installation.md) |
| CNI (Calico) | [Установка CNI](./cni_installation.md) |
| Присоединение узлов | [Node Joining](./node_joining.md) |
| Верификация кластера | [Верификация](./k8s_ha_cluster_verification.md) |
| Обновление кластера | [Cluster Upgrade](../../Operations/upgrading_clusters.md) |
| Управление сертификатами | [Certificate Management](../../Operations/certificate_management.md) |
| MetalLB | [MetalLB для Bare-metal](../../Networking/metallb.md) |
| Ingress | [Ingress: обзор](../../Networking/Ingress/overview.md) |
| kube-proxy / IPVS | [kube-proxy](../../Networking/Network/kube-proxy.md) |
| Velero (бэкап) | [Velero Overview](../../ToolsUtilities/velero-overview.md) |
| PDB | [Pod Disruption Budget](../../Autoscaling/pod_disruption_budget.md) |
| ResourceQuota / Limits | [Requests, Limits, Quotas](../../Scheduling/qos_limit_and_requests.md) |
| Pod Security Admission | [PSS и Secret](../../Base/secrets/pod_security_and_secrets.md) |
| Мониторинг etcd | [etcd Monitoring](../../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/etcd-monitoring.md) |
| Backup strategies | [Backup Strategies](../../Operations/backup-strategies.md) |
| Node maintenance | [Cordon/Drain](../../Operations/node_maintenance.md) |

### Рекомендации для собеседований

При ответах на вопросы по Day-2 операциямHA bare-metal кластера:

1. **"Как дать внешний доступ?"** -- MetalLB (L2 для простоты, BGP для масштаба) + Ingress-контроллер (Nginx/Gateway API)
2. **"Как мониторить?"** -- Prometheus Operator (kube-prometheus-stack) + Grafana, алерты на etcd, API, узлы
3. **"Как обновить кластер?"** -- По одному мастеру (kubeadm upgrade apply/node), потом worker'ы (drain -> upgrade -> uncordon)
4. **"Как бэкапить?"** -- etcd snapshot каждые 4-6 ч + Velero для приложений
5. **"Что такое PDB?"** -- Защита от чрезмерного выселения при drain, minAvailable/maxUnavailable
6. **"IPVS или iptables?"** -- IPVS для >500 сервисов (O(1) vs O(n)), рекомендуется
7. **"Как PSA работает?"** -- Метки на namespace: enforce (блокировка), warn (предупреждение), audit (логирование)
8. **"Как ограничить ресурсы?"** -- ResourceQuota на namespace + LimitRange для дефолтных значений
