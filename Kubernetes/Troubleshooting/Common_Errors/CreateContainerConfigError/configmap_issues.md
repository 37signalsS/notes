# CreateContainerConfigError: Проблемы с ConfigMap

## Определения

**ConfigMap-related CreateContainerConfigError** — критическое состояние пода, возникающее на этапе подготовки среды выполнения контейнера, когда агент `kubelet` не может успешно разрешить ссылки на объекты `ConfigMap`. Это блокирует создание контейнера в Container Runtime (CRI), так как внешние зависимости для формирования переменных окружения (`env`, `envFrom`) или файловых проекций (`volumes`) недоступны или некорректны. Поскольку контейнер не запущен, логи приложения отсутствуют, и диагностика полностью полагается на события API-сервера.

В отличие от проблем с Secret (которые аналогичны по механике, но требуют Base64-валидации и шифрования), ConfigMap содержит неконфиденциальные данные. Однако механизм ошибки идентичен: `kubelet` при `SyncPod` не может получить ресурс из API-сервера, и под блокируется до появления зависимости или перезапуска.

### Связь с другими файлами серии

| Файл | Фокус |
| :--- | :--- |
| [definitions.md](./definitions.md) | Общие определения CreateContainerConfigError, жизненный цикл, таймауты |
| [diagnostics.md](./diagnostics.md) | Общий алгоритм диагностики всех причин CreateContainerConfigError |
| [secret_issues.md](./secret_issues.md) | Проблемы с Secret (аналогичная механика, Base64-валидация) |
| [rbac_issues.md](./rbac_issues.md) | Проблемы с RBAC и ServiceAccount (403 Forbidden при чтении ConfigMap) |
| [volume_issues.md](./volume_issues.md) | Проблемы с томами (hostPath, emptyDir, projected, CSI) |
| [configmap_issues.md](./configmap_issues.md) | **Данный файл** — ConfigMap-специфичные причины, диагностика, исправление |
| **Базовые файлы по ConfigMap** | |
| [creation.md](../../../Base/ConfigMap/creation.md) | Создание ConfigMap (декларативный, генеративный, императивный подходы) |
| [pod_usage.md](../../../Base/ConfigMap/pod_usage.md) | Использование ConfigMap в подах (env, volumes, обновления) |
| [best_practices.md](../../../Base/ConfigMap/best_practices.md) | Лучшие практики (иммутабельность, именование, GitOps) |
| [immutable.md](../../../Base/ConfigMap/immutable.md) | Неизменяемые ConfigMap (immutable: true, преимущества) |
| [update_and_rollout.md](../../../Base/ConfigMap/update_and_rollout.md) | Обновление и плавный перезапуск (Hot Reload, Rollout) |

## Основные концепции

### Архитектура разрешения ConfigMap в kubelet

```
API-сервер → kubelet (Pod Worker)
    │
    ├── 1. Pod Spec Analysis
    │   ├── env:    configMapKeyRef → {name, key, optional}
    │   ├── envFrom: configMapRef   → {name, prefix, optional}
    │   └── volumes: configMap      → {name, items[], defaultMode}
    │
    ├── 2. Resolution Phase
    │   ├── GET /api/v1/namespaces/<ns>/configmaps/<name>
    │   ├── Если optional: true → пропуск при 404
    │   └── Если optional: false → блокировка (CreateContainerConfigError)
    │
    ├── 3. Processing Phase
    │   ├── env/envFrom: маппинг ключей → переменные окружения
    │   ├── volumes: создание директории в /var/lib/kubelet/pods/<uid>/volumes/
    │   └── binaryData: декодирование Base64 → запись в файл
    │
    └── 4. CRI Config Generation
        └── Если шаг 2-3 успешен → CreateContainer
            Если шаг 2-3 провалился → CreateContainerConfigError
```

**Ключевой нюанс:** `kubelet` разрешает ConfigMap **до** вызова CRI `CreateContainer`. Если ConfigMap не найден — под получает `CreateContainerConfigError` (не `ContainerCreating`). Диагностика полностью полагается на Events API-сервера.

### Механизм возникновения ошибки (SyncPod Workflow)

