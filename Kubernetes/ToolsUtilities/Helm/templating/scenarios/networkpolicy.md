# Шаблонизация NetworkPolicy

---

## Определения

**NetworkPolicy** — ресурс Kubernetes для управления сетевым трафиком между подами. Требует точного соответствия селекторов меткам подов.

---

## Использование с именованными шаблонами

NetworkPolicy требует точного соответствия селекторов меткам подов. Использование именованных шаблонов исключает рассинхронизацию.

**Пример политики в `templates/mail-relay-netpol.yaml`:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-mail-relay
spec:
  # Применяем политику к подам mail-relay
  podSelector:
    matchLabels:
      {{- include "myapp.mail-relay.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
  ingress:
    # Разрешаем трафик от подов основного приложения
    - from:
      - podSelector:
          matchLabels:
            {{- include "myapp.labels" . | nindent 12 }}
      ports:
        - protocol: TCP
          port: 25
```

Здесь `include` гарантирует, что селекторы в NetworkPolicy точно соответствуют меткам в Deployment и Service.

---

## Преимущества подхода

- Централизованное управление метками
- Упрощение использования в Service, Deployment, NetworkPolicy
- Снижение риска ошибок из-за опечаток

---

## Дополнительные ссылки

- [Именованные шаблоны](../_helpers.md) — создание и использование
- [helm_templating](../../helm_templating.md) — обзорная страница
