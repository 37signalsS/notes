# Параметризация через values.yaml

---

## Определения

**Параметризация** — замена жёстко заданных значений (хардкода) в манифестах на переменные из конфигурационного файла `values.yaml` и объекта `.Values`. Подробнее об объекте `.Values`: [Встроенные объекты Helm](../objects.md). Управление конфигурацией для различных окружений — в [Практические сценарии чартов](../../helm_chart_practical_scenarios.md).

---

## Основные концепции

### Проблема хардкода

Без параметризации одни и те же значения (имена, порты, репозитории образов) дублируются в различных ресурсах (Deployment, Service, Ingress). Изменение таких данных требует правки в каждом файле, что часто приводит к рассинхронизации и ошибкам.

| Проблема | Риск |
|----------|------|
| Дублирование порта в Deployment и Service | Рассинхронизация при изменении |
| Хардкод имён | Невозможность запуска нескольких экземпляров приложения |
| Ручные правки шаблонов | Человеческая ошибка может сломать развёртывание |
| Отсутствие гибкости | Невозможность развернуть приложение с другими параметрами без изменения кода чарта |

### Принцип централизованной конфигурации для values.yaml

Файл `values.yaml` становится единым источником всех изменяемых параметров. Шаблоны манифестов только ссылаются на объект `.Values` и не содержат жёстко заданных значений.

Пример структуры группировки параметров:

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

## Практические сценарии

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

Параметр `targetPort` ссылается на `.Values.app.port` — тот же источник, что и `containerPort` в Deployment. Благодаря этому рассинхронизация при изменении порта невозможна.

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

В пределах одного файла шаблона длинные конструкции или часто используемые значения выносятся в локальные переменные:

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

Для динамической генерации имён ресурсов на основе названия чарта:

```yaml
metadata:
  name: {{ .Chart.Name }}-web
  labels:
    app.kubernetes.io/name: {{ .Chart.Name }}
```

При имени чарта `myapp` ресурс получит имя `myapp-web`. Подробнее: [Встроенные объекты Helm](../objects.md).

---

## Валидация и тестирование

### Локальный рендеринг (Local Render)

Позволяет проверить итоговые манифесты без отправки их в кластер Kubernetes.

```bash
# Итоговые манифесты с параметрами по умолчанию
helm template myrelease .

# С переопределением кастомных значений через CLI (Command Line Interface)
helm template myrelease . --set app.port=9090

# С использованием альтернативного values-файла
helm template myrelease . -f values-production.yaml
```

### Тестирование с подключением к кластеру (Dry-run)

Позволяет проверить шаблоны и их совместимость с кластером без фактического применения изменений.

```bash
# Проверка перед первичной установкой
helm install --dry-run --debug myrelease .

# Проверка перед обновлением существующего релиза
helm upgrade --dry-run --debug myrelease .
```

### Проверка синтаксиса (Линтинг)

```bash
# Проверка синтаксиса и структуры чарта
helm lint .

# Проверка с альтернативными параметрами
helm lint . -f values-production.yaml
```

---

## Лучшие практики

| Практика | Описание |
|----------|----------|
| **Централизация конфигурации** | Все изменяемые параметры должны храниться в `values.yaml` |
| **Группировка параметров** | Разделение на логические секции: `app`, `image`, `service`, `ingress` |
| **Синхронизация данных** | Один путь в `.Values` используется во всех связанных манифестах (например, Deployment и Service) |
| **Локальные переменные** | Использование переменных (`$var`) для уменьшения дублирования кода внутри одного файла шаблона |
| **Именованные шаблоны** | Использование хелперов для межфайловых конструкций (динамические имена, общие метки) — [Именованные шаблоны](../_helpers.md) |
| **Обязательная валидация** | Выполнение команд `helm template` и `helm lint` перед развёртыванием |
| **Dry-run тестирование** | Использование `helm upgrade --dry-run --debug` для финальной проверки перед внесением изменений в production |

---

## Дополнительная информация

- [Встроенные объекты Helm](../objects.md) — подробности об объекте `.Values`.
- [Практические сценарии чартов](../../helm_chart_practical_scenarios.md) — управление конфигурацией (values-файлами) для различных окружений.
- [Условная логика](./conditionals.md) — использование параметров в конструкциях `if/else`.
