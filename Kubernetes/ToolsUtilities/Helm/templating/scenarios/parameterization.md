# Вынос параметров в values.yaml

---

## Определения

**Параметризация** — процесс замены жёстко заданных значений в манифестах на переменные, ссылающиеся на `values.yaml`.

**Единый источник правды (SSoT)** — принцип, при котором `values.yaml` становится централизованным хранилищем всех изменяемых параметров чарта.

---

## Проблема жёстко заданных значений

Рассмотрим типичную проблему до параметризации:

**deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: app
          ports:
            - containerPort: 8080
```

**service.yaml:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  type: ClusterIP
  ports:
    - port: 80
      targetPort: 8080
```

**Проблемы:**

| Проблема | Риск |
|----------|------|
| Дублирование порта в Deployment и Service | При изменении нужно править оба файла |
| Хардкод имени `web` | Невозможно использовать чарт для нескольких экземпляров |
| Ручные правки в шаблонах | Ошибка в одном месте ломает развёртывание |
| Отсутствие гибкости | Нельзя развернуть с разными параметрами без изменения шаблонов |

---

## Решение: вынос в values.yaml

### Шаг 1: Создание values.yaml

```yaml
# values.yaml — единый источник правды
app:
  name: kosms-zero-to-hero
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

### Шаг 2: Параметризация Deployment

**templates/deployment.yaml:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.app.name }}-web
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

### Шаг 3: Параметризация Service

**templates/service.yaml:**

```yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ .Values.app.name }}-service
spec:
  type: {{ .Values.service.type }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: {{ .Values.app.port }}  # Синхронизировано с Deployment
      protocol: TCP
      name: http
  selector:
    app: {{ .Values.app.name }}
```

### Шаг 4: Параметризация Ingress

**templates/ingress.yaml:**

```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Values.app.name }}-ingress
spec:
  rules:
    - host: {{ .Values.app.domain }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ .Values.app.name }}-service
                port:
                  number: {{ .Values.service.port }}
{{- end }}
```

---

## Преимущества параметризации

| Аспект | До | После |
|--------|-----|-------|
| Изменение порта | Правка в 2+ файлах | Изменение в одном месте |
| Развёртывание в разных окружениях | Копирование шаблонов | Разные values-файлы |
| Риск ошибки | Высокий | Минимальный |
| Поддержка | Сложная | Централизованная |

---

## Практика: проверка шаблонов

### Локальный рендер

```bash
# Проверка итоговых манифестов
helm template myrelease .

# Рендер с кастомными значениями
helm template myrelease . --set app.port=9090

# Рендер с альтернативным values-файлом
helm template myrelease . -f values-production.yaml
```

### Dry-run с кластером

```bash
# Проверка без применения изменений (показывает итоговые манифесты)
helm install --dry-run --debug myrelease .

# Проверка существующего релиза перед обновлением
helm upgrade --dry-run --debug myrelease .
```

### Валидация чарта

```bash
# Линтинг чарта (проверка синтаксиса и структуры)
helm lint .

# Линтинг с альтернативными values
helm lint . -f values-production.yaml
```

### Проверка с незакоммиченными изменениями

При разработке шаблонов удобно использовать `helm template` с флагом, позволяющим рендерить манифесты с локальными изменениями без коммита в Git:

```bash
# Рендер с незакоммиченными изменениями
helm template myrelease . --debug
```

Это позволяет итеративно проверять изменения шаблонов без необходимости коммитить каждое изменение.

---

## Лучшие практики

| Практика | Описание |
|----------|----------|
| **Единый источник правды** | Все изменяемые параметры выносятся в `values.yaml` |
| **Группировка параметров** | Логическая группировка в секции (`app`, `image`, `service`, `ingress`) |
| **Синхронизация через переменные** | Один шаблон используется в нескольких файлах (например, порт в Deployment и Service) |
| **Локальные переменные** | Уменьшение дублирования в пределах одного файла шаблона |
| **Итеративная проверка** | `helm template` + `helm lint` перед применением в кластер |
| **Dry-run перед deploy** | `helm upgrade --dry-run --debug` для финальной проверки |

---

## Локальные переменные в шаблонах

Для упрощения повторяющихся конструкций используйте локальные переменные:

**templates/ingress.yaml:**

```yaml
{{- $domain := .Values.app.domain }}
{{- $port := .Values.app.port }}
{{- $serviceName := printf "%s-service" .Values.app.name }}

apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Values.app.name }}-ingress
spec:
  rules:
    - host: {{ $domain }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ $serviceName }}
                port:
                  number: {{ $port }}
```

**Преимущества локальных переменных:**

- Уменьшение дублирования длинных конструкций
- Улучшение читаемости шаблона
- Упрощение поддержки (изменение в одном месте)

**Ограничение:** действуют только в пределах одного файла шаблона.

---

## Встроенная переменная .Chart.Name

Для динамической генерации имён на основе названия чарта:

```yaml
metadata:
  name: {{ .Chart.Name }}-web
  labels:
    app.kubernetes.io/name: {{ .Chart.Name }}
```

При имени чарта `myapp` ресурс получит имя `myapp-web`.

---

## Дополнительные ссылки

- [Структура Helm-чарта](../../helm_chart_structure.md) — организация values.yaml
- [Встроенные объекты](../objects.md) — .Values, .Chart, .Release
- [Синтаксис шаблонов](../syntax.md) — базовый синтаксис Go templates
- [Условная логика](./conditionals.md) — if/else, with
