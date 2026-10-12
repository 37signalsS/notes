# Horizontal Pod Autoscaler (HPA)

**Актуально для:** Kubernetes 1.28–1.35 (API autoscaling/v2)

Horizontal Pod Autoscaler (HPA) — встроенный контроллер Kubernetes, автоматически регулирующий количество реплик вычислительной нагрузки (Deployment, ReplicaSet, StatefulSet) на основе метрик утилизации аппаратных ресурсов (CPU, память) или прикладных бизнес-показателей.

Файл является центральной точкой входа и навигатором раздела автомасштабирования подов. Материал ориентирован на инженеров DevOps, SRE и системных администраторов инфраструктуры Kubernetes (включая bare-metal и on-premise инсталляции) без привязки к проприетарным облачным сервисам.

---

## Определения

**Horizontal Pod Autoscaler (HPA)** — контроллер в составе `kube-controller-manager`, который непрерывно сверяет наблюдаемые метрики с заданными целевыми значениями и при необходимости изменяет поле `replicas` целевого масштабируемого объекта через подресурс `/scale`.

**Control Loop (Петля управления)** — периодический цикл контроллера HPA: сбор метрик через API → расчет желаемого числа реплик → применение изменений через `/scale`. Интервал запуска цикла определяется флагом `--horizontal-pod-autoscaler-sync-period` в `kube-controller-manager` (по умолчанию 15 секунд).

**ScaleTargetRef** — блок манифеста HPA, определяющий целевой управляющий объект (`apiVersion`, `kind`, `name`). В сценариях с Deployment ссылка обязана указывать строго на Deployment, а не на дочерний ReplicaSet, чтобы исключить конфликты при выкатке новых версий (Rollout).

**Подресурс `/scale` (Scale Subresource)** — специализированный REST-эндпоинт Kubernetes API (`/apis/apps/v1/namespaces/{ns}/deployments/{name}/scale`), предоставляющий раздельный доступ к управлению количеством реплик (`spec.replicas` и `status.replicas`) без необходимости модифицировать или считывать всю спецификацию пода.

**Resource Requests и Limits** — параметры резервирования ресурсов контейнера в `spec.containers[*].resources`. Поле `requests` задает гарантированный минимум, резервируемый планировщиком (Scheduler) на узле, и служит 100%-й базой для расчета относительной утилизации (`Utilization`) в HPA. Поле `limits` — верхний жесткий лимит cgroups. Если `requests` не заданы, вычисление процентной нагрузки невозможно, и HPA переходит в состояние `<unknown>`.

**Metrics Server** — легковесный in-memory агрегатор метрик утилизации CPU и памяти контейнеров, опрашивающий kubelet на узлах кластера и экспортирующий данные через Resource Metrics API (`metrics.k8s.io`).

**Custom Metrics API (`custom.metrics.k8s.io`)** — расширение API Kubernetes через механизм Aggregated API, предоставляющее метрики, ассоциированные с объектами кластера (например, HTTP RPS на под или задержка обработки запросов сервисом), поставляемые адаптерами мониторинга (например, Prometheus Adapter).

**External Metrics API (`external.metrics.k8s.io`)** — расширение API Kubernetes для метрик систем, не привязанных к объектам подов кластера (длина очереди сообщений RabbitMQ, лаг консьюмеров Kafka, количество открытых клиентских сессий во внешней СУБД).

**Толерантность масштабирования (Tolerance)** — коэффициент нечувствительности алгоритма HPA к колебаниям метрик около целевого значения (по умолчанию `0.1` или 10%, настраивается флагом `--horizontal-pod-autoscaler-tolerance`). Предотвращает срабатывания при отклонениях в диапазоне `[0.9, 1.1]`.

**Окно стабилизации (Stabilization Window)** — временной интервал в блоке `behavior`, в течение которого контроллер оценивает все рассчитанные рекомендации и выбирает наиболее безопасную (наибольшую при масштабировании вниз для исключения дефицита ресурсов). По умолчанию для `scaleDown` составляет 300 секунд (5 минут), для `scaleUp` — 0 секунд (немедленный отклик).

