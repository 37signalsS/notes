# Сетевые настройки в Rancher

## Определения

**CNI (Container Network Interface)** — плагин, обеспечивающий сетевую связность подов в Kubernetes. В Rancher доступны: Canal (по умолчанию), Calico, Cilium, Flannel, Weave, Multus.

**Canal** — CNI по умолчанию в RKE2, объединяющий Flannel (для overlay-сети) и Calico (для Network Policies). FIPS-совместимый, рекомендуется для большинства сред.

**Ingress Controller** — компонент, маршрутизирующий HTTP/HTTPS-трафик извне к сервисам внутри кластера. В RKE2 до K8s v1.35 — ingress-nginx; начиная с v1.36 — Traefik.

**Gateway API** — современный стандарт маршрутизации в Kubernetes ( замена Ingress). Поддерживается cert-manager v1.20+ и рекомендуется для новых установок.

**CoreDNS** — кластерный DNS-сервис, обеспечивающий разрешение имен сервисов (например, `my-svc.my-namespace.svc.cluster.local`).

**kube-proxy** — компонент, управляющий правилами iptables/ipvs для балансировки трафика к Service.

## Базовые концепции

### Архитектура сети в Rancher-кластере

```
Внешний трафик → Load Balancer → Ingress Controller → Service → Pod
                                   ↑
                              Traefik/nginx
```

**Сетевой стек RKE2:**
- **CoreDNS** — DNS для сервисов и подов.
- **CNI (Canal)** — overlay-сеть для подов (10.42.0.0/16).
- **kube-proxy** — балансировка через iptables/ipvs.
- **Ingress Controller** — маршрутизация HTTP/HTTPS.

### Типы Service в Rancher

| Тип | Назначение | Пример |
| :--- | :--- | :--- |
| **ClusterIP** | Внутренний доступ в пределах кластера | `type: ClusterIP` |
| **NodePort** | Доступ через порт на каждом узле | `type: NodePort` |
| **LoadBalancer** | Доступ через внешний LB (облачный/ bare-metal) | `type: LoadBalancer` |
| **ExternalName** | CNAME-запись на внешний сервис | `type: ExternalName` |

### DNS в Rancher

**Формат имени сервиса:**
```
<service-name>.<namespace>.svc.cluster.local
```

**Примеры:**
```bash
# Доступ к сервису в том же namespace
curl http://my-service

# Доступ к сервису в другом namespace
curl http://my-service.other-namespace

# Полное FQDN
curl http://my-service.other-namespace.svc.cluster.local
```

### Ingress Controller в RKE2

| Версия K8s | Ingress по умолчанию | Примечание |
| :--- | :--- | :--- |
| до v1.35 | ingress-nginx | Классический NGINX |
| v1.36+ | Traefik | Рекомендуется для новых кластеров |

**Важно:** при обновлении RKE2 существующие Ingress-ресурсы сохраняют свой controller (для обратной совместимости).

## Практические сценарии

### Шаг 1: Проверка сетевых компонентов

```bash
# CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
# → coredns-<hash>   1/1   Running

# kube-proxy
kubectl -n kube-system get pods -l k8s-app=kube-proxy

# CNI (Canal)
kubectl -n kube-system get pods -l k8s-app=canal
# → canal-<hash>   2/2   Running

# Ingress Controller
kubectl -n kube-system get pods -l app.kubernetes.io/name=ingress-nginx
# или
kubectl -n kube-system get pods -l app.kubernetes.io/name=traefik
```

### Шаг 2: Создание Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app
  namespace: prod
spec:
  type: ClusterIP
  selector:
    app: my-app
  ports:
    - port: 80
      targetPort: 8080
      protocol: TCP
```

```bash
# Проверка
kubectl get svc my-app -n prod
# → NAME     TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)   AGE
# → my-app   ClusterIP   10.43.100.50   <none>        80/TCP    5m

# Тестирование DNS
kubectl run test --rm -it --image=busybox -- wget -qO- http://my-app.prod
# → HTML-ответ
```

### Шаг 3: Создание Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app
  namespace: prod
  annotations:
    # Для ingress-nginx:
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    # Для Traefik:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
spec:
  ingressClassName: nginx   # или traefik
  tls:
    - hosts:
        - my-app.example.com
      secretName: my-app-tls
  rules:
    - host: my-app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: my-app
                port:
                  number: 80
```

```bash
# Проверка
kubectl get ingress my-app -n prod
# → NAME     CLASS   HOSTS                 ADDRESS         PORTS     AGE
# → my-app   nginx   my-app.example.com   10.0.100.50     80, 443   5m

# Тестирование
curl -H "Host: my-app.example.com" http://<ingress-ip>/health
```

