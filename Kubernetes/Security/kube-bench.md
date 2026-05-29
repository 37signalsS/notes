# kube-bench: Аудит безопасности Kubernetes

## Определения

* **kube-bench**: Утилита от Aqua Security (<https://github.com/aquasecurity/kube-bench>), предназначенная для проверки конфигурации Kubernetes на соответствие рекомендациям **CIS Kubernetes Benchmark**.
* **CIS Kubernetes Benchmark**: Общепринятый стандарт от Center for Internet Security (CIS), содержащий набор лучших практик по обеспечению безопасности кластеров Kubernetes.

**Важно:** kube-bench проверяет **инфраструктуру кластера**, а не манифесты приложений. Для проверки манифестов используйте [kubesec](./kubesec.md) или [Kyverno](./kyverno/policies/practical_scenarios.md).

## Основные концепции

`kube-bench` запускается непосредственно на узлах кластера и выполняет аудит конфигурации ключевых компонентов Kubernetes на соответствие стандарту CIS.

**Что проверяет:**

* **Компоненты Control Plane**: Настройки `kube-apiserver`, `kube-scheduler`, `kube-controller-manager`, `etcd`.
* **Конфигурацию узлов**: Настройки `kubelet`.
* **Политики безопасности** и другие аспекты конфигурации кластера.

**Ключевой функционал:**

* Поддержка различных версий Kubernetes и облачных сред (GKE, EKS, AKS, OpenShift).
* Автоматическое определение роли узла (master или worker) для применения релевантных тестов.
* Генерация отчётов в текстовом или JSON-формате, классифицирующих проверки как пройденные (PASS), проваленные (FAIL) или требующие внимания (WARN).

**Место в экосистеме безопасности:**

kube-bench и [kubesec](./kubesec.md) дополняют друг друга, охватывая разные аспекты:

* **kube-bench** — аудит работающей инфраструктуры кластера (конфигурация компонентов, безопасность узлов).
* **kubesec** — статический анализ манифестов приложений до деплоя.
* [Kyverno](./kyverno/policies/practical_scenarios.md) — проверка манифестов во время деплоя (admission controller).
* [Falco](../../Security/Tools/falco.md) — мониторинг runtime-поведения после деплоя.

## Практические сценарии

### Запуск kube-bench

**Способ 1: Job в Kubernetes** (рекомендуется):

```bash
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-master.yaml
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-node.yaml
```

**Способ 2: Docker**:

```bash
docker run --rm \
  -v $(pwd):/host \
  aquasec/kube-bench:latest \
  kube-bench --config-dir /host/config --config /host/config/<version>/master.yaml
```

**Способ 3: Бинарный файл**:

```bash
# Скачать актуальную версию: https://github.com/aquasecurity/kube-bench/releases
kube-bench master  # или node
```

### Интерпретация результатов

kube-bench классифицирует проверки:

* **PASS** — проверка пройдена
* **FAIL** — проверка провалена (требует исправления)
* **WARN** — предупреждение (рекомендация, не требующая обязательного выполнения)
* **INFO** — информационная проверка

## Дополнительная информация

Сравнение с другими инструментами безопасности Kubernetes:

* **kube-bench** — аудит инфраструктуры на соответствие CIS Kubernetes Benchmark.
* **kubescape** — комплексный инструмент для сканирования кластера на наличие проблем безопасности, misconfigurations (включая манифесты) и уязвимостей, часто используется для проверки соответствия политикам (например, NSA, MITRE).
* **kube-hunter** — инструмент для пентеста (penetration testing) кластера. Выполняет активное сканирование для выявления уязвимостей с точки зрения атакующего. Потенциально может нарушить работу кластера, поэтому требует осторожности при использовании.
* **kubesec** — статический анализ рисков в манифестах до деплоя.
* [Kyverno](./kyverno/policies/practical_scenarios.md) — политики безопасности при деплое.
* [Pod Security Context](./pod_security_context.md) — безопасность подов.
* Официальный стандарт CIS — [CIS Kubernetes Benchmark](https://www.cisecurity.org/benchmark/kubernetes).
