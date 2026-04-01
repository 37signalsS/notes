# Путь трафика в Kubernetes

## Определения

**Путь трафика (Traffic Path)** — последовательность сетевых компонентов, через которые проходит запрос от внешнего источника до целевого пода в кластере Kubernetes.

**Ingress Controller** — специализированный под (обычно Nginx, Traefik, HAProxy), работающий как обратный прокси-сервер и маршрутизатор входящего HTTP/HTTPS-трафика на основе правил ресурсов `Ingress`.

**Endpoints** — объект Kubernetes, содержащий актуальный список IP-адресов подов, соответствующих селектору `Service`. Автоматически обновляется при изменениях в кластере.

**kube-proxy** — сетевой агент, работающий на каждом узле кластера. Реализует абстракцию `Service` через управление правилами `iptables` или `IPVS` для маршрутизации трафика к подам.

## Основные концепции

### Общая схема пути трафика

Стандартный путь внешнего запроса в Kubernetes:

```
Внешний клиент → LoadBalancer → Ingress Controller → Service (ClusterIP) → Pod
```

Каждый этап выполняет определённую функцию:

| Этап | Компонент | Назначение |
| :--- | :--- | :--- |
| **1** | DNS | Преобразует доменное имя во внешний IP балансировщика |
| **2** | LoadBalancer | Распределяет входящий трафик между узлами кластера |
| **3** | Ingress Controller | Маршрутизирует HTTP/HTTPS на основе правил Ingress |
| **4** | Service | Предоставляет стабильную точку входа (ClusterIP) |
| **5** | kube-proxy | Перенаправляет трафик на конкретный под через iptables/IPVS |
| **6** | Pod | Контейнер с приложением обрабатывает запрос |

### Детальное описание этапов

#### Этап 1: DNS и LoadBalancer

1. Клиент запрашивает `https://my-app.com/path`
2. DNS возвращает внешний IP балансировщика нагрузки
3. Балансировщик создаётся облачным провайдером для сервиса Ingress Controller
4. Трафик перенаправляется на узел кластера через `NodePort`

#### Этап 2: Ingress Controller

1. Под Ingress Controller принимает запрос на узле
2. Анализирует заголовки запроса (хост, путь, метод)
3. Сопоставляет с правилами ресурсов `Ingress`
4. Определяет целевой `Service` для маршрутизации

#### Этап 3: Service и ClusterIP

1. Ingress Controller отправляет трафик на `ClusterIP` сервиса
2. `ClusterIP` — виртуальный IP, доступный только внутри кластера
3. `Service` отслеживает поды по меткам (label selector)
4. Объект `Endpoints` хранит список IP-адресов здоровых подов

#### Этап 4: kube-proxy и маршрутизация к Pod

1. `kube-proxy` перехватывает трафик, направленный на `ClusterIP`
2. Выбирает IP пода из списка `Endpoints` (алгоритм балансировки)
3. Правила `iptables` или `IPVS` подменяют IP назначения
4. Пакет перенаправляется на реальный IP пода

#### Этап 5: Доставка в Pod

1. CNI-плагин обеспечивает доставку пакета до сетевого интерфейса пода
2. Контейнер приложения получает запрос и обрабатывает его
3. Ответ следует обратным путём к клиенту

### Путь трафика Pod-to-Pod

Для внутренних запросов между подами путь короче:

**Внутри одного узла:**
```
Pod A → veth → cni0 (мост) → veth → Pod B
```

**Между узлами (на примере Flannel VXLAN):**
```
Pod A (Node 1) → veth → cni0 → flannel.1 → VXLAN → Node 2 → cni0 → Pod B
```

CNI-плагин инкапсулирует пакет в VXLAN/UDP и отправляет на IP узла назначения.

## Практические сценарии

### Диагностика пути трафика

```bash
# Проверка Endpoints сервиса
kubectl get endpoints my-app-service

# Трассировка пути до сервиса
kubectl run test-pod --rm -it --image=busybox -- traceroute my-app-service

# Проверка правил iptables для Service
iptables-save | grep my-app-service

# Просмотр логов Ingress Controller
kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller
```

### Типичные проблемы и решения

| Симптом | Возможная причина | Диагностика |
| :--- | :--- | :--- |
| 502 Bad Gateway | Pod недоступен | `kubectl get endpoints`, логи приложения |
| 503 Service Unavailable | Нет здоровых подов | Проверка readiness probe, статус подов |
| Таймаут соединения | NetworkPolicy блокирует трафик | `kubectl get networkpolicy`, логи CNI |
| Неправильная маршрутизация | Ошибка в правилах Ingress | `kubectl describe ingress`, конфиг Ingress Controller |

### Рекомендации по архитектуре

**Выделение Ingress-нод (DMZ-зона):**

Для production-окружений рекомендуется запускать Ingress Controller на выделенных узлах:

```
Внешний трафик → Load Balancer → Ingress-ноды → Backend-ноды → Pods
```

**Преимущества:**
- Изоляция внешнего трафика от рабочих нагрузок
- Независимое масштабирование ingress и backend
- Оптимизация узлов под конкретные задачи (TLS, L7-маршрутизация)

**Реализация:**
- `nodeSelector` или `affinity` для привязки Ingress Controller
- `taints/tolerations` для предотвращения планирования других подов
- `NetworkPolicy` для изоляции трафика между зонами

### Избегайте hostPort и hostNetwork

Использование `hostNetwork: true` и `hostPort` привязывает под к конкретному узлу:

```yaml
# Не рекомендуется без крайней необходимости
spec:
  hostNetwork: true
  containers:
  - name: app
    ports:
    - containerPort: 80
      hostPort: 80
```

**Проблемы:**
- Ограничение планирования (под может запуститься только на узле со свободным портом)
- Расширение поверхности атаки (прямой доступ к портам узла)
- Конфликты портов между подами

**Альтернативы:**
- `NodePort` — базовый внешний доступ
- `LoadBalancer` — облачные среды
- `Ingress` — HTTP/HTTPS трафик
- `kubectl port-forward` — отладка

**Легитимные сценарии использования:**
- DaemonSet мониторинга (Node Exporter)
- CNI-плагины (Calico, Cilium)
- NodeLocalDNS
- Специализированные Ingress-контроллеры

## Дополнительная информация

**См. также:**
- [Обзор сетевой модели Kubernetes](./network_overview.md) — CNI, kube-proxy, принципы
- [CNI и kube-proxy: роли](./cni_kube_proxy_roles.md) — детальное описание компонентов
- [Обзор Service](../Service/service_overview.md) — абстракция Service, типы
- [Обзор Ingress](../Ingress/overview.md) — правила маршрутизации HTTP
- [Архитектура Load Balancer + Ingress](./CNI/selection_and_external_access.md#архитектура-load-balancer--ingress-controller)
