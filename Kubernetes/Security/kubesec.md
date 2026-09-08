# Kubesec: Анализ рисков и сканер безопасности в Kubernetes

## Определения

**Kubesec** — это инструмент с открытым исходным кодом для статического анализа безопасности (SAST) манифестов Kubernetes (YAML). Он оценивает риски конфигурации и выставляет числовую оценку (score) на основе соответствия лучшим практикам безопасности ControlPlane и CIS Benchmark.

* **Shift-Left Security:** Стратегия переноса проверок безопасности на максимально ранние этапы разработки (IDE, CI/CD), позволяющая выявлять ошибки конфигурации до момента их развертывания.
* **Score (Оценка):** Агрегированный показатель безопасности. Отрицательный итоговый балл сигнализирует о наличии критических уязвимостей, блокирующих использование манифеста в production.
* **Remediation (Исправление):** Процесс изменения конфигурации для устранения выявленных рисков и повышения итоговой оценки.

**Важно:** Kubesec фокусируется на логике безопасности (Security Context, Capabilities). Для проверки синтаксиса и соответствия схемам API он интегрируется с [Kubeconform](../ToolsUtilities/kubeconform_overview.md). Для аудита инфраструктуры Control Plane используйте [kube-bench](./kube-bench.md). Для мультидисциплинарного сканирования (cluster + image + фреймворки CIS/NSA) — [Kubescape](./kubescape_overview.md) (другой инструмент, не путать с Kubesec).

---

## Основные концепции

### Принцип работы и архитектура движка оценки

Kubesec разбирает YAML-манифесты в абстрактное синтаксическое дерево (AST), извлекает объекты безопасности (`securityContext`, `capabilities`, `privileged`) и применяет набор взвешенных правил. Каждое правило имеет три состояния:

| Состояние | Описание | Влияние на Score |
| :--- | :--- | :--- |
| **pass** | Установлен безопасный параметр или явно сброшена опасная capability. | +баллы |
| **fail** | Присутствует небезопасная конфигурация (например, `privileged: true`). | -баллы |
| **skip** | Правило неприменимо к данному ресурсу (например, отсутствие `volumes` при проверке `hostPath`). | 0 |

Итоговый score вычисляется как сумма взвешенных значений всех правил. Пороговое значение для блокировки по умолчанию — **0**: манифесты с отрицательным score блокируются Admission Controller.

### Область анализа

Проверка Pod, Deployment, Service, DaemonSet, StatefulSet, CronJob, а также `initContainers` и `volumeClaimTemplates`.

### Vigilant Mode (Бдительный режим)

Режим строгой проверки, требующий явного определения всех параметров безопасности (например, обязательный `readOnlyRootFilesystem`). В этом режиме отсутствие безопасного параметра трактуется как нарушение, а не как нейтральное значение.

### Поддержка CRD и схем

Kubesec v2+ может проверять структуру Custom Resources. Для этого используются переменные окружения `K8S_SCHEMA_VER` и `SCHEMA_LOCATION`.

### Режимы работы

1.  **CLI:** Локальное сканирование файлов или потока `stdin`.
2.  **HTTP Server:** Запуск в режиме `serve` для создания внутреннего микросервиса безопасности.
3.  **Admission Controller:** Блокировка деплоя небезопасных ресурсов на уровне API-сервера Kubernetes.
4.  **Kubesec-as-a-Service:** Использование публичного API (`v2.kubesec.io/scan`) для быстрой проверки без установки инструмента.

### Формат вывода и интерпретация

При сканировании Kubesec возвращает JSON-массив, где каждый элемент соответствует одному проверенному ресурсу:

```json
[
  {
    "object": "Deployment/my-app",
    "valid": true,
    "score": 10,
    "scoring": {
      "pass": [
        { "id": "readOnlyRootFilesystem", "reason": "Container has a read-only root filesystem" },
        { "id": "runAsNonRoot", "reason": "Container runs as non-root user" }
      ],
      "fail": [],
      "skip": [{ "id": "capabilities", "reason": "Resource does not define capabilities" }]
    }
  }
]
```

