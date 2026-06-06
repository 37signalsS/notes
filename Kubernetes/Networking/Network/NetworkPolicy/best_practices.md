# NetworkPolicy: Лучшие практики

## Определения

**Лучшие практики NetworkPolicy** — проверенные рекомендации по безопасному и эффективному внедрению сетевой изоляции в Kubernetes.

**Принцип минимальных привилегий** — стратегия безопасности, при которой субъекту (Pod) предоставляются только те права доступа, которые необходимы для выполнения его функций.

**CNI (Container Network Interface)** — сетевой интерфейс контейнеров, отвечающий за реализацию правил NetworkPolicy на уровне узлов кластера.

## Базовые Концепции

### Безопасность по умолчанию

Основой построения защищенной сети является отказ от доверительной модели «все со всеми».

* **Default Deny**: Весь трафик запрещен, пока не разрешен явно.
* **Гранулярность**: Правила должны быть максимально специфичными (конкретные порты, протоколы и селекторы).
* **Метки (Labels)**: Использование меток как единственного механизма идентификации объектов внутри кластера.

## Практические Сценарии

### 1. Внедрение Default Deny

Всегда начинайте с политики, блокирующей весь входящий трафик для пространства имен (Namespace). Это гарантирует, что новые сервисы не будут открыты по ошибке.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: <target-namespace>
spec:
  podSelector: {} # Выбрать все Pod в Namespace
  policyTypes:
  - Ingress
  ingress: [] # Пустой список — запретить всё
```

### 2. Разрешение системного трафика

При использовании Egress-изоляции необходимо явно разрешить доступ к критическим сервисам инфраструктуры, таким как DNS (Domain Name System) и API (Application Programming Interface) Server.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: <target-namespace>
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
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
```

### 3. Использование селекторов вместо IP-адресов

Для внутренних взаимодействий всегда предпочитайте `namespaceSelector` и `podSelector` вместо `ipBlock`.

* **Динамичность**: IP-адреса Pod постоянно меняются; селекторы автоматически отслеживают эти изменения.
* **Надежность**: `ipBlock` в формате CIDR (Classless Inter-Domain Routing) подвержен ошибкам при изменении топологии сети. Используйте `ipBlock` только для внешнего трафика.

### 4. Виртуальный патчинг (Virtual Patching)

В случае обнаружения критических уязвимостей, таких как RCE (Remote Code Execution), на конкретных эндпоинтах приложения, сетевые политики могут быть использованы для временной блокировки доступа к уязвимому компоненту до выхода исправления. Это позволяет минимизировать риски без полной остановки сервиса.

### 5. Тестирование и отладка

Для проверки работоспособности политик используйте временные Pod с необходимыми инструментами диагностики.

```bash
# Проверка Ingress (входящий трафик)
kubectl run test-curl --rm -it --image=curlimages/curl -- curl -v http://<service-name>:<port>

# Проверка Egress и DNS (исходящий трафик)
kubectl run test-dig --rm -it --image=registry.k8s.io/dnsutils:1.3 -- dig google.com

# Проверка блокировки порта через netcat
kubectl run test-nc --rm -it --image=busybox -- nc -zv <target-ip> <port>
```

### 6. Логирование заблокированного трафика

Используйте возможности расширенных CNI (например, Calico или Cilium) для логирования попыток несанкционированного доступа. Это критически важно для обнаружения атак и отладки правил.

## Дополнительные Сведения

### Реализация и инструменты

Эффективность NetworkPolicy зависит от выбранного сетевого плагина:

* **Поддерживают**: Calico, Cilium, Antrea, Weave Net.
* **Не поддерживают**: Flannel (в стандартной конфигурации).

Для визуализации и анализа правил рекомендуется использовать:

* [Orca Turfin](https://orca-tufin.com/) — графическая визуализация манифестов.
* Встроенные команды диагностики:
  * `kubectl get networkpolicy` — список политик.
  * `kubectl describe networkpolicy <name>` — детали конфигурации.

* **Определения и структура**: [NetworkPolicy: Определения и концепции](./definitions.md)
* **Логика правил**: [NetworkPolicy: Логика правил (И/ИЛИ)](./rule_logic.md)
* **Пошаговые примеры**: [NetworkPolicy: Практические сценарии](./practical_scenarios.md)
* **Реализация в CNI**: [NetworkPolicy: Поддержка в CNI-плагинах](./cni_implementation.md)
