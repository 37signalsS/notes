# 10 ошибок Kubernetes, которые вы должны знать (и как их исправить)

Ошибки Kubernetes — одна из самых распространенных проблем, с которыми сталкиваются разработчики при работе с продакшн-нагрузками. Они приводят к сбоям развертывания, простоям и потере времени на устранение неполадок.

В этой статье мы обсудим самые частые ошибки и способы их устранения, что поможет вам сэкономить часы и поддерживать работоспособность ваших кластеров.

## 1. CrashLoopBackOff

### Что это?
`CrashLoopBackOff` означает, что под в Kubernetes постоянно запускается и сразу же падает. Kubernetes пытается перезапустить его с экспоненциальной задержкой (10с, 20с, 40с, до 5 минут), чтобы снизить нагрузку на ресурсы, в соответствии с политикой `restartPolicy`.

[Изображение: Схема ошибки CrashLoopBackOff]

### Почему это происходит?
- **Сбой или баги в приложении:** неперехваченные исключения, ошибки времени выполнения.
- **Неправильная команда запуска:** опечатки или вызов несуществующих исполняемых файлов.
- **Ограничения ресурсов:** нехватка памяти (OOM kills) или троттлинг CPU.
- **Некорректно настроенные liveness-пробы.**
- **Отсутствие необходимых конфигураций:** отсутствующие ConfigMap, Secret, тома или переменные окружения.

### Пример
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: crash-demo
spec:
  containers:
    - name: crash-demo
      image: busybox
      command: ["wrongcommand"]
  restartPolicy: Always
```
Этот под немедленно падает из-за несуществующей команды, что приводит к `CrashLoopBackOff`.

### Устранение неполадок
1.  **Найдите проблемные поды:**
    ```bash
    kubectl get pods
    # NAME                    READY   STATUS             RESTARTS   AGE
    # nginx-579667dbc7d-lll6q   0/1     CrashLoopBackOff   6          2m
    ```
2.  **Изучите детали и события пода:**
    ```bash
    kubectl describe pod <pod_name>
    # State:        Waiting
    # Reason:       CrashLoopBackOff
    # Last State:   Terminated
    # Reason:       Error
    ```
3.  **Просмотрите логи:**
    ```bash
    # Логи текущего упавшего контейнера
    kubectl logs <pod_name>
    # Логи предыдущего экземпляра контейнера
    kubectl logs --previous <pod_name>
    ```
    Ищите стектрейсы, ошибки о недостающих файлах или проблемы при запуске.

### Решение
- Исправьте команду запуска на валидную.
- Обработайте исключения в коде приложения.
- Настройте пробы: увеличьте `initialDelaySeconds`, чтобы дать приложению время на запуск.
- Выделите реалистичное количество CPU/Memory.

---

## 2. ImagePullBackOff

### Что это?
`ImagePullBackOff` означает, что Kubernetes многократно пытается, но не может скачать образ контейнера, после чего увеличивает задержку между попытками. Это признак того, что под не может запуститься, потому что его образ недоступен.

[Изображение: Схема ошибки ImagePullBackOff]

### Почему это происходит?
- **Неверное имя или тег образа:** опечатка, отсутствие тега, неправильный репозиторий.
- **Образ удален или не был загружен** в репозиторий.
- **Проблемы с авторизацией:** отсутствуют или неверны `imagePullSecrets`.
- **Сетевые проблемы:** файрвол, DNS, прокси.
- **Ограничения со стороны репозитория:** превышены лимиты на скачивание (rate limits) или репозиторий недоступен.

### Пример
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: pull-demo
spec:
  containers:
    - name: pull-demo
      image: ngiinx:1.14.2 # Опечатка в имени
  restartPolicy: Always
```

### Устранение неполадок
1.  **Проверьте статус пода:**
    ```bash
    kubectl get pods
    # NAME       READY   STATUS             RESTARTS   AGE
    # test-pod   0/1     ImagePullBackOff   0          52s
    ```
2.  **Изучите детали пода:**
    ```bash
    kubectl describe pod <pod_name>
    ```
    В секции `Events` ищите сообщения вроде `ErrImagePull`, `Repository does not exist` или `pull access denied`.

