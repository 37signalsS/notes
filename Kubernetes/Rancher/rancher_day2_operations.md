# Day-2 операции в Rancher

## Определения

**Day-2 Operations** — операции по эксплуатации и обслуживанию кластеров после первичного развертывания (обновления, масштабирование, обслуживание узлов, ротация сертификатов, управление ресурсами).

**Rolling Update** — последовательное обновление узлов кластера по одному (или группами) с обеспечением доступности сервисов в процессе обновления.

**Drain** — безопасное выселение подов с узла перед обслуживанием (обновление ОС, замена оборудования). Выполняется через `kubectl drain` или Rancher UI.

**Cordon** — пометка узла как `unschedulable` для прекращения размещения новых подов. Выполняется через `kubectl cordon` или Rancher UI.

**System Upgrade Controller (SUC)** — Kubernetes-контроллер, используемый Rancher для автоматического обновления версии Kubernetes на узлах RKE2. Управляется через CRD `Plan`.

## Базовые концепции

### Жизненный цикл кластера в Rancher

```
Провижининг → Настройка → Эксплуатация → Обновление → (Опционально) Удаление
                                ↑
                          Day-2 операции
```

Day-2 операции в Rancher выполняются через:
1. **Rancher UI** — графический интерфейс для основных операций.
2. **Rancher CLI** — командная строка для автоматизации.
3. **kubectl** — прямое управление через API (ACE или Rancher Proxy).
4. **Terraform/OpenTofu** — декларативное управление через провайдер `rancher2`.

### Обновление версии Kubernetes

Rancher поддерживает обновление версии Kubernetes на downstream-кластерах через UI:

1. Cluster Management → Edit Config → Kubernetes Version
2. Выбор новой версии из списка (KDM - Kubernetes Distribution Manager)
3. Rancher через Cluster API изменяет план развертывания
4. System Upgrade Controller последовательно обновляет узлы

**Порядок обновления:**
1. Сначала обновляются Master-узлы (по одному).
2. Затем Worker-узлы согласно настройкам Drain/Concurrency.

### Настройки Drain при обновлении

| Параметр | Описание | Рекомендация |
| :--- | :--- | :--- |
| **Drain** | Включить/выключить выселение подов при обновлении узла | Включить для Worker, опционально для Master |
| **Grace Period** | Время ожидания завершения подов (секунды) | 300 (5 минут) |
| **Timeout** | Максимальное время ожидания завершения drain | 600 (10 минут) |
| **Force** | Принудительное удаление подов | Включить, если есть поды без контроллеров |
| **Ignore DaemonSets** | Игнорировать DaemonSet при drain | Включить (всегда) |
| **Delete EmptyDir Data** | Удалять данные emptyDir | Включить (иначе drain не завершится) |
| **Max Unavailable** | Максимальное количество одновременно обновляемых узлов | 1 (для безопасности) |

## Практические сценарии

### Шаг 1: Обновление версии Kubernetes через Rancher UI

1. Откройте Rancher UI → **Cluster Management**
2. Выберите кластер → **Edit** (или **Edit Config**)
3. В поле **Kubernetes Version** выберите новую версию
4. Настройте параметры Drain (см. таблицу выше)
5. Нажмите **Save**

**Проверка прогресса:**
```bash
# Статус кластера
kubectl get clusters.management.cattle.io
# → my-cluster    Updated

# План обновления (System Upgrade Controller)
kubectl get plans.upgrade.cattle.io -A
# → rke2-upgrade-master-...   True
# → rke2-upgrade-worker-...   True
```

### Шаг 2: Обновление Rancher Server

```bash
# 1. Проверка текущей версии
helm get values rancher -n cattle-system

# 2. Обновление Helm-чарта
helm repo update
helm upgrade rancher rancher-latest/rancher \
  --namespace cattle-system \
  --set hostname=rancher.example.com \
  --set bootstrapPassword='Strong-C0mp1ex-Pass!' \
  --set replicaCount=3

# 3. Проверка
kubectl rollout status deployment/rancher -n cattle-system
```

**Важно:** между minor-версиями (2.13→2.14) обновляйтесь только с последнего патча текущей версии.

### Шаг 3: Обновление system charts (monitoring, logging, fleet)

```bash
# Через Apps & Marketplace в Rancher UI:
# 1. Перейдите в Apps & Marketplace → Installed
# 2. Найдите нужный чарт (rancher-monitoring, rancher-logging)
# 3. Нажмите "Upgrade"
# 4. Выберите новую версию

# Или через Helm:
helm upgrade rancher-monitoring rancher-monitoring/rancher-monitoring \
  --namespace cattle-monitoring-system \
  --reuse-values
```

### Шаг 4: Масштабирование кластера (добавление узлов)

**Добавление Worker-узла:**

1. Rancher UI → Cluster Management → Edit → **Add Node Pool**
2. Укажите количество узлов, образ ОС, ресурсы
3. Или используйте Registration Command для Custom Nodes:

```bash
# На новом узле выполните команду из Rancher UI
curl --insecure -fL https://<rancher-host>/system-agent-install.sh | sudo sh -s - \
  --server https://<rancher-host> \
  --label 'cattle.io/os=linux' \
  --worker \
  --token <cluster-token> \
  --ca-checksum <checksum>
```

**Добавление Master/etcd-узла:**
- Для HA рекомендуется нечетное количество etcd-узлов (1→3→5).
- Добавление Master-узла аналогично Worker, но с флагами `--etcd --controlplane`.

### Шаг 5: Удаление узла из кластера

**Через Rancher UI:**
1. Cluster Management → выберите кластер → Edit → **Remove Node**

