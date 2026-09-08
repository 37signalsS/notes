# Паттерны и устранение неисправностей Helm

## Определения

**Паттерн Helm** — проверенное архитектурное или конфигурационное решение, обеспечивающее масштабируемость, безопасность, идемпотентность и простоту сопровождения чартов в среде **Helm v4**.

**Устранение неисправностей (Troubleshooting)** — процесс системной диагностики и исправления ошибок на этапах рендеринга шаблонов, разрешения зависимостей, линтинга, применения манифестов и восстановления работоспособности релизов при сбоях в кластере Kubernetes.

**Blueprint-паттерн** — централизованный шаблон чарта (скелет с жестко заданной структурой, хелперами и политиками), из которого генерируются новые чарты командой `helm create --starter` или копированием. Обеспечивает единообразие именования, меток, `securityContext` и ресурсных лимитов across сотен микросервисов.

**Field Ownership (SSA)** — в Helm v4 механизм Kubernetes Server-Side Apply, при котором API-сервер отслеживает, какой `field manager` (в данном случае Helm) управляет каждым полем манифеста. Это исключает «пинг-понг» при совместном использовании с внешними контроллерами (HPA, Kyverno, Istio-инъекторы).

**Идемпотентная миграция** — паттерн выполнения изменений схемы базы данных или внешних систем через Helm Job-хуки (`pre-upgrade`), гарантирующий, что повторный запуск не приведёт к дублированию данных или разрушительной операции. Реализуется через проверку текущей версии миграции перед её применением.

**Orphaned Resource (Осиротевший ресурс)** — объект Kubernetes, оставшийся в кластере после удаления или обновления чарта из-за изменения имени, отсутствия хуков очистки или ошибок в шаблонах. См. практический сценарий 5.

**Pending Install/Upgrade/Rollback** — промежуточный статус релиза, при котором Helm не может завершить операцию из-за конфликта ресурсов, ошибки в шаблоне или проблем с API-сервером. Повторные попытки управления релизом блокируются ошибкой `another operation is in progress`.

**Drift (Увод конфигурации)** — расхождение между состоянием ресурса в кластере и тем, что описан в чарте. В Helm v4 drift отслеживается через `managedFields`, но автоматического исправления нет — требуется `helm upgrade` с корректным манифестом.

**Chart.lock** — файл фиксации точных версий зависимостей, генерируемый `helm dependency update` и коммитируемый в VCS. Гарантирует воспроизводимость сборки: `helm dependency build` устанавливает зависимости строго по lock-файлу, без обновлений.

---

## Основные концепции

### Продвинутые паттерны проектирования чартов

#### 1. Библиотечные чарты (Library Charts)

Централизация общих хелперов и именованных шаблонов. Позволяет избежать дублирования логики формирования меток, селекторов и политик безопасности в сотнях микросервисов. См. **[Зависимости и библиотечные чарты](../helm_dependencies_and_library_charts.md)**.

**Архитектурный принцип:** Library-чарт не создаёт собственных Kubernetes-ресурсов, а служит контейнером для переиспользуемых функций. Дочерние чарты подключают его через секцию `dependencies` в `Chart.yaml` и обращаются к шаблонам через `include`.

**Практическое значение:** Изменение стандартной метки или политики безопасности в одном библиотечном чарте автоматически применяется ко всем прикладным чартам после пересборки зависимостей. Это критично для compliance в enterprise-средах, где изменение политик происходит регулярно.

#### 2. Зонтичные чарты (Umbrella Charts)

Агрегация множества независимых чартов в единый стек (например, стек логирования LGTM). Позволяет управлять жизненным циклом связанных компонентов как единым целым.

**Принцип работы:** Родительский чарт перечисляет все зависимые чарты в `dependencies` секции `Chart.yaml`. При `helm upgrade` агрегатора Helm автоматически обновляет все сабчарты в правильном порядке, учитывая их зависимости друг от друга.

**Ограничение:** Зонтичный чарт не предоставляет детального контроля над отдельными компонентами — для этого требуется внешний оркестратор (Helmfile, Helmwave, ArgoCD).

#### 3. Идемпотентные миграции

Использование Helm Jobs в связке с хуками (`pre-install`, `pre-upgrade`) для выполнения миграций баз данных. Паттерн требует строгой идемпотентности кода миграции.

