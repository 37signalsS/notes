# Управление жизненным циклом Deployment в Kubernetes

**Актуально для:** Kubernetes 1.30–1.32+

Декларативные и императивные процессы контроля состояния stateless-нагрузки: от архитектуры контроллера и математики ротации реплик до автоматизированных гейтов в CI/CD, безаварийного переключения трафика на bare-metal и процедур аварийного восстановления (SRE Runbooks).

## Предварительные требования (Prerequisites)

- **Рабочий кластер Kubernetes:** версии 1.30–1.32+ (на базе `kubeadm`, RKE2 или K3s на bare-metal / локальных виртуальных машинах). Стабильная группа API `apps/v1`.
- **Утилиты командной строки:**
  - `kubectl` актуальной версии (совпадающей с версией кластера ±1 minor). Флаг `--record` окончательно удален в v1.24; документирование причин изменений выполняется исключительно через аннотацию `kubernetes.io/change-cause`.
  - `jq` (v1.6+) и стандартный POSIX-совместимый интерпретатор команд (`bash` v4.4+) для автоматизации сценариев развертывания и отката.
- **RBAC-полномочия:**
  - Минимальный набор прав для инженера и сервисного аккаунта CI/CD: глаголы `get`, `list`, `watch`, `update`, `patch` для ресурсов `deployments`, `replicasets`, `pods` в API-группе `apps/v1` и `core/v1`, а также доступ к чтению `events`.
  - Команды семейства `kubectl rollout ...` **не используют** выделенный субресурс `rollout` — они считывают и мутируют спецификацию и аннотации самого объекта `Deployment` через стандартные эндпоинты Kubernetes API.
- **Базовые знания архитектуры:**
  - Понимание иерархии абстракций: [Deployment: Обзор](./index.md), [ReplicaSet](../replicaset.md), [Pod](../Pod/pod_overview.md).
  - Спецификация полей и QoS-классы: [Манифест и лучшие практики](./deployment_manifest.md).
  - Механика сетевых проверок: [Пробы жизнедеятельности в Kubernetes](../probes.md).

---

## 1. Определения

- **Управление жизненным циклом (Lifecycle Management)** — замкнутый цикл процессов контроля желаемого и фактического состояний приложения: планирование развертывания, постепенная или монопольная ротация реплик, валидация прогресса через пробы, масштабирование, пакетное внесение изменений, откат к историческим версиям и аварийное дренирование.
- **Deployment Controller** — управляющий контур (reconciliation loop) в составе демона `kube-controller-manager`, непрерывно сравнивающий декларативную спецификацию `spec` объекта `Deployment` с фактическим состоянием дочерних объектов `ReplicaSet` и статусом `status`.
- **Rollout (Выкатка / Раскатка)** — процесс детерминированного перехода группы подов с одной версии шаблона (`spec.template`) на другую. В рамках стандартной стратегии `RollingUpdate` выполняется путем постепенного изменения желаемого числа реплик между старыми и новыми объектами `ReplicaSet`.
- **Revision (Ревизия)** — зафиксированный в кластере моментальный снимок шаблона пода (`spec.template`), материализованный в виде отдельного объекта `ReplicaSet`. Порядковый номер ревизии сохраняется в аннотации `deployment.kubernetes.io/revision` (строковый целочисленный счетчик).
- **pod-template-hash** — 32-битный FNV-1a хеш структуры `PodTemplateSpec`, вычисляемый контроллером и автоматически добавляемый в метки селектора `ReplicaSet` и подов (`pod-template-hash=<hash>`). Предотвращает коллизии селекторов между поколениями одного Deployment.
- **Rollback (Откат)** — процедура восстановления конфигурации пода из выбранной исторической ревизии. В Kubernetes откат является направленным вперед процессом (**Rollout Forward**): контроллер не удаляет историю и не «перематывает время», а создает новую ревизию с шаблоном, скопированным из целевого `ReplicaSet`.
- **Rollover (Перекрытие выкаток / Каскадная замена)** — состояние, когда новый запуск обновления (`spec.template`) поступает до того, как предыдущий rollout успел завершиться. Контроллер не ждет стабилизации промежуточной версии, а немедленно начинает ее сворачивание, форсируя развертывание последней целевой версии.
- **Пропорциональное масштабирование (Proportional Scaling)** — внутренний алгоритм контроллера Deployment, делящий добавление или удаление реплик между всеми активными `ReplicaSet` пропорционально их текущему размеру, если масштабирование инициировано во время незавершенного или приостановленного rollout.
- **Пауза (Pause)** — состояние `spec.paused: true`, при котором контроллер Deployment временно отключает запуск новых процессов ротации ReplicaSet при изменениях в `spec.template`, продолжая обслуживать текущие поды и обрабатывать изменение общего числа реплик (`spec.replicas`).
- **Restart (Принудительный перезапуск)** — процедура инициирования нового rollout без изменения кода и конфигурации контейнеров путем внедрения временной метки `kubectl.kubernetes.io/restartedAt` в метаданные шаблона пода.
- **Zero-Downtime Rollout** — процесс обновления сервиса без потери сетевых соединений и без возврата ошибок клиентам (502/504 Bad Gateway). Достигается синхронизацией времени готовности подов (`readinessProbe`), задержки стабилизации (`minReadySeconds`), переключения маршрутов в `EndpointSlice` и плавного завершения (`preStop` + `terminationGracePeriodSeconds`).
- **Change Cause (Причина изменения)** — значение служебной аннотации `kubernetes.io/change-cause`, фиксирующее человекочитаемое описание релиза и отображаемое в выводе `kubectl rollout history`.

