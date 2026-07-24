# Kubespray: Установка — Практические сценарии

## Определения

**Сценарий развертывания** — последовательная последовательность действий по подготовке инфраструктуры, конфигурации Ansible и запуску плейбуков для создания функционирующего кластера Kubernetes.

**Кастомизация переменных** — процесс адаптации стандартных шаблонов Kubespray под конкретные требования (выбор сетевого плагина, версии компонентов, параметров безопасности).

---

## Основные концепции

Практическая работа с Kubespray строится на жизненном цикле "Подготовка → Конфигурация → Применение":

1. **Подготовка:** настройка машины управления и обеспечение сетевой связности с целевыми узлами.
2. **Конфигурация:** декларативное описание топологии в инвентаре и параметров кластера в `group_vars`.
3. **Применение:** запуск основного плейбука `cluster.yml` для развертывания или специфических плейбуков для управления жизненным циклом.

---

## Практические сценарии

### Сценарий 1: Подготовка окружения и зависимостей

1. **Установка системных пакетов** на машине управления (Ubuntu/Debian):

   ```bash
   sudo apt update
   sudo apt install -y git python3-pip python3-venv software-properties-common
   ```

2. **Клонирование репозитория** Kubespray:

   ```bash
   git clone https://github.com/kubernetes-sigs/kubespray.git
   cd kubespray
   ```

3. **Создание и активация виртуального окружения** (рекомендуемый метод):

   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

### Сценарий 2: Обеспечение сетевой связности (SSH)

Машина управления должна подключаться к узлам по SSH с правами `sudo` без ввода пароля.

```bash
# Генерация ключа на машине управления
ssh-keygen -t ed25519

# Копирование ключа на все целевые узлы
ssh-copy-id -i ~/.ssh/id_ed25519.pub user@target-node-ip
```

### Сценарий 3: Настройка топологии кластера (Inventory)

1. **Создание инвентаря на основе шаблона:**

   ```bash
   cp -rfp inventory/sample inventory/my_cluster
   ```

2. **Генерация инвентаря** с помощью скрипта-строителя:

   ```bash
   # Список IP-адресов будущих узлов кластера
   IPS=(10.128.0.10 10.128.0.11 10.128.0.12 10.128.0.13)
   CONFIG_FILE=inventory/my_cluster/hosts.yaml python3 contrib/inventory_builder/inventory.py ${IPS[@]}
   ```

3. **Верификация ролей** в `inventory/my_cluster/hosts.yaml`:
   Убедитесь, что группы `kube_control_plane` и `etcd` содержат нечетное количество узлов (минимум 3 для обеспечения отказоустойчивости в Production).

### Сценарий 4: Кастомизация параметров (group_vars)

#### Файл `inventory/my_cluster/group_vars/all/all.yml`

- `bin_dir: /usr/local/bin` — путь для установки бинарных файлов.
- `http_proxy` / `https_proxy` — настроить при работе через прокси.
- `kubeconfig_localhost: true` — автоматически копировать `admin.conf` на машину управления.

#### Файл `inventory/my_cluster/group_vars/k8s_cluster/k8s-cluster.yml`

- `kube_version: v1.32.1` — целевая версия Kubernetes.
- `kube_network_plugin: calico` — сетевой плагин (варианты: calico, cilium, flannel).
- `container_manager: containerd` — современный стандарт среды выполнения.
- `dns_mode: coredns` — основной сервис разрешения имен.

### Сценарий 5: Запуск развертывания

Запуск основного плейбука. Флаг `--become` необходим для выполнения задач с правами `root`.

```bash
ansible-playbook -i inventory/my_cluster/hosts.yaml --become cluster.yml
```

### Сценарий 6: Очистка узлов (Сброс кластера)

Если требуется полностью удалить компоненты Kubernetes и вернуть узлы в исходное состояние:

```bash
ansible-playbook -i inventory/my_cluster/hosts.yaml --become reset.yml
```

---

## Дополнительная информация

### Действия после установки

1. **Верификация:** детальные инструкции по проверке статуса узлов и системных подов — в руководстве **[Проверка работоспособности кластера](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_verification.md)**.
2. **Настройка доступа:** методы подключения через `kubectl` и работа с артефактами описаны в **[Дополнительной информации](./additional_info.md)** и **[Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)**.
3. **Диагностика:** инструменты низкоуровневой отладки (crictl) — в разделе **[Диагностика Runtime](../../Troubleshooting/Common_Errors/NodeUnavailability/runtime_issues.md)**.

### См. также

- **[Определения](./definitions.md)** — глоссарий и описание плейбуков.
- **[Основные концепции](./basic_concepts.md)** — архитектурные требования и системные параметры.
- **[Обзор Kubespray](../overview.md)** — матрица совместимости и возможности.