**Теоретическое обоснование:** Helm не гарантирует однократного выполнения хука — при откате и повторном upgrade хук может запуститься повторно. Миграция, не являющаяся идемпотентной, приведёт к дублированию данных или ошибке.

**Реализация:** Миграционный Job должен проверять текущую версию схемы (через запрос к БД или проверку наличия таблицы/колонки) и пропускать уже применённые изменения. Используйте `helm.sh/hook-delete-policy: hook-succeeded` для очистки завершённых Job'ов.

#### 4. Управление ресурсами через SSA (Helm v4)

Использование Server-Side Apply позволяет Helm делить владение ресурсом с другими контроллерами (например, Istio-инъекторами или HPA), предотвращая конфликты «пинг-понга» конфигураций.

**Механизм:** В отличие от three-way merge в v3, SSA (v4) не вычисляет diff на стороне клиента. Helm передаёт манифест с указанием `field_manager=helm`, и API-сервер самостоятельно разрешает конфликты между полями, управляемыми разными менеджерами.

**Флаг `--force-conflicts`:** При миграции с Helm v3 на v4 или при необходимости захвата полей, ранее изменённых вручную (`kubectl edit`), используйте `--force-conflicts`. Helm перезапишет владение полями, но **только** для полей, присутствующих в его манифесте.

#### 5. Паттерн Skeleton

Использование эталонной структуры чарта для быстрой генерации новых сервисов. См. **[Helm Skeleton](../helm_skeleton_pattern.md)**.

#### 6. Паттерн Immutable Release (установка по дигесту)

Установка чарта по SHA-дигесту (`oci://registry.example.com/charts/app@sha256:...`) вместо семантического тега. Гарантирует криптографическую неизменность артефакта между пайплайном сборки и кластером. Критично для аудита и регуляторных требований.

**Отличие от тегирования:** Тег `:1.2.3` может быть перезаписан (tag moving), дигест — нет. При обновлении реестра (например, после пересборки чарта с той же версией) дигест остаётся уникальным идентификатором содержимого.

#### 7. Паттерн Values Layering (многослойные значения)

Использование нескольких файлов `values.yaml` с чётким порядком переопределения: `base values` → `environment values` → `cluster-specific overrides` → `runtime flags (--set)`. Каждый слой перекрывает предыдущий, что позволяет поддерживать единый чарт для dev/staging/prod без форков.

**Правило:** Базовый `values.yaml` коммитится в VCS. Environment-файлы (`values-prod.yaml`) — тоже в VCS, но в защищённом репозитории. Runtime-флаги (`--set`) — только для временных override в CI, не для постоянных конфигураций.

#### 8. Паттерн Blue/Green и Canary через Helm

Helm сам по себе не управляет трафиком, но обеспечивает инфраструктуру для blue/green и canary деплоев:

- **Blue/Green:** Два релиза (`app-blue`, `app-green`) с разными `values.yaml` (реплики, версия образа, Service selector). Переключение трафика — через изменение Service или Ingress.
- **Canary:** Установка Canary-релиза с меньшим количеством реплик и весом в Ingress/Service Mesh. Helm управляет только количеством реплик; маршрутизация — на стороне Ingress Controller или Service Mesh.

**Важно для SSA:** При переключении трафика оба релиза (blue и green) управляют **разными** Deployment-ами, поэтому конфликтов field ownership не возникает.

### Паттерны управления жизненным циклом релизов

#### 1. Атомарный деплой с защитой от drift

Комбинация флагов `--atomic --wait --wait-for-jobs --timeout 10m --cleanup-on-fail --history-max 5` обеспечивает:

- Откат при неуспехе rollout (`--atomic`).
- Ожидание готовности всех ресурсов (`--wait` + `--wait-for-jobs`).
- Удаление ресурсов неудавшегося релиза (`--cleanup-on-fail`).
- Ограничение истории для минимизации Secret-объектов (`--history-max 5`).

**Практическое правило:** Для production-чартов с Job-хуками (миграции БД) устанавливайте `--timeout` не менее `10m`. Короткий таймаут приведёт к `context deadline exceeded` при длительных миграциях, и Helm откатит релиз, хотя миграция могла завершиться успешно.

#### 2. Pre-flight проверки через хуки

Использование `pre-install` и `pre-upgrade` хуков для проверки:

