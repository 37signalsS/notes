# Helm: пакетный менеджер для Kubernetes

## Определения

Helm – пакетный менеджер для Kubernetes, решающий проблемы управления множеством манифестов. Позволяет использовать переменные и шаблоны для генерации конечных манифестов, упрощая управление конфигурациями для разных окружений.

### Альтернативные подходы и их недостатки

Существуют различные подходы к темплейтизации манифестов:

1.  **Простые утилиты (`sed`, `envsubst`):** Заменяют плейсхолдеры переменными окружения, но ограничены в сложной логике.
2.  **Системы управления конфигурациями ([Ansible](../../Ansible/ansible_introduction.md)):** Предоставляют мощные шаблонизаторы (Jinja2) и модули для Kubernetes. Являются `kubectl-based`, генерируют YAML и применяют через `kubectl`.
3.  **Специализированные инструменты (`kustomize`, `jsonnet`):** Предлагают структурированные методы управления конфигурациями.

**Основной недостаток `kubectl-based` подходов** — проблема атомарного отката. `kubectl rollout undo` работает только для `Deployment`. Откат других ресурсов (`Service`, `Ingress`, `ConfigMap`) требует ручного вмешательства.

### Путь к решению: версионирование релизов

Для решения проблемы отката применяется стратегия версионирования:

1.  **Сохранение отрендеренных манифестов:** После генерации YAML-файлы для каждой версии приложения сохраняются как единый артефакт.
2.  **Версионирование артефактов:** Каждому набору присваивается версия (v1, v2, v3).
3.  **Хранение артефактов:** Артефакты хранятся во внешнем хранилище (например, Artifactory) или в кластере Kubernetes. В кластере можно использовать `ConfigMap`, преодолевая его ограничение по размеру сжатием манифестов в `zip-архив`, кодированием в `base64` и сохранением в `ConfigMap`.

Эта концепция лежит в основе Helm. Helm автоматизирует темплейтизацию, создает версионированные релизы и управляет их жизненным циклом. Helm 3 использует `Secrets` для хранения информации о релизах, что безопаснее `ConfigMap`. Helm – полноценная система управления релизами приложений в Kubernetes.

## Основные понятия

### Структура Helm-чарта

**Чарт** – это пакет Helm в формате `.tgz`, содержащий все для развертывания приложения в Kubernetes.

Стандартизированная структура чарта:

*   **`Chart.yaml`**: Файл с метаданными о чарте.
    *   `apiVersion`: Версия API чарта (обязательно).
    *   `name`: Имя чарта (обязательно).
    *   `version`: Версия самого чарта (обязательно, следует семантическому версионированию).
    *   `appVersion`: Версия приложения, которое разворачивается этим чартом.
    *   `description`: Краткое описание чарта.
    *   `maintainers`: Список ответственных за чарт.

*   **`values.yaml`**: Файл со значениями по умолчанию для переменных, используемых в шаблонах. Это позволяет легко настраивать чарт без изменения его шаблонов.

*   **`templates/`**: Директория, в которой хранятся все темплейтизированные манифесты Kubernetes (например, `deployment.yaml`, `service.yaml`, `ingress.yaml`).

*   **`charts/`**: Директория для зависимостей — других чартов, от которых зависит текущий чарт.

### Темплейтизация манифестов

Helm использует **Go template engine** для генерации манифестов.

