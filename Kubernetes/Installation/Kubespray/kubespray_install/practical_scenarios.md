# Kubespray: Установка — Практические сценарии

## Определения

**Сценарий развертывания** — последовательность операций по подготовке инфраструктуры, конфигурации Ansible и запуску плейбуков для создания или изменения кластера Kubernetes.

**Кастомизация (Customization)** — адаптация параметров Kubespray (через `group_vars`) под требования безопасности, сетевой топологии или специфических версий компонентов.

**Inventory Builder** — встроенный инструмент Kubespray (`contrib/inventory_builder/inventory.py`) для автоматической генерации файла `hosts.yaml` на основе списка IP-адресов.

**Day 0/1/2 Operations** — классификация этапов жизненного цикла: подготовка (Day 0), развертывание (Day 1) и обслуживание/масштабирование/обновление (Day 2).

---

## Основные концепции

### Жизненный цикл управления
Практическая работа с Kubespray не ограничивается разовой установкой и делится на этапы:

1.  **Подготовка (Day 0):** Настройка Control Node, проверка SSH-доступа, выбор сетевого плагина и CRI.
2.  **Развертывание (Day 1):** Инициализация кластера через `cluster.yml`.
3.  **Эксплуатация (Day 2):** Добавление узлов (`scale.yml`), удаление узлов (`remove-node.yml`), обновление версии (`upgrade-cluster.yml`) и ротация сертификатов.

### Принцип декларативности
Любое изменение в кластере должно начинаться с изменения кода (инвентаря или переменных) и завершаться запуском соответствующего плейбука. Прямая модификация узлов через `kubectl` или SSH без отражения в Ansible-конфигурации нарушает принцип идемпотентности.

---

## Практические сценарии

### 1. Подготовка окружения и зависимостей (Control Node)

1.  **Установка системных пакетов** (на примере Ubuntu 24.04):
    ```bash
    sudo apt update && sudo apt install -y \
      git python3-pip python3-venv software-properties-common
    ```
2.  **Клонирование и настройка venv**:
    ```bash
    git clone https://github.com/kubernetes-sigs/kubespray.git
    cd kubespray
    python3 -m venv venv
    source venv/bin/activate
    pip install -U pip
    pip install -r requirements.txt
    ```

### 2. Настройка инвентаря и SSH-доступа

1.  **Генерация ключей и дистрибуция**:
    ```bash
    ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_kubespray
    # Копирование на все узлы (включая masters, workers, etcd)
    ssh-copy-id -i ~/.ssh/id_kubespray.pub user@10.128.0.10
    ```
2.  **Автоматическая генерация топологии**:
    ```bash
    cp -rfp inventory/sample inventory/my_cluster
    IPS=(10.128.0.10 10.128.0.11 10.128.0.12 10.128.0.13)
    CONFIG_FILE=inventory/my_cluster/hosts.yaml python3 contrib/inventory_builder/inventory.py ${IPS[@]}
    ```

### 3. Конфигурация сетевых плагинов (CNI)

Настройка выполняется в `inventory/my_cluster/group_vars/k8s_cluster/k8s-cluster.yml`.

#### Сценарий: Использование Cilium (eBPF)
```yaml
kube_network_plugin: cilium
cilium_version: "v1.16.5"
cilium_kube_proxy_replacement: true
cilium_enable_prometheus: true
```

#### Сценарий: Использование Calico (BGP/VXLAN)
```yaml
kube_network_plugin: calico
calico_network_backend: "bird" # Для BGP
# calico_network_backend: "vxlan" # Если BGP запрещен в сети
```

### 4. Операции Day 2 (Управление кластером)

#### Масштабирование (Добавление Worker-узла)
1.  Добавьте IP нового узла в `hosts.yaml`.
2.  Запустите плейбук с ограничением по новому узлу:
    ```bash
    ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
      --limit=node_name scale.yml
    ```

#### Обновление версии Kubernetes
1.  Обновите код Kubespray (`git pull` или переключение ветки).
2.  Актуализируйте `kube_version` в переменных.
3.  Запустите плейбук обновления:
    ```bash
    ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
      upgrade-cluster.yml
    ```

### 5. Очистка узлов (Reset)
Полное удаление всех следов Kubernetes, сетевых интерфейсов и правил iptables:
```bash
ansible-playbook -i inventory/my_cluster/hosts.yaml --become reset.yml
```

---

## Дополнительная информация

### Действия после развертывания
1.  **Верификация:** Детальные инструкции по проверке статуса узлов и системных подов — в руководстве **[Проверка работоспособности кластера](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_verification.md)**.
2.  **Настройка доступа:** Методы подключения через `kubectl` и работа с артефактами описаны в **[Дополнительной информации](./additional_info.md)** и **[Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)**.
3.  **HA-режим:** Если требуется высокая доступность API-сервера, см. **[Развертывание HA-кластера](../HA/index.md)**.

### См. также
- **[Определения](./definitions.md)** — глоссарий терминов и описание плейбуков.
- **[Основные концепции](./basic_concepts.md)** — архитектурные требования и системные параметры.
- **[Обзор Kubespray](../overview.md)** — матрица совместимости и возможности.

### Внешние ресурсы
- [Kubespray Official Roadmap and Day 2 Ops](https://kubespray.io/#/docs/upgrading)
- [Cilium Installation with Kubespray](https://docs.cilium.io/en/stable/installation/k8s-install-kubespray/)
