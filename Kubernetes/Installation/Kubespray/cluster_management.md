# Kubespray: Управление кластером

## Определения

**Управление кластером (Cluster Management)** — комплекс операций по изменению жизненного цикла существующего кластера Kubernetes: масштабирование, обновление версий, ротация сертификатов и вывод узлов из эксплуатации.

**Масштабирование (Scaling)** — изменение количества узлов. В Kubespray разделяется на добавление рабочих узлов (Workers) и узлов управления (Control Plane/etcd). Операции выполняются через специализированные плейбуки, которые автоматизируют добавление узла в инвентарь, установку компонентов и перенастройку кластера.

**Обновление (Upgrade)** — переход на новую версию Kubernetes. В Kubespray выполняется как автоматизированный rolling update: последовательное обновление Control Plane (по одному узлу) с последующим обновлением Worker-узлов. Поддерживается обновление только на одну минорную версию за раз (v1.34 → v1.35, но не v1.33 → v1.35).

**Ротация сертификатов (Certificate Rotation)** — плановая замена TLS-сертификатов компонентов кластера до истечения их срока действия. В Kubespray реализована через тег `--tags=certificates` плейбука `cluster.yml`. Сертификаты компонентов Control Plane действуют 1 год, корневой CA — 10 лет.

**Rollback** — откат кластера на предыдущую работоспособную конфигурацию после неудачного обновления или изменения. В Kubespray полный откат версии Kubernetes через плейбук не поддерживается; единственная стратегия — восстановление etcd из снапшота и/или чистая переустановка с предыдущей версией Kubespray.

---

## Основные концепции

### Плейбуки жизненного цикла

После первичного развертывания для управления кластером используются специализированные сценарии:

| Плейбук | Назначение | Важные флаги |
| :--- | :--- | :--- |
| **`scale.yml`** | Добавление новых рабочих узлов (Workers). | `--limit=<node>` (ускорение на целевом узле) |
| **`cluster.yml`** | Полная перенастройка, добавление Control Plane / etcd, ротация сертификатов. | `--tags=certificates`, `--tags=etcd`, `--tags=addons` |
| **`upgrade-cluster.yml`** | Последовательное обновление всех компонентов (etcd, runtime, K8s). | Требует изменения `kube_version` в переменных |
| **`remove-node.yml`** | Безопасный вывод узла: `kubectl drain`, удаление из API, очистка конфигурации и остановка сервисов. | `-e node=<name>` |
| **`reset.yml`** | Полная очистка узлов от компонентов Kubernetes. **Внимание:** все данные будут удалены. | `--limit=<node>` (только на конкретном узле) |
| **`facts.yml`** | Сбор актуальных данных о состоянии узлов (метаданные, версии, сетевые интерфейсы). | Используется для диагностики |

### Правила и ограничения обновлений

1.  **Минорные версии:** поддерживается обновление только на одну минорную версию за раз (например, v1.34 → v1.35). Прямой переход v1.33 → v1.35 не поддерживается и может привести к ошибкам в схемах API.
2.  **Состояние кластера:** перед началом любых операций все узлы должны быть в статусе `Ready`. Узлы в состоянии `NotReady` или `Unknown` указывают на проблемы, которые необходимо устранить до обновления.
3.  **Кворум etcd:** обновление или добавление мастер-узлов критически зависит от доступности etcd. Рекомендуется иметь нечетное количество узлов etcd (3, 5). Потеря кворума делает кластер read-only.
4.  **Версия Kubespray:** целевая версия Kubespray должна соответствовать нужной версии Kubernetes. Используйте ветку `branch-2.XX` для нужной минорной версии K8s.

### Выбор операции

Перед выполнением операции определите, какой сценарий соответствует вашей задаче:

