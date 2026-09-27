# Karma Deployment: Развёртывание дашборда

## Определения

**Karma Deployment** — ресурс Kubernetes для запуска визуального интерфейса алертов. Является полностью stateless-приложением (не требует PVC), которое агрегирует данные из одного или нескольких API Alertmanager и предоставляет удобный UI для фильтрации и управления оповещениями.

> **См. также:** [Дашборд Karma — архитектура и возможности](../../../karma_dashboard.md).

---

## Предварительные требования

Перед применением манифеста Deployment убедитесь, что окружение подготовлено:

- Рабочий кластер Kubernetes с установленным `kubectl` и правами администратора в namespace `monitoring`.
- Созданный namespace `monitoring` (`kubectl create namespace monitoring`).
- Развёрнутый Alertmanager StatefulSet с рабочим ClusterIP Service (`alertmanager.monitoring.svc.cluster.local:9093`).
- Созданный ConfigMap `karma-config` в namespace `monitoring` (см. [Конфигурация (ConfigMap)](./karma-config.md)).
- Созданный Service `karma` в namespace `monitoring` (см. [Сетевой доступ: Сервисы и Ingress](./services.md)).

---

## Основные концепции

### Характеристики пода Karma

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Образ** | `ghcr.io/prymitive/karma:v0.131` | Стабильная версия (2026) с поддержкой Vite и React 19. |
| **Порт** | `8080` | Стандартный TCP порт для веб-интерфейса. |
| **Пробы** | HTTP GET `/health` | Механизмы проверки готовности и живучести контейнера. |
| **Безопасность** | Non-root | Запуск от не привилегированного пользователя для защиты кластера. |

### Архитектура: почему Deployment, а не StatefulSet

Karma не хранит состояние на диске и не участвует в кластеризации через Gossip-протокол (в отличие от Alertmanager). Поэтому Deployment — достаточный и правильный контроллер: он создаёт stateless-поды с динамическими IP и обеспечивает Rolling Update без привязки к сетевым идентификаторам. StatefulSet требуется только для Alertmanager из-за необходимости стабильных DNS-имён и PersistentVolume для хранения silences.

### Безопасность и изоляция контейнера

| Поле | Значение | Обоснование |
| :--- | :--- | :--- |
| `runAsUser: 65534` | Пользователь `nobody` | Запрет запуска от root; даже при компрометации контейнера атакующий не получит root-доступ на узле. |
| `runAsGroup: 65534` | Группа `nobody` | Согласованность с `runAsUser` для POSIX-прав на файлы. |
| `fsGroup: 65534` | Группа тома | При монтировании ConfigMap Tom запускается от `nobody`; `fsGroup` гарантирует, что права на том позволят чтение. |
| `readOnly: true` | Read-only том | Защита конфигурации от случайного изменения или записи вредоносным кодом в контейнере. |

### Стратегия обновления RollingUpdate

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0
```

- `maxSurge: 1` — контроллер может создать 1 под сверх желаемого количества (`replicas: 1`). Это обеспечивает готовность нового пода до остановки старого.
- `maxUnavailable: 0` — во время обновления старый под не завершается, пока новый не пройдёт readiness-пробы. Для Karma с 1 репликой это гарантирует отсутствие простоев UI.

> **Важно:** Readiness probe критична для работы RollingUpdate. Если проба возвращает ошибку, контроллер не переключит трафик на новый под, и rollout повиснет.

### Пробы жизнеспособности и готовности

| Проба | Эндпоинт | `initialDelaySeconds` | `periodSeconds` | Назначение |
| :--- | :--- | :--- | :--- | :--- |
| **Readiness** | `GET /health` | `5` | `10` | Включение пода в Service Endpoints. Если проба падает, трафик прекращается, но под не перезапускается. |
| **Liveness** | `GET /health` | `10` | `20` | Перезапуск контейнера при зависании процесса. Более мягкие параметры, чтобы не убить под во время холодного старта. |

Эндпоинт `/health` проверяет способность Karma опросить хотя бы один Alertmanager. Если бэкенд недоступен, проба возвращает `503`, и под исключается из балансировки Service. Это предотвращает доступ пользователей к неработающему UI.

### Ресурсы и QoS

| Параметр | CPU | Memory | Назначение |
| :--- | :--- | :--- | :--- |
| `requests` | `100m` | `128Mi` | Гарантированное выделение; влияет на планирование и базовый QoS `Burstable`. |
| `limits` | `200m` | `256Mi` | Жёсткий потолок; защита от consumption аномалий и OOMKill соседних подов на узле. |

Для Karma с 1 репликой и статическим UI лимиты `200m/256Mi` достаточны. При увеличении реплик или нагрузке на вкладку с тысячами алертов мониторьте `karma_alertmanager_requests_duration_seconds` и готовьтесь увеличить лимит памяти до `512Mi`.

### Монтирование конфигурации

ConfigMap монтируется в под Karma как read-only том:

```yaml
volumeMounts:
  - name: config
    mountPath: /etc/karma
    readOnly: true
