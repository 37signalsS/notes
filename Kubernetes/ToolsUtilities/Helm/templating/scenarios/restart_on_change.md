# Автоматический перезапуск подов (Restart on Change)

---

## Определения

**Checksum-аннотации (аннотации контрольной суммы)** — специальные метаданные, размещаемые в секции `spec.template.metadata.annotations` контроллеров Kubernetes (Deployment, StatefulSet, DaemonSet). Они содержат криптографический хеш (SHA-256) отрендеренного содержимого конфигурационных файлов (ConfigMap или Secret). Изменение этого хеша при обновлении чарта вынуждает Kubernetes запустить процесс плавного обновления (Rolling Update) для применения новых настроек.

**SHA-256** — криптографическая хеш-функция из семейства SHA-2, генерирующая 256-битный (64 hex-символа) отпечаток. В контексте паттерна используется за счёт Detectable Collision Resistance: вероятность случайного совпадения хешей для двух разных конфигураций пренебрежимо мала (~2⁻²⁵⁶), что исключает ложные срабатывания перезапуска при различиях в пробелах или форматировании без изменения семантики.

**Rolling Update** — стратегия обновления контроллера Kubernetes, при которой поды заменяются постепенно (wave by wave) с соблюдением параметров `maxSurge` и `maxUnavailable`. Каждое изменение `spec.template` создаёт новую ревизию ReplicaSet; старые поды завершаются только после подтверждения готовности новыми (Readiness Probe).

**ReplicaSet** — контроллер Kubernetes, отвечающий за поддержание заданного количества экземпляров пода (`replicas`). Для Deployment каждой ревизии шаблона пода соответствует отдельный объект ReplicaSet; количество сохраняемых ревизий ограничено `revisionHistoryLimit` (по умолчанию 10).

**Template Spec** — секция `spec.template` внутри Deployment/StatefulSet/DaemonSet, содержащая метаданные пода и спецификацию контейнеров. Kubernetes инициирует Rolling Update только при изменении этой секции, что делает её единственным местом для размещения checksum-аннотаций.

**Config Skew Window** — временной интервал, в течение которого поды одного приложения работают с разными версиями конфигурации. Возникает потому, что узлы синхронизируют тома независимо, а пересоздаваемые поды новой ревизии готовностью отличаются от ещё работающих старых.

**Immutable ConfigMap** — ConfigMap с флагом `immutable: true`, который запрещает изменение данных после создания. Для обновления конфигурации необходимо создать новый объект с новым именем. Использование в связке с checksum-аннотацией гарантирует, что обновление конфигурации требует явного изменения версии чарта.

**Hot Reload** — способность приложения перечитывать конфигурационные файлы без перезапуска основного процесса, часто реализуемая через отслеживание событий файловой системы (`inotify`) или получение внешнего сигнала (SIGHUP, HTTP-запрос). Паттерн "Restart on Change" используется как альтернатива для приложений, не поддерживающих Hot Reload.

**Helm Release Revision** — номер версии релиза Helm, увеличивающийся при каждом `helm upgrade` или `helm rollback`. История ревизий хранится в секрете Kubernetes и может быть просмотрена через `helm history`.

---

## Основные концепции

### Принцип работы

1. В спецификацию шаблона пода (`spec.template`) добавляется аннотация, имя которой обычно начинается с `checksum/` (например, `checksum/config`).
2. В качестве значения аннотации вычисляется хеш-сумма от содержимого файлов конфигурации с помощью функций Helm.
3. При выполнении команд `helm upgrade`, `helm install` или `helm rollback` Helm заново рендерит все шаблоны. Если данные в ConfigMap или Secret изменились по сравнению с текущим состоянием в кластере (или при переходе между ревизиями), итоговая строка хеша также изменится.
4. Kubernetes отслеживает изменения в `spec.template`. Любое изменение в этой секции (включая только аннотации) приводит к созданию новой ревизии ReplicaSet (для Deployment) и инициации Rolling Update.

### Жизненный цикл паттерна