| Задача | Операция | Плейбук | Ссылка |
| :--- | :--- | :--- | :--- |
| Добавить Worker-узлы | Масштабирование | `scale.yml` | [Сценарий 1](#1-масштабирование-кластера) |
| Добавить Control Plane / etcd | Масштабирование Control Plane | `cluster.yml` | [Сценарий 1.2](#12-добавление-узлов-управления-control-plane) |
| Обновить версию Kubernetes | Обновление | `upgrade-cluster.yml` | [Сценарий 3](#3-обновление-версии-kubernetes) |
| Вывести узел из эксплуатации | Удаление | `remove-node.yml` | [Сценарий 2](#2-удаление-узла) |
| Ротировать сертификаты | Ротация | `cluster.yml --tags=certificates` | [Сценарий 4](#4-ротация-сертификатов) |
| Очистить узлы для переиспользования | Сброс | `reset.yml` | [Сценарий 5](#5-полный-сброс-reset) |
| Проверить здоровье кластера | Диагностика | `kubectl` + `etcdctl` | [Диагностика](#диагностика-и-обслуживание) |

---

## Практические сценарии

### 1. Масштабирование кластера

#### 1.1 Добавление рабочих узлов (Worker Nodes)

Добавление Worker-узла — наиболее безопасная операция масштабирования: новый узел не влияет на работоспособность существующих компонентов.

**Предусловия:**
- Новый узел доступен по SSH с ключами Control Node.
- Установлен Python 3 на новом узле.
- Инвентарь кластера доступен на Control Node.

**Пошаговая инструкция:**

1.  **Добавьте хост в инвентарь:**
    ```yaml
    # inventory/mycluster/hosts.yaml
    all:
      hosts:
        new-worker:                # Имя узла
          ansible_host: 10.128.0.14  # IP-адрес
          ansible_user: user
    children:
      kube_node:
        hosts:
          new-worker:              # ← добавьте сюда
    ```

2.  **Проверьте SSH-доступ к новому узлу:**
    ```bash
    ansible new-worker -i inventory/mycluster/hosts.yaml -m ping --become
    # → new-worker | SUCCESS => { "changed": false, "ping": "pong" }
    ```

3.  **Запустите масштабирование с `--limit`:**
    ```bash
    ansible-playbook -i inventory/mycluster/hosts.yaml --become \
      scale.yml --limit=new-worker
    ```
    Флаг `--limit` ограничивает выполнение только целевым узлом, что значительно ускоряет процесс (не затрагивает остальные узлы).

4.  **Проверьте результат:**
    ```bash
    kubectl get nodes -o wide
    # → NAME         STATUS   ROLES           AGE     VERSION   INTERNAL-IP
    # → new-worker   Ready    <none>          2m      v1.35.4   10.128.0.14
    ```

#### 1.2 Добавление узлов управления (Control Plane)

Добавление мастер-узла — критическая операция, затрагивающая кворум etcd и конфигурацию API-сервера. **`--limit` не рекомендуется** — изменения должны применяться ко всем узлам одновременно для корректного обновления конфигурации.

**Предусловия:**
- Кластер работает стабильно (все узлы `Ready`).
- Кворум etcd здоров.
- Новый узел добавлен в группы `kube_control_plane` и `etcd`.

**Пошаговая инструкция:**

1.  **Проверьте здоровье кластера:**
    ```bash
    kubectl get nodes
    kubectl exec -n kube-system etcd-<master-1> -- \
      etcdctl endpoint health --cluster -w table
    ```

2.  **Добавьте хост в инвентарь:**
    ```yaml
    # inventory/mycluster/hosts.yaml
    all:
      hosts:
        new-master:
          ansible_host: 10.128.0.15
          ansible_user: user
    children:
      kube_control_plane:
        hosts:
          new-master:              # ← добавьте сюда
      etcd:
        hosts:
          new-master:              # ← добавьте сюда (для stacked etcd)
    ```

3.  **Запустите кластер без `--limit`:**
    ```bash
    ansible-playbook -i inventory/mycluster/hosts.yaml --become cluster.yml
    ```
    > [!IMPORTANT]
    > Использование `--limit` при добавлении Control Plane приведет к нарушению кворума etcd и некорректной настройке сертификатов. Kubespray должен обновить конфигурацию HAProxy/kube-vip на всех узлах одновременно.

4.  **Проверьте результат:**
    ```bash
    kubectl get nodes
    # → NAME         STATUS   ROLES           AGE     VERSION
    # → master-1     Ready    control-plane   30d     v1.35.4
    # → new-master   Ready    control-plane   2m      v1.35.4

    kubectl exec -n kube-system etcd-master-1 -- \
      etcdctl member list -w table
    # → ... новый узел должен появиться в списке членов etcd
    ```

#### 1.3 Ускорение масштабирования через `--limit`

Флаг `--limit` применяется для всех операций, где нужно затронуть только конкретный узел:

```bash
# Только масштабирование Worker
ansible-playbook ... scale.yml --limit=new-worker

# Только обновление конкретного Worker (через upgrade-cluster.yml)
ansible-playbook ... upgrade-cluster.yml --limit=worker-2

# Только сброс конкретного узла
ansible-playbook ... reset.yml --limit=old-worker
```

> [!WARNING]
> Не используйте `--limit` при:
> - Добавлении Control Plane / etcd узлов (требуется обновление на всех узлах).
> - Обновлении версии Kubernetes (rolling update должен пройти последовательно).
> - Ротации сертификатов (сертификаты должны быть обновлены на всех Control Plane узлах).

---

### 2. Удаление узла

Плейбук `remove-node.yml` выполняет безопасный вывод узла из эксплуатации:

1.  `kubectl drain` — выселение подов с узла (с учетом PodDisruptionBudget).
2.  Удаление узла из Kubernetes API (`kubectl delete node`).
3.  Очистка локальных данных (конфигурация kubelet, сертификаты).
4.  Остановка системных сервисов (kubelet, containerd).

#### Удаление Worker-узла

```bash
# 1. Убедитесь, что кластер здоров
kubectl get nodes

# 2. Запустите удаление
ansible-playbook -i inventory/mycluster/hosts.yaml --become \
  remove-node.yml -e node=worker-2

# 3. Удалите узел из инвентаря (hosts.yaml)
# Уберите запись из группы kube_node

# 4. Проверьте результат
kubectl get nodes
# → worker-2 отсутствует в списке
```

#### Удаление Control Plane / etcd узла

> [!IMPORTANT]
> Удаление мастер-узла из кластера требует особого внимания:
> - Количество узлов etcd должно оставаться нечетным (3, 5).
> - Если у вас было 3 узла etcd и вы удаляете один — кластер потеряет отказоустойчивость (кворум = 2 из 2 — нет容错).
> - Сначала добавьте новый узел, затем удалите старый (swap, а не удаление).

```bash
# 1. Проверьте здоровье кластера и кворум
kubectl get nodes
kubectl exec -n kube-system etcd-master-1 -- \
  etcdctl endpoint status --cluster -w table

# 2. Удалите узел из инвентаря (kube_control_plane и etcd)

# 3. Запустите удаление
ansible-playbook -i inventory/mycluster/hosts.yaml --become \
  remove-node.yml -e node=master-3

# 4. Проверьте кворум etcd после удаления
kubectl exec -n kube-system etcd-master-1 -- \
  etcdctl member list -w table
# → Количество членов должно уменьшиться на 1
```

---

### 3. Обновление версии Kubernetes

Обновление через Kubespray — последовательный процесс, затрагивающий все компоненты кластера. Kubespray автоматизирует обновление в правильном порядке: сначала Control Plane (по одному узлу), затем Worker-узлы.

#### 3.1 Подготовка к обновлению

1.  **Создайте бэкап etcd:**
    ```bash
    sudo ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-pre-upgrade-$(date +%Y%m%d).db \
      --endpoints=https://127.0.0.1:2379 \
      --cacert=/etc/kubernetes/pki/etcd/ca.crt \
      --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
      --key=/etc/kubernetes/pki/etcd/healthcheck-client.key
    ```

2.  **Проверьте здоровье кластера:**
    ```bash
    # Все узлы Ready?
    kubectl get nodes

    # etcd здоров?
    kubectl exec -n kube-system etcd-master-1 -- \
      etcdctl endpoint health --cluster

    # Нет pending-подов?
    kubectl get pods -A | grep -E "Pending|CrashLoop"
    ```

3.  **Проверьте место на диске:**
    ```bash
    # На всех узлах (min 2GB свободных)
    df -h /var/lib/kubelet /var/lib/etcd
    ```

4.  **Обновите репозиторий Kubespray:**
    ```bash
    git fetch origin
    git checkout v2.31.0  # целевая версия для нужной версии K8s
    pip install -r requirements.txt  # обновите зависимости Ansible
    ```

5.  **Проверьте доступные версии:**
    ```bash
    kubeadm upgrade plan
    # → Shows the difference between target and current version
    ```

#### 3.2 Выполнение обновления

1.  **Укажите целевую версию:**
    ```yaml
    # inventory/mycluster/group_vars/k8s_cluster/k8s-cluster.yml
    kube_version: v1.35.4
    ```

2.  **Запустите обновление:**
    ```bash
    ansible-playbook -i inventory/mycluster/hosts.yaml --become \
      upgrade-cluster.yml
    ```
    Процесс обновления:
    - Kubespray обновляет etcd (если используется встроенная топология).
    - Последовательно обновляет Control Plane узлы (по одному).
    - Обновляет Worker-узлы (rolling update).
    - Продлевает сертификаты автоматически.

#### 3.3 Проверка после обновления

```bash
# Все узлы в статусе Ready?
kubectl get nodes -o wide

# Версия обновилась?
kubectl version --short
# → Server Version: v1.35.4

# etcd здоров?
kubectl exec -n kube-system etcd-master-1 -- \
  etcdctl endpoint health --cluster

# Все поды в kube-system запущены?
kubectl get pods -n kube-system -o wide | grep -v Running

# Приложения работают?
kubectl get pods -A --field-selector=status.phase!=Running
```

#### 3.4 Откат при неудачном обновлении

> [!IMPORTANT]
> Kubespray не поддерживает автоматический откат версии Kubernetes. `kubeadm` не имеет команды rollback. Единственные стратегии отката:

**Стратегия 1: Восстановление etcd из снапшота (рекомендуется)**

Если бэкап etcd создан перед обновлением, восстановите состояние кластера:

```bash
# На всех Control Plane узлах
sudo systemctl stop kube-apiserver etcd

# Восстановите данные
sudo ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd-pre-upgrade-$(date +%Y%m%d).db \
  --data-dir=/var/lib/etcd-restored \
  --name=<etcd-member-name> \
  --initial-cluster=<etcd-member1>=https://<ip1>:2380,... \
  --initial-advertise-peer-urls=https://<ip>:2380

# Обновите конфигурацию etcd на восстановленных данных
# Запустите etcd и API-сервер
sudo systemctl start etcd kube-apiserver
```

**Стратегия 2: Чистая переустановка**

Если восстановление etcd невозможно:
1. Выполните `reset.yml` на всех узлах.
2. Используйте предыдущую версию Kubespray (ветка с нужной версией K8s).
3. Запустите `cluster.yml`.

> [!NOTE]
> Детальная методология отката описана в **[Обновлении кластера](../../Operations/upgrading_clusters.md)**.

---

### 4. Ротация сертификатов

Если сертификаты истекают или скомпрометированы, их можно обновить без полного апгрейда кластера.

#### Плановая ротация через теги

```bash
# Ротация всех сертификатов + kubeadm-конфигурации
ansible-playbook -i inventory/mycluster/hosts.yaml --become \
  cluster.yml --tags=certificates,kubeadm
```

#### Ротация только сертификатов etcd

```bash
ansible-playbook -i inventory/mycluster/hosts.yaml --become \
  cluster.yml --tags=etcd
```

#### Проверка срока действия

```bash
# На любом Control Plane узле
sudo kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME   ...
# → admin.conf                 Dec 30, 2026 23:59 UTC   364d
# → apiserver                  Dec 30, 2026 23:59 UTC   364d
# → apiserver-kubelet-client   Dec 30, 2026 23:59 UTC   364d
```

> [!NOTE]
> При обновлении Kubernetes через `upgrade-cluster.yml` сертификаты продлеваются автоматически. Ручная ротация нужна только между обновлениями версий. Детали — в **[Управлении сертификатами](../../Operations/certificate_management.md)**.

---

### 5. Полный сброс (Reset)

Используется для очистки узлов перед переиспользованием или аварийным восстановлением.

```bash
# Сброс всех узлов
ansible-playbook -i inventory/mycluster/hosts.yaml --become reset.yml

# Сброс только конкретного узла
ansible-playbook -i inventory/mycluster/hosts.yaml --become reset.yml --limit=old-worker
```

> [!WARNING]
> `reset.yml` удаляет ВСЕ данные: поды, PersistentVolume, конфигурацию kubelet, сертификаты, сетевые правила. Используйте только на узлах, которые планируется переиспользовать. На production-кластерах без понимания последствий **не запускайте**.

---

## Диагностика и обслуживание

### Проверка состояния кластера перед операциями

Перед любой операцией (масштабирование, обновление, удаление) убедитесь в работоспособности кластера:

```bash
# 1. Статус узлов
kubectl get nodes -o wide
# → Все узлы должны быть Ready

# 2. Системные поды
kubectl get pods -n kube-system -o wide
# → Все поды в Running (кроме Pending обновлений)

# 3. Kubelet и containerd
sudo systemctl status kubelet containerd
# → active (running) на каждом узле

# 4. Кворум etcd
kubectl exec -n kube-system etcd-master-1 -- \
  etcdctl endpoint status --cluster -w table
# → IS LEADER = true на одном узле, RAFT TERM одинаковый

# 5. API-сервер
curl -sk https://localhost:6443/healthz
# → ok
```

### Типовые проблемы при масштабировании

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Новый Worker не переходит в `Ready` | kubelet не запущен или CNI не установлен | `ssh new-worker && sudo journalctl -u kubelet -f` |
| Ошибка `etcd cluster is unavailable` | Нет кворума etcd | Проверьте `etcdctl member list` и健康的 все ли узлы etcd |
| Pod на новом узле в `ContainerCreating` | CNI не может подключиться | Проверьте CNI-плагин: `kubectl get pods -n kube-system -l k8s-app=calico-node` |
| `unreachable` при `ansible ping` | Нет SSH-доступа или Python | Проверьте SSH: `ssh user@new-host`. Установите Python: `sudo apt install python3` |

### Типовые проблемы при обновлении

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `upgrade-cluster.yml` зависает на Control Plane | etcd не отвечает или сертификаты истекли | Проверьте etcd: `etcdctl endpoint health --cluster`. Обновите сертификаты вручную: `kubeadm certs renew all` |
| Worker не переходит в `Ready` после обновления | kubelet не смог подключиться к API | `ssh worker && sudo journalctl -u kubelet -f` → проверьте TLS-сертификаты |
| Поды `CrashLoopBackOff` после обновления | Несовместимость версий API | Проверьте `kubectl describe pod <name>` → Events. Используйте `kubent` для поиска deprecated API |
| etcd потерял кворум после обновления | Сетевой сбой или disk pressure | `etcdctl member list` → восстановление из снапшота |

### Ручные операции (kubectl)

При необходимости ручного обслуживания узла используйте последовательность `cordon → drain → работы → uncordon`:

```bash
# 1. Изоляция узла (планировщик не ставит новые поды)
kubectl cordon <node>

# 2. Выселение существующих подов (с уважением к PDB)
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=300s

# 3. Проведение работ на узле (обновление, ремонт, перезагрузка и т.д.)

# 4. Возврат узла в планировщик
kubectl uncordon <node>
```

> [!NOTE]
> Детальный разбор флагов `kubectl drain`, взаимодействие с PDB и NodeMaintenance API — в **[Обслуживании узлов](../../Operations/node_maintenance.md)**.

---

## Дополнительная информация

### См. также
- **[Обновление кластера: методология](../../Operations/upgrading_clusters.md)** — Version Skew Policy, аудит deprecated API, порядок обновления компонентов.
- **[Обслуживание узлов](../../Operations/node_maintenance.md)** — детальный разбор `cordon`/`drain`/`uncordon`, PDB, NodeMaintenance API.

### Внешние ресурсы
- [Kubespray: Upgrading Kubernetes](https://kubespray.io/#/docs/upgrades) — официальное руководство по обновлению.
- [Kubeadm: Certificate Management](https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/) — подробности PKI.
