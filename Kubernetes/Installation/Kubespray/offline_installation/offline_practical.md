# Kubespray: Offline установка — Практические сценарии

## Обзор этапов

Offline-установка Kubernetes через Kubespray состоит из 5 основных этапов:

| Этап | Название | Файл |
| :--- | :--- | :--- |
| **Шаг 1** | Подготовка виртуальных серверов | [step1_vm_preparation.md](./step1_vm_preparation.md) |
| **Шаг 2** | Подготовка окружения на машине с интернетом | [step2_internet_env.md](./step2_internet_env.md) |
| **Шаг 3** | Подготовка закрытого контура | [step3_offline_env.md](./step3_offline_env.md) |
| **Шаг 4** | Развертывание кластера | [step4_cluster_deploy.md](./step4_cluster_deploy.md) |
| **Шаг 5** | Настройка MetalLB и Ingress | [step5_metallb_ingress.md](./step5_metallb_ingress.md) |

## Инфраструктура

| Роль | IP | Назначение |
| :--- | :--- | :--- |
| pc-inet | 192.168.1.99 | Машина с интернетом |
| harbor | 192.168.1.100 | Harbor реестр |
| master-1-k8s | 192.168.1.101 | Control Plane + Ansible control |
| master-2-k8s | 192.168.1.102 | Control Plane |
| master-3-k8s | 192.168.1.103 | Control Plane |
| node-1-k8s | 192.168.1.104 | Worker |
| node-2-k8s | 192.168.1.105 | Worker |
| MetalLB VIP | 192.168.1.200 | Виртуальный IP для LoadBalancer |

## Предварительные требования

1. **SSH доступ:** master-1 должен иметь доступ ко всем узлам по SSH с sudo правами
2. **Harbor:** Настроенный HTTPS реестр в закрытом контуре
3. **Сеть:** Все узлы в одной подсети, свободный IP для MetalLB
4. **Пользователь:** root или пользователь с беспарольным sudo (например, `admin`)

## Быстрый старт

```bash
# 1. Подготовка VM (Шаг 1)
ansible-playbook -i inventory.ini play.yml -u admin

# 2. Загрузка артефактов (Шаг 2)
cd /opt/kuber_off/kubespray
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -e local_release_dir=/opt/kubespray-releases \
  --tags download --skip-tags upload,upgrade -b -u admin

# 3. Развертывание кластера (Шаг 4)
ansible-playbook -i inventory/offline_cluster/inventory.ini \
  cluster.yml -b -u admin

# 4. Настройка LoadBalancer (Шаг 5)
kubectl apply -f kube-manifests/
```

## Связанные документы

- **[Определения](./offline_definitions.md)** — базовые термины
- **[Основные концепции](./offline_concepts.md)** — принципы offline-установки
- **[Шаг 1: Подготовка VM](./step1_vm_preparation.md)** — подготовка серверов
- **[Шаг 2: Подготовка с интернетом](./step2_internet_env.md)** — загрузка артефактов
- **[Шаг 3: Подготовка закрытого контура](./step3_offline_env.md)** — загрузка в Harbor
- **[Шаг 4: Развертывание кластера](./step4_cluster_deploy.md)** — установка Kubernetes
- **[Шаг 5: MetalLB и Ingress](./step5_metallb_ingress.md)** — настройка LoadBalancer
- **[Troubleshooting](./troubleshooting.md)** — решение проблем
- **[Post-Install управление](./post_install_management.md)** — управление после установки
- **[Проверка кластера](./cluster_verification.md)** — валидация установки
- **[Kubespray: Управление кластером](../cluster_management.md)** — масштабирование и обновление

---

*Этот файл является частью декомпозированной документации по offline-установке Kubespray.*