- Доступности внешних зависимостей (БД, кэш, внешние API).
- Корректности RBAC-прав ServiceAccount.
- Соответствия namespace политикам PSA (Pod Security Admission).
- Наличия CRD, от которых зависит чарт.

**Пример pre-upgrade hook с dry-run проверкой:**
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ .Release.Name }}-preflight"
  annotations:
    "helm.sh/hook": pre-upgrade
    "helm.sh/hook-weight": "-10"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: {{ .Release.Name }}-preflight
      containers:
      - name: preflight
        image: "{{ .Values.tools.image }}:{{ .Values.tools.tag }}"
        command: ["sh", "-c", "kubectl auth can-i create deployment --as=system:serviceaccount:prod:helm-deployer"]
```

#### 3. Graceful Shutdown через hook delete policy

Для Job-хуков, изменяющих внешние системы (миграции, бэкапы), используйте комбинацию политик удаления:

```yaml
"helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
```

- `before-hook-creation` — удаляет предыдущий хук перед запуском нового (не накапливает Completed Job'ы).
- `hook-succeeded` — удаляет хук после успешного завершения.
- `hook-failed` — оставляет хук при ошибке для отладки (логи можно получить через `kubectl logs job/...`).

**Предупреждение:** `post-delete` хук не может быть откачен — он выполняется на удалении. Не размещайте в нём код, изменяющий внешние системы без подтверждения пользователя.

### Антипаттерны (Чего следует избегать)

- **Использование `latest` тегов**: Приводит к невозможности детерминированного отката (`helm rollback`) и нарушению reproducibility. Используйте семантические версии или SHA-дигесты.
- **Злоупотребление функцией `tpl`**: Динамический рендеринг строк из `values.yaml` затрудняет статический анализ и линтинг. Используйте `tpl` только для внешних шаблонов (например, NOTES.txt), но не для основной логики манифестов.
- **Хранение секретов в `values.yaml`**: Нарушает принципы безопасности. Используйте `helm-secrets` или External Secrets Operator.
- **Игнорирование `.helmignore`**: Увеличивает размер пакета чарта, что может привести к превышению лимита Secret релиза (1MB).
- **Монолитный чарт для множества сервисов**: Вместо Shared Chart или Skeleton, когда изменения в одном сервисе требуют пересборки всего чарта. Используйте Library Chart для общей логики и отдельные чарты для каждого сервиса.
- **Отсутствие `--atomic` в CI/CD**: При сбое rollout часть ресурсов применяется, часть — нет. Без `--atomic` кластер остаётся в промежуточном состоянии.
- **Жёсткая привязка к версиям Kubernetes без `.Capabilities`**: Адаптивные чарты, использующие `semverCompare` вместо проверки API через `.Capabilities.APIVersions.Has`, ломаются при миграции кластера на другую версию.
- **Ручное редактирование ресурсов, управляемых Helm**: Изменения через `kubectl edit` создают drift и конфликты field ownership при следующем `helm upgrade`. Все изменения должны проходить через чарт.

---

## Практические сценарии

### 1. Глубокая интроспекция и отладка шаблонов

Перед применением изменений всегда выполняйте проверку в «холостом» режиме.

**Инструменты отладки:**

- `helm template <name> <chart>` — локальный рендеринг. Помогает найти ошибки синтаксиса Go Templates, неверные отступы и опечатки в путях к values.
- `helm install <name> <chart> --dry-run --debug` — рендеринг + имитация установки с проверкой API-схем на стороне Kubernetes. Выводит итоговые манифесты и значения.
- `helm lint <chart>` — проверка структуры и соответствия стандартам. Обнаруживает отсутствующие зависимости, невалидные `Chart.yaml` и проблемы с `values.schema.json`.

**Диагностика проблем с пробельными символами и отступами:**

Go-шаблоны чувствительны к отступам. Если манифест рендерится с лишними пробелами или неправильными отступами:

```bash
# Включение отладочного вывода с исходными позициями
helm template my-release ./my-chart --debug 2>&1 | head -n 100
```

Для точной настройки отступов используйте функции `nindent` (с переносом строки) вместо `indent`, и `{{-` / `-}}` для обрезки пробелов вокруг блоков.

### 2. Проблема лимита размера релиза (Secret size limit)

**Проблема:** Данные релиза в Secret превышают лимит 1MB (ошибка `etcdserver: request is too large`).

**Решение:**
1. **Ограничение истории**: `helm upgrade ... --history-max 5`.
2. **Очистка пакета**: Убедитесь, что `.helmignore` исключает папки `.git`, `node_modules` и тяжелые медиа-файлы.
3. **Миграция на SQL**: В высоконагруженных средах Helm можно настроить на хранение состояний в SQL-базе вместо Secrets. Это релевантно для кластеров с десятками тысяч релизов.

**Диагностика:**
```bash
# Проверка размера Secret релиза
kubectl get secret sh.helm.release.v1.<release>.v<N> -n <ns> -o jsonpath='{.data.release}' | base64 -d | wc -c
# → 1048576 (1MB) или больше
```

### 3. Восстановление «зависшего» релиза (`pending-install`, `pending-upgrade`, `pending-rollback`)

**Проблема:** Релиз заблокирован в промежуточном статусе. Повторные попытки выдают ошибку: `another operation is in progress`.

**Решение:**
1. **Ручная очистка секрета**:
   ```bash
   # Поиск секрета последней ревизии
   kubectl get secret -n <ns> -l owner=helm,name=<release> --sort-by=.metadata.creationTimestamp
   # Удаление секрета с последней (неудачной) ревизии
   kubectl delete secret sh.helm.release.v1.<release>.v<N> -n <ns>
   ```
2. **Форсированный откат**: `helm rollback <release> <last-working-version>`.

**Диагностика статуса:**
```bash
# Подробный статус релиза
helm status <release> -n <ns> --show-details
# → STATUS: pending-install, DESCRIPTION: ...