---

## 2. Базовые концепции и архитектура

### Архитектура контроллера и цикл согласования

В Kubernetes `Deployment` не управляет подами напрямую. Он реализует двухуровневое дерево владения через ссылки `ownerReferences`:

```text
               Deployment Controller (kube-controller-manager)
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼ (управляет spec.replicas)                         ▼ (управляет spec.replicas)
     ReplicaSet (New: rev 3)                             ReplicaSet (Old: rev 2)
   hash: 7d6b9f4b9c, replicas: 3                       hash: 58f8b88df8, replicas: 0
            │                                                   │
   ┌────────┴────────┐                                 (поды завершены)
   ▼                 ▼
Pod (v3)          Pod (v3)
```

1. **Deployment** управляет объектами **ReplicaSet** (создает новые, изменяет их `spec.replicas`, удаляет устаревшие по лимиту истории).
2. **ReplicaSet Controller** управляет конкретными экземплярами **Pod** (создает их через API-сервер, отслеживает соответствие селекторам).
3. **Kubelet** на рабочих узлах запускает контейнеры, исполняет проверки (`probes`) и исполняет хуки жизненного цикла (`preStop`).
4. **EndpointSlice Controller** и **kube-proxy** связывают сетевой сервис (`Service`) с подами, перешедшими в состояние `Ready`.

Каскадное удаление (Garbage Collection): при удалении объекта Deployment механизм `ownerReferences` удаляет все дочерние `ReplicaSet` и их поды (если не был явно передан флаг `--cascade=orphan`).

### Механизм генерации `pod-template-hash`

При каждом изменении `spec.template` контроллер Deployment:
1. Берет полную структуру шаблона пода (`PodTemplateSpec`).
2. Очищает из нее системные поля и саму метку `pod-template-hash`.
3. Рассчитывает 32-битный FNV-1a хеш от сериализованной структуры.
4. Добавляет вычисленный хеш в селектор меток создаваемого `ReplicaSet` и в шаблон меток пода:
   ```yaml
   labels:
     app: payment-api
     pod-template-hash: "6f8c7b8d4f"
   ```
Благодаря этому несколько `ReplicaSet`, имеющих одинаковые пользовательские метки `app: payment-api`, изолированы друг от друга и не захватывают чужие поды.

### Триггеры запуска Rollout

Обновление (новый Rollout и новая ревизия) инициируется **исключительно** при изменении содержимого шаблона пода (`spec.template`).

| Область манифеста | Поля | Инициирует Rollout? | Создает новую ревизию? |
| :--- | :--- | :---: | :---: |
| **Спецификация контейнера** | `image`, `command`, `args`, `env`, `envFrom`, `resources`, `ports`, `securityContext` | **Да** | **Да** |
| **Тома и монтирования** | `volumes`, `volumeMounts` | **Да** | **Да** |
| **Проверки (Probes)** | `livenessProbe`, `readinessProbe`, `startupProbe` | **Да** | **Да** |
| **Метаданные шаблона** | `spec.template.metadata.labels`, `spec.template.metadata.annotations` | **Да** | **Да** |
| **Жизненный цикл пода** | `terminationGracePeriodSeconds`, `serviceAccountName`, `dnsPolicy`, `affinity` | **Да** | **Да** |
| **Масштабирование** | `spec.replicas` | **Нет** | **Нет** (меняет размер текущего RS) |
| **Параметры выкатки** | `spec.strategy`, `spec.minReadySeconds`, `spec.progressDeadlineSeconds` | **Нет** | **Нет** (применяется к текущему rollout) |
| **Лимит истории** | `spec.revisionHistoryLimit` | **Нет** | **Нет** (удаляет лишние RS) |
| **Метаданные Deployment** | `metadata.labels`, `metadata.annotations` (включая `change-cause`) | **Нет** | **Нет** |

> [!IMPORTANT]
> Изменение данных внутри `ConfigMap` или `Secret` само по себе **не изменяет** манифест Deployment и **не запускает** Rollout. Контейнеры продолжают работать со старыми конфигурациями, пока не будет вызван `kubectl rollout restart` либо не будет изменена аннотация с хешем конфигурации внутри `spec.template.metadata.annotations` (см. [Обновление и rollout ConfigMap](../ConfigMap/update_and_rollout.md)).

---

### Механика RollingUpdate: алгоритм пошаговой ротации

При стандартной стратегии обновления (`type: RollingUpdate`) контроллер гарантирует выполнение двух инвариантов на каждом шаге цикла:

1. **Верхний лимит мощности (Surge Limit):**
   $$\text{MaxPods} = \text{spec.replicas} + \text{maxSurge}$$
   Фактическое количество созданных подов во всех связанных `ReplicaSet` ни в какой момент времени не может превысить данное значение.
