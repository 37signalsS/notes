# Темплейтизация манифестов в Helm

Helm использует **Go template engine** для генерации манифестов.

## Основы темплейтизации

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

## Продвинутое шаблонизирование: функции и управление потоком

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