Полный цикл применения паттерна "Restart on Change" в рамках одного `helm upgrade`:

1. **Рендеринг Helm:** Движок шаблонов обрабатывает все файлы в `templates/`, подставляя значения из `values.yaml` и CLI-флагов. В результате формируется YAML-манифест Deployment с аннотацией `checksum/config`.
2. **Вычисление хеша:** Функция `include` рендерит целевой шаблон (например, `configmap.yaml`) с учётом текущих `.Values`. Результат передаётся в `sha256sum`, генерирующий 64-символьную строку.
3. **Сравнение с кластером:** Helm запрашивает у API-сервера текущий объект Deployment в указанном Namespace. Если значение аннотации `checksum/config` в кластере совпадает с только что вычисленным — Rolling Update не требуется.
4. **Инициация обновления:** При расхождении Helm применяет новый манифест. Kubernetes создаёт новую ревизию ReplicaSet, которая начинает постепенно заменять поды согласно `strategy.rollingUpdate`.
5. **Синхронизация конфигурации:** Для томов (volumes) kubelet загружает актуальный ConfigMap через механизм симлинков `..data` (атомарное переключение). Для переменных окружения новые поды получают актуальные значения из обновлённого шаблона пода.

### Архитектура и взаимодействие компонентов

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  values.yaml │────>│   Helm       │────>│  Kubernetes  │
│  templates/  │     │  (рендеринг) │     │  API Server  │
│  Chart.yaml  │     │              │     │              │
└──────────────┘     └──────┬───────┘     └──────┬───────┘
                            │                    │
                            ▼                    ▼
                     sha256sum              spec.template
                    (вычисление)          (изменение → Rolling Update)
                            │                    │
                            ▼                    ▼
                     ┌──────────────┐     ┌──────────────┐
                     │  ConfigMap   │<────│  kubelet     │
                     │  (данные)    │     │  (sync 60-90s)│
                     └──────────────┘     └──────────────┘
