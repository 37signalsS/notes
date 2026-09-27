# CreateContainerConfigError: Определения

## Определения

**CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки к запуску контейнера. Оно означает, что `kubelet` не смог сформировать полную конфигурацию контейнера из-за проблем с внешними зависимостями (ConfigMap, Secret, Volumes) или внутренними механизмами разрешения метаданных (Downward API).

В системной иерархии ошибок Kubernetes эта проблема занимает место между **Scheduling** (назначение на узел) и **Container Runtime Execution** (непосредственный запуск процессов). Поскольку контейнер еще не создан в Container Runtime (CRI), логи приложения (`kubectl logs`) отсутствуют, и диагностика полностью полагается на события API-сервера (`kubectl describe pod`).

### Отличие от других ошибок создания контейнера

| Ошибка | Причина | Этап |
| :--- | :--- | :--- |
| **CreateContainerConfigError** | Не удалось разрешить зависимости (ConfigMap, Secret, Volumes, Downward API) | Подготовка конфигурации до CRI |
| **CreateContainerError** | Технический сбой CRI (монтирование `/proc`, нехватка ресурсов, SELinux) | Вызов CRI `CreateContainer` |
| **InvalidImageName** | Ошибка парсинга имени образа (невалидный тег, отсутствие registry) | Валидация образа |
| **ImagePullBackOff** | Не удалось скачать образ из реестра (таймаут, аутентификация) | Pull образа |
| **CrashLoopBackOff** | Приложение запустилось, но завершилось с ошибкой | Выполнение процесса |

## Основные концепции

### Механизм возникновения (Технический Workflow)

Ошибка возникает в рабочем цикле `kubelet` (Pod Worker) до вызова CRI-метода `CreateContainer`. Полный процесс занимает от долей секунды до нескольких секунд в зависимости от количества зависимостей и скорости API-сервера.

1.  **SyncPod Loop:** `kubelet` обнаруживает новый под, назначенный на узел, через механизм Watch API-сервера. Запускается горутина Pod Worker, которая управляет жизненным циклом пода.
2.  **Volume Admission:** Проверка и монтирование томов. Если PVC не существует или не привязан — возникает задержка, которая может перерасти в ошибку конфигурации. Для ephemeral volumes (emptyDir, hostPath) проверяется локальная файловая система узла.
3.  **Dependency Resolution (Критическая фаза):**
    *   `kubelet` запрашивает через API-сервер содержимое всех ConfigMap и Secret, указанных в `env`, `envFrom` и `volumes`. Запросы выполняются параллельно для оптимизации.
    *   Генерируются спецификации для Downward API (формирование файлов или переменных с метаданными пода).
    *   Для **SidecarContainers** (Native Sidecars, K8s 1.29+) зависимости разрешаются в строгом порядке до запуска основных контейнеров.
    *   Проверяются `imagePullSecrets` для доступа к приватным реестрам.
4.  **CRI Config Generation:** `kubelet` пытается собрать `ContainerConfig` для передачи в рантайм (containerd/CRI-O). Включает подготовку bind mounts, environment variables и security contexts.
5.  **Блокировка:** Если на шаге 3 или 4 происходит сбой (ресурс не найден, ошибка прав RBAC, некорректный ключ), `kubelet` выставляет статус `CreateContainerConfigError` и прекращает попытку создания контейнера.

### Таймауты и повторные попытки

При возникновении ошибки `kubelet` не прерывает цикл синхронизации, а планирует повторную попытку с экспоненциальной задержкой:

| Попытка | Задержка | Максимум |
| :--- | :--- | :--- |
| 1-5 | 10 секунд | 50 секунд |
| 6-10 | 30 секунд | 5 минут |
| 11+ | 60 секунд | 10 минут |

Если зависимость (ConfigMap/Secret) появится в API-сервере, следующая попытка `kubelet` завершится успешно. Если ошибка сохраняется дольше 5 минут, под помечается как «старый» и логируется реже для снижения нагрузки.

### Типы зависимостей и причины ошибок (2024-2025)

| Ресурс | Роль | Типичная причина ошибки |
| :--- | :--- | :--- |
| **ConfigMap** | Конфиг-файлы, ENV | Отсутствие ресурса, опечатка в ключе, превышение лимита размера (1MiB). |
| **Secret** | Секретные данные | Отсутствие ресурса, недостаток прав у `ServiceAccount` (RBAC), истечение срока действия токена. |
| **PVC / CSI** | Постоянные диски | Ошибки провижининга, конфликт зон (AZ), ошибки в кастомных атрибутах CSI-драйвера. |
| **Projected Volume** | Агрегация данных | Сбой хотя бы одного источника (например, ServiceAccountToken не может быть сгенерирован). |
| **Downward API** | Метаданные пода | Обращение к `status.podIP` или `status.hostIP` до их назначения, опечатки в `fieldPath`. |
| **Sidecar Containers** | Вспомогательные процессы | Недоступность зависимостей, специфичных для init-контейнеров с `restartPolicy: Always`. |

