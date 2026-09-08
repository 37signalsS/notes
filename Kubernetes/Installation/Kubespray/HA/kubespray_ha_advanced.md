# Kubespray: Развертывание HA-кластера — Продвинутые темы

## Определения

**Отказоустойчивость (High Availability, HA)** — архитектурный подход, обеспечивающий непрерывную работу системы при выходе из строя отдельных компонентов. В Kubespray это достигается резервированием узлов Control Plane и etcd.

**Виртуальный IP (VIP)** — плавающий IP-адрес для доступа к API-серверу, который автоматически перемещается на активный мастер-узел при сбое текущего лидера.

**VRRP (Virtual Router Redundancy Protocol)** — сетевой протокол, используемый Keepalived для обнаружения отказов и автоматического переключения VIP между узлами в L2-сегменте.

**Split-Brain** — критическое состояние, при котором из-за сетевой изоляции два или более узла одновременно объявляют себя лидерами и используют один и тот же VIP, что приводит к конфликтам в сети и нестабильности API.

**Ротация сертификатов** — процесс плановой или экстренной замены TLS-сертификатов компонентов кластера (API-server, etcd, Kubelet) до истечения срока их действия.

**Kubernetes Node Readiness** — совокупность условий узла (`Ready`, `MemoryPressure`, `DiskPressure`, `PIDPressure`, `NetworkUnavailable`), определяющих его способность принимать поды.

---

## Основные концепции

### Тюнинг параметров отказоустойчивости

Настройка поведения механизмов HA выполняется через переменные в `inventory/mycluster/group_vars/k8s_cluster/k8s-cluster.yml` или `all/all.yml`.

#### Общие параметры

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **`loadbalancer_apiserver_localhost`** | `false` | Если `true`, на каждом узле запускается локальный прокси (nginx/haproxy) для связи с мастерами. Рекомендуется как дополнение к основному методу HA. |
| **`loadbalancer_apiserver_port`** | `6443` | Порт, который слушает локальный балансировщик. Не должен конфликтовать с API-сервером. |

#### Kube-vip параметры

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **`kube_vip_enabled`** | `false` | Активация kube-vip. Рекомендуемый метод для bare-metal. |
| **`kube_vip_address`** | — | Целевой VIP-адрес, который будет назначен на активный узел. |
| **`kube_vip_interface`** | определяется автоматически | Сетевой интерфейс для VIP (например, `eth0`, `bond0`). Рекомендуется указывать явно. |
| **`kube_vip_arp_enabled`** | `true` | Включает L2 (ARP) режим. Отключите для BGP. |
| **`kube_vip_cloud_provider`** | — | Провайдер для Service type LoadBalancer. Не используется для control plane VIP. |
| **`kube_vip_controlplane_vip`** | `true` | Управляет VIP для control plane (API-сервер). |
| **`kube_vip_services_vip`** | `false` | Управляет VIP для Service type LoadBalancer (замена MetalLB). |
| **`kube_vip_lb_class`** | — | Класс负载 балансировщика для Service type LoadBalancer. |

#### Keepalived параметры

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **`enable_keepalived`** | `false` | Активация Keepalived. Альтернатива kube-vip. |
| **`keepalived_virtual_router_id`** | `51` | Уникальный ID группы VRRP. Не должен конфликтовать с другими инстансами в подсети. |
| **`keepalived_interface`** | определяется автоматически | Интерфейс для VRRP-объявлений. |
| **`keepalived_password`** | — | Пароль аутентификации VRRP (одинаковый для группы). |
| **`keepalived_unicast_peers`** | — | Список IP-адресов для unicast (альтернатива multicast). Используйте, если multicast заблокирован. |
| **`keepalived_priority`** | `101` | Приоритет узла (выше = становится лидером при старте). |

#### Параметры HAProxy

| Переменная | Значение по умолчанию | Описание |
| :--- | :--- | :--- |
| **`haproxy_enabled`** | `true` (при `enable_keepalived`) | Запуск HAProxy на узлах Control Plane. |
| **`haproxy_global_maxconn`** | `100000` | Максимальное количество одновременных соединений. |
| **`haproxy_frontend_port`** | `6443` | Порт входящих соединений HAProxy. |
| **`haproxy_backend_port`** | `6444` | Порт бэкенда (реальный порт API-сервера). |