1.  **SyncPod Loop:** `kubelet` получает спецификацию пода от API-сервера и запускает цикл синхронизации.
2.  **Dependency Resolution:** Агент идентифицирует все ссылки на ConfigMap в разделах `env`, `envFrom` и `volumes`.
3.  **API Fetching:** `kubelet` запрашивает содержимое объектов через API-сервер.
4.  **Data Processing:**
    *   **env/envFrom:** `kubelet` сопоставляет ключи ресурса с переменными окружения. Если ресурс помечен как обязательный (по умолчанию), любой сбой (404 Not Found или 403 Forbidden) прерывает процесс.
    *   **volumes:** Агент подготавливает локальную директорию на узле (`/var/lib/kubelet/pods/<uid>/volumes/kubernetes.io~configmap/`) и записывает в нее данные.
    *   **projected:** ConfigMap является одним из источников в aggregated volume. Если любой источник отсутствует — весь том не может быть создан.
5.  **Блокировка:** Если разрешение зависимостей не завершено успешно, вызов CRI `CreateContainer` не производится, поду присваивается статус `CreateContainerConfigError`.

### Способы использования ConfigMap и точки отказа

| Способ использования | Точка отказа | Типичная ошибка | Автообновление |
| :--- | :--- | :--- | :--- |
| **`env` (configMapKeyRef)** | Ресурс или ключ не найден | `configmap "x" not found` | **Нет** — требует рестарт |
| **`envFrom` (configMapRef)** | Ресурс не найден | `configmap "x" not found` | **Нет** — требует рестарт |
| **`volumes` (configMap)** | Ресурс не найден | `configmap "x" not found` | **Да** — через ~60 сек |
| **`volumes` + `subPath`** | Ключ не найден в ресурсе | `key "y" not found` | **Нет** — требует рестарт |
| **`projected` (configMap source)** | Один из источников не найден | `projected volume error: configmap "x" not found` | **Да** — через ~60 сек |

### Типичные причины возникновения ошибки (Расширенный каталог)

| Сообщение в Events | Причина | Статус ресурса | Вероятность |
| :--- | :--- | :--- | :--- |
| `configmap "x" not found` | Ресурс не существует в текущем Namespace | **Missing** | Очень высокая |
| `configmaps "x" not found: key "y" not found` | Ресурс существует, но в нем нет требуемого ключа | **Key Missing** | Высокая |
| `forbidden: user "x" cannot get resource "configmaps"` | Недостаточно прав у ServiceAccount пода (RBAC) или блокировка NodeRestriction | **Forbidden** | Средняя |
| `Error: ConfigMap "x" is not a valid configmap` | Превышение лимитов размера или повреждение метаданных | **Invalid** | Низкая |
| `projected volume error: configmap "x" not found` | ConfigMap отсутствует в составе projected volume | **Missing** (projected) | Средняя |
| `unable to mount: configmap "x" has been marked as deleted` | ConfigMap удален после создания пода | **Deleted** | Низкая |
| `subPath "x" not found in configmap "y"` | Ключ не найден при монтировании через subPath | **Key Missing** (subPath) | Средняя |

### Лимиты и параметры управления

*   **Размер:** Максимальный размер одного объекта ConfigMap ограничен **1 MiB** (ограничение etcd). При превышении API-сервер отклоняет запрос с ошибкой `RequestEntityTooLarge`.
*   **BinaryData:** Для нетекстовых данных (сертификаты, `.jks`) используйте поле `binaryData`. Попытка записать бинарный контент в `data` приведет к ошибкам кодировки UTF-8.
*   **Иммутабельность (`immutable: true`):** С K8s 1.21 позволяет оптимизировать работу `kubelet` (отключается Watch). Ресурс нельзя редактировать; для изменений создается новый объект, что гарантирует контролируемый Rollout.
*   **Ключи:** Ключи должны быть валидными POSIX-именами файлов (RFC 1123, до 253 символов, строчные буквы, дефисы, точки). Ключи с `/`, `..`, пробелами или спецсимволами приведут к ошибке монтирования.
*   **Namespace:** ConfigMap является ресурсом уровня пространства имен. Поды могут использовать только те ConfigMap, которые находятся в том же Namespace.

## Алгоритм диагностики

