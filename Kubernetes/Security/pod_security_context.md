# Security Context в Kubernetes

## Определения

**Security Context** — это набор настроек в Kubernetes, определяющих права доступа и ограничения для подов (Pod) и контейнеров (Container). Эти настройки являются ключевым элементом для реализации **принципа наименьших привилегий** и предотвращения несанкционированного доступа к ресурсам.

## Основные концепции

### Назначение и уровни применения

*   **Назначение:** Ограничение прав контейнеров, предотвращение доступа к ресурсам узла, соответствие требованиям безопасности, защита от атак "escape" из контейнера.
*   **Уровни применения:** Настройки могут быть определены на уровне пода (`spec.securityContext`) и/или на уровне контейнера (`spec.containers[*].securityContext`), при этом настройки контейнера переопределяют настройки пода в случае конфликта.

### Основные параметры

*   **`runAsNonRoot: true`**: Гарантирует запуск контейнера не от имени пользователя `root`.
*   **`runAsUser` / `runAsGroup`**: Указывают UID пользователя и GID основной группы, под которыми будет запущен процесс в контейнере.
    *   **Использование:** Запуск процессов от имени непривилегированного пользователя является базовой практикой безопасности.
*   **`readOnlyRootFilesystem: true`**: Делает корневую файловую систему контейнера доступной только для чтения, защищая от нежелательных модификаций.
*   **`allowPrivilegeEscalation: false`**: Предотвращает получение процессом в контейнере больших привилегий, чем у его родительского процесса.
*   **`capabilities`**: Позволяет тонко настраивать [Linux capabilities](https://man7.org/linux/man-pages/man7/capabilities.7.html). Используется для удаления (`drop: ["ALL"]`) или добавления (`add: ["NET_BIND_SERVICE"]`) определенных возможностей.
    *   **Использование:** Предпочтительный и более безопасный способ предоставления повышенных прав по сравнению с `privileged: true`.
*   **`seccompProfile`**: Ограничивает системные вызовы (syscalls), которые может выполнять контейнер, с помощью [seccomp](https://man7.org/linux/man-pages/man2/seccomp.2.html). Рекомендуется `type: RuntimeDefault`.
    *   **Использование:** Значительно сужает поверхность атаки на ядро Linux.
*   **`privileged: true`**: **Крайне опасно**, предоставляет контейнеру полные привилегии, эквивалентные правам `root` на хостовой системе. Следует избегать.
*   **`fsGroup`**: Указывает GID, который будет назначен для всех томов, примонтированных к поду, обеспечивая правильные разрешения для чтения/записи.

### Pod Security Standards (PSS) и Pod Security Admission (PSA)

PSS/PSA — это современный механизм контроля безопасности подов, заменивший PodSecurityPolicy (PSP) с версии Kubernetes v1.25. Он работает на уровне неймспейсов и определяет три политики: `privileged`, `baseline` и `restricted`.

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
        type: RuntimeDefault           # Стандартный seccomp профиль
```

### 3. Конфигурация Pod Security Admission (PSA) для неймспейса

Пример конфигурации для неймспейса `production` с использованием PSS/PSA:
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

## Дополнительная информация

Security Context является базовым инструментом для обеспечения **security-in-depth** в Kubernetes. Он не заменяет сетевые политики или Pod Security Standards, но создает фундамент для безопасной работы приложений, значительно снижая поверхность атаки.

*   **Pod Security Standards**: [Официальная документация Kubernetes](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
*   **Конфигурация Security Context**: [Официальная документация Kubernetes](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/)
