# Kubespray: Offline установка — Шаг 4: Развёртывание кластера

## Определения

**Развёртывание кластера (Cluster Deployment)** — процесс автоматизированной установки и настройки всех системных компонентов Kubernetes (control plane, worker nodes, сетевой плагин, etcd) на целевых узлах с использованием Ansible-плейбуков.

**kubeconfig (admin.conf)** — конфигурационный файл, содержащий данные для аутентификации и адрес API-сервера, используемый утилитой `kubectl` для управления кластером.

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

---

## Практические сценарии

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

**Проверка Cilium (сетевого плагина):**
```bash
# Если установлена утилита cilium cli
cilium status
# → KVStore:                Ok
# → Kubernetes:             Ok 1.34 (v1.34.3) [v1.34.3]
```

---

## Дополнительная информация

### Типовые проблемы

- **Ошибка сертификатов Harbor:** если Harbor использует самоподписанный сертификат, убедитесь, что он добавлен в доверенные на всех узлах (см. **[Сертификаты Harbor](../../../../Docker/Docker_registries/Harbor/certificates.md)**).
- **Сбой etcd:** часто возникает из-за медленных дисков (HDD) или высокой задержки сети. Проверьте задержки командой `ping` между мастерами.

### См. также

- **[Шаг 5: Настройка MetalLB и Ingress](./step5_metallb_ingress.md)** — публикация сервисов во внешнюю сеть.
- **[Проверка кластера](./cluster_verification.md)** — глубокое тестирование сетевой связности и DNS.
- **[Troubleshooting](./troubleshooting.md)** — решения специфических ошибок offline-режима.
