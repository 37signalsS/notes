# Kubespray: Offline установка — Практические сценарии

## Определения

**Дорожная карта (Roadmap)** — стратегическая последовательность этапов от подготовки виртуальной инфраструктуры до получения полностью функционального и проверенного кластера в закрытом контуре. Каждый этап имеет чётко определённые входные и выходные данные, а порядок их выполнения является критичным.

**Инфраструктурный план** — сводная таблица распределения вычислительных ресурсов и IP-адресации, являющаяся唯一енным источником истины для конфигурации инвентаря Ansible. Любые отклонения от плана должны быть отражены в инвентаре до запуска плейбуков.

**Pre-flight проверка (Pre-flight Check)** — блок проверок перед каждым этапом установки, гарантирующий готовность инфраструктуры к следующему шагу. Позволяет выявить и устранить проблемы на ранней стадии, когда стоимость исправления минимальна.

**Критический путь (Critical Path)** — последовательность этапов, нарушение которой делает невозможным выполнение последующих шагов. Например: без SSH-доступа (Шаг 1) невозможна загрузка артефактов (Шаг 2), без Harbor (Шаг 3) невозможен deploy (Шаг 4).

**Сквозная валидация (E2E Validation)** — тестирование полной цепочки «Registry -> Runtime -> Pod -> Network -> Ingress» для подтверждения корректности offline-развёртывания. Выполняется на финальном этапе и имитирует реальную нагрузку кластера.

---

## Основные концепции

### Дорожная карта установки

Процесс разбит на пять этапов, каждый из которых зафиксирован в отдельном руководстве. Порядок этапов строго последовательный — каждый следующий зависит от результатов предыдущего.

| Шаг | Задача | Технический фокус | Зависимости | Руководство |
| :--- | :--- | :--- | :--- | :--- |
| **Шаг 1** | Подготовка ВМ | SSH по ключам, беспарольный sudo, системные параметры | Нет (стартовый) | **[VM Preparation](./step1_vm_preparation.md)** |
| **Шаг 2** | Открытый контур | Сбор бандла артефактов на pc-inet, Python venv | Шаг 1 (SSH-ключи) | **[Internet Env](./step2_internet_env.md)** |
| **Шаг 3** | Закрытый контур | Развертывание Harbor, тегирование и загрузка образов | Шаг 2 (архивы) | **[Offline Env](./step3_offline_env.md)** |
| **Шаг 4** | Развёртывание | Запуск основного плейбука `cluster.yml` | Шаг 3 (Harbor + образы) | **[Cluster Deploy](./step4_cluster_deploy.md)** |
| **Шаг 5** | Публикация | Настройка MetalLB L2, Ingress-Nginx, Hubble UI | Шаг 4 (рабочий кластер) | **[LoadBalancer & Ingress](./step5_metallb_ingress.md)** |

### Принцип критического пути

Ошибки на ранних этапах имеют мультипликативный эффект. Ошибка в IP-адресации (Шаг 1) приведёт к невозможности подключения Ansible (Шаг 4), что потребует полного перезапуска. Поэтому каждый этап завершается валидацией перед переходом к следующему.

**Порядок зависит от контекста:**
- **Новое развертывание:** строго последовательно (1 -> 2 -> 3 -> 4 -> 5).
- **Добавление узла в существующий кластер:** достаточно шагов 1 и 4 (`scale.yml`).
- **Обновление версии Kubernetes:** шаги 2, 3, 4 (с тегами upgrade).
- **Миграция Harbor:** только шаг 3 (обновление образов) и 4 (применение).

### Требования к ресурсам и ожидаемые тайминги

Понимание временных затрат критично для планирования окон установки. Время зависит от производительности дисковой подсистемы и скорости сети.

| Этап | Ожидаемое время | Факторы влияния |
| :--- | :--- | :--- |
| **Шаг 1: Подготовка ВМ** | 30-60 мин | Количество узлов, ручные проверки SSH |
| **Шаг 2: Загрузка артефактов** | 15-40 мин | Скорость интернета, объём образов (~2-4 ГБ) |
| **Шаг 3: Настройка Harbor** | 20-40 мин | Установка Harbor, загрузка образов, тегирование |
| **Шаг 4: Deploy кластера** | 20-45 мин | Количество узлов, производительность SSD |
| **Шаг 5: MetalLB + Ingress** | 15-30 мин | Ручная настройка, DNS, тестирование |
| **Итого (полная установка)** | **2-4 часа** | Включая диагностику и исправления |

