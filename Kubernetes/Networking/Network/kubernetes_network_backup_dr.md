# Бэкап и восстановление сетевой инфраструктуры Kubernetes

## Определения

**Network Backup** — процесс сохранения конфигурации сетевых ресурсов Kubernetes (CNI, NetworkPolicy, Service, MetalLB) для возможности восстановления после сбоя.

**Disaster Recovery (DR)** — комплекс мер по восстановлению сетевой инфраструктуры кластера после катастрофических сбоев (потеря узла, повреждение etcd, некорректное обновление CNI).

**etcd Backup** — резервное копирование ключевого хранилища Kubernetes, содержащего все объекты кластера, включая сетевые конфигурации.

**CNI Restore** — процесс восстановления работы CNI-плагина после его некорректного обновления или удаления.

---

## Основные концепции

### Что нужно бэкапить

| Компонент | Важность | Способ бэкапа |
| :--- | :--- | :--- |
| **etcd** | Критично | `etcdctl snapshot save` |
| **NetworkPolicy** | Высокая | `kubectl get networkpolicy -A -o yaml` |
| **CNI ConfigMap** | Высокая | `kubectl -n kube-system get configmap <cni-config> -o yaml` |
| **MetalLB** | Средняя | `kubectl -n metallb-system get configmap,ipaddresspool,l2advertisement -o yaml` |
| **kube-proxy ConfigMap** | Средняя | `kubectl -n kube-system get configmap kube-proxy -o yaml` |
| **Gateway API** | Средняя | `kubectl get gateway,httproute,gatewayclass -A -o yaml` |
| **CNI CRD (Cilium)** | Средняя | `kubectl get ciliumnetworkpolicy,ciliumclusterwidenetworkpolicy -A -o yaml` |
| **CNI CRD (Calico)** | Средняя | `calicoctl get globalnetworkpolicy,networkpolicy -o yaml` |

### Порядок восстановления

```
1. Восстановление etcd (если поврежден)
   └─ etcdctl snapshot restore

2. Проверка Control Plane
   └─ kubectl get nodes, pods -n kube-system

3. Восстановление CNI
   └─ kubectl apply -f <cni-manifest>

4. Восстановление NetworkPolicy
   └─ kubectl apply -f networkpolicies.yaml

5. Восстановление MetalLB/LoadBalancer
   └─ kubectl apply -f metallb-config.yaml

6. Восстановление Gateway API/Ingress
   └─ kubectl apply -f gateway-config.yaml

7. Валидация
   └─ Тест connectivity pod-to-pod, service, external
```

---

## Практические сценарии

### 1. Бэкап NetworkPolicy

```bash
# Бэкап всех NetworkPolicy
kubectl get networkpolicy -A -o yaml > backup-networkpolicies.yaml

# Бэкап CiliumNetworkPolicy
kubectl get ciliumnetworkpolicy -A -o yaml > backup-cilium-networkpolicies.yaml
kubectl get ciliumclusterwidenetworkpolicy -o yaml > backup-cilium-ccnp.yaml

# Бэкап Calico NetworkPolicy
calicoctl get globalnetworkpolicy -o yaml > backup-calico-gnp.yaml
calicoctl get networkpolicy --all-namespaces -o yaml > backup-calico-np.yaml
```

### 2. Бэкап CNI конфигурации

```bash
# Cilium
kubectl -n kube-system get configmap cilium-config -o yaml > backup-cilium-config.yaml
helm get values cilium -n kube-system > backup-cilium-helm-values.yaml

# Calico
kubectl -n kube-system get configmap calico-config -o yaml > backup-calico-config.yaml
calicoctl get installation -o yaml > backup-calico-installation.yaml

# kube-proxy
kubectl -n kube-system get configmap kube-proxy -o yaml > backup-kube-proxy-config.yaml
```

### 3. Бэкап MetalLB

```bash
# Всё конфигурации MetalLB
kubectl -n metallb-system get all,configmaps,crd -o yaml > backup-metallb.yaml

# Или по отдельности
kubectl -n metallb-system get ipaddresspool -o yaml > backup-metallb-ipaddrpool.yaml
kubectl -n metallb-system get bgppeers -o yaml > backup-metallb-bgppeers.yaml
kubectl -n metallb-system get bgpadvertisement -o yaml > backup-metallb-bgp.yaml
kubectl -n metallb-system get l2advertisement -o yaml > backup-metallb-l2.yaml
```

### 4. Бэкап Gateway API

```bash
kubectl get gatewayclass -o yaml > backup-gatewayclass.yaml
kubectl get gateway -A -o yaml > backup-gateway.yaml
kubectl get httproute -A -o yaml > backup-httproute.yaml
kubectl get referencegrant -A -o yaml > backup-referencegrant.yaml
kubectl get tlsroute -A -o yaml > backup-tlsroute.yaml
kubectl get grpcroute -A -o yaml > backup-grpcroute.yaml
```

### 5. Бэкап etcd

