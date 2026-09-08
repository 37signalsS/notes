# Практические сценарии Service

## Определения

**Практические сценарии** — пошаговые руководства по публикации приложений в Kubernetes через сервисы различных типов.

**Цель:** Демонстрация настройки сетевой связности от базового внутреннего доступа до продвинутых конфигураций с сохранением IP-адреса клиента. Теоретическую базу см. в [Обзоре Service](./service_overview.md). Детальное описание каждого типа Service — в соответствующих файлах: [ClusterIP](./service_type_clusterip.md), [NodePort](./service_type_nodeport.md), [Headless](./service_type_headless.md), [LoadBalancer](./service_type_loadbalancer.md), [ExternalName](./service_type_externalname.md).

## Предварительные требования

Для выполнения практических сценариев необходимо обеспечить следующее окружение:

- **Кластер Kubernetes** версии 1.21+ (для поддержки EndpointSlices) или 1.31+ (для стабильной поддержки `trafficDistribution`, nftables)
- **CNI-плагин** (Calico, Flannel, Cilium или аналог) — обеспечивает базовую связность подов
- **kube-proxy** — DaemonSet, развёрнутый на всех узлах кластера (или eBPF-замена, например Cilium kube-proxy replacement)
- **CoreDNS** — кластерный DNS-сервер для Service Discovery через имена
- **kubectl** — CLI-инструмент для управления ресурсами кластера

**Проверка готовности окружения:**
```bash
# Проверка статуса kube-proxy
kubectl -n kube-system get pods -l k8s-app=kube-proxy
# → Все поды должны быть в статусе Running и Ready

# Проверка CoreDNS
kubectl -n kube-system get pods -l k8s-app=kube-dns
# → Все поды должны быть в статусе Running и Ready

# Проверка режима kube-proxy
kubectl -n kube-system get configmap kube-proxy -o yaml | grep mode
# → mode: "nftables" (или "ipvs", "iptables")

# Проверка диапазона ClusterIP
kubectl cluster-info dump | grep -E "service-cluster-ip-range"
# → --service-cluster-ip-range=10.96.0.0/12

# Проверка диапазона NodePort (если планируется использование)
kubectl cluster-info dump | grep -E "service-node-port-range"
# → --service-node-port-range=30000-32767
```

## Основные концепции

### Иерархия публикации

При разработке и развертывании рекомендуется придерживаться следующей последовательности:

1. **ClusterIP:** Изоляция сервиса внутри кластера.
2. **Headless:** Для прямого взаимодействия между узлами БД или Stateful-приложений.
3. **Topology Aware Routing:** Оптимизация трафика внутри зон для снижения задержек.
4. **NodePort / LoadBalancer:** Вывод приложения на внешний контур.

### Ключевые требования и компоненты

- **Метки (Labels):** Основа связности. Service находит поды только при точном совпадении `spec.selector` и `metadata.labels` пода.
- **Порты:**
    - `port`: порт, на котором сервис принимает трафик.
    - `targetPort`: порт, на котором приложение слушает внутри контейнера.
- **Ready State:** Сервис направляет трафик только на те поды, которые прошли `readinessProbe`.
- **EndpointSlices (v1.30+):** Современный механизм управления эндпоинтами, заменяющий устаревший API `Endpoints`. Именно EndpointSlices обеспечивают масштабируемость и поддержку топологии (Topology Hints).

---

## Практические сценарии

### Подготовка: Создание Deployment

Используем Nginx для демонстрации сетевого взаимодействия.

```yaml
# nginx-deploy.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-lb-test
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx-demo
  template:
    metadata:
      labels:
        app: nginx-demo
    spec:
      containers:
      - name: nginx
        image: nginx:latest
        ports:
        - containerPort: 80
```

**Применение и проверка:**
```bash
# Создание Deployment
kubectl apply -f nginx-deploy.yaml
# → deployment.apps/nginx-lb-test created

# Проверка статуса подов
kubectl get pods -l app=nginx-demo
# → NAME                            READY   STATUS    RESTARTS   AGE
# → nginx-lb-test-xxxxxxxxxx-xxxxx   1/1     Running   0          30s
# → nginx-lb-test-xxxxxxxxxx-yyyyy   1/1     Running   0          30s

# Проверка EndpointSlices
kubectl get endpointslice -l kubernetes.io/service-name=nginx-lb-test
# → Пока нет сервиса, EndpointSlices не созданы
```

---

### Сценарий 0: Быстрое создание Service (Императивный путь)

Использование `kubectl expose` для автоматического создания сервиса на основе существующего Pod или Deployment.

