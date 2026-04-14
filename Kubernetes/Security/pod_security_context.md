# Security Context в Kubernetes

## Определения

**Security Context** — набор настроек в Kubernetes, определяющий права доступа и ограничения для подов (Pod) и контейнеров (Container). Ключевой элемент реализации **принципа наименьших привилегий** и предотвращения несанкционированного доступа к ресурсам.

## Основные концепции

### Назначение и уровни применения

* **Назначение:** ограничение прав контейнеров, предотвращение доступа к ресурсам узла, соответствие требованиям безопасности, защита от атак типа "escape" из контейнера.
* **Уровни применения:** настройки определяются на уровне пода (`spec.securityContext`) и/или на уровне контейнера (`spec.containers[*].securityContext`). Настройки контейнера переопределяют настройки пода при конфликте.

### Основные параметры

* **`runAsNonRoot: true`** — гарантирует запуск контейнера не от имени пользователя `root`.
* **`runAsUser` / `runAsGroup`** — указывают UID (User ID) пользователя и GID (Group ID) основной группы, под которыми будет запущен процесс в контейнере.
  * **Использование:** запуск процессов от непривилегированного пользователя — базовая практика безопасности.
* **`readOnlyRootFilesystem: true`** — делает корневую файловую систему контейнера доступной только для чтения, защищая от нежелательных модификаций.
* **`allowPrivilegeEscalation: false`** — предотвращает получение процессом в контейнере больших привилегий, чем у его родительского процесса.
  * **Механизм:** устанавливает флаг `no_new_privs` в ядре Linux. Блокирует получение дополнительных привилегий через setuid/setgid-бинарные файлы или Linux capabilities.
* **`capabilities`** — позволяет тонко настраивать [Linux capabilities](https://man7.org/linux/man-pages/man7/capabilities.7.html). Используется для удаления (`drop: ["ALL"]`) или добавления (`add: ["NET_BIND_SERVICE"]`) определённых возможностей.
  * **Использование:** предпочтительный и более безопасный способ предоставления повышенных прав по сравнению с `privileged: true`.
* **`seccompProfile`** — ограничивает системные вызовы (syscall), которые может выполнять контейнер, с помощью [seccomp](https://man7.org/linux/man-pages/man2/seccomp.2.html). Рекомендуется `type: RuntimeDefault`.
  * **Использование:** значительно сужает поверхность атаки на ядро Linux.
* **`privileged: true`** — **крайне опасно**, предоставляет контейнеру полные привилегии, эквивалентные правам `root` на хостовой системе. Следует избегать.
* **`fsGroup`** — указывает GID, который будет назначен для всех томов, примонтированных к поду, обеспечивая правильные разрешения для чтения/записи.
  * **Поведение:** файлы, создаваемые в томах, наследуют указанную группу. Владелец файла остаётся тем, под которым запущен процесс, но группа всегда соответствует `fsGroup`.
* **`seLinuxOptions`** — позволяет назначать SELinux (Security-Enhanced Linux) метки для процессов в контейнере.

## Pod Security Standards (PSS) и Pod Security Admission (PSA)

**PSS (Pod Security Standards)** — набор из трёх политик безопасности, определяющих допустимые конфигурации подов в кластере:

- **`privileged`** — без ограничений (аналог отсутствия политик).
- **`baseline`** — запрещает известные опасные конфигурации, но допускает большинство стандартных workload.
- **`restricted`** — максимально строгая политика, требующая соблюдения лучших практик (не-root, без privilege escalation, drop всех capabilities).

**PSA (Pod Security Admission)** — встроенный контроллер (admission controller) Kubernetes, применяющий PSS на уровне неймспейсов. Заменяет PodSecurityPolicy (PSP), удалённый в Kubernetes v1.25.

PSA работает через метки неймспейса и поддерживает три режима:

- **`enforce`** — отклоняет поды, не соответствующие политике.
- **`audit`** — пропускает поды, но записывает нарушения в аудит-логи API-сервера.
- **`warn`** — пропускает поды, но возвращает предупреждение пользователю через `kubectl`.

## Практические сценарии

### 1. Настройки `securityContext` на уровне пода

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

### 2. Настройки `securityContext` на уровне контейнера

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

### 4. Верификация Security Context в работающем поде

После создания пода с Security Context важно убедиться, что настройки применены корректно.

**Вход в контейнер для проверки:**

```bash
kubectl exec -it <pod-name> -- sh
# или для bash-оболочки
kubectl exec -it <pod-name> -- bash
```

**Проверка пользователя и групп процесса:**

```bash
# Просмотр таблицы процессов — все процессы должны быть запущены от указанного UID
ps aux

# Проверка текущего пользователя, UID, GID и дополнительных групп
id
# → uid=1000 gid=3000 groups=2000
```

**Проверка прав на смонтированных томах:**

```bash
cd /data/demo
ls -la
# Файлы должны принадлежать пользователю uid=1000 и группе, указанной в fsGroup (например, gid=2000)

# Попытка записи в папку, принадлежащую root, завершится ошибкой
touch /test-file
# → Permission denied
```

> **Важное ограничение:** Security Context, заданный на уровне пода (`spec.securityContext`), применяется **ко всем контейнерам в поде** одинаково. Невозможно задать разные `runAsUser` для разных контейнеров на уровне пода — для этого нужно использовать `securityContext` на уровне каждого контейнера.

## Дополнительная информация

Security Context — базовый инструмент для обеспечения **security-in-depth** в Kubernetes. Он не заменяет сетевые политики или Pod Security Standards, но создаёт фундамент для безопасной работы приложений, значительно снижая поверхность атаки.

## См. также

- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
- [Конфигурация Security Context](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/)
- [Применение Security Context через Kyverno](./kyverno/policies/practical_scenarios.md)