# История ревизий
helm history <release> -n <ns>
```

**Важно:** В Helm v4 при использовании SSA зависший релиз может оставить ресурсы в кластере без владельца Helm. После очистки секрета проверьте:
```bash
kubectl get all,secret,configmap,serviceaccount,role,rolebinding -n <ns> -l app.kubernetes.io/managed-by=Helm
```

### 4. Конфликты владения полями в Helm v4 (SSA)

**Проблема:** Ошибка `Apply failed due to conflicts` при использовании Server-Side Apply.

**Решение:**
1. **Анализ владельцев**: `kubectl get <resource> -o yaml` → секция `managedFields`.
2. **Разрешение конфликта**:
   - Если поле должно управляться Helm: `helm upgrade ... --force-conflicts`.
   - Если поле должно управляться внешним инструментом (например, HPA): удалите это поле из чарта или используйте `ignoreDifferences` (в ArgoCD).

**Теория конфликтов:**
В SSA каждый field manager фиксирует своё владение полем при первом `apply`. При попытке Helm управлять полем, уже захваченным другим менеджером (например, Kyverno mutate, изменивший `securityContext`), API-сервер возвращает конфликт. Helm v4, в отличие от v3, не затирает чужие поля автоматически.

### 5. Поиск «осиротевших» ресурсов (Orphaned Resources)

**Проблема:** При удалении или обновлении чарта некоторые ресурсы остаются в кластере (например, из-за изменения имен или ошибок в хуках).

**Решение:**
1. **Использование меток**: Все ресурсы чарта должны иметь стандартные метки `app.kubernetes.io/managed-by: Helm`.
2. **Поиск**:
   ```bash
   kubectl get all -A -l app.kubernetes.io/managed-by=Helm
   ```
3. **Автоматизация**: Использование GitOps-инструментов (ArgoCD) с включенным `Prune`, которые автоматически удаляют ресурсы, отсутствующие в текущем состоянии чарта.

**Ручная очистка orphaned-ресурсов:**
```bash
# Поиск всех ресурсов с меткой Helm в namespace
kubectl get all,secret,configmap,serviceaccount,role,rolebinding,networkpolicy,poddisruptionbudget \
  -n <ns> -l app.kubernetes.io/managed-by=Helm