```
CreateContainerConfigError + configMap-related
│
├── 1. Проверить Events пода
│   ├── "configmap 'x' not found" → Проверить existence (шаг 2)
│   ├── "key 'y' not found" → Проверить ключи (шаг 3)
│   ├── "forbidden: user ... cannot get" → Проверить RBAC (шаг 4)
│   ├── "is not a valid configmap" → Проверить размер/данные (шаг 5)
│   ├── "projected volume error" → Проверить все источники projected (шаг 6)
│   └── "subPath not found" → Проверить ключи + subPath (шаг 7)
│
├── 2. Проверить Existence ConfigMap
│   ├── kubectl get configmap <name> -n <namespace> → существует?
│   ├── Если нет → проверить во всех namespace: kubectl get configmap <name> -A
│   └── Если есть, но в другом namespace → исправить манифест пода
│
├── 3. Проверить ключи в ConfigMap
│   ├── kubectl get configmap <name> -o jsonpath='{.data}' | jq 'keys'
│   ├── Сравнить с ключами в манифесте пода
│   ├── Если ключ отсутствует → добавить ключ или исправить манифест
│   └── Если ключ есть, но имя отличается → проверить регистр (case-sensitive)
│
├── 4. Проверить RBAC
│   ├── kubectl auth can-i get configmap/<name> --as=system:serviceaccount:<ns>:<sa>
│   ├── Если нет → создать Role/RoleBinding с правами get
│   └── Если да → проверить NodeRestriction и admission controllers
│
├── 5. Проверить размер и данные
│   ├── kubectl get configmap <name> -o yaml | wc -c → размер в байтах
│   ├── Если > 1 MiB → разбить на несколько ConfigMap или использовать PV
│   └── Если есть binaryData → проверить Base64-валидность
│
├── 6. Проверить все источники projected
│   ├── kubectl get pod <name> -o jsonpath='{.spec.volumes[*].projected.sources}'
│   ├── Для каждого configMap source: kubectl get configmap <name> -n <ns>
│   └── Если любой источник отсутствует → создать его или добавить optional: true
│
├── 7. Проверить subPath
│   ├── kubectl get configmap <name> -o jsonpath='{.data}' | jq 'keys'
│   ├── Сравнить с subPath.path в манифесте пода
│   └── Если ключ не совпадает → исправить subPath или добавить ключ в ConfigMap
│
└── 8. Проверить тип использования
    ├── env/envFrom → требует рестарт для применения изменений
    ├── volumes → автоматическое обновление через ~60 сек
    └── volumes + subPath → требует рестарт для обновления
```

## Практические сценарии

### Сценарий 1: ConfigMap не найден (Namespace mismatch)

Самая частая причина. Ресурс создан в `dev`, а под запущен в `prod`. Или опечатка в имени ConfigMap.

**Диагностика:**
```bash
# Проверка наличия ресурса в нужном namespace
kubectl get configmap app-config -n <namespace>
# → Error from server (NotFound): configmaps "app-config" not found

# Поиск ConfigMap во всех namespace
kubectl get configmap app-config -A
# → No resources found  -- нет ни в одном namespace

# Проверка опечатки: поиск похожих имен
kubectl get configmap -n <namespace> | grep app
# → NAME            DATA   AGE
# → app-config-v2   3      2d  -- возможно, имелся в виду этот
```

**Типичная ошибка в Events:**
```text
Warning  Failed  kubelet  Error: configmap "app-config" not found
```

**Решение:**
1. Создайте ConfigMap в том же Namespace, что и Pod
2. Или исправьте имя ConfigMap в манифесте пода
3. Для использования в другом Namespace — скопируйте ресурс: `kubectl get configmap <name> -o yaml | kubectl apply -n <target-ns> -f -`

### Сценарий 2: Отсутствие ключа (Key mismatch)

Манифест пода ссылается на ключ `DB_HOST`, а в ConfigMap указан `HOST`. Ключи чувствительны к регистру.

**Диагностика:**
```bash
# Просмотр ключей без вывода значений (для больших конфигов)
kubectl get configmap app-config -o jsonpath='{.data}' | jq 'keys'
# → [ "HOST", "PORT" ] -- ключа DB_HOST нет

# Проверка конкретного ключа
kubectl get configmap app-config -o jsonpath='{.data.DB_HOST}' 2>/dev/null
# → пусто или null -- ключ не найден

# Извлечение ключа из манифеста пода
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].env[*].valueFrom.configMapKeyRef.key}'
```

