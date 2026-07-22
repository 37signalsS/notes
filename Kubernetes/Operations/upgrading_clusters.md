# Обновление кластера Kubernetes: Методология и практики

## Определения

**Обновление кластера (Cluster Upgrade)** — процесс поэтапного и контролируемого перевода компонентов Kubernetes (Control Plane, Worker Nodes, Add-ons) на новую минорную или патч-версию с сохранением работоспособности приложений и целостности данных.

**Политика N-2 / N-3** — официальная политика поддержки Kubernetes. Сообщество поддерживает три последние минорные версии. Обновление "через версию" (например, 1.30 → 1.32) официально не поддерживается и сопряжено с высоким риском ошибок в схемах API.

**Breaking changes** — критические изменения в API или логике работы компонентов, которые требуют предварительной модификации манифестов приложений или настроек инфраструктуры перед выполнением обновления.

**Deprecation Policy** — регламентированный процесс вывода устаревших API из эксплуатации. Перед обновлением необходимо убедиться, что все ресурсы (Ingress, Deployment и др.) переведены на актуальные версии API (например, с `extensions/v1beta1` на `networking.k8s.io/v1`).

**Version Skew Policy** — набор правил, определяющих допустимую разницу версий между компонентами кластера (kube-apiserver, kubelet, kubectl, kube-proxy).

## Основные концепции

### Порядок обновления компонентов

Строгое соблюдение очередности критически важно для сохранения стабильности Control Plane и доступности API.

| Очередность | Компонент | Роль | Принцип обновления |
| :--- | :--- | :--- | :--- |
| 1 | **etcd** | SSoT кластера | Всегда первым (или одновременно с первым узлом CP). Обязателен снапшот перед началом. |
| 2 | **Control Plane** | API, Scheduler, CM | Обновляются по одному узлу. В HA-кластере сначала обновляется "первичный" мастер. |
| 3 | **Add-ons** | CNI, CoreDNS, Ingress | Сразу после стабилизации Control Plane. Проверяется матрица совместимости для новой версии K8s. |
| 4 | **Узлы (Worker Nodes)** | Kubelet, Kube-proxy | Последовательно (Rolling update) с использованием механизмов Cordon и Drain. |

### Золотые правила безопасности

1. **Не пропускать минорные версии:** Обновление всегда идет по цепочке (1.31 → 1.32 → 1.33).
2. **Бэкап etcd:** Единственная точка восстановления. Снапшот должен быть сохранен на внешнем носителе.
3. **Дренаж узлов:** Обновление `kubelet` без `kubectl drain` может привести к некорректному завершению подов и потере данных (особенно для Stateful-нагрузок).
4. **Аудит API:** Использование специализированных инструментов (`kubent`, `pluto`) для автоматического поиска ресурсов, использующих удаляемые в целевой версии API.
5. **Тестирование на Staging:** Полное воспроизведение процесса обновления на идентичном по конфигурации окружении.
6. **Валидация после шага:** Проверка `kubectl get nodes` и `kubectl get pods -A` после обновления каждого отдельного узла.
7. **Проверка рантайма:** Убедитесь, что версия Containerd или CRI-O совместима с целевой версией Kubernetes.

### Совместимость версий (Version Skew Policy)

Актуальные правила для последних версий Kubernetes (1.28+):

* **Kube-apiserver:** В HA-кластере версии экземпляров API-сервера могут отличаться максимум на 1 минорную версию.
* **Kubelet:** Начиная с K8s 1.28, Kubelet может быть на **3 минорные версии старее** API-сервера (например, API 1.31 → Kubelet 1.28). Kubelet **никогда** не может быть новее API-сервера.
* **Kubectl:** Должен быть в пределах ±1 минорной версии от API-сервера.
* **Kube-proxy:** Должен соответствовать версии Kubelet на узле (рекомендуется) и не может быть новее API-сервера.

## Практические сценарии

### 1. Подготовка и аудит готовности

#### Аудит API и Release Notes
Изучите раздел "Urgent Upgrade Notes" в официальном репозитории Kubernetes для целевой версии.

```bash
# Поиск устаревших/удаленных API с помощью Kube No Trouble (kubent)
# Сканирует Helm-чарты и манифесты в кластере
kubent --helm3 --exit-error
# → list of deprecated/deleted APIs found in the cluster
```

#### Проверка здоровья и планов обновления
```bash
# Проверка статуса всех узлов
kubectl get nodes

# Просмотр доступных версий и проверка готовности (только для kubeadm)
kubeadm upgrade plan
```

### 2. Резервное копирование etcd

Выполняется на одном из узлов Control Plane.