| Поле | Тип | Описание |
| :--- | :--- | :--- |
| `object` | string | Имя и тип ресурса Kubernetes. |
| `valid` | boolean | `true`, если score >= 0 и критических нарушений нет. |
| `score` | integer | Итоговый балл безопасности. |
| `scoring.pass` | array | Список пройденных проверок с пояснениями. |
| `scoring.fail` | array | Список проваленных проверок с пояснениями. |
| `scoring.skip` | array | Правила, не применимые к данному ресурсу. |

Для извлечения score в скриптах:

```bash
kubesec scan deployment.yaml --output=json | jq '.[0].score'
```

### Система оценки и правила

Kubesec начисляет баллы за "хорошие" практики и вычитает за "опасные". Детальные настройки описаны в **[Security Context в Kubernetes](./pod_security_context.md)**.

| Правило | Описание | Баллы |
| :--- | :--- | :--- |
| **Privileged** | Контейнер запущен с флагом `privileged: true`. | **-30** |
| **HostNetwork/IPC/PID** | Использование пространств имен хоста (риск выхода на хост). | **-10** |
| **ReadOnlyRootFilesystem** | Файловая система контейнера доступна только для чтения. | **+30** |
| **RunAsNonRoot** | Запрет запуска процесса от пользователя root. | **+10** |
| **Capabilities** | Наличие опасных Linux capabilities (например, `CAP_SYS_ADMIN`). | **-10** |
| **AllowPrivilegeEscalation** | Разрешение процессу повышать свои привилегии. | **-10** |

### Взаимодействие с Pod Security Admission (PSA)

Kubesec дополняет, но не заменяет PSA/PSS. PSA работает на уровне Namespace и блокирует небезопасные поды до их создания. Kubesec добавляет:

*   **Гибкие scoring-механизмы:** Возможность тонкой настройки весов правил под конкретный стандарт.
*   **Shift-Left:** Проверка манифестов до попадания в кластер (CI/CD, IDE).
*   **Явные remediation:** Конкретные рекомендации по исправлению для каждого правила.

Рекомендуется использовать Kubesec в связке с PSA: Kubesec — на этапе CI/CD, PSA — как safety net в кластере.

### Ограничения инструмента

*   **Статический анализ:** Kubesec не видит конфигурацию, injected патчи (MutatingWebhook) или runtime-состояние. Security Context, добавленный через admission-контроллер после создания пода, не анализируется.
*   **Зависимость от схем:** Для корректного анализа CRD требуются актуальные OpenAPI-схемы. Устаревшие схемы приводят к пропуску проверок.
*   **Отсутствие семантического анализа:** Инструмент проверяет факт наличия/отсутствия параметров, но не валидирует их значения в контексте приложения (например, `readOnlyRootFilesystem: true` может сломать приложение, пишущее в `/tmp`).
*   **Kubesec-as-a-Service:** Публичный API не гарантирует конфиденциальность сканируемых манифестов. Для внутренней политики безопасности используйте локальный инстанс.

---

## Практические сценарии

### Установка Kubesec

*   **Docker:** `docker run -i kubesec/kubesec:v2 scan /dev/stdin < pod.yaml`
*   **Kubectl Plugin:** `kubectl krew install kubesec`
*   **Binary (Linux/macOS):**
    ```bash
    curl -sSL https://github.com/controlplaneio/kubesec/releases/download/v2.11.0/kubesec_linux_amd64.tar.gz | tar -xz
    mv ./kubesec /usr/local/bin/
    ```

### Pre-commit Hook

Интеграция с `pre-commit` framework позволяет блокировать коммиты небезопасных манифестов:

```yaml
# .pre-commit-config.yaml
- repo: https://github.com/controlplaneio/kubesec
  rev: v2.11.0
  hooks:
    - id: kubesec
      args: ['--output=json']
```

Установка:

```bash
pre-commit install
# → Pre-commit hook installed
```

При попытке закоммитить манифест с score < 0 коммит отклоняется с выводом проваленных правил.

### Интеграция в CI/CD

#### GitHub Actions

Блокировка пайплайна при обнаружении критических проблем:

```yaml
- name: Run Kubesec
  run: |
    kubesec scan k8s/deployment.yaml > result.json
    SCORE=$(jq '.[0].score' result.json)
    if [ "$SCORE" -lt 0 ]; then
      echo "Security Score is too low: $SCORE"
      exit 1
    fi
```

#### GitLab CI

```yaml
kubesec_scan:
  stage: test
  image: kubesec/kubesec:v2
  script:
    - kubesec scan k8s/deployment.yaml --output=json > result.json
    - |
      SCORE=$(jq '.[0].score' result.json)
      if [ "$SCORE" -lt 0 ]; then
        echo "Security Score is too low: $SCORE"
        exit 1
      fi
  rules:
    - changes:
        - k8s/**/*.yaml
```

### Argo CD / GitOps Integration

В GitOps-пайплайне Kubesec работает как внешний анализатор. Argo CD может запускать Kubesec через **Config Management Plugin (CMP)** или внешний Job:

```yaml
# ApplicationSet с CMP
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: secure-apps
spec:
  generators:
    - git:
        repoURL: https://github.com/org/k8s-manifests.git
        revision: HEAD
        directories:
          - path: apps/*
  template:
    metadata:
      name: "{{path.basename}}"
    spec:
      configManagementPlugins:
        - name: kubesec
          init:
            command: ["/bin/sh", "-c"]
            args: ["curl -sSL https://github.com/controlplaneio/kubesec/releases/download/v2.11.0/kubesec_linux_amd64.tar.gz | tar -xz"]
      source:
        plugin:
          name: kubesec
```

Для долгосрочного хранения результатов аудита и корреляции с Flux/Argo CD используйте [Аудит и трассируемость в GitOps](../../GitOps/Concepts/audit_logs.md).

### Примеры исправления (Remediation)

#### 1. Устранение критического риска (Privileged)

*   **Проблема:** Использование `privileged: true` (Score: -30).
*   **Исправление:** Отключить привилегированный режим и добавить только необходимые capability.

```yaml
# Исправленный SecurityContext
securityContext:
  privileged: false
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
    add: ["NET_BIND_SERVICE"]
```

#### 2. Повышение оценки (Root & FS)

*   **Исправление:** Явное указание не-root пользователя и read-only файловой системы.

```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
  containers:
  - name: app
    securityContext:
      readOnlyRootFilesystem: true
      allowPrivilegeEscalation: false
```

### Пакетное сканирование репозитория

Скрипт для рекурсивного сканирования всех YAML-манифестов в директории:

```bash
#!/bin/bash
# scan-all.sh — пакетное сканирование всех манифестов в k8s/

SCAN_DIR="./k8s"
TEMP_DIR=$(mktemp -d)
FAILED=0

find "$SCAN_DIR" -name "*.yaml" -o -name "*.yml" | while read -r file; do
  kubesec scan "$file" --output=json > "$TEMP_DIR/$(basename "$file").json" 2>/dev/null
  SCORE=$(jq '.[0].score' "$TEMP_DIR/$(basename "$file").json")
  if [ "$SCORE" -lt 0 ]; then
    echo "FAIL: $file (score: $SCORE)"
    FAILED=$((FAILED + 1))
  else
    echo "PASS: $file (score: $SCORE)"
  fi
done

echo "---"
echo "Total failed: $FAILED"

rm -rf "$TEMP_DIR"
```

### Настройка Admission Controller

Kubesec может работать как `ValidatingWebhookConfiguration`. При попытке `kubectl apply` API-сервер отправляет запрос в Kubesec, который блокирует операцию, если `score < 0`.

```bash
# Запуск Kubesec как сервиса внутри кластера
kubectl run kubesec --image=kubesec/kubesec:v2 --port=8080 -- http 8080
```

### Полный развертывание Admission Controller

Для production-развертывания используйте отдельный Deployment, Service, ServiceAccount и RBAC. Пример конфигурации ValidatingWebhookConfiguration:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: kubesec
webhooks:
  - name: kubesec.io
    matchPolicy: Exact
    rules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
      - apiGroups: ["apps"]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["deployments", "daemonsets", "statefulsets", "replicasets"]
    clientConfig:
      service:
        name: kubesec
        namespace: security-tools
        path: "/"
      caBundle: "<CA_CERT_BASE64>"
    admissionReviewVersions: ["v1"]
    sideEffects: None
    failurePolicy: Ignore
