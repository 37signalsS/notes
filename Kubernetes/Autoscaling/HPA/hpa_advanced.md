# HPA: Продвинутые темы и тонкая настройка

В данном документе рассматриваются сложные аспекты настройки Horizontal Pod Autoscaler (HPA), стратегии предотвращения «дребезга» (flapping), особенности работы с метриками памяти, взаимодействие с другими компонентами Kubernetes и методы глубокой диагностики.

Для получения вводной информации см. основной раздел **[HPA: Главная](./index.md)**. Алгоритм расчета и типы метрик описаны в **[HPA: Основные концепции](./hpa_concepts.md)**. Готовые YAML-манифесты — в **[HPA: Практические сценарии](./hpa_scenarios.md)**.

## Определения

**Flapping (дребезг)** — ситуация, при которой количество реплик постоянно колеблется (увеличивается и тут же уменьшается) из-за нестабильных метрик или слишком агрессивных настроек масштабирования.

**Поле `behavior`** — секция в спецификации HPA (API `v2`), позволяющая тонко настраивать политики и скорость масштабирования вверх (`scaleUp`) и вниз (`scaleDown`), включая управление окнами стабилизации.

**kube-state-metrics** — сервис, генерирующий метрики о состоянии объектов Kubernetes (включая статус HPA и количество целевых реплик) из API-сервера для сбора системой Prometheus.

**ContainerResource** — тип метрики в HPA v2, позволяющий масштабировать по ресурсам конкретного контейнера в поде, игнорируя потребление sidecar-контейнеров.

**Политика масштабирования (Scaling Policy)** — правило, определяющее допустимый темп изменения количества реплик за единицу времени. Задается в блоке `behavior.scaleUp` или `behavior.scaleDown` через список `policies`.

## Предварительные требования

Перед настройкой продвинутых параметров HPA необходимо убедиться в выполнении следующих условий:

1. **Kubernetes 1.23+** — стабильная версия API `autoscaling/v2`. Старые версии (`v2beta1`, `v2beta2`) удалены в актуальных релизах.
2. **Metrics Server** — развернут и доступен. Проверка:
   ```bash
   kubectl get apiservice v1beta1.metrics.k8s.io
   # → v1beta1.metrics.k8s.io    kube-system/metrics-server   True    1m
   kubectl top pods
   ```
3. **Resource Requests** — заданы у **всех** контейнеров пода (включая sidecar). Без них расчет утилизации невозможен, статус HPA будет `<unknown>`.
4. **Работающий HPA** — базовая конфигурация HPA уже создана и функционирует. См. [HPA: Главная](./index.md) для создания базового HPA.
5. **Подключенные источники метрик** (для кастомных/внешних метрик) — Prometheus Adapter, KEDA или другой адаптер метрик настроен и отдает данные через Custom/External Metrics API.

## Базовые концепции

### Диагностика и статус условий (Conditions)

HPA сообщает о своем состоянии через `status.conditions`. Это первый источник данных при отладке. Проверка условий осуществляется командой `kubectl describe hpa <name>`.

| Условие | Значение `False` | Значение `True` |
|:---|:---|:---|
| **`AbleToScale`** | Отсутствие прав RBAC, удаленный целевой объект, некорректный `scaleTargetRef`. | HPA может управлять масштабированием. |
| **`ScalingActive`** | Metrics Server недоступен, отсутствуют `requests` у контейнеров, API метрик не зарегистрирован. | Метрики собираются, расчеты выполняются. |
| **`ScalingLimited`** | — | Достигнут `minReplicas` или `maxReplicas`, или политика `Disabled` блокирует масштабирование. |

**Быстрая диагностика:**
```bash
# Просмотр всех условий
kubectl get hpa <name> -o jsonpath='{.status.conditions[*]}' | jq .

# Проверка конкретного условия
kubectl get hpa <name> -o jsonpath='{.status.conditions[?(@.type=="ScalingActive")].status}'
# → True или False

# События HPA (последние действия)
kubectl describe hpa <name> | grep -A 20 "Events:"
```

### Особенности метрик памяти

Масштабирование по памяти (Memory) концептуально сложнее, чем по CPU, и имеет ряд подводных камней:

1. **Working Set vs RSS**: Kubernetes (и HPA) использует метрику `working_set_bytes` (RSS + Page Cache). Если приложение активно читает или пишет файлы, страничный кеш растет. HPA будет учитывать этот кеш и может ошибочно считать, что память заканчивается, инициируя ложное масштабирование.
2. **Отсутствие освобождения**: Многие среды исполнения и виртуальные машины (JVM, Go, Python) не возвращают память операционной системе мгновенно после сборки мусора (Garbage Collection). Это приводит к тому, что HPA «застревает» на максимальном количестве реплик, так как метрика использования не падает.
3. **Рекомендация**: Используйте память как **второстепенную** метрику, ограничение безопасности или в связке с `ScalingLimited`. Отдавайте приоритет CPU для stateless-нагрузок или кастомным метрикам (например, RPS).

**Практический пример:** Приложение на Go потребляет 500Mi памяти. После GC освобождается 200Mi, но `working_set_bytes` остается на уровне 480Mi (кеш). HPA видит 96% утилизации (при `requests: 512Mi`) и не масштабирует вниз, даже если реальное потребление упало до 300Mi.

**Диагностика:**
```bash
# Просмотр текущего потребления памяти
kubectl top pods -l app=my-app --sort-by=memory

# Просмотр working_set vs rss (через метрики kubelet)
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/namespaces/default/pods" | jq '.items[] | select(.metadata.name | startswith("my-app")) | {name: .metadata.name, memory: .memory}'
```

### Конфликты с инструментами GitOps (ArgoCD)

Если в Git-репозитории в манифесте Deployment жестко указано поле `replicas`, а ArgoCD работает с включенной опцией `SelfHeal`, возникает конфликт: HPA масштабирует поды, а ArgoCD пытается вернуть их количество к значению из Git.

**Решение 1 (рекомендуемое):** Настройте ArgoCD на игнорирование изменений в поле `replicas` в целевом кластере:

```yaml
# Application манифест ArgoCD
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
```

**Решение 2:** Полностью удалите поле `replicas` из манифеста в Git. Kubernetes установит значение по умолчанию (1), а дальше управление перехватит HPA.

**Решение 3 (Server-Side Apply):** Используйте Server-Side Apply для раздельного владения полями. Kubernetes отслеживает, какие поля манифеста управляются Helm/ArgoCD, а какие — HPA. Это предотвращает конфликты «пинг-понга» конфигураций.

```bash
# Просмотр владельцев полей Deployment
kubectl get deployment my-app -o yaml | grep -A 5 "managedFields"
```

**Важно:** При обновлении Deployment через `kubectl apply` или Helm без учета HPA поле `replicas` будет перезаписано. Убедитесь, что ваш GitOps-процесс не конфликтует с HPA.

### Взаимодействие с Pod Disruption Budget (PDB)

HPA учитывает PDB при масштабировании вниз, но есть нюансы:

- **PDB ограничивает количество одновременно удаленных подов.** Если PDB указан `minAvailable: 3`, а текущее количество реплик — 5, HPA не сможет удалить более 2 подов за раз.
- **HPA и PDB могут конфликтовать** при агрессивном `scaleDown`. Если политика HPA требует удалить 5 подов за 60 секунд, а PDB разрешает удаление только 2, масштабирование будет «застревать».

**Рекомендация:** Настраивайте политику `scaleDown` в HPA с учетом PDB. Например, если PDB требует `minAvailable: 50%`, не удаляйте более 10% реплик за раз.

```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 300
    policies:
      - type: Percent
        value: 10          # Не более 10% реплик за раз
        periodSeconds: 60  # Каждые 60 секунд
```

**Проверка PDB:**
```bash
# Просмотр PDB для сервиса
kubectl get pdb -l app=my-app

# Проверка, разрешит ли PDB удаление подов
kubectl describe pdb my-app-pdb
# → Allowed disruptions: 2 (при minAvailable: 3 и 5 подах)
```

### Взаимодействие с StatefulSets

HPA поддерживает масштабирование StatefulSets, но с ограничениями:

- **Стабильные имена подов:** StatefulSet создает поды с детерминированными именами (`pod-0`, `pod-1`, ...). HPA добавляет и удаляет поды с конца списка.
- **VolumeClaimTemplates:** При масштабировании вниз PVC **не удаляются** автоматически. Это может привести к «зависшим».volume-ам.
- **Особенности Rollout:** При обновлении StatefulSet HPA может масштабировать старую ревизию, если `partition` установлен.

**Пример HPA для StatefulSet:**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: stateful-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet
    name: stateful-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Важно:** Убедитесь, что `minReplicas >= 2` для StatefulSet, чтобы обеспечить доступность при обновлении (rolling update). Для StatefulSet с `podManagementPolicy: Parallel` масштабирование происходит быстрее.

### Несколько HPA на один объект

Kubernetes **не запрещает** создание нескольких HPA, ссылающихся на один и тот же Deployment/StatefulSet. Однако это приводит к непредсказуемому поведению:

- Каждый HPA независимо рассчитывает целевое количество реплик.
- Они конфликтуют за право записи в `/scale` подресурс.
- Результат определяется тем, какой HPA последним применил изменения.

**Рекомендация:** Используйте **один HPA на объект**. Если необходимо масштабировать по нескольким метрикам — используйте несколько метрик в одном HPA (см. [HPA: Практические сценарии](./hpa_scenarios.md)).

### Миграция с autoscaling/v1 на v2

Если в кластере используются манифесты с `autoscaling/v1`, рекомендуется миграция на `autoscaling/v2`:

**Что меняется:**
- `v1` поддерживает только CPU-метрику с фиксированным форматом.
- `v2` добавляет: несколько метрик, `behavior`, `ContainerResource`, кастомные/внешние метрики.

**Шаги миграции:**
```bash
# 1. Экспорт текущего HPA
kubectl get hpa my-hpa -o yaml > hpa-v1.yaml

# 2. Измените apiVersion
sed -i 's|autoscaling/v1|autoscaling/v2|' hpa-v1.yaml

# 3. Удалите неподдерживаемые поля (если есть)
# Поле spec.scaleTargetRef в v1 может отличаться по структуре

# 4. Примените обновленный манифест
kubectl apply -f hpa-v1.yaml

# 5. Проверьте статус
kubectl get hpa my-hpa
kubectl describe hpa my-hpa
```

**Автоматическая конвертация:** Инструмент `kubectl convert` (часть kubebuilder) может автоматически конвертировать манифесты:
```bash
kubectl convert -f hpa-v1.yaml --output-version autoscaling/v2
```

**Важно:** Миграция безопасна и обратима. Если после миграции возникнут проблемы, можно вернуться к `v1` аналогичным способом.

## Практические сценарии

### Продвинутые возможности API v2: Настройка Behavior

Поле `behavior` — ключевой инструмент для предотвращения «дребезга» и управления скоростью масштабирования.

**Параметры стабилизации:**
- **`stabilizationWindowSeconds`**: период (от 0 до 3600), за который HPA анализирует исторические рекомендации. Для `scaleDown` выбор идет по **наибольшему** (наиболее безопасному) количеству реплик за окно. Значения по умолчанию: `scaleUp` = 0с, `scaleDown` = 300с (5 минут).

**Типы политик:**
- **`Percent`**: изменение на указанный процент от текущего количества реплик.
- **`Pods`**: изменение на фиксированное количество реплик.

**Политика выбора (`selectPolicy`):**
- **`Max`** (по умолчанию): выбирает политику, дающую **наибольшее** количество реплик. Для `scaleUp` — агрессивный рост, для `scaleDown` — консервативное сжатие.
- **`Min`**: выбирает политику, дающую **наименьшее** количество реплик. Для `scaleUp` — консервативный рост, для `scaleDown` — агрессивное сжатие.
- **`Disabled`**: полностью отключает масштабирование в данном направлении.

#### Сценарий 1: Агрессивный рост, медленное сжатие

Типичный паттерн для продакшена: быстрая реакция на всплески нагрузки и плавное уменьшение для защиты от flapping.

```yaml
behavior:
  scaleUp:
    stabilizationWindowSeconds: 0    # Мгновенная реакция
    policies:
      - type: Percent
        value: 100                    # Удвоение за раз
        periodSeconds: 15
    selectPolicy: Max
  scaleDown:
    stabilizationWindowSeconds: 600  # 10 минут ожидания
    policies:
      - type: Pods
        value: 1                      # Строго по 1 поду
        periodSeconds: 60
    selectPolicy: Max
```

