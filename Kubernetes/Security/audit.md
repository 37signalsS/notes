# Аудит в Kubernetes

## Определения

**Аудит (Auditing)** — механизм Kubernetes, предоставляющий набор записей, которые документируют последовательность действий в кластере. Аудит позволяет ответить на вопросы: что произошло, кто это сделал, когда и с какого устройства.

**Audit ID** — уникальный идентификатор, присваиваемый каждому HTTP-запросу к API-серверу. Он записывается в заголовок ответа `Audit-ID` и во все записи аудита, связанные с этим запросом, что позволяет коррелировать события.

**Политика аудита (Audit Policy)** — файл в формате YAML/JSON, определяющий правила логирования: какие этапы запроса записывать, на каком уровне детализации и для каких ресурсов/субъектов. Поддерживаются версии схемы `audit.k8s.io/v1`.

**Запись аудита (Audit Event)** — структурированный объект в формате JSON, содержащий метаданные запроса, данные пользователя, параметры запроса и ответа.

**Журнал аудита (Audit Log)** — набор записей аудита, выгруженных во внешнее хранилище (файл, SIEM, Loki) для долгосрочного хранения и анализа.

---

## Основные концепции

### Этапы аудита (Audit Stages)

Каждый запрос проходит через несколько этапов, на каждом из которых может быть создана запись в журнале:

- **RequestReceived:** этап получения запроса обработчиком (до передачи в цепочку фильтров).
- **ResponseStarted:** отправка заголовков ответа, но до отправки тела (используется для длительных запросов, например, `watch`).
- **ResponseComplete:** этап завершения отправки тела ответа. Самый информативный этап.
- **Panic:** возникает при критической ошибке (panic) во время обработки запроса.

### Уровни аудита (Audit Levels)

Определяют объем записываемых данных:

- **None:** событие не записывается (используется для исключения шумных системных запросов).
- **Metadata:** записываются только метаданные (пользователь, время, ресурс, метод), но не тело запроса/ответа. Рекомендуется для высоконагруженных ресурсов.
- **Request:** записываются метаданные и тело запроса.
- **RequestResponse:** записываются метаданные, тело запроса и тело ответа.
    - **Внимание:** Не рекомендуется использовать этот уровень для ресурсов `Secrets` и `ConfigMaps`, так как это приведет к утечке конфиденциальных данных в логи в открытом виде. Детальная настройка для секретов приведена в разделе [Аудит Secrets](../Base/secrets/security.md).

### Бэкенды аудита (Audit Backends)

Kubernetes поддерживает три основных способа хранения и передачи логов:

1.  **Log Backend:** Запись событий в локальные файлы в формате JSONlines.
    - Флаги: `--audit-log-path`, `--audit-log-maxsize` (размер файла), `--audit-log-maxbackup` (количество ротаций), `--audit-log-maxage` (срок хранения в днях), `--audit-log-format` (`json` или `text`), `--audit-log-truncate-*` (ограничение размера записей).
2.  **Webhook Backend:** Отправка событий во внешние системы (SIEM, Logstash, Fluentd) по протоколу HTTP.
    - Флаг: `--audit-webhook-config-file`.
    - Конфигурационный файл использует формат kubeconfig и содержит endpoint вебхука, TLS-настройки и параметры аутентификации.
3.  **BatchWebhook Backend:** Пакетная отправка событий через вебхук с буферизацией и настраиваемыми лимитами.
    - Дополнительные флаги: `--audit-log-batch-max-*` (максимальный размер/время/записи в пакете), `--audit-log-batch-wait` (максимальное время ожидания заполнения пакета).

### Схема события аудита (Audit Event Schema)

Каждая запись аудита соответствует схеме `audit.k8s.io/v1` и содержит следующие поля:

```json
{
  "kind": "Event",
  "apiVersion": "audit.k8s.io/v1",
  "level": "RequestResponse",
  "auditID": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "stage": "ResponseComplete",
  "requestURI": "/api/v1/namespaces/prod/pods",
  "verb": "list",
  "user": {
    "username": "system:serviceaccount:argo-cd:argocd-application-controller",
    "uid": "uid-12345",
    "groups": ["system:serviceaccounts", "system:serviceaccounts:argo-cd"]
  },
  "sourceIPs": ["10.0.1.50"],
  "userAgent": "kubectl/v1.31.0",
  "objectRef": {
    "resource": "pods",
    "namespace": "prod",
    "name": "payment-service-abc123",
    "apiGroup": "",
    "apiVersion": "v1"
  },
  "responseStatus": {
    "code": 200,
    "message": "OK"
  },
  "requestObject": { /* тело запроса (для уровней Request/RequestResponse) */ },
  "responseObject": { /* тело ответа (только для RequestResponse) */ },
  "requestReceivedTimestamp": "2026-08-30T10:00:00.000000Z",
  "stageTimestamp": "2026-08-30T10:00:01.500000Z",
  "annotations": {
    "authorization.k8s.io/decision": "allow",
    "authorization.k8s.io/reason": "RBAC: allowed by RoleBinding 'edit-binding'"
  }
}
```

