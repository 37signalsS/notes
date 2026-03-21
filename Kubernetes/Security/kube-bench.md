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
* Генерация отчетов в текстовом или JSON-формате, классифицирующих проверки как пройденные (PASS), проваленные (FAIL) или требующие внимания (WARN).

## Практические сценарии

`kube-bench` и [Kubesec](./kubesec.md) являются взаимодополняющими инструментами, каждый из которых ориентирован на свой аспект безопасности Kubernetes:

* **Аудит инфраструктуры кластера (`kube-bench`)**: Используется для проверки текущей конфигурации самого кластера (настроек компонентов, безопасности узлов) на соответствие рекомендациям CIS. Это важно для обеспечения базовой защищенности среды выполнения.
* **Аудит манифестов приложений (`Kubesec`)**: Применяется для анализа YAML-файлов приложений на наличие потенциальных рисков и уязвимостей еще до их развертывания в кластере. Это позволяет предотвратить внедрение небезопасных конфигураций на уровне рабочих нагрузок.

## Практические сценарии

### Запуск kube-bench

**Способ 1: Запуск как Job в Kubernetes** (рекомендуется):

```bash
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-master.yaml
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-node.yaml
```

**Способ 2: Запуск в Docker**:

```bash
docker run --rm \
  -v $(pwd):/host \
  aquasec/kube-bench:latest \
  kube-bench --config-dir /host/config --config /host/config/<version>/master.yaml
```

**Способ 3: Установка бинарного файла**:

```bash
wget https://github.com/aquasecurity/kube-bench/releases/download/v0.7.2/kube-bench_0.7.2_linux_amd64.deb
sudo dpkg -i kube-bench_0.7.2_linux_amd64.deb
kube-bench master  # или node
```

### Интерпретация результатов

kube-bench классифицирует проверки:

* **PASS** — проверка пройдена
* **FAIL** — проверка провалена (требует исправления)
* **WARN** — предупреждение (рекомендация, не требующая обязательного выполнения)
* **INFO** — информационная проверка

## Дополнительная информация

### Сравнение инструментов безопасности

| Инструмент | Объект проверки | Когда работает |
|------------|-----------------|----------------|
| **kube-bench** | Инфраструктура кластера | Периодический аудит | Этот файл |
| **[kubesec](./kubesec.md)** | Манифесты приложений | До деплоя (CI/CD) | kubesec.md |
| **[Kyverno](./kyverno/policies/practical_scenarios.md)** | Манифесты приложений | Во время деплоя (Admission) | kyverno.md |
| **[Falco](../../Security/Tools/falco.md)** | Runtime-поведение | После деплоя | falco.md |

### Связанные темы

* **[Kubesec](./kubesec.md)** — анализ рисков в манифестах
* **[Kyverno](./kyverno/policies/practical_scenarios.md)** — политики безопасности
* **[Pod Security Context](./pod_security_context.md)** — безопасность подов
* **[CIS Benchmark](https://www.cisecurity.org/benchmark/kubernetes)** — официальный стандарт
