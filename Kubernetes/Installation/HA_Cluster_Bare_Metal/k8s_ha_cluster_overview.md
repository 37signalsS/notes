# Высокая доступность Kubernetes на Bare-Metal: Обзор

## Определения

**Bare-Metal** — физические серверы без слоя виртуализации. Обеспечивают максимальную производительность и прямой доступ к ресурсам, но требуют автономного управления жизненным циклом (IPMI, PXE) и обработки отказов на уровне ОС.

**kubeadm** — стандартная утилита для развертывания кластеров Kubernetes. В 2026 году (v1.35+) поддерживает расширенные функции жизненного цикла, включая автоматическую ротацию сертификатов и интеграцию с внешними etcd. Подробнее: [Индекс kubeadm](../kubeadm/index.md).

**containerd** — индустриальный стандарт среды выполнения контейнеров. В современных инсталляциях используется с поддержкой плагинов для расширенной изоляции (например, gVisor или Kata Containers через RuntimeClass).

**Высокая доступность (High-Availability, HA)** — архитектурный подход, исключающий единую точку отказа (SPoF). Для Kubernetes это означает наличие 3+ узлов Control Plane и отказоустойчивой точки входа (Endpoint). Базовые принципы: [Обзор HA](../../../Concepts/High_Availability/ha_overview.md).

**Control Plane Endpoint** — виртуальный адрес (VIP) или DNS-имя, которое всегда указывает на доступные экземпляры API-сервера.

**SPOF (Single Point of Failure)** — единая точка отказа, компонент, выход из строя которого приводит к недоступности всей системы. Цель HA-архитектуры — устранение всех SPOF.

**Кворум (Quorum)** — минимальное количество работоспособных узлов, необходимое для принятия решений в распределенной системе. Для etcd с N узлами кворум равен `(N/2) + 1`. Подробнее: [Обзор etcd](../../Concepts/etcd_overview.md).

**Leader Election** — механизм выбора активного экземпляра среди нескольких реплик. В Kubernetes `kube-scheduler` и `kube-controller-manager` используют его для обеспечения того, что только один экземпляр выполняет работу в любой момент времени.