```bash
# Создание ClusterIP сервиса для пода
kubectl expose pod my-nginx --port=80 --target-port=80 --name=nginx-internal

# Создание NodePort сервиса для Deployment
kubectl expose deployment my-deploy --port=80 --type=NodePort --name=nginx-external
```

**Валидация:**
```bash
# Проверка созданного сервиса
kubectl get svc nginx-internal
# → NAME             TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
# → nginx-internal   ClusterIP   10.96.x.x       <none>        80/TCP    5s

# Проверка NodePort сервиса
kubectl get svc nginx-external
# → NAME             TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
# → nginx-external   NodePort   10.96.x.x       <none>        80:3xxxx/TCP   5s

# Проверка доступности
kubectl run test-pod --rm -it --image=curlimages/curl -- curl http://nginx-internal
# → Должен вернуть HTML-ответ Nginx
```

**Ограничения императивного подхода:**
- Нельзя задать все параметры (sessionAffinity, externalTrafficPolicy и др.)
- Сложно поддерживать в GitOps/CI-CD пайплайнах
- Рекомендуется использовать декларативный подход (манифесты) для production

---

### Сценарий 1: Внутренний доступ (ClusterIP)

Создание стабильной точки входа для межсервисного взаимодействия.

```yaml
# clusterip-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: internal-api
spec:
  type: ClusterIP
  selector:
    app: nginx-demo
  ports:
    - protocol: TCP
      port: 80
      targetPort: 80
```

**Применение и проверка:**
```bash
# Создание сервиса
kubectl apply -f clusterip-service.yaml
# → service/internal-api created

# Получение ClusterIP
kubectl get svc internal-api
# → NAME          TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
# → internal-api   ClusterIP   10.96.x.x       <none>        80/TCP    5s

# Проверка из другого пода
kubectl run test-pod --rm -it --image=curlimages/curl -- curl http://internal-api
# → Должен вернуть HTML-ответ Nginx

# Проверка DNS-имени
kubectl run test-pod --rm -it --image=busybox:1.37 -- nslookup internal-api
# → Name:      internal-api
# → Address 1: 10.96.x.x

# Проверка EndpointSlices
kubectl get endpointslice -l kubernetes.io/service-name=internal-api
# → NAME                          ADDRESSTYPE   PORTS   ENDPOINTS                      AGE
# → internal-api-xxxxx            IPv4          80      10.244.1.5,10.244.2.3          30s
```

**Подробнее:** детальная конфигурация и сценарии для [ClusterIP](./service_type_clusterip.md).

---

### Сценарий 2: Сохранение IP клиента (NodePort + Local Policy)

Используется, когда приложению необходимо видеть реальный IP-адрес источника, а не IP-адрес узла кластера.

```yaml
# nodeport-local.yaml
apiVersion: v1
kind: Service
metadata:
  name: external-web-access
spec:
  type: NodePort
  externalTrafficPolicy: Local # Критично для сохранения Source IP
  selector:
    app: nginx-demo
  ports:
    - port: 80
      targetPort: 80
      nodePort: 32080
```

**Применение и проверка:**
```bash
# Создание сервиса
kubectl apply -f nodeport-local.yaml
# → service/external-web-access created

# Проверка создания сервиса
kubectl get svc external-web-access
# → NAME                  TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
# → external-web-access   NodePort   10.96.x.x       <none>        80:32080/TCP   5s

# Проверка доступности через NodePort (замените <node-ip> на IP узла)
curl http://<node-ip>:32080
# → Должен вернуть HTML-ответ Nginx

# Проверка распределения подов по узлам
kubectl get pods -l app=nginx-demo -o wide
# → NAME                            READY   STATUS    IP            NODE
# → nginx-lb-test-xxxxxxxxxx-xxxxx   1/1     Running   10.244.1.5    node-1
# → nginx-lb-test-xxxxxxxxxx-yyyyy   1/1     Running   10.244.2.3    node-2

# Проверка healthCheckNodePort (автоматически назначенный)
kubectl get svc external-web-access -o yaml | grep healthCheckNodePort
# → healthCheckNodePort: 3xxxx
```

**Особенности:**
- Трафик принимается только теми узлами, на которых запущены целевые поды.
- Если на узле нет подов, соединение будет сброшено.
- `healthCheckNodePort` используется внешним балансировщиком для проверки доступности узлов.

**Подробнее:** детальная конфигурация и сценарии для [NodePort](./service_type_nodeport.md).

---

### Сценарий 3: Прямое обнаружение подов (Headless)

Используется для кластерных решений (Elasticsearch, Kafka), где клиенту нужен список IP всех реплик.

