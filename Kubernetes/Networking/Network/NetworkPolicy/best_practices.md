# NetworkPolicy: Лучшие практики

## Определения

**Лучшие практики NetworkPolicy** — экспертные рекомендации по проектированию, внедрению и эксплуатации сетевой изоляции в Kubernetes, направленные на минимизацию рисков безопасности и оптимизацию производительности.

**Zero Trust Architecture (ZTA)** — стратегия безопасности «Никому не доверяй», предполагающая, что каждый сетевой запрос должен быть проверен и разрешен явно, независимо от его источника (внутри или вне периметра).

**AdminNetworkPolicy (ANP) и BaselineAdminNetworkPolicy (BANP)** — современные инструменты иерархического управления сетью. ANP позволяет администраторам задавать обязательные правила (например, запрет доступа к метаданным облака), которые разработчики не могут переопределить в своих NetworkPolicy.

**Lifecycle Management (Управление жизненным циклом)** — стратегия планирования изменений NetworkPolicy на протяжении всего времени жизни кластера: от начального развертывания через постепенное ужесточение до отката при инцидентах. Включает контроль версий, аудит изменений и откат к предыдущему состоянию.

**Namespace Label Hygiene (Гигиена меток пространств имен)** — практика нанесения и поддержки семантически осмысленных меток на пространствах имен для использования в селекторах. Метки должны отражать бизнес-логику (`env: production`, `tier: backend`) и поддерживаться стабильно, без частых переименований.

**Policy-as-Code** — подход к управлению сетевыми политиками, при котором все манифесты хранятся в Git, проходят код-ревью и применяются через автоматизированные пайплайны. Обеспечивает воспроизводимость, аудит изменений и возможность отката.

**Audit Mode (Режим аудита)** — механизм временного мониторинга действия политик без их фактического исполнения. Позволяет оценить影響 применяемых правил перед переводом в режим принуждения (Enforce). Поддерживается部分 CNI (Cilium, Calico).

**Observability (Наблюдаемость)** — способность видеть и анализировать эффект NetworkPolicy в реальном времени: какие пакеты разрешены, какие заблокированы и почему. Включает визуализацию потоков, метрики блокировок и алертинг.

**Phased Rollout (Поэтапное развертывание)** — стратегия внедрения сетевой изоляции постепенно: от мониторинга (Audit) через частичную изоляцию (Ingress-only) к полному Zero Trust (Ingress + Egress). Минимизирует риск нарушения рабочих процессов.

## Базовые Концепции

### Архитектурные принципы

Эффективное управление сетью основано на масштабируемости и наблюдаемости:

*   **Производительность Data Plane:** При большом количестве политик (>1000) стандартные `iptables` страдают от линейного поиска (O(N)), что увеличивает задержки. Рекомендуется использовать CNI на базе **eBPF** (Cilium, Calico eBPF), где поиск правил происходит через хэш-таблицы за константное время (O(1)).
*   **Иерархия ответственности (3-Tier Model):** 
    1.  **Admin Tier (ANP):** Глобальные запреты и разрешения безопасности (Security Team).
    2.  **Developer Tier (NetworkPolicy):** Разрешение доступа между микросервисами (App Team).
    3.  **Baseline Tier (BANP):** Настройки «по умолчанию» (например, Default Deny для всех), если разработчики не создали своих политик.
*   **Декларативное именование:** Названия должны отражать логику: `<действие>-<направление>-<цель>-<назначение>`. Например, `allow-egress-to-rds-production`.

### Технические принципы

*   **Принцип минимальных привилегий:** Открывайте только те порты, которые необходимы. Избегайте разрешений широких диапазонов без необходимости.
*   **Абстракция East-West:** Для трафика внутри кластера **никогда** не используйте `ipBlock`. Поды эфемерны, их IP меняются. Используйте только `podSelector` и `namespaceSelector`.
*   **Именованные порты (Named Ports):** Используйте имена (например, `http-api`) вместо номеров портов (`8080`). Это позволяет изменять порты в контейнерах без обновления манифестов NetworkPolicy.

### Управление жизненным циклом

NetworkPolicy — долгоживущие объекты. Планируйте их изменение на протяжении всего времени жизни кластера:

*   **Версионирование в Git:** Храните все манифесты в репозитории, ведите историю коммитов. Используйте семантическое именование тегов для релизов (например, `netpol-v1.2.0`).
*   **Процесс отката:** При проблемах откатывайте к предыдущей версии манифеста через `kubectl apply -f previous-version.yaml`. Не удаляйте политики вручную — это приводит к瞬間енному раскрытию поверхности.
*   **Очистка устаревших политик:** Регулярно аудитируйте неиспользуемые политики (связанные с удалеными подами/сервисами). Осторожно: политика `podSelector: {}` активна даже при 0 подах.

### Гигиена меток (Label Hygiene)

Метки в `podSelector` и `namespaceSelector` — основа селективности. Их качество определяет надежность политик:

*   **Стабильные имена:** Изменение метки в Pod Spec потребует обновления всех связанных NetworkPolicy. Введите обязательные префиксы для команд: `app.kubernetes.io/name`, `app.kubernetes.io/component`.
*   **Минимальный набор:** Используйте только те метки, которые реально необходимы для фильтрации. Избегайте меток-дубликатов с разными значениями (`team: backend`, `team: backend-v2`).
*   **Namespace Labels:** Начиная с Kubernetes 1.21, каждый namespace автоматически получает метку `kubernetes.io/metadata.name`. Используйте её вместо ручной разметки — это упрощает выборку по имени.
*   **Ревизия меток:** Периодически проверяйте соответствие меток стандартам: `kubectl get ns --show-labels`, `kubectl get pods -A --show-labels | grep <your-label>`.

### Влияние на ресурсы

NetworkPolicy оказывают прямое влияние на производительность кластера:

*   **Память на узле:** Каждое правило consumes память в сетевом стеке узла. При тысячи правил на узле потребление может достигать сотен мегабайт.
*   **Время перезапуска пода:** При большом количестве правил (1000+) увеличивается время пересчета секций iptables/nftables, что задерживает запуск новых подов.
*   **Пропускная способность:** В режиме Default Deny каждое новое соединение требует перебора правил. Для приложений с высокой пропускной способностью используйте CNI с eBPF (O(1) lookup).

## Практические Сценарии

### 1. Реализация Zero Trust (Default Deny)

Начинайте настройку Namespace с политики «запретить всё». Это переводит сетевой стек в режим разрешительных списков.

**Критический нюанс: DNS.** При включении изоляции исходящего трафика (Egress) поды теряют доступ к DNS. Необходимо явно разрешить трафик к `kube-dns` (порт 53 UDP/TCP).

```yaml
# Разрешение DNS для всех подов в Namespace
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-dns
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
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
```

### 2. Фильтрация внешнего трафика (North-South)

Используйте `ipBlock` для ограничения доступа к внешним API или подсетям ЦОД.

**Проблема Source IP:** Чтобы `ipBlock` корректно фильтровал входящий трафик от клиентов, установите `externalTrafficPolicy: Local` в соответствующем Service. Это предотвратит SNAT на узлах и позволит политике увидеть реальный IP клиента.

### 3. Защита от SSRF (Server-Side Request Forgery)

Блокируйте доступ к чувствительным эндпоинтам облачных провайдеров (AWS, GCP, Azure), чтобы предотвратить кражу IAM-ролей. Лучше всего это делать через **AdminNetworkPolicy** на уровне кластера.

```yaml
# Пример блокировки Cloud Metadata API через NetworkPolicy
egress:
- to:
  - ipBlock:
      cidr: 0.0.0.0/0
      except:
      - 169.254.169.254/32
```

### 4. Поддержка IPv6 и Dual-stack

Если кластер использует IPv6, убедитесь, что ваши политики включают соответствующие блоки. CNI-плагины могут обрабатывать IPv6 по-разному. Рекомендуется явно указывать оба типа адресов в `ipBlock`, если это необходимо.

### 5. Шаблонизация через Helm

Для управления NetworkPolicy в масштабе используйте Helm-шаблоны с параметризацией. Это позволяет генерировать манифесты для разных окружений (dev, staging, prod) из одного источника.

```yaml
# templates/networkpolicy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ .Values.appName }}-default-deny
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app: {{ .Values.appName }}
  policyTypes:
  - Ingress
  - Egress
  egress:
  {{- range .Values.allowedEgress }}
  - to:
    - ipBlock:
        cidr: {{ . }}
  {{- end }}
```

```yaml
# values.yaml для dev
appName: api-server
allowedEgress:
  - "0.0.0.0/0"      # разрешить все

# values.yaml для prod
appName: api-server
allowedEgress:
  - "10.0.0.0/8"     # только внутренняя сеть
  - "172.16.0.0/12"
```

### 6. Поэтапное развертывание (Phased Rollout)

