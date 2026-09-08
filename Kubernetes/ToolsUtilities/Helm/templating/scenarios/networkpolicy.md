# Шаблонизация NetworkPolicy

---

## Определения

**NetworkPolicy** — ресурс Kubernetes (API-группа `networking.k8s.io`), предназначенный для декларативного управления сетевым доступом на уровнях L3 (IP) и L4 (TCP/UDP). Функционирует по принципу «белых списков» (Allow-lists).

**Селекторная связность** — принцип работы NetworkPolicy, основанный на точном совпадении меток (labels). В контексте Helm это требует синхронизации меток между манифестами управления (Deployment, StatefulSet) и самой политикой через общие хелперы.

**CNI-реализация** — техническое исполнение правил NetworkPolicy осуществляется сетевым плагином (Cilium, Calico, Antrea). Helm лишь обеспечивает корректную генерацию манифестов, но не гарантирует их работу, если CNI в кластере не поддерживает сетевые политики.

**policyTypes** — обязательное поле, определяющее направления фильтрации: `Ingress`, `Egress` или оба одновременно. Без него политика не оказывает воздействия, даже если правила определены.

**podSelector** — механизм выбора подов, к которым применяется политика. Пустой селектор `{}` означает «все поды в namespace».

**namespaceSelector** — механизм выбора namespace'ов, из которых разрешается трафик. Использует метки namespace для идентификации.

**ipBlock** — механизм фильтрации по CIDR-блокам IP-адресов. Полезен для ограничения доступа к внешним подсетям, но неэффективен для East-West трафика из-за эфемерности IP подов.

**Default Deny** — режим изоляции, при котором весь входящий и исходящий трафик блокируется по умолчанию. Требует явного указания правил `ingress` и `egress` для разрешения соединений.

**microsegmentation** — стратегия разделения сети на мелкие изолированные сегменты. В Kubernetes реализуется через комбинацию NetworkPolicy и namespace-изоляции.

---

## Базовые концепции

### Проблема рассинхронизации меток

NetworkPolicy изолирует поды на основе `podSelector`. Если селектор в политике не совпадает с реальными метками пода (из-за опечатки или изменения логики в `_helpers.tpl`), трафик будет либо полностью заблокирован (при Default Deny), либо политика просто не применится.