**Scaling Conditions** — системные статусные условия объекта HPA (`AbleToScale`, `ScalingActive`, `ScalingLimited`), отражающие готовность контроллера к масштабированию, доступность метрик и достижение границ диапазона `minReplicas`/`maxReplicas`.

---

## Архитектура и базовые концепции

### Конвейер передачи метрик и компонентов

Решение о масштабировании принимается на основе сквозного конвейера данных от ядра Linux до контроллера:

```
Linux cgroups (v1/v2) → cAdvisor (в Kubelet) → Kubelet Summary API (:10250)
                                                       │
                                                       ▼
                                                Metrics Server
                                                       │
                                                       ▼
                                            Aggregated API (metrics.k8s.io)
                                                       │
                                                       ▼
                                            HPA Controller (kube-controller-manager)
                                                       │
                                                       ▼
                                            /scale subresource (Deployment)
                                                       │
                                                       ▼
                                            Kube-Scheduler → Worker Nodes (Kubelet)
```

1. **Сбор на узлах:** Kubelet через встроенный cAdvisor считывает счетчики cgroups (`cpu.stat`, `memory.current` в cgroups v2).
2. **Агрегация:** Metrics Server опрашивает узлы кластера каждые 15–60 секунд и кэширует текущие значения в оперативной памяти.
3. **Запрос контроллера:** `kube-controller-manager` с периодичностью `--horizontal-pod-autoscaler-sync-period` (15 с) запрашивает Resource Metrics API (`metrics.k8s.io`) либо Custom/External API.
4. **Математический расчет:** Контроллер нормализует значения, фильтрует поды в переходных состояниях и вычисляет желаемое число реплик.
5. **Мутация `/scale`:** Контроллер отправляет PATCH-запрос к подресурсу `/scale` масштабируемого объекта (например, Deployment).
6. **Развертывание:** Контроллер Deployment обновляет ReplicaSet, планировщик (Scheduler) связывает новые поды с узлами, а kubelet запускает контейнеры.

### Версии API

В современных версиях Kubernetes используется стабильная спецификация API:

| Версия API | Статус в Kubernetes | Особенности и ограничения |
|:---|:---|:---|
| **`autoscaling/v1`** | Устарела (только обратная совместимость) | Поддерживает только метрику CPU в процентах. Отсутствуют память, кастомные метрики и блок `behavior`. |
| **`autoscaling/v2`** | **Текущий стандарт (GA с 1.23)** | Полная поддержка мультиметрик (CPU, Memory, Pods, Object, External), детального блока `behavior`, таргетинга контейнеров (`ContainerResource`). |

> **Примечание:** Устаревшие промежуточные версии `autoscaling/v2beta1` и `autoscaling/v2beta2` полностью удалены из кодовой базы в Kubernetes 1.25 и 1.26 соответственно. Любые production-манифесты обязаны использовать строго `autoscaling/v2`.

### Алгоритмическая модель и обработка краевых случаев

Базовая формула расчета желаемого числа реплик:

$$\text{DesiredReplicas} = \left\lceil \text{CurrentReplicas} \times \left( \frac{\text{CurrentMetricValue}}{\text{TargetMetricValue}} \right) \right\rceil$$

Ключевые правила работы алгоритма:

1. **Толерантность (Tolerance):** Если отношение $\frac{\text{CurrentMetricValue}}{\text{TargetMetricValue}}$ находится в интервале $[1.0 - \text{tolerance}, 1.0 + \text{tolerance}]$ (по умолчанию $[0.9, 1.1]$), масштабирование не выполняется.
2. **Округление вверх (`ceil`):** Дробные значения всегда округляются до ближайшего большего целого числа, гарантируя запас вычислительной мощности.
3. **Обработка неинициализированных подов:**
   - Поды без готовых readiness-проб или еще не начавшие сбор метрик исключаются из расчета среднего значения.
   - При потенциальном масштабировании **вверх** (scale-up) метрика отсутствующего пода условно принимается равной $0$ (консервативная оценка, предотвращающая ложный всплеск).
   - При потенциальном масштабировании **вниз** (scale-down) метрика отсутствующего пода принимается равной $100\%$ от таргета (предотвращает преждевременное удаление подов).
