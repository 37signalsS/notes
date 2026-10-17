# Pod Security Standards и Secret

**Актуально для:** Kubernetes 1.30+ (PSA в статусе GA с v1.25, актуально для версий v1.28–v1.32)

## Определения

**Pod Security Standards (PSS)** — официальная спецификация Kubernetes, определяющая три профиля изоляции контейнеров (`privileged`, `baseline`, `restricted`) на основе настроек `securityContext`.

**Pod Security Admission (PSA)** — встроенный контроллер допуска (Validating Admission Controller) в `kube-apiserver`, проверяющий создаваемые и обновляемые поды на соответствие профилям PSS. Управляется через метки пространств имен (`pod-security.kubernetes.io/*`) или глобальный файл конфигурации кластера.

**SecurityContext** — декларативная секция конфигурации Pod (`spec.securityContext`) и отдельных контейнеров (`spec.containers[*].securityContext`), задающая привилегии операционной системы, идентификаторы UID/GID, параметры Linux capabilities, seccomp-профили и правила разграничения доступа к файловой системе.

**tmpfs (RAM-диск)** — временная файловая система в оперативной памяти хоста Linux, которую `kubelet` монтирует в каталог пода для размещения содержимого томов типа `secret`, `configMap` и `downwardAPI`, исключая запись незашифрованных данных на постоянный накопитель узла.

**fsGroup** — дополнительный групповой идентификатор (Supplemental GID), задаваемый в `spec.securityContext` пода. `kubelet` назначает этот GID владельцем каталогов и файлов смонтированных томов, позволяя процессам непривилегированного пользователя читать конфиденциальные данные.

**Bound Service Account Token** — ограниченный по времени жизни JWT-токен, привязанный к конкретному экземпляру Pod и целевой аудитории (`audience`). Выдается через TokenRequest API и монтируется через `projected` volume, заменяя устаревшие постоянные токены `kubernetes.io/service-account-token`.

---

## Архитектура и основные концепции

### Взаимодействие Pod Security Admission и жизненного цикла Secret

Контроллер допуска PSA встроен непосредственно в бинарный файл `kube-apiserver` и срабатывает на этапе валидации (Validating Admission) перед сохранением объекта Pod в etcd. 

```
[ kubectl / CI/CD ]
        │ (POST /api/v1/namespaces/prod/pods)
        ▼
[ kube-apiserver ]
        │
        ├─► Mutating Admission (инъекция sidecar, мутация)
        │
        ├─► Schema Validation
        │
        ├─► Pod Security Admission (Проверка PSS: privileged / baseline / restricted)
        │     ├─► Режим enforce: отказ при нарушении (HTTP 403 Forbidden)
        │     ├─► Режим audit: запись в kube-audit.log
        │     └─► Режим warn: возвращение предупреждения в HTTP-заголовке
        │
        └─► etcd (Сохранение манифеста Pod)
                 │
                 ▼
          [ kube-scheduler ] ──► Назначение на узел Worker
                                         │
                                         ▼
                                   [ kubelet ]
                                         ├─► Создание tmpfs для Secret
                                         ├─► Расшифровка секретов из apiserver
                                         ├─► Применение прав (defaultMode, fsGroup)
                                         └─► Запуск контейнеров через CRI
```

#### Режимы применения PSA

PSA поддерживает независимую настройку трех режимов для каждого пространства имен:

| Режим | Действие при несоответствии PSS | Влияние на развертывание пода | Назначение |
| :--- | :--- | :--- | :--- |
| `enforce` | Блокирует создание/обновление пода (`HTTP 403`) | Жесткий отказ (Pod не создается) | Защита production-контуров |
| `audit` | Пропускает pod, добавляет аннотацию в аудит-лог | Отсутствует | Сбор статистики и аудит compliance |
| `warn` | Пропускает pod, возвращает предупреждение клиенту | Отсутствует (предупреждение в CLI) | Тестирование и подготовка разработчиков |

