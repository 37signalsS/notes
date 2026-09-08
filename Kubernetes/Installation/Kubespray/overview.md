# Kubespray: Обзор

## Определения

**Kubespray** — проект с открытым исходным кодом под эгидой Kubernetes SIG Cluster Lifecycle, предназначенный для автоматизации развертывания и управления жизненным циклом кластеров Kubernetes (LCPM) в различных средах: bare metal, публичные и частные облака.

**Принцип работы:** инструмент использует возможности [Ansible](../../../Ansible/ansible_introduction.md) для декларативного описания конфигурации и [kubeadm](../kubeadm/index.md) для низкоуровневой инициализации компонентов кластера. Это позволяет стандартизировать процесс установки при сохранении высокой степени гибкости.

**Control Plane** — управляющий слой кластера, включающий API-сервер, scheduler, controller-manager и etcd. В Kubespray развертывается как набор статических подов на узлах группы `kube_control_plane`.

**Worker Node** — рабочий узел кластера, на котором запускаются пользовательские поды. Обеспечивает вычислительные ресурсы (CPU, память, диск) для приложений.

## Основные концепции

### Совместимость версий (2025–2026)

Kubespray следует циклу релизов Kubernetes, обеспечивая поддержку актуальных версий. Матрица соответствия последних релизов:

| Версия Kubespray | Версия Kubernetes (Default) | Диапазон поддерживаемых версий K8s |
| :--- | :--- | :--- |
| **v2.31** | **v1.35.x** | v1.33 – v1.35 |
| **v2.30** | **v1.34.x** | v1.32 – v1.34 |
| **v2.29** | v1.33.x | v1.31 – v1.33 |
| **v2.28** | v1.32.x | v1.30 – v1.32 |
| **v2.27** | v1.31.x | v1.29 – v1.31 |

> [!IMPORTANT]
> Kubespray поддерживает обновление только на одну минорную версию за раз (v1.34 → v1.35). Прямой переход через версию (v1.33 → v1.35) не поддерживается.

### Технические требования

*   **Машина управления (Control Node):** Ansible 2.14+, Python 3.10+.
*   **Целевые узлы (Target Nodes):**
    *   **ОС:** Ubuntu (22.04, 24.04), Debian 12, Rocky Linux 9, AlmaLinux 9, RHEL 9/10, Fedora 40+.
    *   **Память:** минимум 2 ГБ RAM (рекомендуется 4 ГБ+ для узлов управления).
    *   **Сеть:** IPv4 (Dual-stack IPv4/IPv6 поддерживается), доступ по SSH, отключенный файл подкачки (SWAP).
    *   **Cgroups:** полная поддержка Cgroup v2. Начиная с K8s v1.35, поддержка Cgroup v1 считается устаревшей и отключена по умолчанию.
    *   **Сеть:** открытые порты: `6443` (API-сервер), `10250` (kubelet), `10251` (scheduler), `10252` (controller-manager), `2379-2380` (etcd), `30000-32767` (NodePort).

### Поддерживаемые компоненты

| Компонент | Варианты реализации | Рекомендация |
| :--- | :--- | :--- |
| **Container Runtime** | **containerd v2.x**, CRI-O | containerd — стандарт индустрии, оптимальная производительность |
| **CNI-плагины** | Calico, **Cilium**, Flannel, Kube-OVN | Cilium для eBPF и NetworkPolicy, Calico для BGP |
| **DNS** | [CoreDNS](../../Networking/dns_deep_dive.md), NodeLocal DNSCache | NodeLocal DNSCache обязателен для production |
| **HA (Control Plane)** | **Kube-Vip**, Keepalived + HAProxy, External LB | Kube-Vip — современный стандарт для bare-metal |
| **Ingress** | Helm-установка (NGINX, Traefik) | Встроенная поддержка NGINX удалена в v2.30 |
| **LoadBalancer** | [MetalLB](../../Networking/metallb.md), Kube-Vip | MetalLB для L2/BGP, Kube-Vip для простых сценариев |
| **Storage** | CSI-драйверы, Local Path, Ceph, NFS | Local Path для dev/test, Ceph/NFS для production |

