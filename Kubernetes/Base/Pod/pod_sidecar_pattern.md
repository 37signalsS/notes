# Init Containers и Sidecar Pattern в Kubernetes

## Определения

**Init Container** — контейнер, который запускается и должен успешно завершиться перед запуском основных контейнеров приложения. Выполняются последовательно, один за другим.

**Sidecar Pattern** — паттерн многоконтейнерного пода, где один контейнер является основным (приложение), а другой (сайдкар) выполняет вспомогательную функцию, расширяющую возможности основного приложения.

**Adapter Pattern** — вариация sidecar, преобразующая данные основного приложения для внешних систем (например, форматирование метрик для Prometheus).

**Ambassador Pattern** — вариация sidecar, управляющая внешними соединениями (например, проксирование запросов через Envoy).

**Native Sidecar** — механизм Kubernetes 1.29+ (stable в 1.33+), позволяющий определить sidecar как init-контейнер с `restartPolicy: Always`, работающий на протяжении всего жизненного цикла пода ([KEP-3839](https://github.com/kubernetes/enhancements/blob/master/keps/sig-node/3839-sidecar-containers.md)).

---

## Базовые концепции

### Init Containers: Назначение и сценарии

Init-контейнеры подходят для выполнения подготовительных задач, отделённых от логики основного приложения:

| Сценарий | Описание |
| :--- | :--- |
| Подготовка конфигурации | Генерация или модификация конфигурационных файлов для основного приложения |
| Ожидание зависимостей | Блокировка запуска до доступности внешних сервисов (БД, API) |
| Миграции БД | Запуск скриптов обновления схемы БД перед стартом приложения |
| Управление правами | Изменение прав на файлы в томах для непривилегированного пользователя |
| Скачивание артефактов | Загрузка файлов, библиотек или бинарников из репозитория |

**Ключевые отличия от обычных контейнеров:**

| Характеристика | Init Container | Обычный контейнер |
| :--- | :--- | :--- |
| Порядок запуска | До `containers`, последовательно | Параллельно с другими |
| Завершение | Должен завершиться с кодом `0` | Работает до остановки |
| Probes | Не имеют `livenessProbe`, `readinessProbe`, `startupProbe` | Имеют все типы проб |
| Перезапуск | При ошибке `kubelet` перезапускает по `restartPolicy` | По `restartPolicy` пода |

### Sidecar Pattern: Виды и применение

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

**Где критически важно:**

- Прямая зависимость: приложение падает без готового sidecar (прокси, логгер)
- Service Mesh: Istio, Envoy
- Сборщики логов: Fluentd, Fluent Bit
- Динамическая загрузка конфигурации

---

## Практические сценарии

### Пример 1: Init Container для ожидания зависимости

Init-контейнер ожидает доступности БД перед запуском основного приложения:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-init
spec:
  containers:
  - name: app-container
    image: my-app:1.0
    ports:
    - containerPort: 8080
  initContainers:
  - name: wait-for-db
    image: busybox:1.36
    command: ['sh', '-c', 'until nc -z db-service 5432; do echo "Waiting for DB..." && sleep 2; done']
```

### Пример 2: Sidecar для сбора логов

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

### Пример 3: Native Sidecar с гарантированным запуском

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

### Пример 4: Nginx Sidecar для раздачи статики

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

### Пример 6: Ambassador для проброса localhost-трафика

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

> **Предостережение:**  Правильный подход — исправить приложение, чтобы оно слушало на `0.0.0.0`. Sidecar-прокси — временная мера для legacy-приложений.

### Пример 7: Adapter Pattern для форматирования метрик

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

**Связанные темы:** [Жизненный цикл пода](./pod_lifecycle_and_state.md), [Обзор пода](./pod_overview.md), [Deployment с sidecar](../Deployment/deployment_manifest.md), [Service и targetPort](../../Networking/Service/service_overview.md), [KEP-3839: Native Sidecar](https://github.com/kubernetes/enhancements/blob/master/keps/sig-node/3839-sidecar-containers.md).