```bash
# Бэкап etcd (на master-узле)
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%Y%m%d-%H%M).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# Проверка бэкапа
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-*.db --write-out=table
```

### 6. Восстановление NetworkPolicy

```bash
# Применение бэкапа
kubectl apply -f backup-networkpolicies.yaml

# Проверка
kubectl get networkpolicy -A
kubectl describe networkpolicy <policy-name> -n <namespace>
```

### 7. Восстановление CNI (Cilium)

```bash
# Переустановка через Helm
helm upgrade --install cilium cilium/cilium \
  --namespace kube-system \
  --version 1.20.0 \
  --values backup-cilium-helm-values.yaml

# Или из манифеста
kubectl apply -f https://raw.githubusercontent.com/cilium/cilium/main/install/kubernetes/quick-install.yaml

# Валидация
cilium status
kubectl -n kube-system rollout status daemonset/cilium
```

### 8. Восстановление CNI (Calico)

```bash
# Переустановка через оператор
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.27.0/manifests/tigera-operator.yaml

# Восстановление конфигурации
calicoctl apply -f backup-calico-installation.yaml
calicoctl apply -f backup-calico-gnp.yaml

# Валидация
calicoctl node status
kubectl -n calico-system get pods
```

### 9. Восстановление MetalLB

```bash
# Переустановка
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.16.1/config/manifests/metallb-native.yaml

# Восстановление конфигурации
kubectl apply -f backup-metallb-ipaddrpool.yaml
kubectl apply -f backup-metallb-l2.yaml
# Или bGP
kubectl apply -f backup-metallb-bgppeers.yaml
kubectl apply -f backup-metallb-bgp.yaml

# Валидация
kubectl -n metallb-system get pods
kubectl get ipaddresspool -n metallb-system
```

### 10. Автоматизация бэкапа

```yaml
# CronJob для ежедневного бэкапа NetworkPolicy
apiVersion: batch/v1
kind: CronJob
metadata:
  name: network-backup
  namespace: kube-system
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: backup-sa
          containers:
          - name: backup
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl get networkpolicy -A -o yaml > /backup/networkpolicies-$(date +%Y%m%d).yaml
              kubectl get ciliumnetworkpolicy -A -o yaml > /backup/cilium-np-$(date +%Y%m%d).yaml
              kubectl -n kube-system get configmap kube-proxy -o yaml > /backup/kube-proxy-$(date +%Y%m%d).yaml
            volumeMounts:
            - name: backup-volume
              mountPath: /backup
          restartPolicy: OnFailure
          volumes:
          - name: backup-volume
            persistentVolumeClaim:
              claimName: backup-pvc
```

---

## Диагностика и устранение неполадок

### Типичные сценарии восстановления

| Сценарий | Симптомы | Решение |
| :--- | :--- | :--- |
| **CNI удалён** | Все поды в NotReady, нет сетевой связности | Переустановить CNI из манифеста/Helm |
| **NetworkPolicy сломана** | Трафик блокируется или разрешён всё | Восстановить из бэкапа, проверить Default Deny |
| **MetalLB не работает** | LoadBalancer сервисы не получают IP | Восстановить IPAddressPool, L2/BGP advertisement |
| **etcd повреждён** | Control Plane не работает | Восстановить из snapshot etcd |
| **kube-proxy конфигурация** | Балансировка не работает | Восстановить ConfigMap, перезапустить DaemonSet |
| **Обновление CNI сломало сеть** | Частичная связность | Откатить на предыдущую версию CNI |

### Валидация после восстановления

```bash
# 1. Статус узлов
kubectl get nodes -o wide

# 2. Статус подов kube-system
kubectl -n kube-system get pods -o wide

# 3. Тест DNS
kubectl run debug --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default

# 4. Тест pod-to-pod connectivity
kubectl run test1 --image=busybox --rm -it --restart=Never -- ping <pod-ip-on-other-node>

# 5. Тест Service
kubectl run debug --image=busybox --rm -it --restart=Never -- wget -qO- --timeout=5 http://kubernetes.default

# 6. Проверка NetworkPolicy
kubectl get networkpolicy -A
```

---

## Рекомендации для production

1. **Автоматический бэкап:** Настройте CronJob для ежедневного бэкапа NetworkPolicy и конфигураций CNI
2. **etcd snapshot:** Регулярно делайте снимки etcd (минимум раз в день)
3. **Хранение бэкапов:** Используйте отдельное хранилище (S3, NFS) для бэкапов
4. **Тестирование восстановления:** Регулярно проверяйте процедуру восстановления
5. **GitOps:** Храните конфигурации NetworkPolicy в Git для отслеживания изменений
6. **Версионирование:** Используйте теги для версий CNI и Helm-чартов

---

## См. также

- [NetworkPolicy](./network_policy.md) — сетевые политики
- [CNI и kube-proxy: роли](./cni_kube_proxy_roles.md) — компоненты сетевого стека
- [kube-proxy](./kube-proxy.md) — режимы работы

**[К списку разделов CNI](../cni_kube_proxy_roles.md)**
