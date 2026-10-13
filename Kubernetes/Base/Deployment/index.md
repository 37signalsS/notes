# Deployment в Kubernetes

**Актуально для:** Kubernetes 1.30–1.32+

Декларативное управление жизненным циклом stateless-приложений, координация контроллеров ReplicaSet и обеспечение непрерывной доступности рабочих нагрузок (Zero-Downtime) в инфраструктуре bare-metal и on-premise кластеров.

Файл является центральной точкой входа и навигатором раздела Deployment. Материал ориентирован на инженеров DevOps, SRE и системных администраторов.

---

## Определения

**Deployment** — высокоуровневый декларативный контроллер ядра Kubernetes (API-группа `apps/v1`), управляющий развертыванием, масштабированием, обновлением и самоисцелением идентичных реплик stateless-приложений.

**ReplicaSet** — низкоуровневый контроллер, гарантирующий постоянное поддержание заданного количества идентичных подов (`spec.replicas`). Deployment не создает поды напрямую, а управляет наборами ReplicaSet.

**Stateless Workload (Нагрузка без сохранения состояния)** — архитектурный паттерн приложения, при котором поды полностью взаимозаменяемы, не привязаны к конкретному узлу или монопольному локальному диску, а состояние сессий вынесено во внешние хранилища (СУБД, Redis, S3/MinIO).

**Reconciliation Loop (Цикл согласования)** — непрерывный цикл контроллера `deployment-controller` в составе `kube-controller-manager`, сравнивающий желаемое состояние (`spec`) с фактическим состоянием кластера (`status`) и приводящий систему к целевому виду.

**PodTemplateSpec (`spec.template`)** — спецификация шаблона пода. Любое изменение содержимого этого блока инициирует создание новой ревизии и запуск процесса Rollout.

**Метка `pod-template-hash`** — 32-битный FNV-1a хеш от спецификации `PodTemplateSpec`, автоматически добавляемый контроллером в метки ReplicaSet и подов для разграничения реплик между старыми и новыми версиями.

**Rollout (Выкатка)** — процесс перехода Deployment с текущего шаблона пода на новый. Управляется выбранной стратегией обновления.

**Revision (Ревизия)** — номер версии конфигурации Deployment, фиксируемый в аннотации `deployment.kubernetes.io/revision` связанного ReplicaSet. Позволяет инспектировать историю изменений и выполнять откат.

**Rollback (Откат)** — возврат спецификации Deployment к шаблону одной из предыдущих ревизий через команду `kubectl rollout undo`. В архитектуре Kubernetes откат порождает новую ревизию, копирующую параметры старого ReplicaSet.

**Rollover (Прерывание выкатки)** — механизм контроллера, при котором новое обновление манифеста принимается до завершения предыдущего rollout. Контроллер не ожидает стабилизации промежуточной версии, а сразу начинает масштабировать ее вниз и разворачивать целевую.

**Proportional Scaling (Пропорциональное масштабирование)** — алгоритм распределения дополнительных или удаляемых реплик между всеми активными ReplicaSet, если изменение `spec.replicas` происходит в момент незавершенного Rollout.

**Стратегии обновления (`spec.strategy.type`):**
- **`RollingUpdate`** — пошаговая ротация подов без прерывания обслуживания (Zero-Downtime) с контролем допустимого всплеска (`maxSurge`) и временной недоступности (`maxUnavailable`).
- **`Recreate`** — полная остановка и удаление всех старых подов перед запуском новых. Приводит к гарантированному технологическому простою (downtime).

**Status Conditions** — системные статусные условия объекта (`Available`, `Progressing`, `ReplicaFailure`), отражающие ход выкатки, готовность подов и блокирующие ошибки.

**Owner References и Каскадное удаление** — метаданные родства ресурсов (`metadata.ownerReferences`). При удалении Deployment сборщик мусора (Garbage Collector) Kubernetes удаляет зависимые ReplicaSet и Pods согласно выбранной политике (`Background`, `Foreground` или `Orphan`).