Стратегия безопасного внедрения изоляции в production:

**Этап 1: Audit Mode (мониторинг)**
Включите CNI в режим аудита (Cilium: `policyAuditMode: true`), чтобы видеть, какие соединения были бы заблокированы, без фактического разрыва. Анализируйте логи 1-2 недели.

**Этап 2: Ingress-only Isolation**
Примените Default Deny только для входящего трафика. Egress оставьте открытым. Это безопасно: поды могут инициировать соединения, но новые входящие — только по правилам.

**Этап 3: Ingress + Egress Isolation**
Добавьте Egress-изоляцию с явным разрешением DNS и необходимых внешних сервисов. Протестируйте каждую группу подов отдельно.

**Этап 4: ANP + BANP**
Настройте глобальные правила через AdminNetworkPolicy (Tier 1) и дефолтные разрешения через BANP (Tier 3). Полная 3-Tier модель.

### 7. Тестирование политик перед применением

NetworkPolicy не логируют по умолчанию. Используйте следующие методы для проверки:

```bash
# 1. Проверка доступа из пода
kubectl exec -it <pod> -- curl -v <service>:<port>

# 2. Проверка с помощью temporary debug pod
kubectl debug -it <pod> --image=nicolaka/netshoot -- curl -v <target>

# 3. Проверка через kubectl auth (для RBAC, не для NetworkPolicy)
kubectl auth can-i create pods --namespace=production

# 4. Визуализация правил (Cilium)
cilium policy get <policy-name>
cilium policy trace -s <source-pod> -d <dest-pod>

# 5. Проверка через dnslookup (проверка DNS-связности)
kubectl exec -it <pod> -- nslookup <service>.<namespace>.svc.cluster.local
```

### 8. GitOps Workflow для NetworkPolicy

Полный пайплайн управления политиками через Git:

```bash
# Структура репозитория
network-policies/
├── base/
│   ├── default-deny.yaml
│   └── allow-dns.yaml
├── overlays/
│   ├── dev/
│   │   ├── kustomization.yaml
│   │   └── allow-all.yaml
│   ├── staging/
│   │   └── kustomization.yaml
│   └── prod/
│       └── kustomization.yaml
└── tests/
    ├── policy_test.rego      # Open Policy Agent (OPA) / Conftest
    └── schema_check.yaml

# Проверка перед коммитом
conftest test network-policies/base/ --policy tests/policy_test.rego
```

```rego
# policy_test.rego — пример теста: каждая политика должна иметь policyTypes
package main

deny[msg] {
  input.kind == "NetworkPolicy"
  not input.spec.policyTypes
  msg := sprintf("NetworkPolicy %s не имеет policyTypes", [input.metadata.name])
}
```

## Дополнительные Сведения

### Отладка и аудит (Troubleshooting)

Стандартный Kubernetes не логирует заблокированные пакеты. Для диагностики используйте специализированные инструменты:

*   **Cilium Hubble:** `hubble observe --type drop` — показывает, какая именно политика и почему отбросила пакет. Идеально для визуализации East-West трафика.
*   **Calico Cloud/Enterprise:** Предоставляет расширенный аудит и симуляцию политик (Policy Staging).
*   **kubectl debug:** Запуск временного контейнера с инструментами (`curl`, `dig`, `nc`) внутри пода для проверки связности.
*   **Network Policy Editor:** Используйте онлайн-визуализаторы (например, `editor.networkpolicy.io`) для проверки логики сложных правил перед применением.

### Решение типичных проблем

| Симптом | Вероятная причина | Решение |
|:---|:---|:---|
| `connection refused` между подами | Ingress-политика не разрешает порт | Добавить `ports: [{port: <номер>}]` в `ingress` |
| DNS-имена не резолвятся | Egress блокирует порт 53 | Разрешить трафик к `kube-dns` в `egress` |
| Под не может выйти в интернет | Egress Default Deny без разрешающих правил | Добавить правила Egress для необходимых CIDR/сервисов |
| Политика создана, но не действует | Отсутствует `policyTypes` | Добавить `policyTypes: [Ingress]` и/или `[Egress]` |
| Трафик от другого namespace не проходит | В `from` указан только `podSelector` | Добавить `namespaceSelector` |
| Правила работают нестабильно | Используются IP подов вместо селекторов | Заменить `ipBlock` на `podSelector` + `namespaceSelector` |

### Рекомендации по оптимизации и эксплуатации

