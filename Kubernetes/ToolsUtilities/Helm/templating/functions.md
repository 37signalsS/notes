# Функции Helm-шаблонов

---

## Определения

**Функции Sprig** — библиотека из 100+ функций для работы со строками, коллекциями, математикой, датами и криптографией. Интегрирована в Helm.

---

## Ключевые функции

| Функция | Назначение | Пример |
|---------|------------|--------|
| `quote` | Заключение в двойные кавычки | `{{ .Values.name \| quote }}` |
| `default` | Значение по умолчанию | `{{ .Values.tag \| default "latest" }}` |
| `required` | Обязательный параметр | `{{ required "Image required" .Values.image }}` |
| `toYaml` | Сериализация в YAML | `{{ toYaml .Values.nodeSelector }}` |
| `nindent` | Отступ для YAML-блока | `{{ toYaml .Values.tolerations \| nindent 8 }}` |
| `tpl` | Рендер строки как шаблона | `{{ tpl .Values.config . }}` |
| `include` | Вставка именованного шаблона | `{{ include "chart.fullname" . }}` |
| `trunc` | Обрезка строки до указанной длины | `{{ .Release.Name \| trunc 10 }}` |
| `trimSuffix`| Удаление суффикса из строки | `{{ "my-release-1" \| trimSuffix "-1" }}` |
| `sha256sum` | Вычисление SHA256-хеша | `{{ .Values.data \| sha256sum }}` |
| `b64enc` | Base64 кодирование | `{{ .Values.data \| b64enc }}` |
| `b64dec` | Base64 декодирование | `{{ .Values.data \| b64dec }}` |

---

## Примеры использования

### toYaml и nindent

```yaml
spec:
  template:
    spec:
      {{- if .Values.affinity }}
      affinity:
        {{- toYaml .Values.affinity | nindent 8 }}
      {{- end }}
      {{- if .Values.tolerations }}
      tolerations:
        {{- toYaml .Values.tolerations | nindent 8 }}
      {{- end }}
```

### Комбинирование функций

```yaml
image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
```

### required — обязательные параметры

```yaml
{{- $image := required "Values.image.repository обязателен" .Values.image.repository }}
image: "{{ $image }}"
```

### tpl — рендер строки как шаблона

Позволяет динамически генерировать конфигурацию:

```yaml
{{- $context := . }}
{{- range .Values.configFiles }}
{{ .name }}: |
  {{ tpl .content $context | nindent 2 }}
{{- end }}
```

---

## Функции Sprig

Helm использует библиотеку [Sprig](http://masterminds.github.io/sprig/), которая включает:

- **Строки**: `lower`, `upper`, `title`, `quote`, `squote`, `trim`, `trimSuffix`, `trimPrefix`
- **Коллекции**: `first`, `last`, `rest`, `push`, `append`, `reverse`, `uniq`
- **Математика**: `add`, `sub`, `mul`, `div`, `mod`
- **Даты**: `now`, `dateModify`, `date`
- **Крипто**: `sha256sum`, `sha512sum`, `b64enc`, `b64dec`

---

## Дополнительные ссылки

- [Синтаксис шаблонов](./syntax.md) — базовый синтаксис и управляющие конструкции
- [Встроенные объекты](./objects.md) — .Values, .Release, .Chart и другие
- [Именованные шаблоны](./templates/_helpers.md) — создание переиспользуемых блоков
- [helm_templating](../Helm/helm_templating.md) — обзорная страница
