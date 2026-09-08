# kube-bench: Аудит безопасности инфраструктуры Kubernetes

## Определения

**kube-bench** — это инструмент с открытым исходным кодом от Aqua Security для автоматизированной проверки конфигурации кластера Kubernetes на соответствие рекомендациям по безопасности CIS.

* **CIS (Center for Internet Security) Kubernetes Benchmark:** Отраслевой стандарт, содержащий набор атомарных проверок для обеспечения безопасности компонентов Kubernetes.
* **Remediation (Исправление):** Входящие в состав отчета инструкции по устранению выявленных уязвимостей (конкретные команды `chmod`, флаги запуска и т.д.).
* **Compliance-as-Code:** Подход к управлению соответствием стандартам через автоматизированные тесты, интегрированные в жизненный цикл инфраструктуры.
* **Уровень 1 (Level 1 / Profile):** Базовый набор рекомендаций, ориентированный на безопасность «из коробки» без существенного влияния на функциональность или производительность. Рекомендуется для большинства production-сред.
* **Уровень 2 (Level 2 / Policy):** Расширенный набор рекомендаций для сред с повышенными требованиями к безопасности (PCI DSS, военные/государственные контуры). Может включать отключение функциональности или введение дополнительных ограничений.
* **Test Config (YAML):** Файл конфигурации проверки, описывающий логику (`audit`, `check`, `remediation`) для конкретного контрольного пункта CIS.
* **Target (Цель аудита):** Компонент инфраструктуры, на который направлена проверка: `master`, `node`, `etcd`, `managed-services`.

**Важно:** kube-bench проверяет параметры запуска бинарных файлов (API-сервер, Kubelet, etcd) и права доступа к конфигурационным файлам на хосте. Для статического анализа YAML-манифестов приложений (Deployment, Service) используйте [kubesec](./kubesec.md).

---

## Основные концепции

### Принцип работы

Инструмент запускается непосредственно на узлах кластера или в контейнере с доступом к хостовой файловой системе (`--pid=host`, `-v /etc:/etc:ro`, `-v /var:/var:ro`). Он считывает текущие параметры запущенных процессов (через `/proc` или `ps`) и проверяет их соответствие эталонным значениям, описанным в YAML-файлах конфигурации тестов.

### Архитектура процесса аудита