### Архитектура сети в закрытом контуре

Offline-кластер функционирует в полностью изолированной среде. Все DNS-запросы и pull-образов перенаправляются на локальные сервисы.

```text
Интернет (НЕТ доступа)
       │
       ×
       │
┌──────────────────────────────────────────────────────────────────┐
│                     Закрытый контур                              │
│                                                                  │
│  ┌──────────┐    DNS: harbor.domain.local → 192.168.1.100       │
│  │ Клиент   │────────────────────────────────────────────────┐   │
│  │ (браузер)│                                                 │   │
│  └──────────┘                                                 │   │
│       │                                                       │   │
│       │  HTTP: hubble.k8s.domain.local                        │   │
│       ▼                                                       │   │
│  ┌─────────────────┐     ┌─────────────────────┐              │   │
│  │ MetalLB VIP     │     │ Harbor              │              │   │
│  │ 192.168.1.200   │     │ 192.168.1.100       │              │   │
│  │ (L2 Anycast)    │     │ - k8s/* (Public)    │              │   │
│  └────────┬────────┘     │ - helm/* (Private)  │              │   │
│           │              └─────────────────────┘              │   │
│           ▼                                                   │   │
│  ┌─────────────────┐                                          │   │
│  │ Ingress-Nginx   │  containerd: hosts.toml → Harbor         │   │
│  │ Pod (L7)        │──────────────────────────────────────────┘   │
│  └────────┬────────┘                                             │
│           │                                                      │
│           ▼                                                      │
│  ┌─────────────────┐     ┌─────────────────────┐                 │
│  │ Hubble UI       │     │ kube-apiserver      │                 │
│  │ (port 80)       │     │ 192.168.1.101:6443  │                 │
│  └─────────────────┘     └─────────────────────┘                 │
└──────────────────────────────────────────────────────────────────┘
```

### Ключевые решения при установке

Перед началом установки необходимо принять несколько решений, которые повлияют на архитектуру кластера:

| Решение | Варианты | Рекомендация для offline |
| :--- | :--- | :--- |
| **CNI-плагин** | Cilium / Calico / Flannel | **Cilium** (eBPF, Hubble, без kube-proxy) |
| **Режим MetalLB** | Layer 2 / BGP | **L2** (проще, не требует настройки маршрутизатора) |
| **Ingress-контроллер** | Nginx / Cilium Ingress | **Nginx** (знако��ом, стабилен) или **Cilium** (еBPF-нативный) |
| **Реестр** | Harbor / Docker Registry | **Harbor** (OCI, проекты, RBAC, веб-интерфейс) |
| **Режим etcd** | Stacked / External | **Stacked** (3 мастера = 3 etcd, проще для малых кластеров) |
| **DNS-стратегия** | Локальный DNS / /etc/hosts | **Локальный DNS** (масштабируемость, централизация) |

---

## Практические сценарии

### Инфраструктурный план кластера

Данные параметры являются эталонными для всех примеров. **Требование к дискам:** SSD/NVMe обязательны для узлов Control Plane (из-за чувствительности `etcd` к задержкам записи fsync).

| Узел | IP-адрес | Роль | CPU | RAM | Диск (SSD) | Примечание |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **pc-inet** | 192.168.1.99 | Сбор артефактов (Gateway) | 2 | 4 ГБ | 40 ГБ | Доступ в интернет |
| **harbor** | 192.168.1.100 | Registry / OCI / DNS | 4 | 8 ГБ | 100 ГБ | Рекомендуется выделить SSD |
| **master-1** | 192.168.1.101 | CP 1 / Ansible Control Node | 2 | 4 ГБ | 50 ГБ | Точка управления |
| **master-2** | 192.168.1.102 | Control Plane 2 | 2 | 4 ГБ | 50 ГБ | Чётное число CP не рекомендуется |
| **master-3** | 192.168.1.103 | Control Plane 3 | 2 | 4 ГБ | 50 ГБ | Минимум 3 для отказоустойчивости etcd |
| **node-1** | 192.168.1.104 | Worker Node 1 | 4 | 8 ГБ | 100 ГБ | Приложения и PVC |
| **node-2** | 192.168.1.105 | Worker Node 2 | 4 | 8 ГБ | 100 ГБ | Приложения и PVC |

