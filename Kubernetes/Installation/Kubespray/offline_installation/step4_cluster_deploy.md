# Kubespray: Offline установка — Шаг 4: Развёртывание кластера

## Определения

**Развёртывание кластера (Cluster Deployment)** — процесс автоматизированной установки и настройки всех системных компонентов Kubernetes (control plane, worker nodes, сетевой плагин, etcd) на целевых узлах с использованием Ansible-плейбуков.

**kubeconfig (admin.conf)** — конфигурационный файл, содержащий данные для аутентификации и адрес API-сервера, используемый утилитой `kubectl` для управления кластером. Генерируется автоматически при инициализации первого master-узла и содержит клиентский сертификат с правами `cluster-admin`.

**Become (Privilege Escalation)** — механизм Ansible для выполнения задач с повышенными привилегиями (обычно через `sudo`). Флаг `-b` (`--become`) обязателен для установки Kubernetes, так как все системные операции (установка пакетов, запись в `/etc/kubernetes`, управление systemd-сервисами) требуют root-прав.

---

## Основные концепции

### Цель этапа

Финальная стадия создания инфраструктуры в изолированной среде. На этом этапе Ansible применяет подготовленные на предыдущих шагах переменные и артефакты из локального реестра (Harbor) ко всем узлам.

**Основные операции плейбука:**

- **Установка пакетов:** `kubelet`, `kubeadm`, `kubectl`, `containerd`.
- **Конфигурация рантайма:** настройка `containerd` на работу с локальным Harbor (через `hosts.toml` или `config.toml`).
- **Инициализация etcd:** создание отказоустойчивого хранилища состояния кластера.
- **Настройка Control Plane:** запуск API-сервера, планировщика и контроллеров.
- **Сетевая связность:** развёртывание Cilium и настройка маршрутизации между подами.
- **Системные сервисы:** установка CoreDNS и Node Local DNS.

### Параметры выполнения

- **Управляющий узел:** все команды запускаются с `master-1`.
- **Длительность:** от 20 до 45 минут (зависит от количества узлов и производительности дисковой подсистемы).
- **Версия Kubespray:** v2.31.0 (совместима с K8s v1.34.x).

### Механизм работы Ansible при развёртывании

Ansible использует SSH для подключения к целевым узлам и выполнения задач. Процесс развёртывания проходит в несколько фаз:

1. **Gathering Facts:** сбор информации об узлах (ОС, сетевые интерфейсы, ресурсы).
2. **Preflight Checks:** проверка совместимости, доступности ресурсов, наличия зависимостей.
3. **Container Runtime Setup:** установка и настройка containerd, конфигурация подключения к Harbor.
4. **etcd Deployment:** инициализация кластера etcd на master-узлах (stacked-топология).
5. **Control Plane Initialization:** `kubeadm init` на первом мастере, `kubeadm join --control-plane` на остальных.
6. **Worker Nodes Join:** присоединение worker-узлов к кластеру через `kubeadm join`.
7. **CNI Installation:** установка сетевого плагина (Cilium) через Helm.
8. **Addons Deployment:** установка CoreDNS, Node Local DNS и дополнительных компонентов.

**Важно:** В offline-режиме каждый pull образа происходит через Harbor. Если образ отсутствует в реестре или недоступен по сети, плейбук завершится с ошибкой.

### Инициализация etcd и кворум

etcd — распределённое хранилище ключ-значение, используемое как основное хранилище состояния кластера Kubernetes. В Kubespray по умолчанию используется **stacked-топология**: каждый master-узел одновременно является узлом Control Plane и членом кластера etcd.

**Кворум etcd:**
- Минимум 3 узла для отказоустойчивости (выдерживает отказ 1 узла).
- Чётное количество узлов (2, 4) не даёт преимуществ в отказоустойчивости, но увеличивает нагрузку.
- Потеря кворума (менее 51% узлов доступны) переводит кластер в режим read-only.

**Процесс инициализации:**
1. Первый master-узел генерирует CA и сертификаты etcd.
2. Остальные master-узлы присоединяются к кластеру etcd через peer-communication.
3. После формирования кворума etcd становится доступен для API-сервера.

### Генерация сертификатов

При развёртывании Kubespray автоматически генерирует PKI-инфраструктуру:

| Сертификат | Срок действия | Назначение |
| :--- | :--- | :--- |
| **CA (Root)** | 10 лет | Корневой центр сертификации для всех компонентов |
| **etcd CA** | 10 лет | Отдельный CA для etcd (изоляция от основного) |
| **API Server** | 1 год | TLS-сертификат для kube-apiserver |
| **Kubelet Client** | 1 год | Для подключения kubelet к API-серверу |
| **Admin (admin.conf)** | 1 год | Клиентский сертификат для администратора |

