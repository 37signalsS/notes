# Обновление и откат K3s кластера

Руководство по обновлению K3s на single-node и multi-node кластерах, включая проверку совместимости, пошаговый upgrade, откат и автоматизацию. Специфика K3s: обновление через curl-скрипт или systemd, а не через kubeadm.

Контекст: Часть серии по созданию dev-окружения в K3s. См. [Архитектура K3s](./k3s_architecture.md), [Бэкап и восстановление](./k3s_backup_velero.md).

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **K3s Upgrade** | Обновление бинарного файла K3s (`/usr/local/bin/k3s`) и перезапуск systemd-юнита. В отличие от kubeadm, K3s не требует `kubeadm upgrade apply` — обновление атомарное. |
| **Manifests Directory** | Директория `/var/lib/rancher/k3s/server/manifests/` с YAML-манифестами, автоматически применяемыми при старте K3s. HelmChart CRD обновляются через `helm upgrade`, а не через замену файлов. |
| **Channel Server** | Канал обновлений K3s (`stable`, `latest`), определяющий доступные версии. Управляется через `INSTALL_K3S_CHANNEL`. |
| **Drain** | Процесс безопасного выведения ноды из эксплуатации: эвакуация подов с соблюдением PDB, установка cordon. Обязателен для multi-node кластеров перед обновлением agent-нод. |
| **Cordon** | Пометка ноды как unschedulable. Предотвращает размещение новых подов, но не перемещает существующие. |
| **System Agent Upgrader** | Встроенный в K3s агент для автоматического обновления agent-нод через SystemUpgradeController (_ARGOCD-подобный механизм для K3s). |

Навигация: [Kubernetes Upgrade](../../Operations/upgrading_clusters.md) | [Velero Backup](../../ToolsUtilities/velero-overview.md) | [Высокая доступность](../../Base/high_availability.md)

---

## Основные концепции

### Модель обновления K3s

K3s использует простую модель обновления: замена единого бинарного файла + перезапуск systemd-юнита. Это отличается от классического Kubernetes (kubeadm), где обновление затрагивает множество компонентов по отдельности.

| Этап | Single-Node | Multi-Node |
| :--- | :--- | :--- |
| **Server** | `curl` + перезапуск `k3s.service` | Поочеред drain/upgrade/uncordon каждой server-ноды (если HA) |
| **Agent** | Нет (сервер = агент) | Drain → upgrade binary → restart `k3s-agent.service` → uncordon |
| **Manifests** | Автоматически при старте | Автоматически при старте |
| **Helm-чарты** | `helm upgrade` вручную или через GitOps | `helm upgrade` вручную или через GitOps |

### Совместимость версий

K3s следует стандартной политике совместимости Kubernetes:

- **kubectl** должен совпадать с версией API-сервера (допускается отклонение +/- 1 минорная версия)
- **Agent-ноды** могут работать на версии, отстающей от Server не более чем на 1 минорную версию
- **CRD** обновляются автоматически при обновлении Server (обратная совместимость не гарантирована)

```bash
# Проверка текущей версии
k3s --version
# → k3s version v1.36.3+k3s1 (xxxxxx)

# Проверка доступных обновлений
curl -sL https://update.k3s.io/v1-k3s/channels/stable | jq '.data[] | select(.type=="channel") | .latest'
```

### Стратегии обновления

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **In-Place Upgrade** | Обновление бинарника на работающей ноде | Dev-окружения, single-node кластеры |
| **Blue-Green** | Параллельный запуск старого и нового кластера, переключение трафика | Production, критичные системы |
| **Rolling Upgrade** | Поочередное обновление нод с drain/uncordon | Multi-node кластеры |
| **Automatic (System Agent)** | Автоматическое обновление через SystemUpgradeController | Large кластеры, edge-сценарии |

### Процесс обновления (визуализация)

```text
1. Проверка совместимости
   │
2. Бэкап (etcd/SQLite + PV)
   │
3. Single-Node:
   │  ├── curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="..." sh -
   │  └── systemctl restart k3s
   │
   Multi-Node:
   │  ├── Server (HA): drain → upgrade → restart → uncordon (каждую ноду)
   │  └── Agent: drain → upgrade → restart → uncordon (каждую ноду)
   │
4. Валидация: kubectl get nodes, kubectl get pods -A
   │
5. Обновление Helm-чартов (ArgoCD/GitLab CI)
```

---

## Требования и предварительная подготовка