3.  **Попробуйте скачать образ вручную:**
    ```bash
    docker pull <image>:<tag>
    ```
    Если команда падает — проблема в имени, теге или доступности репозитория. Если выполняется успешно — проблема на стороне Kubernetes (сеть, права).

### Решение
- Исправьте опечатки в имени образа, теге или пути к репозиторию.
- Убедитесь, что образ загружен в репозиторий.
- Добавьте или исправьте `imagePullSecrets` для приватных репозиториев.
- Проверьте сетевые правила (файрвол, DNS).

---

## 3. CreateContainerConfigError

### Что это?
Эта ошибка возникает, когда Kubernetes не может создать конфигурацию для контейнера из-за отсутствия или некорректности необходимых ресурсов, таких как ConfigMap или Secret.

[Изображение: Схема ошибки CreateContainerConfigError]

### Почему это происходит?
- **Отсутствует ConfigMap,** на который ссылаются `envFrom` или `volumeMounts`.
- **Отсутствует Secret,** используемый для `envFrom` или `volumeMounts`.
- **Некорректное монтирование тома,** например, указано имя несуществующего PVC.
- **Неверные ссылки на переменные окружения,** например, неправильное имя ключа.

### Пример
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: bad-config-demo
spec:
  containers:
  - name: app
    image: nginx
    envFrom:
      - configMapRef:
          name: missing-config # Этот ConfigMap не существует
  restartPolicy: Never
```

### Устранение неполадок
1.  **Проверьте статус пода:**
    ```bash
    kubectl get pods
    # NAME    READY    STATUS                      RESTARTS   AGE
    # my-pod   0/1     CreateContainerConfigError   0          28s
    ```
2.  **Изучите события пода:**
    ```bash
    kubectl describe pod bad-config-demo
    # Warning  Failed   56s (x6 over 1m45s)    kubelet   Error: configmap "missing-config" not found
    ```
3.  **Проверьте наличие ресурсов:**
    ```bash
    kubectl get configmap missing-config
    kubectl get secret my-secret
    ```

### Решение
- Создайте или исправьте недостающие ConfigMap и Secret.
- Убедитесь в правильности имен и неймспейсов для всех ссылающихся ресурсов.
- Исправьте имена монтируемых томов или PVC.

---
## 4. CreateContainerError / StartError

### Что это?
`CreateContainerError` (или `StartError`) возникает, когда Kubernetes не может создать или запустить контейнер внутри пода. Проблема связана с самим процессом создания контейнера, а не с его конфигурацией.

### Почему это происходит?
- **Не указана команда запуска** в образе (нет `ENTRYPOINT`/`CMD`).
- **Неправильная команда запуска** (несуществующий исполняемый файл).
- **Проблемы с томами/PVC:** указанное хранилище не существует или недоступно.
- **Ошибки среды выполнения контейнеров (container runtime):** конфликты имен, сбои, нехватка ресурсов.

### Пример
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: missing-cmd
spec:
  containers:
  - name: no-cmd
    image: ubuntu:latest
    command: ["nonexistentcommand"] # Несуществующая команда
  restartPolicy: Never
```

### Устранение неполадок
1.  **Проверьте статус пода:**
    ```bash
    kubectl get pods
    # NAME          READY   STATUS       RESTARTS   AGE
    # missing-cmd   0/1     StartError   0          32s
    ```
2.  **Изучите события пода:**
    ```bash
    kubectl describe pod <pod_name>
    # State:      Terminated
    # Reason:     StartError
    # Message:    ... exec: "nonexistentcommand": executable file not found
    ```

### Решение
- Добавьте `CMD` или `ENTRYPOINT` в `Dockerfile` или укажите `command` в спецификации пода.
- Исправьте команду запуска на валидную.
- Убедитесь, что все используемые тома и PVC существуют и доступны.
- Устраните конфликты имен, удалив старые контейнеры, или перезапустите `kubelet`.

---

## 5. FailedScheduling

### Что это?
`FailedScheduling` означает, что планировщик Kubernetes не смог найти подходящую ноду для размещения пода. Под остается в состоянии `Pending`.

### Почему это происходит?
- **Недостаточно ресурсов (CPU, memory)** на всех нодах.
- **Наличие `taints` на нодах,** для которых у пода нет `tolerations`.
- **Некорректные или слишком строгие правила** `nodeSelector` или `affinity`/`anti-affinity`.
- **Ноды в состоянии `Unschedulable` или `NotReady`** (например, после `kubectl cordon`).
- **Проблемы с PersistentVolumeClaim (PVC),** например, конфликт зон доступности.