# Для ресурсов без стандартной метки (созданных вручную или старыми версиями чарта):
kubectl get all -n <ns> | grep <release-name-prefix>
```

### 6. Ошибки рендеринга шаблонов (Template Rendering Errors)

**Проблема:** Helm завершается с ошибкой `template: ...: executing ... at <.Values...>: invalid value; expecting ...` или `at <.Chart...>: invalid value`.

**Решение:**
1. **Проверка типов значений:** Убедитесь, что в `values.yaml` значение соответствует ожидаемому типу в шаблоне.
   ```bash
   # Рендеринг с подroscомом значений
   helm template my-release ./my-chart --debug
   ```
2. **Проверка `values.schema.json`:** При наличии JSON Schema Helm автоматически валидирует типы на этапе рендеринга.
   ```bash
   # Рендеринг с принудительной проверкой схемы
   helm template my-release ./my-chart -f values.yaml
   ```
3. **Типичные причины:**
   - Передача строки там, где ожидается число: `--set replicas=abc`.
   - Отсутствие обязательного поля: `required "image.tag" not provided`.
   - Неверный синтаксис Go Template: отсутствие `{{ }}`, неверные кавычки.

### 7. Конфликты зависимостей и `Chart.lock`

**Проблема:** `helm dependency update` не может разрешить версии зависимостей, или `helm install` падает с `found in Chart.yaml, but missing in charts/ directory`.

**Решение:**
1. **Фиксация зависимостей:** Всегда используйте `helm dependency build` (по `Chart.lock`) в CI, а не `helm dependency update`.
2. **Явное указание репозиториев:** В `Chart.yaml` указывайте полный URL или OCI-ссылку для каждой зависимости.
3. **Проверка `condition` и `tags`:** Зависимость может быть отключена через `values.yaml`. Убедитесь, что флаг `condition` не установлен в `false`.

**Диагностика:**
```bash
# Проверка lock-файла
cat Chart.lock | grep -A 5 '"name": "postgresql"'

# Принудительная пересборка зависимостей
helm dependency build --skip-refresh ./my-chart
```

### 8. Сбои хуков (Hook Failures)

**Проблема:** Релиз переходит в статус `failed` после ошибки в Job-хуке.

**Диагностика:**
```bash
# Просмотр статуса hook-ресурсов
kubectl get job -n <ns> -l helm.sh/hook=pre-upgrade

# Логи hook-пода
kubectl logs job/<release>-migrate -n <ns>

# Описание hook-пода для просмотра событий
kubectl describe pod <release>-migrate-<hash> -n <ns>
```

**Решение:**
1. **Исправьте ошибку в шаблоне или логике хука** (неверный пароль к БД, отсутствующий ConfigMap).
2. **Удалите failed-ресурс хука** (если `hook-failed` не задан):
   ```bash
   kubectl delete job <release>-migrate -n <ns>
   ```
3. **Повторите upgrade** с флагом `--atomic`:
   ```bash
   helm upgrade <release> ./my-chart --atomic --wait
   ```

**Предупреждение:** Hook Job с `restartPolicy: Never` и `backoffLimit: 0` не перезапускается автоматически. Это правильный подход для миграций, но требует исправления причины сбоя перед повторным запуском.

### 9. Проблемы с CRD и порядком применения ресурсов

**Проблема:** При установке чарта с CRD и зависящими от него ресурсами возникает ошибка `the server could not find the requested resource` (например, `CustomResourceDefinition` не установлен, но уже создаётся `MyCustomResource`).

**Причина:** Helm создаёт ресурсы в определённом порядке (Namespace → ServiceAccount → Secret → ConfigMap → CRD → ClusterRole → Deployment → Service). Если чарт содержит CRD в директории `crds/`, они применяются **до** рендеринга шаблонов. Но если CRD лежит в `templates/` (устаревший подход), порядок применения зависит от сортировки по Kind, что ненадёжно.

**Решение (Helm v4):**
1. **Переместите CRD в директорию `crds/`.** Helm применяет их первыми, без SSA и без хуков.
2. **Для зависимых ресурсов:** добавьте проверку в шаблон:
   ```yaml
   {{- if .Capabilities.APIVersions.Has "example.com/v1/MyCustomResource" }}
   apiVersion: example.com/v1
   kind: MyCustomResource
   ...
   {{- end }}
   ```

**Важно:** В Helm v4 CRD из `crds/` не подлежат откату через `helm rollback` — они остаются в кластере после удаления релиза. Это защита от случайного удаления критических определений ресурсов.

### 10. Предупреждение о несовместимости API-версий

**Проблема:** Чарт рендерит `apiVersion: networking.k8s.io/v1beta1`, но кластер работает на Kubernetes 1.25+, где API удалён.

**Решение:**
1. **Адаптивные шаблоны:** Используйте `.Capabilities.APIVersions.Has` для условного выбора API.
   ```yaml
   {{- $ingressApi := "networking.k8s.io/v1" -}}
   {{- if not (.Capabilities.APIVersions.Has "networking.k8s.io/v1/Ingress") -}}
     {{- $ingressApi = "networking.k8s.io/v1beta1" -}}
   {{- end -}}
   apiVersion: {{ $ingressApi }}
   ```
2. **Статическая валидация:** Используйте `kubeconform` в CI с флагом `-strict` для проверки соответствия схеме целевой версии Kubernetes.

### 11. Проблемы с предельными значениями и ресурсами (Resource Quota)

**Проблема:** При установке чарта в namespace с жёсткими `ResourceQuota` или `LimitRange` Pod'ы не создаются или переходят в `CreateContainerConfigError`.

**Диагностика:**
```bash
# Проверка событий namespace
kubectl get events -n <ns> --sort-by='.lastTimestamp' | grep -i quota