#### Фиксация версий политик (Version Pinning)

Метки версий (`enforce-version`, `audit-version`, `warn-version`) определяют правила какого релиза Kubernetes применяются:
- `latest` — правила обновляются автоматически при обновлении версии `kube-apiserver`. Это несет операционный риск: обновление кластера может неожиданно заблокировать деплой работающих приложений, если новые правила ужесточились.
- `v1.31` (или конкретная версия) — правила зафиксированы. Изменения стандартов вступают в силу только после явного обновления метки администратором.

---

### Матрица профилей PSS и ограничения для секретов

Kubernetes разделяет требования безопасности на три уровня. Профиль `restricted` предъявляет максимальные требования к монтированию томов и процессам, потребляющим секреты.

| Профиль | Допустимые Volume Types для Secret | Требования к процессу, читающему секрет | Ограничения hostPath |
| :--- | :--- | :--- | :--- |
| **privileged** | Все типы без ограничений | Любой UID (включая root), любые capabilities | Разрешен |
| **baseline** | Все стандартные типы томов | Запрещены privileged-контейнеры, запрещен захват хостовых пространств (`hostPID`, `hostIPC`, `hostNetwork`) | **Запрещен** |
| **restricted** | `secret`, `projected`, `configMap`, `downwardAPI`, `emptyDir`, `ephemeral`, `persistentVolumeClaim` | Обязательно `runAsNonRoot: true`, сброс capabilities `drop: ["ALL"]`, `allowPrivilegeEscalation: false`, `seccompProfile` | **Запрещен категорически** |

```
                       Иерархия профилей PSS
┌─────────────────────────────────────────────────────────────────┐
│ Privileged (Доступен hostPath, запуск root, доступ к хосту)     │
├─────────────────────────────────────────────────────────────────┤
│ Baseline (Запрещен hostPath, запрещены host-неймспейсы)         │
├─────────────────────────────────────────────────────────────────┤
│ Restricted (Разрешен tmpfs/secret, запрещен root, drop: [ALL])  │
└─────────────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> Стандартные типы томов `secret` и `projected` **полностью разрешены** во всех профилях PSS, включая `restricted`. Запрет касается исключительно монтирования файлов учетных данных через `hostPath`.

---

### Механика монтирования Secret через tmpfs и права доступа в Linux

Когда pod с томом типа `secret` назначается на рабочий узел, демон `kubelet` выполняет следующие действия:

1. **Создание файловой системы в RAM**: На хосте создается каталог `/var/lib/kubelet/pods/<pod-uid>/volumes/kubernetes.io~secret/<volume-name>` и монтируется как `tmpfs`. Данные хранятся исключительно в оперативной памяти узла и не сбрасываются на диск (при условии корректного отключения swap или настройки шифрования подкачки).
2. **Атомарная запись через структуру симлинков**:
   - `kubelet` запрашивает расшифрованные данные секрета у `kube-apiserver`.
   - Создается каталог с временной меткой `..data_<timestamp>`.
   - Внутри создаются файлы ключей.
   - Создается относительный симлинк `..data -> ..data_<timestamp>`.
   - Целевые файлы (например, `db-password`) симлинкуются на `..data/db-password`.
   - При изменении секрета обновляется симлинк `..data`, что обеспечивает атомарность обновления данных для приложений.
3. **Применение прав доступа (UID / GID / defaultMode)**:
   - Владельцем файлов по умолчанию является пользователь `root` (`UID 0`).
   - Если в `pod.spec.securityContext` указан `fsGroup: <GID>`, группа всех файлов и каталогов тома рекурсивно меняется на `<GID>`.

#### Разбор конфликта: defaultMode: 0400 против runAsNonRoot

Классическая ошибка SRE и DevOps при переходе на профиль `restricted`:

```yaml
# ❌ Конфигурация, вызывающая ошибку Permission Denied
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    fsGroup: 10001
  containers:
  - name: app
    volumeMounts:
    - name: secret-vol
      mountPath: /etc/secrets
  volumes:
  - name: secret-vol
    secret:
      secretName: app-secret
      defaultMode: 0400  # Чтение разрешено ТОЛЬКО владельцу (UID 0)!