**Почему именно такая конфигурация:**
- **3 Control Plane:** минимальное число для кворума etcd (2 из 3 должны быть доступны). Чётное число (2 или 4) не даёт преимуществ в отказоустойчивости, но увеличивает потребление ресурсов.
- **2 Worker Node:** минимальное число для балансировки нагрузки и обслуживания без простоя. Один Worker — единичная точка отказа для приложений.
- **SSD обязательно:** `etcd` выполняет синхронную запись (fsync) при каждом транзакции. HDD добавляет задержки 5-15 мс против 0.1 мс для SSD, что вызывает таймауты и расщепление кластера etcd.

### Сводный алгоритм действий (Чек-лист)

#### Этап 1: Инфраструктура

```bash
# 1.1 Разверните 7 ВМ с Ubuntu 24.04 LTS
# 1.2 Настройте статические IP-адреса согласно таблице выше
# 1.3 Проверьте связность между всеми узлами
for ip in 192.168.1.{99,100,101,102,103,104,105}; do
  ping -c 1 -W 1 $ip && echo "$ip: OK" || echo "$ip: FAILED"
done
# → Ожидаемый результат: все 7 IP отвечают

# 1.4 Настройте SSH-ключи с master-1 (подробности в Шаге 1)
ssh-keygen -t rsa -b 4096 -N "" -f ~/.ssh/id_rsa
eval $(ssh-agent -s)
ssh-add ~/.ssh/id_rsa

# 1.5 Распространите ключи на все узлы
for ip in 192.168.1.{99,100,102,103,104,105}; do
  ssh-copy-id admin@$ip
done

# 1.6 Проверьте беспарольный sudo
ssh admin@192.168.1.102 "sudo whoami"
# → root
```

**Валидация этапа 1:**
```bash
# Все узлы доступны по SSH без пароля
for ip in 192.168.1.{99,100,101,102,103,104,105}; do
  ssh -o BatchMode=yes admin@$ip "hostname" 2>/dev/null && echo "$ip: SSH OK" || echo "$ip: SSH FAILED"
done
# → Ожидаемый результат: все 7 IP отвечают
```

#### Этап 2: Загрузка артефактов (на pc-inet)

```bash
# 2.1 Подготовка Python-окружения на pc-inet
sudo mkdir -p /opt/kuber_off && sudo chown $USER:$USER /opt/kuber_off
cd /opt/kuber_off

sudo apt update && sudo apt install python3.12-venv python3-pip -y
python3.12 -m venv venv
source venv/bin/activate
# → (venv) admin@pc-inet:/opt/kuber_off$

# 2.2 Клонирование Kubespray
git clone --branch v2.31.0 --single-branch https://github.com/kubernetes-sigs/kubespray.git
cd kubespray
pip install -r requirements.txt

# 2.3 Настройка инвентаря (temporary: все IP = pc-inet)
cp -r inventory/sample inventory/offline_cluster
# → Отредактируйте inventory.ini, указав 192.168.1.99 во всех группах

# 2.4 Создание offline.yml с путями кэша
cat > inventory/offline_cluster/group_vars/all/offline.yml << 'EOF'
---
download_run_once: true
download_localhost: true
download_format: "tarball"
local_release_dir: "/opt/kubespray-releases"
download_cache_dir: "/opt/kubespray-cache"
cilium_version: "v1.19.6"
cilium_install_with_helm: true
EOF

# 2.5 Загрузка артефактов (15-40 мин)
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  --tags download --skip-tags upload,upgrade \
  -e "@inventory/offline_cluster/group_vars/all/offline.yml" \
  -b -u admin
# → PLAY RECAP ***************** localhost : ok=145 changed=89 ...

# 2.6 Дополнительная загрузка Helm-чарта Cilium
helm repo add cilium https://helm.cilium.io
helm repo update
helm pull cilium/cilium --version 1.19.6
mv cilium-1.19.6.tgz /opt/kubespray-releases/

# 2.7 Упакка для переноса
tar -C /opt -czf kubespray-code.tar.gz kuber_off
tar -C /opt -czf kubespray-offline-bundle.tar.gz kubespray-cache kubespray-releases
# → Проверьте размер: du -sh *.tar.gz (ожидается ~2-4 ГБ)
```