# Проверка ResourceQuota
kubectl get resourcequota -n <ns> -o yaml

# Проверка LimitRange
kubectl get limitrange -n <ns> -o yaml
```

**Решение:**
1. Увеличьте лимиты в `values.yaml` (requests/limits cpu/memory).
2. Используйте `LimitRange` для автоматического установления лимитов на поды, если namespace их требует.
3. Для чартов, устанавливающих HPA, убедитесь, что `requests` не равны `limits` (HPA не работает с одинаковыми значениями в v4 без `resourcePolicy`).

### 12. Откат релиза и edge cases `helm rollback`

**Проблема:** `helm rollback` падает с `no available release name found` или `unable to rollback to specified revision`.

**Причины:**
1. `--history-max` слишком мал, и нужная ревизия удалена.
2. Релиз в статусе `failed`, и Helm не может определить целевую ревизию.
3. Релиз был удалён (`helm uninstall`), но `--keep-history` был указан — rollback возможен только если Secret ревизии существует.

**Решение:**
```bash
# Проверка доступных ревизий
helm history <release> -n <ns>

# Откат к конкретной ревизии
helm rollback <release> <revision> -n <ns> --wait --timeout 5m

# Если rollback падает из-за конфликта ресурсов:
helm rollback <release> <revision> -n <ns> --force
```

**Внимание:** При rollback Helm создаёт **новую** ревизию (N+1), а не восстанавливает старую. История сохраняется последовательно.

### 13. Проблемы с сетью и доступом к реестрам (OCI/HTTP)

**Проблема:** `helm install` или `helm dependency build` падает с `context deadline exceeded`, `dial tcp ... i/o timeout` или `failed to fetch ...`.

**Решение:**
1. **Проверка прокси:** В корпоративных сетях настройте переменные окружения:
   ```bash
   export HTTPS_PROXY="http://proxy.corp.local:8080"
   export NO_PROXY=".cluster.local,.svc,.internal"
   ```
2. **Сертификаты:** Для OCI-реестров с самоподписанными сертификатами добавьте их в trust store:
   ```bash
   helm registry login registry.corp.local --ca-file /path/to/ca.crt
   ```
3. **DNS:** Проверьте разрешение имён:
   ```bash
   nslookup registry.example.com
   dig registry.example.com
   ```

### 14. Миграция с Helm v3 на v4: типичные проблемы

**Проблема:** После обновления Helm на v4 `helm upgrade` падает с неожиданными ошибками, или хуки ведут себя иначе.

**Основные отличия и точки миграции:**
- **Пост-рендереры:** В v4 только плагины типа `postrenderer/v1`. Прямые пути к shell-скриптам больше не поддерживаются.
- **GPG-верификация плагинов:** При `helm plugin install` из git-URL проверяется GPG-подпись тега. Для legacy-плагинов используйте `--verify=false` или импортируйте ключ в keyring.
- **SSA по умолчанию:** `helm upgrade` без флагов использует SSA. Если чарт содержит ресурсы, изменённые вручную, добавьте `--force-conflicts` или очистите `managedFields`.
- **CRD в `crds/`:** В v4 CRD из `crds/` не подлежат SSA и хукам. Если в v3 CRD лежал в `templates/`, переместите его.

### 15. Диагностика и линтинг в CI/CD

**Проблема:** Чарт проходит локальный `helm lint`, но падает в CI или на кластере.

**Решение:** Используйте многоуровневую валидацию, имитирующую production:

```bash
# 1. Линтинг (синтаксис и структура)
helm lint ./my-chart