### Взаимодействие с сетевыми плагинами (CNI)

При выборе метода HA необходимо учитывать особенности сетевой подсистемы:

- **Calico (BGP):** При использовании BGP в Calico и BGP в kube-vip может потребоваться настройка пиринга с разными AS-номерами или использование разных сетевых интерфейсов. Убедитесь, что `kube_vip_bgp_asn` не конфликтует с `calico_bgp_asn`.
- **Cilium:** Поддерживает встроенную балансировку через eBPF. В сложных топологиях Cilium может брать на себя функции маршрутизации до API-сервера. Убедитесь, что `kube_vip_interface` соответствует интерфейсу, который Cilium использует для маршрутизации.
- **Flannel:** Не требует специальной настройки для HA. VIP работает на уровне L2/L3 без конфликтов с overlay-сеть.

---

## Практические сценарии

### 1. Тестирование отказоустойчивости (Keepalived + HAProxy)

#### Сценарий A: Миграция VIP при отказе узла

1. **Определите текущего владельца VIP:**
   ```bash
   ip a show <interface> | grep <VIP_ADDRESS>
   # → inet 192.168.1.100/32 scope global eth0
   ```
2. **Имитируйте сбой:** Остановите Keepalived на текущем лидере:
   ```bash
   systemctl stop keepalived
   ```
3. **Проверьте переключение:** На соседнем мастере убедитесь, что VIP появился:
   ```bash
   ip a show <interface> | grep <VIP_ADDRESS>
   # → inet 192.168.1.100/32 scope global eth0
   ```
4. **Замерьте время failover:** От времени остановки Keepalived до появления VIP на другом узле. Время переключения обычно составляет 1–3 секунды.
5. **Восстановите:** Запустите Keepalived на восстановленном узле:
   ```bash
   systemctl start keepalived
   ```

#### Сценарий B: Исключение API-сервера из балансировки

1. Остановите API-сервер на одном из мастеров:
   ```bash
   systemctl stop kube-apiserver
   ```
2. Проверьте статус бэкенда через сокет HAProxy:
   ```bash
   echo "show stat" | socat stdio /var/run/haproxy/admin.sock | grep kubernetes-api
   # → kubernetes-api-masters,master-1,0,0,0,0,,0,0,0,,0,,OFFLINE,...
   ```
3. HAProxy должен пометить узел как `OFFLINE` и перестать направлять на него трафик.
4. Проверьте доступность API через VIP:
   ```bash
   curl -sk https://<VIP>:6443/healthz
   # → ok
   ```
5. **Восстановите:** Перезапустите API-сервер и убедитесь, что он вернулся в балансировку:
   ```bash
   systemctl start kube-apiserver
   echo "show stat" | socat stdio /var/run/haproxy/admin.sock | grep kubernetes-api
   # → kubernetes-api-masters,master-1,0,0,0,0,,...,UP,...
   ```

### 2. Тестирование отказоустойчивости (Kube-vip)

1. **Проверка статуса пода:**
   ```bash
   kubectl get pods -n kube-system -l name=kube-vip -o wide
   # → kube-vip-master-1   1/1     Running   0          10d   master-1
   # → kube-vip-master-2   1/1     Running   0          10d   master-2
   # → kube-vip-master-3   1/1     Running   0          10d   master-3
   ```
2. **Проверка лидерства в логах:**
   ```bash
   kubectl logs -n kube-system -l name=kube-vip --tail=50
   # → INFO[0005] Node master-1 is now the leader
   ```
3. **Имитация отказа:** Временно переместите манифест:
   ```bash
   mv /etc/kubernetes/manifests/kube-vip.yaml /tmp/
   ```
   Kubelet остановит под и лидерство перейдет к другому узлу.
4. **Проверьте переключение VIP:**
   ```bash
   ip a show <interface> | grep <VIP_ADDRESS>
   ```
5. **Восстановите:** Верните манифест:
   ```bash
   mv /tmp/kube-vip.yaml /etc/kubernetes/manifests/
   ```

### 3. Проверка здоровья кластера

#### etcd

