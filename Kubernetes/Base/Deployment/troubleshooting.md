# Устранение неполадок Deployment и RollingUpdate

**Актуально для:** Kubernetes 1.30–1.32+

Руководство для инженеров DevOps, SRE и системных администраторов по диагностике и решению проблем, возникающих при развертывании и обновлении stateless-приложений в Kubernetes: теория механики зависаний, системный алгоритм поиска причины, матрица сбоев и экстренные процедуры восстановления. Фокус на on-premise и bare-metal инфраструктуре без использования облачных абстракций.

## Предварительные требования (Prerequisites)

- **Рабочий кластер Kubernetes:** версии 1.30–1.32+ (на базе `kubeadm`, RKE2 или K3s на bare-metal или локальных виртуальных машинах). Стабильная группа API `apps/v1`.
- **Утилиты командной строки и права доступа:**
  - `kubectl` актуальной версии (совпадающей с версией кластера ±1 minor). Команда `kubectl events` доступна штатно (начиная с v1.24 заменила `kubectl alpha events`).
  - Минимальный набор RBAC-прав: чтение и управление объектами `deployments`, `replicasets`, `pods`, чтение `events`, `resourcequotas`, `limitranges`, `poddisruptionbudgets` и выполнение `kubectl auth can-i`.
- **Системный доступ к узлам (для bare-metal SRE):**
  - Доступ по SSH к worker-нодам кластера с правами `sudo`.
  - Утилиты рантайма и ОС: `crictl`, `journalctl -u kubelet`, `dmesg`, `conntrack`.
- **Вспомогательные инструменты:**
  - `jq` (версии 1.6+) и `curl` для парсинга ответов API и проверки сетевой доступности из подов.
- **Базовые знания архитектуры:**
  - Понимание иерархии абстракций: [Deployment: Обзор](./index.md), [ReplicaSet](../replicaset.md), [Pod](../Pod/pod_overview.md).
  - Структура полей спецификации: [Манифест и лучшие практики](./deployment_manifest.md).
  - Механика сетевых проверок: [Пробы жизнедеятельности в Kubernetes](../probes.md).
  - Политики доступности: [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md).

---

## 1. Определения

- **Зависшее обновление (Stuck Rollout)** — состояние объекта Deployment, при котором процесс перехода на новую версию (RollingUpdate) останавливается и не завершается в течение времени, заданного в `progressDeadlineSeconds`.
- **ProgressDeadlineExceeded** — условие (`Condition`) в статусе Deployment (`type: Progressing`, `status: "False"`, `reason: ProgressDeadlineExceeded`), сигнализирующее о том, что контроллер не смог завершить обновление в отведенный лимит времени.
- **ReplicaFailure** — условие в статусе Deployment (`type: ReplicaFailure`, `status: "True"`), сигнализирующее о невозможности создания или запуска подов контроллером ReplicaSet (например, из-за нехватки прав RBAC, исчерпания ResourceQuota или недопустимой конфигурации).
- **observedGeneration** — целое число (`status.observedGeneration`), отражающее последнее значение `metadata.generation`, которое контроллер Deployment успел прочитать и обработать. Если `status.observedGeneration < metadata.generation`, контроллер еще не обработал последнее изменение спецификации — обновление технически не началось.
- **Каскадный отказ (Cascading Failure)** — цепная реакция деградации, при которой сбой одного компонента (например, недоступность ConfigMap, ошибка миграции БД или дефицит ресурсов при surge) вызывает массовые падения подов и блокировку всего процесса развертывания.
- **Зависший под в Terminating (Terminating Pod Deadlock)** — состояние, когда под помечен на удаление (`metadata.deletionTimestamp` установлен), но процесс удаления не завершается в течение `terminationGracePeriodSeconds` (типичные причины: зависший хук `preStop`, неснятый `finalizer`, зависший или сетевой изолированный kubelet). Зависшие поды блокируют масштабирование вниз старого ReplicaSet и завершение rollout.
- **Deployment Controller Reconcile Loop** — бесконечный цикл согласования в составе `kube-controller-manager`, непрерывно сравнивающий желаемое состояние (`spec`) с фактическим (`status`) и управляющий дочерними объектами ReplicaSet.
- **Откат вперед (Rollout Undo / Forward Recovery)** — механика возврата к стабильной версии в Kubernetes: контроллер не удаляет исторические записи и не перематывает ревизии назад, а создает новую ревизию с шаблоном пода (`spec.template`), скопированным из выбранного целевого ReplicaSet.

---

## 2. Базовые концепции и архитектура сбоев

### Зависшее обновление как механизм защиты

Зависшее обновление в Kubernetes — это **механизм защиты**, а не фатальный сбой платформы. Контроллер Deployment намеренно останавливает продвижение процесса ротации, если поды новой ревизии не проходят проверки готовности (`readinessProbe`) или завершаются аварийно. 

Благодаря этому предотвращается полная деградация сервиса («выжигание» рабочей нагрузки): старые, стабильно работающие поды продолжают обслуживать входящий трафик до тех пор, пока новые реплики не подтвердят свою работоспособность.

```text
               Deployment (spec.replicas: 3, maxUnavailable: 0, maxSurge: 1)
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
   ReplicaSet (New: rev 2)                             ReplicaSet (Old: rev 1)
   Desired: 1, Current: 1, Ready: 0                    Desired: 3, Current: 3, Ready: 3
            │                                                   │
     [ Pod (rev 2) ]                                     [ 3x Pod (rev 1) ]
  (CrashLoop / Ready 0/1)                                 (Трафик идет сюда)
            │
  ⛔ Rollout ЗАВИС: контроллер ждет Ready-статуса от нового пода
     Старые поды НЕ удаляются благодаря maxUnavailable: 0
```

### Контроллер не откатывает сам: логика Reconcile Loop

После истечения лимита времени `progressDeadlineSeconds` контроллер Deployment **не выполняет автоматический откат** и **не прекращает** попытки достичь желаемого состояния. 

1. Контроллер переводит условие в блоке `status.conditions`:
   - `type: Progressing`
   - `status: "False"`
   - `reason: ProgressDeadlineExceeded`
   - `message: ReplicaSet "<new-rs-name>" has timed out progressing.`
2. Контроллер продолжает регулярные циклы согласования (Reconcile Loop). Если причина сбоя устранена во внешнем окружении (например, освобождены ресурсы узла, создан недостающий Secret или поднялась БД), rollout возобновится и условие `Progressing` вернется в `True`.
3. Kubernetes сам по себе не вмешивается в конфигурацию приложения. Восстановление стабильности при неудачном релизе требует **внешнего действия**:
   - Вмешательство дежурного инженера (ручной откат `kubectl rollout undo` или исправление манифеста).
   - Автоматический триггер в CI/CD (команда `kubectl rollout status --timeout=...`, возвращающая ненулевой код выхода и запускающая шаг отката).