> [!IMPORTANT]
> Начиная с версии **v2.30**, Kubespray прекратил поддержку встроенных аддонов для Ingress NGINX и Kubernetes Dashboard. Эти компоненты теперь рекомендуется устанавливать отдельно с помощью Helm.

### Структура инвентаря

Kubespray использует иерархическую структуру инвентаря Ansible для управления конфигурацией кластера:

```
inventory/mycluster/
├── hosts.yaml              # Определение узлов и групп
├── group_vars/
│   ├── all/
│   │   └── all.yml         # Общие настройки (реестры образов, прокси)
│   ├── k8s_cluster/
│   │   ├── k8s-cluster.yml # Параметры кластера (версия K8s, CNI, DNS)
│   │   └── addons.yml      # Конфигурация аддонов (MetalLB, Metrics Server и др.)
│   └── kube_control_plane/
│       └── k8s-cluster.yml # Настройки control plane (etcd, API)
└── inventory.ini           # Альтернативный формат инвентаря
```

**Группы узлов в инвентаре:**

| Группа | Назначение | Пример |
| :--- | :--- | :--- |
| `kube_control_plane` | Узлы управления (API, scheduler, controller-manager) | master-1, master-2, master-3 |
| `etcd` | Узлы etcd (может совпадать с control plane) | master-1, master-2, master-3 |
| `kube_node` | Рабочие узлы | worker-1, worker-2, worker-3 |
| `calico-rr` | Route Reflector для Calico BGP (опционально) |专用 узлы или master-ы |

### Цепочка зависимостей компонентов

Порядок установки критичен — компоненты зависят друг от друга:

```
1. Подготовка узлов (sysctl, модули ядра, containerd)
   └─► 2. etcd (хранилище состояния)
       └─► 3. API-сервер (точка входа в кластер)
           └─► 4. Scheduler + Controller Manager
               └─► 5. CNI (Calico/Cilium/Flannel) — сетевая связность
                   └─► 6. CoreDNS (сервис-дискавери)
                       └─► 7. Metrics Server, NodeLocal DNS, MetalLB и др.
```

**Важно:** При сбое на любом этапе последующие компоненты не будут работать корректно. Например, без работающего CNI поды CoreDNS не смогут получить сетевой доступ.

### Особенности эксплуатации

*   **Декларативность:** все настройки хранятся в `group_vars`, что позволяет использовать Git для версионирования конфигурации (GitOps).
*   **Идемпотентность:** повторный запуск плейбуков гарантирует достижение целевого состояния без побочных эффектов.
*   **Масштабируемость:** подходит для кластеров до 200–500 узлов. При дальнейшем росте требуется оптимизация параметров Ansible (forks, pipelining).
*   **Управление жизненным циклом:** наличие специализированных плейбуков для расширения (`scale.yml`), удаления узлов (`remove-node.yml`) и обновления кластера (`upgrade-cluster.yml`).
*   **Offline-режим:** поддержка развертывания в изолированных сетях без доступа к интернету через локальные реестры образов (Harbor, Docker Registry).

### Ограничения и масштабирование

| Параметр | Ограничение | Рекомендация |
| :--- | :--- | :--- |
| **Количество узлов** | 200–500 (без оптимизации) | Увеличить `ansible_forks`, включить `pipelining` |
| **etcd кворум** | Нечетное число узлов (3, 5, 7) | Для >7 узлов etcd — выделенная группа |
| **Обновления** | Только на одну минорную версию | Планируйте обновления каждые 3–4 месяца |
| **Версия K8s** | 3 минорные версии назад | Отслеживайте end-of-life для целевой версии |
| **Ansible** | 2.14+ (требуется Python 3.10+) | Используйте виртуальное окружение для control node |

## Практические сценарии

