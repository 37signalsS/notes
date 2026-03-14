# Kubespray: Offline установка — Шаг 2: Подготовка окружения на машине с интернетом

## 2.1. Установка зависимостей

```bash
mkdir /opt/kuber_off && cd /opt/kuber_off
apt update -y
apt install python3.12-venv -y
python3.12 -m venv venv
source venv/bin/activate
```

## 2.2. Клонирование Kubespray

```bash
git clone --branch v2.29.1 --single-branch https://github.com/kubernetes-sigs/kubespray.git
cd kubespray

# Проверка версии
git describe --tags  # Должно быть: v2.29.1
```

## 2.3. Подготовка inventory для download

```bash
cp -r /opt/kuber_off/kubespray/inventory/sample \
      /opt/kuber_off/kubespray/inventory/offline_cluster

nano /opt/kuber_off/kubespray/inventory/offline_cluster/inventory.ini
```

**Содержимое `inventory.ini`:**

```ini
[all]
pc-inet ansible_host=192.168.1.99 ip=192.168.1.99

[kube_control_plane]
pc-inet

[etcd]
pc-inet

[kube_node]
pc-inet

[k8s_cluster:children]
kube_control_plane
kube_node
```

## 2.4. Настройка переменных

### Включение аддонов

Файл: `group_vars/k8s_cluster/addons.yml`

```yaml
helm_enabled: true
ingress_nginx_enabled: true
metallb_enabled: true
```

### Основные параметры

Файл: `group_vars/k8s_cluster/k8s-cluster.yml`

```yaml
kube_owner: root
kube_proxy_remove: true

kube_network_plugin: cilium
cilium_version: "1.18.5"
kube_proxy_strict_arp: true

cluster_name: k8s.domain.local
container_manager: containerd
```

### Настройка etcd

Файл: `group_vars/all/etcd.yml`

```yaml
etcd_deployment_type: host
```

### Настройка Cilium

Файл: `group_vars/k8s_cluster/k8s-net-cilium.yml`

```yaml
cilium_mtu: "1450"
cilium_kube_proxy_replacement: true
cilium_tunnel_mode: geneve

# Hubble
cilium_enable_hubble: true
cilium_enable_hubble_ui: "{{ cilium_enable_hubble }}"
cilium_enable_hubble_metrics: true
cilium_hubble_metrics:
  - dns
  - drop
  - tcp
  - flow
  - icmp
  - http
```

### Offline переменные

Файл: `group_vars/all/offline.yml`

```yaml
---
download_run_once: true
download_localhost: true
download_keep_remote_cache: true
download_force_cache: true
download_cache_dir: /opt/kubespray-cache
```

### Прокси (если требуется)

Файл: `group_vars/all/all.yml`

```yaml
# http_proxy: ""
# https_proxy: ""
```

## 2.5. Загрузка артефактов

### Установка Python зависимостей

```bash
cd /opt/kuber_off/kubespray

pip install -r requirements.txt
```

### Создание директорий

```bash
apt install containerd -y
mkdir -p /opt/kubespray-cache/images/
mkdir /opt/kubespray-releases/
```

### Первый запуск (может завершиться ошибкой)

```bash
/opt/kuber_off/venv/bin/ansible-playbook \
  -i inventory/offline_cluster/inventory.ini \
  cluster.yml \
  -e local_release_dir=/opt/kubespray-releases \
  --tags download \
  --skip-tags upload,upgrade \
  -b -u admin
```

### Исправление ошибки с nerdctl

```bash
cp /opt/kubespray-releases/nerdctl /opt/kubespray-releases/crictl /usr/local/bin
sudo ln -sf /usr/bin/ctr /usr/local/bin/ctr
/usr/local/bin/nerdctl --version
```

### Повторный запуск

```bash
/opt/kuber_off/venv/bin/ansible-playbook \
  -i inventory/offline_cluster/inventory.ini \
  cluster.yml \
  -e local_release_dir=/opt/kubespray-releases \
  --tags download \
  --skip-tags upload,upgrade \
  -b -u admin
```

Должно завершиться успешно, без ошибок.

## 2.6. Загрузка дополнительных образов

Некоторые образы не скачиваются автоматически. Создаем скрипт для докачки:

```bash
cd /opt/
nano download_k8s_images.sh
```

**Содержимое скрипта:**

```bash
#!/bin/bash
set -e

KUBEADM_PATH="/opt/kubespray-cache/kubeadm-*-amd64"
IMAGES=$($KUBEADM_PATH config images list 2>/dev/null | grep -v "WARN" || $KUBEADM_PATH config images list)

DOWNLOAD_DIR="/opt/kubespray-cache/images"
cd "$DOWNLOAD_DIR"

for IMAGE in $IMAGES; do
    echo "Pulling: $IMAGE"
    nerdctl pull "$IMAGE"
    FILENAME=$(echo "$IMAGE" | sed 's|/|_|g; s|:|_|g').tar
    nerdctl save "$IMAGE" -o "$FILENAME"
    nerdctl rmi "$IMAGE"
    echo "Saved: $FILENAME"
done
```

**Запуск скрипта:**

```bash
chmod +x /opt/kubespray-cache/kube*
chmod +x download_k8s_images.sh
./download_k8s_images.sh
```

**Дополнительные образы:**

```bash
nerdctl pull quay.io/cilium/operator-generic:v1.18.5
nerdctl save -o /opt/kubespray-cache/images/quay.io_cilium_operator-generic_v1.18.5.tar \
  quay.io/cilium/operator-generic:v1.18.5
```

## 2.7. Загрузка Helm чарта Cilium

```bash
cp /opt/kubespray-releases/helm-3.18.4/linux-amd64/helm /usr/local/bin/
helm version

helm repo add cilium https://helm.cilium.io
helm repo update
helm pull cilium/cilium --version 1.18.5
# появится файл cilium-1.18.5.tgz
mv cilium-1.18.5.tgz /opt/cilium-1.18.5.tgz
```

## 2.8. Упаковка артефактов

```bash
tar -C /opt -czf kubespray-code.tar.gz kuber_off
tar -C /opt -czf kubespray-offline-bundle.tar.gz \
  kubespray-cache kubespray-releases cilium-1.18.5.tgz
```

**Перенос файлов на master-1-k8s (закрытый контур):**

```bash
# Копирование архивов на закрытый контур
scp kubespray-code.tar.gz kubespray-offline-bundle.tar.gz admin@192.168.1.101:/home/admin/
```

## Проверка после загрузки

**Проверка кэша образов:**

```bash
ls -lh /opt/kubespray-cache/images/*.tar | wc -l  # Должно быть 20+ образов
```

**Проверка бинарных файлов:**

```bash
/opt/kubespray-releases/helm-3.18.4/linux-amd64/helm version
/opt/kubespray-releases/nerdctl --version
```

## Связанные документы

- **[Шаг 1: Подготовка VM](./step1_vm_preparation.md)** — подготовка серверов
- **[Шаг 3: Подготовка закрытого контура](./step3_offline_env.md)** — загрузка в Harbor
- **[Шаг 4: Развертывание кластера](./step4_cluster_deploy.md)** — установка Kubernetes
- **[Kubespray: Установка](../kubespray_install/basic_concepts.md)** — базовая установка

---

*Этот файл является частью декомпозированной документации по offline-установке Kubespray.*