### Иерархия уровней диагностики

Диагностику проблем с Deployment следует проводить строго по уровням — от верхнеуровневого симптома к первопричине на уровне инфраструктуры:

1. **Уровень 1 — Симптом:** Команда `kubectl rollout status` блокируется или возвращает ошибку таймаута; клиенты видят деградацию или старую версию.
2. **Уровень 2 — Conditions и Generation:** Анализ `status.conditions` и сравнение `metadata.generation` с `status.observedGeneration`.
3. **Уровень 3 — ReplicaSet:** Проверка распределения реплик (`Desired`, `Current`, `Ready`) между старыми и новым ReplicaSet; изучение событий ReplicaSet (`FailedCreate`).
4. **Уровень 4 — Pod:** Глубокий анализ подов проблемной ревизии: фазы (`Pending`, `Running`, `CrashLoopBackOff`), события пода, логи основного и init-контейнеров, коды завершения (exit codes).
5. **Уровень 5 — Инфраструктура (Node, CRI, OS):** Анализ ресурсов узла (CPU/RAM/диск), квот namespace, сетевых политик, работы Kubelet и рантайма containerd/CRI-O.

### Три режима зависания (Точка отказа)

Перед началом детального поиска первопричины необходимо локализовать фазу, на которой заблокирован процесс обновления:

| Режим | Признак | Типовая первопричина | Что проверить в первую очередь |
| :--- | :--- | :--- | :--- |
| **A. Обновление не началось** | `rollout status` сообщает: «Waiting for deployment spec update to be observed...»; **новый RS не создается** | `observedGeneration < generation` (контроллер не обработал спецификацию), `spec.paused: true`, изменение вне `spec.template` | Поля `generation`, флаг `paused`, события controller-manager |
| **B. Новые поды не становятся Ready** | Новый RS создан, но `CURRENT > READY`; поды в статусах `Pending`, `ImagePullBackOff`, `CrashLoopBackOff`, `Ready 0/1` | Ошибки приложения, падение `readinessProbe`, отсутствие ConfigMap/Secret, дефицит CPU/RAM, Taints узлов | Поды нового RS, логи контейнеров, события пода |
| **C. Старые поды не удаляются** | Новый RS достиг целевого числа `READY`, но старый RS не масштабируется вниз (`DESIRED > 0`) | Поды старого RS застряли в `Terminating` (бесконечный `preStop`, висящий finalizer, отказ Kubelet на узле) | Поды со статусом `Terminating`, события `FailedKillPod`, статус узлов |

### Параметры спецификации, влияющие на процесс обновления

| Параметр | Значение по умолчанию | Роль при сбое | Критическая ситуация в продакшне |
| :--- | :--- | :--- | :--- |
| **`spec.strategy.rollingUpdate.maxUnavailable`** | `25%` | Определяет максимальное число реплик, которые могут быть недоступны в процессе ротации. | При значении `0` контроллер не удалит ни одного старого пода, пока новый не перейдет в статус `Ready`. Если в кластере нет свободных ресурсов под surge, rollout зависнет намертво. |
| **`spec.strategy.rollingUpdate.maxSurge`** | `25%` | Определяет максимальное число дополнительных реплик сверх желаемого `replicas`. | Высокое значение ускоряет выкатку, но создает резкий всплеск нагрузки на CPU/RAM узлов и может превысить лимиты `ResourceQuota`, вызвав отказ создания подов. |
| **`spec.minReadySeconds`** | `0` | Минимальное время в секундах, в течение которого новый под должен оставаться готовым (Ready) без падений, чтобы контроллер признал его доступным (`Available`). | Позволяет выявлять отложенные падения (например, утечки памяти при старте, ошибки прогрева кэша). Замедляет выкатку пропорционально числу шагов. |
| **`spec.progressDeadlineSeconds`** | `600` (10 мин) | Максимальное время ожидания прогресса обновления перед выставлением признака ошибки. | Если значение меньше или равно `minReadySeconds`, условие ошибки сработает мгновенно при старте. Должно покрывать время вытягивания образов и прогрева приложения. |

### Условия (Conditions) в статусе Deployment

Блок `status.conditions` объекта Deployment содержит три ключевых типа условий. Каждое условие включает поля `type`, `status` (`True`/`False`/`Unknown`), `reason` (машиночитаемый код) и `message` (описание).

| Тип условия | Значение `status` | Интерпретация | Типовые `reason` |
| :--- | :--- | :--- | :--- |
| **`Available`** | `True` | Минимально необходимое число реплик приложения готово и обслуживает запросы. | `MinimumReplicasAvailable` |
| | `False` | Число доступных реплик ниже допустимого минимума (приложение частично или полностью недоступно). | `MinimumReplicasUnavailable` |
| **`Progressing`** | `True` | Контроллер успешно выполняет обновление или успешно завершил его. | `NewReplicaSetAvailable`, `ReplicaSetUpdated` |
| | `False` | Процесс обновления заблокирован и превысил отведенный дедлайн. | `ProgressDeadlineExceeded`, `TimedOutReplicaSet` |
| | `Unknown` / `Paused` | Обновление приостановлено оператором. | `DeploymentPaused` |
| **`ReplicaFailure`** | `True` | Контроллер ReplicaSet столкнулся с ошибкой при попытке создать или удалить поды. | `FailedCreate`, `FailedScheduling` |

**Диагностическая матрица условий:**
- `Available=True` + `Progressing=False` (`ProgressDeadlineExceeded`): Старая версия приложения продолжает штатно работать и обслуживать клиентов, но выкатка новой версии зависла. Безопасная ситуация для SLA, требующая планового вмешательства.
- `Available=False` + `Progressing=False` (`ProgressDeadlineExceeded`): Авария (Outage). Старые поды были частично или полностью удалены (при `maxUnavailable > 0`), а новые не смогли запуститься. Требуется немедленный откат.

### Взаимодействие с PodDisruptionBudget (PDB) на on-premise

`PodDisruptionBudget` (PDB) и параметр `maxUnavailable` в Deployment контролируют доступность реплик, но работают на разных уровнях:

- **Deployment `maxUnavailable`**: контролирует плановую ротацию подов, инициированную самим контроллером Deployment. Контроллер сам решает, когда удалить старый под в рамках стратегии RollingUpdate, и **не обращается** к PDB API.
- **PodDisruptionBudget**: ограничивает **добровольное вытеснение (Voluntary Eviction)**, выполняемое через API вытеснения (`/v1/pods/eviction`), например при выполнении `kubectl drain <node>`.

