# Автоматический перезапуск при изменении ConfigMap

---

## Определения

**Checksum-аннотации** — аннотации с SHA256-хешем содержимого ConfigMap, вызывающие rolling update при изменении конфигурации.

---

## Принцип работы

1. В манифест Deployment/StatefulSet добавляется аннотация в `spec.template.metadata.annotations`
2. Значение аннотации — SHA256-хеш от содержимого шаблона ConfigMap
3. При `helm upgrade` содержимое ConfigMap меняется → хеш меняется → Kubernetes видит изменение в `spec.template` → rolling update

Этот подход избавляет от необходимости устанавливать внешние контроллеры (stakater/reloader).

---

## Пример для StatefulSet

**templates/configmap.yaml:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "myapp.fullname" . }}-config
data:
  my-value: {{ .Values.myValue | quote }}
  another-value: {{ .Values.anotherValue | quote }}
```

**templates/statefulset.yaml:**

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ include "myapp.fullname" . }}
spec:
  # ...
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      containers:
        # ...
```

**Разбор аннотации:**

- `print .Template.BasePath "/configmap.yaml"` — конструирует путь к файлу
- `include ... .` — вставляет отрендеренное содержимое файла
- `| sha256sum` — вычисляет SHA256-хеш

---

## Важные замечания

- Работает одинаково для **Deployment** и **StatefulSet**
- Распространённая ошибка — добавить аннотацию в Deployment, но забыть в StatefulSet
- При изменении values.yaml, используемых в ConfigMap, хеш автоматически обновится

---

## Дополнительные ссылки

- [Функции](../functions.md) — sha256sum, include, toYaml
- [Условная логика](./conditionals.md) — условное создание ресурсов
- [helm_templating](../Helm/helm_templating.md) — обзорная страница
