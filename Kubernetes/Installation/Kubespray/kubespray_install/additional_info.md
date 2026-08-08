# Kubespray: Установка — Дополнительная информация

## Определения

**Артефакты (Artifacts)** — файлы конфигурации, сертификаты и ключи доступа, генерируемые или извлекаемые Kubespray в процессе развертывания. По умолчанию хранятся на целевых узлах, но могут быть скопированы на машину управления.

**`kubeconfig_localhost`** — переменная в `group_vars`, которая при значении `true` инициирует автоматическое копирование файла `admin.conf` в директорию инвентаря на машине управления.

**`artifacts_dir`** — директория на машине управления (по умолчанию `inventory/<cluster_name>/artifacts`), куда копируются манифесты и файлы конфигурации.

**`credentials_dir`** — защищенная директория (по умолчанию `inventory/<cluster_name>/credentials`), содержащая корневые сертификаты (CA), сертификаты etcd и пароли пользователей.

**CRI (Container Runtime Interface)** — интерфейс взаимодействия Kubernetes со средой выполнения контейнеров. В Kubespray по умолчанию используется **containerd**.

---

## Основные концепции

### Результаты работы установщика

После успешного выполнения плейбука `cluster.yml` формируются следующие ключевые элементы:

1.  **Инфраструктурный слой:** Установлены бинарные файлы Kubernetes, настроен `containerd` и системные сервисы (`kubelet`).
2.  **Сетевой слой:** Настроен CNI-плагин (Calico/Cilium) и обеспечена связность между подами и узлами.
3.  **Слой управления:** Сгенерирован файл `admin.conf` с правами `cluster-admin`, позволяющий полностью управлять кластером.
4.  **Безопасность:** Выпущены сертификаты со сроком действия 1 год (для компонентов) и 10 лет (для корневого CA).

### Стратегия хранения артефактов

Kubespray придерживается принципа централизованного управления: все критические данные (сертификаты, конфиги) должны дублироваться на **Control Node**. Это необходимо для:
- Возможности управления кластером без SSH-доступа к мастерам.
- Проведения операций масштабирования (`scale.yml`) и обновления (`upgrade-cluster.yml`).
- Аварийного восстановления компонентов Control Plane.

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
```

### 2. Низкоуровневая диагностика через crictl

Поскольку в Kubespray используется `containerd`, стандартные команды `docker` недоступны. Используйте `crictl` на целевых узлах.

| Задача | Команда |
| :--- | :--- |
| Список запущенных подов | `sudo crictl pods` |
| Список контейнеров | `sudo crictl ps -a` |
| Просмотр логов контейнера | `sudo crictl logs <container_id>` |
| Выполнение команды в контейнере | `sudo crictl exec -it <container_id> sh` |
| Список образов в кеше | `sudo crictl images` |
| Очистка неиспользуемых образов | `sudo crictl rmi --prune` |

### 3. Верификация системных компонентов

После установки убедитесь, что все критические сервисы запущены и синхронизированы:

```bash
# Проверка статуса узлов (Ready)
kubectl get nodes -o wide

# Проверка подов в kube-system (должны быть Running)
kubectl get pods -n kube-system

# Проверка эндпоинтов etcd
kubectl exec -n kube-system -it etcd-master-1 -- etcdctl endpoint status --cluster -w table
```

---

## Дополнительная информация

### См. также
- **[Проверка работоспособности кластера](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_verification.md)** — глубокая верификация сети и DNS.
- **[Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)** — продвинутое управление контекстами.
- **[Диагностика Runtime](../../Troubleshooting/Common_Errors/NodeUnavailability/runtime_issues.md)** — решение проблем с `containerd`.
- **[Управление сертификатами](../../Operations/certificate_management.md)** — ротация и продление TLS-ключей.

### Внешние ресурсы
- [Kubernetes CLI (crictl) User Guide](https://github.com/kubernetes-sigs/cri-tools/blob/master/docs/crictl.md)
- [Kubespray Documentation: Artifacts and Credentials](https://kubespray.io/#/docs/vars?id=artifacts-and-credentials)
