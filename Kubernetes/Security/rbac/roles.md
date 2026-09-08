# Роли (Role) и кластерные роли (ClusterRole)

## Определения

- **Role** — объект, определяющий набор разрешений в рамках одного [пространства имён (namespace)](./rbac_overview.md). Предоставляет доступ только к ресурсам, ограниченным пространством имён (pods, services, configmaps).

- **ClusterRole** — объект, определяющий набор разрешений на уровне всего кластера. Предоставляет доступ к кластерным ресурсам (nodes, persistentvolumes), нересурсным URL или ко всем пространствам имён одновременно.

Подробное описание архитектуры **RBAC (Role-Based Access Control — управление доступом на основе ролей)** приведено в файле **[Обзор RBAC](./rbac_overview.md)**.

### Предупреждения безопасности

- **Безопасность объектов:** использование префикса `system:` зарезервировано для системных компонентов. См. раздел **[Предупреждения безопасности](./rbac_overview.md)**.
- **Группа `system:masters`:** Членство в этой группе дает неограниченный доступ в обход RBAC. Избегайте добавления пользователей в эту группу.
- **Pod Security Admission (PSA):** Начиная с v1.25 (после удаления PodSecurityPolicy), для контроля безопасности подов используются метки на уровне Namespace, а не RBAC-глагол `use`. См. раздел **[Pod Security Context](../pod_security_context.md)**.
- **CVE-2021-25740 (историческая справка):** В кластерах до v1.22 доступ на запись к `EndpointSlices` был в агрегируемых ролях `admin`/`edit`. В новых версиях это исправлено. Подробности: раздел «Сценарий 4» в **[Агрегируемые ClusterRole](./aggregation_scenarios.md)**.

## Основные концепции

### Структура правил (rules)

Каждая роль содержит список правил, определяющих разрешённые действия:

| Поле | Описание | Пример |
|------|----------|--------|
| `apiGroups` | API-группы ресурсов | `""` (core), `"apps"`, `"rbac.authorization.k8s.io"` |
| `resources` | Типы ресурсов | `pods`, `deployments`, `configmaps` |
| `verbs` | Действия (глаголы) | `get`, `list`, `watch`, `create`, `update`, `delete` |
| `resourceNames` | Ограничение по именам | `["my-config"]` — доступ только к конкретному ресурсу. **Внимание:** ограничение не работает с глаголами `create` и `deletecollection` (см. подраздел ниже). Для `list`/`watch` требует указания field selector. |
| `nonResourceURLs` | Нересурсные пути | `/healthz`, `/metrics` (только для ClusterRole) |

#### Подстановочные знаки (wildcards)

Символ `*` (звёздочка) в полях `apiGroups`, `resources`, `verbs` означает «любое значение» этого поля. Он позволяет создавать максимально широкие роли (например, аналог `cluster-admin`) и покрывать новые ресурсы и глаголы, которые появятся в будущих версиях Kubernetes, без обновления роли.

- `resources: ["*"]` — любые текущие и будущие ресурсы в указанной группе.
- `verbs: ["*"]` — любые действия.
- `apiGroups: ["*"]` — все API-группы (включая core и будущие).

Для `nonResourceURLs` звёздочка работает как **суффиксный glob-шаблон**: `/foo/*` соответствует всем подпутям `/foo/`, отдельная `*` соответствует всем non-resource-путям.

> **Примечание по безопасности:** широкое использование `*` упрощает написание ролей, но затрудняет аудит и нарушает принцип наименьших привилегий. В production предпочтительно перечислять конкретные ресурсы и глаголы вместо `*`.

#### Ограничение по именам (`resourceNames`) — практические нюансы

`resourceNames` сужает доступ к конкретным экземплярам ресурса (например, к определённому `ConfigMap`), но подчиняется важным правилам и ограничениям, которые часто становятся причиной 403-ошибок:

- **`create` не сужается по имени для «верхнеуровневых» ресурсов.** Имя нового объекта не передаётся в URL запроса на момент авторизации, поэтому правило с `resourceNames` не разрешит произвольный `create`. Единственный способ создать объект с конкретным именем при наличии такого ограничения — **server-side apply** (SSA), который отправляет запрос на эндпоинт, содержащий имя объекта в URL.
- **Исключение — субресурсы:** для субресурсов (например, `pods/exec`, `pods/attach`, `pods/portforward`) ограничение по имени **работает** с глаголами `create` и `get`. Это позволяет строго ограничить, к каким контейнерам конкретного пода можно подключиться.
- **`deletecollection` не сужается по имени:** массовое удаление коллекции всегда проверяется без учёта `resourceNames`.
- **`list`/`watch` требуют field selector:** чтобы запрос `list` или `watch` с `resourceNames` прошёл авторизацию, клиент обязан указать field selector `metadata.name=<имя>`, например:
  ```bash
  kubectl get configmaps --field-selector=metadata.name=my-configmap
  ```
  Без него список вернёт `403 Forbidden`, хотя `get` конкретного объекта будет разрешён.
- **Ложное «да» от `kubectl auth can-i`:** команда `kubectl auth can-i create configmap/fluentd-extra-config` может вернуть `yes`, хотя фактический `kubectl create` закончится `403`. Причина — `can-i` проверяет разрешения на «именованный» эндпоинт, а реальный `POST` идёт на коллекцию без имени. Учитывайте это при отладке: проверяйте реальное действие, а не только `can-i`.

#### API-группы (apiGroups)

Для большинства базовых ресурсов (Pods, Services, Secrets, ConfigMaps) `apiGroups` указывается как пустая строка `""`. Для остальных ресурсов необходимо указывать их группу:

- **`apps`**: Deployments, StatefulSets, DaemonSets.
- **`batch`**: Jobs, CronJobs.
- **`networking.k8s.io`**: Ingress, NetworkPolicies.
- **`storage.k8s.io`**: StorageClasses, CSINodes.
- **`rbac.authorization.k8s.io`**: Roles, ClusterRoles, Bindings.
- **`autoscaling`**: HorizontalPodAutoscalers.

#### Субресурсы (Subresources)

Субресурсы позволяют предоставлять доступ к специфическим функциям объекта без предоставления полного доступа к самому объекту. Указываются через `/`.

| Субресурс | Назначение | Пример использования |
|-----------|------------|----------------------|
| `pods/log` | Чтение логов контейнера | `kubectl logs` |
| `pods/exec` | Выполнение команд в контейнере | `kubectl exec` |
| `pods/attach` | Подключение к стандартным потокам контейнера | `kubectl attach` |
| `pods/status` | Чтение или обновление статуса пода | Используется контроллерами |
| `pods/portforward` | Проброс портов к поду | `kubectl port-forward` |
| `nodes/proxy` | Доступ к API через узел | Используется для отладки и метрик |
| `nodes/stats` | Сбор статистики с узла | Используется Kubelet и мониторингом |
| `services/proxy` | Проксирование запросов через сервис | Доступ к веб-интерфейсам внутри кластера |

**Внимание (эскалация прав через `pods/exec`/`pods/attach`):** глаголы `pods/exec`, `pods/attach` и `pods/portforward` дают почти неограниченные возможности внутри контейнера (включая выполнение команд с правами root контейнера и доступ по сети). Выдача этих прав сопоставима по опасности с административными правами в namespace. Не выдавайте их ServiceAccount без необходимости и ограничивайте через `resourceNames` по конкретным подам.

**Агрегированные API и метрики:** ресурс `metrics.k8s.io` (а также `nodes/metrics`) предоставляется агрегированным API-сервером metrics-server и используется командами вида `kubectl top`. Для работы команды `top` соответствующая роль должна явно разрешать доступ к этому ресурсу — он не подразумевается автоматически правами на `nodes`.

### Глаголы (Verbs)

| Глагол (Verb) | Описание | Риски и особенности |
|---------------|----------|-------------------|
| `get` | Чтение одного ресурса по имени | Базовый доступ. |
| `list` | Список ресурсов | **Риск:** `list` секретов позволяет увидеть содержимое всех секретов в namespace. |
| `watch` | Отслеживание изменений | Используется контроллерами. |
| `create` | Создание нового ресурса | Несовместим с `resourceNames`. |
| `update` | Полное обновление ресурса | Заменяет существующий объект. Требует `resourceVersion`. |
| `patch` | Частичное обновление | Рекомендуется для точечных изменений и избежания конфликтов. |
| `delete` | Удаление ресурса | Возможность прерывания работы сервиса. |
| `deletecollection` | Массовое удаление | **Высокий риск:** удаление всех объектов типа в namespace. |
| `bind` | Привязка роли к субъекту | **Критический риск:** позволяет пользователю выдать права самому себе. |
| `escalate` | Повышение прав роли | **Критический риск:** редактирование ролей для добавления прав, которых нет у пользователя. |
| `impersonate` | Действие от имени другого | **Критический риск:** обход ограничений через привилегированную учётку. |
| `use` | Использование ресурса | **Устарело:** ранее использовалось для PodSecurityPolicy (удалено в 1.25+). |