**Пример `deployment.yaml` после темплейтизации:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-deployment
  labels:
    app: {{ .Chart.Name }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app: {{ .Chart.Name }}
  template:
    metadata:
      labels:
        app: {{ .Chart.Name }}
    spec:
      containers:
      - name: {{ .Chart.Name }}
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        ports:
        - containerPort: {{ .Values.service.port }}
```

Значения подставляются из:

*   `{{ .Values.replicaCount }}`: Из файла `values.yaml`.
*   `{{ .Release.Name }}`: Из данных о самом релизе (имя, которое вы даете при установке).
*   `{{ .Chart.Name }}`: Из метаданных чарта (`Chart.yaml`).

Соответствующий `values.yaml`:

```yaml
replicaCount: 2

image:
  repository: nginx
  tag: stable

service:
  port: 80
```

Helm рендерит шаблоны, подставляя значения из `values.yaml` и встроенных объектов (`.Release`, `.Chart`), генерируя итоговые манифесты для Kubernetes API.

### Продвинутое шаблонизирование: функции и управление потоком

Go template engine позволяет использовать функции, управляющие конструкции и встроенные объекты.

#### Пример: `values.yaml`

```yaml
# values.yaml
replicas: 2

image:
  name: nginx
  tag: "1.12"

port: 80

resources:
  limits:
    cpu: 100m
    memory: 128Mi
  requests:
    cpu: 100m
    memory: 128Mi

env:
  - name: VAR1
    value: "value1"
  - name: VAR2
    value: "value2"

annotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "80"
```

#### Условное включение секций: `if`

Для условного включения секций используется `if`.

**Задача:** Добавить `annotations`, если они определены в `values.yaml`.

```yaml
template:
  metadata:
    {{- if .Values.annotations }}
    annotations:
      {{- toYaml .Values.annotations | nindent 6 }}
    {{- end }}
```

*   `{{- if .Values.annotations }}`: Проверяет наличие объекта `annotations` в `values`.
*   `{{- toYaml .Values.annotations }}`: Функция `toYaml` сериализует объект `annotations` обратно в формат YAML. Это позволяет вставлять целые структуры, а не отдельные значения.
*   `| nindent 6`: Функция `nindent` (newline indent) добавляет перенос строки и ставит 6 пробелов перед каждой строкой, обеспечивая корректную вложенность YAML.
*   `{{- end }}`: Закрывает блок `if`.
*   Дефисы (`-`) по краям (`{{- ... -}}`) используются для **удаления пробельных символов** (включая переносы строк) до или после тега, что помогает форматировать итоговый YAML и избегать пустых строк.

#### Итерация по спискам: `range`

Для генерации повторяющихся блоков используется `range`.

**Задача:** Сгенерировать переменные окружения для контейнера из `values.yaml`.

```yaml
spec:
  containers:
    - name: {{ .Chart.Name }}
      {{- if .Values.env }}
      env:
        {{- range .Values.env }}
        - name: {{ .name | quote }}
          value: {{ .value | quote }}
        {{- end }}
      {{- end }}
```

*   `{{- range .Values.env }}`: Запускает цикл, который итерируется по каждому элементу списка `.Values.env`. Внутри цикла контекст (`.`) меняется на текущий элемент списка (например, на `{"name": "VAR1", "value": "value1"}`).
*   `{{ .name | quote }}`: Обращается к полю `name` текущего элемента и заключает его значение в кавычки с помощью функции `quote`. Это предотвращает проблемы, если значение является числом или булевым типом, которые YAML может интерпретировать не как строку.

#### Локальная отладка: `helm template`

`helm template` рендерит чарт локально, выводя результат в `stdout`.

```bash
helm template my-app .
```

**Типичные проблемы и решения:**

*   **Неправильные отступы:** YAML чувствителен к отступам.
    *   **Решение:** Использовать `nindent` (или `indent`).
    ```yaml
    spec:
      containers:
      - name: {{ .Chart.Name }}
        resources:
    {{- toYaml .Values.resources | nindent 10 }}
    ```
*   **Лишние пустые строки:** Управляющие конструкции Go могут оставлять пустые строки.
    *   **Решение:** Использовать дефисы `{-` и `-}` для удаления пробелов и переносов строк.
    ```yaml
      env:
        {{- if .Values.env }}
        {{- range .Values.env }}
        - name: {{ .name | quote }}
          value: {{ .value | quote }}
        {{- end }}
        {{- end }}
    ```

#### Стартовые чарты: `helm create`

Команда `helm create my-new-chart` генерирует шаблонный чарт с необходимой структурой: `Deployment`, `Service`, `Ingress`, `HPA`, тесты и `values.yaml`.

## Практические сценарии

### Основные команды и рабочий процесс

Helm предоставляет набор команд для управления жизненным циклом приложений. Пример установки `kube-ops-view`.

#### Шаг 1: Управление репозиториями

Helm-репозиторий — это HTTP-сервер, хранящий упакованные чарты.

*   **Добавить репозиторий:**
    ```bash
    # helm repo add [NAME] [URL]
    helm repo add stable https://charts.helm.sh/stable
    ```
*   **Обновить информацию о чартах:**
    ```bash
    helm repo update
    ```

#### Шаг 2: Поиск чарта

*   **Поиск в Artifact Hub(поиск CNCF-пакетов):**
    ```bash
    helm search hub kube-ops-view
    ```
*   **Поиск в подключенных репозиториях:**
    ```bash
    helm search repo kube-ops-view
    ```

#### Шаг 3: Подготовка к установке

Изучение настраиваемых параметров (`values`).

*   **Просмотреть значения по умолчанию:**
    ```bash
    helm show values stable/kube-ops-view
    ```
*   **Сохранить `values.yaml` для кастомизации:**
    ```bash
    helm show values stable/kube-ops-view > values.yaml
    ```
    Например, для `kube-ops-view`:
    ```yaml
    # values.yaml
    ingress:
      enabled: true
      hostname: kube-ops-view.my-cluster.com
    
    rbac:
      create: true
    ```

#### Шаг 4: Установка и управление релизом

**Релиз** — конкретный экземпляр чарта в кластере.

*   **Установить чарт:**
    ```bash
    helm install ops-view stable/kube-ops-view --namespace kube-system -f values.yaml
    ```

    *   `ops-view`: Имя релиза. Вы можете выбрать любое.
    *   `stable/kube-ops-view`: Имя чарта.
    *   `--namespace kube-system`: Целевое пространство имен.
    *   `-f values.yaml`: Файл с вашими кастомными значениями.

#### Идемпотентное развертывание: `upgrade --install`

Команда `helm upgrade --install` идемпотентна: устанавливает релиз, если не существует, или обновляет, если существует.

```bash
helm upgrade --install ops-view stable/kube-ops-view -f values.yaml
```

#### Автоматический откат при сбое: `--atomic` и `--timeout`

Флаги `--atomic` и `--timeout` защищают от сбоев.

**Сценарий:** Приложение "ломается" (неверный адрес БД), обновление запускается с `--atomic`.

1.  **Внесение неисправности:** В `values.yaml` изменяется хост БД на несуществующий.
2.  **Запуск обновления:** `helm upgrade my-app ./my-chart --atomic`.
3.  **Наблюдение:** Kubernetes развертывает новую версию. Поды падают (`CrashLoopBackOff`). Helm ожидает `Ready` состояние и фиксирует неудачу.
4.  **Автоматический откат:** По таймауту Helm инициирует `helm rollback` к стабильной ревизии. Нерабочие поды удаляются, старые остаются.

**Итог:** Работа приложения не нарушается. Пайплайн CI/CD завершается с ошибкой, но в кластере остается стабильная версия.

*   **Список релизов:**
    ```bash
    helm list -n kube-system
    ```
*   **Статус релиза:**
    ```bash
    helm status ops-view -n kube-system
    ```

#### Шаг 5: Обновление и откат

*   **Обновить релиз:**

    Если вы изменили `values.yaml` или хотите обновить версию чарта, используйте `helm upgrade`.

    ```bash
    helm upgrade ops-view stable/kube-ops-view -f values.yaml
    ```
    Рекомендуется использовать плагин `helm-diff` перед обновлением.
*   **Откатить релиз:**
    ```bash
    # helm rollback [RELEASE_NAME] [REVISION]
    helm rollback ops-view 1 
    ```

#### Шаг 6: Удаление релиза

*   **Удалить релиз и ресурсы:**
    ```bash
    # helm delete [RELEASE_NAME] -n [NAMESPACE]
    helm delete ops-view -n kube-system
    ```

    Рекомендуется удалять приложения, установленные с помощью Helm, именно через `helm delete`, а не `kubectl delete`, чтобы гарантировать удаление всех ресурсов, включая те, что находятся вне пространства имен релиза (например, `ClusterRole`).

### Инспектирование локального чарта

*   **Скачать и распаковать чарт:**

    Команда `helm pull` скачивает архив `.tgz` чарта из репозитория. Флаг `--untar` позволяет сразу же его распаковать.

    ```bash
    helm pull stable/kube-ops-view --untar
    ```
    В текущей директории появится папка `kube-ops-view` с `Chart.yaml`, `values.yaml` и `templates`.

### Тестирование релиза (`helm test`)

Helm имеет механизм тестирования развернутого релиза.

**Принцип работы:**

1.  **Создание тестовых манифестов:** В директории `templates/` вашего чарта создается поддиректория `tests/`.
2.  **Размещение тестов:** Внутрь `templates/tests/` помещаются манифесты Kubernetes, которые выполняют проверку. Как правило, это `Pod` или `Job`, которые запускают тестовый контейнер.
3.  **Аннотация для тестов:** Ключевым моментом является добавление аннотации `helm.sh/hook: test` в метаданные тестовых ресурсов. Эта аннотация сообщает Helm, что данный манифест является тестом и его не нужно включать в основной релиз.
4.  **Запуск тестов:** После установки или обновления релиза, тесты запускаются командой `helm test <release_name>`.

Если под завершается с кодом `0`, тест успешен.

**Пример (`templates/tests/test-connection.yaml`):**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: "{{ .Release.Name }}-connection-test"
  annotations:
    "helm.sh/hook": test
spec:
  containers:
    - name: wget
      image: busybox
      command: ['wget']
      args: ['{{ .Release.Name }}-my-service:{{ .Values.service.port }}']
  restartPolicy: Never
```

### Хуки (Hooks)

Хуки — это механизм, позволяющий выполнять определенные действия на разных этапах жизненного цикла релиза. Это могут быть `Job` для миграции базы данных перед обновлением приложения, `Pod` для выполнения резервного копирования перед удалением релиза или любые другие манифесты Kubernetes.

Ресурс становится хуком, если в его метаданные добавлена аннотация `helm.sh/hook`.

**Доступные хуки:**

*   `pre-install`: Выполняется перед тем, как в кластер будут загружены какие-либо ресурсы релиза.
*   `post-install`: Выполняется после того, как все ресурсы релиза были установлены.
*   `pre-delete`: Выполняется перед удалением ресурсов релиза.
*   `post-delete`: Выполняется после того, как все ресурсы релиза были удалены.
*   `pre-upgrade`: Выполняется перед обновлением релиза.
*   `post-upgrade`: Выполняется после того, как релиз был обновлен.
*   `pre-rollback`: Выполняется перед откатом релиза.
*   `post-rollback`: Выполняется после отката релиза.

**Управление хуками:**

*   **Вес хука (`helm.sh/hook-weight`):** Если для одного и того же этапа (например, `pre-install`) определено несколько хуков, их можно упорядочить с помощью веса. Хуки выполняются в порядке возрастания их веса (отрицательные значения разрешены).
*   **Политика удаления (`helm.sh/hook-delete-policy`):** Хуки не являются частью самого релиза и не удаляются автоматически вместе с ним (если только они не попали под `helm delete`). Аннотация `helm.sh/hook-delete-policy` позволяет управлять их удалением.
    *   `before-hook-creation`: Удаляет предыдущий хук перед запуском нового (поведение по умолчанию).
    *   `hook-succeeded`: Удаляет хук после его успешного завершения.
    *   `hook-failed`: Удаляет хук, если он завершился с ошибкой.

**Пример хука для `post-install`:**

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ .Release.Name }}-post-install-job"
  annotations:
    "helm.sh/hook": post-install
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  template:
    spec:
      containers:
        - name: post-install-container
          image: alpine:3.3
          command: ["/bin/sleep", "{{ default "10" .Values.sleepyTime }}"]
      restartPolicy: Never
  backoffLimit: 4
