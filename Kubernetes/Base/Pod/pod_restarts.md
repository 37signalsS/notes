# Перезапуск Pod в Kubernetes

**Актуально для:** Kubernetes 1.30–1.32+

---

## Определения

**Перезапуск контейнера (Container Restart)** — процедура завершения и повторного запуска изолированного процесса внутри существующего контейнера под управлением локального агента `kubelet` и рантайма CRI (containerd, CRI-O). Объект Pod в API-сервере Kubernetes сохраняется, его сетевой стек (Network Namespace, IP-адрес), метаданные и UID остаются неизменными. Счётчик перезапусков (`status.containerStatuses[*].restartCount`) инкрементируется.

**Пересоздание Pod (Pod Recreation)** — полное удаление старого объекта Pod из API-сервера и развертывание нового объекта вышестоящим контроллером рабочей нагрузки (Deployment, StatefulSet, DaemonSet, Job). Новый Pod получает новый уникальный идентификатор UID, заново проходит цикл планирования (kube-scheduler), монтирует тома и в большинстве случаев получает новый кластерный IP-адрес. Счётчики `restartCount` для нового пода инициализируются со значения 0.

**CrashLoopBackOff** — транзитное состояние контейнера в Pod (`Waiting` с причиной `CrashLoopBackOff`), информирующее о том, что контейнер аварийно завершает работу сразу после запуска или проваливает обязательные пробы, а `kubelet` перезапускает его с экспоненциально увеличивающейся задержкой (Exponential Back-off Delay).

**Экспоненциальная задержка (Back-off Delay)** — защитный механизм `kubelet`, предотвращающий перегрузку вычислительного узла и дисковой подсистемы частыми рестартами сбойного процесса: интервалы между попытками запуска удваиваются (10с → 20с → 40с → 80с → 160с → 300с) с добавлением случайного фактора (jitter).

**Graceful Shutdown (Корректное завершение)** — детерминированный процесс мягкой остановки приложения: доставка процессам контейнера сигнала завершения (`SIGTERM` или объявленного `STOPSIGNAL`), прекращение приема нового сетевого трафика, обработка текущих транзакций и сброс файловых буферов в рамках лимита времени `spec.terminationGracePeriodSeconds` (по умолчанию 30 секунд) до отправки принудительного сигнала `SIGKILL`.

**PID 1 в контейнере** — процесс с идентификатором 1 внутри изолированного пространства имён PID (PID Namespace) контейнера. В ядре Linux процесс PID 1 наделен специальным статусом: операционная система не применяет к нему стандартные обработчики сигналов по умолчанию. Если процесс PID 1 не регистрирует обработчик `SIGTERM`, сигнал игнорируется, и приложение ожидает жесткой остановки по `SIGKILL`. Также PID 1 обязан утилизировать процессы-зомби («reaping child processes»).

**preStop Hook** — синхронный блокирующий вызов (команда в окружении контейнера `exec` или HTTP-запрос `httpGet`), инициируемый `kubelet` непосредственно перед передачей контейнеру сигнала остановки. Служит буфером для сетевой конвергенции кластера (удаление IP пода из правил маршрутизации kube-proxy/CNI).

**In-place Pod Vertical Scaling** — возможность мутации запросов (`requests`) и лимитов (`limits`) ресурсов CPU и памяти работающего контейнера без пересоздания пода (KEP-1287). Политика `resizePolicy` определяет, изменяются ли cgroups на лету (`NotRequired`) или для применения лимитов рантайм обязан перезапустить конкретный контейнер (`RestartContainer`).

**Native Sidecar (Встроенные sidecar-контейнеры)** — контейнеры, объявленные в блоке `initContainers` с директивой `restartPolicy: Always` (GA в Kubernetes 1.29+). В отличие от стандартных Init-контейнеров, они не блокируют запуск основных контейнеров после перехода в состояние `Ready`, продолжают работать на протяжении жизненного цикла Pod и перезапускаются независимо от основного приложения.

---

## Архитектура и принципы работы

### Перезапуск контейнера против пересоздания Pod

Понимание границы ответственности между `kubelet` на узле и контроллерами на уровне Control Plane критично при траблшутинге сетевых разрывов и сброса локальных состояний:

| Характеристика | Перезапуск контейнера (Container Restart) | Пересоздание Pod (Pod Recreation) |
| :--- | :--- | :--- |
| **Инициатор события** | `kubelet` через Container Runtime Interface (CRI) | Контроллер рабочей нагрузки (`kube-controller-manager`) |
| **Объект в API (etcd)** | Тот же самый Pod (UID неизменен) | Новый объект Pod (генерируется новый UID) |
| **IP-адрес Pod** | **Сохраняется** (сетевой неймспейс Pod Sandbox жив) | **Меняется** (новый Network Namespace и аренда IP из пула CNI) |
| **Счётчик `restartCount`** | Увеличивается на 1 при каждом сбое | Сбрасывается в 0 для нового экземпляра |
| **Локальная FS контейнера** | Очищается (новая запись в overlayfs/writable layer) | Полностью создается заново |
| **Тома `emptyDir`** | **Сохраняются** (живут, пока существует Pod Sandbox) | Уничтожаются и выделяются заново |
| **Сетевые соединения** | Разрываются (сокеты процесса закрываются) | Разрываются (IP выводится из Endpoints) |
| **Контейнеры Pod** | Перезапускается **только упавший** контейнер | Уничтожаются и создаются **все** контейнеры пода |
| **Привязка к узлу (Node)** | Pod остается на том же физическом/виртуальном узле | Может быть запланирован планировщиком на другой узел |

