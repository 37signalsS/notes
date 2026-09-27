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

Kubespray идеально подходит для GitOps-подхода, где вся конфигурация кластера хранится в Git.

**Структура Git-репозитория:**

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
├── playbooks/
│   ├── cluster.yml       # Основной плейбук
│   ├── scale.yml         # Масштабирование
│   └── upgrade.yml       # Обновление
├── .gitlab-ci.yml        # CI/CD pipeline
└── ansible.cfg           # Конфигурация Ansible
```

**Преимущества GitOps для Kubespray:**
- **Версионирование:** отслеживание всех изменений конфигурации.
- **Ревью:** pull request'ы для изменений конфигурации кластера.
- **Воспроизводимость:** развертывание идентичных кластеров из одного репозитория.
- **Аудит:** история коммитов для отслеживания изменений.
- **Автоматизация:** CI/CD пайплайны для автоматического развертывания.

**CI/CD Pipeline (пример для GitLab CI):**

```yaml
# .gitlab-ci.yml
stages:
  - validate
  - deploy
  - upgrade

variables:
  ANSIBLE_HOST_KEY_CHECKING: "False"

validate:
  stage: validate
  script:
    - ansible-playbook -i inventory/mycluster/hosts.yaml --check --diff cluster.yml
  only:
    - merge_requests

deploy:
  stage: deploy
  script:
    - ansible-playbook -i inventory/mycluster/hosts.yaml --become cluster.yml
  only:
    - main
  when: manual

upgrade:
  stage: upgrade
  script:
    - ansible-playbook -i inventory/mycluster/hosts.yaml --become upgrade-cluster.yml
  only:
    - tags
  when: manual
```

**Инструменты GitOps для Kubernetes:**

| Инструмент | Назначение | Особенности |
| :--- | :--- | :--- |
| **ArgoCD** | GitOps-контроллер | Автоматическая синхронизация состояния кластера с Git |
| **Flux** | GitOps-контроллер | Легковесный, встраивается в Kubernetes |
| **Jenkins X** | CI/CD для Kubernetes | Интеграция с Kubernetes, автоматические пайплайны |

**Пример интеграции с ArgoCD:**

```bash
# Установка ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Создание Application для Kubespray
cat <<EOF | kubectl apply -f -
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kubespray-cluster
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://gitlab.com/your-group/kubespray-config.git
    targetRevision: main
    path: inventory/mycluster
  destination:
    server: https://kubernetes.default.svc
    namespace: kube-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
EOF
```

**Рекомендации по GitOps:**
1. **Храните инвентарь в Git:** Все изменения в `hosts.yaml` и `group_vars` должны проходить через pull request.
2. **Используйте branch protection:** Запретите прямые коммиты в ветку `main`.
3. **Настраивайте CI/CD:** Автоматизируйте проверку и деплой изменений.
4. **Версионируйте Kubespray:** Используйте теги для отслеживания версий Kubespray.
5. **Документируйте изменения:** Описывайте назначение изменений в pull request'ах.

## Безопасность в Kubespray

### Сертификаты и PKI

Kubespray автоматически управляет TLS-сертификатами для компонентов кластера:

- **Срок действия:** Сертификаты компонентов Control Plane действуют 1 год, корневой CA — 10 лет.
- **Ротация:** При обновлении через `upgrade-cluster.yml` сертификаты продлеваются автоматически.
- **Ручная ротация:** Выполняется через `cluster.yml --tags=certificates`.

```bash
# Проверка сроков действия сертификатов
sudo kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME   ...
# → admin.conf                 Dec 30, 2026 23:59 UTC   364d
# → apiserver                  Dec 30, 2026 23:59 UTC   364d
```

### RBAC (Role-Based Access Control)

Kubernetes использует RBAC для разграничения доступа. Kubespray не предоставляет встроенных переменных для настройки RBAC, но рекомендует:

1. **Минимальные привилегии:** Не используйте `cluster-admin` для приложений.
2. **ServiceAccount:** Создавайте отдельные ServiceAccount для каждого приложения.
3. **Namespace:** Ограничивайте доступ на уровне пространств имен.

**Пример создания роли для приложения:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: app-reader
  namespace: production
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: production
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
  namespace: production
subjects:
- kind: ServiceAccount
  name: app-reader
  namespace: production
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

### Pod Security Standards (PSS)

С Kubernetes 1.25+ Pod Security Policy заменены на Pod Security Admission (PSA). Kubespray поддерживает настройку PSA через лейблы неймспейсов.

**Уровни безопасности:**

| Уровень | Описание | Примеры ограничений |
| :--- | :--- | :--- |
| **privileged** | Без ограничений (по умолчанию) | Запуск от root, привилегированные контейнеры |
| **baseline** | Минимальные ограничения | Запрет privileged, hostNetwork, hostPID |
| **restricted** | Строгие ограничения | Запрет hostPath, capabilities, только non-root |

**Настройка PSA для неймспейса:**

```bash
# Применение baseline для неймспейса production
kubectl label ns production \
  pod-security.kubernetes.io/enforce=baseline \
  pod-security.kubernetes.io/warn=restricted \
  pod-security.kubernetes.io/audit=restricted
