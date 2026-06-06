# Kubespray: Offline установка — Шаг 5: Настройка MetalLB и Ingress

## Определения

Базовые определения и концепции MetalLB (Speaker, Controller, IPAddressPool, L2Advertisement) подробно описаны в разделе **[MetalLB — балансировщик для Bare-metal](../../../Networking/metallb.md)**.

**Ingress** — ресурс Kubernetes для маршрутизации внешнего HTTP/HTTPS-трафика к сервисам внутри кластера.

---

## Основные концепции

### Цель этапа

Настройка внешнего доступа к сервисам кластера:

- Развёртывание MetalLB для назначения внешних IP
- Создание Ingress для доступа к Hubble UI
- Настройка DNS для доменного имени Hubble

### Компоненты

| Компонент | Назначение |
| :--- | :--- |
| **MetalLB** | Балансировщик нагрузки (LoadBalancer) |
| **Ingress-nginx** | Ingress-контроллер для маршрутизации HTTP |
| **Hubble UI** | Веб-интерфейс для визуализации сетевого трафика Cilium |

### Архитектура доступа

```
Внешний пользователь → MetalLB VIP (192.168.1.200) → Ingress → Hubble UI Service → Pod
```

---

## Практические сценарии

### Создание манифестов

```bash
mkdir kube-manifests
cd kube-manifests
```

### Настройка MetalLB

#### Создание IPAddressPool и L2Advertisement

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

#### Применение конфигурации

```bash
kubectl apply -f metallb.yml
```

#### Проверка MetalLB

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

### Настройка Ingress для Hubble UI

#### Создание Ingress манифеста

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

#### Применение Ingress

```bash
kubectl apply -f ingress-hubble-ui.yml
```

#### Проверка Ingress

```bash
# Статус Ingress
kubectl get ingress -n kube-system hubble-ui

# Сервис Hubble UI
kubectl get svc -n kube-system hubble-ui

# Pod'ы ingress-nginx
kubectl get pods -n ingress-nginx
```

### Настройка DNS

#### Вариант 1: Локальный DNS сервер

Добавить A-запись в DNS-сервер:

```
hubble.k8s.domain.local.  IN  A  192.168.1.200
```

#### Вариант 2: Файл hosts (временное решение)

**Linux (`/etc/hosts`):**

```
192.168.1.200  hubble.k8s.domain.local
```

**Windows (`C:\Windows\System32\drivers\etc\hosts`):**

```
192.168.1.200  hubble.k8s.domain.local
```

### Проверка доступа к Hubble UI

#### Через порт-форвардинг

```bash
kubectl port-forward -n kube-system svc/hubble-ui 8080:80
```

Открыть в браузере: `http://localhost:8080`

#### Через Ingress

Открыть в браузере: `http://hubble.k8s.domain.local`

**Ожидаемый результат:** Веб-интерфейс Hubble с визуализацией сетевого трафика.

### Тестирование LoadBalancer

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

---

## Дополнительная информация

### Связанные темы

Развёртывание кластера описано в [шаге 4](./step4_cluster_deploy.md), решение проблем — в [troubleshooting.md](./troubleshooting.md). Детальная документация по MetalLB — в [metallb.md](../../../Networking/metallb.md), сравнение Ingress-контроллеров — в [controllers_comparison.md](../../../Networking/Ingress/controllers_comparison.md).