4. **Исключение завершающихся подов:** Поды со статусом `DeletionTimestamp` (в фазе `Terminating`) полностью исключаются из расчета текущего пула.
5. **Мультиметрика:** Если в секции `metrics` определено несколько правил, контроллер рассчитывает целевое число реплик для каждого правила независимо и выбирает **наибольшее** значение ($\max$).

### Типы метрик спецификации API v2

| Тип | Описание | Метод таргетинга (`target.type`) | Типовой сценарий (On-premise / SRE) |
|:---|:---|:---|:---|
| **`Resource`** | Стандартные ресурсы пода (CPU, Memory). | `Utilization` (процент от requests) или `AverageValue` | Базовые веб-сервисы, бэкенды, API-шлюзы |
| **`ContainerResource`** | Ресурсы конкретного контейнера внутри пода. | `Utilization` или `AverageValue` | Изоляция основного приложения от sidecar (Envoy, Filebeat) |
| **`Pods`** | Метрика приложения, усредненная по всем подам. | `AverageValue` | RPS на инстанс, количество активных горутин/потоков |
| **`Object`** | Метрика отдельного ресурса Kubernetes. | `Value` или `AverageValue` | Очередь Ingress-контроллера, задержка маршрутизатора |
| **`External`** | Метрика внешней инфраструктуры вне кластера. | `Value` или `AverageValue` | Длина очереди RabbitMQ, лаг партиций Kafka, сессии СУБД |

### Управление поведением (блок `behavior`)

Блок `spec.behavior` позволяет раздельно задавать политики масштабирования вверх (`scaleUp`) и вниз (`scaleDown`):

- **`stabilizationWindowSeconds`**: Период усреднения рекомендаций (максимум 3600 секунд). Для `scaleDown` алгоритм выбирает максимальное число реплик за окно, сглаживая кратковременные провалы нагрузки.
- **`selectPolicy`**: Определяет правило выбора между несколькими политиками (`Max`, `Min`, `Disabled`).
- **`policies`**: Массив правил, задающих предел изменения (`Pods` — фиксированное число подов, `Percent` — процент от текущего числа) за указанный период `periodSeconds`.

---

## Практические сценарии и конфигурация

### Предварительные требования

Перед развертыванием HPA убедитесь в соблюдении следующих системных условий:

1. **Доступность Metrics Server:**
   ```bash
   kubectl get apiservice v1beta1.metrics.k8s.io
   # → NAME                      SERVICE                      AVAILABLE   AGE
   # → v1beta1.metrics.k8s.io   kube-system/metrics-server   True        12d

   kubectl top nodes
   # → NAME           CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
   # → node-worker-1  280m         7%     3140Mi          41%
   ```
   Если сервис недоступен, см. руководство по настройке **[Metrics Server](../../MonitoringLogging/metrics-server.md)**.

2. **Обязательное задание `requests` у всех контейнеров:**
   Расчет утилизации в процентах базируется строго на `requests`. Если хотя бы один контейнер пода не имеет блока `requests.cpu`, HPA не сможет рассчитать метрику:
   ```yaml
   resources:
     requests:
       cpu: "250m"
       memory: "256Mi"
     limits:
       cpu: "1000m"
       memory: "512Mi"
   ```

3. **Права RBAC:**
   Учетная запись `system:hpa-controller` в составе `kube-controller-manager` имеет встроенную роль ClusterRole с правами на чтение и обновление подресурса `/scale`. Дополнительных прав для стандартных ресурсов не требуется.

### Декларативное создание HPA (autoscaling/v2)

