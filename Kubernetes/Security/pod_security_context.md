# Security Context в Kubernetes

## Определения

**Security Context** — набор настроек в Kubernetes, определяющий права доступа и ограничения для подов (Pod) и контейнеров (Container). Ключевой элемент реализации принципа наименьших привилегий и предотвращения несанкционированного доступа к ресурсам.

## Основные концепции

### Назначение и уровни применения

* **Назначение:** ограничение прав контейнеров, предотвращение доступа к ресурсам узла, соответствие требованиям безопасности, защита от атак типа "escape" из контейнера.
* **Поведение по умолчанию:** если `securityContext` не задан явным образом, Kubernetes по умолчанию присваивает контейнерам UID 0 (root).
* **Уровни применения:** настройки определяются на уровне пода (`spec.securityContext`) и/или на уровне контейнера (`spec.containers[*].securityContext`). Настройки контейнера переопределяют настройки пода при конфликте.

### Основные параметры

*   **`hostNetwork`, `hostPID`, `hostIPC`** — управляют взаимодействием подов с хост-системой:
    *   `hostNetwork: true`: разрешает поду использовать сетевое пространство имен хоста (дает доступ к сетевым интерфейсам и портам узла).
    *   `hostPID: true`: разрешает поду использовать пространство имен процессов хоста (позволяет видеть процессы, запущенные на узле).
    *   `hostIPC: true`: разрешает использование пространства имен межпроцессного взаимодействия (IPC) хоста.
*   **`runAsNonRoot: true`** — гарантирует запуск контейнера не от имени пользователя `root` (UID 0).
    *   **Особенности:** Если в образе не задан пользователь (или задан root) и не указан `runAsUser`, запуск пода завершится ошибкой.
    *   **PSA:** Если в неймспейсе включен Pod Security Admission для запрета root-подов, параметр `runAsNonRoot: true` обязателен. Контейнер автоматически будет использовать UID, настроенный в образе.
*   **`runAsUser` / `runAsGroup`** — указывают явный UID (User ID) пользователя и GID (Group ID) основной группы.
    *   **Рекомендация:** Если образ правильно настроен с non-root пользователем (инструкция `USER` в Dockerfile), `runAsUser` можно не указывать. Используйте его для принудительного соблюдения политик или compliance.
*   **`readOnlyRootFilesystem: true`** — делает корневую файловую систему контейнера доступной только для чтения, защищая от нежелательных модификаций.
*   **`allowPrivilegeEscalation: false`** — предотвращает получение процессом в контейнере больших привилегий, чем у его родительского процесса.
    *   **Механизм:** Устанавливает флаг `no_new_privs` в ядре Linux. Блокирует получение дополнительных привилегий через setuid/setgid-бинарные файлы или Linux capabilities.
*   **`capabilities`** — позволяет тонко настраивать Linux capabilities.
    *   **Использование:** Предпочтительный и более безопасный способ предоставления повышенных прав по сравнению с `privileged: true`. Используется для удаления (`drop: ["ALL"]`) или добавления (`add: ["NET_BIND_SERVICE"]`) определённых возможностей ядра.
*   **`seccompProfile`** — ограничивает системные вызовы (syscall), которые может выполнять контейнер, с помощью seccomp. Рекомендуется `type: RuntimeDefault`. Значительно сужает поверхность атаки на ядро Linux.
*   **`appArmorProfile`** — задаёт профиль AppArmor.
    *   **Версии:** Начиная с Kubernetes 1.30 — это полноправное поле в API (Beta), в 1.31 — GA. Ранее настраивалось через аннотации.
*   **`privileged: true`** — крайне опасно, предоставляет контейнеру полные привилегии, эквивалентные правам root на хостовой системе. Следует избегать.
*   **`fsGroup`** — указывает GID, который будет назначен для всех томов, примонтированных к поду, обеспечивая правильные разрешения для чтения/записи.
    *   **Поведение:** Файлы, создаваемые в томах, наследуют указанную группу. Владелец файла остаётся тем, под которым запущен процесс, но группа всегда соответствует `fsGroup`.
*   **`seLinuxOptions`** — позволяет назначать SELinux (Security-Enhanced Linux) метки для процессов в контейнере. Работает только на узлах с включенным SELinux (RHEL, CentOS, Fedora).
    *   **Поля:** `user` ( тип процесса), `role`, `level` (уровень.mac/priv/container). SELinux изолирует процессы на уровне MAC (Mandatory Access Control), дополняя DAC-разрешения (Linux permissions).
