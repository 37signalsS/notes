# Kubespray: Offline установка — Шаг 2: Подготовка окружения на машине с интернетом

## Определения

**pc-inet** — узел с доступом к интернету, выполняющий роль станции сбора (Gateway). Используется для предварительной загрузки всех артефактов Kubespray (образы контейнеров, бинарные файлы, Helm-чарты) и формирования архивов для переноса в закрытую сеть.

**download_localhost** — специальный параметр Ansible в Kubespray, который заставляет систему загружать все внешние зависимости на управляющую машину (Ansible Control Node, в данном сценарии — pc-inet) вместо того, чтобы пытаться скачать их на целевые узлы кластера.

**Артефакты (Artifacts)** — полный набор внешних зависимостей, необходимых для успешного развертывания без интернета: Python-пакеты, бинарные компоненты Kubernetes (kubeadm, kubectl), исполняемые файлы рантайма (containerd/nerdctl) и образы системных сервисов.

---

## Основные концепции

### Цель этапа

Создание автономного бандла (bundle), содержащего 100% необходимых ресурсов. Ошибка или отсутствие даже одного образа на этом этапе приведет к сбою установки в закрытом контуре.

**Ключевые группы ресурсов:**

- **Python-окружение:** все зависимости из `requirements.txt` для корректной работы Ansible.
- **Инфраструктурные бинарные файлы:** `kubeadm`, `kubectl`, `kubelet`, `helm`, `etcd`, `cni-plugins`.
- **Контейнерные образы:** образы Kubernetes (apiserver, scheduler и др.), сетевые плагины (Cilium), системные аддоны (CoreDNS, Local Path Provisioner).
- **Helm-чарты:** шаблоны для развертывания Cilium и других компонентов через Helm-контроллер.

### Архитектура хранения артефактов

На узле `pc-inet` используется стандартизированная структура директорий для упрощения последующей упаковки:

```text
/opt/
├── kuber_off/              # Корневая директория проекта
│   └── kubespray/          # Исходный код установщика (git)
├── kubespray-cache/        # Локальный кэш артефактов (создается автоматически)
│   ├── images/             # Образы контейнеров в формате .tar
│   └── kubeadm-v*          # Бинарные файлы K8s
└── kubespray-releases/     # Дополнительные инструменты (helm, nerdctl)
```

Версии компонентов должны соответствовать матрице совместимости, указанной в **[определениях offline-установки](./offline_definitions.md#версии-компонентов-базовый-гайд)**.

---

## Практические сценарии

### 1. Подготовка системы и клонирование репозитория

Выполняется на узле `pc-inet` под управлением Ubuntu 24.04.

```bash
sudo mkdir -p /opt/kuber_off && sudo chown $USER:$USER /opt/kuber_off
cd /opt/kuber_off

# Создание изолированного окружения Python 3.12
sudo apt update && sudo apt install python3.12-venv python3-pip -y
python3.12 -m venv venv
source venv/bin/activate
# → (venv) admin@pc-inet:/opt/kuber_off$

# Клонирование стабильной ветки Kubespray (v2.31.0)
git clone --branch v2.31.0 --single-branch https://github.com/kubernetes-sigs/kubespray.git
cd kubespray
# → Checking out files: 100% (2105/2105), done.
```

### 2. Установка зависимостей и настройка инвентаря

```bash
# Установка Ansible и необходимых библиотек
pip install -r requirements.txt
# → Successfully installed ansible-core-2.17.x ...

# Создание конфигурации кластера на основе шаблона
cp -r inventory/sample inventory/offline_cluster
```

**Настройка `inventory/offline_cluster/inventory.ini`:**
Для этапа загрузки укажите IP-адрес `pc-inet` (192.168.1.99) во всех группах. Это позволит Ansible «думать», что он настраивает кластер на этой машине, и скачивать образы локально.

### 3. Конфигурация переменных offline-загрузки

Создайте файл `inventory/offline_cluster/group_vars/all/offline.yml` со следующим содержимым:

```yaml
---
# Режим загрузки артефактов на локальную машину
download_run_once: true
download_localhost: true
download_format: "tarball"

# Пути для сохранения (согласуются со структурой /opt)
local_release_dir: "/opt/kubespray-releases"
download_cache_dir: "/opt/kubespray-cache"

# Версии и специфические настройки (пример для Cilium)
cilium_version: "v1.19.6"
cilium_install_with_helm: true
```

### 4. Запуск процесса загрузки

Этот шаг может занять значительное время (от 15 до 40 минут) в зависимости от скорости интернет-канала.

```bash
ansible-playbook -i inventory/offline_cluster/inventory.ini cluster.yml \
  --tags download \
  --skip-tags upload,upgrade \
  -e "@inventory/offline_cluster/group_vars/all/offline.yml" \
  -b -u admin
# → PLAY RECAP ***************** localhost : ok=145 changed=89 ...
```

### 5. Ручная загрузка дополнительных компонентов

Некоторые специфические ресурсы (Helm-чарты и дополнительные утилиты) надежнее скачать вручную.

**Загрузка Helm-чарта Cilium:**

```bash
helm repo add cilium https://helm.cilium.io
helm repo update
helm pull cilium/cilium --version 1.19.6
# → /opt/kuber_off/kubespray/cilium-1.19.6.tgz
mv cilium-1.19.6.tgz /opt/kubespray-releases/
```

**Проверка наличия образов:**
Убедитесь, что в директории `/opt/kubespray-cache/images/` присутствуют основные образы (kube-apiserver, etcd, coredns, cilium).

### 6. Формирование финальных архивов

После завершения всех проверок упакуйте данные для физического переноса (на USB или через SCP).

```bash
# Упаковка кода Kubespray (включая venv)
tar -C /opt -czf kubespray-code.tar.gz kuber_off

# Упаковка кэша и бинарных файлов
tar -C /opt -czf kubespray-offline-bundle.tar.gz \
  kubespray-cache kubespray-releases
# → Проверьте размер: du -sh *.tar.gz (ожидается ~2-4 ГБ)
```

---

## Дополнительная информация

### Типовые проблемы и решения

- **Ошибка 'python3-apt' missing:** на некоторых версиях Ubuntu Ansible требует `python3-apt` внутри venv. Решение: `pip install python-apt` или использовать системный Python с параметром `--system-site-packages`.
- **Недостаточно места в /opt:** Убедитесь, что раздел `/opt` имеет минимум 10 ГБ свободного места перед началом загрузки.
- **Блокировки реестров:** Если `gcr.io` или `quay.io` недоступны, используйте зеркала или VPN на этапе `pc-inet`.

### См. также

- **[Шаг 1: Подготовка VM](./step1_vm_preparation.md)** — SSH-доступ и настройка ОС.
- **[Шаг 3: Подготовка закрытого контура](./step3_offline_env.md)** — развертывание Harbor и импорт бандла.
- **[Базовые концепции Kubespray](../kubespray_install/basic_concepts.md)** — как работает установщик под капотом.
