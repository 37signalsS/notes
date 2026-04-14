# Kubespray: Установка — Определения

## Определения

**Kubespray** — инструмент для автоматизации развертывания кластеров Kubernetes на базе Ansible. Полное описание — в [обзоре Kubespray](../overview.md).

**Inventory** — файл `inventory.ini`, определяющий хосты и их роли в кластере (control plane, worker, etcd).

**Group vars** — переменные для групп хостов в директории `group_vars/`. Основные файлы:

- `all/all.yml` — общие настройки кластера
- `k8s-cluster/k8s-cluster.yml` — параметры компонентов Kubernetes
- `etcd.yml` — настройки etcd

**Control Plane** — узлы управления кластером (ранее назывались master-узлами). Запускают API server, scheduler, controller manager.

**Worker Node** — узлы для запуска рабочих нагрузок (подов). Запускают kubelet и kube-proxy.

**etcd** — распределённое key-value хранилище для данных кластера Kubernetes.

**CNI (Container Network Interface)** — плагин для настройки сети между подами (Calico, Flannel, Cilium).

**kubeconfig** — файл конфигурации для доступа к API кластера (обычно `admin.conf`).

**Плейбуки Kubespray** — Ansible playbooks для управления кластером:

- `cluster.yml` — развертывание кластера
- `scale.yml` — добавление узлов
- `upgrade-cluster.yml` — обновление Kubernetes
- `remove-node.yml` — удаление узлов

**crictl** — CLI-утилита для взаимодействия с containerd через Container Runtime Interface.

---

## Дополнительная информация

### Связанные темы

- **[Основные концепции](./basic_concepts.md)** — компоненты конфигурации, требования, этапы установки
- **[Практические сценарии](./practical_scenarios.md)** — настройка inventory, запуск развертывания
- **[Дополнительная информация](./additional_info.md)** — действия после установки, проверка кластера
- **[Offline установка](../offline_installation/offline_definitions.md)** — развертывание в закрытом контуре
