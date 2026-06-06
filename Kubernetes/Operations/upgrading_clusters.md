# Обновление кластера Kubernetes: Методология и практики

## Определения

**Обновление кластера (Cluster Upgrade)** — процесс поэтапного обновления компонентов Kubernetes до новой минорной или патч-версии с сохранением работоспособности приложений.

**Политика N-2** — официальная политика поддержки Kubernetes, согласно которой поддерживаются 3 последние минорные версии. Обновление через несколько минорных версий (например, 1.30 → 1.33) официально не поддерживается и требует последовательного перехода.

**Breaking changes** — критические изменения в API или поведении компонентов, требующие модификации манифестов или конфигурации перед переходом на новую версию.

**Deprecation Policy** — правила вывода устаревших API из эксплуатации. Перед обновлением необходимо убедиться, что используемые ресурсы переведены на актуальные версии API.

**Version Skew Policy** — правила совместимости версий между различными компонентами кластера (kube-apiserver, kubelet, kubectl).

## Основные концепции

### Порядок обновления компонентов

| Компонент | Роль | Принцип обновления |
| :--- | :--- | :--- |
| **etcd** | SSoT кластера | Всегда первым (или перед Control Plane), обязателен бэкап. |
| **Control Plane** | API, Scheduler, CM | Обновляются по одному узлу, первыми в кластере. |
| **Узлы (Nodes)** | Kubelet, Kube-proxy | Последовательно после стабилизации Control Plane. |
| **Add-ons** | CNI, CoreDNS, Ingress | В соответствии с матрицей совместимости целевой версии. |

### Золотые правила безопасности

1. **Не пропускать минорные версии:** Всегда идти по цепочке (например, 1.32 → 1.33 → 1.34).
2. **Бэкап etcd:** Единственная точка восстановления состояния кластера при фатальном сбое.
3. **Дренаж узлов:** Всегда использовать `kubectl drain` перед обновлением `kubelet`.
4. **Аудит API:** Использование инструментов поиска устаревших ресурсов (`kubent`, `pluto`).
5. **Тестирование на Staging:** Полный цикл обновления на окружении, идентичном production.

### Совместимость версий (Version Skew Policy)

* **Kube-apiserver:** В HA-кластере версии разных экземпляров API-сервера могут отличаться максимум на 1 минорную версию.
* **Kubelet:** Не может быть новее API-сервера. Может быть максимум на 2 минорные версии старее (например, API 1.33 → Kubelet 1.31).
* **Kubectl:** Должен быть в пределах ±1 минорной версии от API-сервера.
* **Kube-proxy:** Должен соответствовать версии Kubelet на узле.

## Практические сценарии

### Общий алгоритм подготовки

#### 1. Аудит и проверка готовности

* **Изучение Release Notes:** Проверка разделов "Urgent Upgrade Notes" для целевой версии.
* **Проверка API:**

    ```bash
    # Поиск устаревших API с помощью Kube No Trouble (kubent)
    kubent --helm3 --exit-error
    # → list of deprecated/deleted APIs found in the cluster
    ```

* **Проверка здоровья кластера:**

    ```bash
    kubectl get nodes
    # → node-1  Ready  ...
    # → node-2  Ready  ...
    ```

#### 2. Резервное копирование etcd

Снапшот необходимо выполнить на одном из узлов Control Plane.

```bash
ETCDCTL_API=3 etcdctl snapshot save /path/to/backup.db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
# → Snapshot saved at /path/to/backup.db
```

Подробнее о восстановлении: **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)**.

### Процедура обновления узла (на примере kubeadm)

Для каждого узла (сначала Master, затем Worker) выполняется стандартный цикл:

1. **Изоляция и Дренаж:**

   ```bash
   kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data
   # → node/node-1 cordoned
   # → evicting pod ...
   ```

2. **Обновление kubeadm:**

   ```bash
   apt-mark unhold kubeadm && \
   apt-get update && apt-get install -y kubeadm=1.33.0-1.1 && \
   apt-mark hold kubeadm
   ```

3. **Применение обновления:**

   ```bash
   # На первом мастере
   sudo kubeadm upgrade apply v1.33.0
   # На остальных узлах
   sudo kubeadm upgrade node
   ```

4. **Обновление kubelet и kubectl:**

   ```bash
   apt-mark unhold kubelet kubectl && \
   apt-get update && apt-get install -y kubelet=1.33.0-1.1 kubectl=1.33.0-1.1 && \
   apt-mark hold kubelet kubectl
   ```

5. **Перезапуск агента:**

   ```bash
   systemctl daemon-reload
   systemctl restart kubelet
   ```

6. **Возврат в работу:**

   ```bash
   kubectl uncordon node-1
   # → node/node-1 uncordoned
   ```

## Диагностика и устранение проблем

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **Node NotReady** | `kubectl describe node <node>` | Проверить логи `journalctl -u kubelet`. Часто: ошибки сертификатов или несовместимые флаги. |
| **Pod CrashLoopBackOff** | `kubectl logs <pod>` | Проверить использование удаленных API. Проверить совместимость CNI. |
| **API Server Timeout** | `curl -k https://localhost:6443/healthz` | Проверить статус контейнеров CP. Проверить кворум etcd. |
| **Drain Failure** | Ошибка при выполнении `drain` | Проверить [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md). Использовать `--force`. |
| **Cert Expired** | Ошибка TLS в логах | См. [Управление сертификатами](certificate_management.md). |

## Рекомендации (Best Practices)

* **Один узел за раз:** В HA-кластерах обновляйте Control Plane по одному узлу, чтобы не потерять кворум etcd и доступность API.
* **Автоматизация:** Для больших кластеров используйте инструменты автоматизации (Kubespray, Cluster API, Ansible), но всегда понимайте ручной процесс.
* **Мониторинг метрик:** Следите за `apiserver_request_duration_seconds` и `etcd_disk_wal_fsync_duration_seconds` в процессе.
* **План отката:** Kubernetes не поддерживает официальный Downgrade. Откат возможен только через восстановление etcd из бэкапа и переустановку бинарных файлов.

## Дополнительная информация

### Связанные темы

* [Управление сертификатами](certificate_management.md) — ротация сертификатов при обновлении.
* [Обслуживание узлов](node_maintenance.md) — детальное описание процессов Cordon и Drain.
* [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md) — защита доступности при обновлении.
* [Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md) — резервное копирование etcd.
* [Kubespray: Управление кластером](../Installation/Kubespray/cluster_management.md) — автоматизированное обновление.
* [RKE: Управление](../Installation/RKE/rke_management_scenarios.md) — специфика обновления RKE.
