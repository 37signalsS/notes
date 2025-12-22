# Security Context в Kubernetes

**Security Context** — это набор настроек в Kubernetes, определяющих права доступа и ограничения для подов (Pod) и контейнеров (Container). Эти настройки являются ключевым элементом для реализации **принципа наименьших привилегий** и предотвращения несанкционированного доступа к ресурсам.

## Зачем это нужно?

*   **Ограничение прав контейнеров**: Минимизация ущерба в случае компрометации приложения.
*   **Предотвращение доступа к ресурсам узла**: Изоляция контейнеров от хостовой системы.
*   **Соответствие требованиям безопасности и compliance**: Выполнение стандартов безопасности (например, PCI DSS, HIPAA).
*   **Защита от атак "escape" из контейнера**: Снижение риска захвата контроля над узлом (node).

## Уровни применения

Настройки Security Context могут быть определены на двух уровнях:

1.  **`spec.securityContext` (уровень пода):** Применяется ко всем контейнерам в поде.
2.  **`spec.containers[*].securityContext` (уровень контейнера):** Применяется к отдельному контейнеру и переопределяет настройки, заданные на уровне пода, если они конфликтуют.

## Основные параметры

Ниже представлены ключевые поля, используемые в `securityContext` для управления привилегиями.

### `runAsNonRoot`, `runAsUser`, и `runAsGroup`

*   `runAsNonRoot: true`: Гарантирует, что контейнер не будет запущен от имени пользователя `root`. Kubelet проверит это перед запуском контейнера и завершится ошибкой, если образ пытается запуститься от `root`.
*   `runAsUser`: Указывает UID пользователя, под которым будет запущен процесс в контейнере.
*   `runAsGroup`: Указывает GID основной группы, под которой будет запущен процесс в контейнере.
*   **Использование:** Запуск процессов от имени непривилегированного пользователя является базовой практикой безопасности. `runAsNonRoot: true` в сочетании с `runAsUser: <UID>` (где UID > 0) — надежный способ этого добиться.

### `readOnlyRootFilesystem`

*   `readOnlyRootFilesystem: true`: Делает корневую файловую систему контейнера доступной только для чтения.
*   **Использование:** Защищает от модификации системных файлов и установки вредоносного ПО. Приложения, которым требуется записывать данные, могут использовать тома (`volumes`), которые монтируются в указанные пути.

### `allowPrivilegeEscalation`

*   `allowPrivilegeEscalation: false`: Предотвращает получение процессом в контейнере больших привилегий, чем у его родительского процесса. Это достигается путем установки флага `no_new_privs` на процессе.
*   **Использование:** Критически важная настройка для блокировки атак, использующих бинарные файлы с `setuid` или `setgid` для повышения привилегий.

### `capabilities`

*   `capabilities`: Позволяет тонко настраивать [Linux capabilities](https://man7.org/linux/man-pages/man7/capabilities.7.html), вместо предоставления полных привилегий root.
*   **Синтаксис:**
    *   `drop: ["ALL"]`: Удаляет все стандартные capabilities, предоставленные средой выполнения контейнеров.
    *   `add: ["NET_BIND_SERVICE"]`: Добавляет только необходимые capabilities. Например, `NET_BIND_SERVICE` позволяет процессу привязываться к портам ниже 1024, не требуя прав `root`.
*   **Использование:** Предпочтительный способ предоставления повышенных прав, так как он более гранулирован и безопасен, чем `privileged: true`.

### `seccompProfile`

*   `seccompProfile`: Ограничивает системные вызовы (syscalls), которые может выполнять контейнер, с помощью [seccomp](https://man7.org/linux/man-pages/man2/seccomp.2.html).
*   **Профили:**
    *   `type: RuntimeDefault`: Использует профиль по умолчанию, предоставляемый средой выполнения контейнеров (например, Docker, containerd). Это рекомендуемая базовая настройка.
    *   `type: Unconfined`: Отключает seccomp.
    *   `type: Localhost`: Использует кастомный профиль, загруженный на узел (`<kubelet-root-dir>/seccomp/<path>`).
*   **Использование:** Значительно сужает поверхность атаки на ядро Linux, блокируя доступ к неиспользуемым или опасным системным вызовам.

### `privileged`

*   `privileged: true`: Предоставляет контейнеру полные привилегии, эквивалентные правам `root` на хостовой системе. Контейнер получает доступ ко всем устройствам (`/dev`) и возможность изменять параметры ядра.
*   **Риски:** **Крайне опасно.** Скомпрометированный привилегированный контейнер означает компрометацию всего узла.
*   **Использование:** Следует избегать любой ценой. Применяется только в исключительных случаях (например, для запуска Docker-in-Docker или агентов, работающих с ядром).

### `fsGroup`

*   `fsGroup`: Указывает GID, который будет назначен для всех томов, примонтированных к поду. Владение томами изменяется на этот GID.
*   **Использование:** Гарантирует, что процессы в контейнере имеют правильные разрешения для чтения/записи на смонтированных томах, особенно при работе с `Persistent Volumes`.

## Pod Security Standards (PSS) и Pod Security Admission (PSA)

PSA/PSS — современная замена PSP и база для baseline безопасности. PodSecurityPolicy (PSP) удалены в Kubernetes v1.25.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    # 1. В аудит-логи API-сервера попадут ВСЕ поды, которые не соответствуют самому высокому стандарту restricted. Это даёт полную картину.
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
    # 2. Разработчики сразу увидят предупреждение в kubectl, если их под нарушает даже базовые требования.
    pod-security.kubernetes.io/warn: baseline
    pod-security.kubernetes.io/warn-version: latest
    # 3. Фактически не блокирует ничего, кроме совсем уж экзотических случаев. Это позволяет начать сбор данных, не ломая рабочие процессы. По мере готовности можно повысить уровень enforce до baseline, а затем и до restricted.
    pod-security.kubernetes.io/enforce: privileged
    pod-security.kubernetes.io/enforce-version: latest
```

Для более сложных политик можно использовать: [Kyverno](../../Kubernetes/Security/kyverno.md) или *OPA Gatekeeper*.

## Примеры

### 1. Настройки на уровне пода

Этот пример применяет `securityContext` ко всем контейнерам внутри пода.

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

### 2. Настройки на уровне контейнера

Этот пример демонстрирует гранулярную настройку для отдельного контейнера, которая переопределит любые аналогичные настройки на уровне пода.

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
        type: RuntimeDefault           # Стандартный seccomp профиль
```

## Значение Security Context

Security Context — это базовый инструмент для обеспечения **security-in-depth** в Kubernetes. Он не заменяет сетевые политики и Pod Security Standards, но создаёт фундамент для безопасной работы приложений, значительно снижая поверхность атаки.

## Дополнительные материалы

*   **Pod Security Standards**: [Официальная документация Kubernetes](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
*   **Конфигурация Security Context**: [Официальная документация Kubernetes](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/)
