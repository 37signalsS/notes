# Sidecar Patterns в Kubernetes

## Определения

**Sidecar Pattern** — паттерн многоконтейнерного пода, где один контейнер является основным (приложение), а другой (сайдкар) выполняет вспомогательную функцию, расширяющую возможности основного приложения.

**Adapter Pattern** — вариация sidecar, преобразующая данные основного приложения для внешних систем (например, форматирование метрик для Prometheus).

**Ambassador Pattern** — вариация sidecar, управляющая внешними соединениями (например, проксирование запросов через Envoy).

**Native Sidecar** — механизм Kubernetes 1.29+ (stable в 1.33+), позволяющий определить sidecar как init-контейнер с `restartPolicy: Always`, работающий на протяжении всего жизненного цикла пода ([KEP-3839](https://github.com/kubernetes/enhancements/blob/master/keps/sig-node/3839-sidecar-containers.md)).

Подробнее об init-контейнерах: [Init Containers](./pod_init_containers.md).

---

## Базовые концепции

### Виды и применение

| Паттерн | Назначение | Пример |
| :--- | :--- | :--- |
| **Sidecar** | Дополняет основное приложение | Fluentd для логов, Istio для трафика |
| **Adapter** | Преобразует данные для внешних систем | Форматирование метрик для Prometheus |
| **Ambassador** | Управляет внешними соединениями | Проксирование через Envoy |

**Задачи sidecar-контейнеров:**

| Задача | Описание |
| :--- | :--- |
| Сбор и отправка логов | Чтение логов из общего тома, отправка в централизованную систему (Fluentd, Logstash) |
| Сбор метрик | Экспортер Prometheus для сбора и предоставления метрик |
| Сетевые функции (прокси) | Перехват входящего/исходящего трафика (Istio, Linkerd, Envoy) |
| Управление конфигурацией | Динамическая загрузка конфигов из Git, Consul, Vault |
| Управление сертификатами | Автоматическое обновление TLS-сертификатов |
| Адаптация данных | Преобразование форматов для совместимости с другими системами |

### Native Sidecar (Kubernetes 1.29+)

До Kubernetes 1.29 гарантированный запуск sidecar перед основным приложением решался обходными путями. С версии 1.29 (beta), 1.33+ (stable) sidecar можно определить как init-контейнер с особыми параметрами.

**Два ключевых механизма:**

| Механизм | Описание |
| :--- | :--- |
| `initContainer` + `restartPolicy: Always` | Превращает init-контейнер в постоянный sidecar, работающий весь жизненный цикл пода |
| `startupProbe` для sidecar | Основные контейнеры не запустятся, пока `startupProbe` sidecar не завершится успешно |

**Порядок запуска при смешанных init-контейнерах:**

Если в поде одновременно присутствуют sidecar-контейнеры (`restartPolicy: Always`) и обычные init-контейнеры, kubelet запускает их в следующем порядке:

1. **Sidecar-контейнеры** (`restartPolicy: Always`) — запускаются первыми, работают параллельно
2. **Обычные init-контейнеры** — запускаются последовательно, после старта всех sidecar
3. **Основные контейнеры** — запускаются после завершения всех обычных init-контейнеров

Sidecar-контейнеры не блокируют запуск последующих init-контейнеров — они стартуют и переходят в состояние `Ready`, после чего kubelet продолжает выполнение обычных init-контейнеров.

**Где критически важно:**

- Прямая зависимость: приложение падает без готового sidecar (прокси, логгер)
- Service Mesh: Istio, Envoy
- Сборщики логов: Fluentd, Fluent Bit
- Динамическая загрузка конфигурации

**Диагностика и логи:**

В отличие от завершённых init-контейнеров, sidecar-контейнеры (`restartPolicy: Always`) работают на протяжении всего жизненного цикла пода, что позволяет просматривать их логи в реальном времени:

```bash
# Логи sidecar-контейнера (работает постоянно)
kubectl logs <pod-name> -c <sidecar-container-name> -f

# Логи sidecar в Job — доступны до завершения Job
kubectl logs <job-pod-name> -c <sidecar-container-name>
```

---

## Практические сценарии

### Sidecar для сбора логов

Fluentd собирает логи из общего тома и отправляет в централизованную систему:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-logging-sidecar
spec:
  volumes:
  - name: shared-logs
    emptyDir: {}
  containers:
  - name: app
    image: my-app:1.0
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
  - name: log-shipper
    image: fluent/fluentd
    volumeMounts:
    - name: shared-logs
      mountPath: /var/log/app
      readOnly: true
```

### Native Sidecar с гарантированным запуском

Sidecar (Envoy) запускается до основного приложения и работает весь жизненный цикл пода:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-native-sidecar
spec:
  initContainers:
  - name: envoy-sidecar
    image: envoyproxy/envoy:v1.28
    restartPolicy: Always
    startupProbe:
      httpGet:
        path: /ready
        port: 9901
      initialDelaySeconds: 5
      periodSeconds: 2
      failureThreshold: 10
  containers:
  - name: app
    image: my-app:1.0
    ports:
    - containerPort: 8080
```

**Порядок запуска:**

1. Запускается `envoy-sidecar`
2. `startupProbe` проверяет готовность Envoy
3. После успеха `startupProbe` запускается основной контейнер `app`
4. Sidecar работает параллельно с основным приложением
5. При завершении пода sidecar останавливается вместе с основным контейнером

### Sidecar в Job — логирование без блокировки завершения

Sidecar-контейнер в Job не предотвращает завершение Job после completion основного контейнера. Это полезно для задач сбора логов или мониторинга, которые должны работать параллельно с основной задачей, но не должны блокировать завершение Job.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: data-processing-job
spec:
  template:
    spec:
      initContainers:
      - name: log-collector
        image: fluent/fluentd:latest
        restartPolicy: Always  # Native sidecar
        # Собирает логи из общего тома в течение всей работы Job
      containers:
      - name: processor
        image: data-processor:1.0
        command: ['python', '/app/process.py']
        # После завершения process.py Job считается completed,
        # несмотря на работающий log-collector
      volumes:
      - name: shared-logs
        emptyDir: {}
      restartPolicy: Never
```

**Поведение:**

1. Запускается `log-collector` (sidecar)
2. Запускается `processor` (основной контейнер)
3. После завершения `processor` Job переходит в статус `Completed`
4. Sidecar не блокирует завершение Job — kubelet завершает sidecar вместе с подом

> **Важно:** Sidecar в Job полезен для вспомогательных задач (логирование, мониторинг), которые не должны влиять на критерий завершения Job.

### Sidecar для мониторинга файла — обмен данными через shared volume

Sidecar-контейнер читает файл, в который основное приложение записывает данные. Общий `emptyDir` volume обеспечивает обмен данными между контейнерами.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app-with-file-monitor
spec:
  replicas: 1
  selector:
    matchLabels:
      app: app-with-monitor
  template:
    metadata:
      labels:
        app: app-with-monitor
    spec:
      initContainers:
      - name: file-monitor
        image: alpine:latest
        restartPolicy: Always  # Native sidecar — работает весь жизненный цикл пода
        command: ['sh', '-c', 'set -x; tail -f /opt/filelogs/log.txt']
        volumeMounts:
        - name: data
          mountPath: /opt/filelogs
      containers:
      - name: my-app
        image: alpine:latest
        command: ['sh', '-c', 'while true; do echo "log entry" >> /opt/filelogs/log.txt; sleep 1; done']
        volumeMounts:
        - name: data
          mountPath: /opt/filelogs
      volumes:
      - name: data
        emptyDir: {}
```

**Как это работает:**

1. Sidecar `file-monitor` запускается первым (как init с `restartPolicy: Always`)
2. Sidecar начинает ожидать файл через `tail -f` — файл ещё не существует, sidecar ждёт
3. Запускается основной контейнер `my-app`
4. `my-app` каждую секунду записывает строку в `/opt/filelogs/log.txt`
5. Sidecar видит появление данных и выводит их в лог

**Проверка:**

```bash
# Посмотреть логи sidecar (читает файл)
kubectl logs <pod-name> -c file-monitor -f

# Посмотреть логи основного контейнера (пишет в файл)
kubectl logs <pod-name> -c my-app

# describe покажет sidecar в разделе Init Containers, но со статусом Running
kubectl describe pod <pod-name>
# Init Containers:
#   file-monitor:  Running  (restartPolicy: Always)
# Containers:
#   my-app:  Running
```

> **Важно:** При изменении `initContainers` в Deployment kubelet пересоздаёт под — это вызывает кратковременный downtime. Sidecar-контейнеры не влияют на это поведение.

### Nginx Sidecar для раздачи статики

Nginx sidecar кэширует статику, выполняет rate limiting и TLS-терминацию:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-nginx-sidecar
spec:
  containers:
  - name: app
    image: my-api:1.0
    ports:
    - containerPort: 8080
  - name: nginx
    image: nginx:1.28.0
    ports:
    - containerPort: 80
    volumeMounts:
    - name: static-content
      mountPath: /usr/share/nginx/html
  volumes:
  - name: static-content
    emptyDir: {}
```

**Применение в Service:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: app-service
spec:
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 80  # Трафик идёт на Nginx sidecar, не на приложение
```

Подробнее: [Service и Sidecar](../../Networking/Service/service_overview.md).

### Ambassador для проброса localhost-трафика

**Проблема:** Приложение внутри контейнера слушает **только на `127.0.0.1`** (localhost), и это нельзя изменить — нет доступа к конфигурации или исходному коду. Внешний трафик от Service не может попасть на localhost контейнера.

**Решение:** Sidecar-контейнер в том же поде работает как **ambassador** — принимает трафик на `0.0.0.0` и проксирует его на `127.0.0.1` основного приложения. Контейнеры в поде разделяют сетевой namespace, поэтому `127.0.0.1` — общий для всех.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-localhost-proxy
spec:
  containers:
  - name: app
    image: legacy-app:1.0  # Слушает только на 127.0.0.1:8080
    # Приложение не конфигурируется — нельзя изменить bind address

  - name: localhost-proxy
    image: nginx:alpine
    # Nginx принимает трафик на 0.0.0.0:80 и проксируем на 127.0.0.1:8080
    volumeMounts:
    - name: nginx-config
      mountPath: /etc/nginx/conf.d
  volumes:
  - name: nginx-config
    configMap:
      name: nginx-proxy-config
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: nginx-proxy-config
data:
  proxy.conf: |
    server {
      listen 80;
      location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
      }
    }
---
apiVersion: v1
kind: Service
metadata:
  name: app-service
spec:
  selector:
    app: legacy-app
  ports:
  - port: 80
    targetPort: 80  # Трафик идёт на sidecar, он проксирует на localhost приложения
```

> **Предостережение:** Правильный подход — исправить приложение, чтобы оно слушало на `0.0.0.0`. Sidecar-прокси — временная мера для legacy-приложений.

### Adapter Pattern для форматирования метрик

Adapter преобразует метрики приложения в формат Prometheus:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-adapter
spec:
  containers:
  - name: app
    image: legacy-app:1.0
    # Приложение пишет метрики в собственном формате
  - name: metrics-adapter
    image: prometheus-adapter:1.0
    # Преобразует метрики в формат Prometheus
    ports:
    - containerPort: 9090
```

---

## Дополнительная информация

### Особенности поведения

- **Изменение образа sidecar-контейнера:** изменение образа sidecar-контейнера (определённого как init-контейнер с `restartPolicy: Always`) в спецификации пода **не вызывает** автоматический перезапуск пода (в отличие от изменения образа основного контейнера в Deployment). Для применения изменений требуется пересоздать под вручную или через контроллер (Deployment, StatefulSet).
- **Уникальность имён, Resource sharing:** общие для всех контейнеров пода правила описаны в разделе [Общие ресурсы контейнеров в поде](./pod_overview.md#общие-ресурсы-контейнеров-в-поде).

> **Практическое следствие:** При обновлении sidecar-контейнера в Deployment нужно изменить также образ основного контейнера или добавить аннотацию/хеш для triggers rolling update. Иначе sidecar продолжит работать в старой версии.

### См. также

- [Init Containers](./pod_init_containers.md)
- [Жизненный цикл пода](./pod_lifecycle_and_state.md)
- [Service Overview](../../Networking/Service/service_overview.md)