```

**Компоненты:**
- **Helm** — источник истины для шаблонов и значений; вычисляет контрольную сумму.
- **Kubernetes API Server** — хранилище желаемого состояния (Deployment, ConfigMap).
- **Kubelet** — агент на узле, отвечающий за синхронизацию файлов ConfigMap на диск пода.
- **Controller Manager** — создаёт новые ReplicaSet и управляет волнами обновления.
- **Kube-proxy** — обновляет iptables/IPVS правила для новых подов (не зависит от паттерна, но важен для доступности).

### Почему это необходимо

Kubernetes обладает специфическим поведением при обновлении внешних конфигураций:
- **Переменные окружения (`env`, `envFrom`):** Значения считываются только в момент старта контейнера. Если ConfigMap в API обновится, переменные в уже запущенном поде останутся старыми до ручного перезапуска.
- **Тома (`volumes`):** Изменения в ConfigMap/Secret синхронизируются на файловую систему пода через `kubelet` с задержкой (по умолчанию до 1-2 минут). Однако большинство приложений считывают конфиг один раз при старте и не отслеживают изменения файлов (отсутствие механизма Hot Reload через `inotify`).

Использование паттерна "Restart on Change" гарантирует, что приложение всегда работает с актуальной конфигурацией, так как обновление настроек автоматически влечет за собой контролируемый перезапуск всех экземпляров приложения.

### Ключевые функции Helm

| Функция | Назначение в контексте паттерна |
| :--- | :--- |
| `print` | Формирует полный путь к файлу шаблона внутри чарта для функции `include`. |
| `include` | Рендерит указанный шаблон и возвращает результат как строку, что позволяет передавать его в пайплайн. |
| `sha256sum` | Генерирует SHA-256 отпечаток. Использование SHA-256 предпочтительнее `sha1sum` из-за более высокой устойчивости к коллизиям. |
| `tpl` | Позволяет обработать строку как полноценный шаблон Helm (необходимо для динамических конфигов). |
| `toYaml` | Преобразует структуру данных (Map/List) в YAML-строку для последующего хеширования. |

### Сравнение алгоритмов хеширования

| Алгоритм | Длина хеша | Стойкость к коллизиям | Рекомендация для аннотаций |
| :--- | :--- | :--- | :--- |
| `sha1sum` | 40 hex | Низкая (NIST отозвал для цифровых подписей в 2011) | Не рекомендуется |
| `sha256sum` | 64 hex | Высокая (2⁻²⁵⁶) | **Стандарт де-факто** |
| `sha512sum` | 128 hex | Очень высокая (2⁻⁵¹²) | Избыточен для аннотаций |

SHA-256 является оптимальным выбором: длина 64 символа укладывается в лимит размера аннотаций Kubernetes (256 KiB), а вычислительная стоимость пренебрежимо мала по сравнению с рендерингом шаблонов.

### Сравнение методов автоматизации перезапуска

| Метод | Механизм | Плюсы | Минусы | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Checksum-аннотации (Helm)** | Хеш ConfigMap/Secret в `spec.template.metadata.annotations` | Стандартный для Helm, не требует дополнительных компонентов, работает в GitOps | Не видит правок вне Git, требует хеширования каждого ресурса | Основной метод для Helm-чартов |
| **Reloader (контроллер)** | Watch API + модификация шаблона пода | Видит изменения напрямую в кластере, поддерживает CSI, не требует изменения чартов | Дополнительный контроллер в кластере, потребляет ресурсы | Для legacy-приложений и mixed-окружений |
| **Kustomize Name Hashing** | Добавление суффикса-хеша к имени ConfigMap | Встроено в Kustomize, автоматическое обновление ссылок | Только для Kustomize-пайплайнов, меняет имя ресурса | Альтернатива для Kustomize-пользователей |
| **Sidecar configmap-reload** | Контейнер в поде, отслеживающий файлы | Точечная перезагрузка без rollout, атомарность | Требует изменения образа/чарта, `shareProcessNamespace` | Для приложений с Hot Reload эндпоинтом |
| **kubectl rollout restart** | Императивная команда, добавляет `restartedAt` | Простой, не требует изменений чарта | Не автоматизируется без CI/CD-скрипта, нет связи с содержимым ConfigMap | Ручное управление / emergency |

---

## Практические сценарии

### Предварительные требования

- **Helm 3.x:** CLI установлен и сконфигурирован с доступом к целевому кластеру (`kubectl config current-context`).
- **Kubernetes 1.20+:** Поддержка аннотаций в `spec.template` стандартизирована.
- **Чарт:** Структура чарта соответствует стандарту Helm (`Chart.yaml`, `values.yaml`, `templates/`).
- **RBAC:** ServiceAccount, используемый для деплоя, имеет права `get`, `list`, `watch`, `create`, `update`, `patch` на Deployment, ConfigMap, Secret в целевом Namespace.
- **Знания:** Понимание механики Rolling Update, разницы между `env` и `volume` подключением ConfigMap.

### Deployment с ConfigMap

Использование глобального контекста `$` позволяет корректно вычислять пути даже внутри вложенных циклов (`range`).

**templates/configmap.yaml:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  app.conf: |
    server_port: {{ .Values.server.port | default 8080 }}
    log_level: {{ .Values.logging.level | default "info" }}
```

**templates/deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: {{ include "myapp.name" . }}
  template:
    metadata:
      annotations:
        # Автоматический перезапуск при изменении configmap.yaml
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        - name: app
          image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
          volumeMounts:
            - name: config-volume
              mountPath: /etc/app
      volumes:
        - name: config-volume
          configMap:
            name: {{ include "myapp.fullname" . }}-config
```

### StatefulSet и DaemonSet

Для этих контроллеров механизм идентичен — аннотация должна находиться строго внутри `spec.template.metadata`. Это инициирует обновление подов согласно `updateStrategy` (например, `RollingUpdate` или `OnDelete`).

**templates/daemonset.yaml:**
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: {{ include "myapp.fullname" . }}-agent
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        - name: agent
          image: {{ .Values.agent.image }}
          volumeMounts:
            - name: config
              mountPath: /etc/agent
      volumes:
        - name: config
          configMap:
            name: {{ include "myapp.fullname" . }}-config
```

