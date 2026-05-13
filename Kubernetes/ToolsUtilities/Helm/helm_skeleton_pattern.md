# Helm Skeleton Pattern

Использование единого шаблона (Skeleton) для всех микросервисов позволяет избежать дублирования манифестов, стандартизировать нейминг и упростить поддержку инфраструктуры при росте количества сервисов.

---

## Definitions

| Термин | Описание |
|--------|----------|
| **Helm Skeleton** | Набор базовых шаблонов (`_template/`), на основе которых создаются чарты для конкретных сервисов |
| **_helpers.tpl** | Файл с общими функциями для генерации имён, меток и переменных окружения |
| **Probes** | Механизмы проверки готовности (`readinessProbe`) и работоспособности (`livenessProbe`) контейнера |

---

## Basic Concepts

### Когда использовать

Паттерн Skeleton рекомендуется внедрять, когда количество однотипных микросервисов превышает 5–10 штук. Это решает проблему "разъезжающегося" нейминга, портов и конфигураций.

### Структура шаблона

Типовая структура директории `charts/_template/`:

```text
charts/_template/
├── Chart.yaml              # Метаданные (имя шаблона)
├── values.yaml               # Значения по умолчанию для всех сервисов
├── values-dev.yaml           # Специфичные настройки для dev-окружения
├── values-prod.yaml          # Специфичные настройки для prod-окружения
├── templates/
│   ├── _helpers.tpl          # Логика именования и общие блоки
│   ├── deployment.yaml       # Шаблон развёртывания
│   ├── service.yaml          # Шаблон сервиса
│   ├── serviceaccount.yaml   # Управление правами
│   ├── role.yaml             # RBAC: Роль
│   ├── rolebinding.yaml      # RBAC: Привязка роли
│   ├── hpa.yaml              # Горизонтальное масштабирование
│   ├── ingress.yaml          # Внешний доступ
│   ├── secret.yaml           # Секреты (через sops или внешние хранилища)
│   └── configmap.yaml        # Конфигурация
└── README.md                 # Документация по использованию шаблона
```

При создании нового сервиса достаточно скопировать эту структуру и заполнить `values.yaml`.

---

## Practical Scenarios

### 1. Стандартизация нейминга через _helpers.tpl

Использование функций вместо жёстких имён позволяет устанавливать несколько экземпляров чарта в разные namespace без конфликтов.

**_helpers.tpl:**

```go
{{- define "my-service.fullname" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "my-service.labels" -}}
helm.sh/chart: {{ include "my-service.chart" . }}
app.kubernetes.io/name: {{ include "my-service.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

### 2. Параметризация Probes (функция omit)

В Kubernetes поле `enabled` внутри `livenessProbe` недопустимо. Оно используется только Helm'ом для управления логикой шаблона. Чтобы передать чистый YAML в API Kubernetes, используется функция `omit`.

**deployment.yaml:**

```yaml
{{- if .Values.livenessProbe.enabled }}
livenessProbe:
  {{- omit .Values.livenessProbe "enabled" | toYaml | nindent 12 }}
{{- end }}
```

**values.yaml:**

```yaml
livenessProbe:
  enabled: true
  httpGet:
    path: /actuator/health
    port: 8080
  initialDelaySeconds: 60
  periodSeconds: 20
```

### 3. Слияние переменных окружения (mergeOverwrite)

Для поддержки общих и специфичных для окружения (dev/prod) переменных используется функция `mergeOverwrite`.

**_helpers.tpl:**

```go
{{- define "my-service.env" -}}
{{- $merged := mergeOverwrite (dict) .Values.env.common .Values.env.dev .Values.env.prod }}
{{- range $key, $val := $merged }}
- name: {{ $key }}
  value: {{ $val | quote }}
{{- end }}
{{- end }}
```

**values.yaml:**

```yaml
env:
  common:
    JAVA_OPTS: "-Xmx512m"
    SPRING_PROFILES_ACTIVE: "k8s"
  dev:
    LOGGING_LEVEL: "DEBUG"
  prod:
    LOGGING_LEVEL: "INFO"
    JAVA_OPTS: "-Xmx2g"
```

---

## Дополнительная информация

### См. также

- [Структура Helm-чарта](./helm_chart_structure.md) — базовые компоненты чарта
- [Функции шаблонов](./templating/functions.md) — подробнее об `omit` и `mergeOverwrite`
- [Зависимости и Library Charts](./helm_dependencies_and_library_charts.md) — альтернативный подход через библиотечные чарты