Ниже приведен эталонный production-манифест с настроенными политиками защиты от дребезга (flapping):

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-service-hpa
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-service
  minReplicas: 3
  maxReplicas: 15
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
    scaleUp:
      stabilizationWindowSeconds: 0
      selectPolicy: Max
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 4
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: 300
      selectPolicy: Min
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
```

### Быстрое создание через CLI (для отладки)

```bash
# Создание HPA по CPU для целевого Deployment
kubectl autoscale deployment api-service -n production --cpu-percent=70 --min=3 --max=15
# → horizontalpodautoscaler.autoscaling/api-service autoscaled
```

### Валидация и проверка статуса

1. Проверка текущих метрик и количества реплик:
   ```bash
   kubectl get hpa api-service -n production
   # → NAME              REFERENCE                TARGETS          MINPODS   MAXPODS   REPLICAS   AGE
   # → api-service-hpa   Deployment/api-service   42%/70%, 55%/80% 3         15        3          4m
   ```

2. Детальная диагностика условий и событий:
   ```bash
   kubectl describe hpa api-service-hpa -n production
   # → Name:                                                  api-service-hpa
   # → Namespace:                                             production
   # → Reference:                                             Deployment/api-service
   # → Metrics:                                               ( current / target )
   # →   resource cpu on pods  (as a percentage of request):  42% (105m) / 70%
   # →   resource memory on pods  (as a percentage of request): 55% (140Mi) / 80%
   # → Min replicas:                                          3
   # → Max replicas:                                          15
   # → Deployment pods:                                       3 current / 3 desired
   # → Conditions:
   # →   Type            Status  Reason               Message
   # →   ----            ------  ------               -------
   # →   AbleToScale     True    ScaleDownStabilized  recent recommendations were higher than current one, applying the highest recent recommendation
   # →   ScalingActive   True    ValidMetricFound     the HPA was able to successfully calculate a replica count from cpu resource
   # →   ScalingLimited  False   DesiredWithinRange   the desired count is within the acceptable range
   # → Events:
   # →   Type    Reason             Age   From                       Message
   # →   ----    ------             ----  ----                       -------
   # →   Normal  SuccessfulRescale  2m    horizontal-pod-autoscaler  New size: 5; reason: cpu resource above target
   ```

3. Генерация синтетической нагрузки для проверки петли управления:
   ```bash
   kubectl run load-tester --rm -i --tty --image=busybox:1.36 --restart=Never -- /bin/sh -c \
     "while true; do wget -q -O- http://api-service.production.svc.cluster.local:8080/healthz; done"
   # → OK
   # → OK
   ```

---

## Операции и команды

Практический справочник команд для регулярной эксплуатации HPA:

| Операция | Команда | Назначение и ожидаемый результат |
|:---|:---|:---|
| **Список всех HPA в кластере** | `kubectl get hpa -A` | Обзор всех контроллеров во всех namespace `# → NAMESPACE NAME REFERENCE TARGETS MINPODS MAXPODS REPLICAS` |
| **Расширенный вывод статуса** | `kubectl get hpa -o wide -n production` | Просмотр детальных метрик и целевого объекта |
| **Проверка статуса сырого API метрик** | `kubectl get --raw "/apis/metrics.k8s.io/v1beta1/pods" \| jq .items[0]` | Прямая валидация доступности cAdvisor и Metrics Server через Aggregated API |
| **Просмотр условий в формате JSON** | `kubectl get hpa api-service-hpa -n production -o jsonpath='{.status.conditions}' \| jq .` | Быстрая проверка флагов `AbleToScale`, `ScalingActive`, `ScalingLimited` |
| **Временная фиксация реплик (отключение HPA)** | `kubectl patch hpa api-service-hpa -n production -p '{"spec":{"minReplicas":5,"maxReplicas":5}}'` | Принудительная фиксация размера пула при инцидентах без удаления объекта HPA |
| **Отключение направления scaleDown** | `kubectl patch hpa api-service-hpa -n production --patch '{"spec":{"behavior":{"scaleDown":{"selectPolicy":"Disabled"}}}}'` | Блокировка удаления подов при расследовании деградации производительности |
| **Удаление HPA** | `kubectl delete hpa api-service-hpa -n production` | Удаление контроллера. **Важно:** Deployment сохраняет текущее число реплик на момент удаления |
| **Логи контроллера масштабирования** | `kubectl logs -n kube-system -l tier=control-plane,component=kube-controller-manager --tail=100 \| grep -i "horizontal-pod-autoscaler"` | Аудит системных решений алгоритма HPA в control-plane |