---

## Архитектура и принцип работы

### Иерархия контроллеров и механизм управления

Deployment реализует двухуровневую модель управления рабочей нагрузкой:

```text
               kube-apiserver
                     │
                     ▼
         kube-controller-manager
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
 deployment-controller   replicaset-controller
         │                       │
         │ (управляет RS)         │ (управляет Pods)
         ▼                       ▼
    ReplicaSet (v1) ───────► Pod [v1] (Active)
    ReplicaSet (v2) ───────► Pod [v2] (Rolling)
```

1. **`deployment-controller`**: отслеживает изменения объекта Deployment в etcd через SharedInformer. При изменении `spec.template` вычисляет хеш шаблона, создает новый объект `ReplicaSet` или находит существующий с таким же шаблоном, после чего плавно меняет поле `spec.replicas` у старого и нового ReplicaSet.
2. **`replicaset-controller`**: отслеживает поды с соответствующим `pod-template-hash` и селектором. Создает новые поды через вызовы API-сервера или отправляет запросы на удаление лишних экземпляров.
3. **`kubelet`**: на рабочих узлах запускает и останавливает контейнеры через CRI (containerd/CRI-O), выполняет пробы (`readinessProbe`, `livenessProbe`, `startupProbe`) и передает статус обратно в API.

### Алгоритм RollingUpdate под капотом

В стратегии `RollingUpdate` контроллер балансирует количество подов на основе параметров `maxSurge` и `maxUnavailable`:

- **`maxSurge`** (по умолчанию `25%`): максимальное число подов сверх целевого `spec.replicas`.
- **`maxUnavailable`** (по умолчанию `25%`): максимально допустимое число неготовых или отсутствующих подов относительно `spec.replicas`.

#### Математические границы процесса:
- **Максимальное число подов в любой момент времени:**  
  $$\text{MaxPods} = \text{replicas} + \text{maxSurge}$$
- **Минимальное число доступных подов в любой момент времени:**  
  $$\text{MinAvailable} = \text{replicas} - \text{maxUnavailable}$$

#### Пошаговая механика ротации:
1. Контроллер создает новый ReplicaSet с меткой `pod-template-hash=<new_hash>` и начальным числом реплик 0.
2. Новый ReplicaSet масштабируется вверх на величину `maxSurge`.
3. Kubelet запускает новые контейнеры. Под считается доступным (`Available`) только после успешного прохождения `readinessProbe` и истечения интервала `minReadySeconds`.
4. Как только новый под стал готов, контроллер масштабирует старый ReplicaSet вниз на 1 реплику.
5. Процесс циклически повторяется до тех пор, пока новый ReplicaSet не достигнет `spec.replicas`, а старый — 0.
6. Старый ReplicaSet не удаляется, а сохраняется в etcd со значением `spec.replicas: 0` для возможности мгновенного отката.

### Механика сетевого взаимодействия и Zero-Downtime

Одной готовности `readinessProbe` недостаточно для исключения сетевых ошибок при выкатке. В распределенном кластере удаление старого пода и обновление сетевых маршрутов происходят асинхронно:

```text
Событие удаления пода (Delete Pod)
    │
    ├──► 1. API Server удаляет Pod из EndpointSlice ──► kube-proxy обновляет IPVS/iptables (задержка 1-5 сек)
    │
    └──► 2. kubelet отправляет SIGTERM в контейнер ──► Приложение немедленно завершает работу
```

Если приложение завершается сразу при получении `SIGTERM`, клиенты получают ошибки `502 Bad Gateway` или `Connection Refused`, так как сетевые пакеты еще маршрутизируются на IP удаляемого пода.

#### Архитектурное решение проблемы:
1. **Хук `lifecycle.preStop`**: вызов задержки `sleep 5..10` перед отправкой `SIGTERM`. Это дает время `kube-proxy` на всех рабочих узлах исключить IP пода из локальных правил IPVS/iptables.
2. **Параметр `terminationGracePeriodSeconds`**: должен превышать время выполнения `preStop` плюс время закрытия активных соединений приложения (рекомендуется от 30 до 60 секунд).
3. **Параметры ротации**: установка `maxUnavailable: 0` гарантирует, что вывод старых реплик начнется строго после ввода новых в рабочий пул.