volumes:
  - name: config
    configMap:
      name: karma-config
```

Karma считывает `config.yaml` только при старте. Изменение ConfigMap в кластере не приводит к автоматическому перезапуску пода. Для применения новой конфигурации требуется `kubectl rollout restart deployment/karma -n monitoring` или изменение `spec.template` манифеста Deployment.

> **Важно:** Если требуется Hot Reload без перезапуска пода — используйте контроллер [Reloader](https://github.com/stakater/Reloader) с аннотацией `configmap.reloader.stakater.com/reload: "karma-config"`. Это создаёт зависимость от внешнего контроллера и не рекомендуется для минимальных установок.

---

## Практические сценарии

### Манифест Deployment для Karma

**`karma-deployment.yaml`**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: karma
  namespace: monitoring
spec:
  replicas: 1
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: karma
  template:
    metadata:
      labels:
        app: karma
    spec:
      securityContext:
        runAsUser: 65534
        runAsGroup: 65534
        fsGroup: 65534
      containers:
        - name: karma
          image: ghcr.io/prymitive/karma:v0.131
          args:
            - "--config.file=/etc/karma/config.yaml"
          ports:
            - name: web
              containerPort: 8080
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 200m
              memory: 256Mi
          livenessProbe:
            httpGet:
              path: /health
              port: web
            initialDelaySeconds: 10
            periodSeconds: 20
          readinessProbe:
            httpGet:
              path: /health
              port: web
            initialDelaySeconds: 5
            periodSeconds: 10
          volumeMounts:
            - name: config
              mountPath: /etc/karma
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: karma-config
      terminationGracePeriodSeconds: 30
```

### Применение и первичная валидация

```bash
# Применение манифеста Deployment
kubectl apply -f karma-deployment.yaml
# → deployment.apps/karma created

# Проверка создания Deployment
kubectl get deployment karma -n monitoring -o wide
# → NAME    READY   UP-TO-DATE   AVAILABLE   AGE   CONTAINERS   IMAGES                           SELECTOR
# → karma   1/1     1            1           5s     karma        ghcr.io/prymitive/karma:v0.131   app=karma

# Проверка создания ReplicaSet
kubectl get replicaset -n monitoring -l app=karma
# → NAME               DESIRED   CURRENT   READY   AGE
# → karma-xxxxxx       1         1         1       5s

# Проверка статуса rollout
kubectl rollout status deployment/karma -n monitoring
# → deployment "karma" successfully rolled out

# Проверка подов
kubectl get pods -n monitoring -l app=karma
# → karma-xxxxxx   1/1     Running   0          30s

# Проверка готовности пода
kubectl get pods -n monitoring -l app=karma -o wide
# → NAME         READY   STATUS    RESTARTS   AGE     IP           NODE        NOMINATED NODE   READINESS GATES
# → karma-xxxx   1/1     Running   0          30s     10.244.x.x  <node>      <none>           <none>
```

### Мониторинг rollout'а и состояния подов

```bash
# История ревизий Deployment
kubectl rollout history deployment/karma -n monitoring
# → deployment.apps/karma
# → REVISION  CHANGE-CAUSE
# → 1         <none>

# Описание Deployment ( Conditions, Events )
kubectl describe deployment karma -n monitoring
# → Conditions:
# →   Type            Status  Reason
# →   ----            ------  ------
# →   Available       True    MinimumReplicasAvailable
# →   Progressing     True    NewReplicaSetAvailable

# Описание пода ( securityContext, mounts, probes )
kubectl describe pod -n monitoring -l app=karma
# → Security Context:
# →   runAsUser: 65534
# →   runAsGroup: 65534
# →   fsGroup: 65534
# → Volumes:
# →   config:
# →     Type:      ConfigMap (a volume populated by a ConfigMap)
# →     Name:      karma-config

# Проверка монтирования ConfigMap внутри пода
POD=$(kubectl get pods -n monitoring -l app=karma -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n monitoring $POD -- cat /etc/karma/config.yaml
# → содержимое должно совпадать с ожидаемым

# Проверка логов на ошибки парсинга конфигурации
kubectl logs -n monitoring $POD | grep -i "config\|error\|parse"
# → (пусто, если ошибок нет)
```

### Валидация изнутри пода