2. **Нижний лимит доступности (Availability Floor):**
   $$\text{MinAvailablePods} = \text{spec.replicas} - \text{maxUnavailable}$$
   Фактическое количество подов в статусе `Available` (готовых к обслуживанию трафика) ни в какой момент не может опуститься ниже данного значения.

#### Шаги перехода реплик:
```text
Начало:        RS-Old: 4 реплики (Ready) | RS-New: 0 реплик
               (maxSurge: 1, maxUnavailable: 0, всего desired: 4)

Шаг 1 (Surge): RS-Old: 4 реплики (Ready) | RS-New: 1 реплика (Creating/Starting)
               Всего подов: 5 (не превышает 4 + 1)

Шаг 2 (Ready): RS-New-1 прошел readinessProbe и выждал minReadySeconds → Available!
               Доступно подов: 5. Допустимый минимум: 4.

Шаг 3 (Drain): RS-Old уменьшается: 4 → 3 (один старый под получает SIGTERM).
               RS-New увеличивается: 1 → 2.

... цикл повторяется до полной ротации ...

Итог:          RS-Old: 0 реплик          | RS-New: 4 реплики (Available)
```

---

### Пропорциональное масштабирование (Proportional Scaling)

Если во время активного или приостановленного (`paused`) процесса обновления администратор или HPA меняет значение `spec.replicas`, контроллер не может просто передать все новые реплики новому `ReplicaSet` — это сломало бы баланс готовности.

Контроллер запускает алгоритм **пропорционального распределения**:
1. Вычисляется суммарное текущее количество подов во всех активных `ReplicaSet` с `replicas > 0`.
2. Каждому активному `ReplicaSet` выделяется доля от нового целевого размера по формуле:
   $$\text{desired}_{RS} = \text{round}\left( \frac{\text{current}_{RS}}{\text{totalCurrent}} \times \text{newDeploymentReplicas} \right)$$
3. **Обработка остатка:** Если из-за целочисленного округления сумма долей не совпадает с `newDeploymentReplicas`, разница добавляется к `ReplicaSet` с наибольшим количеством реплик.
4. `ReplicaSet`, имеющие `replicas: 0`, **никогда не масштабируются вверх** при пропорциональном масштабировании.

*Пример:*
- Deployment разворачивается: `RS-Old` имеет 6 реплик, `RS-New` успел набрать 2 реплики (всего 8).
- HPA увеличивает нагрузку до `replicas: 12`.
- Прирост в 4 реплики распределяется пропорционально:
  - `RS-Old`: $\frac{6}{8} \times 12 = 9$ реплик.
  - `RS-New`: $\frac{2}{8} \times 12 = 3$ реплики.
- После пропорционального изменения размеров контроллер продолжает обычный процесс RollingUpdate, перекачивая поды с `RS-Old` на `RS-New`.

---

### Перекрывающиеся обновления (Rollover)

Когда разработчик или CI/CD выполняет выкатку версии `v3` в момент, когда выкатка `v2` поверх `v1` еще не завершена:
1. Контроллер определяет `RS-v3` как целевой активный набор реплик.
2. Промежуточный набор `RS-v2` немедленно понижается до статуса «старого» (устаревшего).
3. Оба старых набора (`RS-v1` и `RS-v2`) синхронно масштабируются вниз до 0 по мере того, как поднимаются поды `RS-v3`.
4. Выкатка `v2` прерывается без ожидания готовности ее подов.

Это фундаментальное свойство позволяет оперативно выкатывать аварийные хотфиксы поверх зависших деплоев без ручной очистки промежуточных состояний.

---

### Архитектура Zero-Downtime и координация остановки пода

Стандартная ошибка на bare-metal инсталляциях: во время RollingUpdate клиенты получают спорадические ошибки `502 Bad Gateway` или `Connection Reset`, даже если `maxUnavailable: 0`.

Причина кроется в асинхронной природе компонентов Kubernetes при выводе пода из эксплуатации:

```text
1. API-сервер: Pod помечен как Terminating (deletionTimestamp выставлен)
          │
          ├────────────────────────────────────────┬────────────────────────────────────────┐
          ▼ (асинхронно)                           ▼ (асинхронно)                           ▼ (асинхронно)
EndpointSlice Controller                  Kubelet на ноде                        Ingress / LB
          │                                        │                                        │
Исключает Pod IP из EndpointSlice         Запускает hook lifecycle.preStop         Продолжает слать трафик,
          │                                        │                               пока не обновится
iptables / IPVS на узлах обновляются      По завершении preStop                    локальный кеш эндпоинтов
(задержка синхронизации: 1–3 сек)         посылает процессору SIGTERM              (задержка: 1–5 сек)
```

Если приложение перехватывает `SIGTERM` и мгновенно закрывает сокет, оно отклонит входящие TCP-соединения, которые Ingress-контроллер все еще отправляет по старому состоянию кеша.

**Обязательное инженерное решение:**
1. Внедрить задержку через `preStop`-хук:
   ```yaml
   lifecycle:
     preStop:
       exec:
         command: ["/bin/sh", "-c", "sleep 10"]
   ```
