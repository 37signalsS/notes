# 4. Конфигурация переменных (group_vars)

Это наиболее важный шаг, где определяется конфигурация кластера.

### 4.1. `inventory/my-cluster/group_vars/all/all.yml`
Здесь указывается, что `etcd` должен устанавливаться и управляться через `kubeadm`. Это критически важно для последующего [управления сертификатами](../../../Operations/certificate_management.md).

```yaml
# Управлять etcd через kubeadm
etcd_kubeadm_enabled: true
# На каждой ноде будет запущен локальный прокси на API-сервер
loadbalancer_apiserver_localhost: true
# Позволяет kubelet подгружать необходимые модули ядра
kubelet_load_modules: true
# Отключает использование kubeadm (используется классический способ установки)
kubeadm_enabled: false
# Включает read-only порт (10255) для сбора метрик без авторизации
kube_read_only_port: 10255
```

### 4.2. `inventory/my-cluster/group_vars/all/docker.yml` (опционально)
Настройки для Docker (если используется вместо containerd).

```yaml
# Устанавливает `overlay2` как драйвер хранилища для Docker
docker_storage_options: -s overlay2
```

### 4.3. `inventory/my-cluster/group_vars/all/download.yml`
Оптимизация загрузки артефактов.

```yaml
# Оптимизация загрузки: файлы и образы скачиваются один раз на один узел,
# а затем копируются на остальные узлы кластера.
download_run_once: true
```

### 4.4. `inventory/my-cluster/group_vars/etcd.yml`
Настройки для компонента etcd.

```yaml
# Уменьшает количество записей в журнале операций, хранимых в памяти,
# для снижения потребления памяти etcd.
etcd_snapshot_count: "5000"
# Устанавливает приоритет I/O для etcd
etcd_ionice: '-c2 -n0'
# Лимит памяти для etcd (0 - без ограничений)
etcd_memory_limit: 0
```

### 4.5. `inventory/my-cluster/group_vars/k8s_cluster/k8s-cluster.yml`
Основные параметры кластера.

```yaml
# Версия Kubernetes (укажите актуальную стабильную версию)
kube_version: v1.31.0

# Среда выполнения контейнеров. Docker устарел, используем containerd
container_manager: containerd

# Сетевой CNI-плагин. Рекомендуется Calico.
kube_network_plugin: calico

# Сеть для сервисов типа ClusterIP
kube_service_addresses: 10.232.0.0/16
# Сеть для подов
kube_pods_subnet: 10.233.0.0/16

# Режим работы kube-proxy. IPVS производительнее iptables
kube_proxy_mode: ipvs

# Имя кластера
cluster_name: k8s-cluster

# Отключаем небезопасный порт API-сервера
kube_apiserver_insecure_port: 0

# Отключаем OIDC и basic auth, оставляем только токен
kube_oidc_auth: false
kube_basic_auth: false

# Копирование kubeconfig на локальную машину для управления кластером
kubeconfig_localhost: true
kubectl_localhost: true

# Включаем аутентификацию и авторизацию kubelet через вебхуки по токену
kubelet_authentication_token_webhook: true
kubelet_authorization_mode_webhook: true

# Включить локальный кеширующий DNS на каждом узле для ускорения DNS-запросов
enable_nodelocaldns: true

# Принудительная регенерация сертификатов при необходимости
# (полезно при обновлениях)
auto_renew_certificates: true
```

### 4.6. `inventory/my-cluster/group_vars/k8s_cluster/k8s-net-calico.yml` (или `k8s-net-flannel.yml`)
Настройки для сетевого плагина.

**Для Calico:**
```yaml
# Режим инкапсуляции трафика между узлами.
# IPIP - производительный режим для сетей, где узлы находятся в одном L2-домене.
# Для VXLAN укажите 'VXLAN'.
calico_ipip_mode: CrossSubnet
```

**Для Flannel:**
```yaml
# Указываем бэкенд для Flannel. host-gw - самый быстрый и простой режим,
# так как он создает статические маршруты между узлами в одной L2-сети.
flannel_backend_type: "host-gw"
# Указываем Flannel, на каком сетевом интерфейсе работать.
# Он выберет тот интерфейс, IP-адрес которого совпадет с регулярным выражением.
flannel_interface_regexp: '192\.168\.1\.\d{1,3}'
```
