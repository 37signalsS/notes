# Kubespray: Offline установка — Практические сценарии

## Определения

Базовые термины (Offline-установка, Kubespray, Артефакты) описаны в [определениях offline-установки](./offline_definitions.md).

---

## Основные концепции

### Этапы установки

| Этап | Название | Файл |
| :--- | :--- | :--- |
| **Шаг 1** | Подготовка виртуальных серверов | [step1_vm_preparation.md](./step1_vm_preparation.md) |
| **Шаг 2** | Подготовка окружения на машине с интернетом | [step2_internet_env.md](./step2_internet_env.md) |
| **Шаг 3** | Подготовка закрытого контура | [step3_offline_env.md](./step3_offline_env.md) |
| **Шаг 4** | Развертывание кластера | [step4_cluster_deploy.md](./step4_cluster_deploy.md) |
| **Шаг 5** | Настройка MetalLB и Ingress | [step5_metallb_ingress.md](./step5_metallb_ingress.md) |

### Инфраструктура и требования

Информация о ролях узлов (IP-адреса, назначение) и предварительных требованиях (SSH, Harbor, сеть, пользователь) приведена в [подготовке виртуальных серверов](./step1_vm_preparation.md).

---

## Практические сценарии

### Быстрый старт

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

---

## Дополнительная информация

### Навигация по документации

Базовые термины описаны в [определениях offline-установки](./offline_definitions.md), принципы — в [основных концепциях](./offline_concepts.md). Детальные инструкции по этапам: [подготовка VM](./step1_vm_preparation.md), [загрузка артефактов](./step2_internet_env.md), [подготовка закрытого контура](./step3_offline_env.md), [развёртывание кластера](./step4_cluster_deploy.md), [настройка MetalLB и Ingress](./step5_metallb_ingress.md).

Валидация установки — в [проверке кластера](./cluster_verification.md), решение проблем — в [troubleshooting](./troubleshooting.md), управление после установки — в [post-install управлении](./post_install_management.md). Общее управление кластером Kubespray — в [cluster_management.md](../cluster_management.md), общий обзор — в [overview.md](../overview.md).

Смежные темы: [Harbor](../../../../Docker/Docker_registries/Harbor/overview.md), [MetalLB](../../../Networking/metallb.md), [CNI](../../../Networking/Network/CNI/definitions.md), [air-gapped кластеры](../../../Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md).
