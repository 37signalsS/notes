# Kubespray: Offline установка — Шаг 3: Подготовка закрытого контура

## 3.1. Распаковка артефактов

**На master-1-k8s:**

```bash
tar -xzf /home/admin/kubespray-code.tar.gz -C /opt/
tar -xzf /home/admin/kubespray-offline-bundle.tar.gz -C /opt/

cp /opt/kubespray-releases/crictl /opt/kubespray-releases/nerdctl /usr/local/bin
/usr/local/bin/nerdctl --version
/usr/local/bin/crictl --version
```

## 3.2. Загрузка образов в Harbor

### Установка Docker

```bash
apt install docker.io -y
systemctl enable docker --now
```

### Настройка Harbor

1. Войти в веб-интерфейс Harbor
2. Создать проект `k8s` (**публичный**)
3. Создать проект `helm` (приватный)

> **Важно:** Проект `k8s` должен быть публичным, так как containerd не считывает логин/пароль из конфига автоматически.

### Переменные окружения

```bash
export HARBOR="harbor.domain.local"
export PROJECT="k8s"
export IMG_DIR="/opt/kubespray-cache/images"
```

### Авторизация в Harbor

```bash
docker login $HARBOR
# Если x509 ошибка — проблема с сертификатами Harbor
```

### Загрузка образов в локальный Docker

```bash
cd $IMG_DIR

for f in *.tar; do
  echo "Loading $f"
  docker load -i "$f"
done
```

### Тегирование и push образов

```bash
docker images --format '{{.Repository}}:{{.Tag}}' \
  | grep -E '^(quay\.io|registry\.k8s\.io|docker\.io|gcr\.io)/|^nginx:' \
  | while read img; do
      if [[ "$img" == nginx:* ]]; then
        img="docker.io/library/${img}"
      fi
      new="${HARBOR}/${PROJECT}/${img}"
      echo "TAG  $img -> $new"
      docker tag "$img" "$new"
      echo "PUSH $new"
      docker push "$new"
    done
```

### Push всех образов в Harbor

```bash
docker images --format '{{.Repository}}:{{.Tag}}' \
  | grep -E "^${HARBOR}/${PROJECT}/(quay\.io|registry\.k8s\.io|docker\.io|gcr\.io)/" \
  | while read img; do
      echo "PUSH $img"
      docker push "$img"
    done
```

**Итог:** Должно получиться ~21 образ в Harbor.

## 3.3. Загрузка Helm чарта в Harbor

### Установка Helm

```bash
cp /opt/kubespray-releases/helm-3.18.4/linux-amd64/helm /usr/local/bin/
helm version
```

### Авторизация и push

```bash
helm registry login $HARBOR
helm push /opt/cilium-1.18.5.tgz oci://$HARBOR/helm
```

## 3.4. Настройка inventory для offline кластера

### Редактирование inventory.ini

```bash
nano /opt/kuber_off/kubespray/inventory/offline_cluster/inventory.ini
```

**Содержимое:**

```ini
[all]
master-1-k8s    ansible_host=192.168.1.101
master-2-k8s    ansible_host=192.168.1.102
master-3-k8s    ansible_host=192.168.1.103
node-1-k8s      ansible_host=192.168.1.104
node-2-k8s      ansible_host=192.168.1.105

[kube_control_plane]
master-1-k8s
master-2-k8s
master-3-k8s

[kube_node]
node-1-k8s
node-2-k8s

[etcd]
master-1-k8s

[k8s_cluster:children]
kube_control_plane
kube_node
```

### Настройка репозиториев

Файл: `group_vars/all/offline.yml`

```yaml
registry_host: "harbor.domain.local"
kube_image_repo: "{{ registry_host }}/k8s/registry.k8s.io"
gcr_image_repo: "{{ registry_host }}/k8s/gcr.io"
docker_image_repo: "{{ registry_host }}/k8s/docker.io"
quay_image_repo: "{{ registry_host }}/k8s/quay.io"

# Для Cilium через OCI
cilium_install_extra_flags: "--repository oci://{{registry_host}}/helm/cilium"
```

### Аутентификация containerd

Файл: `group_vars/all/containerd.yml`

```yaml
containerd_registry_auth:
  - registry: harbor.domain.local
    prefix: harbor.domain.local
    username: admin
    password: password_ot_harbor
```

### Отключение проверки digest

Файл: `group_vars/k8s_cluster/k8s-net-cilium.yml`

```yaml
cilium_extra_values:
  image:
    useDigest: false
    digest: ""
  operator:
    image:
      useDigest: false
      digest: ""
  envoy:
    image:
      useDigest: false
      digest: ""
  hubble:
    relay:
      image:
        useDigest: false
        digest: ""
    ui:
      backend:
        image:
          useDigest: false
          digest: ""
      frontend:
        image:
          useDigest: false
          digest: ""
```

## Проверка после настройки

**Проверка Harbor:**

```bash
# Проверка доступности репозитория
curl -k https://harbor.domain.local/api/v2.0/projects/k8s/repositories

# Проверка количества образов
docker images | grep harbor.domain.local/k8s | wc -l
```

**Проверка Helm чарта:**

```bash
helm search repo cilium --versions | grep 1.18.5
```

**Проверка inventory:**

```bash
cd /opt/kuber_off/kubespray
ansible-playbook -i inventory/offline_cluster/inventory.ini --list-hosts all
```

## Связанные документы

- **[Шаг 2: Подготовка окружения с интернетом](./step2_internet_env.md)** — загрузка артефактов
- **[Шаг 4: Развертывание кластера](./step4_cluster_deploy.md)** — установка Kubernetes
- **[Harbor: Обзор](../../../../Docker/Docker_registries/Harbor/overview.md)** — информация о Harbor
- **[Kubespray: Конфигурация](./offline_concepts.md)** — переменные offline-режима

