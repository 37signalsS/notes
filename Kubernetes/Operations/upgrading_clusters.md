# Обновление кластера Kubernetes

## Определения

**Обновление кластера** — процесс поэтапного обновления компонентов Kubernetes до новой минорной или патч-версии с сохранением работоспособности приложений.

**Политика N-2** — Kubernetes поддерживает 3 последние минорные версии одновременно. Например, при выходе 1.35 поддерживаются 1.35, 1.34, 1.33.

**Breaking changes** — критические изменения в API или поведении компонентов, требующие модификации манифестов или конфигурации перед обновлением.

## Основные концепции

### Компоненты, затрагиваемые при обновлении

| Компонент | Описание | Требования |
| :--- | :--- | :--- |
| **etcd** | Хранилище состояния кластера | Требуется бэкап перед обновлением |
| **Control Plane** | `kube-apiserver`, `kube-controller-manager`, `kube-scheduler` | Обновляются первыми, по одному узлу |
| **Kubelet** | Агент на узлах (master и worker) | Обновляется после Control Plane |
| **Kube-proxy** | Сетевой прокси | Обновляется через DaemonSet или вручную |
| **CNI/CoreDNS** | Сетевые компоненты | Проверить совместимость версий |
| **TLS-сертификаты** | Сертификаты компонентов | Проверить срок действия — [certificate_management.md](certificate_management.md) |

### Важность актуализации версий API

Kubernetes API постоянно развивается: старые версии API объявляются устаревшими (`deprecated`) и удаляются. Использование устаревших API — главная причина сбоев.

**Ключевые риски:**

* `kubectl apply` выдаёт ошибки для манифестов с удалёнными API
* Развёртывание и обновление приложений останавливается
* Helm-чарты перестают работать

**Решение:** Провести аудит API перед обновлением и миграцию на актуальные версии.

### Поддерживаемые версии (актуально на март 2026)

| Версия | Статус | Дата EOL | Рекомендация |
| :--- | :--- | :--- | :--- |
| **1.35** | Current | 28 дек 2026 | Рекомендуемая версия |
| **1.34** | Security fixes | 27 авг 2026 | Планировать обновление на 1.35 |
| **1.33** | Security fixes | 28 апр 2026 | Срочное обновление |
| **1.32** | End of Life | 28 фев 2026 | Критическое обновление |
| **≤1.31** | End of Life | 2025 | Немедленное обновление |