```bash
# Health-check всех узлов etcd
kubectl exec -n kube-system -it etcd-master-1 -- \
  etcdctl endpoint health --cluster \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key
# → https://10.0.0.11:2379 is healthy: successful commit to takes 4.547229ms
# → https://10.0.0.12:2379 is healthy: successful commit to takes 5.058137ms
# → https://10.0.0.13:2379 is healthy: successful commit to takes 4.812046ms

# Статус кластера: лидер, размер DB
kubectl exec -n kube-system -it etcd-master-1 -- \
  etcdctl endpoint status --cluster -w table \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key
# → | ENDPOINT        | VERSION | DB SIZE | IS LEADER | IS LEARNER | RAFT TERM | RAFT INDEX | RAFT APPLIED INDEX | ...
# → | 10.0.0.11:2379  | 3.5.12  | 24 MB   | true      | false      | 8         | 1945       | 1945               | ...
# → | 10.0.0.12:2379  | 3.5.12  | 24 MB   | false     | false      | 8         | 1945       | 1945               | ...
# → | 10.0.0.13:2379  | 3.5.12  | 24 MB   | false     | false      | 8         | 1945       | 1945               | ...
```

#### Kubernetes API

```bash
# Доступность API через VIP
curl -sk https://<VIP>:6443/healthz
# → ok

# Детальный health
curl -sk https://<VIP>:6443/readyz
# → [+]poststarthook/start-kube-apiserver-admission-plugins ok
# → [+]poststarthook/start-kube-aggregator-informers ok
# → ...

# Проверка версии API
kubectl version --short
```

#### Component Status

```bash
kubectl get componentstatuses
# → NAME                 STATUS    MESSAGE             ERROR
# → controller-manager   Healthy   ok
# → scheduler            Healthy   ok
# → etcd-0               Healthy   {"health":"true"}
# → etcd-1               Healthy   {"health":"true"}
# → etcd-2               Healthy   {"health":"true"}
```

#### Node Readiness

```bash
kubectl get nodes -o custom-columns=\
'NAME:.metadata.name,STATUS:.status.conditions[-?(@.type=="Ready")].status,ROLES:.metadata.labels.node-role\.kubernetes\.io\/control-plane'
# → NAME       STATUS   ROLES
# → master-1   True     control-plane
# → master-2   True     control-plane
# → master-3   True     control-plane
# → worker-1   True     <none>
```

### 4. Ротация сертификатов

#### Проверка срока действия

```bash
# На любом мастер-узле
kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME   ...
# → admin.conf                 Dec 30, 2026 23:59 UTC   364d
# → apiserver                  Dec 30, 2026 23:59 UTC   364d
# → apiserver-etcd-client      Dec 30, 2026 23:59 UTC   364d
# → ...
```

#### Плановая ротация (все сертификаты)

```bash
# Через Kubespray
ansible-playbook -i inventory/mycluster/hosts.yml cluster.yml \
  --become --become-user=root \
  --tags=rotate_certs

# Или вручную на каждом мастере
kubeadm certs renew all
```

#### Ротация только etcd-сертификатов

```bash
ansible-playbook -i inventory/mycluster/hosts.yml cluster.yml \
  --become --become-user=root \
  --tags=etcd,rotate_certs
```

#### Ротация kubelet-сертификатов на worker-узлах

```bash
# На каждом worker-узле
kubeadm certs renew kubelet
# Или через Kubespray на конкретном узле
ansible-playbook -i inventory/mycluster/hosts.yml cluster.yml \
  --become --become-user=root \
  --tags=rotate_certs \
  --limit=worker-1
```

#### Экстренная ротация при компрометации

```bash
# 1. Остановите API-сервер на всех мастерах
# 2. Удалите скомпрометированные сертификаты
rm /etc/kubernetes/pki/apiserver.crt /etc/kubernetes/pki/apiserver.key

# 3. Сгенерируйте новые
kubeadm certs renew apiserver

# 4. Перезапустите API-сервер
systemctl start kube-apiserver
```

### 5. Масштабирование Control Plane

#### Добавление мастер-узла

