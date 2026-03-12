# Использование NOTES.txt

---

## Определения

**NOTES.txt** — специальный шаблон в `templates/NOTES.txt`, содержимое которого выводится в консоль после `helm install` или `helm upgrade`.

---

## Назначение

Файл `templates/NOTES.txt` — специальный шаблон, содержимое которого выводится в консоль после `helm install` или `helm upgrade`. Предоставляет пользователю инструкции по доступу к приложению.

---

## Пример структуры

```yaml
Thank you for installing {{ .Chart.Name }}.

Your release is named {{ .Release.Name }}.

To learn more about the release, try:

  $ helm status {{ .Release.Name }}
  $ helm get all {{ .Release.Name }}

{{- if .Values.ingress.enabled }}
  {{- range .Values.ingress.hosts }}
  {{ .name }}:
    http://{{ .name }}
  {{- end }}
{{- else if eq .Values.service.type "LoadBalancer" }}
  NOTE: It may take a few minutes for the LoadBalancer IP to be available.
  To watch the status, run:

  $ kubectl get svc -w {{ .Release.Name }}
{{- else if eq .Values.service.type "NodePort" }}
  To access your application:

  $ kubectl port-forward svc/{{ .Release.Name }} {{ .Values.service.port }}:{{ .Values.service.port }}
{{- end }}
```

---

## Типичные сценарии

| Тип Service | Инструкция |
|-------------|-------------|
| LoadBalancer | Команда для получения внешнего IP |
| NodePort | Формирование URL с NodePort |
| ClusterIP | Предложение использовать port-forward |

---

## Дополнительные ссылки

- [helm_templating](../Helm/helm_templating.md) — обзорная страница
- [Функции](../functions.md) — используемые функции