| Сценарий | Описание и ссылка |
| :--- | :--- |
| **Базовая установка** | Подготовка окружения, инвентаря и первый запуск: **[Установка кластера](./kubespray_install/basic_concepts.md)** |
| **Управление узлами** | Масштабирование, замена узлов и обновление версии: **[Управление кластером](./cluster_management.md)** |
| **Высокая доступность** | Настройка HA Control Plane через Kube-Vip или HAProxy: **[HA через Kubespray](./HA/index.md)** |
| **Offline (Air-gapped)** | Развертывание в изолированных сетях без доступа к интернету: **[Offline установка](./offline_installation/offline_definitions.md)** |
| **Примеры конфигураций** | Готовые наборы переменных для различных сценариев: **[Примеры](./examples.md)** |
| **Ручная альтернатива** | Если автоматизация Ansible не требуется: **[kubeadm: Быстрый старт](../kubeadm/index.md)** |

### Быстрый старт для DevOps/SRE

Для специалистов, работающих с Kubernetes на bare-metal, рекомендуется следующий порядок действий:

1. **Подготовка:** Убедитесь, что ОС соответствует требованиям, SSH-доступ настроен, SWAP отключен.
2. **Инвентарь:** Создайте `inventory/mycluster/hosts.yaml` с группами `kube_control_plane`, `etcd`, `kube_node`.
3. **Конфигурация:** Отредактируйте `group_vars/k8s_cluster/k8s-cluster.yml` (версия K8s, CNI, DNS).
4. **Аддоны:** Включите необходимые аддоны в `group_vars/k8s_cluster/addons.yml` (Metrics Server, MetalLB и др.).
5. **Запуск:** `ansible-playbook -i inventory/mycluster/hosts.yaml --become cluster.yml`.
6. **Верификация:** Проверьте статус узлов (`kubectl get nodes`), подов (`kubectl get pods -A`), DNS (`kubectl run test --image=busybox --rm -it -- nslookup kubernetes.default`).

> **Подробнее:** Пошаговое руководство — в [Установка кластера](./kubespray_install/basic_concepts.md).

### GitOps-интеграция

Kubespray идеально подходит для GitOps-подхода, где вся конфигурация кластера хранится в Git:

```
git-repo/
├── inventory/
│   └── mycluster/
│       ├── hosts.yaml
│       └── group_vars/
│           ├── all/all.yml
│           └── k8s_cluster/
│               ├── k8s-cluster.yml
│           └── addons.yml
├── playbook.yml          # Обертка над cluster.yml
└── .gitlab-ci.yml        # CI/CD pipeline для автоматического деплоя
```

**Преимущества:**
- Версионирование: отслеживание всех изменений конфигурации.
- Ревью:.pull request'ы для изменений конфигурации кластера.
- Воспроизводимость: развертывание идентичных кластеров из одного репозитория.
- Аудит: история коммитов для отслеживания изменений.

## Дополнительная информация

### См. также

*   [Ansible: Введение](../../../Ansible/ansible_introduction.md) — основы работы с инструментом автоматизации.
*   [Автоматизация Kubernetes через Ansible](../../../Ansible/ansible-kubernetes-automation.md) — управление ресурсами кластера (Day-2 operations).
*   [kubeadm: Быстрый старт](../kubeadm/index.md) — базовый механизм, используемый Kubespray.
*   [HA с kubeadm](../kubeadm/ha_concepts.md) — концепции отказоустойчивости.
*   [Control Plane: Архитектура](../../Concepts/control_plane_architecture.md) — внутреннее устройство Kubernetes.
*   [etcd: Обзор](../../Concepts/etcd_overview.md) — работа распределенного хранилища.
*   [CNI и kube-proxy](../../Networking/Network/cni_kube_proxy_roles.md) — сетевая подсистема.
*   [containerd: Установка и настройка](../../Installation/HA_Cluster_Bare_Metal/k8s_ha_component_installation.md) — конфигурация container runtime.
*   [HA: Kube-vip vs Keepalived](../../Installation/Kubespray/HA/kubespray_ha_concepts.md) — сравнение методов отказоустойчивости.

### Внешние ресурсы

*   [Официальный репозиторий GitHub](https://github.com/kubernetes-sigs/kubespray) — исходный код и задачи.
*   [Документация Kubespray](https://kubespray.io/) — подробное описание всех переменных.
*   [Документация Ansible](https://docs.ansible.com/) — справочник по модулям и синтаксису.
*   [Kubernetes Release Schedule](https://kubernetes.io/releases/) — график релизов Kubernetes.
