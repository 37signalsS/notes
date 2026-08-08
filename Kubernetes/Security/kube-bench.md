# kube-bench: Аудит безопасности инфраструктуры Kubernetes

## Определения

**kube-bench** — это инструмент с открытым исходным кодом от Aqua Security для автоматизированной проверки конфигурации кластера Kubernetes на соответствие рекомендациям по безопасности CIS.

* **CIS (Center for Internet Security) Kubernetes Benchmark:** Отраслевой стандарт, содержащий набор атомарных проверок для обеспечения безопасности компонентов Kubernetes.
* **Remediation (Исправление):** Входящие в состав отчета инструкции по устранению выявленных уязвимостей (конкретные команды `chmod`, флаги запуска и т.д.).
* **Compliance-as-Code:** Подход к управлению соответствием стандартам через автоматизированные тесты, интегрированные в жизненный цикл инфраструктуры.

**Важно:** kube-bench проверяет параметры запуска бинарных файлов (API-сервер, Kubelet, etcd) и права доступа к конфигурационным файлам на хосте. Для статического анализа YAML-манифестов приложений (Deployment, Service) используйте [kubesec](./kubesec.md).

## Основные концепции

### Принцип работы

Инструмент запускается непосредственно на узлах кластера. Он считывает текущие параметры запущенных процессов (через `/proc` или `ps`) и проверяет их соответствие эталонным значениям, описанным в YAML-файлах конфигурации тестов.

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

### 2. Использование через Trivy (рекомендуемый современный подход)

Aqua Security интегрировала логику kube-bench в **Trivy**. Это позволяет выполнять аудит без ручного развертывания Job:

```bash
# Аудит всего кластера на соответствие CIS
trivy kubernetes cluster --compliance=k8s-cis-1.31
```

### 3. Запуск в облачных средах (EKS, GKE, AKS)

В управляемых сервисах пользователь отвечает только за Worker ноды. kube-bench предоставляет оптимизированные профили:

```bash
# Пример для Amazon EKS (версия v1.8+)
docker run --pid=host --rm -v /etc:/etc:ro -v /var:/var:ro \
  aquasec/kube-bench:latest run --targets node --benchmark eks-1.8
```

### 4. Интеграция в CI/CD (GitHub Actions)

Проверка инфраструктуры при использовании Kind или эфемерных кластеров:

```yaml
- name: Run kube-bench
  run: |
    docker run --pid=host --rm -v /etc:/etc:ro -v /var:/var:ro \
      aquasec/kube-bench:latest run --targets master,node --json | jq .
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

### 6. Экспорт результатов в Prometheus

Для мониторинга комплаенса можно использовать `kube-bench` вместе с адаптерами. Рекомендуется использовать [Policy Reporter](./kyverno/reporter.md) для визуализации и агрегации результатов в единую панель.

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

### Проверка на соответствие FIPS

Для систем, требующих **FIPS 140-2/3**, kube-bench проверяет использование криптографических модулей, если выбран соответствующий профиль или версия Kubernetes поддерживает FIPS.

### Сравнение с другими инструментами

* [kubesec](./kubesec.md) — статический анализ манифестов (Deployment, Pod).
* [Kyverno](./kyverno/policies/practical_scenarios.md) — принудительное исполнение политик в рантайме.
* [Falco](../../Security/Tools/falco.md) — обнаружение аномалий в реальном времени.
* **kube-hunter** — поиск уязвимостей методом имитации атак (Penetration Testing).

**Связанные темы:**

* [Официальный репозиторий проекта](https://github.com/aquasecurity/kube-bench)
* [Документация по маппингу версий CIS](https://github.com/aquasecurity/kube-bench/blob/main/docs/benchmark-mapping.md)
* [Аутентификация в Kubernetes](./authentication.md) — настройки, которые проверяет kube-bench.
* [Pod Security Admission](./pod_security_context.md) — стандарт безопасности для подов.