**Механика взаимной блокировки (Deadlock):**
Сам по себе PDB не блокирует штатный rollout. Конфликт возникает, когда системный администратор выполняет обслуживание узла (`kubectl drain`) **одновременно** с процессом RollingUpdate:
1. PDB требует, чтобы минимум 3 из 4 реплик оставались доступными (`minAvailable: 3`).
2. В процессе RollingUpdate одна реплика обновляется и еще не стала `Ready`.
3. Команда `kubectl drain` пытается вытеснить старый под с обслуживаемого узла, но API-сервер отклоняет запрос с ошибкой `Cannot evict pod as it would violate the pod's disruption budget`.
4. В результате дренаж узла зависает, узел переходит в статус `SchedulingDisabled`, а новые поды не могут разместиться из-за дефицита емкости.

---

## 3. Практические сценарии диагностики и аварийного восстановления

### Системный пошаговый алгоритм диагностики (Rollout Stuck)

Если команда `kubectl rollout status deployment/<name>` заблокирована или завершилась с ошибкой, выполните последовательную диагностику по шагам.

#### Шаг 0: Локализовать режим зависания

Определите, на каком этапе (A, B или C) остановился процесс:

```bash
# Проверка фиксации поколения спецификации контроллером
kubectl get deploy <name> -n <namespace> -o jsonpath='observedGeneration={.status.observedGeneration} generation={.metadata.generation}{"\n"}'
# → observedGeneration=3 generation=3

# Проверка флага паузы
kubectl get deploy <name> -n <namespace> -o jsonpath='paused={.spec.paused}{"\n"}'
# → paused=false

# Проверка списка ReplicaSet по селектору приложения
kubectl get rs -n <namespace> -l app=<app-label> --sort-by='.metadata.creationTimestamp'
# → NAME                 DESIRED   CURRENT   READY   AGE
# → my-app-7d6b9f4b9c   0         0         0       5d
# → my-app-58f8b88df8   3         3         3       1d
# → my-app-6c589b4f77   1         1         0       4m  ← Новая ревизия
```

**Анализ результата:**
- Если `observedGeneration < generation` или `paused=true` → **Режим A** (обновление не запущено).
- Если новый RS создан, но `READY < CURRENT` → **Режим B** (поды новой ревизии не готовы).
- Если новый RS имеет `READY == DESIRED`, но старый RS сохраняет `DESIRED > 0` и поды висят в `Terminating` → **Режим C** (зависание сворачивания старых подов).

#### Шаг 1: Инспекция объекта Deployment и условий

Проверьте статус условий и сводку событий контроллера:

```bash
# Детальный статус Deployment
kubectl describe deployment <name> -n <namespace>
# → Conditions:
# →   Type           Status  Reason
# →   ----           ------  ------
# →   Available      True    MinimumReplicasAvailable
# →   Progressing    False   ProgressDeadlineExceeded

# Извлечение машиночитаемых условий через JSONPath
kubectl get deploy <name> -n <namespace> -o jsonpath='{range .status.conditions[*]}{.type}={.status} reason={.reason} msg="{.message}"{"\n"}{end}'
# → Available=True reason=MinimumReplicasAvailable msg="Deployment has minimum availability."
# → Progressing=False reason=ProgressDeadlineExceeded msg="ReplicaSet \"my-app-6c589b4f77\" has timed out progressing."
```

#### Шаг 2: Анализ дочерних ReplicaSet

Определите имя проблемного ReplicaSet и проверьте события контроллера ReplicaSet:

```bash
# Получение событий целевого ReplicaSet
kubectl describe rs <new-rs-name> -n <namespace>
# → Events:
# →   Type     Reason        Age    From                   Message
# →   ----     ------        ----   ----                   -------
# →   Normal   SuccessfulCreate  4m   replicaset-controller  Created pod: my-app-6c589b4f77-x9k2p
# →   Warning  FailedCreate      2m   replicaset-controller  Error creating: pods "my-app-6c589b4f77-z4m1q" is forbidden: exceeded quota: default-quota
```

Если обнаружено событие `FailedCreate`, проблема кроется на уровне Admission Webhook, ResourceQuota или прав ServiceAccount.

#### Шаг 3: Глубокая диагностика подов новой ревизии

Получите список подов нового ReplicaSet и изучите их жизненный цикл:

```bash
# Список подов с выводом узлов и IP
kubectl get pods -n <namespace> -l app=<app-label> -o wide
# → NAME                       READY   STATUS             RESTARTS   NODE      IP
# → my-app-58f8b88df8-2b8zq   1/1     Running            0          node-02   10.244.2.14
# → my-app-58f8b88df8-m9k1l   1/1     Running            0          node-03   10.244.3.22
# → my-app-6c589b4f77-x9k2p   0/1     CrashLoopBackOff   4          node-01   10.244.1.88

# Детальная инспекция пода (состояния контейнеров, exit codes, монтирование)
kubectl describe pod <new-pod-name> -n <namespace>

# Логи текущего запуска контейнера
kubectl logs <new-pod-name> -n <namespace> --tail=100

# Логи предыдущего аварийно завершившегося запуска
kubectl logs <new-pod-name> -n <namespace> --previous --tail=100

# Логи init-контейнера (если под застрял в Init:CrashLoopBackOff или Init:Error)
kubectl logs <new-pod-name> -n <namespace> -c <init-container-name>
```

#### Шаг 4: Анализ системных событий кластера

Отфильтруйте события, связанные с подом, неймспейсом и контроллерами:

```bash
# События для конкретного пода (kubectl >= 1.24)
kubectl events -n <namespace> --for pod/<new-pod-name>
# → LAST SEEN   TYPE      REASON      OBJECT                              MESSAGE
# → 2m          Warning   Unhealthy   Pod/my-app-6c589b4f77-x9k2p        Readiness probe failed: HTTP probe failed with statuscode: 503

# Последние события namespace, отсортированные по времени
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | tail -25

# Поиск критических предупреждений по признакам планирования и монтирования
kubectl get events -n <namespace> --field-selector type=Warning
```

#### Шаг 5: Проверка ресурсов и инфраструктуры узла на Bare-Metal

Если поды находятся в фазе `Pending` или падают с кодом 137 (`OOMKilled`), проверьте ресурсы кластера и состояние узла:

```bash
# Проверка расхода ResourceQuota в namespace
kubectl describe quota -n <namespace>
# → Resource     Used   Hard
# → requests.cpu 7900m  8000m  ← Исчерпание квоты процессора

# Анализ нагрузки на узлы
kubectl top nodes
# → NAME      CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → node-01   3820m        95%    28900Mi         90%

# Проверка условий узла (DiskPressure, MemoryPressure, PIDPressure)
kubectl describe node <node-name> | grep -A6 "Conditions:"

# Диагностика на самом узле через SSH (уровень рантайма containerd)
crictl ps -a --name <container-name>
# → CONTAINER     IMAGE          CREATED         STATE     NAME         ATTEMPT
# → b4f8a129d10e  my-image:v2    10 seconds ago  Exited    app-server   5

# Проверка системного лога Kubelet на узле
sudo journalctl -u kubelet --no-pager -n 50 | grep -E 'Failed|Error|OOM'
```