```

### Интеграция в GitHub Actions

Блокировка пайплайна при обнаружении критических проблем:

```yaml
- name: Run Kubesec
  run: |
    kubesec scan k8s/deployment.yaml > result.json
    SCORE=$(jq '.[0].score' result.json)
    if [ "$SCORE" -lt 0 ]; then
      echo "Security Score is too low: $SCORE"
      exit 1
    fi
```

---

## Дополнительная информация

### Сравнение с инструментами (2025–2026)

| Инструмент | Фокус | Сильные стороны | Когда выбирать |
| :--- | :--- | :--- | :--- |
| **Kubesec** | K8s YAML | Экстремальная скорость, простой скоринг. | Быстрый чек в IDE/Pre-commit. |
| **Trivy** | Универсальный | Сканирует образы, IaC, SBOM. Лидер рынка. | Основной стандарт для CI/CD. |
| **Checkov** | IaC Graph | Поиск связей между ресурсами (Terraform/K8s). | Сложные инфраструктуры. |
| **Terrascan** | OPA/Rego | *Архивирован (Nov 2025).* | **Мигрировать на Trivy.** |

### Вопросы производительности

Kubesec оптимизирован для скорости. На типичном манифесте (~50 строк) CLI-сканирование занимает <100 мс. В режиме HTTP Server (`serve`) инструмент держит схему в памяти и обрабатывает запросы параллельно, что позволяет интегрировать его как внутренний микросервис без существенного влияния на latency пайплайна.

### Best Practices

1.  **Combo-подход:** Всегда запускайте Kubesec вместе с [Kubeconform](../ToolsUtilities/kubeconform_overview.md). Первый проверяет безопасность, второй — корректность схемы.
2.  **Score threshold в CI:** Устанавливайте порог `score >= 0` как prerequisite для merge в main.
3.  **RBAC для Admission Controller:** ServiceAccount Kubesec должен иметь минимальные права (только `get`, `list` на поды). Никогда не давайте `cluster-admin`.
4.  **failurePolicy: Ignore:** В ValidatingWebhookConfiguration используйте `Ignore`, чтобы отказ Kubesec не блокировал деплой при недоступности сервиса.
5.  **Версионирование образов:** Никогда не используйте тег `latest` в production-развертываниях Admission Controller. Фиксируйте версию (например, `kubesec/kubesec:v2.11.0`).

### Compliance Mapping

Kubesec покрывает требования следующих стандартов:

| Стандарт | Раздел | Соответствие |
| :--- | :--- | :--- |
| **CIS Kubernetes Benchmark** | 5.2.7, 5.2.8 | Проверка `allowPrivilegeEscalation`, `readOnlyRootFilesystem`, `runAsNonRoot`. |
| **PCI DSS** | 2.2, 6.3 | Запуск от root, привилегированные контейнеры. |
| **ISO 27001** | A.14.2.5 | Принцип наименьших привилегий в контейнерах. |
| **SOC 2** | CC6.1 | Логическое разделение сред через Security Context. |

Общие принципы комплаенса подробно описаны в разделе [Аудит и комплаенс: Обзор](../../Security/audit_and_compliance_overview.md).

### Связанные темы

* [Security Context в Kubernetes](./pod_security_context.md) — детальный разбор всех параметров безопасности.
* [kube-bench](./kube-bench.md) — проверка конфигурации хостов и Control Plane на соответствие CIS.
* [Falco: Runtime Security](../../Security/Tools/falco.md) — мониторинг активности в реальном времени.
* [Kubeconform](../ToolsUtilities/kubeconform_overview.md) — валидация схем и CRD.
* [Аудит событий в Kubernetes](./audit.md) — логирование API-вызовов.

**Ссылки:**
* [Официальный репозиторий проекта](https://github.com/controlplaneio/kubesec)
* [Документация и список правил](https://kubesec.io)