```

### `helm-diff`: предпросмотр изменений

`helm-diff` – плагин, показывающий `diff` изменений перед `helm upgrade`.

**Ключевые возможности:**

*   **Предпросмотр обновлений.**
*   **Сравнение ревизий.**
*   **Анализ отката.**

**Установка:**
```bash
helm plugin install https://github.com/databus23/helm-diff
```

**Использование:**
```bash
# Сравнить текущий релиз с изменениями из локального чарта
helm diff upgrade my-release ./my-chart

# Можно использовать те же флаги, что и для `helm upgrade`, например, для передачи values
helm diff upgrade my-release ./my-chart -f values.yaml
```

**Сравнить две ревизии релиза:**

```bash
# Показать разницу между 1-й и 2-й ревизией
helm diff revision my-release 1 2
```

**Показать `diff` для `helm rollback`:**
```bash
# Показать, что изменится, если откатиться к ревизии 1
helm diff rollback my-release 1
```

### Создание собственного репозитория Helm

Helm-репозиторий — HTTP-сервер, отдающий YAML и `.tgz` файлы.

**Требования:**
1.  Сервер обслуживает YAML и `.tgz`.
2.  Отвечает на GET-запросы.
3.  Содержит `index.yaml` с метаданными обо всех чартах в репозитории.

**Структура репозитория:**
```
https://example.com/charts/
├── index.yaml
├── alpine-0.1.2.tgz
└── alpine-0.1.2.tgz.prov (опционально)
```

`index.yaml` генерируется `helm package --destination <path>` и `helm repo index <path>`.

**Рабочий процесс:**
1.  **Упаковка чарта:** `helm package ./my-chart`.
2.  **Создание/обновление индекса:** `helm repo index . --url https://my-repo.com/charts`.
3.  **Загрузка на сервер:** `*.tgz` и `index.yaml`.