---

### Специфические проблемы и методы их устранения

#### 1. Дедлок зондов доступности (Readiness / Startup Probe)

Самая распространенная причина зависания в **Режиме B**: контейнер переходит в статус `Running`, но порт приложения не готов вовремя отвечать на запросы проверки, под остается `Ready 0/1`, и контроллер Deployment блокирует запуск следующих реплик.

**Математика окна проверки:**
Максимальное время, отведенное приложению на успешный старт до фиксации отказа:
```text
T_start = initialDelaySeconds + (failureThreshold - 1) * periodSeconds
```
Если приложению на прогрев пула соединений с БД или загрузку кэша требуется 45 секунд, а в манифесте задано `initialDelaySeconds: 5`, `periodSeconds: 5`, `failureThreshold: 3` (окно = 5 + 2 * 5 = 15 секунд), под будет циклически признаваться нездоровым.

**Диагностика:**
```bash
kubectl describe pod <new-pod-name> -n <namespace> | grep -A8 "Readiness:"
# → Readiness: exec [curl -f http://localhost:8080/healthz] delay=5s timeout=2s period=5s #success=1 #failure=3
# → Events:
# →   Warning  Unhealthy  1m (x8 over 2m)  kubelet  Readiness probe failed: HTTP probe failed with statuscode: 503
```

**Решение:**
1. Разделите проверки инициализации и рабочей готовности: внедрите `startupProbe` для приложений с медленным стартом.
2. Во время работы `startupProbe` проверки `readinessProbe` и `livenessProbe` отключены и не инициируют перезапуски:

```yaml
startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  failureThreshold: 30
  periodSeconds: 5   # Дает приложению до 150 секунд на инициализацию
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  periodSeconds: 5
  failureThreshold: 2
```

#### 2. Ошибки монтирования томов и конфигураций (CreateContainerConfigError / FailedMount)

Если новая ревизия Deployment ссылается на ConfigMap или Secret, который отсутствует в кластере или содержит недопустимые ключи:

```bash
# Диагностика статуса подов
kubectl get pods -n <namespace> -l app=<app-label>
# → NAME                       READY   STATUS                         RESTARTS   AGE
# → my-app-6c589b4f77-x9k2p   0/1     CreateContainerConfigError     0          2m

# Поиск конкретного отсутствующего ресурса в событиях
kubectl describe pod <new-pod-name> -n <namespace> | grep -A5 "Events:"
# → Warning  FailedMount  1m  kubelet  configmap "app-config-v2" not found
```

**Нюансы валидации имен ключей:**
- Переменные окружения (`envFrom.configMapRef`): ключи обязаны быть валидными C-идентификаторами (символы `[A-Za-z_][A-Za-z0-9_]*`). Ключи с точками или дефисами (например, `application.yaml`) не могут быть импортированы через `envFrom` и вызовут падение контейнера.
- Тома (`volumes.configMap`): имя ключа становится именем файла на диске. Здесь точки разрешены, но запрещены ведущие точки или разделители путей.

**Решение:**
```bash
# Проверить наличие требуемого ConfigMap/Secret в целевом namespace
kubectl get configmap,secret -n <namespace>

# Применить недостающий ConfigMap перед продолжением rollout
kubectl apply -f configmap-v2.yaml -n <namespace>
```

#### 3. Ошибки доступа RBAC и ServiceAccount

Если новые реплики при старте обращаются к API-серверу Kubernetes (например, для чтения CRD, синхронизации секретов или координации кластера):

```bash
# Проверка привязанного ServiceAccount к поду
kubectl get pod <new-pod-name> -n <namespace> -o jsonpath='{.spec.serviceAccountName}{"\n"}'
# → app-service-account

# Проверка прав сервисного аккаунта через API авторизации
kubectl auth can-i get configmaps -n <namespace> --as=system:serviceaccount:<namespace>:app-service-account
# → no - User "system:serviceaccount:default:app-service-account" cannot get resource "configmaps"
```

**Решение:**
Создать недостающий `Role` и `RoleBinding` для предоставления необходимых полномочий сервисному аккаунту пода.

#### 4. Зависшие поды в статусе Terminating на Bare-Metal (Режим C)

Старый ReplicaSet не может уменьшить число реплик до `0`, потому что поды старой ревизии заблокированы в фазе удаления.

```bash
# Поиск зависших подов со временем удаления
kubectl get pods -n <namespace> -l app=<app-label> | grep Terminating
# → my-app-58f8b88df8-2b8zq   1/1   Terminating   0   14m

# Проверка финализаторов и времени начала удаления
kubectl get pod <terminating-pod> -n <namespace> -o jsonpath='deletionTimestamp={.metadata.deletionTimestamp} finalizers={.metadata.finalizers}{"\n"}'
# → deletionTimestamp=2026-10-13T16:40:12Z finalizers=["storage.example.com/cleanup-lock"]
```

**Первопричины и действия:**
1. **Бесконечный `preStop` hook:** Kubelet блокирует отправку `SIGTERM`, пока не завершится команда хука `preStop`. По истечении `spec.terminationGracePeriodSeconds` Kubelet отправляет принудительный `SIGKILL`. Если grace period задан равным 3600с, под будет висеть час.
   - *Решение:* Скорректировать `terminationGracePeriodSeconds` и длительность команды хука в шаблоне Deployment.
2. **Зависший Finalizer:** Внешний оператор или контроллер хранилища не снял блокировку удаления из `.metadata.finalizers`.
   - *Решение:* Убедиться, что процесс очистки завершен, и снять финализатор вручную:
     ```bash
     kubectl patch pod <terminating-pod> -n <namespace> -p '{"metadata":{"finalizers":[]}}' --type=merge
     ```
3. **Отказ узла (Node NotReady / Сетевой Partition на bare-metal):** Kubelet на узле отключен или потерял связь с Control Plane. Control Plane не может подтвердить удаление контейнера.
   - *ВНИМАНИЕ SRE:* Принудительное удаление `kubectl delete pod <name> --grace-period=0 --force` удаляет объект из etcd, но **не останавливает** реальный процесс на изолированном узле. Это может привести к состоянию Split-Brain (два экземпляра пишут в один том или базу данных). Выполняйте force delete только после физического отключения питания или изоляции проблемного сервера!

---

### Экстренные процедуры восстановления (SRE Runbooks)

#### Процедура 1: Экстренный откат к предыдущей ревизии (Rollout Undo)

При критическом сбое обновления самым быстрым способом восстановления доступности является откат.