### Чек-лист перед обновлением

| Проверка | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| Текущая версия K3s | `k3s --version` | Записать текущую версию |
| Версия Kubernetes | `kubectl version` | Server/Client версии совпадают |
| Статус нод | `kubectl get nodes` | Все ноды в статусе `Ready` |
| Поды в не-Running | `kubectl get pods -A \| grep -v Running \| grep -v Completed` | Пустой вывод |
| Дисковое пространство | `df -h /var/lib/rancher/` | Свободно >5 ГБ |
| Бэкап | `ls -la /var/lib/rancher/k3s/server/db/` | Наличие свежей копии SQLite/etcd |
| PDB | `kubectl get pdb -A` | Нет подов с `disruptions: 0` |

### Предварительные шаги

1. **Создание бэкапа (КРИТИЧНО):**
```bash
# Для SQLite (по умолчанию)
sudo cp /var/lib/rancher/k3s/server/db/state.db /var/lib/rancher/k3s/server/db/state.db.bak.$(date +%s)

# Для etcd (если используется --datastore-endpoint=etcd)
sudo k3s etcd-snapshot save --name pre-upgrade-$(date +%s)

# Бэкап конфигурации
sudo tar -czf /tmp/k3s-config-backup-$(date +%s).tar.gz \
  /etc/rancher/k3s/k3s.yaml \
  /etc/rancher/k3s/registries.yaml \
  /var/lib/rancher/k3s/server/manifests/
```

2. **Проверка доступных версий:**
```bash
# Список доступных стабильных версий
curl -sL https://update.k3s.io/v1-k3s/channels/stable | jq -r '.data[] | select(.type=="channel") | .latest'

# Или через INSTALL_K3S_CHANNEL=stable
curl -sfL https://get.k3s.io --dry-run 2>&1 | grep INSTALL_K3S_CHANNEL
```

---

## Практические сценарии

### 1. Обновление single-node K3s (In-Place Upgrade)

Самый распространенный сценарий для dev-окружений.

```bash
# Шаг 1: Бэкап
sudo cp /var/lib/rancher/k3s/server/db/state.db \
  /var/lib/rancher/k3s/server/db/state.db.bak.$(date +%Y%m%d%H%M%S)

# Шаг 2: Обновление через curl (с теми же флагами, что и при установке)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik --disable servicelb" sh -

# Шаг 3: Ожидание готовности (обычно 10-30 секунд)
sudo k3s kubectl get nodes --watch
# → NAME     STATUS   ROLES                  AGE     VERSION
# → server   Ready    control-plane,master   10m     v1.37.0+k3s1

# Шаг 4: Проверка подов
sudo k3s kubectl get pods -A | grep -v Running | grep -v Completed
# → (пустой вывод = все поды работоспособны)

# Шаг 5: Проверка версии
k3s --version
# → k3s version v1.37.0+k3s1 (xxxxxx)
```

**Валидация:**
```bash
# Проверка API-сервера
kubectl cluster-info
# → Kubernetes control plane is running at https://127.0.0.1:6443

# Проверка всех компонентов
kubectl get componentstatuses
# → NAME                 STATUS    MESSAGE             ERROR
# → controller-manager   Healthy   ok
# → scheduler            Healthy   ok

# Проверка работоспособности сервисов
kubectl get svc -A | grep LoadBalancer
# → ingress-nginx-controller   LoadBalancer   10.43.x.x   192.168.1.x
```

**Откат при ошибке:**
```bash
# 1. Остановка K3s
sudo systemctl stop k3s

# 2. Восстановление SQLite
sudo cp /var/lib/rancher/k3s/server/db/state.db.bak.<timestamp> \
  /var/lib/rancher/k3s/server/db/state.db

# 3. Установка предыдущей версии
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="<старая_версия>" \
  INSTALL_K3S_EXEC="--disable traefik --disable servicelb" sh -

# 4. Запуск
sudo systemctl start k3s

# 5. Проверка
k3s --version
# → k3s version v1.36.3+k3s1 (xxxxxx)
```

### 2. Обновление multi-node K3s (Rolling Upgrade)

Для кластеров с отдельными server и agent нодами.

