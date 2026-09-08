# Kubespray: Установка — Дополнительная информация

## Определения

**Артефакты (Artifacts)** — файлы конфигурации, сертификаты и ключи доступа, генерируемые или извлекаемые Kubespray в процессе развертывания. По умолчанию хранятся на целевых узлах, но могут быть скопированы на машину управления.

**`kubeconfig_localhost`** — переменная в `group_vars` (по умолчанию `false`). При значении `true` Kubespray автоматически копирует файл `admin.conf` в директорию артефактов на машине управления.

**`artifacts_dir`** — директория на машине управления (по умолчанию `inventory/<cluster_name>/artifacts`), куда копируются манифесты, конфигурационные файлы и kubeconfig.

**`credentials_dir`** — защищенная директория (по умолчанию `inventory/<cluster_name>/credentials`), содержащая корневые сертификаты (CA), сертификаты etcd и пароли пользователей.

**Дополнительные термины** — полный глоссарий (kubeconfig, Bootstrap Token, Certificate Key, Playbooks, Become и др.) доступен в разделе **[Определения](./definitions.md)**.

---

## Основные концепции

### Результаты работы установщика

После успешного выполнения плейбука `cluster.yml` формируются следующие ключевые элементы:

1.  **Инфраструктурный слой:** Установлены бинарные файлы Kubernetes (`kubelet`, `kubectl`, `kubeadm`), настроен `containerd` как Container Runtime и зарегистрированы systemd-сервисы (`kubelet.service`).
2.  **Сетевой слой:** Настроен CNI-плагин (Calico, Cilium или Flannel), обеспечена связность между подами и узлами, настроены правила `kube-proxy` (iptables или IPVS).
3.  **Слой управления:** Сгенерирован файл `admin.conf` с правами `cluster-admin`, позволяющий полностью управлять кластером. Настроены статические поды Control Plane (API Server, Scheduler, Controller Manager, etcd).
4.  **Безопасность:** Выпущены сертификаты со сроком действия 1 год (для компонентов Control Plane и kubelet) и 10 лет (для корневого CA). Сгенерированы ключи подписи ServiceAccount (`sa.key`/`sa.pub`).

### Структура директории артефактов

На машине управления после развертывания формируется следующая структура:

```
inventory/<cluster_name>/
├── artifacts/
│   ├── admin.conf                  # kubeconfig для cluster-admin
│   ├── k8s-cluster.yml             # Итоговые переменные кластера
│   ├── nodes                       # Список узлов с IP-адресами
│   └── *.pem                       # Сертификаты (при копировании)
├── credentials/
│   ├── ca.crt / ca.key             # Корневой CA кластера
│   ├── etcd/ca.crt / etcd/ca.key   # Корневой CA для etcd
│   └── *.key                       # Приватные ключи компонентов
└── group_vars/
    ├── all/all.yml                 # Глобальные настройки
    └── k8s_cluster/k8s-cluster.yml # Параметры кластера
```

### Стратегия хранения артефактов

Kubespray придерживается принципа централизованного управления: все критические данные (сертификаты, конфиги) дублируются на **Control Node**. Это необходимо для:
- Возможности управления кластером без SSH-доступа к мастерам.
- Проведения операций масштабирования (`scale.yml`) и обновления (`upgrade-cluster.yml`).
- Аварийного восстановления компонентов Control Plane.
- Ротации сертификатов и добавления новых узлов.

---

## Практические сценарии

### 1. Настройка удаленного доступа (kubectl)

Если параметр `kubeconfig_localhost` включен, выполните следующие шаги на машине управления:

```bash
# 1. Создание локальной директории
mkdir -p ~/.kube

# 2. Копирование артефакта
cp inventory/my_cluster/artifacts/admin.conf ~/.kube/config

# 3. Настройка прав (только для текущего пользователя)
chmod 600 ~/.kube/config

# 4. Проверка связи
kubectl cluster-info
# → Kubernetes control plane is running at https://10.128.0.10:6443
```

#### Управление несколькими кластерами

Если на машине управления разворачивается несколько кластеров, используйте контексты:

```bash
# Добавление нового контекста
kubectl config rename-context $(kubectl config current-context) my-cluster-1

# Переключение между кластерами
kubectl config use-context my-cluster-2

# Просмотр всех контекстов
kubectl config get-contexts -o name
# → my-cluster-1
# → my-cluster-2
```

### 2. Низкоуровневая диагностика через crictl

Поскольку в Kubespray используется `containerd`, стандартные команды `docker` недоступны. Используйте `crictl` на целевых узлах.

| Задача | Команда |
| :--- | :--- |
| Список запущенных подов | `sudo crictl pods` |
| Список контейнеров (все) | `sudo crictl ps -a` |
| Просмотр логов контейнера | `sudo crictl logs <container_id>` |
| Выполнение команды в контейнере | `sudo crictl exec -it <container_id> sh` |
| Список образов в кеше | `sudo crictl images` |
| Очистка неиспользуемых образов | `sudo crictl rmi --prune` |
| Подробная информация о поде | `sudo crictl inspectp <pod_id>` |
| Подробная информация о контейнере | `sudo crictl inspect <container_id>` |
| Статистика по контейнерам | `sudo crictl stats` |
| Порт-форвардинг через crictl | `sudo crictl port-forward <pod_id> 8080:80` |

> [!TIP]
> Используйте `crictl inspect` для диагностики проблем с конкретным контейнером: он покажет текущее состояние, ограничения ресурсов, путь к sandbox и настройки сети.

### 3. Проверка сертификатов после установки

После установки необходимо убедиться, что все сертификаты выпущены и не истекли:

```bash
# Проверка сроков действия сертификатов (на любом Control Plane узле)
sudo kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME   ...
# → admin.conf                 Dec 30, 2026 23:59 UTC   364d
# → apiserver                  Dec 30, 2026 23:59 UTC   364d
# → apiserver-kubelet-client   Dec 30, 2026 23:59 UTC   364d
# → front-proxy-client         Dec 30, 2026 23:59 UTC   364d
# → ...
```

Если сроки действия корректны (1 год для компонентов, 10 лет для CA), сертификаты в порядке.

> [!IMPORTANT]
> Не обновляйте сертификаты вручную до истечения срока, если не планируете ротацию. Подробности управления сертификатами — в **[Управление сертификатами](../../Operations/certificate_management.md)**.

### 4. Проверка состояния etcd

etcd — критически важный компонент. Проверка его здоровья обязательна после установки:

```bash
# Проверка статуса всех узлов etcd
sudo ETCDCTL_API=3 etcdctl endpoint status --cluster -w table \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# → ENDPOINT             ID                    VERSION   DB SIZE   IS LEADER   IS LEARNER   RAFT TERM   RAFT INDEX   RAFT APPLIED INDEX   ...
# → https://10.128.0.10:2379   abc123...   3.5.x     5.0 MB    true        false        2           10           10

# Проверка здоровья (health check)
sudo ETCDCTL_API=3 etcdctl endpoint health --cluster \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# → https://10.128.0.10:2379 is healthy: committed proposal slow took ...
```

#### Интерпретация результатов

| Поле | Ожидаемое значение | Что проверять при отклонении |
| :--- | :--- | :--- |
| **IS LEADER** | Один узел — `true`, остальные — `false` | Если нет ни одного лидера — проблема с кворумом |
| **DB SIZE** | Одинаковый на всех узлах (±10%) | Различия >50% указывают на проблемы с синхронизацией |
| **RAFT TERM** | Одинаковый на всех узлах | Различия означают partition или_SPLIT-BRAIN |
| **HEALTH** | `is healthy` на всех узлах | Нездоровые узлы — проблема с диском или сетью |

### 5. Проверка состояния CNI-плагина

После установки убедитесь, что сетевой плагин корректно работает:

```bash
# Проверка подов CNI (пример для Calico)
kubectl get pods -n kube-system -l k8s-app=calico-node -o wide
# → NAME                READY   STATUS    RESTARTS   AGE   IP            NODE
# → calico-node-xxxxx   1/1     Running   0          10m   10.128.0.10   master-1

# Проверка NetworkPolicy (если используется Calico)
kubectl get networkpolicy -A
# → NAMESPACE         NAME            POD-SELECTORS   AGE
# → kube-system       calico-kube-controllers   k8s-app=calico-kube-controllers   10m

# Проверка IP-pool (для Calico)
kubectl get ippool -o wide
# → NAME         AGE
# → default-ipv4-ippool   10m

# Проверка связности между подами (注明来源)
kubectl run test-pod --image=busybox:1.36 --restart=Never --rm -it -- wget -qO- --timeout=5 http://kubernetes.default
# → {"kind":"Status","apiVersion":"v1","metadata":{},"status":"Failure","message":"forbidden: ..."}
```

