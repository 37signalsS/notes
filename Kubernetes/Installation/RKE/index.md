# RKE (Rancher Kubernetes Engine)

> [!WARNING]
> **RKE1 достиг конца жизненного цикла (EOL) 31 июля 2025 года.** 
> Поддержка и обновления безопасности прекратились. Для всех новых проектов рекомендуется использовать **RKE2**. Подробности в разделе [RKE2 документация](https://docs.rke2.io/).

## Определения

**RKE (Rancher Kubernetes Engine)** — сертифицированный дистрибутив Kubernetes от Rancher Labs, предназначенный для развертывания production-кластеров на bare-metal серверах и виртуальных машинах. Полностью запускается внутри Docker-контейнеров.

**Rancher** — платформа для управления несколькими Kubernetes-кластерами (RKE, RKE2, K3s, EKS, GKE), предоставляющая централизованный интерфейс для управления доступом (RBAC), мониторинга и эксплуатации.

**RKE CLI** — утилита командной строки для развертывания и управления кластерами RKE. Работает по принципу "запуск из любого места", подключаясь к узлам по SSH.

**cluster.rkestate** — критически важный файл состояния кластера в формате JSON. Содержит полную копию `cluster.yml`, сгенерированные сертификаты и ключи. Без этого файла обновление или модификация кластера через RKE CLI невозможны.

**rke-tools** — вспомогательный образ контейнера, используемый RKE для выполнения системных операций на узлах (подготовка конфигураций, ротация сертификатов, создание снимков etcd).

## Базовые концепции

### Архитектурные особенности

* **Docker-based:** RKE1 использует Docker как среду выполнения контейнеров для всех компонентов Kubernetes (control plane, worker, etcd).
* **Декларативность:** Конфигурация кластера описывается в одном YAML-файле (`cluster.yml`).
* **Идемпотентность (Idempotency):** Запуск `rke up` приводит текущее состояние кластера в соответствие с конфигурацией.
* **Автономность:** Кластер продолжает функционировать даже при отключении Rancher Server (если он использовался для развертывания).
* **SSH-управление:** RKE подключается к узлам по SSH, проверяет версию Docker и запускает контейнеры компонентов.
* **Статические сертификаты:** RKE самостоятельно генерирует все необходимые TLS-сертификаты для внутренних коммуникаций.

### Системные требования

| Компонент | Требования | Примечания |
| :--- | :--- | :--- |
| **ОС** | Ubuntu 16.04+, CentOS 7+, RHEL 7+, SLES 12+ | Любой Linux с поддержкой Docker |
| **Docker** | 1.13.1, 17.03, 18.06, 18.09, 19.03, 20.10 | Строгое соответствие версиям Rancher |
| **Hardware (Control Plane)** | 2 CPU, 4 GB RAM | Рекомендуется 4 CPU / 8 GB RAM для etcd |
| **Hardware (Worker)** | 1 CPU, 2 GB RAM | Зависит от нагрузки приложений |
| **Сеть** | Порты 6443, 2379-2380, 10250, 8472 (UDP) | Требуется полный доступ между узлами |
| **Диск** | SSD рекомендуется для etcd | Высокая задержка I/O влияет на стабильность |

### Роли узлов (Node Roles)

В RKE узел может совмещать несколько ролей:
1. **etcd:** Хранилище состояния. Требуется нечетное количество (1, 3, 5) для обеспечения кворума.
2. **controlplane:** Запуск API Server, Scheduler, Controller Manager.
3. **worker:** Запуск пользовательских нагрузок (Kubelet, Proxy).

> [!IMPORTANT]
> Для production-сред рекомендуется выделять etcd на отдельные узлы и не совмещать с controlplane.

### Сетевые плагины (CNI)

RKE поддерживает несколько плагинов, которые разворачиваются как Kubernetes-ресурсы сразу после запуска Control Plane:
* **Canal:** Гибрид Flannel (для VXLAN сети) и Calico (для сетевых политик). Самый популярный выбор.
* **Flannel:** Простая L3-сеть, не поддерживает сетевые политики.
* **Calico:** Полноценная поддержка политик и BGP.
* **Weave:** Поддержка шифрования трафика "из коробки".

Подробнее описание архитектуры, отличий от других дистрибутивов вынесено в документ: **[RKE: Основные концепции](./rke_concepts.md)**.

## Практические сценарии

### Методы развертывания

1. **Через Rancher UI:** Самый простой способ с визуальным управлением. Инструкции: [RKE в Rancher](../../Rancher/rancher_rke.md).
2. **Через RKE CLI:** Рекомендуется для автоматизации и инфраструктуры как кода (IaC). Подробности: **[RKE: Установка RKE CLI](./rke_management_scenarios.md#установка-rke-cli)**.

### Высокая доступность (HA)

Для production-кластеров необходима HA-архитектура: минимум 3 control plane + etcd узла и Load Balancer перед API-сервером. Подробное руководство: **[RKE: Высокая доступность](./rke_high_availability.md)**.

### Предварительная подготовка узлов

Перед развертыванием кластера необходимо выполнить подготовку на каждом узле:

```bash
# 1. Установка Docker (пример для Ubuntu)
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
sudo usermod -aG docker $USER

# 2. Проверка версии Docker
docker --version
# → Docker version 20.10.x, build xxxxxxx

# 3. Настройка SSH-доступа (беспарольный)
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa_rke
ssh-copy-id -i ~/.ssh/id_rsa_rke.pub user@node-ip

# 4. Проверка доступности портов между узлами
nc -zv node-ip 6443  # API Server
nc -zv node-ip 2379  # etcd client
nc -zv node-ip 10250 # kubelet
```

### Создание конфигурации cluster.yml

Базовый пример конфигурации для production-кластера:

```yaml
# cluster.yml
nodes:
  - address: 192.168.1.10
    user: ubuntu
    role: [controlplane, etcd]
    ssh_key_path: ~/.ssh/id_rsa_rke
    
  - address: 192.168.1.11
    user: ubuntu
    role: [worker]
    ssh_key_path: ~/.ssh/id_rsa_rke

services:
  etcd:
    snapshot: true
    creation: 6h
    retention: 24h
  kube-api:
    service_cluster_ip_range: 10.43.0.0/16
    service_node_port_range: 30000-32767
  kube-controller:
    cluster_cidr: 10.42.0.0/16
  kubelet:
    cluster_dns_server: 10.43.0.10

network:
  plugin: canal

authentication:
  strategy: x509

ingress:
  provider: nginx
  options:
    use-forwarded-headers: "true"

dns:
  provider: coredns
```

### Запуск кластера

```bash
# Инициализация кластера
rke up --config cluster.yml

# Процесс займет 5-15 минут в зависимости от инфраструктуры
# → INFO[0000] Running pre-checks
# → INFO[0005] Building Kubernetes cluster
# → INFO[0120] Successfully deployed Kubernetes cluster

# Проверка созданного файла конфигурации
ls -la kube_config_cluster.yml cluster.rkestate
```

### Настройка доступа (kubectl)

Для взаимодействия с кластером необходимо установить `kubectl` и получить файл конфигурации `kubeconfig`. Пошаговое руководство: **[RKE: Установка kubectl и настройка доступа](./rke_kubectl_setup.md)**.

### Масштабирование кластера

**Добавление worker-узла:**

```bash
# 1. Подготовить новый узел (Docker, SSH)
# 2. Добавить узел в cluster.yml
# 3. Запустить обновление
rke up --config cluster.yml
```

**Удаление узла:**

```bash
# 1. Удалить узел из cluster.yml
# 2. Выполнить drain (если есть поды)
kubectl drain node-name --ignore-daemonsets --delete-emptydir-data

# 3. Запустить обновление
rke up --config cluster.yml

# 4. Удалить узел из etcd (если был etcd-узлом)
rke etcd remove --name node-name --config cluster.yml
```

### Обновление версии Kubernetes

```yaml
# В файле cluster.yml
kubernetes_version: "v1.28.10-rancher1-1"
```

При запуске `rke up` процесс обновления происходит последовательно:
1. Обновление компонентов на etcd-узлах.
2. Обновление controlplane-узлов.
3. Поочередное обновление worker-узлов (Rolling Update).

## Эксплуатация и поиск неисправностей (Troubleshooting)

### Ротация сертификатов

Сертификаты RKE истекают через 1 год. Рекомендуется выполнять ротацию заблаговременно:

```bash
# Ротация всех сертификатов
rke cert rotate --config cluster.yml

# Ротация только для конкретного сервиса
rke cert rotate --service kubelet --config cluster.yml

# Ротация с шифрованием
rke cert rotate --rotate-ca --config cluster.yml
```

### Резервное копирование etcd

**Создание снимка:**

```bash
# Ручное создание снимка
rke etcd snapshot-save --name backup-$(date +%F) --config cluster.yml
# → INFO[0000] Sending image [rancher/rke-tools:v0.1.99] to nodes
# → INFO[0015] Finished saving snapshot [backup-2026-08-07] on all etcd nodes

# Снимки хранятся в /opt/rke/etcd-snapshots/ на всех etcd-узлах
```

**Восстановление из снимка:**

```bash
rke etcd snapshot-restore --name backup-2026-08-07 --config cluster.yml
# → INFO[0000] Restoring snapshot [backup-2026-08-07]
# → INFO[0045] Finished restoring snapshot successfully
```

### Диагностика проблем

**Проблема: API-сервер недоступен**

```bash
# Проверка состояния компонентов на controlplane-узле
docker ps --filter name=kube-apiserver
docker ps --filter name=etcd

# Просмотр логов kube-apiserver
docker logs kube-apiserver 2>&1 | tail -50

# Проверка логов etcd при ошибках кворума
docker logs etcd 2>&1 | grep -i "error"
```

**Проблема: x509: certificate has expired**

```bash
# Принудительная ротация всех сертификатов
rke cert rotate --config cluster.yml
```

**Проблема: Расхождение состояния (State Mismatch)**

1. Проверьте наличие актуального `cluster.rkestate`.
2. Если файл поврежден, попробуйте `rke up` — RKE попытается восстановить состояние.

**Проверка портов между узлами:**

```bash
# Проверка доступности API Server
nc -zv controlplane-ip 6443

# Проверка доступности etcd
nc -zv etcd-ip 2379
nc -zv etcd-ip 2380

# Проверка доступности kubelet
nc -zv worker-ip 10250
```

### Мониторинг кластера

**Проверка состояния узлов:**

```bash
kubectl get nodes -o wide
# → NAME      STATUS   ROLES                      AGE   VERSION   INTERNAL-IP     ...
# → node-01   Ready    controlplane,etcd,worker   10d   v1.28.10  192.168.1.10

# Проверка системных подов
kubectl get pods -n kube-system
```

**Проверка использования ресурсов:**

```bash
# Установка metrics-server (если не установлен)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# Просмотр использования ресурсов
kubectl top nodes
kubectl top pods -n kube-system
```

## Дополнительная информация

### Рекомендации по безопасности

* **Права доступа:** Ограничивайте права на файл `kubeconfig` (`chmod 600`) и файл состояния `cluster.rkestate`.
* **Минимальные привилегии:** Используйте ServiceAccounts вместо глобальных конфигов администратора.
* **Изоляция узлов:** Изолируйте Control Plane узлы от пользовательских нагрузок с помощью taints.
* **Сетевые политики:** Включайте сетевые политики Kubernetes для ограничения трафика между подами.
* **Обновление Docker:** Регулярно обновляйте Docker до поддерживаемых версий.
* **Брандмауэр:** Настройте iptables или firewalld для ограничения доступа к портам кластера.

**Важные порты для блокировки:**

| Порт | Назначение | Кому разрешать |
| :--- | :--- | :--- |
| 6443 | Kubernetes API Server | Control Plane, kubectl |
| 2379-2380 | etcd | Только etcd-узлы |
| 10250 | kubelet API | Control Plane |
| 8472 | VXLAN (Canal/Flannel) | Все узлы кластера |
| 9099 | Canal health | Все узлы кластера |

### Оптимизация производительности

* **etcd:** Используйте SSD/NVMe диски для etcd. Минимальная задержка I/O критична для стабильности.
* **Сеть:** Обеспечьте низкую задержку между узлами (<1ms для control plane).
* **Ресурсы:** Выделяйте достаточно ресурсов для системных подов (recommendation: 0.5 CPU, 512MB RAM на узел).
* **Планирование:** Настройте толерантности и аффинити для критических системных подов.

### Миграция на RKE2

В связи с окончанием поддержки RKE1 (июль 2025), рекомендуется планировать миграцию на RKE2.

* **Почему RKE2?** Отсутствие зависимости от Docker, встроенная безопасность (CIS hardening), поддержка FIPS.
* **Метод миграции:** Прямого апгрейда "на месте" (in-place) не существует. Требуется развертывание нового кластера и перенос ресурсов (Workloads).

**Шаги миграции:**
1. **Подготовка:** Создание нового кластера RKE2 параллельно существующему.
2. **Сетевая связность:** Настройка маршрутизации или использование общих балансировщиков.
3. **Перенос данных:** Использование Velero или Rancher Backup для миграции объектов и томов (PV).
4. **Тестирование:** Проверка работоспособности приложений на новом кластере.
5. **Переключение трафика:** Обновление DNS записей или балансировщиков.
6. **Очистка:** После успешного переключения трафика, старый кластер RKE1 удаляется командой `rke remove`.

### Сравнение с другими дистрибутивами

| Аспект | RKE (RKE1) | RKE2 | kubeadm |
| :--- | :--- | :--- | :--- |
| **Runtime** | Docker | containerd | Любой CRI |
| **Конфигурация** | Один файл `cluster.yml` | Конфиг-файлы + CLI | CLI флаги + ConfigMaps |
| **Управление узлами** | SSH от RKE CLI | Локальный запуск | Локальный запуск |
| **Безопасность** | Базовая | Высокая (CIS Hardened) | Зависит от пользователя |
| **Установка** | Через Docker | Системные сервисы | Статические поды |

---

**См. также:**
* [RKE: Основные концепции](./rke_concepts.md)
* [RKE: Высокая доступность](./rke_high_availability.md)
* [RKE: Управление и поиск неисправностей](./rke_management_scenarios.md)
* [RKE2: Следующее поколение](https://docs.rke2.io/) — рекомендуемый путь миграции.
* [kubeadm: Быстрый старт](../kubeadm/index.md) — альтернативный метод установки.
* [Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md) — детали настройки доступа.