#### Глаголы `bind` / `escalate` и защита от повышения прав

Глагол `escalate` на ресурсе `roles`/`clusterroles` позволяет пользователю редактировать саму роль, расширяя её до прав, которых у него изначально нет (самое грубое повышение привилегий). Глагол `bind` на `rolebindings`/`clusterrolebindings` позволяет привязывать роли к субъектам — включая себя.

Без соответствующих ограничений админ может осознанно наделить роль правом `escalate`/`bind`, чтобы например делегировать управление ролями отдельной команде. Чтобы минимизировать риск:

1. **Не выдавайте эти глаголы без явной необходимости** — они почти не нужны в обычных ролях.
2. **Для делегирования управления ролями** используйте официальные рекомендации: разрешайте конкретному субъекту `escalate`/`bind`, но контролируйте это централизованно и всегда переоценивайте необходимость.
3. **Применяйте `kubectl auth reconcile`** для приведения фактических прав к ожидаемым и выявления расхождений в ролях:
   ```bash
   # Применяет права из файла и удаляет лишние правила ролей
   kubectl auth reconcile -f rbac-manifests.yaml
   ```
4. **Следите за `impersonate`:** позволив пользователю подменять другой субъект, вы даёте ему все права этого субъекта. Выдавайте только по строгой необходимости (например, для административных проверок `can-i --as`).

#### Сравнение update и patch

- **`update`**: Отправляет полную копию объекта. Если объект в кластере изменился с момента последнего чтения (изменился `resourceVersion`), API-сервер вернет ошибку `409 Conflict`.
- **`patch`**: Отправляет только измененные поля. Позволяет нескольким контроллерам или пользователям изменять разные части одного объекта без конфликтов версий.

### Сравнение Role и ClusterRole

| Критерий | Role | ClusterRole |
|----------|------|-------------|
| **Область действия** | Один namespace | Весь кластер или все namespace |
| **Ресурсы** | Только ресурсы в namespace | Кластерные + ресурсы в namespace |
| **Привязка** | [RoleBinding](./bindings.md) | [ClusterRoleBinding](./bindings.md) или [RoleBinding](./bindings.md) |
| **Агрегация** | Нет | Да ([aggregationRule](./aggregation_scenarios.md)) |
| **resourceNames** | Поддерживается | Поддерживается |
| **nonResourceURLs** | Нет | Да (`/healthz`, `/metrics`) |

> **Ловушка:** путают область действия. Role + RoleBinding работают только в **одном namespace**. ClusterRole + ClusterRoleBinding — на **весь кластер** (nodes, PV, namespaces). ClusterRole, привязанная через RoleBinding, даёт права только в namespace этой привязки. Role, привязанная через ClusterRoleBinding, **невозможна** — ClusterRoleBinding требует ClusterRole.

### Рекомендации по выбору

| Сценарий | Рекомендуемый объект | Обоснование |
|----------|---------------------|-------------|
| Доступ к ресурсам в одном namespace | Role | Изоляция, минимальные привилегии |
| Мониторинг всех namespace (Prometheus) | ClusterRole + RoleBinding | Глобальное чтение с ограниченной привязкой |
| Административные операции | ClusterRole + ClusterRoleBinding | Глобальный доступ для админов |
| Кросс-namespace доступ к Secrets | ClusterRole + RoleBinding в каждом NS | Контролируемый доступ |
| Доступ к нересурсным URL | ClusterRole | Только ClusterRole поддерживает `nonResourceURLs` |

## Практические сценарии

### Примеры манифестов Role

```yaml
# Чтение информации о поде (get, list, watch) в пространстве имен dev
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: dev
  name: pod-reader
rules:
- apiGroups: [""] # "" указывает на основную (core) API группу
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
```

```yaml
# Доступ только к чтению логов подов
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: log-reader
  namespace: production
rules:
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get", "list", "watch"]
```

```yaml
# Ограничение доступа конкретным ConfigMap по имени
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: config-reader
  namespace: development
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  resourceNames: ["app-config", "shared-config"]
  verbs: ["get", "update"]
```