**Валидация этапа 2:**
```bash
# Проверка наличия критических образов
ls /opt/kubespray-cache/images/*.tar | wc -l
# → Ожидаемый результат: >50 файлов

# Проверка наличия бинарных файлов
ls /opt/kubespray-releases/
# → Ожидаемый результат: helm, cilium-1.19.6.tgz, nerdctl, ...

# Проверка размера архивов
du -sh /opt/kubespray-offline-bundle.tar.gz
# → Ожидаемый результат: ~2-4 ГБ
```

#### Этап 3: Настройка Harbor (в закрытом контуре)

```bash
# 3.1 Перенесите архивы на master-1 (USB или SCP)
scp kubespray-code.tar.gz admin@192.168.1.101:~/
scp kubespray-offline-bundle.tar.gz admin@192.168.1.101:~/

# 3.2 Распаковка на master-1
ssh admin@192.168.1.101
tar -xzf ~/kubespray-code.tar.gz -C /opt/
tar -xzf ~/kubespray-offline-bundle.tar.gz -C /opt/
sudo cp /opt/kubespray-releases/helm /usr/local/bin/
sudo chmod +x /usr/local/bin/helm

# 3.3 Установка Harbor на 192.168.1.100
# (следуйте инструкции в step3_offline_env.md)
# Рекомендуется Harbor v2.11+

# 3.4 Создание проектов в Harbor
# - k8s (Public) — для системных образов
# - helm (Private) — для OCI-чартов

# 3.5 Загрузка образов в Harbor
export HARBOR="harbor.domain.local"
docker login $HARBOR

cd /opt/kubespray-cache/images
for f in *.tar; do docker load -i "$f"; done

# Массовое тегирование и push
docker images --format '{{.Repository}}:{{.Tag}}' \
  | grep -E '^(quay\.io|registry\.k8s\.io|docker\.io|gcr\.io)/' \
  | while read img; do
      target="${HARBOR}/k8s/${img}"
      docker tag "$img" "$target"
      docker push "$target"
    done

# 3.6 Публикация Helm-чарта Cilium
helm registry login $HARBOR
helm push /opt/kubespray-releases/cilium-1.19.6.tgz oci://$HARBOR/helm
```

**Валидация этапа 3:**
```bash
# Проверка доступности Harbor
curl -sk https://harbor.domain.local/api/v2.0/health
# → {"status":"healthy"}

# Проверка наличия образов в проекте k8s
# (через веб-интерфейс Harbor или API)
curl -sk https://harbor.domain.local/api/v2.0/projects/k8s/repositories \
  | python3 -m json.tool | grep name | head -5
# → Ожидаемый результат: список репозиториев (k8s/registry.k8s.io/kube-apiserver и т.д.)

# Проверка публикации Helm-чарта
helm search oci://$HARBOR/helm/cilium --version 1.19.6
# → NAME                CHART VERSION   APP VERSION
# → harbor.domain.local/helm/cilium   1.19.6          1.19.6

# Проверка связности Ansible
cd /opt/kuber_off/kubespray
ansible -i inventory/offline_cluster/inventory.ini all -m ping
# → Ожидаемый результат: все узлы отвечают "pong"
```

#### Этап 4: Развёртывание кластера

