# Kubespray: Установка — Дополнительная информация

## Основные концепции

После успешного завершения Ansible playbook `cluster.yml` кластер требует дополнительной проверки и настройки для начала эксплуатации.

### Проверка кластера

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

3. **Запустить тестовый под для проверки работоспособности:**

   ```bash
   kubectl run test-busybox --image=busybox --restart=Never --command -- sleep 3600
   kubectl get pods
   ```

   Если под успешно создался и перешёл в статус `Running` — кластер функционирует. Для учебных целей можно удалить:

   ```bash
   kubectl delete pod test-busybox
   ```

   > **Примечание:** Запуск пода без команд (`busybox` без `sleep`) приведёт к CrashLoopBackOff, так как контейнер завершает работу немедленно. Это нормальное поведение — главное, что под создаётся и запускается.

### Работа с containerd

Kubespray использует `containerd` как среду выполнения контейнеров. Docker не устанавливается. Для диагностики на уровне узлов применяется `crictl` — CLI для Container Runtime Interface.

### kubeconfig

При настройке `kubeconfig_localhost: true` Kubespray копирует `admin.conf` на локальную машину в `inventory/<cluster>/artifacts/admin.conf`.

---

## Дополнительная информация

### Связанные темы

- **[Определения](./definitions.md)** — базовые термины
- **[Основные концепции](./basic_concepts.md)** — компоненты конфигурации, требования, этапы установки
- **[Практические сценарии](./practical_scenarios.md)** — настройка inventory, запуск развертывания, post-install проверка
- **[Offline установка](../offline_installation/offline_definitions.md)** — развертывание в закрытом контуре