**Через CLI:**
```bash
# 1. Drain узла
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --force

# 2. Удаление узла из etcd (для Master/etcd)
sudo rke2 etcd-snapshot save --name pre-removal-$(date +%F)
kubectl delete node <node-name>

# 3. Удаление из Rancher (если Custom Node)
# Через UI: Cluster Management → Edit → Remove Node
```

### Шаг 6: Обслуживание узла (обновление ОС, замена дисков)

```bash
# 1. Cordon (прекратить размещение подов)
kubectl cordon <node-name>

# 2. Drain (безопасно выселить поды)
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force \
  --grace-period=300 \
  --timeout=600s

# 3. Выполните работы на узле (обновление ОС, замена дисков)

# 4. Uncordon (вернуть узел в работу)
kubectl uncordon <node-name>
```

**Через Rancher UI:**
1. Cluster Management → Machine → выберите узел
2. **Cordon** / **Uncordon** / **Delete** (в меню)

### Шаг 7: Ротация сертификатов

```bash
# Через Rancher UI:
# Cluster Management → Edit Config → Rotate Certificates

# Через CLI (RKE2):
sudo rke2 certificate rotate
sudo systemctl restart rke2-server
```

**Когда нужна ротация:**
- Истечение срока действия сертификатов (по умолчанию 1 год).
- Компрометация ключа.
- Изменение SAN (например, добавление нового FQDN).

### Шаг 8: Управление ресурсами (Resource Quotas)

**Настройка квот для проекта в Rancher UI:**
1. Cluster Management → Projects → Edit Project
2. Resource Quotas → Add Quota
3. Установите лимиты (CPU, Memory, PV Count)

```yaml
# Пример ResourceQuota через kubectl
apiVersion: v1
kind: ResourceQuota
metadata:
  name: project-quota
  namespace: project-a
spec:
  hard:
    requests.cpu: "8"
    requests.memory: 16Gi
    limits.cpu: "16"
    limits.memory: 32Gi
    persistentvolumeclaims: "10"
```

### Шаг 9: Мониторинг здоровья кластера

```bash
# Проверка состояния узлов
kubectl get nodes
# → NAME     STATUS   ROLES                       AGE   VERSION
# → node1    Ready    control-plane,etcd,master   30d   v1.34.3+rke2r1
# → node2    Ready    control-plane,etcd,master   30d   v1.34.3+rke2r1
# → node3    Ready    control-plane,etcd,master   30d   v1.34.3+rke2r1
# → node4    Ready    <none>                      30d   v1.34.3+rke2r1

# Проверка подов System
kubectl get pods -A | grep -v Running | grep -v Completed

# Проверка etcd
kubectl get etcd -n kube-system

# Проверка событий (ошибки)
kubectl get events -A --field-selector type=Warning --sort-by=.lastTimestamp | tail -20
```

### Шаг 10: Автоматизация через Terraform

```hcl
# terraform/rancher_cluster.tf
resource "rancher2_cluster" "production" {
  name        = "production"
  description = "Production cluster"

  rke2_config {
    kubernetes_version = "v1.34.3+rke2r1"
  }

  cluster_agent_deployment_strategy {
    rollout_strategy {
      type = "RollingUpdate"
      rolling_update {
        max_surge       = "1"
        max_unavailable = "0"
      }
    }
  }
}
```

## Диагностика и устранение неполадок

### Обновление зависло на Master-узлах

```bash
# Проверка плана обновления
kubectl get plans.upgrade.cattle.io -A -o wide
# → если план в состоянии "Waiting" — проверьте PDB

# Проверка PDB
kubectl get pdb -A

# Проверка System Upgrade Controller
kubectl -n cattle-system logs -l app=system-upgrade-controller --tail=50
```

**Решение:** если PDB блокирует обновление, временно ослабьте его или дождитесь завершения текущего rollout.

### Drain "зависает"

```bash
# Проверка подов, блокирующих drain
kubectl describe node <node-name> | grep -A 10 "Conditions"

# Проверка PDB
kubectl get pdb -A -o wide

# Принудительный drain (опасно!)
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data --force --timeout=60s
```

### Kubectl не подключается к downstream-кластеру

```bash
# Проверка cattle-cluster-agent
kubectl -n cattle-system get pods -l app=cattle-cluster-agent
# → если не Running — перезапустите

kubectl -n cattle-system rollout restart deployment/cattle-cluster-agent

# Проверка исходящей связности
curl -v https://<rancher-fqdn>/v3
```

## Дополнительная информация

### Рекомендации по Day-2 операциям

1. **Регулярные обновления:** обновляйте Rancher и kubernetes минимум раз в квартал (следуйте support matrix).
2. **Тестирование перед обновлением:** всегда делайте backup перед обновлением Rancher Server.
3. **Drain при обслуживании:** всегда используйте drain перед обновлением ОС или заменой оборудования.
4. **Мониторинг:** настройте алертинг на `NodeNotReady`, `PodCrashLooping`, `etcdHighCommitDuration`.
5. **Автоматизация:** используйте Terraform/Fleet для декларативного управления кластерами.

### Связанные темы

- [Установка Rancher Server](./rancher_installation.md) — первичная установка.
- [RKE: Обновления](./rancher_rke.md) — детали обновлений RKE2.
- [Disaster Recovery](./rancher_disaster_recovery.md) —.backup и восстановление.
- [Обслуживание узлов](../Operations/node_maintenance.md) — drain/cordon.

**Внешние ресурсы:**

- [Rancher Cluster Management](https://ranchermanager.docs.rancher.com/cluster-provisioning)
- [System Upgrade Controller](https://github.com/rancher/system-upgrade-controller)