**Как это работает:** При пиковой нагрузке HPA немедленно удваивает количество реплик каждые 15 секунд. При спаде — ждет 10 минут стабильности, затем удаляет по 1 поду в минуту.

#### Сценарий 2: Консервативный рост, агрессивное сжатие

Редкий, но полезный паттерн: медленное масштабирование для экономии ресурсов и быстрое сжатие при длительном спаде.

```yaml
behavior:
  scaleUp:
    stabilizationWindowSeconds: 300  # 5 минут анализа
    policies:
      - type: Pods
        value: 1                      # По 1 поду
        periodSeconds: 120            # Каждые 2 минуты
    selectPolicy: Min
  scaleDown:
    stabilizationWindowSeconds: 60   # Быстрое сжатие
    policies:
      - type: Percent
        value: 50                     # Удаление 50% за раз
        periodSeconds: 30
    selectPolicy: Max
```

#### Сценарий 3: Полная блокировка масштабирования вниз

Используйте, когда критически важно не терять реплики (например, во время обслуживания или миграции).

```yaml
behavior:
  scaleDown:
    selectPolicy: Disabled  # Масштабирование вниз отключено
```

#### Сценарий 4: Комбинированные политики

Несколько политик в одном блоке позволяют задать гибкие правила. Например, ограничить максимальный рост, но разрешить быстрый рост до определенного порога.

```yaml
behavior:
  scaleUp:
    stabilizationWindowSeconds: 0
    policies:
      - type: Percent
        value: 100                    # До 100% роста
        periodSeconds: 15
      - type: Pods
        value: 4                      # Или не более 4 подов
        periodSeconds: 60
    selectPolicy: Max  # Выбирает более агрессивную политику
```

**Результат:** При росте HPA будет добавлять до 100% реплик каждые 15 секунд, но не более 4 подов в минуту. Это предотвращает «взрывной» рост при ошибках метрик.

### Масштабирование по отдельным контейнерам

Тип `ContainerResource` позволяет игнорировать потребление ресурсов sidecar-контейнерами (например, `istio-proxy`, `fluent-bit` или `telegraf`), которые могут сильно искажать общую картину утилизации пода.

**Когда использовать:**
- Sidecar потребляет значительную долю CPU/памяти (например, Envoy proxy — до 100m CPU).
- Основное приложение имеет сложную архитектуру (микросервис + sidecar для логов).
- Необходимо масштабировать только по бизнес-логике, а не по инфраструктурным компонентам.

**Пример:**
```yaml
metrics:
  - type: ContainerResource
    containerResource:
      name: cpu
      container: main-app  # Целевой контейнер с бизнес-логикой
      target:
        type: Utilization
        averageUtilization: 70
```

**Важно:** Контейнер `main-app` должен иметь `resources.requests.cpu`, иначе расчет утилизации невозможен. Если в поде несколько целевых контейнеров — используйте несколько метрик `ContainerResource`.

**Диагностика:**
```bash
# Просмотр потребления конкретного контейнера
kubectl top pods -l app=my-app --containers
# → CONTAINER     CPU(cores)   MEMORY(bytes)
# → main-app      150m         200Mi
# → istio-proxy   50m          100Mi
```

### Пошаговая отладка: сценарий восстановления HPA

Ниже представлен пошаговый сценарий диагностики и устранения типичной проблемы: HPA показывает `<unknown>` в колонке TARGETS.

**Шаг 1: Проверка статуса HPA**
```bash
kubectl get hpa my-app
# → NAME       REFERENCE          TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# → my-app     Deployment/my-app  <unknown>/70%   3         20        3          5m
```

**Шаг 2: Проверка событий HPA**
```bash
kubectl describe hpa my-app | grep -A 20 "Events:"
# → Warning  FailedGetResourceMetric  unable to get metrics for resource cpu: unable to fetch resource metrics API: the server could not find the requested resource
```

**Шаг 3: Проверка доступности Metrics Server**
```bash
kubectl get apiservice v1beta1.metrics.k8s.io
# → v1beta1.metrics.k8s.io    kube-system/metrics-server   True    1m
kubectl top pods
# → NAME                     CPU(cores)   MEMORY(bytes)
# → my-app-6d4b8f7c9-x2j    100m         128Mi
```

