# Шаблонизация NetworkPolicy

---

## Определения

**NetworkPolicy** — ресурс Kubernetes (API-группа `networking.k8s.io`), предназначенный для декларативного управления сетевым доступом на уровнях L3 (IP) и L4 (TCP/UDP). Функционирует по принципу «белых списков» (Allow-lists).

**Селекторная связность** — принцип работы NetworkPolicy, основанный на точном совпадении меток (labels). В контексте Helm это требует синхронизации меток между манифестами управления (Deployment, StatefulSet) и самой политикой через общие хелперы.

**CNI-реализация** — техническое исполнение правил NetworkPolicy осуществляется сетевым плагином (Cilium, Calico, Antrea). Helm лишь обеспечивает корректную генерацию манифестов, но не гарантирует их работу, если CNI в кластере не поддерживает сетевые политики.

---

## Базовые концепции

### Проблема рассинхронизации меток

NetworkPolicy изолирует поды на основе `podSelector`. Если селектор в политике не совпадает с реальными метками пода (из-за опечатки или изменения логики в `_helpers.tpl`), трафик будет либо полностью заблокирован (при Default Deny), либо политика просто не применится.

При шаблонизации необходимо решить три задачи:
1. **DRY (Don't Repeat Yourself):** Использование единого источника меток через именованные шаблоны `include`.
2. **Гибкость:** Возможность включать/выключать политики и настраивать CIDR-блоки через `values.yaml`.
3. **Безопасность:** Использование подхода Default Deny по умолчанию.

### Именованные порты (Named Ports)

Рекомендуется использовать имена портов (например, `http`, `grpc`) вместо жестко прописанных чисел. Это позволяет изменять порты в контейнерах через `values.yaml` без необходимости обновления манифестов NetworkPolicy.

```yaml
ports:
  - protocol: TCP
    port: {{ .Values.service.targetPort | default "http" }}
```

### Валидация через required

Для критически важных параметров (например, внешних IP-адресов) следует использовать функцию `required`. Это прервет процесс `helm install/upgrade` с понятной ошибкой, если пользователь забыл указать необходимые данные.

```yaml
cidr: {{ required "A valid CIDR is required for external-db egress rule" .Values.networkPolicy.egress.db.cidr }}
```

---

## Практические сценарии

### Стандартная политика для приложения (Ingress)

Разрешение входящего трафика на порт приложения только от Ingress-контроллера и внутри кластера от определенных компонентов.

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
      # Трафик от Ingress Controller
      - podSelector:
          matchLabels:
            app.kubernetes.io/component: controller
      # Внутренний трафик от фронтенда
      - podSelector:
          matchLabels:
            {{- include "myapp.selectorLabels" . | nindent 12 }}
            component: frontend
      ports:
        - protocol: TCP
          port: {{ .Values.service.targetPort | default "http" }}
```

### Изоляция (Default Deny)

Блокировка всего входящего и исходящего трафика для подов приложения. Это «нулевой рубеж» безопасности.

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

### Работа с внешними CIDR и исключениями

Доступ к внешней базе данных с использованием `ipBlock` и исключением локальных подсетей.

**values.yaml:**
```yaml
networkPolicy:
  egress:
    externalDb:
      enabled: true
      cidr: 1.2.3.4/32
      except:
        - 10.0.0.0/8
```

**templates/networkpolicy-egress.yaml:**
```yaml
{{- if .Values.networkPolicy.egress.externalDb.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-egress-db
spec:
  podSelector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Egress
  egress:
    - to:
      - ipBlock:
          cidr: {{ required "CIDR is required" .Values.networkPolicy.egress.externalDb.cidr }}
          {{- if .Values.networkPolicy.egress.externalDb.except }}
          except:
            {{- toYaml .Values.networkPolicy.egress.externalDb.except | nindent 12 }}
          {{- end }}
      ports:
        - protocol: TCP
          port: 5432
{{- end }}
```

### Динамический список портов

Если приложение прослушивает несколько портов, их список можно генерировать динамически через цикл.

```yaml
ingress:
  - from:
    - podSelector: {}
    ports:
      {{- range .Values.networkPolicy.ingressPorts }}
      - protocol: {{ .protocol | default "TCP" }}
        port: {{ .port }}
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
          port: {{ .Values.monitoring.port | default 9090 }}
{{- end }}
```

---

## Дополнительная информация

### Лучшие практики

1. **Имена шаблонов:** Всегда используйте префикс чарта в `define` (например, `myapp.selectorLabels`), чтобы избежать коллизий при использовании чарта как зависимости (Subchart).
2. **Типизация CIDR:** При использовании `ipBlock` передавайте строки в кавычках в `values.yaml`, чтобы избежать интерпретации чисел как других типов.
3. **Автоматические метки:** Используйте метку `kubernetes.io/metadata.name` для `namespaceSelector`, так как она автоматически добавляется в Kubernetes 1.21+.
4. **Приоритет AdminNetworkPolicy:** Помните, что глобальные политики администратора (ANP) имеют приоритет над обычными `NetworkPolicy`.

### Отладка и верификация

Для проверки корректности генерации манифестов NetworkPolicy используйте:
- `helm template .` — для просмотра отрендеренных YAML-файлов.
- `helm install --dry-run --debug` — для симуляции установки с проверкой API-версий.
- `kubectl get networkpolicy -n <namespace>` — для проверки наличия объектов в кластере.

### См. также
- [Именованные шаблоны и хелперы](../_helpers.md) — управление метками и DRY.
- [Обзор сценариев шаблонизации](./overview.md) — каталог практических примеров.
- [NetworkPolicy: навигатор](../../../../Networking/Network/network_policy.md) — подробная теория сетевых политик.