> Подробнее о ротации сертификатов: **[Управление сертификатами](../../../Operations/certificate_management.md)**.

---

## Практические сценарии

### 0. Предварительные проверки (Pre-flight)

Перед запуском основного плейбука убедитесь, что все предыдущие этапы завершены успешно:

```bash
# Проверка доступности Harbor
curl -sk https://harbor.domain.local/api/v2.0/health
# → {"status":"healthy"}

# Проверка наличия образов в Harbor
curl -sk https://harbor.domain.local/v2/k8s/registry.k8s.io/kube-apiserver/tags/list
# → {"name":"k8s/registry.k8s.io/kube-apiserver","tags":["v1.34.3"]}

# Проверка SSH-доступа ко всем узлам
ansible -i inventory/offline_cluster/inventory.ini all -m ping
# → master-1 | SUCCESS => { "changed": false, "ping": "pong" }
# → master-2 | SUCCESS => ...
# → node-1 | SUCCESS => ...

# Проверка переменных offline.yml
grep -E "registry_host|cilium_install" inventory/offline_cluster/group_vars/all/offline.yml
# → registry_host: "harbor.domain.local"
# → cilium_install_with_helm: true
```

### 1. Подготовка и активация окружения

Перед запуском убедитесь, что все переменные в `group_vars/all/offline.yml` актуальны и указывают на ваш Harbor.

```bash
cd /opt/kuber_off/kubespray
# Активация виртуального окружения
source venv/bin/activate
# → (venv) admin@master-1:/opt/kuber_off/kubespray$
```

### 2. Запуск основного плейбука установки

Для развёртывания используется плейбук `cluster.yml`. Использование флага `-b` (become) обязательно для выполнения операций от root.

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -b -v -u admin
# → PLAY RECAP *********************************************************************
# → master-1 : ok=650 changed=120 unreachable=0 failed=0 ...
# → node-1   : ok=480 changed=90  unreachable=0 failed=0 ...
```

**Параметры команды:**
- `-b` — включение `become` (выполнение от root через sudo).
- `-v` — подробный вывод (verbose). Для ещё большей детализации используйте `-vvv`.
- `-u admin` — пользователь для SSH-подключения.

**Ожидаемое время выполнения:** 20-45 минут в зависимости от количества узлов и производительности дисков.

*Примечание: Если установка прервалась на этапе загрузки образов, проверьте доступность Harbor с проблемного узла через `curl -I https://harbor.domain.local`.*

### 3. Настройка доступа через kubectl

По завершении установки файл конфигурации генерируется на всех master-узлах.

```bash
# Создание директории для конфига в домашней папке пользователя
mkdir -p ~/.kube

# Копирование и настройка прав
sudo cp /etc/kubernetes/admin.conf ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config

# Проверка связи с API-сервером
kubectl cluster-info
# → Kubernetes control plane is running at https://192.168.1.101:6443
# → CoreDNS is running at https://192.168.1.101:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
```

**Проверка содержимого kubeconfig:**
```bash
kubectl config view
# → apiVersion: v1
# → clusters:
# → - cluster:
# →     certificate-authority-data: DATA+OMITTED
# →     server: https://192.168.1.101:6443
# →   name: kubernetes
# → contexts:
# → - context:
# →     cluster: kubernetes
# →     user: kubernetes-admin
# →   name: kubernetes-admin@kubernetes
```

### 4. Первичная диагностика кластера

Проверьте, что все узлы и системные компоненты перешли в рабочее состояние.

**Статус узлов:**
```bash
kubectl get nodes
# → NAME       STATUS   ROLES           AGE   VERSION
# → master-1   Ready    control-plane   10m   v1.34.3
# → master-2   Ready    control-plane   10m   v1.34.3
# → node-1     Ready    worker          10m   v1.34.3
```

**Состояние etcd и системных подов:**
```bash
kubectl get pods -n kube-system
# → NAME                               READY   STATUS    RESTARTS   AGE
# → cilium-xxxxx                       1/1     Running   0          5m
# → kube-apiserver-master-1            1/1     Running   0          9m
# → etcd-master-1                      1/1     Running   0          9m
```

**Проверка здоровья etcd:**
```bash
kubectl -n kube-system exec -it etcd-master-1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/ssl/etcd/ca.crt \
  --cert=/etc/kubernetes/ssl/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/ssl/etcd/healthcheck-client.key \
  endpoint health --cluster
# → https://192.168.1.101:2379 is healthy: successfully committed proposal
# → https://192.168.1.102:2379 is healthy: successfully committed proposal
# → https://192.168.1.103:2379 is healthy: successfully committed proposal
```

