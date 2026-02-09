# Kubespray: Дополнительная информация и примеры

## 4. Дополнительная информация

### 4.1. Системные поды после установки

После установки в пространстве имен `kube-system` будут развернуты системные поды. Их состав зависит от конфигурации.

* **Control Plane (Static Pods):** `kube-apiserver-*`, `kube-controller-manager-*`, `kube-scheduler-*`.
* **Сетевые компоненты:** `kube-flannel-*` (или Calico, Cilium), `kube-proxy-*`.
* **DNS и сервисы:** `coredns-*`, `dns-autoscaler`, `nodelocaldns-*`.
* **Дополнения (Addons):** `kubernetes-dashboard-*`, `nginx-proxy-ingress-*` и др.

Подробнее о пространствах имен и о том, как Kubespray их использует, можно прочитать в документе [о пространствах имен](../Base/namespace.md#namespaces-и-kubespray).

### 4.2. Пример: Выделенные ноды для Ingress

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

### 4.3. Пример: Конфигурация MetalLB

**MetalLB** — это реализация балансировщика нагрузки для bare-metal кластеров, которая позволяет использовать сервисы типа `LoadBalancer`.

**`group_vars/k8s-cluster/addons.yml`**

```yaml
# Включаем MetalLB
metallb_enabled: true
metallb_speaker_enabled: true

# Определяем пулы IP-адресов, которые MetalLB будет использовать
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
