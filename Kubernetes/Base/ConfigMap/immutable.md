# Неизменяемые (Immutable) ConfigMap

## Определения

**Immutable ConfigMap** (неизменяемый ConfigMap) — это объект API Kubernetes, в спецификации которого установлен флаг `immutable: true`. После создания такого объекта его данные (`data` и `binaryData`) становятся защищенными от изменений на уровне API-сервера. Эта функция стала **GA (General Availability)** в Kubernetes v1.21.

### Историческая справка

Функциональность неизменяемых ConfigMap и Secret прошла следующие этапы развития:

*   **Alpha (v1.19):** Первоначальная реализация за фиче-флагом `ImmutableFieldSelector`. Требовалась явная активация на API-сервере.
*   **Beta (v1.20):** Функция доступна по умолчанию, но для использования `immutable: true` требовалось указание `--feature-gates=ImmutableFieldSelector=true`.
*   **GA (v1.21+):** Функция стала полностью доступной без дополнительных фиче-флагов. Рекомендуется к использованию во всех Production-окружениях.

Эволюция этой функции отражает общую тенденцию Kubernetes к оптимизации производительности Control Plane за счет сокращения количества长期 Watch-соединений.

## Основные концепции

### Технические преимущества (Производительность и Масштабирование)

Использование неизменяемых ресурсов радикально оптимизирует работу **Control Plane** и агентов **Kubelet**:

*   **Снятие нагрузки с API-сервера (Watch Reduction):** Для обычных ConfigMap каждый `kubelet` на каждом узле, где запущен под с этим конфигом, поддерживает постоянное соединение (**Watch**) с API-сервером. В крупных кластерах с тысячами узлов это создает огромную нагрузку на etcd и API-сервер.
*   **Оптимизация Kubelet:** При обнаружении флага `immutable: true` `kubelet` скачивает данные один раз (через `GET`) и немедленно закрывает соединение. Он "знает", что данные гарантированно не изменятся, что экономит ресурсы CPU и памяти на всех уровнях.
*   **Исключение "Configuration Drift":** Запрет на редактирование (`kubectl edit`) защищает систему от ручных правок в обход GitOps-процессов, гарантируя, что состояние кластера строго соответствует коду в репозитории.

### Детальный анализ механизма Watch

Watch-механизм — это основа реактивной архитектуры Kubernetes, но его стоимость возрастает экспоненциально с масштабом кластера:

**Почему Watch дорогие:**

1.  **Постоянные соединения:** Каждый kubelet устанавливает long-lived HTTP/2 соединение с API-сервером для каждого отслеживаемого ресурса (ConfigMap, Secret, Endpoints и т.д.). В кластере с 1000 узлов и 500 ConfigMap это 500,000 активных соединений.
2.  **Десериализация:** При каждом изменении API-сервер отправляет полный объект всем подписчикам. Это нагружает CPU API-сервера и сеть.
3.  **Хранение состояния:** etcd должен поддерживать список ревизий для каждого Watch-клиента, потребляя оперативную память.
4.  **Retry-циклы:** При обрыве соединения kubelet переподключается и запрашивает все объекты заново, создавая пиковую нагрузку.

**Что дает immutable:**

*   kubelet выполняет один `GET`-запрос при запуске пода
*   Watch-соединение не устанавливается
*   При перезапуске пода kubelet повторно запрашивает данные (но без long-lived соединения)
*   Экономия ~100-200 MiB RAM на каждом узле в кластерах с 100+ ConfigMap

### Взаимосвязь с GitOps и Name Hashing

Неизменяемость неразрывно связана с паттерном **хеширования имен** (Name Hashing):
1.  Поскольку объект нельзя изменить, любое обновление конфигурации — это создание **нового** объекта (например, `app-config-a1b2c3` -> `app-config-d4e5f6`).
2.  Новое имя объекта в спецификации Pod автоматически инициирует **Rolling Update** (перезапуск подов).
3.  Это обеспечивает атомарность обновления: поды либо работают со старым конфигом, либо с новым, исключая промежуточные состояния.

### Границы неизменяемости

*   **Данные (`data`, `binaryData`):** Полностью защищены от изменений.
*   **Метаданные (`metadata`):** Остаются **изменяемыми**. Вы можете добавлять, удалять или изменять `labels` и `annotations` у неизменяемого ConfigMap.
*   **Жизненный цикл:** Объект можно удалить. Для "обновления" данных необходимо либо удалить и создать объект заново с тем же именем (не рекомендуется), либо создать новый объект с новым именем (Best Practice).

### Взаимодействие с Admission Controllers

Неизменяемые ConfigMap имеют особенности взаимодействия с контроллерами допуска:

*   **ValidatingWebhookConfiguration:** Webhook может блокировать создание неизменяемых ConfigMap или требовать дополнительных аннотаций (например, `required-annotation: immutable-approved`).
*   **MutatingWebhookConfiguration:** Может автоматически добавлять флаг `immutable: true` к определенным ConfigMap (например, все конфиги с префиксом `prod-`).
*   **Resource Quota:** Неизменяемые ConfigMap учитываются в квотах `configmaps`, но их создание может быть ограничено квотой `count/configmaps.production`.

### Поведение при апгрейде кластера

При обновлении кластера с версии < 1.21 до >= 1.21:

*   Существующие ConfigMap с `immutable: true` начинают работать в штатном режиме
*   Кластерные компоненты (kube-controller-manager, kube-scheduler) автоматически переходят на оптимизированный режим чтения
*   Рекомендуется постепенное внедрение: сначала пометить как immutable тестовые ConfigMap, затем production

## Практические сценарии

### Создание неизменяемого ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config-v1
  namespace: production
immutable: true # Включение режима неизменяемости
data:
  DB_HOST: "db.example.com"
  LOG_LEVEL: "error"
```

### Императивное создание (kubectl)

```bash
# Создание immutable ConfigMap из литералов
kubectl create configmap app-config \
  --from-literal=DB_HOST=db.example.com \
  --from-literal=LOG_LEVEL=error \
  --dry-run=client -o yaml | \
  sed 's/immutable: false/immutable: true/' | \
  kubectl apply -f -

# Создание из YAML-файла с последующей модификацией
kubectl create configmap app-config --from-file=config.yaml
kubectl patch configmap app-config -p '{"immutable":true}'
```

### Автоматизация через Kustomize (configMapGenerator)

Kustomize берет на себя всю рутину по хешированию имен и установке флага неизменяемости.

```yaml
# kustomization.yaml
generatorOptions:
  immutable: true # Применяется ко всем генерируемым ресурсам в этом файле

configMapGenerator:
- name: app-config
  files:
    - configs/server.properties
```

При выполнении `kubectl apply -k .` Kustomize создаст ConfigMap вида `app-config-hash` и обновит все ссылки в Deployment.

### Автоматизация через Helm

Helm поддерживает неизменяемые ConfigMap через значения в `values.yaml`:

```yaml
# values.yaml
configMap:
  immutable: true
  data:
    DB_HOST: "db.example.com"
    LOG_LEVEL: "error"
```

```yaml
# templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
immutable: {{ .Values.configMap.immutable }}
data:
  {{- range $key, $value := .Values.configMap.data }}
  {{ $key }}: {{ $value | quote }}
  {{- end }}
```

### Миграция существующего ConfigMap на immutable

Для перевода существующего изменяемого ConfigMap в режим неизменяемости:

```bash
# 1. Проверьте текущее состояние
kubectl get configmap app-config -o yaml > app-config-backup.yaml

# 2. Пометьте как immutable
kubectl patch configmap app-config -p '{"immutable":true}'

# 3. Проверьте результат
kubectl get configmap app-config -o jsonpath='{.immutable}'
# → true

# 4. Принудительно перезапустите поды (опционально, для гарантии)
kubectl rollout restart deployment/my-app
```

### Попытка несанкционированного изменения

Если вы попытаетесь изменить данные в неизменяемом ConfigMap, API-сервер отклонит запрос:

```bash
kubectl patch configmap app-config-v1 -p '{"data":{"LOG_LEVEL":"debug"}}'
# → Error from server (BadRequest): error when patching "app-config-v1":
#   cannot modify fields other than 'metadata' for immutable configmap
```

### Валидация перед применением

```bash
# Проверка манифеста на стороне сервера
kubectl apply -f immutable-configmap.yaml --dry-run=server

# Сравнение текущего и Desired состояния
kubectl diff -f immutable-configmap.yaml

# Проверка через kubectl explain
kubectl explain configmap.immutable
# → <boolean>
#     Immutable if set to true, ensures that data stored in the ConfigMap cannot
#     be updated
```

### Проверка статуса в кластере

Чтобы убедиться, что ConfigMap действительно неизменяем, проверьте поле `immutable` в выводе:

```bash
kubectl get cm app-config-v1 -o jsonpath='{.immutable}'
# → true
```

### Массовая проверка всех ConfigMap в Namespace

```bash
# Найти все immutable ConfigMap
kubectl get configmap -A -o json | jq -r '
  .items[] | 
  select(.immutable == true) | 
  "\(.metadata.namespace)/\(.metadata.name)"
'

# Найти все mutable ConfigMap (кандидаты на миграцию)
kubectl get configmap -A -o json | jq -r '
  .items[] | 
  select(.immutable != true) | 
  "\(.metadata.namespace)/\(.metadata.name)"