*   **`sysctls`** — позволяет настраивать параметры ядра (sysctl) для пода. Разделяются на «безопасные» (разрешены по умолчанию, например `net.core.somaxconn`) и «небезопасные» (требуют явного разрешения в конфигурации kubelet через `--allowed-unsafe-sysctls`).
    *   **Примеры безопасных:** `net.core.somaxconn`, `net.ipv4.ip_local_port_range`.
    *   **Примеры небезопасных:** `net.ipv4.ip_forward`, `kernel.msgmax`. Использование небезопасных sysctls требует включения на уровне узла.
*   **`windowsOptions`** — специфичные для Windows настройки, такие как `RunAsUserName` или интеграция с GMSA (Group Managed Service Accounts).
*   **`automountServiceAccountToken`** — управляет автоматическим монтированием ServiceAccount Token в под. По умолчанию `true` (токен монтируется в `/var/run/secrets/kubernetes.io/serviceaccount/token`). Установите `false`, если приложению не нужен доступ к Kubernetes API.
*   **`supplementalGroups`** — список дополнительных GID, добавляемых в список групп процесса. Используется для предоставления доступа к общим томам (NFS, CephFS) нескольким подам с разными UID.

## Особенности работы с образами

То, как Kubernetes обрабатывает запуск контейнера, зависит от настроек самого образа и параметров `securityContext`.

Если образ собран с инструкцией `USER 1001` (или любым другим не-root UID), и в манифесте пода не указан `securityContext`:

* Контейнер запустится под пользователем, определенным в образе.
* Это считается лучшей практикой подготовки образов.

### Образ с root пользователем (по умолчанию)

Если образ собран без инструкции `USER` (по умолчанию root):

1. **Без SecurityContext:** запустится как root (UID 0).
2. **С `runAsNonRoot: true`:** запуск завершится ошибкой (Error/CrashLoopBackOff), так как Kubernetes обнаружит попытку запуска от root без альтернативного UID.
3. **С `runAsNonRoot: true` и `runAsUser: 1001`:** запустится успешно под UID 1001, переопределив настройки образа.

### Проблема привилегированных портов (на примере Nginx)

Стандартные образы (например, `nginx`) часто требуют root-прав для привязки к портам ниже 1024 (например, порт 80).

* Если запустить такой образ с `runAsNonRoot: true` и `runAsUser: 1001`, контейнер упадет в `CrashLoopBackOff`, так как Nginx не сможет открыть порт 80.
* **Решение:** использовать специализированные образы (например, `nginx-unprivileged`) или перенастроить приложение на использование портов >1024.

**Итог:** Контейнер будет работать без ошибок в non-root режиме только в том случае, если процессы внутри него не требуют привилегий root (модификация системных файлов, привязка к портам <1024 и т.д.).

## Новые механизмы безопасности (v1.30+)

### Пользовательские пространства имен (User Namespaces)

User Namespaces позволяют изолировать UID/GID контейнера от UID/GID хоста. Это означает, что пользователь `root` внутри контейнера (UID 0) отображается на непривилегированного пользователя на хосте.

* **Статус:** Beta в Kubernetes 1.30.
* **Применение:** устанавливается через поле `spec.hostUsers: false` в спецификации Пода.
* **Подробнее:** см. отдельную статью [User Namespaces в Pod](../Base/Pod/user_namespaces.md).
* **Преимущество:** значительно снижает риск выхода за пределы контейнера (container breakout), так как даже при успешном escape атакующий не получит прав root на хосте.

### Политика дополнительных групп (supplementalGroupsPolicy)

Введена в Kubernetes 1.31 (Alpha) для контроля того, как группы из образа контейнера объединяются с группами, указанными в Pod spec.

* **`Merge` (по умолчанию):** объединяет группы из `/etc/group` образа с группами из спецификации пода.
* **`Strict`:** игнорирует группы из образа и использует только те, что явно указаны в `fsGroup`, `supplementalGroups` или `runAsGroup`.

## Pod Security Standards (PSS) и Pod Security Admission (PSA)

**PSS (Pod Security Standards)** — набор из трёх политик безопасности, определяющих допустимые конфигурации подов в кластере. Уровни безопасности категоризируются следующим образом:

*   **`privileged` (Привилегированный)** — Самый высокий уровень доступа и привилегий. Разрешает действия, которые обычно ограничены (например, `hostNetwork`, `hostPID`, `hostIPC`, доступ к конфиденциальным системным ресурсам). Представляет высокий риск, должен использоваться крайне экономно.
*   **`baseline` (Базовый)** — Средний уровень безопасности, подходящий для большинства приложений общего назначения. Соответствует стандартным практикам безопасности: запрет известных опасных конфигураций, но допуск стандартных нагрузок с минимальной настройкой.
*   **`restricted` (Ограниченный)** — Самые строгие требования безопасности. Включает принудительное монтирование `readOnlyRootFilesystem`, запрет любых capabilities, строгий контроль за UID/GID и доступом к сети. Предназначен для высокочувствительных рабочих нагрузок и сред со строгими требованиями соответствия (compliance).

**PSA (Pod Security Admission)** — встроенный **[контроллер допуска](../../Concepts/admission_controllers.md)** Kubernetes, применяющий PSS на уровне неймспейсов. Заменяет Pod Security Policy (PSP), удалённый в Kubernetes v1.25.

PSA работает через метки неймспейса и поддерживает три режима:

* **`enforce`** — отклоняет поды, не соответствующие политике.
* **`audit`** — пропускает поды, но записывает нарушения в логи аудита (audit logs) API-сервера.
* **`warn`** — пропускает поды, но возвращает предупреждение пользователю через `kubectl`.

## Практические сценарии

### 1. Настройки securityContext на уровне пода

Пример применения `securityContext` ко всем контейнерам внутри пода:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: security-context-pod-demo
spec:
  securityContext:
    runAsNonRoot: true    # Запрет запуска от root
    runAsUser: 1000       # UID для всех контейнеров
    runAsGroup: 3000      # GID для всех контейнеров
    fsGroup: 2000         # GID для всех томов
  containers:
  - name: sec-ctx-demo
    image: busybox
    command: [ "sh", "-c", "sleep 1h" ]
```

### 2. Настройки securityContext на уровне контейнера

Пример гранулярной настройки для отдельного контейнера, переопределяющей настройки уровня пода:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: security-context-container-demo
spec:
  containers:
  - name: sec-ctx-demo
    image: nginx
    securityContext:
      allowPrivilegeEscalation: false  # Запрет повышения привилегий
      capabilities:
        drop: ["ALL"]                  # Удаляем все capabilities
        add: ["NET_BIND_SERVICE"]      # Добавляем только нужные (для порта 80)
      readOnlyRootFilesystem: true     # ФС только для чтения
      seccompProfile:
        type: RuntimeDefault           # Стандартный seccomp-профиль
```

### 3. Конфигурация Pod Security Admission (PSA) для неймспейса

Пример конфигурации для неймспейса `production`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    # Аудит: все поды, не соответствующие restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
    # Предупреждения: нарушение базовых требований
    pod-security.kubernetes.io/warn: baseline
    pod-security.kubernetes.io/warn-version: latest
    # Принудительное применение: минимальные ограничения
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/enforce-version: latest
```

Для более сложных политик можно использовать: [Kyverno](./kyverno/policies/practical_scenarios.md) или OPA Gatekeeper.

### 4. Комбинированный пример: capabilities + seccomp + AppArmor (v1.30+)

Максимальная защита достигается сочетанием нескольких механизмов. В современных версиях K8s AppArmor настраивается в самом `securityContext`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flask-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: flask-app
  template:
    metadata:
      labels:
        app: flask-app
    spec:
      containers:
        - name: flask
          image: my-secure-app:latest
          securityContext:
            runAsNonRoot: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: [ALL]
            seccompProfile:
              type: RuntimeDefault
            appArmorProfile:
              type: Localhost
              localhostProfile: flask-deny-shadow
```

Назначение каждого уровня:

| Уровень | Блокирует | Пример |
|:--------|:----------|:-------|
| `capabilities.drop` | Целые категории привилегий | Raw-сокеты, монтирование ФС |
| `seccompProfile` | Опасные системные вызовы | `unshare`, `mount`, `clone` |
| `appArmorProfile` | Доступ к путям ФС и ресурсам | Чтение `/etc/shadow`, запись в `/etc/` |

Подробнее о модели: [Обзор механизмов безопасности Linux](../../Linux/Security/Linux_Security_Mechanisms_Overview.md).

### 5. Изоляция рантайма (RuntimeClass)

Для запуска недоверенного кода использование только `securityContext` может быть недостаточно. Изоляция на уровне ядра или виртуализации через `RuntimeClass` обеспечивает более высокий уровень защиты, что критично для **[жесткой мультитенантности](../Concepts/multi-tenancy.md)**.