*   **Группировка правил:** Если несколько сервисов требуют одинаковых прав доступа, объедините их общими метками (Labels).
*   **GitOps Workflow:** Изменения в сетевых политиках должны проходить через Code Review и автоматические тесты (например, с использованием `conftest` или `polaris`).
*   **Автоматизация:** Используйте инструменты генерации политик на основе реального трафика (Cilium Hubble, Otterize), чтобы избежать ошибок при ручном написании.
*   **Мониторинг:** Настройте алерты на количество заблокированных пакетов через Prometheus + Grafana. Резкий рост блокировок может указывать на неправильную политику или атаку.
*   **Откат:** При проблемах быстро откатывайте к предыдущей версии манифеста через `kubectl apply`. Не удаляйте политики вручную — это может привести к раскрытию поверхности.

### Критерии выбора CNI для NetworkPolicy

| Критерий | Calico | Cilium | Antrea |
|:---|:---|:---|:---|
| eBPF Data Plane | Да (опционально) | Да (по умолчанию) | Нет (Open vSwitch) |
| L7-политики | Ограниченные | Полные (HTTP, gRPC) | Нет |
| FQDN Egress | Нет | Да (DNS-based) | Нет |
| Hubble/Tetragon | Нет | Да (встроенная наблюдаемость) | Нет |
| Audit Mode | Да (как GlobalNetworkPolicy) | Да (`policyAuditMode`) | Да |
| Производительность при >1000 правил | Средняя (iptables) / Высокая (eBPF) | Высокая (eBPF) | Средняя (OVS) |
| Интеграция с OPA/Gatekeeper | Да | Да | Да |

### NetworkPolicy и Pod Security Standards (PSS/PSA)

Pod Security Admission (PSA) работает на уровне подов, а NetworkPolicy — на уровне сети. Эти механизмы дополняют друг друга:

| PSS уровень | Ограничения | Влияние на NetworkPolicy |
| :--- | :--- | :--- |
| **privileged** | Нет ограничений | hostNetwork поды НЕ фильтруются NetworkPolicy |
| **baseline** | Запрет特权 конфигураций | Стандартные поды фильтруются NetworkPolicy |
| **restricted** | Строгие ограничения | Рекомендуется комбинировать с NetworkPolicy |

**Рекомендация:** Используйте `restricted` PSA + Default Deny NetworkPolicy для максимальной безопасности.

### NetworkPolicy в Helm Charts

При шаблонизации NetworkPolicy в Helm избегайте дублирования:

```yaml
# templates/networkpolicy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ .Release.Name }}-default-deny
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app: {{ .Values.app.name }}
  policyTypes:
  - Ingress
  - Egress
  egress:
  {{- toYaml .Values.networkPolicy.egress | nindent 2 }}
```

```yaml
# values.yaml
networkPolicy:
  egress:
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### NetworkPolicy для Admission Webhooks

Admission Webhooks (Kyverno, Gatekeeper, OPA) требуют явного разрешения сетевого доступа:

```yaml
# Разрешить входящий трафик к webhook от API Server
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-webhook-ingress
  namespace: kyverno
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: kyverno
  policyTypes:
  - Ingress
  ingress:
  # от API Server (master-узлы)
  - from:
    - ipBlock:
        cidr: 10.0.0.0/8  # CIDR master-узлов
    ports:
    - protocol: TCP
      port: 9443  # webhook порт
  # от подов (validate webhook)
  - from:
    - namespaceSelector: {}
    ports:
    - protocol: TCP
      port: 9443
```

**Типичные порты webhook'ов:**
| Компонент | Порт | Описание |
| :--- | :--- | :--- |
| Kyverno | 9443 | Validating/Mutating webhook |
| Gatekeeper | 8443 | Validating webhook |
| OPA Gatekeeper | 8443 | Validating webhook |
| cert-manager | 8089 | Webhook server |

### См. также

* [NetworkPolicy: Определения и концепции](./definitions.md) — базовые термины и иерархия ANP/BANP.
* [NetworkPolicy: Логика правил](./rule_logic.md) — детальный разбор логики И/ИЛИ и аддитивности.
* [NetworkPolicy: Control Plane](./control_plane_network_policy.md) — изоляция control plane.
* [NetworkPolicy: DNS](./dns_network_policy.md) — DNS-политики и NodeLocal DNSCache.
* [Cilium: Высокопроизводительный CNI](../CNI/cilium.md) — реализация eBPF и Hubble для глубокой наблюдаемости.
