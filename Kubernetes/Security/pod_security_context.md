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
*   **`seLinuxOptions`** — позволяет назначать SELinux (Security-Enhanced Linux) метки для процессов в контейнере.
*   **`sysctls`** — позволяет настраивать параметры ядра (sysctl) для пода. Разделяются на «безопасные» (разрешены по умолчанию) и «небезопасные» (требуют явного разрешения в конфигурации kubelet).
*   **`windowsOptions`** — специфичные для Windows настройки, такие как `RunAsUserName` или интеграция с GMSA (Group Managed Service Accounts).

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

## Дополнительная информация

Security Context — базовый инструмент обеспечения многоуровневой защиты (security-in-depth). Он дополняет сетевые политики и Pod Security Standards, создавая фундамент для безопасной работы приложений.

## См. также

* [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
* [Конфигурация Security Context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/)
* [Применение Security Context через Kyverno](./kyverno/policies/practical_scenarios.md)