```bash
# 1. Просмотр истории ревизий для определения стабильной версии
kubectl rollout history deployment/<name> -n <namespace>
# → REVISION  CHANGE-CAUSE
# → 2         Релиз 2.1.0 с миграцией схемы
# → 3         Релиз 2.2.0 (проблемный)

# 2. Предпросмотр изменений отката (dry-run на стороне сервера)
kubectl rollout undo deployment/<name> -n <namespace> --dry-run=server -o yaml | grep "image:"
# → image: my-registry.local/app:2.1.0

# 3. Выполнение отката к предыдущей версии
kubectl rollout undo deployment/<name> -n <namespace>
# → deployment.apps/my-app rolled back

# 4. Выполнение отката к явно указанной исторической ревизии
kubectl rollout undo deployment/<name> -n <namespace> --to-revision=2

# 5. Ожидание завершения восстановления
kubectl rollout status deployment/<name> -n <namespace> --timeout=3m
# → deployment "my-app" successfully rolled out
```

**Особенности механики отката:**
- Откат формирует **новую ревизию** (например, ревизию 4, идентичную по спецификации ревизии 2).
- Флага `rollout undo --force` не существует.
- Нельзя выполнить откат Deployment, находящегося в состоянии паузы (`spec.paused: true`). Сначала выполните `kubectl rollout resume`.

#### Процедура 2: Приостановка обновления (Rollout Pause) и Hotfix

Если необходимо остановить замену оставшихся реплик для анализа ситуации на проде без немедленного сброса уже обновленных подов:

```bash
# 1. Приостановить процесс ротации
kubectl rollout pause deployment/<name> -n <namespace>
# → deployment.apps/my-app paused

# 2. Внести исправление в конфигурацию (например, исправить переменную окружения)
kubectl set env deployment/<name> -n <namespace> DB_TIMEOUT=30s
# → deployment.apps/my-app env updated

# 3. Возобновить процесс развертывания
kubectl rollout resume deployment/<name> -n <namespace>
# → deployment.apps/my-app resumed
```

#### Процедура 3: Экстренная остановка рабочей нагрузки (Zero-Scale Drain)

Если дефектный релиз повреждает данные или вызывает лавину ошибок на зависимых системах:

```bash
# 1. Масштабировать Deployment в 0 реплик
kubectl scale deployment/<name> -n <namespace> --replicas=0
# → deployment.apps/my-app scaled

# 2. Дождаться полного завершения всех подов
kubectl wait --for=delete pod -l app=<app-label> -n <namespace> --timeout=2m
# → pod/my-app-6c589b4f77-x9k2p condition met

# 3. После устранения дефекта — вернуть расчетное число реплик
kubectl scale deployment/<name> -n <namespace> --replicas=5
```

---

### Разбор реальных инцидентов (Post-Mortem Cases)

#### Инцидент 1: Сбой миграции схемы базы данных в Init-контейнере

**Симптомы:**
Rollout завис на 1 новой реплике. Пользователи продолжают работать со старой версией, но релиз заблокирован. Новый под висит в статусе `Init:CrashLoopBackOff`.

**Диагностика:**
```bash
# 1. Проверка подов
kubectl get pods -n prod -l app=billing-api
# → NAME                           READY   STATUS                  RESTARTS   AGE
# → billing-api-58f8b88df8-v2k1m   1/1     Running                 0          12d
# → billing-api-7d9f5c4b6a-9m4lp   0/1     Init:CrashLoopBackOff   3          6m

# 2. Проверка логов init-контейнера миграций
kubectl logs billing-api-7d9f5c4b6a-9m4lp -n prod -c schema-migration
# → 2026-10-13 16:42:01 FATAL [db:migrate] relation "invoices_v2" already exists with conflicting schema
```

**Первопричина:**
Миграция базы данных выполнялась внутри `initContainers` каждого пода. При параллельном старте возник конфликт блокировок или попытка повторного наката миграции.

**Решение:**
1. Выполнять миграции схемы базы данных через отдельный атомарный объект `Job` в рамках CI/CD до старта обновления Deployment, а не внутри Pod template.
2. Откатить зависший Deployment:
   ```bash
   kubectl rollout undo deployment/billing-api -n prod
   ```

#### Инцидент 2: Исчерпание ResourceQuota из-за всплеска maxSurge

**Симптомы:**
При обновлении сервиса с 10 репликами процесс останавливается после создания 2 новых реплик. Команда `kubectl rollout status` блокируется.

**Диагностика:**
```bash
# 1. Проверка условий Deployment
kubectl describe deployment payment-gateway -n finance | grep -A5 "Conditions:"
# → Type: ReplicaFailure, Status: True, Reason: FailedCreate

# 2. Проверка событий ReplicaSet
kubectl describe rs payment-gateway-8f4b2c1d -n finance | grep "FailedCreate"
# → Warning  FailedCreate  2m  replicaset-controller  Error creating: pods "payment-gateway-8f4b2c1d-..." is forbidden: exceeded quota: finance-quota, requested: requests.cpu=2, used: requests.cpu=19, limited: requests.cpu=20

# 3. Проверка параметров стратегии
kubectl get deploy payment-gateway -n finance -o jsonpath='maxSurge={.spec.strategy.rollingUpdate.maxSurge} maxUnavailable={.spec.strategy.rollingUpdate.maxUnavailable}{"\n"}'
# → maxSurge=25% maxUnavailable=0
```

**Первопричина:**
При 10 репликах по 1 CPU каждая и `maxSurge: 25%` контроллер попытался создать 3 дополнительных пода (итого 13 CPU при лимите квоты в 20 CPU, но другие сервисы namespace уже занимали 9 CPU). Параметр `maxUnavailable: 0` запретил удалять старые поды до готовности новых. Возник тупик (deadlock).

**Решение:**
Скорректировать стратегию, разрешив временное уменьшение доступности старых реплик:
```bash
kubectl patch deployment payment-gateway -n finance --type='strategic' -p '{"spec":{"strategy":{"rollingUpdate":{"maxSurge":1,"maxUnavailable":1}}}}'
```

#### Инцидент 3: Дедлок готовности при холодном старте кэша

**Симптомы:**
Новые поды запускаются, переходят в `Running`, но падают каждые 40 секунд. Статус `Running (Ready 0/1)` сменяется на `CrashLoopBackOff`.

**Диагностика:**
```bash
# 1. Проверка проверок в описании пода
kubectl describe pod catalog-service-6d8b9f-x1z4 -n shop | grep -E 'Liveness:|Readiness:|Last State:'
# → Readiness: http-get http://:8080/healthz delay=10s timeout=2s period=5s #failure=3
# → Liveness:  http-get http://:8080/healthz delay=20s timeout=2s period=5s #failure=3
# → Last State: Terminated, Exit Code: 137, Reason: OOMKilled/Killed by liveness probe

# 2. Логи приложения
kubectl logs catalog-service-6d8b9f-x1z4 -n shop --previous | tail -20
# → [Warmup] Loading product graph into memory... 65% completed
# → Received SIGKILL from Kubelet
```