```bash
# === ЭТАП 1: Обновление Server-нод (HA) ===
# Для каждого server-узла (поочередно):

# 1. Drain ноды
kubectl drain <server-node> --ignore-daemonsets --delete-emptydir-data --force
# → node "<server-node>" cordoned
# → pods evicted

# 2. Обновление на сервере
ssh <server-node>
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik" sh -
sudo systemctl restart k3s

# 3. Ожидание готовности
kubectl get nodes --watch
# → <server-node>   Ready    control-plane,master   1m    v1.37.0+k3s1

# 4. Uncordon
kubectl uncordon <server-node>

# === ЭТАП 2: Обновление Agent-нод ===
# Для каждого agent-узла (поочередно):

# 1. Drain ноды
kubectl drain <agent-node> --ignore-daemonsets --delete-emptydir-data

# 2. Обновление на агенте
ssh <agent-node>
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="" sh -
sudo systemctl restart k3s-agent

# 3. Ожидание Ready
kubectl get node <agent-node> --watch

# 4. Uncordon
kubectl uncordon <agent-node>
```

**Валидация multi-node:**
```bash
# Проверка версий всех нод
kubectl get nodes -o wide
# → NAME           STATUS   ROLES                  AGE   VERSION        INTERNAL-IP
# → server         Ready    control-plane,master   1h    v1.37.0+k3s1   192.168.1.100
# → agent-1        Ready    <none>                 1h    v1.37.0+k3s1   192.168.1.101
# → agent-2        Ready    <none>                 1h    v1.37.0+k3s1   192.168.1.102

# Проверка, что все поды работают
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
# → (пустой вывод)
```

### 3. Обновление через System Agent Upgrader (автоматическое)

K3s включает SystemUpgradeController для автоматического обновления agent-нод.

```yaml
# upgrade-plan.yaml — план обновления agent-нод
apiVersion: upgrade.cattle.io/v1
kind: Plan
metadata:
  name: k3s-agent-upgrade
  namespace: system-upgrade
spec:
  agentServiceAccount: system-upgrade-controller
  concurrency: 1
  cordon: true
  drain:
    force: true
    ignore-daemonsets: true
    delete-emptydir-data: true
  nodeSelector:
    matchExpressions:
      - key: node-role.kubernetes.io/agent
        operator: Exists
  serviceAccountName: system-upgrade-controller
  version: v1.37.0+k3s1
  upgrade:
    image: rancher/k3s-upgrade
```

```bash
# Установка SystemUpgradeController
kubectl apply -f https://raw.githubusercontent.com/rancher/system-upgrade-controller/master/manifests/system-upgrade-controller.yaml

# Применение плана обновления
kubectl apply -f upgrade-plan.yaml

# Мониторинг прогресса
kubectl get plans -A
# → NAME                  AGE    VERSION    MESSAGE
# → k3s-agent-upgrade     30s    v1.37.0    Preparing to upgrade worker nodes

kubectl get jobs -n system-upgrade
# → NAME                      COMPLETIONS   DURATION   AGE
# → upgrade-agent-1-x8664     1/1           2m         3m
```

### 4. Обновление Helm-чартов после обновления K3s

После обновления K3s рекомендуется обновить Helm-чарты для совместимости с новым API.

```bash
# Проверка устаревших API
kubectl get apiresources | grep -i deprecated
# → (не должно быть deprecated API в использовании)

# Обновление ingress-nginx
helm upgrade ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx \
  --reuse-values

# Обновление cert-manager
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --reuse-values \
  --set crds.enabled=true

# Обновление Harbor
helm upgrade harbor harbor/harbor \
  --namespace harbor \
  --reuse-values

# Обновление GitLab
helm upgrade gitlab gitlab/gitlab \
  --namespace gitlab \
  -f gitlab-values.yaml \
  --timeout 10m \
  --wait

# Обновление ArgoCD
helm upgrade argocd argo/argo-cd \
  --namespace argocd \
  --reuse-values
```

### 5. Обновление встроенных компонентов K3s

K3s включает встроенные компоненты (CoreDNS, Flannel, Local Path Provisioner), которые обновляются вместе с K3s.

```bash
# Проверка версий встроенных компонентов
kubectl -n kube-system get pods -o wide
# → NAME                                      READY   STATUS    RESTARTS   AGE
# → coredns-xxx                               1/1     Running   0          30m
# → local-path-provisioner-xxx                1/1     Running   0          30m
# → metrics-server-xxx                        1/1     Running   0          30m

# Проверка версии CoreDNS
kubectl -n kube-system exec coredns-xxx -- coredns --version
# → CoreDNS-1.12.0

# Проверка версии Flannel
kubectl -n kube-system exec $(kubectl -n kube-system get pods -l app=flannel -o name) -- \
  cat /etc/kube-flannel/net-conf | grep Version
# → "Version": "1"
```