```text
┌──────────────────────────────────────────────────────────────────┐
│  Компонент инфраструктуры                                        │
│  (kube-apiserver / kubelet / etcd)                              │
└────────────────────────────┬─────────────────────────────────────┘
                             │ Статический опрос (ps, /proc, stat)
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  kube-bench                                                      │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐  │
│  │ Загрузка cfg/  │─>│ Матчинг тестов │─>│ Формирование     │  │
│  │ (YAML-тесты)   │  │ по версии K8s  │  │ отчета (PASS/    │  │
│  │                │  │                │  │ FAIL/WARN)       │  │
│  └────────────────┘  └────────────────┘  └──────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**Этапы выполнения:**
1. **Определение версии Kubernetes:** kube-bench опрашивает кластер (через `kubectl` или локальный `kubeconfig`) и определяет точную версию.
2. **Выбор профиля CIS:** На основе версии подгружается набор тестов из директории `cfg/`.
3. **Сбор evidence:** Чтение аргументов процессов и прав доступа к конфигурационным файлам.
4. **Оценка:** Каждый тест возвращает `PASS`, `FAIL` или `WARN` (если evidence неполное).
5. **Ремедиация:** Для каждого `FAIL` генерируется блок `Remediation` с конкретными командами исправления.

### Структура YAML-конфигурации теста

Каждый контрольный пункт CIS описывается в файле `cfg/*.yaml`. Пример минимального теста:

```yaml
controls:
  - id: CIS-1.2.1
    text: "Ensure that the --anonymous-auth argument is set to false"
    tests:
      - test_type: "file"
        test_output: "false"
        audit: "grep -P -- '--anonymous-auth=false' /etc/kubernetes/manifests/kube-apiserver.yaml"
        check_type: "regex_match"
        check: "false"
        expected_value: "false"
        flags:
          negative: "on"
    remediation: |
      Edit the API server pod specification file /etc/kubernetes/manifests/kube-apiserver.yaml
      and set the --anonymous-auth=false flag.
```

**Поля теста:**
* `test_type` — источник evidence: `file` (содержимое файла), `command` (выполнение команды), `socket` (служба systemd).
* `audit` — команда или путь для получения текущего значения.
* `check_type` — метод сравнения: `eq` (равно), `gt` (больше), `regex_match` (регулярное выражение), `file` (существование файла).
* `remediation` — рекомендуемые действия для устранения нарушения.

### Области аудита по уровням CIS

1. **Безопасность Control Plane (Control Plane Security):** Проверка API-сервера, контроллер-менеджера, шедулера и etcd.
2. **Безопасность узлов (Node Security):** Аудит Kubelet и настроек контейнерной среды выполнения (CRI).
3. **Политики (Policies):** Проверка RBAC, сетевых политик и настроек Pod Security.

### Соответствие версий (2025–2026)

kube-bench автоматически определяет версию Kubernetes и выбирает соответствующий профиль CIS. Актуальная версия на середину 2026 года — **v0.15.6**.

| Версия CIS | Версия Kubernetes | Профиль в kube-bench |
| :--- | :--- | :--- |
| **CIS 1.10** | 1.30 | `cis-1.10` |
| **CIS 1.11** | 1.31 | `cis-1.11` |
| **CIS 1.12** | 1.32 – 1.35 | `cis-1.12` |
| **CIS 1.13** | 1.36+ | `cis-1.13` |

### Выходные форматы (Output Formats)

kube-bench поддерживает несколько форматов для интеграции с пайплайнами:

* **Текстовый (по умолчанию):** Читаемый вывод с ASCII-таблицей и цветовой кодировкой (зеленый/красный).
* **JSON:** Машиночитаемый формат для парсинга в CI/CD. Флаг `--json`.
* **JUnit XML:** Формат для интеграции с Jenkins, GitLab CI, Test Reporting. Флаг `--junit`.
* **Github Annotations:** Специальный режим для GitHub Actions. Флаг `--github-annotations`.

Пример JSON-вывода (фрагмент):
```json
[
  {
    "id": "1.1.1",
    "test_number": "1.1.1",
    "test_desc": "Ensure that the --anonymous-auth argument is set to false",
    "status": "PASS",
    "remediation": "Edit the API server pod specification file ...",
    "test_info": null,
    "scored": true,
    "severity": "high"
  }
]
```

### Безопасность запуска kube-bench

Поскольку kube-bench требует доступа к хостовой файловой системе и `/proc`, запуск с `--pid=host` и монтированием `/etc` и `/var` расширяет его права до уровня узла. Рекомендации:

* Запускайте kube-bench из-под привилегированного ServiceAccount или root.
* Для Job в кластере используйте `hostPID: true` и соответствующие `hostPath` volumes.
* В managed-средах убедитесь, что DaemonSet не имеет прав на запись в `/etc/kubernetes`.
* Рассматривайте сканирование как privileged-операцию и ограничьте запуск только SRE-аккаунтами через RBAC или OPA.

---

## Практические сценарии

### 1. Запуск через Kubernetes Job

Рекомендуемый способ для аудита всех узлов.

**Для Control Plane:**
```bash
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-master.yaml
```

**Для Worker нод:**
```bash
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-node.yaml
```

После выполнения Job соберите логи:
```bash
kubectl logs job/kube-bench -n kube-bench
```

### 2. Использование через Trivy (рекомендуемый современный подход)

Aqua Security интегрировала логику kube-bench в **Trivy**. Это позволяет выполнять аудит без ручного развертывания Job:

```bash
# Аудит всего кластера на соответствие CIS
trivy kubernetes cluster --compliance=k8s-cis-1.31
```

### 3. Запуск в распределенных средах (Kubeadm, RKE2, K3s)

Для кластеров, развернутых через Kubeadm, RKE2 или K3s, используйте локальный запуск на каждом Control Plane узле:

```bash
docker run --pid=host --rm -v /etc:/etc:ro -v /var:/var:ro \
  aquasec/kube-bench:latest run --targets master,node
```

**RKE2 / K3s специфика:**
* Конфигурации размещаются в `/var/lib/rancher/rke2/etc/` (RKE2) или `/var/lib/rancher/k3s/etc/` (K3s).
* Kube-bench автоматически определяет специфические пути, но при необходимости укажите их через переменные окружения или кастомный config.

### 4. Интеграция в CI/CD (GitHub Actions, GitLab CI)

Проверка инфраструктуры при использовании Kind или эфемерных кластеров:

```yaml
- name: Run kube-bench
  run: |
    docker run --pid=host --rm -v /etc:/etc:ro -v /var:/var:ro \
      aquasec/kube-bench:latest run --targets master,node --json | jq .
```

Для блокировки пайплайна при обнаружении критических нарушений:
```bash
docker run --pid=host --rm -v /etc:/etc:ro -v /var:/var:ro \
  aquasec/kube-bench:latest run --targets master,node --json > result.json

SCORE=$(jq '[.[] | select(.scored == true) | .status] | map(select(. == "FAIL")) | length' result.json)
if [ "$SCORE" -gt 0 ]; then
  echo "Security failures detected: $SCORE"
  exit 1
fi
```

### 5. Создание пользовательских проверок (Custom Checks)

Тесты описываются в YAML-файлах в директории `cfg/`. Вы можете добавить свои проверки, создав файл `cfg/custom.yaml`:

```yaml
controls:
  id: custom
  text: "Организационные проверки безопасности"
  tests:
    - id: C-001
      text: "Проверка наличия файла организационной политики"
      audit: "test -f /etc/org-security-policy"
      tests:
        bin_op: or
        items:
          - set: true
      remediation: "Создайте файл /etc/org-security-policy"
```

### 6. Запуск с кастомным config файлом

Для тонкой настройки используйте `--config`, указывая файл с параметрами:

```yaml
# config.yaml
targets:
  - master
  - node
  - etcd
tests:
  - "1.1"
  - "1.2"
  - "2.1"
```

```bash
kube-bench run --config config.yaml
```

### 7. Запуск конкретных тестов

Для проверки только определенных контрольных пунктов используйте флаг `--tests`:

```bash
kube-bench run --tests 1.1.1,1.1.2,1.2.1
```

Или через регулярное выражение (зависит от версии):
```bash
kube-bench run --tests "1.1.*"
```

### 8. Запуск через Krew Plugin

```bash
kubectl krew install kube-bench
kube-bench run
```

### 9. Запуск как CronJob для непрерывного комплаенса

Для регулярного аудита разверните CronJob в кластере:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: kube-bench
  namespace: security-tools
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          hostPID: true
          restartPolicy: Never
          containers:
          - name: kube-bench
            image: aquasec/kube-bench:v0.15.6
            args:
            - run
            - --targets
            - master,node,etcd
            - --json
            volumeMounts:
            - name: etc
              mountPath: /etc
              readOnly: true
            - name: var
              mountPath: /var
              readOnly: true
          volumes:
          - name: etc
            hostPath:
              path: /etc
          - name: var
            hostPath:
              path: /var
```

Храните результаты в ConfigMap или отправляйте во внешний бэкенд через вебхук.

### 10. Экспорт результатов в Prometheus и визуализация

Для мониторинга комплаенса используйте адаптер, преобразующий JSON-результат в метрики Prometheus. Рекомендуется использовать [Policy Reporter](./kyverno/reporter.md) для визуализации и агрегации результатов в единую панель.

Альтернативный подход — кастомный экспортер на Python:
```python
#!/usr/bin/env python3
import json, sys
from prometheus_client import CollectorRegistry, Gauge, write_to_textfile

results = json.load(open(sys.argv[1]))
registry = CollectorRegistry()

g_fail = Gauge('kube_bench_failures_total', 'CIS benchmark failures', ['test_id'], registry=registry)
g_pass = Gauge('kube_bench_passes_total', 'CIS benchmark passes', ['test_id'], registry=registry)

for item in results:
    test_id = item.get('test_number', 'unknown')
    status = item.get('status', 'UNKNOWN')
    if status == 'FAIL':
        g_fail.labels(test_id=test_id).inc(1)
    elif status == 'PASS':
        g_pass.labels(test_id=test_id).inc(1)

write_to_textfile('/var/lib/node_exporter/kube_bench.prom', registry)
```

### 11. Автоматизация remedation через Ansible

Для массового исправления нарушений используйте Ansible:

```yaml
- name: Ensure anonymous auth is disabled
  hosts: k8s_control_plane
  tasks:
    - name: Patch kube-apiserver manifest
      lineinfile:
        path: /etc/kubernetes/manifests/kube-apiserver.yaml
        regexp: '--anonymous-auth='
        line: '    - --anonymous-auth=false'
      notify: Restart kubelet

  handlers:
    - name: Restart kubelet
      systemd:
        name: kubelet
        state: restarted
      become: true
```

### 12. Проверка соответствия FIPS

Для систем, требующих **FIPS 140-2/3**, kube-bench проверяет использование криптографических модулей, если выбран соответствующий профиль или версия Kubernetes поддерживает FIPS.

---

## Дополнительная информация

### Автоматизированное исправление (Remediation)

После каждой неудачной проверки (`FAIL`) инструмент выдает блок `Remediation`.

**Пример:**
```text
[FAIL] 1.1.1 Ensure that the --anonymous-auth argument is set to false
[INFO] 1.1.1 Remediation:
Отредактируйте файл /etc/kubernetes/manifests/kube-apiserver.yaml 
и установите параметр --anonymous-auth=false.
```

### Compliance-соответствие

kube-bench покрывает требования следующих стандартов:

| Стандарт | Раздел | Соответствие |
| :--- | :--- | :--- |
| **CIS Kubernetes Benchmark** | Все контроли | Полное покрытие рекомендаций CIS для K8s. |
| **PCI DSS** | 2.2, 6.3 | Запуск от root, привилегированные контейнеры, изоляция сетей. |
| **ISO 27001** | A.14.2.5 | Принцип наименьших привилегий в контейнерах. |
| **SOC 2** | CC6.1 | Логическое разделение сред через Security Context. |
| **DISA STIG** | Kubernetes STIG | Частичное покрытие через overlap с CIS. |

Общие принципы комплаенса подробно описаны в разделе [Аудит и комплаенс: Обзор](../../Security/audit_and_compliance_overview.md).

### Сравнение с другими инструментами

| Инструмент | Фокус | Сильные стороны | Когда выбирать |
| :--- | :--- | :--- | :--- |
| **kube-bench** | Control Plane / Node / etcd | Эталон для CIS, проверка хостовых параметров. | Базовый аудит безопасности инфраструктуры. |
| **kubesec** | K8s YAML | Скоринг манифестов, SAST. | Анализ Deployment/Pod конфигураций. |
| **Kyverno** | Admission / Policy | Принудительное исполнение политик в рантайме. | Блокировка несоответствующих ресурсов. |
| **Falco** | Runtime Security | Обнаружение аномалий в реальном времени. | Детекция вторжений и insider-угроз. |
| **Lynis** | Host OS | Общий аудит безопасности Linux-хоста. | Харденинг ОС перед установкой K8s. |
| **kube-hunter** | Penetration Testing | Имитация атак, поиск уязвимостей. | Red Team, проверка сетевого периметра. |

### Best Practices

1. **Поэтапный аудит:** Начните с Level 1 профиля, исправьте критические (`FAIL`), затем переходите к Level 2.
2. **CI/CD Gate:** Интегрируйте kube-bench (через Trivy) в пайплайн инфраструктуры. Блокируйте merge, если score упал ниже порога.
3. **Continuous Compliance:** Запускайте аудит как CronJob или как часть nightly-пайплайна. Накопление исторических данных позволяет выявлять drift (отклонение от эталона).
4. **Remediation as Code:** Храните скрипты исправления (Ansible, bash) в отдельном репозитории и применяйте их через CI/CD после Approval.
5. **RBAC для сканера:** ServiceAccount, от имени которого работает kube-bench, должен иметь минимальные права. Никогда не используйте `cluster-admin` для сканеров безопасности.
6. **Версионирование:** Фиксируйте версию образа kube-bench (`aquasec/kube-bench:v0.15.6`), никогда не используйте `latest` в production.
7. **Сохранение evidence:** Сохраняйте raw-отчеты (JSON/JUnit) в артефактах пайплайна с временными метками. Это необходимо для аудиторских проверок.
8. **Связка с Audit Logs:** Результаты kube-bench (статический аудит) дополняются [Аудитом событий в Kubernetes](./audit.md) (динамический аудит). Используйте оба источника для полной картины.

### Ограничения инструмента

* **Статический анализ:** kube-bench проверяет только текущее состояние параметров запуска. Он не видит изменений, примененных MutatingWebhook после старта пода (например, injected Security Context).
* **Зависимость от структуры файлов:** В RKE2/K3s пути к манифестам отличаются от Kubeadm. При запуске на этих дистрибутивах используйте соответствующие флаги или переменные окружения.
* **Глубина проверок:** kube-bench не проверяет логику внутри контейнеров (например, уязвимости в образе, открытые порты). Для этого используйте Trivy или Grype.
* **Одномоментный снимок:** Инструмент показывает состояние на момент запуска. Для отслеживания drift используйте регулярные запуски.
* **Managed Services:** В управляемых сервисах проверка Control Plane недоступна пользователю. Используйте встроенные отчеты соответствия провайдера.

### Связанные темы

* [Официальный репозиторий проекта](https://github.com/aquasecurity/kube-bench)
* [Документация по маппингу версий CIS](https://github.com/aquasecurity/kube-bench/blob/main/docs/benchmark-mapping.md)
* [Аутентификация в Kubernetes](./authentication.md) — настройки, которые проверяет kube-bench.
* [Pod Security Admission](./pod_security_context.md) — стандарт безопасности для подов.
* [kubesec](./kubesec.md) — статический анализ манифестов (Deployment, Pod).
* [Kyverno](./kyverno/policies/practical_scenarios.md) — принудительное исполнение политик в рантайме.
* [Falco](../../Security/Tools/falco.md) — обнаружение аномалий в реальном времени.
* [Безопасность Kubelet](./kubelet_security.md) — полный гайд по аутентификации, авторизации и TLS kubelet.
