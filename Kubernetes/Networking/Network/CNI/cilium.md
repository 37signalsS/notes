# Cilium: Высокопроизводительный CNI на базе eBPF

## Определения

**Cilium** — это современный плагин интерфейса сетевой связности контейнеров (CNI), спроектированный для обеспечения сетевой связности, безопасности и наблюдаемости между рабочими нагрузками. В отличие от традиционных CNI, Cilium использует технологию **eBPF** (Extended Berkeley Packet Filter) в ядре Linux для обработки пакетов.

**kube-proxy-replacement** — режим работы Cilium, при котором он полностью заменяет стандартный компонент `kube-proxy`, реализуя балансировку нагрузки сервисов (ClusterIP, NodePort, LoadBalancer) через eBPF-программы.

## Основные концепции

### Архитектура Cilium

Cilium состоит из нескольких ключевых компонентов:

- **Cilium Agent (DaemonSet):** Работает на каждом узле кластера. Управляет eBPF-программами, обрабатывает события от API-сервера и настраивает сетевые интерфейсы.
- **Cilium Operator (Deployment):** Отвечает за общекластерные задачи, такие как управление IP-адресами (IPAM) и сборку объектов Cilium. Обычно запускается в 2 экземплярах для отказоустойчивости.
- **Envoy:** Интегрированный прокси-сервер, используемый для обработки трафика на уровне L7 (HTTP, gRPC, сетевые политики уровня приложения).

### Преимущества использования Cilium

- **Высокая производительность:** Замена `iptables` на eBPF устраняет линейную деградацию производительности при росте количества сервисов (O(n) → O(1)).
- **Глубокая наблюдаемость (Hubble):** Позволяет отслеживать сетевые потоки на уровнях L3/L4 и L7 с детализацией до конкретных подов и сервисов.
- **Безопасность на уровне L7:** Возможность создания политик безопасности на основе HTTP-методов, путей и заголовков.
- **Прозрачное шифрование:** Поддержка IPsec и WireGuard для защиты трафика между узлами.

---

## Практические сценарии

### Подготовка узлов (Prerequisites)

Перед установкой Cilium необходимо настроить узлы (например, на базе Rocky Linux/Ubuntu):

1. **Отключение Swap и Firewall:**

   ```bash
   sudo swapoff -a
   sudo systemctl stop firewalld && sudo systemctl disable firewalld
   ```

2. **Загрузка модулей ядра:**

   ```bash
   cat <<EOF | sudo tee /etc/modules-load.d/cilium.conf
   overlay
   br_netfilter
   EOF
   sudo modprobe overlay
   sudo modprobe br_netfilter
   ```

3. **Настройка параметров ядра:**

   ```bash
   cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
   net.bridge.bridge-nf-call-iptables  = 1
   net.bridge.bridge-nf-call-ip6tables = 1
   net.ipv4.ip_forward                 = 1
   EOF
   sudo sysctl --system
   ```

4. **Настройка Containerd:**
   Убедитесь, что в `/etc/containerd/config.toml` параметр `SystemdCgroup` установлен в `true`:

   ```toml
   [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
     SystemdCgroup = true
   ```

### Установка кластера без kube-proxy

При использовании `kubeadm` рекомендуется исключить `kube-proxy` на этапе инициализации:

```bash
# Пример команды инициализации
sudo kubeadm init --config=kubeadm-config.yaml --skip-phases=addon/kube-proxy
```

В `kubeadm-config.yaml` в секции `ClusterConfiguration` желательно сразу указать внешний адрес API-сервера (`controlPlaneEndpoint`), который Cilium будет использовать для подключения.

### Установка Cilium через Helm

После инициализации кластера (когда ноды находятся в состоянии `NotReady`), установите Cilium:

```bash
helm install cilium cilium/cilium \
  --namespace kube-system \
  --set kubeProxyReplacement=strict \
  --set k8sServiceHost=<API_SERVER_IP> \
  --set k8sServicePort=6443 \
  --set operator.replicas=2
```

- `kubeProxyReplacement=strict`: Включает полную замену `kube-proxy`.
- `k8sServiceHost`: IP-адрес API-сервера (или балансировщика перед мастерами).

### Интеграция с Node Local DNS

Для оптимальной работы DNS рекомендуется использовать `node-local-dns`. В конфигурации `kubelet` необходимо указать адрес локального DNS-сервера (например, `169.254.25.10`), чтобы трафик DNS не покидал узел.

## Дополнительная информация

### Проверка статуса

```bash
# Проверка через CLI Cilium (требуется установка cilium-cli)
cilium status --wait

# Проверка подов в кластере
kubectl get pods -n kube-system -l k8s-app=cilium

# Проверка режима замены kube-proxy
kubectl -n kube-system exec ds/cilium -- cilium status | grep KubeProxyReplacement
```

**См. также:**

- [eBPF в Kubernetes: Замена kube-proxy](./ebpf.md)
- [Выбор CNI и внешние типы доступа](./selection_and_external_access.md)
- [CNI и kube-proxy: роли и взаимодействие](../cni_kube_proxy_roles.md)