```bash
# Получение имени пода
POD=$(kubectl get pods -n monitoring -l app=karma -o jsonpath='{.items[0].metadata.name}')

# Проверка доступности Alertmanager из пода Karma
kubectl exec -n monitoring $POD -- curl -s http://alertmanager.monitoring.svc.cluster.local:9093/api/v2/alerts
# → [] (если алертов нет) или JSON со списком алертов

# Проверка health endpoint
kubectl exec -n monitoring $POD -- curl -s http://localhost:8080/health
# → {"status":"healthy"}
```

### Устранение неисправностей

| Симптом | Возможная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Pod в CrashLoopBackOff | Ошибка в аргументе `--config.file` или правах на том | `kubectl describe pod -n monitoring <karma-pod>`; проверить путь монтирования и права `fsGroup`. |
| Pod в ImagePullBackOff | Неверный тег образа или недоступность `ghcr.io` | `kubectl describe pod -n monitoring <karma-pod>` → Events; проверить `imagePullPolicy: IfNotPresent` или `Always`. |
| Pod Ready=0/1, Readiness probe failing | Endpoint `/health` возвращает 503 | `kubectl logs -n monitoring <karma-pod>`; проверить доступность Alertmanager и корректность `config.yaml`. |
| Pod Ready=0/1, Liveness probe failing | Зависание процесса или утечка памяти | `kubectl logs -n monitoring <karma-pod> --previous`; проверить лимиты памяти и логи. |
| Rollout завис на 0/1 | Недостаточно ресурсов узла или PDB блокирует | `kubectl describe node <node>`; `kubectl get poddisruptionbudget -n monitoring`; проверить `kubectl get events -n monitoring`. |
| Pod не перезапускается после изменения ConfigMap | Ожидается поведение: ConfigMap не триггерит перезапуск | `kubectl rollout restart deployment/karma -n monitoring`. |
| Ошибка парсинга YAML | Синтаксическая ошибка в `config.yaml` | `kubectl logs -n monitoring <karma-pod> | grep -i parse`; исправить YAML и применить ConfigMap заново. |

### Мониторинг Karma через ServiceMonitor

Для отслеживания здоровья самого дашборда Karma настройте ServiceMonitor. Подробности по синтаксису CRD — в [ServiceMonitor CRD](../../../../Kubernetes/Prometheus/kubernetes/operator/crd/servicemonitor.md).

**`karma-servicemonitor.yaml`**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: karma
  namespace: monitoring
  labels:
    release: kube-prometheus-stack  # Должен совпадать с serviceMonitorSelector Prometheus
spec:
  selector:
    matchLabels:
      app: karma
  namespaceSelector:
    matchNames:
      - monitoring
  endpoints:
    - port: web
      path: /metrics
      interval: 30s
```

```bash
kubectl apply -f karma-servicemonitor.yaml
# → servicemonitor.monitoring.coreos.com/karma created

# Проверка, что Prometheus обнаружил цель
kubectl port-forward -n monitoring svc/prometheus 9090:9090 &
# → Откройте http://localhost:9090/targets и найдите job "karma"
```

### PodDisruptionBudget для Karma

PDB защищает Karma от одновременного удаления всех реплик при обслуживании узлов (`kubectl drain`). Подробности по синтаксису — в [PDB](../../../../Kubernetes/Autoscaling/pod_disruption_budget.md).

**`karma-pdb.yaml`**

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: karma-pdb
  namespace: monitoring
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: karma
```

> **Важно:** PDB блокирует только *добровольные* прерывания (eviction через `kubectl drain`). Прямое `kubectl delete pod` игнорирует PDB.

```bash
kubectl apply -f karma-pdb.yaml
# → poddisruptionbudget.policy/karma-pdb created

# Проверка допустимых прерываний
kubectl get pdb -n monitoring karma-pdb
# → NAME        MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → karma-pdb   1               <none>            0                     5s
```

### Reloader (Stakater) для горячей перезагрузки