# 2. Валидация входных данных через JSON Schema
helm template my-release ./my-chart -f values.yaml

# 3. Валидация манифестов (kubeconform)
helm template my-release ./my-chart | kubeconform -strict -summary -

# 4. Проверка на соответствие политикам (conftest)
helm template . | conftest test -

# 5. Проверка устаревших API
helm template . | yq '.*.apiVersion' | sort | uniq
```

### 16. Отладка hook-ресурсов и lifecycle

**Проблема:** Релиз зависает на хуке (например, pre-upgrade Job завершается с ошибкой, но Helm не откатывается).

**Диагностика:**
```bash
# Все ресурсы хуков текущего релиза
kubectl get all,job -n <ns> -l helm.sh/hook

# События namespace
kubectl get events -n <ns> --sort-by='.lastTimestamp'

# Helm-события (если установлен Helm Dashboard или EventLogger)
kubectl get events -n <ns> --field-selector reason=Helm
```

**Решение:**
1. Удалите failed-хук вручную (если `hook-failed` не задан).
2. Исправьте причину сбоя (неверный образ, отсутствующий Secret, ошибка RBAC).
3. Повторите upgrade с `--atomic --wait`.

### 17. Проблемы с namespaces и RBAC

**Проблема:** `helm install` падает с `namespaces is forbidden` или `deployments.apps is forbidden`.

**Решение:**
1. **Проверка kubeconfig:** Helm v3/v4 использует kubeconfig текущего пользователя. Убедитесь, что контекст указывает на правильный кластер и namespace:
   ```bash
   kubectl config current-context
   kubectl config view --minify --output 'jsonpath={..namespace}'
   ```
2. **RBAC-отладка:**
   ```bash
   # Проверка прав текущего пользователя
   kubectl auth can-i create deployment --namespace=<ns>
   kubectl auth can-i create secret --namespace=<ns>
   ```
3. **Автоматизация:** Для CI/CD создайте отдельный ServiceAccount с минимальными правами (см. **[Безопасность Helm](./security_best_practices.md)**).

### 18. Диагностика проблем с `helm diff`

**Проблема:** Плагин `helm diff` показывает неожиданные изменения или падает с ошибкой парсинга YAML.

**Решение:**
1. **Обновите плагин:** Убедитесь, что версия `helm-diff` совместима с Helm v4.
   ```bash
   helm plugin upgrade diff
   ```
2. **Проверка вывода:** `helm diff` работает через рендеринг шаблонов. Если шаблон содержит невалидный YAML, плагин может неверно парсить вывод. Сначала проверьте `helm template`.
3. **Игнорирование полей:** Используйте `--suppress` для полей, меняющихся на каждом релизе (например, `helm.sh/release.v123`):
   ```bash
   helm diff upgrade my-release ./my-chart --suppress "helm.sh/release"
   ```

---

## Систематическая диагностика

Для типичных инцидентов используйте следующий алгоритм:

### Шаг 1: Определение статуса релиза

```bash
helm list -A -o wide | grep <release>
helm status <release> -n <ns> --show-details
```

| Статус | Следующее действие |
|--------|-------------------|
| `deployed` | Проверка drift через `kubectl get <resource> -o yaml` → `managedFields` |
| `pending-install` | Очистка секрета неудавшейся ревизии (сценарий 3) |
| `pending-upgrade` | Проверка hook-ресурсов и событий namespace |
| `pending-rollback` | Очистка секрета + принудительный rollback |
| `failed` | Просмотр событий, hook-логов, затем ручная очистка или `helm rollback` |

### Шаг 2: Проверка ресурсов кластера

```bash
# Все ресурсы релиза
kubectl get all,secret,configmap,serviceaccount,role,rolebinding,networkpolicy \
  -n <ns> -l app.kubernetes.io/instance=<release>

# События namespace
kubectl get events -n <ns> --sort-by='.lastTimestamp' | tail -n 20