2. Установить `terminationGracePeriodSeconds` больше, чем задержка `preStop` + время дообработки активных соединений (например, `sleep 10` + дренаж 15с $\rightarrow$ `terminationGracePeriodSeconds: 45`).

---

### Структура и хранение истории ревизий

История изменений хранится в объектах `ReplicaSet` в `etcd`.
- Параметр `spec.revisionHistoryLimit` (по умолчанию `10`) задает, сколько неактивных объектов `ReplicaSet` с 0 реплик сохраняется контроллером.
- **Алгоритм очистки:** При создании ревизии контроллер сортирует все связанные RS с нулевым числом реплик по возрастанию аннотации `deployment.kubernetes.io/revision` и удаляет самые старые, превышающие лимит.
- Если `revisionHistoryLimit: 0`, контроллер немедленно удаляет старые RS. **Откат через `kubectl rollout undo` становится технически невозможен.**

---

## 3. Практические сценарии

### Сценарий 1: Производственный Zero-Downtime Rolling Update

Эталонный манифест для stateless API-сервиса, разворачиваемого на bare-metal кластере с гарантией отсутствия даунтайма:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-service
  namespace: production
  labels:
    app.kubernetes.io/name: order-service
    app.kubernetes.io/part-of: e-commerce
  annotations:
    kubernetes.io/change-cause: "Релиз 2.14.0: оптимизация пула соединений БД"
spec:
  replicas: 4
  revisionHistoryLimit: 5
  minReadySeconds: 15
  progressDeadlineSeconds: 300
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: order-service
  template:
    metadata:
      labels:
        app: order-service
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: api
          image: registry.internal/finance/order-service:v2.14.0
          imagePullPolicy: IfNotPresent
          ports:
            - containerPort: 8080
              name: http
          lifecycle:
            preStop:
              exec:
                command: ["/bin/sh", "-c", "sleep 10"]
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
            failureThreshold: 3
            successThreshold: 1
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 15
            periodSeconds: 10
            failureThreshold: 3
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: 1000m
              memory: 512Mi
```

Применение обновления и контроль процесса:
```bash
# Применение манифеста
kubectl apply -f order-service-deployment.yaml
# → deployment.apps/order-service configured

# Отслеживание ротации с выводом статуса
kubectl rollout status deployment/order-service -n production --timeout=5m
# → Waiting for deployment "order-service" rollout to finish: 1 of 4 updated replicas are available...
# → Waiting for deployment "order-service" rollout to finish: 2 of 4 updated replicas are available...
# → Waiting for deployment "order-service" rollout to finish: 3 of 4 updated replicas are available...
# → deployment "order-service" successfully rolled out
```

---

### Сценарий 2: Атомарное пакетное обновление через Pause / Resume

Когда требуется синхронно изменить образ, лимиты ресурсов и переменные окружения, применение трех последовательных команд `kubectl set ...` вызовет создание трех последовательных ревизий и три тяжелых цикла пересоздания подов.

Использование режима паузы объединяет все правки в единый rollout:

```bash
# 1. Замораживаем реакцию контроллера на изменение шаблона
kubectl rollout pause deployment/order-service -n production
# → deployment.apps/order-service paused

# 2. Вносим пакет изменений в спецификацию (rollout не начинается)
kubectl set image deployment/order-service api=registry.internal/finance/order-service:v2.14.1 -n production
# → deployment.apps/order-service image updated

kubectl set resources deployment/order-service -c=api --requests=cpu=500m,memory=512Mi --limits=cpu=1500m,memory=1Gi -n production
# → deployment.apps/order-service resource requirements updated

kubectl set env deployment/order-service LOG_LEVEL=warn DB_POOL_SIZE=30 -n production
# → deployment.apps/order-service env updated

# 3. Документируем причину комплексного изменения
kubectl annotate deployment/order-service kubernetes.io/change-cause="Пакетный апдейт v2.14.1: повышение пула и ресурсов" -n production --overwrite
# → deployment.apps/order-service annotated

# 4. Проверяем, что Deployment действительно находится на паузе
kubectl get deployment order-service -n production -o jsonpath='{.spec.paused}'
# → true

# 5. Снимаем с паузы — стартует ровно ОДИН rollout, объединяющий все изменения
kubectl rollout resume deployment/order-service -n production
# → deployment.apps/order-service resumed