```text
  [ Событие сбоя процесса ]
              │
              ▼
   Kubelet на узле фиксирует выход процесса
              │
      ┌───────┴───────────────────────────────┐
      ▼                                       ▼
restartPolicy: Always/OnFailure         restartPolicy: Never
      │                                       │
      ▼                                       ▼
Kubelet инициирует перезапуск          Pod переходит в фазу Failed
(UID и IP сохраняются,                  (Контроллер Deployment создает
 restartCount инкрементируется)          новый Pod с новым UID и IP)
```

### Политики перезапуска (spec.restartPolicy)

Политика `spec.restartPolicy` задается на уровне спецификации Pod и транслируется агенту `kubelet`. Допустимые значения: `Always` (по умолчанию), `OnFailure`, `Never`.

| Значение политики | Поведение при Exit Code = 0 | Поведение при Exit Code != 0 (или OOM) | Типичные рабочие нагрузки |
| :--- | :--- | :--- | :--- |
| **Always** | Перезапуск контейнера | Перезапуск контейнера | Deployment, StatefulSet, DaemonSet |
| **OnFailure** | Контейнер завершен (Completed) | Перезапуск контейнера с бэкоффом | Job, разовые расчетные задачи |
| **Never** | Контейнер завершен (Completed) | Контейнер завершен с ошибкой (Error) | Job (с отключенным рестартом), аудит |

> **Важно:** В контроллерах `Deployment`, `StatefulSet` и `DaemonSet` спецификация пода обязана иметь `restartPolicy: Always`. Попытка выставить `OnFailure` или `Never` в шаблоне Deployment будет отклонена валидационным вебхуком API-сервера Kubernetes.

### Механизм и алгоритм экспоненциальной задержки (Back-off)

Когда контейнер завершает работу аварийно (Exit Code отличный от 0, падение процесса, OOMKilled, сбой зонда Liveness), `kubelet` не перезапускает его мгновенно бесконечное число раз. Во избежание каскадного исчерпания процессорного времени и дискового ввода-вывода (IOPS) на узле включается алгоритм **Exponential Back-off**.

#### Алгоритм расчета интервалов

Задержка рассчитывается по геометрической прогрессии с базовым шагом:
- 1-й сбой: немедленный перезапуск (задержка ~0c–10c);
- 2-й сбой: задержка **10 секунд**;
- 3-й сбой: задержка **20 секунд**;
- 4-й сбой: задержка **40 секунд**;
- 5-й сбой: задержка **80 секунд**;
- 6-й сбой: задержка **160 секунд**;
- 7-й сбой и далее: максимальная задержка **300 секунд (5 минут)**.

К расчетному интервалу `kubelet` добавляет псевдослучайный разброс (jitter до 20%), чтобы предотвратить явление «громоподобного стада» (Thundering Herd Problem), когда десятки реплик на одном узле одновременно обращаются к общему диску или API.

#### Сброс таймера задержки (Back-off Reset)

Счетчик задержки сбрасывается к начальному значению, если контейнер успешно проработал непрерывно в течение определенного периода:
- В `kubelet` задержка сбрасывается после стабильного выполнения контейнера в статусе `Running` на протяжении **двойного текущего периода задержки** (но не менее **10 минут**).
- Если контейнер стабильно работает более 10 минут, следующий сбой начнется снова с задержки 10 секунд, несмотря на то, что общий счетчик `restartCount` сохраняет историческое суммарное значение.

> **Справка:** Архитектура и глубокая диагностика цикличных аварий подробно описаны в [Определениях и концепциях CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md) и [Диагностике CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md).

### Причины и триггеры перезапуска

Контейнер подвергается перезапуску или пересозданию под воздействием следующих триггеров:

| Триггерное событие | Механизм фиксации | Итоговый результат | Контекст ядра и рантайма |
| :--- | :--- | :--- | :--- |
| **Exit Code 1..125, 139, 255** | CRI сообщает kubelet о завершении PID 1 | Перезапуск контейнера | Внутренняя ошибка приложения, необработанное исключение, panic, segfault. |
| **Exit Code 126 / 127** | CRI сообщает об ошибке запуска бинарника | CrashLoopBackOff | 126: нет прав на исполнение (+x); 127: бинарник или зависимая библиотека `.so` не найдены. |
| **OOMKilled (Exit Code 137)** | Ядро Linux (cgroups OOM Killer) | Перезапуск контейнера | Превышен `resources.limits.memory`. `oom_kill` инкрементируется в `memory.events`. |
| **Liveness Probe Failure** | `kubelet` фиксирует таймаут или код != 2xx/3xx | Принудительный перезапуск | `kubelet` отправляет `SIGKILL` процессу и инициирует создание нового контейнера. |
| **Startup Probe Failure** | `kubelet` фиксирует исчерпание попыток | Принудительный перезапуск | Приложение не успело инициализироваться за отведенный лимит `failureThreshold × periodSeconds`. |
| **In-place Resize (RestartContainer)** | `kubelet` сверяет `resizePolicy` при изменении Pod | Перезапуск контейнера | Изменение `resources.limits` требует рестарта контейнера по политике спецификации. |
| **Ручной kill PID 1** | Сигнал внутри контейнера (`kill 1`) | Перезапуск контейнера | PID 1 завершается, `kubelet` обнаруживает остановку контейнера и перезапускает его. |
| **Node Eviction (Нехватка ресурсов узла)** | `kubelet` эвиктит Pod при исчерпании диска/памяти узла | **Пересоздание Pod** | Pod переходит в `Failed`/`Evicted`. Контроллер разворачивает замену на другом узле. |
| **kubectl rollout restart** | Пользователь патчит аннотацию `spec.template` | **Пересоздание Pod** | Контроллер проводит Rolling Update с созданием нового ReplicaSet. |