**Важные поля:**
- `level` — определенный политикой уровень детализации.
- `stageTimestamp` — время фиксации события (может отличаться от времени обработки из-за часовых поясов узлов).
- `annotations` — дополнительные данные от admission-вебхуков и авторизатора (RBAC decision, reason).
- `requestReceivedTimestamp` — фиксируется на этапе `RequestReceived`; если в политике указано `omitStages: ["RequestReceived"]`, это поле будет пустым, но запись сохранится на последующих этапах.

### Взаимодействие с admission-цепочкой

Аудит происходит **после** завершения всех admission-вебхуков (включая mutating и validating), но **до** сохранения объекта в etcd. Это означает:
- В `requestObject` уже присутствуют изменения, внесенные mutating-вебхуками.
- В `annotations` попадают решения validating-вебхуков (`authorization.k8s.io/decision`, `authorization.k8s.io/reason`).
- Если вебхук ответил ошибкой или таймаутом, запись аудита может не создаться (зависит от `failurePolicy` вебхука).

### Ограничения аудита

- **Прямой доступ к etcd:** Аудит фиксирует только запросы к API-серверу. Прямые обращения к etcd (например, через `etcdctl`) не проходят через аудит. Для их отслеживания используется RBAC на уровне etcd и сетевая изоляция (см. [Безопасность etcd](../Concepts/etcd_alternatives_and_security.md)).
- **Производительность:** Уровень `RequestResponse` для часто изменяемых ресурсов (Endpoints, Events) создает значительную нагрузку на память API-сервера и пропускную способность диска/сети.
- **Clock Skew:** При корреляции событий между API-сервером, узлами и внешними системами необходимо синхронизировать часы по NTP/PTP. Расхождения больше секунды делают хронологию ненадежной.
- **Retention в кластере:** Логи audit log backend ротируются и удаляются с узлов. Для долгосрочного хранения (>30 дней) требуется экспорт во внешнее хранилище.

---

## Практические сценарии

### Настройка бэкенда через kube-apiserver

Для включения аудита необходимо добавить флаги запуска API-сервера (обычно в `/etc/kubernetes/manifests/kube-apiserver.yaml` для кластеров, созданных через `kubeadm`):

```yaml
# /etc/kubernetes/manifests/kube-apiserver.yaml (фрагмент)
spec:
  containers:
  - command:
    - kube-apiserver
    - --audit-policy-file=/etc/kubernetes/audit-policy.yaml
    - --audit-log-path=/var/log/kubernetes/audit.log
    - --audit-log-format=json
    - --audit-log-maxsize=100
    - --audit-log-maxbackup=10
    - --audit-log-maxage=30
    volumeMounts:
    - mountPath: /etc/kubernetes/audit-policy.yaml
      name: audit-policy
      readOnly: true
    - mountPath: /var/log/kubernetes
      name: audit-log
  volumes:
  - hostPath:
      path: /etc/kubernetes/audit-policy.yaml
      type: File
    name: audit-policy
  - hostPath:
      path: /var/log/kubernetes
      type: DirectoryOrCreate
    name: audit-log
```

Для систем на systemd (не-static pod), флаги указываются в сервисе `kube-apiserver.service` или в конфигурационном файле (например, `/etc/kubernetes/kube-apiserver.yaml` для Kubelet-managed компонентов).

### Настройка Webhook Backend

Для отправки аудита во внешнюю SIEM-систему создайте kubeconfig-подобный файл и укажите его в флаге `--audit-webhook-config-file`:

```yaml
# /etc/kubernetes/audit/webhook-config.yaml
apiVersion: v1
kind: Config
clusters:
- name: audit-sink
  cluster:
    server: "https://siem.internal.example.com/kubernetes-audit"
    certificate-authority: "/etc/kubernetes/pki/siem-ca.crt"
users:
- name: audit-sink
  user:
    client-certificate: "/etc/kubernetes/pki/audit-client.crt"
    client-key: "/etc/kubernetes/pki/audit-client.key"
current-context: audit-sink
contexts:
- context:
    cluster: audit-sink
    user: audit-sink
    namespace: default
  name: audit-sink
```

Флаги для активации:
```bash
--audit-webhook-config-file=/etc/kubernetes/audit/webhook-config.yaml
--audit-webhook-mode=batch        # blocking или batch; batch позволяет API-серверу не ждать ответа вебхука
--audit-webhook-batch-max-wait=5s # максимальное время ожидания пакета
--audit-webhook-batch-max-size=4096 # максимальный размер пакета в записях
```

**Режимы:**
- `blocking`: API-сервер ожидает ответ вебхука перед завершением запроса. Гарантирует доставку, но добавляет задержку.
- `batch`: API-сервер собирает пакеты и отправляет их асинхронно. Минимальное влияние на latency, но возможна потеря записей при перезагрузке API-сервера.

### Рекомендованная политика аудита (2024-2025)

Пример политики, балансирующей безопасность и производительность.

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
# Пропускать этап RequestReceived для всех правил, чтобы уменьшить объем логов
omitStages:
  - "RequestReceived"
rules:
  # 1. Исключить шумные запросы от системных компонентов
  - level: None
    users: ["system:kube-proxy", "system:kube-scheduler", "system:apiserver"]
    verbs: ["get", "list", "watch"]

  # 2. Логировать секреты только на уровне Metadata (Безопасность)
  - level: Metadata
    resources:
      - group: ""
        resources: ["secrets", "configmaps", "serviceaccounts"]

  # 3. Детально логировать изменения критических ресурсов
  - level: RequestResponse
    verbs: ["create", "update", "patch", "delete"]
    resources:
      - group: ""
        resources: ["pods", "services", "endpoints"]
      - group: "rbac.authorization.k8s.io"
        resources: ["roles", "rolebindings", "clusterroles", "clusterrolebindings"]

  # 4. Логировать все остальное на уровне Metadata (По умолчанию)
  - level: Metadata
```

### Валидация работы аудита

После применения конфигурации и перезапуска kube-apiserver проверьте, что записи появляются в журнале:

```bash
# Для Log Backend
tail -n 1 /var/log/kubernetes/audit.log | jq '{verb, user: .user.username, obj: .objectRef.name, stage: .stage}'
# → ожидаемый результат: объект с verb, user, obj и stage

# Для Webhook Backend — проверьте логи целевого SIEM/вебхука на наличие POST-запросов
# Если используется batch-режим, первые записи могут появиться с задержкой до audit-webhook-batch-max-wait

# Проверка флагов API-сервера
ps aux | grep kube-apiserver | grep audit
# → должны отображаться все --audit-* флаги
```

Для проверки корреляции по Audit ID выполните тестовый запрос и найдите его ID:

```bash
# Создать под и получить Audit ID из ответа
kubectl run test-pod --image=nginx --restart=Never -n default --dry-run=server -o yaml | grep -i audit-id
# Или через curl к API напрямую:
curl -k -H "Authorization: Bearer $TOKEN" https://k8s-api:6443/api/v1/namespaces/default/pods -v 2>&1 | grep -i "audit-id"
```

### Анализ логов: команды и фильтры

Распространенные сценарии анализа audit.log через `jq`:

```bash
# Все операции создания/удаления подов
jq 'select(.verb == "create" or .verb == "delete") | select(.objectRef.resource == "pods") | {time: .stageTimestamp, user: .user.username, verb, pod: .objectRef.name}' /var/log/kubernetes/audit.log

# Операции изменения RBAC
jq 'select(.verb in ["create", "patch", "delete"]) | select(.objectRef.group == "rbac.authorization.k8s.io") | {time: .stageTimestamp, user: .user.username, verb, resource: .objectRef.resource, name: .objectRef.name}' /var/log/kubernetes/audit.log

# Поиск по Audit ID (корреляция)
jq 'select(.auditID == "a1b2c3d4-e5f6-7890-abcd-ef1234567890")' /var/log/kubernetes/audit.log

# Аудит действий конкретного пользователя
jq 'select(.user.username == "dev-user-01") | {time: .stageTimestamp, verb, resource: .objectRef.resource, name: .objectRef.name, sourceIP: .sourceIPs[0]}' /var/log/kubernetes/audit.log

