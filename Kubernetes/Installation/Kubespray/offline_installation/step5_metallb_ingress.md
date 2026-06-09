# Kubespray: Offline установка — Шаг 5: Настройка MetalLB и Ingress

## Определения

**Ingress** — ресурс Kubernetes, управляющий внешним доступом к сервисам в кластере (обычно HTTP/HTTPS) и обеспечивающий балансировку нагрузки, терминацию SSL и маршрутизацию на основе путей.

**MetalLB** — реализация балансировщика нагрузки для bare-metal кластеров Kubernetes, использующая стандартные сетевые протоколы (ARP/NDP или BGP).

Базовые определения и детальные концепции MetalLB приведены в **[SSoT: MetalLB — балансировщик для Bare-metal](../../../Networking/metallb.md)**.

---

## Основные концепции

### Цель этапа

Обеспечение внешнего доступа к веб-интерфейсам и API-сервисам кластера, развёрнутого в закрытом контуре. В условиях отсутствия облачного провайдера (Cloud Provider) MetalLB берет на себя роль поставщика внешних IP-адресов.

**Ключевые задачи:**

- Настройка пула IP-адресов для MetalLB (в режиме L2).
- Публикация Ingress-контроллера (Nginx) через сервис типа `LoadBalancer`.
- Создание Ingress-ресурсов для системных аддонов (например, Hubble UI).
- Обеспечение DNS-разрешения имен внутри изолированной сети.

### Архитектура доступа

Типовая цепочка прохождения трафика в offline-инсталляции:

1. **Пользователь** обращается по доменному имени (например, `hubble.k8s.domain.local`).
2. **DNS** (локальный или `/etc/hosts`) направляет запрос на **MetalLB VIP** (например, `192.168.1.200`).
3. **MetalLB Speaker** отвечает на ARP-запросы для этого VIP, направляя трафик на узел с **Ingress-контроллером**.
4. **Ingress-nginx** маршрутизирует запрос к соответствующему **Service** и **Pod**.

---

## Практические сценарии

### 1. Конфигурация MetalLB (L2 режим)

Для активации балансировщика необходимо определить пул адресов и способ их анонсирования.

**Манифест конфигурации (`metallb-config.yml`):**

```yaml
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: ingress-pool
  namespace: metallb-system
spec:
  addresses:
  - 192.168.1.200/32 # Свободный IP из вашей подсети
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

**Применение:**

```bash
kubectl apply -f metallb-config.yml
```

### 2. Настройка доступа к Hubble UI через Ingress

Hubble UI позволяет визуализировать сетевые потоки Cilium. Для доступа к нему создается Ingress-ресурс.

**Манифест Ingress (`hubble-ingress.yml`):**

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

**Применение:**

```bash
kubectl apply -f hubble-ingress.yml
```

### 3. Настройка DNS-разрешения

Для работы через доменные имена в закрытом контуре необходимо добавить записи на локальный DNS-сервер или в файлы `hosts` клиентских машин.

**Пример для `/etc/hosts`:**

```text
192.168.1.200  hubble.k8s.domain.local
```

### 4. Проверка и тестирование

Убедитесь, что компоненты работают корректно и IP-адрес назначен.

**Проверка MetalLB:**

```bash
kubectl get ipaddresspool -n metallb-system
kubectl get pods -n metallb-system
```

**Проверка назначения внешнего IP:**

```bash
kubectl get svc -n ingress-nginx ingress-nginx-controller
# В колонке EXTERNAL-IP должен появиться адрес 192.168.1.200
```

**Тестирование доступности:**

```bash
curl -I http://hubble.k8s.domain.local
```

---

## Дополнительная информация

### Диагностика

- **IP не назначается:** проверьте логи контроллера MetalLB (`kubectl logs -n metallb-system -l app.kubernetes.io/component=controller`).
- **Сайт недоступен по имени:** проверьте DNS-разрешение командой `nslookup` или `dig`.
- **Ошибка 404/503:** проверьте статус подов Ingress-контроллера и Hubble UI.

### Связанные темы

- **[Шаг 4: Развёртывание кластера](./step4_cluster_deploy.md)** — завершение базовой установки.
- **[Проверка кластера](./cluster_verification.md)** — комплексное тестирование всех компонентов.
- **[MetalLB — детальный обзор](../../../Networking/metallb.md)** — подробная документация по режимам работы.
- **[Сравнение Ingress-контроллеров](../../../Networking/Ingress/controllers_comparison.md)** — выбор альтернативных решений.
