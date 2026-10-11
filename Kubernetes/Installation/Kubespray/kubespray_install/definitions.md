# Kubespray: Установка — Определения

## Определения

**Kubespray** — инструмент для автоматизации развертывания и управления жизненным циклом кластеров Kubernetes на базе Ansible. Полное описание — в [обзоре Kubespray](../overview.md).

**Машина управления (Control Node)** — узел (физический сервер, виртуальная машина или контейнер), с которого инициируется процесс развертывания через Ansible. Требует наличия Python 3.10+, установленного Ansible и SSH-доступа к целевым узлам по ключам.

**Целевые узлы (Target Nodes)** — серверы, на которых развертываются компоненты Kubernetes. Делятся на роли: Control Plane, Worker, etcd.

**Inventory (Инвентарь)** — конфигурационный файл (обычно в формате YAML или INI), описывающий узлы кластера, их IP-адреса и распределение по ролям. Рекомендуемый стандарт — `hosts.yaml`.

**Group vars (Групповые переменные)** — иерархия YAML-файлов в директории `group_vars/` (например, `all/all.yml`, `k8s_cluster/k8s-cluster.yml`), определяющая параметры установки: версии компонентов, сетевые плагины, настройки облачных провайдеров.

**Become** — механизм Ansible для повышения привилегий на целевых узлах (обычно до `root`). Флаг `--become` (или `-b`) обязателен для большинства плейбуков Kubespray.

**Container Runtime (CRI)** — среда выполнения контейнеров. В Kubespray по умолчанию используется **containerd**. Для диагностики состояния контейнеров и подов на узлах используется утилита `crictl`.

**Kubeadm** — базовый инструмент Kubernetes, который Kubespray использует для инициализации компонентов кластера, управления сертификатами и настройки статических подов Control Plane.

**Плейбуки Kubespray** — набор Ansible-сценариев для управления жизненным циклом кластера:
- `cluster.yml` — полная установка кластера "с нуля".
- `scale.yml` — добавление новых узлов (горизонтальное масштабирование).
- `upgrade-cluster.yml` — последовательное обновление версии Kubernetes (Rolling Update).
- `remove-node.yml` — безопасный вывод узла из эксплуатации (`drain` + удаление компонентов).
- `reset.yml` — полная очистка узлов от компонентов Kubernetes (сброс состояния ОС).
- `facts.yml` — сбор актуальных данных о состоянии узлов (Facter/Ansible facts).

**etcd** — распределенное хранилище состояния кластера. Kubespray поддерживает как "stacked" схему (etcd на мастерах), так и выделенные узлы etcd. Подробности — в [Обзоре etcd](../../../../Concepts/etcd_overview.md).

**CNI (Container Network Interface)** — стандарт интерфейса для настройки сети между подами. Реализация в Kubespray и взаимодействие с компонентами — в [Роли CNI и kube-proxy](../../../../Networking/Network/cni_kube_proxy_roles.md).

**kubeconfig** — файл с параметрами аутентификации для доступа к API Kubernetes. В Kubespray по умолчанию копируется в `inventory/<cluster_name>/artifacts/admin.conf` на машине управления.

**Bootstrap Token** — временный токен аутентификации, генерируемый Kubespray для присоединения новых узлов к кластеру. Используется командой `kubeadm join`. Токен действителен 24 часа; по истечении необходимо генерировать новый или использовать existing key.

**Certificate Key** — AES-CBC ключ для шифрования сертификатов Control Plane при их загрузке в Secret `kubeadm-certs` (через `--upload-certs`). Необходим для автоматического присоединения дополнительных мастеров. Действителен 2 часа; по истечении необходимо выполнить `kubeadm init phase upload-certs --upload-certs` повторно.

**Артефакты (Artifacts)** — файлы конфигурации, сертификаты и ключи доступа, генерируемые или извлекаемые Kubespray в процессе развертывания. По умолчанию хранятся на целевых узлах, но могут быть скопированы на машину управления (см. переменную `kubeconfig_localhost` в `group_vars`).

**Конфигурация kubelet** — файл `/var/lib/kubelet/config.yaml` на каждом узле, содержащий параметры работы kubelet: лимиты ресурсов, тайм-ауты, política подбора подов (eviction). Управляется Kubespray через шаблон `kubelet.conf.v1beta1`.

**Конфигурация kubeadm** — файл `/etc/kubernetes/kubeadm-config.yaml`, определяющий параметры инициализации кластера: версию API, адрес API-сервера, диапазон CIDR для подов и сервисов, провайдер облачной инфраструктуры (или `external` для bare-metal).