### Пример
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: picky-pod
spec:
  containers:
  - name: app
    image: nginx
  nodeSelector:
    disktype: ssd # Требует ноду с этой меткой
  resources:
    requests:
      cpu: "4" # Требует 4 CPU
      memory: "8Gi"
```
Если ни одна нода не удовлетворяет этим требованиям, под не будет запланирован.

### Устранение неполадок
1.  **Изучите события пода:**
    ```bash
    kubectl describe pod picky-pod
    # Warning  FailedScheduling  ... 0/5 nodes are available: 5 Insufficient cpu.
    ```
    Сообщение точно укажет причину сбоя планирования.
2.  **Проверьте состояние и ресурсы нод:**
    ```bash
    kubectl describe nodes
    ```
3.  **Проверьте `taints` и `tolerations`:**
    ```bash
    kubectl get nodes -o json | jq '.items[].spec.taints'
    ```
4.  **Проверьте метки нод** для `nodeSelector`.

### Решение
- Уменьшите запросы к ресурсам (`requests`).
- Добавьте поду `tolerations`, соответствующие `taints` нод.
- Добавьте нодам нужные метки или ослабьте правила `nodeSelector`/`affinity`.
- Разблокируйте ноды (`kubectl uncordon`).
- Добавьте новые ноды в кластер.

---

## 6. OOMKilled

### Что это?
`OOMKilled` (Out Of Memory Killed) означает, что контейнер потребил больше памяти, чем ему было разрешено (`limits.memory`), и был принудительно завершен OOM Killer'ом ядра Linux. Для Kubernetes это выглядит как завершение с кодом `137`.

### Почему это происходит?
- **Превышены лимиты памяти:** приложение запросило больше памяти, чем указано в `resources.limits.memory`.
- **Утечки памяти** или неожиданные всплески нагрузки.
- **Нехватка памяти на уровне ноды:** ядро может "убивать" процессы, чтобы освободить память на ноде, даже если лимиты пода не превышены.

### Пример
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: oom-example
spec:
  containers:
    - name: mem-hog
      image: polinux/stress
      resources:
        requests:
          memory: "100Mi"
        limits:
          memory: "200Mi" # Лимит 200 MiB
      command: ["stress", "--vm", "1", "--vm-bytes", "250M"] # Попытка занять 250 MiB
```

### Устранение неполадок
1.  **Проверьте статус пода:**
    Часто под с `OOMKilled` уходит в `CrashLoopBackOff`, так как постоянно перезапускается и снова "убивается".
2.  **Изучите детали пода:**
    ```bash
    kubectl describe pod oom-example
    # Last State:     Terminated
    #   Reason:       OOMKilled
    #   Exit Code:    137
    ```
3.  **Просмотрите логи,** чтобы найти причину всплеска потребления памяти.
4.  **Проверьте потребление ресурсов:**
    ```bash
    kubectl top pod oom-example
    ```

### Решение
- **Настройте `requests` и `limits` памяти,** основываясь на реальном потреблении приложения.
- **Найдите и исправьте утечки памяти** с помощью профилировщиков.
- **Оптимизируйте приложение** для более эффективного использования памяти.
- **Используйте Vertical Pod Autoscaler (VPA)** для динамической настройки лимитов.

---

## 7. NodeNotReady

### Что это?
`NodeNotReady` означает, что нода в кластере не может выполнять рабочие нагрузки и помечена как недоступная для планирования. `kubelet` на этой ноде перестал отправлять "heartbeats" (сигналы о работоспособности) в control plane.

### Почему это происходит?
- **Исчерпание системных ресурсов** на ноде (CPU, память, диск).
- **Сбой сервиса `kubelet`:** он упал, остановлен или неверно сконфигурирован.
- **Проблемы с CNI (сетевым плагином)** или `kube-proxy`.
- **Потеря сетевой связности** между нодой и control plane.

### Устранение неполадок
1.  **Проверьте статус нод:**
    ```bash
    kubectl get nodes
    # NAME     STATUS     ROLES    AGE   VERSION
    # node2    NotReady   <none>   25d   v1.32.1
    ```