**Шаг 4: Проверка requests у контейнеров**
```bash
kubectl get deployment my-app -o jsonpath='{.spec.template.spec.containers[*].resources.requests}'
# → {"cpu":"200m","memory":"256Mi"} {"cpu":"50m","memory":"64Mi"}
```

**Шаг 5: Если `requests` отсутствуют у sidecar**
```bash
# Исправление: добавление requests для sidecar
kubectl patch deployment my-app --type='json' -p='[
  {"op": "add", "path": "/spec/template/spec/containers/1/resources/requests", "value": {"cpu": "50m", "memory": "64Mi"}}
]'
```

**Шаг 6: Проверка восстановления**
```bash
# Ожидание следующего цикла HPA (15 секунд)
sleep 20
kubectl get hpa my-app
# → NAME       REFERENCE          TARGETS   MINPODS   MAXPODS   REPLICAS   AGE
# → my-app     Deployment/my-app  35%/70%   3         20        3          6m
```

**Шаг 7: Альтернативное решение — использование ContainerResource**
Если sidecar не должен влиять на масштабирование:
```yaml
metrics:
  - type: ContainerResource
    containerResource:
      name: cpu
      container: main-app
      target:
        type: Utilization
        averageUtilization: 70
```

## Дополнительная информация

### Лучшие практики

- **Постепенное внедрение:** Вводите масштабирование постепенно, начиная с наименее критичных сервисов. Обязательно тестируйте настройки `behavior` в staging-окружениях под имитируемой нагрузкой.
- **Интеграция с PDB:** Обязательно используйте **Pod Disruption Budget (PDB)** вместе с HPA. Это гарантирует, что даже при агрессивном `scaleDown` или удалении узлов не будет нарушена базовая доступность сервиса (например, всегда держать `minAvailable: 50%`).
- **Readiness Probes:** HPA при расчетах учитывает только «готовые» поды. Без настроенных `readinessProbe` HPA может начать масштабирование на основе данных от еще не прогретых или некорректно инициализированных подов.
- **CPU как база:** Для stateless-приложений CPU почти всегда является наиболее надежным и предсказуемым показателем нагрузки.
- **Избегайте малых диапазонов `maxReplicas`:** Слишком узкий диапазон (например, от 1 до 2 реплик) лишает HPA математического смысла и делает его излишне чувствительным к малейшим колебаниям.
- **Не задавайте `replicas` в манифесте:** Если HPA управляет масштабированием — удалите поле `replicas` из Deployment-манителста. Иначе повторный `kubectl apply` перезапишет значение, выставленное HPA.
- **Мониторинг HPA:** Настройте алерты на основе метрик kube-state-metrics (`kube_hpa_status_current_replicas`, `kube_hpa_status_desired_replicas`). Разрыв между этими значениями указывает на достижение лимитов.
- **Тестирование behavior:** Перед применением в продакшена протестируйте настройки `behavior` в staging. Используйте инструменты нагрузки (vegeta, hey, k6) для имитации пиков.

### Типовые ошибки и ограничения

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `FailedGetResourceMetric` | Metrics Server недоступен или отсутствуют `requests`. | Установите Metrics Server, добавьте `requests` всем контейнерам. |
| `FailedGetScale` | Целевой объект (Deployment) не найден или нет прав RBAC. | Проверьте `scaleTargetRef` и ClusterRole `system:hpa-controller`. |
| HPA не масштабирует вниз | Достигнут `minReplicas` или окно стабилизации еще активно. | Уменьшите `minReplicas` или сократите `stabilizationWindowSeconds`. |
| HPA «застревает» на максимуме | Метрика памяти не падает после GC (JVM, Go). | Используйте CPU как основную метрику, память — как второстепенную. |
| Flapping (дребезг) | Слишком узкий диапазон `maxReplicas` или агрессивные политики. | Настройте `behavior` с окном стабилизации, увеличьте `maxReplicas`. |
| Конфликт с ArgoCD/Helm | `SelfHeal` или `kubectl apply` перезаписывают `replicas`. | Используйте `ignoreDifferences` или Server-Side Apply. |
| `<unknown>` при работающем Metrics Server | У sidecar-контейнера отсутствуют `requests`. | Добавьте `requests` или используйте `ContainerResource`. |