**Типичная ошибка в Events:**
```text
Warning  Failed  kubelet  Error: configmaps "app-config" not found: key "DB_HOST" not found
```

**Решение:**
1. Добавьте недостающий ключ в ConfigMap
2. Или исправьте имя ключа в манифесте пода
3. Для необязательных ключей используйте `optional: true`

### Сценарий 3: Права доступа (RBAC) и NodeRestriction

Даже если ресурс существует, `kubelet` может получить отказ 403 Forbidden.
1. **RBAC:** У ServiceAccount пода нет прав `get` на ConfigMap.
2. **NodeRestriction:** Admission-контроллер запрещает узлу читать конфиги, которые не используются его подами.

**Диагностика:**
```bash
# Имитация проверки прав от имени SA пода
kubectl auth can-i get configmap/app-config \
  --as=system:serviceaccount:<namespace>:<service-account-name>
# → no

# Проверка, какие Role/RoleBinding существуют для SA
kubectl get rolebinding,clusterrolebinding -A -o json | \
  jq -r '.items[] | select(.subjects[]?.name=="<sa-name>") | .metadata.name'

# Проверка деталей Role
kubectl describe role <role-name> -n <namespace>
# → Rules:
# → Resources  Non-Resource URLs  Verbs
# → configmaps []                  [get list]  -- достаточно
```

**Решение:**
```yaml
# Создайте Role с правами get на ConfigMap
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: configmap-reader
  namespace: <namespace>
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list", "watch"]
---
# Привяжите Role к ServiceAccount
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: configmap-reader-binding
  namespace: <namespace>
subjects:
- kind: ServiceAccount
  name: <service-account-name>
  namespace: <namespace>
roleRef:
  kind: Role
  name: configmap-reader
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 4: Опциональные ссылки (Optional)

Чтобы отсутствие ConfigMap не блокировало запуск (например, для локальной отладки или постепенной миграции), используйте `optional: true`.

**Использование в env:**
```yaml
env:
- name: DEBUG_CONFIG
  valueFrom:
    configMapKeyRef:
      name: non-critical-cfg
      key: debug-level
      optional: true  # Под запустится, если ресурса нет
```

**Использование в envFrom:**
```yaml
envFrom:
- configMapRef:
    name: optional-config
    optional: true  # Все ключи будут пропущены, если ConfigMap не найден
```

**Использование в volumes:**
```yaml
volumes:
- name: optional-vol
  configMap:
    name: optional-config
    optional: true  # Том не будет создан, если ConfigMap не найден
```

**Важно:** `optional: true` — осознанный выбор. Для критичных конфигов оставляйте `optional: false` (по умолчанию) — отсутствие ConfigMap должно приводить к ошибке запуска, а не к старту с неполной конфигурацией.

### Сценарий 5: Перезапуск при обновлении (Rollout Restart)

Если ConfigMap используется как `env`, его изменение требует пересоздания подов. Kubernetes не перезапускает поды автоматически при изменении ConfigMap — это происходит только при изменении `spec.template`.

**Диагностика:**
```bash
# Проверка, что ConfigMap изменился, но поды работают со старыми данными
kubectl get configmap app-config -o jsonpath='{.data.LOG_LEVEL}' 
# → DEBUG  -- новое значение

kubectl exec <pod-name> -- printenv LOG_LEVEL
# → INFO  -- старое значение, под не перезапускался
```

**Решение:**
```bash
# Безопасный перезапуск всех подов деплоймента
kubectl rollout restart deployment <deployment-name>

# Проверка статуса rollout
kubectl rollout status deployment <deployment-name>

# Для автоматического перезапуска при изменении ConfigMap используйте:
# - Kustomize configMapGenerator (хеширование имен)
# - Helm checksum/config аннотацию
# - Reloader (сторонний контроллер)
```

### Сценарий 6: Невалидные данные в binaryData (Base64)

Если ConfigMap содержит поле `binaryData` с некорректным Base64-кодированием, `kubelet` не может декодировать данные и монтировать том.

**Диагностика:**
```bash
# Проверка Presence binaryData в ConfigMap
kubectl get configmap <name> -o jsonpath='{.binaryData}' | jq 'keys'
# → ["server.crt", "server.key"]