```

**Механика отказа ядра Linux:**
1. Файл `/etc/secrets/token` принадлежит `root:10001` (UID 0, GID 10001).
2. Маска `0400` задает права: `r--------` (чтение владельцу `root`, группе `---`, остальным `---`).
3. Процесс контейнера работает от `UID 10001`. Процесс входит в группу `10001` благодаря `fsGroup`.
4. Ядро Linux проверяет соответствие UID: `10001 != 0` (не владелец).
5. Ядро проверяет соответствие GID: `10001 == 10001` (член группы).
6. Ядро проверяет права группы: `---` (доступ запрещен!).
7. Результат: приложение завершается с ошибкой `EACCES: Permission denied`.

**Корректное решение:**
Для non-root приложений маска `defaultMode` обязана содержать бит чтения для группы: `0440` (`r--r-----`) или `0444` (`r--r--r--`). В сочетании с `fsGroup: 10001` это дает:
- `UID 0 (root)`: чтение.
- `GID 10001 (группа приложения)`: чтение.
- Все остальные пользователи на хосте: нет доступа (`---`).

---

### Сравнение способов доставки секретов в контексте PSS

| Критерий | Volume Mount (`tmpfs`) | Environment Variables (`secretKeyRef`) | Projected Volume |
| :--- | :--- | :--- | :--- |
| **Совместимость с PSS Restricted** | Полная | Полная | Полная |
| **Поддержка `readOnlyRootFilesystem`** | Да (`readOnly: true`) | Да (не создает файлов) | Да (`readOnly: true`) |
| **Утечка в `crictl inspect` / `/proc`** | **Исключена** (данные в файловой системе) | **Высокий риск** (видны в `/proc/<pid>/environ`, дампах ядра) | **Исключена** |
| **Динамическое обновление без рестарта** | Поддерживается (через симлинк) | Не поддерживается (требуется рестарт пода) | Поддерживается |
| **Влияние на cgroup memory** | Потребляет RAM пода (tmpfs) | Потребляет только память процесса | Потребляет RAM пода (tmpfs) |

> [!WARNING]
> Данные томов `tmpfs` аллоцируются в памяти ядра на узле и учитываются в лимитах потребления оперативной памяти контейнера (`spec.containers[*].resources.limits.memory`). Монтирование объемных секретов или TLS-цепочек в pod с жестким лимитом памяти может спровоцировать `OOMKilled` (Exit Code 137).

---

## Практические сценарии

### Сценарий 1: Настройка PSA на уровне Namespace

Настройка пространства имен с разделением уровней: блокировка нарушений (`enforce`), журналирование в аудит (`audit`) и вывод предупреждений (`warn`) с фиксацией версии стандарта.

```yaml
# namespace-production.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: payment-production
  labels:
    # Жесткая блокировка подов, нарушающих профиль restricted
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: v1.31
    # Логирование нарушений в аудит-лог для анализа безопасности
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: v1.31
    # Вывод предупреждений администраторам и CI/CD пайплайнам
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: v1.31
```

Применение манифеста и проверка активных меток:

```bash
kubectl apply -f namespace-production.yaml
# → namespace/payment-production created