# Обнаружение kubectl exec (подозрительная активность)
jq 'select(.verb == "create" and .objectRef.subResource == "exec") | {time: .stageTimestamp, user: .user.username, pod: .objectRef.name, container: .requestObject.container.name}' /var/log/kubernetes/audit.log

# Отсеивание системных аккаунтов
jq 'select(.user.username | startswith("system:") | not)' /var/log/kubernetes/audit.log
```

### Мониторинг и алертинг

API-сервер экспортирует метрики аудита в формате Prometheus. Ключевые метрики:

- `apiserver_audit_requests_total` — общее количество записей аудита по уровню (`level="Metadata"`, `level="Request"`, `level="RequestResponse"`).
- `apiserver_audit_responses_total` — распределение ответов по кодам HTTP.
- `apiserver_audit_truncated_total` — количество записей, усеченных из-за превышения лимитов (`--audit-log-truncate-*`).

Пример алертов (Prometheus Rule):

```yaml
groups:
- name: k8s-audit-alerts
  rules:
  - alert: AuditLogTruncation
    expr: increase(apiserver_audit_truncated_total[5m]) > 0
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "Записи аудита усекаются (truncated)"
      description: "API-сервер обрезает тела запросов/ответов. Проверьте флаги --audit-log-truncate-* и производительность диска."

  - alert: AuditLogBackendDown
    expr: increase(apiserver_audit_requests_total[5m]) == 0 and rate(apiserver_request_total[5m]) > 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Audit backend не получает записи"
      description: "Запросов к API есть, но audit-записей нет. Проверьте --audit-log-path, место на диске или доступность вебхука."

  - alert: HighAuditLevelRequestResponse
    expr: rate(apiserver_audit_requests_total{level="RequestResponse"}[5m]) > 1000
    for: 10m
    labels:
      severity: info
    annotations:
      summary: "Высокий объем RequestResponse-записей"
      description: "Уровень RequestResponse генерирует >1000 записей/сек. Рассмотрите переход на Metadata для read-only операций."
```

### Интеграция с пайплайном сбора логов

Для экспорта audit.log в централизованное хранилище используйте:

**Fluent Bit:**
```yaml
# /etc/fluent-bit/parsers.conf
[PARSER]
    Name   k8s-audit
    Format json
    Time_Key stageTimestamp
    Time_Format %Y-%m-%dT%H:%M:%S%.NZ

# /etc/fluent-bit/fluent-bit.conf (фрагмент)
[INPUT]
    Name   tail
    Path   /var/log/kubernetes/audit.log
    Parser k8s-audit
    Tag    k8s.audit
    Read_From_Head true

[OUTPUT]
    Name   loki
    Match  k8s.audit
    Host   loki.internal.example.com
    Port   3100
    Labels job=k8s-audit,cluster=prod-eu-central
```

**Vector:**
```yaml
# vector.yaml (фрагмент)
sources:
  k8s_audit:
    type: file
    include:
      - /var/log/kubernetes/audit.log
    read_from: beginning
    parsing:
      type: json

sinks:
  loki_audit:
    type: loki
    inputs: ["k8s_audit"]
    endpoint: http://loki.internal.example.com:3100
    labels:
      job: k8s_audit
      cluster: prod-eu-central