### Структура проекта с Helm и Kustomize

Гибридный подход: Helm для шаблонизации, Kustomize для патчей под окружения.

```
k8s-project/
├── base/                   # Базовые манифесты из `helm template`
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   ├── ingress.yaml
│   └── kustomization.yaml
│
├── overlays/               # Специфичные для окружений "наслоения"
│   ├── dev/
│   │   ├── kustomization.yaml
│   │   ├── namespace.yaml
│   │   ├── configmap-patch.yaml
│   │   └── ingress-patch.yaml
│   │
│   ├── staging/
│   │   └── ...
│   └── prod/
│       └── ...
│
└── helm/                     # Исходный Helm-чарт
    ├── Chart.yaml
    ├── values.yaml
    └── templates/
        └── ...
```

**Рабочий процесс:**
1.  **Генерация базы:** `helm template ./helm > ./base`.
2.  **Применение Kustomize:** `kubectl apply -k overlays/dev`.

### Оркестраторы для Helm

Для управления множеством релизов:

*   **[Helmfile](./helmfile_overview.md)**: Управление релизами через `helmfile.yaml`.
*   **[Helmwave](./helmwave_overview.md)**: Использует Go-шаблоны для конфигурации.

## Дополнительная информация

### Ключевые преимущества Helm

Helm является стандартом для развертывания в Kubernetes благодаря:

1.  **Шаблонизации и переиспользуемости:** Гибкие, переиспользуемые манифесты через Go template engine.
2.  **Версионированию и управляемым релизам:** Контролируемая работа с инфраструктурой, легкие обновления/откаты.
3.  **Управлению зависимостями:** Автоматическая установка и обновление зависимых чартов. [Helm Best Practices](./helm_best_practices.md).
4.  **Надежным развертываниям и атомарным откатам:** Механизмы CI/CD: `--wait`, `--atomic`.
5.  **Архитектуре без Tiller (Helm 3):** Исключительно клиентский инструмент, безопаснее.
6.  **Хукам и тестированию:** Действия на этапах жизненного цикла, встроенный механизм тестирования (`helm test`).
7.  **Проекту CNCF:** Высокий уровень поддержки и развития.
8.  **Системе плагинов:** Расширение функциональности (`helm-diff`, `helm 2to3`, `helm-monitor`).