> [!NOTE]
> Ответ `forbidden` от API-сервера означает, что сетевая связность работает (DNS-резолв и маршрутизация функционируют), но запрос не прошел авторизацию — это нормальное поведение для неаутентифицированного доступа.

### 6. Резервное копирование etcd

Снапшот etcd — единственный надежный способ забекапить весь кластер Kubernetes целиком. Выполняйте его перед мажорными обновлениями и регулярно по расписанию.

```bash
# Создание снапшота (на любом Control Plane узле)
sudo ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%Y%m%d-%H%M).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# Проверка целостности снапшота
sudo ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-20260831-1200.db -w table

# → +---------+----------+------------+------------+--------------+
# │ DB SIZE | FRAGS    | DB SIZE IN | VERSION    | TABLE KEYS   |
# │          │          | USEC       │            │              |
# +---------+----------+------------+------------+--------------+
# │ 5.0 MB  │ 0        │ 5242880    │ 3.5.x      │ 42           |
# +---------+----------+------------+------------+--------------+
```

#### Автоматизация по расписанию

```bash
# Добавление cron-задачи для ежедневного бэкапа (с очисткой старше 7 дней)
echo "0 2 * * * root ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-\$(date +\\%Y\\%m\\%d-\\%H\\%M).db --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt --key=/etc/kubernetes/pki/etcd/healthcheck-client.key && find /backup -name 'etcd-*.db' -mtime +7 -delete" | sudo tee /etc/cron.d/etcd-backup
```

> [!IMPORTANT]
> Бэкапы etcd должны храниться **вне кластера** (на отдельном носителе или в Object Storage). Восстановление из снапшота требует остановки Control Plane. Подробности — в **[etcd: практические сценарии](../../../Concepts/etcd_operations.md)**.

### 7. Безопасность credentials и артефактов

Файлы в директориях `artifacts/` и `credentials/` содержат root-доступ к кластеру. Их потеря или утечка эквивалентна компрометации всей инфраструктуры.

```bash
# Проверка прав доступа к артефактам
ls -la inventory/my_cluster/artifacts/
# → -rw------- 1 user user  ... admin.conf   ← права 600 (только владелец)

# Проверка прав на credentials
ls -la inventory/my_cluster/credentials/
# → -rw------- 1 user user  ... ca.key       ← права 600

# Проверка, что .gitignore исключает credentials
cat .gitignore | grep -E "credentials|\.key"
# → credentials/
# → *.key
```

#### Рекомендации по безопасности

- **Не коммитьте** `admin.conf`, `*.key` или `credentials/` в Git-репозитории.
- Используйте **менеджеры секретов** (HashiCorp Vault, SOPS) для шифрования credentials в Git.
- Регулярно **ротируйте** сертификаты и kubeconfig ( срок действия — 1 год ).
- На **CI/CD-пайплайнах** храните kubeconfig как зашифрованный секрет, а не как текстовую переменную.
- При работе с несколькими кластерами используйте **отдельные kubeconfig-файлы** и переключайтесь через `KUBECONFIG` environment variable.

---

## Дополнительная информация

### См. также
- **[Определения](./definitions.md)** — глоссарий терминов и описание плейбуков.
- **[Управление сертификатами](../../Operations/certificate_management.md)** — ротация и продление TLS-ключей.
- **[etcd: практические сценарии](../../../Concepts/etcd_operations.md)** — бэкап, восстановление, дефрагментация.

### Внешние ресурсы
- [Kubernetes CLI (crictl) User Guide](https://github.com/kubernetes-sigs/cri-tools/blob/master/docs/crictl.md)
- [Kubespray Documentation: Artifacts and Credentials](https://kubespray.io/#/docs/vars?id=artifacts-and-credentials)