```

### Сочетание инструментов (Defense in Depth)

Для комплексной защиты рекомендуется использовать иерархический подход, охватывающий все этапы жизненного цикла:
1.  **[IaC Security](../../CI-CD/DevSecOps/iac-security-defense-in-depth.md):** Превентивные проверки на этапе написания кода и CI/CD (Checkov, OPA).
2.  **Kubernetes Audit:** Фиксирует взаимодействие с API-сервером ("Кто вызвал API?").
3.  **[Falco](../../Security/Tools/falco.md):** Мониторинг системных вызовов внутри контейнеров в runtime ("Что произошло внутри системы?").
4.  **[Linux Auditd](../../Linux/SystemAdministration/Logging/auditd.md):** Аудит действий на уровне хостовой ОС (доступ к конфигурационным файлам `/etc/kubernetes`).
5.  **[Журналы аудита и трассируемость в GitOps](../GitOps/Concepts/audit_logs.md):** Корреляция событий API-сервера с действиями GitOps-контроллеров и Git-историей.

### Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Записи в audit.log не появляются | Политика не смонтирована или флаги не переданы API-серверу | Проверить `ps aux | grep kube-apiserver`, наличие флага `--audit-policy-file`, права на файл политики |
| Записи пишутся с задержкой или теряются при пиках | File backend буферизует и режет события при переполнении (`--audit-log-truncate-*`, медленный диск) | Мониторить метрики `apiserver_audit_*`; вынести журнал на отдельный быстрый том; при высоких требованиях — webhook backend |
| Записи о чтении секретов отсутствуют | Правило аудита не покрывает `get secrets` или стоит правило более низкого уровня выше нужного | Пересмотреть порядок правил политики: правила применяются сверху вниз |
| Webhook backend не принимает события | TLS-ошибка, недоступность endpoint, неверный формат конфига | Проверить доступность endpoint (`curl -k ...`), логи вебхука, валидность сертификатов в конфиге |
| Объем логов превышает возможности диска | Слишком высокий уровень детализации или отсутствие ротации | Увеличить `--audit-log-maxage`/`--audit-log-maxsize`, перейти на Metadata для read-only операций, добавить экспорт во внешнее хранилище |
| Часовые метки не сходятся между источниками | Clock skew на узлах кластера | Проверить синхронизацию NTP/chrony на всех control-plane и worker-нодах |
| Записи дублируются | На kube-apiserver запущено несколько инстансов с общим томом для логов (HA) без разделения путей | Убедиться, что каждый инстанс API-сервера пишет в уникальный путь или использует совместно доступный внешний бэкенд |

---

## Дополнительная информация

### Лучшие практики

- **Изоляция логов:** Отправляйте логи аудита во внешнее хранилище (SIEM, S3 с Object Lock) в режиме реального времени. Это предотвратит их удаление злоумышленником после компрометации кластера.
- **Шифрование в покое:** На уровне ОС применяйте шифрование диска (`dm-crypt`/LUKS) к разделу, где хранятся аудит-логи. На уровне кластера — encrypt-at-rest для etcd и внешнего хранилища.
- **RBAC на доступ к логам:** Доступ к файлам `/var/log/kubernetes/audit.log` и конфигурации audit policy должен быть ограничен группе `audit-readers` (SSoT-роль для SRE). Доступ по принципу least privilege: только чтение, без права записи или удаления.
- **Производительность:** Избегайте уровня `RequestResponse` для операций `list` и `watch` на часто меняющихся ресурсах (например, `Endpoints`), чтобы не перегружать память API-сервера.
- **Мониторинг аномалий:** Настройте алертинг на специфические события, такие как `kubectl exec` в поды продуктового окружения или изменение RBAC-группы `system:masters`. См. также [Реагирование на инциденты безопасности](./incident_response.md) — полные сценарии обнаружения и реагирования на инциденты через Audit Log.
- **CIS Benchmarks:** Используйте **[kube-bench](./kube-bench.md)** для проверки соответствия настроек аудита стандартам безопасности CIS.
- **Синхронизация времени:** Обязательно используйте NTP (chrony/systemd-timesyncd) на всех узлах. Для корреляции в forensic-расследованиях предпочтительна микросекундная точность (PTP в финансовых контурах).

### Compliance-соответствие

Аудит в Kubernetes является ключевым контролем для удовлетворения требований регуляторов:
- **PCI DSS v4.0.1:** Требование 10.2.1.7 — логирование всех действий с карточными данными, включая создание и чтение ресурсов `secrets`. Ротация не менее 90 дней, горячий доступ к 3 месяцам.
- **ISO/IEC 27001:2022:** Контроль A.8.15 (Logging) — необходимость фиксации событий доступа, ошибок и отказов с защитой целостности и конфиденциальности логов.
- **SOC 2:** Критерий CC7.2 — мониторинг компонентов на предмет неавторизованных изменений; журналы аудита служат доказательством (evidence).
- **152-ФЗ:** Логирование доступа к ПДн и действий администраторов.

Общие принципы комплаенса подробно описаны в разделе [Аудит и комплаенс: Обзор](../../Security/audit_and_compliance_overview.md).

### Связанные темы

- [Обзор RBAC](./rbac/rbac_overview.md) — управление доступом, который проверяется аудитом.
- [Аудит и трассируемость в GitOps](../GitOps/Concepts/audit_logs.md) — долгосрочное хранение и корреляция с Flux/Argo CD.
- [Аудит и комплаенс: Обзор](../../Security/audit_and_compliance_overview.md) — общие принципы комплаенса и стандарты.