При шаблонизации необходимо решить три задачи:
1. **DRY (Don't Repeat Yourself):** Использование единого источника меток через именованные шаблоны `include`.
2. **Гибкость:** Возможность включать/выключать политики и настраивать CIDR-блоки через `values.yaml`.
3. **Безопасность:** Использование подхода Default Deny по умолчанию.

### Важность Egress и DNS

При включении изоляции исходящего трафика (Egress) поды теряют доступ к DNS. Это одна из наиболее частых причин сбоев при внедрении NetworkPolicy. Любая Egress-политика должна явно разрешать трафик к `kube-dns` (порт 53 UDP/TCP) в namespace `kube-system`.

### Валидация через required

Для критически важных параметров (например, внешних IP-адресов) следует использовать функцию `required`. Это прервет процесс `helm install/upgrade` с понятной ошибкой, если пользователь забыл указать необходимые данные.

```yaml
cidr: {{ required "A valid CIDR is required for external-db egress rule" .Values.networkPolicy.egress.db.cidr }}
```

### JSON Schema для networkPolicy

Для предотвращения ошибок типизации в `values.yaml` используйте `values.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "properties": {
    "networkPolicy": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean" },
        "egress": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["cidr", "ports"],
            "properties": {
              "cidr": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+\\.\\d+/\\d+$" },
              "except": {
                "type": "array",
                "items": { "type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+\\.\\d+/\\d+$" }
              },
              "ports": {
                "type": "array",
                "items": {
                  "type": "object",
                  "required": ["port", "protocol"],
                  "properties": {
                    "port": { "type": "integer", "minimum": 1, "maximum": 65535 },
                    "protocol": { "enum": ["TCP", "UDP", "SCTP"] }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### Deep copy и mutation

Функции `merge` и `mergeOverwrite` мутируют первый аргумент. При шаблонизации политик, где значения `values.yaml` используются в нескольких местах, всегда создавайте копию:

```go
{{- $defaultEgress := list }}
{{- $userEgress := .Values.networkPolicy.egress | default list }}
{{- $allEgress := append $defaultEgress $userEgress }}
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

### Egress с разрешением DNS

Критически важный сценарий: разрешение исходящего трафика к внешним сервисам с обязательным доступом к DNS.

```yaml
{{- if .Values.networkPolicy.egress.enabled }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "myapp.fullname" . }}-egress
spec:
  podSelector:
    matchLabels:
      {{- include "myapp.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Egress
  egress:
    # Разрешение DNS (обязательно при Egress-изоляции)
    - to:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: kube-system
        podSelector:
          matchLabels:
            k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Разрешение внешних сервисов
    {{- range .Values.networkPolicy.egress.destinations }}
    - to:
      - ipBlock:
          cidr: {{ .cidr }}
          {{- if .except }}
          except:
            {{- toYaml .except | nindent 12 }}
          {{- end }}
      ports:
        - protocol: {{ .protocol | default "TCP" }}
          port: {{ .port }}
    {{- end }}
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

### Динамические namespace-селекторы

Генерация правил для нескольких разрешенных namespace через `range`:

```yaml
egress:
  {{- range .Values.networkPolicy.allowedNamespaces }}
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: {{ . }}
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

### ResourceQuota enforcement (SRE)

Условное создание ResourceQuota на основе флага окружения. SRE используют это для предотвращения «шумных соседей» (noisy neighbor):

```yaml
{{- if .Values.resourceQuota.enabled }}
apiVersion: v1
kind: ResourceQuota
metadata:
  name: {{ include "myapp.fullname" . }}-quota
spec:
  hard:
    requests.cpu: {{ .Values.resourceQuota.cpu | quote }}
    requests.memory: {{ .Values.resourceQuota.memory | quote }}
    pods: {{ .Values.resourceQuota.maxPods | quote }}
  {{- if .Values.resourceQuota.scopeSelector }}
  scopeSelector:
    {{- toYaml .Values.resourceQuota.scopeSelector | nindent 4 }}
  {{- end }}
{{- end }}
```

### RBAC: условные правила

Добавление правил только при включенном флаге:

```yaml
{{- if .Values.rbac.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "myapp.fullname" . }}
---
{{- if .Values.rbac.createRole }}
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "myapp.fullname" . }}
rules:
  {{- range .Values.rbac.rules }}
  - apiGroups: [{{ .apiGroups | quote }}]
    resources: [{{ .resources | quote }}]
    verbs: [{{ .verbs | quote }}]
    {{- if .resourceNames }}
    resourceNames: [{{ range .resourceNames }}{{ . | quote }},{{ end }}]
    {{- end }}
  {{- end }}
{{- end }}
```

### SecurityContext: условная настройка

Условная настройка `seccompProfile` на основе окружения:

```yaml
{{- if .Values.podSecurityContext.enabled }}
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  {{- if eq $.Values.global.env "prod" }}
  seccompProfile:
    type: RuntimeDefault
  {{- end }}
{{- end }}
```

### Валидация в CI/CD (bash-скрипт)

Интеграция статической валидации NetworkPolicy в pipeline:

```bash
#!/bin/bash
set -euo pipefail

CHART_DIR="./my-chart"
VALUES_FILE="values.yaml"

# 1. Линтинг чарта
helm lint "$CHART_DIR" --strict -f "$VALUES_FILE"

# 2. Рендеринг только NetworkPolicy ресурсов
helm template test-release "$CHART_DIR" -f "$VALUES_FILE" \
  | yq e 'select(.kind == "NetworkPolicy")' - \
  | kubeconform --strict

# 3. Дополнительная валидация через conftest (если установлен)
if command -v conftest &> /dev/null; then
  helm template test-release "$CHART_DIR" -f "$VALUES_FILE" \
    | yq e 'select(.kind == "NetworkPolicy")' - \
    | conftest test -
fi

echo "NetworkPolicy validation passed"
```

### Проверка связности в CI/CD

Скрипт для проверки, что политики не блокируют критичный трафик:

```bash
#!/bin/bash
set -euo pipefail

NS="my-app"
RELEASE="my-release"

# Деплой в тестовый namespace
helm upgrade --install "$RELEASE" ./my-chart -n "$NS" --create-namespace --wait

# Проверка DNS
kubectl exec -n "$NS" deploy/"$RELEASE" -- nslookup kubernetes.default

# Проверка подключения к зависимостям
kubectl exec -n "$NS" deploy/"$RELEASE" -- curl -s --max-time 2 http://database:5432 || true

# Просмотр сгенерированных политик
kubectl get networkpolicy -n "$NS" -o yaml

# Очистка
helm uninstall "$RELEASE" -n "$NS"
```

---

## Дополнительная информация

### Лучшие практики

1. **Имена шаблонов:** Всегда используйте префикс чарта в `define` (например, `myapp.selectorLabels`), чтобы избежать коллизий при использовании чарта как зависимости (Subchart).
2. **Типизация CIDR:** При использовании `ipBlock` передавайте строки в кавычках в `values.yaml`, чтобы избежать интерпретации чисел как других типов.
3. **Автоматические метки:** Используйте метку `kubernetes.io/metadata.name` для `namespaceSelector`, так как она автоматически добавляется в Kubernetes 1.21+.
4. **DNS в Egress:** Всегда добавляйте правило для `kube-dns` при включении Egress-изоляции. Без этого поды не смогут резолвить имена сервисов.
5. **Приоритет AdminNetworkPolicy:** Помните, что глобальные политики администратора (ANP) имеют приоритет над обычными `NetworkPolicy`.
6. **Deep copy при merge:** Используйте `deepCopy` перед `mergeOverwrite`, чтобы не мутировать исходные значения.
7. **Валидация в CI:** Всегда рендерите и валидируйте NetworkPolicy через `kubeconform` или `conftest` перед деплоем.

### Устранение неисправностей

| Ошибка | Вероятная причина | Решение |
|--------|-------------------|---------|
| Политика создана, но не работает | Отсутствует `policyTypes` | Добавить `policyTypes: [Ingress]` и/или `[Egress]` |
| DNS не резолвится после Default Deny | Egress блокирует порт 53 | Добавить Egress-правило для `kube-dns` |
| Connection Timeout между подами | Ingress не разрешает порт | Добавить `ports` в секцию `ingress` |
| Трафик от другого namespace не проходит | Используется только `podSelector` | Добавить `namespaceSelector` |
| Высокий CPU на kube-proxy | Линейный перебор iptables при >1000 правил | Перейти на eBPF-based CNI (Cilium) |
| Связность не восстанавливается | conntrack кэширует старые решения | Очистить conntrack: `conntrack -D -s <pod-ip>` |
| Трафик к Service блокируется | NetworkPolicy работает с IP подов | Использовать `podSelector` вместо `ipBlock` |
| `nil pointer evaluating` в шаблоне | Обращение к полю `nil`-объекта | Проверьте существование родителя через `if` или `with` |
| `invalid value; expecting map` | Передача списка вместо словаря в `toYaml` | Проверьте тип данных в `values.yaml` |
| Условный ресурс не создается | Ложное значение feature flag | Проверьте `values.yaml` и используйте `default false` |

### Отладка и верификация

Для проверки корректности генерации манифестов NetworkPolicy используйте:
- `helm template .` — для просмотра отрендеренных YAML-файлов.
- `helm install --dry-run --debug` — для симуляции установки с проверкой API-версий.
- `kubectl get networkpolicy -n <namespace>` — для проверки наличия объектов в кластере.
- `kubectl describe networkpolicy <name> -n <ns>` — для детального просмотра правил и селекторов.
- `kubectl get pods --show-labels -n <ns>` — для проверки фактических меток подов.

### См. также
- [Именованные шаблоны и хелперы](../_helpers.md) — управление метками и DRY.
- [Обзор сценариев шаблонизации](./overview.md) — каталог практических примеров.
- [NetworkPolicy: Навигатор](../../../../Kubernetes/Networking/Network/network_policy.md) — подробная теория сетевых политик.