### Алгоритм пропорционального масштабирования (Proportional Scaling)

Если во время активного или приостановленного обновления администратор или HPA изменяет `spec.replicas` (например, с 10 до 15), контроллер не отдает все новые реплики в новый ReplicaSet:

1. Вычисляется текущая доля реплик между всеми активными ReplicaSet.
2. Дополнительные реплики распределяются пропорционально между старым и новым ReplicaSet.
3. Это предотвращает исчерпание вычислительных ресурсов узлов и сохраняет баланс доступности, пока новый образ не подтвердил стабильность.

### Сравнение стратегий обновления

| Параметр / Характеристика | RollingUpdate | Recreate |
| :--- | :--- | :--- |
| **Доступность сервиса** | 100% (Zero-Downtime при корректных пробах) | Простой (Downtime) на время перезапуска |
| **Расход ресурсов узлов** | Требует запас CPU/RAM на величину `maxSurge` | Не требует запаса (освобождает ресурсы старых подов) |
| **Версионность в рантайме** | Некоторое время одновременно работают версии N и N+1 | В рантайме всегда работает только одна версия |
| **Совместимость с БД** | Требует обратно-совместимых миграций схемы | Допускает ломающие миграции перед стартом |
| **Работа с RWO дисками** | Риск `Multi-Attach error` при перепривязке | Безопасна для монопольных блочных томов (Ceph RBD, Local PV) |
| **Основное назначение** | Production stateless web-сервисы, API, воркеры | Тестовые стенды, монопольные сервисы, несовместимые схемы |

---

## Анатомия манифеста

### Базовый пример манифеста

Манифест промышленного stateless-сервиса с гарантированным отсутствием простоев и защитой от типовых инфраструктурных сбоев:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-service
  namespace: production
  labels:
    app.kubernetes.io/name: api-service
    app.kubernetes.io/instance: production
    app.kubernetes.io/part-of: backend
spec:
  replicas: 3
  revisionHistoryLimit: 5
  minReadySeconds: 10
  progressDeadlineSeconds: 600
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: api-service
  template:
    metadata:
      labels:
        app.kubernetes.io/name: api-service
    spec:
      terminationGracePeriodSeconds: 45
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: api
        image: internal-registry.company.local/apps/api:1.28.3
        imagePullPolicy: IfNotPresent
        ports:
        - name: http
          containerPort: 8080
          protocol: TCP
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 10"]
        resources:
          requests:
            cpu: "250m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
        startupProbe:
          httpGet:
            path: /healthz/startup
            port: http
          initialDelaySeconds: 5
          periodSeconds: 5
          failureThreshold: 12
        readinessProbe:
          httpGet:
            path: /healthz/ready
            port: http
          periodSeconds: 5
          successThreshold: 1
          failureThreshold: 2
        livenessProbe:
          httpGet:
            path: /healthz/live
            port: http
          periodSeconds: 10
          failureThreshold: 3
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
```

Подробный разбор каждого параметра спецификации, PSS Restricted профиля и топологических политик см. в [Манифест и лучшие практики](./deployment_manifest.md).

---

## Практические сценарии

### Предварительные требования (Prerequisites)

- Доступ к рабочему кластеру Kubernetes (v1.30+ для полноценной работы; базовый API `apps/v1` стабилен с v1.16+).
- Утилита `kubectl` с настроенным контекстом администратора или оператора неймспейса.
- RBAC-права: `get`, `list`, `watch`, `create`, `update`, `patch`, `delete` для ресурсов `deployments`, `replicasets`, `pods`, `events`.
- Настроенная политика сетевой безопасности и метрик в неймспейсе.

### Сценарий 1: Декларативное развертывание и валидация

Проверка изменений перед применением исключает синтаксические и архитектурные ошибки:

```bash
# 1. Валидация манифеста на стороне сервера (Server-side Dry-Run)
kubectl apply -f deployment.yaml --dry-run=server
# → deployment.apps/api-service configured (server dry run)