### Откат и очистка

**Удаление HPA:**
```bash
kubectl delete hpa my-app
# Поды останутся в текущем количестве, масштабирование прекратится
```

**Возврат к ручному управлению репликами:**
```bash
# 1. Удалите HPA
kubectl delete hpa my-app

# 2. Установите желаемое количество реплик
kubectl scale deployment my-app --replicas=3

# 3. (Опционально) Добавьте replicas обратно в манифест
```

**Полный откат изменений behavior:**
```bash
# Экспорт текущего HPA
kubectl get hpa my-app -o yaml > hpa-current.yaml

# Удаление секции behavior (возврат к поведению по умолчанию)
# Или применение манифеста без behavior
kubectl apply -f hpa-basic.yaml
```

**Проверка после отката:**
```bash
kubectl get hpa my-app
kubectl describe hpa my-app | grep -A 5 "Behavior"
```

### Взаимодействие HPA с ResourceQuota и LimitRange

HPA масштабирует Deployment/StatefulSet, но если в namespace настроены ResourceQuota или LimitRange, масштабирование может быть заблокировано.

#### Проблема: ResourceQuota блокирует scale-up

HPA увеличивает `replicas`, но новые поды не могут быть созданы из-за исчерпания квоты:

```bash
# Симптом: поды в Pending
kubectl get pods -l app=my-app
# → NAME                     READY   STATUS    RESTARTS   AGE
# → my-app-xxxxx             0/1     Pending   0          2m

# Причина: квота исчерпана
kubectl describe resourcequota -n production
# → Name:                   compute-quota
# → Resource                Used    Hard
# ───────────────────────────────────────
# → cpu                     4000m   4000m    ← исчерпано!
# → memory                  8Gi     8Gi
# → pods                    15      15
```

**Почему это происходит:** ResourceQuota проверяет суммарное потребление ресурсов **всех** подов (включая Terminating). HPA увеличивает `replicas`, но новые поды не проходят admission control.

**Решения:**

1. **Увеличить квоту с запасом:**
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute-quota
  namespace: production
spec:
  hard:
    requests.cpu: "8000m"    # Запас под HPA maxReplicas
    requests.memory: "16Gi"
    pods: "30"
```

2. **Проверить достаточность квоты:**
```bash
# Рассчитать, сколько подов поместится
MAX_PODS_BY_CPU=$(echo "scale=0; 8000 / 500" | bc)  # 8000m / requests.cpu=500m
MAX_PODS_BY_MEM=$(echo "scale=0; 16384 / 512" | bc)  # 16Gi / requests.memory=512Mi
echo "Максимум подов: CPU=$MAX_PODS_BY_CPU, Memory=$MAX_PODS_BY_MEM"
```

3. **Использовать PriorityClass для критичных подов:**
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000000
globalDefault: false
preemptionPolicy: PreemptLowerPriority
description: "Для сервисов с HPA"
---
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  priorityClassName: high-priority
```

#### Проблема: LimitRange конфликтует с requests подов

LimitRange устанавливает минимальные/максимальные значения для `requests` и `limits`. Если HPA создает поды с requests, не соответствующими LimitRange, поды отклоняются.

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
    - type: Container
      default:
        cpu: "500m"
        memory: "512Mi"
      defaultRequest:
        cpu: "100m"
        memory: "128Mi"
      min:
        cpu: "50m"
        memory: "64Mi"
      max:
        cpu: "2"
        memory: "4Gi"
```

**Проблема:** Если Deployment указывает `requests.cpu: 50m` (ниже `min`), под будет отклонён.

**Решение:** Убедитесь, что `resources.requests` в Deployment соответствуют ограничениям LimitRange.

#### Diagnostic-чек-лист

```bash
# 1. Проверить ResourceQuota
kubectl get resourcequota -n <namespace>
kubectl describe resourcequota -n <namespace>

# 2. Проверить LimitRange
kubectl get limitrange -n <namespace>
kubectl describe limitrange -n <namespace>