**Проверка Cilium (сетевого плагина):**
```bash
# Если установлена утилита cilium cli
cilium status
# → KVStore:                Ok
# → Kubernetes:             Ok 1.34 (v1.34.3) [v1.34.3]
```

**Альтернативная проверка Cilium через kubectl:**
```bash
kubectl -n kube-system exec ds/cilium -- cilium status
# → KVStore:                Ok
# → Kubernetes:             Ok 1.34 (v1.34.3)
# → Cluster health:         reachable (all nodes)
```

### 5. Восстановление после сбоя установки

Если плейбук завершился с ошибкой, не запускайте его повторно без анализа причины. В offline-среде повторный запуск может привести к непредсказуемым результатам.

**Сценарий 5.1: Ошибка на этапе загрузки образов**

```bash
# Проверьте доступность Harbor с проблемного узла
ssh node-1 "curl -sk https://harbor.domain.local/api/v2.0/health"
# → {"status":"healthy"}

# Проверьте наличие конкретного образа
curl -sk https://harbor.domain.local/v2/k8s/registry.k8s.io/kube-apiserver/tags/list
# → {"name":"k8s/registry.k8s.io/kube-apiserver","tags":["v1.34.3"]}
```

**Сценарий 5.2: Частичное выполнение — перезапуск с тегами**

Если установка прервалась после успешной инициализации etcd, можно продолжить с определённого этапа:

```bash
# Перезапуск только установки CNI
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -b -v -u admin --tags "cilium"

# Перезапуск только аддонов (CoreDNS и т.д.)
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -b -v -u admin --tags "addons"
```

**Сценарий 5.3: Полный сброс и переустановка**

Если кластер в неработоспособном состоянии и требуется чистая переустановка:

```bash
# Сброс всех узлов (ВНИМАНИЕ: удаляет все данные!)
ansible-playbook -i inventory/offline_cluster/inventory.ini reset.yml \
  -b -v -u admin

# После сброса — повторная установка
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -b -v -u admin
```

> Подробнее о сбросе и управлении кластером: **[Управление кластером](../cluster_management.md)**.

### 6. Увеличение производительности установки

Для ускорения развёртывания в больших кластерах можно настроить параметры Ansible:

```bash
# Увеличение количества параллельных подключений (forks)
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -b -v -u admin --forks 10

# Или через ansible.cfg
echo "[defaults]" >> ansible.cfg
echo "forks = 10" >> ansible.cfg
```

**Оптимизация для offline-среды:**
- Убедитесь, что между master-1 и Harbor высокоскоростное соединение (1+ Гбит/с).
- Используйте SSD на всех узлах — это критично для etcd.
- Предварительно загрузите образы в containerd на узлах (оптимизация `download_run_once`).

---

## Дополнительная информация

### Типовые проблемы

- **Ошибка сертификатов Harbor:** если Harbor использует самоподписанный сертификат, убедитесь, что он добавлен в доверенные на всех узлах (см. **[Сертификаты Harbor](../../../../Docker/Docker_registries/Harbor/certificates.md)**).
- **Сбой etcd:** часто возникает из-за медленных дисков (HDD) или высокой задержки сети. Проверьте задержки командой `ping` между мастерами.
- **ImagePullBackOff после установки:** проверьте доступность Harbor и наличие образов. В offline-среде digest может измениться при `docker save/load` — отключите `cilium_deploy_with_digest: false`.
- **Узел в статусе NotReady:** проверьте `journalctl -u kubelet -f` на проблемном узле. Частая причина — несоответствие `SystemdCgroup` в containerd.
- **Плейбук зависает на Gathering Facts:** проверьте SSH-доступ и наличие Python на целевых узлах.

### Чеклист валидации после установки

- [ ] Все узлы в статусе `Ready` (`kubectl get nodes`).
- [ ] Все системные поды в `Running` (`kubectl get pods -n kube-system`).
- [ ] etcd кластер здоров (`etcdctl endpoint health --cluster`).
- [ ] Cilium показывает `Cluster health: reachable`.
- [ ] DNS работает внутри кластера (`nslookup kubernetes.default`).
- [ ] Нет ошибок `ImagePullBackOff` (`kubectl get pods -A | grep ImagePullBackOff`).

### См. также

- **[Шаг 5: Настройка MetalLB и Ingress](./step5_metallb_ingress.md)** — публикация сервисов во внешнюю сеть.
- **[Проверка кластера](./cluster_verification.md)** — глубокое тестирование сетевой связности и DNS.
- **[Troubleshooting](./troubleshooting.md)** — решения специфических ошибок offline-режима.
- **[Управление кластером](../cluster_management.md)** — масштабирование, обновление, сброс.