# 2. Просмотр различий между локальным манифестом и состоянием в кластере
kubectl diff -f deployment.yaml
# → Вывод стандартного diff (изменения образов, реплик, аннотаций)

# 3. Применение манифеста
kubectl apply -f deployment.yaml
# → deployment.apps/api-service created

# 4. Проверка статуса запуска
kubectl rollout status deployment/api-service --timeout=120s
# → Waiting for deployment "api-service" rollout to finish: 0 of 3 updated replicas are available...
# → Waiting for deployment "api-service" rollout to finish: 1 of 3 updated replicas are available...
# → deployment "api-service" successfully rolled out
```

### Сценарий 2: Обновление версии (Rollout) и фиксация причины

Флаг `--record` окончательно удален из `kubectl` в версии v1.24. Причина изменений фиксируется через аннотацию `kubernetes.io/change-cause`:

```bash
# 1. Обновление версии контейнера
kubectl set image deployment/api-service api=internal-registry.company.local/apps/api:1.29.0
# → deployment.apps/api-service image updated

# 2. Фиксация причины изменения для аудита ревизий
kubectl annotate deployment/api-service kubernetes.io/change-cause="Релиз v1.29.0: фикс утечки памяти в пуле соединений" --overwrite
# → deployment.apps/api-service annotated

# 3. Мониторинг прогресса выкатки в реальном времени
kubectl rollout status deployment/api-service
# → Waiting for deployment "api-service" rollout to finish: 1 out of 3 new replicas have been updated...
# → Waiting for deployment "api-service" rollout to finish: 2 of 3 updated replicas are available...
# → deployment "api-service" successfully rolled out

# 4. Просмотр истории ревизий с комментариями
kubectl rollout history deployment/api-service
# → REVISION  CHANGE-CAUSE
# → 1         Базовая установка приложения
# → 2         Релиз v1.29.0: фикс утечки памяти в пуле соединений
```

### Сценарий 3: Аварийный откат (Rollback)

При деградации метрик или сбое приложения выполняется немедленный возврат на проверенную ревизию:

```bash
# 1. Детальный просмотр спецификации конкретной ревизии перед откатом
kubectl rollout history deployment/api-service --revision=1
# → deployment.apps/api-service with revision #1
# → Pod Template:
# →   Containers:
# →    api:
# →     Image: internal-registry.company.local/apps/api:1.28.3

# 2. Немедленный откат к предыдущей ревизии
kubectl rollout undo deployment/api-service
# → deployment.apps/api-service rolled back

# 3. Откат к конкретной целевой ревизии
kubectl rollout undo deployment/api-service --to-revision=1
# → deployment.apps/api-service rolled back

# 4. Проверка возврата состояния подов
kubectl get pods -l app.kubernetes.io/name=api-service
# → NAME                           READY   STATUS    RESTARTS   AGE
# → api-service-7bb8c54968-4m2zx   1/1     Running   0          25s
# → api-service-7bb8c54968-8xptl   1/1     Running   0          22s
# → api-service-7bb8c54968-v9q1a   1/1     Running   0          18s
```

Детальные сценарии автоматизации отката по метрикам Prometheus см. в [Продвинутые стратегии отката](./advanced_rollback_strategies.md).

### Сценарий 4: Масштабирование нагрузки

Масштабирование меняет количество реплик без создания новой ревизии в истории Deployment:

```bash
# 1. Императивное масштабирование
kubectl scale deployment/api-service --replicas=5
# → deployment.apps/api-service scaled

# 2. Декларативное масштабирование через патч (предпочтительно для скриптов)
kubectl patch deployment api-service --type='json' -p='[{"op": "replace", "path": "/spec/replicas", "value": 5}]'
# → deployment.apps/api-service patched