# Проверка валидности Base64 (должно декодироваться без ошибок)
kubectl get configmap <name> -o jsonpath='{.binaryData.server\.crt}' | base64 -d > /tmp/test.crt
# → base64: invalid input  -- невалидный Base64

# Проверка размера (Base64 увеличивает размер на ~33%)
kubectl get configmap <name> -o yaml | wc -c
# → Если > 1 MiB (1048576 байт) — превышен лимит
```

**Решение:**
1. Перекодируйте данные в Base64: `cat server.crt | base64 -w0`
2. Проверьте, что размер итогового объекта не превышает 1 MiB
3. Используйте `kubectl create secret tls` для TLS-сертификатов (он кодирует автоматически)

### Сценарий 7: Projected Volume — отсутствие ConfigMap в составе агрегированного тома

ConfigMap может быть одним из источников в `projected` volume (наряду с Secret, Downward API, ServiceAccountToken). Если ConfigMap отсутствует — весь том не может быть создан.

**Диагностика:**
```bash
# Проверка событий пода
kubectl describe pod <pod-name> | grep -A 2 "Events:"
# → Warning  Failed  kubelet  Error: projected volume error: configmap "app-config" not found

# Проверка всех источников в projected volume
kubectl get pod <pod-name> -o json | \
  jq '.spec.volumes[].projected.sources[] | select(.configMap) | .configMap.name'
# → "app-config"  -- этот ConfigMap нужен

# Проверка его наличия
kubectl get configmap app-config -n <namespace>
# → Error from server (NotFound): configmaps "app-config" not found
```

**Решение:**
1. Создайте отсутствующий ConfigMap
2. Или добавьте `optional: true` к источнику в projected volume:
```yaml
volumes:
- name: combined-config
  projected:
    sources:
    - configMap:
        name: app-config
        optional: true  # Не блокирует запуск при отсутствии
```

### Сценарий 8: subPath и отсутствие ключа

При монтировании отдельных ключей ConfigMap через `subPath`, каждый ключ становится отдельным файлом. Если ключ не существует — ошибка.

**Диагностика:**
```bash
# Проверка ключей в ConfigMap
kubectl get configmap app-config -o jsonpath='{.data}' | jq 'keys'
# → ["config.yaml", "logging.yaml"]  -- ключа "settings.json" нет

# Проверка манифеста пода
kubectl get pod <pod-name> -o json | \
  jq '.spec.containers[].volumeMounts[] | select(.name=="app-config") | {mountPath, subPath}'
# → {"mountPath":"/etc/app/settings.json","subPath":"settings.json"}
```

**Типичная ошибка:**
```text
Warning  Failed  kubelet  subPath "settings.json" not found in configmap "app-config"
```

**Решение:**
1. Добавьте ключ `settings.json` в ConfigMap
2. Или исправьте `subPath` на существующий ключ
3. Используйте монтирование всего тома (без subPath) для автоматического обновления

### Сценарий 9: Helm-шаблон с пустым ConfigMap

Helm может создавать ConfigMap с пустыми данными, если переменные не определены в `values.yaml`.

**Диагностика:**
```bash
# Рендер манифеста Helm и проверка ConfigMap
helm template my-release /path/to/chart -f values.yaml | grep -A 10 "kind: ConfigMap"
# → apiVersion: v1
# → kind: ConfigMap
# → data:
# →   config.yaml: |     -- пусто или шаблон не рендерится

# Проверка значений переменных
helm template my-release /path/to/chart -f values.yaml --show-only templates/configmap.yaml
```

**Решение:**
1. Проверьте `values.yaml` на наличие обязательных переменных
2. Добавьте дефолтные значения: `{{ .Values.config.data | default "fallback" }}`
3. Используйте `required` для обязательных полей: `{{ required "config.data is required" .Values.config.data }}`

### Сценарий 10: Immutable ConfigMap с некорректными данными

Если ConfigMap помечен как `immutable: true` и содержит ошибки, его нельзя отредактировать — нужно пересоздавать.

**Диагностика:**
```bash
# Проверка иммутабельности
kubectl get configmap <name> -o jsonpath='{.metadata.labels}'
# → {"immutable":"true"}

# Или через describe
kubectl describe configmap <name> | grep -i immutable
# → Immutable:  true