# Проверка установленных меток через jsonpath
kubectl get ns payment-production -o jsonpath='{.metadata.labels}' | jq 'with_entries(select(.key | startswith("pod-security")))'
# → {
# →   "pod-security.kubernetes.io/audit": "restricted",
# →   "pod-security.kubernetes.io/audit-version": "v1.31",
# →   "pod-security.kubernetes.io/enforce": "restricted",
# →   "pod-security.kubernetes.io/enforce-version": "v1.31",
# →   "pod-security.kubernetes.io/warn": "restricted",
# →   "pod-security.kubernetes.io/warn-version": "v1.31"
# → }
```

---

### Сценарий 2: Эталонный Deployment с секретами в профиле Restricted

Манифест сервиса, соответствующий всем требованиям PSS `restricted`:
1. Полный отказ от root (`runAsNonRoot: true`, `runAsUser: 10001`).
2. Разрешение доступа к файлам секретов через `fsGroup: 10001` и `defaultMode: 0440`.
3. Защита от модификации контейнера: `readOnlyRootFilesystem: true`.
4. Сброс всех capabilities ядра Linux: `drop: ["ALL"]`.
5. Использование `emptyDir` в памяти для каталога временных файлов приложения `/tmp`.

```yaml
# secure-app-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-service
  namespace: payment-production
  labels:
    app.kubernetes.io/name: payment-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: payment-service
  template:
    metadata:
      labels:
        app: payment-service
    spec:
      # Отключение автомонтирования токена SA для минимизации прав
      automountServiceAccountToken: false
      serviceAccountName: payment-service-sa
      # Настройки безопасности уровня всего пода
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        fsGroupChangePolicy: OnRootMismatch
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: payment-api
        image: internal-registry.local/apps/payment-api:1.4.2
        imagePullPolicy: IfNotPresent
        # Настройки безопасности конкретного контейнера
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 256Mi
        volumeMounts:
        - name: db-credentials-vol
          mountPath: /etc/secrets/database
          readOnly: true
        - name: tls-certs-vol
          mountPath: /etc/secrets/tls
          readOnly: true
        - name: tmp-dir
          mountPath: /tmp
      volumes:
      - name: db-credentials-vol
        secret:
          secretName: payment-db-secret
          defaultMode: 0440  # Владелец root, группа 10001 (чтение), чужие ---
          items:
          - key: username
            path: db_user
          - key: password
            path: db_pass
      - name: tls-certs-vol
        secret:
          secretName: payment-tls-pair
          defaultMode: 0440
      - name: tmp-dir
        emptyDir:
          medium: Memory
          sizeLimit: 32Mi
```

Проверка соответствия манифеста через валидацию на API-сервере:

```bash
kubectl apply -f secure-app-deployment.yaml --dry-run=server
# → deployment.apps/payment-service created (server dry run)
```

---

### Сценарий 3: Projected Volume с Bound Service Account Token и Secret

Пример объединения криптографического токена доступа, CA-сертификата и конфиденциальных ключей в единый том без использования постоянных секретов токенов SA:

```yaml
# pod-projected-tokens.yaml
apiVersion: v1
kind: Pod
metadata:
  name: audit-collector
  namespace: payment-production
spec:
  automountServiceAccountToken: false
  serviceAccountName: audit-collector-sa
  securityContext:
    runAsNonRoot: true
    runAsUser: 20000
    fsGroup: 20000
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: collector
    image: internal-registry.local/infra/collector:v2.1.0
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
    volumeMounts:
    - name: token-and-certs
      mountPath: /var/run/secrets/tokens
      readOnly: true
  volumes:
  - name: token-and-certs
    projected:
      defaultMode: 0440
      sources:
      # Динамический ограниченный токен SA (Bound Token)
      - serviceAccountToken:
          path: sa-token.jwt
          expirationSeconds: 3600
          audience: "https://vault.internal.local"
      # Внутренний корпоративный корневой сертификат
      - secret:
          name: internal-ca-cert
          items:
          - key: ca.crt
            path: ca.crt