### Сценарий с Secret (Обновление паролей)

При хешировании секретов важно помнить, что хеш будет храниться в открытом виде в аннотациях Deployment. Хотя это необратимый хеш, само наличие изменений в секрете становится видимым в манифесте пода.

**templates/secret.yaml:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "myapp.fullname" . }}-secret
type: Opaque
data:
  db-password: {{ .Values.db.password | b64enc | quote }}
```

**templates/deployment.yaml (фрагмент):**
```yaml
spec:
  template:
    metadata:
      annotations:
        # Хешируется отрендеренный YAML секрета
        checksum/secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
```

### Динамические файлы и каталоги (Files.Glob)

Если ConfigMap собирается из множества файлов в папке (например, `configs/`), необходимо вычислить суммарный хеш, учитывающий и пути, и содержимое.

```yaml
annotations:
  # Хеширование всех файлов в папке configs для отслеживания любых изменений
  checksum/all-configs: {{ range $path, $bytes := $.Files.Glob "configs/**" }}{{ $path }}{{ $bytes | sha256sum }}{{ end | sha256sum }}
```

### Хеширование объектов из Values

Если конфигурация передаётся непосредственно в `values.yaml` в виде объекта, можно использовать `toYaml` для получения стабильного строкового представления перед хешированием.

```yaml
annotations:
  # Хеширование всего блока параметров из values.yaml
  checksum/params: {{ .Values.appConfig | toYaml | sha256sum }}
```

### Многоокружная стратегия

Для окружений dev/staging/prod используйте отдельные файлы значений, объединяемые через `-f`:

```bash
# Развёртывание в production с перезаписью дефолтов
helm upgrade myapp ./mychart \
  -f values.yaml \
  -f values-dev.yaml \
  -f values-production.yaml \
  --namespace production
```

**Структура values-production.yaml:**
```yaml
replicaCount: 5
server:
  port: 8443
logging:
  level: warn

# Отдельный ConfigMap для production (отслеживается отдельным хешем)
configMap:
  enabled: true
  source: configs/prod/
```

При изменении любого из переопределённых ключей итоговый хеш `checksum/config` изменится, что вызовет Rolling Update.

### Интеграция с CI/CD пайплайном

Типовой этап для GitLab CI / GitHub Actions / Jenkins:

```yaml
# .gitlab-ci.yml фрагмент
deploy:
  stage: deploy
  image: alpine/helm:3.22.0
  script:
    - helm upgrade myapp ./mychart \
        -f values.yaml \
        -f values-$CI_ENVIRONMENT_NAME.yaml \
        --namespace $K8S_NAMESPACE \
        --atomic \
        --timeout 5m
  only:
    - main
```

**Ключевые флаги:**
- `--atomic`: автоматический откат при ошибке деплоя.
- `--timeout`: таймаут ожидания завершения Rolling Update (в CI обязателен).
- `-f`: каскадное переопределение значений; порядок файлов определяет приоритет (последний побеждает).

### Валидация перед деплоем

```bash
# 1. Синтаксис шаблонов
helm lint ./mychart

# 2. Рендеринг и проверка YAML-структуры
helm template myapp ./mychart -f values-prod.yaml | kubeconform -strict -

# 3. Проверка контрольных сумм
RENDERED=$(helm template myapp ./mychart -f values-prod.yaml)
echo "$RENDERED" | grep -A1 "checksum/config"

# 4. Dry-run на стороне сервера (требует доступ к кластеру)
helm install myapp ./mychart -f values-prod.yaml --dry-run --debug
```

### Интеграция с Reloader

Для приложений, которые не поддерживают автоматическую перезагрузку при изменении ConfigMap, можно использовать контроллер Reloader. В этом случае checksum-аннотации не требуются, так как Reloader сам модифицирует шаблон пода при изменении конфигурации:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  annotations:
    configmap.reloader.stakater.com/reload: "{{ include \"myapp.fullname\" . }}-config"
```

