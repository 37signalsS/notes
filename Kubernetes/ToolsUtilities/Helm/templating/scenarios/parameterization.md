# Параметризация через values.yaml

---

## Определения

**Параметризация** — это процесс замены жёстко заданных значений (хардкода) в манифестах на переменные, значения которых хранятся в конфигурационном файле `values.yaml` и доступны через объект `.Values`.

**`.Values`** — встроенный объект Helm, который объединяет значения из `values.yaml` чарта, его субчартов и внешних источников (файлы через `-f`, параметры через `--set`). Подробнее об объекте: [Встроенные объекты Helm](../objects.md).

---

## Базовые концепции

### Проблема хардкода

Без параметризации одни и те же значения дублируются в различных ресурсах, что делает чарт негибким и подверженным ошибкам при обновлении.

| Проблема | Риск |
|----------|------|
| Дублирование порта в Deployment и Service | Рассинхронизация при изменении порта (Service перестанет направлять трафик) |
| Хардкод имён ресурсов | Невозможность запустить несколько экземпляров (релиза) одного чарта в одном Namespace |
| Ручные правки шаблонов | Высокий риск человеческой ошибки, ломающей структуру YAML |
| Статичные образы | Невозможность автоматизировать CI/CD для деплоя различных тегов (dev/prod) |

### Иерархия и приоритеты значений

Helm объединяет значения из нескольких источников. В случае конфликта применяется следующий приоритет (от низшего к высшему):
1.  **`values.yaml` в субчартах** — самые базовые значения.
2.  **`values.yaml` в основном чарте** — переопределяют значения субчартов.
3.  **Файлы значений (`-f` / `--values`)** — переданные пользователем файлы переопределяют дефолты чарта.
4.  **Индивидуальные значения (`--set`)** — имеют наивысший приоритет.

### Глобальные значения (Global Values)

Специальная секция `global` в `values.yaml` позволяет передавать параметры одновременно всем компонентам и субчартам. Это единственный объект, который автоматически «пробрасывается» вниз по иерархии зависимостей.

```yaml
global:
  domain: example.com
  imageRegistry: registry.hub.docker.com
```

---

## Практические сценарии

### Группировка параметров в values.yaml

Для поддержания чистоты рекомендуется группировать параметры по логическим блокам (приложение, образ, сервис).

**values.yaml:**
```yaml
app:
  name: myapp
  replicas: 3
  port: 8080
image:
  repository: nginx
  tag: latest
  pullPolicy: IfNotPresent
service:
  type: ClusterIP
  port: 80
ingress:
  enabled: true
```

### Синхронизация Deployment и Service

Использование одного и того же параметра `.Values.app.port` в разных манифестах гарантирует их связность.

**templates/deployment.yaml:**
```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: {{ .Values.app.replicas }}
  template:
    spec:
      containers:
        - name: app
          image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
          ports:
            - containerPort: {{ .Values.app.port }}
```

**templates/service.yaml:**
```yaml
apiVersion: v1
kind: Service
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.app.port }} # Тот же источник, что и в Deployment
  selector:
    app: {{ .Values.app.name }}
```

### Условная параметризация Ingress

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  rules:
    - host: {{ index .Values "global" "domain" | default "localhost" }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ include "myapp.fullname" . }}
                port:
                  number: {{ .Values.service.port }}
{{- end }}
```

### Локальные переменные и динамические ключи

Локальные переменные действуют в пределах одного файла и помогают сократить длинные пути к объектам.

```yaml
{{- $domain := .Values.global.domain -}}
{{- $port := .Values.app.port -}}
{{- $fullName := include "myapp.fullname" . -}}

# Использование функции index для ключей со спецсимволами
{{- $apiUrl := index .Values "api-config" "url" -}}

metadata:
  name: {{ $fullName }}
spec:
  containers:
    - name: web
      env:
        - name: APP_URL
          value: {{ $apiUrl | quote }}
```

### Работа со списками (Environment Variables)

**values.yaml:**
```yaml
env:
  - name: DB_HOST
    value: "postgres"
  - name: DEBUG
    value: "true"
```

**templates/deployment.yaml:**
```yaml
env:
{{- range .Values.env }}
  - name: {{ .name }}
    value: {{ .value | quote }}
{{- end }}
```

---

## Валидация и тестирование

### Локальный рендеринг (helm template)

Позволяет увидеть итоговый результат без отправки в Kubernetes.
```bash
# С дефолтными значениями
helm template my-release .

# С переопределением через CLI
helm template my-release . --set app.port=9090

# С использованием нескольких values-файлов (порядок важен!)
helm template my-release . -f values.yaml -f values-prod.yaml
```

### Тестирование в режиме Dry-run

```bash
# Проверка манифестов на стороне API Kubernetes без их создания
helm install my-release . --dry-run --debug
```

### Проверка синтаксиса и линтинг

```bash
# Проверка структуры чарта и соответствия стандартам
helm lint .
```

---

## Дополнительная информация

### Лучшие практики

| Практика | Описание |
|----------|----------|
| **Централизация** | Все изменяемые данные — только в `values.yaml`. В шаблонах не должно быть магических чисел. |
| **Плоская структура** | Избегайте вложенности более 3 уровней в `values.yaml` для удобства переопределения через `--set`. |
| **Типизация** | Всегда используйте кавычки и пайп `| quote` для строк, которые могут быть похожи на числа или булевы. |
| **Документирование** | Комментируйте каждый параметр в `values.yaml`, указывая единицы измерения (мс/сек/Мб). |
| **Безопасность** | Не храните пароли в `values.yaml`. Используйте пустые значения и проверку `required`. |

### Устранение неисправностей

- **`nil pointer evaluating`**: Проверьте, не ошиблись ли вы в регистре или уровне вложенности в пути к параметру.
- **`wrong type for value`**: Возникает, если функция ожидает строку, а передано число (используйте `quote`).
- **Значение не применилось**: Проверьте приоритет. Параметр в `--set` всегда перекрывает любые файлы `-f`.

### См. также
- [Встроенные объекты](../objects.md) — справочник по `.Values`, `.Release`, `.Chart`.
- [Именованные шаблоны](../_helpers.md) — использование параметров внутри хелперов.
- [Условная логика](./conditionals.md) — управление структурой через параметры.
- [Обзор сценариев](./overview.md) — каталог практических примеров.