```yaml
# headless-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: db-cluster
spec:
  clusterIP: None # Делает сервис Headless
  selector:
    app: nginx-demo
  ports:
    - port: 80
```

**Применение и проверка:**
```bash
# Создание сервиса
kubectl apply -f headless-service.yaml
# → service/db-cluster created

# Проверка создания (ClusterIP должен быть None)
kubectl get svc db-cluster
# → NAME        TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)   AGE
# → db-cluster   ClusterIP   None         <none>        80/TCP    5s

# Проверка DNS (возвращает список IP подов)
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup db-cluster
# → Name:      db-cluster
# → Address 1: 10.244.1.5
# → Address 2: 10.244.2.3

# Проверка EndpointSlices
kubectl get endpointslice -l kubernetes.io/service-name=db-cluster
# → NAME                          ADDRESSTYPE   PORTS   ENDPOINTS                      AGE
# → db-cluster-xxxxx              IPv4          80      10.244.1.5,10.244.2.3          30s
```

**Подробнее:** детальная конфигурация и сценарии для [Headless](./service_type_headless.md).

---

### Сценарий 4: Оптимизация трафика по зонам (Topology Aware Routing)

**Новое в K8s 1.31 (Beta):** Использование поля `spec.trafficDistribution` для удержания трафика в той же зоне доступности.

```yaml
# topology-service.yaml
apiVersion: v1
kind: Service
metadata:
  name: local-zone-api
spec:
  selector:
    app: nginx-demo
  trafficDistribution: PreferClose # Предпочитать эндпоинты в той же зоне/узле
  ports:
    - port: 80
      targetPort: 80
```

**Применение и проверка:**
```bash
# Создание сервиса
kubectl apply -f topology-service.yaml
# → service/local-zone-api created

# Проверка создания сервиса
kubectl get svc local-zone-api
# → NAME              TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
# → local-zone-api    ClusterIP   10.96.x.x       <none>        80/TCP    5s

# Проверка трафика из пода
kubectl run test-pod --rm -it --image=curlimages/curl -- curl http://local-zone-api
# → Должен вернуть HTML-ответ Nginx

# Проверка EndpointSlices с топологическими hints
kubectl get endpointslice -l kubernetes.io/service-name=local-zone-api -o yaml | grep -A 5 "hints"
# → hints:
# →   forZones:
# →   - name: "us-east-1a"
```

**Примечание:** Для работы `trafficDistribution: PreferClose` необходимо, чтобы узлы имели метки топологии (`topology.kubernetes.io/zone`, `topology.kubernetes.io/region`).

---

### Сценарий 5: Абстракция внешних ресурсов (ExternalName)

Создание DNS-алиаса для внешней базы данных или API.

```yaml
# external-db.yaml
apiVersion: v1
kind: Service
metadata:
  name: external-postgres
spec:
  type: ExternalName
  externalName: db.prod.example.com
```

**Применение и проверка:**
```bash
# Создание сервиса
kubectl apply -f external-db.yaml
# → service/external-postgres created

# Проверка создания сервиса
kubectl get svc external-postgres
# → NAME               TYPE           EXTERNAL-IP              PORT(S)   AGE
# → external-postgres   ExternalName   db.prod.example.com      <none>    5s

# Проверка DNS-резолвинга (CNAME)
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup external-postgres
# → Name:      external-postgres
# → Address 1: db.prod.example.com (CNAME)
```

**Подробнее:** детальная конфигурация и сценарии для [ExternalName](./service_type_externalname.md).

---

## Устранение неполадок (Troubleshooting)

Связь между Service и подами — фундаментальная концепция сети Kubernetes. Проблемы здесь обычно проявляются как таймауты соединений или отсутствие ответа от сервиса.

### Типичные ошибки конфигурации

1.  **ClusterIP для внешнего доступа:** Использование типа `ClusterIP` (по умолчанию) при попытке достучаться до сервиса извне кластера напрямую.
    *   *Решение:* Используйте `NodePort`, `LoadBalancer` или настройте `Ingress/Gateway`.
2.  **Несоответствие портов:** Значение `targetPort` в манифесте Service должно точно совпадать с портом, который прослушивает приложение в контейнере (`containerPort`).
    *   *Проверка:* `kubectl get svc <name> -o yaml | grep targetPort` и `kubectl describe pod <pod> | grep "Containers:" -A 5`
3.  **Отсутствие конечных точек (Endpoints):** Если `kubectl describe service <name>` показывает `Endpoints: <none>`, сервис не может найти подходящие поды.
    *   *Диагностика:* см. раздел "Отсутствие конечных точек" ниже.