### Влияние изменений конфигурации: развенчание мифов

Одной из самых частых ошибок системных администраторов и инженеров является непонимание того, как Kubernetes реагирует на изменение `ConfigMap` и `Secret`.

```text
                      [ Изменение данных ConfigMap/Secret ]
                                       │
        ┌──────────────────────────────┴──────────────────────────────┐
        ▼                                                             ▼
 Способ доставки: Volume                                    Способ доставки: ENV
 (configMap / secret)                                     (valueFrom / envFrom)
        │                                                             │
        ├───────────────────────────────┐                             ▼
        ▼                               ▼                 Значения ENV зафиксированы
 subPath: true                  Без subPath (дефолт)       в /proc/PID/environ при старте.
        │                               │                 ИЗМЕНЕНИЯ НЕ ПРИМЕНЯЮТСЯ!
        ▼                               ▼                             │
 Файл НЕ обновляется.           Kubelet обновляет файлы               ▼
 Требуется пересоздание          через атомарный symlink swap.    Требуется явный
 Pod вручную.                   Контейнер НЕ перезапускается!    rollout restart
                                (Нужен inotify/SIGHUP приложения).
```

1. **Миф: Изменение ConfigMap или Secret автоматически перезапускает поды.**
   - **Факт:** Изменение объекта `ConfigMap` или `Secret` в API Kubernetes **никогда само по себе не изменяет манифест Deployment/StatefulSet и не приводит к перезапуску контейнеров**.
2. **Монтирование через Volume без `subPath`:**
   - `kubelet` отслеживает изменения в кластере и обновляет проецируемые файлы в файловой системе контейнера без остановки пода.
   - Механизм обновления: атомарная подмена симлинка (`..data_tmp` → `..data`).
   - Контейнер **не перезапускается**. Если приложение не умеет перечитывать конфигурацию на лету (hot-reload через `inotify`, чтение при запросе или получение `SIGHUP`), оно продолжит работать со старой конфигурацией из оперативной памяти до тех пор, пока не произойдет рестарт.
3. **Монтирование через `subPath`:**
   - При монтировании отдельного ключа через `subPath` симлинки не используются. Файл монтируется жестко.
   - Такой файл **не обновляется вообще**, пока Pod не будет полностью пересоздан.
4. **Переменные окружения (`env`, `envFrom`):**
   - Переменные окружения считываются ядром Linux только в момент вызова системного вызова `execve` при инициализации контейнера.
   - Значения в переменных окружения работающего контейнера не изменяются никогда. Для их обновления обязателен `kubectl rollout restart`.

> **Справка:** Подробный архитектурный разбор задержек распространения томов и механики symlink swap представлен в [Обновление и Rollout ConfigMap](../ConfigMap/update_and_rollout.md).

### Механизм Graceful Shutdown и сетевая гонка (Race Condition)

При перезапуске или пересоздании пода в продакшене критично обеспечить нулевое прерывание клиентских запросов (Zero Downtime).

#### Жизненный цикл вывода пода из эксплуатации

```text
 1. Инициация: API-сервер проставляет объекту Pod поле deletionTimestamp и grace period
         │
         ├───► Контроллер Endpoints/EndpointSlice: удаляет IP пода из списка эндпоинтов сервиса
         │         │
         │         └───► kube-proxy / CNI на всех узлах обновляет iptables / IPVS / eBPF
         │               (Задержка распространения: от сотен миллисекунд до 2-5 секунд!)
         │
         └───► Kubelet на узле локально запускает процедуру остановки:
                   │
                   ├── 1. Выполняет preStop Hook (синхронно, блокируя SIGTERM)
                   │
                   ├── 2. Отправляет сигнал SIGTERM процессу PID 1 контейнера
                   │
                   ├── 3. Запускает обратный отсчет terminationGracePeriodSeconds
                   │
                   └── 4. По истечении таймера (если процесс жив) отправляет SIGKILL
```

#### Проблема сетевой гонки (Race Condition)

Системы Control Plane (`kubelet` на рабочем узле и `endpoint-slice-controller` с `kube-proxy`) работают **асинхронно**:
1. `kubelet` получает команду на удаление и немедленно отправляет `SIGTERM` процессу.
2. Приложение мгновенно переходит в shutdown: закрывает listening сокет порта (перестает принимать соединения) и начинает завершать текущие задачи.
3. В это же самое время контроллер EndpointSlice еще не успел уведомить демоны `kube-proxy` на всех серверах кластера, или `kube-proxy` еще не успел перегенерировать цепочки `iptables`/таблицы `IPVS`.
4. Клиентские запросы, поступающие в сервис, продолжают маршрутизироваться на IP-адрес завершающегося пода, натыкаются на закрытый сокет и получают от ядра ответ `TCP RST` (ошибки `502 Bad Gateway` или `Connection Refused` на стороне Ingress).