1. Добавьте новый узел в секции `[kube_control_plane]` и `[etcd]` инвентаря:
   ```yaml
   # inventory/mycluster/hosts.yml
   [kube_control_plane]
   master-1 ansible_host=10.0.1.11
   master-2 ansible_host=10.0.1.12
   master-3 ansible_host=10.0.1.13
   master-4 ansible_host=10.0.1.14  # новый

   [etcd]
   master-1
   master-2
   master-3
   master-4  # новый
   ```
2. Запустите масштабирование:
   ```bash
   ansible-playbook -i inventory/mycluster/hosts.yml cluster.yml
   ```
3. **Важно:** Kubespray автоматически обновит конфигурацию HAProxy/kube-vip на всех узлах. Не используйте `--limit` — кворум etcd требует обновления на всех узлах одновременно.

#### Удаление мастер-узла

```bash
# 1. Убедитесь, что кластер здоров перед удалением
kubectl get nodes
kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint status --cluster -w table

# 2. Удалите узел из инвентаря (удалите из [kube_control_plane] и [etcd])

# 3. Запустите удаление
ansible-playbook -i inventory/mycluster/hosts.yml remove-node.yml \
  -e node=master-4
```

> [!IMPORTANT]
> После удаления мастер-узла из кластера количество узлов etcd должно оставаться нечетным. Если у вас было 3 узла etcd и вы удалили один, кластер потеряет отказоустойчивость (кворум = 2 из 2 — нет容错). Сначала добавьте новый узел, затем удалите старый.

### 6. Обновление кластера (Upgrade)

#### Подготовка к обновлению

1. **Создайте бэкап etcd:**
   ```bash
   ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%Y%m%d-%H%M).db \
     --endpoints=https://127.0.0.1:2379 \
     --cacert=/etc/kubernetes/pki/etcd/ca.crt \
     --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
     --key=/etc/kubernetes/pki/etcd/healthcheck-client.key
   ```

2. **Проверьте состояние кластера:**
   ```bash
   kubectl get nodes
   kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint health --cluster
   ```

3. **Обновите Kubespray:**
   ```bash
   git fetch origin
   git checkout v2.31.0  # целевая версия
   ```

#### Выполнение обновления

1. Укажите целевую версию Kubernetes:
   ```yaml
   # inventory/mycluster/group_vars/k8s_cluster/k8s-cluster.yml
   kube_version: v1.31.4
   ```

2. Запустите обновление:
   ```bash
   ansible-playbook -i inventory/mycluster/hosts.yml --become upgrade-cluster.yml
   ```

#### Проверка после обновления

```bash
# Все узлы в статусе Ready?
kubectl get nodes

# etcd здоров?
kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint health --cluster

# Все поды в kube-system запущены?
kubectl get pods -n kube-system -o wide | grep -v Running

# API-сервер отвечает через VIP?
curl -sk https://<VIP>:6443/healthz
```

#### Откат при неудачном обновлении

Полный откат версии Kubernetes через Kubespray не поддерживается. Альтернативы:

1. **Восстановление etcd из снапшота:**
   ```bash
   # На всех мастер-узлах остановите etcd и API-сервер
   systemctl stop kube-apiserver etcd

   # Восстановите данные
   etcdctl snapshot restore /backup/etcd-pre-upgrade.db \
     --data-dir=/var/lib/etcd-restored

   # Обновите конфигурацию etcd на новых данных
   # Запустите etcd и API-сервер
   systemctl start etcd kube-apiserver
   ```

2. **Чистая переустановка** с предыдущей версией Kubespray (если восстановление невозможно).

### 7. Обслуживание узлов

#### Подготовка узла к обслуживанию

```bash
# 1. Запретите планирование новых подов
kubectl cordon master-2

# 2. Вытесните существующие поды (кроме DaemonSet)
kubectl drain master-2 --ignore-daemonsets --delete-emptydir-data \
  --force --timeout=300s

# 3. Проверьте, что поды мигрировали
kubectl get pods -o wide | grep master-2
```

#### Ручное обслуживание etcd на конкретном узле

```bash
# Остановите etcd
systemctl stop etcd

# Выполните обслуживание (дефрагментация, обновление конфигурации и т.д.)
# ...

# Проверьте健康 перед запуском
etcdctl endpoint health https://localhost:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# Запустите etcd
systemctl start etcd

# Убедитесь, что узел вернулся в кворум
kubectl exec -n kube-system etcd-master-1 -- etcdctl endpoint status --cluster -w table
```