'
```

## Типичные ошибки и их решение

### Ошибка: "cannot modify fields other than 'metadata' for immutable configmap"

**Причина:** Попытка обновить данные в неизменяемом ConfigMap.

**Решение:**
```bash
# Вариант 1: Создать новый ConfigMap с новым именем
kubectl create configmap app-config-v2 --from-file=config.yaml
kubectl patch deployment my-app -p '{"spec":{"template":{"spec":{"volumes":[{"name":"config","configMap":{"name":"app-config-v2"}}]}}}}'

# Вариант 2: Удалить старый и создать заново (не рекомендуется в production)
kubectl delete configmap app-config-v1
kubectl create configmap app-config-v1 --from-file=config.yaml
kubectl rollout restart deployment/my-app
```

### Ошибка: Pod не получает обновленный ConfigMap

**Причина:** Pod использует immutable ConfigMap и не был перезапущен.

**Решение:**
```bash
# Проверьте, какой ConfigMap используется
kubectl get pod my-pod -o jsonpath='{.spec.volumes[*].configMap.name}'

# Перезапустите поды
kubectl rollout restart deployment/my-app
```

### Ошибка: "configmap not found" после удаления immutable ConfigMap

**Причина:** Pod ссылается на удаленный ConfigMap.

**Решение:**
```bash
# Создайте ConfigMap с тем же именем и теми же данными
kubectl create configmap app-config-v1 --from-literal=DB_HOST=db.example.com

# Проверьте, что поды восстановились
kubectl get pods -l app=my-app
```

## Дополнительная информация

### Сравнение типов ConfigMap

| Характеристика | Изменяемый (Mutable) | Неизменяемый (Immutable) |
| :--- | :--- | :--- |
| **Обновление в поде** | Автоматически (~60-90 сек для томов) | Требует Rolling Update пода |
| **Нагрузка на API** | Высокая (постоянные Watch-соединения) | Минимальная (разовое чтение GET) |
| **Целостность** | Риск рассинхрона между репликами | Гарантированная идентичность |
| **Rollback** | Сложный (нужен откат данных в CM) | Мгновенный (смена ссылки на старое имя) |
| **Применение** | Отладка, Feature Flags | Production, критическая инфраструктура |

### Безопасность при использовании immutable ConfigMap

#### RBAC-ограничения

```yaml
# Role для запрета создания immutable ConfigMap
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: immutable-configmap-blocker
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["create", "update", "patch"]
  # Ограничение: запрет immutable: true для определенных namespace
  resourceNames: ["app-config"]
```

#### Admission Control

```yaml
# ValidatingWebhookConfiguration для блокировки immutable ConfigMap
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: immutable-configmap-validator
webhooks:
  - name: validate-immutable-configmap.k8s.io
    rules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["configmaps"]
    failurePolicy: Fail