### Работа с Custom Resources (CRD)

Для работы с кастомными ресурсами необходимо точно указывать их API-группу. Ресурсы всегда указываются во множественном числе.

```yaml
# Доступ к управлению сертификатами cert-manager
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: cert-manager-user
  namespace: apps
rules:
- apiGroups: ["cert-manager.io"]
  resources: ["certificates", "certificaterequests"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
```

### Примеры манифестов ClusterRole

```yaml
# Глобальное чтение нод
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
```

```yaml
# Доступ к нересурсным URL
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: health-checker
rules:
- nonResourceURLs: ["/healthz", "/readyz"]
  verbs: ["get"]
```

### Привязка ClusterRole к конкретному namespace

Для предоставления разрешений, определенных в ClusterRole, только в рамках одного namespace, используется RoleBinding.

```yaml
# 1. ClusterRole для чтения секретов (создается один раз)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: secret-viewer
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "watch"]
---
# 2. RoleBinding в конкретном namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: view-secrets-in-staging
  namespace: staging
subjects:
- kind: Group
  name: devs
  apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: secret-viewer
  apiGroup: rbac.authorization.k8s.io
```

### Типовые роли для задач DevOps/SRE

Сборка ролей из готовых правил ускоряет выдачу прав и упрощает ревью. Ниже — практичные паттерны, используемые в реальных кластерах.

#### Роль для приложения (ServiceAccount приложения)

Типичный минимум для обычного приложения: чтение своих ConfigMap/Secrets и управление своими под/деплойментами, но без доступа к чужим ресурсам. Подробно о ServiceAccount — см. [Субъекты доступа](./subjects.md).

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: app-runtime
  namespace: myapp
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["configmaps", "secrets"]
  verbs: ["get"]
```

#### Роль для оператора/контроллера (watch + patch)

Контроллеры (операторы) обычно должны наблюдать за ресурсами (`watch`/`list`) и модифицировать статус (`patch`/`update`). Минимизируйте права до только необходимых ресурсов и субресурсов.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: operator-controller
  namespace: myapp
rules:
- apiGroups: [""]
  resources: ["configmaps", "secrets", "pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "deployments/status"]
  verbs: ["get", "list", "watch", "patch", "update"]
```

#### Роль для команды разработки (чтение без доступа к Secrets)

Сборка на основе встроенной `view`, но с исключением чтения Secrets. Такой паттерн даёт разработчикам диагностическую видимость, не раскрывая секреты.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: developer-readonly
  namespace: myapp
rules:
- apiGroups: [""]
  resources: ["pods", "services", "configmaps", "endpoints", "replicationcontrollers"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets", "daemonsets", "replicasets"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods/log", "pods/exec"]
  verbs: ["get", "create"]
```

#### Роль для отладки инцидентов (pod exec + logs, но без записи)

SRE-инженеру при разборе инцидента часто нужны логи и `exec`, но не изменение ресурсов. Такая узкая роль снижает риск случайных изменений в production.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: incident-debug
  namespace: production
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["pods/exec", "pods/attach", "pods/portforward"]
  verbs: ["create", "get"]
```

#### Ресурсы отладки мониторинга: доступ к метрикам

Для работы `kubectl top` и доступа к агрегированному metrics-server необходимы отдельные права на ресурс `metrics.k8s.io`:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: metrics-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list"]
- apiGroups: ["metrics.k8s.io"]
  resources: ["nodes", "pods"]
  verbs: ["get", "list"]
```

## Проверка прав (Verification)

Для отладки RBAC и проверки разрешений без смены контекста используются встроенные средства `kubectl`.

### Проверка своих прав
```bash
# Список всех разрешений в текущем namespace
kubectl auth can-i --list

# Список всех разрешений в конкретном namespace
kubectl auth can-i --list --namespace=foo

# Проверка возможности конкретного действия
kubectl auth can-i create deployments

# Проверка прав в другом namespace
kubectl auth can-i get secrets -n production

# Проверка прав в контексте конкретного ресурса (тип/имя)
kubectl auth can-i get configmaps/my-configmap -n dev

# Проверка прав с квалификацией API-группы (тип.группа)
kubectl auth can-i list jobs.batch -n ci

# Проверка доступа к субресурсу (например, чтение логов)
kubectl auth can-i get pods --subresource=log

# Проверка доступа к нересурсному пути
kubectl auth can-i get /logs/