```

---

### Сценарий 4: Общекластерная конфигурация AdmissionConfiguration (Sysadmin)

На bare-metal и on-premise кластерах системный администратор задает глобальные правила PSA через конфигурационный файл контроллеров допуска `kube-apiserver`.

Файл конфигурации плагина `/etc/kubernetes/admission/pod-security.yaml`:

```yaml
apiVersion: apiserver.config.k8s.io/v1
kind: AdmissionConfiguration
plugins:
- name: PodSecurity
  configuration:
    apiVersion: pod-security.admission.config.k8s.io/v1
    kind: PodSecurityConfiguration
    defaults:
      enforce: "baseline"
      enforce-version: "v1.31"
      audit: "restricted"
      audit-version: "v1.31"
      warn: "restricted"
      warn-version: "v1.31"
    exemptions:
      # Пространства имен, исключенные из проверки (системные компоненты)
      namespaces:
      - kube-system
      - ingress-nginx
      - monitoring
      # Пользователи-администраторы, исключенные из проверки
      usernames:
      - system:kube-controller-manager
      - system:kube-scheduler
      # Исключенные RuntimeClass (например, gVisor / kata-containers)
      runtimeClasses: []
```

Подключение конфигурации к статическому манифесту Control Plane `/etc/kubernetes/manifests/kube-apiserver.yaml`:

```yaml
spec:
  containers:
  - name: kube-apiserver
    command:
    - kube-apiserver
    - --admission-control-config-file=/etc/kubernetes/admission/pod-security.yaml
    # Монтирование файла конфигурации внутрь контейнера kube-apiserver
    volumeMounts:
    - mountPath: /etc/kubernetes/admission
      name: admission-config
      readOnly: true
  volumes:
  - hostPath:
      path: /etc/kubernetes/admission
      type: DirectoryOrCreate
    name: admission-config
```

---

## Операции и команды

### Сводная таблица команд администратора

| Операция | Команда | Назначение |
| :--- | :--- | :--- |
| **Просмотр профилей PSA во всех NS** | `kubectl get ns -L pod-security.kubernetes.io/enforce,pod-security.kubernetes.io/warn,pod-security.kubernetes.io/audit` | Аудит покрытия кластера политиками безопасности |
| **Установка enforce: restricted** | `kubectl label --overwrite ns <ns> pod-security.kubernetes.io/enforce=restricted` | Включение принудительной изоляции |
| **Тестовая валидация манифеста** | `kubectl apply -f manifest.yaml --dry-run=server -n <ns>` | Серверная проверка пода на совместимость с PSS |
| **Снятие меток PSS с NS** | `kubectl label ns <ns> pod-security.kubernetes.io/enforce- pod-security.kubernetes.io/warn-` | Отключение политик для отладки |
| **Поиск нарушений в аудит-логе** | `grep "pod-security.kubernetes.io/audit-violations" /var/log/kubernetes/audit/kube-audit.log` | Анализ заблокированных или потенциально опасных подов |

### Примеры выполнения команд с ожидаемым выводом

Инспекция всех пространств имен кластера на предмет соблюдения стандартов PSS:

```bash
kubectl get ns -L pod-security.kubernetes.io/enforce -L pod-security.kubernetes.io/enforce-version
# → NAME                 STATUS   AGE   ENFORCE      ENFORCE-VERSION
# → default              Active   45d   baseline     v1.31
# → kube-system          Active   45d   privileged   latest
# → payment-production   Active   12d   restricted   v1.31
```

Проверка прав доступа к смонтированному секрету внутри запущенного пода:

```bash
kubectl exec -n payment-production deploy/payment-service -c payment-api -- ls -la /etc/secrets/database
# → total 0
# → drwxr-xr-x 3 root  10001 120 Oct 17 21:30 .
# → drwxr-xr-x 3 root  root   80 Oct 17 21:30 ..
# → drwxr-xr-x 2 root  10001  80 Oct 17 21:30 ..2026_10_17_18_30_05.412958102
# → lrwxrwxrwx 1 root  10001  31 Oct 17 21:30 ..data -> ..2026_10_17_18_30_05.412958102
# → lrwxrwxrwx 1 root  10001  14 Oct 17 21:30 db_pass -> ..data/db_pass
# → lrwxrwxrwx 1 root  10001  14 Oct 17 21:30 db_user -> ..data/db_user

