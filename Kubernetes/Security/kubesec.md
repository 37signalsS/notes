# Kubesec: Анализ рисков и сканер безопасности в Kubernetes

## Определения

**Kubesec** — это инструмент с открытым исходным кодом для статического анализа безопасности (SAST) манифестов Kubernetes (YAML). Он оценивает риски конфигурации и выставляет числовую оценку (score) на основе соответствия лучшим практикам безопасности ControlPlane и CIS Benchmark.

* **Shift-Left Security:** Стратегия переноса проверок безопасности на максимально ранние этапы разработки (IDE, CI/CD), позволяющая выявлять ошибки конфигурации до момента их развертывания.
* **Score (Оценка):** Агрегированный показатель безопасности. Отрицательный итоговый балл сигнализирует о наличии критических уязвимостей, блокирующих использование манифеста в production.
* **Remediation (Исправление):** Процесс изменения конфигурации для устранения выявленных рисков и повышения итоговой оценки.

**Важно:** Kubesec фокусируется на логике безопасности (Security Context, Capabilities). Для проверки синтаксиса и соответствия схемам API он интегрируется с [Kubeconform](../ToolsUtilities/kubeconform_overview.md).

---

## Основные концепции

* **Область анализа:** Проверка Pod, Deployment, Service, DaemonSet, StatefulSet, CronJob, а также `initContainers` и `volumeClaimTemplates`.
* **Vigilant Mode (Бдительный режим):** Режим строгой проверки, требующий явного определения всех параметров безопасности (например, обязательный `readOnlyRootFilesystem`).
* **Поддержка CRD и схем:** Kubesec v2+ может проверять структуру Custom Resources. Для этого используются переменные окружения `K8S_SCHEMA_VER` и `SCHEMA_LOCATION`.
* **Режимы работы:**
    1.  **CLI:** Локальное сканирование файлов или потока `stdin`.
    2.  **HTTP Server:** Запуск в режиме `serve` для создания внутреннего микросервиса безопасности.
    3.  **Admission Controller:** Блокировка деплоя небезопасных ресурсов на уровне API-сервера Kubernetes.
* **Kubesec-as-a-Service:** Использование публичного API (`v2.kubesec.io/scan`) для быстрой проверки без установки инструмента.

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
```

### Настройка Admission Controller
Kubesec может работать как `ValidatingWebhookConfiguration`. При попытке `kubectl apply` API-сервер отправляет запрос в Kubesec, который блокирует операцию, если `score < 0`.

```bash
# Запуск Kubesec как сервиса внутри кластера
kubectl run kubesec --image=kubesec/kubesec:v2 --port=8080 -- http 8080
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

### Сравнение с инструментами (2025)

| Инструмент | Фокус | Сильные стороны | Когда выбирать |
| :--- | :--- | :--- | :--- |
| **Kubesec** | K8s YAML | Экстремальная скорость, простой скоринг. | Быстрый чек в IDE/Pre-commit. |
| **Trivy** | Универсальный | Сканирует образы, IaC, SBOM. Лидер рынка. | Основной стандарт для CI/CD. |
| **Checkov** | IaC Graph | Поиск связей между ресурсами (Terraform/K8s). | Сложные инфраструктуры. |
| **Terrascan** | OPA/Rego | *Архивирован (Nov 2025).* | **Мигрировать на Trivy.** |

### Связанные темы
* [Security Context в Kubernetes](./pod_security_context.md) — детальный разбор всех параметров безопасности.
* [kube-bench](./kube-bench.md) — проверка конфигурации хостов и Control Plane на соответствие CIS.
* [Falco: Runtime Security](../../Security/Tools/falco.md) — мониторинг активности в реальном времени.
* [Kubeconform](../ToolsUtilities/kubeconform_overview.md) — валидация схем и CRD.

**Ссылки:**
* [Официальный репозиторий проекта](https://github.com/controlplaneio/kubesec)
* [Документация и список правил](https://kubesec.io)