```

**Проверка:**

```bash
# Проверка лейблов неймспейса
kubectl get ns production -o json | jq '.metadata.labels | with_entries(select(.key | startswith("pod-security")))'
# → {
#   "pod-security.kubernetes.io/audit": "restricted",
#   "pod-security.kubernetes.io/enforce": "baseline",
#   "pod-security.kubernetes.io/warn": "restricted"
# }
```

### NetworkPolicy

NetworkPolicy позволяет ограничивать сетевой трафик между подами. В Kubespray выбор CNI-плагина определяет поддержку NetworkPolicy:

- **Calico:** Полная поддержка NetworkPolicy.
- **Cilium:** Полная поддержка + расширения (L7-политики).
- **Flannel:** Не поддерживает NetworkPolicy.

**Пример базовой NetworkPolicy:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-only-frontend
  namespace: production
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - protocol: TCP
      port: 8080
```

### Управление секретами

Kubespray не предоставляет встроенных инструментов управления секретами (HashiCorp Vault, SOPS). Рекомендуется:

1. **Kubernetes Secrets:** Базовое шифрование через etcd.
2. **External Secrets Operator:** Синхронизация секретов из внешних хранилищ.
3. **Sealed Secrets:** Шифрование секретов в Git.

**Пример использования Kubernetes Secrets:**

```bash
# Создание секрета
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password=secret123 \
  -n production

# Монтирование секрета в под
kubectl get secret db-credentials -n production -o jsonpath='{.data.password}' | base64 --decode
```

### CIS Benchmark и хардening

Для соответствия стандартам безопасности (CIS Kubernetes Benchmark) рекомендуется:

1. **kube-bench:** Инструмент для проверки соответствия CIS Benchmark.
2. **kube-hunter:** Инструмент для поиска уязвимостей в кластере.
3. **Trivy:** Сканирование образов контейнеров на уязвимости.

**Установка kube-bench:**

```bash
# Запуск как под
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job.yaml

# Просмотр результатов
kubectl logs -l app=kube-bench
```

### Рекомендации по безопасности в Kubespray

1. **Изоляция Control Plane:** Не запускайте приложения на мастер-узлах.
2. **Ограничение доступа:** Используйте SSH-ключи вместо паролей.
3. **Аудит:** Включите аудит API-сервера через `kube_apiserver_audit_log_path`.
4. **Обновления:** Регулярно обновляйте Kubespray и Kubernetes.
5. **Резервное копирование:** Настраивайте автоматические бэкапы etcd.

> **Подробнее:** Детальная настройка безопасности — в [Security Overview](../../Security/overview.md).

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