```bash
# 4.1 Активация окружения
cd /opt/kuber_off/kubespray
source venv/bin/activate
# → (venv) admin@master-1:/opt/kuber_off/kubespray$

# 4.2 Запуск плейбука (20-45 мин)
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -b -v -u admin
# → PLAY RECAP *********************************************************************
# → master-1 : ok=650 changed=120 unreachable=0 failed=0
# → node-1   : ok=480 changed=90  unreachable=0 failed=0

# 4.3 Настройка kubectl
mkdir -p ~/.kube
sudo cp /etc/kubernetes/admin.conf ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config

# 4.4 Первичная проверка
kubectl get nodes
# → NAME       STATUS   ROLES           AGE   VERSION
# → master-1   Ready    control-plane   10m   v1.34.3
# → master-2   Ready    control-plane   10m   v1.34.3
# → master-3   Ready    control-plane   10m   v1.34.3
# → node-1     Ready    worker          10m   v1.34.3
# → node-2     Ready    worker          10m   v1.34.3
```

**Валидация этапа 4:**
```bash
# Все узлы в статусе Ready
kubectl get nodes | grep -c Ready
# → 5 (все узлы)

# Системные поды работают
kubectl get pods -n kube-system | grep -v Running | grep -v Completed
# → Ожидаемый результат: пусто (все поды в Running или Completed)

# etcd здоров
kubectl -n kube-system exec -it etcd-master-1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/ssl/etcd/ca.crt \
  --cert=/etc/kubernetes/ssl/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/ssl/etcd/healthcheck-client.key \
  endpoint health --cluster
# → Ожидаемый результат: все эндпоинты healthy

# Cilium работает
kubectl -n kube-system exec ds/cilium -- cilium status
# → KVStore: Ok
# → Kubernetes: Ok
# → Cluster health: reachable
```

#### Этап 5: MetalLB + Ingress + Валидация

```bash
# 5.1 Настройка MetalLB (L2-режим)
cat <<EOF | kubectl apply -f -
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: primary-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.200-192.168.1.210
  autoAssign: true
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: l2-adv
  namespace: metallb-system
spec:
  ipAddressPools:
  - primary-pool
EOF

# 5.2 Проверка назначения VIP
kubectl get svc -n ingress-nginx ingress-nginx-controller
# → TYPE           EXTERNAL-IP
# → LoadBalancer   192.168.1.200

# 5.3 Настройка Ingress для Hubble UI
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hubble-ui
  namespace: kube-system
  annotations:
    kubernetes.io/ingress.class: nginx
spec:
  rules:
  - host: hubble.k8s.domain.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: hubble-ui
            port:
              number: 80
EOF

# 5.4 DNS: добавьте A-запись на вашем DNS-сервере
# hubble.k8s.domain.local  IN  A  192.168.1.200
# Или в /etc/hosts на клиенте:
# 192.168.1.200  hubble.k8s.domain.local
```

**Финальная валидация (E2E):**
```bash
# Доступ к Hubble UI (с клиента с настроенным DNS)
curl -s http://hubble.k8s.domain.local | head -5
# → Ожидаемый результат: HTML-ответ (страница Hubble UI)

# Тест DNS внутри кластера
kubectl run dns-test --image=busybox:1.37 --rm -it --restart=Never -- nslookup kubernetes.default
# → Server:    10.233.0.3
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.233.0.1

# Тест сетевой связности Cilium
kubectl -n kube-system exec ds/cilium -- cilium connectivity test
# → connectivity test passed

# Проверка отсутствия ошибок ImagePullBackOff
kubectl get pods -A | grep ImagePullBackOff
# → Ожидаемый результат: пусто
```

### Чек-лист финальной приемки

| # | Проверка | Команда | Ожидаемый результат |
| :--- | :--- | :--- | :--- |
| 1 | Все узлы Ready | `kubectl get nodes` | Все 5 узлов в статусе Ready |
| 2 | Системные поды работают | `kubectl get pods -n kube-system` | Все поды Running/Completed |
| 3 | etcd здоров | `etcdctl endpoint health --cluster` | Все эндпоинты healthy |
| 4 | Cilium связность | `cilium status` | Cluster health: reachable |
| 5 | MetalLB VIP назначен | `kubectl get svc -n ingress-nginx` | EXTERNAL-IP из пула |
| 6 | Hubble UI доступен | `curl http://hubble.k8s.domain.local` | HTTP 200 |
| 7 | DNS внутри кластера | `nslookup kubernetes.default` | Разрешается в 10.233.0.1 |
| 8 | Нет ImagePullBackOff | `kubectl get pods -A \| grep ImagePullBackOff` | Пустой вывод |
| 9 | Harbor доступен | `curl -sk https://harbor.domain.local/api/v2.0/health` | `{"status":"healthy"}` |
| 10 | Образы из Harbor | `crictl images \| grep harbor` | Системные образы из Harbor |