#### Возврат узла в эксплуатацию

```bash
# 1. Верните узел в планировщик
kubectl uncordon master-2

# 2. Проверьте readiness
kubectl get node master-2
# → NAME       STATUS   ROLES           AGE   VERSION
# → master-2   Ready    control-plane   10d   v1.31.0
```

#### Maintenance Window (окно обслуживания)

Для кластеров с Production-нагрузкой рекомендуется:

1. **Согласуйте окно обслуживания** с владельцами сервисов.
2. **Убедитесь, что有足够的 реплик** для выдерживания потери одного узла:
   ```bash
   # Проверка количества реплик критичных сервисов
   kubectl get deploy -A -o custom-columns=\
   'NAMESPACE:.metadata.namespace,NAME:.metadata.name,REPLICAS:.spec.replicas,READY:.status.readyReplicas'
   ```
3. **Выполняйте обслуживание последовательно** — не более одного узла Control Plane одновременно.
4. **Мониторьте после каждого узла** — убедитесь, что кластер стабилен, прежде чем переходить к следующему.

### 8. Резервное копирование и восстановление etcd

#### Ручной бэкап

```bash
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%Y%m%d-%H%M).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# Проверка целостности
etcdctl snapshot status /backup/etcd-20260831-1430.db -w table
# → +---------+----------+------------+------------+
# → | TOTAL   | REVISION | TOTAL KEYS | TOTAL SIZE |
# → +---------+----------+------------+------------+
# → | 24 MB   | 1945     | 892        | 24 MB      |
# → +---------+----------+------------+------------+
```

#### Автоматический бэкап через Cron

```bash
# Добавьте на каждый мастер-узел
cat > /etc/cron.d/etcd-backup << 'EOF'
# Бэкап etcd каждые 6 часов
0 */6 * * * root ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +\%Y\%m\%d-\%H\%M).db --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt --key=/etc/kubernetes/pki/etcd/healthcheck-client.key && find /backup -name 'etcd-*.db' -mtime +7 -delete
EOF
```

#### Восстановление etcd из бэкапа

> [!WARNING]
> Процедура восстановления требует остановки etcd и API-сервера на всех узлах. Кластер будет недоступен на время восстановления.

```bash
# 1. Остановите API-сервер и etcd на ВСЕХ мастер-узлах
systemctl stop kube-apiserver etcd

# 2. Очистите старые данные etcd
mv /var/lib/etcd /var/lib/etcd.bak

# 3. Восстановите из снапшота
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-20260831-1430.db \
  --data-dir=/var/lib/etcd \
  --name=master-1 \
  --initial-cluster="master-1=https://10.0.1.11:2380,master-2=https://10.0.1.12:2380,master-3=https://10.0.1.13:2380" \
  --initial-cluster-token=k8s-etcd-cluster \
  --initial-advertise-peer-urls=https://10.0.1.11:2380

# 4. Запустите etcd
systemctl start etcd

# 5. Проверьте здоровье
etcdctl endpoint health --cluster \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# 6. Запустите API-сервер
systemctl start kube-apiserver
```

### 9. Мониторинг и алертинг

#### Ключевые метрики для мониторинга

| Компонент | Метрика | Порог алерта | Описание |
| :--- | :--- | :--- | :--- |
| **etcd** | `etcd_server_leader_changes_seen_total` | > 3 за 10 мин | Частые смены лидера — признак нестабильности сети |
| **etcd** | `etcd_disk_wal_fsync_duration_seconds` | p99 > 10 мс | Медленная запись WAL на диск |
| **etcd** | `etcd_server_proposals_failed_total` | Непрерывный рост | Проваленные提案ы Raft |
| **etcd** | `etcd_mvcc_db_total_size_in_bytes` | > 8 ГБ | Требуется дефрагментация |
| **API** | `apiserver_request_duration_seconds` | p99 > 1 с | Высокая латентность API |
| **API** | `apiserver_request_total{verb="WATCH"}` | Аномалия | Всплеск watch-запросов |
| **VIP** | `keepalived_master` | != 1 на VIP | Отсутствие активного мастера Keepalived |
| **Node** | `node_cpu_seconds_total` | > 90% на Control Plane | Перегрузка Control Plane узла |