**Первопричина:**
`livenessProbe` начала проверять здоровье приложения через 20 секунд после старта. Приложение выполняло прогрев локального кэша в течение 60 секунд и не отвечало на HTTP-запросы. Kubelet принудительно убил контейнер по таймауту Liveness-пробы.

**Решение:**
Внедрить `startupProbe` с достаточным запасом времени (`failureThreshold: 24`, `periodSeconds: 5` = 120 секунд), чтобы защитить контейнер от преждевременного завершения liveness-пробой:
```bash
kubectl patch deployment catalog-service -n shop --type='json' -p '[{"op":"add","path":"/spec/template/spec/containers/0/startupProbe","value":{"httpGet":{"path":"/healthz","port":8080},"failureThreshold":24,"periodSeconds":5}}]'
```

---

## 4. Операции и команды диагностики

### Справочная таблица основных команд диагностики

| Задача диагностики | Команда `kubectl` | Ожидаемый результат / Вывод |
| :--- | :--- | :--- |
| **Проверка статуса с таймаутом** | `kubectl rollout status deployment/<name> -n <ns> --timeout=60s` | `# → deployment "my-app" successfully rolled out` или `# → error: deployment "my-app" exceeded its progress deadline` |
| **Проверка поколения** | `kubectl get deploy <name> -n <ns> -o jsonpath='{.status.observedGeneration}/{.metadata.generation}{"\n"}'` | `# → 4/4` (синхронизировано) или `# → 3/4` (контроллер отстает) |
| **Анализ условий** | `kubectl get deploy <name> -n <ns> -o jsonpath='{range .status.conditions[*]}{.type}={.status} ({.reason}){"\n"}{end}'` | `# → Progressing=False (ProgressDeadlineExceeded)` |
| **История ревизий** | `kubectl rollout history deployment/<name> -n <ns>` | `# → REVISION  CHANGE-CAUSE`<br>`# → 1         v1.0.0`<br>`# → 2         v1.1.0` |
| **Детали ревизии** | `kubectl rollout history deployment/<name> -n <ns> --revision=2` | `# → Pod Template: ... Containers: ... Image: ...` |
| **Сверка реплик RS** | `kubectl get rs -n <ns> -l app=<label>` | `# → NAME         DESIRED  CURRENT  READY`<br>`# → app-v1     3        3        3` |
| **Поиск нездоровых подов** | `kubectl get pods -n <ns> -l app=<label> --field-selector status.phase!=Running` | `# → NAME         READY   STATUS   RESTARTS`<br>`# → app-v2-xyz   0/1     Pending  0` |
| **Просмотр событий пода** | `kubectl events -n <ns> --for pod/<pod-name>` | `# → Warning  FailedScheduling  pod/app-v2  Insufficient cpu` |
| **Логи упавшего пода** | `kubectl logs <pod-name> -n <ns> --previous --tail=50` | `# → panic: runtime error: invalid memory address` |
| **Перезапуск выкатки** | `kubectl rollout restart deployment/<name> -n <ns>` | `# → deployment.apps/my-app restarted` |
| **Приостановка выкатки** | `kubectl rollout pause deployment/<name> -n <ns>` | `# → deployment.apps/my-app paused` |
| **Возобновление выкатки** | `kubectl rollout resume deployment/<name> -n <ns>` | `# → deployment.apps/my-app resumed` |
| **Откат к предыдущей версии**| `kubectl rollout undo deployment/<name> -n <ns>` | `# → deployment.apps/my-app rolled back` |

### Экспресс-команды JSONPath и jq для оператора и CI/CD

```bash
# Получить имя нового (активного) ReplicaSet
TARGET_RS=$(kubectl get deploy <name> -n <ns> -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}' | xargs -I {} kubectl get rs -n <ns> -l app=<label> -o json | jq -r --arg rev "{}" '.items[] | select(.metadata.annotations["deployment.kubernetes.io/revision"]==$rev) | .metadata.name')
echo "Target RS: ${TARGET_RS}"
# → Target RS: my-app-6c589b4f77

# Получить список подов, находящихся в неготовности (NotReady)
kubectl get pods -n <ns> -l app=<label> -o json | jq -r '.items[] | select(.status.containerStatuses[]?.ready==false) | .metadata.name'
# → my-app-6c589b4f77-x9k2p

# Проверить наличие контейнеров с OOMKilled в namespace
kubectl get pods -n <ns> -o json | jq -r '.items[] | {name: .metadata.name, terminated: .status.containerStatuses[]?.lastState.terminated} | select(.terminated.reason=="OOMKilled")'
```

### Коды завершения контейнеров (Exit Codes) и действия SRE

При анализе поля `Last State -> Exit Code` в выводе `kubectl describe pod`:

| Exit Code | Сигнал / Описание | Первопричина | План действий SRE |
| :--- | :--- | :--- | :--- |
| **`0`** | Успешный выход | Процесс завершил работу штатно. Если это не Job, приложение завершилось преждевременно. | Проверить аргументы запуска (`command`/`args`) и фоновые демоны. |
| **`1`** | Ошибка приложения | Необработанное исключение, аварийный выход в коде (например, ошибка подключения к БД). | Читать логи `kubectl logs <pod> --previous`. |
| **`126`** | Permission Denied | Бинарный файл не имеет прав на исполнение (`chmod +x`), либо несовместима архитектура процессора (ARM vs x86_64). | Проверить права в Dockerfile и скомпилированную архитектуру бинарника. |
| **`127`** | Command Not Found | Указанный в `command` файл не существует внутри файловой системы контейнера (ошибка в `PATH`). | Проверить точку входа в манифесте и состав образа. |
| **`130`** | SIGINT (128 + 2) | Процесс прерван сигналом прерывания с клавиатуры или инициализирующим скриптом. | Проверить оберточные bash-скрипты внутри контейнера. |
| **`137`** | **SIGKILL (128 + 9)** | 1. **OOMKilled:** Процесс превысил лимит `limits.memory` и был убит ядром Linux.<br>2. Kubelet принудительно убил контейнер по истечении `terminationGracePeriodSeconds`. | 1. Изучить `kubectl describe pod` на наличие статуса `OOMKilled`. Увеличить `limits.memory`.<br>2. Проверить хук `preStop`. |
| **`143`** | **SIGTERM (128 + 15)** | Штатное завершение: Kubelet запросил остановку контейнера при плановой ротации подов. | Нормальное поведение старых реплик при RollingUpdate. |

---

## 5. Типичные ошибки и матрица устранения неисправностей

