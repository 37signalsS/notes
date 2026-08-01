# Практические сценарии Service

## Определения

**Практические сценарии** — пошаговые руководства по публикации приложений в Kubernetes через сервисы различных типов.

**Цель:** Демонстрация настройки сетевой связности от базового внутреннего доступа до продвинутых конфигураций с сохранением IP-адреса клиента. Теоретическую базу см. в [Обзоре Service](./service_overview.md).

## Основные концепции

### Иерархия публикации

При разработке и развертывании рекомендуется придерживаться следующей последовательности:

1. **ClusterIP:** Изоляция сервиса внутри кластера.
2. **Headless:** Для прямого взаимодействия между узлами БД или Stateful-приложений.
3. **NodePort / LoadBalancer:** Вывод приложения на внешний контур.

### Ключевые требования

- **Метки (Labels):** Основа связности. Service находит поды только при точном совпадении `spec.selector` и `metadata.labels` пода.
- **Порты:**
    - `port`: порт, на котором сервис принимает трафик.
    - `targetPort`: порт, на котором приложение слушает внутри контейнера.
- **Ready State:** Сервис направляет трафик только на те поды, которые прошли `readinessProbe`.

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

Примените манифест: `kubectl apply -f nginx-deploy.yaml`.

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

**Проверка:**
```bash
# Получение ClusterIP
kubectl get svc internal-api
# → <CLUSTER-IP>

# Проверка из другого пода
kubectl run test-pod --rm -it --image=curlimages/curl -- curl http://internal-api
```

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

**Особенности:**
- Трафик будет приниматься только теми узлами, на которых запущены поды `nginx-demo`.
- Если на узле нет подходящих подов, соединение будет сброшено.

---

### Сценарий 3: Прямое обнаружение подов (Headless)

Используется для кластерных решений (Elasticsearch, MongoDB, Kafka), где клиенту нужен список IP всех реплик.

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

**Проверка DNS:**
```bash
kubectl run dns-test --rm -it --image=busybox:1.28 -- nslookup db-cluster
# → Возвращает список IP-адресов всех подов вместо одного VIP
```

## Устранение неполадок (Troubleshooting)

Связь между Service и подами — фундаментальная концепция сети Kubernetes. Проблемы здесь обычно проявляются как таймауты соединений или отсутствие ответа от сервиса.

### Отсутствие конечных точек (Endpoints)

Если Service получает запросы, но не перенаправляет их никуда, вероятнее всего, у него отсутствуют связанные эндпоинты.

**Основной диагностический инструмент:**
```bash
kubectl describe service <имя-сервиса>
```

В выводе команды обратите внимание на два ключевых поля:
*   **Selector:** пары ключ-значение, которые сервис использует для поиска подов (например, `app=frontend`).
*   **Endpoints:** список комбинаций `IP:порт` исправных подов. Если здесь указано `<none>`, селектор не нашел ни одного подходящего и готового пода.

#### Основные причины отсутствия эндпоинтов

1.  **Несоответствие меток (Label Mismatch):** Метки на подах (например, `app: web-frontend`) не полностью совпадают с селектором сервиса (например, `app: frontend`).
    *   *Проверка:* `kubectl get pods --selector=app=frontend`. Если команда не возвращает подов, причина в метках.
2.  **Поды не готовы (Not Ready):** Под добавляется в список эндпоинтов только тогда, когда он прошел проверку готовности (`readinessProbe`). Если под находится в статусе `Running`, но не проходит пробу, он не будет получать трафик.
    *   *Проверка:* `kubectl get pods` (столбец `READY` должен быть `1/1`).
3.  **Неправильная конфигурация портов:** Значение `targetPort` в манифесте Service должно точно совпадать с `containerPort` в манифесте Pod. Если они различаются, трафик не будет маршрутизироваться корректно, даже если эндпоинты указаны.

### Мини-кейс: Опечатка в метке

Команда развернула микросервис `payments`, но другие сервисы не могут с ним связаться, сообщая о таймаутах.

*   **Диагностика:** Выполнение `kubectl describe svc payments` показало `Endpoints: <none>`.
*   **Анализ:** Селектор сервиса искал метку `app: payments`. Однако при проверке Deployment (`kubectl get deploy payments -o yaml`) была обнаружена опечатка в шаблоне пода: `app: pay`.
*   **Решение:** Исправление метки в манифесте Deployment на `app: payments` и повторное применение конфигурации мгновенно решило проблему: IP-адреса подов появились в `Endpoints`.

> **Совет для собеседования:**
> Должен ли под находиться в состоянии `Running`, чтобы попасть в список эндпоинтов сервиса?
> **Ответ:** Нет, одного `Running` недостаточно. Под должен находиться в состоянии **Ready**. Его IP-адрес добавляется в объект `Endpoints` только после успешного прохождения проверки готовности (`readinessProbe`), если она определена. Это предотвращает отправку трафика на поды, которые еще инициализируются или временно перегружены.

## Дополнительная информация

### Инструменты диагностики

| Задача | Команда |
| :--- | :--- |
| Проверка эндпоинтов | `kubectl get endpoints nginx-service` |
| Анализ EndpointSlices | `kubectl get endpointslice -l kubernetes.io/service-name=nginx-service` |
| Описание состояния | `kubectl describe svc nginx-service` |
| Ручной поиск по селектору | `kubectl get pods --selector=key=value` |
| Проверка правил iptables | `iptables-save | grep nginx-service` (на узле) |

### См. также

- [Диагностика и устранение неисправностей проб](../Base/probes.md#диагностика-и-устранение-неисправностей)
- [Подробный разбор типов Service](./service_types_summary.md)
- [Service Discovery через DNS](../Network/dns_service_discovery.md)
- [Траблшутинг Kubernetes (обзор)](../Troubleshooting/troubleshooting_overview.md)