```bash
ETCDCTL_API=3 etcdctl snapshot save /var/lib/kubelet/etcd-snapshot-$(date +%F).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
# → Snapshot saved at /var/lib/kubelet/etcd-snapshot-2026-07-22.db
```
*Подробнее: **[Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md)***.

### 3. Сценарий: Автоматизированное обновление (Kubespray)

Для кластеров, развернутых через Kubespray, рекомендуется использовать встроенные плейбуки.

```bash
# Обновление всего кластера до версии, указанной в переменных (v1.x.x)
ansible-playbook -i inventory/mycluster/hosts.yml upgrade-cluster.yml -e kube_version=v1.32.0
```
*Kubespray автоматически выполняет cordon, drain и обновление каждого узла по очереди.*

### 4. Сценарий: Ручное обновление (на примере kubeadm)

Повторяется для каждого узла. Сначала все узлы Control Plane (один за другим), затем Worker-узлы.

**Шаг 1: Изоляция и дренаж (Drain)**
```bash
kubectl drain node-1 --ignore-daemonsets --delete-emptydir-data --timeout=5m
# → node/node-1 cordoned
# → evicting pod ...
```

**Шаг 2: Обновление kubeadm**
```bash
apt-mark unhold kubeadm && \
apt-get update && apt-get install -y kubeadm=1.32.0-1.1 && \
apt-mark hold kubeadm
```

**Шаг 3: Применение обновления конфигурации**
```bash
# На первом (primary) мастере:
sudo kubeadm upgrade apply v1.32.0

# На всех остальных узлах (мастера и воркеры):
sudo kubeadm upgrade node
```

**Шаг 4: Обновление бинарных файлов kubelet и kubectl**
```bash
apt-mark unhold kubelet kubectl && \
apt-get update && apt-get install -y kubelet=1.32.0-1.1 kubectl=1.32.0-1.1 && \
apt-mark hold kubelet kubectl
```

**Шаг 5: Перезапуск сервиса**
```bash
systemctl daemon-reload
systemctl restart kubelet
```

**Шаг 6: Возврат в работу (Uncordon)**
```bash
kubectl uncordon node-1
# → node/node-1 uncordoned
```

## Диагностика и устранение проблем

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **Node NotReady** | `kubectl describe node <node>` | Проверить логи `journalctl -u kubelet`. Возможны ошибки в новых параметрах конфигурации или сертификатах. |
| **Pod CrashLoopBackOff** | `kubectl logs <pod>` | Проверить, не использует ли приложение API, удаленное в этой версии. Проверить совместимость CNI плагина. |
| **API Server Timeout** | `curl -k https://localhost:6443/healthz` | Проверить статус статических подов в `/etc/kubernetes/manifests/`. Проверить кворум etcd. |
| **Drain Failure** | Ошибка таймаута при выселении | Проверить [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md). Использовать `--force` для подов без контроллеров. |
| **Cert Expired** | Ошибка TLS в логах компонентов | `kubeadm certs check-expiration`. Обновление через `kubeadm upgrade` автоматически продлевает сертификаты. |

## Рекомендации (Best Practices)

* **Один узел за раз (Serial Upgrades):** Никогда не обновляйте более одного узла Control Plane одновременно, чтобы избежать потери кворума etcd.
* **Инфраструктура как код (IaC):** Всегда фиксируйте версии Kubernetes в ваших Ansible-плейбуках или Terraform-конфигурациях.
* **Мониторинг метрик:** Во время обновления следите за:
    * `apiserver_request_duration_seconds` (время ответа API).
    * `etcd_server_has_leader` (стабильность кворума).
* **План отката:** Помните, что `kubeadm` не поддерживает команду rollback. Единственный путь назад — удаление узлов, переустановка пакетов старой версии и восстановление etcd из снапшота.
* **Обновление сертификатов:** Проверяйте статус сертификатов перед обновлением. `kubeadm upgrade` обновит их только если они управляются им напрямую.

## Дополнительная информация

### Связанные темы

* [Управление сертификатами](certificate_management.md) — ручное продление и ротация.
* [Обслуживание узлов](node_maintenance.md) — детальное описание процессов Cordon и Drain.
* [PodDisruptionBudget](../Autoscaling/pod_disruption_budget.md) — настройка бюджетов доступности.
* [Кластеризация и восстановление etcd](../../etcd/clustering_and_recovery.md) — глубокое погружение в etcd.
* [Kubespray: Управление кластером](../Installation/Kubespray/cluster_management.md) — детали автоматизации.
* [RKE: Управление](../Installation/RKE/rke_management_scenarios.md) — специфика обновления в Rancher.