# Проверка данных
kubectl get configmap <name> -o yaml | grep -A 5 "data:"
# → Данные содержат ошибку
```

**Решение:**
```bash
# 1. Экспортируйте текущий ConfigMap (для справки)
kubectl get configmap <name> -o yaml > old-configmap.yaml

# 2. Создайте новый ConfigMap с правильными данными
kubectl create configmap <name>-v2 --from-literal=key=value -n <namespace>

# 3. Обновите Pod/Deployment для использования нового ConfigMap
# (вручную или через Helm/Kustomize)

# 4. Удалите старый ConfigMap
kubectl delete configmap <name> -n <namespace>
```

## Список проверок (Checklist)

### Источники данных
- [ ] ConfigMap существует в том же Namespace, что и Pod: `kubectl get cm <name> -n <ns>`
- [ ] Все ключи в `configMapKeyRef.key` и `envFrom.prefix` существуют в ConfigMap
- [ ] Ключи в `subPath.path` совпадают с ключами в `.data` ConfigMap
- [ ] Все источники в `projected` volume существуют (или используют `optional: true`)

### Размер и данные
- [ ] Размер ConfigMap не превышает 1 MiB: `kubectl get cm <name> -o yaml | wc -c`
- [ ] Поле `binaryData` содержит валидный Base64
- [ ] Ключи являются валидными POSIX-именами (RFC 1123)
- [ ] Значения в `data` — валидный UTF-8

### Namespace и безопасность
- [ ] Pod и ConfigMap в одном Namespace
- [ ] ServiceAccount имеет права `get` на ConfigMap: `kubectl auth can-i get cm/<name> --as=system:serviceaccount:<ns>:<sa>`
- [ ] NodeRestriction не блокирует доступ (если используется)

### Иммутабельность и жизненный цикл
- [ ] Если ConfigMap `immutable: true` — данные корректны, пересоздание не требуется
- [ ] Если ConfigMap был удален — под не может запуститься (требуется пересоздание ConfigMap)

### Обновления и Rollout
- [ ] При использовании `env` — известно, что обновление требует рестарт
- [ ] При использовании `volumes` (без subPath) — обновление автоматическое (~60 сек)
- [ ] При использовании `volumes + subPath` — обновление требует рестарт

### Helm и шаблоны
- [ ] Переменные в Helm-шаблоне определены в `values.yaml`
- [ ] Deault-значения установлены для необязательных полей
- [ ] `{{ required }}` используется для обязательных полей
- [ ] `checksum/config` аннотация добавлена в шаблон пода (для автоматического рестарта)

## Быстрая диагностика

```bash
# 1. Определить причину из Events
kubectl describe pod <pod-name> | grep -A 5 "Events:"
# Ищите: "configmap not found", "key not found", "forbidden", "projected volume error"