* **[gVisor](../../Docker/alternative_runtimes_and_tools.md)** — создает userspace-ядро, которое перехватывает системные вызовы.
* **[Kata Containers](../../Docker/alternative_runtimes_and_tools.md)** — запускает каждый под в отдельной легковесной VM.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: untrusted-code-pod
spec:
  runtimeClassName: gvisor 
  containers:
  - name: untrusted-container
    image: untrusted-app:latest
```

### 6. Отключение автомонтирования ServiceAccount Token

Если приложению не нужен доступ к Kubernetes API, отключите автомонтирование токена:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-without-k8s-api
spec:
  automountServiceAccountToken: false  # Отключаем монтирование токена
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 3000
  containers:
  - name: app
    image: nginx:alpine
    securityContext:
      readOnlyRootFilesystem: true
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
```

**Проверка:**
```bash
kubectl exec app-without-k8s-api -- ls /var/run/secrets/kubernetes.io/
# → ls: cannot access '/var/run/secrets/kubernetes.io/': No such file or directory
```

### 7. SELinux в Security Context

Для систем с включенным SELinux (RHEL, CentOS, Fedora):

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-selinux
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
  containers:
  - name: app
    image: nginx:alpine
    securityContext:
      seLinuxOptions:
        user: "system_u"
        role: "system_r"
        type: "container_t"
        level: "s0:c123,c456"  # MLS уровень
```

**Проверка:**
```bash
# На узле с SELinux
ps -eZ | grep <pod-container-pid>
# → system_u:system_r:container_t:s0:c123,c456  12345 ?  00:00:00 nginx
```

### 8. Sysctl в Security Context

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-sysctls
spec:
  securityContext:
    runAsNonRoot: true
    sysctls:
    - name: net.core.somaxconn        # Безопасный sysctl
      value: "1024"
    - name: net.ipv4.ip_local_port_range
      value: "1024 65535"
  containers:
  - name: app
    image: nginx:alpine
```

**Проверка:**
```bash
kubectl exec app-with-sysctls -- sysctl net.core.somaxconn
# → net.core.somaxconn = 1024
```

**Небезопасные sysctls** (требуют `--allowed-unsafe-sysctls` на kubelet):
```bash
# На узле (в kubelet конфигурации)
--allowed-unsafe-sysctls=net.ipv4.ip_forward,kernel.shmmax
```

### 9. supplementalGroups для доступа к NFS

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-nfs-access
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 3000
    supplementalGroups: [5000, 5001]  # Дополнительные GID для NFS
    fsGroup: 2000
  containers:
  - name: app
    image: nginx:alpine
    volumeMounts:
    - name: nfs-volume
      mountPath: /data
  volumes:
  - name: nfs-volume
    nfs:
      server: 10.0.1.100
      path: /exports/data
```

**Проверка:**
```bash
kubectl exec app-nfs-access -- id
# → uid=1000 gid=3000 groups=3000,2000,5000,5001
```

## Проверка корректности настроек

После создания пода с Security Context важно убедиться, что настройки применены корректно.

**Вход в контейнер для проверки:**

```bash
kubectl exec -it <pod-name> -- sh
```

**Проверка пользователя и групп процесса:**

```bash
# Проверка текущего пользователя, UID, GID и дополнительных групп
id 
# → uid=1000 gid=3000 groups=2000
```

**Проверка прав на смонтированных томах:**

```bash
cd /data/demo
ls -la
# Файлы должны принадлежать пользователю uid=1000 и группе fsGroup (например, gid=2000)

# Попытка записи в папку root завершится ошибкой
touch /test-file 
# → Permission denied
```

**Важное ограничение:** Security Context на уровне пода (`spec.securityContext`) применяется ко всем контейнерам в поде. Настройки на уровне контейнера имеют приоритет.

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в `CrashLoopBackOff` после добавления `runAsNonRoot: true`** | Образ использует root по умолчанию (нет инструкции `USER` в Dockerfile) | Добавьте `runAsUser: <UID>` в securityContext, либо пересоберите образ с инструкцией `USER 1000`. |
| **`Permission denied` на смонтированном volume** | Неверный `fsGroup` или `defaultMode` | Укажите `fsGroup` в `spec.securityContext` пода. Для NFS/cephfs убедитесь, что GID разрешен на сервере. |
| **`Permission denied` при записи в корневую ФС** | Включен `readOnlyRootFilesystem: true` | Монтируйте `emptyDir` в `/tmp`, `/var/cache/nginx`, `/var/run` и другие каталоги, куда приложение пишет. |
| **Nginx/Apache падает на порту 80** | `runAsNonRoot: true` + порт < 1024 | Используйте unprivileged образ (`nginx-unprivileged`) или перенастройте на порт > 1024. |
| **PSA `enforce: restricted` блокирует под** | Нарушение политик PSS (отсутствует `seccompProfile`, есть `hostPath` и т.д.) | Используйте `--dry-run=server` для проверки перед деплоем. Исправьте `securityContext`. |
| **sysctl не применяется** | Sysctl небезопасный и не добавлен в `--allowed-unsafe-sysctls` на kubelet | Добавьте sysctl в список разрешенных или используйте безопасный sysctl. |
| **SELinux блокирует доступ к томам** | Несовпадение метки SELinux контейнера и файла на хосте | Проверьте `ls -Z` на хосте. Добавьте `:z` к volumeMount или настройте `seLinuxOptions`. |
| **Automounted токен утекает в приложение** | `automountServiceAccountToken` не отключен (по умолчанию `true`) | Установите `automountServiceAccountToken: false` в Pod spec. |

### Диагностические команды

```bash
# Просмотр securityContext пода
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].securityContext}'