4.  **Несоответствие протоколов:** Указание `protocol: TCP` когда приложение работает по UDP (или наоборот).
    *   *Решение:* Проверьте протокол приложения и укажите соответствующий в манифесте Service.

### Отсутствие конечных точек (Endpoints и EndpointSlices)

Если Service получает запросы, но не перенаправляет их никуда, вероятнее всего, у него отсутствуют связанные эндпоинты. В современных версиях K8s (1.30+) диагностику следует начинать с **EndpointSlices**.

**Основной диагностический инструмент:**
```bash
# Проверка высокоуровневого состояния сервиса
kubectl describe service <имя-сервиса>

# Проверка конкретных EndpointSlices (v1.30+)
kubectl get endpointslice -l kubernetes.io/service-name=<имя-сервиса>
```

В выводе команды `describe service` обратите внимание на:
*   **Selector:** пары ключ-значение (например, `app=frontend`).
*   **Endpoints:** список `IP:порт`. Если здесь `<none>`, селектор не нашел ни одного пода.

#### Основные причины отсутствия эндпоинтов

1.  **Несоответствие меток (Label Mismatch):** Метки на подах не совпадают с селектором сервиса.
    *   *Проверка:* `kubectl get pods --show-labels`.
    *   *Решение:* Исправьте метки подов или селектор сервиса.
2.  **Поды не готовы (Not Ready):** Под добавляется в эндпоинты только после прохождения `readinessProbe`.
    *   *Проверка:* `kubectl get pods` (столбец `READY`).
    *   *Решение:* Проверьте логи пода и корректность `readinessProbe`.
3.  **Namespace Mismatch:** Сервис и поды находятся в разных пространствах имен. Сервис ищет поды только в **своем** namespace.
    *   *Проверка:* `kubectl get pods -n <namespace> --show-labels`.
    *   *Решение:* Убедитесь, что сервис и поды в одном namespace.
4.  **Сбой EndpointSlice Mirroring:** В редких случаях (при ручном создании Endpoints) контроллер может не создать соответствующий EndpointSlice.
    *   *Решение:* Проверьте логи контроллера EndpointSlice.

### Мини-кейс: "Призрачные" поды и Readiness

Команда развернула приложение, поды в статусе `Running`, но сервис выдает `503 Service Unavailable`.
*   **Диагностика:** `kubectl get endpoints` показывает пустой список.
*   **Анализ:** Команда `kubectl describe pod <name>` выявила, что `readinessProbe` обращается к порту `/health`, который в новой версии приложения был изменен на `/ready`.
*   **Решение:** Обновление пути в `readinessProbe` мгновенно вернуло поды в пул эндпоинтов сервиса.

### Проблемы с DNS-резолвингом

**Симптом:** Сервис существует, но DNS-имя не резолвится.

**Диагностика:**
```bash
# Проверка CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns
# → Все поды должны быть Running

# Проверка DNS из пода
kubectl run dns-test --rm -it --image=busybox:1.37 -- nslookup <service-name>
# → Должен вернуть IP сервиса

# Проверка CoreDNS логов
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
```

**Типичные причины:**
- CoreDNS не запущен или в состоянии CrashLoopBackOff
- Сервис создан в другом namespace (используйте FQDN: `<service>.<namespace>.svc.cluster.local`)
- Проблемы с CoreDNS ConfigMap

### Проблемы с доступом при externalTrafficPolicy: Local

**Симптом:** При `externalTrafficPolicy: Local` часть запросов получает ошибку соединения.

**Диагностика:**
```bash
# Проверка распределения подов по узлам
kubectl get pods -l <selector> -o wide
# → Если на узле нет подов, трафик на него не должен направляться

# Проверка healthCheckNodePort
kubectl get svc <service-name> -o yaml | grep healthCheckNodePort
# → healthCheckNodePort: 3xxxx
```

**Решение:** Убедитесь, что внешний балансировщик использует `healthCheckNodePort` для проверки доступности узлов.

> **Совет для собеседования:**
> **Вопрос:** В чем разница между Endpoints и EndpointSlices?
> **Ответ:** `Endpoints` — старый монолитный API, который хранит все IP в одном объекте. При наличии 1000+ подов это перегружает `etcd` и API-сервер. `EndpointSlices` (стандарт с 1.21+) разбивает список на части (по 100 подов по умолчанию), поддерживает топологию и IPv4/IPv6 стеки одновременно.

## Best Practices

1. **Используйте декларативный подход:** Для production всегда используйте манифесты (YAML) вместо императивных команд. Это обеспечивает воспроизводимость и версионирование конфигураций.