# 6. Блокирующее ожидание успешной раскатки
kubectl rollout status deployment/order-service -n production --timeout=5m
# → deployment "order-service" successfully rolled out
```

---

### Сценарий 3: CI/CD Deployment Gate со скриптованным откатом

Промышленный bash-скрипт для шага развертывания в GitLab CI / Woodpecker / Jenkins без внешних зависимостей. Обрабатывает таймауты, транзиентные сбои сети API и производит автоматический откат при нарушении условий готовности:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOYMENT_NAME="order-service"
NAMESPACE="production"
TARGET_IMAGE="registry.internal/finance/order-service:${CI_COMMIT_TAG:-latest}"
ROLLOUT_TIMEOUT="300s"
CHANGE_REASON="CI Release ${CI_COMMIT_SHORT_SHA:-manual} by ${GITLAB_USER_LOGIN:-cli}"

echo "=== [1/4] Инициирование обновления ${DEPLOYMENT_NAME} ==="
kubectl set image "deployment/${DEPLOYMENT_NAME}" \
  "api=${TARGET_IMAGE}" \
  -n "${NAMESPACE}"

kubectl annotate "deployment/${DEPLOYMENT_NAME}" \
  kubernetes.io/change-cause="${CHANGE_REASON}" \
  --overwrite \
  -n "${NAMESPACE}"

echo "=== [2/4] Ожидание стабилизации Rollout (таймаут: ${ROLLOUT_TIMEOUT}) ==="
if ! kubectl rollout status "deployment/${DEPLOYMENT_NAME}" \
  -n "${NAMESPACE}" \
  --timeout="${ROLLOUT_TIMEOUT}"; then

  echo "!!! ОШИБКА: Rollout завершился сбоем или превысил лимит времени. Запуск аварийного отката..." >&2

  # Вывод диагностических данных перед откатом для артефактов пайплайна
  echo "--- Диагностика подов ---"
  kubectl get pods -n "${NAMESPACE}" -l app="${DEPLOYMENT_NAME}" --show-labels || true
  kubectl describe deployment "${DEPLOYMENT_NAME}" -n "${NAMESPACE}" | tail -n 25 || true

  echo "=== [3/4] Выполнение kubectl rollout undo ==="
  kubectl rollout undo "deployment/${DEPLOYMENT_NAME}" -n "${NAMESPACE}"

  echo "=== [4/4] Ожидание завершения отката ==="
  if kubectl rollout status "deployment/${DEPLOYMENT_NAME}" -n "${NAMESPACE}" --timeout=180s; then
    echo ">>> Откат успешно завершен. Приложение стабилизировано на предыдущей версии." >&2
  else
    echo "!!! КРИТИЧЕСКИЙ СБОЙ: Откат не завершился вовремя. Требуется ручное вмешательство On-call!" >&2
  fi
  exit 1
fi

echo "=== Выкатка успешно завершена ==="
```

---

### Сценарий 4: Экстренная каскадная замена (Hotfix Rollover)

Ситуация: Выкатка версии `v2.14.0` зависла (контейнеры падают с `CrashLoopBackOff` из-за ошибки в коде). Старые поды `v2.13.0` продолжают работать, но нужно срочно доставить исправление `v2.14.1`:

```bash
# 1. Проверяем текущее зависшее состояние (новый RS не может подняться)
kubectl get rs -n production -l app=order-service
# → NAME                           DESIRED   CURRENT   READY   AGE
# → order-service-6f8c7b8d4f       4         4         4       2d    (старый v2.13.0)
# → order-service-7a9b1c2d3e       1         1         0       3m    (зависший v2.14.0)

# 2. Не выполняя ручного удаления и отката, сразу применяем исправленный образ v2.14.1
kubectl set image deployment/order-service api=registry.internal/finance/order-service:v2.14.1 -n production
# → deployment.apps/order-service image updated

kubectl annotate deployment/order-service kubernetes.io/change-cause="HOTFIX: исправление NPE в обработчике платежей" -n production --overwrite
# → deployment.apps/order-service annotated

# 3. Контроллер автоматически переводит зависший RS в режим масштабирования вниз:
kubectl get rs -n production -l app=order-service
# → NAME                           DESIRED   CURRENT   READY   AGE
# → order-service-6f8c7b8d4f       3         3         3       2d    (старый v2.13.0, сворачивается)
# → order-service-7a9b1c2d3e       0         1         0       4m    (битый v2.14.0, принудительно в 0)
# → order-service-8b5d6e7f1a       1         1         1       10s   (хотфикс v2.14.1, растет)

# 4. Дожидаемся успешного завершения
kubectl rollout status deployment/order-service -n production --timeout=3m
# → deployment "order-service" successfully rolled out
```

---

### Сценарий 5: Нативный Canary-релиз на двух Deployment без Service Mesh

В среде без Istio/Linkerd канареечный релиз можно реализовать базовыми средствами ядра Kubernetes с помощью разделения общего Service:

```text
                  Service: order-service (selector: app=order-service)
                                          │
            ┌─────────────────────────────┴─────────────────────────────┐
            ▼ (90% трафика)                                             ▼ (10% трафика)
Deployment: order-service-stable                            Deployment: order-service-canary
replicas: 9, image: v2.13.0                                 replicas: 1, image: v2.14.0
labels:                                                     labels:
  app: order-service                                          app: order-service
  track: stable                                               track: canary
```

1. **Создание канареечного Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-service-canary
  namespace: production
spec:
  replicas: 1
  selector:
    matchLabels:
      app: order-service
      track: canary
  template:
    metadata:
      labels:
        app: order-service
        track: canary
    spec:
      containers:
        - name: api
          image: registry.internal/finance/order-service:v2.14.0
          ports:
            - containerPort: 8080
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8080
```

2. **Процедура промоушена или отката:**
```bash
# В случае обнаружения всплеска 5xx на канарейке — мгновенный откат в 0 реплик:
kubectl scale deployment/order-service-canary --replicas=0 -n production
# → deployment.apps/order-service-canary scaled