Karma читает `config.yaml` только при старте. Для автоматической перезагрузки при изменении ConfigMap без ручного `kubectl rollout restart` используйте контроллер [Reloader](https://github.com/stakater/Reloader). Подробности по альтернативам — в [Обзор Reloader](../../../../Kubernetes/ToolsUtilities/reloader/reloader_overview.md).

Добавьте аннотацию к манифесту Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: karma
  namespace: monitoring
  annotations:
    configmap.reloader.stakater.com/reload: "karma-config"
spec:
  # ... остальной контент Deployment
```

> **Важно:** Reloader должен быть установлен в кластере (`helm install reloader stakater/reloader -n monitoring`). Без него аннотация игнорируется, и перезапуск остаётся ручным.

```bash
# Установка Reloader (если не установлен)
helm repo add stakater https://stakater.github.io/stakater-charts
helm install reloader stakater/reloader -n monitoring --create-namespace

# Проверка работы Reloader
kubectl get pods -n monitoring -l app=reloader
# → reloader-xxxxx   1/1     Running   0          2m
```

### HorizontalPodAutoscaler для Karma

HPA масштабирует Karma при росте нагрузки (тысячи алертов, множество источников Alertmanager). Подробности по синтаксису HPA — в [Autoscaling](../../../../Kubernetes/Autoscaling/overview_concepts.md).

> **Важно:** Karma не поддерживает кастомные метрики из коробки. Для масштабирования по количеству алертов потребуется Exporter или кастомный Adapters. Стандартный подход — масштабирование по CPU/Memory.

**`karma-hpa.yaml`**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: karma-hpa
  namespace: monitoring
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: karma
  minReplicas: 2
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60
```

> **Важно:** При использовании HPA `replicas` в Deployment опускается (управляется HPA). Убедитесь, что PDB совместим с `minReplicas` HPA: `minAvailable` в PDB должен быть < `minReplicas` в HPA.

```bash
kubectl apply -f karma-hpa.yaml
# → horizontalpodautoscaler.autoscaling/karma-hpa created

# Проверка состояния HPA
kubectl get hpa -n monitoring karma-hpa
# → NAME         REFERENCE          TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
# → karma-hpa   Deployment/karma   35%/70%, 40%/80%   2         5         2          30s
```

### Рекомендации

- **Версионирование:** Храните `karma-deployment.yaml` в Git-репозитории вместе с остальными манифестами. Используйте аннотацию `kubernetes.io/change-cause` для трассируемости (`kubectl annotate deployment/karma kubernetes.io/change-cause="Add readiness probe"`).
- **Изменения без простоя:** Используйте `kubectl rollout restart deployment/karma -n monitoring` вместо прямого удаления пода. Это гарантирует последовательное создание нового пода и проверку readiness перед завершением старого.
- **Image Pull Policy:** В production используйте `imagePullPolicy: IfNotPresent` для закреплённых тегов (например, `v0.131`) или `Always` при использовании `latest`. Это снижает риск неожиданных изменений образа.
- **Replicas:** Для production-сред рекомендуется `replicas: 2` с соответствующей лимитировкой ресурсов и PDB (`minAvailable: 1`), чтобы обеспечить отказоустойчивость при обновлениях узлов.
- **Мультикластер:** При подключении нескольких Alertmanager указывайте уникальные `name` для каждого инстанса — это отображается в UI как источник алерта.
- **Версия Karma:** Перед обновлением образа ознакомьтесь с [CHANGELOG](https://github.com/prymitive/karma/releases) и проверяйте совместимость `config.yaml` с новой версией.

### Очистка ресурсов

```bash
# Удалить Deployment Karma
kubectl delete -f karma-deployment.yaml

# Удалить Service Karma (если создаётся отдельным манифестом)
kubectl delete svc karma -n monitoring

# Проверить отсутствие ресурсов
kubectl get deployment,svc,pods -n monitoring -l app=karma
# → (должен вернуть пустой результат)

# Примечание: ConfigMap karma-config и Secret не удаляются при удалении Deployment.
# Удалите их отдельно, если нужно полностью очистить namespace.
kubectl delete configmap karma-config -n monitoring
```

---

## Дополнительная информация

- **[Конфигурация (ConfigMap)](./karma-config.md)** — настройки подключения к Alertmanager, OIDC, ACL и фильтрация.
- **[Сетевой доступ: Сервисы и Ingress](./services.md)** — публикация интерфейса с SSL и Auth.
- **[Дашборд Karma — общая информация](../../../karma_dashboard.md)** — архитектура, агрегация, ACL, метрики и фильтрация.
- **[Дашборд Karma — Безопасность](../../../karma_dashboard.md#безопасность-и-ingress)** — SSoT по защите UI, OIDC и ACL.
- **[Дашборд Karma — Мониторинг](../../../karma_dashboard.md#мониторинг-самой-karma)** — метрики и контроль здоровья.
- **[ServiceMonitor CRD](../../../../Kubernetes/Prometheus/kubernetes/operator/crd/servicemonitor.md)** — детали синтаксиса CRD для мониторинга.
- **[Pod Disruption Budget](../../../../Kubernetes/Autoscaling/pod_disruption_budget.md)** — защита доступности при обслуживании узлов.
- **[Reloader](../../../../Kubernetes/ToolsUtilities/reloader/reloader_overview.md)** — автоматическая перезагрузка при изменении ConfigMap/Secret.