**`etcd_deployment_type`** — переменная в `group_vars/all/all.yml`, определяющая способ развертывания etcd: `host` (по умолчанию — etcd как systemd-сервис на узлах группы `etcd`), `kubeadm` (experimental — etcd как статический под) или `docker` (etcd в контейнере). Подробности — в [документации etcd](https://kubespray.io/#/docs/operations/etcd).

**`ip` и `access_ip`** — парные переменные инвентаря для каждого хоста. `ip` — адрес, на котором компоненты Kubernetes биндятся (обычно основной интерфейс); `access_ip` — адрес, по которому Ansible и другие узлы подключаются к хосту (в облаках обычно приватный IP). Если `access_ip` не задан, используется `ansible_default_ipv4.address`. Типичная ловушка в облаках: хост за NAT имеет внешний IP для SSH и внутренний для трафика кластера — тогда `ansible_host` указывает на внешний IP, а `ip`/`access_ip` — на внутренний.

**`ansible_host`** — переменная Ansible в инвентаре, задающая адрес для SSH-подключения к хосту. Не путать с `ip`/`access_ip`: `ansible_host` управляет только подключением Ansible, а `ip`/`access_ip` — адресами, которые Kubernetes использует внутри кластера.

**`supplementary_addresses_in_ssl_keys`** — переменная в `group_vars/all/all.yml`: список дополнительных IP-адресов и DNS-имён, включаемых в SAN (Subject Alternative Name) сертификатов API-сервера. Необходима, если API-сервер будет доступен по адресам, отличным от `ip` узлов control plane (например, по VIP или внешнему DNS-имени балансировщика).

**`kube_proxy_mode`** — режим работы kube-proxy: `iptables` (по умолчанию), `ipvs` или `nftables`. Задаётся в `group_vars/all/all.yml`.

**`enable_nodelocaldns`** — переменная в `group_vars/all/all.yml` (по умолчанию `false`). При значении `true` на каждом узле развёртывается DaemonSet NodeLocal DNSCache, кеширующий DNS-ответы локально для подов.

**`ping_access_ip`** — переменная инвентаря: адрес, по которому Ansible проверяет доступность хоста (ICMP-пинг) перед выполнением задач. Полезна, когда `access_ip` недоступен для ping, но доступен по SSH.

---

## Основные концепции

### Модель развертывания

Логика Kubespray строится на декларативном подходе и идемпотентности:
1. **Inventory** связывает физические/виртуальные серверы с логическими ролями Kubernetes.
2. **Group vars** определяют желаемое состояние кластера (Desired State): версии, плагины, параметры ядра.
3. **Плейбуки** выступают исполнительным механизмом, который приводит целевые узлы к заданному состоянию, используя `kubeadm` и системные менеджеры пакетов.

### Иерархия переменных

Kubespray использует сложную систему приоритетов переменных. Изменения рекомендуется вносить только в файлы внутри `inventory/<cluster_name>/group_vars/`, избегая модификации файлов в корне репозитория, чтобы сохранить возможность обновления самого Kubespray.

Порядок переопределения (от низшего к высшему):
1. `roles/kubespray-defaults/defaults/main.yml` — дефолты ролей.
2. `inventory/sample/group_vars/all/all.yml` — глобальные настройки шаблона.
3. `inventory/<cluster>/group_vars/all/all.yml` — глобальные настройки кластера.
4. `inventory/<cluster>/group_vars/k8s_cluster/k8s-cluster.yml` — параметры кластера.
5. `inventory/<cluster>/group_vars/k8s_cluster/addons.yml` — параметры аддонов.
6. `inventory/<cluster>/group_vars/kube_control_plane/k8s-cluster.yml` — параметры control plane.
7. `inventory/<cluster>/group_vars/kube_node/k8s-cluster.yml` — параметры worker-узлов.
8. Переменные, переданные через `-e` при запуске плейбука (highest priority).

> [!IMPORTANT]
> Никогда не редактируйте файлы в корне репозитория Kubespray — они перезаписываются при обновлении. Все изменения — только в `inventory/<cluster>/group_vars/`.

### Теги (Tags)

Для точечного воздействия на компоненты при повторных запусках используются теги:

| Тег | Назначение |
| :--- | :--- |
| `download` | Только скачивание образов (подготовка offline-среды) |
| `certificates` | Ротация сертификатов TLS |
| `kubeadm` | Переинициализация kubeadm-конфигурации |
| `etcd` | Операции с etcd (бэкап, восстановление, обновление) |
| `network` | Настройка CNI-плагинов |
| `addons` | Установка/обновление аддонов (Metrics Server, Dashboard и др.) |
| `kube-proxy` | Обновление правил kube-proxy |

**Пример:** ротация только сертификатов:
```bash
ansible-playbook -i inventory/mycluster/hosts.yaml cluster.yml --tags=certificates,kubeadm
```

### Режимы работы (Online/Offline)

Kubespray поддерживает два режима развертывания:
- **Online** (по умолчанию): все образы и бинарные файлы скачиваются из публичных реестров при каждом запуске.
- **Offline (Air-gapped)**: предварительное скачивание всех зависимостей в локальный реестр (Harbor, Docker Registry), после чего установка выполняется без доступа к интернету. Управляется переменной `download_mode: offline` и файлом `group_vars/all/offline.yml`. Подробности — в [Offline установке](../offline_installation/offline_definitions.md).

### Диапазоны CIDR

Kubespray требует явного определения сетевых диапазонов для подов и сервисов:
- **`kube_pods_subnet`** (по умолчанию `10.233.64.0/18`) — адреса для подов. Каждому узлу выделяется подсеть /24 (254 адреса).
- **`kube_service_subnet`** (по умолчанию `10.233.0.0/18`) — виртуальные адреса для Service (ClusterIP). Не должны пересекаться с `kube_pods_subnet` и реальными сетями.

> [!CAUTION]
> Изменение CIDR после развертывания кластера требует полного сброса (`reset.yml`) и переустановки. Планируйте диапазоны заранее.

---

## Практические сценарии

### 1. Подготовка инвентаря

Создание структуры на основе шаблона:
```bash
cp -rfp inventory/sample inventory/my_cluster
# Далее редактируется inventory/my_cluster/hosts.yaml
```

**Ручное определение узлов** (пример `hosts.yaml`):
```yaml
all:
  children:
    kube_control_plane:
      hosts:
        master-1:
          ansible_host: 10.128.0.10
        master-2:
          ansible_host: 10.128.0.11
        master-3:
          ansible_host: 10.128.0.12
    etcd:
      hosts:
        master-1:
          ansible_host: 10.128.0.10
        master-2:
          ansible_host: 10.128.0.11
        master-3:
          ansible_host: 10.128.0.12
    kube_node:
      hosts:
        worker-1:
          ansible_host: 10.128.0.20
        worker-2:
          ansible_host: 10.128.0.21
```

**Автоматическая генерация** (для стандартной топологии):
```bash
IPS=(10.128.0.10 10.128.0.11 10.128.0.12 10.128.0.20 10.128.0.21)
CONFIG_FILE=inventory/my_cluster/hosts.yaml python3 contrib/inventory_builder/inventory.py ${IPS[@]}
```

### 2. Применение изменений конфигурации

При изменении параметров (например, включение нового аддона) необходимо запустить основной плейбук. Для экономии времени можно использовать теги:
```bash
ansible-playbook -i inventory/my_cluster/hosts.yaml cluster.yml --become --tags=download
```

### 3. Диагностика узла

Проверка состояния CRI после установки через `definitions.md`:
```bash
# Выполняется на целевом узле
sudo crictl pods
sudo crictl ps
```

### 4. Проверка связности кластера

После успешного развертывания:
```bash
# Статус узлов (все должны быть Ready)
kubectl get nodes -o wide

# Системные поды (kube-system)
kubectl get pods -n kube-system -o wide

# DNS-резолв изнутри пода
kubectl run test-dns --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default

# Проверка доступа к API
kubectl cluster-info
```

### 5. Быстрое восстановление control plane

Если мастер-узел недоступен, восстановление выполняется через `reset.yml` и повторный запуск:
```bash
# На целевом узле (если сеть работает, etcd доступен)
ansible-playbook -i inventory/mycluster/hosts.yaml reset.yml --limit=damaged_node
ansible-playbook -i inventory/mycluster/hosts.yaml cluster.yml --limit=damaged_node
```

> [!WARNING]
> Для кластеров с etcd на 3+ узлах восстановление возможно без потери данных. При single-master конфигурации потребуется бэкап etcd.

---

## Дополнительная информация

### См. также
- **[Основные концепции](./basic_concepts.md)** — архитектура и этапы установки.
- **[Практические сценарии](./practical_scenarios.md)** — пошаговое руководство по развертыванию.
- **[Дополнительная информация](./additional_info.md)** — артефакты, credentials, диагностика.
- **[HA через Kubespray](../HA/index.md)** — настройка отказоустойчивости API-сервера.
- **[Offline установка](../offline_installation/offline_definitions.md)** — развертывание в изолированных сетях.

### Внешние ресурсы
- [Kubespray Documentation: Variable Priority](https://kubespray.io/#/docs/vars)
- [Ansible Documentation: Understanding Privilege Escalation](https://docs.ansible.com/ansible/latest/user_guide/become.html)