---

## Диагностика и устранение неполадок

### 1. Статус `<unknown>` в колонке TARGETS

- **Симптом:** Вывод `kubectl get hpa` показывает `<unknown>/70%`.
- **Корневые причины:**
  1. У контейнеров в спецификации PodTemplate отсутствуют параметры `resources.requests.cpu` или `resources.requests.memory`.
  2. Metrics Server не запущен, упал по OOM или не может установить TLS-соединение с kubelet узлов (код ошибки `x509: certificate signed by unknown authority`).
  3. Поды только что запущены и Metrics Server еще не успел собрать первый интервал метрик (требуется 30–60 с).
- **Диагностические шаги:**
  ```bash
  # Проверка наличия requests в подах
  kubectl get pods -n production -l app=api-service -o jsonpath='{.items[*].spec.containers[*].resources.requests}'
  # → {"cpu":"250m","memory":"256Mi"}

  # Проверка работоспособности сервиса метрик
  kubectl top pods -n production -l app=api-service
  # → NAME                           CPU(cores)   MEMORY(bytes)
  # → api-service-75b4865f85-2b4kz   120m         180Mi

  # Проверка логов Metrics Server на наличие ошибок сети и TLS
  kubectl logs -n kube-system -l k8s-app=metrics-server --tail=50
  ```

### 2. Залипание на `maxReplicas` и флаг `ScalingLimited = True`

- **Симптом:** Приложение не справляется с нагрузкой, число подов уперлось в потолок `maxReplicas`, в статусе `ScalingLimited: True`.
- **Корневые причины:**
  - Недостаточный лимит `maxReplicas` для пиковой нагрузки.
  - Утечка памяти (Memory Leak): память не освобождается, HPA держит максимальное число реплик.
  - Дефицит ресурсов на узлах кластера: новые поды зависают в состоянии `Pending` из-за нехватки свободных CPU/RAM на нодах.
- **Диагностические шаги:**
  ```bash
  # Проверка событий масштабирования
  kubectl describe hpa api-service-hpa -n production | grep -A 5 Conditions
  # → ScalingLimited  True  TooManyReplicas  the desired replica count is more than the maximum replica count

  # Проверка подов в статусе Pending
  kubectl get pods -n production -l app=api-service --field-selector status.phase=Pending
  ```

### 3. Дребезг нагрузки (Flapping / Thrashing)

- **Симптом:** HPA постоянно увеличивает число подов, затем через минуту удаляет их, провоцируя лавину рестартов и деградацию кэшей.
- **Корневые причины:**
  - Отсутствие или слишком короткое окно стабилизации `stabilizationWindowSeconds` при масштабировании вниз.
  - Завышенный шаг сжатия (например, удаление 50% подов за раз приводит к мгновенной перегрузке оставшихся).
  - Целевой порог утилизации установлен слишком близко к базовому потреблению приложения.
- **Решение:** Настроить консервативный `behavior.scaleDown`: установить `stabilizationWindowSeconds: 300` и ограничить шаг удаления `policies[0].value: 10%`.

### 4. Конфликт с GitOps-операторами (ArgoCD / Flux)

