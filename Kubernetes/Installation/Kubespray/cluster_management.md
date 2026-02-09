# Kubespray: Управление кластером (Масштабирование и Обновление)

### 3.3. Управление кластером: Масштабирование

#### Добавление Worker Node

1. **Обновите inventory:** Добавьте новые узлы в `inventory.ini` в группу `[kube_node]`.
2. **Запустите плейбук `scale.yml`:**

    ```bash
    ansible-playbook -i inventory/my-cluster/inventory.ini scale.yml
    ```

#### Добавление Master Node (Control Plane)

1. **Обновите inventory:** Добавьте новые master-узлы в `inventory.ini` в группы `[kube_control_plane]` и `[etcd]`.
2. **Запустите плейбук `cluster.yml`:** Для добавления master-узлов используется основной плейбук.

    ```bash
    ansible-playbook -i inventory/my-cluster/inventory.ini cluster.yml
    ```

### 3.4. Управление кластером: Обновление

#### Проверка доступной версии для обновления

Перед обновлением выясните, до какой версии Kubernetes можно обновиться с вашей версией Kubespray.

1. Перейдите в директорию `roles/download/defaults`.
2. Откройте файл `main.yml` и найдите переменную `kubelet_checksums`.

#### Процесс обновления

1. **Измените версию** в `group_vars/k8s-cluster/k8s-cluster.yml`:

    ```yaml
    kube_version: v1.35.0
    ```

2. **Запустите плейбук `upgrade-cluster.yml`:**

    ```bash
    ansible-playbook -i inventory/my-cluster/inventory.ini upgrade-cluster.yml
    ```

    > **Важно:** Плейбук `upgrade-cluster.yml` выполняет задачи последовательно на каждом узле, а не параллельно, для большей безопасности.

#### Проверка после обновления

1. **Проверьте версию API Server и `kubelet`:**

    ```bash
    kubectl version
    kubectl get nodes
    ```

2. **Проверьте версии компонентов Control Plane**, посмотрев на версию образа (`Image`) в описании их подов:

    ```bash
    kubectl describe pod <pod-name> -n kube-system
    ```

#### Возможные проблемы и важные моменты при обновлении

* **Правило одной минорной версии:** Обновлять кластер можно только последовательно, на одну минорную версию за раз (например, с `1.34` на `1.35`).
* **Устаревшие API и манифесты:** В новых версиях Kubernetes могут быть удалены API. Проверяйте манифесты на использование устаревших `apiVersion`.
* **Изменение опций компонентов:** Параметры запуска компонентов могут измениться. Kubespray обычно это обрабатывает, но кастомные конфигурации могут потребовать ручной корректировки.
* **Проверка `release notes`:** Критически важно изучить официальные `release notes` для новой версии Kubernetes.