**Когда выбирать Reloader вместо checksum:**
- Приложение не умеет Hot Reload и изменение чарта невозможно.
- Необходимо отслеживать изменения, сделанные напрямую в кластере (`kubectl edit configmap`).
- Требуется централизованная политика перезапуска для множества чартов.

---

## Разбор работы аннотации

Рассмотрим подробно цепочку обработки:

```yaml
checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

1. **`$.Template.BasePath`**: Системная переменная, возвращающая путь к директории `templates` чарта. Использование префикса `$` гарантирует доступ к глобальной области видимости.
2. **`print`**: Формирует полную строку пути к файлу.
3. **`include`**: Выполняет рендеринг файла как именованного шаблона. Это критично, так как мы хотим отслеживать изменения именно в *результате* рендеринга (с учетом подставленных значений `values`), а не в исходном файле.
4. **`sha256sum`**: Генерирует контрольную сумму от полученной строки. Если хотя бы один символ в ConfigMap изменится, изменится и весь хеш.

### Пример вычисления хеша для нескольких ConfigMap

Если в приложении используется несколько ConfigMap (например, `app-config` и `app-secrets`), можно вычислить объединённый хеш:

```yaml
annotations:
  checksum/combined: |
    {{- $config := include (print $.Template.BasePath "/configmap.yaml") . }}
    {{- $secret := include (print $.Template.BasePath "/secret.yaml") . }}
    {{- printf "%s%s" $config $secret | sha256sum }}