# 3. Проверка распределения подов по узлам
kubectl get pods -l app.kubernetes.io/name=api-service -o wide
# → NAME                           READY   STATUS    RESTARTS   AGE   IP            NODE
# → api-service-7bb8c54968-4m2zx   1/1     Running   0          3m    10.244.1.42   worker-01
# → api-service-7bb8c54968-8xptl   1/1     Running   0          3m    10.244.2.19   worker-02
# → api-service-7bb8c54968-v9q1a   1/1     Running   0          3m    10.244.3.77   worker-03
```

> **Важно:** При использовании [HPA](../../Autoscaling/HPA/index.md) управление полем `spec.replicas` передается контроллеру HPA. Ручные изменения `spec.replicas` будут перезаписаны в следующем цикле сверки HPA.

### Сценарий 5: Пауза, пакетные изменения и перезапуск

Пауза блокирует запуск Rollout при последовательном внесении нескольких изменений в спецификацию:

```bash
# 1. Приостановка контроллера Deployment
kubectl rollout pause deployment/api-service
# → deployment.apps/api-service paused

# 2. Внесение нескольких изменений (образ, ресурсы, переменные окружения)
kubectl set image deployment/api-service api=internal-registry.company.local/apps/api:1.29.1
kubectl set resources deployment/api-service -c=api --limits=memory=1Gi --requests=memory=512Mi

# 3. Возобновление работы (запускается единый Rollout для всех правок сразу)
kubectl rollout resume deployment/api-service
# → deployment.apps/api-service resumed

# 4. Принудительный перезапуск подов (например, после обновления ConfigMap/Secret)
kubectl rollout restart deployment/api-service
# → deployment.apps/api-service restarted
```

Подробнее о тонкостях управления жизненным циклом см. в [Управление жизненным циклом](./lifecycle_management.md).

### Сценарий 6: Управление каскадным удалением

При удалении Deployment системный администратор может контролировать поведение дочерних ReplicaSet и подов:

```bash
# 1. Стандартное каскадное удаление (удаляет Deployment, все ReplicaSet и Pods)
kubectl delete deployment api-service
# → deployment.apps "api-service" deleted

# 2. Фоновое удаление (Background — удаление Deployment мгновенно, дочерние удаляются асинхронно)
kubectl delete deployment api-service --cascade=background
# → deployment.apps "api-service" deleted

# 3. Синхронное удаление (Foreground — блокирует команду до полного завершения всех подов)
kubectl delete deployment api-service --cascade=foreground
# → deployment.apps "api-service" deleted

# 4. Изолированное удаление (Orphan — удаляет только Deployment, оставляя ReplicaSet и Pods работать)
kubectl delete deployment api-service --cascade=orphan
# → deployment.apps "api-service" deleted
```

---

## Операции и команды

Сводная таблица основных операций управления Deployment для дежурных инженеров и администраторов:

| Операция | Команда | Назначение и контекст |
| :--- | :--- | :--- |
| **Применение** | `kubectl apply -f deploy.yaml` | Декларативное создание или синхронизация конфигурации |
| **Dry-Run проверка** | `kubectl apply -f deploy.yaml --dry-run=server` | Валидация схемы и прав на API-сервере без применения |
| **Статус выкатки** | `kubectl rollout status deployment/<name>` | Блокирующий мониторинг до успешного завершения или таймаута |
| **История ревизий** | `kubectl rollout history deployment/<name>` | Список ревизий с отображением причины изменений |
| **Детали ревизии** | `kubectl rollout history deployment/<name> --revision=2` | Просмотр PodTemplateSpec конкретной исторической ревизии |
| **Откат назад** | `kubectl rollout undo deployment/<name>` | Откат к непосредственно предыдущей ревизии |
| **Целевой откат** | `kubectl rollout undo deployment/<name> --to-revision=1` | Откат к выбранному номеру ревизии |
| **Пауза выкатки** | `kubectl rollout pause deployment/<name>` | Заморозка rollout для пакетного внесения изменений |
| **Снятие паузы** | `kubectl rollout resume deployment/<name>` | Разморозка контроллера и применение накопленных изменений |
| **Перезапуск подов** | `kubectl rollout restart deployment/<name>` | Инициирует пересоздание всех подов через rolling update |
| **Масштабирование** | `kubectl scale deployment/<name> --replicas=5` | Изменение количества реплик без создания новой ревизии |
| **Поиск ReplicaSet** | `kubectl get rs -l app.kubernetes.io/name=<name>` | Список активных и исторических ReplicaSet деплоймента |
| **События сбоев** | `kubectl describe deployment/<name>` | Просмотр status conditions, scaling events и ошибок квот |

---

## Диагностика и устранение неполадок

### Пошаговый алгоритм расследования инцидентов

При сбое или зависании выкатки диагностика выполняется по цепочке абстракций сверху вниз:

```text
1. Deployment Status & Conditions
   └──► kubectl describe deployment <name>
        └──► 2. ReplicaSet Events
             └──► kubectl describe rs <rs-name>
                  └──► 3. Pod Status & Events
                       └──► kubectl describe pod <pod-name>
                            └──► 4. Container Logs
                                 └──► kubectl logs <pod-name> --previous
