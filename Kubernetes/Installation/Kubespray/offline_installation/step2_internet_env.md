# Kubespray: Offline установка — Шаг 2: Подготовка окружения на машине с интернетом

## Определения

**pc-inet** — узел с доступом к интернету, используемый для предварительной загрузки артефактов Kubespray (образы, бинарные файлы, Helm-чарты) и подготовки архивов для переноса.

**download_localhost** — переменная Kubespray, указывающая Ansible загружать артефакты на управляющую машину (в данном случае pc-inet) вместо целевых узлов кластера.

**Артефакты Kubespray** — полный набор зависимостей (бинарные файлы, образы, чарты), необходимых для работы установщика. Общее определение приведено в **[определениях offline-установки](./offline_definitions.md)**.

---

## Основные концепции

### Цель этапа

Создание полной копии всех необходимых ресурсов на машине с интернетом. Это критически важный этап, так как отсутствие даже одного образа в закрытом контуре может остановить процесс развертывания.

**Загружаемые компоненты:**

- **Python-зависимости:** библиотеки, необходимые для работы Ansible и Kubespray.
- **Бинарные файлы:** компоненты Kubernetes (kubeadm, kubectl), инструменты контейнеризации (nerdctl, crictl) и менеджер чартов (helm).
- **Образы контейнеров:** системные компоненты K8s, сетевой плагин Cilium и дополнительные аддоны.
- **Helm-чарты:** шаблоны развертывания для Cilium и других сервисов.

### Структура рабочих директорий

Для удобства упаковки и переноса используется следующая структура на pc-inet:

```text
/opt/
├── kuber_off/              # Основная рабочая директория
│   └── kubespray/          # Клонированный репозиторий установщика
├── kubespray-cache/        # Локальный кэш Kubespray
│   ├── images/             # Сохранённые образы контейнеров в формате .tar
│   └── kubeadm-*           # Бинарные файлы Kubernetes
└── kubespray-releases/     # Дополнительные бинарные файлы (helm, nerdctl)
```

Версии всех используемых компонентов зафиксированы в **[SSoT: Определения](./offline_definitions.md#версии-компонентов-базовый-гайд)**.

---

## Практические сценарии

### 1. Подготовка окружения и клонирование Kubespray

```bash
mkdir /opt/kuber_off && cd /opt/kuber_off

# Установка виртуального окружения Python
sudo apt update -y && sudo apt install python3.12-venv -y
python3.12 -m venv venv
source venv/bin/activate

# Клонирование стабильной версии (v2.29.1)
git clone --branch v2.29.1 --single-branch https://github.com/kubernetes-sigs/kubespray.git
cd kubespray
```

### 2. Настройка конфигурации для загрузки (download)

Для загрузки артефактов создается временный inventory, где pc-inet выступает во всех ролях.

**Создание inventory:**

```bash
cp -r inventory/sample inventory/offline_cluster
```

**Редактирование inventory.ini:**
Укажите IP-адрес pc-inet для всех групп узлов.

**Настройка переменных offline-режима:**
В файле `inventory/offline_cluster/group_vars/all/offline.yml` необходимо установить параметры кэширования, описанные в **[основных концепциях](./offline_concepts.md#справочник-переменных-kubespray-для-offline-режима)**.

### 3. Загрузка артефактов через Ansible

**Установка зависимостей:**

```bash
pip install -r requirements.txt
```

**Запуск процесса загрузки:**

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  -e local_release_dir=/opt/kubespray-releases \
  --tags download \
  --skip-tags upload,upgrade \
  -b -u admin
```

### 4. Докачка недостающих образов и чартов

Некоторые образы (например, специфичные для Cilium или текущей версии kubeadm) могут не скачаться автоматически.

**Загрузка образов K8s через скрипт:**
Используйте `kubeadm config images list` для получения списка и `nerdctl save` для сохранения их в `/opt/kubespray-cache/images/`.

**Загрузка Helm-чарта Cilium:**

```bash
helm repo add cilium https://helm.cilium.io
helm repo update
helm pull cilium/cilium --version 1.18.5
mv cilium-1.18.5.tgz /opt/
```

### 5. Упаковка для переноса

После завершения загрузки все данные упаковываются в архивы для передачи в закрытый контур.

```bash
tar -C /opt -czf kubespray-code.tar.gz kuber_off
tar -C /opt -czf kubespray-offline-bundle.tar.gz \
  kubespray-cache kubespray-releases cilium-1.18.5.tgz
```

---

## Дополнительная информация

### Типовые проблемы

- **Ошибка nerdctl:** если бинарный файл не найден, убедитесь, что он скопирован в `/usr/local/bin` и создана символьная ссылка на `ctr`.
- **Изменение Digest:** при переносе образов в локальный реестр SHA-хеш может измениться. Решение описано в **[Troubleshooting: Проблема Cilium digest](./troubleshooting.md#2-проблема-cilium-несовпадение-sha-digest)**.

### Связанные темы

- **[Шаг 1: Подготовка VM](./step1_vm_preparation.md)** — предыдущий этап.
- **[Шаг 3: Подготовка закрытого контура](./step3_offline_env.md)** — следующий этап (развертывание Harbor).
- **[Базовые концепции Kubespray](../kubespray_install/basic_concepts.md)** — общая логика работы инструмента.