**SRE-решение проблемы:**
Внедрение задержки в `preStop` хук (`sleep 5..15`), чтобы процесс гарантированно продолжал слушать сокет и принимать запросы в течение времени, необходимого для полной сетевой конвергенции кластера:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh", "-c", "sleep 10"]
```

### Архитектура PID 1 и обработка сигналов

В операционных системах Linux ядро относится к процессу с `PID 1` специфическим образом:
- Обычный процесс, не имеющий зарегистрированного обработчика `SIGTERM`, уничтожается ядром при получении этого сигнала.
- Процесс с **PID 1 игнорирует любой сигнал**, для которого он явно не установил функцию-обработчик (signal handler). Сигнал `SIGKILL` перехватить нельзя, но он разрушает структуры без очистки ресурсов.
- Если точкой входа в Dockerfile является shell-скрипт вида `CMD ["/run.sh"]` или `ENTRYPOINT /run.sh` (в строковой форме), то `PID 1` становится `/bin/sh`. Стандартный `/bin/sh` не проксирует сигналы своим дочерним процессам. В результате при деплое приложение игнорирует `SIGTERM`, зависает на весь интервал `terminationGracePeriodSeconds` и аварийно уничтожается через `SIGKILL` (код 137), теряя транзакции и данные.

**Методы решения:**
1. Использование команды `exec` в shell-скриптах:
   ```bash
   #!/bin/sh
   # Подготовка окружения...
   exec /usr/local/bin/my-app "$@"  # Заменяет процесс shell процессом приложения, передавая ему PID 1
   ```
2. Использование легковесных диспетчеров инициализации (`tini` или `dumb-init`), берущих на себя обязанности корректного PID 1:
   ```dockerfile
   RUN apk add --no-cache tini
   ENTRYPOINT ["/sbin/tini", "--"]
   CMD ["/usr/local/bin/my-app"]
   ```

---

## Практические сценарии и конфигурация

### Сценарий 1: Плавный перезапуск рабочих нагрузок без простоя (Rollout Restart)

Когда необходимо применить новые параметры конфигурации, сбросить внутренние утечки памяти или обновить сертификаты без простоя, используется механизм `kubectl rollout restart`.

#### Механика команды

Команда `kubectl rollout restart` не удаляет поды напрямую. Она накладывает патч на манифест контроллера в раздел шаблона пода:
`spec.template.metadata.annotations["kubectl.kubernetes.io/restartedAt"] = <текущий_timestamp>`.
Так как шаблон пода изменился, контроллер начинает процедуру плавного обновления (Rolling Update) с учетом ограничений `maxSurge` и `maxUnavailable`.

```bash
# Перезапуск Deployment в пространстве имен production
kubectl rollout restart deployment/api-gateway -n production
# → deployment.apps/api-gateway restarted

# Отслеживание процесса обновления подов
kubectl rollout status deployment/api-gateway -n production --watch
# → Waiting for deployment "api-gateway" rollout to finish: 1 out of 3 new replicas have been updated...
# → deployment "api-gateway" successfully rolled out

# Экстренный откат к предыдущей ревизии в случае сбоя нового запуска
kubectl rollout undo deployment/api-gateway -n production
# → deployment.apps/api-gateway rolled back

# Перезапуск StatefulSet (поды перезапускаются строго по очереди в обратном порядке)
kubectl rollout restart statefulset/redis-cluster -n database
# → statefulset.apps/redis-cluster restarted

# Перезапуск DaemonSet (поды обновляются по одному на каждом узле)
kubectl rollout restart daemonset/node-exporter -n monitoring
# → daemonset.apps/node-exporter restarted
```

### Сценарий 2: Перезапуск контейнера без пересоздания Pod

В практике системного администрирования и SRE возникают ситуации, когда требуется перезапустить упавший или зависший процесс внутри пода, не меняя его сетевой IP-адрес и не удаляя сам Pod (например, на тестовом стенде или при расследовании состояния shared memory).

#### Вариант А: Завершение PID 1 через kubectl exec

Так как `spec.restartPolicy` для подов в Deployment установлена в `Always`, аварийная остановка главного процесса контейнера заставит `kubelet` перезапустить контейнер заново с сохранением IP и томов:

```bash
# Мягкое завершение PID 1 (если приложение перехватывает SIGTERM)
kubectl exec api-gateway-74b889d469-xk9qp -c app -n production -- kill 1

# Принудительное завершение всех процессов в неймспейсе контейнера
kubectl exec api-gateway-74b889d469-xk9qp -c app -n production -- kill -9 -1

# Проверка факта перезапуска: restartCount увеличится на 1
kubectl get pod api-gateway-74b889d469-xk9qp -n production -o wide
# → NAME                                READY   STATUS    RESTARTS      AGE   IP             NODE
# → api-gateway-74b889d469-xk9qp        1/1     Running   1 (10s ago)   15m   10.244.2.145   worker-02
```

#### Вариант Б: Остановка контейнера через CRI на узле (для администраторов узла)

Если доступ через `kubectl exec` заблокирован (например, нарушена аутентификация в контейнере или процесс полностью заблокировал ввод-вывод), администратор узла может перезапустить контейнер через `crictl`:

```bash
# 1. Поиск ID контейнера на узле, где запущен Pod
sudo crictl ps --name app --state Running
# → CONTAINER           IMAGE               CREATED             STATE               NAME                ATTEMPT             POD ID
# → 8e3d54fa78120       my-registry/app     2 hours ago         Running             app                 0                   f29bc1198da12