# Просмотр пользователя контейнера
kubectl exec <pod-name> -- id
# → uid=1000 gid=3000 groups=3000,2000,5000

# Просмотр процесса (PID 1) и его пользователя
kubectl exec <pod-name> -- ps aux
# → USER  PID %CPU %MEM    VSZ   RSS TTY  STAT START   TIME COMMAND
# → 1000    1  0.0  0.0   2344  1234 ?    Ss   10:00   0:00 nginx: master process

# Проверка прав на файле в контейнере
kubectl exec <pod-name> -- ls -la /data/
# → drwxr-xr-x 2 1000 3000 4096 Aug 31 10:00 .

# Проверка, что корневая ФС только для чтения
kubectl exec <pod-name> -- touch /test-file
# → touch: cannot touch '/test-file': Read-only file system

# Проверка automountServiceAccountToken
kubectl get pod <pod-name> -o jsonpath='{.spec.automountServiceAccountToken}'

# Проверка PSA меток неймспейса
kubectl get ns <namespace> -o jsonpath='{.metadata.labels}' | grep pod-security

# Просмотр событий PSA (отклонения)
kubectl get events --field-selector reason=FailedCreate --namespace <namespace>
```

## Дополнительная информация

Security Context — базовый инструмент обеспечения многоуровневой защиты (security-in-depth). Он дополняет сетевые политики и Pod Security Standards, создавая фундамент для безопасной работы приложений.

### Типичные ошибки (Antipatterns)

1. **Запуск от root без необходимости** — основной вектор атаки. Используйте `runAsNonRoot: true` + `runAsUser: 1000`.
2. **Отсутствие `readOnlyRootFilesystem`** — позволяет атакующему записать бэкдор в контейнер.
3. **`privileged: true` без крайней необходимости** — эквивалентен root на хосте. Используйте `capabilities` с `drop: ["ALL"]` + `add` только нужных.
4. **Несбрасывание capabilities** — по умолчанию Docker дает контейнеру ~14 capabilities. Используйте `drop: ["ALL"]`.
5. **Токен ServiceAccount в production** — если приложению не нужен API K8s, отключите `automountServiceAccountToken: false`.
6. **Отсутствие `seccompProfile`** — без него контейнер может выполнять любые syscall. Используйте `RuntimeDefault`.

### Связь с другими механизмами безопасности

Security Context работает в связке с:
- **[Pod Security Admission](../../Kubernetes/Base/namespace.md#безопасность-pod-security-admission)** — контроль на уровне Namespace.
- **[NetworkPolicy](../../Kubernetes/Networking/Network/network_policy.md)** — контроль сетевого доступа.
- **[RBAC](./rbac/rbac_overview.md)** — контроль доступа к API Kubernetes.
- **[Linux Capabilities](../../Linux/Security/Mechanisms/Capabilities.md)** — детали работы capabilities в ядре Linux.
- **[Seccomp](../../Linux/Security/Mechanisms/Seccomp.md)** — фильтрация syscall.
- **[AppArmor](../../Linux/Security/Mechanisms/AppArmor.md)** — контроль доступа к файлам и ресурсам.

## См. также

* [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
* [Конфигурация Security Context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/)
* [Применение Security Context через Kyverno](./kyverno/policies/practical_scenarios.md)
* [Лучшие практики Pod](../Base/Pod/pod_best_practices.md) — минимальный безопасный securityContext для production.
* [User Namespaces в Pod](../Base/Pod/user_namespaces.md) — изоляция root внутри контейнера.
* [Ephemeral Containers: Debug Profiles](../Base/Pod/ephemeral_containers.md) — профили безопасности для отладки.
