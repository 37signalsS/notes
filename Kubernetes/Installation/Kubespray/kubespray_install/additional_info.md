# Kubespray: Установка — Дополнительная информация

## Действия после установки

### 8.1. Проверка кластера

1. **Подключиться к любому узлу control plane.**

2. **Проверить статус узлов:**

   ```bash
   kubectl get nodes -o wide
   ```

   **Ожидаемый результат:**

   ```
   NAME        STATUS   ROLES                  AGE   VERSION   INTERNAL-IP     OS-IMAGE         KERNEL-VERSION    CONTAINER-RUNTIME
   control-1   Ready    control-plane,master   1h    v1.31.0   192.168.1.11    CentOS Linux 7   3.10.0-1160...    containerd://1.7.x
   worker-1    Ready    <none>                 1h    v1.31.0   192.168.1.21    CentOS Linux 7   3.10.0-1160...    containerd://1.7.x
   ```

   Обратите внимание на `CONTAINER-RUNTIME` — должен быть `containerd`.

### 8.2. Работа с containerd через crictl

Поскольку Docker не используется, для взаимодействия с контейнерами на уровне узла применяется `crictl`:

* **Запущенные контейнеры** (аналог `docker ps`):

  ```bash
  sudo crictl ps
  ```

* **Запущенные поды на текущем узле:**

  ```bash
  sudo crictl pods
  ```

* **Логи контейнера:**

  ```bash
  sudo crictl logs <CONTAINER_ID>
  ```

Подробнее: [Альтернативные среды выполнения](../../../Podman/alternatives_crio_containerd.md).

### 8.3. Работа с kubeconfig

Если установлен параметр `kubeconfig_localhost: true`, Kubespray скопирует `admin.conf` на локальную машину:

1. **Найти файл:**

   ```
   inventory/my-cluster/artifacts/admin.conf
   ```

2. **Проверить статус узлов:**

   ```bash
   kubectl --kubeconfig=inventory/my-cluster/artifacts/admin.conf get nodes
   ```

3. **Установить переменную окружения:**

   ```bash
   export KUBECONFIG=$(pwd)/inventory/my-cluster/artifacts/admin.conf
   ```

4. **Скопировать в домашнюю директорию (опционально):**

   ```bash
   mkdir -p ~/.kube
   cp inventory/my-cluster/artifacts/admin.conf ~/.kube/config
   ```

Подробнее: [kubeconfig и подключение](../../../Operations/kubeconfig_and_connection.md).

### 8.4. Управление и мониторинг

* **Обновление сертификатов:** Сертификаты живут 1 год. Требуется периодическое обновление. См. [Управление сертификатами](../../../Operations/certificate_management.md).
* **Графический интерфейс:** Используйте [Lens](../../../ToolsUtilities/lens/definitions_and_concepts.md) или другие IDE.
* **Мониторинг:** Разверните [Prometheus](../../../../Prometheus/Exporters/blackbox/blackbox_exporter_installation_and_setup.md) и [Grafana](../../../../Grafana/grafana_overview.md).

## Связанные документы

* **[Обзор Kubespray](./overview.md)** — определения и основные концепции.
* **[Управление кластером](./cluster_management.md)** — масштабирование и обновление.
* **[Примеры конфигураций](./examples.md)** — Ingress, MetalLB, системные поды.
* **[HA-кластер через Kubespray](../HA/index.md)** — развертывание высокодоступного кластера.
* **[Offline установка](../offline_installation/offline_definitions.md)** — развертывание в закрытом контуре
* **[kubeadm: Быстрый старт](../../kubeadm/ha_keepalived_haproxy/index.md)** — альтернативный ручной метод.
* **[Управление сертификатами](../../../Operations/certificate_management.md)** — обновление сертификатов кластера.
* **[kind](../../kind/kind_concepts.md)** — локальные кластеры для разработки.
* **[Talos](../../local_cluster_with_talosctl.md)** — безопасная ОС для K8s.

---

## Связанные документы

* **[Определения](./definitions.md)** — базовые термины
* **[Основные концепции](./basic_concepts.md)** — компоненты конфигурации, этапы установки
* **[Практические сценарии](./practical_scenarios.md)** — настройка inventory, запуск развертывания
