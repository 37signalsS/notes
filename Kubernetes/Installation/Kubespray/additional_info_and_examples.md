# Kubespray: Дополнительная информация и примеры

## 1. Определения

**Системные поды** — поды, развертываемые в пространстве имен `kube-system` для работы кластера Kubernetes.

**Addons** — дополнительные компоненты, устанавливаемые в кластер (Ingress, MetalLB, Dashboard).

## 2. Основные концепции

### Системные компоненты

* **Control Plane (Static Pods):** `kube-apiserver-*`, `kube-controller-manager-*`, `kube-scheduler-*`.
* **Сетевые компоненты:** CNI-плагин (Flannel, Calico, Cilium), `kube-proxy-*`.
* **DNS и сервисы:** `coredns-*`, `dns-autoscaler`, `nodelocaldns-*`.
* **Дополнения (Addons):** `kubernetes-dashboard-*`, Ingress-контроллер и др.

Подробнее о пространствах имен в [документации](../../Base/namespace.md).

## 3. Практические сценарии

### 3.1. Системные поды после установки

После установки в пространстве имен `kube-system` будут развернуты системные поды. Их состав зависит от конфигурации:

* **Control Plane (Static Pods):** `kube-apiserver-*`, `kube-controller-manager-*`, `kube-scheduler-*`.
* **Сетевые компоненты:** CNI-плагин (`kube-flannel-*`, Calico, Cilium), `kube-proxy-*`.
* **DNS и сервисы:** `coredns-*`, `dns-autoscaler`, `nodelocaldns-*`.
* **Дополнения (Addons):** `kubernetes-dashboard-*`, Ingress-контроллер и др.

### 3.2. Пример: Выделенные ноды для Ingress

Этот подход использует `taints` и `tolerations` для изоляции Ingress-подов на выделенных узлах. Подробное объяснение механизма: **[Taints and Tolerations](../Scheduling/taints_and_tolerations.md)**.

**`group_vars/k8s-cluster/addons.yml`**

```yaml
# Параметры для дополнительного ПО
ingress_nginx_enabled: true
ingress_nginx_host_network: true # Прокидывает сетевой неймспейс узла внутрь контейнера
ingress_nginx_configmap: # Настройки ConfigMap для Ingress-контроллера
  server-tokens: "false" # Не показывать версию Nginx
  proxy-body-size: "2048m" # Максимальный размер тела запроса
  proxy-buffer-size: "16k" # Размер буфера для прокси
  worker-shutdown-timeout: "180s" # Таймаут для graceful shutdown воркеров
ingress_nginx_nodeselector:
  node-role.kubernetes.io/ingress: "" # Запускать поды только на нодах с этой меткой
ingress_nginx_tolerations: # Позволяет подам запускаться на "отравленных" нодах
- key: "node-role.kubernetes.io/ingress"
  operator: "Exists"
  effect: "NoSchedule"
```

**`group_vars/all/kube-ingress.yml`** (не существует по-умолчанию, создается пользователем)

```yaml
# На ноды из группы 'kube_ingress' будет установлена соответствующая метка
node_labels:
  node-role.kubernetes.io/ingress: ""

# На эти же ноды будет добавлено "отравление" (taint)
node_taints:
  - "node-role.kubernetes.io/ingress:NoSchedule"
```

### 3.3. Пример: Конфигурация MetalLB

**MetalLB** — реализация балансировщика нагрузки для bare-metal кластеров. Подробнее о компонентах, режимах работы и конфигурации см. в [MetalLB — детальная документация](../../Networking/Addons/metallb.md).

**Пример конфигурации в Kubespray:**

**`group_vars/k8s-cluster/addons.yml`**

```yaml
# Включаем MetalLB
metallb_enabled: true
metallb_speaker_enabled: true

# Определяем пулы IP-адресов
metallb_config:
  address_pools:
    primary:
      ip_range:
        - "5.75.169.149/32"
        - "91.99.78.20/32"
      # auto_assign: false # Можно отключить автоматическое назначение адресов для этого пула
```

* `metallb_enabled: true`: Включает установку MetalLB.
* `metallb_speaker_enabled: true`: Включает компонент `speaker`, который отвечает за анонсирование IP-адресов по протоколам L2 (ARP) или BGP.
* `metallb_config`: Содержит конфигурацию пулов адресов. В данном примере определен один пул `primary` с двумя IP-адресами, которые могут быть назначены сервисам типа `LoadBalancer`.

## 4. Дополнительная информация

* [Обзор Kubespray](./overview.md) — определения и основные концепции.
* [Установка и конфигурация](./installation_and_config.md) — развертывание кластера.
* [Управление кластером](./cluster_management.md) — масштабирование и обновление.