#### Prometheus alerting правила (пример)

```yaml
groups:
  - name: kubespray-ha
    rules:
      - alert: EtcdLeaderChanges
        expr: increase(etcd_server_leader_changes_seen_total[10m]) > 3
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Частые смены лидера etcd"
          description: "Обнаружено {{ $value }} смен лидера за 10 минут"

      - alert: EtcdHighLatency
        expr: histogram_quantile(0.99, rate(etcd_disk_wal_fsync_duration_seconds_bucket[5m])) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Высокая латентность etcd WAL"

      - alert: KubeVipNoLeader
        expr: absent(kube_vip_leader)
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "kube-vip не имеет активного лидера"
```

#### Быстрая проверка мониторинга

```bash
# Prometheus: количество алертов
curl -s http://prometheus:9090/api/v1/alerts | jq '.data.alerts | length'

# Grafana: проверка доступности дашбордов
curl -s http://grafana:3000/api/health
# → { "database": "ok", "version": "10.2.0" }
```

### 10. Катастрофическое восстановление (Disaster Recovery)

#### Сценарий: Полная потеря Control Plane

Если все мастер-узла вышли из строя, но etcd-данные сохранены (есть бэкап):

1. **Подготовьте новый Control Plane узел** с чистой ОС и доступом к бэкапу etcd.
2. **Установите Kubespray** и сконфигурируйте инвентарь с одним мастером.
3. **Восстановите etcd** из снапшота (см. раздел 8).
4. **Инициализируйте кластер:**
   ```bash
   ansible-playbook -i inventory/mycluster/hosts.yml cluster.yml
   ```
5. **Добавьте оставшиеся мастер-узлы** по одному.

#### Сценарий: Потеря всех данных etcd без бэкапа

Это наихудший сценарий. Кластер пересоздается с нуля:

```bash
# 1. Очистите все узлы
ansible-playbook -i inventory/mycluster/hosts.yml reset.yml

# 2. Пересоздайте кластер
ansible-playbook -i inventory/mycluster/hosts.yml cluster.yml
```

> [!NOTE]
> При полном пересоздании все данные (Deployments, Services, Secrets, ConfigMaps) будут утеряны. Рекомендуется хранить манифесты приложений в Git (GitOps) для быстрого восстановления.

#### Сценарий: Split-brain с двумя активными VIP

```bash
# 1. Определите, какой узел должен быть лидером
ip a show <interface> | grep <VIP>

# 2. На «лишнем» узле остановите Keepalived
systemctl stop keepalived

# 3. Проверьте, что VIP назначен только на один узел
ip a show <interface> | grep <VIP>
# → inet 192.168.1.100/32 scope global eth0  (только на одном узле)

# 4. Проверьте VRRP-трафик
tcpdump -i any proto 112 -c 20

# 5. Если проблема повторяется, проверьте firewall
iptables -L INPUT -v | grep vrrp
```

---

## Устранение неполадок

### Проблемы с VIP (Keepalived)

| Симптом | Диагностика | Решение |
| :--- | :--- | :--- |
| VIP назначен на нескольких узлах (split-brain) | `tcpdump -i any proto 112` — есть ли VRRP-пакеты? | 1. Разрешить proto 112 в firewall. 2. Использовать unicast: `keepalived_unicast_peers` |
| VIP не назначается вообще | `systemctl status keepalived` — запущен ли сервис? | 1. Проверить интерфейс в конфигурации. 2. Проверить `ip_nonlocal_bind` |
| VIP мигрирует слишком часто (flapping) | `journalctl -u keepalived -f` — что в логах? | 1. Увеличить ` advert_int`. 2. Проверить стабильность сети |

### Проблемы с Kube-vip

| Симптом | Диагностика | Решение |
| :--- | :--- | :--- |
| kube-vip не становится лидером | `kubectl logs -n kube-system -l name=kube-vip` | 1. Проверить RBAC (ServiceAccount, ClusterRoleBinding). 2. Проверить доступ к API |
| VIP не анонсируется в L2 | `tcpdump -i <interface> arp` — есть ли Gratuitous ARP? | 1. Проверить `kube_vip_arp_enabled`. 2. Проверить L2-связность |
| kube-vip消耗 много CPU | `kubectl top pods -n kube-system -l name=kube-vip` | 1. Проверить версию (актуальные версии оптимизированы). 2. Увеличить ресурсы |