# 3. Проверить, есть ли Terminating поды (занимают квоту)
kubectl get pods -n <namespace> --field-selector=status.phase=Terminating

# 4. Проверить Events на ошибки квоты
kubectl get events -n <namespace> | grep -i "quota\|exceeded\|forbidden"

# 5. Проверить, что HPA maxReplicas не превышает квоту
MAX_BY_QUOTA=$(kubectl get resourcequota compute-quota -n <namespace> \
  -o jsonpath='{.spec.hard.pods}')
echo "Максимум подов по квоте: $MAX_BY_QUOTA"
```

### Взаимодействие HPA с Graceful Shutdown при scale-down

При масштабировании вниз HPA удаляет поды. Если приложение не обрабатывает корректно завершение, это приводит к потере запросов и ошибкам 5xx.

#### Последовательность событий при scale-down

```
HPA уменьшает replicas (например, с 10 до 8)
  → Kubernetes помечает 2 пода на удаление (deletionTimestamp)
    → Параллельно:preStop hook + удаление из EndpointSlice
      → SIGTERM приложению
        → Приложение завершает активные запросы
          → По истечении terminationGracePeriodSeconds → SIGKILL
```

**Критический момент:** Между установкой `deletionTimestamp` и обновлением EndpointSlice существует задержка (Propagation Delay). During этого времени трафик продолжает поступать на удаляемый под.

#### Настройка для HPA scale-down

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 10
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 0  # Важно для HPA: не создавать лишние поды при scale-down
  template:
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: app
          lifecycle:
            preStop:
              sleep:
                seconds: 10  # Компенсация propagation delay
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8080
            periodSeconds: 5
            failureThreshold: 1  # Быстрое исключение из трафика
```

**Ключевые настройки:**
- `preStop.sleep: 10` — дает сети время на обновление EndpointSlice
- `terminationGracePeriodSeconds: 45` — покрывает preStop (10с) + дренаж (30с) + запас (5с)
- `readinessProbe.failureThreshold: 1` — быстрое исключение из трафика после SIGTERM
- `maxSurge: 0` — HPA не создает лишние поды при scale-down

#### Проблема: Зависшие Terminating поды блокируют scale-down

Если приложение не обрабатывает SIGTERM, поды зависают в статусе Terminating до истечения `terminationGracePeriodSeconds`. Это блокирует HPA от дальнейшего масштабирования вниз.

```bash
# Проверка зависших подов
kubectl get pods -n <namespace> --field-selector=status.phase=Terminating

# Если поды зависли — принудительное удаление (крайний случай)
kubectl delete pod <pod-name> --grace-period=0 --force
```

**Профилактика:**
1. Приложение должно обрабатывать SIGTERM и завершать работу за время < `terminationGracePeriodSeconds`
2. Использовать `preStop` hook для компенсации propagation delay
3. Настроить `readinessProbe` для быстрого исключения из трафика

### Scaling Latency: задержка масштабирования HPA

**Scaling Latency** — время от момента превышения порога метрики до момента, когда новый под обрабатывает трафик.

#### Компоненты задержки

```
Событие: метрика превысила порог
  │
  ├── [1] Sync Period: 0–15 сек (по умолчанию 15 сек)
  │   HPA опрашивает Metrics API каждые 15 секунд
  │
  ├── [2] Расчёт + Applying: ~1 сек
  │   HPA вычисляет replicas и применяет через /scale
  │
  ├── [3] Создание пода: 5–30 сек
  │   Scheduler распределяет, Kubelet создаёт контейнер
  │
  ├── [4] Image Pull: 0–60 сек
  │   Зависит от размера образа и сети
  │
  ├── [5] Startup: 5–120 сек
  │   Время запуска приложения (JVM warmup, миграции БД)
  │
  └── [6] Readiness Probe: 5–30 сек
      Приложение должно пройти проверку готовности
      ─────────────────────────────────────────
      ИТОГО: 20 сек – 4+ минуты
```

#### Типичные тайминги

| Приложение | Sync | Создание | Image | Startup | Readiness | **Итого** |
|:---|:---|:---|:---|:---|:---|:---|
| Go/Node.js (lightweight) | 15с | 5с | 2с | 3с | 5с | **~30 сек** |
| Python (Flask/Django) | 15с | 5с | 5с | 10с | 10с | **~45 сек** |
| Java (Spring Boot) | 15с | 5с | 10с | 30с | 15с | **~75 сек** |
| Java (large, с миграциями) | 15с | 10с | 15с | 60с | 30с | **~2 мин** |