2. **Проверяйте метки:** Всегда проверяйте соответствие `spec.selector` Service и `metadata.labels` подов перед созданием сервиса.

3. **Настраивайте readinessProbe:** Без `readinessProbe` поды могут получать трафик до полной готовности приложения, что приводит к ошибкам.

4. **Используйте DNS-имена:** Вместо жёсткого кодирования ClusterIP используйте DNS-имена сервисов (`<service>.<namespace>.svc.cluster.local`).

5. **Ограничивайте доступ:** Для внешних сервисов используйте `loadBalancerSourceRanges` (LoadBalancer) или NetworkPolicy для ограничения доступа.

6. **Мониторьте EndpointSlices:** Регулярно проверяйте состояние EndpointSlices для критических сервисов.

7. **Выбирайте оптимальный тип:** Начинайте с ClusterIP и переходите на другие типы только при необходимости (см. [Сводку по типам](./service_types_summary.md)).

## Edge Cases и ограничения

1. **Невозможность изменения типа:** Поле `type` Service неизменяемое. Для смены типа требуется удаление и создание сервиса заново.

2. **Hairpin трафик:** Когда под обращается к внешнему IP собственного сервиса, могут возникнуть проблемы с маршрутизацией. Используйте `externalTrafficPolicy: Local` или настройте hairpin mode в kube-proxy.

3. **Ограничение диапазона NodePort:** По умолчанию диапазон 30000-32767. Изменение требует перезапуска API-сервера с флагом `--service-node-port-range`.

4. **Dual-Stack:** При использовании IPv4/IPv6 убедитесь, что CNI и kube-proxy поддерживают dual-stack. Поведение определяется `ipFamilyPolicy`.

5. **Session Affinity:** `sessionAffinity: ClientIP` работает только для трафика внутри кластера. Для внешнего трафика используйте Ingress с сессионной привязкой.

6. **Headless и StatefulSet:** Headless Service обязательна для StatefulSet — она обеспечивает стабильные DNS-имена для каждого пода (`<pod-name>.<service-name>.<namespace>.svc.cluster.local`).

7. **ExternalName и порт:** ExternalName Service не поддерживает указание порта — используйте порт целевого ресурса.

8. **Topology Aware Routing:** Требует наличия меток топологии на узлах (`topology.kubernetes.io/zone`, `topology.kubernetes.io/region`). Без них `trafficDistribution: PreferClose` не даст эффекта.

## Очистка и откат изменений

```bash
# Просмотр всех сервисов в namespace
kubectl get svc
# → NAME                  TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
# → internal-api          ClusterIP   10.96.x.x       <none>        80/TCP         5m
# → external-web-access   NodePort    10.96.x.x       <none>        80:32080/TCP   5m
# → db-cluster            ClusterIP   None            <none>        80/TCP         5m

# Удаление конкретного сервиса
kubectl delete svc internal-api
# → service "internal-api" deleted

# Удаление сервиса по манифесту
kubectl delete -f clusterip-service.yaml

# Удаление всех сервисов из сценариев
kubectl delete svc internal-api external-web-access db-cluster local-zone-api external-postgres

# Удаление Deployment
kubectl delete -f nginx-deploy.yaml
# → deployment.apps "nginx-lb-test" deleted

# Проверка удаления
kubectl get svc
# → Должны остаться только системные сервисы (kubernetes, kube-dns и т.д.)
```

**Важно:** При удалении сервиса EndpointSlices удаляются автоматически. Убедитесь, что на сервис нет зависимых ресурсов (Ingress, другие сервисы).

## Дополнительная информация

### Инструменты диагностики

| Задача | Команда |
| :--- | :--- |
| Проверка EndpointSlices | `kubectl get endpointslice -l kubernetes.io/service-name=<name>` |
| Проверка меток подов | `kubectl get pods --show-labels` |
| Описание состояния | `kubectl describe svc <name>` |
| Эфемерная отладка сети | `kubectl debug -it <pod> --image=nicolaka/netshoot` |
| Проверка DNS резолвинга | `kubectl run test --rm -it --image=busybox:1.37 -- nslookup <svc>` |
| Проверка доступности сервиса | `kubectl run test --rm -it --image=curlimages/curl -- curl http://<svc>` |

### См. также

- [Обзор Service](./service_overview.md) — теоретическая база и архитектура Service
- [Сводка по типам Service](./service_types_summary.md) — сравнение всех типов и дерево решений
- [Диагностика проб](../../Base/probes.md#диагностика-и-устранение-неисправностей) — устранение проблем с readiness/liveness probes
