# Kubespray: Offline установка — Проверка кластера

## Определения

**Валидация кластера (Cluster Verification)** — комплекс мероприятий по проверке работоспособности всех системных компонентов после завершения установки в изолированной среде.

**Сквозная проверка (E2E Check)** — тестирование цепочки «Registry → Runtime → Pod → Network → Ingress» для подтверждения отсутствия блокировок в закрытом контуре.

---

## Основные концепции

### Критерии успешной установки в offline-режиме

В закрытом контуре критически важно убедиться, что образы загружаются исключительно из локального реестра и сетевая связность (eBPF) работает без задержек.

**Ключевые показатели:**

- **Узлы (Nodes):** все участники кластера находятся в статусе `Ready`.
- **Реестр (Registry):** системные образы загружены из локального Harbor (проверка через `crictl`).
- **etcd:** хранилище состояния консистентно и доступно со всех мастеров.
- **Сеть (Network):** Cilium показывает полную связность (Status: OK).
- **Балансировщик:** MetalLB успешно назначает VIP-адреса.
- **Инструментарий:** Hubble UI доступен и визуализирует трафик.

---

## Практические сценарии

### 1. Проверка состояния узлов и системных подов

Первичная диагностика через стандартные средства Kubernetes.

**Статус узлов:**
```bash
kubectl get nodes -o wide
# → master-1   Ready   control-plane   v1.34.3   192.168.1.101   containerd://1.7.x
```

**Статус системных компонентов:**
```bash
kubectl get pods -n kube-system
# → cilium-xxxxx           1/1     Running   0          10m
# → kube-apiserver-xxx     1/1     Running   0          12m
```

### 2. Валидация хранилища etcd

Проверка здоровья распределенной базы данных. Выполняется на любом мастере.

```bash
# Использование контейнеризированного etcdctl
export ETCDCTL_API=3
kubectl -n kube-system exec -it etcd-master-1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/ssl/etcd/ca.crt \
  --cert=/etc/kubernetes/ssl/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/ssl/etcd/healthcheck-client.key \
  endpoint health --cluster
# → https://192.168.1.101:2379 is healthy: successfully committed proposal: lasted = 10.2ms
```

### 3. Валидация сетевого плагина Cilium

Проверка eBPF-связности и статуса Hubble.

**Общий статус Cilium:**
```bash
kubectl -n kube-system exec ds/cilium -- cilium status
# → KVStore:                Ok
# → Kubernetes:             Ok 1.34 (v1.34.3)
# → Cluster health:         reachable (all nodes)
```

**Тест связности (Connectivity Test):**
Если установлена утилита `cilium` cli на master-1:
```bash
cilium connectivity test
# → connectivity test passed
```

### 4. Тестирование балансировщика и Ingress

Проверка цепочки внешнего доступа.

**Проверка пула MetalLB:**
```bash
kubectl get ipaddresspool -n metallb-system
# → primary-pool   192.168.1.200-192.168.1.210
```

**Проверка внешнего IP для Ingress-контроллера:**
```bash
kubectl get svc -n ingress-nginx ingress-nginx-controller
# → TYPE           EXTERNAL-IP
# → LoadBalancer   192.168.1.200
```

### 5. Проверка DNS внутри кластера

Валидация разрешения имен без выхода за пределы контура.

```bash
kubectl run dns-test --image=busybox:1.37 --rm -it --restart=Never -- nslookup kubernetes.default
# → Server:    10.233.0.3
# → Address:   10.233.0.3#53
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.233.0.1
```

---

## Дополнительная информация

### Чек-лист финальной приемки

- [ ] Все узлы в статусе `Ready`.
- [ ] `etcd` кластер находится в состоянии Healthy (все эндпоинты доступны).
- [ ] Отсутствуют ошибки `ImagePullBackOff` в системных неймспейсах.
- [ ] MetalLB успешно назначил IP из пула.
- [ ] Hubble UI доступен по DNS-имени (через Ingress).
- [ ] Тестовые поды успешно разрешают внутренние DNS-имена.

### См. также

- **[Шаг 5: Настройка MetalLB и Ingress](./step5_metallb_ingress.md)** — конфигурация внешнего доступа.
- **[Troubleshooting](./troubleshooting.md)** — решение проблем при неудачных проверках.