> **Важно:** Всегда проверяйте [официальный график релизов](https://kubernetes.io/releases/) перед обновлением.

## Практические сценарии

### Процедура обновления (kubeadm)

#### Этап 1: Подготовка

**1. Изучение release notes:**

```bash
# Официальные release notes
# https://github.com/kubernetes/kubernetes/releases/tag/v1.35.0
```

**2. Аудит версий API:**

```bash
# Просмотр доступных API
kubectl api-resources
kubectl api-versions

# Автоматическая проверка устаревших API (kubent)
docker run --rm -v ~/.kube:/root/.kube:ro ghcr.io/doitintl/kube-no-trouble:latest --helm3
```

**3. Бэкап критических компонентов:**

```bash
# Бэкап etcd (на master-узле)
ETCDCTL_API=3 etcdctl snapshot save snapshot.db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Проверка бэкапа
ETCDCTL_API=3 etcdctl snapshot status snapshot.db --write-out=table
```

**4. Проверка текущего состояния:**

```bash
# Версия kubeadm, kubelet, kubectl
kubeadm version
kubelet --version
kubectl version

# Состояние узлов
kubectl get nodes
kubectl get pods -A --field-selector=status.phase!=Running
```

#### Этап 2: Обновление Control Plane

```bash
# 1. Обновить kubeadm
sudo apt update
sudo apt install -y kubeadm=1.35.0-00
sudo apt-mark hold kubeadm

# 2. Проверить доступные обновления
sudo kubeadm upgrade plan

# 3. Применить обновление (на первом master)
sudo kubeadm upgrade apply v1.35.0

# 4. Обновить kubelet и kubectl
sudo apt install -y kubelet=1.35.0-00 kubectl=1.35.0-00
sudo apt-mark hold kubelet kubectl

# 5. Перезапустить kubelet
sudo systemctl daemon-reload
sudo systemctl restart kubelet
```

**Обновление остальных master-узлов:**

```bash
# На каждом дополнительном master
sudo kubeadm upgrade node
sudo apt install -y kubelet=1.35.0-00 kubectl=1.35.0-00
sudo systemctl daemon-reload
sudo systemctl restart kubelet
```

#### Этап 3: Обновление worker-узлов

```bash
# На каждом worker-узле по очереди:

# 1. Дренаж узла
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# 2. Обновить kubeadm
sudo apt update
sudo apt install -y kubeadm=1.35.0-00

# 3. Обновить узел
sudo kubeadm upgrade node

# 4. Обновить kubelet и kubectl
sudo apt install -y kubelet=1.35.0-00 kubectl=1.35.0-00
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# 5. Вернуть узел в кластер
kubectl uncordon <node-name>
```

#### Этап 4: Проверка

```bash
# Версия компонентов
kubectl version
kubectl get nodes

# Состояние подов
kubectl get pods -A

# Проверка сертификатов
sudo kubeadm certs check-expiration
```

### Обновление через Kubespray

```bash
# 1. Клонировать репозиторий нужной версии
git clone https://github.com/kubernetes-sigs/kubespray.git
cd kubespray
git checkout release-2.26  # версия для K8s 1.35

# 2. Установить зависимости
pip install -r requirements.txt

# 3. Обновить inventory (указать target version)
# В inventory/my_cluster/group_vars/k8s_cluster/k8s-cluster.yml:
# kube_version: "v1.35.0"

# 4. Запустить playbook
ansible-playbook -i inventory/my_cluster/inventory.ini \
  cluster.yml \
  --become \
  -e "upgrade_cluster_setup=true"
```

### Troubleshooting

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **Node NotReady** | `kubectl describe node <node>` | Проверить kubelet, сертификаты |
| **Pod CrashLoopBackOff** | `kubectl logs <pod>`, `kubectl describe pod <pod>` | Проверить совместимость API |
| **API server недоступен** | `curl -k https://localhost:6443/healthz` | Проверить логи `docker ps \| grep apiserver` |
| **etcd connection refused** | `etcdctl endpoint health` | Проверить сертификаты etcd |
| **CNI не работает** | `kubectl get pods -n kube-system \| grep -i cni` | Обновить CNI плагин |

## Дополнительная информация

### Best Practices

| Практика | Описание |
| :--- | :--- |
| **Не пропускать версии** | Обновляться последовательно: 1.33 → 1.34 → 1.35 |
| **Тестировать на staging** | Полный цикл обновления на не-production |
| **Один узел за раз** | Сохранять доступность кластера |
| **Мониторить метрики** | API server latency, etcd latency, pod restarts |
| **Бэкап etcd** | Перед каждым этапом обновления |
| **Проверять сертификаты** | [certificate_management.md](certificate_management.md) |

### Автоматизация

| Инструмент | Назначение |
| :--- | :--- |
| **kubeadm** | Стандартное обновление для kubeadm-кластеров |
| **Kubespray** | Ansible-автоматизация для bare-metal |
| **Cluster API** | Декларативное обновление через CRD |
| **Rancher** | GUI для обновления управляемых кластеров |

### Связанные темы

* [Управление сертификатами](certificate_management.md) — проверка и обновление TLS при обновлении
* [Обслуживание узлов](node_maintenance.md) — Cordon и Drain при обновлении узлов
* [Kubeconfig](kubeconfig_and_connection.md) — доступ к обновлённому кластеру
* [Kubespray: Cluster Management](../Installation/Kubespray/cluster_management.md) — обновление через Kubespray
* [RKE: Управление](../Installation/RKE/rke_management_scenarios.md) — обновление через RKE