kubectl exec -n payment-production deploy/payment-service -c payment-api -- id
# → uid=10001(appuser) gid=10001(appgroup) groups=10001(appgroup)
```

Проверка фактического монтирования tmpfs на ноде (выполняется на рабочем узле системным администратором):

```bash
findmnt -t tmpfs | grep "volumes/kubernetes.io~secret"
# → /var/lib/kubelet/pods/8c5a4d1e-2c8b-4b2a-9f5e-1829384756af/volumes/kubernetes.io~secret/db-credentials-vol tmpfs tmpfs rw,nosuid,nodev,relatime,size=1048576k,mode=700
```

---

## Диагностика и типичные ошибки

### Матрица неисправностей

| Симптом | Первопричина | Диагностика | Способ устранения |
| :--- | :--- | :--- | :--- |
| `violates PodSecurity "restricted:latest": hostPath volumes` | Использование `hostPath` для монтирования сертификатов или ключей | `kubectl describe pod` или вывод dry-run | Заменить `hostPath` на `secret` или `projected` volume |
| `violates PodSecurity "restricted:latest": runAsNonRoot != true` | В манифесте отсутствует `runAsNonRoot: true` | `kubectl get pod <pod> -o yaml \| grep securityContext` | Добавить `runAsNonRoot: true` и `runAsUser: <UID>` в `securityContext` |
| `violates PodSecurity "restricted:latest": allowPrivilegeEscalation != false` | Контейнер допускает повышение привилегий | Проверка `spec.containers[*].securityContext` | Установить `allowPrivilegeEscalation: false` |
| `CrashLoopBackOff`: `open /etc/secrets/db_pass: permission denied` | `defaultMode: 0400` при запуске от non-root пользователя | `kubectl logs <pod>`, проверка прав через `ls -l` | Изменить `defaultMode` на `0440` и задать `fsGroup: <GID>` |
| `CrashLoopBackOff`: `Read-only file system` | Приложение пытается записать файл в каталог со смонтированным секретом | Трассировка логов приложения | Вынести секреты в отдельный путь, для записи настроить `emptyDir` |
| Секрет не обновляется при изменении Secret в Kubernetes | Использование `subPath` в `volumeMounts` | Проверка `volumeMounts[*].subPath` | Убрать `subPath`, монтировать весь каталог секрета |

### Диагностика отклонения подов контроллером PSA

Если deployment не создает поды в пространстве имен с `enforce: restricted`:

```bash
# 1. Проверка событий ReplicaSet
kubectl get events -n payment-production --field-selector reason=FailedCreate --sort-by='.lastTimestamp'
# → 2m FailedCreate replicaset/payment-service-59bc65584b 
# → Error creating: pods "payment-service-59bc65584b-z89lx" is forbidden: 
# → violates PodSecurity "restricted:v1.31": 
# → seccompProfile (pod or container "payment-api" must set securityContext.seccompProfile.type to "RuntimeDefault" or "Localhost")

# 2. Выявление точных несоответствий стандарту через server dry-run
kubectl apply -f deployment.yaml --dry-run=server -n payment-production
# → Error from server (Forbidden): error when creating "deployment.yaml": pods "payment-service" is forbidden: 
# → violates PodSecurity "restricted:v1.31": unrestricted capabilities (container "payment-api" must set securityContext.capabilities.drop=["ALL"])
```

### Диагностика прав на узле при ошибке Permission Denied

Если pod запустился, но приложение не может прочитать файл секрета:

```bash
# 1. Проверка UID и групп процесса
kubectl exec -n payment-production <pod-name> -- id
# → uid=10001 gid=10001 groups=10001

# 2. Проверка реальных прав доступа к файлу
kubectl exec -n payment-production <pod-name> -- ls -lL /etc/secrets/database/db_pass
# → -r-------- 1 root 10001 32 Oct 17 21:30 /etc/secrets/database/db_pass