# Секреты Helm
kubectl get secret -n <ns> -l owner=helm,name=<release>
```

### Шаг 3: Локальный рендеринг и линтинг

```bash
helm lint ./my-chart
helm template <release> ./my-chart -f values.yaml | head -n 50
helm template <release> ./my-chart --debug 2>&1 | tail -n 30
```

### Шаг 4: Проверка зависимостей и конфигурации

```bash
# Валидность Chart.yaml
cat Chart.yaml | yq '.dependencies'

# Проверка lock-файла
cat Chart.lock

# Размер пакета чарта
helm package ./my-chart --dry-run
tar -tzf my-chart-1.0.0.tgz | wc -l
```

### Шаг 5: Dry-run на сервере

```bash
helm upgrade --install <release> ./my-chart \
  --dry-run --debug --atomic --timeout 30s
```

Если dry-run проходит, но реальный деплой падает — проблема в состоянии кластера (квоты, сеть, admission-контроллеры).

---

## Ограничения и известные проблемы

- **SSA и устаревшие API:** Некоторые старые версии Kubernetes (<1.18) не поддерживают полный функционал SSA и Field Ownership. При миграции на Helm v4 в кластерах с устаревшими API требуется предварительное обновление Kubernetes.
- **CRD в `crds/`:** В Helm v4 CRD из директории `crds/` не подлежат SSA, хукам и откату. После удаления релиза CRD остаётся в кластере. Это защита, но может приводить к накоплению неиспользуемых CRD.
- **`tpl` и статический анализ:** Использование `tpl` для динамического рендеринга строк из `values.yaml` делает невозможным статический анализ шаблонов. Линтеры и helm-unittest не могут проверить корректность выражения, если оно формируется динамически.
- **`.Capabilities` в client-side dry-run:** При `helm install --dry-run=client` объект `.Capabilities` пуст/дефолтен. Адаптивные шаблоны, использующие `.Capabilities.APIVersions.Has`, могут давать результат, отличный от server-side. Для CI-проверки используйте `--dry-run=server` либо явно задавайте capabilities флагами `--kube-version` и `--api-versions`.
- **Лимит истории и откат:** `--history-max N` ограничивает количество ревизий. Если откатить нужно к ревизии, удалённой лимитом — команда завершится ошибкой `unable to rollback to specified revision`. Для критических production-релизов используйте `--history-max 10` или храните манифесты ревизий отдельно.
- **Пост-рендеринг без доступа к API:** Пост-рендерер работает только с статическими YAML-манифестами, не видит состояние кластера. Для динамических мутаций (например, добавление аннотаций в зависимости от существующих ресурсов) нужны admission webhooks (Kyverno mutate, OPA Gatekeeper).
- **WASM-плагины и производительность:** На данный момент не все плагины v3 имеют портированные версии для WASM. Плагины, требующие длительных операций или интенсивного доступа к файловой системе, могут иметь ограничения производительности в песочнице Extism.
- **OCI в изолированных сетях:** При работе через корпоративные прокси и файрволы требуется предварительная настройка доверенных корневых сертификатов. Дигесты артефактов должны проверяться на этапе сборки, так как в изолированных сетях может отсутствовать возможность повторной проверки через удалённый реестр.
- **Helm v3 EOL:** баг-фиксы до 8 июля 2026 года, security-фиксы до 11 ноября 2026 года. Планируйте миграцию на v4 в этот промежуток.

---

## Дополнительная информация

- **[Обзор Helm](../helm_overview.md)** — основы и архитектура v4.
- **[Команды и рабочий процесс](../helm_commands_and_workflow.md)** — интроспекция и управление релизами.
- **[Безопасность Helm](./security_best_practices.md)** — работа с секретами и RBAC.
- **[Хуки и тестирование](../helm_hooks_and_tests.md)** — управление жизненным циклом ресурсов.
- **[Юнит-тестирование чартов](./unit_testing.md)** — превентивное обнаружение ошибок в шаблонах.
- **[Зависимости и библиотечные чарты](../helm_dependencies_and_library_charts.md)** — композиция и управление версиями.
- **[Helm Skeleton](../helm_skeleton_pattern.md)** — стандартизация структуры чартов.
- **[Практические сценарии Helm-чартов](../helm_chart_practical_scenarios.md)** — umbrella-чарты и Shared Chart.