# Проверка прав сразу во всех namespaces
kubectl auth can-i create pods --all-namespaces

# Проверка в стиле "все сразу" ('*' означает все действия)
kubectl auth can-i '*' '*'
```

**Тихий режим:** флаг `--quiet` возвращает только код выхода (`0` — можно, `1` — нельзя), что удобно для скриптов и CI:
```bash
if kubectl auth can-i create secrets --quiet; then
  echo "Разрешено"
else
  echo "Запрещено"
fi
# → "Разрешено"
```

### Проверка прав другого субъекта
Требуются права администратора кластера.
```bash
# Проверка прав ServiceAccount в namespace
kubectl auth can-i list secrets \
  --as=system:serviceaccount:production:my-app-sa \
  -n production

# Проверка прав конкретного пользователя
kubectl auth can-i get nodes --as=johndoe

# Проверка прав группы
kubectl auth can-i get pods --as-group=dev-team -n dev
```

### Просмотр содержимого ролей

Для аудита и отладки полезно смотреть фактические правила встроенных и собственных ролей:

```bash
# Полный YAML роли (правила, метки агрегации, аннотации)
kubectl get roles -n dev pod-reader -o yaml
kubectl get clusterrole system:discovery -o yaml

# Сводка правил в широком формате
kubectl get clusterrole admin -o wide
```

### Диагностика 403 при настроенной, но «не работающей» роли

1. Убедитесь, что субъект действительно имеет права — через `can-i` с `--as` (см. выше).
2. Проверьте, что имя ресурса/глагол/API-группа указаны точно (в нижнем регистре, во множественном числе). Для уточнения группы используйте `kubectl api-resources -o wide | grep <ресурс>`.
3. Помните про ограничения `resourceNames` (см. выше): `create`/`deletecollection` не сужаются, `list`/`watch` требуют field selector.
4. Для глубокой диагностики включите подробное логирование решений RBAC в `kube-apiserver` (`--v=5` или `--vmodule=rbac*=5`) — в логах появятся записи об отказах с префиксом `RBAC`.
5. Если проблема у контроллера/приложения, использующего ServiceAccount, проверьте, что права выданы именно нужному SA (не путайте контексты и пространства имён). Подробный разбор типичных ошибок: [Объекты RBAC: структура и типичные ошибки](../../Troubleshooting/Common_Errors/ApiAccessForbidden/rbac_objects.md).

## Дополнительная информация

### Встроенные роли

Kubernetes предоставляет стандартные ClusterRole для типичных задач. Они делятся на **пользовательские роли** (без префикса `system:`) и **системные/служебные роли** (с префиксом `system:`).

#### Пользовательские роли (user-facing)

Эти роли предназначены для назначения реальным пользователям и рабочим нагрузкам:

- `cluster-admin` — полный доступ ко всем ресурсам кластера и во всех namespace. При использовании в `ClusterRoleBinding` даёт полный контроль над кластером; при использовании в `RoleBinding` — полный контроль над ресурсами в конкретном namespace, включая сам namespace. По умолчанию привязана к группе `system:masters`.
- `admin` — административные права в рамках namespace (чтение/запись большинства ресурсов, включая возможность создавать роли и привязки в этом namespace). **Не даёт** права записи на квоты ресурсов, на сам namespace, а также (в кластерах v1.22+) на запись `EndpointSlices`.
- `edit` — чтение и запись большинства объектов в namespace. **Не даёт** просмотр/изменение ролей и привязок, но **дает** доступ к Secrets и право запускать поды от имени любого ServiceAccount namespace (что фактически позволяет получить уровень доступа любого SA). Также не разрешает запись `EndpointSlices` в кластерах v1.22+.
- `view` — доступ только на чтение к большинству объектов. **Исключает** Secrets (чтение содержимого Secrets даёт доступ к учётным данным ServiceAccount и является формой повышения привилегий), а также роли и привязки.

**Агрегация пользовательских ролей:** роли `admin`, `edit`, `view` построены на механизме агрегации ClusterRole. Чтобы расширить их правами на собственные (custom) ресурсы, создайте ClusterRole с соответствующей меткой — правила будут автоматически добавлены в базовую роль:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: aggregate-cron-tabs
  labels:
    rbac.authorization.k8s.io/aggregate-to-admin: "true"
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
    rbac.authorization.k8s.io/aggregate-to-view: "true"
# (правила на нужный ресурс, например crontabs)
rules: []
```