2.  **Изучите детали ноды:**
    ```bash
    kubectl describe node node2
    # Conditions:
    #   Type            Status  ... Message
    #   ----            ------      -------
    #   MemoryPressure  True    ... kubelet has insufficient memory available
    #   Ready           False   ... KubeletNotReady
    ```
    Секция `Conditions` укажет на причину (нехватка памяти, диска, проблемы с сетью).
3.  **Проверьте системные компоненты** на этой ноде:
    ```bash
    kubectl get pods -n kube-system --field-selector spec.nodeName=node2
    ```

### Решение
- Увеличьте ресурсы ноды или уменьшите потребление ресурсов подами на ней.
- Проверьте статус и логи сервиса `kubelet` на самой ноде.
- Проверьте логи подов `kube-proxy` и CNI-плагина (например, Calico, Flannel).
- Проверьте сетевую конфигурацию на ноде.

---

## 8. Unauthorized / Forbidden (RBAC)

### Что это?
- **Unauthorized (401):** API-сервер Kubernetes не может распознать вашу личность (невалидный токен, сертификат).
- **Forbidden (403):** Kubernetes знает, кто вы, но у вас нет прав на выполнение запрошенного действия согласно правилам RBAC.

### Почему это происходит?
- **Неправильные или отсутствующие учетные данные** в `kubeconfig`.
- **Отсутствуют `RoleBinding` или `ClusterRoleBinding`,** связывающие вашего пользователя/сервисный аккаунт с нужными правами (`Role`/`ClusterRole`).
- **Неправильный неймспейс:** вы пытаетесь получить доступ к ресурсу в одном неймспейсе, имея права только в другом.

### Устранение неполадок
1.  **Проверьте свои права** с помощью `kubectl auth can-i`:
    ```bash
    # Проверяем, можем ли мы смотреть поды в неймспейсе default
    kubectl auth can-i get pods -n default
    ```
2.  **Проверьте текущий контекст** и пользователя:
    ```bash
    kubectl config view --minify
    ```
3.  **Изучите существующие роли и привязки:**
    ```bash
    kubectl get roles,rolebindings -n <namespace>
    kubectl get clusterroles,clusterrolebindings
    ```

### Решение
- Убедитесь, что ваш `kubeconfig` настроен правильно.
- Создайте `Role` и `RoleBinding` (или `ClusterRole` и `ClusterRoleBinding`) для предоставления необходимых прав.
- Убедитесь, что привязки (`RoleBinding`) созданы в правильном неймспейсе.

---

## 9. YAML Misconfiguration

### Что это?
Ошибки в манифестах YAML: неправильные отступы, типы данных, опечатки, неверные версии API. Это приводит к сбоям развертывания или неожиданному поведению.

### Почему это происходит?
- **Ошибки отступов:** смешивание пробелов и табов.
- **Неправильные типы данных:** `replicas: "3"` (строка) вместо `replicas: 3` (число).
- **Опечатки в ключах:** `apiVerion` вместо `apiVersion`.
- **Неверная версия API:** `apps/v1beta1` вместо `apps/v1`.
- **Отсутствие обязательных полей,** например, секции `spec.template` в Deployment.

### Пример
```yaml
apiVerion: apps/v1 # Опечатка
kind: Deployment
metadata:
  name: demo-app
spec:
  replicas: "3" # Строка вместо числа
  template:
    metadata:
      labels:
        app: demo
    spec:
      containers:
        - image: nginx
          name: nginx
          ports:
            - containerPort: "80" # Строка вместо числа
```

### Устранение неполадок и решение
- **Проверяйте манифесты перед применением:**
  ```bash
  # Проверка на стороне клиента без отправки в кластер
  kubectl apply --dry-run=client -f manifest.yaml
  ```
- **Используйте линтеры:** `yamllint`, `kubeconform` для автоматического поиска ошибок.
- **Встраивайте валидацию в CI/CD:** остановите пайплайн, если манифесты некорректны.
- **Исправляйте типы данных и отступы:** всегда используйте пробелы.
- **Храните все манифесты в Git** и используйте code review для их проверки.

---
*Остальные ошибки, такие как `NonZeroExitCode`, не были включены в этот список для краткости, но их принципы устранения схожи с `CrashLoopBackOff` (анализ логов и команды запуска).*