### Проблемы с etcd

| Симптом | Диагностика | Решение |
| :--- | :--- | :--- |
| Потеря кворума | `etcdctl endpoint status --cluster` | Восстановление из снапшота. См. раздел 8 |
| Высокая латентность | `etcdctl check perf` | 1. Проверить IOPS диска. 2. Дефрагментация: `etcdctl defrag --cluster` |
| DB слишком большая | `etcdctl endpoint status --cluster -w table` | 1. Compaction: `etcdctl compact $(etcdctl endpoint status -w json \| jq '.[0].Status.header.revision')`. 2. Defrag |
| etcd не запускается после рестарта | `journalctl -u etcd -f` | 1. Проверить права доступа на `/var/lib/etcd`. 2. Проверить сертификаты |

### Проблемы с сертификатами

| Симптом | Диагностика | Решение |
| :--- | :--- | :--- |
| `x509: certificate has expired` | `kubeadm certs check-expiration` | Ротация сертификатов. См. раздел 4 |
| API-сервер не стартует из-за сертификатов | `journalctl -u kube-apiserver -f` | Проверить `/etc/kubernetes/pki/`, пересоздать при необходимости |
| kubelet не может подключиться к API | `kubectl describe node <node>` | Ротация kubelet-сертификата: `kubeadm certs renew kubelet` |

### Проблемы с DNS

| Симптом | Диагностика | Решение |
| :--- | :--- | :--- |
| Поды не резолвят имена | `kubectl run test --image=busybox --rm -it -- nslookup kubernetes.default` | 1. Проверить CoreDNS: `kubectl get pods -n kube-system -l k8s-app=kube-dns`. 2. Проверить `/etc/resolv.conf` на узлах |
| CoreDNS в CrashLoopBackOff | `kubectl logs -n kube-system -l k8s-app=kube-dns` | 1. Проверить конфигурацию Corefile. 2. Проверить CNI-плагин |

### Проблемы с HAProxy

| Симптом | Диагностика | Решение |
| :--- | :--- | :--- |
| 503 Service Unavailable | `curl -k https://localhost:6443/healthz` — работает ли локально? | 1. Проверить `haproxy.cfg`. 2. Проверить порты бэкендов |
| HAProxy не запускается | `systemctl status haproxy` | 1. Проверить конфигурацию: `haproxy -c -f /etc/haproxy/haproxy.cfg`. 2. Проверить порт 6443 не занят |
| Медленные ответы через VIP | `time curl -sk https://<VIP>:6443/healthz` | 1. Проверить балансировку: `echo "show stat" \| socat stdio /var/run/haproxy/admin.sock`. 2. Проверить сеть между HAProxy и мастерами |

---

## Дополнительная информация

### См. также

- [Основные концепции HA Kubespray](./kubespray_ha_concepts.md) — теория и схемы сетевых потоков.
- [Практика развертывания HA](./kubespray_ha_deployment.md) — пошаговая настройка инвентаря.
- [Обновление и масштабирование](../cluster_management.md) — плейбуки жизненного цикла (upgrade, scale, remove).
- [etcd: Обзор и операции](../../Concepts/etcd_overview.md) — архитектура, MVCC, компакция.
- [Кластеризация и восстановление etcd](../../../../etcd/clustering_and_recovery.md) — процедуры аварийного восстановления.
- [Обслуживание узлов](../../../Operations/node_maintenance.md) — регламент работ на узлах.

### Внешние ресурсы

- [kube-vip Documentation](https://kube-vip.io/) — официальная документация.
- [Keepalived User Guide](https://www.keepalived.org/doc/index.html) — руководство Keepalived.
- [HAProxy Configuration Manual](https://docs.haproxy.org/2.8/configuration.html) — справочник HAProxy.
- [Kubeadm: Certificate Management](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/) — управление сертификатами.
- [etcd Operations Guide](https://etcd.io/docs/v3.5/op-guide/) — операционный справочник etcd.