---

## Типичные ошибки и устранение неполадок

### Ошибка: K3s не запускается после обновления

```bash
# Проверка логов systemd
sudo journalctl -u k3s -n 50 --no-pager
# → Ищите "FATAL" или "failed"

# Проверка версии бинарника
ls -la /usr/local/bin/k3s
# → Должен показывать дату обновления

# Проверка конфигурации
sudo cat /etc/rancher/k3s/k3s.yaml
# → Убедитесь, что конфигурация не повреждена

# Откат на предыдущую версию
sudo systemctl stop k3s
sudo cp /var/lib/rancher/k3s/server/db/state.db.bak.<timestamp> \
  /var/lib/rancher/k3s/server/db/state.db
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="<старая_версия>" sh -
sudo systemctl start k3s
```

### Ошибка: Нода в статусе `NotReady` после обновления agent

```bash
# Проверка логов агента
sudo journalctl -u k3s-agent -n 50 --no-pager
# → Ищите "failed to register" или "connection refused"

# Проверка токена
sudo cat /var/lib/rancher/k3s/server/node-token
# → Должен совпадать с токеном на агенте

# Перезапуск агента
sudo systemctl restart k3s-agent

# Проверка CA-сертификата (если обновление сломало доверие)
sudo ls -la /var/lib/rancher/k3s/server/tls/
# → Должны быть актуальные сертификаты
```

### Ошибка: CRD несовместимы после обновления

```bash
# Проверка CRD
kubectl get crd | wc -l
# → Сравните с количеством до обновления

# Обновление CRD (если используется cert-manager)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.1/cert-manager.crds.yaml

# Проверка deprecated API
kubectl get apiresources -o wide | grep -i deprecated
# → Если есть deprecated API — обновите чарты, использующие их
```

### Ошибка: Helm-чарты перестали работать после обновления

```bash
# Проверка версии Helm-сервера
helm version
# → version.BuildInfo{Version:"v4.2.3", ...}

# Обновление репозиториев
helm repo update

# Проверка совместимости чарта
helm lint ./my-chart
# → 0 chart(s) linted, 0 chart(s) failed

# Принудительное обновление (если конфликт манифестов)
helm upgrade my-release ./my-chart --force-conflicts --atomic
```

---

## Дополнительная информация

### Автоматизация обновлений через CI/CD

```yaml
# .gitlab-ci.yml — автоматическое обновление K3s в dev-окружении
k3s-upgrade:
  stage: deploy
  image: curlimages/curl:latest
  script:
    - |
      curl -sfL https://get.k3s.io | \
        INSTALL_K3S_EXEC="--disable traefik --disable servicelb" sh -
    - sleep 30
    - kubectl get nodes
  rules:
    - if: '$CI_PIPELINE_SOURCE == "web"'
      when: manual
  tags:
    - k3s-server
```

### Рекомендации по частоте обновлений

| Тип обновления | Рекомендуемая частота | Примечание |
| :--- | :--- | :--- |
| **Patch (x.y.Z)** | Ежемесячно | Исправления безопасности, минимальный риск |
| **Minor (x.Y.0)** | Ежеквартально | Новые функции, тестирование совместимости |
| **Major (X.0.0)** | По необходимости | Возможны breaking changes, требует тщательного тестирования |

### Предупреждения

| Аспект | Риск | Рекомендация |
| :--- | :--- | :--- |
| **Single-node** | Нет HA, обновление приводит к даунтайму | Планируйте обновление в окно обслуживания (ночное время) |
| **SQLite** | Нет конкурентного доступа, риск повреждения | Всегда делайте бэкап state.db перед обновлением |
| **Helm через manifests** | Конфликт с GitOps | Используйте один метод управления: manifests ИЛИ Helm, не оба |
| **Agent-ноды** | Несовместимость версий Server/Agent | Agent не может быть новее Server; обновляйте Server первым |

### См. также

- [Архитектура K3s](./k3s_architecture.md) -- обзор всей лаборатории
- [Бэкап и восстановление K3s](./k3s_backup_velero.md) -- стратегии бэкапа перед обновлением
- [Обновление Kubernetes](../../Operations/upgrading_clusters.md) -- общий обзор обновлений K8s
- [Высокая доступность](../../Base/high_availability.md) -- HA-паттерны для multi-node кластеров