#### Как ускорить масштабирование

1. **Уменьшить sync period** (не рекомендуется < 10с — нагрузка на API Server):
```bash
# kube-controller-manager
--horizontal-pod-autoscaler-sync-period=10s
```

2. **Ускорить readiness probe:**
```yaml
readinessProbe:
  httpGet:
    path: /readyz
    port: 8080
  initialDelaySeconds: 0
  periodSeconds: 3
  failureThreshold: 1  # 3 сек до готовности
```

3. **Использовать startupProbe** для медленных приложений:
```yaml
startupProbe:
  httpGet:
    path: /readyz
    port: 8080
  periodSeconds: 5
  failureThreshold: 30  # до 150 сек на старт
  # readinessProbe и livenessProbe не проверяются до прохождения startupProbe
```

4. **Предварительный прогрев (Predictive Scaling):**
```yaml
# KEDA Cron Scaler для планового масштабирования
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: my-app-predictive
spec:
  scaleTargetRef:
    name: my-app
  minReplicaCount: 3
  maxReplicaCount: 20
  triggers:
    - type: cron
      metadata:
        timezone: Europe/Moscow
        start: 0 8 * * 1-5    # Пн-Пт с 8:00
        end: 0 20 * * 1-5      # до 20:00
        desiredReplicas: "15"   # Предварительное масштабирование
```

#### Мониторинг scaling latency

```yaml
# PromQL: время от Desired != Current до Ready pods
# (требует kube-state-metrics + custom metrics)

# Средняя задержка масштабирования (если есть timestamp метрики)
histogram_quantile(0.95,
  rate(hpa_scaling_duration_seconds_bucket[5m])
)
```

### HPA + TopologySpreadConstraints

TopologySpreadConstraints ограничивают распределение подов по доменам (узлы, зоны, регионы). При масштабировании HPA может создавать поды, которые не могут быть размещены из-за этих ограничений.

**Проблема:** HPA масштабирует до 10 подов, но `maxSkew: 1` и `DoNotSchedule` не позволяют разместить более 3 подов на одном узле → поды в Pending.

**Решение 1: ScheduleAnyway (мягкие ограничения)**

```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway  # Поды размещаются, но не равномерно
    labelSelector:
      matchLabels:
        app: my-app
```

**Решение 2: HPA behavior для ограничения скорости**

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
spec:
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 2       # Не более 2 подов за раз (ограничиваем перекос)
          periodSeconds: 60
```

**Решение 3: Комбинация с Cluster Autoscaler**

```yaml
# HPA масштабирует → поды в Pending → CA добавляет узлы
# CA использует --balance-similar-node-groups для распределения
```

**Диагностика:**
```bash
kubectl describe pod <pending-pod> | grep -A 5 "Events:"
# → 0/5 nodes are available: 2 didn't match topology spread constraints

kubectl get events --field-selector reason=FailedScheduling | grep topology
# → Warning  FailedScheduling  0/5 nodes are available: 3 didn't match topology spread constraints
```

### См. также

- **[Устранение неполадок HPA](../../Troubleshooting/Common_Errors/hpa_troubleshooting.md)** — пошаговая диагностика типичных ошибок.
- **[HPA: Основные концепции](./hpa_concepts.md)** — алгоритм и типы метрик.
- **[HPA: Каскадное масштабирование](./cascading_scaling.md)** — цепочки зависимостей микросервисов.
- **[HPA: Prometheus Adapter](./prometheus_adapter_setup.md)** — настройка кастомных метрик.
- **[HPA: Cost и Right-sizing](./hpa_cost_rightsizing.md)** — оптимизация requests и затрат.
- **[HPA + PriorityClass + Preemption](../hpa_priority_preemption.md)** — взаимодействие с приоритетами.
- **[KEDA (Event-driven Autoscaling)](../keda/keda_concepts.md)** — масштабирование по событиям и до нуля.
- **[Descheduler](../descheduler.md)** — исправление перекосов после масштабирования.