```

### Интеграция с CI/CD

#### GitHub Actions

```yaml
# .github/workflows/immutable-config.yaml
name: Deploy Immutable ConfigMap
on:
  push:
    paths:
      - 'k8s/configs/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Validate Immutable ConfigMap
        run: |
          # Проверка, что immutable: true установлен
          grep -l "immutable: true" k8s/configs/*.yaml || exit 1
          
      - name: Apply ConfigMap
        run: |
          kubectl apply -f k8s/configs/
          
      - name: Verify Deployment
        run: |
          kubectl rollout status deployment/my-app
```

### Мониторинг и алертинг

```yaml
# Prometheus-алерт на изменение immutable ConfigMap
- alert: ImmutableConfigMapChanged
  expr: |
    changes(kubernetes_configmap_info{immutable="true"}[5m]) > 0
  for: 0m
  labels:
    severity: critical
  annotations:
    summary: "Изменен immutable ConfigMap"
    description: "ConfigMap {{ $labels.name }} в namespace {{ $labels.namespace }} был изменен, хотя помечен как immutable"
```

### Стратегии очистки (Garbage Collection)

При использовании хешированных имен в кластере со временем накапливаются старые версии объектов.

#### Автоматическая очистка через ArgoCD/Flux

*   **ArgoCD:** Включите опцию **Auto-Prune** в Application spec:
    ```yaml
    spec:
      syncPolicy:
        automated:
          prune: true
    ```
*   **Flux:** Используйте опцию `spec.pruning: true` в Kustomization.

#### Ручная очистка

```bash
# Найти старые ConfigMap (старше 30 дней)
kubectl get configmap -A -o json | jq -r '
  .items[] | 
  select(.metadata.creationTimestamp < (now - 30*86400 | todate)) |
  "\(.metadata.namespace)/\(.metadata.name) \(.metadata.creationTimestamp)"
'

# Удалить старые ConfigMap с префиксом "app-config-"
kubectl get configmap -A -o name | grep "app-config-" | while read cm; do
  kubectl delete $cm
done
```

#### CronJob для автоматической очистки

```yaml
# cleanup-old-configmaps.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup-old-configmaps
spec:
  schedule: "0 2 * * *" # Ежедневно в 2:00
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: configmap-cleanup
          containers:
          - name: cleanup
            image: bitnami/kubectl:latest
            command:
            - /bin/sh
            - -c
            - |
              kubectl get configmap -A -o json | jq -r '
                .items[] |
                select(.metadata.name | test("^app-config-[a-f0-9]{6}$")) |
                select(.metadata.creationTimestamp < (now - 7*86400 | todate)) |
                "\(.metadata.namespace) \(.metadata.name)"
              ' | while read ns name; do
                kubectl delete configmap $name -n $ns
              done
          restartPolicy: OnFailure
```

### Рекомендации по эксплуатации

*   **Default to Immutable:** Считайте неизменяемость стандартом для всех конфигураций в стабильных окружениях.
*   **Используйте для Secret:** Применяйте этот же подход к [Secret](../secrets/security.md). Это дает аналогичный прирост производительности и безопасности.
*   **Sidecars (v1.29+):** Для нативных Sidecar-контейнеров использование неизменяемых конфигов критично, так как их жизненный цикл отличается от основных контейнеров, и рассинхрон конфигурации может привести к трудноуловимым ошибкам.
*   **Версионирование:** Всегда добавляйте суффикс версии к имени ConfigMap (например, `app-config-v1`, `app-config-v2`). Это обеспечивает:
    *   Отслеживание изменений через метаданные
    *   Возможность быстрого отката к предыдущей версии
    *   Аудит изменений через историю Git
*   **Валидация в CI:** Используйте `kubeconform` или `conftest` для проверки, что:
    *   Неизменяемые ConfigMap созданы с `immutable: true`
    *   Все обязательные поля заполнены
    *   Размер не превышает 1 MiB

### Границы применения

**Не используйте immutable ConfigMap когда:**

*   Конфигурация требует частых обновлений (несколько раз в день)
*   Приложение не поддерживает перезапуск без простоя
*   Используется feature flagging с динамическим переключением
*   Конфигурация зависит от внешних систем и меняется автоматически

**Альтернативы:**

*   **ConfigMap + Hot Reload:** Для приложений с поддержкой inotify/SIGHUP
*   **ConfigMap + External Reloader:** Для автоматического перезапуска (Reloader, Stakater)
*   **API Configuration:** Для критических приложений с задержкой <1с

### Граничные случаи (Edge Cases)

#### Удаление ConfigMap, используемого в поде

Если удалить immutable ConfigMap, который монтирован в Pod:
*   **Тома (Volumes):** Pod продолжает работать с кешем на узле. При перезапуске пода будет ошибка `FailedMount`.
*   **Переменные окружения:** Pod продолжает работать со старыми значениями. При перезапуске будет ошибка `CreateContainerConfigError`.

```bash
# Проверьте, какие поды используют ConfigMap
kubectl get pods -A -o json | jq -r '
  .items[] | 
  select(.spec.volumes[]?.configMap.name == "app-config-v1") |
  "\(.metadata.namespace)/\(.metadata.name)"
'
```

#### Конфликт имен при миграции

При миграции с mutable на immutable:
1. Создайте новый immutable ConfigMap с новым именем
2. Обновите Deployment для использования нового ConfigMap
3. Дождитесь завершения Rollout
4. Удалите старый mutable ConfigMap

```bash
# Безопасная миграция
kubectl create configmap app-config-v2 --from-file=config.yaml
kubectl patch configmap app-config-v2 -p '{"immutable":true}'
kubectl set env deployment/my-app CONFIG_MAP=app-config-v2
kubectl rollout status deployment/my-app
kubectl delete configmap app-config-v1
```

#### Работа с Projected Volumes

При использовании projected volumes с immutable ConfigMap:
```yaml
volumes:
- name: config-volume
  projected:
    sources:
    - configMap:
        name: immutable-config
        items:
        - key: "config.yaml"
          path: "config.yaml"
```

В этом случае:
*   Изменение metadata (labels/annotations) не влияет на содержимое тома
*   Для обновления данных необходимо создать новый ConfigMap и обновить под

**См. также:**

* [Создание ConfigMap](./creation.md) — обзор декларативного и генеративного подходов.
* [Лучшие практики ConfigMap](./best_practices.md) — нейминг, структура и безопасность.
* [Использование в подах](./pod_usage.md) — способы монтирования и ограничения.
* [Обновление и Rollout](./update_and_rollout.md) — стратегии актуализации настроек.
* [Работа с большими конфигурациями](./large_configs.md) — обход лимита 1 MiB.
* [Готовые шаблоны ConfigMap](./practical_templates.md) — шаблоны для Nginx, Prometheus, Postgres.