# В случае успешной валидации метрик:
# 1. Обновляем основной stable deployment:
kubectl set image deployment/order-service-stable api=registry.internal/finance/order-service:v2.14.0 -n production
kubectl rollout status deployment/order-service-stable -n production

# 2. Сворачиваем canary deployment:
kubectl scale deployment/order-service-canary --replicas=0 -n production
```

---

### Сценарий 6: Аварийный откат (SRE Break-Glass Runbook)

Пошаговый регламент действий дежурного инженера при инциденте SEV-1 после релиза:

```bash
# Шаг 1: Оценка истории ревизий и определение стабильного номера
kubectl rollout history deployment/order-service -n production
# → REVISION  CHANGE-CAUSE
# → 4         Релиз 2.13.0: базовая версия
# → 5         Релиз 2.14.0: сбойная версия (вызывает 500 ISE)

# Шаг 2: Проверка шаблона целевой ревизии перед откатом
kubectl rollout history deployment/order-service --revision=4 -n production

# Шаг 3: Проверка состояния паузы (откат не сработает, если Deployment paused)
IS_PAUSED=$(kubectl get deployment order-service -n production -o jsonpath='{.spec.paused}')
if [ "$IS_PAUSED" = "true" ]; then
  echo "Снятие паузы перед откатом..."
  kubectl rollout resume deployment/order-service -n production
fi

# Шаг 4: Выполнение отката к подтвержденной ревизии
kubectl rollout undo deployment/order-service --to-revision=4 -n production
# → deployment.apps/order-service rolled back

# Шаг 5: Документирование аварийного действия
kubectl annotate deployment/order-service kubernetes.io/change-cause="ROLLBACK: Аварийный откат к rev 4 в рамках INCIDENT-4029" -n production --overwrite

# Шаг 6: Контроль восстановления доступности
kubectl rollout status deployment/order-service -n production --timeout=3m
```

> [!CAUTION]
> Откат Deployment возвращает только шаблон пода (`spec.template`). Он **не откатывает** изменения в схемах баз данных, миграциях и содержимом разделяемых сетевых хранилищ. При разработке обязательно использование архитектурного шаблона неломающих изменений схемы (Expand / Contract Pattern).

---

## 4. Операции и команды

### Справочная таблица команд управления жизненным циклом

| Операция | Команда | Назначение и параметры |
| :--- | :--- | :--- |
| **Статус выкатки** | `kubectl rollout status deployment/<name>` | Блокирующее ожидание завершения. Флаги: `--timeout=5m`, `--watch=false` (снимок состояния). |
| **История ревизий** | `kubectl rollout history deployment/<name>` | Список всех сохраненных ревизий с их `CHANGE-CAUSE`. |
| **Анализ ревизии** | `kubectl rollout history deployment/<name> --revision=N` | Детальный вывод YAML-шаблона пода для ревизии `N`. |
| **Откат к предыдущей** | `kubectl rollout undo deployment/<name>` | Создает ревизию $N+1$ со спецификацией из ревизии $N-1$. |
| **Откат к целевой** | `kubectl rollout undo deployment/<name> --to-revision=N` | Откат к конкретной исторической ревизии $N$. |
| **Пробный откат** | `kubectl rollout undo deployment/<name> --dry-run=server -o yaml` | Проверка валидации на API-сервере без реального применения. |
| **Пауза выкатки** | `kubectl rollout pause deployment/<name>` | Заморозка ротации подов для пакетирования изменений. |
| **Снятие паузы** | `kubectl rollout resume deployment/<name>` | Запуск отложенного согласования накопленных изменений. |
| **Перезапуск подов** | `kubectl rollout restart deployment/<name>` | Плавный перезапуск без изменения конфигурации (инъекция restartedAt). |
| **Масштабирование** | `kubectl scale deployment/<name> --replicas=N` | Императивное изменение числа реплик активного RS. |
| **Субресурс Scale** | `kubectl patch deployment/<name> --subresource scale -p '{"spec":{"replicas":N}}'` | Безопасное изменение реплик без конфликта манифестов. |

---

### Примеры выполнения и ожидаемый вывод

```bash
# 1. Просмотр истории с документированными причинами
kubectl rollout history deployment/order-service -n production
# → REVISION  CHANGE-CAUSE
# → 1         Первичный деплой v1.0.0
# → 2         Оптимизация пулов БД v2.0.0
# → 3         Обновление runtime v2.1.0

# 2. Принудительный перезапуск подов (rolling restart)
kubectl rollout restart deployment/order-service -n production
# → deployment.apps/order-service restarted

# 3. Мониторинг процесса перезапуска с жестким таймаутом
kubectl rollout status deployment/order-service -n production --timeout=120s
# → Waiting for deployment "order-service" rollout to finish: 1 of 4 updated replicas are available...
# → Waiting for deployment "order-service" rollout to finish: 2 of 4 updated replicas are available...
# → Waiting for deployment "order-service" rollout to finish: 3 of 4 updated replicas are available...
# → deployment "order-service" successfully rolled out