### Важные параметры управления

*   **`optional: true`**: Директива, позволяющая `kubelet` игнорировать отсутствие ConfigMap или Secret. Если ресурс помечен как опциональный, переменные окружения будут пропущены, а файлы в томах не создадутся.
*   **`immutable: true`**: Позволяет помечать ConfigMap/Secret как неизменяемые. Это снижает нагрузку на API-сервер, так как `kubelet` перестает отслеживать их изменения через Watch-запросы.
*   **Recursive Read-Only Mounts (v1.30+):** Новая функциональность монтирования томов, ошибки в которой на этапе конфигурации могут блокировать старт.

## Практические сценарии

### Сценарий 1: Сбой Downward API

Downward API позволяет пробрасывать метаданные пода (имя, namespace, IP) внутрь контейнера. Ошибка возникает при обращении к полям, которые не могут быть разрешены на этапе старта.

**Пример ошибки в манифесте:**
```yaml
env:
- name: MY_POD_IP
  valueFrom:
    fieldRef:
      fieldPath: status.podIP # Может быть пустым на очень ранних стадиях в специфичных CNI
```
**Результат:** Если `kubelet` не может получить значение поля, он выставляет `CreateContainerConfigError`.

**Допустимые поля для Downward API (K8s 1.30+):**
- `metadata.name`, `metadata.namespace`, `metadata.uid`
- `metadata.labels['<KEY>']`, `metadata.annotations['<KEY>']`
- `spec.nodeName`, `spec.serviceAccountName`
- `status.podIP`, `status.hostIP`
- `resourceFieldRef` для CPU/memory limits и requests

**Решение:** Убедитесь, что поле `fieldPath` указывает на допустимое значение. Если под еще не получил IP (ранняя стадия), используйте `spec.nodeName` вместо `status.podIP` или добавьте `optional: true`.

### Сценарий 2: Ошибки RBAC при доступе к секретам

Даже если секрет существует, под не сможет его прочитать, если его `ServiceAccount` не имеет соответствующих прав.

**Диагностика через события:**
```text
Events:
  Warning  Failed  10s  kubelet  Error: secret "vault-token" is forbidden: User "system:serviceaccount:default:myapp-sa" cannot get resource "secrets"
```

**Типичные RBAC-ошибки:**
- Отсутствие Role/ClusterRole с разрешением `get` на ресурс `secrets`
- Отсутствие RoleBinding/ClusterRoleBinding для ServiceAccount
- Конфликт с NodeRestriction (для `kubelet`)

**Диагностика:**
```bash
# Проверка прав ServiceAccount
kubectl auth can-i get secret/vault-token --as=system:serviceaccount:default:myapp-sa
# → no

# Просмотр всех RoleBinding в Namespace
kubectl get rolebindings -n default -o wide
```

**Решение:** Создайте Role с разрешением `get` на `secrets` и привяжите его к ServiceAccount через RoleBinding.

### Сценарий 3: Отсутствие ключа в ConfigMap/Secret

Ресурс существует, но в нем отсутствует ключ, указанный в манифесте пода.

**Пример манифеста:**
```yaml
env:
- name: DB_HOST
  valueFrom:
    configMapKeyRef:
      name: app-config
      key: database.host  # Ключ отсутствует в ConfigMap
```

**Диагностика:**
```bash
# Проверка ключей в ConfigMap
kubectl get configmap app-config -o jsonpath='{.data}' | jq 'keys'
# → ["app.name", "app.version"]  # database.host отсутствует

# Проверка события пода
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].state.waiting.message}'
# → configmaps "app-config" not found: key "database.host" not found
```

**Решение:** Добавьте недостающий ключ в ConfigMap или скорректируйте манифест пода. Для необязательных параметров используйте `optional: true`.

### Сценарий 4: Ошибка монтирования Projected Volume

Projected Volume объединяет несколько источников (Secret, ConfigMap, Downward API, ServiceAccountToken). Сбой хотя бы одного источника блокирует запуск.

**Пример манифеста:**
```yaml
volumes:
- name: vault-token
  projected:
    sources:
    - secret:
        name: vault-token
        items:
        - key: token
          path: vault/token
    - configMap:
        name: vault-config  # Этот ConfigMap не существует
        items:
        - key: url
          path: vault/config/url
```

**Ошибка:**
```text
Events:
  Warning  Failed  kubelet  Error: projected volume "vault-token": configmap "vault-config" not found
```

**Диагностика:**
```bash
# Проверка всех источников, указанных в манифесте
kubectl get secret vault-token,configmap vault-config -n <namespace>
```

**Решение:** Убедитесь, что все источники в Projected Volume существуют. Для необязательных источников используйте `optional: true`.

### Сценарий 5: Конфликт immutable ConfigMap с запущенным Pod

Если ConfigMap помечен как `immutable: true` и содержит некорректные данные, под не сможет запуститься до пересоздания ConfigMap.