| Статус / Ошибка | Первопричина | Команда быстрой диагностики | Решение SRE |
| :--- | :--- | :--- | :--- |
| **`Pending`** | Нехватка CPU/памяти на узлах, Taints, селекторы `nodeSelector` или `affinity`. | `kubectl describe pod <pod> \| grep -A5 "Events:"` | Увеличить емкость узлов, уменьшить `requests`, скорректировать tolerations. См. [Pod Pending](../../Troubleshooting/Common_Errors/pod_pending/diagnostics.md). |
| **`ImagePullBackOff` / `ErrImagePull`** | Несуществующий тег образа, опечатка в URL реестра, отсутствие `imagePullSecrets`. | `kubectl describe pod <pod> \| grep -E 'Failed\|BackOff'` | Исправить тег в манифесте, проверить авторизацию в локальном реестре. См. [Ошибки образов](../../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md). |
| **`CrashLoopBackOff`** | Сбой конфигурации приложения, отсутствие обязательных переменных окружения, падение при старте. | `kubectl logs <pod> --previous` | Исправить код или переменные окружения. См. [CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md). |
| **`Init:CrashLoopBackOff`** | Падение вспомогательного init-контейнера (миграция БД, проверка зависимостей). | `kubectl logs <pod> -c <init-container> --previous` | Исправить скрипт миграции или восстановить сетевую доступность зависимого сервиса. |
| **`Running (Ready 0/1)`** | Приложение не проходит проверку `readinessProbe`. | `kubectl describe pod <pod> \| grep -A8 "Readiness:"` | Проверить порт, путь и таймауты проверки; добавить `startupProbe` для медленного старта. См. [Пробы](../probes.md). |
| **`OOMKilled`** | Превышение лимита оперативной памяти `resources.limits.memory`. | `kubectl describe pod <pod> \| grep -E 'OOMKilled\|Exit Code'` | Профиль потребления памяти приложения, увеличение `limits.memory`. См. [Анализ OOMKilled](../../Troubleshooting/Common_Errors/oomkilled_pods.md). |
| **`CreateContainerConfigError`** | Ссылка на несуществующий ConfigMap/Secret или некорректный ключ. | `kubectl get pods -n <ns> \| grep ConfigError` | Проверить наличие объекта: `kubectl get configmap,secret -n <ns>`. См. [ConfigError](../../Troubleshooting/Common_Errors/CreateContainerConfigError/definitions.md). |
| **`FailedScheduling`** | Ни один узел кластера не удовлетворяет требованиям размещения пода. | `kubectl events --for pod/<pod>` | Освободить ресурсы на узлах, проверить Taints/Affinity. |
| **`Evicted`** | Kubelet вытеснил под из-за дефицита дискового пространства или памяти на узле. | `kubectl describe node <node> \| grep -A5 "Conditions:"` | Очистить диск узла (`crictl rmi --prune`), проверить log rotation. |
| **`ReplicaFailure`** | ReplicaSet не может создать под из-за исчерпания ResourceQuota или отказа Admission Webhook. | `kubectl describe deploy <name> \| grep -A5 "Conditions:"` | Проверить квоты `kubectl describe quota -n <ns>` и логи Admission вебхуков. |
| **`Terminating` (зависший)** | Зависший хук `preStop`, неснятый finalizer, недоступность Kubelet на узле. | `kubectl get pod <pod> -o jsonpath='{.metadata.finalizers}'` | Снять зависший finalizer, проверить состояние узла и Kubelet. |

---

## 6. Мониторинг, алертинг и наблюдаемость

### Ключевые метрики для выявления зависших выкаток

Для проактивного обнаружения сбоев развертывания используются стандартные метрики экспортера `kube-state-metrics` (v2.10+) и метрики `kube-controller-manager`:

- `kube_deployment_status_condition{condition="Progressing", status="false", reason="ProgressDeadlineExceeded"}` — флаг зависшего обновления (значение `1` означает зафиксированный таймаут).
- `kube_deployment_status_replicas_unavailable` — число недоступных реплик Deployment в текущий момент.
- `kube_deployment_status_observed_generation` и `kube_deployment_metadata_generation` — рассинхронизация поколений спецификации (контроллер не обработал изменения).
- `kube_deployment_spec_replicas != kube_deployment_status_replicas_available` — несоответствие желаемого и фактического числа готовых реплик.

### Production PromQL правила алертинга

```yaml
groups:
  - name: deployment_troubleshooting_alerts
    rules:
      # Критический алерт: обновление зависло и превысило progressDeadlineSeconds
      - alert: DeploymentRolloutStuck
        expr: |
          kube_deployment_status_condition{condition="Progressing", status="false", reason="ProgressDeadlineExceeded"} == 1
        for: 2m
        labels:
          severity: critical
          tier: platform
        annotations:
          summary: "Deployment {{ $labels.namespace }}/{{ $labels.deployment }} завис при обновлении"
          description: "Контроллер Deployment зафиксировал условие ProgressDeadlineExceeded. Новые поды не могут стать доступными. Требуется вмешательство инженера или откат."

      # Предупреждение: рассинхронизация поколения спецификации и статуса
      - alert: DeploymentGenerationMismatch
        expr: |
          kube_deployment_metadata_generation{job="kube-state-metrics"}
          !=
          kube_deployment_status_observed_generation{job="kube-state-metrics"}
        for: 5m
        labels:
          severity: warning
          tier: platform
        annotations:
          summary: "Deployment {{ $labels.namespace }}/{{ $labels.deployment }} не обработан контроллером"
          description: "observedGeneration отстает от metadata.generation более 5 минут. Проверьте состояние kube-controller-manager или флаг spec.paused."

      # Деградация доступности: число доступных реплик меньше желаемого
      - alert: DeploymentReplicasUnavailable
        expr: |
          (kube_deployment_spec_replicas{job="kube-state-metrics"}
          -
          kube_deployment_status_replicas_available{job="kube-state-metrics"}) > 0
        for: 10m
        labels:
          severity: warning
          tier: platform
        annotations:
          summary: "У Deployment {{ $labels.namespace }}/{{ $labels.deployment }} отсутствуют доступные реплики"
          description: "Фактическое число доступных реплик меньше спецификации в течение 10 минут."
```

### Автоматизированный гейт в CI/CD пайплайнах

Для реализации безопасной непрерывной доставки внедряйте проверку статуса в скрипты деплоя:

```bash
# Пример шага деплоя в Bash / CI/CD pipeline
kubectl apply -f deployment.yaml

echo "Ожидание завершения Rollout..."
if ! kubectl rollout status deployment/my-app -n prod --timeout=300s; then
    echo "ОШИБКА: Обновление превысило лимит времени 300 секунд! Запуск аварийного отката..."
    kubectl rollout undo deployment/my-app -n prod
    kubectl rollout status deployment/my-app -n prod --timeout=120s
    exit 1
fi

echo "Развертывание успешно завершено."
```