# 2. Остановка контейнера (CRI рапортует kubelet, и тот инициирует перезапуск)
sudo crictl stop 8e3d54fa78120
# → 8e3d54fa78120

# 3. Kubelet автоматически создает новый экземпляр контейнера
sudo crictl ps --name app
# → 3d4a11be89012       my-registry/app     5 seconds ago       Running             app                 1                   f29bc1198da12
```

### Сценарий 3: Настройка отказоустойчивого Graceful Shutdown

Комплексный пример манифеста Deployment с защитой от сетевой гонки (`preStop sleep`), расширенным тайм-аутом завершения и политикой сохранения диагностических логов при падении:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
  namespace: production
  labels:
    app: billing-service
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  selector:
    matchLabels:
      app: billing-service
  template:
    metadata:
      labels:
        app: billing-service
    spec:
      # Лимит времени на полную остановку всех процессов в поде
      terminationGracePeriodSeconds: 45
      containers:
      - name: billing
        image: internal-registry.local/finance/billing:v2.4.1
        imagePullPolicy: IfNotPresent
        # Захват последних строк лога при аварийном падении процесса
        terminationMessagePath: /dev/termination-log
        terminationMessagePolicy: FallbackToLogsOnError
        lifecycle:
          preStop:
            exec:
              # Пауза 10с для вывода IP из iptables/IPVS до отправки SIGTERM процессу
              command: ["/bin/sh", "-c", "sleep 10"]
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1024Mi
        ports:
        - containerPort: 8080
          name: http
        startupProbe:
          httpGet:
            path: /healthz/startup
            port: 8080
          failureThreshold: 30
          periodSeconds: 2
        livenessProbe:
          httpGet:
            path: /healthz/liveness
            port: 8080
          periodSeconds: 10
          timeoutSeconds: 2
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /healthz/ready
            port: 8080
          periodSeconds: 5
          timeoutSeconds: 2
          failureThreshold: 2
```

### Сценарий 4: Автоматический перезапуск подов при изменении ConfigMap и Secret

Чтобы изменения конфигураций гарантированно вступали в силу без ручного вмешательства инженера, применяются два проверенных продакшен-подхода:

#### Метод А: Вычисление контрольной суммы (Config Hash Annotation)

В Helm-шаблонах или Kustomize в манифест Deployment добавляется аннотация с хешем содержимого конфигурационного файла. При редактировании ConfigMap хеш автоматически изменяется, провоцируя стандартный Rolling Update:

```yaml
kind: Deployment
spec:
  template:
    metadata:
      annotations:
        # Helm автоматически вычисляет SHA256 содержимого ConfigMap
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

#### Метод Б: Использование оператора Reloader

Для кластеров без сложного CI/CD применяется контроллер Stakater Reloader, отслеживающий события изменения ConfigMap/Secret и автоматически вызывающий rolling upgrade связанных Deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: order-processor
  annotations:
    # Перезапускать под при изменении ConfigMap "order-config" или Secret "order-secrets"
    configmap.reloader.stakater.com/reload: "order-config"
    secret.reloader.stakater.com/reload: "order-secrets"
spec:
  template:
    # ...
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Алгоритм расследования нестабильных и перезапускающихся подов

```text
               Под находится в CrashLoopBackOff или растет restartCount
                                          │
                                          ▼
                      Выполнить: kubectl describe pod <pod-name>
                                          │
          ┌───────────────────────────────┴───────────────────────────────┐
          ▼                                                               ▼
   Секция "Last State"                                            Секция "Events"
          │                                                               │
  ┌───────┼────────────────────────┐                    ┌─────────────────┼─────────────────┐
  ▼       ▼                        ▼                    ▼                 ▼                 ▼
Exit 137 Exit 1/127/143          OOMKilled           Liveness Probe    Back-off restarting  FailedMount /
(SIGKILL)(Ошибка приложения)    (Память превышена)       Failed          failed container    ConfigError
  │       │                        │                    │                 │                 │
  │       ▼                        ▼                    ▼                 ▼                 ▼
  │   kubectl logs -p        Увеличить limits.    Проверить логи    Изучить код       Проверить наличие
  │   (анализ panic,         memory, настроить    приложения,       выхода и логи     ConfigMap/Secret
  │    конфигов, ENV)        GOMEMLIMIT / JVM     таймаут пробы     предыдущего шага  и права томов
  ▼
