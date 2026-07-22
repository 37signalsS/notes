# kube-bench: Аудит безопасности инфраструктуры Kubernetes

## Определения

**kube-bench** — это инструмент с открытым исходным кодом от Aqua Security для автоматизированной проверки конфигурации кластера Kubernetes на соответствие рекомендациям по безопасности.

* **CIS (Center for Internet Security) Kubernetes Benchmark:** Отраслевой стандарт, содержащий набор атомарных проверок для обеспечения безопасности компонентов Kubernetes.
* **Remediation (Исправление):** Входящие в состав отчета инструкции по устранению выявленных уязвимостей (конкретные команды `chmod`, флаги запуска и т.д.).
* **Compliance-as-Code:** Подход к управлению соответствием стандартам через автоматизированные тесты, интегрированные в жизненный цикл инфраструктуры.

**Важно:** kube-bench проверяет параметры запуска бинарных файлов (API-сервер, Kubelet, etcd) и права доступа к конфигурационным файлам на хосте. Для статического анализа YAML-манифестов приложений (Deployment, Service) используйте [kubesec](./kubesec.md).

## Основные концепции

### Принцип работы

Инструмент запускается непосредственно на узлах кластера. Он считывает текущие параметры запущенных процессов (через `/proc` или `ps`) и проверяет их соответствие эталонным значениям, описанным в YAML-файлах конфигурации тестов.

### Области аудита по уровням CIS

1. **Control Plane Security:** Проверка API-сервера, контроллер-менеджера, шедулера и etcd.
2. **Node Security:** Аудит Kubelet и настроек контейнерной среды выполнения (CRI).
3. **Policies:** Проверка RBAC, сетевых политик и настроек Pod Security.

### Соответствие версий (2024–2025)

kube-bench автоматически определяет версию Kubernetes и выбирает соответствующий профиль CIS:

| Версия CIS | Версия Kubernetes | Профиль в kube-bench |
| :--- | :--- | :--- |
| **CIS 1.9** | 1.27 | `cis-1.9` |
| **CIS 1.10** | 1.28 | `cis-1.10` |
| **CIS 1.11** | 1.29 – 1.31 | `cis-1.11` |
| **CIS 1.12** | 1.32 – 1.34+ | `cis-1.12` |

## Практические сценарии

### 1. Запуск через Kubernetes Job

Рекомендуемый способ для аудита всех узлов. Используйте `DaemonSet`, если требуется регулярная проверка каждого воркера.

```bash
# Запуск для Control Plane (актуальная версия v0.8.x+)
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-master.yaml

# Запуск для Worker нод
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-node.yaml
```

### 2. Запуск в облачных средах (EKS, GKE, AKS)

В управляемых сервисах Control Plane недоступен пользователю. kube-bench поддерживает специальные флаги для пропуска проверок мастера:

```bash
# Пример для Amazon EKS
docker run --pid=host --rm -v /etc:/etc:ro -v /var:/var:ro \
  aquasec/kube-bench:latest run --targets node --benchmark eks-1.0
```

### 3. Автоматизированное исправление (Remediation)

После каждой неудачной проверки (`FAIL`) инструмент выдает блок `Remediation`.

**Пример вывода:**
```text
[FAIL] 1.1.1 Ensure that the --anonymous-auth argument is set to false (Automated)
...
[INFO] 1.1.1 Remediation:
Edit the API server pod specification file /etc/kubernetes/manifests/kube-apiserver.yaml 
on the control plane node and set the --anonymous-auth parameter to false.
```

### 4. Создание пользовательских проверок (Custom Checks)

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

## Дополнительная информация

### Интеграция с Trivy

Aqua Security интегрировала логику kube-bench в **Trivy**. Теперь можно выполнять аудит CIS одной командой:
```bash
trivy kubernetes cluster --compliance=k8s-cis-1.23
```

### Сравнение с другими инструментами

* [kubesec](./kubesec.md) — фокус на безопасности прикладных манифестов.
* [Kyverno](./kyverno/policies/practical_scenarios.md) — принудительное исполнение политик (Enforcement) вместо простого аудита.
* [Falco](../../Security/Tools/falco.md) — обнаружение атак в реальном времени (попытки записи в системные файлы и т.д.).
* **kube-hunter** — активный поиск уязвимостей (симуляция атаки).

**Ссылки:**
* [Официальный репозиторий проекта](https://github.com/aquasecurity/kube-bench)
* [Документация по маппингу версий CIS](https://github.com/aquasecurity/kube-bench/blob/main/docs/benchmark-mapping.md)
* [Pod Security Admission](./pod_security_context.md) — современный механизм защиты подов в Kubernetes.