---

## Дополнительная информация

### Типовые ошибки по этапам

| Этап | Ошибка | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **1** | SSH: `Permission denied` | Ключ не скопирован или ssh-agent не запущен | `ssh-copy-id`, `eval $(ssh-agent -s)` |
| **1** | `sudo: a password is required` | Не настроен NOPASSWD | Отредактируйте `/etc/sudoers.d/admin` |
| **2** | `python3-apt: No module named` | Venv не видит системные пакеты | `pip install python-apt` или `--system-site-packages` |
| **2** | Download fails: `403 Forbidden` | Реестр блокирует скачивание | Используйте зеркала или VPN на pc-inet |
| **3** | `x509: certificate signed by unknown authority` | CA Harbor не установлен на узле | Добавьте сертификат в `/usr/local/share/ca-certificates/` |
| **3** | `manifest unknown` | Образ отсутствует в Harbor | Проверьте проект k8s в веб-интерфейсе Harbor |
| **4** | etcd: `leader changed` | Медленные диски или сеть | Используйте SSD, проверьте `ping` между мастерами |
| **4** | kubelet не запускается | Несовпадение SystemdCgroup | Установите `SystemdCgroup = true` в containerd |
| **5** | VIP застрял в `<pending>` | IP-пул вне L2-подсети | Проверьте `addresses` в IPAddressPool |
| **5** | 404 при обращении по DNS | Несовпадение `host` в Ingress | Проверьте имя в Ingress и `/etc/hosts` |

### Оптимизации для ускорения установки

- **Кэширование образов:** при повторном запуске `download_run_once: true` предотвращает повторную загрузку.
- **Тегирование Ansible:** использование `--tags` позволяет запускать только необходимые задачи (см. `post_install_management.md`).
- **Параллельный запуск:** Ansible по умолчанию выполняет задачи параллельно на всех узлах (`forks=5` по умолчанию). Увеличьте в `ansible.cfg` при наличии ресурсов.
- **Локальный кэш пакетов:** на `master-1` настройте кэш APT/YUM для ускорения установки пакетов на остальные узлы.

### Блок-схема принятия решений

```text
Начало установки
       │
       ▼
┌─────────────────┐     ДА     ┌─────────────────┐
│ SSH-ключи есть? │────────────▶│ Переход к Шагу 2│
└────────┬────────┘            └─────────────────┘
         │ НЕТ
         ▼
┌─────────────────┐
│ Шаг 1:          │
│ Настройка SSH   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ДА     ┌─────────────────┐
│ Архивы есть?    │────────────▶│ Переход к Шагу 3│
└────────┬────────┘            └─────────────────┘
         │ НЕТ
         ▼
┌─────────────────┐
│ Шаг 2:          │
│ Загрузка на     │
│ pc-inet         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ДА     ┌─────────────────┐
│ Harbor работает?│────────────▶│ Переход к Шагу 4│
└────────┬────────┘            └─────────────────┘
         │ НЕТ
         ▼
┌─────────────────┐
│ Шаг 3:          │
│ Установка Harbor│
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ДА     ┌─────────────────┐
│ Кластер Ready?  │────────────▶│ Переход к Шагу 5│
└────────┬────────┘            └─────────────────┘
         │ НЕТ
         ▼
┌─────────────────┐
│ Шаг 4:          │
│ Deploy +        │
│ Диагностика     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Шаг 5:          │
│ MetalLB +       │
│ Ingress + E2E   │
└────────┬────────┘
         │
         ▼
    Установка завершена
```

### См. также

- **[Определения](./offline_definitions.md)** — архитектурная схема и глоссарий.
- **[Основные концепции](./offline_concepts.md)** — логика перенаправления трафика и настройка containerd.
- **[Проверка кластера](./cluster_verification.md)** — детальные команды тестирования.
- **[Troubleshooting](./troubleshooting.md)** — решение проблем с Digest, MTU и сертификатами.