# 4. Проверка системных событий, подтверждающих ротацию ReplicaSet
kubectl get events -n production --field-selector involvedObject.name=order-service --sort-by='.metadata.creationTimestamp' | tail -n 6
# → 2m   Normal   ScalingReplicaSet   deployment/order-service   Scaled up replica set order-service-7f8d6c to 1
# → 95s  Normal   ScalingReplicaSet   deployment/order-service   Scaled down replica set order-service-5c4b3a to 3
# → 95s  Normal   ScalingReplicaSet   deployment/order-service   Scaled up replica set order-service-7f8d6c to 2
# → 40s  Normal   ScalingReplicaSet   deployment/order-service   Scaled down replica set order-service-5c4b3a to 0
```

---

## 5. Диагностика и устранение неполадок

### Матрица типовых сбоев жизненного цикла (SRE Diagnostic Matrix)

| Симптом | Корневая причина | Диагностическая команда | Быстрое решение (Remediation) |
| :--- | :--- | :--- | :--- |
| `rollout status` зависает; Condition `ProgressDeadlineExceeded` | Контейнеры нового RS падают при старте (`CrashLoopBackOff`, неверные env/тома) | `kubectl describe deployment <name>`<br>`kubectl logs -n <ns> -l app=<name> --previous` | 1. `kubectl rollout undo`<br>2. Исправить баг в коде / env |
| Поды нового RS в статусе `Pending`; rollout заблокирован | На bare-metal узлах исчерпан CPU/RAM под `maxSurge` поды | `kubectl describe pod -n <ns> -l app=<name>` (смотрим Events: `FailedScheduling`) | 1. Снизить `maxSurge: 0, maxUnavailable: 1`<br>2. Очистить ресурсы узлов |
| `rollout undo` возвращает `unable to rollback to specified revision` | Целевой `ReplicaSet` удален сборщиком мусора из-за `revisionHistoryLimit` | `kubectl get rs -n <ns> -l app=<name>` | Извлечь прошлый манифест из Git и выполнить `kubectl apply` |
| Изменения применились через `kubectl apply`, но ничего не происходит | Объект забыли снять с паузы (`spec.paused: true`) | `kubectl get deploy <name> -o jsonpath='{.spec.paused}'` | `kubectl rollout resume deployment/<name>` |
| Клиенты ловят 502 ошибки во время обычного RollingUpdate | Отсутствует `preStop sleep`; kubelet убивает под до обновления iptables/IPVS | `kubectl get events`<br>Логи Ingress: `connect() failed (111: Connection refused)` | Добавить `lifecycle.preStop.exec.command: ["sleep", "10"]` |
| Поды застряли в `Ready 0/1`; старый RS не масштабируется вниз | `readinessProbe` возвращает 5xx или порт недоступен | `kubectl describe pod <pod-name>` (событие `Unhealthy`) | Проверить здоровье эндпоинта `/readyz` внутри пода через `curl` |
| Масштабирование через `kubectl scale` мгновенно сбрасывается | Конфликт с контроллером Horizontal Pod Autoscaler (HPA) | `kubectl get hpa -n <ns>` | Изменять `minReplicas`/`maxReplicas` в манифесте HPA, а не в Deployment |

---

### Анализ условий развертывания (Deployment Conditions)

Состояние объекта Deployment определяется тремя ключевыми условиями в секции `status.conditions`:

1. **`type: Progressing`**:
   - `status: "True"`, `reason: NewReplicaSetAvailable` — процесс идет успешно или завершен.
   - `status: "False"`, `reason: ProgressDeadlineExceeded` — время ожидания превысило `progressDeadlineSeconds`. Контроллер **не предпринимает дальнейших шагов** по ротации, но продолжает попытки согласования.
   - `status: "Unknown"`, `reason: DeploymentPaused` — Deployment находится на паузе.
2. **`type: Available`**:
   - `status: "True"`, `reason: MinimumReplicasAvailable` — количество доступных подов удовлетворяет требованиям.
   - `status: "False"`, `reason: MinimumReplicasUnavailable` — доступных подов меньше, чем `spec.replicas - maxUnavailable`.
3. **`type: ReplicaFailure`**:
   - Появляется при невозможности создать поды на уровне ReplicaSet (превышение квоты `ResourceQuota`, отсутствие прав ServiceAccount, ошибки Admission Webhook).

Команда для мгновенного извлечения условий:
```bash
kubectl get deployment order-service -n production -o jsonpath='{range .status.conditions[*]}{.type}{"\t"}{.status}{"\t"}{.reason}{"\t"}{.message}{"\n"}{end}'
# → Available       True    MinimumReplicasAvailable    Deployment has minimum availability.
# → Progressing     True    NewReplicaSetAvailable      ReplicaSet "order-service-7f8d6c" has successfully progressed.
```

---

## 6. Лучшие практики (Best Practices)

1. **Строгая неизменяемость тегов образов:**
   - Категорически запрещено использовать теги `:latest`, `:master` или ветки.
   - Используйте семантическое версионирование (`:v2.14.0`) или хеш коммита (`:git-4a8b1c3`). При использовании мутабельных тегов контроллер не сможет обнаружить изменение в `spec.template`, `pod-template-hash` не изменится, и история ревизий утратит возможность детерминированного отката.
2. **Обязательное документирование ревизий:**
   - Всегда сопровождайте выкатки аннотацией `kubernetes.io/change-cause`. Без описания причин диагностика в `kubectl rollout history` во время аварии становится неэффективной.
3. **Безопасная конфигурация RollingUpdate для High-Load:**
   - Для критичных API задавайте `maxUnavailable: 0` и `maxSurge: 1` (или 25%). Это гарантирует 100% сохранение вычислительной мощности во время релиза.
   - Всегда проверяйте наличие запаса по CPU и памяти на узлах bare-metal кластера для размещения дополнительных surge-подов.
4. **Защитный интервал стабилизации (`minReadySeconds`):**
   - Устанавливайте `minReadySeconds: 15..30` для сервисов общего профиля и `30..60` для сервисов с отложенным прогревом JVM/кешей. Это заставляет контроллер выждать указанное время после перехода пода в статус `Ready`, прежде чем признать его `Available` и убить старую реплику.
5. **Таймауты в CI/CD пайплайнах:**
   - Любая автоматизация выкатки обязана содержать явный таймаут: `kubectl rollout status --timeout=5m`. Запуск без флага `--timeout` блокирует runner на неограниченное время при зависшем релизе.
6. **Оптимизация глубины истории ревизий:**
   - Задавайте `spec.revisionHistoryLimit: 3..5` вместо дефолтных 10. Десятки неактивных `ReplicaSet` создают паразитное число неиспользуемых объектов в `etcd` и замедляют листинг ресурсов контроллером.
7. **Координация Graceful Shutdown:**
   - Внедряйте связку `lifecycle.preStop: sleep 10` и `terminationGracePeriodSeconds: 30..60` для устранения 502 ошибок на стыке сетевой перемаршрутизации `EndpointSlice`.
8. **Разделение выкатки кода и миграций базы данных:**
   - Никогда не запускайте тяжелые DDL-миграции базы данных внутри контейнеров Deployment при старте. Используйте паттерн [Expand-Contract](../../../Databases/Concepts/migrations/expand_contract.md) и отдельные объекты `Job`.

---

## 7. Дополнительная информация

### Ограничения и граничные случаи (Edge Cases)

1. **Взаимодействие с Horizontal Pod Autoscaler (HPA):**
   - Если Deployment управляется HPA, манифест в Git и команды оператора не должны жестко фиксировать `spec.replicas`. При конфликте HPA перезапишет ручные изменения. Во время RollingUpdate HPA вычисляет нагрузку по фактически готовым подам, что может вызвать внезапный всплеск масштабирования.
2. **Server-Side Apply (SSA) и конфликты Field Management:**
   - Если Deployment управляется декларативным CI/CD пайплайном через Server-Side Apply (`kubectl apply --server-side`), выполнение императивной команды `kubectl rollout undo` приведет к конфликту владения полями (`FieldManager conflict`). Для корректного разрешения GitOps-пайплайн должен использовать декларативный откат через `git revert`.
3. **Мутирующие вебхуки (Mutating Admission Webhooks):**
   - Если в кластере установлен сторонний admission-вебхук, модифицирующий аннотации или переменные пода «на лету», хеш шаблона (`pod-template-hash`) может рассчитываться до мутации. Убедитесь, что вебхуки идемпотентны и не вызывают бесконечной перегенерации ревизий.
4. **Невосстановимость ревизий при лимите 0:**
   - При `revisionHistoryLimit: 0` старые ReplicaSet удаляются сразу после сворачивания в 0. Команда `kubectl rollout undo` завершается с фатальной ошибкой `error: no rollout history found`.
5. **No-Op Rollback:**
   - Если шаблон целевой ревизии побайтово идентичен текущему шаблону (например, вы попытались откатиться к ревизии с тем же образом и env), контроллер игнорирует команду — создание новой ревизии не инициируется, поды не пересоздаются.

---

### См. также

- [Манифест и лучшие практики Deployment](./deployment_manifest.md) — детальный разбор всех полей спецификации, QoS и конфигураций.
- [Устранение неполадок Deployment и RollingUpdate](./troubleshooting.md) — углубленный траблшутинг зависаний, сбоев планировщика и циклических падений.
- [Продвинутые стратегии отката Deployment](./advanced_rollback_strategies.md) — стратегии автоматического отката по метрикам, канареечные схемы и работа с БД.
- [Мониторинг и наблюдаемость Deployment](./deployment_monitoring_observability.md) — метрики Prometheus, Alertmanager-правила и Grafana дашборды.
- [Контроллер ReplicaSet](../replicaset.md) — устройство и жизненный цикл базового контроллера репликации.
- [Пробы жизнедеятельности в Kubernetes](../probes.md) — настройка Startup, Liveness и Readiness проб.
- [Жизненный цикл и состояния Pod](../Pod/pod_lifecycle_and_state.md) — фазы пода, Graceful Shutdown и сигналы завершения.
- [Перезапуск подов в Kubernetes](../Pod/pod_restarts.md) — сравнение сценариев `rollout restart`, удаления подов и сбоев контейнеров.
- [Обновление и rollout ConfigMap](../ConfigMap/update_and_rollout.md) — стратегии обновления конфигураций без простоев.