# kube-bench: Аудит безопасности инфраструктуры Kubernetes

## Определения

**kube-bench** — это инструмент с открытым исходным кодом для автоматизированной проверки конфигурации кластера Kubernetes на соответствие рекомендациям по безопасности.

**CIS (Center for Internet Security) Kubernetes Benchmark** — отраслевой стандарт, содержащий набор проверок и рекомендаций для обеспечения безопасности компонентов Kubernetes.

**Важно:** kube-bench проверяет параметры запуска и конфигурационные файлы инфраструктуры (API-сервер, Kubelet, etcd). Для статического анализа манифестов приложений используйте [kubesec](./kubesec.md).

## Основные концепции

### Принцип работы

Инструмент запускается на узлах кластера (Control Plane и Worker) и проверяет настройки запущенных процессов и права доступа к файлам конфигурации. По результатам проверки формируется отчет со статусами и рекомендациями по исправлению выявленных несоответствий.

### Области проверки

* **Control Plane:** Аудит `kube-apiserver`, `kube-scheduler`, `kube-controller-manager` и `etcd`.
* **Worker Nodes:** Аудит конфигурации `kubelet` и параметров безопасности среды выполнения контейнеров.
* **RBAC и политики:** Проверка базовых настроек управления доступом и политик безопасности.

### Поддержка окружений

* Релизные версии Kubernetes (от 1.15 до текущих).
* Облачные управляемые сервисы: GKE (Google Kubernetes Engine), EKS (Amazon Elastic Kubernetes Service), AKS (Azure Kubernetes Service).
* Дистрибутивы: OpenShift, RKE2, K3s.

## Практические сценарии

### 1. Запуск через Kubernetes Job

Это рекомендуемый способ для регулярного аудита всех узлов кластера.

```bash
# Запуск проверки для Control Plane
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/v0.15.0/job-master.yaml

# Запуск проверки для Worker нод
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/v0.15.0/job-node.yaml
```

### 2. Запуск через Docker

Удобно для разовой проверки узла без установки дополнительных компонентов в кластер.

```bash
docker run --pid=host --rm -v /etc:/etc:ro -v /var:/var:ro \
  aquasec/kube-bench:v0.15.0 master
```

### 3. Интерпретация результатов

Результаты классифицируются по четырем статусам:

* **PASS:** Конфигурация соответствует рекомендациям CIS.
* **FAIL:** Обнаружено несоответствие, требующее исправления. Обычно сопровождается текстом рекомендации.
* **WARN:** Рекомендация, требующая ручной проверки (например, если параметр нельзя проверить автоматически).
* **INFO:** Справочная информация о параметре.

## Дополнительная информация

### Сравнение с другими инструментами

* [kubesec](./kubesec.md) — статический анализ YAML-манифестов до деплоя.
* [Kyverno](./kyverno/policies/practical_scenarios.md) — контроль соответствия политикам при деплое (Admission Control).
* [Falco](../../Security/Tools/falco.md) — обнаружение угроз во время выполнения (Runtime Security).
* **kubescape** — комплексный аудит безопасности, включая уязвимости и misconfigurations.
* **kube-hunter** — поиск уязвимостей в кластере с позиции внешнего или внутреннего атакующего (пентест).

### Полезные ссылки

* [Официальный репозиторий kube-bench](https://github.com/aquasecurity/kube-bench)
* [Официальный сайт CIS Benchmarks](https://www.cisecurity.org/benchmark/kubernetes)
* [Pod Security Context](./pod_security_context.md) — настройка безопасности на уровне подов.
