# Kubespray: Установка и конфигурация кластера

## 1. Определения

**Kubespray** — инструмент для автоматизации развертывания кластеров Kubernetes на базе Ansible. Подробнее в [обзоре](./overview.md).

## 2. Основные концепции

### Компоненты конфигурации

* **Inventory** — файл `inventory.ini`, определяющий хосты и их роли в кластере.
* **Group vars** — переменные для групп хостов в директории `group_vars`:
  * `all/` — общие переменные для всех хостов.
  * `k8s-cluster/` — переменные для компонентов Kubernetes.
* **Плейбуки** — основной плейбук `cluster.yml` для развертывания.

### Требования

* Python 3 + pip
* Ansible (устанавливается через `requirements.txt`)
* SSH-доступ до целевых хостов

## 3. Процесс установки

Процесс установки с помощью Kubespray разбит на несколько этапов. Следуйте руководствам для каждого шага:

1.  [**Предварительные требования к узлам**](./InstallationGuide/node_prerequisites.md) — подготовка серверов для кластера.
2.  [**Установка Kubespray и зависимостей**](./InstallationGuide/kubespray_setup.md) — клонирование репозитория и установка необходимых пакетов.
3.  [**Конфигурация Inventory**](./InstallationGuide/inventory_configuration.md) — определение состава кластера.
4.  [**Конфигурация переменных (group_vars)**](./InstallationGuide/group_vars_configuration.md) — настройка параметров Kubernetes и компонентов.
5.  [**Запуск развертывания**](./InstallationGuide/deployment.md) — выполнение Ansible playbook.
6.  [**Действия после установки**](./InstallationGuide/post_installation.md) — проверка кластера, работа с `crictl` и `kubeconfig`.

## 4. Дополнительная информация

* [Обзор Kubespray](./overview.md) — определения и основные концепции.
* [Управление кластером](./cluster_management.md) — масштабирование и обновление.
* [Дополнительные примеры](./additional_info_and_examples.md) — примеры конфигурации.