**Split-Brain** — ситуация в распределенной системе, при которой из-за network partition обе части кластера считают себя главными, что может привести к порче данных. Предотвращается механизмом кворума. Подробнее: [Проблема Split-Brain и кворум](../../../Concepts/High_Availability/ha_overview.md#проблема-split-brain-и-кворум).

---

## Основные концепции

### Архитектура HA кластера

Для bare-metal наиболее распространена схема **Stacked Control Plane**, где база данных `etcd` работает на тех же узлах, что и управляющие компоненты. Альтернатива — **External etcd** с выделенными узлами для базы данных.

#### Ключевые компоненты отказоустойчивости

1.  **Балансировка нагрузки API (L4 Load Balancer)**
    - **Классический подход**: Связка `Keepalived` (для VIP) и `HAProxy` (для балансировки на порт 6443).
    - **Современный подход**: [**kube-vip**](../kubeadm/ha_concepts.md#альтернатива-kube-vip) — cloud-native решение, работающее как Static Pod. Оно управляет VIP и может анонсировать маршруты через BGP.
    - **Локальная балансировка**: `kube-proxy` или `node-local-dns` на worker-узлах могут работать в паре с локальным балансировщиком для снижения нагрузки на центральный VIP.
    - **Назначение**: Обеспечить единую точку входа (VIP), которая всегда указывает на работающий API-сервер. Без балансировщика отказ одного мастера сделает API недоступным для клиентов.

2.  **Плоскость управления (Control Plane Nodes)**
    - Минимум **3 узла** для обеспечения кворума etcd.
    - **Статус компонентов**: `kube-apiserver` является stateless-компонентом, тогда как `kube-scheduler` и `kube-controller-manager` используют механизм выбора лидера (Leader Election).
    - **Требования к etcd**: Критически важна низкая задержка дисковой подсистемы (рекомендуется NVMe) и стабильность сети между мастерами (Latency < 10ms).
    - **Почему нечетное число узлов**: Кластер из N узлов и кластер из N+1 (четный) узлов имеют одинаковую отказоустойчивость, но четный кластер требует больше ресурсов. При четном числе существует риск раскола на две равные половины без возможности формирования кворума.

3.  **Сетевая связность (CNI)**
    - В HA-средах CNI должен поддерживать отказоустойчивость путей передачи трафика. [Calico](../cni_installation.md) часто выбирается за счет поддержки BGP-пиринга с физическим оборудованием.
    - **Требования к сети**: Низкие задержки между узлами, отсутствие единой точки отказа на сетевом уровне (резервированные коммутаторы, несколько сетевых интерфейсов).

### Механизм кворума и выбор лидера

**Почему кворум критичен:**

etcd использует консенсус-алгоритм Raft. Любая операция записи должна быть подтверждена большинством узлов (кворумом). Без кворума:
- etcd переходит в режим только чтения
- Новые поды не могут быть созданы
- Конфигурация кластера не может быть изменена
- Существующие рабочие нагрузки продолжают выполняться

**Формула кворума:** `Q = (N / 2) + 1`, где N — общее число узлов.

**Допустимые отказы:** `F = (N - 1) / 2`

| Узлов | Кворум | Допустимые отказы | Рекомендация |
| :--- | :--- | :--- | :--- |
| 3 | 2 | 1 | Стандарт для Production |
| 5 | 3 | 2 | Крупные кластеры с повышенными требованиями |
| 7 | 4 | 3 | Максимум (далее растет задержка репликации) |

**Leader Election для scheduler и controller-manager:**

В отличие от etcd, где лидер выбирается через Raft, `kube-scheduler` и `kube-controller-manager` используют lease-объекты в API-сервере:
- Активный экземпляр периодически обновляет lease
- При падении лидера lease истекает через `leaseDurationSeconds` (обычно 15 секунд)
- Остальные экпемпляры проводят выборы нового лидера
- Это гарантирует, что только один экземпляр выполняет работу (например, назначает поды)

**Практическое следствие:** При потере кворума etcd лидерство scheduler/controller-manager также будет потеряно, так как они не могут обновить lease.

### Проблема Split-Brain и защита

**Сценарий Network Partition:**
1. Сеть разделяет кластер на две части
2. Обе части обнаруживают недоступность другой
3. Без механизма кворума обе части могли бы продолжить работу независимо

**Решение через кворум:**
- Только та часть, которая видит большинство узлов (кворум), продолжает обслуживание
- Меньшинство прекращает принимать записи (read-only mode)
- Это предотвращает рассинхронизацию данных

**Практическая рекомендация:** Для критичных сред используйте 5 узлов вместо 3 — это позволяет пережить отказ двух узлов или network partition с сохранением кворума.

### CAP-теорема и компромиссы Kubernetes

Kubernetes etcd выбирает **CP** (Consistency + Partition Tolerance):
- **Consistency (Согласованность)**: Все узлы видят одинаковые данные
- **Partition Tolerance (Устойчивость к разделению)**: Кластер продолжает работу при network partition (при наличии кворума)
- **Availability (Доступность)**: Жертвуется — при потере кворума API становится read-only

**Почему не AP:** Для оркестратора консистентность данных важнее доступности. Два разных планировщика, назначающих поды на один узел, создадут неконсистентное состояние.

### Топологии размещения etcd

| Характеристика | Stacked etcd (Совмещенный) | External etcd (Выделенный) |
| :--- | :--- | :--- |
| **Ресурсы** | Экономия серверов (мин. 3) | Требует больше железа (мин. 3+3) |
| **Изоляция** | API и etcd делят CPU/RAM/Disk | Полная изоляция ресурсов |
| **Сложность** | Настраивается через `kubeadm` автоматически | Требует отдельного управления сертификатами |
| **Масштабируемость** | Ограничена ресурсами узла | Позволяет масштабировать etcd независимо |
| **Отказоустойчивость** | Падение узла выбивает и API, и etcd | Изолирование отказов |

Подробнее: [Сценарии etcd](../../Concepts/etcd_overview.md), [Архитектура Control Plane](../../Concepts/control_plane_architecture.md).

---

## Практические сценарии

### Жизненный цикл развёртывания HA кластера

Процесс состоит из последовательных фаз, каждая из которых описана в детальных руководствах:

1.  **Окружение**: Проверка соответствия [аппаратным и программным требованиям](./k8s_ha_environment_requirements.md).
2.  **Подготовка**: Настройка параметров ядра, модулей и `/etc/hosts` на [всех узлах](./k8s_ha_node_preparation.md).
3.  **Компоненты**: Установка Runtime (`containerd`) и утилит Kubernetes на [каждый сервер](./k8s_ha_component_installation.md).
4.  **Load Balancer**: Развертывание [Keepalived + HAProxy](../kubeadm/keepalived_haproxy_setup.md) или [kube-vip](../kubeadm/ha_concepts.md#альтернатива-kube-vip).
5.  **Bootstrap**: [Инициализация первого мастера](../kubeadm/cluster_initialization.md) с флагом `--control-plane-endpoint`.
6.  **Сетевой плагин**: Установка и настройка [CNI (Calico)](./cni_installation.md).
7.  **Масштабирование CP**: [Присоединение остальных мастеров](./node_joining.md) через `join --control-plane`.
8. **Worker Nodes**: Присоединение рабочих узлов и [финальная верификация](./k8s_ha_cluster_verification.md).
9. **Day-2**: [Эксплуатация и обслуживание](./k8s_ha_bare_metal_day2_operations.md) -- внешний доступ, мониторинг, обновления, бэкапы.

### Сценарий: Самовосстановление при отказе мастера

1.  **Детекция**: Балансировщик (или Keepalived) фиксирует недоступность узла через health-check (обычно < 5 секунд).
2.  **Failover**: VIP переходит на исправный узел. Новые запросы к API направляются на работающие бэкенды.
3.  **Кворум**: etcd продолжает работу в режиме Read/Write (2 из 3 узлов доступны).
4.  **Worker Response**: `kubelet` на воркерах может кратковременно потерять связь, но поды продолжают работать (если не используется короткий Grace Period для Node Lease).
5.  **Восстановление лидерства**: После возвращения узла в строй, `kube-scheduler` и `kube-controller-manager` автоматически проводят выборы лидера.

### Сценарий: Плановое обслуживание узла (Drain)

Для безопасного вывода мастера из кластера на время обслуживания:

```bash
# 1. Пометить узел как недоступный для планирования
kubectl drain <master-node-name> --ignore-daemonsets --delete-emptydir-data

# 2. Проверить, что поды мигрировали
kubectl get pods -A -o wide --field-selector spec.nodeName=<master-node-name>
# → Должен остаться только DaemonSet (kube-proxy, CNI)

# 3. После обслуживания — вернуть узел в строй
kubectl uncordon <master-node-name>

# 4. Проверить статус
kubectl get nodes
# → <master-node-name> Ready
```

**Важно:** Drain НЕ удаляет статические поды Control Plane (etcd, apiserver) — они управляются напрямую kubelet через манифесты в `/etc/kubernetes/manifests/`.

### Сценарий: Тестирование отказоустойчивости (GameDay)

Регулярное тестирование HA обязательно — система, не протестированная на отказ, считается неработающей.

```bash
# 1. Запустить непрерывный мониторинг API
while true; do kubectl get nodes > /dev/null && echo -n "." || echo -n "X"; sleep 1; done

# 2. Имитировать отказ мастера (на одном из master-узлов)
sudo systemctl stop kubelet
# Или остановить etcd:
sudo crictl stop $(crictl ps --name etcd -q)

# 3. Наблюдать за поведением:
# - VIP должен мигрировать в течение 5-10 секунд
# - Допускается 1-3 "X" подряд (потеря 连接)
# - Затем точки "." должны возобновиться

# 4. Восстановить узел
sudo systemctl start kubelet

# 5. Проверить, что кластер вернулся в исходное состояние
kubectl get nodes
kubectl get pods -n kube-system -o wide
```

**Метрики для оценки:**
- **RTO (Recovery Time Objective)**: Время до восстановления API-доступности (цель: < 30 секунд)
- **RPO (Recovery Point Objective)**: Потеря данных (для etcd с синхронной репликацией: 0)

### Сценарий: Добавление нового мастера в существующий HA кластер

```bash
# 1. На существующем мастере сгенерировать токен и хеш CA
sudo kubeadm token create --print-join-command
openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | openssl rsa -pubin -outform der 2>/dev/null | openssl dgst -sha256 -hex | sed 's/^.* //'

# 2. На новом узле выполнить join с флагами для Control Plane
sudo kubeadm join <VIP>:6443 --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane --certificate-key <certificate-key>

# 3. Проверить, что узел присоединился
kubectl get nodes
# → Новый узел в статусе Ready с ролью control-plane

# 4. Проверить кворум etcd
kubectl exec -n kube-system etcd-<master-1> -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  member list -w table
```

### Сценарий: Резервное копирование и восстановление etcd

Резервное копирование etcd — единственный способ сохранить состояние всего кластера.

```bash
# 1. Создание снапшота (выполнять на master-узле)
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /backup/etcd-$(date +%Y%m%d-%H%M%S).db

# 2. Проверка целостности снапшота
sudo etcdutl snapshot status /backup/etcd-<timestamp>.db -w table
# → Hash: 1234567890  Revision: 12345  Total Key: 6789  Total Size: 45MB

# 3. Восстановление из снапшота (при полной потере кластера)
sudo etcdutl snapshot restore /backup/etcd-<timestamp>.db \
  --data-dir=/var/lib/etcd-restored \
  --name=<node-name> \
  --initial-cluster=<node1>=https://<ip1>:2380,<node2>=https://<ip2>:2380,<node3>=https://<ip3>:2380 \
  --initial-cluster-token=etcd-cluster-1 \
  --initial-advertise-peer-urls=https://<node-ip>:2380

# 4. Запустить etcd с восстановленными данными
# (Обновить манифест /etc/kubernetes/manifests/etcd.yaml для указания нового пути)
```

**Расписание бэкапов:** Рекомендуется создавать снапшоты каждые 1-6 часов в зависимости от критичности данных. Подробнее: [Операции с etcd](../../Concepts/etcd_operations.md).

---

## Дополнительная информация

### Мониторинг и отладка HA

```bash
# 1. Проверка доступности API через Endpoint (VIP)
curl -k https://<CONTROL_PLANE_ENDPOINT>:6443/healthz

# 2. Список участников etcd и их состояние
kubectl exec -n kube-system etcd-<master-node-name> -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status --cluster -w table

# 3. Статус выбора лидера в Control Plane
kubectl get endpoints -n kube-system kube-scheduler -o jsonpath='{.metadata.annotations.control-plane\.alpha\.kubernetes\.io/leader}'

# 4. Проверка VIP (на каком узле находится)
for node in master-1 master-2 master-3; do
  echo "=== $node ==="
  ssh $node "ip a | grep <VIP>" 2>/dev/null || echo "VIP not found"
done
```

**Критические показатели здоровья:**
- `etcd_disk_wal_fsync_duration_seconds`: задержка записи в лог (должна быть < 10ms).
- `apiserver_request_duration_seconds`: время ответа API на запросы.
- `etcd_server_leader_changes_seen_total`: количество смен лидера (рост указывает на нестабильность).
- `etcd_mvcc_db_total_size_in_bytes`: размер базы данных etcd.

### Типичные проблемы и решения

| Проблема | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Потеря кворума etcd** | Отказ 2+ узлов из 3 | `etcdctl endpoint health` показывает unhealthy | Восстановить из снапшота или добавить узлы |
| **VIP не миграцирует** | Keepalived не работает или VRRP заблокирован | `journalctl -u keepalived`, `tcpdump proto vrrp` | Проверить firewall, перезапустить Keepalived |
| **Flapping VIP** | Нестабильная сеть или слишком чувствительные health checks | `journalctl -u keepalived -f` | Увеличить `fall` и `interval` в конфигурации |
| **Scheduler не назначает поды** | Потеря лидерства или недоступность API | `kubectl get lease -n kube-system kube-scheduler` | Проверить доступность etcd и API-сервера |
| **Медленные операции API** | Высокая нагрузка на etcd или медленный диск | `etcd_disk_wal_fsync_duration_seconds` > 10ms | Оптимизировать запросы, обновить диск до NVMe |

### Чек-лист готовности HA кластера к Production

**Инфраструктура:**
- [ ] Минимум 3 мастер-узла с нечетным кворумом etcd
- [ ] Балансировщик нагрузки (Keepalived+HAProxy или kube-vip) настроен и протестирован
- [ ] VIP автоматически мигрирует при отказе мастера
- [ ] Синхронизация времени (chrony) настроена на всех узлах
- [ ] DNS резолвинг между узлами работает корректно

**Данные и безопасность:**
- [ ] Снапшоты etcd создаются по расписанию и проверяются
- [ ] Сертификаты не истекают в ближайшие 90 дней

**Day-2 операции:**
- [ ] Внешний доступ настроен (MetalLB + Ingress-контроллер)
- [ ] Мониторинг и алертинг настроен (Prometheus, Grafana, ключевые алерты)
- [ ] Сбор логов настроен (Loki/EFK)
- [ ] ResourceQuota и LimitRange установлены для production namespace
- [ ] Pod Security Admission включен (baseline/restricted)
- [ ] PDB созданы для критичных сервисов
- [ ] Playbook обновления кластера подготовлен
- [ ] Документация и runbook для инцидентов актуальны

### Связанные руководства

- **Развертывание**: [Подготовка узлов](./k8s_ha_node_preparation.md), [Компоненты](./k8s_ha_component_installation.md).
- **Инициализация**: [Инициализация мастера](../kubeadm/cluster_initialization.md), [Присоединение узлов](./node_joining.md).
- **Проверка**: [Верификация HA](./k8s_ha_cluster_verification.md).
- **Инфраструктура**: [Балансировка HAProxy](../kubeadm/keepalived_haproxy_setup.md), [Концепции HA](../../../Concepts/High_Availability/ha_overview.md).
- **Альтернативы**: [HA через Kubespray](../Kubespray/HA/index.md).
- **Day-2 эксплуатация**: [Внешний доступ, мониторинг, обновления, бэкапы](./k8s_ha_bare_metal_day2_operations.md).
