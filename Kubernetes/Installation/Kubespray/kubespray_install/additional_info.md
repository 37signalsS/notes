# Kubespray: Установка — Дополнительная информация

## Основные концепции

После успешного завершения Ansible playbook `cluster.yml` кластер требует дополнительной проверки и настройки для начала эксплуатации.

### Проверка кластера

**Требования:**
- Доступ к любому узлу control plane по SSH
- Kubeconfig файл (`admin.conf`)

**Ожидаемый результат:** Все узлы в статусе `Ready`, runtime — `containerd`.

### Работа с containerd

Kubespray использует `containerd` как среду выполнения контейнеров. Docker не устанавливается. Для диагностики на уровне узлов применяется `crictl` — CLI для Container Runtime Interface.

### kubeconfig

При настройке `kubeconfig_localhost: true` Kubespray копирует `admin.conf` на локальную машину в `inventory/<cluster>/artifacts/admin.conf`.

---

## Практические сценарии

### Проверка статуса узлов

1. **Подключиться к узлу control plane:**

   ```bash
   ssh user@control-plane-ip
   ```

2. **Проверить статус узлов:**

   ```bash
   kubectl get nodes -o wide
   ```

   **Ожидаемый вывод:**

   ```
   NAME        STATUS   ROLES                  AGE   VERSION   INTERNAL-IP     OS-IMAGE         KERNEL-VERSION    CONTAINER-RUNTIME
   control-1   Ready    control-plane,master   1h    v1.31.0   192.168.1.11    CentOS Linux 7   3.10.0-1160...    containerd://1.7.x
   worker-1    Ready    <none>                 1h    v1.31.0   192.168.1.21    CentOS Linux 7   3.10.0-1160...    containerd://1.7.x
   ```

   Обратите внимание на `CONTAINER-RUNTIME` — должен быть `containerd://`.

### Работа с crictl

**Запущенные контейнеры на узле** (аналог `docker ps`):

```bash
sudo crictl ps
```

**Запущенные поды на текущем узле:**

```bash
sudo crictl pods
```

**Просмотр логов контейнера:**

```bash
sudo crictl logs <CONTAINER_ID>
```

Подробнее о средах выполнения: [Альтернативные среды выполнения](../../../Podman/alternatives_crio_containerd.md).

### Настройка kubeconfig

1. **Найти файл на локальной машине:**

   ```
   inventory/my-cluster/artifacts/admin.conf
   ```

2. **Проверить кластер без установки переменной:**

   ```bash
   kubectl --kubeconfig=inventory/my-cluster/artifacts/admin.conf get nodes
   ```

3. **Установить переменную окружения:**

   ```bash
   export KUBECONFIG=$(pwd)/inventory/my-cluster/artifacts/admin.conf
   ```

4. **Скопировать в домашнюю директорию:**

   ```bash
   mkdir -p ~/.kube
   cp inventory/my-cluster/artifacts/admin.conf ~/.kube/config
   chmod 600 ~/.kube/config
   ```

Подробнее: [kubeconfig и подключение](../../../Operations/kubeconfig_and_connection.md).

### Управление и мониторинг

**Обновление сертификатов:** Сертификаты живут 1 год. Требуется периодическое обновление через [Управление сертификатами](../../../Operations/certificate_management.md).

**Графический интерфейс:** Используйте [Lens](../../../ToolsUtilities/lens/definitions_and_concepts.md) или другие IDE.

**Мониторинг:** Разверните [Prometheus](../../../../Prometheus/Exporters/blackbox/blackbox_exporter_installation_and_setup.md) и [Grafana](../../../../Grafana/grafana_overview.md).

---

## Дополнительная информация

### Связанные темы

- **[Определения](./definitions.md)** — базовые термины
- **[Основные концепции](./basic_concepts.md)** — компоненты конфигурации, этапы установки
- **[Практические сценарии](./practical_scenarios.md)** — настройка inventory, запуск развертывания
- **[Управление кластером](./cluster_management.md)** — масштабирование и обновление
- **[Примеры конфигураций](./examples.md)** — Ingress, MetalLB, системные поды
- **[HA-кластер](../HA/index.md)** — развертывание высокодоступного кластера
- **[Offline установка](../offline_installation/offline_definitions.md)** — развертывание в закрытом контуре
- **[kubeadm](../../kubeadm/ha_keepalived_haproxy/index.md)** — альтернативный ручной метод
- **[kind](../../kind/kind_concepts.md)** — локальные кластеры для разработки
- **[Talos](../../local_cluster_with_talosctl.md)** — безопасная ОС для K8s