```

### Матрица типовых сбоев и решений

| Симптом / Ошибка | Первопричина | Метод диагностики | Пошаговое устранение |
| :--- | :--- | :--- | :--- |
| **`ImagePullBackOff` / `ErrImagePull`** | Опечатка в имени/теге, недоступен локальный реестр, отсутствие `imagePullSecrets` | `kubectl describe pod <name>` (секция Events) | 1. Проверить доступность реестра с узла.<br>2. Проверить секрет авторизации.<br>3. Исправить тег через `kubectl set image`. |
| **`CrashLoopBackOff`** | Сбой процесса внутри контейнера (exit code != 0), ошибка в конфиге | `kubectl logs <pod> --previous`<br>`kubectl logs <pod> -c <container>` | 1. Проверить логи аварийного завершения.<br>2. Проверить корректность env, ConfigMap и монтирования томов. |
| **`OOMKilled` (Exit Code 137)** | Превышение лимита оперативной памяти `limits.memory` | `kubectl describe pod <name>` (Last State: Terminated, Reason: OOMKilled) | 1. Проверить профиль потребления памяти.<br>2. Увеличить `limits.memory`.<br>3. Устранить утечку памяти в приложении. |
| **`ProgressDeadlineExceeded`** | Выкатка зависла дольше `progressDeadlineSeconds` (не проходят пробы) | `kubectl rollout status deployment/<name>`<br>`kubectl describe deployment <name>` | 1. Выявить непрошедшую пробу (`readinessProbe` / `startupProbe`).<br>2. Выполнить `kubectl rollout undo` для восстановления сервиса.<br>3. Скорректировать пороги проб. |
| **`Pending` подов** | Недостаток CPU/RAM на узлах, строгие правила Affinity, Taints без Tolerations | `kubectl describe pod <name>` (Events: 0/N nodes are available...) | 1. Проверить загрузку узлов: `kubectl top nodes`.<br>2. Проверить квоты неймспейса: `kubectl describe quota`.<br>3. Скорректировать `requests` или добавить воркер-ноды. |
| **Всплеск 502/504 при Rollout** | Контейнер завершается до обновления правил маршрутизации в сети | Анализ логов Ingress-контроллера / Envoy в момент деплоя | 1. Добавить хук `lifecycle.preStop: sleep 10`.<br>2. Увеличить `terminationGracePeriodSeconds: 45`.<br>3. Установить `maxUnavailable: 0`. |
| **`field is immutable` (Selector)** | Попытка изменить неизменяемое поле `spec.selector.matchLabels` | Ошибка при `kubectl apply -f deployment.yaml` | Поле селектора нельзя менять. Требуется создать Deployment с новым именем или удалить старый (`kubectl delete` → `kubectl apply`). |

Глубокий разбор сложных сценариев, сетевых гонок и деградации производительности см. в:
- [Устранение неполадок и RollingUpdate](./troubleshooting.md)
- [Продвинутые сценарии диагностики](./advanced_troubleshooting_scenarios.md)

---

## Рекомендации и лучшие практики

### Надежность и высокая доступность (SRE)

1. **Безопасная стратегия выкатки для Web-приложений:**  
   Устанавливайте `maxSurge: 25%` и `maxUnavailable: 0`. Это гарантирует, что кластер никогда не снизит текущую доступную емкость ниже 100%, пока новые поды не подтвердят готовность.
2. **Обязательные Requests и Limits:**  
   Ни один под в продакшене не должен запускаться без ресурсов. Для критически важных stateless-компонентов задавайте `requests.cpu == limits.cpu` и `requests.memory == limits.memory` (класс качества обслуживания **Guaranteed**), что минимизирует вероятность завершения процесса OOM-киллером ОС. См. [Управление ресурсами](../../Scheduling/qos_limit_and_requests.md).
3. **Корректная триада проб:**  
   - Используйте `startupProbe` для приложений с медленным стартом (Java, инициализация кешей). Это защищает под от преждевременного убийства со стороны `livenessProbe`.
   - Проверка `readinessProbe` обязана быть легковесной и отражать реальную готовность принимать трафик. Используйте HTTP-проверки вместо TCP-сокетов (TCP-сокет открывается ОС до готовности логики приложения). См. [Пробы в Kubernetes](../probes.md).
4. **Защита от сбоев узлов и топология:**  
   Не допускайте размещения всех реплик на одном узле или в одной стойке. Используйте `podAntiAffinity` или `topologySpreadConstraints`:
   ```yaml
   topologySpreadConstraints:
   - maxSkew: 1
     topologyKey: kubernetes.io/hostname
     whenUnsatisfiable: DoNotSchedule
     labelSelector:
       matchLabels:
         app.kubernetes.io/name: api-service
   ```
   См. [Affinity и распределение подов](../../Scheduling/affinity.md).
5. **Бюджет доступности (PDB):**  
   Обязательно сопровождайте каждый production-деплой объектом [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md). Это защитит приложение от падения при операциях обслуживания узлов администраторами (`kubectl drain`).
6. **Очистка etcd:**  
   Ограничивайте `spec.revisionHistoryLimit` диапазоном `3..5` вместо дефолтных 10. Хранение сотен неактивных ReplicaSet создает паразитную нагрузку на etcd и замедляет работу API-сервера.

### Безопасность (Security Hardening)

1. **Непривилегированный запуск:**  
   Всегда указывайте `runAsNonRoot: true`, конкретный `runAsUser` (например, 10001) и отключайте повышение привилегий `allowPrivilegeEscalation: false`.
2. **Изоляция файловой системы:**  
   Переводите корневую ФС в режим только для чтения (`readOnlyRootFilesystem: true`), монтируя временные каталоги через `emptyDir`.
3. **Отказ от токенов API по умолчанию:**  
   Если приложению не требуется взаимодействовать с Kubernetes API, отключайте автоматическое монтирование токена: `automountServiceAccountToken: false`.
4. **Неизменяемость артефактов:**  
   Категорически запрещено использовать тег `:latest`. Фиксируйте точные семантические теги или SHA256-хеши (`internal-registry.company.local/apps/api@sha256:...`). Мутабельные теги делают выкатку невоспроизводимой и блокируют работу механизма Rollback.

Комплексный манифест с полным профилем безопасности см. в [Безопасность Deployment](./deployment_security_hardening.md).

### Ограничения и граничные случаи (Edge Cases)

- **Конфликт с ResourceQuota:** При параметре `maxSurge > 0` суммарное потребление ресурсов в неймспейсе временно возрастает. Если квота неймспейса заполнена, создание новых подов заблокируется с ошибкой `failed quota`, и выкатка зависнет.
- **Монопольные диски (RWO):** При использовании блочных томов (Ceph RBD, Local PV, iSCSI) со стратегией `RollingUpdate` новый под не сможет смонтировать том, пока старый под не завершит работу (ошибка `VolumeSubpathInitializationFailed` или `Multi-Attach error`). В таких случаях обязательна стратегия `Recreate` либо переход на [StatefulSet](../StatefulSet/statefulset_overview.md).
- **Связка с HPA:** HPA обязан ссылаться строго на `kind: Deployment`, а не на дочерний `ReplicaSet`. При обновлении манифеста через GitOps не управляйте полем `spec.replicas` в манифесте Deployment вручную, чтобы не провоцировать конфликт (flapping) с HPA.

---

## Дополнительная информация

### Специализированные руководства по Deployment
- [Манифест и лучшие практики](./deployment_manifest.md) — детальный разбор всех полей спецификации, PodTemplateSpec и пример hardened-манифеста.
- [Устранение неполадок и RollingUpdate](./troubleshooting.md) — глубокая диагностика зависших выкаток, анализ таймаутов и сетевых гонок.
- [Управление жизненным циклом](./lifecycle_management.md) — пауза, возобновление, пропорциональное масштабирование и управление ревизиями.
- [Безопасность Deployment](./deployment_security_hardening.md) — адаптация под стандарты Pod Security Standards (Restricted) и аудит уязвимостей.
- [Production Checklist](./production_checklist.md) — контрольный перечень требований перед выпуском сервиса в промышленную эксплуатацию.
- [Продвинутые стратегии отката](./advanced_rollback_strategies.md) — автоматический откат на основе метрик Prometheus и интеграция в пайплайны.
- [Progressive Delivery](./progressive_delivery.md) — канареечные релизы, Blue-Green развертывания, Argo Rollouts.
- [Deployment с Service Mesh](./deployment_with_servicemesh.md) — интеграция с Istio и Gateway API, управление трафиком и circuit breaking.
- [Deployment с GitOps](./deployment_with_gitops.md) — синхронизация через ArgoCD и Flux, разрешение конфликтов реконсиляции.
- [Мониторинг и наблюдаемость](./deployment_monitoring_observability.md) — метрики `kube-state-metrics`, Prometheus алерты и визуализация в Grafana.
- [Продвинутые сценарии диагностики](./advanced_troubleshooting_scenarios.md) — разбор комплексных аварийных инцидентов из производственной практики.

### Смежные разделы базы знаний
- [Pod: архитектура и жизненный цикл](../Pod/pod_overview.md) — базовый строительный блок вычислительной нагрузки.
- [ReplicaSet: контроллер репликации](../replicaset.md) — механизм обеспечения заданного числа копий подов.
- [StatefulSet: приложения с состоянием](../StatefulSet/statefulset_overview.md) — сравнение с stateless-подходом Deployment.
- [Пробы в Kubernetes (Health Checks)](../probes.md) — настройка проверок startup, liveness и readiness.
- [Управление ресурсами и классы QoS](../../Scheduling/qos_limit_and_requests.md) — конфигурация requests/limits и предотвращение OOMKilled.
- [Affinity и Anti-Affinity подов](../../Scheduling/affinity.md) — правила топологического размещения реплик на узлах кластера.
- [PodDisruptionBudget (PDB)](../../Autoscaling/pod_disruption_budget.md) — обеспечение минимальной доступности при плановых работах на узлах.
- [Horizontal Pod Autoscaler (HPA)](../../Autoscaling/HPA/index.md) — динамическое масштабирование Deployment по метрикам нагрузки.
- [Pod Security Context](../../Security/pod_security_context.md) — параметры изоляции ядра Linux, Seccomp и прав доступа.
- [Сравнение стратегий развертывания](../../../CI-CD/Deployment_Strategies/comparison.md) — RollingUpdate, Recreate, Canary и Blue-Green в контексте CI/CD.
