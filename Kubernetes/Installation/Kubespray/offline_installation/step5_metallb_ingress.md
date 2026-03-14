# Kubespray: Offline установка — Шаг 5: Настройка MetalLB и Ingress для Hubble

## 5.1. Создание манифестов

```bash
mkdir kube-manifests
cd kube-manifests
```

## 5.2. Настройка MetalLB

### Создание IPAddressPool

Файл: `metallb.yml`

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: ingress-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.200/32
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: ingress-l2
  namespace: metallb-system
spec:
  ipAddressPools:
  - ingress-pool
```

> **Важно:** Выберите свободный IP-адрес или пул из той же подсети, где находится кластер. В примере используется `192.168.1.200/32`.

### Применение конфигурации MetalLB

```bash
kubectl apply -f metallb.yml
```

### Проверка MetalLB

```bash
# Статус контроллера
kubectl get pods -n metallb-system

# Статус speaker
kubectl get daemonset -n metallb-system

# Проверка IPAddressPool
kubectl get ipaddresspool -n metallb-system

# Проверка L2Advertisement
kubectl get l2advertisement -n metallb-system
```

## 5.3. Настройка Ingress для Hubble UI

### Создание Ingress манифеста

Файл: `ingress-hubble-ui.yml`

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: hubble-ui
  namespace: kube-system
spec:
  ingressClassName: nginx
  rules:
  - host: hubble.k8s.domain.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: hubble-ui
            port:
              number: 80
```

### Применение Ingress

```bash
kubectl apply -f ingress-hubble-ui.yml
```

### Проверка Ingress

```bash
# Статус Ingress
kubectl get ingress -n kube-system hubble-ui

# Сервис Hubble UI
kubectl get svc -n kube-system hubble-ui

# Pod'ы ingress-nginx
kubectl get pods -n ingress-nginx
```

## 5.4. Настройка DNS

### Вариант 1: Локальный DNS сервер

Добавить A-запись в DNS сервер:

```
hubble.k8s.domain.local.  IN  A  192.168.1.200
```

### Вариант 2: Файл hosts (временное решение)

**Linux (`/etc/hosts`):**

```
192.168.1.200  hubble.k8s.domain.local
```

**Windows (`C:\Windows\System32\drivers\etc\hosts`):**

```
192.168.1.200  hubble.k8s.domain.local
```

## 5.5. Проверка доступа к Hubble UI

### Через порт-форвардинг

```bash
kubectl port-forward -n kube-system svc/hubble-ui 8080:80
```

Открыть в браузере: `http://localhost:8080`

### Через Ingress

Открыть в браузере: `http://hubble.k8s.domain.local`

**Ожидаемый результат:** Веб-интерфейс Hubble с визуализацией сетевого трафика.

## Проверка LoadBalancer

### Тестирование сервиса LoadBalancer

```bash
# Создание тестового сервиса
kubectl run nginx --image=nginx --port=80
kubectl expose pod nginx --port=80 --type=LoadBalancer

# Проверка внешнего IP
kubectl get svc nginx

# Должен появиться IP из пула MetalLB (192.168.1.200)
```

### Диагностика проблем

```bash
# Логи контроллера MetalLB
kubectl logs -n metallb-system -l app.kubernetes.io/component=controller

# Логи speaker
kubectl logs -n metallb-system -l app.kubernetes.io/component=speaker

# Статус IP allocation
kubectl get ipaddresspool ingress-pool -n metallb-system -o yaml
```

## Связанные документы

- **[Шаг 4: Развертывание кластера](./step4_cluster_deploy.md)** — установка Kubernetes
- **[Дополнительная информация](./offline_additional.md)** — troubleshooting
- **[MetalLB](../../../Networking/metallb.md)** — детальная документация по MetalLB
- **[Ingress Controllers](../../../Networking/Ingress/controllers_comparison.md)** — сравнение Ingress контроллеров

---

*Этот файл является частью декомпозированной документации по offline-установке Kubespray.*