### Шаг 4: Настройка NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend
  namespace: prod
spec:
  podSelector:
    matchLabels:
      app: my-app
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: frontend
      ports:
        - port: 8080
          protocol: TCP
  egress:
    - to:
        - namespaceSelector: {}
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
```

```bash
# Проверка
kubectl get networkpolicy allow-frontend -n prod
```

### Шаг 5: Проверка DNS

```bash
# Разрешение имени сервиса
kubectl run dns-test --rm -it --image=busybox -- nslookup my-app.prod
# → Name:      my-app.prod.svc.cluster.local
# → Address:   10.43.100.50

# Проверка CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50
```

### Шаг 6: Проверка сетевой связности

```bash
# Между подами
kubectl run test --rm -it --image=busybox -- wget -qO- http://my-app.prod:8080

# Из одного namespace в другой
kubectl run test --rm -it --image=busybox -n frontend -- wget -qO- http://my-app.prod:8080

# Проверка NetworkPolicy
kubectl run test --rm -it --image=busybox -n default -- wget -qO- --timeout=3 http://my-app.prod:8080
# → должен завершиться с таймаутом (если NetworkPolicy блокирует)
```

### Шаг 7: Переключение на Traefik (RKE2 v1.36+)

```yaml
# Конфигурация RKE2 (/etc/rancher/rke2/config.yaml)
# При новой установке Traefik используется по умолчанию

# Для существующих кластеров:
# 1. Удалите ingress-nginx
kubectl -n kube-system delete ds ingress-nginx

# 2. Установите Traefik
helm install traefik traefik/traefik \
  --namespace kube-system \
  --set providers.kubernetesCRD.allowCrossNamespace=true
```

### Шаг 8: Публикация Grafana через Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana
  namespace: cattle-monitoring-system
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - grafana.example.com
      secretName: grafana-tls
  rules:
    - host: grafana.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: rancher-monitoring-grafana
                port:
                  number: 80
```

## Диагностика и устранение неполадок

### DNS не разрешается

```bash
# Проверка CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50

# Проверка CoreDNS конфигурации
kubectl -n kube-system get configmap coredns -o yaml

# Тестирование с different DNS server
kubectl run test --rm -it --image=busybox -- nslookup kubernetes.default.svc.cluster.local 10.43.0.10
```

### Ingress не работает

```bash
# Проверка Ingress Controller
kubectl -n kube-system get pods -l app.kubernetes.io/name=ingress-nginx

# Проверка Ingress ресурса
kubectl describe ingress <name> -n <namespace>
# → Events: правильный ingressClassName? TLS secret существует?

# Проверка Service
kubectl get svc <name> -n <namespace>
# → ENDPOINTS: есть ли IP-адреса?

# Проверка Pod
kubectl get pods -l app=<name> -n <namespace>
# → Ready: 1/1?
```

### NetworkPolicy блокирует легитимный трафик

```bash
# Просмотр всех NetworkPolicy
kubectl get networkpolicy -A

# Временное удаление (для теста)
kubectl delete networkpolicy <name> -n <namespace>
# → если заработало — проблема в NetworkPolicy

# Проверка правил
kubectl describe networkpolicy <name> -n <namespace>
```

### Service не доступен

```bash
# Проверка Endpoints
kubectl get endpoints <svc-name> -n <namespace>
# → Endpoints: <ip>:<port> (норма), <none> (проблема)

# Проверка(selector)
kubectl get pods -l app=<name> -n <namespace>
# → есть ли поды с нужными лейблами?

# Проверка порта
kubectl describe svc <svc-name> -n <namespace>
# → Port: совпадает с targetPort в Deployment?
```

## Дополнительная информация

### Рекомендации по сети

1. **Canal по умолчанию:** для большинства сред достаточно Canal. Используйте Cilium, если нужен eBPF и L7-политики.
2. **NetworkPolicy:** всегда создавайте политики для production-namespace.
3. **DNS:** проверяйте DNS после установки кластера (crucial для сервисов).
4. **Ingress:** переходите на Traefik для новых кластеров (RKE2 v1.36+).
5. **TLS:** используйте cert-manager для автоматического выпуска сертификатов.

### Связанные темы

- [Установка Rancher Server](./rancher_installation.md) — сетевые требования.
- [RKE: CNI](./rancher_rke.md) — выбор CNI-плагина.
- [Мониторинг](./rancher_monitoring.md) — ServiceMonitor для метрик.

**Внешние ресурсы:**

- [RKE2 Networking](https://docs.rke2.io/networking)
- [Canal Documentation](https://docs.projectcalico.org/security/calico-network-policy)
- [Traefik on Kubernetes](https://doc.traefik.io/traefik/)
