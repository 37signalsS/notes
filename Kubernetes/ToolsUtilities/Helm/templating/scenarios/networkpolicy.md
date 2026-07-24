# Шаблонизация NetworkPolicy

---

## Определения

**NetworkPolicy** — ресурс Kubernetes, определяющий правила прохождения трафика между группами подов и сетевыми сегментами на уровнях L3 (IP) и L4 (TCP/UDP).

**Селекторная связность** — принцип работы NetworkPolicy, основанный на точном совпадении меток (labels). В контексте Helm это требует синхронизации меток между манифестами Deployment/StatefulSet и самой политикой.

---

## Базовые концепции

### Проблема рассинхронизации меток

NetworkPolicy работает по принципу «белого списка» (allow-list). Если селектор в политике не совпадает с метками пода из-за опечатки или изменения логики именования, политика либо не применится, либо заблокирует весь трафик. 

При шаблонизации необходимо решить две задачи:
1. **DRY (Don't Repeat Yourself):** Использование единого источника меток через именованные шаблоны.
2. **Гибкость:** Возможность включать/выключать политики и настраивать CIDR-блоки через `values.yaml`.

### Почему использование include обязательно

В отличие от Service, где селектор часто прост, NetworkPolicy может содержать множество правил `from` и `to`. Использование `{{ include "myapp.selectorLabels" . }}` гарантирует, что при изменении структуры меток в `_helpers.tpl` изменения автоматически применятся ко всей сетевой инфраструктуре чарта.

---

## Практические сценарии

### Стандартная политика для приложения (Ingress)

Разрешение входящего трафика на порт приложения только из определенных сегментов.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-allow-ingress
spec:
  podSelector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
  ingress:
    - from:
      # Разрешаем трафик от Ingress Controller (по меткам)
      - podSelector:
          matchLabels:
            app.kubernetes.io/component: controller
      # Разрешаем трафик внутри Namespace от определенных подов
      - podSelector:
          matchLabels:
            {{- include "myapp.selectorLabels" . | nindent 12 }}
            component: frontend
      ports:
        - protocol: TCP
          port: {{ .Values.service.port }}
```

### Изоляция (Default Deny)

Рекомендуемый паттерн безопасности — блокировка всего трафика по умолчанию с последующим точечным разрешением.

```yaml
{{- if .Values.networkPolicy.defaultDeny }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-default-deny
spec:
  podSelector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
    - Egress
{{- end }}
```

### Работа с внешними CIDR-блоками

Шаблонизация доступа к внешним системам (например, базам данных вне кластера) через списки IP-адресов.

**values.yaml:**
```yaml
networkPolicy:
  egress:
    dbExternal:
      enabled: true
      cidrs:
        - 192.168.1.10/32
        - 10.0.4.0/24
```

**templates/networkpolicy-egress.yaml:**
```yaml
{{- if .Values.networkPolicy.egress.dbExternal.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-external-db
spec:
  podSelector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Egress
  egress:
    - to:
      {{- range .Values.networkPolicy.egress.dbExternal.cidrs }}
      - ipBlock:
          cidr: {{ . }}
      {{- end }}
      ports:
        - protocol: TCP
          port: 5432
{{- end }}
```

### Кросс-пространственное взаимодействие (Monitoring)

Разрешение сбора метрик для Prometheus, находящегося в другом Namespace.

```yaml
{{- if .Values.monitoring.enabled }}
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
            kubernetes.io/metadata.name: {{ .Values.monitoring.namespace | default "monitoring" }}
        podSelector:
          matchLabels:
            app.kubernetes.io/name: prometheus
      ports:
        - protocol: TCP
          port: 9090
{{- end }}
```

---

## Дополнительная информация

### Лучшие практики

1. **Имена шаблонов:** Всегда используйте префикс чарта в именах `define` (например, `myapp.selectorLabels`), чтобы избежать конфликтов при использовании субчартов.
2. **Валидация CIDR:** При работе с `ipBlock` убедитесь, что в `values.yaml` передаются валидные CIDR-строки, иначе Helm успешно отрендерит манифест, но Kubernetes отклонит его при применении.
3. **Селектор Namespace:** Помните, что `namespaceSelector` требует наличия соответствующих меток на самих объектах Namespace. В современных версиях K8s метка `kubernetes.io/metadata.name` добавляется автоматически.

### См. также
- [Именованные шаблоны и хелперы](../_helpers.md) — управление метками и DRY.
- [Обзор сценариев шаблонизации](./overview.md) — каталог практических примеров.
- [NetworkPolicy: навигатор](../../../../Networking/Networking/Network/network_policy.md) — подробная теория сетевых политик.