---

## 7. Лучшие практики (Best Practices)

1. **Обязательная настройка `readinessProbe`:** Без проверки готовности Kubernetes считает под готовым сразу после запуска процесса, немедленно удаляя старые реплики. При сбое нового кода это приводит к полной недоступности приложения.
2. **Внедрение `startupProbe` для медленных сервисов:** Выносите длительную инициализацию (прогрев кэша, подключение к БД) в `startupProbe`, чтобы избежать ложных срабатываний и циклических перезапусков от `livenessProbe`.
3. **Фиксация причин изменений через аннотацию:** Флаг `--record` окончательно удален в Kubernetes v1.24. Всегда документируйте релизы через аннотацию `kubernetes.io/change-cause`:
   ```bash
   kubectl annotate deployment/my-app -n prod kubernetes.io/change-cause="Релиз 2.4.1 (тикет SRE-1042)" --overwrite
   ```
4. **Консервативный `progressDeadlineSeconds`:** Не занижайте таймаут прогресса ниже максимального времени вытягивания образов и прогрева подов на ваших bare-metal узлах. Для критических сервисов рекомендуемое значение — от 300 до 600 секунд.
5. **Ограничение истории ревизий (`revisionHistoryLimit`):** Задавайте `revisionHistoryLimit: 3-5` (по умолчанию 10). Избыточные старые ReplicaSet создают бесполезную нагрузку на etcd, но значение не должно быть меньше глубины планируемого отката.
6. **Корректный Graceful Shutdown:** Убедитесь, что приложение перехватывает сигнал `SIGTERM` и корректно завершает соединения. `spec.terminationGracePeriodSeconds` должен превышать время хука `preStop` плюс время дообслуживания активных запросов.
7. **Безопасная стратегия ротации (`maxUnavailable: 0` для SLA):** Для критичных stateless-сервисов настраивайте `maxUnavailable: 0` и `maxSurge: 1` или `25%`, чтобы при любых сбоях новых реплик емкость работающего приложения не снижалась ниже 100%.
8. **Проверка запаса ресурсов перед релизом:** Убедитесь, что суммарные `requests` новых реплик с учетом `maxSurge` укладываются в свободную емкость узлов и лимиты `ResourceQuota`.

---

## 8. Ограничения и особенности (Edge Cases)

1. **Обновление при `spec.replicas: 0`:** Если Deployment масштабирован в 0, изменение `spec.template` завершается мгновенно (новые поды не создаются). Ожидаемо при плановой консервации сервиса, но может ввести в заблуждение при автоматическом релизе.
2. **Перекрытие выкаток (Rollover):** Если применить второе обновление до завершения первого, контроллер Deployment не ждет завершения промежуточного rollout. Он начинает немедленно сворачивать недоразвернутый ReplicaSet и выкатывать последний. В выводе `kubectl rollout status` это может отображаться как резкие скачки номеров ревизий.
3. **Неизменяемость селектора меток (`spec.selector`):** Поле `spec.selector` неизменяемо после создания объекта Deployment. Попытка изменить селектор приведет к ошибке валидации API-сервера. Для изменения селектора требуется полное пересоздание Deployment.
4. **Взаимодействие HPA и RollingUpdate:** Настраивайте `HorizontalPodAutoscaler` строго на объект `Deployment`, а не на дочерний `ReplicaSet`. При ротации HPA масштабирует общий размер нагрузки, а контроллер Deployment делит реплики между старым и новым ReplicaSet.
5. **Мутабельные теги образов (`:latest`):** Если в манифесте используется мутабельный тег без изменения самого манифеста, команда `kubectl apply` не изменит `spec.template`. Контроллер не зафиксирует новое поколение и не запустит rollout. Для обновления одинаковых тегов используйте `kubectl rollout restart`.
6. **Изменения ConfigMap/Secret не инициируют Rollout:** Изменение содержимого ConfigMap или Secret не меняет хэш шаблона пода (`spec.template`). Контроллер Deployment не перезапускает поды. Для применения конфигурации требуется выполнить `kubectl rollout restart deployment/<name>` либо использовать утилиты автоматического перезапуска.
7. **Откат приостановленного Deployment заблокирован:** Команда `kubectl rollout undo` завершится ошибкой, если Deployment находится на паузе (`spec.paused: true`). Сначала выполните `kubectl rollout resume`.
8. **Конфликт параметров времени:** Если `progressDeadlineSeconds <= minReadySeconds`, условие `ProgressDeadlineExceeded` выставится мгновенно при старте, так как под не успеет подтвердить доступность до истечения дедлайна.
9. **Отсутствие команды `rollout undo --force`:** Принудительный откат не предусмотрен синтаксисом kubectl. Принудительная перезагрузка осуществляется через удаление конкретных подов или `rollout restart`.
10. **Ограничение глубины отката:** Нельзя откатиться к ревизии, чей ReplicaSet был удален сборщиком мусора из-за превышения `revisionHistoryLimit`.
11. **Поды в Terminating блокируют сворачивание старого RS:** Пока старый под не освободит ресурсы узла и не завершит цикл удаления, старый ReplicaSet не сможет уменьшить счетчик `CURRENT` до нуля, блокируя закрытие фазы rollout.
12. **Разрыв сетевых соединений при мгновенном SIGTERM:** Если приложение мгновенно завершает процесс по `SIGTERM`, клиенты получат ошибки `502 Bad Gateway`, поскольку переключение маршрутов в kube-proxy (iptables/IPVS) и EndpointSlice происходит асинхронно с задержкой в 1–3 секунды. Обязательно используйте задержку `preStop: exec: command: ["/bin/sleep", "5"]`.

---

## 9. Дополнительная информация

### См. также
- [Deployment: Архитектура и концепции](./index.md) — базовые принципы работы контроллера Deployment.
- [Управление жизненным циклом Deployment](./lifecycle_management.md) — детальная механика процессов Rollout, Rollback и пропорционального масштабирования.
- [Продвинутые сценарии диагностики Deployment](./advanced_troubleshooting_scenarios.md) — глубокий анализ сбоев уровня ядра Linux, CRI containerd и сетевого стека.
- [Манифест Deployment и лучшие практики](./deployment_manifest.md) — эталонные конфигурации манифестов и параметры надежности.
- [Пробы жизнедеятельности в Kubernetes](../probes.md) — тонкая настройка Startup, Liveness и Readiness проб.
- [Производственный чек-лист Deployment](./production_checklist.md) — регламенты предрелизной валидации stateless-нагрузок.
- [Поиск и устранение неисправностей в Kubernetes](../../Troubleshooting/troubleshooting_overview.md) — общая методология диагностики инфраструктуры кластера.