Подробнее об агрегации — в разделе [Агрегируемые ClusterRole](./aggregation_scenarios.md).

#### Системные роли обнаружения API (API discovery)

- `system:basic-user` — доступ только на чтение к базовой информации о самом пользователе (например, `SelfSubjectAccessReview`, `SelfSubjectRulesReview`). Привязана по умолчанию к группе `system:authenticated`.
- `system:discovery` — доступ только на чтение к эндпоинтам обнаружения API (`/api`, `/api/*`, `/apis`, `/apis/*`, `/openapi`, `/openapi/*`, `/version`), необходимым для обнаружения и согласования версий API. Привязана к `system:authenticated`. В версиях до v1.14 также привязывалась к `system:unauthenticated`.
- `system:public-info-viewer` — доступ только на чтение к нечувствительной информации о кластере (`/healthz`, `/version`, `/version/`). Привязана к `system:authenticated` и `system:unauthenticated`. Введена в v1.14 для ограничения анонимного доступа к discovery-эндпоинтам.

**Внимание по безопасности:** до v1.14 роли `system:discovery` и `system:basic-user` по умолчанию выдавали доступ и неаутентифицированным пользователям, что раскрывало информацию об API (включая имена custom resources). В новых кластерах анонимные пользователи получают только `system:public-info-viewer`. Если требуется заново открыть discovery для анонимных пользователей, это делается явно:
```bash
kubectl create clusterrolebinding anonymous-discovery \
  --clusterrole=system:discovery --group=system:unauthenticated
```

**Внимание:** встроенные роли защищены контроллером. Если вы вручную измените `ClusterRole/view` (или другие роли с аннотацией `rbac.authorization.kubernetes.io/autoupdate: "true"`), `kube-controller-manager` восстановит её исходное состояние в следующем цикле. Для изменения таких ролей снимите аннотацию автообновления.

### Лучшие практики

1. **Принцип наименьших привилегий (PoLP):** Предоставляйте только тот минимум прав, который необходим для работы.
2. **Избегайте подстановочных знаков (`*`):** Явно указывайте ресурсы и глаголы. `*` в `apiGroups` или `resources` затрудняет аудит.
3. **Ограничивайте `list` для Secrets:** Глагол `list` на ресурсе `secrets` позволяет получить данные всех секретов сразу. Используйте `get` + `resourceNames`.
4. **Не используйте группу `system:masters`:** Пользователи в этой группе обходят все проверки RBAC. Это "черный ход", который невозможно заблокировать политиками.
5. **Используйте `resourceNames`:** Где возможно, ограничивайте доступ конкретными экземплярами (например, доступ только к одному `ConfigMap`). Помните об ограничениях `resourceNames` (глаголы `create`/`deletecollection`, field selector для `list`/`watch`).
6. **Аудит и сканирование:** Регулярно проверяйте права инструментами вроде `rakkess` или `kubescape` для обнаружения избыточных привилегий.
7. **Агрегация:** Для расширения стандартных ролей используйте [aggregationRule](./aggregation_scenarios.md). Помните, что агрегация работает только для ClusterRole.
8. **Версионируйте роли как код:** Храните манифесты Role/ClusterRole в Git (GitOps) и применяйте через `kubectl apply`/CD-пайплайн. Это обеспечивает ревью изменений, воспроизводимость и упрощает откат. Для однократного выравнивания с файлом используйте `kubectl auth reconcile`.
9. **Выдавайте права именно ServiceAccount приложения, а не «кластерному» пользователю:** Минимизируйте ClusterRoleBinding и предпочитайте Role/RoleBinding в конкретном namespace, ограничивая «площадь поражения» при компрометации поды.
10. **Привязывайте роли к группам, а не к отдельным пользователям:** Управлять членством в группе (например, в SSO/IdP) легче, чем пересоздавать множество биндингов при кадровых изменениях. Подробнее — [Субъекты доступа](./subjects.md).

### Связанные темы

- **[Общий обзор RBAC](./rbac_overview.md)**
- **[Привязки ролей (RoleBinding)](./bindings.md)**
- **[Агрегируемые ClusterRole](./aggregation_scenarios.md)**
- **[Субъекты доступа (Subjects)](./subjects.md)**
- **[Эскалация привилегий: attack vectors и защита](./privilege_escalation.md)**
- **[Программная проверка прав: AccessReview API](./authorization_review_api.md)**