Проверить:
- OOMKilled = true? -> Нехватка памяти cgroups
- OOMKilled = false? -> Превышен terminationGracePeriodSeconds
```

### Справочник кодов завершения контейнеров (Exit Codes)

| Код выхода | Системный сигнал / Причина | Что произошло | Действия по устранению (SRE / DevOps) |
| :--- | :--- | :--- | :--- |
| **0** | `Success` | Процесс завершился штатно. Если это сервис (Web API) — он завершился раньше времени. | Проверить точку входа (`ENTRYPOINT`/`CMD`). Если это фоновый процесс, убедиться, что он не форкается в фон (демонизация), оставляя PID 1 пустым. |
| **1** | `General Error` | Фатальная ошибка приложения: падение рантайма, необработанный Exception, синтаксический сбой конфига. | Просмотреть логи предыдущей сессии: `kubectl logs <pod> --previous`. Проверить валидность параметров подключения и конфигурационных файлов. |
| **126** | `Command Invoked Cannot Execute` | Найден исполняемый файл, но у процесса нет прав на его выполнение (Permission Denied). | Проверить флаг исполнения (`chmod +x`) бинарника при сборке образа. Проверить параметры `securityContext.runAsUser` и `readOnlyRootFilesystem`. |
| **127** | `Command Not Found` | Исполняемый файл или зависимый интерпретатор (например, `/bin/bash` или `/bin/sh`) не найден. | Проверить пути в `command` и `args`. В минималистичных образах (Distroless, Scratch, Alpine) проверить наличие интерпретатора и динамических библиотек (`ldd`). |
| **137** | `SIGKILL (128 + 9)` | Процесс принудительно убит ядром или `kubelet`. Два ключевых сценария: **OOMKilled** либо **Grace Period Timeout**. | 1. Проверить `reason: OOMKilled`. Если да — поднять `resources.limits.memory`. 2. Если `OOMKilled: false` — процесс не успел завершиться за `terminationGracePeriodSeconds`, увеличить тайм-аут или оптимизировать shutdown. |
| **139** | `SIGSEGV (128 + 11)` | Ошибка сегментации (Segmentation Fault): процесс обратился к невыделенному участку памяти. | Проверить нативные бинарные библиотеки (C/C++, Go cgo, JNI). Собрать coredump. Проверить совместимость версий glibc/musl. |
| **143** | `SIGTERM (128 + 15)` | Процесс получил стандартный сигнал остановки. В штатной ситуации нормален. | Если контейнер перезапускается в цикле с кодом 143 во время обычной работы — проверить сбои зондов `livenessProbe` (kubelet посылает SIGTERM при сбое пробы). |
| **255** | `Exit Status Out Of Range` | Ошибка инициализации контейнера рантаймом или падение внутри точки входа. | Проверить события `kubectl get events`. Изучить логи `crictl` на узле. |

### Исчерпывающие команды инспекции причин падений

#### Извлечение точного статуса последнего падения

```bash
# Получение структурированного JSON с кодом выхода, причиной и временем падения
kubectl get pod api-gateway-74b889d469-xk9qp -n production -o json | jq '.status.containerStatuses[] | {
  container: .name,
  restarts: .restartCount,
  current_state: .state,
  last_termination: .lastState.terminated
}'
# → {
# →   "container": "app",
# →   "restarts": 4,
# →   "current_state": {
# →     "waiting": {
# →       "message": "back-off 160s restarting failed container=app pod=api-gateway-74b889d469-xk9qp_production",
# →       "reason": "CrashLoopBackOff"
# →     }
# →   },
# →   "last_termination": {
# →     "exitCode": 137,
# →     "finishedAt": "2026-10-17T14:22:10Z",
# →     "reason": "OOMKilled",
# →     "startedAt": "2026-10-17T14:20:05Z"
# →   }
# → }
```

#### Просмотр логов аварийно завершенного экземпляра

```bash
# Чтение логов упавшего контейнера до момента перезапуска
kubectl logs api-gateway-74b889d469-xk9qp -c app -n production --previous --tail=100
# → [FATAL] 2026-10-17 14:22:09 panic: runtime error: out of memory
# → goroutine 42 [running]:
# → main.processPayload(...)
```

#### Системная диагностика OOM на узле (Host-level)

Если статус в Kubernetes не очевиден, системный администратор проверяет кольцевой буфер ядра Linux (`dmesg`) и счетчики контрольных групп (cgroups v2):

```bash
# Проверка сообщений OOM Killer в кольцевом буфере ядра Linux
dmesg -T | grep -iE "oom[-_]killer|killed process"
# → [Sat Oct 17 17:22:10 2026] Memory cgroup out of memory: Killed process 384912 (my-app) total-vm:1854200kB, anon-rss:1048120kB, file-rss:4120kB, shmem-rss:0kB, UID:10001 pgtables:2140kB oom_score_adj:998

