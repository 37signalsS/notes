# Parameterization with values.yaml

---

## Definitions

**Параметризация** — замена жёстко заданных значений в манифестах на переменные из `values.yaml` и `.Values`. Подробнее об объекте `.Values`: [Встроенные объекты Helm](../objects.md). Управление values-файлами для окружений — в [Практические сценарии чартов](../../helm_chart_practical_scenarios.md).

---

## Basic Concepts

### Проблема хардкода

Без параметризации одни и те же значения (имена, порты, репозитории) дублируются в Deployment, Service, Ingress. Изменение требует правки в каждом файле, что приводит к рассинхронизации.

| Проблема | Риск |
|----------|------|
| Дублирование порта в Deployment и Service | Рассинхронизация при изменении |
| Хардкод имён | Невозможно несколько экземпляров |
| Ручные правки шаблонов | Ошибка ломает развёртывание |
| Отсутствие гибкости | Нельзя развернуть с другими параметрами |

### Принцип SSoT для values.yaml

`values.yaml` становится единственным источником всех изменяемых параметров. Шаблоны только ссылаются на `.Values`, не содержат жёстких значений.

Структура группировки:

```yaml
app:
  name: myapp
  replicas: 3
  port: 8080
  domain: app.example.com

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

---

## Practical Scenarios

### Параметризация Deployment

**templates/deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "myapp.fullname" . }}
  labels:
    app: {{ .Values.app.name }}
spec:
  replicas: {{ .Values.app.replicas }}
  selector:
    matchLabels:
      app: {{ .Values.app.name }}
  template:
    metadata:
      labels:
        app: {{ .Values.app.name }}
    spec:
      containers:
        - name: app
          image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
          ports:
            - containerPort: {{ .Values.app.port }}
```

### Параметризация Service (синхронизация с Deployment)

**templates/service.yaml:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.app.port }}
      protocol: TCP
      name: http
  selector:
    app: {{ .Values.app.name }}
```

`targetPort` ссылается на `.Values.app.port` — тот же источник, что и `containerPort` в Deployment. Рассинхронизация невозможна.

### Параметризация Ingress с условным включением

**templates/ingress.yaml:**

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  rules:
    - host: {{ .Values.app.domain }}
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

### Локальные переменные для уменьшения дублирования

В пределах одного файла шаблона длинные конструкции выносятся в переменные:

```yaml
{{- $domain := .Values.app.domain }}
{{- $port := .Values.app.port }}
{{- $fullName := include "myapp.fullname" . }}

apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ $fullName }}
spec:
  rules:
    - host: {{ $domain }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ $fullName }}
                port:
                  number: {{ $port }}
```

Локальные переменные действуют **только в пределах одного файла**. Для межфайлового доступа используются именованные шаблоны (`include`).

### Использование .Chart.Name

Для динамической генерации имён на основе чарта:

```yaml
metadata:
  name: {{ .Chart.Name }}-web
  labels:
    app.kubernetes.io/name: {{ .Chart.Name }}
```

При имени чарта `myapp` ресурс получит имя `myapp-web`. Подробнее: [Встроенные объекты Helm](../objects.md).

---

## Validation and Testing

### Локальный рендер

```bash
# Итоговые манифесты
helm template myrelease .

# С кастомными значениями
helm template myrelease . --set app.port=9090

# С альтернативным values-файлом
helm template myrelease . -f values-production.yaml
```

### Dry-run с кластером

```bash
# Проверка без применения
helm install --dry-run --debug myrelease .

# Проверка перед обновлением
helm upgrade --dry-run --debug myrelease .
```

### Линтинг

```bash
# Проверка синтаксиса и структуры
helm lint .

# С альтернативными values
helm lint . -f values-production.yaml
```

---

## Best Practices

| Практика | Описание |
|----------|----------|
| **SSoT** | Все изменяемые параметры — в `values.yaml` |
| **Группировка** | Логические секции: `app`, `image`, `service`, `ingress` |
| **Синхронизация** | Один `.Values` используется в Deployment, Service, Ingress |
| **Локальные переменные** | Уменьшение дублирования внутри одного файла |
| **Именованные шаблоны** | Для межфайловых конструкций (имена, метки) — [Именованные шаблоны](../_helpers.md) |
| **Валидация** | `helm template` + `helm lint` перед `helm install` |
| **Dry-run** | `helm upgrade --dry-run --debug` для финальной проверки |

---

## Additional Information

Объект `.Values` — в [Встроенные объекты Helm](../objects.md). Управление values-файлами для окружений — в [Практические сценарии чартов](../../helm_chart_practical_scenarios.md). Условная логика с параметрами — в [Условная логика](./conditionals.md).
