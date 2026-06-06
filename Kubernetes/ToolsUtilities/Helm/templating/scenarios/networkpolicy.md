# Шаблонизация NetworkPolicy

---

## Определения

**NetworkPolicy** — ресурс Kubernetes для управления сетевым трафиком между Pod (подами) на сетевом (L3) и транспортном (L4) уровнях. Подробнее о концепции: [NetworkPolicy: навигатор](../../../../Networking/Networking/Network/network_policy.md).

**Ключевая особенность:** NetworkPolicy требует **точного совпадения** селекторов `podSelector` с метками подов. Рассинхронизация меток между Deployment (развертыванием) и NetworkPolicy приводит к тому, что политика либо не применяется, либо блокирует легитимный трафик.

---

## Основные концепции

При шаблонизации NetworkPolicy в Helm возникают две типовые проблемы:

1. **Рассинхронизация меток** — метки в `podSelector` NetworkPolicy не совпадают с метками в `spec.selector` Deployment.
2. **Хардкод имён** — имена ресурсов и меток жёстко заданы, что ломает логику при изменении `fullnameOverride` или `nameOverride`.

Решение — использование именованных шаблонов (`include`), определённых в `_helpers.tpl`. Это гарантирует использование общих определений для всех меток. Подробнее: [Именованные шаблоны и хелперы](../_helpers.md).

### Почему именно NetworkPolicy

В отличие от Service и Deployment, где Kubernetes допускает некоторые расхождения, NetworkPolicy работает по принципу **exact match** (точного соответствия):

- `podSelector.matchLabels` должен **в точности** совпадать с `spec.selector.matchLabels` пода.
- `from[].podSelector.matchLabels` должен совпадать с метками подов-источников.
- Любая опечатка → политика не применяется или блокирует не тот трафик.

---

## Практические сценарии

### NetworkPolicy для sidecar-компонента

Политика для mail-relay, разрешающая ingress (входящий трафик) только от подов основного приложения:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-mail-relay
spec:
  podSelector:
    matchLabels:
      {{- include "myapp.mail-relay.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
  ingress:
    - from:
      - podSelector:
          matchLabels:
            {{- include "myapp.selectorLabels" . | nindent 12 }}
      ports:
        - protocol: TCP
          port: 25
```

Использование `include` гарантирует, что:

- `podSelector` совпадает с метками mail-relay Deployment.
- `from[].podSelector` совпадает с метками основного приложения.

### Условное включение NetworkPolicy

Создание политики только при включённом флаге в `values.yaml`:

```yaml
{{- if .Values.networkPolicy.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-default-deny
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
{{- end }}
```

Политика блокирует весь входящий (Ingress) и исходящий (Egress) трафик по умолчанию.

### Разрешение трафика между Namespace (пространствами имен)

NetworkPolicy с динамическим `namespaceSelector`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-allow-monitoring
spec:
  podSelector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
  ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: {{ .Values.monitoringNamespace | default "monitoring" }}
        podSelector:
          matchLabels:
            app: prometheus
      ports:
        - protocol: TCP
          port: 9090
```

---

## Дополнительная информация

- [Именованные шаблоны и хелперы](../_helpers.md) — управление метками.
- [NetworkPolicy: навигатор](../../../../Networking/Networking/Network/network_policy.md) — концептуальный обзор.
- [Обзор сценариев](./overview.md) — другие примеры шаблонизации.