# Проверка счетчиков cgroups v2 для конкретного пода на рабочей ноде
# Путь формируется из UID пода:
POD_UID=$(kubectl get pod api-gateway-74b889d469-xk9qp -n production -o jsonpath='{.metadata.uid}' | tr '-' '_')
cat /sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod${POD_UID}.slice/memory.events
# → low 0
# → high 0
# → max 14
# → oom 14
# → oom_kill 14
```

### Диагностика сбоев зондов Liveness и Startup

Частой причиной перезапусков являются неверно настроенные пробы:
1. **Симптом:** Под переходит в `Running`, работает 1-2 минуты, затем `restartCount` увеличивается, а в событиях (`kubectl describe pod`) появляется:
   `Unhealthy: Liveness probe failed: HTTP probe failed with statuscode: 500` или `Get "http://10.244.1.25:8080/healthz": context deadline exceeded`.
2. **Причина:**
   - Высокая утилизация CPU или блокировка event loop потока приложения: поток не успевает ответить на запрос пробы за время `timeoutSeconds` (по умолчанию 1с).
   - Liveness probe обращается к внешней базе данных, которая временно зависла. **Антипаттерн:** падение БД приводит к каскадному перезапуску сотен микросервисов.
3. **Устранение:**
   - Развязать Liveness и внешние зависимости: Liveness должен проверять только жизнеспособность локального процесса (deadlock потоков, зависание цикла событий).
   - Добавить `startupProbe` для приложений с длительной загрузкой (JVM, тяжелые миграции).
   - Увеличить `timeoutSeconds: 3` и `periodSeconds: 10`.

---

## Лучшие практики (Best Practices)

### 1. Четкое разделение ответственности зондов (Probes)

- **Startup Probe:** Защищает медленно стартующие сервисы. Пока Startup Probe не перейдет в состояние `Success`, `livenessProbe` и `readinessProbe` отключены и **не могут вызвать перезапуск контейнера**.
- **Liveness Probe:** Предназначена исключительно для обнаружения фатальных внутренних зависаний (deadlock, бесконечный цикл). Должна быть максимально легковесной. Не должна проверять внешние СУБД, кэши или смежные микросервисы.
- **Readiness Probe:** Управляет включением пода в балансировку трафика сервиса. При сбое Readiness Probe контейнер **не перезапускается**, а лишь исключается из Endpoints.

> **Справка:** Полное руководство по конфигурации зондов доступно в [Пробы в Kubernetes (Probes)](../probes.md).

### 2. Корректный расчет terminationGracePeriodSeconds

Формула безопасного времени завершения:
$$\text{terminationGracePeriodSeconds} \ge \text{preStop sleep} + \text{Application Drain Timeout} + 5\text{s (запас)}$$

- Для Web API со стандартным keep-alive: `preStop: sleep 10` + время завершения активных HTTP-запросов (15с) $\rightarrow$ `terminationGracePeriodSeconds: 30..45`.
- Для брокеров очередей и СУБД: время на сброс буферов транзакций на диск $\rightarrow$ `terminationGracePeriodSeconds: 60..120`.

### 3. Тюнинг параметров RollingUpdate и PDB

Для защиты сервисов от деградации при плановых перезапусках (`rollout restart`, дренаж узлов `kubectl drain`):
- Задавайте в Deployment стратегию с нулевым числом недоступных реплик:
  ```yaml
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 25%
      maxUnavailable: 0
  ```
- Обязательно защищайте критичные сервисы манифестом `PodDisruptionBudget` (PDB):
  ```yaml
  apiVersion: policy/v1
  kind: PodDisruptionBudget
  metadata:
    name: billing-pdb
    namespace: production
  spec:
    minAvailable: 2
    selector:
      matchLabels:
        app: billing-service
  ```

### 4. Профилактика OOMKilled в среде с cgroups v2

Для предотвращения резкого убийства процессов по OOM Killer настраивайте внутренние лимиты рантаймов ниже лимитов cgroups:
- **Go приложения (Go 1.19+):** Задавайте переменную окружения `GOMEMLIMIT=900MiB` при значении `limits.memory: 1024Mi`. Сборщик мусора Go (GC) активизируется до того, как cgroup ядра отправит `SIGKILL`.
- **Java приложения (JVM):** Используйте `-XX:MaxRAMPercentage=75.0` при запущенном `UseContainerSupport` (включен по умолчанию в современных JDK 11+ / 17+ / 21+).

### 5. Антипаттерны управления перезапусками

| Антипаттерн | В чем заключается опасность | Правильное решение |
| :--- | :--- | :--- |
| **Liveness Probe проверяет базу данных** | При деградации БД все поды приложения начинают одновременно падать в CrashLoopBackOff, добивая базу миллионами коннектов при рестарте. | Проверять БД только в `readinessProbe`. Liveness должен проверять только локальный HTTP-сокет приложения. |
| **Использование `:latest` без imagePullPolicy** | При перезапуске контейнера `kubelet` может затянуть несовместимую версию образа из реестра, сломав работающую инсталляцию. | Использовать фиксированные immutable теги (semver или git commit SHA) и `imagePullPolicy: IfNotPresent`. |
| **Отсутствие preStop хука при быстром shutdown** | Клиенты получают ошибки 502 Bad Gateway / TCP Reset в моменты деплоя из-за задержки обновления правил маршрутизации kube-proxy. | Добавить `lifecycle.preStop.exec.command: ["/bin/sh", "-c", "sleep 10"]`. |
| **Использование shell без exec** | Shell становится PID 1 и «глотает» `SIGTERM`. Приложение завершается только по истечении 30 секунд жестким `SIGKILL`. | Использовать `exec "$@"` в скриптах-обертках либо внедрять `tini`/`dumb-init`. |
| **Монтирование критичных конфигов через subPath** | При изменении ConfigMap конфигурация внутри контейнера не обновляется даже после ручного перечитывания. | Использовать стандартное монтирование тома ConfigMap без subPath или паттерн hash-аннотаций. |

---

## Мониторинг, алертинг и SLO (SRE-контекст)

### Ключевые метрики Kubernetes для отслеживания перезапусков

| Метрика | Источник | Описание |
| :--- | :--- | :--- |
| `kube_pod_container_status_restarts_total` | `kube-state-metrics` | Суммарное количество перезапусков конкретного контейнера за всё время жизни пода. |
| `kube_pod_container_status_last_terminated_reason` | `kube-state-metrics` | Причина последнего завершения контейнера (`OOMKilled`, `Error`, `Completed`, `ContainerCannotRun`). |
| `kube_pod_container_status_waiting_reason` | `kube-state-metrics` | Причина нахождения контейнера в состоянии ожидания (`CrashLoopBackOff`, `ImagePullBackOff`). |
| `container_last_seen` | `cAdvisor` (встроен в kubelet) | Timestamp последней активности контейнера (сброс означает удаление или крах). |
| `container_memory_working_set_bytes` | `cAdvisor` | Текущее потребление оперативной памяти контейнером (именно оно триггерит OOMKilled при приближении к лимиту). |

### Важное различие: rate() против increase()

При построении запросов в Prometheus для метрики `kube_pod_container_status_restarts_total`:
- `rate(kube_pod_container_status_restarts_total[15m])` возвращает усредненное число перезапусков в секунду (дробное значение). Подходит для графиков тренда интенсивности аварий.
- `increase(kube_pod_container_status_restarts_total[15m])` возвращает целочисленный прирост количества перезапусков за указанный интервал. Является стандартом для построения SRE-алертов.

### Продакшен-правила алертинга (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: pod-restart-alerts
  namespace: monitoring
  labels:
    role: alert-rules
spec:
  groups:
  - name: pod.restarts.rules
    rules:
    # 1. Контейнер находится в состоянии цикличного падения
    - alert: PodCrashLooping
      expr: |
        kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} == 1
      for: 5m
      labels:
        severity: critical
        tier: platform
      annotations:
        summary: "Контейнер {{ $labels.container }} в поде {{ $labels.pod }} зациклен в CrashLoopBackOff"
        description: "Контейнер постоянно падает и перезапускается на узле. Пространство имен: {{ $labels.namespace }}."
        runbook_url: "https://kb.corp.local/troubleshooting/crashloopbackoff"

    # 2. Высокая частота перезапусков контейнера
    - alert: PodFrequentRestarts
      expr: |
        increase(kube_pod_container_status_restarts_total[15m]) > 3
      for: 2m
      labels:
        severity: warning
        tier: service
      annotations:
        summary: "Частые перезапуски пода {{ $labels.pod }}"
        description: "Контейнер {{ $labels.container }} перезапустился более 3 раз за последние 15 минут в namespace {{ $labels.namespace }}."

    # 3. Фиксация аварийного завершения по нехватке памяти (OOMKilled)
    - alert: ContainerOOMKilled
      expr: |
        kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1
      for: 1m
      labels:
        severity: critical
        tier: performance
      annotations:
        summary: "Контейнер {{ $labels.container }} в поде {{ $labels.pod }} завершен из-за OOMKilled"
        description: "Ядро уничтожило процесс из-за превышения memory limits. Требуется профилирование памяти или увеличение лимитов."

    # 4. Мониторинг приближения к OOM (Working Set > 90% от Limit)
    - alert: ContainerMemoryNearLimit
      expr: |
        (
          container_memory_working_set_bytes{container!=""}
          /
          container_spec_memory_limit_bytes{container!=""}
        ) * 100 > 90
      for: 3m
      labels:
        severity: warning
      annotations:
        summary: "Потребление памяти контейнером {{ $labels.container }} приближается к лимиту (>90%)"
        description: "Высокий риск OOMKilled для пода {{ $labels.pod }} в namespace {{ $labels.namespace }}."
```