```

Это гарантирует, что изменение любого из ресурсов вызовет единый перезапуск пода.

---

## Тонкости и нюансы

### Влияние пробелов и форматирования

Функция `sha256sum` чувствительна к любым изменениям байтов.
- Добавление пустой строки или изменение отступа в ConfigMap изменит хеш.
- Добавление комментария в YAML-файл, который не попадает в итоговый `data` объекта ConfigMap, но присутствует в шаблоне, также изменит хеш при использовании `include`.

**Рекомендация:** Используйте `.helmignore` для исключения незначимых файлов и фиксируйте стиль форматирования (например, через `prettier` или `yamllint`) в pre-commit хуках.

### include против template

Это фундаментальное различие:
- **`template`**: Директива, которая просто вставляет контент. Она не возвращает значение, поэтому её нельзя использовать в пайплайне после символа `|`.
- **`include`**: Функция, возвращающая строку. Только её можно комбинировать с `sha256sum`.

### Обработка динамических шаблонов (tpl)

Если файлы конфигурации считываются через `.Files.Get` и содержат внутри себя теги Helm (например, `{{ .Release.Name }}`), обычного чтения недостаточно. Нужно прогнать их через функцию `tpl`:

```yaml
# 1. Считываем файл
# 2. Рендерим его как шаблон (tpl)
# 3. Считаем хеш от результата
checksum/config: {{ tpl ($.Files.Get "configs/app.conf") . | sha256sum }}
```

### Согласованность имён аннотаций

Используйте префикс `checksum/` для стандартных аннотаций и уникальный суффикс при нескольких конфигурациях:

```yaml
annotations:
  checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
  checksum/secret: {{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}
```

Избегайте нестандартных имен (`config-hash`, `myapp-checksum`), если не требуется интеграция с внешними инструментами — префикс `checksum/` является общепринятым соглашением.

### Отключение кэширования Helm

Helm кэширует содержимое файлов в течение одного запуска рендеринга. При повторном вызове `.Files.Get` для того же пути возвращается закэшированное значение. Это означает, что функция `tpl`, применённая к содержимому файла, не будет перевычислена при повторном обращении к тому же файлу в рамках одного релиза. Для обхода кэширования используйте разные пути к файлам или запускайте отдельные `helm template`.

### Взаимодействие с immutable ConfigMap

При использовании `immutable: true` в ConfigMap паттерн работает без изменений: хеш вычисляется при каждом рендеринге, и если содержимое ConfigMap изменилось, хеш изменится. Однако обновление самого ConfigMap требует создания нового объекта с новым именем, что должно быть отражено в шаблоне Deployment.

**Пример миграции на immutable:**

```yaml
# values.yaml
configMap:
  immutable: true
  name: "{{ include \"myapp.fullname\" . }}-config-v{{ .Chart.AppVersion }}"
```

```yaml
# templates/deployment.yaml
spec:
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
  volumes:
    - name: config-volume
      configMap:
        name: {{ .Values.configMap.name }}
```

### Совместимость с GitOps-инструментами

При использовании ArgoCD или Flux паттерн checksum-аннотаций работает без изменений. Однако обратите внимание на:
- **ArgoCD:** аннотация `checksum/config` будет видна в diff; это нормальное поведение.
- **Flux:** при использовании `kustomize`-контроллера хеширование имён ConfigMap происходит автоматически; checksum-аннотации в этом случае избыточны.
- **Sync waves:** если вы используете sync-волны в ArgoCD, убедитесь, что ConfigMap применяется раньше Deployment (например, через аннотацию `argocd.argoproj.io/sync-wave: "-1"`).

---

## Проверка и отладка

### Использование helm-diff

Для проверки того, изменится ли хеш (и, как следствие, произойдет ли перезапуск) перед деплоем, рекомендуется использовать плагин `helm-diff`:

```bash
helm diff upgrade my-release ./my-chart --values values.yaml
```

В выводе будет четко видно изменение значения в секции `annotations`.

### Интроспекция через kubectl

Проверка текущего значения хеша в работающем кластере:

```bash
kubectl get deploy my-app -o jsonpath='{.spec.template.metadata.annotations.checksum/config}'
```

### Проверка через helm template

```bash
# Рендеринг и поиск аннотации в выводе
helm template my-release ./my-chart -f values.yaml | grep -A1 "checksum/config"

# Сравнение хеша ConfigMap и аннотации
ACTUAL_HASH=$(kubectl get configmap my-app-config -o jsonpath='{.data}' | sha256sum | cut -d' ' -f1)
ANNOTATION_HASH=$(kubectl get deploy my-app -o jsonpath='{.spec.template.metadata.annotations.checksum/config}')
echo "ConfigMap: $ACTUAL_HASH"
echo "Annotation: $ANNOTATION_HASH"
```

### Отслеживание статуса Rolling Update

```bash
# Ожидание завершения обновления (обязательно с таймаутом в CI/CD-пайплайне)
kubectl rollout status deployment/my-app --timeout=5m
# → deployment "my-app" successfully rolled out

# Просмотр истории изменений
kubectl rollout history deployment/my-app
# → REVISION  CHANGE-CAUSE

# Откат к предыдущей версии
kubectl rollout undo deployment/my-app
kubectl rollout undo deployment/my-app --to-revision=2
```

### Диагностика типичных проблем

| Симптом | Вероятная причина | Метод диагностики | Решение |
| :--- | :--- | :--- | :--- |
| Поды не перезапускаются после изменения ConfigMap | Аннотация `checksum/config` отсутствует или вычислена неправильно | `kubectl describe deploy` → проверка `annotations` | Убедитесь, что `include` рендерит правильный файл и путь корректен |
| Rolling Update запускается при каждом `helm upgrade` без изменений конфигурации | В хешируемый файл включены `now` или `randAlphaNum` | `helm template` → поиск нестабильных значений | Уберите недетерминированные функции из хешируемых файлов |
| Конфигурация в томе устарела после rollout | Hot Reload отсутствует, приложение кэширует файл | `kubectl exec` → проверка содержимого файла | Добавьте механизм перезагрузки (SIGHUP, HTTP `/reload`) или перезапустите под |
| `CreateContainerConfigError` после изменений | ConfigMap не найден или ключ отсутствует | `kubectl describe pod` → `Events` | Проверьте имя ConfigMap и наличие обязательных ключей |
| Размер аннотации превышает лимит | В аннотацию попало слишком много данных | `kubectl get deploy -o json | jq '.spec.template.metadata.annotations'` | Хешируйте только контрольные суммы, не включайте сами данные |

---

## Безопасность и RBAC

### Утечка информации через аннотации

Значение аннотации `checksum/secret` является необратимым хешем отрендеренного YAML-секрета. Хотя хеш не позволяет восстановить исходные данные, он позволяет обнаружить факт изменения секрета. В высокозащищённых окружениях это может считаться утечкой метаданных.

**Рекомендации:**
- Используйте `checksum/config` для ConfigMap без ограничений.
- Для Secret оцените риск раскрытия факта ротации; при необходимости замените паттерн на контроллер [Reloader](../../../reloader/reloader_overview.md), который модифицирует шаблон пода без явного хеширования содержимого.

### Минимальные права ServiceAccount

```yaml
# role.yaml — минимальные права для деплоя через Helm/ArgoCD/Flux
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: production
  name: helm-deployer
rules:
- apiGroups: ["apps"]
  resources: ["deployments", "statefulsets", "daemonsets"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["configmaps", "secrets"]
  verbs: ["get", "list", "watch", "create", "update", "patch"]
- apiGroups: [""]
  resources: ["serviceaccounts"]
  verbs: ["get", "list"]
```

```bash
# Проверка прав
kubectl auth can-i get configmap/app-config \
  --as=system:serviceaccount:production:helm-deployer \
  --namespace=production
```

---

## Мониторинг и аудит

### Метрики для отслеживания

- **Частота перезапусков:** Алерт при увеличении частоты Rolling Update сверх базового уровня (например, >3 за час).
- **Время Rolling Update:** `kubectl rollout status` возвращает время; экспортируйте через внешний скрипт или CI-метрики.
- **Конфигурационный дрейф:** Сравнивайте `helm get values` и фактический ConfigMap в кластере.

### Проверка после деплоя

```bash
# 1. Убедитесь, что поды обновились
kubectl get pods -l app=my-app -o wide

# 2. Проверьте версию образа и ревизию
kubectl get deploy my-app -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
kubectl get deploy my-app -o jsonpath='{.metadata.annotations}{"\n"}'

# 3. Для томов — проверка доставленной версии через симлинк ..data
kubectl exec deploy/my-app -- cat /etc/config/..data/app.config | head

# 4. Для env — проверка фактических значений в работающем поде
kubectl exec deploy/my-app -- env | grep ^LOG_LEVEL=
# → LOG_LEVEL=info

# 5. Проверка контрольной суммы файла внутри пода
kubectl exec -n production deploy/myapp -- sh -c \
  "sha256sum /etc/app/config/nginx.conf"
```

### Аудит изменений ConfigMap

```bash
# Просмотр событий ConfigMap (если включен audit)
kubectl get configmap app-config -n production -o jsonpath='{.metadata.annotations}' 

# Проверка, кто изменил ConfigMap последним
kubectl describe configmap app-config -n production
# → Events:  Normal  Updated  2m  configmap-controller  Updated configmap

# Просмотр истории Helm-релизов
helm history myapp -n production
# → REVISION  UPDATED                   STATUS      CHART                           DESCRIPTION
# → 1         2026-09-02 10:00:00 +0000  superseded  myapp-1.0.0    Install complete
# → 2         2026-09-02 14:30:00 +0000  deployed    myapp-1.1.0    Upgrade "myapp" complete
```

---

## Лучшие практики

1. **Принцип единственного источника правды:** Каждый уникальный параметр (порт, домен, версия) должен определяться в `values.yaml` ровно один раз. Все ссылки в шаблонах должны указывать на этот источник.
2. **Идемпотентность:** Для обновления чарта всегда используйте `helm upgrade --install` вместо последовательности `helm uninstall` + `helm install`. Это предотвращает потерю истории релизов и обеспечивает предсказуемость.
3. **Атомарность:** Используйте флаг `--atomic` в CI/CD-пайплайнах. При ошибке деплоя Helm автоматически откатит релиз к предыдущей ревизии.
4. **Версионирование образов:** Никогда не используйте тег `latest` в production. Фиксируйте версии в `values.yaml` и изменяйте их только через явный коммит.
5. **Защита секретов:** Не передавайте секреты через `--set`. Используйте `helm secrets` или внешние vault-решения. Если секрет хранится в `values.yaml`, он попадает в историю Helm и в репозиторий Git.
6. **Revision History:** Ограничьте `revisionHistoryLimit` разумным значением (например, 5) для Production, чтобы контроллер не удерживал устаревшие ReplicaSet.
7. **Валидация:** Внедрите `helm lint` и `kubeconform` в каждый pipeline. Пайплайн должен блокировать мерж при ошибках синтаксиса или схемы.
8. **Observability:** Добавьте в Deployment аннотации с причиной изменения (`CHANGE-CAUSE`) для упрощения аудита:
   ```bash
   helm upgrade myapp ./mychart \
     --set CHANGE_CAUSE="Increased timeout to 30s for DB connections" \
     -f values-prod.yaml
   ```
9. **Именование аннотаций:** Используйте префикс `checksum/` для стандартных аннотаций. При нескольких конфигурациях добавляйте уникальный суффикс (`checksum/config`, `checksum/secret`).
10. **Тестирование изменений:** Перед деплоем в production протестируйте паттерн в staging: внесите изменение в ConfigMap, выполните `helm upgrade` и убедитесь, что Rolling Update запустился корректно.

---

## Ограничения и риски

- **Статическая природа:** Паттерн работает только в момент рендеринга Helm. Он "не видит" изменений, сделанных напрямую в кластере (например, через `kubectl edit configmap`) или изменений внешних секретов (Vault, AWS Secrets Manager).
- **Лимит аннотаций:** Kubernetes имеет ограничение на размер аннотаций (256KB). Хеширование очень больших структур данных не вызовет проблем (хеш всегда короткий), но сам рендеринг `include` может замедлить работу Helm на гигантских файлах.
- **Ложные срабатывания:** Использование функций с побочными эффектами (`now`, `randAlphaNum`) внутри хешируемых файлов приведет к тому, что хеш будет меняться при *каждом* запуске `helm upgrade`, вызывая ненужные перезапуски подов.
- **Rollback:** При выполнении `helm rollback` Helm восстановит состояние аннотаций из выбранной ревизии, что также инициирует перезапуск подов для возврата к старой конфигурации.
- **Config Skew Window:** Во время Rolling Update часть подов работает со старой конфигурацией, часть — с новой. Новый формат конфигурации должен быть обратно совместим со старой версией приложения.
- **Кэширование Helm:** При повторном вызове `.Files.Get` для того же пути в рамках одного релиза возвращается закэшированное значение. Это может привести к некорректному хешированию, если файл был изменён между вызовами.
- **Чувствительность к форматированию:** Любое изменение пробелов, отступов или комментариев в шаблоне ConfigMap изменит хеш, даже если семантика конфигурации осталась прежней.
- **Утечка метаданных:** Хеш секрета в аннотации позволяет обнаружить факт его изменения. В высокозащищённых окружениях это может противоречить политикам безопасности.

---

## Дополнительная информация

- [Функции Helm](../functions.md) — детальный разбор `sha256sum`, `tpl` и `include`.
- [Обновление и Rollout ConfigMap](../../../../Base/ConfigMap/update_and_rollout.md) — как Kubernetes обрабатывает изменения конфигурации на уровне Kubelet.
- [stakater/Reloader](../../../reloader/reloader_overview.md) — альтернативный "динамический" подход к перезапуску через контроллер.
- [Kustomize Name Hashing](../../../../ToolsUtilities/kustomize/kustomize_advanced_features.md) — аналогичный механизм в Kustomize через суффиксы имен ресурсов.