# Анализ: Права -r-------- означают mode 0400. 
# Процесс с UID 10001 не является root (UID 0), а группе 10001 чтение запрещено.
# Решение: обновить defaultMode до 0440 в манифесте Pod/Deployment.
```

---

## Best Practices

1. **Двухэтапное внедрение политик PSS**:
   - Этап 1: включите `warn: restricted` и `audit: restricted` на 2–4 недели в staging и production.
   - Этап 2: проанализируйте аудит-логи и устраните все предупреждения в CI/CD пайплайнах.
   - Этап 3: включите `enforce: restricted`.
2. **Всегда фиксируйте версии политик (`enforce-version`)**: Избегайте значения `latest` в production. Фиксация (например, `v1.31`) гарантирует, что плановое обновление кластера Kubernetes не сломает доставку секретов и деплой рабочих нагрузок.
3. **Стандартная связка прав для non-root подов**:
   - `runAsNonRoot: true`
   - `runAsUser: <UID>` (например, `10001`)
   - `fsGroup: <GID>` (совпадающий с UID приложения)
   - `fsGroupChangePolicy: OnRootMismatch` (предотвращает зависания при старте подов с большими томами)
   - `defaultMode: 0440` в секции `secret` тома.
4. **Всегда задавайте `readOnly: true` в volumeMounts**: Предотвращает случайные попытки процессов модифицировать смонтированные файлы в tmpfs.
5. **Отключайте автомонтирование SA токенов**: Задавайте `automountServiceAccountToken: false` в спецификации Pod или ServiceAccount, если сервису не требуется прямой доступ к Kubernetes API.
6. **Откажитесь от `subPath` для секретов**: Использование `subPath` монтирует отдельный файл вместо каталога с симлинком `..data`. Это полностью блокирует автоматическое обновление секрета при его изменении в кластере.
7. **Учитывайте лимиты памяти при использовании tmpfs**: Помните, что секреты в оперативной памяти входят в лимит `resources.limits.memory` контейнера. Для объемных сертификатов и цепочек закладывайте буфер по памяти не менее 32–64 MiB.

---

## Дополнительная информация

### Миграция с устаревшего PodSecurityPolicy (PSP) на PSA

Механизм PSP был полностью удален в релизе Kubernetes 1.25. Ключевые различия при работе с секретами:

| Параметр | Устаревший PSP | Современный PSA |
| :--- | :--- | :--- |
| **Управление** | RBAC (`ClusterRole` + глагол `use` на объект PSP) | Метки на объектах `Namespace` |
| **Мутация манифестов** | Поддерживалась (PSP мог автоматически подставлять `fsGroup` или `runAsUser`) | **Только валидация** (PSA не мутирует поды; манифест обязан явно содержать валидный `securityContext`) |
| **Гранулярность** | На уровне конкретного ServiceAccount/User | На уровне всего Namespace |

Для гранулярных политик сложнее стандартных трех профилей PSS (например, запрет монтирования секретов без определенной метки или принудительная инъекция sidecar-агентов) используйте специализированные Policy Engines: [Kyverno](../../Security/kyverno/Scenarios/security_policies.md) или OPA Gatekeeper.

### Смотрите также

- [Security Context в Kubernetes](../../Security/pod_security_context.md) — детальное описание всех параметров изоляции подов и контейнеров.
- [Безопасность Secret в Kubernetes](security.md) — общие принципы защиты, шифрование etcd и классификация конфиденциальных данных.
- [Использование Secret в Pod](using_secrets.md) — способы передачи секретов через Volume, переменные окружения и Projected Volumes.
- [Хранение секретов в etcd](etcd_storage.md) — шифрование на уровне хранилища (`EncryptionConfiguration`).
- [Обзор управления доступом на основе ролей (RBAC)](../../Security/rbac/rbac_overview.md) — разграничение прав доступа к объектам Secret в API-сервере.
- [NetworkPolicy: Сетевая безопасность и изоляция подов](../../Security/network_policies.md) — изоляция сетевого трафика приложений, работающих с конфиденциальными данными.
- [Внешние менеджеры секретов](external_managers.md) — интеграция кластера с локальными хранилищами (HashiCorp Vault, SOPS).

