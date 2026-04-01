# Kubespray: Управление кластером

## Определения

**Управление кластером** — операции по масштабированию (добавление/удаление узлов) и обновлению компонентов кластера Kubernetes с помощью Kubespray.

## Основные концепции

### Плейбуки управления

| Плейбук | Назначение |
| :--- | :--- |
| `scale.yml` | Добавление новых worker-узлов |
| `cluster.yml` | Добавление master-узлов (Control Plane) |
| `upgrade-cluster.yml` | Обновление Kubernetes до новой версии |
| `remove-node.yml` | Удаление узлов из кластера |

### Версионирование и совместимость

| Правило | Описание |
| :--- | :--- |
| **Одна минорная версия** | Обновлять можно только на одну минорную версию за раз (например, 1.29 → 1.30) |
| **Версия Kubespray** | Определяет максимальную версию Kubernetes для обновления |
| **Проверка совместимости** | См. `roles/download/defaults/main.yml` (переменная `kubelet_checksums`) |

> **Важно:** Перед обновлением изучите [Release Notes](https://github.com/kubernetes/kubernetes/releases) целевой версии Kubernetes.

## Практические сценарии

### Масштабирование кластера

#### Добавление Worker Node

1. **Обновите inventory** (`inventory/my-cluster/inventory.ini`):

   ```ini
   [kube_node]
   worker-1
   worker-2
   worker-3  # Новый узел
   ```

2. **Запустите плейбук `scale.yml`:**

   ```bash
   ansible-playbook -i inventory/my-cluster/inventory.ini scale.yml
   ```

3. **Проверьте результат:**

   ```bash
   kubectl get nodes
   ```

#### Добавление Master Node (Control Plane)

1. **Обновите inventory:**

   ```ini
   [kube_control_plane]
   control-1
   control-2
   control-3
   control-4  # Новый master

   [etcd]
   control-1
   control-2
   control-3
   control-4  # Новый master (etcd должен быть на всех master)
   ```

2. **Запустите плейбук `cluster.yml`:**

   ```bash
   ansible-playbook -i inventory/my-cluster/inventory.ini cluster.yml
   ```

3. **Проверьте результат:**

   ```bash
   kubectl get nodes -l node-role.kubernetes.io/control-plane
   ```

#### Удаление узла

1. **Обновите inventory** — удалите узел из всех групп.

2. **Запустите плейбук `remove-node.yml`:**

   ```bash
   ansible-playbook -i inventory/my-cluster/inventory.ini remove-node.yml -e node=<имя_узла>
   ```

3. **Проверьте результат:**

   ```bash
   kubectl get nodes
   ```

### Обновление кластера

#### Подготовка к обновлению

1. **Проверьте поддерживаемую версию:**

   ```bash
   cat roles/download/defaults/main.yml | grep kubelet_checksums -A 20
   ```

2. **Изучите Release Notes** целевой версии Kubernetes.

3. **Сделайте бэкап etcd:**

   ```bash
   etcdctl snapshot save snapshot.db
   ```

4. **Проверьте манифесты** на использование устаревших API (см. [Deprecation Guide](https://kubernetes.io/docs/reference/using-api/deprecation-guide/)).

#### Процесс обновления

1. **Измените версию** в `group_vars/k8s-cluster/k8s-cluster.yml`:

   ```yaml
   kube_version: v1.30.0  # Целевая версия
   ```

2. **Запустите плейбук `upgrade-cluster.yml`:**

   ```bash
   ansible-playbook -i inventory/my-cluster/inventory.ini upgrade-cluster.yml
   ```

   > **Важно:** Плейбук выполняет задачи **последовательно** на каждом узле (не параллельно) для минимизации рисков.

3. **Время выполнения:** 20–40 минут в зависимости от количества узлов.

#### Проверка после обновления

1. **Версия API Server и kubelet:**

   ```bash
   kubectl version
   kubectl get nodes
   ```

2. **Версии компонентов Control Plane:**

   ```bash
   kubectl describe pod kube-apiserver-control-1 -n kube-system | grep Image
   kubectl describe pod kube-controller-manager-control-1 -n kube-system | grep Image
   kubectl describe pod kube-scheduler-control-1 -n kube-system | grep Image
   ```

3. **Версия etcd:**

   ```bash
   etcdctl version
   ```

4. **Проверка подов:**

   ```bash
   kubectl get pods -A --field-selector=status.phase!=Running
   ```

### Возможные проблемы при обновлении

| Проблема | Решение |
| :--- | :--- |
| **Устаревшие API** | Обновите манифесты до актуальных `apiVersion` |
| **Изменение опций компонентов** | Проверьте кастомные конфигурации в `group_vars/` |
| **Недостаточно ресурсов** | Освободите ресурсы на узлах перед обновлением |
| **Сбой во время обновления** | Восстановите из бэкапа etcd, откатите версию |

## Дополнительная информация

Связанные документы: [Обзор Kubespray](./overview.md), [Установка кластера](./installation.md), [Примеры конфигураций](./examples.md), [Offline установка](./offline_installation/offline_definitions.md), [Управление сертификатами](../../Operations/certificate_management.md), [etcd: Обзор](../../Concepts/etcd_overview.md).