### Влияние перезапусков на SRE SLO и Error Budget

В модели SRE нестабильность подов напрямую сжигает бюджет ошибок (Error Budget):
- При каждом внезапном падении активные HTTP/gRPC соединения с клиентами сбрасываются с ошибками 5xx или TCP reset.
- Если сервис таргетирует SLO доступности **99.9%**, допустимое время деградации составляет всего **43 минуты в месяц**.
- Быстрые каскадные перезапуски подов (CrashLooping реплик) приводят к исчерпанию бюджета ошибок в течение нескольких минут, что требует внедрения автоматических Circuit Breaker механизмов и строгой валидации манифестов в пайплайнах.

---

## Дополнительная информация

### Связанные темы в базе знаний

- [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — детальный разбор фаз, условий `status.conditions` и жизненного цикла Pod Sandbox.
- [Пробы в Kubernetes (Probes)](../probes.md) — исчерпывающее руководство по Startup, Liveness и Readiness механизмам.
- [Паттерны Sidecar в Kubernetes](./pod_sidecar_patterns.md) — архитектура Native Sidecars и Ambassador/Adapter контейнеров.
- [Практические команды и сценарии управления Pod](./pod_practical_scenarios_commands.md) — сценарии отладки, инспекции и выгрузки дампов.
- [Обзор архитектуры Pod](./pod_overview.md) — основы сетевой изоляции, разделение PID/IPC пространств и спецификация томов.
- [Обновление и Rollout ConfigMap](../ConfigMap/update_and_rollout.md) — задержки распространения изменений конфигураций и стратегии rolling update.
- [Управление жизненным циклом Deployment](../Deployment/lifecycle_management.md) — алгоритмы работы ReplicaSet, стратегии отката и выкатки.
- [Изменение ресурсов подов без перезапуска (In-Place Pod Resize)](../../Autoscaling/in_place_pod_resize.md) — архитектура KEP-1287 и контроллер cgroups v2.
- [Диагностика CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/diagnostics.md) — пошаговый разбор устранения инцидентов цикличных падений.
- [Определения и концепции CrashLoopBackOff](../../Troubleshooting/Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md) — теоретическая база и архитектура цикла повторных попыток.
- [OOMKilled в контейнерах](../../Troubleshooting/Common_Errors/oomkilled_pods.md) — глубокий анализ классов QoS, структуры памяти Linux и настроек OOM score.
- [Graceful Shutdown: Глубокое погружение](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md) — решение проблем зависания подов в статусе `Terminating`.