# 2. Проверить все ConfigMap-ссылки в поде
kubectl get pod <pod-name> -o json | jq -r '
  (.spec.containers[].env[]?.valueFrom.configMapKeyRef.name // empty),
  (.spec.containers[].envFrom[]?.configMapRef.name // empty),
  (.spec.volumes[]?.configMap?.name // empty),
  (.spec.volumes[]?.projected?.sources[]?.configMap?.name // empty)
' | sort -u | while read -r name; do
  [ -n "$name" ] && kubectl get cm "$name" -n <namespace> &>/dev/null && echo "OK: $name" || echo "MISSING: $name"
done

# 3. Проверить ключи в ConfigMap
kubectl get cm <name> -o jsonpath='{.data}' | jq 'keys'

# 4. Проверить, все ли ключи из манифеста существуют
kubectl get pod <pod-name> -o json | jq -r '
  .spec.containers[].env[]? | 
  select(.valueFrom.configMapKeyRef) |
  "\(.valueFrom.configMapKeyRef.name) → \(.valueFrom.configMapKeyRef.key)"
' | while IFS=" → " read -r cm key; do
  kubectl get cm "$cm" -o jsonpath="{.data.$key}" -n <namespace> &>/dev/null && echo "OK: $cm/$key" || echo "MISSING: $cm/$key"
done

# 5. Проверить RBAC
kubectl auth can-i get configmap/<name> \
  --as=system:serviceaccount:<namespace>:<service-account-name> \
  -n <namespace>

# 6. Проверить размер ConfigMap
kubectl get cm <name> -o yaml | wc -c
# Если > 1048576 (1 MiB) — превышен лимит

# 7. Проверить иммутабельность
kubectl get cm <name> -o jsonpath='{.metadata.labels.immutable}' 2>/dev/null && echo "IMMUTABLE" || echo "MUTABLE"
```

## Типичные ошибки Helm-шаблонов

| Проблема | Симптом | Решение |
| :--- | :--- | :--- |
| Переменная не определена | `configmap "x" not found` | Добавить дефолт в `values.yaml` |
| Пустой ConfigMap | Под запускается, но конфиг пустой | Использовать `required` в шаблоне |
| Опечатка в имени | `configmap "x" not found` | Проверить `{{ .Release.Name }}-config` |
| Невалидный Base64 в binaryData | `kubelet` не может смонтировать том | Перекодировать: `base64 -w0 < file` |
| ConfigMap в другом namespace | 403 Forbidden | Убедиться, что ConfigMap в том же namespace |
| checksum/config не добавлен | Под не перезапускается при обновлении | Добавить аннотацию: `checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}` |

## Дополнительная информация

### Сравнение ConfigMap и Secret

| Аспект | ConfigMap | Secret |
| :--- | :--- | :--- |
| **Тип данных** | UTF-8 текст / BinaryData | Base64 (бинарные/строки) |
| **Безопасность** | Открытый текст | Требует шифрования (KMS/etcd) |
| **Размер** | До 1 MiB | До 1 MiB |
| **Назначение** | Флаги, конфиги, скрипты | Пароли, токены, TLS-ключи |
| **Шифрование по умолчанию** | Нет | Нет (требует EncryptionConfiguration) |
| **Watch kubelet** | Да (для mutable) | Да (для mutable) |
| **Обновление в volumes** | Автоматическое (~60 сек) | Автоматическое (~60 сек) |
| **Обновление в env** | Требует рестарт | Требует рестарт |

### Способы использования ConfigMap и их ограничения

| Способ | Автообновление | Требует рестарт | Примечание |
| :--- | :--- | :--- | :--- |
| `env` (configMapKeyRef) | Нет | Да | Точечный выбор ключа |
| `envFrom` (configMapRef) | Нет | Да | Все ключи сразу |
| `volumes` (configMap) | Да (~60 сек) | Нет | Все ключи как файлы |
| `volumes` + `subPath` | Нет | Да | Один ключ как файл |
| `projected` (configMap source) | Да (~60 сек) | Нет | Агрегированный том |
| `command/args` $(VAR) | Нет | Да | Раскрытие переменных в shell |

### Lifecycle ConfigMap в kubelet

```
Pod Scheduled → Node Assigned
    │
    ├── kubelet: SyncPod Loop
    │   ├── 1. GET configmap/<name> from API-server
    │   ├── 2. Если optional: true и 404 → пропуск
    │   ├── 3. Если optional: false и 404 → CreateContainerConfigError
    │   ├── 4. Если 403 Forbidden → CreateContainerConfigError (RBAC)
    │   ├── 5. Обработка данных:
    │   │   ├── env: маппинг ключей → переменные окружения
    │   │   ├── volumes: создание директории в /var/lib/kubelet/pods/<uid>/volumes/
    │   │   └── projected: агрегация с другими источниками
    │   └── 6. Generate CRI config → CreateContainer
    │
    └── Если шаг 3/4 → CreateContainerConfigError
```

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Профилактика и мониторинг](./prevention.md)
- [Проблемы с Secret](./secret_issues.md)
- [Проблемы с RBAC и ServiceAccount](./rbac_issues.md)
- [Проблемы с томами](./volume_issues.md)
- [CRI и containerd](./cri_and_runtime.md) — Container Runtime Interface, взаимодействие kubelet с рантаймом
- [Создание ConfigMap](../../../Base/ConfigMap/creation.md)
- [Использование ConfigMap в подах](../../../Base/ConfigMap/pod_usage.md)
- [Лучшие практики ConfigMap](../../../Base/ConfigMap/best_practices.md)
- [Неизменяемые ConfigMap](../../../Base/ConfigMap/immutable.md)
- [Обновление и Rollout](../../../Base/ConfigMap/update_and_rollout.md)
- [Projected Volumes](../../../Base/Pod/volume_types/projected_volumes.md)