**Пример:**
```bash
# ConfigMap создан с ошибкой
kubectl create configmap app-config --from-literal=database.host=wrong-host --dry-run=client -o yaml | kubectl apply -f -
kubectl patch configmap app-config -p '{"metadata":{"annotations":{"immutable":"true"}}}'

# Pod не может запуститься
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].state.waiting.message}'
# → configmap "app-config" is immutable: key "database.host" has wrong value
```

**Решение:** Создайте новый ConfigMap с правильными данными и обновите Pod/Deployment для использования нового ресурса. Иммутабельные ConfigMap нельзя редактировать.

## Граничные случаи и ограничения

### Неочевидные сценарии возникновения ошибки

1.  **Race condition с созданием Secret:** Если Pod и Secret создаются одновременно (например, через один манифест с `---`), `kubelet` может попытаться разрешить зависимости до создания Secret. В этом случае ошибка временная и исправляется автоматически при следующем цикле синхронизации.

2.  **Namespace mismatch:** ConfigMap/Secret создаются в другом Namespace. Это одна из самых частых ошибок, особенно при использовании Helm или Kustomize с неправильно настроенными переменными окружения.

3.  **Превышение лимита размера:** Максимальный размер ConfigMap и Secret — **1 MiB**. При превышении лимита ресурс не создается или `kubelet` не может его прочитать.

4.  **Поврежденные данные:** Если ConfigMap содержит невалидный JSON/YAML (для mounted volumes), `kubelet` может не смонтировать том.

5.  **Конфликт с Security Context:** Если `securityContext.runAsNonRoot: true` указан в поде, но образ запускает процесс от root, контейнер не запустится. Однако это ошибка `CreateContainerError`, а не `CreateContainerConfigError`.

### Ограничения Kubernetes

1.  **Нет кэширования:** `kubelet` не кэширует зависимости между попытками. Каждый цикл синхронизации запрашивает данные заново через API-сервер.

2.  **Синхронная обработка:** Если один ConfigMap недоступен, все остальные зависимости также блокируются, даже если они доступны.

3.  **Ограничение на количество переменных:** Kubernetes не накладывает жестких лимитов на количество переменных окружения, но слишком большое количество может замедлить запуск пода.

4.  **Отсутствие каталога ошибок:** Kubernetes не предоставляет централизованный каталог ошибок CreateContainerConfigError. Каждый случай требует индивидуальной диагностики через Events.

### Особенности для StatefulSet и DaemonSet

- **StatefulSet:** Ошибка в конфигурации одного пода не влияет на другие, но предотвращает создание последующих подов в порядке обновления.
- **DaemonSet:** Ошибка в конфигурации предотвращает запуск пода на всех узлах, где должен работать DaemonSet.
- **Job/CronJob:** Ошибка предотвращает запуск задачи, но не влияет на расписание следующего запуска.

## Дополнительная информация

### Место в жизненном цикле пода

`CreateContainerConfigError` — это «внешняя» ошибка по отношению к приложению. Приложение еще не начало выполняться, поэтому код возврата (exit code) не определен.

**Сравнение с критическими состояниями:**
*   **CreateContainerError**: Технический сбой CRI (например, ошибка монтирования `/proc` или нехватка ресурсов на узле).
*   **InvalidImageName**: Ошибка парсинга имени образа, возникающая до `ImagePullBackOff`.
*   **CrashLoopBackOff**: Приложение запустилось, но упало. [Подробнее](../pod_crash_loop_back_off/common_cases_and_solutions.md).

### Автоматическое восстановление

Kubernetes использует экспоненциальную задержку (Exponential Backoff) для повторных попыток. Как только зависимость (ConfigMap/Secret) появится в API-сервере, `kubelet` подхватит её в следующем цикле синхронизации (обычно < 10 секунд).

### Влияние на рабочую нагрузку

- **Без эластичности:** Ошибка не влияет на другие поды в кластере.
- **С HPA:** Если под не может запуститься, HPA не может масштабировать приложение.
- **С PDB:** Ошибка не считается «прерыванием» и не учитывается в Pod Disruption Budget.
- **С rolling update:** Обновление зависает, пока не будут исправлены все ошибки конфигурации.

### Связанные ресурсы

*   [Диагностика и инструменты](./diagnostics.md)
*   [Проблемы с ConfigMap](./configmap_issues.md)
*   [Проблемы с Secret](./secret_issues.md)
*   [Проблемы с PVC](./pvc_issues.md)
*   [Проблемы с томами](./volume_issues.md)
*   [Проблемы с RBAC](./rbac_issues.md)
*   [CRI и containerd](./cri_and_runtime.md) — Container Runtime Interface, взаимодействие kubelet с рантаймом
*   [Профилактика и мониторинг](./prevention.md)
*   [Жизненный цикл Pod](../../../Base/Pod/pod_lifecycle_and_state.md)