- **Симптом:** HPA масштабирует Deployment до 8 реплик, но через несколько секунд GitOps-контроллер принудительно возвращает значение 3, указанное в Git-репозитории.
- **Причина:** Поле `spec.replicas` явно объявлено в Git-манифесте Deployment, и контроллер синхронизации расценивает изменение HPA как конфигурационный дрифт.
- **Решение:**
  - Удалить поле `replicas` из манифеста Deployment в Git.
  - Для ArgoCD настроить игнорирование дрифта в `Application`:
    ```yaml
    spec:
      ignoreDifferences:
        - group: apps
          kind: Deployment
          jsonPointers:
            - /spec/replicas
    ```

### 5. Проблема масштабирования по памяти (GC и кэширование)

- **Симптом:** После всплеска трафика нагрузка спала, но HPA не масштабирует сервис вниз, потребление памяти остается высоким.
- **Причина:** Среды выполнения управляемых языков (JVM, Go, Node.js) не возвращают выделенную память операционной системе мгновенно после сборки мусора (GC), удерживая виртуальные страницы в Working Set. cAdvisor считывает метрику `memory.current`, поэтому HPA считает под непрерывно нагруженным.
- **Решение:** Избегать использования памяти как единственной метрики автомасштабирования. Использовать CPU либо прикладные показатели (RPS, concurrency), оставляя память исключительно как аварийный предохранитель с высоким порогом (85–90%).

---

## Лучшие практики

1. **Разделение ролей метрик (CPU vs Memory):**
   Для большинства stateless-приложений основным драйвером масштабирования должен быть CPU. Метрика CPU эластична и мгновенно падает при исчезновении запросов. Память следует включать в HPA только при наличии строгих гарантий освобождения буферов приложением либо в комбинации с кастомными метриками.

2. **Обязательное использование PodDisruptionBudget (PDB):**
   При динамическом масштабировании вниз контроллер удаляет поды. Наличие PDB гарантирует, что в процессе сжатия или параллельного обслуживания узлов (drain) сервис сохранит минимально необходимый кворум реплик:
   ```yaml
   apiVersion: policy/v1
   kind: PodDisruptionBudget
   metadata:
     name: api-service-pdb
     namespace: production
   spec:
     minAvailable: 2
     selector:
       matchLabels:
         app: api-service
   ```

3. **Синхронизация с Probes (Readiness & Startup):**
   HPA учитывает только поды, перешедшие в состояние `Ready`. Корректная настройка `readinessProbe` и `startupProbe` предотвращает попадание «холодных» инстансов в алгоритм распределения метрик, защищая от преждевременного пересчета.

4. **Корректный сайзинг `requests` относительно `limits`:**
   Значение `requests` должно соответствовать нормальному среднему потреблению инстанса под номинальной нагрузкой, а не быть заниженным. Занижение `requests` приводит к тому, что под утилизирует 300% от запроса, вызывая взрывной scale-up и перегрузку физических узлов.

5. **Мониторинг и алертинг контроллера через Prometheus (`kube-state-metrics`):**
   Инфраструктурная команда должна отслеживать ключевые метрики состояния HPA:
   - `kube_horizontalpodautoscaler_status_desired_replicas` — расчетное число подов.
   - `kube_horizontalpodautoscaler_status_current_replicas` — фактически запущенные поды.
   - `kube_horizontalpodautoscaler_spec_max_replicas` — сконфигурированный верхний предел.
   - **Рекомендуемый SRE-алерт:** срабатывание при `kube_horizontalpodautoscaler_status_desired_replicas >= kube_horizontalpodautoscaler_spec_max_replicas` на протяжении более 15 минут (сигнализирует о нехватке лимита масштабирования).

---

## Дополнительная информация

### Карта раздела автомасштабирования HPA

Для углубленного изучения смежных архитектурных и практических аспектов используйте специализированные материалы раздела:

- **[HPA: Основные концепции](./hpa_concepts.md)** — математика алгоритма, устройство подресурса `/scale`, взаимодействие cgroups и Kubelet Summary API.
- **[HPA: Практические сценарии](./hpa_scenarios.md)** — готовые манифесты масштабирования по CPU, памяти, ContainerResource, очередям RabbitMQ/Kafka и HTTP RPS.
- **[HPA: Продвинутые темы](./hpa_advanced.md)** — детальный разбор блока `behavior`, окна стабилизации, флаги `kube-controller-manager` и ядро Linux.
- **[Prometheus Adapter: Настройка и интеграция](./prometheus_adapter_setup.md)** — интеграция Prometheus с Custom и External Metrics API через правила PromQL.
- **[HPA: Каскадное масштабирование](./cascading_scaling.md)** — предотвращение каскадных сбоев, резонанса и лавинной перегрузки в цепочках микросервисов.
- **[HPA: Cost и Right-sizing](./hpa_cost_rightsizing.md)** — оптимизация аппаратных затрат, расчет плотности размещения и баланс requests/limits.

### Взаимодействие со смежными компонентами кластера

- **[Metrics Server](../../MonitoringLogging/metrics-server.md)** — развертывание, RBAC и обеспечение отказоустойчивости источника системных метрик.
- **[KEDA: Событийное масштабирование](../keda/keda_concepts.md)** — масштабирование по событиям внешних систем и поддержка scale-to-zero (масштабирование в 0 реплик).
- **[VPA: Вертикальное автомасштабирование](../vpa_detailed.md)** — оптимизация размеров контейнеров. **Важно:** запрещено совместное использование HPA и VPA по одним и тем же метрикам (CPU/RAM).
- **[Cluster Autoscaler](../cluster_autoscaler_detailed.md)** — автоматическое управление физическими или виртуальными узлами кластера при дефиците ресурсов.
- **[Pod Disruption Budget](../pod_disruption_budget.md)** — обеспечение непрерывной доступности при плановых выводах узлов и масштабировании вниз.
- **[Устранение неполадок HPA](../../Troubleshooting/Common_Errors/hpa_troubleshooting.md)** — расширенное руководство по локализации ошибок и сбоев масштабирования.

### Вопросы и ответы для собеседования

**Вопрос:** Как устроен цикл управления (control loop) HPA и с какой периодичностью он срабатывает?  
**Ответ:** Контроллер HPA работает внутри `kube-controller-manager`. Каждые 15 секунд (параметр `--horizontal-pod-autoscaler-sync-period`) он опрашивает Aggregated API (`metrics.k8s.io`, `custom.metrics.k8s.io` или `external.metrics.k8s.io`), сравнивает значения с целевыми, рассчитывает желаемое количество подов по формуле с учетом толерантности (10%) и при необходимости обновляет поле `replicas` через подресурс `/scale`.

**Вопрос:** Почему при наличии HPA нельзя указывать поле `replicas` в манифесте Deployment в GitOps (ArgoCD)?  
**Ответ:** Возникает гонка состояний (reconciliation loop fight). Когда HPA изменяет число реплик в кластере, GitOps-оператор обнаруживает расхождение с Git-репозиторием и откатывает Deployment к значению из манифеста. Решение — убрать `spec.replicas` из Deployment либо добавить поле в `ignoreDifferences`.

**Вопрос:** Почему не рекомендуется использовать утилизацию памяти (RAM) как единственную метрику для HPA?  
**Ответ:** Языки со сборщиком мусора (Java, Go, NodeJS) и дисковые буферы Linux удерживают память в Working Set даже после снижения рабочей нагрузки. Metrics Server отдает текущее потребление cgroups, из-за чего HPA не может инициировать scale-down, удерживая максимальное число подов. Память используют как предохранитель или в связке с CPU/RPS.

**Вопрос:** В чем разница между `Custom Metrics` и `External Metrics` в HPA?  
**Ответ:** Custom Metrics привязаны к объектам кластера Kubernetes (например, метрика `http_requests_per_second` связана с подами конкретного Deployment или объектом Ingress). External Metrics представляют собой показатели систем, находящихся вне кластера или не имеющих прямого маппинга на поды (длина очереди RabbitMQ, лаг группы консьюмеров Kafka, число активных соединений в СУБД).
